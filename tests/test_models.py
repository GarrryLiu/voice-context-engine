import json
import unittest
from unittest.mock import patch
from voice_context.models import ExtractionRouter, RuleExtractor, OllamaExtractor

class ModelTests(unittest.TestCase):
    def test_rule_mode_and_source_validation(self):
        r=ExtractionRouter().extract('聊天\nremember 数据库: PostgreSQL')
        self.assertEqual(r['provider'],'rules-v1')
        self.assertEqual(r['records'][0]['value'],'PostgreSQL')
        self.assertEqual(ExtractionRouter().extract('maybe use Redis')['records'],[])
    def test_routing_and_explicit_fallback(self):
        class Broken:
            name='broken'
            def extract(self,text): raise TimeoutError()
        r=ExtractionRouter({'small':Broken(),'reasoning':RuleExtractor()},fallback=RuleExtractor())
        self.assertTrue(r.extract('remember db: SQLite')['fallback_used'])
        self.assertEqual(r.extract('remember db: SQLite',complex=True)['route'],'reasoning')
        with self.assertRaises(TimeoutError): ExtractionRouter({'small':Broken()}).extract('hello')
    def test_hallucinated_evidence_rejected(self):
        class Bad:
            name='bad'
            def extract(self,text): return [{'key':'db','value':'Redis','evidence':'Use Redis'}]
        with self.assertRaises(ValueError): ExtractionRouter({'small':Bad()}).extract('Use PostgreSQL')
    def test_ollama_transport_contract(self):
        class Response:
            def __enter__(self): return self
            def __exit__(self,*args): pass
            def read(self,n): return json.dumps({'done':True,'message':{'content':json.dumps({'records':[{'key':'db','value':'SQLite','evidence':'Use SQLite'}]})}}).encode()
        with patch('voice_context.models.urlopen',return_value=Response()) as call:
            self.assertEqual(OllamaExtractor('test-model').extract('Use SQLite')[0]['value'],'SQLite')
            request=call.call_args.args[0]
            body=json.loads(request.data)
            self.assertFalse(body['stream']); self.assertEqual(body['model'],'test-model')
            self.assertEqual(call.call_args.kwargs['timeout'],30)
    def test_input_and_duplicate_key_limits(self):
        with self.assertRaises(ValueError): ExtractionRouter(max_chars=2).extract('long text')
        with self.assertRaises(ValueError): RuleExtractor().extract('remember db: x\nremember db: y')
