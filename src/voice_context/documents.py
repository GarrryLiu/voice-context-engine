"""Editable documents with immutable source snapshots and optimistic versions.

Caller serializes a workspace connection. Capturing a final transcript runs inside
its existing transaction, so a confirmed utterance and its voice note are atomic.
Documents are separate from confirmed memory and are not silently fed to a model.
"""
import json
import time
import uuid


class DocumentConflict(ValueError):pass


class Documents:
    def __init__(self,db):
        self.db=db
        db.executescript('''
        CREATE TABLE IF NOT EXISTS documents (
          id TEXT PRIMARY KEY, title TEXT NOT NULL, content TEXT NOT NULL,
          kind TEXT NOT NULL, branch TEXT NOT NULL REFERENCES branches(id),
          collection TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'active',
          version INTEGER NOT NULL, created REAL NOT NULL, updated REAL NOT NULL,
          source_transcript TEXT REFERENCES transcripts(id), source_reply TEXT UNIQUE,
          source_text TEXT NOT NULL DEFAULT '', source_branch TEXT NOT NULL,
          filename TEXT NOT NULL DEFAULT '');
        CREATE TABLE IF NOT EXISTS document_versions (
          document TEXT NOT NULL REFERENCES documents(id), version INTEGER NOT NULL,
          title TEXT NOT NULL, content TEXT NOT NULL, branch TEXT NOT NULL,
          collection TEXT NOT NULL, status TEXT NOT NULL, created REAL NOT NULL,
          PRIMARY KEY(document,version));
        CREATE INDEX IF NOT EXISTS documents_updated ON documents(updated,id);
        ''')
    def _snapshot(self,identifier):
        self.db.execute('''INSERT INTO document_versions
          SELECT id,version,title,content,branch,collection,status,updated FROM documents WHERE id=?''',(identifier,))
    def backfill(self):
        tick=time.time()
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            self.db.execute('''INSERT INTO documents(id,title,content,kind,branch,version,created,updated,
              source_transcript,source_text,source_branch)
              SELECT 'voice:'||t.id,substr(t.text,1,64),t.text,'voice',t.branch,1,?,?,t.id,t.text,t.branch
              FROM transcripts t WHERE t.revoked=0 AND NOT EXISTS
              (SELECT 1 FROM documents d WHERE d.source_transcript=t.id AND d.kind='voice')
              ON CONFLICT DO NOTHING''',(tick,tick))
            self.db.execute('''INSERT INTO document_versions
              SELECT id,version,title,content,branch,collection,status,updated FROM documents d
              WHERE NOT EXISTS (SELECT 1 FROM document_versions v WHERE v.document=d.id AND v.version=d.version)''')
    def capture(self,transcript_id,branch,text):
        """No nested transaction: called only by atomic final transcript ingestion."""
        tick=time.time();identifier='voice:'+transcript_id
        self.db.execute('''INSERT INTO documents(id,title,content,kind,branch,version,created,updated,
          source_transcript,source_text,source_branch) VALUES (?,?,?,'voice',?,1,?,?,?,?,?)''',
          (identifier,text.strip()[:64],text,branch,tick,tick,transcript_id,text,branch))
        self._snapshot(identifier)
    @staticmethod
    def _text(value,limit,empty=False):
        if not isinstance(value,str) or '\0' in value or len(value.encode('utf-8'))>limit or (not empty and not value.strip()):
            raise ValueError('invalid document text')
        return value
    def get(self,identifier):
        self._text(identifier,4096)
        row=self.db.execute('SELECT * FROM documents WHERE id=?',(identifier,)).fetchone()
        if not row:raise KeyError(identifier)
        return dict(row)
    def listing(self,query='',kind='',status='active',branch='',offset=0):
        self._text(query,200,True)
        if kind not in ('','voice','draft','reference','note') or status not in ('active','archived','trash'):
            raise ValueError('invalid filter')
        if not isinstance(branch,str) or len(branch)>100 or not isinstance(offset,int) or not 0<=offset<=1000000:raise ValueError('invalid page')
        # Literal substring search; SQL values remain parameterized.
        search='%'+query.lower().replace('!','!!').replace('%','!%').replace('_','!_')+'%'
        rows=self.db.execute('''SELECT id,title,kind,branch,collection,status,version,created,updated,
          substr(content,1,180) AS preview FROM documents WHERE status=? AND (?='' OR kind=?)
          AND (?='' OR branch=?) AND (lower(title) LIKE ? ESCAPE '!' OR lower(content) LIKE ? ESCAPE '!'
          OR lower(collection) LIKE ? ESCAPE '!') ORDER BY updated DESC,id LIMIT 101 OFFSET ?''',
          (status,kind,kind,branch,branch,search,search,search,offset)).fetchall()
        return {'documents':[dict(r) for r in rows[:100]],'next_offset':offset+100 if len(rows)>100 else None}
    def create(self,title,content,branch,kind='note',filename=''):
        self._text(title,320);self._text(content,131072,True);self._text(filename,240,True)
        if kind not in ('note','reference'):raise ValueError('invalid creation kind')
        identifier='doc-'+uuid.uuid4().hex;tick=time.time()
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            if not self.db.execute('SELECT 1 FROM branches WHERE id=?',(branch,)).fetchone():raise ValueError('unknown thought')
            self.db.execute('''INSERT INTO documents(id,title,content,kind,branch,version,created,updated,
              source_text,source_branch,filename) VALUES (?,?,?,?,?,1,?,?,?,?,?)''',
              (identifier,title.strip(),content,kind,branch,tick,tick,content if kind=='reference' else '',branch,filename))
            self._snapshot(identifier)
        return self.get(identifier)
    def draft(self,reply_id,session):
        """Copy a fully acknowledged reply; source is obtained from its frozen context."""
        self._text(reply_id,4096)
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            row=self.db.execute("SELECT * FROM replies WHERE id=? AND session=? AND state='sealed'",(reply_id,session)).fetchone()
            if not row:raise ValueError('reply not complete')
            chunks=self.db.execute('SELECT * FROM output_chunks WHERE reply=?',(reply_id,)).fetchall()
            if not chunks or any(c['acknowledged']!=c['bytes'] for c in chunks):raise ValueError('reply not confirmed')
            old=self.db.execute('SELECT id FROM documents WHERE source_reply=?',(reply_id,)).fetchone()
            if old:return self.get(old['id'])
            recent=json.loads(row['context']).get('recent',[])
            if not recent:raise ValueError('reply has no source')
            source=self.db.execute('SELECT * FROM transcripts WHERE id=? AND revoked=0',(recent[0]['id'],)).fetchone()
            if not source:raise ValueError('source not available')
            segments=self.db.execute('SELECT text FROM response_segments WHERE reply=? ORDER BY sequence',(reply_id,)).fetchall()
            content=''.join(s['text'] for s in segments);self._text(content,131072)
            tick=time.time();identifier='draft:'+reply_id
            # One raw voice note and multiple reply drafts may share a transcript.
            self.db.execute('''INSERT INTO documents(id,title,content,kind,branch,version,created,updated,
              source_transcript,source_reply,source_text,source_branch) VALUES (?,?,?,'draft',?,1,?,?,?,?,?,?)''',
              (identifier,source['text'].strip()[:64],content,row['branch'],tick,tick,source['id'],reply_id,source['text'],source['branch']))
            self._snapshot(identifier)
        return self.get(identifier)
    def update(self,identifier,expected,changes):
        allowed={'title','content','branch','collection','status'}
        if not isinstance(changes,dict) or not changes or set(changes)-allowed:raise ValueError('invalid document patch')
        if not isinstance(expected,int) or isinstance(expected,bool) or expected<1:raise ValueError('version required')
        for field,limit in [('title',320),('content',131072),('branch',100),('collection',80)]:
            if field in changes:self._text(changes[field],limit,field in ('content','collection'))
        if 'status' in changes and changes['status'] not in ('active','archived','trash'):raise ValueError('invalid status')
        with self.db:
            self.db.execute('BEGIN IMMEDIATE');old=self.get(identifier)
            if old['version']!=expected:raise DocumentConflict('document changed; reload before saving')
            data={**old,**changes}
            if not self.db.execute('SELECT 1 FROM branches WHERE id=?',(data['branch'],)).fetchone():raise ValueError('unknown thought')
            if all(old[k]==data[k] for k in allowed):return old
            if expected>=1000:raise ValueError('document revision limit reached')
            self.db.execute('''UPDATE documents SET title=?,content=?,branch=?,collection=?,status=?,
              version=version+1,updated=? WHERE id=? AND version=?''',
              (data['title'].strip(),data['content'],data['branch'],data['collection'].strip(),data['status'],time.time(),identifier,expected))
            self._snapshot(identifier)
        return self.get(identifier)
    def history(self,identifier):
        self.get(identifier)
        return [dict(r) for r in self.db.execute('''SELECT version,title,created FROM document_versions
          WHERE document=? ORDER BY version DESC LIMIT 1000''',(identifier,)).fetchall()]
    def revision(self,identifier,version):
        self.get(identifier)
        if not isinstance(version,int) or isinstance(version,bool) or version<1:raise ValueError('invalid version')
        row=self.db.execute('SELECT * FROM document_versions WHERE document=? AND version=?',(identifier,version)).fetchone()
        if not row:raise KeyError(version)
        return dict(row)
    def restore(self,identifier,expected,version):
        # Lookups and update must share a connection lock supplied by the caller.
        row=self.revision(identifier,version)
        return self.update(identifier,expected,{'title':row['title'],'content':row['content']})
