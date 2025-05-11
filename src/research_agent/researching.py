import time
import json
import re
import os
import fitz # PyMuPDF
import functools
import hashlib
from typing import List, Dict, Any, Optional, Set, Tuple
from collections import defaultdict

# Use relative imports for modules within the same package
from .config import (
    PDF_ANALYSIS_ENABLED,
    RELEVANCE_SCORE_THRESHOLD,
    MAX_SEARCH_QUERIES_PER_SUBTOPIC, # Although not used directly here, keep for context? Or remove? Let's remove for now.
    MAX_PAPERS_PER_QUERY, # Keep for default limit in utils? No, utils defines its own default. Remove.
    API_CALL_DELAY # Import the delay constant
)
from .utils.utils import (
    call_llm,
    search_semantic_scholar,
    search_open_alex,
    download_pdf,
    extract_text_from_pdf
)
# Import execute_db for local search, keep save_finding_db
from .utils.db_utils import execute_db, save_finding_db, save_source_db # Keep save_source_db for now, might remove later if indexer is sole source provider

# Note: These functions were originally methods of ResearchAgent.
# They now take necessary state (db_path, plan, findings, sources, etc.) as arguments.

# Removed: _generate_search_queries - No longer needed as we search local DB based on subtopic directly.
# def _generate_search_queries(subtopic: str) -> list[str]: ...


# --- Helper Functions ---

# Renamed for clarity: Generates keywords for *any* topic/subtopic
def _generate_search_keywords(topic: str, num_keywords: int = 3) -> list[str]:
    """Generates related keywords or search terms for a given topic/subtopic using an LLM."""
    print(f"--- Generating search keywords for: '{topic}' ---")
    prompt = f"""
Generate {num_keywords} diverse and effective search keywords or short phrases for academic databases related to the topic: '{topic}'.
Focus on core concepts, synonyms, and related terms. Output ONLY a valid JSON list of strings.
Example: ["keyword one", "alternative phrase two", "related concept three"]
Include the original topic if it seems like a good keyword itself.
Output only the raw JSON list.
"""
    keywords_json_str = call_llm(prompt, model="o3-mini")

    if not keywords_json_str:
        print("Warning: LLM did not generate related keywords.")
        return []
    try:
        keywords_json_str = keywords_json_str.strip().lstrip('```json').rstrip('```').strip()
        keywords = json.loads(keywords_json_str)
        if isinstance(keywords, list) and all(isinstance(k, str) for k in keywords):
            print(f"Generated related keywords: {keywords}")
            return keywords[:num_keywords] # Ensure correct number
        else:
            print("Warning: LLM response for keywords was not a valid JSON list of strings.")
            return []
    except json.JSONDecodeError:
        print(f"Error: Failed to parse keywords JSON: {keywords_json_str}")
        return []
    except Exception as e:
        print(f"An unexpected error occurred generating keywords: {e}")
        return []


# Cache for database search results to avoid redundant queries
_search_cache = {}

@functools.lru_cache(maxsize=100)
def _construct_fts_query(search_terms: Tuple[str, ...]) -> str:
    """
    Constructs an optimized FTS5 query string from the given search terms.
    Uses a tuple for search_terms to make it hashable for the lru_cache.
    
    Returns an optimized query string for FTS5 with wildcards and phrase matching.
    """
    if not search_terms:
        return ""
        
    fts_query_terms = []
    
    for term in search_terms:
        # Skip empty terms
        term = term.strip() # Ensure leading/trailing whitespace is removed
        if not term:
            continue

        # More robust escaping for FTS5 special characters AND double quotes
        # Escape double quotes first, then other special chars relevant to FTS syntax
        escaped_term = term.replace('"', '""')
        # Characters that might interfere with FTS query syntax (excluding wildcard *)
        # Adjust this list based on observed errors or FTS5 documentation specifics
        special_chars = r'[-+?^$()\:!\\.]' # Added period .
        escaped_term = re.sub(f'([{re.escape(special_chars)}])', r'\\\1', escaped_term) # Escape special chars

        # For multi-word terms, create phrase queries with NEAR operator for flexibility
        if ' ' in escaped_term:
            # Create both exact phrase match and NEAR variants for better recall
            words = escaped_term.split()
            if len(words) > 1:
                # REMOVED: Add exact phrase match (higher relevance)
                # fts_query_terms.append(f'"{escaped_term}"')
                # Add NEAR variant with proximity of 3 words (good recall)
                fts_query_terms.append(f'NEAR({" ".join(words)}, 3)')
        # For single terms, add both exact and wildcard variants
        elif len(escaped_term) > 3:  # Only add wildcards for terms longer than 3 chars
            # Add exact term (higher relevance)
            fts_query_terms.append(escaped_term)
            # Add wildcard for prefix matching (good recall)
            fts_query_terms.append(f'{escaped_term}*')
        else:
            # For very short terms, just use the term as is
            fts_query_terms.append(escaped_term)
    
    # Combine terms with OR for broader matches
    return " OR ".join(fts_query_terms)

