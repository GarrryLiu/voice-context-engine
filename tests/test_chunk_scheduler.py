import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from voice_context.chunk_scheduler import TextChunkScheduler
from voice_context.conversation import Conversation
from voice_context.sessions import StaleInteraction


class SchedulerTests(unittest.TestCase):
    def test_text_is_preserved_across_every_byte_boundary(self):
        texts=['Dr. Smith paid 3.14 dollars, then left. Goodbye!  ',
               '先确定计划，然后讨论执行。最后保存。', 'no punctuation', '   ',
               'The U.S. example is e.g. a date 2026-11-04.']
        for strategy in ('sentence','short_first','buffer_aware'):
            for text in texts:
                scheduler=TextChunkScheduler(strategy)
                parts=[]
                for char in text:parts+=scheduler.feed(char)
                parts+=scheduler.feed(final=True)
                self.assertEqual(''.join(parts),text)
                self.assertTrue(all(len(x)<=1600 for x in parts))

    def test_abbreviations_and_decimal_not_cut(self):
        s=TextChunkScheduler('sentence')
        self.assertEqual(s.feed('Dr. Smith paid 3.'),[])
        self.assertEqual(s.feed('14 dollars. Next'),['Dr. Smith paid 3.14 dollars. '])

    def test_short_first_changes_only_first_segment(self):
        s=TextChunkScheduler('short_first',min_chars=5)
        self.assertEqual(s.feed('Hello there, next part, then finish. More'),
                         ['Hello there, ','next part, then finish. '])

    def test_feedback_fences_and_stale_fallback(self):
        now=[10.];s=TextChunkScheduler('buffer_aware',min_chars=5,clock=lambda:now[0])
        s.feed('Initial. Next')
        s.update_playback({'epoch':2,'sequence':1,'at':10.,'seconds':0.},epoch=1)
        self.assertIsNone(s.feedback)
        s.update_playback({'epoch':1,'sequence':1,'at':10.,'seconds':0.},epoch=1)
        self.assertEqual(s.feed(' clause, following'),['Next clause, '])
        s.update_playback({'epoch':1,'sequence':0,'at':10.,'seconds':99.},epoch=1)
        self.assertEqual(s.feedback['sequence'],1)
        now[0]=12.
        # Stale feedback does not make a new phrase urgent.
        s.since=12.
        self.assertEqual(s.feed(' clause, more'),[])

    def test_timeout_and_long_word_bound(self):
        now=[0.];s=TextChunkScheduler(clock=lambda:now[0],max_wait=.2,max_chars=20,min_chars=3)
        s.feed('waiting for more')
        now[0]=.3
        self.assertEqual(s.feed(),['waiting for '])
        with self.assertRaises(ValueError):s.feed('x'*21)


@unittest.skipUnless(os.environ.get('VOICE_RUNTIME_LIBRARY'),'native required')
class CoordinatorStrategyTests(unittest.TestCase):
    def test_no_double_segmentation_and_final_utf8(self):
        for policy in ('sentence','short_first','buffer_aware'):
            with tempfile.TemporaryDirectory() as directory:
                c=Conversation(str(Path(directory)/'db'),'s')
                pieces=[];text='Dr. Smith paid 3.14 dollars, 然后继续。 Tail'
                class Text:
                    def stream(self,*args):
                        for b in text.encode():yield bytes([b])
                class TTS:
                    def stream(self,text,*args):pieces.append(text);yield text.encode()
                try:
                    c.respond('r',Text(),TTS(),chunk_strategy=policy)
                    audio,n=c.render(4096)
                    self.assertEqual(audio[:n],text.encode())
                    self.assertTrue(any('3.14' in x for x in pieces))
                finally:c.close()

    def test_timer_flushes_while_text_provider_is_waiting(self):
        sent=threading.Event()
        class Text:
            def stream(self,*args):
                yield 'Enough words to read before the provider resumes '
                if not sent.wait(2):raise AssertionError('timer did not dispatch')
                yield 'the final text.'
        class TTS:
            def stream(self,text,*args):sent.set();yield text.encode()
        with tempfile.TemporaryDirectory() as directory:
            c=Conversation(str(Path(directory)/'db'),'s')
            try:c.respond('r',Text(),TTS(),chunk_strategy='sentence')
            finally:c.close()

    def test_cancellation_clears_scheduled_audio(self):
        with tempfile.TemporaryDirectory() as directory:
            c=Conversation(str(Path(directory)/'db'),'s')
            class Text:
                def stream(self,*args):yield 'This is a phrase, followed by more text.'
            class TTS:
                def stream(self,*args):c.interrupt();yield b'old'
            try:
                with self.assertRaises(StaleInteraction):c.respond('r',Text(),TTS(),chunk_strategy='short_first')
                self.assertEqual(c.render(100)[1],0)
            finally:c.close()
