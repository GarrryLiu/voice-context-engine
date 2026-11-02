"""Explicit opt-in live calls on synthetic fixtures; never run automatically in CI."""
import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import tempfile
from threading import Event
import time
import uuid
from urllib.parse import quote
from voice_context.gateway import Pipeline
from voice_context.openai_provider import OpenAITextProvider, OpenAIExtractor, ModelJournal


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--env-file',default='.env')
    parser.add_argument('--output',default='experiments/live-text-results.json')
    parser.add_argument('--postgres',action='store_true',help='isolated schema in VOICE_TEST_POSTGRES')
    args=parser.parse_args()
    temporary=tempfile.TemporaryDirectory();schema=None
    path=str(Path(temporary.name)/'state.db')
    if args.postgres:
        import psycopg
        from psycopg import sql
        dsn=os.environ['VOICE_TEST_POSTGRES'];schema='live_'+uuid.uuid4().hex
        with psycopg.connect(dsn,autocommit=True) as db:db.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(schema)))
        path=dsn+('&' if '?' in dsn else '?')+'options='+quote('-csearch_path='+schema)
    journal=ModelJournal(path)
    provider=OpenAITextProvider.from_env(args.env_file,journal=journal,max_output_tokens=128)
    extractor=OpenAIExtractor(provider.model,provider.client,journal)
    redis_url=os.environ.get('VOICE_TEST_REDIS') if args.postgres else None
    p=Pipeline(path,publish_on_submit=False,redis_url=redis_url)
    result={'model':provider.model,'backend':'postgresql' if args.postgres else 'sqlite','redis':bool(redis_url),
            'protocol':'one trial per synthetic case; real Responses API; no actual STT/TTS or audio device',
            'sdk':importlib.metadata.version('openai'),'cases':[],
            'source_hashes':{str(f):hashlib.sha256(f.read_bytes()).hexdigest() for f in Path('src/voice_context').glob('*.py')}}
    def ask(name,branch,expected):
        tid='question-'+uuid.uuid4().hex
        p.submit(tid,branch,'synthetic','What is the current project codename? Reply with the codename only.')
        answer=''.join(provider.stream(p.context(branch=branch),Event(),name+'-'+uuid.uuid4().hex))
        passed=expected.lower() in answer.lower()
        result['cases'].append({'name':name,'answer':answer,'expected':expected,'passed':passed,'metrics':dict(provider.last_call)})
    try:
        p.engine.fork('main')
        p.submit('decision','main','synthetic','The project codename is RAVEN. We have decided to use it.')
        ask('immediate_before_extraction','main','RAVEN')
        p.engine.fork('child','main')
        p.submit('child-decision','child','synthetic','For this branch, we have changed the project codename to CEDAR.')
        ask('child_branch','child','CEDAR')
        ask('parent_not_polluted','main','RAVEN')
        p.close();p=Pipeline(path,publish_on_submit=False,redis_url=redis_url)
        ask('restart_resume','main','RAVEN')
        p.correct('codename-v1','main','synthetic','project_codename','RAVEN',0)
        p.correct('codename-v2','main','synthetic','project_codename','MAPLE',1)
        ask('confirmed_revision_overrides_history','main','MAPLE')
        for name,text,expected in [
            ('explicit_vs_tentative','We have decided to use PostgreSQL as the primary database. Redis might be useful later.','PostgreSQL'),
            ('no_decision','Should we maybe use Kafka? No decision has been made.',None)]:
            records=extractor.extract(text)
            passed=not records if expected is None else bool(records) and any(expected in r['value'] for r in records) and all('Redis' not in r['value'] for r in records)
            result['cases'].append({'name':name,'input':text,'records':records,'passed':passed,'metrics':dict(extractor.last_call)})
        # Real model through the C++ coordinator, but deliberately synthetic TTS bytes.
        from voice_context.conversation import Conversation
        class ByteTTS:
            name='synthetic-text-bytes-not-speech'
            def stream(self,text,cancelled,request_id):yield text.encode()
        c=Conversation(path,'native-live',publish_on_submit=False,redis_url=redis_url,deadline_seconds=45)
        try:
            c.pipeline.sessions.submit('native-live','native-question','What is the current project codename? Reply with the codename only.',c.pipeline.sessions.get('native-live')['epoch'])
            response=c.respond('native-'+uuid.uuid4().hex,provider,ByteTTS())
            data,n=c.render(65536);answer=data[:n].decode()
            result['cases'].append({'name':'real_llm_native_queue','answer':answer,'passed':'MAPLE' in answer.upper(),
                'metrics':dict(provider.last_call),'first_synthetic_chunk_seconds':response['first_audio_queued_seconds']})
        finally:c.close()
        result['passed']=all(case['passed'] for case in result['cases'])
    except Exception as error:
        # API adapter errors contain class/code only. Never include raw exceptions.
        result['passed']=False;result['error_type']=type(error).__name__
        if provider.last_call:result['last_call']=dict(provider.last_call)
    finally:
        calls=journal.db.execute('SELECT usage FROM model_calls').fetchall()
        known=[json.loads(row['usage']) for row in calls if row['usage']]
        result['usage']={'input_tokens':sum(x['input_tokens'] for x in known),'output_tokens':sum(x['output_tokens'] for x in known),
                         'calls':len(calls),'calls_without_final_usage':sum(row['usage'] is None for row in calls)}
        Path(args.output).write_text(json.dumps(result,indent=2,ensure_ascii=False)+'\n')
        p.close();provider.close();journal.close()
        if schema:
            with psycopg.connect(dsn,autocommit=True) as db:db.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(schema)))
        temporary.cleanup()
    print(json.dumps({'passed':result['passed'],'cases':len(result['cases']),'output':args.output,'usage':result['usage']}))
    if not result['passed']:raise SystemExit(1)


if __name__=='__main__':main()
