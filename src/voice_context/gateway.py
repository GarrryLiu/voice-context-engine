"""Local JSON-lines transcript gateway. Text input only; no microphone transport."""
import argparse
import hashlib
import json
import sys
import sqlite3
from .engine import Engine
from .models import ExtractionRouter, OllamaExtractor
from .tasks import TaskQueue


class Pipeline:
    def __init__(self, path, router=None):
        self.engine = Engine(path)
        self.queue = TaskQueue(path)
        self.router = router or ExtractionRouter()

    def close(self):
        self.queue.close()
        self.engine.close()

    def submit(self, transcript_id, branch, session, text, final=True, complex=False):
        if not isinstance(final, bool) or not isinstance(complex, bool):
            raise ValueError('final and complex must be booleans')
        if not final:
            return {'accepted': False, 'reason': 'partial transcript'}
        if not all(isinstance(v,str) and v.strip() for v in (transcript_id,branch,session,text)) or len(text)>32000:
            raise ValueError('nonempty identifiers and text up to 32000 characters required')
        if not self.engine.db.execute('SELECT 1 FROM branches WHERE id=?',(branch,)).fetchone():
            raise ValueError('unknown branch')
        task_id = 'transcript:' + transcript_id
        accepted = self.queue.enqueue(task_id, 'extract', {'branch':branch,'session':session,'text':text,'complex':complex})
        return {'accepted':accepted,'task_id':task_id}

    def work_once(self):
        def handler(task):
            if task['kind'] != 'extract':
                raise ValueError('unsupported task kind')
            payload=task['payload']
            return self.router.extract(payload['text'],complex=payload['complex'])
        return self.queue.run_once(handler)

    def approve(self, task_id, keys):
        """Caller confirmation; commits selected candidates as durable memory events.

        Extraction never writes memory. Confirmation is idempotent and all selected
        events are inserted in one transaction. Materialization can resume later.
        """
        task=self.queue.get(task_id)
        if task['kind']!='extract' or task['state']!='succeeded':
            raise ValueError('only successful extraction candidates can be approved')
        records={r['key']:r for r in task['result']['records']}
        if not isinstance(keys,list) or any(not isinstance(k,str) for k in keys) or len(set(keys))!=len(keys) or set(keys)-records.keys():
            raise ValueError('select unique candidate keys')
        inserted=0
        with self.engine.db:
            self.engine.db.execute('BEGIN IMMEDIATE')
            for key in keys:
                record=records[key]
                eid='approved:'+hashlib.sha256(json.dumps([task_id,key]).encode()).hexdigest()
                payload=json.dumps({**record,'task_id':task_id,'provider':task['result']['provider'],'confirmed':True},sort_keys=True)
                branch,session=task['payload']['branch'],task['payload']['session']
                old=self.engine.db.execute('SELECT * FROM events WHERE id=?',(eid,)).fetchone()
                if old:
                    if (old['branch'],old['session'],old['payload'])!=(branch,session,payload):
                        raise ValueError('confirmation event collision')
                    continue
                self.engine.db.execute('INSERT INTO events(id,branch,session,payload) VALUES (?,?,?,?)',(eid,branch,session,payload))
                inserted+=1
        self.engine.drain()
        return {'inserted':inserted}

    def dispatch(self, request):
        action=request['action']
        args={k:v for k,v in request.items() if k!='action'}
        if action=='submit': return self.submit(**args)
        if action=='work': return {'worked':self.work_once()}
        if action=='status':
            result=self.queue.get(**args)
            result.pop('lease_token',None)
            return result
        if action=='approve': return self.approve(**args)
        if action=='context': return self.engine.assemble_context(**args)
        if action=='fork':
            self.engine.fork(**args); return {'created':True}
        if action=='merge': return self.engine.merge(**args)
        if action=='drain': return {'processed':self.engine.drain()}
        raise ValueError('unknown action')


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--db',default='context.db')
    p.add_argument('--model',help='installed Ollama model; otherwise explicit rule mode')
    p.add_argument('--reasoning-model')
    p.add_argument('--standard-model')
    p.add_argument('--cascade',action='store_true')
    p.add_argument('--route-cost-units',type=float,default=20)
    p.add_argument('--route-deadline',type=float,default=45)
    args=p.parse_args()
    router=None
    if args.model:
        router=ExtractionRouter({'small':OllamaExtractor(args.model),
                                 'reasoning':OllamaExtractor(args.reasoning_model or args.model)})
    if args.cascade:
        from .routing import CascadeRouter, Tier, AuditLog
        from .models import RuleExtractor
        tiers=[Tier('rules',RuleExtractor())]
        for label,model,cost in [('small',args.model,1),('standard',args.standard_model,3),('reasoning',args.reasoning_model,8)]:
            if model:
                tiers.append(Tier(label,OllamaExtractor(model,timeout=min(30,args.route_deadline)),cost))
        router=CascadeRouter(tiers,max_cost_units=args.route_cost_units,
                             deadline_seconds=args.route_deadline,audit=AuditLog(args.db))
    pipeline=Pipeline(args.db,router)
    if not pipeline.engine.db.execute("SELECT 1 FROM branches WHERE id='main'").fetchone():
        pipeline.engine.fork('main')
    try:
        for line in sys.stdin:
            try:
                if len(line)>65536: raise ValueError('request too large')
                response={'ok':True,'result':pipeline.dispatch(json.loads(line))}
            except (ValueError,KeyError,TypeError,sqlite3.Error) as exc:
                response={'ok':False,'error':type(exc).__name__}
            print(json.dumps(response,ensure_ascii=False),flush=True)
    finally:
        pipeline.close()

if __name__=='__main__': main()
