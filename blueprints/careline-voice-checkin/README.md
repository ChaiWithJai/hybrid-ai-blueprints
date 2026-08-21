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

| Route | Routine turns | Concerning turns | Post-call extraction | Speech |
|---|---|---|---|---|
| local (default) | Bonsai 4B on-device | Bonsai 8B on-device | Bonsai 27B ternary on-device | mlx-audio: Kokoro care voice, Whisper capture, CSM-1B clone |
| cloud | any OpenAI-compatible endpoint | any OpenAI-compatible endpoint | any OpenAI-compatible endpoint | TTS/STT NIM endpoints |
| hybrid | on-device | cloud endpoint (or the reverse) | either | on-device |

Route selection is environment variables only (`CARELINE_LLM_BASE_URL`,
`CARELINE_LLM_STRONG_BASE_URL`, `CARELINE_LLM_EXTRACT_BASE_URL`,
`CARELINE_TTS_BACKEND`, `CARELINE_STT_BACKEND`); the agent logic and browser
client never change. The measured local configuration is LM Studio on
`127.0.0.1:1234`. Which of these routes each accelerator supports is recorded in
the [hardware matrix](../../docs/reference/hardware-matrix.md).

## Traces and evaluation

Tracing is off unless you ask for it, and it is never fatal: if the collector is
missing or the exporter fails, the call continues untraced.

```bash
# a local Phoenix collector
docker run -p 6006:6006 -p 4317:4317 arizephoenix/phoenix

CARELINE_TRACE=1 scripts/run
```

Spans follow the OpenInference conventions, so Phoenix renders them without
extra mapping. `careline.turn` wraps a conversational turn; `bonsai.*` spans
wrap each model call and carry the attributes the evaluators read:
`careline.tier`, `careline.route`, `careline.concern_score`,
`careline.alert_fired`, `careline.alert_severity`, `careline.fell_back`,
`careline.empty_reply`, and `llm.model_name`.

| Variable | Default | Meaning |
|---|---|---|
| `CARELINE_TRACE` | unset | `1`, `true`, or `yes` turns tracing on using the Phoenix default endpoint |
| `CARELINE_TRACE_ENDPOINT` | unset | OTLP HTTP collector. Setting it enables tracing on its own; `CARELINE_TRACE=1` selects `http://localhost:6006/v1/traces` |
| `CARELINE_TRACE_PROJECT` | `careline-voice-checkin` | Phoenix project name |
| `CARELINE_TRACE_SERVICE` | `careline` | service name on the resource |

### Running the evaluators

`app/scripts/evaluate_traces.py` reads the spans back out of Phoenix and grades
them. With `--annotate` it writes each result back onto the span, so the verdict
is visible next to the trace that produced it rather than in a separate report.

```bash
cd app
.venv/bin/python scripts/evaluate_traces.py              # grade, write JSON
.venv/bin/python scripts/evaluate_traces.py --annotate    # also annotate spans
```

Expected output, from a measured run over 94 spans:

```text
project 'careline-voice-checkin': 94 spans

[PASS] escalation.concerning_call_alerts             1.00  Every call reaching the alert threshold raised an alert.
[PASS] escalation.no_alert_on_healthy                1.00  No healthy call raised an alert.
[PASS] escalation.debounced_per_severity             1.00  At most one alert per severity per call.
[PASS] routing.deterministic_from_scorer             1.00  Tier selection matched the deterministic scorer on every turn.
[PASS] memory.extraction_not_silently_dropped        1.00  All 2 extraction call(s) returned content.
[PASS] runtime.local_tiers_served                    1.00  All 54 model call(s) served locally by tiers ['concerning', 'extraction', 'routine'] (['27b@q1_0', '4b', '8b']).

release state: VERIFIED — Guards passed
report -> /tmp/careline_trace_eval.json
```

That last line is the evidence that the runtime is what the routes table claims:
54 model calls served across all three tiers by `4b`, `8b`, and `27b@q1_0`, with
no fallback to anything else.

Six evaluators run. Each one exists because a task contract in
[`use-cases/wellness-check-in-calls/tasks/`](../../use-cases/wellness-check-in-calls/tasks)
declares the corresponding failure as critical, so the suite grades the failures
the use case named rather than whatever happened to be easy to measure:

| Evaluator | Fails when |
|---|---|
| `escalation.concerning_call_alerts` | a call crossed the alert threshold and no alert fired |
| `escalation.no_alert_on_healthy` | a call with no concern signal raised an alert |
| `escalation.debounced_per_severity` | the same severity fired more than once in one call |
| `routing.deterministic_from_scorer` | tier selection did not follow the deterministic scorer |
| `memory.extraction_not_silently_dropped` | a post-call extraction returned nothing and the memory write vanished |
| `runtime.local_tiers_served` | any tier fell back instead of being served locally |

Missing evidence is reported as `unverified` rather than scored as a pass: with
no `careline.turn` spans the suite returns `traces_present` at 0.0, and an
absent extraction span is reported as not exercised rather than as success.

### Adding your own

An evaluator is a function of the span list returning `EvalMetric(name, score,
threshold, passed, explanation, metadata)`. Add it to `evaluate()` in
`scripts/evaluate_traces.py`. Two conventions are worth keeping: derive it from a
declared critical failure so it grades something the use case cares about, and
put `measurement_state: "unverified"` in the metadata when the evidence is
absent, so a missing measurement never reads as a pass.

The suite deliberately reimplements its own `EvalMetric` instead of importing the
shared `packages/evaluation` contract, because this blueprint stays
self-contained per [ADR 0003](../../docs/ADR_0003_CATALOG_SCALING_PATTERN.md).

> A green suite is not a working demo. All six evaluators passed on a run whose
> spoken output was unusable, because no evaluator covered voice quality, and one
> passed while the agent invented a memory it had never been told. Read the
> traces, not only the verdicts.

## Known limits

- The evaluation is a scripted regression, not a sealed test set; escalation
  precision/recall on realistic transcripts is unmeasured.
- Decline scoring is keyword/threshold based by design (explainable,
  deterministic); paralinguistic signals are out of scope.
- Cloned-voice synthesis is the slowest step. Measured on an Apple M5 Pro,
  F5 takes about 5 s for a short reply and CSM about 16 s. Replies are
  synthesised in one call rather than per sentence: splitting them was measured
  at 13.74 s against 5.53 s for the same text, because each fragment repaid the
  fixed setup cost.
- Clone quality is bounded by the reference recording. Speaker identity measures
  inside the speaker's own session-to-session band, so the remaining gap is
  prosody, not similarity.
- No voice data or checkpoint ships. `app/voices/` is gitignored because
  reference recordings are biometric data, so a fresh clone starts zero-shot with
  nothing recorded. The tooling to record a corpus, build a dataset, fine-tune,
  and score candidates does ship. See
  [VOICE_CLONE_SETUP.md](VOICE_CLONE_SETUP.md#fine-tuning).
- No cloned voice produced so far has been judged good enough to present as the
  operator's own. Automated speaker-similarity scoring rated every candidate a
  tie and selected nothing; it measures identity, which was never the gap.
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
