"""Single-owner staged adapter coordinator; no vendor SDK or physical audio I/O."""
import threading
from collections import deque
import time
import hashlib
import math
from .gateway import Pipeline
from .native import NativeRuntime
from .sessions import StaleInteraction
from .providers import Transcript,STTProvider,TextProvider,TTSProvider


class Backpressure(RuntimeError):pass


class Conversation:
    """Providers stream outside the lock; callbacks/render/interrupt serialize.

    Text provider: stream(context, cancelled, request_id) -> text fragments.
    TTS provider: stream(text, cancelled, request_id) -> bounded PCM byte chunks.
    STT provider: stream(audio_chunks, cancelled, request_id) -> Transcript events.
    A callback always rechecks durable ownership before native enqueue/render.
    """
    def __init__(self,path,session,branch=None,budget=100,library=None,capacity=65536,incremental=True,audio_wait_seconds=.25,deadline_seconds=30,max_text_bytes=32000,max_audio_bytes=16777216,token_counter=None,publish_on_submit=True,redis_url=None):
        if not math.isfinite(deadline_seconds) or deadline_seconds<=0 or not math.isfinite(audio_wait_seconds) or audio_wait_seconds<0 or min(max_text_bytes,max_audio_bytes)<1:raise ValueError('positive operation limits required')
        self.token_counter=token_counter
        self.deadline_seconds=deadline_seconds;self.max_text_bytes=max_text_bytes;self.max_audio_bytes=max_audio_bytes
        self.lock=threading.RLock();self.pipeline=Pipeline(path,check_same_thread=False,publish_on_submit=publish_on_submit,redis_url=redis_url)
        self.native=None
        try:
            existing=self.pipeline.engine.db.execute('SELECT branch FROM interaction_sessions WHERE id=?',(session,)).fetchone()
            branch=branch or (existing['branch'] if existing else 'main')
            if not self.pipeline.engine.db.execute('SELECT 1 FROM branches WHERE id=?',(branch,)).fetchone():
                if branch!='main':raise ValueError('create branch before opening conversation')
                self.pipeline.engine.fork(branch)
            self.session=session;self.native=NativeRuntime(library,capacity=capacity,incremental=incremental)
            self.cancelled={};self.running=set();self.metrics=deque(maxlen=2048);self.closed=False
            self.space=threading.Condition(self.lock);self.audio_wait_seconds=audio_wait_seconds
            state=self.pipeline.sessions.open(session,branch,budget);self.native.advance(state['epoch'])
        except Exception:
            if self.native is not None:self.native.close()
            self.pipeline.close();raise

    def close(self):
        with self.lock:
            if not self.closed:
                for event in self.cancelled.values():event.set()
                self.native.close();self.pipeline.close();self.closed=True

    def _check(self,ticket):
        if self.closed:raise RuntimeError('conversation closed')
        if ticket['session']!=self.session:raise ValueError('ticket from another session')
        state=self.pipeline.sessions.get(self.session);self.native.advance(state['epoch'])
        valid=self.pipeline.sessions.valid(ticket)
        if not valid:self.cancelled.get(ticket['request_id'],threading.Event()).set()
        return valid

    def begin(self,request_id=None,budget=4096,expected_epoch=None):
        with self.lock:
            if expected_epoch is not None and self.pipeline.sessions.get(self.session)["epoch"]!=expected_epoch:
                raise StaleInteraction("turn superseded before dispatch")
            retry=request_id and self.pipeline.engine.db.execute('SELECT 1 FROM replies WHERE id=?',(request_id,)).fetchone()
            if not retry and len(self.running)>=8:raise Backpressure('too many outstanding provider calls')
            ticket=self.pipeline.sessions.begin(self.session,request_id,budget,count=self.token_counter)
            if not retry:
                for key,event in list(self.cancelled.items()):
                    event.set()
                    if key not in self.running:self.cancelled.pop(key)
            self.native.advance(self.pipeline.sessions.get(self.session)['epoch'])
            # Idempotent retry must not replace a cancellation signal held by a provider.
            self.cancelled.setdefault(ticket['request_id'],threading.Event())
            return ticket

    def interrupt(self,branch=None):
        tick=time.perf_counter()
        with self.lock:
            for event in self.cancelled.values():event.set()
            state=self.pipeline.sessions.interrupt(self.session,branch);self.native.advance(state['epoch'])
            self.space.notify_all()
            self.metrics.append({'stage':'interrupt_queue_clear','seconds':time.perf_counter()-tick,'epoch':state['epoch']})
            return state

    def receive_text(self,ticket,text,finish=False):
        with self.lock,self.pipeline.engine.db:
            self.pipeline.engine.db.execute('BEGIN IMMEDIATE')
            if not self._check(ticket):return 0
            return self.native.append(ticket['epoch'],text,finish)

    def receive_audio(self,ticket,sequence,pcm,segment=None):
        with self.lock,self.pipeline.engine.db:
            self.pipeline.engine.db.execute('BEGIN IMMEDIATE')
            if not self._check(ticket):return 0
            status=self.native.push(2,ticket['epoch'],sequence,pcm)
            if status==1:
                try:self.pipeline.engine.db.execute('INSERT INTO output_chunks(reply,sequence,segment,bytes,sha256) VALUES (?,?,?,?,?)',
                        (ticket['request_id'],sequence,segment,len(pcm),hashlib.sha256(pcm).hexdigest()))
                except Exception:
                    self.native.advance(ticket['epoch']+1);raise
            return status

    def render(self,size):
        with self.lock,self.pipeline.engine.db:
            self.pipeline.engine.db.execute('BEGIN IMMEDIATE')
            state=self.pipeline.sessions.get(self.session);self.native.advance(state['epoch'])
            result=self.native.render(state['epoch'],size)
            remaining=result[1]
            rows=self.pipeline.engine.db.execute('''SELECT c.* FROM output_chunks c JOIN replies r ON r.id=c.reply
              WHERE r.session=? AND r.epoch=? AND c.rendered<c.bytes ORDER BY c.sequence''',(self.session,state['epoch'])).fetchall()
            for row in rows:
                take=min(remaining,row['bytes']-row['rendered']);remaining-=take
                self.pipeline.engine.db.execute('UPDATE output_chunks SET rendered=rendered+? WHERE reply=? AND sequence=?',
                                               (take,row['reply'],row['sequence']))
                if remaining==0:break
            if remaining:raise RuntimeError('native playback journal mismatch')
            self.space.notify_all()
            return result

    def _reserve(self,ticket,call_id,stage,cost,provider='unspecified'):
        with self.lock:
            if not self._check(ticket):raise StaleInteraction('response cancelled')
            return self.pipeline.sessions.reserve(ticket,call_id,stage,cost,provider)

    def _admit(self,ticket,call_id,stage,cost,provider):
        with self.lock:
            request=ticket['request_id']
            if request in self.running:return False
            old=self.pipeline.engine.db.execute('SELECT 1 FROM stage_calls WHERE id=?',(call_id,)).fetchone()
            if old:
                try:return self.pipeline.sessions.reserve(ticket,call_id,stage,cost,provider)
                finally:self.cancelled.pop(request,None)
            try:accepted=self._reserve(ticket,call_id,stage,cost,provider)
            except Exception:
                self.cancelled.pop(request,None);raise
            if accepted:self.running.add(request)
            else:self.cancelled.pop(request,None)
            return accepted

    def _finish(self,call_id,tick,failed=False,elapsed=None):
        with self.lock:
            if self.closed:return
            duration=time.perf_counter()-tick if elapsed is None else elapsed
            self.pipeline.sessions.finish(call_id,failed=failed,elapsed=duration)
            self.metrics.append({'stage_call':call_id,'seconds':duration,'failed':failed})

    def _audio(self,ticket,sequence,pcm,segment):
        deadline=time.monotonic()+self.audio_wait_seconds
        while True:
            status=self.receive_audio(ticket,sequence,pcm,segment)
            if status!=2:return self._accepted(status)
            if len(pcm)>self.native.capacity:raise Backpressure('provider frame exceeds capacity')
            with self.space:
                if time.monotonic()>=deadline:raise Backpressure('playback queue drain deadline exceeded')
                self.space.wait(min(.01,max(0,deadline-time.monotonic())))

    def _abort(self,ticket):
        # Clear local output before attempting audit/state writes: a failed DB
        # write must not leave partial provider audio available for later playback.
        with self.lock:
            if self.closed:return
            self.cancelled.get(ticket['request_id'],threading.Event()).set()
            if self.native.stats()['epoch']==ticket['epoch']:self.native.advance(ticket['epoch']+1)
            try:
                if self.pipeline.sessions.valid(ticket):self.pipeline.sessions.interrupt(self.session)
            except Exception as error:
                self.metrics.append({'stage':'abort_state_write','error_class':type(error).__name__})
            self.space.notify_all()

    @staticmethod
    def _accepted(status):
        if status==0:raise StaleInteraction('late provider output discarded')
        if status==2:raise Backpressure('bounded queue full; caller must drain or pause generation')
        if status!=1:raise ValueError('invalid or out-of-order provider output')

    def respond(self,request_id,text_provider:TextProvider,tts_provider:TTSProvider,reason_cost=1,tts_cost=1,context_budget=4096,expected_epoch=None):
        ticket=self.begin(request_id,context_budget,expected_epoch);cancel=self.cancelled[ticket['request_id']]
        reason_id=request_id+':reason';tick=time.perf_counter();audio_seq=0;first_audio=None;audio_bytes=0;text_bytes=0
        deadline=time.monotonic()+self.deadline_seconds
        if not self._admit(ticket,reason_id,'reason',reason_cost,getattr(text_provider,'name',type(text_provider).__name__)):return {'status':'duplicate','ticket':ticket}
        def synthesize_segments():
            nonlocal audio_seq,first_audio,audio_bytes
            while True:
                with self.lock,self.pipeline.engine.db:
                    self.pipeline.engine.db.execute('BEGIN IMMEDIATE')
                    if not self._check(ticket):raise StaleInteraction('response cancelled')
                    segment=self.native.pop(1)
                if segment is None:return
                with self.lock:self.pipeline.sessions.segment(ticket,segment['sequence'],segment['data'].decode('utf-8'))
                call_id=request_id+':tts:'+str(segment['sequence']);started=time.perf_counter()
                if not self._reserve(ticket,call_id,'tts',tts_cost,getattr(tts_provider,'name',type(tts_provider).__name__)):raise ValueError('segment already admitted')
                try:
                    for pcm in tts_provider.stream(segment['data'].decode('utf-8'),cancel,call_id):
                        if time.monotonic()>deadline:raise TimeoutError('response deadline exceeded')
                        audio_bytes+=len(pcm)
                        if audio_bytes>self.max_audio_bytes:raise ValueError('response audio byte cap exceeded')
                        self._audio(ticket,audio_seq,pcm,segment['sequence']);audio_seq+=1
                        if first_audio is None:first_audio=time.perf_counter()-tick
                except Exception:
                    self._finish(call_id,started,True);raise
                else:self._finish(call_id,started)
        stream=None
        reason_active=0.
        try:
            active=time.perf_counter();stream=iter(text_provider.stream(ticket['context'],cancel,reason_id))
            reason_active+=time.perf_counter()-active
            while True:
                active=time.perf_counter()
                try:text=next(stream)
                except StopIteration:break
                finally:reason_active+=time.perf_counter()-active
                if time.monotonic()>deadline:raise TimeoutError('response deadline exceeded')
                text_bytes+=len(text.encode('utf-8') if isinstance(text,str) else text)
                if text_bytes>self.max_text_bytes:raise ValueError('response text byte cap exceeded')
                self._accepted(self.receive_text(ticket,text));synthesize_segments()
            self._accepted(self.receive_text(ticket,b'',finish=True));synthesize_segments()
            with self.lock:
                if not self.pipeline.sessions.seal(ticket):raise StaleInteraction('response ended after cancellation')
        except Exception:
            self._abort(ticket)
            self._finish(reason_id,tick,True,elapsed=reason_active)
            raise
        else:self._finish(reason_id,tick,elapsed=reason_active)
        finally:
            try:
                if stream is not None and hasattr(stream,'close'):stream.close()
            finally:
                with self.lock:
                    event=self.cancelled.pop(ticket['request_id'],None)
                    if event:event.set()
                    self.running.discard(ticket['request_id'])
        return {'status':'queued','ticket':ticket,'audio_chunks':audio_seq,
                'first_audio_queued_seconds':first_audio,'total_seconds':time.perf_counter()-tick}

    def transcribe(self,transcript_id,provider:STTProvider,audio,cost=1,expected_epoch=None,on_begin=None):
        ticket=self.begin('capture:'+transcript_id,expected_epoch=expected_epoch);cancel=self.cancelled[ticket['request_id']]
        if on_begin:on_begin(ticket)
        call_id='capture:'+transcript_id+':stt';tick=time.perf_counter()
        if not self._admit(ticket,call_id,'stt',cost,getattr(provider,'name',type(provider).__name__)):return {'status':'duplicate'}
        deadline=time.monotonic()+self.deadline_seconds
        def bounded_audio():
            total=0
            for sequence,pcm in enumerate(audio):
                total+=len(pcm)
                if total>self.max_audio_bytes or time.monotonic()>deadline:raise ValueError('capture input or duration cap exceeded')
                with self.lock,self.pipeline.engine.db:
                    self.pipeline.engine.db.execute('BEGIN IMMEDIATE')
                    if not self._check(ticket):raise StaleInteraction('capture cancelled')
                    self._accepted(self.native.push(0,ticket['epoch'],sequence,pcm))
                    frame=self.native.pop(0)
                yield frame['data']
        try:
            for event in provider.stream(bounded_audio(),cancel,call_id):
                if time.monotonic()>deadline:raise TimeoutError('STT deadline exceeded')
                if not isinstance(event,Transcript):raise ValueError('STT must return Transcript events')
                if event.final:
                    with self.lock:
                        result=self.pipeline.sessions.submit(self.session,transcript_id,event.text,ticket['epoch'])
                        self.native.advance(result['session']['epoch']);cancel.set()
                    self._finish(call_id,tick);return result
            raise ValueError('STT stream ended without final transcript')
        except Exception:
            self._abort(ticket)
            self._finish(call_id,tick,True)
            raise
        finally:
            with self.lock:
                event=self.cancelled.pop(ticket['request_id'],None)
                if event:event.set()
                self.running.discard(ticket['request_id'])
