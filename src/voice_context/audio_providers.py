"""Completed-recording STT and streaming 24 kHz mono PCM16 TTS adapters."""
import hashlib
import time
from .providers import Transcript
from .openai_provider import ProviderFailure


class AudioCall:
    def __init__(self,journal,model,call_id,payload):
        self.journal,self.call_id=journal,call_id
        self.result={'state':'failed','elapsed_seconds':None,'first_delta_seconds':None,
                     'response_id':None,'usage':None,'error_code':None}
        if journal:journal.begin(call_id,model,hashlib.sha256(payload).hexdigest())
        self.started=time.perf_counter()
    def finish(self,error=None):
        self.result['elapsed_seconds']=time.perf_counter()-self.started
        self.result['state']='failed' if error else 'completed'
        self.result['error_code']=type(error).__name__ if error else None
        if self.journal:self.journal.finish(self.call_id,self.result)


class OpenAIRecordingSTT:
    def __init__(self,client,filename='capture.webm',model='gpt-transcribe',journal=None,on_partial=None):
        self.client,self.filename,self.model,self.journal=client,filename,model,journal
        self.on_partial=on_partial or (lambda text:None)
        self.name='openai:'+model+':recording-stream-v1'
    def stream(self,audio,cancelled,request_id):
        data=bytearray()
        for block in audio:
            data.extend(block)
            if len(data)>8*1024*1024:raise ValueError('recording too large')
        if not data or cancelled.is_set():raise ProviderFailure('invalid_or_cancelled_recording')
        call=AudioCall(self.journal,self.model,request_id,bytes(data));error=None
        try:
            with self.client.audio.transcriptions.create(model=self.model,file=(self.filename,bytes(data)),stream=True) as events:
                for event in events:
                    if cancelled.is_set():raise ProviderFailure('cancelled_stt')
                    if time.perf_counter()-call.started>45:raise ProviderFailure('stt_deadline')
                    if event.type=='transcript.text.delta':
                        self.on_partial(event.delta)
                        yield Transcript(event.delta,False)
                    elif event.type=='transcript.text.done':
                        if not event.text.strip():raise ProviderFailure('empty_transcript')
                        usage=getattr(event,'usage',None)
                        call.result['usage']=usage.model_dump() if hasattr(usage,'model_dump') else usage
                        # Finalize transport/audit before yielding: transcribe stops at final.
                        call.finish()
                        yield Transcript(event.text,True)
                        return
                    elif event.type=='error':raise ProviderFailure('stt_error')
            raise ProviderFailure('stt_stream_missing_final')
        except GeneratorExit:
            if call.result['state']!='completed':call.finish(ProviderFailure('consumer_closed'))
            raise
        except Exception as exc:
            error=exc;call.finish(error)
            raise ProviderFailure(type(exc).__name__) from None


class OpenAIPcmTTS:
    """Align network chunks to signed little-endian 16-bit sample boundaries."""
    def __init__(self,client,model='gpt-4o-mini-tts',voice='coral',journal=None):
        self.client,self.model,self.voice,self.journal=client,model,voice,journal
        self.name='openai:'+model+':'+voice+':pcm24k-v1'
    def stream(self,text,cancelled,request_id):
        if not text.strip() or len(text)>1600:raise ValueError('bounded nonempty speech text required')
        call=AudioCall(self.journal,self.model,request_id,text.encode());total=0;pending=b''
        try:
            with self.client.audio.speech.with_streaming_response.create(model=self.model,voice=self.voice,
                input=text,response_format='pcm') as response:
                for block in response.iter_bytes(chunk_size=4096):
                    if cancelled.is_set():raise ProviderFailure('cancelled_tts')
                    if time.perf_counter()-call.started>60:raise ProviderFailure('tts_deadline')
                    pending+=block
                    size=len(pending)-len(pending)%2
                    if size:
                        total+=size
                        if total>2*1024*1024:raise ProviderFailure('speech_output_limit')
                        if call.result['first_delta_seconds'] is None:call.result['first_delta_seconds']=time.perf_counter()-call.started
                        output,pending=pending[:size],pending[size:]
                        yield output
            if pending or not total:raise ProviderFailure('invalid_pcm_frame')
            call.result['usage']={'source':'local_measurement_not_billing','input_characters':len(text),'output_pcm_bytes':total}
            call.finish()
        except GeneratorExit:call.finish(ProviderFailure('consumer_closed'));raise
        except Exception as exc:
            call.result['usage']={'source':'partial_local_measurement_not_billing','input_characters':len(text),'output_pcm_bytes':total}
            call.finish(exc);raise ProviderFailure(type(exc).__name__) from None
