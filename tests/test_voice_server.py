import base64
import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path
from threading import Event
from types import SimpleNamespace as Obj
from unittest.mock import Mock
from voice_context.providers import Transcript
from voice_context.audio_providers import OpenAIRecordingSTT,OpenAIPcmTTS
from voice_context.openai_provider import ProviderFailure


class Stream:
    def __init__(self,items):self.items=items;self.closed=False
    def __enter__(self):return self
    def __exit__(self,*args):self.closed=True
    def __iter__(self):return iter(self.items)
    def iter_bytes(self,chunk_size):return iter(self.items)


class AudioProviderTests(unittest.TestCase):
    def test_completed_recording_partial_and_final(self):
        client=Mock();events=Stream([Obj(type='transcript.text.delta',delta='hello'),Obj(type='transcript.text.done',text='hello',usage=None)])
        client.audio.transcriptions.create.return_value=events;partials=[]
        p=OpenAIRecordingSTT(client,on_partial=partials.append)
        self.assertEqual(list(p.stream([b'audio'],Event(),'r')),[Transcript('hello',False),Transcript('hello',True)])
        self.assertTrue(events.closed);self.assertEqual(partials,['hello'])
        self.assertTrue(client.audio.transcriptions.create.call_args.kwargs['stream'])
    def test_missing_final_and_cancelled_stt_fail(self):
        client=Mock();client.audio.transcriptions.create.return_value=Stream([])
        with self.assertRaises(ProviderFailure):list(OpenAIRecordingSTT(client).stream([b'a'],Event(),'r'))
        stop=Event();stop.set()
        with self.assertRaises(ProviderFailure):list(OpenAIRecordingSTT(client).stream([b'a'],stop,'r'))
    def test_pcm_sample_alignment_and_incomplete_sample(self):
        client=Mock();raw=Stream([b'a',b'bcd',b'ef'])
        client.audio.speech.with_streaming_response.create.return_value=raw
        self.assertEqual(b''.join(OpenAIPcmTTS(client).stream('hello',Event(),'r')),b'abcdef')
        self.assertTrue(raw.closed)
        client.audio.speech.with_streaming_response.create.return_value=Stream([b'x'])
        with self.assertRaises(ProviderFailure):list(OpenAIPcmTTS(client).stream('hello',Event(),'r'))


