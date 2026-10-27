import json
import unittest
from voice_context import Engine

class RetrievalTests(unittest.TestCase):
    def setUp(self):
        self.e=Engine(); self.e.fork('main')
        for i,(k,v) in enumerate([('数据库','选择 PostgreSQL 保存版本历史'),('cache','Redis active context'),('database','PostgreSQL durable store')]):
            self.e.ingest(str(i),'main','s',key=k,value=v)
        self.e.drain()
    def tearDown(self): self.e.close()
    def test_chinese_subphrase(self):
        self.assertEqual(self.e.recall('main','版本')[0]['key'],'数据库')
    def test_exact_key_and_empty_query(self):
        self.assertEqual(self.e.recall('main','database')[0]['key'],'database')
        self.assertEqual(len(self.e.recall('main')),3)
        self.assertEqual(self.e.recall('main','missing'),[])
    def test_serialized_budget_includes_sources(self):
        c=self.e.assemble_context('main',budget=190)
        self.assertEqual(c['cost'],len(c['text'].encode()))
        self.assertLessEqual(c['cost'],190)
        self.assertGreater(c['omitted'],0)
        for item in json.loads(c['text']): self.assertIn('source',item)
    def test_custom_token_counter(self):
        c=self.e.assemble_context('main',budget=45,count=lambda s: len(s)//4+1)
        self.assertLessEqual(c['cost'],45)
        self.assertEqual(c['cost'],len(c['text'])//4+1)
    def test_revision_updates_and_negative_limit(self):
        before=self.e.assemble_context('main')['revision']
        self.e.ingest('new','main','s2',key='cache',value='local'); self.e.drain()
        self.assertNotEqual(before,self.e.assemble_context('main')['revision'])
        with self.assertRaises(ValueError): self.e.recall('main',limit=-1)
        with self.assertRaises(ValueError): self.e.assemble_context('main',budget=0)
