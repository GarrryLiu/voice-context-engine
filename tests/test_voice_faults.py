"""Browser failure experiments on isolated services; no API calls or real microphone."""
import hashlib
import json
import os
from pathlib import Path
import socket
import tempfile
import threading
import time
import unittest
import wave


@unittest.skipUnless(os.environ.get('VOICE_BROWSER_TEST') and os.environ.get('VOICE_RUNTIME_LIBRARY'),'opt-in browser/native required')
class VoiceFaultTests(unittest.TestCase):
    results=[]
    @classmethod
    def tearDownClass(cls):
        if os.environ.get('VOICE_FAULT_RESULTS'):
            files=list(Path('src/voice_context').glob('*.py'))+list(Path('src/voice_context/web').glob('*'))
            Path(os.environ['VOICE_FAULT_RESULTS']).write_text(json.dumps({'protocol':'headless Chromium, fake providers and fake recording; software timings only',
                'checks':cls.results,'source_hashes':{str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in files}},indent=2)+'\n')
    def setUp(self):
        import uvicorn
        from playwright.sync_api import sync_playwright,expect
        from voice_context.voice_server import VoiceService,create_app
        from voice_context.providers import Transcript
        self.expect=expect;self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.fixture=self.root/'fixture.wav'
        with wave.open(str(self.fixture),'wb') as f:f.setnchannels(1);f.setsampwidth(2);f.setframerate(24000);f.writeframes(bytes(24000))
        self.mode='normal';self.entered=threading.Event();self.release=threading.Event()
        owner=self
        class STT:
            name='fault-stt'
            def stream(self,audio,cancelled,request_id):
                list(audio)
                if owner.mode=='fail_stt':raise RuntimeError('private error detail')
                yield Transcript('Test utterance.',True)
        class Text:
            name='fault-text'
            def stream(self,context,cancelled,request_id):
                if owner.mode=='slow_text':owner.entered.set();owner.release.wait(8);yield 'LATE TEXT.'
                elif owner.mode=='fail_text':raise RuntimeError('private error detail')
                else:yield 'Test reply.'
        class TTS:
            name='fault-tts'
            def stream(self,text,cancelled,request_id):
                if owner.mode=='slow_tts':owner.entered.set();owner.release.wait(8)
                if owner.mode=='fail_tts':yield b'\x00\x10'*2000;raise RuntimeError('private error detail')
                for _ in range(24 if owner.mode=='long_audio' else 6):yield b'\x00\x10'*2000
        self.service=VoiceService(str(self.root/'state.db'),factory=lambda filename,partial:(STT(),Text(),TTS(),None,None))
        listener=socket.socket();listener.bind(('127.0.0.1',0));port=listener.getsockname()[1]
        self.server=uvicorn.Server(uvicorn.Config(create_app(service=self.service),log_level='error'))
        self.thread=threading.Thread(target=lambda:self.server.run(sockets=[listener]),daemon=True);self.thread.start()
        deadline=time.monotonic()+10
        while not self.server.started:
            if time.monotonic()>deadline:raise RuntimeError('test server unavailable')
            time.sleep(.02)
        self.pw=sync_playwright().start();options={'headless':True,'args':['--autoplay-policy=no-user-gesture-required']}
        if os.environ.get('VOICE_CHROME_PATH'):options['executable_path']=os.environ['VOICE_CHROME_PATH']
        self.browser=self.pw.chromium.launch(**options);self.context=self.browser.new_context()
        self.page=self.context.new_page();self.errors=[];self.page.on('pageerror',lambda e:self.errors.append(str(e)))
        self.url=f'http://127.0.0.1:{port}';self.page.goto(self.url)
        expect(self.page.locator('#record')).to_be_enabled()
        self.sid=self.page.evaluate("()=>localStorage.getItem('voice-session')")
        self.c=self.service.session(self.sid)
    def tearDown(self):
        self.release.set()
        self.browser.close();self.pw.stop();self.server.should_exit=True;self.thread.join(12);self.tmp.cleanup()
    def upload(self,mode):
        self.mode=mode;self.page.set_input_files('#file',str(self.fixture))
    def idle(self):
        deadline=time.monotonic()+5
        while self.sid in self.service.active:
            if time.monotonic()>deadline:self.fail('worker/slot not released')
            self.page.wait_for_timeout(20)
    def record(self,name,**data):
        self.assertEqual(self.errors,[])
        self.results.append({'name':name,'passed':True,**data})
    def stopped_phase(self,mode):
        self.upload(mode)
        deadline=time.monotonic()+5
        while not self.entered.is_set():
            if time.monotonic()>deadline:self.fail('provider phase not reached')
            self.page.wait_for_timeout(10)
        before=self.c.pipeline.sessions.get(self.sid)['epoch'];start=time.perf_counter()
        self.page.click('#interrupt');self.expect(self.page.locator('#status')).to_have_text('已停止')
        elapsed=(time.perf_counter()-start)*1000
        self.release.set();self.idle();self.page.wait_for_timeout(100)
        self.assertGreater(self.c.pipeline.sessions.get(self.sid)['epoch'],before)
        self.assertNotIn('LATE',self.page.locator('#answer').inner_text())
        self.assertEqual(self.page.evaluate('()=>sources.size'),0)
        self.assertEqual(self.c.native.stats()['playback_bytes'],0)
        self.assertEqual(self.c.pipeline.context(branch='main')['responses'],[])
        self.upload('normal');self.expect(self.page.locator('#status')).to_have_text('回复结束，可以继续说',timeout=10000)
        self.record(mode,click_to_stop_status_ms=elapsed)
    def test_stop_during_llm_generation(self):self.stopped_phase('slow_text')
    def test_stop_during_tts_generation(self):self.stopped_phase('slow_tts')
    def test_stop_during_playback(self):
        self.upload('long_audio');self.expect(self.page.locator('#status')).to_have_text('正在播放',timeout=10000)
        self.page.click('#interrupt');self.expect(self.page.locator('#status')).to_have_text('已停止')
        self.idle();self.assertEqual(self.page.evaluate('()=>sources.size'),0)
        self.assertEqual(self.c.pipeline.context(branch='main')['responses'],[])
        self.record('stop_playback_no_phantom_ack')
    def test_switch_branch_while_generating(self):
        self.page.evaluate("()=>api('/api/control',{action:'fork',branch:'child'})")
        self.page.reload();self.expect(self.page.locator('#record')).to_be_enabled()
        self.upload('slow_text')
        self.expect(self.page.locator('#status')).to_have_text('正在思考…')
        self.expect(self.page.locator('#branch')).to_be_enabled(timeout=1500)
        self.page.select_option('#branch','child');self.release.set();self.idle()
        self.expect(self.page.locator('#branch')).to_have_value('child')
        self.page.wait_for_timeout(100)
        self.assertEqual(self.c.pipeline.sessions.get(self.sid)['branch'],'child')
        self.assertNotIn('LATE',self.page.locator('#answer').inner_text())
        self.assertEqual(self.c.pipeline.context(branch='child')['recent'],[])
        self.record('active_branch_switch_isolated')
    def test_refresh_during_generation(self):
        self.upload('slow_text');self.expect(self.page.locator('#status')).to_have_text('正在思考…')
        self.page.reload();self.expect(self.page.locator('#record')).to_be_enabled()
        self.release.set();self.idle();self.page.wait_for_timeout(100)
        self.assertEqual(self.page.evaluate('()=>sources.size'),0)
        self.assertEqual(self.c.pipeline.context(branch='main')['responses'],[])
        self.upload('normal');self.expect(self.page.locator('#status')).to_have_text('回复结束，可以继续说',timeout=10000)
        self.record('refresh_inflight_then_resume')
    def test_offline_request_recovers(self):
        self.context.set_offline(True);self.upload('normal')
        self.expect(self.page.locator('#record')).to_be_enabled(timeout=5000)
        self.context.set_offline(False)
        self.upload('normal');self.expect(self.page.locator('#status')).to_have_text('回复结束，可以继续说',timeout=10000)
        self.record('offline_then_retry')
    def test_disconnect_inflight_releases_slot(self):
        self.upload('slow_tts');self.expect(self.page.locator('#answer')).to_have_text('Test reply.')
        self.page.evaluate('()=>controller.abort()');self.release.set();self.idle()
        self.expect(self.page.locator('#record')).to_be_enabled()
        self.assertEqual(self.c.pipeline.context(branch='main')['responses'],[])
        self.upload('normal');self.expect(self.page.locator('#status')).to_have_text('回复结束，可以继续说',timeout=10000)
        self.record('fetch_disconnect_then_retry')
    def test_all_provider_failures_recover(self):
        for mode in ('fail_stt','fail_text','fail_tts'):
            self.upload(mode)
            self.expect(self.page.locator('#status')).to_have_text('本轮未完成，请检查连接或稍后重试。',timeout=5000)
            self.idle();self.assertEqual(self.page.evaluate('()=>sources.size'),0)
            self.assertNotIn('private error',self.page.locator('body').inner_text())
        self.upload('normal');self.expect(self.page.locator('#status')).to_have_text('回复结束，可以继续说',timeout=10000)
        self.record('stt_llm_tts_failures_then_retry')
    def test_delayed_ack_and_failed_ack(self):
        self.page.route('**/api/ack',lambda route:route.fulfill(status=503,content_type='application/json',body='{}'))
        self.upload('normal');self.expect(self.page.locator('#status')).to_have_text('播放确认失败，恢复上下文可能缺少回复',timeout=10000)
        self.assertEqual(self.c.pipeline.context(branch='main')['responses'],[])
        self.page.unroute('**/api/ack')
        self.upload('normal');self.expect(self.page.locator('#status')).to_have_text('回复结束，可以继续说',timeout=10000)
        self.record('failed_ack_not_claimed_as_played')
