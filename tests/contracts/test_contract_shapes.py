import unittest
from voice_context.contracts import capabilities
from voice_context.contracts.workspace import WorkspaceShape


class ContractShapeTests(unittest.TestCase):
    def test_demo_and_connected_advertise_same_routes_and_semantics(self):
        real=capabilities();demo=capabilities('demo')
        self.assertEqual(real['endpoints'],demo['endpoints'])
        self.assertEqual(real['semantics'],demo['semantics'])
        self.assertEqual(real['contract_version'],'1')
    def test_product_identity_is_not_a_runtime_handle(self):
        data={'categories':['Inbox'],'sessions':[{'id':'product-session','title':'A thought','category':'Inbox','branch':'context-branch','demo':False,'x':0,'y':0,'nodes':[],'edges':[]}],'links':[]}
        self.assertIn('product-session',WorkspaceShape.validate(data))
        data['sessions'][0]['edges']=[['runtime-browser-id','product-session']]
        with self.assertRaises(ValueError):WorkspaceShape.validate(data)
