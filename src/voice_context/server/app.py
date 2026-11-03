"""Composition root: security, lifecycle and injected product/runtime services."""
from contextlib import asynccontextmanager
import secrets
from ..contracts import CONTRACT_VERSION

def create_app(path='voice-local.db',env_file='.env',service=None,redis_url=None,product=None,mode='connected'):
    from fastapi import FastAPI,Request
    from fastapi.responses import Response
    from .compat import VoiceService
    from .routes import static,voice,product as product_routes
    service=service or VoiceService(path,env_file,redis_url=redis_url)
    product=product or service.product
    token=secrets.token_urlsafe(32)
    @asynccontextmanager
    async def lifespan(app):
        yield
        service.close()
    app=FastAPI(lifespan=lifespan,docs_url=None,redoc_url=None,openapi_url=None)
    app.state.voice=service;app.state.product=product;app.state.local_token=token
    @app.middleware('http')
    async def local_only(request,call_next):
        host=request.headers.get('host','').split(':')[0]
        if host not in {'localhost','127.0.0.1','testserver'}:return Response(status_code=403)
        origin=request.headers.get('origin')
        if origin and origin!=str(request.base_url).rstrip('/'):return Response(status_code=403)
        if request.url.path.startswith('/api/') and not secrets.compare_digest(request.headers.get('x-voice-token',''),token):return Response(status_code=403)
        response=await call_next(request)
        response.headers['Cache-Control']='no-store'
        if request.url.path.startswith('/api/'):response.headers['X-Voice-Contract']=CONTRACT_VERSION
        response.headers['X-Content-Type-Options']='nosniff'
        response.headers['Content-Security-Policy']="default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; media-src 'self' blob:; frame-ancestors 'none'"
        return response
    static.register(app,token)
    voice.register(app,service,token,mode)
    product_routes.register(app,product)
    return app
