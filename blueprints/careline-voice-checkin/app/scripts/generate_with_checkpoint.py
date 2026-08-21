#!/usr/bin/env python3
"""Generate speech from a fine-tuned checkpoint, for A/B against zero-shot.

Usage:
  generate_with_checkpoint.py CKPT.safetensors REF.wav REF.txt OUT_DIR [SEEDS...]

The checkpoint holds ONLY trainable_parameters() -- 102 M of 337 M with the
lower blocks frozen. So it must be overlaid on the pretrained weights with
strict=False; a default strict load rejects a partial state dict, and loading
the file alone would leave the frozen 235 M uninitialized.

Prints how many tensors were applied: if that is 0, the run silently produced
pretrained output and any "improvement" would be noise.
"""
from __future__ import annotations

import sys
from pathlib import Path

import mlx.core as mx
import numpy as np
import soundfile as sf
from f5_tts_mlx.generate import (
    FRAMES_PER_SEC,
    SAMPLE_RATE,
    TARGET_RMS,
    F5TTS,
    convert_char_to_pinyin,
    estimated_duration,
)

ckpt, ref_wav, ref_txt, out_dir = sys.argv[1:5]
seeds = [int(s) for s in sys.argv[5:]] or [1, 2, 3, 4, 5]
TEXT = "Hey, I just wanted to check in and see how you are doing today."

model = F5TTS.from_pretrained("lucasnewman/f5-tts-mlx")

# Same autograd-era defect fix as training: scale must be a float, not an array.
def patch(m, seen=None):
    seen = seen if seen is not None else set()
    if id(m) in seen:
        return
    seen.add(id(m))
    sf_ = getattr(m, "_scale_factor", None)
    if isinstance(sf_, mx.array):
        m._scale_factor = float(sf_.item())
    ch = getattr(m, "children", None)
    if callable(ch):
        for v in ch().values():
            for c in (v if isinstance(v, (list, tuple)) else [v]):
                if hasattr(c, "children") or hasattr(c, "_scale_factor"):
                    patch(c, seen)

patch(model)

params = mx.load(ckpt)
model.load_weights(list(params.items()), strict=False)
model.eval()
print(f"applied {len(params)} tensors from {Path(ckpt).name} (strict=False overlay)")
if not params:
    print("  ERROR: checkpoint empty -- output would just be pretrained")
    raise SystemExit(1)

audio, sr = sf.read(ref_wav)
assert sr == SAMPLE_RATE, f"reference must be {SAMPLE_RATE} Hz, got {sr}"
audio = mx.array(audio)
rms = mx.sqrt(mx.mean(mx.square(audio)))
if rms < TARGET_RMS:
    audio = audio * TARGET_RMS / rms
ref_text = Path(ref_txt).read_text().strip()

Path(out_dir).mkdir(parents=True, exist_ok=True)
total_s = estimated_duration(audio, ref_text, TEXT)
for seed in seeds:
    wave, _ = model.sample(
        mx.expand_dims(audio, axis=0),
        text=convert_char_to_pinyin([ref_text + " " + TEXT]),
        duration=int(total_s * FRAMES_PER_SEC),
        steps=8, method="rk4", cfg_strength=2.0, sway_sampling_coef=-1.0, seed=seed,
    )
    wave = wave[audio.shape[0]:]
    mx.eval(wave)
    x = np.array(wave)
    if x.size < SAMPLE_RATE // 10:
        print(f"  seed {seed}: {x.size/SAMPLE_RATE:.3f}s -- refusing near-silence")
        continue
    dest = Path(out_dir) / f"ft_s{seed}.wav"
    sf.write(str(dest), x, SAMPLE_RATE, subtype="PCM_16")
    print(f"  seed {seed}: {x.size/SAMPLE_RATE:.2f}s -> {dest.name}")
