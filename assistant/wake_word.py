import sounddevice as sd
from pymicro_wakeword import MicroWakeWord, MicroWakeWordFeatures, Model


class WakeWordDetector:

    def __init__(self):
        try:
            # HEY_JARVIS is NOT released yet — use OKAY_NABU for now
            self.mww = MicroWakeWord.from_builtin(Model.OKAY_NABU)
            self.mww.probability_cutoff = 0.5   # don't go too low — causes false triggers
            self.mww.sliding_window_size = 5
            self.mww_features = MicroWakeWordFeatures()
            self.sample_rate = 16000
            self.frame_length = 160              # exactly 10ms at 16kHz
            print("[wake] Model loaded: OKAY_NABU")
            print("[wake] Say: 'Okay Nabu'")
        except Exception as e:
            print(f"[!] Failed to init wake word: {e}")
            raise SystemExit(1)

    def detect(self) -> bool:
        peak_prob = 0.0

        # blocksize must match frame_length — fixes the main audio bug
        with sd.InputStream(
            samplerate=self.sample_rate,
            channels=1,
            dtype="int16",
            blocksize=self.frame_length,   # <-- THIS was missing, critical fix
        ) as stream:
            while True:
                audio, _ = stream.read(self.frame_length)

                # audio shape is (160, 1) — flatten before tobytes
                pcm_bytes = audio.flatten().tobytes()  # <-- flattening fixes byte count

                for features in self.mww_features.process_streaming(pcm_bytes):
                    detected = self.mww.process_streaming(features)

                    # debug probability display
                    probs = self.mww._probabilities
                    if len(probs) >= self.mww.sliding_window_size:
                        from statistics import mean
                        prob_mean = mean(probs)
                        if prob_mean > peak_prob:
                            peak_prob = prob_mean
                        if prob_mean > 0.05:
                            print(
                                f"  [prob] current={prob_mean:.3f}  "
                                f"peak={peak_prob:.3f}  "
                                f"target={self.mww.probability_cutoff}",
                                end="\r"
                            )

                    if detected:
                        print(f"\n[wake] Detected! peak={peak_prob:.3f}")
                        return True