import asyncio
import json
from fastapi import Request
from fastapi.responses import Response,JSONResponse
from ...product.documents import DocumentConflict
from ..http import limited_body

def register(app,product):
    @app.get('/api/workspace')
    async def workspace_read(request:Request):
        try:return await asyncio.to_thread(product.workspace,request.headers.get('x-voice-session',''))
        except ValueError:return JSONResponse({'error':'invalid_session'},status_code=400)
    @app.post('/api/workspace')
    async def workspace_write(request:Request):
        from ...product.product_workspace import WorkspaceConflict
        raw=await limited_body(request,2100000)
        if raw is None:return Response(status_code=413)
        try:
            data=json.loads(raw)
            if not isinstance(data,dict):raise ValueError('object required')
            return await asyncio.to_thread(product.workspace,request.headers.get('x-voice-session',''),data)
        except WorkspaceConflict:return JSONResponse({'error':'workspace_conflict'},status_code=409)
        except (ValueError,TypeError,KeyError):return JSONResponse({'error':'invalid_workspace'},status_code=400)
    @app.get('/api/documents')
    async def documents_list(request:Request):
        try:
            args=dict(request.query_params);args['offset']=int(args.get('offset',0))
            return await asyncio.to_thread(product.documents,request.headers.get('x-voice-session',''),'list',args)
        except (ValueError,TypeError):return JSONResponse({'error':'invalid_document_filter'},status_code=400)
    @app.get('/api/documents/item')
    async def document_item(request:Request):
        try:return await asyncio.to_thread(product.documents,request.headers.get('x-voice-session',''),'get',{'id':request.query_params['id']})
        except KeyError:return JSONResponse({'error':'document_not_found'},status_code=404)
        except ValueError:return JSONResponse({'error':'invalid_session'},status_code=400)
    @app.get('/api/documents/history')
    async def document_history(request:Request):
        try:return await asyncio.to_thread(product.documents,request.headers.get('x-voice-session',''),'history',{'id':request.query_params['id']})
        except KeyError:return JSONResponse({'error':'document_not_found'},status_code=404)
        except ValueError:return JSONResponse({'error':'invalid_session'},status_code=400)
    @app.get('/api/documents/revision')
    async def document_revision(request:Request):
        try:return await asyncio.to_thread(product.documents,request.headers.get('x-voice-session',''),'revision',
            {'id':request.query_params['id'],'revision':int(request.query_params['version'])})
        except KeyError:return JSONResponse({'error':'version_not_found'},status_code=404)
        except (ValueError,TypeError):return JSONResponse({'error':'invalid_version'},status_code=400)
    @app.post('/api/documents/{action}')
    async def document_write(action:str,request:Request):
        raw=await limited_body(request,262144)
        if raw is None:return Response(status_code=413)
        try:
            data=json.loads(raw)
            return await asyncio.to_thread(product.documents,request.headers.get('x-voice-session',''),action,data)
        except DocumentConflict:return JSONResponse({'error':'document_conflict','message':'A newer version exists. Reload before saving.'},status_code=409)
        except KeyError:return JSONResponse({'error':'document_not_found'},status_code=404)
        except (ValueError,TypeError):return JSONResponse({'error':'invalid_document'},status_code=400)