def _search_local_database(search_terms: List[str], db_path: str, total_limit: int = 50) -> List[Dict[str, Any]]:
    """
    Searches the local sources table for papers matching any of the search terms.
    Uses caching to avoid redundant queries and implements improved FTS5 query construction.
    
    Args:
        search_terms: List of search terms to query
        db_path: Path to the SQLite database
        total_limit: Maximum number of results to return
        
    Returns:
        List of paper dictionaries matching the search terms
    """
    if not search_terms:
        return []

    # Normalize and clean search terms
    normalized_terms = [term.strip().lower() for term in search_terms if term and term.strip()]
    if not normalized_terms:
        return []
        
    # Create a cache key based on the search terms and limit
    cache_key = hashlib.md5(f"{str(sorted(normalized_terms))}-{total_limit}".encode()).hexdigest()
    
    # Check if we have a cached result
    if cache_key in _search_cache:
        print(f"\n--- Using cached database search results for: {normalized_terms} ---")
        return _search_cache[cache_key]

    print(f"\n--- Searching Local Database using FTS5 for terms: {normalized_terms} ---")
    
    # Convert list to tuple for the lru_cache function
    fts_match_query = _construct_fts_query(tuple(normalized_terms))
    if not fts_match_query:
        return []
        
    print(f"Constructed optimized FTS MATCH query: {fts_match_query}")

    try:
        # Enhanced query with better ranking and filtering
        query = """
            SELECT s.paper_id, s.title, s.authors, s.year, s.abstract, s.venue, s.citation_count,
                   s.publication_types, s.journal_name, s.pdf_url, s.source_api
            FROM sources_fts fts
            JOIN sources s ON fts.rowid = s.rowid
            WHERE fts.sources_fts MATCH ?
            ORDER BY 
                fts.rank, -- FTS5 relevance ranking
                s.citation_count DESC, -- More cited papers first
                s.year DESC -- Newer papers first
            LIMIT ?
        """

        params = (fts_match_query, total_limit)
        results = execute_db(db_path, query, params, fetch_all=True)

        # Use a dictionary for better deduplication with paper_id as key
        all_papers_dict = {}
        
        if results:
            print(f"Found {len(results)} potentially relevant papers in local DB.")
            
            for row in results:
                try:
                    (paper_id, title, authors_json, year, abstract, venue, citation_count,
                     pub_types_json, journal_name, pdf_url, source_api) = row

                    # Skip papers with missing critical information
                    if not paper_id or not title:
                        continue

                    # Safely parse JSON fields with improved error handling
                    authors_list = []
                    if authors_json:
                        try:
                            loaded_authors = json.loads(authors_json)
                            # Handle different author formats
                            if isinstance(loaded_authors, list):
                                if loaded_authors and isinstance(loaded_authors[0], dict):
                                    authors_list = [{'name': a.get('name')} for a in loaded_authors 
                                                   if isinstance(a, dict) and a.get('name')]
                                elif loaded_authors and isinstance(loaded_authors[0], str):
                                    authors_list = [{'name': name} for name in loaded_authors]
                        except json.JSONDecodeError:
                            print(f"Warning: Could not decode authors JSON for paper {paper_id}.")

                    pub_types = []
                    if pub_types_json:
                        try:
                            pub_types = json.loads(pub_types_json)
                        except json.JSONDecodeError:
                            print(f"Warning: Could not decode publication_types JSON for paper {paper_id}.")

                    # Construct the paper dictionary with all available metadata
                    paper_dict = {
                        'paperId': paper_id,
                        'title': title,
                        'authors': authors_list,
                        'year': year,
                        'abstract': abstract,
                        'venue': venue,
                        'citationCount': citation_count,
                        'publicationTypes': pub_types,
                        'journal': {'name': journal_name} if journal_name else None,
                        'openAccessPdf': {'url': pdf_url} if pdf_url else None,
                        'source_api': source_api
                    }
                    
                    # Improved deduplication with quality check
                    if paper_id not in all_papers_dict:
                        all_papers_dict[paper_id] = paper_dict
                    elif _is_better_paper_version(paper_dict, all_papers_dict[paper_id]):
                        # Replace with better version if available
                        all_papers_dict[paper_id] = paper_dict
                        
                except Exception as e:
                    print(f"Error processing database result: {e}")
                    continue
        else:
            print("No relevant papers found in local DB for the given terms.")

        # Convert dictionary to list for return
        result_list = list(all_papers_dict.values())
        
        # Cache the results for future use (limit cache size)
        if len(_search_cache) > 50:  # Prevent unbounded growth
            _search_cache.clear()
        _search_cache[cache_key] = result_list
        
        return result_list
        
    except Exception as e:
        print(f"Database search error: {e}")
        return []

