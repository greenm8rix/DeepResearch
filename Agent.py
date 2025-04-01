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
from openai import OpenAI


from config import (
    SQLITE_DB_FILE,
    PDF_ANALYSIS_ENABLED,
    RELEVANCE_SCORE_THRESHOLD,
    MAX_SEARCH_QUERIES_PER_SUBTOPIC,
    MAX_PAPERS_PER_QUERY,
    client
)
from citation_utils import (
    normalize_author_list,
    parse_single_name,
    format_authors_harvard_ref_list,
    format_authors_harvard_intext
)
from aggregation_utils import get_raw_findings_text

from utils import (
    robust_call_llm,
    search_semantic_scholar,
    search_open_alex,
    download_pdf,
    extract_text_from_pdf
)
from db_utils import init_db, save_plan_db, save_source_db, save_finding_db, execute_db

class ResearchAgent:
    """
    Manages the research workflow, including planning, searching, evaluating,
    synthesizing, and writing.
    """
    def __init__(self, db_path: str):
        """Initializes the agent and the database."""
        self.db_path = db_path
        self.current_query: str | None = None
        self.research_plan: dict = {} 
        self.findings: defaultdict[str, list] = defaultdict(list)
        self.sources: dict = {} 
        self.processed_paper_ids: defaultdict[str, set] = defaultdict(set)
        init_db(self.db_path)  

    def _save_plan_db(self):
        """Saves the current research plan to the database using external helper."""
        plan_id = save_plan_db(self.db_path, self.current_query, self.research_plan)
        return plan_id

    def _save_source_db(self, paper_metadata: dict, source_api: str):
        """Saves paper metadata using external helper."""
        save_source_db(self.db_path, self.research_plan, paper_metadata, source_api)

    def _save_finding_db(self, subtopic: str, finding_data: dict):
        """Saves a finding using external helper."""
        save_finding_db(self.db_path, self.research_plan, subtopic, finding_data)

    def _execute_db(self, query: str, params: tuple = (), fetch_one: bool = False, fetch_all: bool = False) -> any:
        """Wraps the external execute_db for instance-specific calls."""
        return execute_db(self.db_path, query, params, fetch_one, fetch_all)
        
    def run_full_workflow(self, user_query: str) -> dict:
        """Executes the entire research and writing workflow."""
        print(f"\n--- Starting Full Workflow for Query: '{user_query}' ---")
        start_time = time.time()

        
        self.__init__(self.db_path)

        
        self.step1_generate_plan(user_query)
        if not self.research_plan or not self.research_plan.get('plan_id'):
            print("Workflow terminated: Failed to generate or save a valid research plan.")
            return {"error": "Failed to generate or store research plan.", "report": None, "plan_id": None}
        plan_id = self.research_plan.get('plan_id')
        print(f"Research Plan (ID: {plan_id}) generated successfully.")

        
        print("\n--- Research & Consolidation Phase ---")
        all_sections = self.research_plan.get('sections', [])
        subtopic_consolidations = {}
        total_subtopics = sum(len(s.get('subtopics', [])) for s in all_sections)
        processed_subtopics = 0
        research_title = self.research_plan.get('title', 'Research Paper')

        if total_subtopics == 0:
            print("Warning: Research plan contains no subtopics to research.")
        else:
            for section_obj in all_sections:
                sec_name = section_obj.get("section_name", "Unnamed Section")
                subtopics = section_obj.get("subtopics", [])
                for subtopic in subtopics:
                    processed_subtopics += 1
                    print(f"\n--- Processing Subtopic {processed_subtopics}/{total_subtopics}: '{subtopic}' (Section: '{sec_name}') ---")

                  
                    try:
                        self.step2_research_subtopic(subtopic)
                    except Exception as e:
                        print(f"ERROR during research (Step 2) for subtopic '{subtopic}': {e}")
                       
                    try:
                        subtopic_consolidations[subtopic] = self.step3_consolidate_findings(subtopic, research_title, sec_name)
                    except Exception as e:
                        print(f"ERROR during consolidation (Step 3) for subtopic '{subtopic}': {e}")
                       
                        subtopic_consolidations[subtopic] = {"error": f"Consolidation failed: {e}"}

        print(f"\n--- Research & Consolidation Phase Complete ({processed_subtopics}/{total_subtopics} subtopics processed) ---")

        
        print("\n--- Writing Phase ---")
        written_sections = {}
        try:
            written_sections = self.step4_write_all_sections_recursive(subtopic_consolidations)
            if not written_sections and total_subtopics > 0:
                print("Warning: Writing phase completed, but no sections were generated.")
            elif not written_sections and total_subtopics == 0:
                print("Writing phase skipped as there were no subtopics.")
            else:
                print(f"Writing phase completed, {len(written_sections)} sections generated.")
        except Exception as e:
            print(f"ERROR during writing (Step 4): {e}")

        
        print("\n--- Compilation Phase ---")
        final_output = "[Compilation Failed]"
        try:
            final_output = self.step5_compile_output(written_sections)
            print("Compilation phase completed successfully.")
        except Exception as e:
            print(f"ERROR during compilation (Step 5): {e}")

        end_time = time.time()
        print(f"\n--- Full Workflow Finished in {end_time - start_time:.2f} seconds ---")

        
        return {"report": final_output, "plan_id": plan_id}


    
    def step1_generate_plan(self, user_query: str):
        """Generates the research plan using an LLM."""
        print("\n>>> STEP 1: Generating Research Plan <<<")
        self.current_query = user_query

        prompt = f"""
You are a research assistant. Based on the user's query: "{user_query}", propose a detailed plan for a research paper.
The plan should directly address the user's request. Create a structure that allows for a comprehensive exploration of the topic.
Ensure the sections flow logically, building a coherent narrative relevant to the research questions.
Include an 'Introduction' and 'Conclusion' section. Generate at least 4 or more distinct intermediate sections (e.g., 'Literature Review', 'Methodology', 'Key Theme Analysis', 'Case Study').
Each section must have at least one specific subtopic relevant to that section's theme.
Define 4 or more or more relevant research questions that the paper aims to answer.

Output ONLY valid JSON with this exact structure:
{{
  "title": "string - A concise and informative paper title",
  "research_questions": ["list - 4 or more specific research questions as strings"],
  "sections": [
    {{
      "section_name": "Introduction",
      "subtopics": ["list", "of", "introductory subtopics"]
    }},
    // ... 4 intermediate sections or more ...
    {{
      "section_name": "string - e.g., 'Literature Review', 'Methodology', 'Analysis', etc.",
      "subtopics": ["list", "of", "specific subtopics for this section"]
    }},
    // ... more intermediate sections ...
    {{
      "section_name": "Conclusion",
      "subtopics": ["list", "of", "concluding subtopics"]
    }}
  ]
}}

Only return the raw JSON object, no additional text, preamble, or markdown formatting.
"""
        plan_json_str = robust_call_llm(prompt, model="o3-mini") 

        if not plan_json_str:
            print("Error: No response from LLM for plan generation.")
            self.research_plan = {'plan_id': None}
            return

        print(f"LLM Response Snippet (Plan): {plan_json_str[:250]}...")

        try:

            plan_json_str = plan_json_str.strip().lstrip('```json').rstrip('```').strip()
            parsed_plan = json.loads(plan_json_str)

   
            required_keys = ['title', 'research_questions', 'sections']
            if not all(k in parsed_plan for k in required_keys) or \
               not isinstance(parsed_plan['research_questions'], list) or \
               not isinstance(parsed_plan['sections'], list) or \
               not parsed_plan['sections']: 
                raise ValueError("Invalid plan structure received (missing keys or wrong types).")

            if len(parsed_plan['research_questions']) < 3:
                print("Warning: Fewer than 3 research questions generated.")
            if len(parsed_plan['sections']) < 5:
                print(f"Warning: Only {len(parsed_plan['sections'])} sections generated. Might lack depth.")
            if not all("subtopics" in s and isinstance(s.get("subtopics"), list) and s.get("subtopics") for s in parsed_plan['sections']):
                 print("Warning: Some sections might be missing subtopics lists or have empty subtopics.")


            self.research_plan = parsed_plan
            print("--- Research Plan Generated ---")
            print(json.dumps(self.research_plan, indent=2))

            self._save_plan_db()

        except json.JSONDecodeError as e:
            print(f"Error: Failed to parse JSON plan from LLM response: {e}")
            print(f"LLM Response was:\n---\n{plan_json_str}\n---")
            self.research_plan = {'plan_id': None}
        except ValueError as e:
            print(f"Error: Invalid plan structure: {e}")
            print(f"Parsed Plan was:\n---\n{parsed_plan}\n---")
            self.research_plan = {'plan_id': None}
        except Exception as e:
            print(f"An unexpected error occurred during plan processing: {e}")
            print(f"LLM Response was:\n---\n{plan_json_str}\n---")
            self.research_plan = {'plan_id': None}

    def _generate_search_queries(self, subtopic: str) -> list[str]:
        """Generates search queries for a given subtopic using an LLM."""
        print(f"--- Generating search queries for subtopic: '{subtopic}' ---")
        prompt = f"""
Generate {MAX_SEARCH_QUERIES_PER_SUBTOPIC} diverse and effective search query strings for academic databases (like Semantic Scholar, OpenAlex, PubMed) to find papers specifically about: '{subtopic}'.

Consider:
- Synonyms and related concepts.
- Alternative phrasings (questions, noun phrases).
- Key technical terms or jargon if applicable.
- Focusing each query on a slightly different facet or angle.

Constraints:
- Output ONLY a valid JSON list of strings. Example: ["query one", "query two", "query three"]
- Do NOT include boolean operators (AND, OR, NOT) within the query strings themselves. The search engine will handle combining terms.
- Ensure queries are distinct and directly relevant to '{subtopic}'.
- Generate exactly {MAX_SEARCH_QUERIES_PER_SUBTOPIC} queries.

Output only the raw JSON list.
"""
        queries_json_str = robust_call_llm(prompt, model="o3-mini")

        if not queries_json_str:
            print("Warning: No search queries generated by LLM. Using fallback.")
            return [subtopic] 

        try:
            queries_json_str = queries_json_str.strip().lstrip('```json').rstrip('```').strip()
            queries = json.loads(queries_json_str)

            if isinstance(queries, list) and all(isinstance(q, str) for q in queries):
                
                valid_queries = []
                for q in queries:
                     q_upper = q.upper()
                     if ' AND ' not in q_upper and ' OR ' not in q_upper and ' NOT ' not in q_upper:
                          valid_queries.append(q)
                     else:
                          print(f"Warning: Filtering out query containing potential boolean operator: '{q}'")

                
                final_queries = valid_queries[:MAX_SEARCH_QUERIES_PER_SUBTOPIC]

                if not final_queries:
                    print("Warning: All generated queries were invalid or filtered. Using fallback.")
                    return [subtopic]

                print(f"Generated queries: {final_queries}")
                return final_queries
            else:
                raise ValueError("LLM response is not a valid JSON list of strings.")

        except json.JSONDecodeError as e:
            print(f"Error: Failed to parse search queries JSON from LLM: {e}")
            print(f"LLM Response was: {queries_json_str}")
            return [subtopic] 
        except Exception as e:
             print(f"An unexpected error occurred parsing search queries: {e}")
             return [subtopic]


    
    def _evaluate_relevance(self, item_text: str, item_type: str, section: str, subtopic: str, paper_id: str, score_threshold: int = RELEVANCE_SCORE_THRESHOLD) -> tuple[int, str, bool]:
        """Evaluates relevance of text to a subtopic using an LLM."""
        print(f"--- Evaluating relevance of {item_type} for paper {paper_id} (Subtopic: '{subtopic}') ---")

        
        max_eval_text_len = 4000 
        truncated_text = item_text[:max_eval_text_len]
        if len(item_text) > max_eval_text_len:
             truncated_text += "..."
             print(f"    (Text truncated to {max_eval_text_len} chars for evaluation)")


        prompt = f"""
You are evaluating the relevance of a research paper's {item_type} to a specific subtopic.

Overall User Query: "{self.current_query}"
Current Section in Outline: "{section}"
Specific Subtopic Being Researched: "{subtopic}"

Assess how directly relevant the following text is to the specific subtopic '{subtopic}'. Consider if it provides direct evidence, arguments, data, methods, or context specifically for this subtopic. Ignore information relevant only to the broader user query but not this specific subtopic.

{item_type.capitalize()} Text Snippet:
---
{truncated_text}
---

Provide a relevance score from 1 (Not Relevant) to 10 (Highly Relevant) specifically for the subtopic '{subtopic}'.
Justify your score briefly, focusing ONLY on the connection (or lack thereof) to '{subtopic}'.

Output format must be exactly:
Score: [number]/10. Justification: [Your brief justification focused on subtopic relevance]
"""
        response = robust_call_llm(prompt, model="o3-mini")

        if not response:
            print("Warning: No LLM response for relevance evaluation.")
            return 0, "No LLM response", False

        try:
            
            score_match = re.search(r"Score:\s*(\d{1,2})\s*/\s*10", response)
            
            justification_match = re.search(r"Justification:\s*(.*)", response, re.DOTALL | re.IGNORECASE)

            score = 0
            if score_match:
                 score = int(score_match.group(1))
                 score = max(0, min(10, score))
            else:
                 print("Warning: Could not parse relevance score from LLM response.")

            justification = "No justification provided or parsing failed."
            if justification_match:
                 justification = justification_match.group(1).strip()

            is_relevant = (score >= score_threshold)
            print(f"Relevance Score: {score}/10. Relevant to '{subtopic}': {is_relevant}.")
            if len(justification) > 150:
                 print(f"Justification: {justification[:150]}...")
            else:
                 print(f"Justification: {justification}")

            return score, justification, is_relevant

        except Exception as e:
            print(f"Error parsing relevance score/justification: {e}")
            print(f"LLM response was: {response}")
            return 0, "Parsing failed", False


    
    def _extract_findings(self, item_text: str, item_type: str, section: str, subtopic: str, paper_id: str) -> str | None:
        """Extracts key findings relevant to the subtopic using an LLM."""
        print(f"--- Extracting findings from {item_type} for paper {paper_id} (Subtopic: '{subtopic}') ---")

        
        max_extract_text_len = 6000 
        truncated_text = item_text[:max_extract_text_len]
        if len(item_text) > max_extract_text_len:
             truncated_text += "..."
             print(f"    (Text truncated to {max_extract_text_len} chars for extraction)")


        prompt = f"""
Analyze the following {item_type} text from a research paper (Paper ID: {paper_id}).
The overall research focuses on: "{self.current_query}"
This analysis is for the section '{section}' and specifically the subtopic: '{subtopic}'.

Identify and extract the key sentences or short paragraphs (max 2-3 sentences) that represent concrete findings, arguments, evidence, data points, methods, or conclusions *directly relevant to the subtopic '{subtopic}'*.
Focus *only* on information pertinent to this specific subtopic. If the text discusses the subtopic but offers no specific finding or conclusion about it, state that clearly. Avoid generic statements.

Text ({item_type}):
---
{truncated_text}
---

If relevant findings for '{subtopic}' are present, list them clearly and concisely. Use bullet points if multiple distinct findings are found.
If no specific findings related *directly* to '{subtopic}' are found in this text, output the single word: None

Extracted Findings for '{subtopic}':
"""
        findings = robust_call_llm(prompt, model="o3-mini") 

        if findings:
             findings = findings.strip()
             
             if findings.lower() in ["none", "none.", "no findings found.", "no specific findings found."]:
                  print(f"No specific findings relevant to '{subtopic}' extracted from this {item_type}.")
                  return None
             else:
                  extracted_finding = findings.strip()
                  snippet = extracted_finding.replace('\n', ' ')[:150] 
                  print(f"Extracted Finding Snippet for '{subtopic}': {snippet}...")
                  return extracted_finding
        else:
             print(f"Warning: No LLM response for finding extraction for '{subtopic}'.")
             return None


    
    def step2_research_subtopic(self, subtopic: str):
        """Researches a specific subtopic using APIs and LLM evaluation."""
        print(f"\n>>> STEP 2: Researching Subtopic: {subtopic} <<<")

        plan_id = self.research_plan.get('plan_id')
        if not plan_id:
             print("Error: Cannot research subtopic, research plan ID is not set.")
             return

        
        if subtopic not in self.findings:
            self.findings[subtopic] = []
        if subtopic not in self.processed_paper_ids:
            self.processed_paper_ids[subtopic] = set()

        search_queries = self._generate_search_queries(subtopic)
        papers_found_metadata = {} 

        
        print("\n--- Searching Semantic Scholar ---")
        for query in search_queries:
            print(f"Querying S2: '{query}'")
            try:
                s2_papers = search_semantic_scholar(query, limit=MAX_PAPERS_PER_QUERY)
                for paper in s2_papers:
                    pid = paper.get('paperId')
                    if pid and pid not in papers_found_metadata:
                        papers_found_metadata[pid] = {'metadata': paper, 'source_api': 'semantic_scholar'}
                time.sleep(1) 
            except Exception as e:
                print(f"Error searching Semantic Scholar for query '{query}': {e}")
                time.sleep(2) 

        
        min_papers_threshold = 5 
        if len(papers_found_metadata) < min_papers_threshold:
            print(f"\n--- Found only {len(papers_found_metadata)} papers from S2. Trying OpenAlex ---")
           
            openalex_queries = [subtopic] 
            for query in openalex_queries:
                print(f"Querying OpenAlex: '{query}'")
                try:
                    
                    oa_limit = max(MAX_PAPERS_PER_QUERY, min_papers_threshold)
                    oa_papers = search_open_alex(query, limit=oa_limit)
                    for paper in oa_papers:
                        pid = paper.get('paperId')
                        if pid and pid not in papers_found_metadata:
                            papers_found_metadata[pid] = {'metadata': paper, 'source_api': 'openalex'}
                    time.sleep(1) 
                except Exception as e:
                    print(f"Error searching OpenAlex for query '{query}': {e}")
                    time.sleep(2)

        
        section_name = "Unknown Section"
        if self.research_plan and 'sections' in self.research_plan:
            for s in self.research_plan.get('sections', []):
                if subtopic in s.get('subtopics', []):
                    section_name = s.get('section_name', "Unknown Section")
                    break

        print(f"\n--- Processing {len(papers_found_metadata)} unique papers found for subtopic: '{subtopic}' (Section: {section_name}) ---")
        processed_count = 0
        relevant_count = 0
        total_to_process = len(papers_found_metadata)

        for paper_id, paper_info in papers_found_metadata.items():
            paper = paper_info['metadata']
            source_api = paper_info['source_api']

            if paper_id in self.processed_paper_ids.get(subtopic, set()):
               
                continue

            processed_count += 1
            title = paper.get('title', 'No Title')
            print(f"\n--- Evaluating Paper {processed_count}/{total_to_process}: {title} (ID: {paper_id}, Source: {source_api}) ---")

            
            self._save_source_db(paper, source_api)
            self.sources[paper_id] = paper 

            abstract = paper.get('abstract')
            finding_added = False
            relevance_score = 0
            relevance_justification = ""
            is_relevant_from_abstract = False

            
            if abstract:
                score, justification, relevant = self._evaluate_relevance(
                    item_text=abstract,
                    item_type='abstract',
                    section=section_name,
                    subtopic=subtopic,
                    paper_id=paper_id
                )
                relevance_score = score
                relevance_justification = justification
                is_relevant_from_abstract = relevant

                if relevant:
                    finding = self._extract_findings(
                        item_text=abstract,
                        item_type='abstract',
                        section=section_name,
                        subtopic=subtopic,
                        paper_id=paper_id
                    )
                    if finding:
                        finding_data = {
                            'paperId': paper_id,
                            'finding': finding,
                            'source_type': 'abstract',
                            'relevance_score': score,
                            'justification': justification,
                            'context_snippet': abstract[:1000] + ('...' if len(abstract) > 1000 else '') 
                        }
                        self.findings[subtopic].append(finding_data)
                        self._save_finding_db(subtopic, finding_data)
                        finding_added = True
                        relevant_count += 1 
            else:
                print("Abstract not available for evaluation.")

            
            pdf_url_info = paper.get('openAccessPdf')
            pdf_url = pdf_url_info.get('url') if isinstance(pdf_url_info, dict) else None

            should_try_pdf = (PDF_ANALYSIS_ENABLED and pdf_url and
                              (not is_relevant_from_abstract or (is_relevant_from_abstract and not finding_added)))

            if should_try_pdf:
                print(f"Abstract analysis inconclusive or missing. Attempting PDF analysis from: {pdf_url}")
                pdf_path = None
                pdf_processed = False
                try:
                    
                    temp_pdf_filename = f"temp_{plan_id}_{paper_id.replace('/', '_').replace(':', '_')}.pdf"
                    pdf_path = download_pdf(pdf_url, filename=temp_pdf_filename)
                    if pdf_path and fitz: 
                        pdf_text = extract_text_from_pdf(pdf_path)
                        pdf_processed = True 

                        if pdf_text:
                            
                            pdf_score = relevance_score 
                            pdf_just = relevance_justification
                            pdf_relevant = is_relevant_from_abstract

                            if not is_relevant_from_abstract:
                                 print("Evaluating relevance based on PDF text...")
                                 pdf_score, pdf_just, pdf_relevant = self._evaluate_relevance(
                                     item_text=pdf_text, item_type='full paper text',
                                     section=section_name, subtopic=subtopic, paper_id=paper_id
                                 )

                            
                            if pdf_relevant and not finding_added:
                                print("Extracting findings from PDF text...")
                                finding_pdf = self._extract_findings(
                                    item_text=pdf_text, item_type='full paper text',
                                    section=section_name, subtopic=subtopic, paper_id=paper_id
                                )
                                if finding_pdf:
                                    finding_data = {
                                        'paperId': paper_id,
                                        'finding': finding_pdf,
                                        'source_type': 'full_text',
                                        'relevance_score': pdf_score,
                                        'justification': pdf_just,
                                        'context_snippet': pdf_text[:1000] + ('...' if len(pdf_text) > 1000 else '') 
                                    }
                                    self.findings[subtopic].append(finding_data)
                                    self._save_finding_db(subtopic, finding_data)
                                    finding_added = True
                                    if not is_relevant_from_abstract:
                                         relevant_count += 1
                                else:
                                     print("PDF was relevant but no specific findings extracted.")
                            elif not pdf_relevant:
                                print("PDF text evaluated as not relevant to the subtopic.")

                        else: 
                            print("PDF text extraction failed or yielded no text.")
                    else: 
                        print("PDF download failed.")

                except Exception as pdf_err:
                    print(f"Error processing PDF {pdf_url}: {pdf_err}")
                finally:
                    
                    if pdf_path and os.path.exists(pdf_path):
                        try:
                            os.remove(pdf_path)
                            
                        except OSError as e:
                            print(f"Error removing temporary PDF file {pdf_path}: {e}")

            
            self.processed_paper_ids[subtopic].add(paper_id)
            time.sleep(0.5)

        print(f"--- Finished processing for subtopic: '{subtopic}'. Found {relevant_count} relevant papers yielding findings. ---")


    def step3_consolidate_findings(self, subtopic: str, title: str | None = None, section: str | None = None) -> dict:
        """Consolidates findings for a subtopic, potentially using web search as fallback."""
        print(f"\n>>> STEP 3: Consolidating Findings for: {subtopic} <<<")
        plan_id = self.research_plan.get('plan_id')
        findings_list = self.findings.get(subtopic, []).copy()  
        attempted_web_search = False
        current_date_str = datetime.datetime.now().strftime("%Y-%m-%d")


        if not findings_list:
            print(f"Initial academic findings list empty for '{subtopic}'.")
            if client and PDF_ANALYSIS_ENABLED: 
                print(f"Attempting web search (as of {current_date_str})...")
                attempted_web_search = True
                try:
    
                    web_search_input = (
                        f"As of {current_date_str}, find the most recent and relevant factual summaries, "
                        f"key developments, or authoritative articles about: '{subtopic}'. "
                        f"This is for a research paper titled '{title or 'N/A'}' in the section '{section or 'N/A'}'. "
                        f"Focus on concise facts and findings."
                    )

                   
                    response = client.responses.create(
                        model="gpt-4o",
                        tools=[{"type": "web_search_preview"}],
                        input=f"As of {current_date_str}, find the most recent and relevant information, articles, or news about: "
                            f"'{subtopic}' for the research plan '{title}' in section '{section}'. Focus on factual summaries and key developments.",
                    )
                    print("Debugging: Web search response structure:")
                    print(response)
                    web_search_text = ""
                    for item in response.output:
                        if hasattr(item, 'type') and item.type == "message":
                            if hasattr(item, 'content') and isinstance(item.content, list):
                                for content_block in item.content:
                                    if hasattr(content_block, 'type') and content_block.type == "output_text":
                                        if hasattr(content_block, 'text'):
                                            web_search_text = content_block.text.strip()
                                            break
                                if web_search_text:
                                    break

                    if web_search_text:
                        print("Web search successful, adding result to findings for consolidation.")
                        
                        new_finding = {
                            'paperId': 'web_search_result',  
                            'finding': web_search_text,
                            'source_type': 'web_search',
                            'relevance_score': 8,  
                            'justification': f'Web search result from {current_date_str}',
                            'context_snippet': web_search_input  
                        }
                        findings_list.append(new_finding)
                        
                        self.findings[subtopic] = findings_list
                        self._save_finding_db(subtopic, new_finding)
                    else:
                        print("Web search ran but no text content was extracted or found.")

                except Exception as e:
                    print(f"Web search API call failed: {e}. Proceeding without web results.")
            else:
                print("Web search skipped (client not configured or PDF_ANALYSIS_ENABLED is False).")


        if not findings_list:
            print("No findings available to consolidate, even after potential web search attempt.")
            return {
                "key_themes": [],
                "evidence_summary": f"No relevant findings were gathered or generated for '{subtopic}' (Web search attempted: {attempted_web_search} on {current_date_str}).",
                "contradictions": [],
                "gaps": [f"Lack of available academic research data or relevant recent web information for '{subtopic}' found during this run."]
            }


        findings_text = get_raw_findings_text(self.findings.get(subtopic, []), self.sources, self.research_plan, self._execute_db)


        consolidation_prompt = f"""
You are a research analyst synthesizing findings for the subtopic: '{subtopic}'.
Your goal is to create a coherent overview based *only* on the extracted information provided below, which includes academic findings and potentially recent web search results.

Review the following findings, each tagged with its source [e.g., (Author et al., Year), Automated Web Search, YYYY-MM-DD].

Raw Findings for '{subtopic}':
--- START FINDINGS ---
{findings_text}
--- END FINDINGS ---

Synthesize these findings. Identify:
1.  **Key Themes:** What are the recurring ideas, concepts, methods, or results across the provided sources? (List 2-5 themes).
2.  **Evidence Summary:** Briefly summarize the main supporting points or data mentioned for the key themes. Note the origin type (e.g., academic paper, web search) if relevant (e.g., "Recent web searches suggest X, while earlier papers found Y").
3.  **Contradictions/Disagreements:** Are there any findings (including web search vs. papers) that conflict with each other? Note them specifically. If none, state "None identified".
4.  **Gaps/Unanswered Questions:** Based *only* on the information provided, what seems to be missing, unaddressed, or requires further investigation regarding '{subtopic}'?

Output ONLY valid JSON with this exact structure:
{{
  "key_themes": ["list of identified themes as strings"],
  "evidence_summary": "string - A concise paragraph summarizing synthesized evidence, referencing themes.",
  "contradictions": ["list of noted contradictions/disagreements as strings, or empty list"],
  "gaps": ["list of identified gaps/questions based *only* on the provided text, as strings"]
}}

Do not add commentary outside the JSON structure. Focus on accurate synthesis of the provided text only.
"""
        print("Sending combined findings to LLM for consolidation...")
        consolidated_json_str = robust_call_llm(consolidation_prompt, model="o3-mini")  

        if not consolidated_json_str:
            print("Error: No LLM response during consolidation.")

            return {"error": "No LLM response during consolidation", "raw_findings_input": findings_text}

        try:
            consolidated_json_str = consolidated_json_str.strip().lstrip('```json').rstrip('```').strip()
            consolidated_data = json.loads(consolidated_json_str)


            required_keys = ['key_themes', 'evidence_summary', 'contradictions', 'gaps']
            if not all(k in consolidated_data for k in required_keys):
                raise ValueError("Consolidated JSON missing required keys.")
            if not isinstance(consolidated_data['key_themes'], list): raise ValueError("key_themes should be a list")
            if not isinstance(consolidated_data['evidence_summary'], str): raise ValueError("evidence_summary should be a string")
            if not isinstance(consolidated_data['contradictions'], list): raise ValueError("contradictions should be a list")
            if not isinstance(consolidated_data['gaps'], list): raise ValueError("gaps should be a list")

            print(f"--- Consolidation Summary for '{subtopic}' (Structured) ---")
            print(json.dumps(consolidated_data, indent=2))
            return consolidated_data

        except json.JSONDecodeError as e:
            print(f"Error: Failed to parse consolidation JSON: {e}")
            print(f"LLM response was:\n---\n{consolidated_json_str}\n---")
            return {"error": f"Failed to parse consolidation JSON: {e}", "raw_response": consolidated_json_str, "raw_findings_input": findings_text}
        except ValueError as e:
             print(f"Error: Invalid consolidation JSON structure: {e}")
             print(f"LLM response was:\n---\n{consolidated_json_str}\n---")
             return {"error": f"Invalid consolidation JSON structure: {e}", "raw_response": consolidated_json_str, "raw_findings_input": findings_text}
        except Exception as e:
            print(f"An unexpected error occurred during consolidation processing: {e}")
            return {"error": f"Unexpected consolidation error: {e}", "raw_response": consolidated_json_str, "raw_findings_input": findings_text}



    def step4_write_all_sections_recursive(self, subtopic_consolidations: dict) -> dict:
        """Writes all sections of the paper sequentially using LLM."""
        print("\n>>> STEP 4: Writing All Sections <<<")
        written_sections = {}
        previously_written_text = "" 
        all_sections = self.research_plan.get('sections', [])
        plan_id = self.research_plan.get('plan_id')

        if not all_sections:
            print("Error: No sections defined in the research plan. Cannot write.")
            return {}

       
        print("--- Compiling Reference Material for Writing ---")
        reference_material_parts = []
        for sec_ref in all_sections:
            sec_name_ref = sec_ref.get('section_name', 'Unnamed Section')
            for subtopic_ref in sec_ref.get('subtopics', []):
                consolidation_data = subtopic_consolidations.get(subtopic_ref)
                ref_text = f"--- Subtopic: '{subtopic_ref}' (Relevant to Section: '{sec_name_ref}') ---\n"
                if consolidation_data and isinstance(consolidation_data, dict) and "error" not in consolidation_data:
                    
                    ref_text += f"  Consolidated Themes: {json.dumps(consolidation_data.get('key_themes', []))}\n"
                    ref_text += f"  Consolidated Summary: {consolidation_data.get('evidence_summary', 'N/A')}\n"
                    ref_text += f"  Consolidated Contradictions: {json.dumps(consolidation_data.get('contradictions', []))}\n"
                    ref_text += f"  Consolidated Gaps: {json.dumps(consolidation_data.get('gaps', []))}\n"
                elif consolidation_data and isinstance(consolidation_data, dict) and "error" in consolidation_data:
                     ref_text += f"  Consolidation Status: Error - {consolidation_data.get('error')}\n"
                else:
                    ref_text += "  Consolidation Status: Data not available or invalid.\n"

                
                raw_findings_for_subtopic = get_raw_findings_text(
    self.findings.get(subtopic_ref, []),
    self.sources,
    self.research_plan,
    self._execute_db 
)
                if raw_findings_for_subtopic != "No raw findings available.":
                    ref_text += f"  Supporting Raw Findings (with citations):\n{raw_findings_for_subtopic}\n"
                else:
                     ref_text += "  Supporting Raw Findings: None available.\n"

                reference_material_parts.append(ref_text)

        reference_material = "\n".join(reference_material_parts)
        print(f"Compiled reference material (approx {len(reference_material)} chars).")
        
        for i, section in enumerate(all_sections):
            sec_name = section.get("section_name", f"Unnamed Section {i+1}")
            sec_subtopics = section.get("subtopics", [])
            print(f"--- Writing section {i+1}/{len(all_sections)}: '{sec_name}' (Subtopics: {', '.join(sec_subtopics)}) ---")

           
            approx_prompt_len = len(reference_material) + len(previously_written_text) + 1000 
            

            prompt = f"""
You are an expert academic writer drafting a specific section of a research paper.
Paper Title: '{self.research_plan.get('title', 'Untitled Paper')}'
Overall Research Question(s): {self.research_plan.get('research_questions', ['N/A'])}

Your current task is to write the complete text for the section titled: '{sec_name}'.
This section should primarily focus on addressing the following subtopic(s): {', '.join(sec_subtopics)}.

Use the provided 'Reference Material' below. This material contains consolidated summaries and raw findings (with citations like (Author et al., Year) or (Automated Web Search, YYYY-MM-DD)) for various subtopics across the entire paper.
Synthesize information *specifically relevant* to '{sec_name}' and its subtopics ({', '.join(sec_subtopics)}) from this material.

**Crucially: Whenever you incorporate specific information, claims, methods, data, or evidence derived from the 'Supporting Raw Findings' section of the reference material, you MUST include the corresponding in-text citation exactly as provided [e.g., (Smith et al., 2022), (Automated Web Search, 2025-03-31)].** Embed these citations naturally within your sentences (e.g., "Recent studies suggest X (Author et al., 2023)."). Aim for multiple citations per paragraph where appropriate to support your statements. Use the consolidated themes and summaries for high-level structure but back up claims with cited raw findings.

Ensure the writing style is academic, objective, clear, and coherent. The section should logically follow the 'Previously Written Text' (if provided) and flow smoothly. Avoid simply listing points; create a well-structured narrative or argument for '{sec_name}'. Adhere strictly to the subtopics assigned to this section.

**Reference Material (Consolidated Summaries & Raw Findings with Citations):**
--- START MATERIAL ---
{reference_material}
--- END MATERIAL ---

**Previously Written Text (End of the preceding section):**
--- START PREVIOUS ---
{previously_written_text if previously_written_text else "This is the first section (Introduction). Start the paper's main body here."}
--- END PREVIOUS ---

**Instructions:** Write *only* the full text for the section '{sec_name}'. Start the output *immediately* with the Markdown header '## {sec_name}'. Do not include any preamble, explanation, or text before this header. Ensure proper Markdown formatting for paragraphs.
"""
            
            section_text = robust_call_llm(prompt, model="o3-mini")

            if not section_text:
                print(f"Warning: No content generated for section '{sec_name}'. Adding placeholder.")
                section_text = f"## {sec_name}\n\n[Content generation failed for this section]\n"
            else:
                section_text = section_text.strip()
                expected_header = f"## {sec_name}"
                header_pos = section_text.find(expected_header)
                if header_pos > 0:
                     print(f"Warning: Trimming preamble before header in '{sec_name}'.")
                     section_text = section_text[header_pos:]
                elif header_pos == -1: 
                     print(f"Warning: LLM output for '{sec_name}' did not contain the expected header. Prepending.")
                     section_text = f"{expected_header}\n\n{section_text}"

            print(f"Generated text snippet for '{sec_name}': {section_text.replace(chr(10), ' ')}[:300]...")
            written_sections[sec_name] = section_text
            
            previously_written_text += section_text + "\n\n"
            time.sleep(1) 

        print("--- All Sections Written ---")
        return written_sections


    
    def step5_compile_output(self, written_sections: dict) -> str:
        """Compiles the final report text including title, sections, and references."""
        print("\n>>> STEP 5: Compiling Final Output <<<")
        plan_id = self.research_plan.get('plan_id')

        
        full_text = f"# {self.research_plan.get('title', 'Research Paper')}\n\n"
        if self.research_plan.get('research_questions'):
            full_text += "## Research Question(s)\n"
            for rq in self.research_plan.get('research_questions', []):
                full_text += f"- {rq}\n"
            full_text += "\n"

        
        section_order = [s.get("section_name") for s in self.research_plan.get('sections', [])]
        for sec_name in section_order:
            if sec_name in written_sections:
                full_text += written_sections[sec_name] + "\n\n"
            elif sec_name: 
                print(f"Warning: Section '{sec_name}' was planned but not found in written sections.")
                full_text += f"## {sec_name}\n\n[Section content not generated or available.]\n\n"

        
        full_text += "## References\n\n"
        cited_paper_ids = set()

        
        if plan_id:
            try:
                
                rows = self._execute_db(
                    """SELECT DISTINCT paper_id FROM findings
                       WHERE plan_id=? AND paper_id != 'web_search_result'""",
                    (plan_id,), fetch_all=True
                )
                if rows:
                    cited_paper_ids.update([r[0] for r in rows])
            except Exception as e:
                print(f"Error fetching cited paper IDs from database: {e}. Falling back to in-memory sources.")
               
                cited_paper_ids.update(k for k in self.sources.keys() if k != 'web_search_result')
        else:
             print("Warning: No plan_id found. Reference list based only on in-memory sources.")
             cited_paper_ids.update(k for k in self.sources.keys() if k != 'web_search_result')


        if not cited_paper_ids:
            full_text += "No academic sources were cited or found for this research.\n"
        else:
            print(f"Generating reference list for {len(cited_paper_ids)} unique cited sources.")
            reference_entries = []
            
            sorted_paper_ids = sorted(list(cited_paper_ids))

            for pid in sorted_paper_ids:
                title, authors_json, year, venue, journal_name = None, None, None, None, None
                source_data = None
                if plan_id:
                    try:
                        row = self._execute_db(
                            """SELECT title, authors, year, venue, journal_name
                               FROM sources WHERE paper_id=? AND plan_id=?""",
                            (pid, plan_id), fetch_one=True
                        )
                        if row:
                            title, authors_json, year, venue, journal_name = row
                            source_data = 'DB'
                    except Exception as e:
                        print(f"DB Error fetching source details for {pid}: {e}.")

                
                if not source_data and pid in self.sources:
                    print(f"Using in-memory source data for {pid}.")
                    src = self.sources[pid]
                    title = src.get("title")
                    authors_list_mem = [a.get('name') for a in src.get('authors', []) if a.get('name')]
                    authors_json = json.dumps(authors_list_mem)
                    year = src.get("year")
                    venue = src.get("venue")
                    journal_info_mem = src.get("journal") or {}
                    journal_name = journal_info_mem.get("name")
                    source_data = 'Memory'

                if source_data:
                    authors_list = []
                    if authors_json:
                        try:
                            authors_list = json.loads(authors_json)
                        except json.JSONDecodeError:
                            print(f"Warning: Could not decode authors JSON for Paper ID {pid} from {source_data}.")
                            authors_list = []

                    
                    authors_str = format_authors_harvard_ref_list(authors_list)
                    year_str = str(year) if year else "n.d."
                    
                    title_str = f"*{title.strip()}*" if title else "*[Title Not Available]*"
                    
                    publication_venue = journal_name or venue or ""

                    
                    ref_str = f"{authors_str} ({year_str}). {title_str}"
                    if publication_venue:
                        ref_str += f" {publication_venue.strip()}."
                    else:
                         ref_str += "."

                    reference_entries.append((authors_str, ref_str)) 
                else:
                    print(f"Warning: Could not retrieve sufficient details for Paper ID {pid} to create reference entry.")

            reference_entries.sort(key=lambda x: x[0].lower())

            if reference_entries:
                full_text += "\n".join([f"- {ref[1]}" for ref in reference_entries])
            else:
                full_text += "No valid reference entries could be generated.\n"

        print("--- Final Compiled Output Ready ---")
        return full_text


   