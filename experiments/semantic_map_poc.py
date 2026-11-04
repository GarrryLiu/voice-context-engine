"""Opt-in real-model UI experiment, synthetic sources and isolated database.
PYTHONPATH=src .venv/bin/python experiments/semantic_map_poc.py --env-file ../voice-context-engine/.env
"""
import argparse
import json
import socket
import tempfile
import threading
import time
from pathlib import Path
import uvicorn
from playwright.sync_api import sync_playwright,expect
from voice_context.server.app import create_app
from voice_context.server.map_provider import OpenAIMapProvider,INSTRUCTIONS
from voice_context.product.semantic_maps import validate_map,normalize_map
import hashlib

ROOT=Path(__file__).resolve().parent

def main():
    p=argparse.ArgumentParser();p.add_argument('--env-file',required=True);p.add_argument('--refresh-model',action='store_true');args=p.parse_args()
    fixture=json.loads((ROOT/'fixtures/long-talk-map.json').read_text());provider=OpenAIMapProvider(args.env_file)
    sources=[{'id':f's{i+1}','text':turn['text']} for i,turn in enumerate(fixture['turns'])]
    digest=hashlib.sha256((INSTRUCTIONS+json.dumps(sources,ensure_ascii=False)).encode()).hexdigest()
    cache=ROOT/'semantic-map-model-output.json'
    recorded=json.loads(cache.read_text()) if cache.exists() and not args.refresh_model else None
    if recorded is None or recorded['input_hash']!=digest:
        print('Requesting real model extraction; output will be saved before browser checks.',flush=True)
        value=provider.extract(sources)
        recorded={'input_hash':digest,'model_call':provider.last_call,'proposal':value}
        cache.write_text(json.dumps(recorded,ensure_ascii=False,indent=2)+'\n')
    validate_map(normalize_map(recorded['proposal']),sources)
    print('Real extraction saved and source-validated. Starting browser replay.',flush=True)
    class RecordedProvider:
        def extract(self,current_sources):
            if current_sources!=sources:raise ValueError('Replay sources changed')
            return recorded['proposal']
    replay=RecordedProvider()
    with tempfile.TemporaryDirectory() as folder:
        app=create_app(str(Path(folder)/'map.db'),mode='demo',map_provider=replay)
        listener=socket.socket();listener.bind(('127.0.0.1',0));port=listener.getsockname()[1]
        server=uvicorn.Server(uvicorn.Config(app,log_level='error'));thread=threading.Thread(target=lambda:server.run(sockets=[listener]),daemon=True);thread.start()
        deadline=time.monotonic()+10
        while not server.started:
            if time.monotonic()>deadline:raise RuntimeError('server timeout')
            time.sleep(.02)
        try:
            with sync_playwright() as pw:
                browser=pw.chromium.launch(executable_path='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',headless=True,args=['--autoplay-policy=no-user-gesture-required'])
                try:
                    page=browser.new_page(viewport={'width':1600,'height':1050});errors=[]
                    page.on('pageerror',lambda e:errors.append(str(e)))
                    page.add_init_script("""const Original=window.AudioContext;window.AudioContext=class extends Original{constructor(...args){super(...args);if(this.setSinkId)this.setSinkId({type:'none'}).catch(()=>{});}};navigator.mediaDevices.getUserMedia=()=>{throw Error('No microphone');};""")
                    page.goto(f'http://127.0.0.1:{port}/product');expect(page.locator('.demo-mode-banner')).to_contain_text('real model')
                    for turn in fixture['turns']:
                        page.wait_for_function('()=>!window.voiceRuntime.busy && !document.getElementById("demo-send").disabled')
                        page.fill('#demo-text',turn['text']);page.click('#demo-send');expect(page.locator('#transcript')).to_have_text(turn['text'])
                        page.wait_for_function('()=>!window.voiceRuntime.busy && !document.getElementById("demo-send").disabled')
                    print('24 turns captured; replaying the saved model result through proposal API.',flush=True)
                    page.click('#finish-session')
                    expect(page.locator('#map-proposal-apply')).to_be_enabled(timeout=15000)
                    result=page.evaluate("async()=>{const r=await fetch('/api/maps/propose',{method:'POST',headers:{...window.voiceRuntime.headers,'Content-Type':'application/json'},body:JSON.stringify({branch:document.getElementById('branch').value})});if(!r.ok)throw Error('Proposal read failed');return r.json();}")
                    expect(page.locator('#map-proposal-dialog')).to_be_visible()
                    page.screenshot(path='/tmp/semantic-map-proposal.png',full_page=True)
                    page.click('#map-proposal-apply');expect(page.locator('#graph-workspace')).to_be_visible()
                    topics=result['proposal']['topics'];expect(page.locator('.graph-node')).to_have_count(len(topics))
                    page.screenshot(path='/tmp/semantic-map-overview.png',full_page=True)
                    page.locator('.graph-node').first.click();expect(page.locator('.graph-node')).to_have_count(len(topics[0]['nodes']))
                    page.locator('.graph-node').first.click();page.click('#graph-source');expect(page.locator('#map-evidence-dialog')).to_be_visible()
                    evidence_visible=page.locator('#map-evidence-items .outcome-item').count();page.screenshot(path='/tmp/semantic-map-sources.png',full_page=True)
                    page.click('#map-evidence-close');page.click('#graph-close-selection')
                    page.screenshot(path='/tmp/semantic-map-topic.png',full_page=True)
                    page.reload();expect(page.locator('.graph-node')).to_have_count(len(topics[0]['nodes']))
                    double=page.evaluate("async id=>{const r=await fetch('/api/maps/apply',{method:'POST',headers:{...window.voiceRuntime.headers,'Content-Type':'application/json'},body:JSON.stringify({id})});return r.json();}",result['id'])
                    workspace=double['workspace']['data'];nodes=[n for t in topics for n in t['nodes']]
                    report={'mode':'Real model extraction recorded first, then exact-output browser replay; typed synthetic voice input, fixed conversational replies, no live audio','input':{'turns':24,'characters':sum(len(t['text']) for t in fixture['turns'])},'model_call':recorded['model_call'],'observed':{'topics':len(topics),'nodes':len(nodes),'within_topic_edges':sum(len(t['edges']) for t in topics),'cross_topic_edges':len(result['proposal']['links']),'states':{s:sum(n['state']==s for n in nodes) for s in ['confirmed','superseded','tentative','open','noted']},'evidence_spans':sum(len(n['evidence']) for n in nodes),'all_quotes_validated':True,'source_dialog_items':evidence_visible,'reload_persisted':True,'duplicate_apply_idempotent':double['already_applied'],'browser_errors':errors},'proposal':result['proposal'],'limitations':['One synthetic conversation; not a general quality estimate.','Exact quote validation proves source existence, not semantic entailment.','No live STT/TTS or commute/background audio test.','Generated topics share the original conversation branch; topic-isolated runtime context is not implemented.','New suggestions append topics, not merge semantic updates into existing maps.']}
                    (ROOT/'semantic-map-poc-results.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
                    print(json.dumps({k:v for k,v in report.items() if k!='proposal'},ensure_ascii=False,indent=2))
                    if errors:raise RuntimeError('Browser errors')
                finally:browser.close()
        finally:server.should_exit=True;thread.join(10)

if __name__=='__main__':main()
