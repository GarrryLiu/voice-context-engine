"""Exercise real worklet code at device sample rates without a microphone."""
import json
from pathlib import Path
import shutil
import subprocess
import unittest


@unittest.skipUnless(shutil.which('node'),'Node needed for audio worklet fixture')
class CaptureTests(unittest.TestCase):
    def run_capture(self,rate,speech,ack=True):
        source=Path('src/voice_context/web/capture.js').read_text()
        harness='''const vm=require('node:vm');let Capture;const messages=[];
          const context={sampleRate:RATE,AudioWorkletProcessor:class{constructor(){this.port={postMessage:m=>messages.push(m)};}},registerProcessor:(_,c)=>Capture=c};
          vm.runInNewContext(SOURCE,context);const capture=new Capture();
          for(let offset=0;offset<RATE*(SECONDS+1);offset+=128){const input=new Float32Array(128);
            for(let j=0;j<128;j++){const t=(offset+j)/RATE;if(t>.2&&t<SECONDS)input[j]=.2*Math.sin(2*Math.PI*220*t);}
            capture.process([[input]]);if(ACK)while(capture.outstanding)capture.port.onmessage({data:{type:'ack'}});}
          let turn=0,maxTurn=0;for(const m of messages){if(m.type==='start')turn=0;if(m.type==='pcm'){turn+=m.pcm.byteLength;maxTurn=Math.max(maxTurn,turn);}}
          console.log(JSON.stringify({maxTurn,overflow:messages.filter(m=>m.type==='overflow').length,start:messages.filter(m=>m.type==='start').length,commit:messages.filter(m=>m.type==='commit').length,
            bytes:messages.filter(m=>m.type==='pcm').reduce((n,m)=>n+m.pcm.byteLength,0),max:Math.max(0,...messages.filter(m=>m.type==='pcm').map(m=>m.pcm.byteLength))}));'''
        script=harness.replace('RATE',str(rate)).replace('SECONDS',str(speech)).replace('SOURCE',json.dumps(source)).replace('ACK',str(ack).lower())
        return json.loads(subprocess.check_output(['node','-e',script],text=True))
    def test_resampling_turn_boundaries_and_silence(self):
        for rate in (16000,24000,44100,48000):
            with self.subTest(rate=rate):
                result=self.run_capture(rate,1.2)
                self.assertEqual((result['start'],result['commit']),(1,1))
                self.assertEqual(result['max'],960)
                self.assertTrue(76000<result['bytes']<85000,result)
                silent=self.run_capture(rate,0)
                self.assertEqual(silent['start'],0);self.assertEqual(silent['bytes'],0)
    def test_long_speech_turns_never_exceed_server_audio_bound(self):
        result=self.run_capture(48000,21)
        self.assertEqual(result['commit'],2)
        # First turn is capped at 1000 x 20 ms, including pre-roll.
        self.assertLessEqual(result['maxTurn'],960000)

    def test_unresponsive_main_thread_bounds_capture_backlog(self):
        result=self.run_capture(48000,2,ack=False)
        self.assertEqual(result['overflow'],1)
        self.assertLessEqual(result['bytes'],9600)
