"""Recorded chunk-policy trials. --live makes paid TTS calls on public synthetic text."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import sys
import tempfile
import threading
import time
from datetime import datetime,timezone
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from voice_context.conversation import Conversation

FIXTURES=[
 'Before we choose the implementation, let us compare the latency and reliability. Then we can record the decision.',
 '先把我们今天讨论的产品需求整理一下，然后比较不同的实现方案。最后记录下一步需要验证的问题。',
 'Dr. Smith measured 3.14 seconds, which is only one sample. We need more observations before drawing a conclusion.',
 'We should preserve every completed thought, even when the final words have no punctuation']


def trial(text,policy,client=None,model=None,voice=None,delay=.01):
    origin=time.monotonic();trace=[];pcm_bytes=0;calls=0;audio_end=None;gaps=[];seq=0
    def mark(kind,**values):trace.append({'event':kind,'seconds':time.monotonic()-origin,**values})
    def playback(ticket):
        nonlocal seq
        seq+=1;now=time.monotonic()
        return {'epoch':ticket['epoch'],'sequence':seq,'at':now,
                'seconds':max(0.,(audio_end or now)-now)}
    class Text:
        def stream(self,*args):
            for char in text:
                time.sleep(delay);mark('text',characters=1);yield char
    class TTS:
        def stream(self,part,cancel,request_id):
            nonlocal pcm_bytes,calls,audio_end
            calls+=1;mark('tts_start',text=part,request=calls)
            if client:
                from voice_context.audio_providers import OpenAIPcmTTS
                blocks=OpenAIPcmTTS(client,model=model,voice=voice).stream(part,cancel,request_id)
            else:
                def synthetic():
                    time.sleep(.08)
                    yield b'\0\0'*max(1,int(len(part)*.018*24000))
                blocks=synthetic()
            first=True
            try:
                for block in blocks:
                    now=time.monotonic();pcm_bytes+=len(block)
                    if audio_end is not None and now>audio_end:gaps.append(now-audio_end)
                    audio_end=max(now,audio_end or now)+len(block)/48000
                    mark('pcm',bytes=len(block),first_for_request=first)
                    first=False;yield block
            finally:
                if hasattr(blocks,'close'):blocks.close()
    with tempfile.TemporaryDirectory() as directory:
        c=Conversation(str(Path(directory)/'state.db'),'synthetic',capacity=2*1024*1024,
                       max_audio_bytes=2*1024*1024,deadline_seconds=90,overlap_text=True)
        try:
            origin=time.monotonic()
            result=c.respond('trial',Text(),TTS(),chunk_strategy=policy,
                             playback_state=playback if policy=='buffer_aware' else None)
            texts=[x['text'] for x in trace if x['event']=='tts_start']
            assert ''.join(texts)==text
            return {'strategy':policy,'total_seconds':result['total_seconds'],
                    'first_audio_queued_seconds':result['first_audio_queued_seconds'],
                    'tts_requests':calls,'input_characters':sum(map(len,texts)),
                    'output_pcm_bytes':pcm_bytes,'idealized_gap_seconds':sum(gaps),
                    'idealized_gap_count':len(gaps),'exact_text':True,'trace':trace}
        finally:c.close()


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--live',action='store_true');p.add_argument('--env-file',default='.env')
    p.add_argument('--model',default='gpt-4o-mini-tts');p.add_argument('--voice',default='coral')
    p.add_argument('--output');a=p.parse_args()
    os.environ.setdefault('VOICE_RUNTIME_LIBRARY',str(ROOT/'build/libvoice_runtime.so'))
    client=None
    if a.live:
        from voice_context.openai_provider import settings,make_client
        client=make_client(settings(a.env_file))
    rows=[]
    try:
        policies=['sentence','short_first'] if a.live else ['sentence','short_first','buffer_aware']
        for i,text in enumerate(FIXTURES):
            for policy in (policies if i%2==0 else list(reversed(policies))):
                print(f'fixture={i} strategy={policy}',flush=True)
                row=trial(text,policy,client,a.model,a.voice);row['fixture']=i;rows.append(row)
    finally:
        if client:client.close()
    paths=['src/voice_context/chunk_scheduler.py','src/voice_context/conversation.py',
           'src/voice_context/text_prefetch.py','experiments/chunk_strategies.py']
    result={'created_utc':datetime.now(timezone.utc).isoformat(),'live_tts':a.live,
            'model':a.model if a.live else 'synthetic','voice':a.voice if a.live else None,
            'python':platform.python_version(),'platform':platform.platform(),
            'configuration':{'text_character_delay_seconds':.01,'min_chars':12,'max_wait_seconds':.6,
                             'max_chars':1600,'feedback_ttl_seconds':1.,'initial_tts_estimate_seconds':.25,
                             'repetitions':1,'playback':'idealized PCM duration, not browser feedback'},
            'source_sha256':{f:hashlib.sha256((ROOT/f).read_bytes()).hexdigest() for f in paths},
            'fixtures':FIXTURES,'samples':rows,
            'limits':['Single trial per fixture/strategy; no statistical performance claim.',
                      'PCM duration model excludes browser/network/decode buffering and is not audible-gap measurement.',
                      'No acoustic quality rating. Character/byte counts are not billed cost.',
                      'Fixed text replay is not real LLM generation; buffer-aware uses simulated feedback only.']}
    path=Path(a.output) if a.output else ROOT/'experiments'/('chunk-strategies-live.json' if a.live else 'chunk-strategies-simulated.json')
    path.write_text(json.dumps(result,indent=2,ensure_ascii=False)+'\n')
    print(path)

if __name__=='__main__':main()
