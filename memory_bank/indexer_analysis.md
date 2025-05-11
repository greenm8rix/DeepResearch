# Analysis of `src/indexer.py`

## Purpose:

*   Runs as a separate, continuous background script (`python src/indexer.py`).
*   Proactively populates the `sources` table with paper metadata relevant to past user queries found in the `research_plans` table.
*   Aims to improve the performance and relevance of the main agent's local FTS search by pre-caching potential sources.

## Process Flow (`if __name__ == "__main__":` loop):

1.  **Initialization:** Calls `init_db` once to ensure schema exists.
2.  **Continuous Loop (`while True`):**
    *   Calls `run_indexing_cycle`.
    *   Waits based on whether new queries were processed (60s if yes, `IDLE_CYCLE_DELAY` if no).
    *   Handles `KeyboardInterrupt` for shutdown.
    *   Includes basic exception handling for the main loop.

## `run_indexing_cycle()`:

1.  **Fetch Queries:** Calls `fetch_recent_queries` to get distinct `user_query` values from `research_plans` (limit `MAX_QUERIES_PER_CYCLE`).
2.  **Filter New Queries:** Selects queries not already in `processed_queries_this_session`.
3.  **Process Queries:** For each new query:
    *   Calls `index_papers_for_query`.
    *   Waits `QUERY_PROCESSING_DELAY`.
4.  Returns `True` if new queries were processed, `False` otherwise.

## `index_papers_for_query(user_query)`:

1.  **Generate Keywords:** Uses `_generate_keywords_for_query` (LLM `o3-mini`) based on the `user_query`.
2.  **Search APIs:** For each keyword, calls `search_semantic_scholar` and `search_open_alex` (respecting `API_CALL_DELAY`, limit `PAPERS_PER_KEYWORD`).
3.  **Deduplicate:** Collects unique papers found across keywords/APIs in a dictionary.
4.  **Save Sources:** Calls `db_utils.save_source_db` for each unique paper, passing `research_plan=None`. This saves to the `sources` table with `plan_id = NULL`. `INSERT OR IGNORE` handles duplicates.
5.  **Mark Processed:** Adds the `user_query` to `processed_queries_this_session`.

## Observations:

*   **Background Operation:** Designed for continuous, independent execution.
*   **Proactive Caching:** Populates the `sources` table ahead of agent runs.
*   **Reuses Utilities:** Leverages functions from `research_agent.utils`.
*   **Implicit FTS Population:** Saving to `sources` automatically updates the `sources_fts` index via database triggers defined in `init_db`.
*   **API Usage:** Potentially high API call volume (LLM, S2, OA). Includes delays.
*   **Session Tracking:** Avoids re-processing the same query within one run of the script using `processed_queries_this_session`.

## Potential Issues:

*   **API Costs/Rate Limits:** Continuous operation could be costly or hit limits.
*   **Error Handling:** Basic error handling might not cover all failure scenarios robustly.
*   **Stale Data:** No mechanism to prune old or irrelevant sources. DB size could grow.
*   **Resource Consumption:** Continuous background process uses resources.
*   **Unused Config:** `INDEXING_CYCLE_MINUTES` is defined but not used in the main loop timing.
