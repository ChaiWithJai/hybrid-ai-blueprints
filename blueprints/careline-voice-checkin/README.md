# CareLine voice check-in

CareLine runs a voice check-in call that remembers earlier calls and escalates
decline signals to a human care contact. Everything runs locally on Apple
Silicon: two LLMs, speech recognition, speech synthesis, voice cloning, and
memory. No audio or text leaves the machine on the local route.

The job and its guards are defined in the
[wellness check-in calls use case](../../use-cases/wellness-check-in-calls/README.md).

## What a call looks like

1. The call opens instantly: the greeting text and audio are precomputed while
   the page loads (measured start: 0.002–0.03 s).
2. The caller speaks. Whisper transcribes on-device (~1 s warm).
3. A deterministic scorer checks the utterance for decline signals. Routine
   turns go to a fast 7B model (~0.6 s). The moment concern registers, a
   27B-class model handles the delicate turns (5–9 s) — the by-stakes router.
4. Replies are spoken sentence-by-sentence so the voice starts while later
   sentences still synthesize.
5. On hangup, the strong model extracts dated facts and a one-sentence care
   summary. The next call references those facts by date.
6. Concerning calls fire at most one alert per severity level to a webhook —
   the care contact's channel.

A **"call yourself" mode** speaks in the operator's own cloned voice (F5-TTS via
MLX, ~5 s per sentence) as a consented self-compassion ritual. Voice references
are biometric data: they stay on the operator's disk and are never committed.
Setup, reference selection, and troubleshooting:
[VOICE_CLONE_SETUP.md](VOICE_CLONE_SETUP.md).

## Run it

Requirements: macOS on Apple Silicon, `uv`, `ffmpeg`, **`espeak-ng`**
(`brew install espeak-ng`), Ollama with `qwen2.5:7b`, and (optional, for strong
turns) Ternary-Bonsai-27B — see the
[Bonsai demo repository](https://github.com/PrismML-Eng/Bonsai-demo). The
router falls back to the fast model when the strong endpoint is absent.

`espeak-ng` is not optional: without it the first care-mode synthesis calls
`exit()` in native code and takes the server process down with it. `scripts/run`
exports `ESPEAK_DATA_PATH` once a system install is present, and
`scripts/preflight` fails loudly if it is missing.

```bash
blueprints/careline-voice-checkin/scripts/run      # server on :8100
blueprints/careline-voice-checkin/scripts/verify   # conversation + voice regression
```

Open http://127.0.0.1:8100/ and start a call. `scripts/verify` runs two
regressions and exits nonzero on any failure:

- the synthetic Dorothy demo — a healthy call that seeds memory, a recall call,
  and a decline call that must alert exactly once;
- the voice path (`app/scripts/verify_voice.py`) — that the clone returns real
  audio rather than silence with HTTP 200, carries no per-chunk leading silence,
  meets a latency budget, and that care-mode synthesis leaves the server alive.

## Routes

| Route | Fast LLM | Strong LLM | Speech |
|---|---|---|---|
| local (default) | Ollama on-device | Bonsai-27B on-device | mlx-audio (Kokoro) + F5-TTS clone, on-device |
| cloud | any OpenAI-compatible endpoint | any OpenAI-compatible endpoint | TTS/STT NIM endpoints |
| hybrid | on-device | cloud endpoint (or the reverse) | on-device |

Route selection is environment variables only (`CARELINE_LLM_BASE_URL`,
`CARELINE_LLM_STRONG_BASE_URL`, `CARELINE_TTS_BACKEND`,
`CARELINE_STT_BACKEND`); the agent logic and browser client never change.

## Known limits

- The evaluation is a scripted regression, not a sealed test set; escalation
  precision/recall on realistic transcripts is unmeasured.
- Decline scoring is keyword/threshold based by design (explainable,
  deterministic); paralinguistic signals are out of scope.
- Cloned-voice synthesis is ~5 s per sentence (real-time factor ~1.2) on an
  M4 Pro; the sentence pipeline hides part of this, not all of it.
- Clone quality is bounded by the reference recording. Speaker identity measures
  inside the speaker's own session-to-session band, so the remaining gap is
  prosody, not similarity.
- A fine-tuned checkpoint ships for the cloned voice, selected by listening
  test; delete `app/voices/f5_finetuned.safetensors` to fall back to zero-shot.
  Automated speaker-similarity scoring rated every candidate a tie and did not
  select it — it measures identity, not prosody. See
  [VOICE_CLONE_SETUP.md](VOICE_CLONE_SETUP.md#fine-tuning).
- `espeak-ng` must be installed system-wide or care-mode synthesis kills the
  server process (native `exit()`, uncatchable from Python).
- Memory fact extraction appends without deduplication across calls.
- Cloud and hybrid routes are wired but unverified end to end.
- This is a wellness tool, not clinical monitoring, diagnosis, or treatment.

Engineering findings and measured latency tables: [IMPLEMENTATION.md](IMPLEMENTATION.md).

## Migration to the shared runtime

This blueprint is deliberately self-contained (see
[ADR 0003](../../docs/ADR_0003_CATALOG_SCALING_PATTERN.md)): `app/` reaches
nothing outside this directory, so the blueprint can graduate to its own
repository unchanged. Planned convergence with the shared packages, in order:

1. Adopt `packages/hybrid-router` in place of the app's own by-stakes router
   once the shared router supports latency-tiered routing for real-time voice.
2. Express the scripted regression through `packages/evaluation` and the
   shared evaluation framework.
3. Retire standalone copies of this app; this directory is the canonical home.
