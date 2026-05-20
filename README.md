# Offline Assistant Embedded AI

An offline, command-focused Jarvis-style voice assistant built for embedded
and resource-constrained devices. It listens for a wake word, converts a
short spoken command to text with Vosk, parses the command locally, and
executes a platform action — all without any cloud APIs.

## Architecture

```text
Microphone
    │
    ▼
┌──────────────────┐
│  Shared Audio     │   Single OS audio stream (16 kHz, mono, 10 ms frames)
│  Stream           │   Ring buffer preserves ~0.5 s of recent audio
└────────┬─────────┘
         │
    ┌────┴────┐
    ▼         ▼
┌────────┐ ┌────────────┐
│ Wake   │ │ Speech-to- │   Vosk with constrained command grammar (~118 terms)
│ Word   │ │ Text (STT) │   Quantised acoustic model (CM format, 4.24 MB)
└────────┘ └─────┬──────┘
                 │
                 ▼
          ┌──────────┐
          │  Parser   │   Exact phrase match → fuzzy fallback (rapidfuzz)
          └────┬─────┘
               │
               ▼
          ┌──────────┐
          │ Executor  │   Windows / Linux / Forward-only backend
          └──────────┘
```

### Shared Audio Stream

The wake-word detector and the Vosk recogniser share a **single OS audio
stream** (`assistant/audio_stream.py`). A ring buffer keeps the last 0.5
seconds of audio so that when the wake word fires, the STT consumer can
replay the backlog and never miss the first word of a command.

Previous versions opened two separate streams — one for wake detection
and another for STT — which doubled OS buffer allocations and introduced
a 50–200 ms audio gap during the handoff.

### Parser and Grammar

The speech grammar is generated from the parser source of truth:

- `INTENTS` — all supported command phrases
- `APP_MAP` — application names and executables
- `WORD_NUMBERS` — spoken numbers (one, two, five, etc.)
- `GRAMMAR_EXTRA_WORDS` — modifiers (percent, seconds, etc.)

This keeps Vosk recognition and parser behaviour synced. When you add a
new app or intent, the grammar picks it up automatically.

The parser prefers exact phrase matches on word boundaries before fuzzy
matching:

```text
restart     → ParsedCommand(intent='restart')
start chrome → ParsedCommand(intent='open_app', app='chrome')
```

### Lazy Voice Loading

`main.py cli` does not load the microphone, wake-word model, or Vosk
model. Voice components are loaded only when `run_voice()` starts.

This makes CLI testing faster and safer on machines or embedded boards
without a configured microphone.

### Platform Executors

The executor layer is split by platform:

```text
assistant/executor_common.py    ← base class + shared logic
assistant/executor_windows.py   ← Windows backend
assistant/executor_linux.py     ← Linux / Raspberry Pi backend
assistant/executor.py           ← dispatcher (selects backend from profile)
```

**Windows backend** — volume (pycaw), brightness (screen-brightness-control),
app launching, file explorer, screenshots, lock screen, shutdown/restart,
Windows SAPI speech.

**Linux backend** — volume (pactl / amixer), brightness (brightnessctl),
app/file opening, screenshots (gnome-screenshot / scrot), lock screen,
shutdown/restart (systemctl), speech (espeak).

**Microcontroller profile** — forward-only. Parses the command and reports
the structured intent instead of executing local OS actions.

### Deployment Profiles

Set `JARVIS_PROFILE` to select the runtime shape:

```powershell
$env:JARVIS_PROFILE="desktop"
$env:JARVIS_PROFILE="raspberry-pi"
$env:JARVIS_PROFILE="microcontroller"
```

| Profile | Backend | Listen Window | Purpose |
| --- | --- | ---: | --- |
| `desktop` | auto Windows/Linux | 3.0 s | Main desktop assistant |
| `raspberry-pi` | Linux | 2.5 s | Embedded Linux command assistant |
| `microcontroller` | forward-only | 2.0 s | Wake/parse/forward deployment |

Profiles live in `assistant/profiles.py`.

---

## Setup

This project uses `uv` and expects Python 3.13.

```powershell
$env:UV_CACHE_DIR = (Resolve-Path '.').Path + '\.uv-cache'
uv run python --version
```

The first run creates `.venv` and installs dependencies from `uv.lock`.
No `.env` keys are required — the project is fully offline.

## Running

Interactive CLI:

```powershell
uv run python jarvis.py
```

Direct text command:

```powershell
uv run python jarvis.py "system info"
uv run python jarvis.py "open chrome"
```

Voice mode:

```powershell
uv run python main.py
```

CLI through `main.py` without loading voice models:

```powershell
uv run python main.py cli
```

Microcontroller/forward-only smoke test:

```powershell
$env:JARVIS_PROFILE="microcontroller"
uv run python jarvis.py "restart"
```

## Model Inventory

One model folder is committed in the repo:

```text
models/vosk-model-small-en-us-0.15
```

