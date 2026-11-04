"""Deterministic synthetic provider timing through the real C++ coordinator. No API calls."""
import hashlib
import json
import os
from pathlib import Path
import platform
import statistics
import sys
import tempfile
import time
from datetime import datetime, timezone

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from voice_context.conversation import Conversation

FIXTURES=[['First sentence.','Second sentence.','Final sentence.'],
          ['先讨论规划。','然后记录决定。','最后继续学习。'],
          ['A short answer.'],['The value is 42.','Keep the remaining text']]
TEXT_DELAY=.04
TTS_DELAY=.08


def trial(parts,overlap):
    trace=[];start=time.perf_counter()
    def mark(event,**values):trace.append({'event':event,'seconds':time.perf_counter()-start,**values})
    class Text:
        def stream(self,*args):
            for part in parts:
                time.sleep(TEXT_DELAY);mark('text',text=part);yield part
            mark('text_end')
    class TTS:
        def stream(self,text,*args):
            mark('tts_start',text=text)
            time.sleep(TTS_DELAY);mark('audio_available');yield text.encode()
    with tempfile.TemporaryDirectory() as directory:
        conversation=Conversation(str(Path(directory)/'test.db'),'experiment',overlap_text=overlap)
        try:
            start=time.perf_counter()
            result=conversation.respond('reply',Text(),TTS())
            elapsed=time.perf_counter()-start
            audio,n=conversation.render(65536)
            assert audio[:n]==''.join(parts).encode(), 'audio sequence mismatch'
            times=[e['seconds'] for e in trace if e['event']=='audio_available']
            return {'overlap':overlap,'first_audio_seconds':times[0],
                    'completion_seconds':elapsed,'tts_requests':len(times),
                    'audio_arrival_intervals_seconds':[b-a for a,b in zip(times,times[1:])],
                    'exact_output':True,'trace':trace}
        finally:conversation.close()


def main():
    os.environ.setdefault('VOICE_RUNTIME_LIBRARY',str(ROOT/'build/libvoice_runtime.so'))
    samples=[]
    for fixture_id,parts in enumerate(FIXTURES):
        for repeat in range(3):
            for overlap in ([False,True] if repeat%2==0 else [True,False]):
                sample=trial(parts,overlap)
                sample.update(fixture=fixture_id,repeat=repeat);samples.append(sample)
    summary={}
    for overlap in (False,True):
        rows=[x for x in samples if x['overlap']==overlap]
        summary['overlap' if overlap else 'baseline']={
            'median_first_audio_seconds':statistics.median(x['first_audio_seconds'] for x in rows),
            'median_completion_seconds':statistics.median(x['completion_seconds'] for x in rows),
            'total_tts_requests':sum(x['tts_requests'] for x in rows)}
    paths=['src/voice_context/conversation.py','src/voice_context/text_prefetch.py','native/runtime.cpp','experiments/text_tts_overlap.py']
    result={'created_utc':datetime.now(timezone.utc).isoformat(),'python':platform.python_version(),
            'platform':platform.platform(),'provider':'synthetic delayed text and UTF-8 bytes, not speech',
            'configuration':{'text_delay_seconds':TEXT_DELAY,'tts_delay_seconds':TTS_DELAY,'queue_capacity':4,'repeats':3},
            'fixtures':FIXTURES,'source_sha256':{p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in paths},
            'summary':summary,'samples':samples,
            'limits':['No real TTS, acoustic quality, playback gaps, API cost or GPU throughput measured.',
                      'Fixed synthetic sleeps model serialized provider consumption, not remote LLM generation.',
                      'Remote providers may already generate and buffer text while the client is busy.',
                      'First audio is provider availability, not physical speaker onset.']}
    output=ROOT/'experiments/text-tts-overlap-results.json'
    output.write_text(json.dumps(result,indent=2,ensure_ascii=False)+'\n')
    print(json.dumps(summary,indent=2))
    print(output)

if __name__=='__main__':main()
