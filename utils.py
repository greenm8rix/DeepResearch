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

from config import (
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
def robust_call_llm(prompt, model="o3-mini", debug=False):
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
def search_semantic_scholar(query, limit=MAX_PAPERS_PER_QUERY, max_retries=11):
    print(f"\n--- Searching Semantic Scholar ---")
    print(f"Query: {query}")
    print("Waiting 60 seconds before the API call...")
    time.sleep(60)

    headers = {'x-api-key': SEMANTIC_SCHOLAR_API_KEY} if SEMANTIC_SCHOLAR_API_KEY else {}
    params = {
        'query': query,
        'limit': limit,
        'fields': 'title,authors,year,abstract,citationCount,venue,paperId,openAccessPdf,publicationTypes,journal'
    }
    retry_delay = 1
    for attempt in range(max_retries):
        try:
            response = requests.get(f"{SEMANTIC_SCHOLAR_API_URL}/paper/search", headers=headers, params=params)
            if response.status_code == 429:
                print(f"Received 429 rate limit response. Attempt {attempt+1}/{max_retries}. Retrying after {retry_delay} seconds...")
                time.sleep(retry_delay)
                retry_delay *= 2
                continue
            response.raise_for_status()
            results = response.json()
            total_found = results.get('total', 0)
            returned_data = results.get('data', [])
            print(f"Found {total_found} papers. Returning {len(returned_data)}.")
            return returned_data
        except Exception as e:
            print(f"Semantic Scholar API call failed on attempt {attempt+1}/{max_retries}: {e}")
            time.sleep(retry_delay)
            retry_delay *= 2
    print("Exceeded maximum retries for Semantic Scholar API.")
    return []
    







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

def search_open_alex(query: str, per_page: int = MAX_PAPERS_PER_QUERY, limit: int = MAX_PAPERS_PER_QUERY) -> list:
    """Searches the OpenAlex API for works."""
    
    actual_per_page = min(per_page, limit, 200) 
    print(f"\n--- Searching OpenAlex for query: '{query}' (Limit: {actual_per_page}) ---")
    url = "https://api.openalex.org/works"
    params = {
        "search": query,
        "per-page": actual_per_page,
       
    }
    try:
        response = requests.get(url, params=params, timeout=30)
        response.raise_for_status() 
        results = response.json()
        works = results.get("results", [])
        mapped_results = []
        for work in works:
            
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
                    if source_type == 'journal':
                        journal_name = venue_name
                    if source_type:
                         pub_type = source_type.replace("_", " ").title()

                
                best_oa = primary_location.get("best_oa_location")
                if best_oa and isinstance(best_oa, dict):
                     pdf_url = best_oa.get("pdf_url")
                     if not pdf_url:
                         pdf_url = best_oa.get("landing_page_url") 

            paper["venue"] = venue_name
            paper["journal"] = {"name": journal_name} if journal_name else None
            paper["openAccessPdf"] = {"url": pdf_url} if pdf_url else None
            paper["publicationTypes"] = [pub_type] if pub_type else []

            mapped_results.append(paper)

            if len(mapped_results) >= limit: 
                 break

        print(f"OpenAlex returned {len(mapped_results)} papers.")
        return mapped_results

    except requests.exceptions.RequestException as e:
        print(f"OpenAlex API request error: {e}")
        return []
    except Exception as e:
        print(f"Error processing OpenAlex results: {e}")
        return []


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