It is a small US English Vosk speech-to-text model. The acoustic model
(`final.mdl`) has been quantised to Kaldi's CompressedMatrix format,
reducing it from 15.22 MB to 4.24 MB. The original is preserved as
`final.mdl.bak`.

Runtime also uses a built-in wake-word model:

```text
pymicro_wakeword → Model.OKAY_NABU
```

That wake model is loaded from the Python package, not from `models/`.

---

## Optimisation Experiments

All experiments use `open_chrome_16k.wav` (a 16 kHz mono recording of the
phrase "open chrome") and are measured on the same desktop machine.

### Experiment 1 — Command Grammar Constraint

**Goal:** Restrict the Vosk decoder to only the words used by our command
parser instead of the full English vocabulary.

**Method:** `build_grammar_vocab()` in `parser.py` generates a JSON word
list (~118 terms) from `INTENTS`, `APP_MAP`, `WORD_NUMBERS`, and
`GRAMMAR_EXTRA_WORDS`. This is passed to `KaldiRecognizer` as a grammar
constraint.

**Results** (5-run average, optimised decoder settings):

| Metric | Grammar OFF | Grammar ON |
| --- | ---: | ---: |
| Vosk load time | 0.751 s | 0.714 s |
| Recognition latency avg | 1.108 s | 0.116 s |
| Memory after Vosk load | 154.4 MB | 153.7 MB |
| CPU sample | 26.3% | 18.0% |
| Recognised text | *open could own* | *open chrome* |
| Parsed intent | open_app | open_app |

**Conclusion:** The command grammar had the strongest single impact of all
optimisations — it reduced recognition latency by **~10×** and fixed
recognition accuracy from a wrong transcription to the correct one.

---

### Experiment 2 — Decoder Parameter Tuning

**Goal:** Reduce CPU work during Kaldi beam search decoding.

**Method:** Lowered `--max-active` from 3000 to 1000 and `--beam` from
10.0 to 7.0 in `models/.../conf/model.conf`. These parameters limit the
number of active decoding hypotheses and the search beam width.

**Results** (5-run average, grammar ON):

| Metric | Default Decoder | Tuned Decoder |
| --- | ---: | ---: |
| Vosk load time | 0.664 s | 0.641 s |
| Recognition latency avg | 0.112 s | 0.109 s |
| Memory after Vosk load | 151.8 MB | 153.6 MB |
| CPU sample | 3.0% | 0.0% |
| Recognised text | *open chrome* | *open chrome* |

**Conclusion:** Modest latency and CPU improvements with no accuracy loss.
Memory roughly unchanged.

---

### Experiment 3 — ivector (Speaker Adaptation) Removal

**Goal:** Remove the `ivector/` directory (~8.5 MB on disk) to save memory
and disk space on embedded devices.

**Method:** Measured model load time and memory with and without the
`ivector/` directory.

**Load-only results:**

| Model Variant | Load Time | RAM After Load |
| --- | ---: | ---: |
| With `ivector/` | 0.809 s | 147.9 MB |
| Without `ivector/` | 0.632 s | 133.0 MB |

**However**, when actually running the recogniser without `ivector/`, Vosk
crashes with:

```text
ERROR: Ivector feature dimension mismatch: got -1 but network expects 30
```

The acoustic model's neural network was trained with 30-dimensional ivector
input for speaker adaptation. Removing the ivector files lets the model
*load*, but recognition *fails* because the network expects those features
at inference time.

**Conclusion:** The ivector directory **cannot be removed** from this model.
The load-time savings are real but useless without a working recogniser.
A model retrained without ivector input would be needed to realise these
savings.

---

### Experiment 4 — Acoustic Model Quantisation (FM → CM)

**Goal:** Reduce the size of `final.mdl` (the acoustic model neural network
weights) on disk.

**Problem:** The model stores all weight matrices in Kaldi's FloatMatrix
(FM) format — 4 bytes per weight (float32). For a command-recognition
task, full 32-bit precision is unnecessary.

**Method:** Built a Python quantisation script (`tools/quantize_model.py`)
that:

1. Scans the Kaldi nnet3 binary for all FloatMatrix (FM) sections
2. Converts each to Kaldi's native **CompressedMatrix (CM)** format — 
   uint8 quantisation with per-column percentile headers (1 byte per weight
   instead of 4)
3. Writes the compressed model in-place (backup saved as `final.mdl.bak`)

The CM format uses a 3-region linear interpolation per column:
- Values in [p0, p25] → mapped to byte range 0–64
- Values in [p25, p75] → mapped to byte range 64–192
- Values in [p75, p100] → mapped to byte range 192–255

Vosk/Kaldi reads CM format natively — no loader changes are needed. On
load, Kaldi decompresses CM back to float32 in memory, so RAM usage
during inference is unchanged.

**Results:**

