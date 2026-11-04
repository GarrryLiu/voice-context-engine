import json
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from voice_context.product.semantic_maps import SemanticMaps,validate_map,normalize_map,MapUnavailable
from voice_context.product.product_workspace import WorkspaceConflict
from voice_context.server.demo import DemoService


def fixture(sources):
    evidence=[{'source':s['id'],'quote':s['text'][:24]} for s in sources[:2]]
    def node(key,kind,state):return {'key':key,'title':key,'content':'Source-backed '+key,'kind':kind,'state':state,'evidence':deepcopy(evidence)}
    return {'title':'Reviewed topics','topics':[{'key':'planning','title':'Planning','summary':'Plans and their revisions','nodes':[node('old','decision','superseded'),node('current','decision','confirmed')],'edges':[{'from':'current','to':'old','relation':'revises','evidence':deepcopy(evidence)}]},{'key':'learning','title':'Learning','summary':'Open questions','nodes':[node('question','question','open')],'edges':[]}],'links':[{'from':'planning','to':'learning','relation':'related','evidence':deepcopy(evidence)}]}


class FakeProvider:
    def __init__(self):self.calls=0
    def extract(self,sources):self.calls+=1;return fixture(sources)


class SemanticMapsTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.service=DemoService(str(Path(self.tmp.name)/'test.db'));self.provider=FakeProvider();self.maps=SemanticMaps(self.service.product.access,self.provider)
        self.service.submit_demo('test','Plan at six. This was the old decision.')
        self.service.submit_demo('test','Revise the plan to seven. Learning is related; offline is undecided.')
    def tearDown(self):self.service.close();self.tmp.cleanup()
    def test_preview_is_separate_apply_is_idempotent_with_sources_and_links(self):
        original=self.service.product.workspace('test');proposal=self.maps.propose('test','main')
        self.assertEqual(self.service.product.workspace('test'),original)
        self.assertEqual(self.maps.propose('test','main')['id'],proposal['id']);self.assertEqual(self.provider.calls,1)
        result=self.maps.apply('test',proposal['id']);data=result['workspace']['data']
        self.assertEqual(len(data['sessions']),2);self.assertEqual(len(data['links']),1)
        nodes=data['sessions'][0]['nodes'];self.assertIn('[superseded]',nodes[0]['content'])
        self.assertEqual(len(self.maps.provenance('test',nodes[0]['id'])['evidence']),2)
        self.assertTrue(self.maps.apply('test',proposal['id'])['already_applied'])
        self.assertEqual(self.maps.propose('test','main')['id'],proposal['id']);self.assertEqual(self.provider.calls,1)
        self.assertEqual(len(self.service.product.documents('test','list',{})['documents']),2)
    def test_source_append_and_workspace_write_reject_stale_suggestion(self):
        proposal=self.maps.propose('test','main');self.service.submit_demo('test','New confirmed speech.')
        with self.assertRaises(WorkspaceConflict):self.maps.apply('test',proposal['id'])
        self.assertEqual(self.service.product.workspace('test')['version'],0)
        proposal=self.maps.propose('test','main');self.service.product.workspace('test',{'version':0,'data':{'categories':['Inbox'],'sessions':[],'links':[]}})
        with self.assertRaises(WorkspaceConflict):self.maps.apply('test',proposal['id'])
    def test_reject_unknown_source_and_fabricated_quote_and_invalid_state(self):
        sources=[{'id':'s1','text':'actual evidence'}]
        for mutation in ['quote','source','state','link','revision_direction']:
            value=fixture(sources)
            if mutation=='quote':value['topics'][0]['nodes'][0]['evidence'][0]['quote']='invented quote'
            if mutation=='source':value['topics'][0]['nodes'][0]['evidence'][0]['source']='missing'
            if mutation=='state':value['topics'][1]['nodes'][0]['state']='confirmed'
            if mutation=='link':value['links'][0]['to']='missing'
            if mutation=='revision_direction':value['topics'][0]['edges'][0].update({'from':'old','to':'current'})
            with self.subTest(mutation=mutation),self.assertRaises(ValueError):validate_map(value,sources)
    def test_resolve_cross_topic_node_links_without_guessing(self):
        sources=[{'id':'s1','text':'actual evidence'}];value=fixture(sources)
        value['topics'][1]['edges']=[{'from':'question','to':'current','relation':'related','evidence':[{'source':'s1','quote':'actual'}]}]
        value['links']=[]
        normalized=validate_map(normalize_map(value),sources)
        self.assertEqual(normalized['topics'][1]['edges'],[])
        self.assertEqual(normalized['links'][0]['from'],'learning')
        self.assertEqual(normalized['links'][0]['to'],'planning')
        value['topics'][1]['edges'][0]['to']='invented'
        with self.assertRaises(ValueError):normalize_map(value)

    def test_provider_failure_does_not_modify_workspace(self):
        class Invalid:
            def extract(self,sources):return {}
        self.maps.provider=Invalid()
        with self.assertRaises(ValueError):self.maps.propose('test','main')
        self.assertEqual(self.service.product.workspace('test')['version'],0)
        with self.assertRaises(MapUnavailable):SemanticMaps(self.service.product.access).propose('test','main')
    def test_changed_sources_during_model_execution_rejected(self):
        service=self.service
        class Changing:
            def extract(self,sources):service.submit_demo('test','Another thought while processing.');return fixture(sources)
        self.maps.provider=Changing()
        with self.assertRaises(WorkspaceConflict):self.maps.propose('test','main')
    def test_http_errors_and_explicit_model_injection(self):
        from fastapi.testclient import TestClient
        from voice_context.server.app import create_app
        app=create_app(service=self.service,mode='demo',map_provider=self.provider)
        with TestClient(app) as client:
            headers={'x-voice-token':app.state.local_token,'x-voice-session':'test'}
            self.assertEqual(client.get('/api/maps/status').status_code,403)
            self.assertTrue(client.get('/api/maps/status',headers=headers).json()['enabled'])
            proposal=client.post('/api/maps/propose',headers=headers,json={'branch':'main'})
            self.assertEqual(proposal.status_code,200)
            result=client.post('/api/maps/apply',headers=headers,json={'id':proposal.json()['id']})
            self.assertEqual(result.status_code,200)
            self.assertEqual(len(result.json()['workspace']['data']['sessions']),2)
