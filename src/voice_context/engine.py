"""Durable event ingestion and branch-aware context, backed by SQLite.

Ingestion and materialization are separate transactions. Event IDs are global
idempotency keys. Forks snapshot the parent's visible memory at fork time.
"""
import json
import re
import sqlite3
from dataclasses import dataclass


def tokens(text):
    return set(re.findall(r"\w+", text.lower()))


@dataclass(frozen=True)
class Route:
    model: str
    reason: str


def route(task, *, complex=False):
    if task == "respond":
        return Route("realtime", "interactive latency budget")
    if task in {"merge", "resolve_conflict"} or complex:
        return Route("reasoning", "requires reconciliation")
    return Route("small", "bounded background extraction")


class Engine:
    def __init__(self, path=":memory:"):
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS branches (
          id TEXT PRIMARY KEY, parent TEXT REFERENCES branches(id));
        CREATE TABLE IF NOT EXISTS events (
          seq INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT UNIQUE NOT NULL,
          branch TEXT NOT NULL REFERENCES branches(id), session TEXT NOT NULL,
          payload TEXT NOT NULL, processed INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS memory (
          branch TEXT NOT NULL REFERENCES branches(id), key TEXT NOT NULL,
          version INTEGER NOT NULL, value TEXT NOT NULL, source TEXT NOT NULL,
          PRIMARY KEY(branch,key,version));
        ''')

    def close(self):
        self.db.close()

    def fork(self, branch, parent=None):
        with self.db:
            self.db.execute("INSERT INTO branches VALUES (?,?)", (branch, parent))
            if parent:
                self.db.execute('''INSERT INTO memory
                  SELECT ?,key,version,value,source FROM memory WHERE branch=?''',
                  (branch, parent))

    def ingest(self, event_id, branch, session, *, key, value):
        if not all(isinstance(x, str) and x.strip() for x in
                   (event_id, branch, session, key, value)):
            raise ValueError("all fields must be nonempty strings")
        payload = json.dumps({"key": key, "value": value}, sort_keys=True)
        with self.db:
            old = self.db.execute("SELECT * FROM events WHERE id=?", (event_id,)).fetchone()
            if old:
                if (old["branch"], old["session"], old["payload"]) != (branch, session, payload):
                    raise ValueError("idempotency key reused with different content")
                return False
            self.db.execute("INSERT INTO events(id,branch,session,payload) VALUES (?,?,?,?)",
                            (event_id, branch, session, payload))
        return True

    def process_one(self):
        # Serialize claiming and applying: rollback leaves event available for retry.
        with self.db:
            self.db.execute("BEGIN IMMEDIATE")
            event = self.db.execute("SELECT * FROM events WHERE processed=0 ORDER BY seq LIMIT 1").fetchone()
            if not event:
                return False
            payload = json.loads(event["payload"])
            version = self.db.execute("SELECT COALESCE(MAX(version),0)+1 FROM memory WHERE branch=? AND key=?",
                                      (event["branch"], payload["key"])).fetchone()[0]
            self.db.execute("INSERT INTO memory VALUES (?,?,?,?,?)",
                            (event["branch"], payload["key"], version, payload["value"], event["id"]))
            self.db.execute("UPDATE events SET processed=1 WHERE id=?", (event["id"],))
        return True

    def drain(self):
        count = 0
        while self.process_one():
            count += 1
        return count

    def recall(self, branch, query="", limit=10):
        rows = self.db.execute('''SELECT m.* FROM memory m JOIN
          (SELECT key,MAX(version) v FROM memory WHERE branch=? GROUP BY key) latest
          ON m.key=latest.key AND m.version=latest.v WHERE m.branch=? ORDER BY m.key''',
          (branch, branch)).fetchall()
        terms = tokens(query)
        ranked = []
        for row in rows:
            item = dict(row)
            item["score"] = len(terms & tokens(item["key"] + " " + item["value"]))
            if not terms or item["score"]:
                ranked.append(item)
        return sorted(ranked, key=lambda x: (-x["score"], x["key"]))[:limit]

    def compact(self, branch, query="", word_budget=128):
        """Deterministic whole-record packing; retains provenance, skips oversize records."""
        if word_budget < 0:
            raise ValueError("word_budget must be nonnegative")
        selected, used = [], 0
        for item in self.recall(branch, query, limit=10000):
            size = len((item["key"] + " " + item["value"]).split())
            if used + size <= word_budget:
                selected.append(item)
                used += size
        return {"records": selected, "words": used, "budget": word_budget}
