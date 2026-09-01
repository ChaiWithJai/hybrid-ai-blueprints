# Demo 01 — Voice-note intelligence

The flagship kill. Free, offline, on-device transcription and summarization
of family voice notes, in the languages every incumbent excludes.

## Kill targets

| Target | Their position | Their gap |
| --- | --- | --- |
| Telegram Premium transcription | 15M+ paid subs at ~$5-6/mo | Cloud-processed, listener-gated, UZ/TJ UIs community-beta |
| WhatsApp transcription (Android free tier) | 7B+ voice notes/day carried | 4 languages (EN/PT/ES/RU); no Urdu, Bengali, Hindi*, Tagalog, French |
| Viber (PH/MM/UA) | 1B+ Play installs, sliding | Core artifact is the family voice note — untranscribed, unlocalized |

*Hindi is on WhatsApp's iOS list, not the Android free tier per the sweep;
verify in-app before quoting.

## The user and the moment

Amina in Dubai sends her mother in Sylhet eleven voice notes a day. Her
mother's phone is a 4GB Android; her data pack runs out mid-month. Today the
notes pile up unheard when data is gone, and nothing on either phone can
turn them into text her low-literacy household can act on. The moment we
win: a voice note arrives (or was queued), and the phone — with zero
connectivity — produces a transcript, a one-line summary, and can read a
reply aloud.

## Business use case (violet-rails style)

- Namespace: `voice_notes`
- Resources: `VoiceNote { id, familyId, senderId, audioRef, lang, durationMs,
  receivedAt, transcript?, summary?, processedOnDevice }`
- Actions (on-create, client-side — this is the inversion of violet_rails:
  the "api action" runs on the phone, not the server):
  1. `transcribe` — whisper.cpp small/base, on-device
  2. `summarize` — Bonsai 1.7B, one-line + bullet summary, prompt templated
     per corridor language
  3. `index` — embed into the local family archive for demo 05/06 recall
- Server-side action (when connected): sync `VoiceNote` metadata + audio
  blob to the family's pod; fan out to other family devices via message
  central. Transcripts stay on-device by default — privacy is the product.

## Serverpod design

Model (`voice_note.spy.yaml`):

```yaml
class: VoiceNote
table: voice_note
fields:
  familyId: int
  senderId: int
  audioPath: String        # cloud storage ref; blob synced lazily
  lang: String
  durationMs: int
  receivedAt: DateTime
  # transcript/summary intentionally NOT server fields in v0 —
  # they live in the client-side store. A nullable serverTranscript
  # field is added only when a family opts into cloud backup.
```

Endpoints (`voice_note_endpoint.dart`):

- `upload(session, VoiceNote note, ByteData audio)` — store blob, insert
  row, `messageCentral.postMessage('family_$familyId', ...)`
- `listSince(session, int familyId, DateTime since)` — delta sync for a
  device that was offline
- Streaming: family channel over Serverpod's websocket for live delivery;
  client falls back to `listSince` polling when the stream drops
  (reconnect-first, per the Serverpod asymptote findings).

On-device pipeline (Flutter, no server required):

```
record/receive -> whisper.cpp (ggml, small) -> Bonsai 1.7B summarize
              -> local drift/sqlite store -> [when online] sync
```

## Bonsai role

Bonsai 1.7B Q1_0 with a summarization prompt template per language tier:
generative for es/fr/ru/hi/ar/vi/id, LoRA for ur/bn/tl/uz, refuse + verbatim
transcript for sidecar-tier languages (the transcript alone still beats the
incumbents there).

## Offline behavior (the demo's whole point)

Airplane-mode demo script: receive 5 queued voice notes -> toggle airplane
mode -> transcripts + summaries appear -> compose a spoken reply -> reply
queues -> connectivity returns -> reply delivers. Every step must work with
the Serverpod server unreachable.

## Eval gates (repo conventions apply: evidence, not claims)

- WER per language on a preregistered voice-note corpus (record via
  `record_voice_corpus.py` pattern from CareLine)
- Summary faithfulness: bounded lexical check + human review queue, same
  contract as the deal-room evaluator
- Latency: note-to-summary under 8s for a 60s note on the M5 Pro host;
  phone target recorded when hardware validation (task zero) lands
- The kill metric: languages covered vs WhatsApp's 4 / Telegram's paywall

## Milestones

1. Laptop pipeline: whisper.cpp + Bonsai over LM Studio, CLI harness
2. Serverpod sync: family pod, two simulated devices, delta sync
3. Flutter client with airplane-mode demo script
4. Urdu + Bengali LoRA drop-in (highest-leverage artifacts per the Ledger)
