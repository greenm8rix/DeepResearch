import json
import datetime
import re
import json # Keep json import

# Use relative import for citation styles
from .citation_styles import get_citation_formatters

def get_raw_findings_text(findings_list, sources, research_plan, execute_db_func=None, citation_style="harvard"):
    """
    Reconstruct the findings text with clear citations for consolidation.
    
    Parameters:
      - findings_list: A list of finding data dictionaries.
      - sources: A dict mapping paper IDs to source metadata.
      - research_plan: The research plan dictionary (to extract plan_id if needed).
      - execute_db_func: Optional callable to fetch missing details from the database.
      - citation_style: The citation style to use (harvard, apa, mla, chicago, ieee)
    
    Returns:
      A string containing all findings concatenated with their corresponding citations.
    """
    if not findings_list:
        return "No raw findings available."
    
    # Get the appropriate citation formatters for the specified style
    formatters = get_citation_formatters(citation_style)
    format_intext = formatters["intext"]
    
    parts = []
    for finding_data in findings_list:
        paper_id = finding_data.get('paperId')
        finding_text = finding_data.get('finding', 'Finding text missing.').strip()
        citation_str = "(Citation details unavailable)"
        source_type = finding_data.get('source_type')

        # Handle Web Search Citation using structured data from context_snippet
        if source_type == 'web_search':
            context_str = finding_data.get('context_snippet', '{}') # Default to empty JSON string
            citation_str = "" # Default to no citation
            try:
                context_data = json.loads(context_str)
                author_org = context_data.get('author_org', 'Unknown Author/Org')
                title = context_data.get('title', 'Untitled Page')
                url = context_data.get('url')

                # Handle IEEE style specifically for web sources
                if citation_style == "ieee":
                    citation_str = "[#]" # Use placeholder for IEEE web sources too
                else:
                    # For other styles, use Author/Org if valid
                    is_author_valid = author_org and author_org != "Unknown Author/Org"
                    is_title_valid = title and title != "Untitled Page" # Keep title check for non-IEEE logic

                    if is_author_valid and is_title_valid:
                        # Use Author/Org for in-text citation if valid (for non-IEEE styles)
                        # Note: This might need refinement for specific non-IEEE styles later
                        citation_str = f"({author_org})"
                    else:
                        # Omit citation if author or title is missing/generic
                        citation_str = ""
                        print(f"Omitting in-text citation for web finding {paper_id} due to missing author/title (Style: {citation_style}).")

            except json.JSONDecodeError:
                # Fallback: If JSON parsing fails, no citation can be reliably generated
                print(f"Warning: Could not parse JSON context for web finding {paper_id}. Falling back to regex URL extraction.")
                url_match = re.search(r'https?://[^\s/$.?#].[^\s]*', context_str) if context_str else None
                if url_match:
                    citation_str = f"(Source: {url_match.group(0)})"
                else:
                    citation_str = "" # No citation if fallback also fails

            # Append finding with citation (if available)
            if citation_str:
                parts.append(f"{finding_text} {citation_str}")
            else:
                parts.append(f"{finding_text}") # Append finding without citation

        # Handle Academic Paper Citation
        elif paper_id:
            source_meta = sources.get(paper_id)
            authors_list = []
            year = None
            if source_meta:
                authors_data = source_meta.get('authors')
                year = source_meta.get('year')
                if isinstance(authors_data, str):
                    try:
                        loaded_authors = json.loads(authors_data)
                        if isinstance(loaded_authors, list) and all(isinstance(a, str) for a in loaded_authors):
                            authors_list = loaded_authors
                        elif isinstance(loaded_authors, list) and loaded_authors and isinstance(loaded_authors[0], dict):
                            authors_list = [a.get('name') for a in loaded_authors if isinstance(a, dict) and a.get('name')]
                    except json.JSONDecodeError:
                        authors_list = []
                elif isinstance(authors_data, list):
                    if authors_data and isinstance(authors_data[0], str):
                        authors_list = authors_data
                    elif authors_data and isinstance(authors_data[0], dict):
                        authors_list = [a.get('name') for a in authors_data if isinstance(a, dict) and a.get('name')]
            
            if (not authors_list or year is None) and execute_db_func and research_plan.get('plan_id'):
                plan_id = research_plan.get('plan_id')
                cols_to_fetch = []
                if not authors_list:
                    cols_to_fetch.append("authors")
                if year is None:
                    cols_to_fetch.append("year")
                if cols_to_fetch:
                    query = f"SELECT {', '.join(cols_to_fetch)} FROM sources WHERE paper_id=? AND plan_id=?"
                    row = execute_db_func(query, (paper_id, plan_id), fetch_one=True)
                    if row:
                        db_data = dict(zip(cols_to_fetch, row))
                        if 'year' in db_data and year is None:
                            year = db_data['year']
                        if 'authors' in db_data and not authors_list:
                            try:
                                loaded_authors_db = json.loads(db_data['authors'])
                                if isinstance(loaded_authors_db, list) and all(isinstance(a, str) for a in loaded_authors_db):
                                    authors_list = loaded_authors_db
                                elif isinstance(loaded_authors_db, list) and loaded_authors_db and isinstance(loaded_authors_db[0], dict):
                                    authors_list = [a.get('name') for a in loaded_authors_db if isinstance(a, dict) and a.get('name')]
                            except json.JSONDecodeError:
                                pass
            citation_str = format_intext(authors_list, year)
            parts.append(f"{finding_text} {citation_str}")
        else:
            parts.append(f"{finding_text} (Unknown Source)")
    return "\n\n".join(parts)
