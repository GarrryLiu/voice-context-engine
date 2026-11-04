"""Additive v1 map proposal API; provider errors are deliberately redacted."""
import asyncio
import json
from fastapi import Request
from fastapi.responses import JSONResponse,Response
from ...product.semantic_maps import MapUnavailable,MapBusy
from ...product.product_workspace import WorkspaceConflict
from ...openai_provider import ProviderFailure
from ..http import limited_body


def register(app,maps):
    @app.get('/api/maps/status')
    def status():return maps.status()

    @app.get('/api/maps/provenance')
    async def provenance(request:Request):
        try:return await asyncio.to_thread(maps.provenance,request.headers.get('x-voice-session',''),request.query_params.get('node',''))
        except ValueError:return JSONResponse({'error':'invalid_session'},status_code=400)

    @app.post('/api/maps/{action}')
    async def change(action:str,request:Request):
        raw=await limited_body(request,4096)
        if raw is None:return Response(status_code=413)
        try:
            data=json.loads(raw)
            if not isinstance(data,dict):raise ValueError('object required')
            session=request.headers.get('x-voice-session','')
            if action=='propose':return await asyncio.to_thread(maps.propose,session,data['branch'])
            if action=='apply':return await asyncio.to_thread(maps.apply,session,data['id'])
            return Response(status_code=404)
        except WorkspaceConflict:return JSONResponse({'error':'map_conflict','message':'Conversation or workspace changed. Generate a new suggestion.'},status_code=409)
        except MapUnavailable:return JSONResponse({'error':'map_disabled'},status_code=503)
        except MapBusy:return JSONResponse({'error':'map_busy'},status_code=429)
        except ProviderFailure:return JSONResponse({'error':'map_provider_failed','message':'Model request failed. Sources are kept. Try again.'},status_code=502)
        except (ValueError,TypeError,KeyError):return JSONResponse({'error':'invalid_map','message':'Could not validate this map or its sources.'},status_code=400)
