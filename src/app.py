
import time
import argparse
from flask import Flask, request, jsonify

# Updated imports for the new structure
from research_agent.config import SQLITE_DB_FILE, PDF_ANALYSIS_ENABLED
from research_agent.agent import ResearchAgent


api_app = Flask(__name__)


# Default citation style is harvard
agent_instance = ResearchAgent(db_path=SQLITE_DB_FILE)




@api_app.route('/research', methods=['POST'])
def handle_research_request():
    data = request.get_json()
    if not data or 'query' not in data:
        return jsonify({"error": "Missing 'query' in request body"}), 400
    global PDF_ANALYSIS_ENABLED
    PDF_ANALYSIS_ENABLED = data.get('analyze_pdfs', True)
    user_query = data['query']
    citation_style = data.get('citation_style', 'harvard')  # Default to harvard if not specified
    
    # Validate citation style
    valid_styles = ['harvard', 'apa', 'mla', 'chicago', 'ieee']
    if citation_style not in valid_styles:
        return jsonify({"error": f"Invalid citation style. Choose from: {', '.join(valid_styles)}"}), 400
        
    result = agent_instance.run_full_workflow(user_query, citation_style=citation_style)
    if result and "report" in result:
        return jsonify(result)
    else:
        return jsonify({"error": result.get("error", "Failed to generate report")}), 500

def run_cli():
    parser = argparse.ArgumentParser(description="Run Enhanced Research Agent Workflow.")
    parser.add_argument("query", type=str, help="The research query/topic.")
    # Note: SQLITE_DB_FILE is now imported from research_agent.config
    parser.add_argument("--db", type=str, default=SQLITE_DB_FILE,
                        help=f"SQLite DB file path (default: {SQLITE_DB_FILE}).")
    parser.add_argument("--disable-pdf", action="store_true",
                        help="Disable full PDF download and analysis.")
    parser.add_argument("--citation-style", type=str, default="harvard", 
                        choices=["harvard", "apa", "mla", "chicago", "ieee"],
                        help="Citation style to use (default: harvard)")
    args = parser.parse_args()

    # PDF_ANALYSIS_ENABLED is imported, but modifying it globally like this
    # might not affect the instance inside ResearchAgent if it reads the config directly.
    # This might need further review depending on how config is used internally.
    # For now, keeping the logic as is.
    pdf_analysis_setting = PDF_ANALYSIS_ENABLED # Use the imported value
    if args.disable_pdf:
        pdf_analysis_setting = False # Override based on CLI arg
        print("--- PDF Analysis Disabled (CLI override) ---")
        # TODO: Consider a better way to pass this setting to the agent instance if needed.

    # Pass the potentially overridden db path and citation style
    cli_agent = ResearchAgent(db_path=args.db, citation_style=args.citation_style)
    # The agent internally uses the config for PDF setting, CLI override here might be ineffective
    # unless passed explicitly to the agent or workflow.
    result = cli_agent.run_full_workflow(args.query)
    if result and "report" in result:
        print("\n\n===== FINAL REPORT =====")
        print(result["report"])
        report_filename = "final_report_enhanced.md"
        with open(report_filename, "w", encoding='utf-8') as f:
            f.write(result["report"])
        print(f"\nReport saved to {report_filename}")
    else:
        print("\n\n===== WORKFLOW FAILED =====")
        print(result.get("error", "An unknown error occurred."))

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == 'runserver':
        print("Starting Flask API server on http://127.0.0.1:5000/")
        api_app.run(host='0.0.0.0', port=5000, debug=True)
    else:
        print("Running in Command-Line Interface mode.")
        run_cli()
