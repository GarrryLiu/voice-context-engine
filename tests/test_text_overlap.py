import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from voice_context.conversation import Conversation
from voice_context.sessions import StaleInteraction
from voice_context.text_prefetch import TextPrefetch


class PrefetchTests(unittest.TestCase):
    def test_error_and_byte_limit(self):
        for factory in (lambda: iter(['x'*11]), lambda: self.failed()):
            stream=TextPrefetch(factory,threading.Event(),time.monotonic()+2,10)
            try:
                with self.assertRaises(ValueError):next(stream)
            finally:stream.close()

    @staticmethod
    def failed():
        raise ValueError('synthetic failure')
        yield

    def test_bounded_lookahead_and_cancel(self):
        produced=[];cancel=threading.Event()
        def source():
            for i in range(100):
                produced.append(i)
                yield 'x'
        stream=TextPrefetch(source,cancel,time.monotonic()+2,100,capacity=2)
        try:
            time.sleep(.05)
            self.assertLessEqual(len(produced),3)  # two queued, one held by producer
            cancel.set()
            with self.assertRaises(StaleInteraction):next(stream)
        finally:stream.close()
        self.assertFalse(stream.thread.is_alive())

    def test_deadline_with_uncooperative_provider_and_owner_close(self):
        release=threading.Event();closed=threading.Event();owners=[]
        def source():
            try:
                owners.append(threading.get_ident())
                release.wait(2)
                yield 'late'
            finally:
                owners.append(threading.get_ident());closed.set()
        stream=TextPrefetch(source,threading.Event(),time.monotonic()+.05,100)
        try:
            with self.assertRaises(TimeoutError):next(stream)
            stream.close()
        finally:
            release.set();stream.thread.join(2)
        self.assertTrue(closed.is_set())
        self.assertEqual(owners[0],owners[1])
        self.assertNotEqual(owners[0],threading.get_ident())


@unittest.skipUnless(os.environ.get('VOICE_RUNTIME_LIBRARY'),'native runtime required')
class OverlapTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.c=Conversation(str(Path(self.tmp.name)/'test.db'),'s',overlap_text=True)
    def tearDown(self):self.c.close();self.tmp.cleanup()

    def test_text_advances_during_tts_and_preserves_order(self):
        tts_started=threading.Event();text_advanced=threading.Event();parts=[]
        class Text:
            def stream(self,*args):
                yield 'First.'
                if not tts_started.wait(2):raise AssertionError('no TTS overlap')
                text_advanced.set()
                yield 'Second.'
        class TTS:
            def stream(self,text,*args):
                parts.append(text);tts_started.set()
                if not text_advanced.wait(2):raise AssertionError('text blocked by TTS')
                yield text.encode()
        self.c.respond('r',Text(),TTS())
        self.assertEqual(parts,['First.','Second.'])
        audio,n=self.c.render(100)
        self.assertEqual(audio[:n],b'First.Second.')

    def test_interrupt_during_tts_discards_prefetched_text_and_audio(self):
        entered=threading.Event();release=threading.Event();errors=[]
        class Text:
            def stream(self,*args):
                yield 'First.'
                yield 'Old second.'
        class TTS:
            def stream(self,*args):
                entered.set();release.wait(2);yield b'old'
        def run():
            try:self.c.respond('r',Text(),TTS())
            except Exception as error:errors.append(error)
        worker=threading.Thread(target=run);worker.start()
        self.assertTrue(entered.wait(2));self.c.interrupt();release.set();worker.join(3)
        self.assertFalse(worker.is_alive())
        self.assertIsInstance(errors[0],StaleInteraction)
        self.assertEqual(self.c.render(100)[1],0)

    def test_tail_flush_and_provider_error_abort(self):
        class Text:
            def stream(self,*args):yield '尾句没有标点'
        class TTS:
            def stream(self,text,*args):yield text.encode()
        self.c.respond('r',Text(),TTS())
        audio,n=self.c.render(100)
        self.assertEqual(audio[:n],'尾句没有标点'.encode())
        class Bad:
            def stream(self,*args):
                yield 'Partial.'
                raise ValueError('synthetic')
        with self.assertRaises(ValueError):self.c.respond('bad',Bad(),TTS())
        self.assertEqual(self.c.render(100)[1],0)
