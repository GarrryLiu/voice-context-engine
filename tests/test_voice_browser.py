"""Headless browser uses fake microphone and providers; no API key or paid calls."""
import json
import math
import os
from pathlib import Path
import struct
import tempfile
import threading
import time
import unittest
import wave


@unittest.skipUnless(os.environ.get('VOICE_BROWSER_TEST') and os.environ.get('VOICE_RUNTIME_LIBRARY'),'opt-in browser and native build required')
class VoiceBrowserTests(unittest.TestCase):
    def test_upload_record_playback_ack_and_responsive_page(self):
        import socket
        import uvicorn
        from playwright.sync_api import sync_playwright,expect
        from voice_context.providers import Transcript
        from voice_context.voice_server import VoiceService,create_app
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);fixture=root/'fixture.wav'
            with wave.open(str(fixture),'wb') as audio:
                audio.setnchannels(1);audio.setsampwidth(2);audio.setframerate(48000);audio.writeframes(bytes(48000*2))
            class STT:
                name='browser-fixture-stt'
                def stream(self,audio,cancelled,request_id):list(audio);yield Transcript('Browser fixture.',True)
            class Text:
                name='browser-fixture-text'
                def stream(self,context,cancelled,request_id):yield 'Browser reply.'
            class TTS:
                name='browser-fixture-tts'
                def stream(self,text,cancelled,request_id):
                    pcm=b''.join(struct.pack('<h',int(1000*math.sin(2*math.pi*440*i/24000))) for i in range(12000))
                    for i in range(0,len(pcm),4096):yield pcm[i:i+4096]
            service=VoiceService(str(root/'state.db'),factory=lambda filename,partial:(STT(),Text(),TTS(),None,None))
            listener=socket.socket();listener.bind(('127.0.0.1',0));port=listener.getsockname()[1]
            server=uvicorn.Server(uvicorn.Config(create_app(service=service),log_level='error'))
            thread=threading.Thread(target=lambda:server.run(sockets=[listener]),daemon=True);thread.start()
            deadline=time.monotonic()+10
            while not server.started:
                if time.monotonic()>deadline:self.fail('server did not start')
                time.sleep(.02)
            try:
                with sync_playwright() as pw:
                    launch={'headless':True,'args':['--use-fake-ui-for-media-stream','--use-fake-device-for-media-stream',
                        '--use-file-for-fake-audio-capture='+str(fixture),'--autoplay-policy=no-user-gesture-required']}
                    if os.environ.get('VOICE_CHROME_PATH'):launch['executable_path']=os.environ['VOICE_CHROME_PATH']
                    browser=pw.chromium.launch(**launch)
                    context=browser.new_context(permissions=['microphone'],viewport={'width':1100,'height':850})
                    page=context.new_page();errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
                    page.goto(f'http://127.0.0.1:{port}')
                    expect(page.locator('#record')).to_be_enabled()
                    page.set_input_files('#file',str(fixture))
                    expect(page.locator('#status')).to_have_text('回复结束，可以继续说',timeout=15000)
                    self.assertEqual(page.locator('#answer').inner_text(),'Browser reply.')
                    session=page.evaluate("()=>localStorage.getItem('voice-session')")
                    c=service.session(session)
                    self.assertEqual(c.pipeline.context(branch='main')['responses'][0]['text'],'Browser reply.')
                    page.click('#record')
                    expect(page.locator('#stop')).to_be_enabled()
                    page.wait_for_timeout(600);page.click('#stop')
                    expect(page.locator('#status')).to_have_text('回复结束，可以继续说',timeout=15000)
                    self.assertEqual(len(c.pipeline.transcripts.recent('main')),2)
                    page.reload();expect(page.locator('#record')).to_be_enabled()
                    expect(page.locator('#answer')).to_have_text('Browser reply.')
                    page.set_viewport_size({'width':390,'height':844})
                    self.assertTrue(page.evaluate('()=>document.documentElement.scrollWidth <= innerWidth'))
                    if os.environ.get('VOICE_SCREENSHOT'):page.screenshot(path=os.environ['VOICE_SCREENSHOT'],full_page=True)
                    self.assertEqual(errors,[])
                    browser.close()
            finally:
                server.should_exit=True;thread.join(10)
