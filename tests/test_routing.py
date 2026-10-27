import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from voice_context.models import RuleExtractor
from voice_context.routing import AuditLog,CascadeRouter,Tier,FixedPolicy,RoutingFailed
from voice_context.gateway import Pipeline

class Provider:
    def __init__(self,name,fn): self.name,self.fn=name,fn; self.calls=0
    def extract(self,text): self.calls+=1; return self.fn(text)

class RoutingTests(unittest.TestCase):
    def setUp(self):
        self.rules=RuleExtractor(); self.text='remember db: PostgreSQL\nremember cache: Redis'
        self.weak=Provider('weak',lambda t:self.rules.extract(t)[:1])
        self.strong=Provider('strong',self.rules.extract)
        self.tiers=[Tier('rules',self.rules),Tier('small',self.weak,1),Tier('reasoning',self.strong,5)]
    def test_rule_and_complex_prerouting(self):
        router=CascadeRouter(self.tiers)
        self.assertEqual(router.extract(self.text)['route'],'rules')
        self.assertEqual(router.extract(self.text,complex=True)['route'],'reasoning')
        self.assertEqual(self.weak.calls,0)
    def test_missing_record_escalates(self):
        r=CascadeRouter(self.tiers,policy=FixedPolicy(1)).extract(self.text)
        self.assertEqual(r['route'],'reasoning'); self.assertTrue(r['fallback_used'])
        self.assertEqual(r['routing_trace']['cost_units'],6)
        self.assertEqual(r['routing_trace']['attempts'][0]['reason'],'missing_explicit_record')
    def test_provider_failure_escalates(self):
        def fail(t): raise TimeoutError('secret')
        self.weak.fn=fail
        r=CascadeRouter(self.tiers,policy=FixedPolicy(1)).extract(self.text)
        self.assertEqual(r['routing_trace']['attempts'][0]['error_type'],'TimeoutError')
        self.assertNotIn('secret',json.dumps(r['routing_trace']))
    def test_cost_and_call_limits(self):
        for kwargs,status in [({'max_cost_units':1},'cost_budget_exhausted'),({'max_calls':1},'call_budget_exhausted')]:
            with self.assertRaises(RoutingFailed) as ctx: CascadeRouter(self.tiers,policy=FixedPolicy(1),**kwargs).extract(self.text)
            self.assertEqual(ctx.exception.trace['status'],status)
        self.assertEqual(self.strong.calls,0)
    def test_late_result_not_accepted(self):
        now=[0.]
        def slow(t): now[0]+=2; return self.rules.extract(t)
        router=CascadeRouter([Tier('slow',Provider('slow',slow))],deadline_seconds=1,clock=lambda:now[0])
        with self.assertRaises(RoutingFailed) as ctx: router.extract(self.text)
        self.assertEqual(ctx.exception.trace['status'],'deadline_exceeded')
    def test_failure_audit_is_durable_without_source_text(self):
        with tempfile.TemporaryDirectory() as d:
            path=str(Path(d)/'audit.db')
            router=CascadeRouter([Tier('empty',Provider('empty',lambda t:[]))],audit=AuditLog(path))
            with self.assertRaises(RoutingFailed): router.extract('undecided discussion')
            with sqlite3.connect(path) as db: raw=db.execute('SELECT trace FROM routing_audit').fetchone()[0]
            self.assertEqual(json.loads(raw)['status'],'quality_gate_exhausted')
            self.assertNotIn('undecided discussion',raw)
    def test_pipeline_keeps_trace_and_confirmation(self):
        with tempfile.TemporaryDirectory() as d:
            p=Pipeline(str(Path(d)/'state.db'),CascadeRouter(self.tiers,policy=FixedPolicy(1)))
            p.engine.fork('main'); p.submit('x','main','s',self.text); p.work_once()
            result=p.queue.get('transcript:x')['result']
            self.assertEqual(len(result['routing_trace']['attempts']),2)
            self.assertEqual(p.engine.recall('main'),[])
            p.approve('transcript:x',['db']); self.assertEqual(len(p.engine.recall('main')),1); p.close()
