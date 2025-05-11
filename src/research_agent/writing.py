import json
import time
from collections import defaultdict
import json # Keep

# Use relative imports for modules within the same package
from .utils.utils import call_llm
from .utils.aggregation_utils import get_raw_findings_text
from .utils.db_utils import execute_db

# Note: This function was originally step4_write_all_sections_recursive in ResearchAgent.
# It now takes necessary state (plan, findings, sources, etc.) as arguments.

def write_all_sections(
    research_plan: dict,
    subtopic_consolidations: dict,
    findings: defaultdict[str, list],
    sources: dict,
    db_path: str,
    citation_style: str = "harvard", # Default citation style
    # execute_db_func: callable # Pass the DB execution function/method
) -> dict:
    """Writes all sections of the paper sequentially using LLM."""
    print("\n>>> STEP 4: Writing All Sections <<<")
    written_sections = {}
    previously_written_text = "" # Keep track of preceding text for context
    all_sections = research_plan.get('sections', [])
    plan_id = research_plan.get('plan_id') # Needed for DB queries in get_raw_findings_text

    if not all_sections:
        print("Error: No sections defined in the research plan. Cannot write.")
        return {}

    # --- Compile Reference Material ---
    # This material combines consolidated summaries and raw findings for the LLM writer
    print("--- Compiling Reference Material for Writing ---")
    reference_material_parts = []
    for sec_ref in all_sections:
        sec_name_ref = sec_ref.get('section_name', 'Unnamed Section')
        for subtopic_ref in sec_ref.get('subtopics', []):
            consolidation_data = subtopic_consolidations.get(subtopic_ref)
            ref_text = f"--- Subtopic: '{subtopic_ref}' (Relevant to Section: '{sec_name_ref}') ---\n"

            # Add consolidated info if available and valid
            if consolidation_data and isinstance(consolidation_data, dict) and "error" not in consolidation_data:
                ref_text += f"  Consolidated Themes: {json.dumps(consolidation_data.get('key_themes', []))}\n"
                ref_text += f"  Consolidated Summary: {consolidation_data.get('evidence_summary', 'N/A')}\n"
                ref_text += f"  Consolidated Contradictions: {json.dumps(consolidation_data.get('contradictions', []))}\n"
                ref_text += f"  Consolidated Gaps: {json.dumps(consolidation_data.get('gaps', []))}\n"
            elif consolidation_data and isinstance(consolidation_data, dict) and "error" in consolidation_data:
                 ref_text += f"  Consolidation Status: Error - {consolidation_data.get('error')}\n"
            else:
                ref_text += "  Consolidation Status: Data not available or invalid.\n"

            # Add raw findings (with citations) for this subtopic
            # Pass the execute_db function directly
            raw_findings_for_subtopic = get_raw_findings_text(
                findings.get(subtopic_ref, []),
                sources,
                research_plan,
                # More robust lambda accepting *args and **kwargs
                lambda *args, **kwargs: execute_db(db_path, *args, **kwargs),
                citation_style=citation_style
            )
            if raw_findings_for_subtopic != "No raw findings available.":
                ref_text += f"  Supporting Raw Findings (with citations):\n{raw_findings_for_subtopic}\n"
            else:
                 ref_text += "  Supporting Raw Findings: None available.\n"

            reference_material_parts.append(ref_text)

    reference_material = "\n".join(reference_material_parts)
    print(f"Compiled reference material (approx {len(reference_material)} chars).")

    # --- Write Each Section ---
    for i, section in enumerate(all_sections):
        sec_name = section.get("section_name", f"Unnamed Section {i+1}")
        sec_subtopics = section.get("subtopics", [])
        print(f"--- Writing section {i+1}/{len(all_sections)}: '{sec_name}' (Subtopics: {', '.join(sec_subtopics)}) ---")

        # Estimate prompt length (optional, for debugging or context management)
        # approx_prompt_len = len(reference_material) + len(previously_written_text) + 1000 # Rough estimate
        inferred_doc_type = research_plan.get('inferred_document_type', 'Research Paper') # Get inferred type

        prompt = f"""
You are an expert writer drafting a section for a document of type: **{inferred_doc_type}**.
Document Title: '{research_plan.get('title', 'Untitled Document')}'
Overall Research Question(s)/Key Questions: {research_plan.get('research_questions', research_plan.get('key_questions_to_address', ['N/A']))}

Your current task is to write the complete text for the section titled: '{sec_name}'.
This section should address the following key subtopics/areas based on the plan outline: {', '.join(sec_subtopics)}.

Use the provided 'Reference Material' below. This material contains consolidated research summaries and raw findings (with citations like (Author et al., Year) or (Web Search, YYYY-MM-DD)) gathered for various subtopics.
Synthesize information *specifically relevant* to '{sec_name}' and its subtopics ({', '.join(sec_subtopics)}) from this material. Go beyond simple summarization; critically evaluate, compare, and contrast findings where appropriate.

**Instructions for Writing Section '{sec_name}':**
1.  **Address Subtopics:** Directly address each subtopic listed for this section: {', '.join(sec_subtopics)}.
2.  **Synthesize Research:** Incorporate relevant insights, data, themes, summaries, contradictions, and gaps from the 'Reference Material'. Perform deeper analysis and synthesis relevant to the '{inferred_doc_type}' format.
3.  **Cite Sources:** When using specific information derived from the 'Supporting Raw Findings' in the reference material, include the corresponding in-text citation *exactly as provided* [e.g., (Smith et al., 2022), (Source: http://example.com)]. Embed citations naturally. If a finding is labeled 'Web Finding:' but has no accompanying '(Source: ...)' citation, integrate the information smoothly into the text *without* adding a generic placeholder like '(Web Search)'.
4.  **Appropriate Tone & Style:** Adopt a writing style suitable for the inferred document type ('{inferred_doc_type}'). Be objective, clear, and professional. For plans/reports, use actionable language where appropriate. For reviews/papers, maintain an academic tone.
5.  **Structure & Flow:** Ensure the section flows logically from the 'Previously Written Text' (if provided). Use paragraphs, headings (if appropriate within the section), and bullet points for clarity.
6.  **Output Format:** Write *only* the full text for the section '{sec_name}'. Start the output *immediately* with the Markdown header '## {sec_name}'. Do not include any preamble, explanation, or text before this header.

**Reference Material (Consolidated Summaries & Raw Findings with Citations):**
--- START MATERIAL ---
{reference_material}
--- END MATERIAL ---

**Previously Written Text (End of the preceding section):**
--- START PREVIOUS ---
{previously_written_text if previously_written_text else "This is the first section."}
--- END PREVIOUS ---

**Write the complete section '## {sec_name}' now:**
"""

        section_text = call_llm(prompt, model="o3-mini")

        if not section_text:
            print(f"Warning: No content generated for section '{sec_name}'. Adding placeholder.")
            section_text = f"## {sec_name}\n\n[Content generation failed for this section]\n"
        else:
            # Basic cleanup and header check
            section_text = section_text.strip()
            expected_header = f"## {sec_name}"
            header_pos = section_text.find(expected_header)
            if header_pos > 0: # Found header, but not at the start
                 print(f"Warning: Trimming preamble before header in '{sec_name}'.")
                 section_text = section_text[header_pos:]
            elif header_pos == -1: # Header missing entirely
                 print(f"Warning: LLM output for '{sec_name}' did not contain the expected header. Prepending.")
                 section_text = f"{expected_header}\n\n{section_text}"

        print(f"Generated text snippet for '{sec_name}': {section_text.replace(chr(10), ' ')}[:300]...")
        written_sections[sec_name] = section_text

        # Append the newly written section to the context for the next iteration
        previously_written_text += section_text + "\n\n"
        time.sleep(1) # Small delay between sections

    print("--- All Sections Written ---")
    return written_sections
