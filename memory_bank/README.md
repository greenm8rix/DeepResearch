# Project Summary: Enhanced Research Agent

## Purpose

This project implements an automated research agent designed to take a user query, generate a research plan, gather information from academic sources (Semantic Scholar, OpenAlex) and potentially web searches, analyze findings (including PDF content), synthesize the information, and compile a structured research report in Markdown format.

## How to Run

The application can be run in two modes:

1.  **Command-Line Interface (CLI):**
    ```bash
    python app.py "Your research query here" [--db path/to/database.db] [--disable-pdf]
    ```
    - Replace `"Your research query here"` with the topic you want to research.
    - Optional: `--db` specifies a different SQLite database file.
    - Optional: `--disable-pdf` prevents downloading and analyzing full PDF texts.
    - The final report is printed to the console and saved as `final_report_enhanced.md`.

2.  **Flask API Server:**
    ```bash
    python app.py runserver
    ```
    - This starts a web server (usually on `http://127.0.0.1:5000/`).
    - Send a POST request to the `/research` endpoint with a JSON body like:
      ```json
      {
        "query": "Your research query here",
        "analyze_pdfs": true 
      }
      ```
    - `analyze_pdfs` is optional (defaults to `true`).
    - The server responds with a JSON containing the report or an error.

## Key Components & Files

-   **`app.py`**: Entry point for both CLI and Flask API. Initializes and runs the `ResearchAgent`.
-   **`Agent.py`**: Contains the core `ResearchAgent` class which orchestrates the entire research workflow (planning, searching, evaluating, consolidating, writing, compiling).
-   **`config.py`**: Defines configuration variables like API keys (loaded from environment variables `SEMANTIC_SCHOLAR_API_KEY`, `OPENAI_API_KEY`), API URLs, database file name, search limits, relevance thresholds, and PDF analysis settings. Initializes the OpenAI client.
-   **`utils.py`**: Helper functions for calling the LLM, searching academic APIs (Semantic Scholar, OpenAlex), downloading PDFs, and extracting PDF text.
-   **`db_utils.py`**: Functions for initializing and interacting with the SQLite database (creating tables, saving/retrieving plans, sources, findings).
-   **`citation_utils.py`**: Functions for formatting author names and citations (Harvard style).
-   **`aggregation_utils.py`**: Helper function(s) likely related to preparing findings data for consolidation.
-   **`research_agent_data.db`**: The SQLite database file where research plans, source metadata, and extracted findings are stored persistently.
-   **`requirements.txt`**: Lists the required Python packages (`Flask`, `requests`, `PyMuPDF`, `openai`).
-   **`memory_bank/`**: This directory, intended to store project context and summaries.
-   **`final_report_enhanced.md`**: Default output file name for the generated report in CLI mode.

## Dependencies

Install dependencies using pip:
```bash
pip install -r requirements.txt
```

## Configuration

-   **API Keys:** Set the following environment variables:
    -   `OPENAI_API_KEY`: Your OpenAI API key.
    -   `SEMANTIC_SCHOLAR_API_KEY`: Your Semantic Scholar API key (optional, but recommended for better results).
-   **Other Settings:** Modify values directly in `config.py` for parameters like `MAX_PAPERS_PER_QUERY`, `RELEVANCE_SCORE_THRESHOLD`, `PDF_ANALYSIS_ENABLED`, etc.

## Architecture Overview (Post-Refactoring & Indexer)

The system now consists of two main parts:

1.  **Background Indexer (`src/indexer.py`):**
    *   Runs as a separate, continuous process (`python src/indexer.py`).
    *   Periodically fetches past `user_query` values from the `research_plans` table in the database.
    *   For each query, it searches external academic APIs (Semantic Scholar, OpenAlex).
    *   Saves the metadata of found papers into the `sources` table of `research_agent_data.db`, using `INSERT OR IGNORE` to avoid duplicates. Papers added by the indexer have a `NULL` `plan_id`.
    *   This process gradually builds a local cache of papers relevant to past research topics.

2.  **Research Agent (`src/research_agent/` & `src/app.py`):**
    *   Triggered via CLI or Flask API (`python src/app.py ...`).
    *   **Orchestration (`agent.py`):** Manages the overall workflow state.
    *   **Planning (`planning.py`):** Generates the research plan based on the user query (same as before).
    *   **Researching (`researching.py`):**
        *   Generates initial search keywords based on the subtopic using an LLM.
        *   Searches the **local** `research_agent_data.db` (`sources` table) for papers matching these keywords (using SQL `LIKE`).
        *   Evaluates the relevance of papers found locally using an LLM (`_evaluate_relevance`).
        *   **Re-query Logic:** If the number of relevant papers found locally (score >= 5) is less than a threshold (default 5), it generates *alternative* keywords and performs a second search in the local database for these new keywords. Newly found papers are also evaluated.
        *   **API Fallback:** If, after the local search and potential local re-query, the number of relevant papers is still below the threshold, it generates *new* keywords and performs a targeted search against the **Semantic Scholar API**.
        *   Sources found via the API fallback are saved to the local database (`sources` table) and then evaluated for relevance.
        *   Extracts findings (using `_extract_findings`) only from papers deemed relevant (score >= 5), whether found locally or via API fallback.
        *   Saves extracted *findings* (linked to the current `plan_id`) to the database.
    *   **Synthesis (`synthesis.py`):**
        *   **Mandatory Web Search:** Performs a web search for the subtopic using the OpenAI API.
        *   Evaluates the relevance of the web search result using the same LLM process (`_evaluate_relevance`) as academic papers.
        *   Includes the web search result in the findings list for consolidation *only if* it meets the relevance threshold.
        *   Consolidates all relevant findings (from local DB, API fallback, and web search) using an LLM to identify themes, summaries, contradictions, and gaps.
    *   **Writing (`writing.py`):** Writes sections based on the final consolidated findings (same as before).
    *   **Compilation (`compilation.py`):** Compiles the final report. References now include academic papers and potentially web sources (cited via URL if possible, extracted during synthesis).

This revised architecture prioritizes the local database but includes fallback mechanisms (local re-query, API search) and integrates evaluated web search results to ensure sufficient relevant information is gathered for each subtopic.

## Refactoring Summary (May 2025)

To improve code readability and maintainability, the core logic previously contained entirely within `Agent.py` has been refactored into separate modules, each responsible for a specific step in the workflow:

-   **`planning.py`**: Handles Step 1 (Generating the research plan).
-   **`researching.py`**: Handles Step 2 (Searching sources, evaluating relevance, extracting findings). Includes helper functions previously prefixed with `_` in `Agent.py`.
-   **`synthesis.py`**: Handles Step 3 (Consolidating findings, including the web search fallback).
-   **`writing.py`**: Handles Step 4 (Writing individual sections based on consolidated data).
-   **`compilation.py`**: Handles Step 5 (Compiling the final report and reference list).

The `Agent.py` file now acts as the central orchestrator. It initializes the agent's state (database connection, findings/sources dictionaries) and calls the functions from the modules above in sequence within the `run_full_workflow` method, passing the necessary state between steps. Database helper methods remain within the `ResearchAgent` class for managing state interaction.

This modular structure separates concerns, making it easier to understand, modify, and test individual parts of the research process.

*(Note: Further restructuring to organize utility functions and potentially create a formal Python package structure is planned.)*
