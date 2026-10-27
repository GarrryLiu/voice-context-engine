"""Observable extraction cascades. Costs are declared units, not billed prices."""
import hashlib
import json
import math
import sqlite3
import time
import uuid
from dataclasses import dataclass
from .models import RuleExtractor, validate_candidates


@dataclass(frozen=True)
class Tier:
    name: str
    provider: object
    cost_units: float = 0


class RoutingFailed(RuntimeError):
    def __init__(self, reason, trace):
        super().__init__(reason)
        self.trace = trace


class HeuristicPolicy:
    name = 'heuristic-v1'

    def select(self, features, tiers):
        if features['complex']:
            return len(tiers)-1
        if features['explicit_only']:
            return 0
        return min(1, len(tiers)-1)


class FixedPolicy:
    name = 'fixed'

    def __init__(self, index):
        self.index = index

    def select(self, features, tiers):
        return self.index


class CoverageGate:
    """Checks schema, source quotes and explicit-command coverage, not semantics."""
    name = 'evidence-and-explicit-coverage-v1'

    def check(self, text, records):
        validate_candidates(text, records)
        expected = RuleExtractor().extract(text)
        found = {(r['key'],r['value']) for r in records}
        if any((r['key'],r['value']) not in found for r in expected):
            return False, 'missing_explicit_record'
        if not records and not expected:
            return False, 'empty_output_requires_review'
        return True, 'structural_checks_passed'


class AuditLog:
    def __init__(self, path):
        self.path = path
        with sqlite3.connect(path) as db:
            db.execute('''CREATE TABLE IF NOT EXISTS routing_audit
              (id TEXT PRIMARY KEY, created REAL NOT NULL, trace TEXT NOT NULL)''')

    def __call__(self, trace):
        with sqlite3.connect(self.path) as db:
            db.execute('INSERT INTO routing_audit VALUES (?,?,?)',
                       (trace['id'], time.time(), json.dumps(trace,sort_keys=True)))


class CascadeRouter:
    def __init__(self, tiers, policy=None, gate=None, max_cost_units=20,
                 max_calls=4, deadline_seconds=45, audit=None, clock=time.monotonic):
        if not tiers or len({t.name for t in tiers}) != len(tiers):
            raise ValueError('nonempty unique tiers required')
        if any(not math.isfinite(t.cost_units) or t.cost_units < 0 for t in tiers):
            raise ValueError('tier costs must be finite and nonnegative')
        if max_calls < 1 or not math.isfinite(max_cost_units) or max_cost_units < 0 or not math.isfinite(deadline_seconds) or deadline_seconds <= 0:
            raise ValueError('invalid request limits')
        self.tiers, self.policy, self.gate = list(tiers), policy or HeuristicPolicy(), gate or CoverageGate()
        self.max_cost, self.max_calls, self.deadline = max_cost_units, max_calls, deadline_seconds
        self.audit, self.clock = audit, clock

    def extract(self, text, complex=False):
        if not isinstance(text,str) or not text.strip() or len(text)>32000:
            raise ValueError('nonempty transcript up to 32000 characters required')
        start=self.clock()
        lines=[line for line in text.splitlines() if line.strip()]
        explicit=RuleExtractor().extract(text)
        features={'chars':len(text),'lines':len(lines),'complex':bool(complex),
                  'explicit_only':len(explicit)==len(lines),'explicit_records':len(explicit)}
        index=self.policy.select(features,self.tiers)
        if not isinstance(index,int) or not 0<=index<len(self.tiers):
            raise ValueError('policy selected an unknown tier')
        trace={'id':uuid.uuid4().hex,'input_sha256':hashlib.sha256(text.encode()).hexdigest(),
               'policy':self.policy.name,'gate':self.gate.name,'features':features,
               'start_tier':self.tiers[index].name,'attempts':[], 'cost_units':0,
               'limits':{'max_cost_units':self.max_cost,'max_calls':self.max_calls,'deadline_seconds':self.deadline}}

        def finish(status):
            trace['status']=status
            trace['elapsed_seconds']=self.clock()-start
            if self.audit:
                self.audit(trace)

        for tier in self.tiers[index:]:
            if len(trace['attempts'])>=self.max_calls:
                finish('call_budget_exhausted'); raise RoutingFailed(trace['status'],trace)
            if trace['cost_units']+tier.cost_units>self.max_cost:
                finish('cost_budget_exhausted'); raise RoutingFailed(trace['status'],trace)
            if self.clock()-start>=self.deadline:
                finish('deadline_exceeded'); raise RoutingFailed(trace['status'],trace)
            trace['cost_units']+=tier.cost_units
            tick=self.clock()
            attempt={'tier':tier.name,'provider':tier.provider.name,'cost_units':tier.cost_units}
            try:
                records=validate_candidates(text,tier.provider.extract(text))
                accepted,reason=self.gate.check(text,records)
                attempt.update(accepted=accepted,reason=reason)
            except Exception as exc:
                accepted=False
                attempt.update(accepted=False,reason='provider_or_validation_error',error_type=type(exc).__name__)
            attempt['elapsed_seconds']=self.clock()-tick
            trace['attempts'].append(attempt)
            if self.clock()-start>=self.deadline:
                finish('deadline_exceeded'); raise RoutingFailed(trace['status'],trace)
            if accepted:
                finish('accepted')
                return {'records':records,'provider':tier.provider.name,'route':tier.name,
                        'fallback_used':len(trace['attempts'])>1,'status':'candidates','routing_trace':trace}
        finish('quality_gate_exhausted')
        raise RoutingFailed(trace['status'],trace)
