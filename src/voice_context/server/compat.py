"""Legacy injected service remains supported while new routes use explicit ports."""
from ..infra.runtime.service import RuntimeService
from ..product.services import ProductService
from .adapters import RuntimeProductAccess


class VoiceService(RuntimeService):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self.product=ProductService(RuntimeProductAccess(self))
    def documents(self,session,action,data):return self.product.documents(session,action,data)
    def workspace(self,session,data=None):return self.product.workspace(session,data)
