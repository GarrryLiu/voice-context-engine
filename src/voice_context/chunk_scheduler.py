"""Experimental deterministic text boundaries; playback feedback is an injected port."""
import math
import re
import time


class TextChunkScheduler:
    def __init__(self, strategy='sentence', min_chars=12, max_chars=1600,
                 max_wait=.6, feedback_ttl=1., clock=time.monotonic):
        if strategy not in ('sentence','short_first','buffer_aware'):raise ValueError('unknown strategy')
        if not 1 <= min_chars <= max_chars or not math.isfinite(max_wait) or max_wait<=0:
            raise ValueError('invalid chunk limits')
        self.strategy,self.min_chars,self.max_chars=strategy,min_chars,max_chars
        self.max_wait,self.feedback_ttl,self.clock=max_wait,feedback_ttl,clock
        self.pending='';self.since=None;self.first=True;self.urgent=False
        self.estimate=.25;self.feedback_sequence=-1;self.feedback=None

    def observe_tts(self, seconds):
        if math.isfinite(seconds) and seconds>=0:
            self.estimate=.8*self.estimate+.2*seconds

    def update_playback(self, feedback, epoch):
        if not isinstance(feedback,dict):return
        seq=feedback.get('sequence');stamp=feedback.get('at');seconds=feedback.get('seconds')
        if feedback.get('epoch')!=epoch or type(seq) is not int or seq<=self.feedback_sequence:return
        if any(type(v) not in (int,float) or not math.isfinite(v) for v in (stamp,seconds)):return
        if seconds<0 or not 0<=self.clock()-stamp<=self.feedback_ttl:return
        self.feedback_sequence=seq;self.feedback=dict(feedback)

    def _boundaries(self, final):
        text=self.pending
        for i,c in enumerate(text):
            # One character of lookahead prevents a token split inside 3.14 / Dr.
            if i+1==len(text) and not final:continue
            end=i+1
            if c=='.':
                if i and text[i-1].isdigit() and end<len(text) and text[end].isdigit():continue
                word=re.search(r'([A-Za-z.]+)$',text[:end])
                if word and (word[1].lower() in {'dr.','mr.','mrs.','ms.','prof.','e.g.','i.e.'}
                             or re.fullmatch(r'(?:[A-Za-z]\.)+',word[1])):continue
                if end<len(text) and text[end].isalnum():continue
            if c not in '.!?。！？\n,;，；:：':continue
            if c in ',:' and i and text[i-1].isdigit() and end<len(text) and text[end].isdigit():continue
            while end<len(text) and text[end].isspace():end+=1
            yield end, c in '.!?。！？\n'

    def feed(self, text='', final=False):
        if not isinstance(text,str):raise TypeError('decoded text required')
        now=self.clock()
        if text and not self.pending:self.since=now
        self.pending+=text
        output=[]
        while self.pending:
            fresh=self.feedback and 0<=now-self.feedback['at']<=self.feedback_ttl
            if fresh:
                remaining=max(0.,self.feedback['seconds']-(now-self.feedback['at']))
                if remaining<=self.estimate+.2:self.urgent=True
                elif remaining>=self.estimate+.8:self.urgent=False
            else:self.urgent=False
            short=(self.strategy=='short_first' and self.first) or (
                self.strategy=='buffer_aware' and ((fresh and self.urgent) or self.first))
            chosen=None
            for end,sentence in self._boundaries(final):
                if end>self.max_chars:break
                if sentence or (short and end>=self.min_chars):chosen=end;break
            if chosen is None and self.pending.strip():
                # Timeout only flushes at a complete word, never inside a number/word.
                expired=self.since is not None and now-self.since>=self.max_wait
                if len(self.pending)>self.max_chars or expired:
                    spaces=[m.end() for m in re.finditer(r'\s+',self.pending[:self.max_chars])
                            if m.start()>0]
                    if spaces:chosen=spaces[-1]
                if chosen is None and final and len(self.pending)<=self.max_chars:chosen=len(self.pending)
                if chosen is None and len(self.pending)>self.max_chars:
                    raise ValueError('no safe boundary within TTS text limit')
            if chosen is None:break
            output.append(self.pending[:chosen]);self.pending=self.pending[chosen:]
            self.first=False;self.since=now if self.pending else None
        # Whitespace carries no speech; preserve it with the final emitted segment when possible.
        if final and self.pending and not self.pending.strip():
            if output:output[-1]+=self.pending
            else:output.append(self.pending)
            self.pending=''
        return output
