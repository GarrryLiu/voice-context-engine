"""At-least-once outbox relay and durable Kafka intake.

Kafka carries IDs, not authority or transcript text. The database outbox provides
canonical immutable task payloads; duplicate records cannot cause duplicate tasks.
"""
import argparse
import hashlib
import json
import os
import sys
import time
from .gateway import Pipeline


class InvalidEvent(ValueError):
    """Deterministic envelope error; safe reason code, never message content."""


def decode_event(message):
    raw = message.value()
    if raw is None:
        raise InvalidEvent('empty_event')
    if len(raw) > 16384:
        raise InvalidEvent('oversized_event')
    try:
        event = json.loads(raw)
    except (ValueError, UnicodeError, RecursionError):
        raise InvalidEvent('invalid_json') from None
    if not isinstance(event, dict):
        raise InvalidEvent('invalid_shape')
    if type(event.get('version')) is not int or event['version'] != 1:
        # Unknown versions may become valid after a consumer upgrade.
        raise ValueError('unsupported Kafka version; upgrade consumer before retrying')
    task_id = event.get('task_id')
    if not isinstance(task_id, str) or not task_id:
        raise InvalidEvent('invalid_task_id')
    try:
        encoded = task_id.encode('utf-8')
    except UnicodeError:
        raise InvalidEvent('invalid_task_id') from None
    if message.key() != encoded:
        raise InvalidEvent('key_mismatch')
    return event


def quarantine_event(pipeline, message, scope, reason):
    """Commit an idempotent audit record BEFORE committing the Kafka offset.

    Raw bytes are deliberately not duplicated in the database. Operators can use
    the source coordinates while Kafka retention permits, or republish a corrected
    event from the authoritative outbox. This is not automatic replay.
    """
    identity = json.dumps([scope, message.topic(), message.partition(), message.offset()])
    record_id = hashlib.sha256(identity.encode()).hexdigest()
    raw = message.value() or b''
    with pipeline.engine.db:
        pipeline.engine.db.execute('CREATE TABLE IF NOT EXISTS kafka_quarantine ('
            'id TEXT PRIMARY KEY, scope TEXT NOT NULL, topic TEXT NOT NULL, '
            'partition_id INTEGER NOT NULL, offset_id BIGINT NOT NULL, '
            'reason TEXT NOT NULL, payload_sha256 TEXT NOT NULL, created REAL NOT NULL)')
        pipeline.engine.db.execute('INSERT INTO kafka_quarantine '
            '(id,scope,topic,partition_id,offset_id,reason,payload_sha256,created) '
            'VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(id) DO NOTHING',
            (record_id, scope, message.topic(), message.partition(), message.offset(),
             reason, hashlib.sha256(raw).hexdigest(), time.time()))
    return record_id


class KafkaRelay:
    def __init__(self, bootstrap, topic='voice.extract.v1', timeout=5):
        from confluent_kafka import Producer
        self.topic, self.timeout = topic, timeout
        self.producer = Producer({'bootstrap.servers': bootstrap,
            'enable.idempotence': True, 'acks': 'all', 'message.timeout.ms': int(timeout*1000)})

    def publish(self, pipeline, limit=100):
        rows = pipeline.engine.db.execute('SELECT task_id FROM transcript_outbox WHERE published=0 ORDER BY rowid LIMIT ?', (limit,)).fetchall()
        count = 0
        for row in rows:
            errors = []
            self.producer.produce(self.topic, key=row['task_id'].encode(),
                value=json.dumps({'version': 1, 'task_id': row['task_id']}).encode(),
                on_delivery=lambda error, message: errors.append(error))
            remaining = self.producer.flush(self.timeout + 1)
            if remaining or not errors or errors[0] is not None:
                raise RuntimeError('Kafka delivery unconfirmed; outbox retained')
            # Crash here deliberately permits a duplicate publication on restart.
            with pipeline.engine.db:
                pipeline.engine.db.execute('UPDATE transcript_outbox SET published=1 WHERE task_id=?', (row['task_id'],))
            count += 1
        return count


