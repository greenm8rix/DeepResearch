import sqlite3
import json
import logging
import time
from functools import lru_cache

def execute_db(db_path: str, query: str, params: tuple = (), fetch_one: bool = False, fetch_all: bool = False) -> any:
    """Executes an SQL query with error handling."""
    conn = None
    try:
        # Enable WAL mode for better concurrency and performance
        conn = sqlite3.connect(db_path, timeout=30.0)  # Increased timeout for busy DB
        conn.execute('PRAGMA journal_mode=WAL')  # WAL mode for better concurrency
        conn.execute('PRAGMA foreign_keys=ON')  # Enforce foreign key constraints
        
        cursor = conn.cursor()
        start_time = time.time()
        cursor.execute(query, params)
        
        # Only commit for non-SELECT queries
        if not query.strip().upper().startswith('SELECT'):
            conn.commit()
            
        if fetch_one:
            result = cursor.fetchone()
        elif fetch_all:
            result = cursor.fetchall()
        else:
            result = cursor.lastrowid
            
        query_time = time.time() - start_time
        if query_time > 0.5:  # Log slow queries
            logging.warning(f"Slow query ({query_time:.2f}s): {query[:100]}...")
            
        return result
    except sqlite3.Error as e:
        print(f"Database error: {e}")
        print(f"Query: {query[:200]} | Params: {str(params)[:200]}")
        return None
    finally:
        if conn:
            conn.close()

