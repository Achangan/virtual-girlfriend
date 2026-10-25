"""记忆系统：SQLite 持久化对话历史、状态键值、长期记忆笔记。

MVP 版：短期上下文 = 最近 20 条；长期记忆 = 简单规则提取的笔记。
后续可换向量检索（Chroma）增强 notes 召回。
"""
import re
import sqlite3
import time

from config import DB_PATH

_SCHEMA = """
CREATE TABLE IF NOT EXISTS messages(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    emotion TEXT DEFAULT '',
    ts REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS kv(key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS notes(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    content TEXT NOT NULL,
    ts REAL NOT NULL
);
"""

# 从用户话语中提取值得记住的事实
_NOTE_PATTERNS = [
    (re.compile(r"我叫([^\s，。,.]{1,12})"), "用户叫{}"),
    (re.compile(r"我喜欢(.{1,20})"), "用户喜欢{}"),
    (re.compile(r"我讨厌(.{1,20})"), "用户讨厌{}"),
]


class MemoryStore:
    def __init__(self, path=DB_PATH):
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.executescript(_SCHEMA)

    def add_message(self, role: str, content: str, emotion: str = ""):
        self.conn.execute(
            "INSERT INTO messages(role, content, emotion, ts) VALUES(?,?,?,?)",
            (role, content, emotion, time.time()),
        )
        self.conn.commit()

    def recent(self, limit: int = 20) -> list[dict]:
        rows = self.conn.execute(
            "SELECT role, content FROM messages ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [{"role": r, "content": c} for r, c in reversed(rows)]

    def get(self, key: str, default=None):
        row = self.conn.execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
        return row[0] if row else default

    def set(self, key: str, value: str):
        self.conn.execute(
            "INSERT INTO kv(key, value) VALUES(?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )
        self.conn.commit()

    def add_note(self, content: str):
        self.conn.execute("INSERT INTO notes(content, ts) VALUES(?,?)", (content, time.time()))
        self.conn.commit()

    def notes(self, limit: int = 10) -> list[str]:
        rows = self.conn.execute(
            "SELECT content FROM notes ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [r[0] for r in rows]

    def extract_notes(self, user_text: str):
        """从用户输入中抽取长期记忆（如名字、喜好）。"""
        for pattern, tpl in _NOTE_PATTERNS:
            m = pattern.search(user_text)
            if m:
                self.add_note(tpl.format(m.group(1)))
