import copy
import tempfile
import unittest
from pathlib import Path
from voice_context.storage import connect
from voice_context.product_workspace import ProductWorkspace,WorkspaceConflict


class ProductWorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.path=str(Path(self.tmp.name)/'workspace.db');self.db=connect(self.path);self.store=ProductWorkspace(self.db)
        self.data={'categories':['Inbox','Research'],'sessions':[{'id':'s','title':'A real session','category':'Inbox','branch':None,'demo':False,'x':45,'y':55,'nodes':[{'id':'n','title':'An idea','content':'Spoken notes','kind':'idea','x':60,'y':100,'source':None},{'id':'m','title':'A question','content':'What next?','kind':'question','x':300,'y':80,'source':None}],'edges':[['n','m']]}],'links':[]}
    def tearDown(self):self.db.close();self.tmp.cleanup()
    def test_saved_map_survives_restart_and_stale_writer_cannot_overwrite(self):
        self.assertEqual(self.store.get()['version'],0)
        saved=self.store.save(0,self.data);self.assertEqual(saved['data'],self.data)
        other_db=connect(self.path);other=ProductWorkspace(other_db)
        try:
            self.assertEqual(other.get(),saved)
            self.data['sessions'][0]['nodes'][0]['x']=320;self.store.save(1,self.data)
            with self.assertRaises(WorkspaceConflict):other.save(1,saved['data'])
            self.assertEqual(other.get()['data'],self.data)
        finally:other_db.close()
    def test_invalid_graph_never_replaces_saved_state(self):
        self.store.save(0,self.data)
        for change in [lambda d:d['sessions'][0]['edges'].append(['n','missing']),lambda d:d['sessions'][0]['edges'].append(['m','n']),lambda d:d['sessions'][0].update(category='Unknown'),lambda d:d['sessions'][0].update(x=float('nan')),lambda d:d['sessions'][0]['nodes'].append(d['sessions'][0]['nodes'][0]),lambda d:d.update(categories=['Inbox','Inbox'])]:
            data=copy.deepcopy(self.data);change(data)
            with self.assertRaises(ValueError):self.store.save(1,data)
            self.assertEqual(self.store.get()['version'],1)
    def test_position_category_content_and_links_can_be_updated(self):
        self.store.save(0,self.data);self.data['sessions'][0]['category']='Research';self.data['sessions'][0]['nodes'][0].update(content='<script>plain text</script>',x=180,y=300)
        self.assertEqual(self.store.save(1,self.data)['data'],self.data)
