"""Bounded, server-authenticated live transcription; no microphone or credentials in logs."""
import asyncio
import base64
import hashlib
import json
import time
import uuid
from collections import deque
from contextlib import asynccontextmanager
from .openai_provider import settings,ModelJournal
from .sessions import StaleInteraction

MODEL='gpt-live-transcribe'
CONFIG={'type':'session.update','session':{'type':'transcription','audio':{'input':{
    'format':{'type':'audio/pcm','rate':24000},
    'transcription':{'model':MODEL,'delay':'low'},'turn_detection':None}}}}


@asynccontextmanager
async def connect(env_file):
    from websockets.asyncio.client import connect as websocket_connect
    key=settings(env_file)['LLM_API_KEY']
    async with websocket_connect('wss://api.openai.com/v1/realtime?intent=transcription',
            additional_headers={'Authorization':'Bearer '+key},open_timeout=10,close_timeout=2,
            max_size=262144,max_queue=8,write_limit=32768) as upstream:
        yield upstream


class LiveTranscription:
    """One local socket / model session, 120 s, 5.76 MB PCM and 32 committed turns.

    Final results are epoch-fenced. A newer speech onset or branch switch discards
    an unconfirmed old final; a confirmed final is immediately transactional.
    """
    def __init__(self,c):
        self.c=c;self.epoch=None;self.speaking=False;self.bytes=0;self.turn_bytes=0
        self.pending=deque();self.items={};self.turns=0;self.started=time.monotonic();self.usage=[]
        self.connection_id='live-'+uuid.uuid4().hex
    def onset(self):
        with self.c.lock:
            self.epoch=self.c.interrupt()['epoch']
        self.speaking=True;self.turn_bytes=0
        return {'type':'speech_started','epoch':self.epoch}
    def accept(self,item,text):
        owner=self.items.pop(item,None)
        if owner is None or not isinstance(text,str) or not text.strip():return None
        if len(text.encode())>32000:raise ValueError('transcript bound')
        with self.c.lock:
            try:result=self.c.pipeline.sessions.submit(self.c.session,self.connection_id+':'+item,text,owner)
            except StaleInteraction:return None
            self.c.native.advance(result['session']['epoch'])
        return {'type':'transcript','text':text,'transcript_id':self.connection_id+':'+item,
                'epoch':result['session']['epoch']}
    async def run(self,ws,upstream):
        await upstream.send(json.dumps(CONFIG))
        # Do not start microphone upload before configuration is acknowledged.
        async def local():
            while True:
                message=await ws.receive()
                if message['type']=='websocket.disconnect':return
                pcm=message.get('bytes')
                if pcm is not None:
                    if not self.speaking or not 0<len(pcm)<=9600 or len(pcm)%2:raise ValueError('invalid PCM')
                    self.bytes+=len(pcm);self.turn_bytes+=len(pcm)
                    if self.bytes>5760000 or self.turn_bytes>960000:raise ValueError('audio bound')
                    await upstream.send(json.dumps({'type':'input_audio_buffer.append','audio':base64.b64encode(pcm).decode()}))
                else:
                    raw=message.get('text','')
                    if len(raw)>256:raise ValueError('control bound')
                    event=json.loads(raw)
                    if event.get('type')=='start' and not self.speaking:
                        await ws.send_json(self.onset())
                    elif event.get('type')=='commit' and self.speaking:
                        if self.turn_bytes<4800:raise ValueError('turn too short')
                        self.speaking=False;self.turns+=1
                        if self.turns>32 or len(self.pending)+len(self.items)>=8:raise ValueError('pending turn bound')
                        self.pending.append(self.epoch)
                        await upstream.send(json.dumps({'type':'input_audio_buffer.commit'}))
                    else:raise ValueError('invalid live control')
        async def remote():
            async for raw in upstream:
                if not isinstance(raw,str) or len(raw)>262144:raise ValueError('provider event bound')
                event=json.loads(raw);kind=event.get('type');item=event.get('item_id')
                if kind in ('session.updated','transcription_session.updated'):
                    await ws.send_json({'type':'ready','model':MODEL,'sample_rate':24000})
                elif kind=='input_audio_buffer.committed':
                    if not self.pending or not isinstance(item,str) or len(item)>128 or item in self.items:raise ValueError('unexpected committed item')
                    self.items[item]=self.pending.popleft()
                elif kind=='conversation.item.input_audio_transcription.delta':
                    with self.c.lock:current=self.c.pipeline.sessions.get(self.c.session)['epoch']
                    if self.items.get(item)==current:
                        delta=event.get('delta','')
                        if not isinstance(delta,str) or len(delta.encode())>32000:raise ValueError('delta bound')
                        await ws.send_json({'type':'partial','text':delta,'epoch':current})
                elif kind=='conversation.item.input_audio_transcription.completed':
                    result=self.accept(item,event.get('transcript'))
                    if event.get('usage') and len(self.usage)<32:self.usage.append(event['usage'])
                    if result:await ws.send_json(result)
                elif kind in ('error','conversation.item.input_audio_transcription.failed'):
                    raise ValueError('transcription provider failure')
        tasks=[asyncio.create_task(local()),asyncio.create_task(remote())]
        try:
            done,_=await asyncio.wait(tasks,timeout=120,return_when=asyncio.FIRST_COMPLETED)
            if not done:raise TimeoutError('live duration bound')
            for task in done:task.result()
        finally:
            for task in tasks:task.cancel()
            await asyncio.gather(*tasks,return_exceptions=True)


