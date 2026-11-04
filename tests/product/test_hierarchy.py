import copy
import os
import tempfile
import unittest
from pathlib import Path
from voice_context.contracts.workspace import WorkspaceShape
from voice_context.server.demo import DemoService
from voice_context.product.semantic_maps import SemanticMaps, validate_map
from product.test_semantic_maps import fixture


def leaf(id='doc'):
    return dict(id=id,title='Complete document',content='A full note, not another empty graph.',kind='document',source=None,x=50,y=70)


def nested():
    child=leaf()
    for i in range(5):child=dict(id=f'level-{i}',title=f'Section {i}',content='',kind='session',source=None,x=50,y=70,nodes=[child],edges=[])
    return dict(categories=['Inbox'],sessions=[dict(id='root',title='Full conversation',category='Inbox',kind='session',branch='main',demo=False,x=50,y=70,nodes=[child],edges=[])],links=[])


class HierarchyTests(unittest.TestCase):
    def test_recursive_roundtrip_and_invalid_containment(self):
        with tempfile.TemporaryDirectory() as folder:
            service=DemoService(str(Path(folder)/'state.db'))
            try:
                data=nested();result=service.product.workspace('test',{'version':0,'data':data})
                self.assertEqual(result['data'],data)
                for mutation in ['ancestor','leaf_children','wrong_scope']:
                    bad=copy.deepcopy(data);node=bad['sessions'][0]['nodes'][0]
                    if mutation=='ancestor':node['id']='root'
                    if mutation=='leaf_children':node['kind']='document'
                    if mutation=='wrong_scope':bad['sessions'][0]['edges']=[['level-4','doc']]
                    with self.subTest(mutation=mutation),self.assertRaises(ValueError):WorkspaceShape.validate(bad)
                self.assertEqual(service.product.workspace('test'),result)
            finally:service.close()

    def test_semantic_parent_tree_is_validated_and_applied_as_one_session(self):
        with tempfile.TemporaryDirectory() as folder:
            service=DemoService(str(Path(folder)/'state.db'))
            try:
                service.submit_demo('test','A complete planning discussion with an open learning question.')
                class Provider:
                    def extract(self,sources):
                        value=fixture(sources);value['topics'][1]['parent']='planning';return value
                maps=SemanticMaps(service.product.access,Provider());proposal=maps.propose('test','main');result=maps.apply('test',proposal['id'])
                roots=result['workspace']['data']['sessions'];self.assertEqual(len(roots),1)
                planning=roots[0]['nodes'][0];self.assertEqual(planning['nodes'][-1]['title'],'Learning')
                self.assertEqual(planning['nodes'][-1]['nodes'][0]['kind'],'document')
                value=fixture([{'id':'s1','text':'evidence'}]);value['topics'][0]['parent']='learning';value['topics'][1]['parent']='planning'
                with self.assertRaises(ValueError):validate_map(value,[{'id':'s1','text':'evidence'}])
            finally:service.close()

    @unittest.skipUnless(os.environ.get('VOICE_BROWSER_TEST'),'opt-in browser required')
    def test_five_levels_document_editor_breadcrumb_and_reload(self):
        import socket, threading, time, uvicorn
        from playwright.sync_api import sync_playwright,expect
        from voice_context.server.app import create_app
        with tempfile.TemporaryDirectory() as folder:
            app=create_app(str(Path(folder)/'state.db'),mode='demo');app.state.product.workspace('seed',{'version':0,'data':nested()})
            listener=socket.socket();listener.bind(('127.0.0.1',0));port=listener.getsockname()[1]
            server=uvicorn.Server(uvicorn.Config(app,log_level='error'));thread=threading.Thread(target=lambda:server.run(sockets=[listener]),daemon=True);thread.start()
            deadline=time.monotonic()+5
            while not server.started:
                if time.monotonic()>deadline:raise RuntimeError('server timeout')
                time.sleep(.02)
            try:
                with sync_playwright() as pw:
                    browser=pw.chromium.launch(headless=True,executable_path=os.environ.get('VOICE_CHROME_PATH'))
                    try:
                        page=browser.new_page(viewport={'width':1440,'height':1000});errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
                        page.goto(f'http://127.0.0.1:{port}/product#library');expect(page.locator('.graph-node')).to_have_count(1)
                        for title in ['Full conversation','Section 4','Section 3','Section 2','Section 1','Section 0']:
                            page.locator('.graph-node').filter(has_text=title).click()
                            expect(page.locator('#graph-title')).to_have_text(title)
                        page.reload();expect(page.locator('#graph-title')).to_have_text('Section 0')
                        expect(page.locator('#graph-breadcrumbs button')).to_have_count(7)
                        page.locator('.graph-node').click();expect(page.locator('#map-document-dialog')).to_be_visible()
                        page.fill('#map-document-content','Edited full document at depth six.');page.click('#map-document-save')
                        expect(page.locator('#map-document-notice')).to_have_text('Saved locally')
                        page.click('#map-document-close');page.reload();page.locator('.graph-node').click()
                        expect(page.locator('#map-document-content')).to_have_value('Edited full document at depth six.')
                        page.click('#map-document-expand');expect(page.locator('#map-document-dialog')).not_to_be_visible()
                        page.locator('.graph-node').click();expect(page.locator('#graph-title')).to_have_text('Complete document')
                        page.locator('.graph-node').click();expect(page.locator('#map-document-content')).to_have_value('Edited full document at depth six.')
                        page.click('#map-document-close');page.click('#graph-back');expect(page.locator('#graph-title')).to_have_text('Section 0')
                        page.get_by_role('button',name='Workspace',exact=True).click();expect(page.locator('.graph-node')).to_have_count(1)
                        page.click('#graph-new-document');page.fill('#graph-name','Top-level document');page.locator('#graph-name-form button[type=submit]').click()
                        expect(page.locator('.graph-node')).to_have_count(2);page.locator('.graph-node').filter(has_text='Top-level document').click()
                        expect(page.locator('#map-document-dialog')).to_be_visible();page.click('#map-document-close')
                        page.screenshot(path='/tmp/voiceline-recursive-overview.png',full_page=True)
                        self.assertEqual(errors,[])
                    finally:browser.close()
            finally:server.should_exit=True;thread.join(10)
