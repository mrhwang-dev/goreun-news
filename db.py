import sqlite3
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DB_PATH = ROOT / "data" / "goreun.db"

def get_connection() -> sqlite3.Connection:
    # Ensure data directory exists
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=10.0)
    # Return rows as dictionaries for easier usage
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_connection() as conn:
        # cache table (summarize.py)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS cache (
                section TEXT NOT NULL,
                k TEXT NOT NULL,
                v TEXT NOT NULL,
                t REAL NOT NULL,
                PRIMARY KEY (section, k)
            )
        """)
        # bias_state table (run.py)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS bias_state (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        """)
        # community_seen table (fetch_community.py)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS community_seen (
                url TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        """)
        # embedding_cache table (embed.py) — 제목 해시 → 임베딩 벡터(JSON)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS embedding_cache (
                k TEXT PRIMARY KEY,
                v TEXT NOT NULL
            )
        """)
        conn.commit()

# DB 초기화
init_db()
