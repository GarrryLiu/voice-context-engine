import importlib.util
import json
import tempfile
from pathlib import Path
import unittest
from voice_context.server.demo import DemoService
from voice_context.gateway import Pipeline


class DemoAdapterTests(unittest.TestCase):
    def test_demo_transcript_reply_ack_and_product_source_without_native(self):
        with tempfile.TemporaryDirectory() as root:
            service=DemoService(str(Path(root)/'demo.db'))
            try:
                self.assertFalse(hasattr(service.session('browser'),'native'))
                confirmed=service.submit_demo('browser','My original product idea.')
                lease=service.acquire('browser',expected_epoch=confirmed['epoch'])
                events=list(service.stream(lease,b'','demo',text_input='My original product idea.'))
                self.assertEqual([e['type'] for e in events],['transcript','reply','text','audio','generated','done'])
                request=next(e for e in events if e['type']=='reply');audio=next(e for e in events if e['type']=='audio')
                self.assertEqual(service.state('browser')['responses'],[])
                self.assertTrue(service.acknowledge('browser',{**request,'sequence':0,'offset':audio['offset']}))
                self.assertIn('Demo reply:',service.state('browser')['responses'][0]['text'])
                notes=service.product.documents('browser','list',{})['documents'];self.assertEqual(len(notes),1)
                draft=service.product.documents('browser','draft',{'reply_id':request['request_id']})
                self.assertEqual(draft['source_text'],'My original product idea.')
                service.controls('browser','new_branch','independent');self.assertEqual(service.controls('browser','switch','independent')['recent'],[])
            finally:service.close()
    def test_demo_cannot_open_existing_connected_workspace(self):
        with tempfile.TemporaryDirectory() as root:
            path=str(Path(root)/'real.db');pipeline=Pipeline(path);pipeline.close()
            with self.assertRaisesRegex(ValueError,'own database'):DemoService(path)


@unittest.skipUnless(importlib.util.find_spec('fastapi'),'voice extra required')
class DemoHTTPTests(unittest.TestCase):
    def test_demo_routes_guard_sources_and_block_real_audio(self):
        from fastapi.testclient import TestClient
        from voice_context.server.app import create_app
        with tempfile.TemporaryDirectory() as root:
            app=create_app(str(Path(root)/'demo.db'),env_file='does-not-exist',mode='demo')
            with TestClient(app) as client:
                headers={'x-voice-token':app.state.local_token,'x-voice-session':'demo-browser'}
                self.assertEqual(client.get('/api/workspace').status_code,403)
                self.assertEqual(client.get('/api/capabilities',headers=headers).json()['mode'],'demo')
                self.assertIn('content="demo"',client.get('/product').text)
                self.assertEqual(client.post('/api/turn',headers={**headers,'content-type':'audio/wav'},content=b'audio').status_code,409)
                self.assertEqual(client.post('/api/demo/utterance',headers=headers,json={'text':''}).status_code,400)
                confirmed=client.post('/api/demo/utterance',headers=headers,json={'text':'A demo thought.'}).json()
                reply=client.post('/api/reply',headers=headers,json=confirmed)
                self.assertEqual(reply.status_code,200)
                events=[json.loads(line) for line in reply.text.splitlines()]
                self.assertEqual(events[-1]['type'],'done')
                from starlette.websockets import WebSocketDisconnect
                with self.assertRaises(WebSocketDisconnect):
                    with client.websocket_connect('/api/live') as ws:ws.receive_json()
