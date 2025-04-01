
import time
import argparse
from flask import Flask, request, jsonify

from config import SQLITE_DB_FILE, PDF_ANALYSIS_ENABLED
from Agent import ResearchAgent


api_app = Flask(__name__)


agent_instance = ResearchAgent(db_path=SQLITE_DB_FILE)




@api_app.route('/research', methods=['POST'])
def handle_research_request():
    data = request.get_json()
    if not data or 'query' not in data:
        return jsonify({"error": "Missing 'query' in request body"}), 400
    global PDF_ANALYSIS_ENABLED
    PDF_ANALYSIS_ENABLED = data.get('analyze_pdfs', True)
    user_query = data['query']
    result = agent_instance.run_full_workflow(user_query)
    if result and "report" in result:
        return jsonify(result)
    else:
        return jsonify({"error": result.get("error", "Failed to generate report")}), 500

def run_cli():
    parser = argparse.ArgumentParser(description="Run Enhanced Research Agent Workflow.")
    parser.add_argument("query", type=str, help="The research query/topic.")
    parser.add_argument("--db", type=str, default=SQLITE_DB_FILE,
                        help=f"SQLite DB file path (default: {SQLITE_DB_FILE}).")
    parser.add_argument("--disable-pdf", action="store_true",
                        help="Disable full PDF download and analysis.")
    args = parser.parse_args()
    global PDF_ANALYSIS_ENABLED
    if args.disable_pdf:
        PDF_ANALYSIS_ENABLED = False
        print("--- PDF Analysis Disabled ---")
    cli_agent = ResearchAgent(db_path=args.db)
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