def init_db(db_path: str):
    """Initializes the database schema if tables don't exist."""
    print("--- Initializing Database ---")
    
    # Enable WAL mode and foreign keys for the connection
    conn = sqlite3.connect(db_path)
    conn.execute('PRAGMA journal_mode=WAL')  # Better concurrency and performance
    conn.execute('PRAGMA foreign_keys=ON')   # Enforce foreign key constraints
    
    # research_plans table with index on created_at for time-based queries
    conn.execute('''CREATE TABLE IF NOT EXISTS research_plans (
                    plan_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_query TEXT NOT NULL,
                    title TEXT,
                    research_questions TEXT,
                    sections TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )''')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_plans_created_at ON research_plans(created_at)')

    # Modify sources table with strategic indexes
    conn.execute('''CREATE TABLE IF NOT EXISTS sources (
                    paper_id TEXT PRIMARY KEY,
                    plan_id INTEGER NULL, -- Allow NULL for indexed papers
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
    
    # Add strategic indexes for common query patterns
    conn.execute('CREATE INDEX IF NOT EXISTS idx_sources_plan_id ON sources(plan_id)')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_sources_year ON sources(year)')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_sources_citation_count ON sources(citation_count)')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_sources_retrieved_at ON sources(retrieved_at)')

    # Modify findings table with explicit foreign key enforcement
    conn.execute('''CREATE TABLE IF NOT EXISTS findings (
                    finding_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    plan_id INTEGER NOT NULL,
                    subtopic TEXT NOT NULL,
                    paper_id TEXT NOT NULL, -- The ID of the paper the finding came from
                    finding_text TEXT,
                    source_type TEXT,
                    relevance_score INTEGER,
                    relevance_justification TEXT,
                    context_snippet TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (plan_id) REFERENCES research_plans(plan_id),
                    FOREIGN KEY (paper_id) REFERENCES sources(paper_id)
                )''')
    
    # Add strategic indexes for findings
    conn.execute('CREATE INDEX IF NOT EXISTS idx_findings_plan_id ON findings(plan_id)')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_findings_paper_id ON findings(paper_id)')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_findings_subtopic ON findings(subtopic)')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_findings_relevance ON findings(relevance_score)')

    # --- FTS5 Setup for faster searching ---
    # Create the FTS5 virtual table with enhanced options
    conn.execute('''CREATE VIRTUAL TABLE IF NOT EXISTS sources_fts USING fts5(
                    title,
                    abstract,
                    content='sources',
                    content_rowid='rowid',
                    tokenize='porter unicode61 remove_diacritics 2'
                )''')

    # Triggers to keep the FTS table synchronized with the sources table
    # After insert on sources
    conn.execute('''CREATE TRIGGER IF NOT EXISTS sources_ai AFTER INSERT ON sources BEGIN
                    INSERT INTO sources_fts (rowid, title, abstract)
                    VALUES (new.rowid, new.title, new.abstract);
                END;''')

    # Before delete on sources
    conn.execute('''CREATE TRIGGER IF NOT EXISTS sources_bd BEFORE DELETE ON sources BEGIN
                    INSERT INTO sources_fts (sources_fts, rowid, title, abstract)
                    VALUES ('delete', old.rowid, old.title, old.abstract);
                END;''')

    # Before update on sources
    conn.execute('''CREATE TRIGGER IF NOT EXISTS sources_bu BEFORE UPDATE ON sources BEGIN
                    INSERT INTO sources_fts (sources_fts, rowid, title, abstract)
                    VALUES ('delete', old.rowid, old.title, old.abstract);
                END;''')

    # After update on sources
    conn.execute('''CREATE TRIGGER IF NOT EXISTS sources_au AFTER UPDATE ON sources BEGIN
                    INSERT INTO sources_fts (rowid, title, abstract)
                    VALUES (new.rowid, new.title, new.abstract);
                END;''')
    
    # Commit changes and optimize the database
    conn.commit()
    conn.execute('PRAGMA optimize')
    conn.close()
    
    print("Database schema, indexes, and FTS5 setup initialized with WAL mode and foreign key enforcement.")


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
    """
    Saves paper metadata to the sources table. Uses INSERT OR IGNORE
    to avoid errors if the paper_id already exists.
    Accepts an optional plan_id for papers found during specific research runs.
    """
    paper_id = paper_metadata.get('paperId')
    # plan_id is now optional, can be None for background indexing
    plan_id = research_plan.get('plan_id') if research_plan else None

    if not paper_id:
        print(f"Warning: Missing paperId for saving source. Metadata: {paper_metadata.get('title')}")
        return

    # No need to check existence first, INSERT OR IGNORE handles it.
    # exists = execute_db(...)

    # Prepare data fields
    authors_list = [a.get('name') for a in paper_metadata.get('authors', []) if isinstance(a, dict) and a.get('name')]
    authors_json = json.dumps(authors_list)
    pub_types_json = json.dumps(paper_metadata.get('publicationTypes', []))
    journal_info = paper_metadata.get('journal') or {}
    pdf_info = paper_metadata.get('openAccessPdf') or {}

    # Use INSERT OR IGNORE to add the source only if paper_id doesn't exist
    execute_db(
        db_path,
        '''INSERT OR IGNORE INTO sources
           (paper_id, plan_id, title, authors, year, venue, citation_count,
            abstract, publication_types, journal_name, source_api, pdf_url)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
        (
            paper_id,
            plan_id, # Can be NULL now
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
    # We don't know if it was inserted or ignored, but the data should be there.
    # Optionally, could check cursor.rowcount if needed, but usually not necessary.

def save_web_source_db(db_path: str, research_plan: dict, source_id: str, url: str = None):
    """
    Saves a web search source to the sources table to maintain foreign key integrity.
    This is necessary before saving web search findings.
    
    Args:
        db_path: Path to the SQLite database
        research_plan: Dictionary containing the research plan information
        source_id: Unique ID for the web source (e.g., 'web_search_2025-05-04')
        url: Optional URL of the web source
    """
    plan_id = research_plan.get('plan_id')
    if not plan_id:
        print("Warning: Cannot save web source, plan_id not set.")
        return False
        
    if not source_id:
        print("Warning: Cannot save web source, source_id not provided.")
        return False
    
    # Check if the source already exists to avoid duplicate entries
    existing = execute_db(
        db_path,
        "SELECT 1 FROM sources WHERE paper_id = ?",
        (source_id,),
        fetch_one=True
    )
    
    if existing:
        # Source already exists, no need to insert
        return True
    
    # Current date for the title
    current_date = time.strftime("%Y-%m-%d")
    
    # Insert the web source into the sources table
    result = execute_db(
        db_path,
        '''INSERT OR IGNORE INTO sources
           (paper_id, plan_id, title, authors, year, venue, citation_count,
            abstract, publication_types, journal_name, source_api, pdf_url)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
        (
            source_id,
            plan_id,
            f"Web Search Results ({current_date})",
            json.dumps([{"name": "Web Search"}]),  # Authors as JSON
            int(current_date.split('-')[0]),  # Year
            "Web",  # Venue
            0,  # Citation count
            "Results from web search",  # Abstract
            json.dumps(["Web"]),  # Publication types as JSON
            "Web Search",  # Journal name
            "web_search",  # Source API
            url  # PDF URL (actually the web URL)
        )
    )
    
    return result is not None

# This is the correct definition of save_finding_db
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
        
    # For web search findings, ensure the source exists in the sources table first
    if finding_data.get('source_type') == 'web_search':
        # Extract URL from context_snippet if available
        url = finding_data.get('context_snippet')
        # Ensure the web source exists in the sources table
        if not save_web_source_db(db_path, research_plan, paper_id, url):
            print(f"Warning: Failed to save web source {paper_id} to database.")
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
