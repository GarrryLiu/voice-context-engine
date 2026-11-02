import os
import unittest
from voice_context.native import NativeRuntime


@unittest.skipUnless(os.environ.get('VOICE_RUNTIME_LIBRARY'),'explicit native build required')
class NativeTests(unittest.TestCase):
    def test_utf8_split_boundaries_and_flush_match_both_modes(self):
        for optimized in (False,True):
            r=NativeRuntime(capacity=1024,incremental=optimized)
            try:
                source='你好。Next! 最后一段'.encode();joined=b''
                for byte in source:
                    self.assertEqual(r.append(1,bytes([byte])),1)
                    while (frame:=r.pop(1)) is not None:joined+=frame['data']
                self.assertEqual(r.append(1,b'',finish=True),1)
                while (frame:=r.pop(1)) is not None:joined+=frame['data']
                self.assertEqual(joined,source)
            finally:r.close()
    def test_cancel_stops_partial_playback_and_late_tts(self):
        r=NativeRuntime(capacity=64)
        try:
            self.assertEqual(r.push(2,1,0,b'abcdefgh'),1)
            self.assertEqual(r.render(1,3),(b'abc',3))
            r.advance(2);self.assertEqual(r.push(2,1,1,b'late'),0)
            self.assertEqual(r.render(2,8),(bytes(8),0))
        finally:r.close()
    def test_backpressure_is_atomic_and_order_errors_do_not_advance_sequence(self):
        r=NativeRuntime(capacity=16,max_items=1)
        try:
            self.assertEqual(r.append(1,b'a.b.'),2);self.assertIsNone(r.pop(1))
            self.assertEqual(r.push(0,1,1,b'x'),-3)
            self.assertEqual(r.push(0,1,0,b'x'),1)
            self.assertEqual(r.push(0,1,1,b'x'),2)
            self.assertEqual(r.pop(0)['data'],b'x')
            self.assertEqual(r.push(0,1,1,b'y'),1)
        finally:r.close()
    def test_closed_runtime_and_invalid_ids_fail(self):
        r=NativeRuntime();r.close()
        with self.assertRaises(RuntimeError):r.advance(1)
        r=NativeRuntime()
        try:
            with self.assertRaises(ValueError):r.advance(-1)
        finally:r.close()
