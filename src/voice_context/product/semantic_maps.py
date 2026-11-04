"""Source-grounded map proposals. Model execution is injected; apply is explicit."""
import hashlib
import json
import uuid
from copy import deepcopy
from threading import Lock

from .product_workspace import WorkspaceConflict


class MapUnavailable(RuntimeError):pass
class MapBusy(RuntimeError):pass


def object_schema(properties):
    return {'type':'object','properties':properties,'required':list(properties),'additionalProperties':False}


def array(items):return {'type':'array','items':items}
STRING={'type':'string'}
EVIDENCE=object_schema({'source':STRING,'quote':STRING})
NODE=object_schema({'key':STRING,'title':STRING,'content':STRING,'kind':{'type':'string','enum':['idea','question','decision']},'state':{'type':'string','enum':['noted','open','confirmed','tentative','superseded']},'evidence':array(EVIDENCE)})
EDGE=object_schema({'from':STRING,'to':STRING,'relation':{'type':'string','enum':['related','supports','revises']},'evidence':array(EVIDENCE)})
SCHEMA=object_schema({'title':STRING,'topics':array(object_schema({'key':STRING,'title':STRING,'summary':STRING,'nodes':array(NODE),'edges':array(EDGE)})),'links':array(EDGE)})



def normalize_map(value):
    """Resolve explicitly supplied cross-topic node links to v1 topic links.

    Never guess an unknown/ambiguous endpoint or add a relationship. Raw model
    evidence is retained; the validator still checks all resolved references.
    """
    value=deepcopy(value)
    if not isinstance(value,dict) or not isinstance(value.get('topics'),list) or not isinstance(value.get('links'),list):raise ValueError('invalid map structure')
    owners={};topic_keys=set()
    for topic in value['topics']:
        if not isinstance(topic,dict) or not isinstance(topic.get('key'),str) or not isinstance(topic.get('nodes'),list) or not isinstance(topic.get('edges'),list):raise ValueError('invalid topic structure')
        topic_keys.add(topic['key'])
        for node in topic['nodes']:
            if not isinstance(node,dict) or not isinstance(node.get('key'),str):raise ValueError('invalid node key')
            owners.setdefault(node['key'],set()).add(topic['key'])
    def owner(key):
        if not isinstance(key,str):raise ValueError('invalid link endpoint')
        if key in topic_keys:return key
        found=owners.get(key,set())
        if len(found)!=1:raise ValueError('unknown or ambiguous link endpoint')
        return next(iter(found))
    links=list(value['links'])
    for topic in value['topics']:
        local={n['key'] for n in topic['nodes']};kept=[]
        for edge in topic['edges']:
            if not isinstance(edge,dict) or not isinstance(edge.get('from'),str) or not isinstance(edge.get('to'),str):raise ValueError('invalid link')
            if edge['from'] in local and edge['to'] in local:kept.append(edge)
            else:
                if edge.get('relation')=='revises':raise ValueError('cross-topic revision unsupported')
                links.append(edge)
        topic['edges']=kept
    combined={}
    for edge in links:
        if not isinstance(edge,dict) or set(edge)!={'from','to','relation','evidence'} or not isinstance(edge.get('evidence'),list) or edge.get('relation') not in {'related','supports','revises'}:raise ValueError('invalid relation')
        edge={**edge,'from':owner(edge.get('from')),'to':owner(edge.get('to'))}
        if edge['from']==edge['to']:raise ValueError('topic link must cross topics')
        pair=tuple(sorted([edge['from'],edge['to']]))
        if pair not in combined:combined[pair]=edge
        else:
            previous=combined[pair]
            # One undirected v1 edge can carry several supporting quotations.
            previous['relation']='related' if previous['relation']!=edge.get('relation') else previous['relation']
            previous['evidence'] += [e for e in edge['evidence'] if e not in previous['evidence']]
    value['links']=list(combined.values())
    return value


