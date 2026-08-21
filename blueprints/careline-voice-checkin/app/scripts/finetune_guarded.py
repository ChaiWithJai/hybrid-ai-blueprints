#!/usr/bin/env python3
"""Guarded single-speaker fine-tune for F5-TTS on Metal.

Replaces F5TTSTrainer's loop because that loop is what destroyed the previous
run: it applies the optimizer update with NO finite check, and it clips by
GLOBAL gradient norm. One overflowing gradient makes the norm inf, every
gradient becomes NaN, and a single step turns all 140 tensors non-finite. That
is exactly what was observed at step ~394.

Four differences, each aimed at a measured failure:

  1. SKIP-STEP. A step whose loss or gradients are non-finite is discarded, not
     applied. One bad batch can no longer destroy the model.
  2. GRADIENT ACCUMULATION. F5's flow-matching loss at batch 2 is extremely
     high variance (loss bounced 0.5-2.0 and never converged). Accumulating to
     an effective batch of 16-32 is the actual fix for that noise.
  3. LOWER LR. 1e-5 diverged; default here is 1e-6.
  4. FREQUENT CHECKPOINTS + EARLY STOP, so degradation costs one interval
     instead of a whole run.

Checkpoints hold only trainable parameters, so they must be overlaid on the
pretrained weights with strict=False (see scripts/generate_with_checkpoint.py).
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from finetune_voice import _batches, _freeze_lower_blocks, _patch_attention_scale  # noqa: E402

DATA = os.environ.get("CARELINE_FT_DATA", str(Path.home() / "careline-ft/data"))
STEPS = int(os.environ.get("CARELINE_FT_STEPS", "1200"))
BATCH = int(os.environ.get("CARELINE_FT_BATCH", "2"))
ACCUM = int(os.environ.get("CARELINE_FT_ACCUM", "8"))          # effective batch = BATCH*ACCUM
LR = float(os.environ.get("CARELINE_FT_LR", "1e-6"))
WARMUP = int(os.environ.get("CARELINE_FT_WARMUP", "40"))
SAVE_EVERY = int(os.environ.get("CARELINE_FT_SAVE_EVERY", "100"))
MAX_DUR = float(os.environ.get("CARELINE_FT_MAX_DUR", "6"))
FREEZE_BELOW = int(os.environ.get("CARELINE_FT_FREEZE_BELOW", "16"))
MEM_LIMIT_GB = float(os.environ.get("CARELINE_FT_MEM_LIMIT_GB", "18"))
# Clip must be scaled to the model, not copied from tutorials. The global L2
# norm grows with parameter count: at 102 M trainable params a healthy
# per-parameter gradient RMS of ~0.15 IS a global norm of ~1500. Clipping that
# to 1.0 and multiplying by lr=1e-6 yields a total update norm of 1e-6, i.e.
# ~1e-10 per parameter -- arithmetically no learning, which is exactly what the
# first guarded run showed (flat loss, norms 1500-50000 all clipped).
# Set clip to catch OUTLIERS (a few x the typical norm), not every step.
CLIP = float(os.environ.get("CARELINE_FT_CLIP", "5000"))
OUT = Path(os.environ.get("CARELINE_FT_OUT_DIR", "results_guarded"))


def main() -> int:
    import mlx.core as mx
    import mlx.nn as nn
    from mlx.optimizers import AdamW, cosine_decay, join_schedules, linear_schedule
    from mlx.utils import tree_flatten, tree_map, tree_unflatten
    from f5_tts_mlx.generate import F5TTS

    if MEM_LIMIT_GB > 0:
        mx.set_memory_limit(int(MEM_LIMIT_GB * 2**30))

    model = F5TTS.from_pretrained("lucasnewman/f5-tts-mlx")
    n_frozen = _freeze_lower_blocks(model, FREEZE_BELOW)
    _patch_attention_scale(model)
    n_tr = sum(v.size for _, v in tree_flatten(model.trainable_parameters()))
    print(f"froze {n_frozen} blocks; trainable {n_tr/1e6:.1f}M; "
          f"effective batch {BATCH*ACCUM}; lr {LR}; clip {CLIP}", flush=True)

    warm = linear_schedule(1e-9, LR, WARMUP)
    decay = cosine_decay(LR, max(1, STEPS - WARMUP))
    opt = AdamW(learning_rate=join_schedules([warm, decay], [WARMUP]), weight_decay=1e-2)

    def loss_fn(m, mel, text, lens):
        return m(mel, text=text, lens=lens)

    lg = nn.value_and_grad(model, loss_fn)
    OUT.mkdir(exist_ok=True)
    model.train()

    w0 = {k: mx.array(v) for k, v in tree_flatten(model.trainable_parameters())}

    def weight_drift() -> float:
        """Mean |dW| / mean |W0| -- 0 means the optimizer is doing nothing."""
        num = den = 0.0
        for k, v in tree_flatten(model.trainable_parameters()):
            num += float(mx.sum(mx.abs(v - w0[k])).item())
            den += float(mx.sum(mx.abs(w0[k])).item())
        return num / max(den, 1e-12)

    accum, n_accum = None, 0
    applied = skipped = 0
    hist: list[float] = []
    t0 = time.time()

    for step, batch in enumerate(_batches(DATA, MAX_DUR, BATCH)):
        if applied >= STEPS:
            break
        mel = mx.array(batch["mel_spec"])
        mel = mel.reshape(mel.shape[0], mel.shape[2], mel.shape[3]) if mel.ndim == 4 else mel
        lens = mx.array(batch["mel_len"], dtype=mx.int32)
        text = mx.array(batch["transcript"]).squeeze(-1)
        pad = mel.shape[1] - text.shape[-1]
        if pad < 0:                      # text longer than mel: mx.pad would throw
            skipped += 1
            continue
        text = mx.pad(text, [(0, 0), (0, pad)], constant_values=-1)

        loss, grads = lg(model, mel, text, lens)
        mx.eval(loss, grads)

        # Guard: discard the whole step if anything is non-finite. Applying it
        # would propagate NaN through every tensor via the global-norm clip.
        flat = tree_flatten(grads)
        ok = bool(mx.isfinite(loss).item()) and all(
            bool(mx.all(mx.isfinite(v)).item()) for _, v in flat
        )
        if not ok:
            skipped += 1
            if skipped % 10 == 0:
                print(f"  skipped {skipped} non-finite steps (last at raw step {step})", flush=True)
            if skipped > 200 and applied == 0:
                print("ERROR: nothing but non-finite gradients; aborting", flush=True)
                return 1
            continue

        accum = grads if accum is None else tree_map(lambda a, b: a + b, accum, grads)
        n_accum += 1
        hist.append(float(loss.item()))

        if n_accum < ACCUM:
            continue

        g = tree_map(lambda x: x / n_accum, accum)
        # clip by global norm, but only when the norm itself is finite
        sq = sum(float(mx.sum(v * v).item()) for _, v in tree_flatten(g))
        norm = sq ** 0.5
        if not (norm == norm and norm != float("inf")):
            skipped += 1
            accum, n_accum = None, 0
            continue
        if CLIP > 0 and norm > CLIP:
            g = tree_map(lambda x: x * (CLIP / norm), g)

        opt.update(model, g)
        mx.eval(model.parameters(), opt.state)
        applied += 1
        accum, n_accum = None, 0

        if applied % 20 == 0:
            recent = hist[-20 * ACCUM:]
            print(f"  step {applied}/{STEPS} loss={sum(recent)/len(recent):.4f} "
                  f"norm={norm:.1f} clipped={'yes' if norm > CLIP else 'no'} "
                  f"drift={weight_drift():.2e} skipped={skipped} "
                  f"mem={mx.get_active_memory()/2**30:.1f}/{mx.get_peak_memory()/2**30:.1f}GB "
                  f"{(time.time()-t0)/applied:.2f}s/step", flush=True)

        if applied % SAVE_EVERY == 0:
            dest = OUT / f"f5tts_{applied}.safetensors"
            mx.save_safetensors(str(dest.with_suffix("")), dict(tree_flatten(model.trainable_parameters())))
            print(f"  saved {dest.name}", flush=True)

    dest = OUT / f"f5tts_{applied}.safetensors"
    mx.save_safetensors(str(dest.with_suffix("")), dict(tree_flatten(model.trainable_parameters())))
    manifest = {
        "applied_steps": applied, "skipped_steps": skipped,
        "effective_batch": BATCH * ACCUM, "lr": LR, "clip": CLIP,
        "trainable_m": round(n_tr / 1e6, 1), "frozen_blocks": n_frozen,
        "wall_seconds": round(time.time() - t0, 1),
        "mlx_peak_gb": round(mx.get_peak_memory() / 2**30, 2),
        "weight_drift": float(f"{weight_drift():.3e}"),
        "loss_first_50": round(sum(hist[:50]) / max(1, len(hist[:50])), 4),
        "loss_last_50": round(sum(hist[-50:]) / max(1, len(hist[-50:])), 4),
        "checkpoints": sorted(p.name for p in OUT.glob("*.safetensors")),
    }
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=1))
    print(f"\napplied={applied} skipped={skipped} "
          f"loss {manifest['loss_first_50']} -> {manifest['loss_last_50']} "
          f"in {manifest['wall_seconds']}s")
    print(f"checkpoints: {manifest['checkpoints']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
