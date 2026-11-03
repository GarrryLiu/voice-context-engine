"""Deterministic text-to-simulated-voice adapter. No native library or providers.

Uses the same persisted transcript, reply/ACK and product stores as connected
mode. It deliberately refuses live audio/STT; input text is explicitly a fixture.
"""
import base64
import hashlib
import re
import threading
import time
import uuid
from ..gateway import Pipeline
from ..storage import connect,table_exists
from ..infra.runtime.service import RuntimeService
from ..product.services import ProductService
from .adapters import RuntimeProductAccess


def claim_demo_database(path):
    db=connect(path,check_same_thread=False)
    try:
        with db:
            db.execute('BEGIN IMMEDIATE')
            if not table_exists(db,'demo_database'):
                if table_exists(db,'interaction_sessions') or table_exists(db,'documents'):
                    raise ValueError('demo mode requires its own database; choose a new demo path')
                db.execute('CREATE TABLE demo_database (id INTEGER PRIMARY KEY)')
                db.execute('INSERT INTO demo_database VALUES (1)')
    finally:db.close()


class DemoConversation:
    def __init__(self,path,session):
        self.session=session;self.lock=threading.RLock()
        self.pipeline=Pipeline(path,check_same_thread=False,publish_on_submit=False)
        if not self.pipeline.engine.db.execute("SELECT 1 FROM branches WHERE id='main'").fetchone():self.pipeline.engine.fork('main')
        self.pipeline.sessions.open(session)
    def interrupt(self,branch=None):
        with self.lock:return self.pipeline.sessions.interrupt(self.session,branch)
    def close(self):self.pipeline.close()


class DemoService(RuntimeService):
    def __init__(self,path):
        claim_demo_database(path)
        super().__init__(path,factory=None)
        self.product=ProductService(RuntimeProductAccess(self))
    def session(self,session):
        if not isinstance(session,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,80}',session):raise ValueError('invalid session')
        with self.lock:
            if session not in self.sessions:
                if len(self.sessions)>=4:raise ValueError('local session limit')
                self.sessions[session]=DemoConversation(self.path,session)
            return self.sessions[session]
    def submit_demo(self,session,text):
        if not isinstance(text,str) or not text.strip() or len(text)>32000:raise ValueError('text required')
        c=self.session(session)
        with c.lock:
            state=c.pipeline.sessions.get(session);identifier='demo-'+uuid.uuid4().hex
            result=c.pipeline.sessions.submit(session,identifier,text,state['epoch'])
            return {'transcript_id':identifier,'epoch':result['session']['epoch']}
    def stream(self,lease,data,filename,stop=None,entered=None,text_input=None):
        if entered is not None:entered.set()
        stop=stop or lease.stop;c=lease.conversation;started=time.perf_counter()
        try:
            if text_input is None:raise ValueError('demo text input required')
            with c.lock:
                ticket=c.pipeline.sessions.begin(c.session,'demo-reply-'+uuid.uuid4().hex,budget=12000)
                lease.epoch=ticket['epoch']
                text='Demo reply: Let’s build on that thought. You can organize it in your session map, add a question, and return to it later.'
                c.pipeline.sessions.segment(ticket,0,text)
                pcm=bytes(4800)
                with c.pipeline.engine.db:
                    c.pipeline.engine.db.execute('''INSERT INTO output_chunks(reply,sequence,segment,bytes,sha256,rendered,acknowledged)
                      VALUES (?,0,0,?,?,?,0)''',(ticket['request_id'],len(pcm),hashlib.sha256(pcm).hexdigest(),len(pcm)))
                call=ticket['request_id']+':tts:0'
                c.pipeline.sessions.reserve(ticket,call,'tts',0,provider='demo-fixture')
                c.pipeline.sessions.finish(call,reported=0,elapsed=0)
                c.pipeline.sessions.seal(ticket)
            meta={'request_id':ticket['request_id'],'epoch':ticket['epoch']}
            for event in [dict(type='transcript',text=text_input,stt_seconds=0),dict(type='reply',**meta),
                          dict(type='text',text=text,**meta),dict(type='audio',sequence=0,offset=len(pcm),sample_rate=24000,format='pcm_s16le',data=base64.b64encode(pcm).decode(),**meta),
                          dict(type='generated',total_seconds=time.perf_counter()-started,metrics={'provider':'demo-fixture'},**meta),dict(type='done',**meta)]:
                if stop.is_set() or lease.stop.is_set():break
                with c.lock:
                    if c.pipeline.sessions.get(c.session)['epoch']!=lease.epoch:break
                yield event
        finally:self.release(lease)
