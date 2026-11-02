"""Synthetic provider/control-plane experiments; no real speech or billed models."""
import argparse
import hashlib
import json
import platform
import statistics
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from voice_context.conversation import Conversation,Transcript


class STT:
    name='scripted-stt-v1'
    def stream(self,audio,cancelled,request_id):
        list(audio);yield Transcript('partial',False);yield Transcript('remember plan: Continue',True)
class Text:
    name='scripted-text-v1'
    def stream(self,context,cancelled,request_id):
        time.sleep(.001);yield 'Continue.'
class TTS:
    name='scripted-tts-v1'
    def stream(self,text,cancelled,request_id):
        time.sleep(.001);yield text.encode() # synthetic payload, NOT a PCM waveform


def stats(values):
    values=sorted(values)
    import math
    return {'samples':len(values),'median_ms':statistics.median(values)*1000,'p95_ms':values[math.ceil(.95*len(values))-1]*1000}


def main():
    p=argparse.ArgumentParser();p.add_argument('--output',default='experiments/realtime-results.json');a=p.parse_args()
    cancel=[];recovery=[];checks={'immediate_context':0,'late_output_rejected':0,'out_of_order_approval_rejected':0,'reconnect_preserved_context':0,'duplicate_outbox_deduplicated':0}
    with tempfile.TemporaryDirectory() as temp:
        for i in range(20):
            path=str(Path(temp)/f'{i}.db');c=Conversation(path,'s',capacity=4096)
            try:
                c.transcribe('turn',STT(),[b'synthetic input'])
                if 'Continue' not in c.pipeline.transcripts.context('main')['text']:raise AssertionError('missing immediate input')
                checks['immediate_context']+=1
                result=c.respond('reply',Text(),TTS());old=result['ticket'];c.render(4)
                start=time.perf_counter();c.interrupt();cancel.append(time.perf_counter()-start)
                if c.receive_audio(old,1,b'late')!=0 or c.render(32)[1]!=0:raise AssertionError('stale playback')
                checks['late_output_rejected']+=1
                c.pipeline.work_once();c.pipeline.approve('transcript:turn',['plan'])
                c.pipeline.submit('old','main','s','remember plan: Old')
                c.pipeline.submit('new','main','s','remember plan: New')
                c.pipeline.work_once();c.pipeline.work_once();c.pipeline.approve('transcript:new',['plan'])
                try:c.pipeline.approve('transcript:old',['plan'])
                except ValueError:checks['out_of_order_approval_rejected']+=1
                else:raise AssertionError('stale memory committed')
                with c.pipeline.engine.db:c.pipeline.engine.db.execute('UPDATE transcript_outbox SET published=0')
                count=c.pipeline.engine.db.execute('SELECT count(*) FROM tasks').fetchone()[0]
                c.pipeline.transcripts.publish(c.pipeline.queue)
                if c.pipeline.engine.db.execute('SELECT count(*) FROM tasks').fetchone()[0]!=count:raise AssertionError('duplicate task')
                checks['duplicate_outbox_deduplicated']+=1
                c.close();start=time.perf_counter();c=Conversation(path,'s',capacity=4096)
                recovery.append(time.perf_counter()-start)
                if c.pipeline.engine.recall('main')[0]['value']!='New' or not c.pipeline.transcripts.recent('main'):raise AssertionError('lost restart state')
                checks['reconnect_preserved_context']+=1
            finally:c.close()
        shared=str(Path(temp)/'concurrent.db')
        clients=[Conversation(shared,f'concurrent-{i}',capacity=4096) for i in range(4)]
        def run(pair):
            i,client=pair;latencies=[]
            for turn in range(10):
                result=client.respond(f'r-{i}-{turn}',Text(),TTS());latencies.append(result['first_audio_queued_seconds']);client.render(4096)
            return latencies
        try:
            with ThreadPoolExecutor(max_workers=4) as pool:latencies=[value for batch in pool.map(run,enumerate(clients)) for value in batch]
            ledger=[dict(r) for c in clients for r in c.pipeline.engine.db.execute('SELECT * FROM stage_calls WHERE reply IN (SELECT id FROM replies WHERE session=?)',(c.session,))]
        finally:
            for c in clients:c.close()
    report={'kind':'synthetic_staged_control_validation','platform':platform.platform(),'trials':20,'correctness_counts':checks,
            'queue_clear_with_sqlite_ms':stats(cancel),'reopen_with_context_ms':stats(recovery),
            'four_session_first_synthetic_chunk_queued_ms':stats(latencies),'concurrent_requests':40,
            'observations_seconds':{'queue_clear':cancel,'reopen':recovery,'four_session_first_chunk':latencies},
            'experiment_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            'declared_stage_units_total':sum(x['reserved'] for x in ledger),
            'declared_stage_units_by_phase':{stage:sum(x['reserved'] for x in ledger if x['stage']==stage) for stage in ('stt','reason','tts')},
            'source_sha256':{name:hashlib.sha256(Path(name).read_bytes()).hexdigest() for name in ['native/runtime.hpp','src/voice_context/conversation.py','src/voice_context/sessions.py']},
            'limitations':'Scripted providers with 1ms sleeps and synthetic byte payloads, NOT real STT/LLM/TTS, PCM, speaker latency, billing, semantic evaluation, distributed services or C++ speedup proof. Four clients share local SQLite; only queue/control/recovery software timing is measured.'}
    out=Path(a.output);out.parent.mkdir(parents=True,exist_ok=True);out.write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))


if __name__=='__main__':main()
