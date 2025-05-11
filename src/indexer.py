import time
import sqlite3
# Removed schedule import
import sys
import os

# Adjust path to import from the research_agent package
# This assumes indexer.py is run from the project root (where src/ is)
sys.path.append(os.path.dirname(__file__)) # Keep this for running as script

# Import keyword generation utility as well
from research_agent.utils.utils import search_semantic_scholar, search_open_alex, call_llm
from research_agent.utils.db_utils import save_source_db, execute_db, init_db
from research_agent.config import SQLITE_DB_FILE
import json # Needed for parsing keyword JSON

# --- Configuration ---
DB_PATH = SQLITE_DB_FILE
# How often to check for new queries and run the indexing cycle (in minutes)
INDEXING_CYCLE_MINUTES = 60
# How many past queries to process in one cycle (to avoid overwhelming APIs)
MAX_QUERIES_PER_CYCLE = 10
# Delay between API calls for a single keyword (in seconds)
API_CALL_DELAY = 10 # Increase delay slightly due to potentially more calls
# Delay between processing different user queries (in seconds)
QUERY_PROCESSING_DELAY = 30 # Slightly increase delay between full queries
# Number of papers to fetch per keyword per API (S2 limit is 100)
PAPERS_PER_KEYWORD = 100 # Reduced limit to match S2 API cap
# Number of keywords to generate per user query
KEYWORDS_PER_QUERY = 5
# Delay at the end of a full indexing cycle if no new queries found (in seconds)
IDLE_CYCLE_DELAY = 300 # 5 minutes

# Keep track of queries processed in the current run to avoid immediate re-processing
processed_queries_this_session = set()

# --- Helper Function: Generate Keywords ---
# (Similar to the one in researching.py, but adapted for user queries)
def _generate_keywords_for_query(user_query: str, num_keywords: int = KEYWORDS_PER_QUERY) -> list[str]:
    """Generates search keywords from a user query using an LLM."""
    print(f"--- Generating keywords for user query: '{user_query}' ---")
    prompt = f"""
Extract {num_keywords} distinct and effective search keywords or short phrases from the following user research query. These keywords should be suitable for searching academic databases like Semantic Scholar or OpenAlex. Focus on the core concepts and entities. Output ONLY a valid JSON list of strings.
Example: ["keyword one", "key phrase two", "concept three"]

User Query: "{user_query}"

Output only the raw JSON list.
"""
    keywords_json_str = call_llm(prompt, model="o3-mini")

    if not keywords_json_str:
        print("Warning: LLM did not generate keywords for the query.")
        return [user_query] # Fallback to the original query
    try:
        keywords_json_str = keywords_json_str.strip().lstrip('```json').rstrip('```').strip()
        keywords = json.loads(keywords_json_str)
        if isinstance(keywords, list) and all(isinstance(k, str) for k in keywords) and keywords:
            print(f"Generated keywords: {keywords}")
            # Return unique keywords, keeping order roughly
            unique_keywords = list(dict.fromkeys(keywords))
            return unique_keywords[:num_keywords]
        else:
            print("Warning: LLM response for keywords was not a valid JSON list of strings. Using original query.")
            return [user_query]
    except json.JSONDecodeError:
        print(f"Error: Failed to parse keywords JSON: {keywords_json_str}. Using original query.")
        return [user_query]
    except Exception as e:
        print(f"An unexpected error occurred generating keywords: {e}. Using original query.")
        return [user_query]

def fetch_recent_queries(limit=MAX_QUERIES_PER_CYCLE):
    """Fetches recent, distinct user queries from the research_plans table."""
    print("\n--- Fetching recent user queries from database ---")
    query = """
        SELECT DISTINCT user_query
        FROM research_plans
        ORDER BY created_at DESC
        LIMIT ?
    """
    results = execute_db(DB_PATH, query, (limit,), fetch_all=True)
    if results:
        queries = [row[0] for row in results]
        print(f"Found {len(queries)} recent distinct queries.")
        return queries
    else:
        print("No past user queries found in the database.")
        return []

