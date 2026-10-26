"""Persistent memory — SQLite-backed conversation & knowledge storage"""

import os
import sqlite3
import threading
from typing import Optional

class ConversationMemory:
    """Persistent conversation memory for agents — reused SQLite connection"""

    def __init__(self, db_path: str = None):
        if db_path is None:
            db_path = os.path.join(os.path.dirname(__file__), "..", "agent_memory.db")
        self.db_path = db_path
        self._conn = None
        self._lock = threading.RLock()
        self._init_db()

    def _get_conn(self):
        if self._conn is None:
            # 多个 Agent / Orchestrator 各自持有连接，WAL 让读写不互斥
            self._conn = sqlite3.connect(self.db_path, check_same_thread=False, timeout=5)
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=NORMAL")
        return self._conn

    def _init_db(self):
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        conn = self._get_conn()
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS conversations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS idx_conv_session ON conversations(session_id, id);

            CREATE TABLE IF NOT EXISTS knowledge (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS agent_notes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                agent_name TEXT NOT NULL,
                note TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        conn.commit()

    def _close(self):
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def add_message(self, session_id: str, role: str, content: str):
        with self._lock:
            conn = self._get_conn()
            conn.execute(
                "INSERT INTO conversations (session_id, role, content) VALUES (?, ?, ?)",
                (session_id, role, content),
            )
            conn.commit()

    def get_history(self, session_id: str, limit: int = 30) -> list[dict]:
        rows = self._get_conn().execute(
            "SELECT role, content FROM conversations WHERE session_id = ? ORDER BY id DESC LIMIT ?",
            (session_id, limit),
        ).fetchall()
        return [{"role": r[0], "content": r[1]} for r in reversed(rows)]

    def remember(self, key: str, value: str):
        """Store a key-value knowledge"""
        with self._lock:
            conn = self._get_conn()
            conn.execute(
                "INSERT OR REPLACE INTO knowledge (key, value) VALUES (?, ?)",
                (key, value),
            )
            conn.commit()

    def recall(self, key: str) -> Optional[str]:
        """Retrieve knowledge by key"""
        row = self._get_conn().execute(
            "SELECT value FROM knowledge WHERE key = ?", (key,)
        ).fetchone()
        return row[0] if row else None

    def add_note(self, agent_name: str, note: str):
        """Agent can save a note for future reference"""
        with self._lock:
            conn = self._get_conn()
            conn.execute(
                "INSERT INTO agent_notes (agent_name, note) VALUES (?, ?)",
                (agent_name, note),
            )
            conn.commit()

    def get_notes(self, agent_name: str, limit: int = 10) -> list[str]:
        rows = self._get_conn().execute(
            "SELECT note FROM agent_notes WHERE agent_name = ? ORDER BY id DESC LIMIT ?",
            (agent_name, limit),
        ).fetchall()
        return [r[0] for r in rows]

    def clear_session(self, session_id: str):
        with self._lock:
            conn = self._get_conn()
            conn.execute("DELETE FROM conversations WHERE session_id = ?", (session_id,))
            conn.commit()


_memory_singleton: Optional[ConversationMemory] = None
_memory_singleton_lock = threading.Lock()


def get_memory() -> ConversationMemory:
    """全局共享一个记忆实例，避免多个连接争抢同一 SQLite 文件"""
    global _memory_singleton
    if _memory_singleton is None:
        with _memory_singleton_lock:
            if _memory_singleton is None:
                _memory_singleton = ConversationMemory()
    return _memory_singleton