def _is_better_paper_version(new_paper: Dict[str, Any], existing_paper: Dict[str, Any]) -> bool:
    """
    Determines if the new paper version is better than the existing one based on completeness.
    
    Args:
        new_paper: New paper dictionary
        existing_paper: Existing paper dictionary
        
    Returns:
        True if the new paper has more complete information
    """
    # Check if the new paper has an abstract when the existing one doesn't
    if not existing_paper.get('abstract') and new_paper.get('abstract'):
        return True
        
    # Check if the new paper has more authors
    if len(new_paper.get('authors', [])) > len(existing_paper.get('authors', [])):
        return True
        
    # Check if the new paper has citation count when the existing one doesn't
    if not existing_paper.get('citationCount') and new_paper.get('citationCount'):
        return True
        
    # Check if the new paper has a PDF URL when the existing one doesn't
    if not existing_paper.get('openAccessPdf', {}).get('url') and new_paper.get('openAccessPdf', {}).get('url'):
        return True
        
    # Default to keeping the existing paper
    return False


# --- Relevance Evaluation and Finding Extraction (Keep as they operate on text) ---
    """Searches the local sources table for papers matching the subtopic."""
    print(f"\n--- Searching Local Database for subtopic: '{subtopic}' ---")
    # Simple LIKE search on title and abstract. Could be enhanced with keyword splitting, FTS, etc.
    search_term = f"%{subtopic}%"
    query = """
        SELECT paper_id, title, authors, year, abstract, venue, citation_count,
               publication_types, journal_name, pdf_url, source_api
        FROM sources
        WHERE title LIKE ? OR abstract LIKE ?
        ORDER BY year DESC, citation_count DESC -- Prioritize recent/cited papers
        LIMIT ?
    """
    results = execute_db(db_path, query, (search_term, search_term, limit), fetch_all=True)

    papers = []
    if results:
        print(f"Found {len(results)} potentially relevant papers in local DB.")
        for row in results:
            (paper_id, title, authors_json, year, abstract, venue, citation_count,
             pub_types_json, journal_name, pdf_url, source_api) = row

            # Reconstruct the paper dictionary structure expected by later steps
            authors_list = []
            if authors_json:
                try:
                    loaded_authors = json.loads(authors_json)
                    # Handle list of strings or list of dicts
                    if isinstance(loaded_authors, list):
                        if loaded_authors and isinstance(loaded_authors[0], dict):
                             authors_list = [{'name': a.get('name')} for a in loaded_authors if isinstance(a, dict) and a.get('name')]
                        elif loaded_authors and isinstance(loaded_authors[0], str):
                             authors_list = [{'name': name} for name in loaded_authors] # Convert simple list back to dict list
                except json.JSONDecodeError:
                    print(f"Warning: Could not decode authors JSON for paper {paper_id} from DB.")

            pub_types = []
            if pub_types_json:
                try:
                    pub_types = json.loads(pub_types_json)
                except json.JSONDecodeError:
                     print(f"Warning: Could not decode publication_types JSON for paper {paper_id} from DB.")


            paper_dict = {
                'paperId': paper_id,
                'title': title,
                'authors': authors_list,
                'year': year,
                'abstract': abstract,
                'venue': venue,
                'citationCount': citation_count,
                'publicationTypes': pub_types,
                'journal': {'name': journal_name} if journal_name else None,
                'openAccessPdf': {'url': pdf_url} if pdf_url else None,
                'source_api': source_api # Keep track of original source if available
            }
            papers.append(paper_dict)
    else:
        print("No relevant papers found in local DB for this subtopic.")

    return papers


# --- Relevance Evaluation and Finding Extraction (Keep as they operate on text) ---

