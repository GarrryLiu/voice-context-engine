import tempfile
import unittest
from pathlib import Path
from voice_context.gateway import Pipeline
from voice_context.sessions import StaleInteraction


class SessionTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.path=str(Path(self.tmp.name)/'state.db')
        self.p=Pipeline(self.path);self.p.engine.fork('main');self.p.engine.fork('other')
        self.p.sessions.open('s',budget=5)
    def tearDown(self):self.p.close();self.tmp.cleanup()
    def test_interrupt_branch_switch_and_reconnect_fence_old_replies(self):
        t=self.p.sessions.begin('s','a');self.assertTrue(self.p.sessions.valid(t))
        self.p.sessions.interrupt('s');self.assertFalse(self.p.sessions.valid(t))
        t=self.p.sessions.begin('s','b');self.p.sessions.interrupt('s','other')
        self.assertFalse(self.p.sessions.valid(t));self.p.sessions.open('s')
        self.assertEqual(self.p.sessions.get('s')['branch'],'other')
    def test_submit_is_visible_and_invalidates_old_response_atomically(self):
        t=self.p.sessions.begin('s','old');epoch=self.p.sessions.get('s')['epoch']
        self.p.sessions.submit('s','turn','现在决定使用 PostgreSQL',epoch)
        self.assertFalse(self.p.sessions.valid(t))
        new=self.p.sessions.begin('s','new')
        self.assertIn('PostgreSQL',new['context']['text'])
        with self.assertRaises(StaleInteraction):self.p.sessions.submit('s','late','late transcript',epoch)
        self.assertFalse(self.p.sessions.submit('s','turn','现在决定使用 PostgreSQL',epoch)['accepted'])
    def test_request_retry_does_not_resurrect_cancelled_generation(self):
        t=self.p.sessions.begin('s','same');self.p.sessions.interrupt('s')
        retry=self.p.sessions.begin('s','same');self.assertEqual(t,retry)
        self.assertFalse(self.p.sessions.valid(retry))
    def test_budget_survives_restart_and_duplicate_call_is_not_reexecuted(self):
        t=self.p.sessions.begin('s','a');self.assertTrue(self.p.sessions.reserve(t,'call','reason',4))
        self.assertFalse(self.p.sessions.reserve(t,'call','reason',4))
        self.p.sessions.finish('call',reported=3);self.p.close();self.p=Pipeline(self.path)
        self.p.sessions.open('s',budget=1000);t=self.p.sessions.begin('s','b')
        self.assertEqual(self.p.sessions.get('s')['spent'],4)
        with self.assertRaises(ValueError):self.p.sessions.reserve(t,'new','tts',2)
    def test_second_connection_cannot_accept_stale_provider_output(self):
        t=self.p.sessions.begin('s','a');other=Pipeline(self.path)
        try:other.sessions.interrupt('s');self.assertFalse(self.p.sessions.valid(t))
        finally:other.close()
    def test_oversize_context_does_not_start_reply(self):
        state=self.p.sessions.get('s');self.p.sessions.submit('s','big','word '*1000,state['epoch'])
        with self.assertRaises(ValueError):self.p.sessions.begin('s','a',budget=128)
        self.assertIsNone(self.p.engine.db.execute("SELECT 1 FROM replies WHERE id='a'").fetchone())
    def test_context_can_use_model_token_counter_without_byte_budget_claim(self):
        state=self.p.sessions.get('s');self.p.sessions.submit('s','a','hello world',state['epoch'])
        ticket=self.p.sessions.begin('s','counted',budget=100,count=lambda text:len(text.split()))
        self.assertEqual(ticket['context']['counter'],'caller_supplied')
        self.assertLessEqual(ticket['context']['cost'],100)
        with self.assertRaises(ValueError):self.p.transcripts.context('main',budget=100,count=lambda text:-1)
