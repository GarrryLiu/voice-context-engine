"""HTTP v1 workspace shape and graph integrity validation."""
import json
import math


class WorkspaceShape:
    @staticmethod
    def validate(data):
        def text(value,limit=200):
            if not isinstance(value,str) or not value.strip() or '\0' in value or len(value)>limit:raise ValueError('invalid text')
        def point(value):
            if not isinstance(value,(int,float)) or isinstance(value,bool) or not math.isfinite(value) or abs(value)>10000:raise ValueError('invalid position')
        if not isinstance(data,dict) or set(data)!={'categories','sessions','links'}:raise ValueError('invalid graph')
        categories=data['categories'];sessions=data['sessions'];links=data['links']
        if not isinstance(categories,list) or not 1<=len(categories)<=40:raise ValueError('invalid categories')
        for category in categories:text(category,60)
        if len(set(categories))!=len(categories):raise ValueError('duplicate category')
        if not isinstance(sessions,list) or len(sessions)>200:raise ValueError('too many sessions')
        ids=set()
        for session in sessions:
            if not isinstance(session,dict) or not {'id','title','category','branch','demo','x','y','nodes','edges'} <= set(session) or set(session)-{'id','title','category','branch','demo','x','y','nodes','edges','kind','content','source','document_id'}:raise ValueError('invalid session')
            for key in ['id','title','category']:text(session[key])
            if session['id'] in ids or session['category'] not in categories:raise ValueError('invalid session identity')
            ids.add(session['id'])
            if session['branch'] is not None:text(session['branch'],80)
            if not isinstance(session['demo'],bool):raise ValueError('invalid demo flag')
            for key in ['x','y']:point(session[key])
            if session.get('kind','session') not in {'session','document'}:raise ValueError('invalid root kind')
            if session.get('kind')=='document' and (session['nodes'] or session['edges']):raise ValueError('document cannot contain nodes')
            for key in ['content']:
                if key in session and (not isinstance(session[key],str) or len(session[key])>131072):raise ValueError('invalid content')
            for key in ['source','document_id']:
                if session.get(key) is not None:text(session[key])
            count=[0]
            def children(container,depth,ancestors):
                if depth>32:raise ValueError('hierarchy exceeds safety limit')
                nodes=container['nodes']
                if not isinstance(nodes,list) or len(nodes)>300:raise ValueError('too many nodes')
                node_ids=set()
                for node in nodes:
                    required={'id','title','content','kind','x','y','source'}
                    if not isinstance(node,dict) or not required<=set(node) or set(node)-required-{'nodes','edges','document_id'}:raise ValueError('invalid node')
                    text(node['id']);text(node['title'])
                    if node['id'] in node_ids or node['id'] in ancestors or node['kind'] not in {'idea','question','decision','document','voice','session'}:raise ValueError('invalid node identity')
                    node_ids.add(node['id']);count[0]+=1
                    if count[0]>2000:raise ValueError('too many nested nodes')
                    if not isinstance(node['content'],str) or len(node['content'])>131072 or '\0' in node['content']:raise ValueError('invalid content')
                    for key in ['source','document_id']:
                        if node.get(key) is not None:text(node[key])
                    for key in ['x','y']:point(node[key])
                    if node['kind']=='session':
                        if 'nodes' not in node or 'edges' not in node:raise ValueError('container requires child graph')
                        children(node,depth+1,ancestors|{node['id']})
                    elif 'nodes' in node or 'edges' in node:raise ValueError('leaf cannot contain graph')
                WorkspaceShape.edges(container['edges'],node_ids)
            children(session,0,{session['id']})
        WorkspaceShape.edges(links,ids)
        return json.dumps(data,ensure_ascii=False,allow_nan=False)

    @staticmethod
    def edges(edges,ids):
        if not isinstance(edges,list) or len(edges)>1000:raise ValueError('invalid edges')
        seen=set()
        for edge in edges:
            if not isinstance(edge,list) or len(edge)!=2 or any(not isinstance(i,str) or i not in ids for i in edge) or edge[0]==edge[1]:raise ValueError('invalid edge')
            pair=tuple(sorted(edge))
            if pair in seen:raise ValueError('duplicate edge')
            seen.add(pair)

