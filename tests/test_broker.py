import os
import unittest
import uuid
import test_postgres as pg
from voice_context.broker import KafkaIntake, KafkaRelay


@unittest.skipUnless(os.environ.get('VOICE_TEST_KAFKA') and os.environ.get('VOICE_TEST_POSTGRES'), 'requires Kafka and PostgreSQL')
class BrokerTests(pg.PostgresTests):
    # Inherit setup/cleanup only, not the unrelated contracts.
    test_atomic_final_outbox_restart_and_versions = None
    test_transaction_rollback_and_epoch_fencing = None
    test_two_workers_cannot_claim_same_task = None

    def test_duplicate_delivery_and_crash_before_offset_commit(self):
        from confluent_kafka.admin import AdminClient, NewTopic
        bootstrap = os.environ['VOICE_TEST_KAFKA']; topic = 'test-' + uuid.uuid4().hex
        admin = AdminClient({'bootstrap.servers': bootstrap})
        for f in admin.create_topics([NewTopic(topic, num_partitions=1, replication_factor=1)]).values():f.result(15)
        self.p.publish_on_submit = False
        self.p.submit('a', 'main', 's', 'remember db: PostgreSQL')
        self.assertIn('PostgreSQL', self.p.transcripts.context('main')['text'])
        self.assertEqual(self.p.queue.db.execute('SELECT count(*) FROM tasks').fetchone()[0], 0)
        relay = KafkaRelay(bootstrap, topic)
        self.assertEqual(relay.publish(self.p), 1)
        with self.p.engine.db:self.p.engine.db.execute('UPDATE transcript_outbox SET published=0')
        self.assertEqual(relay.publish(self.p), 1)
        group = 'test-' + uuid.uuid4().hex
        intake = KafkaIntake(bootstrap, group, topic)
        import time
        def crash():raise RuntimeError('simulated process exit')
        try:
            deadline = time.monotonic()+15
            while time.monotonic()<deadline:
                try:intake.once(self.p, before_commit=crash)
                except RuntimeError as e:
                    self.assertEqual(str(e), 'simulated process exit');break
            else:self.fail('no record received')
        finally:intake.close()
        intake = KafkaIntake(bootstrap, group, topic)
        try:
            received = 0; deadline = time.monotonic()+15
            while received<2 and time.monotonic()<deadline:
                received += bool(intake.once(self.p))
            self.assertEqual(received, 2)
            self.assertEqual(self.p.queue.db.execute('SELECT count(*) FROM tasks').fetchone()[0], 1)
            self.assertTrue(self.p.queue.run_once(lambda task:self.p.router.extract(task['payload']['text'])))
            self.assertEqual(self.p.approve('transcript:a', ['db'])['inserted'], 1)
        finally:
            intake.close()
            for f in admin.delete_topics([topic]).values():f.result(15)
