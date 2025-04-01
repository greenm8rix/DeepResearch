import sqlite3
import json

def execute_db(db_path: str, query: str, params: tuple = (), fetch_one: bool = False, fetch_all: bool = False) -> any:
    """Executes an SQL query with error handling."""
    conn = None
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute(query, params)
        conn.commit()
        if fetch_one:
            return cursor.fetchone()
        if fetch_all:
            return cursor.fetchall()
        return cursor.lastrowid
    except sqlite3.Error as e:
        print(f"Database error: {e}")
        print(f"Query: {query} | Params: {params}")
        return None
    finally:
        if conn:
            conn.close()

def init_db(db_path: str):
    """Initializes the database schema if tables don't exist."""
    print("--- Initializing Database ---")
    execute_db(db_path, '''CREATE TABLE IF NOT EXISTS research_plans (
                                plan_id INTEGER PRIMARY KEY AUTOINCREMENT,
                                user_query TEXT NOT NULL,
                                title TEXT,
                                research_questions TEXT,
                                sections TEXT,
                                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                            )''')

    execute_db(db_path, '''CREATE TABLE IF NOT EXISTS sources (
                                paper_id TEXT PRIMARY KEY,
                                plan_id INTEGER,
                                title TEXT,
                                authors TEXT,
                                year INTEGER,
                                venue TEXT,
                                citation_count INTEGER,
                                abstract TEXT,
                                publication_types TEXT,
                                journal_name TEXT,
                                source_api TEXT,
                                pdf_url TEXT,
                                retrieved_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                                FOREIGN KEY(plan_id) REFERENCES research_plans(plan_id)
                            )''')

    execute_db(db_path, '''CREATE TABLE IF NOT EXISTS findings (
                                finding_id INTEGER PRIMARY KEY AUTOINCREMENT,
                                plan_id INTEGER,
                                subtopic TEXT NOT NULL,
                                paper_id TEXT NOT NULL,
                                finding_text TEXT,
                                source_type TEXT,
                                relevance_score INTEGER,
                                relevance_justification TEXT,
                                context_snippet TEXT,
                                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                                FOREIGN KEY (plan_id) REFERENCES research_plans(plan_id),
                                FOREIGN KEY (paper_id) REFERENCES sources(paper_id)
                            )''')
    print("Database schema checked/initialized.")

def save_plan_db(db_path: str, current_query: str, research_plan: dict) -> any:
    """Saves the current research plan to the database."""
    if not research_plan or 'title' not in research_plan:
        print("Warning: Attempted to save an empty or invalid plan.")
        return None

    plan_id = execute_db(
        db_path,
        '''INSERT INTO research_plans
           (user_query, title, research_questions, sections)
           VALUES (?, ?, ?, ?)''',
        (
            current_query,
            research_plan.get('title'),
            json.dumps(research_plan.get('research_questions', [])),
            json.dumps(research_plan.get('sections', []))
        )
    )
    if plan_id:
        research_plan['plan_id'] = plan_id
        print(f"Research plan saved to DB with ID: {plan_id}")
    else:
        print("Error: Failed to save research plan to DB.")
        research_plan['plan_id'] = None
    return plan_id

def save_source_db(db_path: str, research_plan: dict, paper_metadata: dict, source_api: str):
    """Saves paper metadata to the sources table if it doesn't exist."""
    paper_id = paper_metadata.get('paperId')
    plan_id = research_plan.get('plan_id')

    if not paper_id or not plan_id:
        print(f"Warning: Missing paperId ('{paper_id}') or plan_id ('{plan_id}') for saving source.")
        return

    exists = execute_db(
        db_path,
        "SELECT 1 FROM sources WHERE paper_id = ? AND plan_id = ?",
        (paper_id, plan_id),
        fetch_one=True
    )

    if not exists:
        authors_list = [a.get('name') for a in paper_metadata.get('authors', []) if a.get('name')]
        authors_json = json.dumps(authors_list)
        pub_types_json = json.dumps(paper_metadata.get('publicationTypes', []))
        journal_info = paper_metadata.get('journal') or {}
        pdf_info = paper_metadata.get('openAccessPdf') or {}

        execute_db(
            db_path,
            '''INSERT INTO sources
               (paper_id, plan_id, title, authors, year, venue, citation_count,
                abstract, publication_types, journal_name, source_api, pdf_url)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
            (
                paper_id,
                plan_id,
                paper_metadata.get('title'),
                authors_json,
                paper_metadata.get('year'),
                paper_metadata.get('venue'),
                paper_metadata.get('citationCount'),
                paper_metadata.get('abstract'),
                pub_types_json,
                journal_info.get('name'),
                source_api,
                pdf_info.get('url')
            )
        )

def save_finding_db(db_path: str, research_plan: dict, subtopic: str, finding_data: dict):
    """Saves an extracted finding to the findings table."""
    plan_id = research_plan.get('plan_id')
    paper_id = finding_data.get('paperId')

    if not plan_id:
        print("Warning: Cannot save finding, plan_id not set.")
        return
    if not paper_id:
        print("Warning: Cannot save finding, paperId not set in finding_data.")
        return

    execute_db(
        db_path,
        '''INSERT INTO findings
           (plan_id, subtopic, paper_id, finding_text, source_type,
            relevance_score, relevance_justification, context_snippet)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
        (
            plan_id,
            subtopic,
            paper_id,
            finding_data.get('finding'),
            finding_data.get('source_type'),
            finding_data.get('relevance_score'),
            finding_data.get('justification'),
            finding_data.get('context_snippet')
        )
    )
