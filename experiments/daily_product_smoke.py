"""Explicit paid local-beta smoke: synthetic speech, real providers, isolated DB."""
import argparse
import json
import os
from pathlib import Path
import socket
import tempfile
import threading
import time
import uvicorn
from playwright.sync_api import sync_playwright, expect
from voice_context.server.app import create_app


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('fixture');p.add_argument('--env-file',required=True)
    p.add_argument('--output',default='experiments/daily-product-smoke-results.json')
    args=p.parse_args();errors=[];started=time.monotonic()
    with tempfile.TemporaryDirectory() as root:
        app=create_app(str(Path(root)/'test.db'),env_file=args.env_file)
        sock=socket.socket();sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
        server=uvicorn.Server(uvicorn.Config(app,log_level='error'))
        thread=threading.Thread(target=lambda:server.run(sockets=[sock]),daemon=True);thread.start()
        while not server.started:
            if time.monotonic()-started>10:raise RuntimeError('startup timeout')
            time.sleep(.05)
        try:
            with sync_playwright() as pw:
                browser=pw.chromium.launch(headless=True,executable_path=os.environ.get('VOICE_CHROME_PATH'),args=['--autoplay-policy=no-user-gesture-required'])
                try:
                    page=browser.new_page(viewport={'width':1440,'height':1000});page.on('pageerror',lambda e:errors.append(str(e)))
                    page.add_init_script("const Native=window.AudioContext;window.AudioContext=class extends Native{constructor(...args){super(...args);if(this.setSinkId)this.setSinkId({type:'none'}).catch(()=>{});}}")
                    page.goto(f'http://127.0.0.1:{port}/product');expect(page.locator('#record')).to_be_enabled()
                    page.set_input_files('#file',args.fixture)
                    expect(page.locator('#status')).to_have_text('Reply finished. Ready when you are.',timeout=120000)
                    transcript=page.locator('#transcript').inner_text();answer=page.locator('#answer').inner_text()
                    page.click('#finish-session');expect(page.locator('#map-proposal-apply')).to_be_enabled(timeout=150000)
                    topics=page.locator('.map-topic-preview').count();page.click('#map-proposal-apply')
                    expect(page.locator('.graph-node')).to_have_count(topics)
                    page.locator('.graph-node').first.click();nodes=page.locator('.graph-node').count()
                    page.locator('.graph-node').first.click();page.click('#map-document-source')
                    expect(page.locator('#map-evidence-items')).not_to_be_empty()
                    page.click('#map-evidence-close');page.click('#map-document-close');page.reload();expect(page.locator('.graph-node')).to_have_count(nodes)
                    page.screenshot(path='/tmp/daily-product-smoke.png',full_page=True)
                    checks={'speech_transcribed':'cedar' in transcript.lower(),'model_replied':'cedar' in answer.lower(),'map_saved':topics>0 and nodes>0,'no_browser_errors':not errors}
                    result={'protocol':'Synthetic speech upload; real STT, text, TTS and map model; headless WebAudio ended ACK; temporary database. Not a hardware microphone/speaker or commute evaluation.','checks':checks,'passed':all(checks.values()),'topics':topics,'nodes_in_first_topic':nodes,'seconds':round(time.monotonic()-started,2),'map_call':app.state.maps.provider.last_call,'transcript':transcript,'answer':answer,'browser_errors':errors}
                    Path(args.output).write_text(json.dumps(result,indent=2,ensure_ascii=False)+'\n');print(json.dumps(result,ensure_ascii=False))
                    if not result['passed']:raise SystemExit(1)
                finally:browser.close()
        finally:server.should_exit=True;thread.join(10)


if __name__=='__main__':main()
