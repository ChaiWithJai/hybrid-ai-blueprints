#!/usr/bin/env python3
"""Record a purpose-built voice corpus for fine-tuning, with exact transcripts.

Why record instead of mining more archive audio: the 11.8 h of recordings on
disk are all lecture delivery, and the target register is a warm, unhurried
check-in. That is a STYLE mismatch, and more hours of the wrong style may
reinforce it. Reading prompts also removes two defects measured in the mined
dataset -- ASR transcription error, and clips that end mid-thought, which
Bonsai flagged as materially hurting a reference.

Because you read known text, the transcript is exact BY CONSTRUCTION. No
Whisper pass, no misalignment.

Usage:
    python scripts/record_voice_corpus.py                 # default mic
    python scripts/record_voice_corpus.py --device 3      # pick input
    python scripts/record_voice_corpus.py --list          # show inputs

Per prompt: ENTER starts, ENTER stops, then keep / retake / skip.
Resumable -- already-recorded prompts are skipped, so stop any time.

Record everything in ONE session on ONE mic: the clone reproduces the
reference's channel, so a consistent mic/room across the corpus (and the
reference cut from it) is worth more than any post-processing.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import queue
import subprocess
import sys
import tempfile
import wave
from pathlib import Path

REC_SR = 48000          # capture at device rate, downsample with ffmpeg
OUT_SR = 24000          # what F5 requires
MIN_S, MAX_S = 1.0, 12.0


def load_prompts(path: Path) -> list[str]:
    out = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            out.append(line)
    return out


def prompt_id(i: int, text: str) -> str:
    h = hashlib.sha1(text.encode()).hexdigest()[:6]
    return f"rec{i:03d}_{h}"


def save(frames, out_wav: Path, loudnorm: bool) -> tuple[float, float]:
    import numpy as np

    x = np.concatenate(frames, axis=0).astype("float32").reshape(-1)
    peak = float(np.abs(x).max()) if x.size else 0.0
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tf:
        raw = tf.name
    with wave.open(raw, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(REC_SR)
        w.writeframes((np.clip(x, -1, 1) * 32767).astype("<i2").tobytes())
    # Match the mined dataset's normalisation so the two can be mixed, and keep
    # true-peak headroom: several archive recordings were hard-limited near
    # 0 dBFS and made poorer references.
    af = "loudnorm=I=-20:TP=-3:LRA=11" if loudnorm else "anull"
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-y", "-i", raw, "-af", af,
         "-ar", str(OUT_SR), "-ac", "1", "-c:a", "pcm_s16le", str(out_wav)],
        capture_output=True,
    )
    os.unlink(raw)
    with wave.open(str(out_wav)) as h:
        dur = h.getnframes() / h.getframerate()
    return dur, peak


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--device", type=int, default=None)
    ap.add_argument("--out", default=str(Path.home() / "careline-ft/recorded"))
    ap.add_argument("--prompts", default=str(Path(__file__).parent / "voice_corpus/prompts.txt"))
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--no-loudnorm", action="store_true")
    a = ap.parse_args()

    import numpy as np
    import sounddevice as sd

    if a.list:
        for i, d in enumerate(sd.query_devices()):
            if d["max_input_channels"] > 0:
                print(f"[{i}] {d['name']}  sr={int(d['default_samplerate'])}")
        return 0

    prompts = load_prompts(Path(a.prompts))
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)

    todo = [(i, t) for i, t in enumerate(prompts)
            if not (out / f"{prompt_id(i, t)}.wav").exists()]
    done = len(prompts) - len(todo)

    def total_minutes() -> float:
        s = 0.0
        for w in out.glob("*.wav"):
            with wave.open(str(w)) as h:
                s += h.getnframes() / h.getframerate()
        return s / 60

    print(f"corpus: {len(prompts)} prompts | already recorded: {done} | "
          f"captured so far: {total_minutes():.1f} min")
    print(f"output: {out}")
    print("ENTER = start, ENTER = stop, then [ENTER]=keep  r=retake  s=skip  q=quit\n")

    for n, (i, text) in enumerate(todo, 1):
        pid = prompt_id(i, text)
        while True:
            print(f"[{n}/{len(todo)}]  {text}")
            try:
                input("      ENTER to record... ")
            except EOFError:
                print("\nnon-interactive stdin; run this in your own terminal.")
                return 2
            q: queue.Queue = queue.Queue()

            def cb(indata, frames_, t_, status):
                q.put(indata.copy())

            frames = []
            with sd.InputStream(samplerate=REC_SR, channels=1, dtype="float32",
                                device=a.device, callback=cb):
                print("      ● recording — ENTER to stop", end="", flush=True)
                input()
                while not q.empty():
                    frames.append(q.get())
            if not frames:
                print("      nothing captured; retrying\n")
                continue

            wav = out / f"{pid}.wav"
            dur, peak = save(frames, wav, not a.no_loudnorm)
            warn = []
            if dur < MIN_S:
                warn.append(f"very short ({dur:.1f}s)")
            if dur > MAX_S:
                warn.append(f"long ({dur:.1f}s) — will be dropped by the 6s training cap")
            if peak < 0.02:
                warn.append(f"almost silent (peak {peak:.3f}) — check the mic")
            if peak > 0.99:
                warn.append("clipped at the input — lower gain")
            print(f"      saved {dur:.1f}s peak={peak:.2f}" + ("  ⚠ " + "; ".join(warn) if warn else ""))

            choice = input("      [ENTER]=keep  r=retake  s=skip  q=quit: ").strip().lower()
            if choice == "r":
                wav.unlink(missing_ok=True)
                print()
                continue
            if choice == "s":
                wav.unlink(missing_ok=True)
                break
            if choice == "q":
                wav.unlink(missing_ok=True)
                print(f"\nstopped. captured {total_minutes():.1f} min across "
                      f"{len(list(out.glob('*.wav')))} clips -> {out}")
                return 0
            # transcript is exact because it is the prompt that was read
            (out / f"{pid}.normalized.txt").write_text(text + "\n")
            print()
            break

    print(f"\ndone. {len(list(out.glob('*.wav')))} clips, {total_minutes():.1f} min -> {out}")
    print("next: mix with the mined set and fine-tune, e.g.")
    print(f"  CARELINE_FT_DATA={out} python scripts/finetune_guarded.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
