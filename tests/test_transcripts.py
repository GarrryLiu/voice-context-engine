import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from voice_context.gateway import Pipeline


class TranscriptTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.path=str(Path(self.tmp.name)/'state.db')
        self.p=Pipeline(self.path);self.p.engine.fork('main')
    def tearDown(self):self.p.close();self.tmp.cleanup()
    def submit(self,tid,text='remember db: SQLite'):
        return self.p.submit(tid,'main','s',text)
    def test_visible_before_worker_and_after_restart(self):
        self.submit('a');self.assertEqual(self.p.engine.recall('main'),[])
        self.assertEqual(self.p.dispatch({'action':'context','branch':'main'})['recent'][0]['id'],'a')
        self.p.close();self.p=Pipeline(self.path)
        self.assertEqual(self.p.transcripts.recent('main')[0]['text'],'remember db: SQLite')
    def test_outbox_recovers_crash_without_duplicate_transcripts(self):
        with patch.object(self.p.queue,'enqueue',side_effect=RuntimeError('offline')):
            with self.assertRaises(RuntimeError):self.submit('a')
        self.assertEqual(len(self.p.transcripts.recent('main')),1)
        self.assertFalse(self.submit('a')['accepted'])
        self.assertTrue(self.p.work_once());self.assertFalse(self.p.work_once())
        self.assertEqual(self.p.engine.db.execute('SELECT count(*) FROM tasks').fetchone()[0],1)
    def test_outbox_enqueue_then_crash_before_ack(self):
        self.submit('a')
        with self.p.engine.db:self.p.engine.db.execute('UPDATE transcript_outbox SET published=0')
        self.p.transcripts.publish(self.p.queue)
        self.assertEqual(self.p.engine.db.execute('SELECT count(*) FROM tasks').fetchone()[0],1)
    def test_fork_snapshots_recent_visibility(self):
        self.submit('before');self.p.engine.fork('child','main');self.submit('after')
        self.assertEqual([r['id'] for r in self.p.transcripts.recent('child')],['before'])
        self.p.submit('child','child','s','child only')
        self.assertNotIn('child',[r['id'] for r in self.p.transcripts.recent('main')])
    def test_older_completion_cannot_overwrite_new_confirmation(self):
        a=self.submit('a')['task_id'];b=self.submit('b','remember db: PostgreSQL')['task_id']
        self.p.work_once();self.p.work_once();self.p.approve(b,['db'])
        with self.assertRaises(ValueError):self.p.approve(a,['db'])
        self.assertEqual(self.p.engine.recall('main')[0]['value'],'PostgreSQL')
        self.assertEqual(self.p.approve(b,['db'])['inserted'],0)
    def test_revoke_blocks_approval_and_context_inherited_references(self):
        task=self.submit('a')['task_id'];self.p.work_once();self.p.engine.fork('child','main')
        self.p.transcripts.revoke('a')
        with self.assertRaises(ValueError):self.p.approve(task,['db'])
        self.assertEqual(self.p.transcripts.recent('child'),[])
    def test_budget_charges_envelope_and_reports_oversize_latest(self):
        self.submit('a','很长的发言'*100)
        result=self.p.transcripts.context('main',budget=64)
        self.assertLessEqual(len(result['text'].encode()),64)
        self.assertTrue(result['latest_event_omitted'])
        with self.assertRaises(ValueError):self.p.transcripts.context('main',budget=1)
    def test_manual_correction_is_versioned_and_blocks_old_candidate(self):
        task=self.submit('old')['task_id'];self.p.work_once()
        self.assertEqual(self.p.correct('fix','main','s','db','PostgreSQL',0)['version'],1)
        with self.assertRaises(ValueError):self.p.approve(task,['db'])
        self.assertEqual(self.p.correct('fix','main','s','db','PostgreSQL',0)['inserted'],0)
        self.p.correct('fix2','main','s','db','SQLite',1)
        self.assertEqual([r['value'] for r in self.p.engine.history('main','db')],['PostgreSQL','SQLite'])
        with self.assertRaises(ValueError):self.p.correct('stale','main','s','db','Old',1)
