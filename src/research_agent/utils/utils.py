import os
import time

import os
import time
import requests

try:
    import fitz  
except ImportError:
    fitz = None
    print("Warning: PyMuPDF not installed. PDF processing will be disabled.")

# Use relative import for config as it's in the parent directory
from ..config import (
    LLM_MAX_RETRIES,
    LLM_RETRY_DELAY,
    MAX_PAPERS_PER_QUERY,
    SEMANTIC_SCHOLAR_API_KEY,
    PDF_ANALYSIS_ENABLED,
    PDF_TEXT_EXTRACTION_LIMIT,
    SEMANTIC_SCHOLAR_API_URL,
    CONTEXT_WINDOW_SIZE,
    client
)
def call_llm(prompt, model="o3-mini", debug=False):
    print(f"\n--- Calling LLM (Model: {model}) ---")
    print(f"Prompt Snippet: {prompt[:200]}...")
    retries = 0
    while retries <= LLM_MAX_RETRIES:
        try:
            response = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],               
            )
            result = response.choices[0].message.content.strip()
            if not result:
                raise ValueError("Received an empty response from the model.")
            print(f"LLM Response Snippet: {result[:200]}...")
            if debug:
                print("Full Response:", response)
            return result
        except Exception as e:
            retries += 1
            print(f"LLM API call failed (Attempt {retries}/{LLM_MAX_RETRIES + 1}): {e}")
            if retries > LLM_MAX_RETRIES:
                print("LLM call failed after maximum retries. Returning None.")
                return None
            print(f"Retrying in {LLM_RETRY_DELAY} seconds...")
            time.sleep(LLM_RETRY_DELAY)

# Updated for pagination and limit override
def search_semantic_scholar(query: str, target_total: int | None = None, max_retries: int = 5):
    """
    Searches Semantic Scholar API using pagination to fetch up to target_total results.
    Includes exponential backoff for rate limiting.
    """
    total_limit = target_total if target_total is not None else MAX_PAPERS_PER_QUERY
    page_limit = 100 # S2 API max limit per request
    print(f"\n--- Searching Semantic Scholar (Target Total: {total_limit}, Page Limit: {page_limit}) ---")
    print(f"Query: {query}")

    headers = {'x-api-key': SEMANTIC_SCHOLAR_API_KEY} if SEMANTIC_SCHOLAR_API_KEY else {}
    all_results = []
    current_offset = 0
    retrieved_count = 0

    # Exponential backoff settings
    base_delay = 5
    max_delay = 60

    while retrieved_count < total_limit:
        current_delay = base_delay # Reset delay for each page attempt cycle
        params = {
            'query': query,
            'limit': min(page_limit, total_limit - retrieved_count), # Request remaining or page_limit
            'offset': current_offset,
            'fields': 'paperId,title,authors,year,abstract,venue,citationCount,openAccessPdf,publicationTypes,journal',
            # --- Added Filters ---
            'publicationTypes': 'JournalArticle,Review,Conference,Book,BookSection', # Broaden to include key academic types
            'year': '-2024' # Exclude 2025 and later
            # --- End Added Filters ---
        }
        print(f"DEBUG: S2 API Params: {params}") # Log the parameters being sent

        for attempt in range(max_retries):
            try:
                print(f"Fetching page: Offset={current_offset}, Limit={params['limit']} (Attempt {attempt + 1}/{max_retries})...")
                response = requests.get(f"{SEMANTIC_SCHOLAR_API_URL}/paper/search", headers=headers, params=params, timeout=30)

                if response.status_code == 429:
                    wait_time = min(current_delay, max_delay)
                    retry_after = response.headers.get('Retry-After')
                    if retry_after:
                        try: wait_time = max(wait_time, int(retry_after))
                        except ValueError: pass
                    wait_time = min(wait_time, max_delay)
                    print(f"Received 429 rate limit. Retrying after {wait_time} seconds...")
                    time.sleep(wait_time)
                    current_delay *= 2
                    continue # Retry this page request

                response.raise_for_status()
                results = response.json()
                page_data = results.get('data', [])
                total_found_api = results.get('total', 0) # Total the API reports for the query

                if not page_data:
                    print("No more results returned by API.")
                    retrieved_count = total_limit # Stop pagination
                    break # Exit retry loop for this page

                # Add source_api hint and append results
                for paper in page_data:
                    paper['source_api'] = 'semantic_scholar'
                all_results.extend(page_data)
                retrieved_count += len(page_data)
                current_offset += len(page_data)
                print(f"Fetched {len(page_data)} papers. Total retrieved so far: {retrieved_count}/{total_limit} (API total: {total_found_api})")

                # Add a small delay between successful page fetches
                time.sleep(1)
                break # Exit retry loop and move to next page (or finish)

            except requests.exceptions.RequestException as e:
                print(f"Semantic Scholar API request failed on attempt {attempt+1}/{max_retries}: {e}")
                if attempt + 1 == max_retries:
                    print("Exceeded maximum retries for this page. Stopping pagination for this query.")
                    retrieved_count = total_limit # Stop pagination
                    break # Exit retry loop
                wait_time = min(current_delay, max_delay)
                print(f"Retrying after {wait_time} seconds...")
                time.sleep(wait_time)
                current_delay *= 2
            except Exception as e:
                 print(f"An unexpected error occurred during Semantic Scholar search on attempt {attempt+1}/{max_retries}: {e}")
                 if attempt + 1 == max_retries:
                     print("Exceeded maximum retries for this page due to unexpected error. Stopping pagination.")
                     retrieved_count = total_limit # Stop pagination
                     break # Exit retry loop
                 wait_time = min(current_delay, max_delay)
                 print(f"Retrying after {wait_time} seconds...")
                 time.sleep(wait_time)
                 current_delay *= 2
        else:
             # This block executes if the inner loop completes without break (i.e., all retries failed)
             print("Stopping pagination for this query after multiple failed attempts for a page.")
             break # Exit the outer while loop

        # Check if we've reached the target or if the API has no more results (offset > total)
        if retrieved_count >= total_limit or current_offset >= total_found_api:
            break # Exit the outer while loop

    print(f"--- Finished Semantic Scholar search for '{query}'. Total papers retrieved: {len(all_results)} ---")
    return all_results
    







