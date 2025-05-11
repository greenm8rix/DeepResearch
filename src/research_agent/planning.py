import json
import re
# Use relative imports for modules within the same package
from .config import MAX_SEARCH_QUERIES_PER_SUBTOPIC
from .utils.utils import call_llm
from .utils.db_utils import save_plan_db

def generate_research_plan(user_query: str, db_path: str) -> dict:
    """
    Generates the research plan using an LLM and saves it to the database.

    Args:
        user_query: The user's research query.
        db_path: Path to the SQLite database.

    Returns:
        A dictionary representing the research plan, including the 'plan_id'
        if successful, or {'plan_id': None} on failure.
    """
    print("\n>>> STEP 1: Generating Research Plan <<<")

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
    plan_json_str = call_llm(prompt, model="o3-mini")

    if not plan_json_str:
        print("Error: No response from LLM for plan generation.")
        return {'plan_id': None} # Return a dict indicating failure

    print(f"LLM Response Snippet (Plan): {plan_json_str[:250]}...")
    parsed_plan = None # Initialize to handle potential errors before assignment

    try:
        # Clean up potential markdown code fences
        plan_json_str = plan_json_str.strip().lstrip('```json').rstrip('```').strip()
        parsed_plan = json.loads(plan_json_str)

        # Validate structure
        required_keys = ['title', 'research_questions', 'sections']
        if not all(k in parsed_plan for k in required_keys) or \
           not isinstance(parsed_plan['research_questions'], list) or \
           not isinstance(parsed_plan['sections'], list) or \
           not parsed_plan['sections']:
            raise ValueError("Invalid plan structure received (missing keys or wrong types).")

        # Optional validation warnings
        if len(parsed_plan['research_questions']) < 3:
            print("Warning: Fewer than 3 research questions generated.")
        if len(parsed_plan['sections']) < 5: # Intro + 3 intermediate + Conclusion
            print(f"Warning: Only {len(parsed_plan['sections'])} sections generated. Might lack depth.")
        if not all("subtopics" in s and isinstance(s.get("subtopics"), list) and s.get("subtopics") for s in parsed_plan['sections']):
             print("Warning: Some sections might be missing subtopics lists or have empty subtopics.")


        print("--- Research Plan Generated ---")
        print(json.dumps(parsed_plan, indent=2))

        # Save to DB and add plan_id
        plan_id = save_plan_db(db_path, user_query, parsed_plan)
        if plan_id:
            parsed_plan['plan_id'] = plan_id
            return parsed_plan
        else:
            print("Error: Failed to save plan to database.")
            # Even if saving fails, return the parsed plan but without an ID
            parsed_plan['plan_id'] = None
            return parsed_plan


    except json.JSONDecodeError as e:
        print(f"Error: Failed to parse JSON plan from LLM response: {e}")
        print(f"LLM Response was:\n---\n{plan_json_str}\n---")
        return {'plan_id': None}
    except ValueError as e:
        print(f"Error: Invalid plan structure: {e}")
        if parsed_plan: # Only print if parsing succeeded but validation failed
             print(f"Parsed Plan was:\n---\n{json.dumps(parsed_plan, indent=2)}\n---")
        return {'plan_id': None}
    except Exception as e:
        print(f"An unexpected error occurred during plan processing: {e}")
        print(f"LLM Response was:\n---\n{plan_json_str}\n---")
        return {'plan_id': None}
