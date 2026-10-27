"""Deterministic offline pipeline experiment, not model/audio quality evaluation."""
import argparse
import json
import tempfile
import time
from pathlib import Path
from voice_context.gateway import Pipeline

p=argparse.ArgumentParser()
p.add_argument('--output',default='experiments/end-to-end-results.json')
a=p.parse_args()
with tempfile.TemporaryDirectory() as tmp:
    path=str(Path(tmp)/'experiment.db'); pipeline=Pipeline(path); pipeline.engine.fork('main')
    start=time.perf_counter()
    for i in range(40):
        pipeline.submit(str(i),'main',f'session-{i//10}',f'remember 主题{i}: 决定使用方案{i}')
    duplicates=sum(not pipeline.submit(str(i),'main',f'session-{i//10}',f'remember 主题{i}: 决定使用方案{i}')['accepted'] for i in range(10))
    # Reopen with pending work, then resume extraction from the durable queue.
    pipeline.close(); pipeline=Pipeline(path)
    extracted=0
    while pipeline.work_once(): extracted+=1
    assert pipeline.engine.recall('main')==[]
    for i in range(40): pipeline.approve('transcript:'+str(i),['主题'+str(i)])
    pipeline.close(); pipeline=Pipeline(path)
    recovered=sum(pipeline.engine.recall('main','主题'+str(i),limit=1)[0]['value']==f'决定使用方案{i}' for i in range(40))
    pipeline.engine.fork('child','main')
    for branch,value,tid in [('main','主线新决定','parent-change'),('child','分支新决定','child-change')]:
        pipeline.submit(tid,branch,'session-5','remember 主题0: '+value)
        pipeline.work_once(); pipeline.approve('transcript:'+tid,['主题0'])
    conflict=pipeline.engine.merge('child','main')
    assert not conflict['resolved'] and conflict['applied']==0
    merged=pipeline.engine.merge('child','main',{'主题0':'source'})
    context=pipeline.engine.assemble_context('main','主题0',budget=512)
    assert context['cost']<=512 and context['records'][0]['value']=='分支新决定'
    assert duplicates==10 and extracted==40 and recovered==40 and merged['applied']==1
    report={'kind':'offline_end_to_end','provider':'rules-v1','transcripts':40,
            'duplicate_submissions_deduplicated':duplicates,'tasks_completed_after_restart':extracted,
            'cross_session_exact_key_retrieval_correct':recovered,'retrieval_queries':40,
            'unconfirmed_memory_writes':0,'conflicts_detected':len(conflict['conflicts']),
            'explicit_merge_changes':merged['applied'],'context_cost_bytes':context['cost'],
            'context_budget_bytes':512,'elapsed_seconds':time.perf_counter()-start,
            'limitations':'Explicit remember syntax and synthetic Chinese fixtures; no microphone, live LLM, embeddings or distributed services.'}
    pipeline.close()
out=Path(a.output); out.parent.mkdir(parents=True,exist_ok=True)
out.write_text(json.dumps(report,indent=2,ensure_ascii=False)+'\n'); print(json.dumps(report,indent=2,ensure_ascii=False))
