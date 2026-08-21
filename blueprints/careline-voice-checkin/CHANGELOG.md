# Changelog

## 0.3.0 — 2026-08-21

Cloned voice now ships fine-tuned weights, selected by listening test.

### Added
- **Fine-tuned clone checkpoint** (`app/voices/f5_finetuned.safetensors`), loaded
  as a `strict=False` overlay on the pretrained model since it holds only the
  trainable parameters. Delete it to fall back to zero-shot.
- `app/scripts/record_voice_corpus.py` + `scripts/voice_corpus/prompts.txt`:
  records a purpose-built corpus in the target register, with transcripts exact
  by construction (no ASR error, no mid-thought clips).
- `app/scripts/finetune_guarded.py`: training loop with skip-step on non-finite
  loss/gradients and gradient accumulation. The upstream trainer applies updates
  with no finite check and clips by global norm, so one `inf` gradient turns all
  140 tensors to NaN in a single step — 33% of raw steps produce non-finite
  gradients, so this is not a rare path.
- `app/scripts/eval_voice_similarity.py`, `generate_with_checkpoint.py`,
  `build_ft_dataset.py`.

### Findings
- **Recording 3.66 min of in-domain speech beat mining more archive audio.** The
  11.8 h on disk is all lecture delivery; the target is a warm check-in. Style
  match mattered more than volume.
- **Do not weight a minority dataset by duplicating files.** Copying each clip 6x
  produced gradient norms of 1.47e17 (vs 61,268 without), quality peaking near
  step 375 then decaying, and phoneme-level overfitting — the /aʊ/ in "how",
  present in 10% of prompts and multiplied by 6, regressed audibly by step 500.
  Weight by sampling instead.
- **Speaker-embedding cosine selected nothing.** It rated every checkpoint a tie
  and rated the winner a tie with zero-shot. It measures identity, which was
  already at ceiling; prosody was the gap and cosine is invariant to it. Keep it
  as a guardrail, decide by listening.
- Training saturates near 400 steps for this configuration; drift plateaus by
  ~720 and later steps contribute nothing measurable.

### Corrected
- Gradient spikes were first attributed to unfreezing more blocks. They recur at
  the original depth, so the cause is the duplicated data. Unfreezing only
  explained the memory change (9.9 -> 12.7 GB peak).

## 0.2.0 — 2026-08-21

Voice quality pass. The clone backend changed, two bugs that returned success
while broken were fixed, and the voice path gained a regression suite.

### Changed
- **"Call yourself" now uses F5-TTS via MLX instead of CSM-1B.** On the same
  reference and sentence both reproduced speaker identity equally (cosine 0.93
  vs 0.92, different-speaker floor 0.47), but CSM compressed the pitch range
  118 Hz → 80 Hz (−32 %), heard as monotone. F5 preserved it (130 Hz) and is
  ~3× faster (~5 s compute per ~4.6 s of audio). `CARELINE_CLONE_BACKEND=csm`
  switches back.
- Clone model preloads at startup, so the first spoken turn no longer pays the
  10 s+ cold load.
- Reference rebuilt from measurement rather than convenience: chosen by the
  fidelity of the clone it actually produced, cross-checked against transcript
  quality.

### Fixed
- **Long pause after every punctuation mark.** Each chunk carried 300–500 ms of
  leading silence; because the UI requests TTS per sentence and concatenates,
  that was added to every pause. Now trimmed (296–473 ms → 0 ms).
- **Care-mode synthesis killed the server process.** Kokoro's espeak-ng calls
  `exit()` in native code when its data files are missing — uncatchable from
  Python. `scripts/run` now exports `ESPEAK_DATA_PATH`; `scripts/preflight`
  fails loudly without a system `espeak-ng`.
- **Clone returned 0.04 s of silence with HTTP 200.** F5's `duration` is the
  *total* (reference + generated) in frames; left unset, the predictor returned
  ≈ the reference length. Now derived from `estimated_duration()`, and the
  backend refuses to return near-silence as success.
- `f5-tts-mlx` declared in `pyproject.toml` — installed ad hoc it was silently
  removed by `uv sync`, producing 503s.

### Added
- `app/scripts/verify_voice.py`, wired into `scripts/verify`: six checks, each
  for a failure that actually shipped (silence-as-200, per-chunk leading
  silence, server death on care mode, undeclared-dependency removal, reference
  contract, latency budget).
- `app/scripts/eval_voice_similarity.py`: speaker-embedding scoring with a
  leave-one-out speaker band and a different-speaker floor, so a similarity
  number is interpretable rather than decorative.
- `app/scripts/build_ft_dataset.py`: resumable, contract-verifying dataset
  builder for fine-tuning.
- `app/scripts/finetune_voice.py`: single-speaker fine-tuning on Metal.
  **Experimental and not currently a win** — similarity fell at 250 steps and
  training diverged to NaN at ~394. No fine-tuned checkpoint ships. Contains
  fixes for six defects that stop `f5-tts-mlx`'s training path from running at
  all.
- [VOICE_CLONE_SETUP.md](VOICE_CLONE_SETUP.md): setup, reference selection,
  troubleshooting, memory guidance.

### Corrected
- `:8081` serves Qwen3.6-35B, not Bonsai-27B; the real Ternary-Bonsai-27B is in
  LM Studio on `:1234` as `27b@q1_0`.
- The `enable_thinking: false` fix applies to the llama.cpp fork, not LM Studio,
  which needs a token budget covering reasoning *and* answer.
- The hardware line in IMPLEMENTATION.md (24 GB) does not describe the machine
  used for this session (48 GB).

## 0.1.0 — 2026-08-20

Initial prototype, built and profiled in one day on an M4 Pro (24 GB).

- Voice loop: browser mic → Whisper (mlx-audio) → two-model LLM router →
  Kokoro TTS, all local. Sentence-pipeline playback.
- By-stakes router: fast 7B for routine turns; Ternary-Bonsai-27B for
  concern-flagged turns and end-of-call fact extraction, with silent fallback.
- Cross-session memory: dated fact extraction per call, recalled into the next
  call's system prompt. Guarded against silent extraction failure.
- Deterministic decline scoring with per-severity alert debounce and a webhook
  escalation gateway.
- "Call yourself" mode: consented self-voice cloning (CSM-1B) with an instant
  precomputed greeting.
- Findings and measured latencies: see IMPLEMENTATION.md.
