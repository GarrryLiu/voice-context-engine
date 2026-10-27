import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from voice_context.gateway import Pipeline

class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.path=str(Path(self.tmp.name)/'state.db')
        self.p=Pipeline(self.path); self.p.engine.fork('main')
    def tearDown(self): self.p.close(); self.tmp.cleanup()
    def submit(self,tid='one',text='remember db: PostgreSQL'):
        return self.p.submit(tid,'main','session-1',text)
    def test_partial_ignored_and_retry_conflict(self):
        self.assertFalse(self.p.submit('partial','main','s','text',final=False)['accepted'])
        self.assertTrue(self.submit()['accepted']); self.assertFalse(self.submit()['accepted'])
        with self.assertRaises(ValueError): self.submit(text='changed')
    def test_candidate_confirmation_and_source(self):
        tid=self.submit()['task_id']
        with self.assertRaises(ValueError): self.p.approve(tid,['db'])
        self.p.work_once(); self.assertEqual(self.p.engine.recall('main'),[])
        self.assertEqual(self.p.approve(tid,['db'])['inserted'],1)
        self.assertEqual(self.p.approve(tid,['db'])['inserted'],0)
        row=self.p.engine.history('main','db')[-1]
        event=self.p.engine.db.execute('SELECT payload FROM events WHERE id=?',(row['source'],)).fetchone()
        self.assertEqual(json.loads(event[0])['evidence'],'remember db: PostgreSQL')
    def test_restart_before_and_after_extraction(self):
        tid=self.submit()['task_id']; self.p.close(); self.p=Pipeline(self.path)
        self.assertTrue(self.p.work_once()); self.p.close(); self.p=Pipeline(self.path)
        self.p.approve(tid,['db']); self.p.close(); self.p=Pipeline(self.path)
        self.assertEqual(self.p.engine.recall('main','PostgreSQL')[0]['key'],'db')
    def test_invalid_approval_is_atomic(self):
        tid=self.submit(text='remember db: PostgreSQL\nremember cache: Redis')['task_id']; self.p.work_once()
        with self.assertRaises(ValueError): self.p.approve(tid,['db','unknown'])
        self.assertEqual(self.p.engine.recall('main'),[])
    def test_json_gateway_across_processes(self):
        commands=[{'action':'submit','transcript_id':'cli','branch':'main','session':'s','text':'remember choice: SQLite'},
                  {'action':'work'}, {'action':'approve','task_id':'transcript:cli','keys':['choice']}]
        proc=subprocess.run([sys.executable,'-m','voice_context.gateway','--db',self.path],
              input='\n'.join(json.dumps(x) for x in commands)+'\n',text=True,capture_output=True,check=True)
        self.assertTrue(all(json.loads(line)['ok'] for line in proc.stdout.splitlines()))
        proc=subprocess.run([sys.executable,'-m','voice_context.gateway','--db',self.path],
              input=json.dumps({'action':'context','branch':'main','query':'SQLite'})+'\n',text=True,capture_output=True,check=True)
        self.assertEqual(json.loads(proc.stdout)['result']['records'][0]['value'],'SQLite')
