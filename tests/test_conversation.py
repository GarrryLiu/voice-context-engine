import os
from pathlib import Path
import tempfile
import threading
import unittest
from voice_context.conversation import Conversation,Transcript,Backpressure
from voice_context.sessions import StaleInteraction
from voice_context.gateway import Pipeline


class Text:
    def stream(self,context,cancelled,request_id):yield '你好。';yield 'Done!'
class TTS:
    def stream(self,text,cancelled,request_id):yield text.encode('utf-8')
class STT:
    def stream(self,audio,cancelled,request_id):
        assert list(audio)==[b'pcm']
        yield Transcript('partial',False);yield Transcript('确认决定使用 PostgreSQL',True)


@unittest.skipUnless(os.environ.get('VOICE_RUNTIME_LIBRARY'),'explicit native build required')
class ConversationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.path=str(Path(self.tmp.name)/'state.db')
        self.c=Conversation(self.path,'s',capacity=256)
    def tearDown(self):self.c.close();self.tmp.cleanup()
    def test_staged_transcript_response_and_phase_ledger(self):
        self.assertTrue(self.c.transcribe('turn',STT(),[b'pcm'])['accepted'])
        result=self.c.respond('response',Text(),TTS(),reason_cost=2,tts_cost=1)
        self.assertIn('PostgreSQL',result['ticket']['context']['text'])
        pcm,n=self.c.render(256);self.assertEqual(pcm[:n],'你好。Done!'.encode())
        ledger=self.c.pipeline.engine.db.execute('SELECT stage,state,elapsed FROM stage_calls').fetchall()
        self.assertEqual([r['stage'] for r in ledger],['stt','reason','tts','tts'])
        self.assertTrue(all(r['state']=='completed' and r['elapsed']>=0 for r in ledger))
        self.assertEqual(self.c.pipeline.sessions.get('s')['spent'],5)
    def test_uncancellable_late_text_cannot_repopulate_queues(self):
        entered=threading.Event();release=threading.Event();errors=[]
        class SlowText:
            def stream(self,context,cancelled,request_id):
                entered.set();release.wait(3);yield 'Old response!'
        def worker():
            try:self.c.respond('old',SlowText(),TTS())
            except Exception as error:errors.append(error)
        t=threading.Thread(target=worker);t.start();self.assertTrue(entered.wait(3))
        self.c.interrupt();release.set();t.join(3);self.assertFalse(t.is_alive())
        self.assertIsInstance(errors[0],StaleInteraction)
        self.assertEqual(self.c.render(256),(bytes(256),0))
    def test_uncancellable_late_tts_cannot_play_after_branch_switch(self):
        self.c.pipeline.engine.fork('other');entered=threading.Event();release=threading.Event();errors=[]
        class SlowTTS:
            def stream(self,text,cancelled,request_id):
                entered.set();release.wait(3);yield b'old audio'
        def worker():
            try:self.c.respond('old',Text(),SlowTTS())
            except Exception as error:errors.append(error)
        t=threading.Thread(target=worker);t.start();self.assertTrue(entered.wait(3))
        self.c.interrupt('other');release.set();t.join(3)
        self.assertFalse(t.is_alive());self.assertIsInstance(errors[0],StaleInteraction)
        self.assertEqual(self.c.render(256),(bytes(256),0))
    def test_external_reconnect_flushes_queue_before_render(self):
        self.c.respond('reply',Text(),TTS());other=Pipeline(self.path)
        try:other.sessions.open('s')
        finally:other.close()
        self.assertEqual(self.c.render(256),(bytes(256),0))
    def test_backpressure_waits_for_consumer_and_timeout_clears_partial_audio(self):
        class Audio:
            def stream(self,text,cancelled,request_id):yield bytes(200);yield bytes(200)
        class One:
            def stream(self,context,cancelled,request_id):yield 'One.'
        with self.assertRaises(Backpressure):self.c.respond('too-full',One(),Audio())
        self.assertEqual(self.c.render(256),(bytes(256),0))
        self.assertEqual(self.c.native.stats()['playback_bytes'],0)
    def test_no_final_stt_and_partial_text_never_enters_context(self):
        class Partial:
            def stream(self,audio,cancelled,request_id):yield Transcript('not final',False)
        with self.assertRaises(ValueError):self.c.transcribe('bad',Partial(),[b'pcm'])
        self.assertEqual(self.c.pipeline.transcripts.recent('main'),[])
    def test_repeated_request_does_not_call_providers_twice(self):
        self.c.respond('same',Text(),TTS())
        spent=self.c.pipeline.sessions.get('s')['spent']
        self.assertEqual(self.c.respond('same',Text(),TTS())['status'],'duplicate')
        self.assertEqual(self.c.pipeline.sessions.get('s')['spent'],spent)
    def test_playback_offsets_are_explicit_monotonic_and_survive_reconnect(self):
        result=self.c.respond('r',Text(),TTS());self.c.render(256)
        rows=self.c.pipeline.sessions.delivery('s');first=rows[0]
        self.assertEqual(first['acknowledged'],0) # rendering does not claim hardware playback
        self.assertTrue(self.c.pipeline.sessions.acknowledge('s','r',0,first['bytes']))
        self.assertFalse(self.c.pipeline.sessions.acknowledge('s','r',0,1))
        with self.assertRaises(ValueError):self.c.pipeline.sessions.acknowledge('s','r',0,first['bytes']+1)
        self.c.close();self.c=Conversation(self.path,'s',capacity=256)
        self.assertEqual(self.c.pipeline.sessions.delivery('s')[0]['acknowledged'],first['bytes'])
        self.assertEqual(self.c.render(256),(bytes(256),0))
    def test_consumer_draining_unblocks_tts(self):
        self.c.audio_wait_seconds=1;errors=[];results=[]
        class One:
            def stream(self,context,cancelled,request_id):yield 'One.'
        class Audio:
            def stream(self,text,cancelled,request_id):yield b'a'*200;yield b'b'*200
        def producer():
            try:results.append(self.c.respond('flow',One(),Audio()))
            except Exception as error:errors.append(error)
        worker=threading.Thread(target=producer);worker.start()
        import time
        deadline=time.monotonic()+3;played=b''
        while worker.is_alive() and time.monotonic()<deadline:
            data,n=self.c.render(256);played+=data[:n];time.sleep(.001)
        worker.join(1);data,n=self.c.render(256);played+=data[:n]
        self.assertFalse(errors);self.assertFalse(worker.is_alive())
        self.assertEqual(played,b'a'*200+b'b'*200)
    def test_only_explicitly_acknowledged_segments_enter_resumed_context(self):
        self.c.respond('r',Text(),TTS());self.c.render(256)
        self.assertEqual(self.c.pipeline.transcripts.context('main')['responses'],[])
        first=self.c.pipeline.sessions.delivery('s')[0]
        self.c.pipeline.sessions.acknowledge('s','r',0,first['bytes'])
        context=self.c.pipeline.transcripts.context('main')
        self.assertEqual(context['responses'][0]['text'],'你好。')
        self.assertEqual(self.c.pipeline.engine.recall('main'),[])
    def test_output_caps_fail_closed_and_failed_provider_cost_is_retained(self):
        self.c.max_text_bytes=2
        with self.assertRaises(ValueError):self.c.respond('capped',Text(),TTS(),reason_cost=3)
        self.assertEqual(self.c.pipeline.sessions.get('s')['spent'],3)
        self.assertEqual(self.c.render(256),(bytes(256),0))
        self.assertEqual(len(self.c.running),0)
    def test_completed_provider_cannot_append_more_but_queued_audio_can_play(self):
        result=self.c.respond('finished',Text(),TTS());ticket=result['ticket']
        self.assertEqual(self.c.receive_audio(ticket,2,b'late'),0)
        self.assertEqual(self.c.receive_text(ticket,'late!'),0)
        data,n=self.c.render(256);self.assertEqual(data[:n],'你好。Done!'.encode())
    def test_provider_failure_clears_audio_even_when_audit_completion_fails(self):
        from unittest.mock import patch
        class BrokenTTS:
            def stream(self,text,cancelled,request_id):yield b'partial';raise RuntimeError('provider failed')
        with patch.object(self.c.pipeline.sessions,'finish',side_effect=RuntimeError('audit unavailable')):
            with self.assertRaises(RuntimeError):self.c.respond('broken',Text(),BrokenTTS())
        self.assertEqual(self.c.render(256),(bytes(256),0))
    def test_failed_new_context_does_not_cancel_existing_valid_reply(self):
        ticket=self.c.begin('old');self.assertEqual(self.c.receive_audio(ticket,0,b'old'),1)
        with self.assertRaises(ValueError):self.c.begin('invalid',budget=1)
        self.assertTrue(self.c.pipeline.sessions.valid(ticket))
        self.assertFalse(self.c.cancelled['old'].is_set())
        data,n=self.c.render(256);self.assertEqual(data[:n],b'old')
