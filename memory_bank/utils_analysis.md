# Analysis of `src/research_agent/utils/utils.py`

## Core Functions:

*   **`call_llm(...)`:**
    *   Wraps OpenAI API calls (`client.chat.completions.create`).
    *   Includes retry logic (`LLM_MAX_RETRIES`, `LLM_RETRY_DELAY`) for API errors.
*   **`search_semantic_scholar(...)`:**
    *   Searches Semantic Scholar API (`/paper/search`).
    *   Handles pagination (`offset`/`limit`), API key header.
    *   Includes hardcoded filters for `publicationTypes` and `year`.
    *   Implements robust retries with exponential backoff for 429 rate limits and other request errors.
*   **`reconstruct_openalex_abstract(...)`:**
    *   Helper to reconstruct abstract text from OpenAlex's inverted index format.
*   **`search_open_alex(...)`:**
    *   Searches OpenAlex API (`/works`).
    *   Handles pagination (`cursor`), maps fields to agent's schema, reconstructs abstracts.
    *   *(Note: Appears unused in the main agent workflow analyzed so far.)*
*   **`extract_text_from_pdf(...)`:**
    *   Uses `fitz` (PyMuPDF) if available.
    *   Extracts text, limiting by page count (5) and character count (`PDF_TEXT_EXTRACTION_LIMIT`).
*   **`download_pdf(...)`:**
    *   Downloads file using `requests`.
    *   Sets User-Agent, uses streaming, includes timeout.
    *   Checks Content-Type but proceeds with warning if not PDF.
*   **`get_context_around_keywords(...)`:**
    *   Extracts text snippets around specified keywords within a larger text.
    *   *(Note: Appears unused in the main agent workflow analyzed so far.)*

## Observations:

*   **API Interaction:** Robust handling of Semantic Scholar API, including pagination, rate limits, and filtering. OpenAlex search uses cursor pagination correctly.
*   **PDF Handling:** Sensible limits applied during PDF text extraction. Graceful fallback if `fitz` is missing. Download function includes necessary headers and error handling.
*   **LLM Wrapper:** Provides a basic, retry-enabled wrapper for LLM calls.
*   **Modularity:** Effectively isolates external service interactions and file processing logic.
*   **Unused Code:** `search_open_alex` and `get_context_around_keywords` seem defined but not currently integrated into the core agent workflow steps (planning -> compilation).

## Potential Issues:

*   **Hardcoded Filters/Models:** Filters in `search_semantic_scholar` and the default LLM model in `call_llm` are hardcoded.
*   **LLM Retry Delay:** The retry delay in `call_llm` is constant (`LLM_RETRY_DELAY`), not exponential.
