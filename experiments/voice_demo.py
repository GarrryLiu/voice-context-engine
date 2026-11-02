"""Scripted phase demo; does not capture or play real audio or contact providers."""
import json
import tempfile
from pathlib import Path
from voice_context.conversation import Conversation,Transcript


class STT:
    name='demo-stt-script'
    def stream(self,audio,cancelled,request_id):
        list(audio);yield Transcript('thinking...',False)
        yield Transcript('remember architecture: 语音运行层与持久记忆分离',True)
class Reason:
    name='demo-text-script'
    def stream(self,context,cancelled,request_id):
        assert '语音运行层' in context['text'];yield '收到。';yield '可以跨会话继续这个分支。'
class TTS:
    name='demo-tts-script-not-audio'
    def stream(self,text,cancelled,request_id):yield text.encode() # synthetic transport payload


def main():
    with tempfile.TemporaryDirectory() as temp:
        path=str(Path(temp)/'demo.db');c=Conversation(path,'demo')
        try:
            c.transcribe('turn',STT(),[b'synthetic capture'])
            result=c.respond('reply',Reason(),TTS());data,n=c.render(4096)
            for row in c.pipeline.sessions.delivery('demo'):
                c.pipeline.sessions.acknowledge('demo',row['request_id'],row['sequence'],row['rendered'])
            c.close();c=Conversation(path,'demo')
            report={'simulated':True,'notice':'No microphone, audio waveform, speaker or external model used.',
                'response_payload':data[:n].decode(),'recent_after_reopen':c.pipeline.transcripts.recent('main'),
                'acknowledged_responses':c.pipeline.transcripts.context('main')['responses'],
                'old_reply_valid_after_reopen':c.pipeline.sessions.valid(result['ticket']),
                'declared_units_after_reopen':c.pipeline.sessions.get('demo')['spent']}
            print(json.dumps(report,ensure_ascii=False,indent=2))
        finally:c.close()


if __name__=='__main__':main()
