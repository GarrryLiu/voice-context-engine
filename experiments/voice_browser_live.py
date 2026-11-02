"""Opt-in browser playback verification against the live local voice service."""
import argparse
import json
import os
from pathlib import Path
import time
from playwright.sync_api import sync_playwright,expect


def main():
    p=argparse.ArgumentParser();p.add_argument('fixture');p.add_argument('--url',default='http://127.0.0.1:8765')
    p.add_argument('--output',default='experiments/voice-browser-results.json');p.add_argument('--screenshot',default='/tmp/voice-browser.png')
    args=p.parse_args();errors=[]
    with sync_playwright() as pw:
        options={'headless':True,'args':['--autoplay-policy=no-user-gesture-required']}
        if os.environ.get('VOICE_CHROME_PATH'):options['executable_path']=os.environ['VOICE_CHROME_PATH']
        browser=pw.chromium.launch(**options)
        context=browser.new_context(viewport={'width':1100,'height':850})
        page=context.new_page();page.on('pageerror',lambda e:errors.append(str(e)))
        page.goto(args.url);expect(page.locator('#record')).to_be_enabled()
        started=time.perf_counter();page.set_input_files('#file',args.fixture)
        expect(page.locator('#status')).to_have_text('回复结束，可以继续说',timeout=120000)
        elapsed=time.perf_counter()-started
        transcript=page.locator('#transcript').inner_text();answer=page.locator('#answer').inner_text()
        metrics={k:page.locator('#'+k).inner_text() for k in ('stt','first','total')}
        page.screenshot(path=args.screenshot,full_page=True)
        # Query only this browser session's acknowledged context, server remains authoritative.
        acknowledged=page.evaluate('''async()=>{
          const headers={'X-Voice-Token':document.querySelector('meta[name=voice-token]').content,
              'X-Voice-Session':localStorage.getItem('voice-session')};
          const r=await fetch('/api/state',{headers});return r.json();
        }''')
        result={'protocol':'fixed recording upload in headless Chrome; real STT/LLM/TTS; WebAudio ended ACK, not physical speaker measurement',
                'passed':'cedar' in transcript.lower() and 'cedar' in answer.lower() and any('cedar' in x['text'].lower() for x in acknowledged.get('responses',[])) and not errors,
                'acknowledged_response_segments':len(acknowledged.get('responses',[])),
                'transcript':transcript,'answer':answer,'ui_metrics':metrics,'total_through_browser_ended_seconds':elapsed,
                'browser_errors':errors,'state_epoch':acknowledged['epoch'],
                'source_hashes':{str(f):__import__('hashlib').sha256(f.read_bytes()).hexdigest() for f in Path('src/voice_context').glob('*.py')}}
        browser.close()
    Path(args.output).write_text(json.dumps(result,indent=2,ensure_ascii=False)+'\n')
    print(json.dumps(result,ensure_ascii=False))
    if not result['passed']:raise SystemExit(1)


if __name__=='__main__':main()
