"""ctypes binding for the bounded native runtime. Build and opt-in explicitly."""
import ctypes as C
import os
import threading


class NativeRuntime:
    def __init__(self,path=None,capacity=65536,max_items=256,incremental=True):
        path=path or os.environ.get('VOICE_RUNTIME_LIBRARY')
        if not path:raise ValueError('build native runtime and set VOICE_RUNTIME_LIBRARY')
        if not isinstance(capacity,int) or not isinstance(max_items,int) or not 0<capacity<=16*1024*1024 or not 0<max_items<=100000:
            raise ValueError('bounded positive capacities required')
        self.capacity=capacity;self._buffer=C.create_string_buffer(capacity);self._lock=threading.RLock();self.lib=C.CDLL(path)
        signatures={'vr_create':([C.c_size_t,C.c_size_t,C.c_int],C.c_void_p),
          'vr_destroy':([C.c_void_p],None),'vr_advance':([C.c_void_p,C.c_uint64],C.c_int),
          'vr_push':([C.c_void_p,C.c_int,C.c_uint64,C.c_uint64,C.c_void_p,C.c_size_t],C.c_int),
          'vr_append':([C.c_void_p,C.c_uint64,C.c_void_p,C.c_size_t,C.c_int],C.c_int),
          'vr_pop':([C.c_void_p,C.c_int,C.c_void_p,C.c_size_t,C.POINTER(C.c_size_t),C.POINTER(C.c_uint64),C.POINTER(C.c_uint64)],C.c_int),
          'vr_render':([C.c_void_p,C.c_uint64,C.c_void_p,C.c_size_t],C.c_size_t),
          'vr_stat':([C.c_void_p,C.c_int],C.c_uint64)}
        for name,(args,result) in signatures.items():fn=getattr(self.lib,name);fn.argtypes=args;fn.restype=result
        self.handle=self.lib.vr_create(capacity,max_items,incremental)
        if not self.handle:raise MemoryError('native runtime allocation failed')
    @staticmethod
    def _number(value):
        if not isinstance(value,int) or isinstance(value,bool) or not 0<=value<2**63:raise ValueError('nonnegative signed-64-bit identifier required')
        return value
    def _call(self,name,*args):
        with self._lock:
            if not self.handle:raise RuntimeError('runtime closed')
            return getattr(self.lib,name)(self.handle,*args)
    def close(self):
        with self._lock:
            if self.handle:self.lib.vr_destroy(self.handle);self.handle=None
    def advance(self,epoch):return self._call('vr_advance',self._number(epoch))
    def push(self,lane,epoch,sequence,data):
        if lane not in (0,2) or not isinstance(data,bytes):raise ValueError('audio lane 0/2 and bytes required')
        return self._call('vr_push',lane,self._number(epoch),self._number(sequence),data,len(data))
    def append(self,epoch,data,finish=False):
        if isinstance(data,str):data=data.encode('utf-8')
        if not isinstance(data,bytes) or not isinstance(finish,bool):raise ValueError('text bytes and boolean finish required')
        return self._call('vr_append',self._number(epoch),data,len(data),finish)
    def pop(self,lane):
        if lane not in (0,1,2):raise ValueError('unknown lane')
        with self._lock:
            size=C.c_size_t();seq=C.c_uint64();epoch=C.c_uint64()
            status=self._call('vr_pop',lane,self._buffer,self.capacity,C.byref(size),C.byref(seq),C.byref(epoch))
            if status==0:return None
            if status!=1:raise RuntimeError('native pop failed')
            return {'epoch':epoch.value,'sequence':seq.value,'data':C.string_at(self._buffer,size.value)}
    def render(self,epoch,size):
        if not isinstance(size,int) or not 0<=size<=self.capacity:raise ValueError('render size outside capacity')
        with self._lock:
            written=self._call('vr_render',self._number(epoch),self._buffer,size)
            return C.string_at(self._buffer,size),written
    def stats(self):
        names=['epoch','capture_bytes','text_bytes','playback_bytes','capture_items','text_items','playback_items','pending_bytes','stale_rejections','backpressure_rejections','scan_steps','rendered_bytes']
        return {name:self._call('vr_stat',i) for i,name in enumerate(names)}