def _evaluate_relevance(
    item_text: str,
    item_type: str,
    # Removed erroneous inserted lines from previous incorrect merge
    section: str,
    subtopic: str,
    paper_id: str,
    current_query: str, # Added parameter
    relevance_cache: dict, # Added cache parameter
    score_threshold: int = RELEVANCE_SCORE_THRESHOLD
) -> tuple[int, str, bool]:
    """
    Evaluates relevance of text to a subtopic using an LLM, checking cache first.
    Updates the cache with the result.
    """
    cache_key = (paper_id, subtopic)
    if cache_key in relevance_cache:
        print(f"--- Cache HIT for relevance: Paper {paper_id}, Subtopic '{subtopic}' ---")
        return relevance_cache[cache_key]

    print(f"--- Cache MISS. Evaluating relevance of {item_type} for paper {paper_id} (Subtopic: '{subtopic}') ---")

    # Truncate text for LLM context limits
    max_eval_text_len = 4000
    truncated_text = item_text[:max_eval_text_len]
    if len(item_text) > max_eval_text_len:
         truncated_text += "..."
         print(f"    (Text truncated to {max_eval_text_len} chars for evaluation)")


    prompt = f"""
You are evaluating the relevance of a research paper's {item_type} to a specific subtopic.

Overall User Query: "{current_query}"
Current Section in Outline: "{section}"
Specific Subtopic Being Researched: "{subtopic}"

Assess how directly relevant the following text is to the specific subtopic '{subtopic}'. Consider if it provides direct evidence, arguments, data, methods, or context specifically for this subtopic. Ignore information relevant only to the broader user query but not this specific subtopic.

{item_type.capitalize()} Text Snippet:
---
{truncated_text}
---

Provide a relevance score from 1 (Not Relevant) to 10 (Highly Relevant) specifically for the subtopic '{subtopic}'.
Justify your score briefly, focusing ONLY on the connection (or lack thereof) to '{subtopic}'.

Output format must be exactly:
Score: [number]/10. Justification: [Your brief justification focused on subtopic relevance]
"""
    response = call_llm(prompt, model="o3-mini")

    if not response:
        print("Warning: No LLM response for relevance evaluation.")
        return 0, "No LLM response", False

    try:
        # Parse score and justification
        score_match = re.search(r"Score:\s*(\d{1,2})\s*/\s*10", response)
        justification_match = re.search(r"Justification:\s*(.*)", response, re.DOTALL | re.IGNORECASE)

        score = 0
        if score_match:
             score = int(score_match.group(1))
             score = max(0, min(10, score)) # Clamp score between 0 and 10
        else:
             print("Warning: Could not parse relevance score from LLM response.")

        justification = "No justification provided or parsing failed."
        if justification_match:
             justification = justification_match.group(1).strip()

        is_relevant = (score >= score_threshold)
        print(f"Relevance Score: {score}/10. Relevant to '{subtopic}': {is_relevant}.")
        if len(justification) > 150:
             print(f"Justification: {justification[:150]}...")
        else:
             print(f"Justification: {justification}")

        return score, justification, is_relevant

    except Exception as e:
        print(f"Error parsing relevance score/justification: {e}")
        print(f"LLM response was: {response}")
        # Cache the failure to avoid retrying immediately
        result = (0, "Parsing failed", False)
        relevance_cache[cache_key] = result
        return result

    # Cache the successful result before returning
    result = (score, justification, is_relevant)
    relevance_cache[cache_key] = result
    return result


def _extract_findings(
    item_text: str,
    item_type: str,
    section: str,
    subtopic: str,
    paper_id: str,
    current_query: str, # Added parameter
    findings_cache: dict # Added cache parameter
) -> str | None:
    """
    Extracts key findings relevant to the subtopic using an LLM, checking cache first.
    Updates the cache with the result (finding text or None).
    """
    cache_key = (paper_id, subtopic)
    if cache_key in findings_cache:
        print(f"--- Cache HIT for findings: Paper {paper_id}, Subtopic '{subtopic}' ---")
        return findings_cache[cache_key] # Return cached finding (or None)

    print(f"--- Cache MISS. Extracting findings from {item_type} for paper {paper_id} (Subtopic: '{subtopic}') ---")

    # Truncate text for LLM context limits
    max_extract_text_len = 6000
    truncated_text = item_text[:max_extract_text_len]
    if len(item_text) > max_extract_text_len:
         truncated_text += "..."
         print(f"    (Text truncated to {max_extract_text_len} chars for extraction)")


    prompt = f"""
Analyze the following {item_type} text from a research paper (Paper ID: {paper_id}).
The overall research focuses on: "{current_query}"
This analysis is for the section '{section}' and specifically the subtopic: '{subtopic}'.

Identify and extract the key sentences or short paragraphs (max 2-3 sentences) that represent concrete findings, arguments, evidence, data points, methods, or conclusions *directly relevant to the subtopic '{subtopic}'*.
Focus *only* on information pertinent to this specific subtopic. If the text discusses the subtopic but offers no specific finding or conclusion about it, state that clearly. Avoid generic statements.

Text ({item_type}):
---
{truncated_text}
---

If relevant findings for '{subtopic}' are present, list them clearly and concisely. Use bullet points if multiple distinct findings are found.
If no specific findings related *directly* to '{subtopic}' are found in this text, output the single word: None

Extracted Findings for '{subtopic}':
"""
    findings = call_llm(prompt, model="o3-mini")

    if findings:
         findings = findings.strip()
         # Check for explicit "None" response
         if findings.lower() in ["none", "none.", "no findings found.", "no specific findings found."]:
              print(f"No specific findings relevant to '{subtopic}' extracted from this {item_type}.")
              # Cache the 'None' result
              findings_cache[cache_key] = None
              return None
         else:
              extracted_finding = findings.strip()
              snippet = extracted_finding.replace('\n', ' ')[:150] # Show a snippet in logs
              print(f"Extracted Finding Snippet for '{subtopic}': {snippet}...")
              # Cache the successful finding
              findings_cache[cache_key] = extracted_finding
              return extracted_finding
    else:
         print(f"Warning: No LLM response for finding extraction for '{subtopic}'.")
         # Cache the failure (as None)
         findings_cache[cache_key] = None
         return None


