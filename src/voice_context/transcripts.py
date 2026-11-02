"""Final transcript event log and transactional outbox on the reference SQLite DB."""
import hashlib
import json


class Transcripts:
    def __init__(self, engine):
        self.engine = engine
        self.db = engine.db
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS transcripts (
          seq INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT UNIQUE NOT NULL,
          branch TEXT NOT NULL REFERENCES branches(id), session TEXT NOT NULL,
          text TEXT NOT NULL, complex INTEGER NOT NULL, revoked INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS transcript_visibility (
          branch TEXT NOT NULL REFERENCES branches(id), transcript_id TEXT NOT NULL REFERENCES transcripts(id),
          PRIMARY KEY(branch,transcript_id));
        CREATE TABLE IF NOT EXISTS transcript_outbox (
          task_id TEXT PRIMARY KEY, payload TEXT NOT NULL, published INTEGER NOT NULL DEFAULT 0);
        ''')

    def append(self, transcript_id, branch, session, text, complex=False):
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            old = self.db.execute('SELECT * FROM transcripts WHERE id=?', (transcript_id,)).fetchone()
            if old:
                if (old['branch'],old['session'],old['text'],old['complex']) != (branch,session,text,complex):
                    raise ValueError('transcript id reused with different content')
                return False
            versions = {r['key']:r['version'] for r in self.engine.recall(branch,limit=1000000)}
            payload = {'transcript_id':transcript_id,'branch':branch,'session':session,
                       'text':text,'complex':complex,'expected_versions':versions}
            self.db.execute('INSERT INTO transcripts(id,branch,session,text,complex) VALUES (?,?,?,?,?)',
                            (transcript_id,branch,session,text,complex))
            self.db.execute('INSERT INTO transcript_visibility VALUES (?,?)',(branch,transcript_id))
            self.db.execute('INSERT INTO transcript_outbox VALUES (?,?,0)',
                            ('transcript:'+transcript_id,json.dumps(payload,sort_keys=True)))
        return True

    def publish(self, queue):
        count=0
        for row in self.db.execute('SELECT * FROM transcript_outbox WHERE published=0 ORDER BY rowid').fetchall():
            # A crash between enqueue and marking published is safe: queue IDs deduplicate.
            queue.enqueue(row['task_id'],'extract',json.loads(row['payload']))
            with self.db:
                self.db.execute('UPDATE transcript_outbox SET published=1 WHERE task_id=?',(row['task_id'],))
            count+=1
        return count

    def recent(self, branch, limit=64):
        if not isinstance(limit,int) or limit<0:raise ValueError('nonnegative limit required')
        return [dict(r) for r in self.db.execute('''SELECT t.* FROM transcripts t JOIN transcript_visibility v
          ON v.transcript_id=t.id WHERE v.branch=? AND t.revoked=0 ORDER BY t.seq DESC LIMIT ?''',(branch,limit))]

    def revoke(self, transcript_id):
        with self.db:
            return self.db.execute('UPDATE transcripts SET revoked=1 WHERE id=? AND revoked=0',(transcript_id,)).rowcount==1

    def context(self, branch, query='', budget=4096, count=None):
        default_counter=count is None
        count=count or (lambda text:len(text.encode('utf-8')))
        serialize=lambda memory,recent:json.dumps({'memory':memory,'recent':recent},sort_keys=True,ensure_ascii=False)
        if budget<0 or count(serialize([],[]))>budget:raise ValueError('budget cannot fit context envelope')
        all_recent=self.recent(branch);recent=[];memory=[]
        for row in all_recent:
            # Keep origin branch/session; these are utterances, not confirmed memory.
            if count(serialize(memory,recent+[row]))<=budget:recent.append(row)
        for row in self.engine.recall(branch,query,limit=1000000):
            if count(serialize(memory+[row],recent))<=budget:memory.append(row)
        text=serialize(memory,recent)
        state=json.dumps({'memory':self.engine.recall(branch,limit=1000000),'recent':all_recent},sort_keys=True)
        return {'text':text,'records':memory,'recent':recent,'budget':budget,'cost':count(text),
                'omitted_recent':len(all_recent)-len(recent),
                'latest_event_omitted':bool(all_recent and (not recent or recent[0]['id']!=all_recent[0]['id'])),
                'revision':hashlib.sha256(state.encode()).hexdigest(),'counter':'utf8_bytes' if default_counter else 'caller_supplied'}
