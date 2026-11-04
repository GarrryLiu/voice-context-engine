"""Bounded opt-in text prefetch. Only the producer thread owns the provider iterator."""
import queue
import threading
import time
from .sessions import StaleInteraction

# A provider that ignores cancellation can occupy a slot until its own timeout.
# Keep those lingering threads bounded process-wide rather than spawning forever.
_SLOTS = threading.BoundedSemaphore(8)


class TextPrefetch:
    def __init__(self, factory, cancelled, deadline, max_bytes, capacity=4):
        if not _SLOTS.acquire(blocking=False):
            raise RuntimeError('text prefetch capacity exhausted')
        self.queue = queue.Queue(maxsize=capacity)
        self.stop = threading.Event()
        self.cancelled, self.deadline = cancelled, deadline
        self.active_seconds = 0.
        self.thread = threading.Thread(target=self._produce, args=(factory, max_bytes), daemon=True)
        try:self.thread.start()
        except BaseException:
            _SLOTS.release()
            raise

    def _put(self, item):
        while not self.stop.is_set() and not self.cancelled.is_set() and time.monotonic() < self.deadline:
            try:
                self.queue.put(item, timeout=.01)
                return True
            except queue.Full:pass
        return False

    def _produce(self, factory, max_bytes):
        stream = None
        try:
            started = time.perf_counter()
            try:stream = iter(factory())
            finally:self.active_seconds += time.perf_counter() - started
            total = 0
            while not self.stop.is_set() and not self.cancelled.is_set() and time.monotonic() < self.deadline:
                started = time.perf_counter()
                exhausted = False
                try:item = next(stream)
                except StopIteration:exhausted = True
                finally:self.active_seconds += time.perf_counter() - started
                if exhausted:
                    self._put(('end', None))
                    return
                total += len(item.encode('utf-8') if isinstance(item, str) else item)
                if total > max_bytes:raise ValueError('response text byte cap exceeded')
                if not self._put(('text', item)):return
        except Exception as error:
            self._put(('error', error))
        finally:
            try:
                if stream is not None and hasattr(stream, 'close'):stream.close()
            finally:_SLOTS.release()

    def __iter__(self):return self

    def __next__(self):
        while True:
            if self.cancelled.is_set() or self.stop.is_set():
                raise StaleInteraction('response cancelled')
            if time.monotonic() >= self.deadline:raise TimeoutError('response deadline exceeded')
            try:kind, item = self.queue.get(timeout=.01)
            except queue.Empty:continue
            if kind == 'end':raise StopIteration
            if kind == 'error':raise item
            return item

    def close(self):
        self.stop.set()
        self.thread.join(timeout=.1)
