# edge/mobile — Bonsai demos for the corridor strategy

Prototypes of an offline-first family app built on the Bonsai model family,
targeting the incumbents and language gaps enumerated in
[inventory/](inventory/). One Serverpod backend, one Flutter shell, six
demos — each demo a violet-rails-style **namespace bundle** on the shared
[boilerplate](boilerplate/README.md), not a separate app.

## The premise (and its evidence boundary)

Bonsai 1.7B (0.23 GB ternary) is the one tier with credible phone-class
benchmarks at its size, and the four capabilities it honestly ships —
voice-note intelligence, catch-up summaries, dictation-compose, and answers
over the family's own archive — map onto real, numbered gaps: transcription
paywalled or language-gated by every messenger, offline translation absent
for whole corridors, and ~1B people whose top apps don't speak their
language. Nothing in this directory claims a working phone deployment:
**task zero — Bonsai 1.7B on a real 4 GB Android at usable speed — is
unproven**, and every demo is designed to run laptop-first against LM
Studio, per this repository's conventions.

## The portfolio (after the live review)

Every demo ran the same scorecard against live Bonsai 1.7b. The keeps got
the design layer and a running app; the kills were deleted on the
evidence — see [POSTMORTEM.md](POSTMORTEM.md).

**Keeps — running apps on the [design layer](design/README.md):**

| App | Demo | Ships | Primary targets (from [part-b](inventory/part-b-kill-list.yaml)) |
| --- | --- | --- | --- |
| **Awaaz** (port 8031) | [01 voice-note-intelligence](demos/01-voice-note-intelligence/DESIGN.md) | On-device transcript + summary + read-aloud | Telegram Premium transcription (15M paid subs), WhatsApp's 4-language free tier, Viber |
| **Dhaaga** (port 8033) | [03 family-line](demos/03-family-line/DESIGN.md) | E2EE store-and-forward voice over degraded networks | IMO (1B+ installs, no E2EE), Botim's VoIP-ban moat, MAX |
| **Bol** (port 8034) | [04 dictation-compose](demos/04-dictation-compose/DESIGN.md) | Speak → clean written message, register-aware | Ridmik Keyboard (50M+), the 754M low-literacy non-market |

**Killed — deleted from the tree on live evidence.** The record lives in
[POSTMORTEM.md](POSTMORTEM.md), the decision in
[ADR 0003](../../docs/ADR_0003_EDGE_DEMO_PORTFOLIO_KILLS.md), the
scorecards in [evidence/](evidence/), and the code in git history.
Revival = restore from history + a clean `app.py auto` with unweakened
gates, once the per-corridor LoRAs land.

The suite is also design-reviewed: a screenshot-atlas rig
([design-review/](design-review/)) captures every app state at two
viewports, annotations are clustered by failure mode, and fixes are
verified by recapture — see `design-review/REVIEW.md`.

## How a demo is built (the violet_rails transplant)

Each demo = one `bundle.json`: a namespace (JSON properties template), a
list of **client actions** (transcribe / summarize / translate / extract —
Bonsai, whisper.cpp, Kokoro, on-device), an optional list of server actions
from a pre-compiled registry (send_email, webhook, fan-out), model-pack
references, and eval fixtures. The server is a typed Serverpod app with one
generic `EdgeResource` path plus per-demo typed models where codegen earns
it. Full mapping and the three deliberate inversions from violet_rails:
[boilerplate/README.md](boilerplate/README.md).

## Running the suite (the demos are code, not documents)

Every demo runs today on the shared [`edgekit`](edgekit/) platform —
stdlib Python implementing the namespace/action/store transplant — with a
deterministic fixture mode and a live mode against Bonsai 1.7b on LM
Studio. Each demo ships its own unit tests, acceptance gates including a
negative control that proves its evaluator can fail, and writes a
keep/kill scorecard to [`evidence/`](evidence/).

```bash
cd edge/mobile
python3 run_all.py                # full portfolio sweep (live if 1.7b is up)
python3 run_all.py --fixture-only # deterministic, no model server needed
cd demos/01-voice-note-intelligence && python3 -m unittest && python3 app.py auto
```

Live verdicts are recorded findings, not required gates: a live "kill" is
the capability envelope talking (see each `evidence/*-live.json`), and the
committed evidence preserves exactly what the model did.

## The Flutter build (Awaaz, for real)

[`bonsai_edge_flutter/`](bonsai_edge_flutter/) is the Flutter sprint's
output: Awaaz as one Dart codebase for web/Android/iOS/macOS — animated
onboarding (family, language, elder mode), **real microphone recording**
with a live amplitude waveform, real playback and TTS read-aloud, the
grounding guard ported to Dart, live Bonsai 1.7b when LM Studio is up,
and a queue that survives restarts. 15 tests (`flutter test`), including
regression contracts from the design review. Run it:

```bash
cd bonsai_edge_flutter && flutter run -d web-server
# or serve the committed-ready release: flutter build web --release
```

Native builds compile once Xcode / the Android SDK land (ADR 0004
addendum); the web device runs today.

[`bonsai_edge_pod/`](bonsai_edge_pod/) is the Serverpod backend, running:
the VoiceNote sync model migrated into postgres (Docker compose, dev
ports 9432/9379), upload + delta-fetch endpoints, and an end-to-end proof
via the generated client (`bonsai_edge_pod_client/bin/prove_sync.dart`).

## The Serverpod productization path

```bash
cd edge/mobile/boilerplate
./bootstrap.sh        # dart/flutter/serverpod + project skeletons
make dev DEMO=01      # tmux cockpit: models | pod x2 + redis | app + chaos | watch
make check            # codegen drift + analyze + tests
```

The tmux cockpit runs two pod processes on purpose — Serverpod is
single-threaded per process, so the two-process + Redis fan-out path is
exercised from the first day, not discovered in production. The chaos pane
exists because every demo's acceptance script includes killing the network:
offline-first is the product, so it is also the test.

## Provenance

- Strategy + corridor ranking: The Corridor Ledger (published artifact, rev 2)
- Competitive inventory + sources: The Kill Sheet (published artifact)
- Serverpod scaling review (asymptotes baked into the boilerplate
  guardrails): session research, 2026-08-31 — key claims verified against
  serverpod/serverpod source and issues
- violet_rails pattern analysis: verified against restarone/violet_rails
  source (`api_namespace.rb`, `api_resource.rb`, `api_action.rb`)
