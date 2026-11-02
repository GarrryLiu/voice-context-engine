"""Loopback-only, single active turn voice prototype. Run via python -m."""
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
from .conversation import Conversation
from .openai_provider import settings,make_client,OpenAITextProvider,ModelJournal
from .audio_providers import OpenAIRecordingSTT,OpenAIPcmTTS

WEB=Path(__file__).with_name('web')
MIMES={'audio/webm':'webm','audio/ogg':'ogg','audio/mp4':'mp4','audio/wav':'wav','audio/x-wav':'wav'}


class VoiceService:
    def __init__(self,path,env_file='.env',factory=None,redis_url=None):
        self.path,self.env_file,self.factory,self.redis_url=path,env_file,factory,redis_url
        self.lock=threading.RLock();self.slots=threading.BoundedSemaphore(1)
        self.sessions={};self.active=set()
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
                    'recent':c.pipeline.transcripts.recent(state['branch'],limit=10)}
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
    def acquire(self,session):
        c=self.session(session)
        if not self.slots.acquire(blocking=False):raise ValueError('another turn is active')
        with self.lock:self.active.add(session)
        return c
    def stream(self,c,data,filename,stop=None,entered=None):
        if entered is not None:entered.set()
        events=queue.Queue(maxsize=256);stop=stop or threading.Event();finished=threading.Event()
        reply_id='voice-'+uuid.uuid4().hex;meta={};started=time.perf_counter()
        def emit(kind,**fields):
            if stop.is_set():raise RuntimeError('client disconnected')
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
                        with c.lock:meta.update(request_id=reply_id,epoch=c.pipeline.sessions.get(c.session)['epoch'])
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
                result=c.transcribe('utterance-'+uuid.uuid4().hex,stt,(data[i:i+4096] for i in range(0,len(data),4096)))
                with c.lock:transcript=c.pipeline.transcripts.recent(result['session']['branch'],1)[0]['text']
                emit('transcript',text=transcript,stt_seconds=time.perf_counter()-stt_start)
                result=c.respond(reply_id,ObservedText(),tts,context_budget=12000)
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
            while not stop.is_set():
                while True:
                    try:yield events.get_nowait()
                    except queue.Empty:break
                frame=None
                if meta:
                    with c.lock:
                        row=c.pipeline.engine.db.execute('SELECT sequence,bytes,rendered FROM output_chunks WHERE reply=? AND rendered<bytes ORDER BY sequence LIMIT 1',(reply_id,)).fetchone()
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
                try:c.interrupt()
                except Exception:pass
                worker.join(timeout=15)
            # Keep the slot reserved until a disconnected worker actually exits.
            def release():
                worker.join()
                with self.lock:self.active.discard(c.session)
                self.slots.release()
            if worker.is_alive():threading.Thread(target=release,daemon=True).start()
            else:release()
    def close(self):
        with self.lock:
            for session,c in self.sessions.items():
                if session not in self.active:c.close()


def create_app(path='voice-local.db',env_file='.env',service=None,redis_url=None):
    from fastapi import FastAPI,Request
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
    @app.post('/api/turn')
    async def turn(request:Request):
        mime=request.headers.get('content-type','').split(';')[0]
        if mime not in MIMES:return JSONResponse({'error':'unsupported_audio_type'},status_code=415)
        raw=await limited_body(request,2*1024*1024)
        if raw is None:return Response(status_code=413)
        if not raw:return Response(status_code=400)
        try:c=await asyncio.to_thread(service.acquire,request.headers.get('x-voice-session',''))
        except ValueError:return JSONResponse({'error':'busy_or_invalid_session'},status_code=409)
        stop=threading.Event();entered=threading.Event();advance_lock=threading.Lock()
        iterator=service.stream(c,raw,'capture.'+MIMES[mime],stop,entered)
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
                            with service.lock:service.active.discard(c.session)
                            service.slots.release()
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
    uvicorn.run(create_app(args.db,args.env_file,redis_url=args.redis_url),host='127.0.0.1',port=args.port,access_log=False)


if __name__=='__main__':main()
