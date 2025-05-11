# Research Agent Workflow Details (Post-Refactoring & Indexer Implementation)

This document outlines the step-by-step execution flow of the research agent after the codebase refactoring and the introduction of the background indexer.

## Overview

The system comprises two main components:
1.  **Background Indexer (`src/indexer.py`):** (Assumed functionality) Continuously fetches paper metadata from APIs based on past user queries and stores it in the local SQLite database (`research_agent_data.db`), including building an FTS index.
2.  **Research Agent (triggered by `src/app.py`):** Executes the research workflow for a specific user query, primarily using the local database (leveraging FTS) but falling back to APIs if necessary.

## Detailed Workflow Steps

The agent workflow, typically initiated via `python src/app.py "Your Query"`, proceeds as follows:

1.  **Initialization (`src/app.py` -> `src/research_agent/agent.py`)**
    *   **Trigger:** `src/app.py` is executed.
    *   **Action:** An instance of `ResearchAgent` (from `src/research_agent/agent.py`) is created.
    *   **`ResearchAgent.__init__` (`agent.py`):**
        *   Accepts `db_path` and `citation_style` (defaulting to "harvard").
        *   Stores `self.db_path` and `self.citation_style`.
        *   Sets initial state variables (`current_query=None`, empty dictionaries/defaultdicts for `research_plan`, `findings`, `sources`, `processed_paper_ids`).
        *   Initializes empty caches: `relevance_cache` and `findings_cache`.
        *   Calls `init_db` (from `src/research_agent/utils/db_utils.py`).
        *   **`init_db` (`db_utils.py`):** Connects to the SQLite database (`research_agent_data.db`) and executes `CREATE TABLE IF NOT EXISTS` statements for `research_plans`, `sources` (with FTS table `sources_fts`), and `findings`. Ensures the database schema is ready.

2.  **Workflow Orchestration (`src/app.py` -> `src/research_agent/agent.py`)**
    *   **Trigger:** `src/app.py` calls `agent_instance.run_full_workflow(user_query, citation_style=...)`.
    *   **`ResearchAgent.run_full_workflow` (`agent.py`):**
        *   Accepts `user_query` and optional `citation_style` override.
        *   Resets agent state by calling `self.__init__`.
        *   Stores the `user_query` in `self.current_query`.
        *   Determines the `current_citation_style` for this run (using override or instance default). Prints the style being used.
        *   Starts timing the workflow.
        *   Uses `tqdm` for progress tracking across subtopics.
        *   Proceeds through Steps 1-5 by calling functions from the specialized modules, passing necessary state (like `findings`, `sources`, `processed_paper_ids`, caches) which are modified in place by the called functions.

3.  **Step 1: Generate Research Plan (`agent.py` -> `src/research_agent/planning.py`)**
    *   **Trigger:** `run_full_workflow` calls `generate_research_plan(user_query, db_path)`.
    *   **`generate_research_plan` (`planning.py`):**
        *   Constructs an LLM prompt asking for a research plan JSON based on the `user_query`.
        *   Calls `call_llm` (from `src/research_agent/utils/utils.py`) to interact with the LLM API.
        *   Parses and validates the returned JSON plan.
        *   Calls `save_plan_db` (from `src/research_agent/utils/db_utils.py`).
        *   **`save_plan_db` (`db_utils.py`):** Inserts the plan details (query, title, questions, sections) into the `research_plans` table and retrieves the generated `plan_id`.
        *   Returns the plan dictionary (including `plan_id`) back to `run_full_workflow`.
    *   **`run_full_workflow` (`agent.py`):** Stores the plan in `self.research_plan`. Terminates if planning failed.

