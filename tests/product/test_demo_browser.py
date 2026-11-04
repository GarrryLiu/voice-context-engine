import os
from pathlib import Path
import socket
import tempfile
import threading
import time
import unittest


@unittest.skipUnless(os.environ.get('VOICE_BROWSER_TEST'),'opt-in browser required')
class DemoProductBrowserTests(unittest.TestCase):
    def test_standalone_product_flow_without_native_models_or_microphone(self):
        import uvicorn
        from playwright.sync_api import sync_playwright,expect
        from voice_context.server.app import create_app
        with tempfile.TemporaryDirectory() as root:
            app=create_app(str(Path(root)/'demo.db'),mode='demo')
            listener=socket.socket();listener.bind(('127.0.0.1',0));port=listener.getsockname()[1]
            server=uvicorn.Server(uvicorn.Config(app,log_level='error'))
            thread=threading.Thread(target=lambda:server.run(sockets=[listener]),daemon=True);thread.start()
            deadline=time.monotonic()+5
            while not server.started:
                if time.monotonic()>deadline:self.fail('demo server start timeout')
                time.sleep(.02)
            try:
                with sync_playwright() as pw:
                    launch={'headless':True,'args':['--autoplay-policy=no-user-gesture-required']}
                    if os.environ.get('VOICE_CHROME_PATH'):launch['executable_path']=os.environ['VOICE_CHROME_PATH']
                    browser=pw.chromium.launch(**launch)
                    try:
                        page=browser.new_page(viewport={'width':1440,'height':950});errors=[];external=[]
                        page.on('pageerror',lambda error:errors.append(str(error)))
                        page.on('request',lambda request:external.append(request.url) if not request.url.startswith(f'http://127.0.0.1:{port}/') else None)
                        page.add_init_script("""const Original=window.AudioContext;window.AudioContext=class extends Original{constructor(...args){super(...args);if(this.setSinkId)this.setSinkId({type:'none'}).catch(()=>{});}};
                            navigator.mediaDevices.getUserMedia=()=>{throw Error('Demo must not request a microphone');};""")
                        page.goto(f'http://127.0.0.1:{port}/product')
                        expect(page.locator('.demo-mode-banner')).to_contain_text('No model calls')
                        expect(page.locator('.workspace-nav button')).to_have_count(2)
                        expect(page.locator('#new-topic')).to_have_count(0)
                        expect(page.locator('#topic-title')).to_have_text('Talk')
                        page.click('#finish-session');expect(page.locator('#documents-workspace')).to_be_visible()
                        expect(page.locator('#nav-workspace')).to_have_class('selected')
                        page.click('#library-records');expect(page.locator('.graph-node')).to_have_count(0)
                        expect(page.locator('#topics .topic')).to_have_count(0)
                        page.click('#nav-thoughts')
                        page.fill('#demo-text','A workspace for unfinished ideas.');page.click('#demo-send')
                        expect(page.locator('#status')).to_have_text('Reply finished. Ready when you are.',timeout=10000)
                        expect(page.locator('#answer')).to_contain_text('Demo reply:')
                        page.click('#nav-workspace');page.click('#nav-documents')
                        expect(page.locator('.document-row')).to_have_count(1)
                        expect(page.locator('#nav-workspace')).to_have_class('selected')
                        page.click('#nav-thoughts');expect(page.locator('#answer')).to_contain_text('Demo reply:')
                        page.click('#finish-session');expect(page.locator('#talk-outcome')).to_be_visible()
                        expect(page.locator('#outcome-description')).to_contain_text('1 original voice note')
                        expect(page.locator('#outcome-items')).to_contain_text('A workspace for unfinished ideas.')
                        if os.environ.get('VOICE_ENTRY_SCREENSHOT'):
                            page.screenshot(path=os.environ['VOICE_ENTRY_SCREENSHOT'].replace('.png','-outcome.png'),full_page=True)
                        page.click('#outcome-open');expect(page.locator('.graph-node')).to_have_count(1)
                        page.locator('.graph-node').click();expect(page.locator('#graph-edit-content')).to_have_value('A workspace for unfinished ideas.')
                        page.fill('#graph-edit-title','An unfinished idea');page.locator('#graph-editor button[type=submit]').click()
                        expect(page.locator('#graph-notice')).to_contain_text('Saved locally')
                        page.reload();expect(page.locator('.graph-node')).to_have_count(1)
                        expect(page.locator('.graph-node')).to_contain_text('An unfinished idea')
                        page.click('#graph-continue');expect(page.locator('#demo-text')).to_be_visible()
                        page.fill('#demo-text','A second thought.');page.click('#demo-send')
                        expect(page.locator('#status')).to_have_text('Reply finished. Ready when you are.',timeout=10000)
                        page.click('#finish-session');expect(page.locator('#talk-outcome')).to_be_visible()
                        expect(page.locator('#outcome-description')).to_contain_text('2 original voice notes')
                        page.click('#outcome-continue');expect(page.locator('#topic-title')).to_have_text('Talk')
                        expect(page.locator('#active-session-name')).to_contain_text('Continuing:')
                        page.click('#nav-workspace');expect(page.locator('#workspace-recent .continuity-card')).to_have_count(1)
                        page.locator('#workspace-recent .continuity-card button').last.click()
                        expect(page.locator('.graph-node')).to_have_count(2)
                        page.click('#nav-thoughts');page.locator('#topics .topic').first.click()
                        expect(page.locator('#graph-workspace')).to_be_visible()
                        expect(page.locator('.graph-node')).to_have_count(2)
                        if os.environ.get('VOICE_ENTRY_SCREENSHOT'):
                            page.screenshot(path=os.environ['VOICE_ENTRY_SCREENSHOT'],full_page=True)
                            page.click('#nav-thoughts');page.screenshot(path=os.environ['VOICE_ENTRY_SCREENSHOT'].replace('.png','-talk.png'),full_page=True)
                            page.set_viewport_size({'width':390,'height':844});page.wait_for_timeout(250)
                            self.assertTrue(page.evaluate('()=>document.documentElement.scrollWidth<=innerWidth'))
                            page.screenshot(path=os.environ['VOICE_ENTRY_SCREENSHOT'].replace('.png','-mobile.png'),full_page=True)
                        page.click('#nav-thoughts');page.click('#clear-talk-focus')
                        expect(page.locator('#clear-talk-focus')).not_to_be_visible()
                        expect(page.locator('#answer')).to_have_text('Start a conversation.')
                        expect(page.locator('#topics .topic')).to_have_count(1)
                        expect(page.locator('#talk-resume')).to_be_visible()
                        if os.environ.get('VOICE_ENTRY_SCREENSHOT'):
                            page.screenshot(path=os.environ['VOICE_ENTRY_SCREENSHOT'].replace('.png','-entry.png'),full_page=True)
                            page.set_viewport_size({'width':390,'height':844})
                            self.assertTrue(page.evaluate('()=>document.documentElement.scrollWidth<=innerWidth'))
                            page.screenshot(path=os.environ['VOICE_ENTRY_SCREENSHOT'].replace('.png','-entry-mobile.png'),full_page=True)
                        page.locator('#talk-recent .continuity-resume').click()
                        expect(page.locator('#active-session-name')).to_contain_text('Continuing:')
                        page.click('#clear-talk-focus')
                        page.click('#finish-session');expect(page.locator('#documents-workspace')).to_be_visible()
                        page.click('#library-records');expect(page.locator('.graph-node')).to_have_count(1)
                        self.assertEqual(external,[]);self.assertEqual(errors,[])
                    finally:browser.close()
            finally:server.should_exit=True;thread.join(10)
