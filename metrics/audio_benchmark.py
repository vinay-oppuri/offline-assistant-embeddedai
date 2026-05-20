import argparse
import json
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
import wave
from contextlib import contextmanager
from pathlib import Path

import vosk

from assistant.parser import build_grammar_vocab, parse
from assistant.profiles import current_profile
from metrics.monitor import MetricsMonitor

SAMPLE_RATE = 16000
CHUNK_FRAMES = 4000
MODEL_CONF = Path("models/vosk-model-small-en-us-0.15/conf/model.conf")


@contextmanager
def decoder_config(beam: float, max_active: int):
    original = MODEL_CONF.read_text()
    updated = []
    for line in original.splitlines():
        if line.startswith("--beam="):
            updated.append(f"--beam={beam}")
        elif line.startswith("--max-active="):
            updated.append(f"--max-active={max_active}")
        else:
            updated.append(line)

    MODEL_CONF.write_text("\n".join(updated) + "\n")
    try:
        yield
    finally:
        MODEL_CONF.write_text(original)


def extract_audio(input_path: Path, temp_dir: Path) -> Path:
    if input_path.suffix.lower() == ".wav":
        return input_path

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError(
            "MP4 input needs ffmpeg on PATH. Install ffmpeg, or convert the file to "
            "16 kHz mono WAV and pass that WAV to this script."
        )

    output_path = temp_dir / f"{input_path.stem}_16k_mono.wav"
    command = [
        ffmpeg,
        "-y",
        "-i",
        str(input_path),
        "-ac",
        "1",
        "-ar",
        str(SAMPLE_RATE),
        "-sample_fmt",
        "s16",
        str(output_path),
    ]
    subprocess.run(command, check=True, capture_output=True)
    return output_path


def recognize_wav(model: vosk.Model, wav_path: Path, use_grammar: bool = True) -> tuple[str, float]:
    if use_grammar:
        grammar_json = json.dumps(build_grammar_vocab())
        recognizer = vosk.KaldiRecognizer(model, SAMPLE_RATE, grammar_json)
    else:
        recognizer = vosk.KaldiRecognizer(model, SAMPLE_RATE)

    with wave.open(str(wav_path), "rb") as wav_file:
        if wav_file.getnchannels() != 1:
            raise ValueError("WAV must be mono.")
        if wav_file.getframerate() != SAMPLE_RATE:
            raise ValueError("WAV must be 16 kHz.")
        if wav_file.getsampwidth() != 2:
            raise ValueError("WAV must be 16-bit PCM.")

        start = time.perf_counter()
        while True:
            data = wav_file.readframes(CHUNK_FRAMES)
            if not data:
                break
            recognizer.AcceptWaveform(data)
        elapsed = time.perf_counter() - start

    result = json.loads(recognizer.FinalResult())
    return result.get("text", "").strip(), elapsed


def run_config(
    label: str,
    wav_path: Path,
    beam: float,
    max_active: int,
    runs: int,
    use_grammar: bool = True,
) -> dict:
    monitor = MetricsMonitor()
    with decoder_config(beam=beam, max_active=max_active):
        start = time.perf_counter()
        model = vosk.Model(current_profile().model_path)
        model_load = time.perf_counter() - start
        memory_after_load = monitor.memory_usage()

        latencies = []
        recognized = ""
        for _ in range(runs):
            recognized, latency = recognize_wav(model, wav_path, use_grammar=use_grammar)
            latencies.append(latency)

        parsed = parse(recognized)
        cpu_percent = monitor.cpu_usage()

    return {
        "label": label,
        "beam": beam,
        "max_active": max_active,
        "use_grammar": use_grammar,
        "runs": runs,
        "model_load_sec": model_load,
        "recognition_avg_sec": statistics.mean(latencies),
        "recognition_min_sec": min(latencies),
        "recognition_max_sec": max(latencies),
        "memory_after_load_mb": memory_after_load,
        "cpu_percent": cpu_percent,
        "recognized_text": recognized,
        "parsed_intent": parsed.intent,
        "parsed_app": parsed.app,
    }


def print_table(rows: list[dict]) -> None:
    print("| Metric | Before | After |")
    print("| --- | ---: | ---: |")
    print(f"| Vosk load time | {rows[0]['model_load_sec']:.3f}s | {rows[1]['model_load_sec']:.3f}s |")
    print(
        "| Recognition latency avg | "
        f"{rows[0]['recognition_avg_sec']:.3f}s | {rows[1]['recognition_avg_sec']:.3f}s |"
    )
    print(
        "| Memory after Vosk load | "
        f"{rows[0]['memory_after_load_mb']:.1f}MB | {rows[1]['memory_after_load_mb']:.1f}MB |"
    )
    print(f"| CPU sample | {rows[0]['cpu_percent']:.1f}% | {rows[1]['cpu_percent']:.1f}% |")
    print(f"| Recognized text | {rows[0]['recognized_text']} | {rows[1]['recognized_text']} |")
    print(f"| Parsed intent | {rows[0]['parsed_intent']} | {rows[1]['parsed_intent']} |")


def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark Vosk recognition on a fixed audio file.")
    parser.add_argument("--input", default="open_chrome.mp4", help="Input .mp4 or 16 kHz mono .wav file.")
    parser.add_argument("--runs", type=int, default=5, help="Recognition runs per config.")
    parser.add_argument("--baseline-beam", type=float, default=10.0)
    parser.add_argument("--baseline-max-active", type=int, default=3000)
    parser.add_argument("--optimized-beam", type=float, default=7.0)
    parser.add_argument("--optimized-max-active", type=int, default=1000)
    parser.add_argument(
        "--full-vocab",
        action="store_true",
        help="Disable command grammar and decode against the full model vocabulary.",
    )
    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.exists():
        raise FileNotFoundError(f"Input file not found: {input_path}")

    try:
        with tempfile.TemporaryDirectory() as temp:
            wav_path = extract_audio(input_path, Path(temp))
            rows = [
                run_config(
                    "before",
                    wav_path,
                    beam=args.baseline_beam,
                    max_active=args.baseline_max_active,
                    runs=args.runs,
                    use_grammar=not args.full_vocab,
                ),
                run_config(
                    "after",
                    wav_path,
                    beam=args.optimized_beam,
                    max_active=args.optimized_max_active,
                    runs=args.runs,
                    use_grammar=not args.full_vocab,
                ),
            ]
    except Exception as e:
        print(f"[audio-benchmark] error={e}")
        sys.exit(1)

    print(f"[audio-benchmark] input={input_path}")
    print(f"[audio-benchmark] profile={current_profile().name}")
    print(f"[audio-benchmark] grammar={'off' if args.full_vocab else 'on'}")
    print_table(rows)


if __name__ == "__main__":
    main()
