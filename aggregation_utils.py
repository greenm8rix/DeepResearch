import json
import datetime
import re
from citation_utils import format_authors_harvard_intext

def get_raw_findings_text(findings_list, sources, research_plan, execute_db_func=None):
    """
    Reconstruct the findings text with clear citations for consolidation.
    
    Parameters:
      - findings_list: A list of finding data dictionaries.
      - sources: A dict mapping paper IDs to source metadata.
      - research_plan: The research plan dictionary (to extract plan_id if needed).
      - execute_db_func: Optional callable to fetch missing details from the database.
    
    Returns:
      A string containing all findings concatenated with their corresponding citations.
    """
    if not findings_list:
        return "No raw findings available."
    
    parts = []
    for finding_data in findings_list:
        paper_id = finding_data.get('paperId')
        finding_text = finding_data.get('finding', 'Finding text missing.').strip()
        citation_str = "(Citation details unavailable)"
        
        
        if paper_id == 'web_search_result':
            date_match = re.search(r'(\d{4}-\d{2}-\d{2})', finding_data.get('justification', ''))
            date_str = date_match.group(1) if date_match else datetime.datetime.now().strftime("%Y-%m-%d")
            citation_str = f"(Web Search, {date_str})"
            parts.append(f"Web Finding: {finding_text} {citation_str}")
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
            citation_str = format_authors_harvard_intext(authors_list, year)
            parts.append(f"{finding_text} {citation_str}")
        else:
            parts.append(f"{finding_text} (Unknown Source)")
    return "\n\n".join(parts)
