import json
import tempfile
from pathlib import Path
from threading import Event
from types import SimpleNamespace as Obj
import unittest
from unittest.mock import Mock
from voice_context.openai_provider import OpenAITextProvider, OpenAIExtractor, ModelJournal, ProviderFailure


def event(kind, **kw):return Obj(type=kind, **kw)
def completed():
    usage=Mock();usage.model_dump.return_value={'input_tokens':10,'output_tokens':2,'total_tokens':12}
    return event('response.completed',response=Obj(id='resp_test',status='completed',usage=usage))


class Events:
    def __init__(self, events):self.events=events;self.closed=False
    def __enter__(self):return iter(self.events)
    def __exit__(self,*args):self.closed=True


class OpenAITests(unittest.TestCase):
    def provider(self, events):
        client=Mock();stream=Events(events);client.responses.create.return_value=stream
        return OpenAITextProvider('test-model',client),stream

    def test_stream_usage_and_non_storage_contract(self):
        p,s=self.provider([event('response.output_text.delta',delta='Hello!'),completed()])
        self.assertEqual(list(p.stream({'text':'{}'},Event(),'r')),['Hello!'])
        self.assertTrue(s.closed)
        self.assertEqual(p.last_call['usage']['input_tokens'],10)
        self.assertEqual(p.last_call['state'],'completed')
        kwargs=p.client.responses.create.call_args.kwargs
        self.assertFalse(kwargs['store']);self.assertTrue(kwargs['stream'])
        self.assertEqual(kwargs['reasoning'],{'effort':'none'})

    def test_truncation_incomplete_and_refusal_fail_closed(self):
        for tail in ([],[event('response.incomplete')],[event('response.failed')],[event('response.refusal.delta')]):
            p,s=self.provider([event('response.output_text.delta',delta='partial')]+tail)
            with self.assertRaises(ProviderFailure):list(p.stream({'text':'{}'},Event(),'r'))
            self.assertTrue(s.closed);self.assertEqual(p.last_call['state'],'failed')

    def test_cancel_and_generator_close_release_stream(self):
        cancel=Event();p,s=self.provider([event('response.output_text.delta',delta='first'),completed()])
        stream=p.stream({'text':'{}'},cancel,'r');self.assertEqual(next(stream),'first')
        cancel.set()
        with self.assertRaises(ProviderFailure):next(stream)
        self.assertTrue(s.closed);self.assertEqual(p.last_call['state'],'cancelled')
        p,s=self.provider([event('response.output_text.delta',delta='first'),completed()])
        stream=p.stream({'text':'{}'},Event(),'other');next(stream);stream.close()
        self.assertTrue(s.closed);self.assertEqual(p.last_call['state'],'cancelled')

    def test_predispatch_cancel_does_not_call_api(self):
        p,s=self.provider([]);cancel=Event();cancel.set()
        with self.assertRaises(ProviderFailure):list(p.stream({'text':'{}'},cancel,'r'))
        p.client.responses.create.assert_not_called()

    def test_caps_deadline_and_safe_errors(self):
        p,s=self.provider([event('response.output_text.delta',delta='large')]);p.max_text_bytes=1
        with self.assertRaisesRegex(ProviderFailure,'text_limit'):list(p.stream({'text':'{}'},Event(),'r'))
        p,s=self.provider([completed()]);p.client.responses.create.side_effect=RuntimeError('SECRET_BODY')
        with self.assertRaisesRegex(ProviderFailure,'^RuntimeError$'):list(p.stream({'text':'{}'},Event(),'r'))
        self.assertNotIn('SECRET_BODY',json.dumps(p.last_call))
        from unittest.mock import patch
        p,s=self.provider([completed()])
        with patch('voice_context.openai_provider.time.perf_counter',side_effect=[0,31,32]):
            with self.assertRaisesRegex(ProviderFailure,'deadline'):list(p.stream({'text':'{}'},Event(),'r'))

    def test_journal_duplicate_guard_and_restart_usage(self):
        with tempfile.TemporaryDirectory() as directory:
            path=str(Path(directory)/'state.db');journal=ModelJournal(path)
            p,s=self.provider([event('response.output_text.delta',delta='ok'),completed()]);p.journal=journal
            list(p.stream({'text':'{}'},Event(),'r'));journal.close();journal=ModelJournal(path)
            try:
                row=journal.db.execute('SELECT * FROM model_calls').fetchone()
                self.assertEqual(row['state'],'completed');self.assertEqual(json.loads(row['usage'])['total_tokens'],12)
                p.journal=journal
                with self.assertRaisesRegex(ProviderFailure,'reconciliation'):list(p.stream({'text':'{}'},Event(),'r'))
                self.assertEqual(p.client.responses.create.call_count,1)
            finally:journal.close()

    def test_structured_extractor_rejects_invented_evidence(self):
        client=Mock();response=Obj(status='completed',usage=None,output_text=json.dumps({'records':[{'key':'db','value':'Redis','evidence':'Use Redis'}]}))
        client.responses.create.return_value=response
        extractor=OpenAIExtractor('test',client)
        with self.assertRaises(ProviderFailure):extractor.extract('Use PostgreSQL')
        response.output_text=json.dumps({'records':[{'key':'db','value':'PostgreSQL','evidence':'Use PostgreSQL'}]})
        self.assertEqual(extractor.extract('Use PostgreSQL')[0]['value'],'PostgreSQL')
        self.assertTrue(client.responses.create.call_args.kwargs['text']['format']['strict'])

    def test_journal_can_be_written_from_provider_thread(self):
        import threading
        with tempfile.TemporaryDirectory() as directory:
            journal=ModelJournal(str(Path(directory)/'state.db'));errors=[]
            p,s=self.provider([event('response.output_text.delta',delta='ok'),completed()]);p.journal=journal
            def run():
                try:list(p.stream({'text':'{}'},Event(),'thread-call'))
                except Exception as error:errors.append(type(error).__name__)
            thread=threading.Thread(target=run);thread.start();thread.join(3)
            try:
                self.assertFalse(thread.is_alive());self.assertEqual(errors,[])
                self.assertEqual(journal.db.execute('SELECT state FROM model_calls').fetchone()[0],'completed')
            finally:journal.close()

    def test_usage_known_on_extraction_validation_failure_is_retained(self):
        with tempfile.TemporaryDirectory() as directory:
            journal=ModelJournal(str(Path(directory)/'state.db'))
            client=Mock();usage=Mock();usage.model_dump.return_value={'input_tokens':10,'output_tokens':3,'total_tokens':13}
            client.responses.create.return_value=Obj(id='resp_bad',status='completed',usage=usage,
                output_text=json.dumps({'records':[{'key':'db','value':'invented','evidence':'invented'}]}))
            p=OpenAIExtractor('test',client,journal)
            try:
                with self.assertRaises(ProviderFailure):p.extract('real input')
                row=journal.db.execute('SELECT * FROM model_calls').fetchone()
                self.assertEqual(row['state'],'failed')
                self.assertEqual(json.loads(row['usage'])['total_tokens'],13)
            finally:journal.close()


