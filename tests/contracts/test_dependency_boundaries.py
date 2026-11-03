"""Protect independently replaceable boundaries, including provider-free product use."""
import ast
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
import unittest
from voice_context.product.services import ProductService


class DependencyBoundaryTests(unittest.TestCase):
    def test_product_use_cases_accept_store_port_without_runtime(self):
        class Store:
            def get(self):return {'version':3,'data':{'categories':['Inbox'],'sessions':[],'links':[]}}
        class Access:
            @contextmanager
            def open(self,session):
                if session!='client':raise ValueError('invalid client')
                yield SimpleNamespace(workspace=Store())
        service=ProductService(Access())
        self.assertEqual(service.workspace('client')['version'],3)
        with self.assertRaises(ValueError):service.workspace('invalid')
    def test_product_and_contract_modules_do_not_import_runtime_or_http(self):
        root=Path(__file__).resolve().parents[2]/'src/voice_context'
        for folder in ['contracts','product']:
            for path in (root/folder).rglob('*.py'):
                tree=ast.parse(path.read_text())
                for node in ast.walk(tree):
                    if isinstance(node,ast.ImportFrom):names=[node.module or '']
                    elif isinstance(node,ast.Import):names=[n.name for n in node.names]
                    else:continue
                    for name in names:
                        self.assertFalse(any(part in name.split('.') for part in ['infra','server','fastapi','native']),str(path))
