from statistics import mean

from pymicro_wakeword import MicroWakeWord, MicroWakeWordFeatures, Model

from assistant.audio_stream import AudioStream


class WakeWordDetector:

    def __init__(self):
        try:
            # HEY_JARVIS is NOT released yet — use OKAY_NABU for now
            self.mww = MicroWakeWord.from_builtin(Model.OKAY_NABU)
            self.mww.probability_cutoff = 0.5   # don't go too low — causes false triggers
            self.mww.sliding_window_size = 5
            self.mww_features = MicroWakeWordFeatures()
            print("[wake] Model loaded: OKAY_NABU")
            print("[wake] Say: 'Okay Nabu'")
        except Exception as e:
            print(f"[!] Failed to init wake word: {e}")
            raise SystemExit(1)

    def detect(self) -> bool:
        """Block until the wake word is detected.

        Reads 10 ms frames from the shared AudioStream instead of opening
        its own OS audio stream.  This keeps a single stream running for
        the entire voice loop.
        """
        peak_prob = 0.0
        stream = AudioStream.get()

        while True:
            frame = stream.read_frame(timeout=0.2)
            if frame is None:
                continue

            for features in self.mww_features.process_streaming(frame):
                detected = self.mww.process_streaming(features)

                # Lightweight probability tracking (no per-frame printing)
                probs = self.mww._probabilities
                if len(probs) >= self.mww.sliding_window_size:
                    prob_mean = sum(probs) / len(probs)
                    if prob_mean > peak_prob:
                        peak_prob = prob_mean

                if detected:
                    print(f"\n[wake] Detected! peak={peak_prob:.3f}")
                    return True