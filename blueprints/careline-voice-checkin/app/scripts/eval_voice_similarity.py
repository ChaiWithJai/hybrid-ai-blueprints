#!/usr/bin/env python3
"""Score synthesized speech against the speaker, with interpretable controls.

Usage:
  eval_voice_similarity.py ANCHOR_DIR CLIP [CLIP ...]

A raw cosine is meaningless on its own, so two controls are computed:

  BAND   - leave-one-out similarity among held-out real clips of the speaker.
           This is the speaker's own session-to-session variance. A clone inside
           the band is indistinguishable from a real recording BY THIS METRIC.
  Scoring ABOVE the band is not superhuman fidelity: it means the clone is
  copying the reference clip's channel (mic/room/codec), which speaker
  embeddings are sensitive to. Treat it as channel overfitting, not identity.

Identity is also NOT the whole story: CSM matched F5 on this metric while
sounding markedly worse, because what it degraded was prosody (it compressed
the pitch range ~32%). Use this alongside listening, never instead of it.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
from resemblyzer import VoiceEncoder, preprocess_wav

if len(sys.argv) < 3:
    print(__doc__)
    raise SystemExit(2)

anchor_dir = Path(sys.argv[1])
clips = [Path(p) for p in sys.argv[2:]]
anchors = sorted(anchor_dir.glob("*.wav"))
if len(anchors) < 3:
    print(f"need >=3 anchor clips in {anchor_dir}, found {len(anchors)}")
    raise SystemExit(2)

enc = VoiceEncoder(verbose=False)
emb = lambda p: enc.embed_utterance(preprocess_wav(p))

aes = [emb(p) for p in anchors]
cen = np.mean(aes, axis=0)
cen /= np.linalg.norm(cen)

loo = []
for i, a in enumerate(aes):
    o = np.mean([x for j, x in enumerate(aes) if j != i], axis=0)
    o /= np.linalg.norm(o)
    loo.append(float(np.dot(a, o)))
lo, hi = min(loo), max(loo)

print(f"anchors ({len(anchors)} held-out recordings): {', '.join(p.stem for p in anchors)}")
print(f"SPEAKER BAND (leave-one-out): {lo:.3f} .. {hi:.3f}\n")
print(f"{'clip':44s} {'cosine':>7s}  verdict")
print("-" * 74)
rows = []
for c in clips:
    if not c.exists():
        print(f"{c.name[:44]:44s} {'--':>7s}  MISSING")
        continue
    s = float(np.dot(cen, emb(c)))
    if s > hi:
        v = "above band (channel overfit to reference)"
    elif s >= lo:
        v = "IN BAND (indistinguishable by this metric)"
    else:
        v = f"below band by {lo - s:.3f}"
    rows.append((c.name, s))
    print(f"{c.name[:44]:44s} {s:7.3f}  {v}")

if rows:
    vals = np.array([s for _, s in rows])
    print(f"\nn={len(vals)} mean={vals.mean():.3f} sd={vals.std(ddof=1) if len(vals)>1 else 0:.3f} "
          f"min={vals.min():.3f} max={vals.max():.3f}")