4.  **Step 2: Research Subtopics (`agent.py` -> `src/research_agent/researching.py`)**
    *   **Trigger:** `run_full_workflow` loops through sections/subtopics in the plan and calls `research_subtopic(...)` for each, passing mutable state (`findings`, `sources`, `processed_paper_ids`, `relevance_cache`, `findings_cache`).
    *   **`research_subtopic` (`researching.py`):**
        *   **Keyword Generation (Local):** Calls `_generate_search_keywords` (helper in `researching.py`) using `call_llm` to get initial keywords for the subtopic.
        *   **Local DB Search (FTS):** Calls `_search_local_database` (helper in `researching.py`).
            *   **`_search_local_database`:** Constructs an optimized FTS5 query (`_construct_fts_query`) from keywords using `NEAR` and prefix (`*`) matching (no exact phrase matching). Escapes special characters. Uses `execute_db` (from `db_utils.py`) to query the `sources_fts` table using `MATCH ?`. Orders results by FTS rank, citation count, and year. Uses caching (`_search_cache`) based on keywords to avoid redundant DB queries. Returns a list of paper metadata dictionaries.
        *   **Paper Evaluation Loop (Local Results):** Iterates through papers found locally, up to `max_papers_to_evaluate`.
            *   Checks `processed_paper_ids` to avoid re-evaluating the same paper *for the same subtopic* in this run.
            *   Stores metadata in `self.sources` if not already present.
            *   Calls `_evaluate_relevance` (helper in `researching.py`, uses `relevance_cache`) using `call_llm` to score abstract relevance *specifically for the current subtopic and query context*.
            *   If abstract is relevant (score >= threshold), calls `_extract_findings` (helper in `researching.py`, uses `findings_cache`) using `call_llm`.
            *   If findings extracted from abstract, calls `save_finding_db` (from `db_utils.py`) to save finding to DB (linked to `plan_id`). Adds finding to `self.findings`. Marks `finding_added = True`.
            *   **PDF Analysis (Conditional):** If `PDF_ANALYSIS_ENABLED`, PDF URL exists, and abstract was irrelevant OR relevant but yielded no finding:
                *   Downloads PDF (`download_pdf` from `utils.py`).
                *   Extracts text (`extract_text_from_pdf` from `utils.py`).
                *   If abstract wasn't relevant, calls `_evaluate_relevance` on PDF text.
                *   If PDF is relevant and no finding added yet, calls `_extract_findings` on PDF text.
                *   If findings extracted from PDF, saves finding to DB and adds to `self.findings`.
            *   Stores the final relevance score for the paper in `evaluated_papers_scores`.
            *   Marks paper as processed for this subtopic in `self.processed_paper_ids`.
        *   **Relevance Check & API Fallback:** Counts highly relevant papers found (`highly_relevant_count`). Triggers API fallback if:
            *   Initial local search found few papers (`< local_found_threshold_for_api`).
            *   AND Initial evaluation found few relevant papers (`< local_relevant_threshold_for_api`).
            *   AND Overall evaluation limit not reached (`total_evaluated_count < max_papers_to_evaluate`).
            *   AND Target relevant papers not met (`highly_relevant_count < min_relevant_papers_target`).
        *   **API Fallback Execution (if triggered):**
            *   Generates API-specific keywords (`_generate_search_keywords`).
            *   Calls `search_semantic_scholar` (from `utils.py`) for each keyword to fetch up to `api_fallback_limit` papers, applying publication type and year filters. Handles rate limiting with retries and backoff.
            *   Calls `save_source_db` (from `db_utils.py`) for each *new* paper found via API to add it to the local `sources` table (associated with the current `plan_id`).
            *   Evaluates these newly found API papers for relevance and extracts/saves findings similarly to the local paper loop, respecting evaluation limits and relevance targets.

