"""Isolated real Kafka/PostgreSQL poison-message recovery experiment. No models."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import time
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from voice_context.broker import KafkaIntake, KafkaRelay, InvalidEvent
from voice_context.gateway import Pipeline


def run(bootstrap, dsn):
    import psycopg
    from psycopg import sql
    from confluent_kafka import Producer
    from confluent_kafka.admin import AdminClient, NewTopic
    suffix = uuid.uuid4().hex
    schema, topic, group = 'recovery_' + suffix, 'recovery-' + suffix, 'recovery-' + suffix
    admin = AdminClient({'bootstrap.servers': bootstrap})
    pipeline = intake = None
    topic_created = False
    with psycopg.connect(dsn, autocommit=True) as db:
        db.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(schema)))
    try:
        for future in admin.create_topics([NewTopic(topic, num_partitions=1, replication_factor=1)]).values():
            future.result(15)
        topic_created = True
        scoped = dsn + ('&' if '?' in dsn else '?') + 'options=-csearch_path%3D' + schema
        pipeline = Pipeline(scoped, publish_on_submit=False)
        pipeline.engine.fork('main')
        producer = Producer({'bootstrap.servers': bootstrap})
        delivered = []
        producer.produce(topic, key=b'bad', value=b'broken-json',
                         on_delivery=lambda error, msg: delivered.append(error))
        if producer.flush(10) or delivered != [None]:raise RuntimeError('fixture delivery failed')
        pipeline.submit('good', 'main', 'synthetic', 'remember storage: PostgreSQL')
        KafkaRelay(bootstrap, topic).publish(pipeline)

        def receive(callback=None):
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                if intake.once(pipeline, timeout=.2, before_commit=callback):return
            raise TimeoutError('no record received')

        # Baseline: restart the consumer exactly as the worker does after failure.
        blocked = 0
        for _ in range(3):
            intake = KafkaIntake(bootstrap, group, topic)
            try:
                receive()
                raise AssertionError('baseline unexpectedly accepted poison')
            except InvalidEvent:
                blocked += 1
            finally:
                intake.close();intake = None
        assert pipeline.queue.db.execute('SELECT count(*) FROM tasks').fetchone()[0] == 0

        # Crash between durable quarantine and offset commit, then replay.
        intake = KafkaIntake(bootstrap, group, topic, quarantine_invalid=True)
        def crash():raise RuntimeError('injected_crash')
        try:
            receive(crash)
            raise AssertionError('fault was not injected')
        except RuntimeError as error:
            assert str(error) == 'injected_crash'
        intake.close();intake = None
        pipeline.close();pipeline = Pipeline(scoped, publish_on_submit=False)
        started = time.monotonic()
        intake = KafkaIntake(bootstrap, group, topic, quarantine_invalid=True)
        receive()  # Replay of the quarantined offset.
        receive()  # The valid record previously blocked behind it.
        recovered = time.monotonic() - started
        quarantined = pipeline.engine.db.execute('SELECT count(*) FROM kafka_quarantine').fetchone()[0]
        tasks = pipeline.queue.db.execute('SELECT count(*) FROM tasks').fetchone()[0]
        assert quarantined == 1 and tasks == 1
        assert pipeline.queue.run_once(lambda task: pipeline.router.extract(task['payload']['text']))
        assert pipeline.queue.get('transcript:good')['state'] == 'succeeded'
        result = {'baseline_restarts_blocked': blocked, 'baseline_tasks': 0,
                  'quarantine_rows_after_crash_replay': quarantined,
                  'recovered_tasks': tasks, 'recovered_task_state': 'succeeded',
                  'restart_to_two_records_seconds': round(recovered, 4),
                  'broker_source_sha256': hashlib.sha256((Path(__file__).resolve().parents[1] /
                      'src/voice_context/broker.py').read_bytes()).hexdigest(),
                  'scope': 'one synthetic poison + one valid event; local single-partition Kafka and PostgreSQL',
                  'limits': 'Correctness experiment, not throughput, voice latency, or production SLA evidence.'}
        return result
    finally:
        if intake:intake.close()
        if pipeline:pipeline.close()
        if topic_created:
            for future in admin.delete_topics([topic]).values():future.result(15)
        with psycopg.connect(dsn, autocommit=True) as db:
            db.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(schema)))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', default='experiments/kafka-recovery-results.json')
    args = parser.parse_args()
    result = run(os.environ['VOICE_TEST_KAFKA'], os.environ['VOICE_TEST_POSTGRES'])
    Path(args.output).write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))
