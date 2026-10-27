"""SQLite leased queue; handlers must make external effects idempotent."""
import json
import sqlite3
import time
import uuid


class LeaseLost(RuntimeError):
    pass


class TaskQueue:
    def __init__(self, path=":memory:", clock=time.time):
        self.clock = clock
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.execute('''CREATE TABLE IF NOT EXISTS tasks (
          seq INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT UNIQUE NOT NULL,
          kind TEXT NOT NULL, payload TEXT NOT NULL, state TEXT NOT NULL,
          attempts INTEGER NOT NULL, max_attempts INTEGER NOT NULL,
          available REAL NOT NULL, lease_until REAL, lease_token TEXT,
          result TEXT, error TEXT)''')
        self.db.commit()

    def close(self):
        self.db.close()

    def enqueue(self, task_id, kind, payload, max_attempts=3):
        if not task_id or not kind or max_attempts < 1:
            raise ValueError("task id, kind and positive attempts required")
        encoded = json.dumps(payload, sort_keys=True)
        with self.db:
            self.db.execute("BEGIN IMMEDIATE")
            existing = self.db.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
            if existing:
                if (existing['kind'], existing['payload'], existing['max_attempts']) != (kind, encoded, max_attempts):
                    raise ValueError("task id reused with different request")
                return False
            self.db.execute('''INSERT INTO tasks
              (id,kind,payload,state,attempts,max_attempts,available)
              VALUES (?,?,?,'pending',0,?,?)''', (task_id, kind, encoded, max_attempts, self.clock()))
        return True

    def get(self, task_id):
        row = self.db.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
        if not row:
            raise KeyError(task_id)
        result = dict(row)
        for key in ('payload', 'result'):
            if result[key] is not None:
                result[key] = json.loads(result[key])
        return result

    def claim(self, lease_seconds=60):
        if lease_seconds <= 0:
            raise ValueError("lease must be positive")
        now = self.clock()
        with self.db:
            self.db.execute("BEGIN IMMEDIATE")
            self.db.execute('''UPDATE tasks SET state=CASE WHEN attempts>=max_attempts THEN 'dead' ELSE 'pending' END,
              lease_token=NULL,lease_until=NULL,error='worker lease expired'
              WHERE state='running' AND lease_until<=?''', (now,))
            row = self.db.execute("SELECT id FROM tasks WHERE state='pending' AND available<=? ORDER BY seq LIMIT 1", (now,)).fetchone()
            if not row:
                return None
            self.db.execute("UPDATE tasks SET state='running',attempts=attempts+1,lease_until=?,lease_token=? WHERE id=?",
                            (now + lease_seconds, uuid.uuid4().hex, row['id']))
        return self.get(row['id'])

    def _finish(self, task_id, lease_token, result=None, error=None, backoff=1):
        if backoff < 0:
            raise ValueError("backoff must be nonnegative")
        with self.db:
            self.db.execute("BEGIN IMMEDIATE")
            row = self.get(task_id)
            if row['state'] != 'running' or row['lease_token'] != lease_token or row['lease_until'] <= self.clock():
                raise LeaseLost("worker no longer owns this task")
            state = 'succeeded' if error is None else ('dead' if row['attempts'] >= row['max_attempts'] else 'pending')
            available = self.clock() + backoff * 2 ** (row['attempts'] - 1)
            self.db.execute('''UPDATE tasks SET state=?,result=?,error=?,available=?,lease_token=NULL,lease_until=NULL WHERE id=?''',
                            (state, json.dumps(result), error, available, task_id))

    def complete(self, task_id, lease_token, result):
        self._finish(task_id, lease_token, result=result)

    def fail(self, task_id, lease_token, error, backoff=1):
        self._finish(task_id, lease_token, error=str(error), backoff=backoff)

    def cancel(self, task_id):
        with self.db:
            cursor = self.db.execute("UPDATE tasks SET state='cancelled',lease_token=NULL,lease_until=NULL WHERE id=? AND state IN ('pending','running')", (task_id,))
        return cursor.rowcount == 1

    def run_once(self, handler, lease_seconds=60):
        task = self.claim(lease_seconds)
        if task is None:
            return False
        try:
            result = handler(task)
        except Exception as exc:
            self.fail(task['id'], task['lease_token'], type(exc).__name__)
        else:
            self.complete(task['id'], task['lease_token'], result)
        return True
