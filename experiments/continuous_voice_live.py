"""Opt-in real API experiment. Supply a synthetic mono 24 kHz PCM16 WAV."""
import argparse,hashlib,json,os,socket,struct,tempfile,threading,time,wave
from pathlib import Path
import uvicorn
from playwright.sync_api import sync_playwright,expect
from voice_context.voice_server import create_app
parser=argparse.ArgumentParser();parser.add_argument('--input',required=True);parser.add_argument('--expected',default='北极星');parser.add_argument('--output',default='experiments/continuous-voice-live-results.json')
args=parser.parse_args();source=Path(args.input)
source_hashes={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in [*Path('src/voice_context').glob('*.py'),*Path('src/voice_context/web').glob('*')]}
with tempfile.TemporaryDirectory() as folder:
 fixture=Path(folder)/'chinese-live.wav'
 with wave.open(str(source),'rb') as f:
  if (f.getframerate(),f.getnchannels(),f.getsampwidth())!=(24000,1,2):raise ValueError('24k mono PCM16 WAV required')
  pcm=f.readframes(f.getnframes())
 samples=struct.unpack('<'+'h'*(len(pcm)//2),pcm)
 with wave.open(str(fixture),'wb') as f:
  f.setnchannels(1);f.setsampwidth(2);f.setframerate(48000)
  f.writeframes(bytes(48000)+b''.join(struct.pack('<hh',x,x) for x in samples)+bytes(48000*40))
 app=create_app(str(Path(folder)/'live.db'))
 listener=socket.socket();listener.bind(('127.0.0.1',0));port=listener.getsockname()[1]
 server=uvicorn.Server(uvicorn.Config(app,log_level='error',ws_max_size=16384,ws_max_queue=8))
 thread=threading.Thread(target=lambda:server.run(sockets=[listener]),daemon=True);thread.start()
 try:
  deadline=time.monotonic()+10
  while not server.started:
   if time.monotonic()>deadline:raise TimeoutError('server')
   time.sleep(.02)
  with sync_playwright() as pw:
   browser=pw.chromium.launch(**({'executable_path':os.environ['VOICE_CHROME_PATH']} if os.environ.get('VOICE_CHROME_PATH') else {}),headless=True,args=['--use-fake-ui-for-media-stream','--use-fake-device-for-media-stream','--use-file-for-fake-audio-capture='+str(fixture),'--autoplay-policy=no-user-gesture-required'])
   try:
    page=browser.new_page();timeline=[];errors=[];started=time.perf_counter()
    def incoming(event):
     try:
      data=json.loads(event)
      if data.get('type') in ('ready','partial','transcript','error','speech_started'):timeline.append({'type':data['type'],'seconds':round(time.perf_counter()-started,3),**({'text':data['text']} if data.get('text') else {})})
     except Exception:pass
    page.on('websocket',lambda ws:ws.on('framereceived',incoming));page.on('pageerror',lambda e:errors.append(type(e).__name__))
    page.goto('http://127.0.0.1:'+str(port));expect(page.locator('#record')).to_be_enabled()
    started=time.perf_counter();page.click('#live')
    expect(page.locator('#status')).to_have_text('回复结束，可以继续说',timeout=60000)
    result={'protocol':'one synthetic Chinese microphone fixture, real live STT/text LLM/TTS and headless WebAudio ACK; software timings only',
      'model':'gpt-live-transcribe','timeline':timeline,'transcript':page.locator('#transcript').inner_text(),'answer':page.locator('#answer').inner_text(),
      'first_schedule_after_final_seconds':page.locator('#first').inner_text(),'generation_after_final_seconds':page.locator('#total').inner_text(),
      'complete_after_click_seconds':round(time.perf_counter()-started,3),'browser_errors':errors}
    sid=page.evaluate("()=>localStorage.getItem('voice-session')");state=app.state.voice.state(sid);result['acknowledged_segments']=len(state['responses'])
    page.click('#live');expect(page.locator('#status')).to_have_text('连续对话已结束')
    deadline=time.monotonic()+5
    while sid in app.state.voice.live_sessions and time.monotonic()<deadline:page.wait_for_timeout(25)
    c=app.state.voice.session(sid)
    with c.lock:
     result['audit']=[dict(r) for r in c.pipeline.engine.db.execute('SELECT model,state,usage,error_code FROM model_calls ORDER BY started')]
    result['source_hashes']=source_hashes
    result['expected_present']=args.expected in result['answer'] and args.expected in result['transcript']
    result['single_turn']=len([e for e in timeline if e['type']=='transcript'])==1
    Path(args.output).write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k not in ('source_hashes','audit')},ensure_ascii=False))
    assert result['expected_present'] and result['single_turn'] and not errors and result['acknowledged_segments']>0
   finally:browser.close()
 finally:server.should_exit=True;thread.join(10)
