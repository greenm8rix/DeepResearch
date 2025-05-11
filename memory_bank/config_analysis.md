# Analysis of `app.py` and `config.py`

## `src/app.py`

*   **Functionality:** Serves as the main entry point, handling both CLI and Flask API modes.
    *   **CLI:** Parses arguments (`query`, `--db`, `--disable-pdf`, `--citation-style`), creates a *new* `ResearchAgent` instance per run, calls `run_full_workflow`, prints/saves the report.
    *   **API:** Runs a Flask server (`/research` POST endpoint), uses a *single shared* `ResearchAgent` instance (state reset via `__init__` in `run_full_workflow`), accepts JSON (`query`, `analyze_pdfs`, `citation_style`), calls `run_full_workflow`, returns JSON.
*   **Potential Issue:** Attempts to control PDF analysis by modifying the imported `PDF_ANALYSIS_ENABLED` variable.

## `src/research_agent/config.py`

*   **Functionality:** Defines constants (API keys from env vars, URLs, DB file, limits, thresholds), initializes the global OpenAI client.
*   **Identified Issues:**
    *   **Redundancy:** `SEMANTIC_SCHOLAR_API_KEY` and `PDF_ANALYSIS_ENABLED` are defined twice.
    *   **Critical Flaw (PDF Configuration):** `PDF_ANALYSIS_ENABLED` is set to `True` at the module level. When imported by `app.py` or other modules, its *value* is taken. Modifications to this variable within `app.py` (based on `--disable-pdf` or `analyze_pdfs`) **do not propagate** to other modules that import the setting directly from `config.py`.
    *   **Result:** The `--disable-pdf` flag and the `analyze_pdfs: false` API parameter **will not work**. The agent components will likely always behave as if `PDF_ANALYSIS_ENABLED` is `True`.
*   **Recommendation:** Pass configuration settings (like `pdf_analysis_enabled`) explicitly to the `ResearchAgent` or its methods instead of relying on modifying imported global variables.
