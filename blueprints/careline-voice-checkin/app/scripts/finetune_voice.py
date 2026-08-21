#!/usr/bin/env python3
"""Fine-tune F5-TTS on one speaker, on Apple Metal via MLX.

Why this exists: zero-shot cloning already reproduces speaker IDENTITY at the
ceiling (speaker-embedding cosine lands inside the speaker's own
session-to-session band). What zero-shot does not fix is naturalness/prosody.
Fine-tuning is the only remaining lever, and it is the one place where "bias
toward more examples" is meaningful -- zero-shot conditions on a single
reference clip, so concatenating clips there measurably did nothing.

Dataset contract (from f5_tts_mlx.data.load_dir):
  DATA_DIR/<id>.wav              24 kHz mono, <= MAX_DURATION seconds
  DATA_DIR/<id>.normalized.txt   the exact transcript of that wav

Checkpoints land in ./results/f5tts_<step>.safetensors (the trainer hardcodes
that path) and hold trainable_parameters() only.

Evaluate with scripts/verify_voice.py plus the speaker-similarity harness --
never by ear alone, and never by training loss alone: loss going down does not
prove the voice got closer.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

DATA_DIR = os.environ.get("CARELINE_FT_DATA", "")
STEPS = int(os.environ.get("CARELINE_FT_STEPS", "600"))
BATCH = int(os.environ.get("CARELINE_FT_BATCH", "2"))
LR = float(os.environ.get("CARELINE_FT_LR", "1e-5"))
WARMUP = int(os.environ.get("CARELINE_FT_WARMUP", "25"))
SAVE_EVERY = int(os.environ.get("CARELINE_FT_SAVE_EVERY", "100"))
SAMPLE_EVERY = int(os.environ.get("CARELINE_FT_SAMPLE_EVERY", "300"))
MAX_DURATION = float(os.environ.get("CARELINE_FT_MAX_DUR", "6"))
# Cap MLX so an over-large config raises instead of taking the whole machine
# down. This box has ZERO swap (vm.swapusage total = 0), so an overcommit is an
# immediate kill, not a slowdown.
MEM_LIMIT_GB = float(os.environ.get("CARELINE_FT_MEM_LIMIT_GB", "18"))
FREEZE_BELOW = int(os.environ.get("CARELINE_FT_FREEZE_BELOW", "16"))
VOICES = Path(__file__).resolve().parent.parent / "voices"


def _patch_attention_scale(model) -> int:
    """Make attention `scale` a Python float so autograd can trace the model.

    dit.py sets `self._scale_factor = 1 / mx.sqrt(dim_head)` -- an mlx array --
    and passes it to mx.fast.scaled_dot_product_attention, whose signature wants
    `scale: float`. At inference a concrete 0-d array converts implicitly and
    nobody notices. Under nn.value_and_grad the same value is a TRACER with no
    concrete value, the implicit conversion fails, and training dies with
    "incompatible function arguments". Hence: inference works, training does not.

    Patched on the instance rather than in site-packages, so `uv sync` cannot
    silently revert it.
    """
    import mlx.core as mx

    patched = 0
    seen = set()

    def walk(m):
        nonlocal patched
        if id(m) in seen:
            return
        seen.add(id(m))
        sf = getattr(m, "_scale_factor", None)
        if isinstance(sf, mx.array):
            m._scale_factor = float(sf.item())
            patched += 1
        children = getattr(m, "children", None)
        if callable(children):
            for v in children().values():
                if isinstance(v, (list, tuple)):
                    for c in v:
                        walk(c)
                elif hasattr(v, "children") or hasattr(v, "_scale_factor"):
                    walk(v)

    walk(model)
    return patched


def _freeze_lower_blocks(model, freeze_below: int) -> int:
    """Freeze the lower transformer blocks; train only the top ones.

    Two reasons, one of which is a hard constraint:

      * MEMORY. Gradients and the AdamW moments are allocated per TRAINABLE
        parameter, so a full 337 M-param fine-tune costs 1.26 GB grads +
        2.51 GB moments on top of the weights -- 5.02 GB before a single
        activation. Freezing most blocks scales that down proportionally.
      * FIT. 73 minutes of one speaker is a small dataset. Updating all 22
        blocks invites overfitting and catastrophic forgetting of general
        prosody; adapting the upper blocks is the usual speaker-adaptation
        shape.

    Returns the number of blocks frozen (0 if the structure was not found, so
    the caller can warn rather than silently full-fine-tune).
    """
    blocks = getattr(getattr(model, "transformer", None), "transformer_blocks", None)
    if blocks is None:
        return 0
    n = 0
    for i, blk in enumerate(blocks):
        if i < freeze_below and hasattr(blk, "freeze"):
            blk.freeze(recurse=True)
            n += 1
    return n


def _batches(data_dir: str, max_duration: float, batch_size: int):
    """Yield training batches, working around two upstream defects.

    f5_tts_mlx.data.load_dir cannot be used as shipped:

      1. Its `_to_mel_spec` stores an *mlx* array back into the mlx.data sample.
         mlx.data's batching then calls to_array on it and dies with
         "Contiguous buffer expected". So the mel is stored as contiguous numpy
         here instead.
      2. The trainer calls mx.array(batch[...]) on whatever the iterable yields,
         so every batch value is made contiguous numpy before it is handed over.

    The trainer only iterates `train_dataset`, so a plain generator is a valid
    substitute for an mlx.data stream.
    """
    from functools import partial

    import mlx.core as mx
    import mlx.data as dx
    import numpy as np
    from f5_tts_mlx.audio import log_mel_spectrogram
    from f5_tts_mlx.data import _load_audio_file, _load_transcript, files_with_extensions

    def to_mel(sample):
        audio = mx.squeeze(mx.array(np.ascontiguousarray(sample["audio"])), axis=-1)
        mel = log_mel_spectrogram(audio)
        mx.eval(mel)
        sample["mel_spec"] = np.ascontiguousarray(np.array(mel))
        # Scalar per sample: batching must give lens of shape (b,), not (b, 1).
        # A trailing dim here makes the model's einx expression fail with
        # RankError ("b 1" vs "b").
        sample["mel_len"] = np.int32(mel.shape[1])
        return sample

    files = files_with_extensions(Path(data_dir).expanduser())
    stream = (
        dx.buffer_from_vector(files)
        .to_stream()
        .sample_transform(lambda s: s if bytes(s["file"]).endswith(b".wav") else dict())
        .sample_transform(_load_transcript)
        .sample_transform(partial(_load_audio_file, max_duration=max_duration))
        .load_audio("audio", from_memory=True)
        .sample_transform(to_mel)
        # One epoch over a single-speaker set is far fewer steps than a
        # fine-tune needs, so repeat indefinitely and let total_steps decide.
        .repeat(1_000_000)
        .batch(batch_size)
        # NO .prefetch(): prefetch runs sample_transforms on worker threads, and
        # to_mel calls MLX. MLX GPU streams are bound to the thread that created
        # them, so a worker thread aborts the process with "There is no
        # Stream(gpu, N) in current thread" (same hazard _SingleThreadMlx guards
        # against in careline/tts.py). Throughput is not the bottleneck here.
    )
    for batch in stream:
        out = {}
        for k, v in batch.items():
            if hasattr(v, "shape"):
                v = np.ascontiguousarray(v)
                if k == "mel_len":
                    v = v.reshape(-1)  # (b,), never (b, 1)
            out[k] = v
        yield out


def main() -> int:
    if not DATA_DIR:
        print("set CARELINE_FT_DATA to the dataset directory")
        return 2
    data = Path(DATA_DIR).expanduser()
    wavs = sorted(data.glob("*.wav"))
    pairs = [w for w in wavs if w.with_suffix(".normalized.txt").exists()]
    if not pairs:
        print(f"no <id>.wav + <id>.normalized.txt pairs in {data}")
        return 2

    import mlx.core as mx
    from f5_tts_mlx.generate import F5TTS
    from f5_tts_mlx.trainer import F5TTSTrainer

    total_s = 0.0
    import wave as _w

    for p in pairs:
        with _w.open(str(p), "rb") as f:
            total_s += f.getnframes() / f.getframerate()
    print(f"dataset: {len(pairs)} pairs, {total_s / 60:.1f} min of audio, {data}")
    print(f"config : steps={STEPS} batch={BATCH} lr={LR} warmup={WARMUP}")

    dset = _batches(str(data), MAX_DURATION, BATCH)

    print("loading pretrained weights (fine-tune starts from these, not scratch)")
    model = F5TTS.from_pretrained("lucasnewman/f5-tts-mlx")
    if MEM_LIMIT_GB > 0 and hasattr(mx, "set_memory_limit"):
        mx.set_memory_limit(int(MEM_LIMIT_GB * 2**30))
        print(f"mlx memory limit: {MEM_LIMIT_GB:.0f} GB (raises instead of OOM-killing the host)")
    n_frozen = _freeze_lower_blocks(model, FREEZE_BELOW)
    n_patched = _patch_attention_scale(model)
    from mlx.utils import tree_flatten

    n_all = sum(v.size for _, v in tree_flatten(model.parameters()))
    n_tr = sum(v.size for _, v in tree_flatten(model.trainable_parameters()))
    opt_gb = (n_all * 4 + n_tr * 4 + n_tr * 8) / 2**30
    print(f"froze {n_frozen} lower block(s); trainable {n_tr/1e6:.1f}M / {n_all/1e6:.1f}M "
          f"-> optimizer floor {opt_gb:.2f} GB")
    if n_frozen == 0:
        print("  WARNING: nothing frozen -- full fine-tune, ~5 GB optimizer floor")
    print(f"patched attention scale on {n_patched} module(s) for autograd")
    if n_patched == 0:
        print("  WARNING: none patched -- if training dies in "
              "scaled_dot_product_attention, the module walk missed them")
    trainer = F5TTSTrainer(model, num_warmup_steps=WARMUP, log_with_wandb=False)

    ref_wav = VOICES / "self_ref.wav"
    ref_txt = VOICES / "self_ref.txt"
    sample_kwargs = {}
    if ref_wav.exists() and ref_txt.exists():
        sample_kwargs = dict(
            sample_reference_audio=str(ref_wav),
            sample_reference_text=ref_txt.read_text().strip(),
            sample_generation_text="Hey, I just wanted to check in and see how you are doing today.",
        )

    manifest = {
        "dataset_dir": str(data),
        "pairs": len(pairs),
        "audio_minutes": round(total_s / 60, 2),
        "steps": STEPS,
        "batch": BATCH,
        "learning_rate": LR,
        "warmup": WARMUP,
        "base_model": "lucasnewman/f5-tts-mlx",
        "started": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    Path("results").mkdir(exist_ok=True)
    Path("results/finetune_manifest.json").write_text(json.dumps(manifest, indent=1))

    t0 = time.time()
    trainer.train(
        dset,
        learning_rate=LR,
        total_steps=STEPS,
        save_every=SAVE_EVERY,
        sample_every=SAMPLE_EVERY,
        **sample_kwargs,
    )
    manifest["finished"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    manifest["wall_seconds"] = round(time.time() - t0, 1)
    manifest["checkpoints"] = sorted(p.name for p in Path("results").glob("f5tts_*.safetensors"))
    Path("results/finetune_manifest.json").write_text(json.dumps(manifest, indent=1))
    print(f"\ndone in {manifest['wall_seconds']}s; checkpoints: {manifest['checkpoints']}")
    mx.eval()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
