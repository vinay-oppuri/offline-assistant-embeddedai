"""Compress the Vosk acoustic model using Kaldi's CompressedMatrix (CM) format.

Converts FloatMatrix (FM) sections from float32 (4 bytes/weight) to
Kaldi-native CompressedMatrix format (uint8, ~1 byte/weight).  Vosk reads
CM sections natively so no loader changes are needed.

Binary format reference (from kaldi/src/matrix/compressed-matrix.cc):
  Write: WriteToken "CM" -> writes "CM " (3 bytes)
         then GlobalHeader bytes 4..19 (skips the format int32)
         then PerColHeaders + data
  Read:  ReadToken "CM" -> sets format=1
         reads 16 bytes into GlobalHeader offset 4 (min,range,rows,cols)
         reads remaining (col_headers + data)
  Data is stored COLUMN-MAJOR for kOneByteWithColHeaders format.

Usage:
    python -m tools.quantize_model              # compress
    python -m tools.quantize_model --verify     # compress + recognition test
    python -m tools.quantize_model --restore    # restore original from backup
"""

import argparse
import shutil
import struct
from pathlib import Path

import numpy as np

MODEL_DIR = Path("models/vosk-model-small-en-us-0.15")
MODEL_FILE = MODEL_DIR / "am" / "final.mdl"
BACKUP_FILE = MODEL_DIR / "am" / "final.mdl.bak"


def _scan_fm_sections(data: bytes) -> list[tuple[int, int, int, int]]:
    """Return (offset, rows, cols, data_byte_count) for every FM section."""
    sections = []
    i = 0
    while i < len(data) - 14:
        if data[i:i+3] == b"FM " and data[i+3] == 4:
            rows = struct.unpack_from("<i", data, i + 4)[0]
            if i + 8 < len(data) and data[i + 8] == 4:
                cols = struct.unpack_from("<i", data, i + 9)[0]
                if 0 < rows <= 20000 and 0 < cols <= 20000:
                    nbytes = rows * cols * 4
                    if i + 13 + nbytes <= len(data):
                        sections.append((i, rows, cols, nbytes))
                        i = i + 13 + nbytes
                        continue
        i += 1
    return sections


def _float_to_uint16(global_min: float, global_range: float, value: float) -> int:
    f = (value - global_min) / global_range
    f = max(0.0, min(1.0, f))
    return int(f * 65535 + 0.499)


def _uint16_to_float(global_min: float, global_range: float, value: int) -> float:
    return global_min + global_range * 1.52590218966964e-05 * value


def _fm_to_cm(matrix: np.ndarray) -> bytes:
    """Convert a float32 matrix to Kaldi CM binary format.

    Kaldi file layout for kOneByteWithColHeaders (format=1):
      "CM "                    3 bytes  (WriteToken)
      min_value (float32)      4 bytes  (GlobalHeader bytes 4-7)
      range     (float32)      4 bytes  (GlobalHeader bytes 8-11)
      num_rows  (int32)        4 bytes  (GlobalHeader bytes 12-15)
      num_cols  (int32)        4 bytes  (GlobalHeader bytes 16-19)
      PerColHeader[num_cols]   num_cols * 8 bytes
      uint8 data               num_cols * num_rows bytes  (COLUMN-MAJOR)
    """
    rows, cols = matrix.shape
    global_min = float(matrix.min())
    global_max = float(matrix.max())
    global_range = global_max - global_min
    if global_range == 0:
        global_range = 1.0 + abs(global_min)

    # -- per-column percentiles (matching Kaldi's ComputeColHeader) --
    col_headers = np.zeros((cols, 4), dtype=np.uint16)
    for c in range(cols):
        col = np.sort(matrix[:, c].copy())
        nr = len(col)
        if nr >= 5:
            quarter = nr // 4
            p0_val   = float(col[0])
            p25_val  = float(col[quarter])
            p75_val  = float(col[3 * quarter])
            p100_val = float(col[nr - 1])
        else:
            p0_val   = float(col[0])
            p25_val  = float(col[min(1, nr-1)])
            p75_val  = float(col[min(2, nr-1)])
            p100_val = float(col[min(3, nr-1)])

        u0   = min(_float_to_uint16(global_min, global_range, p0_val),   65532)
        u25  = min(max(_float_to_uint16(global_min, global_range, p25_val),  u0 + 1),  65533)
        u75  = min(max(_float_to_uint16(global_min, global_range, p75_val),  u25 + 1), 65534)
        u100 = max(_float_to_uint16(global_min, global_range, p100_val), u75 + 1)

        col_headers[c] = [u0, u25, u75, u100]

    # -- quantise to uint8 (column-major, matching Kaldi's CompressColumn) --
    quantised = np.zeros((cols, rows), dtype=np.uint8)  # [col][row] for column-major
    for c in range(cols):
        u0, u25, u75, u100 = col_headers[c]
        fp0   = _uint16_to_float(global_min, global_range, u0)
        fp25  = _uint16_to_float(global_min, global_range, u25)
        fp75  = _uint16_to_float(global_min, global_range, u75)
        fp100 = _uint16_to_float(global_min, global_range, u100)
        col_data = matrix[:, c]

        for r in range(rows):
            v = float(col_data[r])
            if v < fp25:
                f = (v - fp0) / (fp25 - fp0)
                ans = int(f * 64 + 0.5)
                ans = max(0, min(64, ans))
            elif v < fp75:
                f = (v - fp25) / (fp75 - fp25)
                ans = 64 + int(f * 128 + 0.5)
                ans = max(64, min(192, ans))
            else:
                f = (v - fp75) / (fp100 - fp75)
                ans = 192 + int(f * 63 + 0.5)
                ans = max(192, min(255, ans))
            quantised[c, r] = ans

    # -- pack binary --
    buf = bytearray()
    buf.extend(b"CM ")                                   # token (3 bytes)
    buf.extend(struct.pack("<f", global_min))             # min_value
    buf.extend(struct.pack("<f", global_range))           # range
    buf.extend(struct.pack("<i", rows))                   # num_rows
    buf.extend(struct.pack("<i", cols))                   # num_cols
    for c in range(cols):                                 # PerColHeaders
        buf.extend(struct.pack("<HHHH", *col_headers[c]))
    buf.extend(quantised.tobytes())                       # data (column-major)
    return bytes(buf)


