"""Probe the shipped demo's actual map behavior; no model-quality claims.
Run: PYTHONPATH=src .venv/bin/python experiments/long_talk_map.py
Uses a temporary database, not the user's preview workspace.
"""
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

ROOT=Path(__file__).resolve().parent

def main():
    fixture=json.loads((ROOT/'fixtures/long-talk-map.json').read_text())
    with tempfile.TemporaryDirectory() as folder:
        app=create_app(str(Path(folder)/'probe.db'),mode='demo')
        listener=socket.socket();listener.bind(('127.0.0.1',0));port=listener.getsockname()[1]
        server=uvicorn.Server(uvicorn.Config(app,log_level='error'))
        thread=threading.Thread(target=lambda:server.run(sockets=[listener]),daemon=True);thread.start()
        deadline=time.monotonic()+10
        while not server.started:
            if time.monotonic()>deadline:raise RuntimeError('server did not start')
            time.sleep(.02)
        try:
            with sync_playwright() as pw:
                browser=pw.chromium.launch(executable_path=os.environ.get('VOICE_CHROME_PATH','/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'),headless=True,args=['--autoplay-policy=no-user-gesture-required'])
                try:
                    page=browser.new_page(viewport={'width':1600,'height':1050});errors=[]
                    page.on('pageerror',lambda e:errors.append(str(e)))
                    page.add_init_script("""const Original=window.AudioContext;window.AudioContext=class extends Original{constructor(...args){super(...args);if(this.setSinkId)this.setSinkId({type:'none'}).catch(()=>{});}};navigator.mediaDevices.getUserMedia=()=>{throw Error('No microphone in fixture probe');};""")
                    page.goto(f'http://127.0.0.1:{port}/product')
                    expect(page.locator('#demo-text')).to_be_visible()
                    for turn in fixture['turns']:
                        page.wait_for_function('()=>!window.voiceRuntime.busy && !document.getElementById("demo-send").disabled')
                        page.fill('#demo-text',turn['text']);page.click('#demo-send')
                        expect(page.locator('#transcript')).to_have_text(turn['text'],timeout=15000)
                        expect(page.locator('#status')).to_have_text('Reply finished. Ready when you are.',timeout=15000)
                        page.wait_for_function('()=>!window.voiceRuntime.busy && !document.getElementById("demo-send").disabled')
                    page.click('#finish-session');expect(page.locator('#talk-outcome')).to_be_visible()
                    page.screenshot(path='/tmp/long-talk-outcome.png',full_page=True)
                    page.click('#outcome-open');expect(page.locator('.graph-node')).to_have_count(len(fixture['turns']))
                    workspace=page.evaluate("async()=>{const r=await fetch('/api/workspace',{headers:window.voiceRuntime.headers});if(!r.ok)throw Error('workspace read failed');return r.json();}")
                    records=workspace['data']['sessions'];nodes=[n for r in records for n in r['nodes']]
                    contents=[n['content'] for n in nodes]
                    intact=sum(t['text'] in contents for t in fixture['turns'])
                    page.screenshot(path='/tmp/long-talk-map.png',full_page=True)
                    page.reload();expect(page.locator('.graph-node')).to_have_count(len(fixture['turns']))
                    page.click('#graph-continue');expect(page.locator('#active-session-name')).to_contain_text('Continuing:')
                    report={
                        'mode':'demo; fixed replies; silent audio; no model calls',
                        'input':{'turns':len(fixture['turns']),'characters':sum(len(t['text']) for t in fixture['turns']),'expected_topics':fixture['expected']['topics']},
                        'observed':{'records':len(records),'nodes':len(nodes),'voice_nodes':sum(n['kind']=='voice' for n in nodes),'within_topic_edges':sum(len(r['edges']) for r in records),'cross_topic_edges':len(workspace['data']['links']),'intact_source_turns':intact,'sources_with_ids':sum(bool(n['source']) for n in nodes),'node_kind_counts':{k:sum(n['kind']==k for n in nodes) for k in ['voice','idea','question','decision','document']},'reload_persisted':True,'resume_available':True,'browser_errors':errors},
                        'acceptance':{'source_capture':intact==len(fixture['turns']),'map_persistence_and_resume':True,'semantic_topic_separation':False,'summarized_concept_nodes':False,'relationship_extraction':False,'superseded_decision_identification':False,'uncertainty_classification':False},
                        'interpretation':'The shipped product stores one source node per turn in one branch record. It does not summarize or construct a semantic map. Semantic checks fail because no extraction stage exists, not because a tested LLM failed.',
                        'limitations':['Typed fixture only, no STT/TTS quality or real microphone test.','No model-quality or latency benchmark.','No user workspace modified.'],
                        'screenshots':['/tmp/long-talk-outcome.png','/tmp/long-talk-map.png'],
                    }
                    (ROOT/'long-talk-map-validation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
                    print(json.dumps(report,ensure_ascii=False,indent=2))
                    if intact!=len(fixture['turns']) or errors:raise RuntimeError('source integrity/browser regression')
                finally:browser.close()
        finally:server.should_exit=True;thread.join(10)

if __name__=='__main__':main()