def validate_map(value,sources):
    def text(value,limit):
        if not isinstance(value,str) or not value.strip() or len(value)>limit or '\0' in value:raise ValueError('invalid map text')
    def fields(value,keys):
        if not isinstance(value,dict) or set(value)!=set(keys):raise ValueError('invalid map fields')
    source_text={s['id']:s['text'] for s in sources}
    def evidence(items):
        if not isinstance(items,list) or not 1<=len(items)<=6:raise ValueError('missing map evidence')
        for item in items:
            fields(item,['source','quote']);text(item['quote'],500)
            if item['source'] not in source_text or item['quote'] not in source_text[item['source']]:raise ValueError('unverifiable map evidence')
    def edges(items,ids):
        if not isinstance(items,list) or len(items)>60:raise ValueError('too many map links')
        seen=set()
        for edge in items:
            fields(edge,['from','to','relation','evidence'])
            if edge['from'] not in ids or edge['to'] not in ids or edge['from']==edge['to']:raise ValueError('invalid map link')
            pair=tuple(sorted([edge['from'],edge['to']]))
            if pair in seen or edge['relation'] not in ('related','supports','revises'):raise ValueError('invalid relation')
            seen.add(pair);evidence(edge['evidence'])
    fields(value,['title','topics','links']);text(value['title'],100)
    if not isinstance(value['topics'],list) or not 1<=len(value['topics'])<=8:raise ValueError('invalid topic count')
    topics=set();total=0
    for topic in value['topics']:
        fields(topic,['key','title','summary','nodes','edges']);text(topic['key'],60);text(topic['title'],100);text(topic['summary'],1200)
        if topic['key'] in topics:raise ValueError('duplicate topic')
        topics.add(topic['key'])
        if not isinstance(topic['nodes'],list) or not 1<=len(topic['nodes'])<=10:raise ValueError('invalid node count')
        ids=set();total+=len(topic['nodes'])
        for node in topic['nodes']:
            fields(node,['key','title','content','kind','state','evidence']);text(node['key'],60);text(node['title'],100);text(node['content'],1600)
            allowed={'idea':{'noted','tentative','superseded'},'question':{'open'},'decision':{'confirmed','superseded'}}
            if node['key'] in ids or node['state'] not in allowed.get(node['kind'],set()):raise ValueError('invalid node state')
            ids.add(node['key']);evidence(node['evidence'])
        edges(topic['edges'],ids)
        by_key={n['key']:n for n in topic['nodes']}
        for edge in topic['edges']:
            if edge['relation']=='revises' and (by_key[edge['to']]['state']!='superseded' or by_key[edge['from']]['state']=='superseded'):
                raise ValueError('revision must point from current to superseded item')
    if total>48:raise ValueError('too many map nodes')
    edges(value['links'],topics)
    return value


