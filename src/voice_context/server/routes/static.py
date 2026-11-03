from pathlib import Path
from fastapi.responses import HTMLResponse,Response
from fastapi import HTTPException

WEB=Path(__file__).parents[2]/'web'

def register(app,token,mode='connected'):
    @app.get('/lab')
    @app.get('/')
    def index():return HTMLResponse((WEB/'index.html').read_text().replace('__LOCAL_TOKEN__',token).replace('__VOICE_MODE__',mode))
    @app.get('/product')
    def product():return HTMLResponse((WEB/'product.html').read_text().replace('__LOCAL_TOKEN__',token).replace('__VOICE_MODE__',mode))
    @app.get('/brand.svg')
    def brand_svg():return Response((WEB/'brand.svg').read_text(),media_type='image/svg+xml')
    @app.get('/product.css')
    def product_css():return Response((WEB/'product.css').read_text(),media_type='text/css')
    @app.get('/workspace.js')
    def workspace_js():return Response((WEB/'workspace.js').read_text(),media_type='text/javascript')
    @app.get('/workspace.css')
    def workspace_css():return Response((WEB/'workspace.css').read_text(),media_type='text/css')
    @app.get('/strings.js')
    def strings_js():return Response((WEB/'strings.js').read_text(),media_type='text/javascript')
    @app.get('/documents.js')
    def documents_js():return Response((WEB/'documents.js').read_text(),media_type='text/javascript')
    @app.get('/documents.css')
    def documents_css():return Response((WEB/'documents.css').read_text(),media_type='text/css')
    @app.get('/product.js')
    def product_js():return Response((WEB/'product.js').read_text(),media_type='text/javascript')
    @app.get('/app.js')
    def js():return Response((WEB/'app.js').read_text(),media_type='text/javascript')
    @app.get('/live.js')
    def live_js():return Response((WEB/'live.js').read_text(),media_type='text/javascript')
    @app.get('/capture.js')
    def capture_js():return Response((WEB/'capture.js').read_text(),media_type='text/javascript')
    @app.get('/style.css')
    def css():return Response((WEB/'style.css').read_text(),media_type='text/css')

    @app.get('/product-entry.js')
    def product_entry():return Response((WEB/'product-entry.js').read_text(),media_type='text/javascript')
    @app.get('/client/{name}.js')
    def client_module(name:str):
        if name not in {'runtime','navigation','demo'}:raise HTTPException(status_code=404)
        return Response((WEB/'client'/(name+'.js')).read_text(),media_type='text/javascript')
