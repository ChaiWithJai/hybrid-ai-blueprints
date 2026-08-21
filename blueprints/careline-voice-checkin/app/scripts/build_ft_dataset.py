#!/usr/bin/env python3
"""Build the single-speaker fine-tune dataset, resumably.

Emits the contract f5_tts_mlx's loader expects:
    OUT/<id>.wav              24 kHz mono, <= MAX_DUR seconds
    OUT/<id>.normalized.txt   exact transcript of that wav

Two hard lessons are encoded here:

  * PERSISTENCE. An earlier build wrote 620 pairs (73.6 min) plus ~26 minutes of
    27B labelling into the session scratchpad under /private/tmp. A reboot
    cleared it and all of it had to be redone. Default output is therefore
    OUTSIDE /tmp, and every step skips work already on disk so an interruption
    costs one utterance, not the whole set.
  * DURATION CAP. The loader silently DROPS samples longer than max_duration,
    so a dataset of 10 s clips trained on nothing while looking fine. Segments
    are cut below the cap here and the contract is verified at the end.

Transcripts come from the running server's Whisper (/api/stt) so they match the
model the app itself uses.
"""
from __future__ import annotations

import collections
import json
import os
import subprocess
import sys
import urllib.request
import wave
from pathlib import Path

RUNS = Path(os.environ.get("CARELINE_FT_RUNS", Path.home() / "careline-ft/utts.tsv"))
OUT = Path(os.environ.get("CARELINE_FT_OUT", Path.home() / "careline-ft/data"))
SRC = Path(os.environ.get("CARELINE_FT_SRC", Path.home() / "Downloads"))
BASE = os.environ.get("CARELINE_BASE_URL", "http://127.0.0.1:8100")
TARGET = int(os.environ.get("CARELINE_FT_TARGET", "620"))
PER_REC = int(os.environ.get("CARELINE_FT_PER_REC", "140"))
MAX_DUR = float(os.environ.get("CARELINE_FT_MAX_DUR", "6"))


def stt(path: Path) -> str:
    req = urllib.request.Request(
        f"{BASE}/api/stt", data=path.read_bytes(),
        headers={"Content-Type": "audio/wav"},
    )
    with urllib.request.urlopen(req, timeout=600) as r:
        return (json.load(r).get("text") or "").strip()


def main() -> int:
    if not RUNS.exists():
        print(f"missing {RUNS}: run the silencedetect scan first")
        return 2
    OUT.mkdir(parents=True, exist_ok=True)

    rows = [l.split("\t") for l in RUNS.read_text().splitlines() if l.strip()]
    rows.sort(key=lambda r: -float(r[2]))          # longest first: more content per sample
    per: collections.Counter = collections.Counter()
    picked = []
    for f, st, du in rows:
        if per[f] >= PER_REC or float(du) > MAX_DUR:
            continue
        per[f] += 1
        picked.append((f, float(st), float(du)))
        if len(picked) >= TARGET:
            break

    made = skipped = dropped = 0
    for i, (f, st, du) in enumerate(picked):
        tag = (f.replace("the-new-business-school_--", "").replace("-2026-restream.m4a", "")
                .replace("writing-something-worth-reading", "writing")
                .replace("intro-to-ai-agents-for-business-formation", "introai"))
        wav = OUT / f"u{i:04d}_{tag}.wav"
        txt = wav.with_suffix(".normalized.txt")
        if wav.exists() and txt.exists() and txt.stat().st_size > 0:
            skipped += 1
            continue
        subprocess.run(
            ["ffmpeg", "-hide_banner", "-y", "-ss", f"{st}", "-t", f"{du}",
             "-i", str(SRC / f), "-af", "loudnorm=I=-20:TP=-3:LRA=11",
             "-ar", "24000", "-ac", "1", "-c:a", "pcm_s16le", str(wav)],
            capture_output=True,
        )
        if not wav.exists():
            dropped += 1
            continue
        try:
            text = stt(wav)
        except Exception as exc:
            print(f"  stt failed on {wav.name}: {exc}")
            wav.unlink(missing_ok=True)
            dropped += 1
            continue
        # An empty/degenerate transcript would train on a text/audio mismatch.
        if len(text.split()) < 3:
            wav.unlink(missing_ok=True)
            dropped += 1
            continue
        txt.write_text(text + "\n")
        made += 1
        if made % 50 == 0:
            print(f"  built {made} (skipped {skipped}, dropped {dropped})", flush=True)

    # verify the contract rather than trusting it
    pairs = [w for w in sorted(OUT.glob("*.wav")) if w.with_suffix(".normalized.txt").exists()]
    bad, total_s = 0, 0.0
    for w in pairs:
        with wave.open(str(w), "rb") as h:
            d = h.getnframes() / h.getframerate()
            total_s += d
            if h.getframerate() != 24000 or h.getnchannels() != 1 or d > MAX_DUR + 0.05:
                bad += 1
    print(f"\npairs={len(pairs)} audio={total_s/60:.1f}min built={made} skipped={skipped} "
          f"dropped={dropped} contract_violations={bad}")
    print(f"dataset: {OUT}")
    return 1 if bad or not pairs else 0


if __name__ == "__main__":
    raise SystemExit(main())