class SemanticMaps:
    def __init__(self,access,provider=None):self.access,self.provider,self.gate=access,provider,Lock()

    def status(self):return {'enabled':self.provider is not None,'mode':'real_model' if self.provider else 'disabled'}

    @staticmethod
    def table(stores):
        stores.workspace.db.execute('''CREATE TABLE IF NOT EXISTS map_proposals
          (id TEXT PRIMARY KEY, branch TEXT NOT NULL, workspace_version INTEGER NOT NULL,
           fingerprint TEXT NOT NULL, sources TEXT NOT NULL, payload TEXT NOT NULL,
           applied INTEGER NOT NULL DEFAULT 0, node_ids TEXT NOT NULL DEFAULT '{}')''')
        stores.workspace.db.commit()

    @staticmethod
    def snapshot(stores,branch):
        rows=stores.workspace.db.execute("SELECT id,version,source_text,created FROM documents WHERE branch=? AND kind='voice' AND status='active' ORDER BY created,id",(branch,)).fetchall()
        if not rows or len(rows)>200:raise ValueError('need 1 to 200 voice notes')
        sources=[{'id':f's{i+1}','document_id':r['id'],'version':r['version'],'text':r['source_text']} for i,r in enumerate(rows)]
        if sum(len(s['text']) for s in sources)>60000:raise ValueError('conversation exceeds map input limit')
        digest=hashlib.sha256(json.dumps(sources,ensure_ascii=False,sort_keys=True).encode()).hexdigest()
        return sources,digest

    def propose(self,session,branch):
        if not self.provider:raise MapUnavailable('map model not enabled')
        if not isinstance(branch,str) or not branch or len(branch)>80:raise ValueError('invalid branch')
        if not self.gate.acquire(blocking=False):raise MapBusy('map generation in progress')
        try:
            with self.access.open(session) as stores:
                self.table(stores);sources,digest=self.snapshot(stores,branch);version=stores.workspace.get()['version']
                applied=stores.workspace.db.execute('SELECT id,payload,node_ids FROM map_proposals WHERE fingerprint=? AND applied=1 ORDER BY rowid DESC LIMIT 1',(digest,)).fetchone()
                if applied and set(json.loads(applied['node_ids']).get('topics',{}).values()) & {t['id'] for t in stores.workspace.get()['data']['sessions']}:return {'id':applied['id'],'proposal':json.loads(applied['payload']),'sources':sources,'cached':True,'already_applied':True}
                cached=stores.workspace.db.execute('SELECT id,payload FROM map_proposals WHERE fingerprint=? AND workspace_version=? AND applied=0 ORDER BY rowid DESC LIMIT 1',(digest,version)).fetchone()
                if cached:return {'id':cached['id'],'proposal':json.loads(cached['payload']),'sources':sources,'cached':True}
            # Do not keep the runtime/store lock while a model is executing.
            value=validate_map(normalize_map(self.provider.extract([{'id':s['id'],'text':s['text']} for s in sources])),sources)
            identifier=uuid.uuid4().hex
            with self.access.open(session) as stores:
                _,latest=self.snapshot(stores,branch)
                if latest!=digest or stores.workspace.get()['version']!=version:raise WorkspaceConflict('conversation changed; generate again')
                with stores.workspace.db:
                    stores.workspace.db.execute('INSERT INTO map_proposals(id,branch,workspace_version,fingerprint,sources,payload) VALUES (?,?,?,?,?,?)',(identifier,branch,version,digest,json.dumps(sources,ensure_ascii=False),json.dumps(value,ensure_ascii=False)))
            return {'id':identifier,'proposal':value,'sources':sources,'cached':False}
        finally:self.gate.release()

    def apply(self,session,identifier):
        if not isinstance(identifier,str) or not identifier or len(identifier)>80:raise ValueError('invalid proposal id')
        with self.access.open(session) as stores:
            self.table(stores);db=stores.workspace.db
            with db:
                db.execute('BEGIN IMMEDIATE')
                row=db.execute('SELECT * FROM map_proposals WHERE id=?',(identifier,)).fetchone()
                if not row:raise KeyError('proposal not found')
                if row['applied']:return {'workspace':stores.workspace.get(),'already_applied':True,'topic_ids':list(json.loads(row['node_ids'])['topics'].values())}
                _,digest=self.snapshot(stores,row['branch']);current=stores.workspace.get()
                if digest!=row['fingerprint'] or current['version']!=row['workspace_version']:raise WorkspaceConflict('sources or workspace changed')
                value=json.loads(row['payload']);sources=json.loads(row['sources']);data=deepcopy(current['data'])
                topic_ids={t['key']:uuid.uuid4().hex for t in value['topics']};provenance={};offset=len(data['sessions'])
                if 'Topics' not in data['categories']:data['categories'].append('Topics')
                for i,topic in enumerate(value['topics']):
                    node_ids={n['key']:uuid.uuid4().hex for n in topic['nodes']};nodes=[]
                    for j,node in enumerate(topic['nodes']):
                        source=next(s for s in sources if s['id']==node['evidence'][0]['source'])
                        nid=node_ids[node['key']];provenance[nid]=node
                        nodes.append({'id':nid,'title':node['title'],'content':f"[{node['state']}] {node['content']}",'kind':node['kind'],'source':source['document_id'],'x':50+(j%3)*255,'y':70+(j//3)*200})
                    data['sessions'].append({'id':topic_ids[topic['key']],'title':topic['title'],'category':'Topics','branch':row['branch'],'demo':False,'x':60+((offset+i)%3)*280,'y':70+((offset+i)//3)*220,'nodes':nodes,'edges':[[node_ids[e['from']],node_ids[e['to']]] for e in topic['edges']]})
                data['links'].extend([[topic_ids[e['from']],topic_ids[e['to']]] for e in value['links']])
                payload=stores.workspace.validate(data)
                if len(payload.encode())>2000000:raise ValueError('workspace too large')
                if current['version']==0:db.execute("INSERT INTO product_workspace VALUES ('local',1,?)",(payload,))
                else:db.execute("UPDATE product_workspace SET version=version+1,payload=? WHERE id='local'",(payload,))
                db.execute('UPDATE map_proposals SET applied=1,node_ids=? WHERE id=?',(json.dumps({'topics':topic_ids,'nodes':provenance}),identifier))
            return {'workspace':stores.workspace.get(),'already_applied':False,'topic_ids':list(topic_ids.values())}

    def provenance(self,session,node):
        with self.access.open(session) as stores:
            self.table(stores)
            for row in stores.workspace.db.execute('SELECT sources,node_ids FROM map_proposals WHERE applied=1 ORDER BY rowid DESC'):
                ids=json.loads(row['node_ids']);entry=ids.get('nodes',{}).get(node)
                if entry:
                    sources={s['id']:s for s in json.loads(row['sources'])}
                    return {'state':entry['state'],'evidence':[{'document_id':sources[e['source']]['document_id'],'quote':e['quote']} for e in entry['evidence']]}
            return {'evidence':[]}
