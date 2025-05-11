# Analysis of `src/research_agent/researching.py`

## Core Function: `research_subtopic(...)`

*   **Purpose:** Handles Step 2 of the workflow - researching a specific subtopic.
*   **Orchestration:** Manages local database search, API fallback, paper evaluation, finding extraction, and PDF analysis for the given subtopic.
*   **State Interaction:** Accepts and modifies mutable state variables passed from `ResearchAgent` (`findings`, `sources`, `processed_paper_ids`, `relevance_cache`, `findings_cache`).

## Process Flow:

1.  **Initialization:** Gets `plan_id`, ensures data structures exist for the subtopic.
2.  **Keyword Generation:** Uses `_generate_search_keywords` (LLM `o3-mini`) for local search terms.
3.  **Local DB Search:** Uses `_search_local_database` (which uses FTS via `_construct_fts_query` and `execute_db`).
4.  **Local Paper Evaluation Loop:**
    *   Iterates through papers found locally.
    *   Checks against `max_papers_to_evaluate` limit.
    *   Skips papers already in `processed_paper_ids[subtopic]`.
    *   Stores metadata in `sources`.
    *   Evaluates abstract relevance (`_evaluate_relevance` - uses LLM, `relevance_cache`).
    *   Extracts findings if relevant (`_extract_findings` - uses LLM, `findings_cache`).
    *   Saves findings to `findings[subtopic]` and DB (`save_finding_db`).
    *   Conditionally analyzes PDF if `PDF_ANALYSIS_ENABLED` is `True`, URL exists, and needed (based on abstract results). Downloads, extracts text, evaluates, extracts findings, saves.
    *   Marks paper ID in `processed_paper_ids[subtopic]`.
    *   Tracks relevance scores.
5.  **API Fallback Check:** Determines if API fallback is needed based on thresholds (local papers found, relevant papers found) and limits (evaluation count, relevant target).
6.  **API Fallback Execution (if triggered):**
    *   Generates API keywords (`_generate_search_keywords`).
    *   Searches Semantic Scholar (`search_semantic_scholar`), respecting `API_CALL_DELAY`.
    *   Saves *new* sources found via API to DB (`save_source_db`).
    *   Evaluates API papers using a similar loop structure as the local evaluation, respecting limits.
7.  **Completion:** Prints a summary of evaluated papers and relevant findings for the subtopic.

## Helper Functions:

*   `_generate_search_keywords`: LLM-based keyword generation.
*   `_construct_fts_query`: Builds complex FTS5 queries (escaping, `NEAR`, wildcards). Uses LRU cache.
*   `_search_local_database`: Executes FTS query, processes results, handles deduplication (`_is_better_paper_version`), uses dictionary cache (`_search_cache`).
*   `_evaluate_relevance`: LLM-based relevance scoring (1-10) with context. Uses `relevance_cache`.
*   `_extract_findings`: LLM-based finding extraction with context. Uses `findings_cache`. Returns text or `None`.

## Key Findings & Issues:

1.  **PDF Configuration Flaw Confirmed:** Uses `PDF_ANALYSIS_ENABLED` imported directly from `config.py`. Runtime changes via CLI/API **will not work**.
2.  **Complex FTS:** Uses sophisticated FTS query construction (`_construct_fts_query`).
3.  **Multi-Layer Caching:** Employs `relevance_cache`, `findings_cache`, `_search_cache`, and LRU cache for `_construct_fts_query`.
4.  **Hardcoded Model:** Uses `o3-mini` LLM model directly in helper functions.
5.  **Code Duplication:** The core evaluation logic (abstract/PDF processing) is largely duplicated between the local and API fallback loops. Potential for refactoring.
6.  **High Complexity:** The module contains intricate logic, especially around the conditions for PDF analysis and API fallback.
7.  **Mutable State:** Relies heavily on modifying dictionaries/lists passed by reference from the agent.