@unittest.skipUnless(__import__('importlib').util.find_spec('openai'), 'optional official SDK required')
class SDKWireTests(unittest.TestCase):
    def test_real_sdk_sse_decode_and_local_config(self):
        import httpx
        from openai import OpenAI
        from voice_context.openai_provider import settings,make_client
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'.env'
            path.write_text('LLM_API_KEY=test-not-a-real-key\nLLM_MODEL=test-model\nLLM_BASE_URL=https://api.openai.com/v1\n')
            from unittest.mock import patch
            with patch.dict('os.environ',{},clear=True):config=settings(path)
            configured=make_client(config)
            try:self.assertEqual(configured.max_retries,0)
            finally:configured.close()
        response={'id':'resp_fixture','object':'response','created_at':0,'status':'completed','model':'test-model','output':[],
                  'usage':{'input_tokens':10,'output_tokens':1,'total_tokens':11}}
        events=[{'type':'response.created','response':{**response,'status':'in_progress'},'sequence_number':0},
                {'type':'response.output_text.delta','delta':'READY','sequence_number':1,'item_id':'msg_1','output_index':0,'content_index':0,'logprobs':[]},
                {'type':'response.completed','response':response,'sequence_number':2}]
        def handler(request):
            body=json.loads(request.content)
            self.assertEqual(request.url.path,'/v1/responses');self.assertFalse(body['store'])
            return httpx.Response(200,headers={'content-type':'text/event-stream'},
                content=''.join('event: '+e['type']+'\ndata: '+json.dumps(e)+'\n\n' for e in events))
        client=OpenAI(api_key='test-not-a-real-key',http_client=httpx.Client(transport=httpx.MockTransport(handler)),max_retries=0)
        p=OpenAITextProvider('test-model',client)
        try:
            self.assertEqual(list(p.stream({'text':'{}'},Event(),'sdk-fixture')),['READY'])
            self.assertEqual(p.last_call['usage']['total_tokens'],11)
        finally:p.close()
