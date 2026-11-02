"""Loopback-only, bounded concurrent turn voice prototype. Run via python -m."""
import argparse
import asyncio
import base64
from contextlib import asynccontextmanager
import json
import os
from pathlib import Path
import queue
import re
import secrets
import threading
import time
import uuid
from dataclasses import dataclass,field
from .conversation import Conversation
from .openai_provider import settings,make_client,OpenAITextProvider,ModelJournal
from .audio_providers import OpenAIRecordingSTT,OpenAIPcmTTS

WEB=Path(__file__).with_name('web')
MIMES={'audio/webm':'webm','audio/ogg':'ogg','audio/mp4':'mp4','audio/wav':'wav','audio/x-wav':'wav'}


@dataclass
class TurnLease:
    conversation: Conversation
    epoch: int
    stop: threading.Event=field(default_factory=threading.Event)
    released: bool=False
    @property
    def session(self):return self.conversation.session


class VoiceService:
    def __init__(self,path,env_file='.env',factory=None,redis_url=None,max_workers=4,live_factory=None):
        self.path,self.env_file,self.factory,self.redis_url=path,env_file,factory,redis_url
        self.lock=threading.RLock();self.slots=threading.BoundedSemaphore(max_workers)
        self.sessions={};self.active={};self.owners={};self.live_sessions=set();self.live_factory=live_factory
    def session(self,session):
        if not isinstance(session,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,80}',session):raise ValueError('invalid session')
        with self.lock:
            if session not in self.sessions:
                if len(self.sessions)>=4:raise ValueError('local session limit; restart server to clear idle handles')
                self.sessions[session]=Conversation(self.path,session,capacity=65536,audio_wait_seconds=5,
                    deadline_seconds=90,max_audio_bytes=2*1024*1024,publish_on_submit=False,redis_url=self.redis_url)
            return self.sessions[session]
    def state(self,session):
        c=self.session(session)
        with c.lock:
            state=c.pipeline.sessions.get(session)
            branches=[dict(r) for r in c.pipeline.engine.db.execute('SELECT id,parent FROM branches ORDER BY id').fetchall()]
            return {'session':session,'branch':state['branch'],'epoch':state['epoch'],'branches':branches,
                    'recent':c.pipeline.transcripts.recent(state['branch'],limit=10),
                    'responses':c.pipeline.context(branch=state['branch'],budget=12000)['responses']}
    def controls(self,session,action,branch=None):
        c=self.session(session)
        if action=='fork':
            if not isinstance(branch,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}',branch):raise ValueError('invalid branch')
            with c.lock:c.pipeline.engine.fork(branch,c.pipeline.sessions.get(session)['branch'])
        elif action=='switch':c.interrupt(branch)
        elif action=='interrupt':c.interrupt()
        else:raise ValueError('unknown action')
        return self.state(session)
    def acknowledge(self,session,data):
        c=self.session(session)
        with c.lock:
            if c.pipeline.sessions.get(session)['epoch']!=data['epoch']:raise ValueError('stale playback')
            return c.pipeline.sessions.acknowledge(session,data['request_id'],data['sequence'],data['offset'])
    def acquire(self,session,expected_epoch=None):
        c=self.session(session)
        if not self.slots.acquire(blocking=False):raise ValueError('provider worker limit reached')
        try:
            with self.lock,c.lock:
                if expected_epoch is not None and c.pipeline.sessions.get(session)['epoch']!=expected_epoch:
                    raise ValueError('stale turn')
                old=self.owners.get(session)
                if old:old.stop.set()
                lease=TurnLease(c,c.interrupt()['epoch'])
                self.owners[session]=lease
                self.active[session]=self.active.get(session,0)+1
                return lease
        except Exception:
            self.slots.release();raise
    def release(self,lease):
        with self.lock:
            if lease.released:return
            lease.released=True
            count=self.active[lease.session]-1
            if count:self.active[lease.session]=count
            else:self.active.pop(lease.session)
            if self.owners.get(lease.session) is lease:self.owners.pop(lease.session)
            self.slots.release()
    def stream(self,lease,data,filename,stop=None,entered=None,text_input=None):
        c=lease.conversation
        if entered is not None:entered.set()
        stop=stop or lease.stop
        events=queue.Queue(maxsize=256);stop=stop or threading.Event();finished=threading.Event()
        reply_id='voice-'+uuid.uuid4().hex;meta={};started=time.perf_counter()
        def emit(kind,**fields):
            if stop.is_set() or lease.stop.is_set():raise RuntimeError('client disconnected')
            events.put({'type':kind,**fields},timeout=2)
        def run():
            client=journal=None
            try:
                if self.factory:stt,text,tts,client,journal=self.factory(filename,lambda s:emit('partial',text=s))
                else:
                    client=make_client(settings(self.env_file));journal=ModelJournal(self.path)
                    stt=OpenAIRecordingSTT(client,filename,journal=journal,on_partial=lambda s:emit('partial',text=s))
                    text=OpenAITextProvider(settings(self.env_file)['LLM_MODEL'],client,journal,max_output_tokens=128,deadline_seconds=75)
                    tts=OpenAIPcmTTS(client,journal=journal)
                class ObservedText:
                    name=text.name
                    def stream(self,context,cancelled,request_id):
                        with c.lock:
                            reply=c.pipeline.engine.db.execute('SELECT epoch FROM replies WHERE id=?',(reply_id,)).fetchone()
                            meta.update(request_id=reply_id,epoch=reply['epoch'])
                            lease.epoch=meta['epoch']
                        emit('reply',**meta)
                        stream=text.stream(context,cancelled,request_id)
                        try:
                            for delta in stream:
                                emit('text',text=delta.decode() if isinstance(delta,bytes) else delta,**meta)
                                yield delta
                        finally:
                            if hasattr(stream,'close'):stream.close()
                emit('status',text='正在转写')
                stt_start=time.perf_counter()
                if stop.is_set() or lease.stop.is_set():return
                if text_input is None:
                    result=c.transcribe('utterance-'+uuid.uuid4().hex,stt,(data[i:i+4096] for i in range(0,len(data),4096)),expected_epoch=lease.epoch,on_begin=lambda ticket:setattr(lease,'epoch',ticket['epoch']))
                    with c.lock:transcript=c.pipeline.transcripts.recent(result['session']['branch'],1)[0]['text']
                    reply_epoch=result['session']['epoch']
                else:
                    transcript=text_input;reply_epoch=lease.epoch
                emit('transcript',text=transcript,stt_seconds=time.perf_counter()-stt_start)
                result=c.respond(reply_id,ObservedText(),tts,context_budget=12000,expected_epoch=reply_epoch)
                emit('generated',total_seconds=time.perf_counter()-started,metrics=getattr(text,'last_call',None),**meta)
            except Exception as error:
                try:emit('error',error=type(error).__name__,message='本轮未完成，请检查连接或稍后重试。')
                except Exception:pass
            finally:
                try:
                    if client:client.close()
                finally:
                    try:
                        if journal:journal.close()
                    finally:finished.set()
        worker=threading.Thread(target=run,daemon=True);worker.start()
        try:
            while not stop.is_set() and not lease.stop.is_set():
                while True:
                    try:yield events.get_nowait()
                    except queue.Empty:break
                frame=None
                if meta:
                    with c.lock:
                        row=None
                        if meta['epoch']==c.pipeline.sessions.get(c.session)['epoch']:row=c.pipeline.engine.db.execute('SELECT sequence,bytes,rendered FROM output_chunks WHERE reply=? AND rendered<bytes ORDER BY sequence LIMIT 1',(reply_id,)).fetchone()
                        if row:
                            pcm,n=c.render(min(4096,row['bytes']-row['rendered']))
                            if n:frame={'type':'audio',**meta,'sequence':row['sequence'],'offset':row['rendered']+n,
                                        'sample_rate':24000,'format':'pcm_s16le','data':base64.b64encode(pcm[:n]).decode()}
                if frame:yield frame
                elif finished.is_set() and events.empty():break
                else:time.sleep(.005)
            yield {'type':'done',**meta,'server_seconds':time.perf_counter()-started}
        finally:
            stop.set()
            if worker.is_alive():
                try:
                    with self.lock,c.lock:
                        if self.owners.get(c.session) is lease and c.pipeline.sessions.get(c.session)['epoch']==lease.epoch:c.interrupt()
                except Exception:pass
                worker.join(timeout=.05)
            # Keep the slot reserved until a disconnected worker actually exits.
            def release():
                worker.join()
                self.release(lease)
            if worker.is_alive():threading.Thread(target=release,daemon=True).start()
            else:release()
    def close(self):
        with self.lock:
            for session,c in self.sessions.items():
                if session not in self.active and session not in self.live_sessions:c.close()


