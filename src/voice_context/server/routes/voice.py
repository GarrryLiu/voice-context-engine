import asyncio
import json
import threading
from fastapi import Request,WebSocket
from fastapi.responses import Response,JSONResponse,StreamingResponse
from ...contracts import capabilities
from ..http import limited_body

MIMES={'audio/webm':'webm','audio/ogg':'ogg','audio/mp4':'mp4','audio/wav':'wav','audio/x-wav':'wav'}

def register(app,service,token,mode='connected'):
    @app.websocket('/api/live')
    async def live(ws:WebSocket):
        if mode=='demo':
            await ws.close(code=1008);return
        from ...realtime_stt import serve
        await serve(ws,service,token)
    @app.get('/api/capabilities')
    def api_capabilities():return capabilities(mode)
    @app.get('/api/state')
    def state(request:Request):
        try:return service.state(request.headers.get('x-voice-session',''))
        except ValueError:return JSONResponse({'error':'invalid_or_full_session'},status_code=400)
    @app.post('/api/demo/utterance')
    async def demo_utterance(request:Request):
        if mode!='demo':return Response(status_code=404)
        raw=await limited_body(request,131072)
        if raw is None:return Response(status_code=413)
        try:
            data=json.loads(raw)
            return await asyncio.to_thread(service.submit_demo,request.headers.get('x-voice-session',''),data['text'])
        except (ValueError,TypeError,KeyError):return JSONResponse({'error':'invalid_demo_text'},status_code=400)
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
            if mode=='demo':return JSONResponse({'error':'demo_text_only'},status_code=409)
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

