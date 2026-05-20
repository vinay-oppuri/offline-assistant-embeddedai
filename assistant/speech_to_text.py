import json

import vosk

from assistant.audio_stream import AudioStream, SAMPLE_RATE, STT_ACCUMULATE
from assistant.parser import build_grammar_vocab

DEFAULT_LISTEN_TIMEOUT_SECONDS = 3.0


class SpeechToText:
    def __init__(self, model_path: str):
        self.model = vosk.Model(model_path)
        grammar_json = json.dumps(build_grammar_vocab())
        self.recognizer = vosk.KaldiRecognizer(self.model, SAMPLE_RATE, grammar_json)

    def listen(self, timeout_seconds: float = DEFAULT_LISTEN_TIMEOUT_SECONDS) -> str:
        """Recognise speech from the shared audio stream.

        First processes any ring-buffer backlog (so the start of the
        command spoken right after the wake word is never lost), then
        reads live frames until Vosk fires an endpoint or the timeout
        expires.
        """
        self.recognizer.Reset()

        stream = AudioStream.get()
        result_text = ""

        # -----------------------------------------------------------
        # 1. Feed the ring-buffer backlog into Vosk so we don't miss
        #    the first word of the command.
        # -----------------------------------------------------------
        backlog = stream.drain_ring_buffer()
        accumulated = b""
        for frame in backlog:
            accumulated += frame
            if len(accumulated) >= STT_ACCUMULATE * len(frame):
                if self.recognizer.AcceptWaveform(accumulated):
                    result = json.loads(self.recognizer.Result())
                    text = result.get("text", "").strip()
                    if text and text != "[unk]":
                        return text
                accumulated = b""
        # Flush any remaining backlog
        if accumulated:
            self.recognizer.AcceptWaveform(accumulated)

        # -----------------------------------------------------------
        # 2. Read live audio frames until timeout or endpoint.
        # -----------------------------------------------------------
        frame_duration = 0.01  # 10 ms per frame
        max_frames = int(timeout_seconds / frame_duration)
        accumulated = b""

        for _ in range(max_frames):
            frame = stream.read_frame(timeout=0.2)
            if frame is None:
                continue

            accumulated += frame

            # Hand Vosk a chunk every STT_ACCUMULATE frames (~100 ms)
            if len(accumulated) >= STT_ACCUMULATE * len(frame):
                if self.recognizer.AcceptWaveform(accumulated):
                    result = json.loads(self.recognizer.Result())
                    text = result.get("text", "").strip()
                    if text and text != "[unk]":
                        result_text = text
                        break
                accumulated = b""

        # Flush anything left in the accumulator
        if accumulated:
            self.recognizer.AcceptWaveform(accumulated)

        if not result_text:
            partial = json.loads(self.recognizer.PartialResult())
            result_text = partial.get("partial", "").strip()

        return result_text
