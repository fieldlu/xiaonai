"""SQLite database engine - WAL mode, connection pool, schema init."""

import sqlite3
import os
import threading
from pathlib import Path

DATA_DIR = Path(os.environ.get("QQBOT_DATA_DIR", "data"))
DB_PATH = DATA_DIR / "memory" / "xiaonai.db"


def _pragma(conn: sqlite3.Connection) -> None:
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA busy_timeout=5000")


class Database:
    """Thread-safe SQLite connection manager."""

    def __init__(self):
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()

    @property
    def conn(self) -> sqlite3.Connection:
        if not hasattr(self._local, "conn") or self._local.conn is None:
            c = sqlite3.connect(str(DB_PATH))
            _pragma(c)
            c.row_factory = sqlite3.Row
            self._local.conn = c
        return self._local.conn

    def execute(self, sql: str, params=()):
        try:
            return self.conn.execute(sql, params)
        except sqlite3.InterfaceError:
            self._local.conn = sqlite3.connect(str(DB_PATH))
            _pragma(self._local.conn)
            self._local.conn.row_factory = sqlite3.Row
            return self._local.conn.execute(sql, params)

    def commit(self):
        self.conn.commit()


db = Database()


def init_db() -> None:
    """Create all tables. Idempotent."""
    db.execute("""
        CREATE TABLE IF NOT EXISTS short_term (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            fact TEXT NOT NULL,
            category TEXT DEFAULT 'general',
            importance INTEGER DEFAULT 1 CHECK(importance BETWEEN 1 AND 5),
            source_msg_id TEXT DEFAULT '',
            created_at TEXT NOT NULL,
            last_recalled TEXT,
            recall_count INTEGER DEFAULT 0
        )
    """)
    db.execute("""
        CREATE TABLE IF NOT EXISTS long_term (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            fact TEXT NOT NULL,
            category TEXT DEFAULT 'general',
            importance INTEGER DEFAULT 3 CHECK(importance BETWEEN 1 AND 5),
            verified_at TEXT,
            source TEXT DEFAULT 'conversation'
                CHECK(source IN ('conversation','declared','inferred','search','admin')),
            related_facts TEXT DEFAULT '[]',
            created_at TEXT NOT NULL,
            last_recalled TEXT,
            recall_count INTEGER DEFAULT 0
        )
    """)
    db.execute("""
        CREATE TABLE IF NOT EXISTS global_kb (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            topic TEXT NOT NULL,
            knowledge TEXT NOT NULL,
            confidence REAL DEFAULT 0.5 CHECK(confidence BETWEEN 0 AND 1),
            sources TEXT DEFAULT '[]',
            evidence_count INTEGER DEFAULT 1,
            contradictions TEXT DEFAULT '[]',
            last_updated TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)
    # FTS5 virtual tables (standalone, content stored in FTS index itself)
    db.execute(
        "CREATE VIRTUAL TABLE IF NOT EXISTS st_fts USING fts5(fact, tokenize='unicode61')"
    )
    db.execute(
        "CREATE VIRTUAL TABLE IF NOT EXISTS lt_fts USING fts5(fact, tokenize='unicode61')"
    )
    db.execute(
        "CREATE VIRTUAL TABLE IF NOT EXISTS gkb_fts USING fts5(topic, knowledge, tokenize='unicode61')"
    )
    db.execute("""
        CREATE TABLE IF NOT EXISTS search_cache (
            cache_key TEXT PRIMARY KEY,
            results TEXT,
            cached_at TEXT
        )
    """)
    db.execute("""
        CREATE TABLE IF NOT EXISTS user_profiles (
            user_id INTEGER PRIMARY KEY,
            nickname TEXT DEFAULT '',
            knowledge_level TEXT DEFAULT 'intermediate'
                CHECK(knowledge_level IN ('beginner','intermediate','advanced')),
            comm_style TEXT DEFAULT 'casual_short'
                CHECK(comm_style IN ('casual_short','formal','technical')),
            interest_tags TEXT DEFAULT '[]',
            kb_gaps TEXT DEFAULT '[]',
            last_profiled TEXT,
            total_messages INTEGER DEFAULT 0
        )
    """)
    db.commit()