def index_papers_for_query(user_query):
    """Generates keywords, searches APIs for them, and saves results to the DB."""
    global processed_queries_this_session
    if user_query in processed_queries_this_session:
        print(f"Skipping query (already processed this session): '{user_query}'")
        return

    print(f"\n--- Indexing papers for user query: '{user_query}' ---")

    # 1. Generate Keywords
    keywords = _generate_keywords_for_query(user_query)
    if not keywords:
        print("No keywords generated, skipping indexing for this query.")
        processed_queries_this_session.add(user_query) # Mark as processed to avoid retrying
        return

    all_papers_found = {} # Use dict {paper_id: paper_metadata} for deduplication

    # 2. Search APIs for each keyword
    for keyword in keywords:
        print(f"\n-- Searching for keyword: '{keyword}' --")
        # Search Semantic Scholar
        try:
            print(f"Querying Semantic Scholar (Target: {PAPERS_PER_KEYWORD})...")
            # Use target_total instead of limit
            s2_papers = search_semantic_scholar(keyword, target_total=PAPERS_PER_KEYWORD)
            if s2_papers:
                print(f"Found {len(s2_papers)} papers from Semantic Scholar.")
                for paper in s2_papers:
                    if paper.get('paperId') and paper['paperId'] not in all_papers_found:
                        all_papers_found[paper['paperId']] = paper
            time.sleep(API_CALL_DELAY)
        except Exception as e:
            print(f"Error searching Semantic Scholar for keyword '{keyword}': {e}")

        # Search OpenAlex
        try:
            print(f"Querying OpenAlex (Target: {PAPERS_PER_KEYWORD})...")
             # Use target_total instead of limit
            oa_papers = search_open_alex(keyword, target_total=PAPERS_PER_KEYWORD)
            if oa_papers:
                print(f"Found {len(oa_papers)} papers from OpenAlex.")
                for paper in oa_papers:
                     if paper.get('paperId') and paper['paperId'] not in all_papers_found:
                         all_papers_found[paper['paperId']] = paper
            time.sleep(API_CALL_DELAY)
        except Exception as e:
            print(f"Error searching OpenAlex for keyword '{keyword}': {e}")

    # 3. Save unique papers found across all keywords to DB
    papers_to_save = list(all_papers_found.values())
    saved_count = 0
    if papers_to_save:
        print(f"\nAttempting to save {len(papers_to_save)} unique papers found for query '{user_query}'...")
        for paper in papers_to_save:
            # Call save_source_db with plan_id=None (research_plan=None)
            save_source_db(DB_PATH, research_plan=None, paper_metadata=paper, source_api=paper.get('source_api', 'unknown'))
            saved_count += 1 # Counts attempts, INSERT OR IGNORE handles duplicates
        print(f"Finished save attempt for {saved_count} papers (duplicates ignored).")
    else:
        print("No papers found from APIs for this query.")

    processed_queries_this_session.add(user_query)
    print(f"--- Finished indexing for query: '{user_query}' ---")


def run_indexing_cycle():
    """Performs one full cycle of fetching queries and indexing papers."""
    print(f"\n{'='*10} Starting Indexing Cycle at {time.strftime('%Y-%m-%d %H:%M:%S')} {'='*10}")
    global processed_queries_this_session
    # Optionally clear the session set if you want to re-process queries every cycle
    # processed_queries_this_session.clear()
    # Or keep it to only process truly new queries added since last run (more efficient)

    queries_to_process = fetch_recent_queries()

    if not queries_to_process:
        print("No queries to process in this cycle.")
        return

    new_queries = [q for q in queries_to_process if q not in processed_queries_this_session]

    if not new_queries:
        print("No *new* queries to process in this cycle (already processed this session).")
        return

    print(f"Processing {len(new_queries)} new queries...")
    for query in new_queries:
        try:
            index_papers_for_query(query)
            print(f"Waiting {QUERY_PROCESSING_DELAY} seconds before next query...")
            time.sleep(QUERY_PROCESSING_DELAY)
        except Exception as e:
            print(f"!!! Unhandled error processing query '{query}': {e}")
            # Mark as processed even if error occurred to avoid retrying immediately
            processed_queries_this_session.add(query)

    print(f"\n{'='*10} Indexing Cycle Finished at {time.strftime('%Y-%m-%d %H:%M:%S')} {'='*10}")
    # Return True if new queries were processed, False otherwise
    return bool(new_queries)


if __name__ == "__main__":
    print("Background Paper Indexer - Continuous Mode")
    print(f"Database: {DB_PATH}")
    print(f"Fetching up to {PAPERS_PER_KEYWORD} papers per keyword.")
    print("-" * 30)

    # Ensure DB exists and schema is initialized before starting
    init_db(DB_PATH)

    # --- Continuous Indexing Loop ---
    while True:
        try:
            processed_in_cycle = run_indexing_cycle()
            if not processed_in_cycle:
                # If no new queries were found and processed, wait longer before checking again
                print(f"No new queries processed. Waiting {IDLE_CYCLE_DELAY} seconds before next check...")
                time.sleep(IDLE_CYCLE_DELAY)
            else:
                # If queries were processed, wait a shorter time before checking again
                # This allows quicker pickup of newly added queries
                print(f"Cycle completed. Waiting 60 seconds before next check...")
                time.sleep(60)
        except KeyboardInterrupt:
            print("\nIndexer stopped by user.")
            break
        except Exception as e:
            print(f"\n!!! UNEXPECTED ERROR in main indexer loop: {e}")
            print("Waiting 5 minutes before retrying...")
            time.sleep(300)
