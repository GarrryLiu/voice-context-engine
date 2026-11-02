"""At-least-once outbox relay and durable Kafka intake.

Kafka carries IDs, not authority or transcript text. The database outbox provides
canonical immutable task payloads; duplicate records cannot cause duplicate tasks.
"""
import argparse
import json
import os
import sys
import time
from .gateway import Pipeline


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
    def __init__(self, bootstrap, group='voice-extract-v1', topic='voice.extract.v1'):
        from confluent_kafka import Consumer
        self.consumer = Consumer({'bootstrap.servers': bootstrap, 'group.id': group,
            'enable.auto.commit': False, 'enable.auto.offset.store': False,
            'auto.offset.reset': 'earliest'})
        self.consumer.subscribe([topic])

    def once(self, pipeline, timeout=1, before_commit=None):
        message = self.consumer.poll(timeout)
        if message is None:return False
        if message.error():raise RuntimeError(str(message.error()))
        event = json.loads(message.value())
        if event.get('version') != 1 or not isinstance(event.get('task_id'), str):
            raise ValueError('unsupported Kafka event; offset left uncommitted')
        if message.key() != event['task_id'].encode():raise ValueError('event key mismatch')
        row = pipeline.engine.db.execute('SELECT payload FROM transcript_outbox WHERE task_id=?', (event['task_id'],)).fetchone()
        if not row:raise ValueError('unknown outbox reference; offset left uncommitted')
        pipeline.queue.enqueue(event['task_id'], 'extract', json.loads(row['payload']))
        if before_commit:before_commit()  # fault injection: durable intake, no offset commit
        self.consumer.commit(message=message, asynchronous=False)
        return True

    def close(self):self.consumer.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('role', choices=['relay', 'worker', 'init-topic'])
    parser.add_argument('--once', action='store_true')
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
    while True:
        pipeline = intake = None
        try:
            pipeline = Pipeline(args.db, publish_on_submit=False)
            relay = KafkaRelay(args.bootstrap, args.topic) if args.role == 'relay' else None
            intake = KafkaIntake(args.bootstrap, args.group, args.topic) if args.role == 'worker' else None
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
        time.sleep(1)


if __name__ == '__main__':main()