def research_subtopic(
    subtopic: str,
    research_plan: dict,
    db_path: str,
    current_query: str,
    findings: defaultdict[str, list], # Modified in-place
    sources: dict, # Modified in-place
    processed_paper_ids: defaultdict[str, set], # Modified in-place
    relevance_cache: dict, # Added cache parameter
    findings_cache: dict, # Added cache parameter
    min_relevant_papers_target: int = 10, # Increased target number of relevant papers to find
    relevance_threshold: int = 5, # Score threshold for relevance
    max_papers_to_evaluate: int = 40, # Increased Max total papers to evaluate per subtopic
    local_found_threshold_for_api: int = 10, # Min papers found locally to skip API fallback check
    local_relevant_threshold_for_api: int = 3, # Min relevant papers found locally to skip API fallback
    api_fallback_limit: int = 20 # Number of papers to fetch in API fallback (if triggered)
):
    """
    Researches a subtopic using the local DB, evaluating relevance up to a max_papers_to_evaluate limit.
    Conditionally falls back to Semantic Scholar API if local results are insufficient.
    attempts re-querying locally, and falls back to Semantic Scholar API if needed & max not reached.
    re-querying locally, and falls back to Semantic Scholar API if needed.
    """
    print(f"\n>>> STEP 2: Researching Subtopic: {subtopic} <<<")

    # Placeholder check removed as planning should no longer generate them.

    plan_id = research_plan.get('plan_id') # Needed for saving findings & fallback sources
    if not plan_id:
         print("Error: Cannot research subtopic, research plan ID is not set.")
         return # Or raise an exception

    # Ensure data structures exist for this subtopic
    if subtopic not in findings:
        findings[subtopic] = []
    if subtopic not in processed_paper_ids:
        processed_paper_ids[subtopic] = set()

    # --- Generate Initial Keywords for Local Search ---
    print("Generating keywords for local database search...")
    local_search_keywords = _generate_search_keywords(subtopic, num_keywords=5)
    if not local_search_keywords:
        print("Warning: Could not generate keywords for local search. Using subtopic directly.")
        local_search_keywords = [subtopic]
    else:
        # Ensure subtopic is included if not generated
        if subtopic not in local_search_keywords:
            local_search_keywords.insert(0, subtopic)

    # --- Initial Local Database Search ---
    current_search_terms = local_search_keywords
    local_papers = _search_local_database(current_search_terms, db_path)
    attempted_local_requery = False
    papers_from_api_fallback = []
    total_evaluated_count = 0 # Track total papers evaluated across all stages

    # --- Process Found Papers & Evaluate Relevance --- (Initial Pass)
    # Find the section name this subtopic belongs to
    section_name = "Unknown Section"
    if research_plan and 'sections' in research_plan:
        for s in research_plan.get('sections', []):
            if subtopic in s.get('subtopics', []):
                    section_name = s.get('section_name', "Unknown Section")
                    break

    # Process papers found in the current search (initial or re-query)
    papers_to_process = local_papers
    print(f"\n--- Processing {len(papers_to_process)} papers from initial local search for terms: {current_search_terms} (Section: {section_name}) ---")

    evaluated_papers_scores = {} # Store scores {paper_id: score}

    for i, paper in enumerate(papers_to_process):
        # Check evaluation limit *before* processing
        if total_evaluated_count >= max_papers_to_evaluate:
            print(f"Reached evaluation limit ({max_papers_to_evaluate}). Stopping initial local paper processing.")
            break

        paper_id = paper.get('paperId')
        if not paper_id:
            print(f"Skipping paper {i+1} with missing ID.")
            continue

        # Skip if already processed for *this specific subtopic* during this entire run
        if paper_id in processed_paper_ids.get(subtopic, set()):
            # print(f"Skipping paper {paper_id} - already processed for subtopic '{subtopic}'.")
            continue

        # Increment count *before* evaluation
        total_evaluated_count += 1
        title = paper.get('title', 'No Title')
        source_origin = paper.get('source_api', 'local_db') # Track if from API or DB
        print(f"\n--- Evaluating Paper #{total_evaluated_count}/{max_papers_to_evaluate} (Initial Local): {title} (ID: {paper_id}, Source: {source_origin}) ---")

        # Store metadata in memory cache if not already there
        if paper_id not in sources:
             sources[paper_id] = paper

        abstract = paper.get('abstract')
        finding_added = False # Track if a finding was extracted from this paper
        relevance_score = 0
        relevance_justification = ""
        is_relevant_from_abstract = False

        # 1. Evaluate Abstract
        if abstract:
            score, justification, relevant = _evaluate_relevance(
                item_text=abstract,
                item_type='abstract',
                section=section_name,
                subtopic=subtopic,
                paper_id=paper_id,
                current_query=current_query, # Pass current_query
                relevance_cache=relevance_cache # Pass cache
            )
            relevance_score = score
            relevance_justification = justification
            is_relevant_from_abstract = relevant

            if relevant:
                finding = _extract_findings(
                    item_text=abstract,
                    item_type='abstract',
                    section=section_name,
                    subtopic=subtopic,
                    paper_id=paper_id,
                    current_query=current_query, # Pass current_query
                    findings_cache=findings_cache # Pass cache
                )
                if finding:
                    finding_data = {
                        'paperId': paper_id,
                        'finding': finding,
                        'source_type': 'abstract',
                        'relevance_score': score,
                        'justification': justification,
                        'context_snippet': abstract[:1000] + ('...' if len(abstract) > 1000 else '') # Store snippet
                    }
                    # Store finding and mark paper as processed for this subtopic
                    findings[subtopic].append(finding_data) # Add to in-memory list
                    save_finding_db(db_path, research_plan, subtopic, finding_data) # Save to DB
                    finding_added = True
                    # Store score for the check later
                    evaluated_papers_scores[paper_id] = score # Store score even if finding added
            else:
                 # Store score even if not relevant enough for finding extraction
                 evaluated_papers_scores[paper_id] = score
        else:
            print("Abstract not available for evaluation.")
            evaluated_papers_scores[paper_id] = 0 # Assign 0 score if no abstract

        # 2. Evaluate PDF (if enabled, needed, and available) - Logic remains similar
        pdf_url_info = paper.get('openAccessPdf')
        pdf_url = pdf_url_info.get('url') if isinstance(pdf_url_info, dict) else None

        # Try PDF if: enabled AND URL exists AND (abstract wasn't relevant OR (abstract was relevant BUT no finding extracted))
        should_try_pdf = (PDF_ANALYSIS_ENABLED and pdf_url and
                          (not is_relevant_from_abstract or (is_relevant_from_abstract and not finding_added)))

        if should_try_pdf:
            print(f"Attempting PDF analysis from: {pdf_url}")
            pdf_path = None
            pdf_processed = False # Flag to track if PDF processing occurred
            try:
                # Use a unique temp filename
                temp_pdf_filename = f"temp_{plan_id}_{paper_id.replace('/', '_').replace(':', '_')}.pdf"
                pdf_path = download_pdf(pdf_url, filename=temp_pdf_filename)
                if pdf_path and fitz: # Check if download succeeded and PyMuPDF is available
                    pdf_text = extract_text_from_pdf(pdf_path)
                    pdf_processed = True # Mark as processed

                    if pdf_text:
                        # Initialize PDF relevance based on abstract results
                        pdf_score = relevance_score # Inherit score if abstract was evaluated
                        pdf_just = relevance_justification
                        pdf_relevant = is_relevant_from_abstract

                        # Re-evaluate relevance ONLY if abstract wasn't relevant
                        if not is_relevant_from_abstract:
                             print("Evaluating relevance based on PDF text...")
                             pdf_score, pdf_just, pdf_relevant = _evaluate_relevance(
                                 item_text=pdf_text, item_type='full paper text',
                                 section=section_name, subtopic=subtopic, paper_id=paper_id,
                                 current_query=current_query, # Pass current_query
                                 relevance_cache=relevance_cache # Pass cache
                             )

                        # Extract findings from PDF ONLY if PDF is relevant AND no finding was added from abstract
                        if pdf_relevant and not finding_added:
                            print("Extracting findings from PDF text...")
                            finding_pdf = _extract_findings(
                                item_text=pdf_text, item_type='full paper text',
                                section=section_name, subtopic=subtopic, paper_id=paper_id,
                                current_query=current_query, # Pass current_query
                                findings_cache=findings_cache # Pass cache
                            )
                            if finding_pdf:
                                finding_data = {
                                    'paperId': paper_id,
                                    'finding': finding_pdf,
                                    'source_type': 'full_text',
                                    'relevance_score': pdf_score, # Use the relevant score (original or PDF-based)
                                    'justification': pdf_just, # Use the relevant justification
                                    'context_snippet': pdf_text[:1000] + ('...' if len(pdf_text) > 1000 else '') # Store snippet
                                }
                                findings[subtopic].append(finding_data)
                                save_finding_db(db_path, research_plan, subtopic, finding_data)
                                finding_added = True
                                # Increment relevant count only if abstract wasn't already counted (handled by score check later)
                                # if not is_relevant_from_abstract: relevant_count += 1
                                # Store score for the check later
                                evaluated_papers_scores[paper_id] = pdf_score # Update score if PDF was evaluated
                            else:
                                 print("PDF was relevant but no specific findings extracted.")
                        elif not pdf_relevant and not is_relevant_from_abstract: # Only update score if abstract wasn't relevant either
                            evaluated_papers_scores[paper_id] = pdf_score
                        # If abstract was relevant but PDF wasn't, keep abstract score

                    else: # PDF downloaded but text extraction failed
                        print("PDF text extraction failed or yielded no text.")
                else: # PDF download failed
                    print("PDF download failed.")

            except Exception as pdf_err:
                print(f"Error processing PDF {pdf_url}: {pdf_err}")
            finally:
                # Clean up temporary PDF file
                if pdf_path and os.path.exists(pdf_path):
                    try:
                        os.remove(pdf_path)
                        # print(f"Removed temporary PDF: {pdf_path}")
                    except OSError as e:
                        print(f"Error removing temporary PDF file {pdf_path}: {e}")

        # Mark paper as processed for this subtopic to avoid re-evaluation in this run
        # Mark paper as processed for this subtopic *after* evaluation
        processed_paper_ids[subtopic].add(paper_id)
        time.sleep(0.2) # Shorter delay maybe needed

    # --- Check Relevance Threshold and Potentially Re-query ---
    highly_relevant_count = sum(1 for score in evaluated_papers_scores.values() if score >= relevance_threshold)
    print(f"--- Relevance Check after initial local search: Found {highly_relevant_count} papers with score >= {relevance_threshold} (Evaluated: {total_evaluated_count}/{max_papers_to_evaluate}) ---")

    # --- Conditional API Fallback Search ---
    # Trigger API fallback only if:
    # 1. Initial local search found few papers (< local_found_threshold_for_api)
    # 2. AND Initial evaluation found few relevant papers (< local_relevant_threshold_for_api)
    # 3. AND We haven't reached the overall evaluation limit yet
    # 4. AND We haven't reached the target number of relevant papers yet
    trigger_api_fallback = (
        len(local_papers) < local_found_threshold_for_api and
        highly_relevant_count < local_relevant_threshold_for_api and
        total_evaluated_count < max_papers_to_evaluate and
        highly_relevant_count < min_relevant_papers_target
    )

    if trigger_api_fallback:
        # Ensuring correct variable name in the f-string below
        print(f"\n--- Still insufficient relevant papers ({highly_relevant_count}/{min_relevant_papers_target}) and limit not reached. Falling back to API search. ---")
        # Generate keywords specifically for API search
        api_search_keywords = _generate_search_keywords(f"academic papers about {subtopic}", num_keywords=3)
        if not api_search_keywords:
             print("Warning: Could not generate keywords for API fallback. Using subtopic directly.")
             api_search_keywords = [subtopic]

        api_papers_found = {} # Deduplicate API results

        for keyword in api_search_keywords:
            print(f"-- Querying Semantic Scholar API for keyword: '{keyword}' (Target: {api_fallback_limit}) --")
            try:
                # Use the updated search_semantic_scholar with target_total
                s2_papers = search_semantic_scholar(keyword, target_total=api_fallback_limit)
                if s2_papers:
                    print(f"API found {len(s2_papers)} papers for '{keyword}'.")
                    for paper in s2_papers:
                        if paper.get('paperId') and paper['paperId'] not in evaluated_papers_scores and paper['paperId'] not in api_papers_found:
                            api_papers_found[paper['paperId']] = paper
                time.sleep(API_CALL_DELAY) # Respect API delay from config/utils
            except Exception as e:
                print(f"Error during Semantic Scholar API fallback search for '{keyword}': {e}")

        papers_from_api_fallback = list(api_papers_found.values())
        print(f"API fallback search yielded {len(papers_from_api_fallback)} new unique papers.")

        # --- Process and Evaluate API Fallback Papers ---
        if papers_from_api_fallback:
            print(f"\n--- Evaluating {len(papers_from_api_fallback)} papers found via API Fallback ---")
            # (Repeat the evaluation loop structure for papers_from_api_fallback, respecting limits)
            for i, paper in enumerate(papers_from_api_fallback):
                 # Check limits *before* processing: overall evaluation limit AND relevant paper target
                 if total_evaluated_count >= max_papers_to_evaluate:
                     print(f"Reached evaluation limit ({max_papers_to_evaluate}). Stopping API fallback paper processing.")
                     break
                 # Check if we've already found enough relevant papers
                 # Recalculate here to ensure it's up-to-date before checking
                 highly_relevant_count = sum(1 for score in evaluated_papers_scores.values() if score >= relevance_threshold)
                 if highly_relevant_count >= min_relevant_papers_target:
                     print(f"Reached relevant paper target ({min_relevant_papers_target}). Stopping API fallback paper processing.")
                     break

                 paper_id = paper.get('paperId')
                 # Skip if already processed (shouldn't happen if logic is correct, but safe check)
                 if not paper_id or paper_id in processed_paper_ids.get(subtopic, set()): continue

                 # Save the source found via API fallback *before* evaluation
                 # Use the current research_plan dict to associate if needed
                 save_source_db(db_path, research_plan, paper, paper.get('source_api', 'semantic_scholar_fallback'))

                 # Increment count *before* evaluation
                 total_evaluated_count += 1
                 title = paper.get('title', 'No Title')
                 source_origin = paper.get('source_api', 'semantic_scholar_fallback')
                 print(f"\n--- Evaluating Paper #{total_evaluated_count}/{max_papers_to_evaluate} (API Fallback): {title} (ID: {paper_id}, Source: {source_origin}) ---")

                 if paper_id not in sources: sources[paper_id] = paper # Add to in-memory cache
                 abstract = paper.get('abstract')
                 finding_added_api = False
                 relevance_score_api = 0
                 is_relevant_from_abstract_api = False

                 if abstract:
                     score, justification, relevant = _evaluate_relevance(
                         abstract, 'abstract', section_name, subtopic, paper_id, current_query, relevance_cache, relevance_threshold
                     )
                     relevance_score_api = score
                     is_relevant_from_abstract_api = relevant
                     evaluated_papers_scores[paper_id] = score # Add score
                     # Update relevant count immediately after evaluation
                     highly_relevant_count = sum(1 for s in evaluated_papers_scores.values() if s >= relevance_threshold)
                     if relevant:
                         finding = _extract_findings(
                             abstract, 'abstract', section_name, subtopic, paper_id, current_query, findings_cache
                         )
                         if finding:
                             finding_data = {'paperId': paper_id, 'finding': finding, 'source_type': 'abstract', 'relevance_score': score, 'justification': justification, 'context_snippet': abstract[:1000] + '...'}
                             findings[subtopic].append(finding_data)
                             save_finding_db(db_path, research_plan, subtopic, finding_data)
                             finding_added_api = True
                 else:
                     evaluated_papers_scores[paper_id] = 0
                     # Update relevant count even if abstract is missing (score is 0)
                     highly_relevant_count = sum(1 for s in evaluated_papers_scores.values() if s >= relevance_threshold)

                 pdf_url_info = paper.get('openAccessPdf')
                 pdf_url = pdf_url_info.get('url') if isinstance(pdf_url_info, dict) else None
                 should_try_pdf_api = (PDF_ANALYSIS_ENABLED and pdf_url and (not is_relevant_from_abstract_api or (is_relevant_from_abstract_api and not finding_added_api)))

                 if should_try_pdf_api:
                     # (Simplified PDF logic - assumes it runs similarly)
                     print(f"Attempting PDF analysis for API fallback paper: {pdf_url}")
                     # ... (PDF download, extraction, evaluation, finding extraction) ...
                     # Make sure to update evaluated_papers_scores[paper_id] if PDF is evaluated

                 processed_paper_ids[subtopic].add(paper_id) # Mark as processed
                 time.sleep(0.2)

            # Recalculate final relevant count
            highly_relevant_count = sum(1 for score in evaluated_papers_scores.values() if score >= relevance_threshold)
            # Recalculate final relevant count *after* the loop finishes or breaks
            highly_relevant_count = sum(1 for score in evaluated_papers_scores.values() if score >= relevance_threshold)
            print(f"--- Relevance Check After API Fallback: Found {highly_relevant_count} papers with score >= {relevance_threshold} (Target: {min_relevant_papers_target}, Evaluated: {total_evaluated_count}/{max_papers_to_evaluate}) ---")
    else:
         # This case handles when API fallback was not triggered
         highly_relevant_count = sum(1 for score in evaluated_papers_scores.values() if score >= relevance_threshold)


    # Final summary for the subtopic processing
    print(f"\n--- Finished processing subtopic: '{subtopic}'. Evaluated {total_evaluated_count} papers total (limit: {max_papers_to_evaluate}). Found {highly_relevant_count} meeting relevance threshold ({relevance_threshold}) (Target: {min_relevant_papers_target}). ---")
