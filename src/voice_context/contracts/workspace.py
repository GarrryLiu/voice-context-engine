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
            if not isinstance(session,dict) or set(session)!={'id','title','category','branch','demo','x','y','nodes','edges'}:raise ValueError('invalid session')
            for key in ['id','title','category']:text(session[key])
            if session['id'] in ids or session['category'] not in categories:raise ValueError('invalid session identity')
            ids.add(session['id'])
            if session['branch'] is not None:text(session['branch'],80)
            if not isinstance(session['demo'],bool):raise ValueError('invalid demo flag')
            for key in ['x','y']:point(session[key])
            if not isinstance(session['nodes'],list) or len(session['nodes'])>300:raise ValueError('too many nodes')
            node_ids=set()
            for node in session['nodes']:
                if not isinstance(node,dict) or set(node)!={'id','title','content','kind','x','y','source'}:raise ValueError('invalid node')
                text(node['id']);text(node['title'])
                if node['id'] in node_ids or node['kind'] not in {'idea','question','decision','document','voice'}:raise ValueError('invalid node identity')
                node_ids.add(node['id'])
                if not isinstance(node['content'],str) or len(node['content'])>131072 or '\0' in node['content']:raise ValueError('invalid content')
                if node['source'] is not None:text(node['source'])
                for key in ['x','y']:point(node[key])
            WorkspaceShape.edges(session['edges'],node_ids)
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

