"""Routing control-flow comparison using scripted providers, never real LLM costs."""
import argparse
import json
import random
from pathlib import Path
from voice_context.models import RuleExtractor
from voice_context.routing import CascadeRouter, FixedPolicy, Tier, RoutingFailed

class ScriptedProvider:
    def __init__(self,name,capacity): self.name,self.capacity=name,capacity
    def extract(self,text): return RuleExtractor().extract(text)[:self.capacity]

p=argparse.ArgumentParser(); p.add_argument('--output',default='experiments/routing-results.json'); args=p.parse_args()
tiers=[Tier('rules',RuleExtractor(),0),Tier('small',ScriptedProvider('scripted-small',1),1),
       Tier('standard',ScriptedProvider('scripted-standard',2),3),Tier('reasoning',ScriptedProvider('scripted-reasoning',32),8)]
cases=[]
for i in range(100):
    count=1 if i<60 else (2 if i<80 else 3)
    text='\n'.join(f'remember key{j}: value{i}-{j}' for j in range(count))
    if i>=40: text='Transcript follows:\n'+text
    cases.append((text,i>=80))
results={}
for strategy in ['always_small','always_strong','random_single','heuristic_single','cascade']:
    rng=random.Random(42); correct=calls=cost=failures=0; final_tiers={}
    for text,complex in cases:
        if strategy=='always_small': router=CascadeRouter(tiers,policy=FixedPolicy(1),max_calls=1)
        elif strategy=='always_strong': router=CascadeRouter(tiers,policy=FixedPolicy(3),max_calls=1)
        elif strategy=='random_single': router=CascadeRouter(tiers,policy=FixedPolicy(rng.randrange(1,4)),max_calls=1)
        elif strategy=='heuristic_single': router=CascadeRouter(tiers,max_calls=1)
        else: router=CascadeRouter(tiers)
        try:
            output=router.extract(text,complex=complex); trace=output['routing_trace']
            correct+=output['records']==RuleExtractor().extract(text)
            final_tiers[output['route']]=final_tiers.get(output['route'],0)+1
        except RoutingFailed as exc:
            trace=exc.trace; failures+=1
        calls+=len(trace['attempts']); cost+=trace['cost_units']
    results[strategy]={'correct_complete_outputs':correct,'unresolved':failures,'provider_calls':calls,
                       'declared_cost_units':cost,'final_tiers':final_tiers}
assert results['cascade']['correct_complete_outputs']==100
assert results['always_strong']['correct_complete_outputs']==100
report={'kind':'scripted_routing_control_flow','seed':42,'requests':100,'results':results,
        'limitations':'Providers have scripted record-count capacities. Gate observes explicit remember commands. Cost units are arbitrary. No live LLM, learned router, calibrated semantic quality, measured model costs or latency savings.'}
out=Path(args.output);out.parent.mkdir(parents=True,exist_ok=True);out.write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report,indent=2))
