import datetime
import requests
import fitz  
import json
import os
import re
import sqlite3
import time  
import argparse
from flask import Flask, request, jsonify
from collections import defaultdict
import random
import time
import json
import os
import re
import sqlite3
from collections import defaultdict
from openai import OpenAI # Keep if client is used directly, otherwise remove
from collections import defaultdict # Keep
import time # Keep for timing workflow
from tqdm import tqdm # Import tqdm for progress bar

# Local module imports for refactored steps (use relative imports within the package)
from .planning import generate_research_plan
from .researching import research_subtopic
from .synthesis import consolidate_findings
from .writing import write_all_sections
from .compilation import compile_final_report

# Configuration and Utility Imports
from .config import (
    SQLITE_DB_FILE, # Keep for default db path in __init__
    PDF_ANALYSIS_ENABLED, # Keep if used directly, otherwise remove
    # RELEVANCE_SCORE_THRESHOLD, # Now used within researching.py
    # MAX_SEARCH_QUERIES_PER_SUBTOPIC, # Now used within researching.py
    # MAX_PAPERS_PER_QUERY, # Now used within researching.py
    client # Keep if used directly (e.g. web search fallback if moved back here), otherwise remove
)
# citation_utils is needed by compilation.py, not directly here
# from .utils.citation_utils import (
# )
# aggregation_utils is needed by synthesis.py/writing.py, not directly here
# from .utils.aggregation_utils import get_raw_findings_text
# utils functions are used by sub-modules, not directly here
# from .utils.utils import (
# )
# Keep DB utils as Agent manages state and DB interaction setup
from .utils.db_utils import init_db, execute_db
# save_* functions are now called within their respective step modules
# from .utils.db_utils import save_plan_db, save_source_db, save_finding_db

