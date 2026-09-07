import json
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path


DEFAULT_STATE = {
    "selected_bank_ids": [], "current_keys": [], "remaining_keys": [],
    "answered_keys": [], "wrong_keys": [], "marked_keys": [],
    "question_index": 0, "wrong_answer_count": 0,
    "ai_cache": {}, "prompt_cache": {}, "total_tokens": 0,
}


def new_state():
    return json.loads(json.dumps(DEFAULT_STATE))


class QBankStore:
    """SQLite storage shared by every Gunicorn worker on one service instance."""

    def __init__(self, path):
        self.path = str(path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._init_lock = threading.Lock()
        self._initialize()

    @contextmanager
    def _connection(self):
        connection = sqlite3.connect(self.path, timeout=15)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout = 15000")
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def _initialize(self):
        with self._init_lock, self._connection() as db:
            db.execute("PRAGMA journal_mode = WAL")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS banks (
                    id TEXT PRIMARY KEY, owner TEXT NOT NULL, name TEXT NOT NULL,
                    questions TEXT NOT NULL, created_at INTEGER NOT NULL
                );
                CREATE INDEX IF NOT EXISTS banks_owner ON banks(owner, created_at);
                CREATE TABLE IF NOT EXISTS user_sessions (
                    sid TEXT PRIMARY KEY, state TEXT NOT NULL, api_key TEXT,
                    updated_at INTEGER NOT NULL
                );
            """)
            columns = {row["name"] for row in db.execute("PRAGMA table_info(user_sessions)")}
            if "ai_config" not in columns:
                db.execute("ALTER TABLE user_sessions ADD COLUMN ai_config TEXT")

    def ensure_session(self, sid):
        with self._connection() as db:
            db.execute(
                "INSERT OR IGNORE INTO user_sessions(sid, state, updated_at) VALUES (?, ?, ?)",
                (sid, json.dumps(new_state(), ensure_ascii=False), int(time.time())),
            )

    def get_state(self, sid):
        self.ensure_session(sid)
        with self._connection() as db:
            row = db.execute("SELECT state FROM user_sessions WHERE sid = ?", (sid,)).fetchone()
        state = new_state()
        state.update(json.loads(row["state"]))
        return state

    def save_state(self, sid, state):
        self.ensure_session(sid)
        with self._connection() as db:
            db.execute(
                "UPDATE user_sessions SET state = ?, updated_at = ? WHERE sid = ?",
                (json.dumps(state, ensure_ascii=False), int(time.time()), sid),
            )

    def set_api_key(self, sid, api_key):
        self.ensure_session(sid)
        config = ({"provider": "gemini", "model": "gemini-2.5-flash",
                   "api_key": api_key, "base_url": ""} if api_key else None)
        with self._connection() as db:
            db.execute(
                "UPDATE user_sessions SET api_key = ?, ai_config = ?, updated_at = ? WHERE sid = ?",
                (api_key or None, json.dumps(config, ensure_ascii=False) if config else None,
                 int(time.time()), sid),
            )

    def get_api_key(self, sid):
        self.ensure_session(sid)
        with self._connection() as db:
            row = db.execute("SELECT api_key FROM user_sessions WHERE sid = ?", (sid,)).fetchone()
        return row["api_key"] if row else None

    def set_ai_config(self, sid, config):
        self.ensure_session(sid)
        value = json.dumps(config, ensure_ascii=False) if config else None
        api_key = (config or {}).get("api_key") or None
        with self._connection() as db:
            db.execute(
                "UPDATE user_sessions SET ai_config = ?, api_key = ?, updated_at = ? WHERE sid = ?",
                (value, api_key, int(time.time()), sid),
            )

    def get_ai_config(self, sid):
        self.ensure_session(sid)
        with self._connection() as db:
            row = db.execute(
                "SELECT ai_config, api_key FROM user_sessions WHERE sid = ?", (sid,)
            ).fetchone()
        if row and row["ai_config"]:
            return json.loads(row["ai_config"])
        if row and row["api_key"]:
            return {"provider": "gemini", "model": "gemini-2.5-flash",
                    "api_key": row["api_key"], "base_url": ""}
        return None

    def create_bank(self, owner, name, questions, bank_id=None):
        bank_id = bank_id or uuid.uuid4().hex
        prepared = []
        for index, question in enumerate(questions):
            item = dict(question)
            item["_key"] = f"{bank_id}:{index}"
            item["_bank_id"] = bank_id
            prepared.append(item)
        with self._connection() as db:
            db.execute(
                "INSERT OR REPLACE INTO banks(id, owner, name, questions, created_at) VALUES (?, ?, ?, ?, ?)",
                (bank_id, owner, name, json.dumps(prepared, ensure_ascii=False), int(time.time())),
            )
        return bank_id

    def create_bank_unique(self, owner, name, questions):
        """Atomically insert unless an accessible bank already has the same name."""
        bank_id = uuid.uuid4().hex
        prepared = []
        for index, question in enumerate(questions):
            item = dict(question)
            item["_key"] = f"{bank_id}:{index}"
            item["_bank_id"] = bank_id
            prepared.append(item)
        with self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            names = db.execute(
                "SELECT name FROM banks WHERE owner IN (?, 'public')", (owner,)
            ).fetchall()
            if name.casefold() in {row["name"].casefold() for row in names}:
                return None
            db.execute(
                "INSERT INTO banks(id, owner, name, questions, created_at) VALUES (?, ?, ?, ?, ?)",
                (bank_id, owner, name, json.dumps(prepared, ensure_ascii=False), int(time.time())),
            )
        return bank_id

    def list_banks(self, owner):
        with self._connection() as db:
            rows = db.execute(
                "SELECT id, owner, name, questions FROM banks WHERE owner IN (?, 'public') ORDER BY created_at, name",
                (owner,),
            ).fetchall()
        result = []
        for row in rows:
            questions = json.loads(row["questions"])
            image_count = sum(bool(question.get("圖片")) for question in questions)
            result.append({"id": row["id"], "name": row["name"],
                           "question_count": len(questions), "image_count": image_count,
                           "has_images": image_count > 0, "deletable": row["owner"] == owner})
        return result

    def delete_bank(self, owner, bank_id):
        with self._connection() as db:
            cursor = db.execute("DELETE FROM banks WHERE id = ? AND owner = ?", (bank_id, owner))
        return cursor.rowcount > 0

    def get_banks(self, owner, bank_ids):
        if not bank_ids:
            return []
        placeholders = ",".join("?" for _ in bank_ids)
        with self._connection() as db:
            rows = db.execute(
                f"SELECT id, name, questions FROM banks WHERE id IN ({placeholders}) AND owner IN (?, 'public')",
                (*bank_ids, owner),
            ).fetchall()
        by_id = {row["id"]: row for row in rows}
        return [{"id": bank_id, "name": by_id[bank_id]["name"],
                 "questions": json.loads(by_id[bank_id]["questions"])}
                for bank_id in bank_ids if bank_id in by_id]

    def get_questions(self, owner, bank_ids):
        return [q for bank in self.get_banks(owner, bank_ids) for q in bank["questions"]]

    def get_question(self, owner, key):
        if not isinstance(key, str) or ":" not in key:
            return None
        bank_id, raw_index = key.rsplit(":", 1)
        try:
            index = int(raw_index)
        except ValueError:
            return None
        banks = self.get_banks(owner, [bank_id])
        if not banks or index < 0 or index >= len(banks[0]["questions"]):
            return None
        question = banks[0]["questions"][index]
        return question if question.get("_key") == key else None
