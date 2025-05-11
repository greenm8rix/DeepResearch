# Analysis of `src/research_agent/compilation.py`

## Core Function: `compile_final_report(...)`

*   **Purpose:** Handles Step 5 of the workflow - assembling the final report string, including title, questions, written sections, and a formatted reference list based on cited sources.
*   **State Interaction:** Reads from `research_plan`, `written_sections`, and the `sources` cache. Relies heavily on querying the database via `execute_db` (passed via `db_path`) to identify cited sources and fetch details.

## Process Flow:

1.  **Initialization:** Gets `plan_id`, retrieves citation formatting functions (`format_reference`, `format_web_source`) from `utils.citation_styles` based on `citation_style`.
2.  **Assemble Main Body:**
    *   Adds title and research questions from the plan.
    *   Appends text from `written_sections` in the order specified by the plan's section list. Adds placeholders for missing sections.
3.  **Generate Reference List:**
    *   **Identify Cited Sources:** Queries the `findings` table for distinct `paper_id`s linked to the `plan_id`, separating academic (`NOT LIKE 'web_search_%'`) and web (`LIKE 'web_search_%'`) sources. Falls back to in-memory `sources` keys if DB fails.
    *   **Process Academic References:**
        *   For each unique academic `paper_id`:
            *   Tries fetching details (title, authors, year, etc.) from the `sources` table (DB).
            *   Falls back to the in-memory `sources` cache if DB fails or lacks data.
            *   Parses author JSON.
            *   Formats using `format_reference`.
            *   Stores `(sort_key, reference_string)` where `sort_key` is lowercased author string.
        *   Sorts academic references alphabetically by author.
    *   **Process Web References:**
        *   Queries `findings` table for web sources to get `paper_id` and `context_snippet`.
        *   Parses JSON `context_snippet` for author/org, title, URL, access date.
        *   Formats using `format_web_source`.
        *   **Filters:** Includes reference only if author/org and title are not default placeholders.
        *   Stores `(sort_key, reference_string)` where `sort_key` is lowercased URL/paper_id.
        *   Sorts web references alphabetically by URL/sort key.
    *   **Combine & Append:** Appends sorted academic and web reference lists (formatted as bullet points) under a "## References" header to the main text. Handles the case of no references.
4.  **Return Value:** Returns the complete final report string.

## Observations:

*   **Final Assembler:** Clearly defined role in creating the final document structure.
*   **DB Dependency:** Critically relies on the `findings` table to identify all cited sources accurately.
*   **Source Detail Fallback:** Good resilience in fetching academic source details (DB first, then memory cache).
*   **Citation Style Handling:** Correctly applies formatting based on the selected style.
*   **Web Reference Filtering:** Sensible approach to exclude incomplete web citations.
*   **Potential Optimization:** Could check the `sources` memory cache for academic details *before* querying the DB.
