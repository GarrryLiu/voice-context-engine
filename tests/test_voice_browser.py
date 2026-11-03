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
        self.run_voice_page('/')

    def test_product_topics_playback_restore_and_mobile(self):
        self.run_voice_page('/product')

    def test_product_voice_documents_edit_versions_trash_and_import(self):
        self.run_voice_page('/product',documents=True)

    def run_voice_page(self,route,documents=False):
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
                    page.goto(f'http://127.0.0.1:{port}'+route)
                    expect(page.locator('#record')).to_be_enabled()
                    if route=='/product':
                        expect(page.locator('#welcome h1')).to_contain_text('find their voice')
                        if os.environ.get('VOICE_PRODUCT_SCREENSHOT'):page.screenshot(path=os.environ['VOICE_PRODUCT_SCREENSHOT'],full_page=True)
                        page.click('#help');expect(page.locator('#help-dialog')).to_be_visible();page.click('#close-help')
                        expect(page.locator('#new-topic')).to_be_enabled();page.click('#new-topic')
                        page.fill('#topic-name','我的新产品');page.click('#create-topic')
                        expect(page.locator('#topic-dialog')).not_to_be_visible()
                        expect(page.locator('#topic-title')).to_have_text('我的新产品')
                        branch=page.locator('#branch').input_value()
                        self.assertNotEqual(branch,'main')
                    else:branch='main'
                    page.set_input_files('#file',str(fixture))
                    expect(page.locator('#status')).to_have_text('Reply finished. Ready when you are.' if route=='/product' else '回复结束，可以继续说',timeout=15000)
                    self.assertEqual(page.locator('#answer').inner_text(),'Browser reply.')
                    session=page.evaluate("()=>localStorage.getItem('voice-session')")
                    c=service.session(session)
                    self.assertEqual(c.pipeline.context(branch=branch)['responses'][0]['text'],'Browser reply.')
                    page.click('#record')
                    expect(page.locator('#stop')).to_be_enabled()
                    page.wait_for_timeout(600);page.click('#stop')
                    expect(page.locator('#status')).to_have_text('Reply finished. Ready when you are.' if route=='/product' else '回复结束，可以继续说',timeout=15000)
                    self.assertEqual(len(c.pipeline.transcripts.recent(branch)),2)
                    page.reload();expect(page.locator('#record')).to_be_enabled()
                    expect(page.locator('#answer')).to_have_text('Browser reply.')
                    if route=='/product':
                        expect(page.locator('#topic-title')).to_have_text('我的新产品')
                        self.assertEqual(page.locator('#topics .topic').count(),2)
                        page.get_by_role('button',name='◈ My workspace').click()
                        expect(page.locator('#topic-title')).to_have_text('My workspace')
                        expect(page.locator('#welcome')).to_be_visible()
                        page.get_by_role('button',name='⑂ 我的新产品').click()
                        expect(page.locator('#topic-title')).to_have_text('我的新产品')
                        expect(page.locator('#answer')).to_have_text('Browser reply.')
                        expect(page.locator('a[href="/lab"]').first).to_be_visible()
                    if documents:
                        page.click('#save-reply')
                        expect(page.locator('#documents-workspace')).to_be_visible()
                        expect(page.locator('#document-content')).to_have_value('Browser reply.')
                        self.assertEqual(page.locator('.document-row').count(),3)
                        page.fill('#document-title','Launch memo');page.fill('#document-content','An edited plan from my spoken idea.')
                        page.fill('#document-collection','Product');page.click('#save-document')
                        expect(page.locator('#document-save-state')).to_have_text('v2 · Saved')
                        page.locator('#document-source summary').click()
                        expect(page.locator('#document-source-text')).to_have_text('Browser fixture.')
                        if os.environ.get('VOICE_DOCUMENT_SCREENSHOT'):
                            page.evaluate('()=>window.scrollTo(0,0)');page.wait_for_timeout(200)
                            page.screenshot(path=os.environ['VOICE_DOCUMENT_SCREENSHOT'],full_page=True)
                        page.click('#document-history');expect(page.locator('#document-versions-dialog')).to_be_visible()
                        page.select_option('#document-version-select','1')
                        expect(page.locator('#document-version-preview')).to_contain_text('Browser reply.')
                        page.click('#restore-document-version')
                        expect(page.locator('#document-save-state')).to_have_text('v3 · Saved')
                        expect(page.locator('#document-content')).to_have_value('Browser reply.')
                        with page.expect_download() as download_info:page.click('#export-document')
                        download=download_info.value
                        self.assertTrue(download.suggested_filename.endswith('.md'))
                        self.assertIn('Browser reply.',Path(download.path()).read_text())
                        page.fill('#document-content','Unsaved words')
                        page.click('#nav-thoughts');expect(page.locator('#document-unsaved-dialog')).to_be_visible()
                        page.click('#cancel-document-leave');expect(page.locator('#document-content')).to_have_value('Unsaved words')
                        page.click('#reload-document');page.click('#discard-document-changes')
                        expect(page.locator('#document-content')).to_have_value('Browser reply.')
                        page.click('#archive-document');expect(page.locator('#document-kind-label')).to_have_text('Draft · archived')
                        page.select_option('#document-status-filter','archived');expect(page.locator('.document-row')).to_have_count(1)
                        page.click('#trash-document');expect(page.locator('#document-kind-label')).to_have_text('Draft · trash')
                        page.select_option('#document-status-filter','trash');expect(page.locator('.document-row')).to_have_count(1)
                        page.click('#trash-document');expect(page.locator('#document-kind-label')).to_have_text('Draft · active')
                        page.select_option('#document-status-filter','active')
                        reference=root/'Research.md';reference.write_text('Reference <script>window.docXss=true</script> text.')
                        page.set_input_files('#import-document',str(reference))
                        expect(page.locator('#document-title')).to_have_value('Research')
                        self.assertIsNone(page.evaluate('()=>window.docXss'))
                        expect(page.locator('#document-source-text')).to_have_text(reference.read_text())
                        page.fill('#document-search','Reference');expect(page.locator('.document-row')).to_have_count(1)
                        page.fill('#document-search','');expect(page.locator('.document-row')).to_have_count(4)
                        page.reload();expect(page.locator('#document-title')).to_have_value('Research')
                        expect(page.locator('#document-content')).to_have_value(reference.read_text())
                    page.set_viewport_size({'width':390,'height':844})
                    self.assertTrue(page.evaluate('()=>document.documentElement.scrollWidth <= innerWidth'))
                    if os.environ.get('VOICE_SCREENSHOT'):page.screenshot(path=os.environ['VOICE_SCREENSHOT'],full_page=True)
                    if route=='/product':expect(page.locator('.mobile-lab')).to_be_visible()
                    if documents:
                        self.assertEqual(page.locator('aside.sidebar').count(),1)
                        self.assertEqual(page.locator('.documents-heading').count(),1)
                    if documents and os.environ.get('VOICE_DOCUMENT_SCREENSHOT'):
                        page.evaluate('()=>window.scrollTo(0,0)');page.wait_for_timeout(250)
                        page.screenshot(path=os.environ['VOICE_DOCUMENT_SCREENSHOT'].replace('.png','-mobile.png'),full_page=True)
                    if route=='/product' and os.environ.get('VOICE_PRODUCT_SCREENSHOT'):
                        page.screenshot(path=os.environ['VOICE_PRODUCT_SCREENSHOT'].replace('.png','-mobile.png'),full_page=True)
                    self.assertEqual(errors,[])
                    browser.close()
            finally:
                server.should_exit=True;thread.join(10)