def reconstruct_openalex_abstract(abstract_index: dict | None) -> str | None:
    """Reconstructs abstract text from OpenAlex inverted index."""
    if not abstract_index:
        return None
    try:
        positions_words = []
        for word, positions in abstract_index.items():
            for pos in positions:
                positions_words.append((pos, word))
        
        positions_words.sort(key=lambda x: x[0])
        
        abstract = " ".join(word for pos, word in positions_words)
        return abstract
    except Exception as e:
        print(f"Failed to reconstruct OpenAlex abstract: {e}")
        return None

# Updated for pagination using cursor
def search_open_alex(query: str, target_total: int | None = None) -> list:
    """Searches the OpenAlex API using cursor pagination to fetch up to target_total results."""
    total_limit = target_total if target_total is not None else MAX_PAPERS_PER_QUERY
    per_page = min(200, total_limit) # OpenAlex max per_page is 200

    print(f"\n--- Searching OpenAlex (Target Total: {total_limit}, Per Page: {per_page}) ---")
    print(f"Query: {query}")

    url = "https://api.openalex.org/works"
    all_results = []
    cursor = "*" # Initial cursor for deep pagination

    while len(all_results) < total_limit:
        params = {
            "search": query,
            "per-page": min(per_page, total_limit - len(all_results)), # Request remaining or per_page
            "cursor": cursor
        }
        try:
            print(f"Fetching page: Cursor={cursor}, Limit={params['per-page']}...")
            response = requests.get(url, params=params, timeout=30)
            response.raise_for_status()
            results_data = response.json()
            works = results_data.get("results", [])

            if not works:
                print("No more results returned by OpenAlex.")
                break # Stop if no works are returned

            # Process and append results
            for work in works:
                # (Mapping logic remains the same as before)
                paper = {}
                paper['paperId'] = work.get("id")
                paper['title'] = work.get("display_name")
                authors = []
                for auth in work.get("authorships", []):
                    author_info = auth.get("author")
                    if author_info and author_info.get("display_name"):
                        authors.append({"name": author_info["display_name"]})
                paper['authors'] = authors
                paper['year'] = work.get("publication_year")
                abstract_inverted = work.get("abstract_inverted_index")
                paper["abstract"] = reconstruct_openalex_abstract(abstract_inverted)
                paper["citationCount"] = work.get("cited_by_count")
                primary_location = work.get("primary_location")
                venue_name = None
                journal_name = None
                pdf_url = None
                pub_type = None
                if primary_location and isinstance(primary_location, dict):
                    source = primary_location.get("source")
                    if source and isinstance(source, dict):
                        venue_name = source.get("display_name")
                        source_type = source.get("type")
                        if source_type == 'journal': journal_name = venue_name
                        if source_type: pub_type = source_type.replace("_", " ").title()
                    best_oa = primary_location.get("best_oa_location")
                    if best_oa and isinstance(best_oa, dict):
                         pdf_url = best_oa.get("pdf_url")
                         if not pdf_url: pdf_url = best_oa.get("landing_page_url")
                paper["venue"] = venue_name
                paper["journal"] = {"name": journal_name} if journal_name else None
                paper["openAccessPdf"] = {"url": pdf_url} if pdf_url else None
                paper["publicationTypes"] = [pub_type] if pub_type else []
                paper['source_api'] = 'openalex'
                all_results.append(paper)

                if len(all_results) >= total_limit:
                    break # Stop if we hit the overall target

            if len(all_results) >= total_limit:
                break # Exit outer loop if target reached

            # Get the next cursor for the next page
            cursor = results_data.get("meta", {}).get("next_cursor")
            if not cursor:
                print("No next cursor found. Stopping pagination.")
                break # Stop if there's no next cursor

            print(f"Total retrieved so far: {len(all_results)}/{total_limit}. Next cursor: {cursor[:10]}...")
            time.sleep(1) # Small delay between pages

        except requests.exceptions.RequestException as e:
            print(f"OpenAlex API request error: {e}. Stopping pagination for this query.")
            break # Stop pagination on error
        except Exception as e:
            print(f"Error processing OpenAlex results: {e}. Stopping pagination for this query.")
            break # Stop pagination on error

    print(f"--- Finished OpenAlex search for '{query}'. Total papers retrieved: {len(all_results)} ---")
    # Removed duplicated block below. The function correctly returns all_results.
    return all_results