def compress_model(verify: bool = False) -> None:
    if not MODEL_FILE.exists():
        raise FileNotFoundError(f"Model not found: {MODEL_FILE}")

    original_size = MODEL_FILE.stat().st_size
    print(f"[compress] Original: {MODEL_FILE} ({original_size / 1024 / 1024:.2f} MB)")

    if not BACKUP_FILE.exists():
        shutil.copy2(MODEL_FILE, BACKUP_FILE)
        print(f"[compress] Backup:   {BACKUP_FILE}")
    else:
        print(f"[compress] Backup already exists")

    data = MODEL_FILE.read_bytes()
    sections = _scan_fm_sections(data)
    print(f"[compress] FM sections found: {len(sections)}")

    if not sections:
        print("[compress] Nothing to compress")
        return

    out = bytearray()
    prev_end = 0
    total_fm = 0
    total_cm = 0

    for idx, (offset, rows, cols, nbytes) in enumerate(sections):
        fm_start = offset
        fm_end   = offset + 13 + nbytes

        out.extend(data[prev_end:fm_start])

        float_data = data[fm_start + 13 : fm_end]
        matrix = np.frombuffer(float_data, dtype=np.float32).reshape(rows, cols)

        cm_bytes = _fm_to_cm(matrix)
        out.extend(cm_bytes)

        total_fm += (fm_end - fm_start)
        total_cm += len(cm_bytes)
        prev_end = fm_end

        if (idx + 1) % 10 == 0 or idx == len(sections) - 1:
            print(f"  compressed {idx+1}/{len(sections)} matrices...")

    out.extend(data[prev_end:])

    MODEL_FILE.write_bytes(out)
    new_size = len(out)

    print(f"[compress] FM bytes: {total_fm:,}  ->  CM bytes: {total_cm:,}")
    print(f"[compress] Model:    {original_size/1024/1024:.2f} MB -> {new_size/1024/1024:.2f} MB")
    print(f"[compress] Saved:    {(original_size-new_size)/1024/1024:.2f} MB ({(1-new_size/original_size)*100:.1f}%)")

    if verify:
        _verify_model()


def _verify_model() -> None:
    import json, time, wave, psutil, os
    import vosk
    from assistant.parser import build_grammar_vocab, parse

    process = psutil.Process(os.getpid())
    print()
    print("[verify] Loading compressed model...")
    mem_before = process.memory_info().rss / (1024**2)

    start = time.perf_counter()
    model = vosk.Model(str(MODEL_DIR))
    load_time = time.perf_counter() - start
    mem_after = process.memory_info().rss / (1024**2)

    grammar = json.dumps(build_grammar_vocab())
    wav_path = Path("open_chrome_16k.wav")
    if not wav_path.exists():
        print("[verify] Test WAV not found -- skipping")
        return

    latencies = []
    for _ in range(5):
        rec = vosk.KaldiRecognizer(model, 16000, grammar)
        start = time.perf_counter()
        with wave.open(str(wav_path), "rb") as wf:
            while True:
                d = wf.readframes(4000)
                if not d: break
                rec.AcceptWaveform(d)
        latencies.append(time.perf_counter() - start)
        result = json.loads(rec.FinalResult())

    text = result.get("text", "").strip()
    parsed = parse(text)

    print(f"[verify] Load time:       {load_time:.3f}s")
    print(f"[verify] RAM after load:  {mem_after:.1f}MB (delta +{mem_after-mem_before:.1f}MB)")
    print(f"[verify] Avg recognition: {sum(latencies)/len(latencies):.3f}s")
    print(f"[verify] Recognized:      {text!r}")
    print(f"[verify] Intent:          {parsed.intent} / app={parsed.app}")

    if parsed.intent == "open_app" and parsed.app == "chrome":
        print("[verify] PASS - compressed model works!")
    else:
        print("[verify] WARN - recognition may have degraded")


def restore() -> None:
    if BACKUP_FILE.exists():
        shutil.copy2(BACKUP_FILE, MODEL_FILE)
        print(f"[restore] Restored original from {BACKUP_FILE}")
    else:
        print("[restore] No backup found.")


def main() -> None:
    ap = argparse.ArgumentParser(description="Compress Vosk model FM->CM")
    ap.add_argument("--verify", action="store_true")
    ap.add_argument("--restore", action="store_true")
    args = ap.parse_args()
    if args.restore:
        restore()
    else:
        compress_model(verify=args.verify)


if __name__ == "__main__":
    main()
