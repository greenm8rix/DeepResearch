# Analysis of `src/research_agent/utils/db_utils.py`

## Core Functions:

*   **`execute_db(...)`:** Central function for executing SQL queries.
    *   Enables WAL mode and foreign keys.
    *   Handles connections, commits (for non-SELECT), fetching results, error handling, and slow query logging.
*   **`init_db(...)`:** Initializes the database schema.
    *   Creates tables: `research_plans`, `sources`, `findings` with appropriate columns, types, primary/foreign keys, and indexes.
    *   `sources.plan_id` is nullable (supports indexer).
    *   Sets up FTS5 virtual table `sources_fts` on `sources(title, abstract)` using `porter unicode61 remove_diacritics 2` tokenizer.
    *   Creates triggers to keep `sources_fts` synchronized with `sources` table changes (INSERT, DELETE, UPDATE).
    *   Optimizes DB after setup.
*   **`save_plan_db(...)`:** Inserts data into `research_plans`.
*   **`save_source_db(...)`:** Inserts academic/API source metadata into `sources` using `INSERT OR IGNORE` to handle potential duplicates gracefully.
*   **`save_web_source_db(...)`:** Helper to insert placeholder web source entries into `sources` using `INSERT OR IGNORE`.
*   **`save_finding_db(...)`:** Inserts finding data into `findings`. Crucially calls `save_web_source_db` first for web findings to ensure foreign key integrity with the `sources` table.

## Key Findings & Observations:

*   **Schema Design:** Well-structured schema with appropriate keys and indexes. Nullable `plan_id` in `sources` correctly accommodates the indexer pattern.
*   **FTS Implementation:** Correct setup of FTS5 virtual table and synchronization triggers for efficient text search. Tokenizer choice is suitable.
*   **Concurrency & Integrity:** Use of WAL mode enhances concurrency. Explicit foreign key enforcement and the logic in `save_finding_db` ensure data integrity between `findings` and `sources`.
*   **Idempotent Saves:** `INSERT OR IGNORE` in source saving functions simplifies logic and prevents errors from duplicate source entries.
*   **Robust Execution:** `execute_db` provides a reliable wrapper for database interactions.
*   **Overall:** The database utility functions appear sound, functional, and well-aligned with the application's requirements, including FTS search and indexer support. No major issues identified.
