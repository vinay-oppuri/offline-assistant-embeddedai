"""Shared singleton audio stream for wake-word and speech-to-text.

Instead of opening separate OS audio streams for wake detection and STT,
this module provides a single RawInputStream that feeds both consumers
through a frame queue. A ring buffer preserves recent audio so the start
of a spoken command is never lost during the wake→STT handoff.
"""

import collections
import queue
import threading

import sounddevice as sd

SAMPLE_RATE = 16000
FRAME_LENGTH = 160  # 10 ms at 16 kHz — required by MicroWakeWord
RING_BUFFER_SECONDS = 0.5
RING_BUFFER_FRAMES = int(SAMPLE_RATE * RING_BUFFER_SECONDS / FRAME_LENGTH)

# How many 10 ms frames to accumulate before handing to Vosk (100 ms)
STT_ACCUMULATE = 10


class AudioStream:
    """Singleton shared audio stream.

    Usage::

        stream = AudioStream.get()
        stream.start()

        # Wake-word phase — read 10 ms frames one at a time
        frame = stream.read_frame()

        # STT phase — grab the ring-buffer backlog, then keep reading
        backlog = stream.drain_ring_buffer()
        frame = stream.read_frame()

        # When done, stop (or leave running for next cycle)
        stream.stop()
    """

    _instance: "AudioStream | None" = None
    _lock = threading.Lock()

    @classmethod
    def get(cls) -> "AudioStream":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def __init__(self) -> None:
        self._ring_buffer: collections.deque[bytes] = collections.deque(
            maxlen=RING_BUFFER_FRAMES,
        )
        self._frame_queue: queue.Queue[bytes] = queue.Queue(maxsize=200)
        self._stream: sd.RawInputStream | None = None
        self._running = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        if self._running:
            return
        self._stream = sd.RawInputStream(
            samplerate=SAMPLE_RATE,
            channels=1,
            dtype="int16",
            blocksize=FRAME_LENGTH,
            callback=self._callback,
        )
        self._stream.start()
        self._running = True
        print("[audio] Shared audio stream started")

    def stop(self) -> None:
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None
        self._running = False

    # ------------------------------------------------------------------
    # Internal callback
    # ------------------------------------------------------------------

    def _callback(self, indata, frames, time_info, status) -> None:
        pcm = bytes(indata)
        self._ring_buffer.append(pcm)
        try:
            self._frame_queue.put_nowait(pcm)
        except queue.Full:
            # Drop oldest frame to keep real-time
            try:
                self._frame_queue.get_nowait()
            except queue.Empty:
                pass
            try:
                self._frame_queue.put_nowait(pcm)
            except queue.Full:
                pass

    # ------------------------------------------------------------------
    # Consumer API
    # ------------------------------------------------------------------

    def read_frame(self, timeout: float = 0.2) -> bytes | None:
        """Return the next 10 ms audio frame, or *None* on timeout."""
        try:
            return self._frame_queue.get(timeout=timeout)
        except queue.Empty:
            return None

    def drain_ring_buffer(self) -> list[bytes]:
        """Return a copy of the ring buffer (recent ~0.5 s of audio).

        Used by STT to recover audio that arrived *before* the wake-word
        callback finished, so the beginning of the user's command is
        never lost.
        """
        return list(self._ring_buffer)

    def flush_queue(self) -> None:
        """Discard any queued frames (call before switching consumers)."""
        while not self._frame_queue.empty():
            try:
                self._frame_queue.get_nowait()
            except queue.Empty:
                break