| Metric | Original (FM) | Quantised (CM) |
| --- | ---: | ---: |
| `final.mdl` file size | 15.22 MB | 4.24 MB |
| Matrices compressed | — | 30 |
| Weights quantised | — | 3,958,207 |
| Compression ratio | — | 72.2% smaller |
| Recognised text | *open chrome* | *open chrome* |
| Parsed intent | open_app / chrome | open_app / chrome |

**Full model directory size:**

| Component | Size |
| --- | ---: |
| `final.mdl` (quantised) | 4.24 MB |
| `Gr.fst` (language model) | 22.9 MB |
| `HCLr.fst` (HMM/lexicon) | 21.4 MB |
| `ivector/` (speaker adapt) | 8.1 MB |
| Other config files | < 0.1 MB |
| **Total** | **56.6 MB** |

(Previously 67.6 MB — **16.3% total reduction.**)

**Conclusion:** The acoustic model shrank by 72.2% with zero accuracy loss
on the test audio. This is the most impactful disk-space optimisation.

The quantisation tool supports backup and restore:

```powershell
uv run python -m tools.quantize_model --verify    # compress + test
uv run python -m tools.quantize_model --restore   # restore original
```

---

### Experiment 5 — Shared Audio Stream

**Goal:** Eliminate the audio gap between wake-word detection and speech
recognition, and reduce OS resource usage.

**Problem:** The original design opened two separate OS audio streams — one
for the wake-word detector (`sd.InputStream`) and another for the Vosk
recogniser (`sd.RawInputStream`). This caused:

- Two sets of OS audio buffers allocated
- A 50–200 ms gap while closing one stream and opening the next
- The first word of a command was often lost during this handoff

**Method:** Created a singleton `AudioStream` class
(`assistant/audio_stream.py`) that runs a single `sd.RawInputStream` for the
entire voice loop. A ring buffer preserves the last 0.5 s of audio. When
the wake word fires, the STT consumer replays the ring-buffer backlog before
reading live frames, so the start of the command is never lost.

**Results:**

| Metric | Before (two streams) | After (shared stream) |
| --- | --- | --- |
| OS audio streams | 2 (opened/closed per cycle) | 1 (always running) |
| Audio gap on wake → STT | ~50–200 ms (audio lost) | 0 ms (ring buffer) |
| First-word recognition | Frequently missed | Preserved |
| Stream open/close overhead | ~20 ms per cycle | 0 ms |

**Conclusion:** The shared audio stream eliminates the first-word-swallowing
problem and removes per-cycle stream overhead. This is the highest-impact
change for user experience during voice interaction.

---

### Summary of All Optimisations

| # | Optimisation | Key Result |
| --- | --- | --- |
| 1 | Command grammar constraint | **10× faster** recognition, correct transcription |
| 2 | Decoder parameter tuning | Modest latency/CPU improvement |
| 3 | ivector removal (attempted) | **Cannot remove** — model requires it at inference |
| 4 | Acoustic model quantisation (FM → CM) | **72.2% smaller** `final.mdl` (15.2 → 4.2 MB) |
| 5 | Shared audio stream | **Zero audio gap**, no missed first words |

Combined before/after (general benchmark):

| Metric | Baseline | After All Optimisations |
| --- | ---: | ---: |
| Grammar terms | 118 | 118 |
| Vosk load time | 1.289 s | 0.960 s |
| Vosk load memory | 46.9 MB | 48.9 MB |
| Model disk size | 67.6 MB | 56.6 MB |
| `final.mdl` disk size | 15.22 MB | 4.24 MB |
| Audio streams (voice mode) | 2 | 1 |
| Recognition result | *open chrome* ✓ | *open chrome* ✓ |

---

## Benchmarks

### General Benchmark

```powershell
$env:UV_CACHE_DIR = (Resolve-Path '.').Path + '\.uv-cache'
uv run python -m metrics.benchmark
```

Example output:

```text
[benchmark] profile=desktop
[benchmark] grammar_terms=118
[benchmark] parser_samples=0.007s | vosk_load=0.960s | parser_mem=23.2MB
           | vosk_load_mem=48.9MB | parser_cpu=0.9% | vosk_load_cpu=23.2%
```

### Fixed-Audio Recognition Benchmark

```powershell
uv run python -m metrics.audio_benchmark --input open_chrome_16k.wav --runs 5
```

MP4 input requires `ffmpeg` on PATH. You can also pass a 16 kHz mono WAV
file directly.

### Model Quantisation Tool

```powershell
uv run python -m tools.quantize_model --verify    # compress + recognition test
uv run python -m tools.quantize_model --restore   # restore original from backup
```

---

## Embedded Notes

The speech stack is suitable for Raspberry Pi-class devices, especially
with the smaller grammar, lower beam settings, and quantised acoustic
model. The Windows executor is not portable, which is why the Linux and
forward-only backends exist.

Recommended validation on real hardware:

- measure wake-word CPU while idle
- measure Vosk load time and memory
- measure recognition latency with the target microphone
- compare accuracy with quantised vs original model
- decide whether the Raspberry Pi profile should keep Vosk or forward
  audio/text to a stronger local machine
