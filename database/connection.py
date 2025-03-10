import sqlite3
import config

def get_db_connection():
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS downloads (
        id TEXT PRIMARY KEY,
        url TEXT NOT NULL,
        format_id TEXT NOT NULL,
        quality TEXT,
        status TEXT NOT NULL,
        progress REAL DEFAULT 0,
        eta REAL,
        speed REAL,
        downloaded_bytes INTEGER,
        total_bytes INTEGER,
        filename TEXT,
        error_message TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    ''')
    
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS cache (
        url TEXT PRIMARY KEY,
        data TEXT NOT NULL,
        timestamp REAL NOT NULL
    )
    ''')
    
    conn.commit()
    conn.close()