def create_app(path='voice-local.db',env_file='.env',service=None,redis_url=None):
    from fastapi import FastAPI,Request,WebSocket
    from fastapi.responses import HTMLResponse,Response,JSONResponse,StreamingResponse
    service=service or VoiceService(path,env_file,redis_url=redis_url);token=secrets.token_urlsafe(32)
    @asynccontextmanager
    async def lifespan(app):
        yield
        service.close()
    app=FastAPI(lifespan=lifespan,docs_url=None,redoc_url=None,openapi_url=None)
    app.state.voice=service;app.state.local_token=token
    @app.middleware('http')
    async def local_only(request,call_next):
        host=request.headers.get('host','').split(':')[0]
        if host not in {'localhost','127.0.0.1','testserver'}:return Response(status_code=403)
        origin=request.headers.get('origin')
        if origin and origin!=str(request.base_url).rstrip('/'):return Response(status_code=403)
        if request.url.path.startswith('/api/') and not secrets.compare_digest(request.headers.get('x-voice-token',''),token):return Response(status_code=403)
        response=await call_next(request)
        response.headers['Cache-Control']='no-store'
        response.headers['X-Content-Type-Options']='nosniff'
        response.headers['Content-Security-Policy']="default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; media-src 'self' blob:; frame-ancestors 'none'"
        return response
    @app.get('/')
    def index():return HTMLResponse((WEB/'index.html').read_text().replace('__LOCAL_TOKEN__',token))
    @app.get('/app.js')
    def js():return Response((WEB/'app.js').read_text(),media_type='text/javascript')
    @app.get('/live.js')
    def live_js():return Response((WEB/'live.js').read_text(),media_type='text/javascript')
    @app.get('/capture.js')
    def capture_js():return Response((WEB/'capture.js').read_text(),media_type='text/javascript')
    @app.websocket('/api/live')
    async def live(ws:WebSocket):
        from .realtime_stt import serve
        await serve(ws,service,token)
    @app.get('/style.css')
    def css():return Response((WEB/'style.css').read_text(),media_type='text/css')
    @app.get('/api/state')
    def state(request:Request):
        try:return service.state(request.headers.get('x-voice-session',''))
        except ValueError:return JSONResponse({'error':'invalid_or_full_session'},status_code=400)
    @app.post('/api/control')
    async def control(request:Request):
        raw=await limited_body(request,4096)
        if raw is None:return Response(status_code=413)
        try:
            data=json.loads(raw)
            return await asyncio.to_thread(service.controls,request.headers.get('x-voice-session',''),data['action'],data.get('branch'))
        except (ValueError,KeyError,TypeError):return JSONResponse({'error':'invalid_control'},status_code=400)
        except Exception:return JSONResponse({'error':'control_failed'},status_code=409)
    @app.post('/api/ack')
    async def ack(request:Request):
        raw=await limited_body(request,4096)
        if raw is None:return Response(status_code=413)
        try:
            data=json.loads(raw)
            return {'advanced':await asyncio.to_thread(service.acknowledge,request.headers.get('x-voice-session',''),data)}
        except Exception:return JSONResponse({'error':'invalid_or_stale_ack'},status_code=409)
    @app.post('/api/reply')
    @app.post('/api/turn')
    async def turn(request:Request):
        text_input=None
        mime=request.headers.get('content-type','').split(';')[0]
        if request.url.path=='/api/reply':
            raw=await limited_body(request,4096)
            if raw is None:return Response(status_code=413)
            try:
                data=json.loads(raw);session=request.headers.get('x-voice-session','')
                conversation=service.session(session)
                with service.lock,conversation.lock:
                    row=conversation.pipeline.engine.db.execute('SELECT text,branch FROM transcripts WHERE id=? AND session=? AND revoked=0',
                        (data['transcript_id'],session)).fetchone()
                    state=conversation.pipeline.sessions.get(session)
                    if not row or row['branch']!=state['branch'] or state['epoch']!=data['epoch']:raise ValueError('stale transcript')
                    c=service.acquire(session,expected_epoch=data['epoch']);text_input=row['text']
            except (ValueError,KeyError,TypeError):return JSONResponse({'error':'stale_or_busy_reply'},status_code=409)
        else:
            if mime not in MIMES:return JSONResponse({'error':'unsupported_audio_type'},status_code=415)
            raw=await limited_body(request,2*1024*1024)
            if raw is None:return Response(status_code=413)
            if not raw:return Response(status_code=400)
            try:c=await asyncio.to_thread(service.acquire,request.headers.get('x-voice-session',''))
            except ValueError:return JSONResponse({'error':'busy_or_invalid_session'},status_code=409)
        stop=c.stop;entered=threading.Event();advance_lock=threading.Lock()
        iterator=service.stream(c,raw,'capture.'+MIMES.get(mime,'wav'),stop,entered,text_input=text_input)
        def advance():
            with advance_lock:
                try:return next(iterator)
                except StopIteration:return None
        async def body():
            try:
                while True:
                    item=await asyncio.to_thread(advance)
                    if item is None:break
                    yield json.dumps(item,ensure_ascii=False)+'\n'
            finally:
                stop.set()
                def close():
                    with advance_lock:
                        iterator.close()
                        if not entered.is_set():
                            service.release(c)
                import anyio
                with anyio.CancelScope(shield=True):await asyncio.to_thread(close)
        return StreamingResponse(body(),media_type='application/x-ndjson')
    return app


async def limited_body(request,limit):
    output=bytearray()
    async for block in request.stream():
        if len(output)+len(block)>limit:return None
        output.extend(block)
    return bytes(output)


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--db',default=os.environ.get('VOICE_DATABASE_URL','voice-local.db'))
    parser.add_argument('--env-file',default='.env');parser.add_argument('--port',type=int,default=8765)
    parser.add_argument('--redis-url',default=os.environ.get('VOICE_REDIS_URL'))
    args=parser.parse_args()
    settings(args.env_file) # Validate privately before opening the listener.
    import uvicorn
    uvicorn.run(create_app(args.db,args.env_file,redis_url=args.redis_url),host='127.0.0.1',port=args.port,access_log=False,ws_max_size=16384,ws_max_queue=8)


if __name__=='__main__':main()