def extract_text_from_pdf(pdf_path: str) -> str | None:
    """Extracts text from the first few pages of a PDF, up to a limit."""
    if not fitz:
        print("PDF processing skipped: PyMuPDF (fitz) is not installed.")
        return None
    print(f"--- Extracting text from PDF: {pdf_path} ---")
    try:
        doc = fitz.open(pdf_path)
        text = ""
        total_chars = 0
        max_pages_to_process = 5
        for page_num, page in enumerate(doc):
            if page_num >= max_pages_to_process:
                 print(f"Stopped PDF processing at page {max_pages_to_process}.")
                 break
            page_text = page.get_text("text", sort=True) 
            text += f"\n--- Page {page_num+1} ---\n" + page_text
            total_chars += len(page_text)
            
            if total_chars >= PDF_TEXT_EXTRACTION_LIMIT:
                print(f"Reached text extraction limit ({PDF_TEXT_EXTRACTION_LIMIT} chars).")
                
                excess = total_chars - PDF_TEXT_EXTRACTION_LIMIT
                text = text[:-excess]
                total_chars = PDF_TEXT_EXTRACTION_LIMIT
                break

        doc.close()
        print(f"Extracted ~{total_chars} characters (limited to {PDF_TEXT_EXTRACTION_LIMIT}).")
        return text
    except Exception as e:
        print(f"Failed to extract text from PDF {pdf_path}: {e}")
        return None


def download_pdf(url: str, filename: str = "temp_paper.pdf") -> str | None:
    """Downloads a PDF from a URL."""
    print(f"--- Downloading PDF from: {url} ---")
    
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
    try:
        
        response = requests.get(url, stream=True, headers=headers, timeout=30, allow_redirects=True)
        
        content_type = response.headers.get('Content-Type', '').lower()
        if 'pdf' not in content_type:
             print(f"Warning: URL Content-Type ({content_type}) doesn't explicitly mention PDF. Proceeding anyway.")
             

        response.raise_for_status() 

        
        os.makedirs(os.path.dirname(filename) or '.', exist_ok=True)

        with open(filename, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
        print(f"Downloaded PDF to {filename}")
        return filename
    except requests.exceptions.Timeout:
        print(f"Failed to download PDF: Request timed out after 30 seconds.")
        return None
    except requests.exceptions.RequestException as e:
        print(f"Failed to download PDF: {e}")
        return None
    except Exception as e:
         print(f"An unexpected error occurred during PDF download: {e}")
         return None


def get_context_around_keywords(text: str, keywords: list[str], window: int = CONTEXT_WINDOW_SIZE) -> str | None:
    """Extracts snippets of text surrounding keywords."""
    if not text or not keywords:
        return None
    snippets = []
    text_lower = text.lower()
    max_snippets = 5 

    for keyword in keywords:
        kw_lower = keyword.lower().strip()
        if not kw_lower: continue

        start_index = 0
        while True:
            index = text_lower.find(kw_lower, start_index)
            if index == -1:
                break 

            
            start = max(0, index - window)
            end = min(len(text), index + len(kw_lower) + window)

            
            snippet = text[start:end]

            
            prefix = "..." if start > 0 else ""
            suffix = "..." if end < len(text) else ""
            snippets.append(f"{prefix}{snippet}{suffix}")

            
            start_index = index + len(kw_lower)

           
            if len(snippets) >= max_snippets:
                 print(f"Reached max snippets ({max_snippets}).")
                 break
        if len(snippets) >= max_snippets:
             break 

    return "\n\n".join(snippets) if snippets else None
