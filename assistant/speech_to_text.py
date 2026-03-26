import json
import vosk
import sounddevice as sd
import numpy as np
import queue

SAMPLE_RATE = 16000

# --- ALL words Jarvis needs to recognize ---
# Add every app name, command word, and value here.
# The more specific this list, the better accuracy you'll get.
GRAMMAR_VOCAB = [
    # intents
    "open", "close", "launch", "start", "search", "find",
    "volume", "brightness", "screenshot", "lock", "shutdown",
    "restart", "system", "info", "timer", "set", "mute", "unmute",
    # directions / values
    "up", "down", "increase", "decrease", "max", "min", "percent",
    # common app names — phonetically distinct spellings help vosk
    "brave", "chrome", "firefox", "edge", "opera",
    "notepad", "calculator", "terminal", "explorer", "spotify",
    "discord", "slack", "code", "visual studio", "steam",
    "vlc", "obs", "zoom", "teams", "word", "excel",
    # number words for timer
    "one", "two", "three", "four", "five", "ten",
    "fifteen", "twenty", "thirty", "sixty",
    "second", "seconds", "minute", "minutes",
    # filler / confirmation
    "yes", "no", "okay", "cancel",
    "[unk]"  # keep this — vosk uses it for truly unknown sounds
]


class SpeechToText:
    def __init__(self, model_path: str):
        self.model = vosk.Model(model_path)
        grammar_json = json.dumps(GRAMMAR_VOCAB)
        self.recognizer = vosk.KaldiRecognizer(self.model, SAMPLE_RATE, grammar_json)
        self.audio_queue: queue.Queue = queue.Queue()

    def _audio_callback(self, indata, frames, time, status):
        self.audio_queue.put(bytes(indata))

    def listen(self, timeout_seconds: float = 5.0) -> str:
        """Block until speech is detected or timeout. Returns transcribed text."""
        self.recognizer.Reset()
        frames_per_block = int(SAMPLE_RATE * 0.1)  # 100ms chunks
        max_blocks = int(timeout_seconds / 0.1)
        result_text = ""

        with sd.RawInputStream(
            samplerate=SAMPLE_RATE,
            blocksize=frames_per_block,
            dtype="int16",
            channels=1,
            callback=self._audio_callback,
        ):
            for _ in range(max_blocks):
                try:
                    data = self.audio_queue.get(timeout=0.2)
                except queue.Empty:
                    continue

                if self.recognizer.AcceptWaveform(data):
                    result = json.loads(self.recognizer.Result())
                    text = result.get("text", "").strip()
                    if text and text != "[unk]":
                        result_text = text
                        break

        if not result_text:
            # pick up any partial result before timeout
            partial = json.loads(self.recognizer.PartialResult())
            result_text = partial.get("partial", "").strip()

        return result_text