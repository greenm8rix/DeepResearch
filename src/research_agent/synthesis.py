import datetime
import json
from collections import defaultdict
from openai import OpenAI # Keep if client is used directly
from collections import defaultdict # Keep
import datetime # Keep
import json # Keep
import re # Import regular expression module

# Use relative imports for modules within the same package
from .config import PDF_ANALYSIS_ENABLED, client
from .utils.utils import call_llm
from .utils.aggregation_utils import get_raw_findings_text
from .utils.db_utils import save_finding_db, execute_db
# Need evaluate_relevance, potentially extract_findings if we want findings from web search too
from .researching import _evaluate_relevance # Removed _extract_findings for now, focus on relevance
from .config import RELEVANCE_SCORE_THRESHOLD, client, PDF_ANALYSIS_ENABLED # Import threshold & client

# Note: This function was originally step3_consolidate_findings in ResearchAgent.
# It now takes necessary state (db_path, plan, findings, sources, etc.) as arguments.

def consolidate_findings(
    subtopic: str,
    research_plan: dict,
    db_path: str,
    findings: defaultdict[str, list], # Modified in-place if web search adds findings
    sources: dict,
    current_query: str, # Need current_query for evaluation context
    relevance_cache: dict # Added cache parameter
) -> dict:
    """Consolidates academic findings and web search results for a subtopic."""
    print(f"\n>>> STEP 3: Consolidating Findings for: {subtopic} <<<")

    # Placeholder check removed as planning should no longer generate them.

    plan_id = research_plan.get('plan_id')
    title = research_plan.get('title', 'Research Paper') # Get title from plan
    section = "Unknown Section" # Find section name
    if research_plan and 'sections' in research_plan:
        for s in research_plan.get('sections', []):
            if subtopic in s.get('subtopics', []):
                section = s.get('section_name', "Unknown Section")
                break

    current_date_str = datetime.datetime.now().strftime("%Y-%m-%d")
    web_search_performed = False
    web_search_finding = None # Variable to hold the relevant web finding, if any

    # --- Step 3.1: Mandatory Web Search (Performed First) ---
    print(f"Performing mandatory web search for '{subtopic}'...")
    if client:
        web_search_performed = True
        web_search_text = ""
        web_search_source_url = "[URL not found]" # Default
        response = None # Initialize response
        try:
            # 1. Build the prompt (Requesting Author/Org and Title)
            web_search_input = (
                f"As of {current_date_str}, find the most recent and relevant factual summary, "
                f"key development, or authoritative article about: '{subtopic}'. "
                f"This is for a research paper titled '{title}' in the section '{section}'. "
                f"Identify the author or organization responsible for the content, the title of the specific page/article, "
                f"a concise factual finding relevant to the subtopic, and the source URL. "
                f"Return ONLY a valid JSON object with this exact structure: "
                f"{{\"author_org\": \"Identified Author or Organization (or null if none)\", \"title\": \"Page/Article Title (or null if none)\", \"finding\": \"Concise factual finding summary\", \"url\": \"best_source_url_found\"}}. "
                f"If no relevant information, author, title, or URL can be found, return null for the respective fields, but always return the JSON structure. "
                f"Example if nothing found: {{\"author_org\": null, \"title\": null, \"finding\": \"No relevant information found.\", \"url\": null}}."
            )

            # 2. Call the Responses API with the Web Search Preview tool enabled
            response = client.responses.create(
                model="gpt-4o", # Expecting JSON output
                tools=[{"type": "web_search_preview"}],
                input=web_search_input
            )
            print("DEBUG: Raw web search response payload:", response) # Log raw response object

        except Exception as api_err:
            print(f"Web search API call failed: {api_err}. Proceeding without web results.")
            response = None # Ensure response is None on API error

        # --- Parsing Logic for client.responses.create structure ---
        if response:
            json_string = None # Initialize json_string
            parsed_json = None # Initialize parsed_json
            try:
                # Navigate the nested structure based on the logs
                if hasattr(response, 'output') and isinstance(response.output, list) and len(response.output) > 1:
                    # Find the assistant message (usually the second item)
                    assistant_message = None
                    for item in response.output:
                         # Check if item is an object with type/role attributes or a dict
                         item_dict = {}
                         if hasattr(item, '__dict__'): item_dict = item.__dict__
                         elif isinstance(item, dict): item_dict = item

                         if item_dict.get('type') == 'message' and item_dict.get('role') == 'assistant':
                              assistant_message = item
                              break

                    if assistant_message and hasattr(assistant_message, 'content') and isinstance(assistant_message.content, list) and len(assistant_message.content) > 0:
                        # Get the first content block (assuming ResponseOutputText)
                        content_block = assistant_message.content[0]
                        if hasattr(content_block, 'text') and isinstance(content_block.text, str):
                            raw_text = content_block.text
                            print(f"DEBUG: Found raw text in response output: {raw_text}")
                            # Strip markdown fences and parse
                            json_string = raw_text.strip().lstrip('```json').rstrip('```').strip()
                            if json_string:
                                 print(f"DEBUG: Attempting to parse JSON string: {json_string}")
                                 parsed_json = json.loads(json_string)
                            else:
                                 print("Warning: Text found but was empty after stripping markdown fences.")
                        else:
                             print("Warning: Assistant message content block has no 'text' attribute or it's not a string.")
                    else:
                     print("Warning: Could not find assistant message or valid content block in response output.")
                else:
                     print("Warning: Response object has no 'output' list or it's too short.")

                # Process the parsed_json if successful
                # REMOVED erroneous line: parsed_json = None

                if parsed_json and isinstance(parsed_json, dict):
                    web_search_author_org = parsed_json.get('author_org')
                    web_search_title = parsed_json.get('title')
                    web_search_text = parsed_json.get('finding', '').strip()
                    web_search_source_url = parsed_json.get('url') # Get URL, could be None

                    # Handle case where no relevant info was found explicitly
                    if not web_search_text or web_search_text.lower() == "no relevant information found.":
                         print("Web search explicitly returned no relevant information.")
                         web_search_text = "" # Reset text so it's not processed further
                         web_search_source_url = "[URL not found]"
                    elif not web_search_text:
                         print("Warning: Web search JSON response had no 'finding' text.")
                         web_search_author_org = web_search_author_org or "Unknown Author/Org"
                         web_search_title = web_search_title or "Untitled Page"
                         web_search_source_url = web_search_source_url or "[URL not found]" # Reset URL if text is missing
                    elif not web_search_source_url:
                         print("Warning: Web search JSON response had 'finding' but no 'url'.")
                         web_search_source_url = "[URL not found]" # Set URL to default if missing
                         web_search_author_org = web_search_author_org or "Unknown Author/Org"
                         web_search_title = web_search_title or "Untitled Page"
                    else:
                         # Use defaults if author/title are missing but URL/finding exist
                         web_search_author_org = web_search_author_org or "Unknown Author/Org"
                         web_search_title = web_search_title or "Untitled Page"
                         print(f"DEBUG: Extracted from JSON - Author/Org: {web_search_author_org}")
                         print(f"DEBUG: Extracted from JSON - Title: {web_search_title}")
                         print(f"DEBUG: Extracted from JSON - URL: {web_search_source_url}")
                         print(f"DEBUG: Extracted from JSON - Finding: {web_search_text[:100]}...")
                else:
                    print("Warning: Web search response was not a valid JSON object or parsing failed.")
                    web_search_text = ""
                    web_search_source_url = "[URL not found]"

            except json.JSONDecodeError as json_err:
                 # Attempt to capture the raw string causing the error if possible
                 raw_err_str = json_string if 'json_string' in locals() and json_string else "Unavailable"
                 print(f"Web search JSON response PARSING failed: {json_err}. Raw string was: '{raw_err_str}'")
                 web_search_text = ""
                 web_search_source_url = "[URL not found]"
            except Exception as parse_err:
                print(f"Unexpected error during web search response PARSING: {parse_err}.")
                web_search_text = ""
                web_search_source_url = "[URL not found]"

        # --- Evaluate and Process Extracted Text ---
        # This block remains largely the same, using the extracted web_search_text and web_search_source_url
        if web_search_text:
                print(f"Web search returned text. Evaluating relevance...")
                # Evaluate relevance using the imported function
                # Create a consistent paper_id for web search that will be used for both evaluation and storage
                web_search_paper_id = f'web_search_{current_date_str}'

                web_score, web_justification, web_relevant = _evaluate_relevance(
                    item_text=web_search_text,
                    item_type='web search result',
                    section=section,
                    subtopic=subtopic,
                    paper_id=web_search_paper_id, # Use consistent ID for evaluation context
                    current_query=current_query,
                    relevance_cache=relevance_cache, # Pass cache
                    score_threshold=RELEVANCE_SCORE_THRESHOLD # Use configured threshold
                )

                if web_relevant:
                    print("Web search result is relevant. Adding to findings.")
                    # Optional: Extract specific findings from web text if desired (using _extract_findings)
                    # finding_web = _extract_findings(web_search_text, 'web search result', section, subtopic, web_search_paper_id, current_query)
                    # finding_to_add = finding_web if finding_web else web_search_text # Use extracted finding or full text

                    # Create finding structure with evaluated score/justification
                    new_finding = {
                        'paperId': web_search_paper_id, # Consistent ID for web search finding
                        'finding': web_search_text,
                        'source_type': 'web_search',
                        'relevance_score': web_score,
                        'justification': web_justification,
                        # Store structured data in context_snippet as JSON string
                        'context_snippet': json.dumps({
                            "author_org": web_search_author_org,
                            "title": web_search_title,
                            "url": web_search_source_url,
                            "access_date": current_date_str # Include access date
                        })
                    }
                    # Store the relevant web finding temporarily
                    web_search_finding = new_finding
                    # Save the web finding to DB immediately if relevant
                    if plan_id:
                        try:
                            # Our enhanced save_finding_db will handle creating the source entry first
                            save_finding_db(db_path, research_plan, subtopic, web_search_finding)
                            print(f"Successfully saved web search finding to database with ID: {web_search_paper_id}")
                        except Exception as e:
                            print(f"Error saving web search finding to database: {e}")
                    else:
                         print("Warning: Cannot save web search finding to DB, plan_id missing.")
                else:
                    print("Web search result evaluated as not relevant.")

    else:
        print("Web search skipped (OpenAI client not configured).")

    # --- Step 3.2: Prepare Combined Findings for Consolidation ---
    # Get academic findings passed into the function
    academic_findings_list = findings.get(subtopic, [])

    # Combine relevant web finding (if any) with academic findings
    combined_findings_list = []
    if web_search_finding:
        combined_findings_list.append(web_search_finding)
        # Also update the main findings dict passed by reference
        # Ensure we don't add duplicates if the function is somehow called multiple times
        # for the same subtopic within a run (unlikely but safer)
        current_subtopic_findings = findings.setdefault(subtopic, [])
        if not any(f.get('paperId') == web_search_finding['paperId'] for f in current_subtopic_findings):
             current_subtopic_findings.insert(0, web_search_finding) # Add web finding at the beginning

    combined_findings_list.extend(academic_findings_list)


    # --- Step 3.3: Consolidate with LLM (using combined list) ---
    if not combined_findings_list:
        print("No findings available to consolidate (academic or web).")
        # Return a default structure indicating no findings
        # Update message slightly to reflect web search was attempted first
        return {
            "key_themes": [],
            "evidence_summary": f"No relevant findings were gathered for '{subtopic}' (Web search attempted: {web_search_performed}).",
            "contradictions": [],
            "gaps": [f"Lack of available academic research data or relevant web information for '{subtopic}' found during this run."]
        }

    # Prepare the raw findings text for the LLM prompt using the combined list
    # Pass the execute_db function directly, ensuring lambda handles kwargs (Corrected Lambda AGAIN)
    findings_text = get_raw_findings_text(
        combined_findings_list,
        sources,
        research_plan,
        lambda *args, **kwargs: execute_db(db_path, *args, **kwargs) # Use *args, **kwargs
    )


    consolidation_prompt = f"""
You are a research analyst synthesizing findings for the subtopic: '{subtopic}'.
Your goal is to create a coherent overview based *only* on the extracted information provided below. This includes potentially web search results [e.g., (Web Search, YYYY-MM-DD) or (Source: URL)] and academic findings [e.g., (Author et al., Year)].

Review the following findings (web search results may appear first):
--- START FINDINGS ---
{findings_text}
--- END FINDINGS ---

Synthesize these findings. **Prioritize insights from academic papers [e.g., (Author et al., Year)] over web search results [e.g., (Web Search, YYYY-MM-DD)] when summarizing and identifying themes.** Identify:
1.  **Key Themes:** What are the recurring ideas, concepts, methods, or results across the provided sources, giving more weight to academic findings? (List 2-5 themes).
2.  **Evidence Summary:** Briefly summarize the main supporting points or data mentioned for the key themes, emphasizing academic evidence. Note the origin type (e.g., academic paper, web search) if relevant (e.g., "Academic papers indicate Z, while a recent web search suggests X").
3.  **Contradictions/Disagreements:** Are there any findings (especially between academic papers and web searches) that conflict? Note them specifically. If none, state "None identified".
4.  **Gaps/Unanswered Questions:** Based *only* on the information provided, what seems to be missing, unaddressed, or requires further investigation regarding '{subtopic}', particularly considering the academic literature?

Output ONLY valid JSON with this exact structure:
{{
  "key_themes": ["list of identified themes as strings"],
  "evidence_summary": "string - A concise paragraph summarizing synthesized evidence, referencing themes.",
  "contradictions": ["list of noted contradictions/disagreements as strings, or empty list"],
  "gaps": ["list of identified gaps/questions based *only* on the provided text, as strings"]
}}

Do not add commentary outside the JSON structure. Focus on accurate synthesis of the provided text only.
"""
    print("Sending combined findings (web search first, if relevant) to LLM for consolidation...")
    consolidated_json_str = call_llm(consolidation_prompt, model="o3-mini") # Consider larger model if needed

    if not consolidated_json_str:
        print("Error: No LLM response during consolidation.")
        # Return error structure including raw input for debugging
        return {"error": "No LLM response during consolidation", "raw_findings_input": findings_text}

    try:
        consolidated_json_str = consolidated_json_str.strip().lstrip('```json').rstrip('```').strip()
        consolidated_data = json.loads(consolidated_json_str)

        # Validate structure
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