5.  **Step 3: Consolidate Findings (`agent.py` -> `src/research_agent/synthesis.py`)**
    *   **Trigger:** `run_full_workflow` calls `consolidate_findings(...)` for each subtopic after the research step.
    *   **`consolidate_findings` (`synthesis.py`):**
        *   **Web Search:** Calls OpenAI API (`client.responses.create` with `web_search_preview` tool), prompting for a JSON object containing `author_org`, `title`, `finding`, and `url`. Parses this JSON from the nested API response.
        *   **Web Relevance:** Calls `_evaluate_relevance` (imported from `researching.py`, uses `relevance_cache`) to score the extracted `finding` text relevance.
        *   If relevant, calls `save_finding_db` (from `db_utils.py`) to save the finding. Stores the extracted `author_org`, `title`, `url`, and `access_date` as a JSON string within the finding's `context_snippet` field in the database. Stores the finding data temporarily.
        *   **Combine Findings:** Creates a combined list including the relevant web finding data (if any) and the academic findings passed in `self.findings[subtopic]`. Updates `self.findings` in place by adding the web finding.
        *   **Prepare Findings Text:** Calls `get_raw_findings_text` (from `aggregation_utils.py`) on the *combined* list, passing the `citation_style`.
        *   **`get_raw_findings_text` (`aggregation_utils.py`):** Retrieves the appropriate `format_intext` function for the style. For academic papers, it formats using author/year via `format_intext`. For web sources, it parses the JSON from `context_snippet`; if the style is IEEE, it uses `[#]`; otherwise, it uses `(Author/Org)` if author/title are valid, or omits the citation. Appends the finding text and the generated citation string (if any).
        *   **LLM Consolidation:** Constructs a prompt asking an LLM to synthesize the prepared `findings_text` (which now includes formatted in-text citations), prioritizing academic sources.
        *   Calls `call_llm` (from `utils.py`).
        *   Parses and returns the structured JSON consolidation (themes, summary, contradictions, gaps).
    *   **`run_full_workflow` (`agent.py`):** Stores the consolidation result for the subtopic.

6.  **Step 4: Write Sections (`agent.py` -> `src/research_agent/writing.py`)**
    *   **Trigger:** `run_full_workflow` calls `write_all_sections(...)`, passing the `current_citation_style`.
    *   **`write_all_sections` (`writing.py`):**
        *   Accepts `citation_style`.
        *   Compiles "Reference Material" by calling `get_raw_findings_text` (from `aggregation_utils.py`) for all subtopics, passing the `citation_style`. This function formats the in-text citations according to the selected style *before* they are included in the reference material.
        *   Loops through sections in the plan.
        *   Constructs a prompt for each section asking an LLM to write the section content, using the reference material (which includes the pre-formatted in-text citations). The prompt instructs the LLM to use the citations *exactly as provided* in the material.
        *   Calls `call_llm` (from `utils.py`) to generate the text for each section.
        *   Stores generated text in `written_sections` dictionary.
        *   Returns the `written_sections` dictionary.

7.  **Step 5: Compile Final Output (`agent.py` -> `src/research_agent/compilation.py`)**
    *   **Trigger:** `run_full_workflow` calls `compile_final_report(...)`, passing the `current_citation_style`.
    *   **`compile_final_report` (`compilation.py`):**
        *   Accepts `citation_style`. Retrieves the appropriate formatters (`format_reference`, `format_web_source`) using `get_citation_formatters`.
        *   Assembles the main report body from title, questions, and `written_sections`.
        *   Queries the `findings` table for distinct cited *academic* `paper_id`s. Fetches details for each (from DB or memory cache). Formats academic references using the selected style's `format_reference` function.
        *   Queries the `findings` table for distinct cited *web* `paper_id`s. Parses the JSON context (`context_snippet`) for each to get author/org, title, URL, access date. Formats web references using the selected style's `format_web_source` function, but only adds the reference to the list if both author/org and title are valid (not default placeholders).
        *   Sorts academic and web reference lists separately.
        *   Combines the lists and appends them to the report text.
        *   Returns the complete report string.

8.  **Return Result (`src/research_agent/agent.py` -> `src/app.py`)**
    *   **`run_full_workflow` (`agent.py`):** Returns `{"report": final_report_string, "plan_id": plan_id}`.
    *   **`src/app.py`:** Handles the final output (prints/saves report in CLI, returns JSON in API mode).

This detailed flow reflects the current implementation, including FTS search, contextual relevance evaluation, caching, web search integration, and refined citation handling.
