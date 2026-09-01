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

## The demos

| Demo | Ships | Primary targets (from [part-b](inventory/part-b-kill-list.yaml)) |
| --- | --- | --- |
| [01 voice-note-intelligence](demos/01-voice-note-intelligence/DESIGN.md) | On-device transcript + summary + read-aloud | Telegram Premium transcription (15M paid subs), WhatsApp's 4-language free tier, Viber |
| [02 offline-translate](demos/02-offline-translate/DESIGN.md) | LoRA + NLLB translation, fully offline | Google Translate's 59/249 offline gap, Yandex TJ/KG |
| [03 family-line](demos/03-family-line/DESIGN.md) | E2EE store-and-forward voice over degraded networks | IMO (1B+ installs, no E2EE), Botim's VoIP-ban moat, MAX |
| [04 dictation-compose](demos/04-dictation-compose/DESIGN.md) | Speak → clean written message, register-aware | Ridmik Keyboard (50M+), the 754M low-literacy non-market |
| [05 catch-up](demos/05-catch-up/DESIGN.md) | Grounded digest of everything missed, on-unlock | Truecaller's "who called and why" (350M+ MAU India) |
| [06 remittance-ledger](demos/06-remittance-ledger/DESIGN.md) | Extract + recall money records from conversation | The engagement layer above Remitly/Wise/wallets (~$90B+/qtr) |

Demos 01–03 are the Tier-1/2 attack; 04 grows the market; 05 proves the
boilerplate's client-only rule; 06 is the monetization surface.

## How a demo is built (the violet_rails transplant)

Each demo = one `bundle.json`: a namespace (JSON properties template), a
list of **client actions** (transcribe / summarize / translate / extract —
Bonsai, whisper.cpp, Kokoro, on-device), an optional list of server actions
from a pre-compiled registry (send_email, webhook, fan-out), model-pack
references, and eval fixtures. The server is a typed Serverpod app with one
generic `EdgeResource` path plus per-demo typed models where codegen earns
it. Full mapping and the three deliberate inversions from violet_rails:
[boilerplate/README.md](boilerplate/README.md).

## Getting started

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
