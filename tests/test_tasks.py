import tempfile
import unittest
from pathlib import Path
from voice_context.tasks import TaskQueue, LeaseLost

class QueueTests(unittest.TestCase):
    def setUp(self):
        self.now=100.; self.q=TaskQueue(clock=lambda:self.now)
        self.q.enqueue('one','extract',{'text':'hi'},max_attempts=2)
    def tearDown(self): self.q.close()
    def test_idempotency_and_conflicting_key(self):
        self.assertFalse(self.q.enqueue('one','extract',{'text':'hi'},max_attempts=2))
        with self.assertRaises(ValueError): self.q.enqueue('one','extract',{})
    def test_retry_backoff_and_dead_letter(self):
        a=self.q.claim(); self.q.fail(a['id'],a['lease_token'],'temporary')
        self.assertIsNone(self.q.claim()); self.now+=1
        b=self.q.claim(); self.assertEqual(b['attempts'],2)
        self.q.fail(b['id'],b['lease_token'],'again')
        self.assertEqual(self.q.get('one')['state'],'dead')
    def test_expired_worker_cannot_complete(self):
        old=self.q.claim(1); self.now+=2
        new=self.q.claim(10)
        with self.assertRaises(LeaseLost): self.q.complete('one',old['lease_token'],{})
        self.q.complete('one',new['lease_token'],{'ok':True})
        self.assertEqual(self.q.get('one')['result'],{'ok':True})
    def test_cancel_revokes_worker(self):
        a=self.q.claim(); self.assertTrue(self.q.cancel('one'))
        with self.assertRaises(LeaseLost): self.q.complete('one',a['lease_token'],{})
    def test_reopen_and_two_connections(self):
        with tempfile.TemporaryDirectory() as d:
            path=str(Path(d)/'tasks.db')
            a=TaskQueue(path,clock=lambda:self.now); a.enqueue('x','extract',{})
            first=a.claim(1); a.close()
            b=TaskQueue(path,clock=lambda:self.now); c=TaskQueue(path,clock=lambda:self.now)
            self.assertIsNone(b.claim()); self.now+=2
            claimed=b.claim(); self.assertIsNone(c.claim())
            b.complete('x',claimed['lease_token'],1)
            self.assertEqual(c.get('x')['state'],'succeeded'); b.close(); c.close()
    def test_worker_records_failure(self):
        def fail(task): raise ValueError('private provider details')
        self.q.run_once(fail)
        self.assertEqual(self.q.get('one')['error'],'ValueError')
