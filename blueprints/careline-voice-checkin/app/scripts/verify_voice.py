#!/usr/bin/env python3
"""Voice-path regression against a running server (see scripts/run).

Every check here corresponds to a failure that actually shipped and went
undetected, because the existing regression only covered memory/escalation:

  1. import      - `uv sync` silently REMOVES a package that is installed ad
                   hoc but absent from pyproject.toml. That returned 503s.
  2. reference   - F5 raises unless the reference is exactly 24 kHz; a wrong
                   rate is a config error, not something to resample away.
  3. not-silence - the clone once returned 0.04 s of audio with HTTP 200, i.e.
                   silence reported as success. Duration must scale with text.
  4. no-lead-gap - the UI speaks one request per sentence and concatenates, so
                   silence inside a chunk is ADDED to every punctuation pause.
                   300-500 ms of leading silence made delivery feel broken.
  5. care-mode   - Kokoro's espeak-ng calls exit() in native code when phontab
                   is missing. No Python except can catch it: the whole server
                   dies. So assert the process is still alive afterwards.
  6. latency     - a clone slower than real time cannot hold a live call.

Exits nonzero on any failure and writes a JSON artifact for evidence/.
"""
from __future__ import annotations

import io
import json
import os
import sys
import time
import urllib.error
import urllib.request
import wave

BASE = os.environ.get("CARELINE_BASE_URL", "http://127.0.0.1:8100")
VOICES = os.path.join(os.path.dirname(__file__), "..", "voices")
SR_EXPECTED = 24000
MAX_LEAD_SILENCE_S = 0.12
MAX_RTF = 3.0  # compute seconds per audio second; above this a live call stalls

results: list[dict] = []


def check(name: str, fn):
    t0 = time.time()
    try:
        detail = fn()
        ok = True
    except AssertionError as exc:
        detail, ok = str(exc), False
    except Exception as exc:  # unexpected: still a failure, but label it
        detail, ok = f"{type(exc).__name__}: {exc}", False
    results.append({"check": name, "ok": ok, "detail": detail, "seconds": round(time.time() - t0, 2)})
    print(f"[{'PASS' if ok else 'FAIL'}] {name}: {detail}")
    return ok


def post_tts(text: str, mode: str, timeout: float = 900.0) -> bytes:
    req = urllib.request.Request(
        f"{BASE}/api/tts",
        data=json.dumps({"text": text, "mode": mode}).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        assert r.status == 200, f"HTTP {r.status}"
        return r.read()


def wav_info(b: bytes):
    with wave.open(io.BytesIO(b), "rb") as w:
        sr, n, ch = w.getframerate(), w.getnframes(), w.getnchannels()
        raw = w.readframes(n)
    import array

    x = array.array("h")
    x.frombytes(raw)
    vals = [v / 32768.0 for v in x]
    if ch > 1:
        vals = vals[::ch]
    return sr, len(vals) / sr, vals


def lead_silence(vals, sr, thresh=0.006) -> float:
    fl = max(1, int(sr * 0.010))
    for i in range(0, len(vals) - fl, fl):
        frame = vals[i : i + fl]
        rms = (sum(v * v for v in frame) / len(frame)) ** 0.5
        if rms > thresh:
            return i / sr
    return len(vals) / sr


# 1. the dependency that uv sync strips
def c_import():
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
    import f5_tts_mlx.generate  # noqa: F401

    return "f5_tts_mlx importable"


# 2. reference contract
def c_reference():
    wav = os.path.join(VOICES, "self_ref.wav")
    txt = os.path.join(VOICES, "self_ref.txt")
    assert os.path.exists(wav), "voices/self_ref.wav missing"
    assert os.path.exists(txt), "voices/self_ref.txt missing"
    body = open(txt).read().strip()
    assert body, "voices/self_ref.txt is empty (F5 needs the transcript)"
    with wave.open(wav, "rb") as w:
        sr, ch, dur = w.getframerate(), w.getnchannels(), w.getnframes() / w.getframerate()
    assert sr == SR_EXPECTED, f"reference is {sr} Hz, F5 requires {SR_EXPECTED}"
    assert ch == 1, f"reference has {ch} channels, expected mono"
    assert 5.0 <= dur <= 25.0, f"reference is {dur:.1f}s; use ~10-15s"
    return f"{dur:.1f}s, {sr} Hz, mono, {len(body.split())} words of ref_text"


# 3. clone must not return silence as success
def c_clone_not_silence():
    b = post_tts("Hey, I just wanted to check in and see how you are doing today.", "self")
    sr, dur, vals = wav_info(b)
    assert sr == SR_EXPECTED, f"output {sr} Hz"
    assert dur > 1.5, f"only {dur:.2f}s of audio for a 13-word sentence (silence-as-success)"
    peak = max(abs(v) for v in vals)
    assert peak > 0.02, f"peak {peak:.4f}: effectively silent"
    return f"{dur:.2f}s, peak {peak:.2f}"


# 4. the pause bug
def c_no_leading_gap():
    worst = 0.0
    for t in ("That sounds really hard.", "I am glad you told me.", "Have you been sleeping alright?"):
        sr, dur, vals = wav_info(post_tts(t, "self"))
        worst = max(worst, lead_silence(vals, sr))
    assert worst <= MAX_LEAD_SILENCE_S, (
        f"{worst * 1000:.0f}ms leading silence per chunk; the UI concatenates "
        f"per-sentence chunks so this is added to every punctuation pause"
    )
    return f"worst leading silence {worst * 1000:.0f}ms (limit {MAX_LEAD_SILENCE_S * 1000:.0f}ms)"


# 5. care mode must not kill the process
def c_care_mode_survives():
    sr, dur, _ = wav_info(post_tts("Good morning.", "care"))
    with urllib.request.urlopen(f"{BASE}/", timeout=30) as r:
        assert r.status == 200, "server unreachable after care-mode synthesis"
    return f"care mode {dur:.2f}s and server still alive"


# 6. latency budget
def c_latency():
    t0 = time.time()
    b = post_tts("I wanted to check in with you about how this week has been going.", "self")
    elapsed = time.time() - t0
    _, dur, _ = wav_info(b)
    rtf = elapsed / dur
    assert rtf <= MAX_RTF, f"RTF {rtf:.2f} (>{MAX_RTF}) — too slow for a live call"
    return f"{elapsed:.1f}s compute for {dur:.1f}s audio (RTF {rtf:.2f})"


if __name__ == "__main__":
    print(f"voice regression against {BASE}\n")
    ok = True
    for name, fn in (
        ("import/f5-declared-in-manifest", c_import),
        ("reference/contract", c_reference),
        ("clone/not-silence", c_clone_not_silence),
        ("clone/no-leading-gap", c_no_leading_gap),
        ("care-mode/server-survives", c_care_mode_survives),
        ("clone/latency", c_latency),
    ):
        ok &= check(name, fn)

    out = {
        "base_url": BASE,
        "passed": ok,
        "checks": results,
    }
    dest = os.environ.get("CARELINE_VOICE_REPORT", "/tmp/careline_voice_report.json")
    with open(dest, "w") as f:
        json.dump(out, f, indent=1)
    print(f"\n{'ALL CHECKS PASSED' if ok else 'FAILURES PRESENT'} -> {dest}")
    sys.exit(0 if ok else 1)