class ResearchAgent:
    """
    Manages the research workflow, including planning, searching, evaluating,
    synthesizing, and writing.
    """
    def __init__(self, db_path: str, citation_style: str = "harvard"):
        """Initializes the agent and the database.
        
        Args:
            db_path: Path to the SQLite database file
            citation_style: Citation style to use (harvard, apa, mla, chicago, ieee)
        """
        self.db_path = db_path
        self.citation_style = citation_style
        self.current_query: str | None = None
        self.research_plan: dict = {}
        self.findings: defaultdict[str, list] = defaultdict(list) # {subtopic: [finding_dict, ...]}
        self.sources: dict = {} # {paper_id: paper_metadata_dict}
        self.processed_paper_ids: defaultdict[str, set] = defaultdict(set) # {subtopic: {paper_id, ...}} - Tracks papers evaluated *for a specific subtopic* in this run

        # --- Caching ---
        # Cache for relevance scores: {(paper_id, subtopic): (score, justification, is_relevant)}
        self.relevance_cache: dict[tuple[str, str], tuple[int, str, bool]] = {}
        # Cache for extracted findings: {(paper_id, subtopic): finding_text or None}
        self.findings_cache: dict[tuple[str, str], str | None] = {}

        init_db(self.db_path) # Initialize DB upon agent creation

    # --- Database Interaction Methods (Kept within Agent for state management) ---

    # Removed _save_plan_db as saving is now handled within planning.generate_research_plan
    # def _save_plan_db(self): ...

    # Removed _save_source_db as saving is now handled within researching.research_subtopic
    # def _save_source_db(self, paper_metadata: dict, source_api: str): ...

    # Removed _save_finding_db as saving is now handled within researching/synthesis modules
    # def _save_finding_db(self, subtopic: str, finding_data: dict): ...

    # Keep _execute_db as it's a direct DB utility used by the agent/passed to modules
    def _execute_db(self, query: str, params: tuple = (), fetch_one: bool = False, fetch_all: bool = False) -> any:
        """Executes a given SQL query against the agent's database."""
        return execute_db(self.db_path, query, params, fetch_one, fetch_all)

    # --- Main Workflow Orchestration ---

    def run_full_workflow(self, user_query: str, citation_style: str = None) -> dict:
        """Citation style can be overridden for a specific research run"""
        """
        Orchestrates the entire research workflow by calling functions from specialized modules.
        """
        print(f"\n--- Starting Full Workflow for Query: '{user_query}' ---")
        start_time = time.time()

        # Reset state for a new workflow run
        self.__init__(self.db_path) # Re-initialize state variables
        self.current_query = user_query
        
        # Use the provided citation style or fall back to the instance default
        current_citation_style = citation_style or self.citation_style
        print(f"Using citation style: {current_citation_style}")

        # === Step 1: Generate Plan ===
        self.research_plan = generate_research_plan(user_query, self.db_path)
        if not self.research_plan or not self.research_plan.get('plan_id'):
            print("Workflow terminated: Failed to generate or save a valid research plan.")
            return {"error": "Failed to generate or store research plan.", "report": None, "plan_id": None}
        plan_id = self.research_plan.get('plan_id')
        print(f"Research Plan (ID: {plan_id}) generated successfully.")

        # === Step 2 & 3: Research Subtopics and Consolidate Findings ===
        print("\n--- Research & Consolidation Phase ---")
        all_sections = self.research_plan.get('sections', [])
        subtopic_consolidations = {} # Store results of consolidation step
        total_subtopics = sum(len(s.get('subtopics', [])) for s in all_sections)
        # processed_subtopics = 0 # tqdm handles the count

        if total_subtopics == 0:
            print("Warning: Research plan contains no subtopics to research.")
        else:
            # Wrap the subtopic iteration with tqdm
            with tqdm(total=total_subtopics, desc="Processing Subtopics", unit="subtopic") as pbar:
                for section_obj in all_sections:
                    sec_name = section_obj.get("section_name", "Unnamed Section")
                    subtopics = section_obj.get("subtopics", [])
                    for subtopic in subtopics:
                        # Update progress bar description
                        pbar.set_description(f"Processing: {sec_name} / {subtopic}")
                        # print(f"\n--- Processing Subtopic {pbar.n + 1}/{total_subtopics}: '{subtopic}' (Section: '{sec_name}') ---") # Optional: keep print statement

                        # Step 2: Research (modifies self.findings, self.sources, self.processed_paper_ids)
                    try:
                        research_subtopic(
                            subtopic=subtopic,
                            research_plan=self.research_plan,
                            db_path=self.db_path,
                            current_query=self.current_query,
                            findings=self.findings, # Pass mutable state
                            sources=self.sources, # Pass mutable state
                            processed_paper_ids=self.processed_paper_ids, # Pass mutable state
                            relevance_cache=self.relevance_cache, # Pass cache
                            findings_cache=self.findings_cache, # Pass cache
                            # Threshold parameters use defaults defined in researching.py
                        )
                    except Exception as e:
                        print(f"ERROR during research (Step 2) for subtopic '{subtopic}': {e}")
                        # Continue to next subtopic or handle error as needed

                    # Step 3: Consolidate (uses self.findings, self.sources; potentially modifies self.findings via web search)
                    try:
                        # Pass execute_db capability via lambda or direct reference if needed by consolidation
                        consolidation_result = consolidate_findings(
                            subtopic=subtopic,
                            research_plan=self.research_plan,
                            db_path=self.db_path,
                            findings=self.findings, # Pass potentially updated findings
                            sources=self.sources,
                            current_query=self.current_query, # Pass current query for context
                            relevance_cache=self.relevance_cache # Pass relevance cache
                        )
                        subtopic_consolidations[subtopic] = consolidation_result
                    except Exception as e:
                        print(f"ERROR during consolidation (Step 3) for subtopic '{subtopic}': {e}")
                        # Store error information
                        subtopic_consolidations[subtopic] = {"error": f"Consolidation failed: {e}"}

                        # Update progress bar after processing each subtopic
                        pbar.update(1)

        # print(f"\n--- Research & Consolidation Phase Complete ({processed_subtopics}/{total_subtopics} subtopics processed) ---") # tqdm shows completion

        # === Step 4: Write Sections ===
        print("\n--- Writing Phase ---")
        written_sections = {}
        try:
            # Pass execute_db capability if needed by writing (e.g., for get_raw_findings_text)
            written_sections = write_all_sections(
                research_plan=self.research_plan,
                subtopic_consolidations=subtopic_consolidations,
                findings=self.findings,
                sources=self.sources,
                db_path=self.db_path,
                citation_style=current_citation_style
                # execute_db_func=self._execute_db # Pass DB function if needed
            )
            if not written_sections and total_subtopics > 0:
                print("Warning: Writing phase completed, but no sections were generated.")
            elif not written_sections and total_subtopics == 0:
                print("Writing phase skipped as there were no subtopics.")
            else:
                print(f"Writing phase completed, {len(written_sections)} sections generated.")
        except Exception as e:
            print(f"ERROR during writing (Step 4): {e}")
            # written_sections might be partially populated or empty

        # === Step 5: Compile Final Output ===
        print("\n--- Compilation Phase ---")
        final_output = "[Compilation Failed]"
        try:
            # Pass execute_db capability if needed by compilation (e.g., for reference list)
            final_output = compile_final_report(
                research_plan=self.research_plan,
                written_sections=written_sections,
                sources=self.sources,
                db_path=self.db_path,
                citation_style=current_citation_style
                # execute_db_func=self._execute_db # Pass DB function if needed
            )
            print("Compilation phase completed successfully.")
        except Exception as e:
            print(f"ERROR during compilation (Step 5): {e}")
            # final_output remains "[Compilation Failed]" or could be partially compiled

        end_time = time.time()
        print(f"\n--- Full Workflow Finished in {end_time - start_time:.2f} seconds ---")

        # Return the final report and plan ID
        return {"report": final_output, "plan_id": plan_id}

# --- Removed Methods (Moved to separate modules) ---
# step1_generate_plan -> planning.py
# _generate_search_queries -> researching.py
# _evaluate_relevance -> researching.py
# _extract_findings -> researching.py
# step2_research_subtopic -> researching.py
# step3_consolidate_findings -> synthesis.py
# step4_write_all_sections_recursive -> writing.py
# step5_compile_output -> compilation.py
