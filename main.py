import sys
import time

from assistant.cli import CLIInterface
from assistant.executor import execute
from assistant.parser import parse
from assistant.profiles import current_profile
from metrics.monitor import BenchmarkReport, MetricsMonitor


class OfflineAssistant:
    def __init__(self):
        self.profile = current_profile()
        self.wake = None
        self.stt = None
        self.metrics = MetricsMonitor()

    def _load_voice_stack(self):
        if self.wake is not None and self.stt is not None:
            return

        from assistant.audio_stream import AudioStream
        from assistant.speech_to_text import SpeechToText
        from assistant.wake_word import WakeWordDetector

        report = BenchmarkReport()

        # Start the shared audio stream once — it stays running for the
        # entire voice loop, serving both wake-word and STT.
        AudioStream.get().start()

        start = time.perf_counter()
        self.wake = WakeWordDetector()
        report.add_timing("wake_load", time.perf_counter() - start)
        report.add_sample("wake_load", self.metrics)

        start = time.perf_counter()
        self.stt = SpeechToText(model_path=self.profile.model_path)
        report.add_timing("vosk_load", time.perf_counter() - start)
        report.add_sample("vosk_load", self.metrics)

        print(f"[metrics] {report.format()}")

    def run_voice(self):
        self._load_voice_stack()
        print(f"Voice Assistant Started ({self.profile.name})")

        while True:
            cycle = BenchmarkReport()
            start = time.perf_counter()
            self.wake.detect()
            cycle.add_timing("wake_wait", time.perf_counter() - start)
            cycle.add_sample("wake_wait", self.metrics)

            start = time.perf_counter()
            command = self.stt.listen(timeout_seconds=self.profile.listen_timeout_seconds)
            cycle.add_timing("stt_listen", time.perf_counter() - start)
            cycle.add_sample("stt_listen", self.metrics)

            start = time.perf_counter()
            parsed_cmd = parse(command)
            execute(parsed_cmd)
            cycle.add_timing("end_to_end_action", time.perf_counter() - start)
            cycle.add_sample("action", self.metrics)

            print(f"[metrics] {cycle.format()}")

    def run_cli(self):
        cli = CLIInterface()
        cli.start()


if __name__ == "__main__":
    assistant = OfflineAssistant()

    if len(sys.argv) > 1 and sys.argv[1] == "cli":
        assistant.run_cli()
    else:
        assistant.run_voice()
