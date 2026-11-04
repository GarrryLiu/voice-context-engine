"""Deterministic failure tests with real SQLite transactions and a fake transport."""
import json
import io
from contextlib import redirect_stdout
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
from voice_context.broker import KafkaIntake, InvalidEvent, decode_event
from voice_context.gateway import Pipeline


def message(value=b'not json', key=b'bad', offset=0):
    result = Mock()
    result.value.return_value = value
    result.key.return_value = key
    result.topic.return_value = 'isolated-test'
    result.partition.return_value = 0
    result.offset.return_value = offset
    result.error.return_value = None
    return result


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = str(Path(self.directory.name) / 'test.db')
        self.pipeline = Pipeline(self.path, publish_on_submit=False)
        self.pipeline.engine.fork('main')
        self.intake = KafkaIntake.__new__(KafkaIntake)
        self.intake.scope = 'test-scope'
        self.intake.quarantine_invalid = True
        self.intake.consumer = Mock()
        self.intake.consumer.poll.return_value = message()

    def tearDown(self):
        self.pipeline.close()
        self.directory.cleanup()

    def test_crash_before_commit_replay_is_durable_and_idempotent(self):
        with self.assertRaises(RuntimeError):
            self.intake.once(self.pipeline, before_commit=Mock(side_effect=RuntimeError('crash')))
        self.intake.consumer.commit.assert_not_called()
        self.pipeline.close()
        self.pipeline = Pipeline(self.path, publish_on_submit=False)
        self.assertTrue(self.intake.once(self.pipeline))
        rows = self.pipeline.engine.db.execute('SELECT * FROM kafka_quarantine').fetchall()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['reason'], 'invalid_json')
        self.assertNotIn('not json', str(dict(rows[0])))
        self.intake.consumer.commit.assert_called_once()

    def test_failed_persistence_does_not_commit_offset(self):
        with patch('voice_context.broker.quarantine_event', side_effect=RuntimeError('db offline')):
            with self.assertRaises(RuntimeError):self.intake.once(self.pipeline)
        self.intake.consumer.commit.assert_not_called()

    def test_strict_default_does_not_quarantine(self):
        self.intake.quarantine_invalid = False
        with self.assertRaises(InvalidEvent):self.intake.once(self.pipeline)
        self.intake.consumer.commit.assert_not_called()

    def test_unknown_reference_and_future_version_are_not_discarded(self):
        for event in ({'version': 1, 'task_id': 'unknown'}, {'version': 2, 'task_id': 'unknown'}):
            self.intake.consumer.poll.return_value = message(json.dumps(event).encode(), b'unknown')
            with self.assertRaises(ValueError):self.intake.once(self.pipeline)
        self.intake.consumer.commit.assert_not_called()

    def test_normal_task_after_poison_is_enqueued_once(self):
        self.intake.once(self.pipeline)
        self.pipeline.submit('a', 'main', 's', 'remember storage: PostgreSQL')
        self.intake.consumer.poll.return_value = message(
            b'{"version":1,"task_id":"transcript:a"}', b'transcript:a', 1)
        self.intake.once(self.pipeline)
        self.intake.once(self.pipeline)
        self.assertEqual(self.pipeline.queue.db.execute('SELECT count(*) FROM tasks').fetchone()[0], 1)
        self.assertTrue(self.pipeline.queue.run_once(lambda task: self.pipeline.router.extract(task['payload']['text'])))

    def test_commit_failure_keeps_audit_for_replay(self):
        self.intake.consumer.commit.side_effect = RuntimeError('broker offline')
        with self.assertRaises(RuntimeError):self.intake.once(self.pipeline)
        self.assertEqual(self.pipeline.engine.db.execute('SELECT count(*) FROM kafka_quarantine').fetchone()[0], 1)
        self.intake.consumer.commit.side_effect = None
        self.intake.once(self.pipeline)
        self.assertEqual(self.pipeline.engine.db.execute('SELECT count(*) FROM kafka_quarantine').fetchone()[0], 1)

    def test_malformed_shapes_are_bounded_safe_errors(self):
        for raw in (None, b'[]', b'null', b'\xff', b'x'*16385,
                    b'{"version":1,"task_id":""}', b'{"version":1,"task_id":"a"}'):
            with self.subTest(raw_type=type(raw).__name__):
                with self.assertRaises(InvalidEvent):decode_event(message(raw))

    def test_status_reports_only_counts_and_reason_codes(self):
        from voice_context.broker import main
        for expected in (0, 1):
            output = io.StringIO()
            with patch('sys.argv', ['broker', 'quarantine-status', '--db', self.path]), redirect_stdout(output):
                main()
            report = json.loads(output.getvalue())
            self.assertEqual(report['quarantined'], expected)
            self.assertNotIn('not json', output.getvalue())
            self.intake.once(self.pipeline)