class KafkaIntake:
    def __init__(self, bootstrap, group='voice-extract-v1', topic='voice.extract.v1', quarantine_invalid=False):
        from confluent_kafka import Consumer
        self.quarantine_invalid = quarantine_invalid
        self.scope = hashlib.sha256(json.dumps([bootstrap, group]).encode()).hexdigest()
        self.consumer = Consumer({'bootstrap.servers': bootstrap, 'group.id': group,
            'enable.auto.commit': False, 'enable.auto.offset.store': False,
            'auto.offset.reset': 'earliest'})
        self.consumer.subscribe([topic])

    def once(self, pipeline, timeout=1, before_commit=None):
        message = self.consumer.poll(timeout)
        if message is None:return False
        if message.error():raise RuntimeError(str(message.error()))
        try:
            event = decode_event(message)
        except InvalidEvent as error:
            if not self.quarantine_invalid:
                raise
            quarantine_event(pipeline, message, self.scope, str(error))
            if before_commit:before_commit()
            self.consumer.commit(message=message, asynchronous=False)
            return True
        row = pipeline.engine.db.execute('SELECT payload FROM transcript_outbox WHERE task_id=?', (event['task_id'],)).fetchone()
        if not row:raise ValueError('unknown outbox reference; offset left uncommitted')
        pipeline.queue.enqueue(event['task_id'], 'extract', json.loads(row['payload']))
        if before_commit:before_commit()  # fault injection: durable intake, no offset commit
        self.consumer.commit(message=message, asynchronous=False)
        return True

    def close(self):self.consumer.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('role', choices=['relay', 'worker', 'init-topic', 'quarantine-status'])
    parser.add_argument('--once', action='store_true')
    parser.add_argument('--quarantine-invalid', action='store_true',
                        help='Durably isolate malformed envelopes before advancing offsets')
    parser.add_argument('--openai', action='store_true', help='real LLM extraction; incurs API usage')
    parser.add_argument('--env-file', default='.env')
    parser.add_argument('--topic', default='voice.extract.v1')
    parser.add_argument('--group', default='voice-extract-v1')
    parser.add_argument('--db', default=os.environ.get('VOICE_DATABASE_URL'))
    parser.add_argument('--bootstrap', default=os.environ.get('VOICE_KAFKA_BOOTSTRAP', '127.0.0.1:59092'))
    args = parser.parse_args()
    if args.role == 'init-topic':
        from confluent_kafka.admin import AdminClient, NewTopic
        from confluent_kafka import KafkaException, KafkaError
        futures = AdminClient({'bootstrap.servers': args.bootstrap}).create_topics([NewTopic(args.topic, num_partitions=3, replication_factor=1)])
        for future in futures.values():
            try:future.result(timeout=15)
            except KafkaException as error:
                if error.args[0].code() != KafkaError.TOPIC_ALREADY_EXISTS:raise
        return
    if not args.db:parser.error('--db or VOICE_DATABASE_URL required')
    if args.role == 'quarantine-status':
        from .storage import connect, table_exists
        db = connect(args.db)
        try:
            rows = []
            if table_exists(db, 'kafka_quarantine'):
                rows = [dict(row) for row in db.execute(
                    'SELECT reason, count(*) AS count FROM kafka_quarantine GROUP BY reason ORDER BY reason').fetchall()]
            print(json.dumps({'quarantined': sum(row['count'] for row in rows), 'reasons': rows}))
        finally:
            db.close()
        return
    while True:
        pipeline = intake = llm_client = journal = None
        try:
            router=None
            if args.openai:
                from .openai_provider import settings, make_client, OpenAIExtractor, ModelJournal
                from .models import ExtractionRouter
                config=settings(args.env_file)
                llm_client=make_client(config);journal=ModelJournal(args.db)
                extractor=OpenAIExtractor(config['LLM_MODEL'],llm_client,journal)
                router=ExtractionRouter({'small':extractor,'reasoning':extractor})
            pipeline = Pipeline(args.db, router=router, publish_on_submit=False)
            relay = KafkaRelay(args.bootstrap, args.topic) if args.role == 'relay' else None
            intake = KafkaIntake(args.bootstrap, args.group, args.topic, args.quarantine_invalid) if args.role == 'worker' else None
            while True:
                if relay:relay.publish(pipeline)
                else:
                    intake.once(pipeline)
                    # Leased database tasks survive offset commits and process restarts.
                    # Do not use work_once(), which bypasses Kafka with local publication.
                    pipeline.queue.run_once(lambda task: pipeline.router.extract(
                        task['payload']['text'], complex=task['payload']['complex']))
                if args.once:return
                if relay:time.sleep(.1)
        except Exception as error:
            if args.once:raise
            # No DSNs, transcript text or provider errors in process logs.
            print(json.dumps({'role':args.role,'state':'retrying','error':type(error).__name__}), file=sys.stderr, flush=True)
        finally:
            if intake:intake.close()
            if pipeline:pipeline.close()
            if llm_client:llm_client.close()
            if journal:journal.close()
        time.sleep(1)


if __name__ == '__main__':main()
