"""CPU-only sentence-buffer ablation, not speech/provider latency."""
import argparse
import codecs
import hashlib
import json
import platform
import random
import re
import statistics
import time
from collections import deque
from pathlib import Path
from voice_context.native import NativeRuntime


class PythonReference:
    """Matched valid-input fixture path using incremental UTF-8 and byte regex."""
    def __init__(self):self.pending=b'';self.scan=0;self.queue=deque();self.decoder=codecs.getincrementaldecoder('utf-8')()
    def append(self,epoch,data,finish=False):
        self.decoder.decode(data,final=finish);candidate=self.pending+data
        complete=len(candidate)-len(self.decoder.getstate()[0]);consumed=0
        for match in re.finditer(rb'[.!?\n]|\xe3\x80\x82|\xef\xbc[\x81\x9f]',candidate[self.scan:complete]):
            end=self.scan+match.end();self.queue.append(candidate[consumed:end]);consumed=end
        if finish and consumed<len(candidate):self.queue.append(candidate[consumed:]);consumed=len(candidate)
        self.pending=candidate[consumed:];self.scan=complete-consumed;return 1
    def pop(self,lane):return {'data':self.queue.popleft()} if self.queue else None
    def close(self):pass


def main():
    p=argparse.ArgumentParser();p.add_argument('--output',default='experiments/runtime-results.json');a=p.parse_args()
    cases={'short_sentences':('hello world. '*24).encode(),
           'long_sentence':b'a'*16000+b'.','utf8_fragmented':('分支上下文'*500+'。').encode()}
    report={'kind':'synthetic_cpu_sentence_buffer_ablation','platform':platform.platform(),'python':platform.python_version(),
            'native_source_sha256':hashlib.sha256(Path('native/runtime.hpp').read_bytes()).hexdigest(),
            'binding_sha256':hashlib.sha256(Path('src/voice_context/native.py').read_bytes()).hexdigest(),
            'protocol':'Five shuffled same-process rounds, five documents per sample; identical bytes/chunk sizes. Includes ctypes and buffer copies. No network/STT/TTS/device playback.',
            'cases':{},'limitations':'Python reference is a valid-input regex fixture, not a full bounded audio runtime. Cross-language results include implementation and FFI differences. Same-process samples are not independent hardware trials.'}
    rng=random.Random(42)
    for name,data in cases.items():
        chunk=17 if name=='utf8_fragmented' else 32
        samples={label:[] for label in ('python_regex','cpp_rescan','cpp_incremental')};scans={}
        for _ in range(5):
            order=list(samples);rng.shuffle(order)
            for label in order:
                elapsed=[];scanned=0
                for _ in range(5):
                    runtime=PythonReference() if label=='python_regex' else NativeRuntime(capacity=32768,incremental=label=='cpp_incremental')
                    try:
                        joined=b'';start=time.perf_counter_ns()
                        for i in range(0,len(data),chunk):
                            assert runtime.append(1,data[i:i+chunk])==1
                            while (frame:=runtime.pop(1)) is not None:joined+=frame['data']
                        assert runtime.append(1,b'',True)==1
                        while (frame:=runtime.pop(1)) is not None:joined+=frame['data']
                        elapsed.append((time.perf_counter_ns()-start)/1000)
                        assert joined==data
                        if label!='python_regex':scanned=runtime.stats()['scan_steps']
                    finally:runtime.close()
                samples[label].append(statistics.median(elapsed));scans[label]=scanned
        medians={k:statistics.median(v) for k,v in samples.items()}
        report['cases'][name]={'input_bytes':len(data),'chunk_bytes':chunk,'median_document_us':medians,
            'round_medians_us':samples,'scan_positions_last_document':scans,
            'incremental_speedup_vs_cpp_rescan':medians['cpp_rescan']/medians['cpp_incremental']}
        print(name,medians,flush=True)
    out=Path(a.output);out.parent.mkdir(parents=True,exist_ok=True);out.write_text(json.dumps(report,indent=2)+'\n')


if __name__=='__main__':main()
