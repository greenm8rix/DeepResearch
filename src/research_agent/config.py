import os
from openai import OpenAI
LLM_RETRY_DELAY = 5
LLM_MAX_RETRIES = 2
SEMANTIC_SCHOLAR_API_KEY = os.getenv("SEMANTIC_SCHOLAR_API_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
SEMANTIC_SCHOLAR_API_URL = "https://api.semanticscholar.org/graph/v1"
SEMANTIC_SCHOLAR_API_KEY = os.getenv("SEMANTIC_SCHOLAR_API_KEY")
SQLITE_DB_FILE = "research_agent_data.db"
MAX_PAPERS_PER_QUERY = 10
MAX_SEARCH_QUERIES_PER_SUBTOPIC = 4
RELEVANCE_SCORE_THRESHOLD = 6
PDF_ANALYSIS_ENABLED = True
CONTEXT_WINDOW_SIZE = 16000
PDF_TEXT_EXTRACTION_LIMIT=2000
PDF_ANALYSIS_ENABLED = True
# Delay between API calls (e.g., in indexer or fallback)
API_CALL_DELAY = 5 # Seconds

client = OpenAI()
