"""Product use cases depend on a store-access port, never a voice worker."""
from typing import ContextManager,Protocol,Any


class ProductStoreAccess(Protocol):
    def open(self,session:str)->ContextManager[Any]:...


class ProductService:
    def __init__(self,access:ProductStoreAccess):self.access=access

    def documents(self,session,action,data):
        if not isinstance(data,dict):raise ValueError('object required')
        with self.access.open(session) as stores:
            store=stores.documents
            if action=='list':return store.listing(**data)
            if action=='get':return store.get(data['id'])
            if action=='revision':return store.revision(data['id'],data['revision'])
            if action=='history':return {'versions':store.history(data['id'])}
            if action=='create':return store.create(data['title'],data.get('content',''),data.get('branch') or stores.branch,data.get('kind','note'),data.get('filename',''))
            if action=='draft':return store.draft(data['reply_id'],session)
            if action=='change':return store.update(data['id'],data['version'],data['changes'])
            if action=='restore':return store.restore(data['id'],data['version'],data['restore_version'])
            raise ValueError('unknown document action')

    def workspace(self,session,data=None):
        with self.access.open(session) as stores:
            if data is None:return stores.workspace.get()
            return stores.workspace.save(data['version'],data['data'])
