"""Real-service correctness and raw context timing study, isolated schema/topic.

Optional restarts affect the project's Compose services: use a disposable local
stack, never a shared deployment. No live model calls or speech latency claims.
"""
import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import subprocess
import time
import uuid
from urllib.parse import quote
import psycopg
from psycopg import sql
from confluent_kafka.admin import AdminClient, NewTopic
from voice_context.gateway import Pipeline
from voice_context.broker import KafkaRelay, KafkaIntake


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', default='experiments/infrastructure-results.json')
    parser.add_argument('--restart-services', action='store_true')
    args = parser.parse_args()
    dsn = os.environ['VOICE_TEST_POSTGRES']; bootstrap = os.environ['VOICE_TEST_KAFKA']; redis_url = os.environ['VOICE_TEST_REDIS']
    identity = uuid.uuid4().hex
    schema, topic = 'experiment_'+identity, 'experiment-'+identity
    with psycopg.connect(dsn, autocommit=True) as db:db.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(schema)))
    scoped = dsn + ('&' if '?' in dsn else '?') + 'options=' + quote('-csearch_path='+schema)
    admin = AdminClient({'bootstrap.servers':bootstrap})
    for f in admin.create_topics([NewTopic(topic, num_partitions=1, replication_factor=1)]).values():f.result(15)
    result = {'protocol':'local single-node real PostgreSQL/Kafka/Redis; no models or speech',
              'service_restarts':args.restart_services, 'checks':{}, 'timings_ms':{},
              'clients':{k:importlib.metadata.version(k) for k in ('psycopg','confluent-kafka','redis')},
              'source_hashes':{str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in Path('src/voice_context').glob('*.py')}}
    p = Pipeline(scoped, publish_on_submit=False, redis_url=redis_url)
    def check(name, condition):
        result['checks'][name] = bool(condition)
        if not condition:raise AssertionError(name)
    def consume(intake, target, hook=None):
        n=0;deadline=time.monotonic()+20
        while n<target and time.monotonic()<deadline:n+=bool(intake.once(p, before_commit=hook))
        return n
    try:
        p.engine.fork('main')
        start=time.perf_counter();p.submit('a','main','s','remember storage: PostgreSQL')
        result['timings_ms']['submit']=(time.perf_counter()-start)*1000
        check('immediate_context_before_kafka', 'PostgreSQL' in p.context(branch='main')['text'] and p.queue.db.execute('SELECT count(*) FROM tasks').fetchone()[0]==0)
        unavailable = KafkaRelay('127.0.0.1:1', topic, timeout=1)
        try:unavailable.publish(p)
        except RuntimeError:pass
        else:raise AssertionError('unavailable broker unexpectedly accepted')
        unavailable.producer.purge()
        unavailable.producer.flush(1)
        del unavailable
        check('broker_failure_retains_outbox', p.engine.db.execute('SELECT published FROM transcript_outbox').fetchone()[0]==0)
        relay = KafkaRelay(bootstrap, topic)
        relay.publish(p)
        with p.engine.db:p.engine.db.execute('UPDATE transcript_outbox SET published=0')
        relay.publish(p)
        group='experiment-'+identity
        intake=KafkaIntake(bootstrap,group,topic)
        def crash():raise RuntimeError('injected pre-offset crash')
        try:
            try:consume(intake,1,crash)
            except RuntimeError:pass
            else:raise AssertionError('crash point not reached')
        finally:intake.close()
        intake=KafkaIntake(bootstrap,group,topic)
        try:check('replay_after_precommit_crash', consume(intake,2)==2)
        finally:intake.close()
        check('duplicate_messages_one_task', p.queue.db.execute('SELECT count(*) FROM tasks').fetchone()[0]==1)
        task=p.queue.claim(lease_seconds=.01);time.sleep(.02)
        p.close();p=Pipeline(scoped,publish_on_submit=False,redis_url=redis_url)
        check('expired_worker_lease_recovered',p.queue.run_once(lambda t:p.router.extract(t['payload']['text'])))
        check('confirmation_exactly_once_in_database',p.approve('transcript:a',['storage'])['inserted']==1 and p.approve('transcript:a',['storage'])['inserted']==0)
        p.submit('b','main','s','remember storage: obsolete')
        relay.publish(p)
        intake=KafkaIntake(bootstrap,group,topic)
        try:check('next_event_consumed',consume(intake,1)==1)
        finally:intake.close()
        p.queue.run_once(lambda t:p.router.extract(t['payload']['text']))
        p.correct('correction','main','s','storage','revised',1)
        try:p.approve('transcript:b',['storage'])
        except ValueError:check('out_of_order_candidate_rejected',True)
        else:check('out_of_order_candidate_rejected',False)
        first=p.context(branch='main');hits=p.context_cache.hits
        check('redis_hit',first==p.context(branch='main') and p.context_cache.hits==hits+1)
        other=Pipeline(scoped,publish_on_submit=False)
        try:other.submit('c','main','s','new immediate utterance')
        finally:other.close()
        check('cross_process_cache_invalidation','new immediate utterance' in p.context(branch='main')['text'])
        for mode in ('postgres_context','redis_context'):
            samples=[]
            for _ in range(30):
                start=time.perf_counter()
                if mode=='postgres_context':
                    with p.engine.db:p.transcripts.context('main')
                else:p.context(branch='main')
                samples.append((time.perf_counter()-start)*1000)
            result['timings_ms'][mode]={'samples':samples,'p50':sorted(samples)[14],'p95':sorted(samples)[28]}
        if args.restart_services:
            subprocess.run(['docker','compose','stop','redis'],check=True,capture_output=True)
            try:check('redis_process_down_fallback','new immediate utterance' in p.context(branch='main')['text'])
            finally:subprocess.run(['docker','compose','start','redis'],check=True,capture_output=True)
            p.close();p=None
            subprocess.run(['docker','compose','restart','postgres','kafka'],check=True,capture_output=True)
            # Wait for PostgreSQL only; metadata below waits for the broker.
            deadline=time.monotonic()+45
            while True:
                try:
                    with psycopg.connect(scoped,connect_timeout=2):pass
                    break
                except psycopg.Error:
                    if time.monotonic()>deadline:raise
                    time.sleep(.5)
            p=Pipeline(scoped,publish_on_submit=False,redis_url=redis_url)
            check('postgres_restart_preserves_memory',p.engine.recall('main')[0]['value']=='revised')
            deadline=time.monotonic()+45
            while True:
                try:admin.list_topics(timeout=2);break
                except Exception:
                    if time.monotonic()>deadline:raise
                    time.sleep(.5)
            relay=KafkaRelay(bootstrap,topic)
            check('kafka_restart_pending_outbox_published',relay.publish(p)==1)
            intake=KafkaIntake(bootstrap,group,topic)
            try:check('kafka_restart_consumer_resumes',consume(intake,1)==1)
            finally:intake.close()
        result['passed']=True
    except Exception as error:
        result['passed']=False;result['error']=type(error).__name__+': '+str(error)
        raise
    finally:
        Path(args.output).write_text(json.dumps(result,indent=2)+'\n')
        if p:p.close()
        for f in admin.delete_topics([topic]).values():f.result(15)
        with psycopg.connect(dsn,autocommit=True) as db:db.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(schema)))
    print(json.dumps({'passed':result['passed'],'checks':len(result['checks']),'output':args.output}))


if __name__=='__main__':main()
