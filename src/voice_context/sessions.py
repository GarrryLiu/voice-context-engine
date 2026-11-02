"""Durable session generations, frozen reply context and session-wide stage budget."""
import hashlib
import json
import math
import uuid


class StaleInteraction(ValueError):pass


class Sessions:
    STAGES={'stt','reason','tts','summarize','archive','deep_reason'}
    def __init__(self,pipeline):
        self.pipeline=pipeline;self.db=pipeline.engine.db
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS interaction_sessions (
          id TEXT PRIMARY KEY, branch TEXT NOT NULL REFERENCES branches(id),
          epoch INTEGER NOT NULL, budget REAL NOT NULL, spent REAL NOT NULL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS replies (
          id TEXT PRIMARY KEY, session TEXT NOT NULL REFERENCES interaction_sessions(id),
          branch TEXT NOT NULL, epoch INTEGER NOT NULL, context TEXT NOT NULL, state TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS stage_calls (
          id TEXT PRIMARY KEY, reply TEXT NOT NULL REFERENCES replies(id), stage TEXT NOT NULL,
          reserved REAL NOT NULL, reported REAL, state TEXT NOT NULL);
        ''')

    def get(self,session):
        row=self.db.execute('SELECT * FROM interaction_sessions WHERE id=?',(session,)).fetchone()
        if not row:raise KeyError(session)
        return dict(row)

    def open(self,session,branch=None,budget=100):
        if not isinstance(session,str) or not session.strip() or not math.isfinite(budget) or budget<0:
            raise ValueError('session and finite nonnegative budget required')
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            if self.db.execute('SELECT 1 FROM interaction_sessions WHERE id=?',(session,)).fetchone():
                # Reconnecting cannot reset spending or reopen old response generations.
                self._advance(session,branch)
            else:self.db.execute('INSERT INTO interaction_sessions VALUES (?,?,1,?,0)',(session,branch or 'main',budget))
        return self.get(session)

    def _advance(self,session,branch=None):
        old=self.get(session);branch=branch or old['branch']
        if not self.db.execute('SELECT 1 FROM branches WHERE id=?',(branch,)).fetchone():raise ValueError('unknown branch')
        self.db.execute('UPDATE interaction_sessions SET epoch=epoch+1,branch=? WHERE id=?',(branch,session))
        self.db.execute("UPDATE replies SET state='cancelled' WHERE session=? AND state='active'",(session,))
        return self.get(session)

    def interrupt(self,session,branch=None):
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            result=self._advance(session,branch)
        return result

    def submit(self,session,transcript_id,text,epoch,final=True,complex=False):
        if not isinstance(final,bool) or not isinstance(complex,bool):raise ValueError('boolean flags required')
        if not final:return {'accepted':False,'reason':'partial transcript'}
        if not all(isinstance(x,str) and x.strip() for x in (transcript_id,text)) or len(text)>32000:raise ValueError('invalid transcript')
        with self.db:
            self.db.execute('BEGIN IMMEDIATE');state=self.get(session)
            old=self.db.execute('SELECT * FROM transcripts WHERE id=?',(transcript_id,)).fetchone()
            if old:
                if (old['session'],old['text'],old['complex'])!=(session,text,complex):
                    raise ValueError('transcript id reused')
                accepted=False
            else:
                if state['epoch']!=epoch:raise StaleInteraction('stale STT final')
                accepted=self.pipeline.transcripts.append_in_transaction(transcript_id,state['branch'],session,text,complex)
                state=self._advance(session)
        self.pipeline.transcripts.publish(self.pipeline.queue)
        return {'accepted':accepted,'task_id':'transcript:'+transcript_id,'session':state}

    def begin(self,session,request_id=None,budget=4096):
        request_id=request_id or uuid.uuid4().hex
        if not isinstance(request_id,str) or not request_id.strip():raise ValueError('request id required')
        with self.db:
            self.db.execute('BEGIN IMMEDIATE');state=self.get(session)
            old=self.db.execute('SELECT * FROM replies WHERE id=?',(request_id,)).fetchone()
            if old:
                if old['session']!=session:raise ValueError('request id reused across sessions')
                return self._ticket(old)
            context=self.pipeline.transcripts.context(state['branch'],budget=budget)
            if context['latest_event_omitted']:raise ValueError('context budget cannot fit latest confirmed utterance')
            state=self._advance(session)
            self.db.execute('INSERT INTO replies VALUES (?,?,?,?,?,?)',
                (request_id,session,state['branch'],state['epoch'],json.dumps(context,sort_keys=True),'active'))
            return self._ticket(self.db.execute('SELECT * FROM replies WHERE id=?',(request_id,)).fetchone())

    @staticmethod
    def _ticket(row):
        return {'request_id':row['id'],'session':row['session'],'branch':row['branch'],
                'epoch':row['epoch'],'context':json.loads(row['context'])}

    def valid(self,ticket):
        state=self.get(ticket['session'])
        row=self.db.execute('SELECT * FROM replies WHERE id=?',(ticket['request_id'],)).fetchone()
        return bool(row and row['state']=='active' and row['session']==ticket['session'] and
                    row['branch']==ticket['branch']==state['branch'] and row['epoch']==ticket['epoch']==state['epoch'])

    def reserve(self,ticket,call_id,stage,cost):
        if not isinstance(call_id,str) or not call_id.strip() or stage not in self.STAGES or not math.isfinite(cost) or cost<0:
            raise ValueError('valid stage, call id and finite nonnegative declared cost required')
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            if not self.valid(ticket):raise StaleInteraction('obsolete response')
            old=self.db.execute('SELECT * FROM stage_calls WHERE id=?',(call_id,)).fetchone()
            if old:
                if (old['reply'],old['stage'],old['reserved'])!=(ticket['request_id'],stage,cost):raise ValueError('call id reused')
                return False # do not execute an external call twice, even after restart
            state=self.get(ticket['session'])
            if state['spent']+cost>state['budget']:raise ValueError('session declared-unit budget exhausted')
            self.db.execute('UPDATE interaction_sessions SET spent=spent+? WHERE id=?',(cost,ticket['session']))
            self.db.execute('INSERT INTO stage_calls VALUES (?,?,?,?,NULL,?)',(call_id,ticket['request_id'],stage,cost,'reserved'))
        return True

    def finish(self,call_id,reported=None,failed=False):
        if reported is not None and (not math.isfinite(reported) or reported<0):raise ValueError('finite usage required')
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            row=self.db.execute('SELECT * FROM stage_calls WHERE id=?',(call_id,)).fetchone()
            if not row:raise KeyError(call_id)
            state='failed' if failed else 'completed'
            if row['state']!='reserved':
                if (row['reported'],row['state'])!=(reported,state):raise ValueError('conflicting call completion')
                return False
            # Admission accounting stays conservative; actual provider billing is separate.
            self.db.execute('UPDATE stage_calls SET reported=?,state=? WHERE id=?',(reported,state,call_id))
        return True
