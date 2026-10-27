import json
import unittest
from voice_context import Engine

class MergeTests(unittest.TestCase):
    def setUp(self):
        self.e=Engine(); self.e.fork('main')
        self.put('a', 'main', 'store', 'Postgres'); self.e.fork('child','main')
    def tearDown(self): self.e.close()
    def put(self,eid,b,k,v):
        self.e.ingest(eid,b,'s',key=k,value=v); self.e.drain()
    def test_nonconflict_and_provenance(self):
        self.put('b','child','cache','Redis')
        self.assertEqual(self.e.merge('child','main')['applied'],1)
        source=self.e.history('main','cache')[-1]['source']
        payload=json.loads(self.e.db.execute('SELECT payload FROM events WHERE id=?',(source,)).fetchone()[0])
        self.assertEqual(payload['origin'],'b')
        self.assertEqual(self.e.merge('child','main')['applied'],0)
    def test_conflict_is_atomic(self):
        self.put('b','child','store','SQLite'); self.put('c','main','store','MySQL')
        self.put('d','child','cache','Redis')
        result=self.e.merge('child','main')
        self.assertFalse(result['resolved']); self.assertEqual(result['conflicts'][0]['key'],'store')
        self.assertEqual(self.e.recall('main','Redis'),[])
        self.e.merge('child','main',{'store':'source'})
        self.assertEqual(self.e.history('main','store')[-1]['value'],'SQLite')
    def test_checkpoint_preserves_new_parent_change(self):
        self.put('b','child','store','SQLite'); self.e.merge('child','main')
        self.put('c','main','store','MySQL')
        self.assertEqual(self.e.merge('child','main')['applied'],0)
        self.assertEqual(self.e.history('main','store')[-1]['value'],'MySQL')
    def test_target_resolution_and_invalid_relationship(self):
        self.put('b','child','store','SQLite'); self.put('c','main','store','MySQL')
        self.assertEqual(self.e.merge('child','main',{'store':'target'})['applied'],0)
        with self.assertRaises(ValueError): self.e.merge('main','child')
