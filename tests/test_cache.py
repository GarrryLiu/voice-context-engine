import os
import unittest
import test_postgres as pg
from voice_context.gateway import Pipeline


@unittest.skipUnless(os.environ.get('VOICE_TEST_REDIS') and os.environ.get('VOICE_TEST_POSTGRES'), 'requires Redis and PostgreSQL')
class CacheTests(pg.PostgresTests):
    test_atomic_final_outbox_restart_and_versions = None
    test_transaction_rollback_and_epoch_fencing = None
    test_two_workers_cannot_claim_same_task = None
    test_real_native_conversation_uses_postgres_and_cache = None

    def setUp(self):
        super().setUp()
        self.p.close()
        self.p = Pipeline(self.scoped, redis_url=os.environ['VOICE_TEST_REDIS'])

    def test_immediate_context_cross_connection_revision_and_cache_loss(self):
        first = self.p.context(branch='main')
        self.assertEqual(first, self.p.context(branch='main'))
        self.assertEqual(self.p.context_cache.hits, 1)
        other = Pipeline(self.scoped)
        try:other.submit('a', 'main', 's', 'remember choice: new decision')
        finally:other.close()
        result = self.p.context(branch='main')
        self.assertIn('new decision', result['text'])
        self.assertNotEqual(first['revision'], result['revision'])
        # Delete only this isolated test workspace's keys, never flush shared Redis.
        namespace = self.p.engine.db.execute('SELECT namespace FROM workspace_revision').fetchone()[0]
        keys = list(self.p.context_cache.redis.scan_iter(match=f'voice:context:{namespace}:*'))
        self.assertTrue(keys)
        self.p.context_cache.redis.delete(*keys)
        self.assertEqual(result, self.p.context(branch='main'))
        other = Pipeline(self.scoped)
        try:other.transcripts.revoke('a')
        finally:other.close()
        self.assertEqual(self.p.context(branch='main')['recent'], [])

    def test_redis_unavailable_falls_back_and_custom_counter_bypasses(self):
        from unittest.mock import patch
        import redis
        self.p.submit('a', 'main', 's', 'hello')
        with patch.object(self.p.context_cache.redis, 'get', side_effect=redis.ConnectionError('offline')), patch.object(self.p.context_cache.redis, 'set', side_effect=redis.ConnectionError('offline')):
            self.assertIn('hello', self.p.context(branch='main')['text'])
        self.assertEqual(self.p.context_cache.failures, 2)
        hits = self.p.context_cache.hits
        self.assertEqual(self.p.context(branch='main', count=lambda s:len(s.split()))['counter'], 'caller_supplied')
        self.assertEqual(self.p.context_cache.hits, hits)

    def test_acknowledged_reply_and_memory_updates_invalidate(self):
        self.p.sessions.open('s')
        self.p.context(branch='main')
        self.p.correct('c', 'main', 's', 'db', 'PostgreSQL', 0)
        self.assertIn('PostgreSQL', self.p.context(branch='main')['text'])
        ticket = self.p.sessions.begin('s', 'r')
        self.p.sessions.segment(ticket, 0, 'acknowledged answer')
        self.p.sessions.reserve(ticket, 'r:tts:0', 'tts', 0)
        self.p.sessions.finish('r:tts:0')
        with self.p.engine.db:
            self.p.engine.db.execute('INSERT INTO output_chunks(reply,sequence,segment,bytes,sha256,rendered) VALUES (?,?,?,?,?,?)', ('r',0,0,3,'fixture',3))
        self.assertEqual(self.p.context(branch='main')['responses'], [])
        self.p.sessions.acknowledge('s', 'r', 0, 3)
        self.assertEqual(self.p.context(branch='main')['responses'][0]['text'], 'acknowledged answer')
        # Cache integration must also operate inside begin's existing transaction.
        self.assertTrue(self.p.sessions.valid(self.p.sessions.begin('s', 'next')))
        self.p.engine.fork('child', 'main')
        self.assertIn('PostgreSQL', self.p.context(branch='child')['text'])
