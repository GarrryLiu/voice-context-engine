"""Live protocol / epoch tests using bounded fake upstream, no API calls."""
import asyncio
from contextlib import asynccontextmanager
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest


@unittest.skipUnless(importlib.util.find_spec('fastapi') and os.environ.get('VOICE_RUNTIME_LIBRARY'),'requires voice/native')
class LiveTests(unittest.TestCase):
    def setUp(self):
        from fastapi.testclient import TestClient
        from voice_context.voice_server import VoiceService,create_app
        from voice_context.providers import Transcript
        self.tmp=tempfile.TemporaryDirectory();self.pcm=[];owner=self
        class Upstream:
            def __init__(self):self.queue=asyncio.Queue();self.count=0
            async def send(self,raw):
                event=json.loads(raw)
                if event['type']=='session.update':await self.queue.put(json.dumps({'type':'session.updated'}))
                if event['type']=='input_audio_buffer.append':owner.pcm.append(event['audio'])
                if event['type']=='input_audio_buffer.commit':
                    self.count+=1;item='item-'+str(self.count)
                    for e in [{'type':'input_audio_buffer.committed','item_id':item},
                              {'type':'conversation.item.input_audio_transcription.delta','item_id':item,'delta':'Live'},
                              {'type':'conversation.item.input_audio_transcription.completed','item_id':item,'transcript':'Live fixture.'}]:
                        await self.queue.put(json.dumps(e))
            def __aiter__(self):return self
            async def __anext__(self):return await self.queue.get()
        @asynccontextmanager
        async def factory(_):yield Upstream()
        class STT:
            name='unused'
            def stream(self,*args):raise AssertionError('live final must not call recording STT')
        class Text:
            name='fake-text'
            def stream(self,*args):yield 'Live reply.'
        class TTS:
            name='fake-tts'
            def stream(self,*args):
                for _ in range(24):yield b'\0\1'*2000
        self.service=VoiceService(str(Path(self.tmp.name)/'live.db'),live_factory=factory,
            factory=lambda *args:(STT(),Text(),TTS(),None,None))
        self.app=create_app(service=self.service);self.client=TestClient(self.app);self.client.__enter__()
        self.headers={'x-voice-token':self.app.state.local_token,'x-voice-session':'live-test'}
    def tearDown(self):self.client.__exit__(None,None,None);self.tmp.cleanup()
    def authenticate(self,ws):
        ws.send_json({'token':self.app.state.local_token,'session':'live-test'})
        self.assertEqual(ws.receive_json()['type'],'ready')
    def test_websocket_live_final_is_durable_and_reply_uses_existing_models(self):
        with self.client.websocket_connect('/api/live',headers={'origin':'http://testserver'}) as ws:
            self.authenticate(ws)
            ws.send_json({'type':'start'});onset=ws.receive_json();self.assertEqual(onset['type'],'speech_started')
            ws.send_bytes(b'\0\1'*2400);ws.send_json({'type':'commit'})
            self.assertEqual(ws.receive_json()['type'],'partial');final=ws.receive_json()
            self.assertEqual(final['text'],'Live fixture.');self.assertTrue(self.pcm)
            state=self.client.get('/api/state',headers=self.headers).json()
            self.assertEqual(state['recent'][0]['text'],'Live fixture.')
            response=self.client.post('/api/reply',headers=self.headers,json={k:final[k] for k in ('transcript_id','epoch')})
            events=[json.loads(x) for x in response.text.splitlines()]
            self.assertEqual(response.status_code,200);self.assertTrue(any(e['type']=='audio' for e in events))
            self.assertFalse(any(e['type']=='error' for e in events))
            # Retrying an old final must not dispatch/bill a second model response.
            self.assertEqual(self.client.post('/api/reply',headers=self.headers,json={k:final[k] for k in ('transcript_id','epoch')}).status_code,409)
    def test_websocket_rejects_bad_auth_and_oversized_pcm(self):
        with self.client.websocket_connect('/api/live',headers={'origin':'http://testserver'}) as ws:
            ws.send_json({'token':'wrong','session':'live-test'});self.assertEqual(ws.receive_json()['type'],'error')
        with self.client.websocket_connect('/api/live',headers={'origin':'http://testserver'}) as ws:
            self.authenticate(ws);ws.send_json({'type':'start'});ws.receive_json();ws.send_bytes(bytes(9602))
            self.assertEqual(ws.receive_json()['type'],'error')
    def test_late_out_of_order_and_duplicate_finals_do_not_cross_branches(self):
        from voice_context.realtime_stt import LiveTranscription
        c=self.service.session('live-test');live=LiveTranscription(c)
        first=live.onset()['epoch'];live.items['old']=first
        new=live.onset()['epoch'];live.items['new']=new
        self.assertIsNone(live.accept('old','Wrong old final.'))
        final=live.accept('new','Confirmed now.')
        self.assertIsNotNone(final);self.assertIsNone(live.accept('new','Confirmed now.'))
        self.assertEqual(c.pipeline.context(branch='main')['recent'][0]['text'],'Confirmed now.')
        live.items['branch-old']=live.onset()['epoch']
        self.service.controls('live-test','fork','child');self.service.controls('live-test','switch','child')
        self.assertIsNone(live.accept('branch-old','Wrong branch.'))

    @unittest.skipUnless(os.environ.get('VOICE_BROWSER_TEST'),'opt-in fake microphone browser')
    def test_continuous_fake_microphone_and_automatic_barge_in(self):
        self.run_browser_capture(False)

    @unittest.skipUnless(os.environ.get('VOICE_BROWSER_TEST'),'opt-in fake microphone browser')
    def test_suspended_audio_context_does_not_dispatch_old_final_after_new_speech(self):
        self.run_browser_capture(True)

    @unittest.skipUnless(os.environ.get('VOICE_BROWSER_TEST'),'opt-in synthetic microphone browser')
    def test_product_continuous_microphone_and_barge_in(self):
        self.run_browser_capture(False,'/product')

    def run_browser_capture(self,delay_resume,route='/'):
        import socket,threading,time
        import uvicorn
        from playwright.sync_api import sync_playwright,expect
        listener=socket.socket();listener.bind(('127.0.0.1',0));port=listener.getsockname()[1]
        server=uvicorn.Server(uvicorn.Config(self.app,log_level='error'))
        thread=threading.Thread(target=lambda:server.run(sockets=[listener]),daemon=True);thread.start()
        try:
            deadline=time.monotonic()+5
            while not server.started:
                if time.monotonic()>deadline:self.fail('server start timeout')
                time.sleep(.02)
            with sync_playwright() as pw:
                options={'headless':True,'args':['--autoplay-policy=no-user-gesture-required']}
                if os.environ.get('VOICE_CHROME_PATH'):options['executable_path']=os.environ['VOICE_CHROME_PATH']
                browser=pw.chromium.launch(**options)
                try:
                    page=browser.new_page();errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
                    page.add_init_script("""window.playbackStops=0;const originalStop=AudioBufferSourceNode.prototype.stop;
                        AudioBufferSourceNode.prototype.stop=function(...args){window.playbackStops++;return originalStop.apply(this,args);};
                        navigator.mediaDevices.getUserMedia=async()=>{
                            const ctx=new AudioContext({sampleRate:48000});await ctx.resume();
                            const oscillator=ctx.createOscillator(),gain=ctx.createGain(),destination=ctx.createMediaStreamDestination();
                            gain.gain.value=0;oscillator.frequency.value=220;oscillator.connect(gain);gain.connect(destination);oscillator.start();
                            window.testMic={ctx,gain};return destination.stream;
                        };""")
                    page.goto('http://127.0.0.1:'+str(port)+route);expect(page.locator('#record')).to_be_enabled()
                    requests=[];page.on('request',lambda request:requests.append(request.url) if request.url.endswith('/api/reply') else None)
                    if delay_resume:
                        page.evaluate('''()=>{const original=audioContext;let delayed=false;audioContext=async()=>{const ctx=await original();if(liveReady&&!delayed){delayed=true;await new Promise(resolve=>window.releaseContext=resolve);}return ctx;};}''')
                    page.click('#live');expect(page.locator('#status')).to_have_text('Listening. Go ahead.' if route=='/product' else '连续对话中，可以开始说话',timeout=10000)
                    def utterance():
                        page.evaluate('()=>testMic.gain.gain.value=.3');page.wait_for_timeout(700)
                        page.evaluate('()=>testMic.gain.gain.value=0')
                    utterance()
                    if delay_resume:
                        deadline=time.monotonic()+5
                        while not page.evaluate("()=>typeof window.releaseContext==='function'"):
                            if time.monotonic()>deadline:self.fail('context suspension not reached')
                            page.wait_for_timeout(20)
                    else:
                        expect(page.locator('#status')).to_have_text('Speaking…' if route=='/product' else '正在播放',timeout=10000)
                        self.assertGreater(page.evaluate('()=>sources.size'),0)
                    # Supply the second microphone utterance only after the tested phase.
                    utterance()
                    expect(page.locator('#status')).to_have_text('Reply finished. Ready when you are.' if route=='/product' else '回复结束，可以继续说',timeout=15000)
                    if delay_resume:
                        self.assertEqual(len(requests),1)
                        page.evaluate('()=>window.releaseContext()');page.wait_for_timeout(200)
                        self.assertEqual(len(requests),1)
                    else:self.assertGreaterEqual(page.evaluate('()=>window.playbackStops'),1)
                    sid=page.evaluate("()=>localStorage.getItem('voice-session')")
                    state=self.service.state(sid)
                    self.assertEqual(len(state['recent']),2);self.assertTrue(state['responses'])
                    expect(page.locator('#record')).to_be_disabled()
                    page.click('#live');expect(page.locator('#status')).to_have_text('Conversation ended' if route=='/product' else '连续对话已结束')
                    expect(page.locator('#record')).to_be_enabled();self.assertEqual(errors,[])
                    page.evaluate('()=>testMic.ctx.close()')
                finally:browser.close()
        finally:server.should_exit=True;thread.join(10)
