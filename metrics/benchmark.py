import time

from assistant.parser import build_grammar_vocab, parse
from assistant.profiles import current_profile
from metrics.monitor import BenchmarkReport, MetricsMonitor

COMMAND_SAMPLES = [
    "open chrome",
    "launch notepad",
    "increase volume",
    "volume down",
    "mute",
    "brightness up",
    "take screenshot",
    "system info",
    "search embedded ai projects",
    "set timer for five minutes",
    "restart",
]


def run_parser_benchmark(report: BenchmarkReport) -> None:
    start = time.perf_counter()
    for command in COMMAND_SAMPLES:
        parse(command)
    report.add_timing("parser_samples", time.perf_counter() - start)


def run_vosk_load_benchmark(report: BenchmarkReport, monitor: MetricsMonitor) -> None:
    from assistant.speech_to_text import SpeechToText

    profile = current_profile()
    start = time.perf_counter()
    SpeechToText(model_path=profile.model_path)
    report.add_timing("vosk_load", time.perf_counter() - start)
    report.add_sample("vosk_load", monitor)


def main() -> None:
    monitor = MetricsMonitor()
    report = BenchmarkReport()

    grammar = build_grammar_vocab()
    print(f"[benchmark] profile={current_profile().name}")
    print(f"[benchmark] grammar_terms={len(grammar)}")

    run_parser_benchmark(report)
    report.add_sample("parser", monitor)

    try:
        run_vosk_load_benchmark(report, monitor)
    except Exception as e:
        print(f"[benchmark] vosk_load_skipped={e}")

    print(f"[benchmark] {report.format()}")


if __name__ == "__main__":
    main()
