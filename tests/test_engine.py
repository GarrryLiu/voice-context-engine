import tempfile
import unittest
from pathlib import Path
from voice_context.engine import Engine, route


class EngineTests(unittest.TestCase):
    def setUp(self):
        self.e = Engine()
        self.e.fork("main")

    def tearDown(self):
        self.e.close()

    def add(self, eid="e1", branch="main", value="PostgreSQL"):
        return self.e.ingest(eid, branch, "s1", key="database", value=value)

    def test_retry_is_idempotent(self):
        self.assertTrue(self.add())
        self.assertFalse(self.add())
        self.assertEqual(self.e.drain(), 1)
        self.assertEqual(self.e.drain(), 0)
        self.assertEqual(self.e.recall("main")[0]["version"], 1)

    def test_conflicting_retry_rejected(self):
        self.add()
        with self.assertRaises(ValueError):
            self.add(value="Redis")

    def test_snapshot_and_branch_isolation(self):
        self.add(); self.e.drain(); self.e.fork("child", "main")
        self.add("e2", value="Redis"); self.add("e3", "child", "SQLite")
        self.e.drain()
        self.assertEqual(self.e.recall("main")[0]["value"], "Redis")
        self.assertEqual(self.e.recall("child")[0]["value"], "SQLite")
        self.assertEqual(self.e.db.execute("SELECT COUNT(*) FROM memory WHERE branch='child'").fetchone()[0], 2)

    def test_parent_future_not_visible(self):
        self.e.fork("child", "main"); self.add(); self.e.drain()
        self.assertEqual(self.e.recall("child"), [])

    def test_reopen_replays_pending_event(self):
        with tempfile.TemporaryDirectory() as d:
            path = str(Path(d) / "state.db")
            a = Engine(path); a.fork("main")
            a.ingest("e", "main", "session-1", key="decision", value="Keep history")
            a.close()
            b = Engine(path); self.assertEqual(b.drain(), 1); b.close()
            c = Engine(path)
            self.assertEqual(c.recall("main", "history")[0]["source"], "e")
            self.assertEqual(c.drain(), 0); c.close()

    def test_compaction_budget_and_source(self):
        self.add(); self.e.drain()
        self.assertEqual(self.e.compact("main", word_budget=1)["records"], [])
        self.assertEqual(self.e.compact("main", word_budget=2)["records"][0]["source"], "e1")

    def test_unknown_branch_rejected(self):
        import sqlite3
        with self.assertRaises(sqlite3.IntegrityError):
            self.add(branch="missing")

    def test_routing(self):
        self.assertEqual(route("respond").model, "realtime")
        self.assertEqual(route("extract").model, "small")
        self.assertEqual(route("merge").model, "reasoning")
        self.assertEqual(route("extract", complex=True).model, "reasoning")

if __name__ == "__main__":
    unittest.main()