async def serve(ws,service,token):
    # WebSocket requests bypass HTTP middleware: repeat host/origin/auth checks.
    host=ws.headers.get('host','').split(':')[0]
    origin=ws.headers.get('origin');expected=('https://' if ws.url.scheme=='wss' else 'http://')+ws.headers.get('host','')
    if host not in {'localhost','127.0.0.1','testserver'} or origin!=expected:
        await ws.close(code=1008);return
    await ws.accept();session=None;live=None;journal=None;call_id=None;started=time.perf_counter();complete=False;stage_id=None
    try:
        import secrets
        raw=await asyncio.wait_for(ws.receive_text(),5)
        if len(raw)>1024:raise ValueError('auth bound')
        auth=json.loads(raw)
        if not isinstance(auth.get('token'),str) or not secrets.compare_digest(auth['token'],token):raise ValueError('invalid token')
        c=service.session(auth.get('session'))
        with service.lock:
            if c.session in service.live_sessions or len(service.live_sessions)>=2:raise ValueError('live session bound')
            service.live_sessions.add(c.session);session=c.session
        live=LiveTranscription(c)
        with c.lock:
            ticket=c.begin(live.connection_id)
            stage_id=live.connection_id+':stt'
            c._reserve(ticket,stage_id,'stt',1,'openai:'+MODEL+':realtime')
        if not service.live_factory:
            journal=ModelJournal(service.path);call_id=live.connection_id
            journal.begin(call_id,MODEL,hashlib.sha256(call_id.encode()).hexdigest())
        factory=service.live_factory or connect
        async with factory(service.env_file) as upstream:await live.run(ws,upstream)
        complete=True
    except Exception:
        try:await ws.send_json({'type':'error','message':'实时转写连接已结束，请重新开始。'})
        except Exception:pass
    finally:
        if live and live.speaking:
            with live.c.lock:
                if live.epoch==live.c.pipeline.sessions.get(live.c.session)['epoch']:live.c.interrupt()
        if stage_id:live.c._finish(stage_id,started,failed=not complete)
        if journal:
            try:journal.finish(call_id,{'state':'completed' if complete else 'failed','elapsed_seconds':time.perf_counter()-started,
                'first_delta_seconds':None,'response_id':None,'error_code':None if complete else 'live_session_ended',
                'usage':{'audio_seconds_sent':live.bytes/48000,'measurement':'local PCM; provider usage when present', 'provider_turns':live.usage}})
            finally:journal.close()
        if session:
            with service.lock:service.live_sessions.discard(session)
        try:await ws.close()
        except Exception:pass
