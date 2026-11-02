"""Explicit paid API test through the local HTTP service with a fixed recording."""
import argparse
import base64
import hashlib
import json
from pathlib import Path
import re
import time
import uuid
import wave
import httpx


def main():
    p=argparse.ArgumentParser();p.add_argument('fixture');p.add_argument('--url',default='http://127.0.0.1:8765')
    p.add_argument('--output',default='experiments/voice-roundtrip-results.json');p.add_argument('--audio-output',default='/tmp/voice-roundtrip-reply.wav')
    args=p.parse_args();pcm=bytearray();events=[];started=time.perf_counter();first=None
    fixture=Path(args.fixture).read_bytes()
    with httpx.Client(base_url=args.url,timeout=120) as client:
        page=client.get('/').text;token=re.search(r'name="voice-token" content="([^"]+)"',page)[1]
        headers={'X-Voice-Token':token,'X-Voice-Session':'fixture-'+uuid.uuid4().hex}
        with client.stream('POST','/api/turn',headers={**headers,'Content-Type':'audio/wav'},content=fixture) as response:
            response.raise_for_status()
            for line in response.iter_lines():
                event=json.loads(line)
                if event['type']=='audio':
                    if first is None:first=time.perf_counter()-started
                    pcm.extend(base64.b64decode(event['data']))
                    # This script has no speaker: deliberately do not send playback ACK.
                else:events.append(event)
    with wave.open(args.audio_output,'wb') as output:
        output.setnchannels(1);output.setsampwidth(2);output.setframerate(24000);output.writeframes(pcm)
    transcript=''.join(x['text'] for x in events if x['type']=='transcript')
    answer=''.join(x['text'] for x in events if x['type']=='text')
    checks={'final_transcript':bool(transcript),'codename_transcribed':'cedar' in transcript.lower(),
            'codename_answered':'cedar' in answer.lower(),'nonempty_pcm':len(pcm)>0 and len(pcm)%2==0,
            'terminal_done':bool(events and events[-1]['type']=='done'),'no_error':not any(x['type']=='error' for x in events)}
    result={'protocol':'fixed macOS-synthesized recording -> real STT/LLM/TTS -> C++ queues -> HTTP PCM; no hardware playback or ACK',
            'fixture_sha256':hashlib.sha256(fixture).hexdigest(),'fixture_bytes':len(fixture),
            'checks':checks,'passed':all(checks.values()),'transcript':transcript,'answer':answer,
            'audio_pcm_bytes':len(pcm),'audio_seconds':len(pcm)/48000,'first_http_audio_seconds':first,
            'total_seconds':time.perf_counter()-started,'events':events,
            'source_hashes':{str(f):hashlib.sha256(f.read_bytes()).hexdigest() for f in Path('src/voice_context').glob('*.py')}}
    Path(args.output).write_text(json.dumps(result,indent=2,ensure_ascii=False)+'\n')
    print(json.dumps({k:result[k] for k in ('passed','checks','transcript','answer','audio_seconds','first_http_audio_seconds')},ensure_ascii=False))
    if not result['passed']:raise SystemExit(1)


if __name__=='__main__':main()