@unittest.skipUnless(importlib.util.find_spec('fastapi') and os.environ.get('VOICE_RUNTIME_LIBRARY'),'requires voice extra and native build')
class VoiceServerTests(unittest.TestCase):
    def setUp(self):
        from fastapi.testclient import TestClient
        from voice_context.voice_server import VoiceService,create_app
        self.tmp=tempfile.TemporaryDirectory()
        class STT:
            name='test-stt'
            def stream(self,audio,cancelled,request_id):
                list(audio);yield Transcript('Say hello.',True)
        class Text:
            name='test-text'
            def stream(self,context,cancelled,request_id):yield 'Hello.'
        class TTS:
            name='test-tts'
            def stream(self,text,cancelled,request_id):
                for _ in range(20):yield b'\x00\x10'*2000
        self.service=VoiceService(str(Path(self.tmp.name)/'state.db'),factory=lambda filename,partial:(STT(),Text(),TTS(),None,None))
        self.app=create_app(service=self.service)
        self.client=TestClient(self.app);self.client.__enter__()
        self.headers={'x-voice-token':self.app.state.local_token,'x-voice-session':'test-session'}
    def tearDown(self):self.client.__exit__(None,None,None);self.tmp.cleanup()
    def test_new_product_session_branch_does_not_inherit_other_thoughts(self):
        c=self.service.session('test-session')
        c.pipeline.submit('old-product-input','main','test-session','A private thought in another session.')
        self.assertEqual(self.client.post('/api/control',headers=self.headers,json={'action':'new_branch','branch':'product-independent'}).status_code,200)
        state=self.client.post('/api/control',headers=self.headers,json={'action':'switch','branch':'product-independent'}).json()
        self.assertEqual(state['recent'],[])
        self.assertEqual(c.pipeline.context(branch='product-independent')['recent'],[])

    def test_v1_boundary_discovery_and_compatible_wire_shapes(self):
        self.assertEqual(self.client.get('/api/capabilities').status_code,403)
        r=self.client.get('/api/capabilities',headers=self.headers)
        self.assertEqual(r.headers['x-voice-contract'],'1')
        caps=r.json();self.assertEqual(caps['mode'],'connected')
        self.assertEqual(caps['semantics']['new_branch'],'independent_context')
        state=self.client.get(caps['endpoints']['state'],headers=self.headers).json()
        self.assertEqual(set(state),{'session','branch','epoch','branches','recent','responses'})
        snapshot=self.client.get(caps['endpoints']['workspace'],headers=self.headers).json()
        self.assertEqual(set(snapshot),{'version','data'})
        self.assertNotIn('LLM_API_KEY',r.text)

    def test_product_workspace_auth_persistence_and_conflict(self):
        self.assertEqual(self.client.get('/api/workspace').status_code,403)
        initial=self.client.get('/api/workspace',headers=self.headers).json()
        self.assertEqual(initial['version'],0)
        initial['data']['categories'].append('Product')
        saved=self.client.post('/api/workspace',headers=self.headers,json=initial)
        self.assertEqual(saved.status_code,200)
        self.assertEqual(saved.json()['version'],1)
        self.assertEqual(self.client.post('/api/workspace',headers=self.headers,json=initial).status_code,409)
        self.assertEqual(self.client.post('/api/workspace',headers=self.headers,json={'version':1,'data':{}}).status_code,400)
        self.assertEqual(self.client.get('/api/workspace',headers=self.headers).json(),saved.json())

    def test_stream_native_pcm_and_explicit_ack_context(self):
        r=self.client.post('/api/turn',headers={**self.headers,'content-type':'audio/wav'},content=b'fixture')
        self.assertEqual(r.status_code,200)
        events=[json.loads(line) for line in r.text.splitlines()]
        self.assertNotIn('error',[e['type'] for e in events]);self.assertEqual(events[-1]['type'],'done')
        self.assertEqual([e['text'] for e in events if e['type']=='transcript'],['Say hello.'])
        audio=[e for e in events if e['type']=='audio'];self.assertTrue(audio)
        self.assertEqual(sum(len(base64.b64decode(e['data'])) for e in audio),80000)
        c=self.service.session('test-session')
        self.assertEqual(c.pipeline.context(branch='main')['responses'],[])
        for e in audio:
            payload={k:e[k] for k in ('epoch','request_id','sequence','offset')}
            self.assertEqual(self.client.post('/api/ack',headers=self.headers,json=payload).status_code,200)
        self.assertEqual(c.pipeline.context(branch='main')['responses'][0]['text'],'Hello.')
    def test_no_secret_in_page_and_request_guards(self):
        page=self.client.get('/');self.assertEqual(page.status_code,200)
        self.assertIn('AI 合成声音',page.text);self.assertNotIn('LLM_API_KEY',page.text)
        self.assertEqual(self.client.get('/api/state').status_code,403)
        self.assertEqual(self.client.get('/api/state',headers={**self.headers,'origin':'https://attacker.example'}).status_code,403)
        self.assertEqual(self.client.get('/',headers={'host':'attacker.example'}).status_code,403)
        self.assertEqual(self.client.post('/api/turn',headers={**self.headers,'content-type':'text/plain'},content=b'x').status_code,415)
        self.assertEqual(self.client.post('/api/turn',headers={**self.headers,'content-type':'audio/wav'},content=b'x'*(2*1024*1024+1)).status_code,413)
    def test_product_and_lab_share_authenticated_backend(self):
        for path in ('/','/lab','/product'):
            page=self.client.get(path)
            self.assertEqual(page.status_code,200)
            self.assertIn(self.app.state.local_token,page.text)
            self.assertNotIn('LLM_API_KEY',page.text)
        self.assertIn('切换到产品体验版',self.client.get('/lab').text)
        for path in ('/product.js','/product.css','/strings.js'):
            self.assertEqual(self.client.get(path).status_code,200)
    def test_documents_capture_edit_conflict_and_restore(self):
        response=self.client.post('/api/turn',headers={**self.headers,'content-type':'audio/wav'},content=b'fixture')
        events=[json.loads(line) for line in response.text.splitlines()]
        listing=self.client.get('/api/documents',headers=self.headers).json()['documents']
        self.assertEqual(len(listing),1);identifier=listing[0]['id']
        doc=self.client.get('/api/documents/item',headers=self.headers,params={'id':identifier}).json()
        self.assertEqual(doc['source_text'],'Say hello.')
        payload={'id':identifier,'version':1,'changes':{'title':'A useful note','content':'Edited note.'}}
        self.assertEqual(self.client.post('/api/documents/change',headers=self.headers,json=payload).json()['version'],2)
        self.assertEqual(self.client.post('/api/documents/change',headers=self.headers,json=payload).status_code,409)
        restored=self.client.post('/api/documents/restore',headers=self.headers,json={'id':identifier,'version':2,'restore_version':1}).json()
        self.assertEqual(restored['version'],3);self.assertEqual(restored['content'],'Say hello.')
        revision=self.client.get('/api/documents/revision',headers=self.headers,params={'id':identifier,'version':2}).json()
        self.assertEqual(revision['content'],'Edited note.')
        self.assertEqual(len(self.client.get('/api/documents/history',headers=self.headers,params={'id':identifier}).json()['versions']),3)
    def test_document_draft_requires_ack_and_retries_deduplicate(self):
        response=self.client.post('/api/turn',headers={**self.headers,'content-type':'audio/wav'},content=b'fixture')
        events=[json.loads(line) for line in response.text.splitlines()];audio=[e for e in events if e['type']=='audio']
        payload={'reply_id':audio[0]['request_id']}
        self.assertEqual(self.client.post('/api/documents/draft',headers=self.headers,json=payload).status_code,400)
        for e in audio:self.client.post('/api/ack',headers=self.headers,json={k:e[k] for k in ('epoch','request_id','sequence','offset')})
        first=self.client.post('/api/documents/draft',headers=self.headers,json=payload).json()
        second=self.client.post('/api/documents/draft',headers=self.headers,json=payload).json()
        self.assertEqual(first['id'],second['id']);self.assertEqual(first['content'],'Hello.')
        self.assertEqual(first['source_text'],'Say hello.')
        self.assertEqual(self.client.get('/api/documents').status_code,403)
        self.assertEqual(self.client.post('/api/documents/create',headers=self.headers,content=b'x'*262145).status_code,413)
        bad={'title':'x','content':'x','branch':'missing'}
        self.assertEqual(self.client.post('/api/documents/create',headers=self.headers,json=bad).status_code,400)
    def test_branch_selection_and_busy_limit(self):
        self.assertEqual(self.client.get('/api/state',headers=self.headers).status_code,200)
        self.assertEqual(self.client.post('/api/control',headers=self.headers,json={'action':'fork','branch':'idea'}).status_code,200)
        r=self.client.post('/api/control',headers=self.headers,json={'action':'switch','branch':'idea'})
        self.assertEqual(r.json()['branch'],'idea')
        leases=[self.service.acquire('test-session') for _ in range(4)]
        try:self.assertEqual(self.client.post('/api/turn',headers={**self.headers,'content-type':'audio/wav'},content=b'x').status_code,409)
        finally:
            for lease in leases:self.service.release(lease)
    def test_new_turn_finishes_while_old_provider_ignores_cancel(self):
        import threading
        entered=Event();release=Event();old_events=[]
        original=self.service.factory
        class Blocked:
            name='blocked'
            def stream(self,*args):
                entered.set();release.wait(5);yield 'STALE.'
        first=True
        def factory(filename,partial):
            nonlocal first
            stt,text,tts,client,journal=original(filename,partial)
            if first:first=False;text=Blocked()
            return stt,text,tts,client,journal
        self.service.factory=factory
        old=self.service.acquire('test-session')
        worker=threading.Thread(target=lambda:old_events.extend(self.service.stream(old,b'x','test.wav')))
        worker.start()
        try:
            self.assertTrue(entered.wait(2))
            self.service.controls('test-session','interrupt')
            new=self.service.acquire('test-session')
            events=list(self.service.stream(new,b'x','test.wav'))
            self.assertFalse(release.is_set())
            self.assertTrue(any(e['type']=='audio' for e in events))
            self.assertFalse(any(e['type']=='error' for e in events))
            epoch=self.service.state('test-session')['epoch']
            release.set();worker.join(3)
            self.assertEqual(self.service.state('test-session')['epoch'],epoch)
            self.assertFalse(any(e['type']=='audio' for e in old_events))
        finally:release.set();worker.join(5)
    def test_old_stream_cleanup_cannot_interrupt_new_live_capture(self):
        import threading
        from voice_context.realtime_stt import LiveTranscription
        entered=Event();release=Event();original=self.service.factory
        class Blocked:
            name='blocked'
            def stream(self,*args):entered.set();release.wait(5);yield 'Late.'
        def factory(*args):
            stt,_,tts,client,journal=original(*args)
            return stt,Blocked(),tts,client,journal
        self.service.factory=factory;lease=self.service.acquire('test-session')
        thread=threading.Thread(target=lambda:list(self.service.stream(lease,b'x','test.wav')));thread.start()
        try:
            self.assertTrue(entered.wait(2))
            live=LiveTranscription(lease.conversation);new_epoch=live.onset()['epoch']
            lease.stop.set();thread.join(1)
            self.assertFalse(thread.is_alive())
            self.assertEqual(self.service.state('test-session')['epoch'],new_epoch)
            live.items['new']=new_epoch
            self.assertIsNotNone(live.accept('new','Confirmed live input.'))
        finally:
            release.set();thread.join(5)
            import time
            deadline=time.monotonic()+2
            while 'test-session' in self.service.active and time.monotonic()<deadline:time.sleep(.01)
    def test_late_provider_failure_still_delivers_error_after_epoch_abort(self):
        import time
        original=self.service.factory
        class PartialFailure:
            name='late-failure'
            def stream(self,*args):
                yield 'First sentence.'
                time.sleep(.05)
                raise RuntimeError('private failure body')
        def factory(*args):
            stt,_,tts,client,journal=original(*args)
            return stt,PartialFailure(),tts,client,journal
        self.service.factory=factory
        lease=self.service.acquire('test-session')
        events=list(self.service.stream(lease,b'x','test.wav'))
        self.assertTrue(any(e['type']=='audio' for e in events))
        self.assertTrue(any(e['type']=='error' for e in events))
        self.assertEqual(events[-1]['type'],'done')
        self.assertNotIn('private failure',json.dumps(events))
    def test_provider_failure_emits_safe_terminal_and_releases_slot(self):
        class Broken:
            name='broken'
            def stream(self,*args):raise RuntimeError('sensitive detail')
        original=self.service.factory
        def factory(filename,partial):
            stt,text,tts,client,journal=original(filename,partial)
            return stt,Broken(),tts,client,journal
        self.service.factory=factory
        r=self.client.post('/api/turn',headers={**self.headers,'content-type':'audio/wav'},content=b'x')
        events=[json.loads(line) for line in r.text.splitlines()]
        self.assertTrue(any(e['type']=='error' for e in events));self.assertEqual(events[-1]['type'],'done')
        self.assertNotIn('sensitive detail',r.text)
        self.assertTrue(self.service.slots.acquire(False));self.service.slots.release()
