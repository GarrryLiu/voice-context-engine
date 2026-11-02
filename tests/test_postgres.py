"""Real database contract tests; enabled explicitly with VOICE_TEST_POSTGRES."""
import os
import threading
import unittest
import uuid
from unittest.mock import patch
from voice_context.gateway import Pipeline
from voice_context.storage import Postgres


@unittest.skipUnless(os.environ.get('VOICE_TEST_POSTGRES'), 'requires real PostgreSQL')
class PostgresTests(unittest.TestCase):
    def setUp(self):
        import psycopg
        from psycopg import sql
        self.dsn = os.environ['VOICE_TEST_POSTGRES']
        self.schema = 'test_' + uuid.uuid4().hex
        with psycopg.connect(self.dsn, autocommit=True) as db:
            db.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(self.schema)))
        self.scoped = self.dsn + ('&' if '?' in self.dsn else '?') + 'options=-csearch_path%3D' + self.schema
        self.p = Pipeline(self.scoped)
        self.p.engine.fork('main')

    def tearDown(self):
        import psycopg
        from psycopg import sql
        self.p.close()
        with psycopg.connect(self.dsn, autocommit=True) as db:
            db.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(self.schema)))

    def test_atomic_final_outbox_restart_and_versions(self):
        with patch.object(self.p.queue, 'enqueue', side_effect=RuntimeError('offline')):
            with self.assertRaises(RuntimeError):
                self.p.submit('a', 'main', 's', 'remember db: PostgreSQL')
        self.assertIn('PostgreSQL', self.p.transcripts.context('main')['text'])
        self.p.close(); self.p = Pipeline(self.scoped)
        self.assertTrue(self.p.work_once())
        self.assertFalse(self.p.work_once())
        self.assertEqual(self.p.approve('transcript:a', ['db'])['inserted'], 1)
        self.p.submit('b', 'main', 's', 'remember db: Redis')
        self.p.work_once()
        self.p.correct('fix', 'main', 's', 'db', 'Kafka', 1)
        with self.assertRaises(ValueError):self.p.approve('transcript:b', ['db'])
        self.p.engine.fork('child', 'main')
        self.assertEqual(self.p.engine.recall('child')[0]['value'], 'Kafka')

    def test_transaction_rollback_and_epoch_fencing(self):
        self.p.sessions.open('s')
        ticket = self.p.sessions.begin('s', 'r')
        self.p.sessions.reserve(ticket, 'c', 'reason', 2)
        self.p.sessions.finish('c', reported=1)
        self.p.sessions.segment(ticket, 0, 'hello')
        with self.assertRaises(RuntimeError):
            with self.p.engine.db:
                self.p.transcripts.append_in_transaction('rolled', 'main', 's', 'rollback')
                raise RuntimeError('crash')
        self.assertEqual(self.p.transcripts.recent('main'), [])
        other = Pipeline(self.scoped)
        try:other.sessions.interrupt('s')
        finally:other.close()
        self.assertFalse(self.p.sessions.valid(ticket))
        self.assertEqual(self.p.sessions.get('s')['spent'], 2)

    def test_two_workers_cannot_claim_same_task(self):
        self.p.submit('a', 'main', 's', 'remember db: pg')
        barrier = threading.Barrier(2); claimed = []; errors = []
        def worker():
            try:
                p = Pipeline(self.scoped)
                try:barrier.wait(timeout=5); claimed.append(p.queue.claim())
                finally:p.close()
            except Exception as e:errors.append(str(e))
        threads = [threading.Thread(target=worker) for _ in range(2)]
        for t in threads:t.start()
        for t in threads:t.join(10)
        self.assertFalse(any(t.is_alive() for t in threads))
        self.assertEqual(errors, [])
        self.assertEqual(sum(x is not None for x in claimed), 1)
