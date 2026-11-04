import sqlite3
import tempfile
import unittest
from pathlib import Path
from voice_context.product.backup import snapshot
from voice_context.server.demo import DemoService
from voice_context.product.semantic_maps import SemanticMaps
from product.test_semantic_maps import FakeProvider


class BackupTests(unittest.TestCase):
    def test_live_snapshot_restores_sources_graph_and_provenance(self):
        with tempfile.TemporaryDirectory() as root:
            source=Path(root)/'source.db';backup=Path(root)/'backup.db';restored=Path(root)/'restored.db'
            service=DemoService(str(source))
            try:
                service.submit_demo('test','A source that must survive recovery.')
                maps=SemanticMaps(service.product.access,FakeProvider())
                proposal=maps.propose('test','main');result=maps.apply('test',proposal['id'])
                snapshot(source,backup)
                with self.assertRaises(FileExistsError):snapshot(source,backup)
                snapshot(backup,restored)
            finally:service.close()
            recovered=DemoService(str(restored))
            try:
                self.assertEqual(recovered.product.workspace('test'),result['workspace'])
                self.assertEqual(len(recovered.product.documents('test','list',{})['documents']),1)
                node=result['workspace']['data']['sessions'][0]['nodes'][0]['id']
                self.assertTrue(SemanticMaps(recovered.product.access).provenance('test',node)['evidence'])
            finally:recovered.close()

    def test_wal_and_invalid_sources(self):
        with tempfile.TemporaryDirectory() as root:
            source=Path(root)/'source.db';target=Path(root)/'copy.db'
            with self.assertRaises(ValueError):snapshot(source,target)
            with sqlite3.connect(source) as db:
                db.execute('PRAGMA journal_mode=WAL');db.execute('CREATE TABLE evidence(value TEXT)')
                db.execute("INSERT INTO evidence VALUES ('committed WAL')");db.commit()
                snapshot(source,target)
                with sqlite3.connect(target) as copy:self.assertEqual(copy.execute('SELECT value FROM evidence').fetchone()[0],'committed WAL')
