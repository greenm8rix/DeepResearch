import json
from collections import defaultdict

# Use relative imports for modules within the same package
from .utils.citation_styles import get_citation_formatters
from .utils.db_utils import execute_db

# Note: This function was originally step5_compile_output in ResearchAgent.
# It now takes necessary state (plan, written sections, sources, etc.) as arguments.

def compile_final_report(
    research_plan: dict,
    written_sections: dict,
    sources: dict, # In-memory cache of sources
    db_path: str,
    citation_style: str = "harvard", # Default citation style
    # execute_db_func: callable # Pass the DB execution function/method
) -> str:
    """Compiles the final report text including title, sections, and references."""
    print("\n>>> STEP 5: Compiling Final Output <<<")
    print(f"Using citation style: {citation_style}")
    plan_id = research_plan.get('plan_id')
    
    # Get the appropriate citation formatters for the specified style
    formatters = get_citation_formatters(citation_style)
    format_ref_list = formatters["ref_list"]
    format_reference = formatters["reference"]
    format_web_source = formatters["web_source"]

    # --- Assemble Main Body ---
    full_text = f"# {research_plan.get('title', 'Research Paper')}\n\n"
    if research_plan.get('research_questions'):
        full_text += "## Research Question(s)\n"
        for rq in research_plan.get('research_questions', []):
            full_text += f"- {rq}\n"
        full_text += "\n"

    # Add sections in the order defined by the plan
    section_order = [s.get("section_name") for s in research_plan.get('sections', [])]
    for sec_name in section_order:
        if sec_name in written_sections:
            full_text += written_sections[sec_name] + "\n\n"
        elif sec_name: # Handle case where section was planned but not written
            print(f"Warning: Section '{sec_name}' was planned but not found in written sections.")
            full_text += f"## {sec_name}\n\n[Section content not generated or available.]\n\n"

    # --- Generate Reference List ---
    full_text += "## References\n\n"
    cited_academic_paper_ids = set() # Renamed
    cited_web_sources_info = {} # To store unique web source details {paper_id: {'url': url, 'date': date}}

    # Fetch distinct *academic* paper IDs cited in findings from the database
    if plan_id:
        try:
            # Use the passed execute_db function
            rows = execute_db(
                db_path,
                """SELECT DISTINCT paper_id FROM findings
                   WHERE plan_id=? AND paper_id IS NOT NULL AND paper_id != '' AND paper_id NOT LIKE 'web_search_%'""", # Ensure paper_id is valid
                (plan_id,), fetch_all=True
            )
            if rows:
                cited_academic_paper_ids.update([r[0] for r in rows if r[0]]) # Filter out potential None/empty IDs
        except Exception as e:
            print(f"Error fetching cited academic paper IDs from database: {e}. Falling back to in-memory sources.")
            # Fallback: Use keys from the in-memory sources dict if DB fails
            cited_academic_paper_ids.update(k for k in sources.keys() if k and not k.startswith('web_search_'))
    else:
         print("Warning: No plan_id found. Academic reference list based only on in-memory sources.")
         cited_academic_paper_ids.update(k for k in sources.keys() if k and not k.startswith('web_search_'))


    # --- Process Academic References ---
    academic_reference_entries = [] # List to hold tuples of (sort_key, reference_string)
    if cited_academic_paper_ids:
        print(f"Processing {len(cited_academic_paper_ids)} unique cited academic sources.")
        # Sort IDs for consistent reference list order
        sorted_academic_paper_ids = sorted(list(cited_academic_paper_ids))

        for pid in sorted_academic_paper_ids:
            title, authors_json, year, venue, journal_name = None, None, None, None, None
            source_data_origin = None # Track if data came from DB or memory

            # 1. Try fetching source details from DB
            if plan_id:
                try:
                    row = execute_db(
                        db_path,
                        """SELECT title, authors, year, venue, journal_name
                           FROM sources WHERE paper_id=? AND plan_id=?""",
                        (pid, plan_id), fetch_one=True
                    )
                    if row:
                        title, authors_json, year, venue, journal_name = row
                        source_data_origin = 'DB'
                except Exception as e:
                    print(f"DB Error fetching source details for {pid}: {e}.")

            # 2. Fallback to in-memory sources if DB fetch failed or no plan_id
            if not source_data_origin and pid in sources:
                print(f"Using in-memory source data for {pid}.")
                src = sources[pid]
                title = src.get("title")
                # Extract author names correctly from the list of dicts
                authors_list_mem = [a.get('name') for a in src.get('authors', []) if isinstance(a, dict) and a.get('name')]
                authors_json = json.dumps(authors_list_mem) # Store as JSON string like DB
                year = src.get("year")
                venue = src.get("venue")
                journal_info_mem = src.get("journal") or {}
                journal_name = journal_info_mem.get("name")
                source_data_origin = 'Memory'

            # 3. Format the reference entry if data was found
            if source_data_origin:
                authors_list = []
                if authors_json:
                    try:
                        # Ensure we handle potential non-list JSON (though unlikely based on creation)
                        loaded_authors = json.loads(authors_json)
                        if isinstance(loaded_authors, list):
                             authors_list = loaded_authors
                        else:
                             print(f"Warning: Decoded authors JSON is not a list for Paper ID {pid}. Type: {type(loaded_authors)}")
                    except json.JSONDecodeError:
                        print(f"Warning: Could not decode authors JSON for Paper ID {pid} from {source_data_origin}.")
                        authors_list = [] # Default to empty list on error

                # Format the reference using the selected citation style
                ref_str = format_reference(authors_list, year, title, journal_name or venue or "")

                # Add tuple (sort_key, reference_string)
                # Sort key uses lowercase author string for case-insensitive sorting
                # The line below is the correct one, the duplicate 'reference_entries.append' above it was removed.
                academic_reference_entries.append((authors_str.lower(), ref_str))
            else:
                print(f"Warning: Could not retrieve sufficient details for Paper ID {pid} to create reference entry.")

        # Sort academic entries alphabetically by author/sort key
        academic_reference_entries.sort(key=lambda x: x[0])

    # --- Process Web References ---
    web_reference_entries = []
    if plan_id:
        try:
            # Fetch distinct web search findings (paper_id, context_snippet which holds URL)
            web_rows = execute_db(
                db_path,
                """SELECT DISTINCT paper_id, context_snippet FROM findings
                   WHERE plan_id=? AND paper_id LIKE 'web_search_%'""",
                (plan_id,), fetch_all=True
            )
            if web_rows:
                print(f"Processing {len(web_rows)} unique cited web sources.")
                import re # Import re for regex matching
                import re # Import re for regex matching (needed for date extraction)
                import datetime # Import datetime for date formatting
                for paper_id, context in web_rows:
                    # Only process if context (JSON string) exists
                    if context:
                        try:
                            web_data = json.loads(context)
                            author_org = web_data.get('author_org', 'Unknown Author/Org')
                            title = web_data.get('title', 'Untitled Page')
                            url = web_data.get('url', '[URL not found]')
                            access_date = web_data.get('access_date', datetime.datetime.now().strftime("%Y-%m-%d")) # Use stored date or current

                            # Format the web reference using the selected citation style
                            web_ref_str = format_web_source(author_org, title, url, access_date)

                            # Check if author and title are valid before adding to reference list
                            is_author_valid = author_org and author_org != "Unknown Author/Org"
                            is_title_valid = title and title != "Untitled Page"

                            if is_author_valid and is_title_valid:
                                # Use URL as sort key for web sources, handle missing URL
                                sort_key = url.lower() if url != '[URL not found]' else paper_id.lower() # Fallback sort key
                                web_reference_entries.append((sort_key, web_ref_str))
                            else:
                                print(f"Excluding web finding {paper_id} from reference list due to missing author/title.")

                        except json.JSONDecodeError:
                            print(f"Warning: Could not parse JSON context for web finding {paper_id}. Skipping reference.")
                        except Exception as e:
                            print(f"Error processing web reference context for {paper_id}: {e}. Skipping reference.")
                    else:
                        # If context is empty/None, skip adding this web source to references
                        print(f"Skipping web reference for {paper_id} due to missing context.")

        except Exception as e:
            print(f"Error fetching or processing cited web sources from database: {e}")

    # Sort web entries alphabetically by URL
    web_reference_entries.sort(key=lambda x: x[0])

    # --- Combine and Add References to Report ---
    if not academic_reference_entries and not web_reference_entries:
         full_text += "No sources were cited or found for this research.\n"
    else:
        if academic_reference_entries:
            full_text += "\n".join([f"- {ref[1]}" for ref in academic_reference_entries])
            if web_reference_entries:
                 full_text += "\n\n" # Add space between academic and web refs
        if web_reference_entries:
             full_text += "\n".join([f"- {ref[1]}" for ref in web_reference_entries])

    print("--- Final Compiled Output Ready ---")
    return full_text
