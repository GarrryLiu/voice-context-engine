"""Product graph state, separate from runtime interaction sessions and memory."""
import json
from .contracts.workspace import WorkspaceShape


class WorkspaceConflict(ValueError):pass


class ProductWorkspace:
    def __init__(self,db):
        self.db=db
        db.execute('CREATE TABLE IF NOT EXISTS product_workspace (id TEXT PRIMARY KEY, version INTEGER NOT NULL, payload TEXT NOT NULL)')
        db.commit()

    def get(self):
        row=self.db.execute("SELECT version,payload FROM product_workspace WHERE id='local'").fetchone()
        return {'version':row['version'],'data':json.loads(row['payload'])} if row else {'version':0,'data':{'categories':['Inbox'],'sessions':[],'links':[]}}

    validate=staticmethod(WorkspaceShape.validate)

    def save(self,expected,data):
        if not isinstance(expected,int) or isinstance(expected,bool) or expected<0:raise ValueError('invalid version')
        payload=self.validate(data)
        if len(payload.encode())>2000000:raise ValueError('workspace too large')
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            if self.get()['version']!=expected:raise WorkspaceConflict('workspace changed')
            if expected==0:self.db.execute("INSERT INTO product_workspace VALUES ('local',1,?)",(payload,))
            else:self.db.execute("UPDATE product_workspace SET version=version+1,payload=? WHERE id='local'",(payload,))
        return self.get()
