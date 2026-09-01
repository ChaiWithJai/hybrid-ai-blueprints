# Demo 04 — Dictation compose

Make the typing problem disappear instead of solving it.

## Kill targets

| Target | Their position | Their gap |
| --- | --- | --- |
| Ridmik Keyboard (BD) | 50M+ downloads; BD Play #9 — a keyboard outranking banks | It optimizes typing; the user's actual job is producing a written message |
| Gboard dictation | 10B+ installs | Narrow offline language coverage; no cleanup/formalization step |
| (segment) low-literacy non-consumption | 754M adults, 63% women | Text-first apps exclude them entirely — this demo grows the market |

## The user and the moment

Rahima cannot comfortably write Bengali but must send text: to the bank, to
her son's school, to the wallet app's support line. Today she hands her
phone to a neighbor. The moment we win: she speaks; the phone produces a
clean, correctly-registered written message (formal for the school,
familiar for family), reads it back to her for approval, and sends it —
all offline.

## Business use case (violet-rails style)

- Namespace: `compositions`
- Resources: `Draft { spokenAudioRef, rawTranscript, cleanText, register:
  formal|familiar, lang, approvedByVoice: bool }`
- Actions (client-side):
  1. `dictate` — whisper.cpp ASR
  2. `clean` — Bonsai 1.7B rewrite: punctuation, register, honorifics
     (Bengali/Urdu honorific systems are a fine-tune target, not a prompt
     hack — track as LoRA work)
  3. `read-back` — Kokoro TTS; approval is spoken, not tapped
  4. `deliver` — share-sheet into WhatsApp/IMO/SMS (wrap incumbents, don't
     replace the channel)
- Server-side actions: none in the core loop. Optional synced draft history
  under the family pod for demo 05/06 recall.

## Serverpod design

Deliberately the thinnest demo: proves the boilerplate's client-only mode —
a demo module MUST be runnable with `serverpod` absent (the same fail-open
posture the hardware matrix documents for platform-specific paths). Server
adds only `DraftHistory` sync when a family pod exists.

## Bonsai role

The rewrite task is squarely in the 1.7B envelope (short-text transform).
Register control per language ships as part of the corridor LoRA. Refusal
rule: if ASR confidence is low, read back the uncertain span and ask —
never send silently-wrong text on a low-literacy user's behalf; the harm
asymmetry is the design constraint.

## Offline behavior

Entire loop offline. The share-sheet delivery queues in the target app when
that app is offline too — we inherit the incumbents' own queueing.

## Eval gates

- Round-trip intelligibility: dictated -> cleaned -> TTS-read-back,
  scored by human review queue (repo review-workshop conventions)
- Register accuracy on a preregistered formal/familiar Bengali set
- The kill metric: task completion time vs typing on Ridmik for the same
  message, measured with real low-literacy testers before any claim

## Milestones

1. CLI loop on the M5 host (bn, ur): dictate -> clean -> read-back
2. Confidence-gated clarification loop
3. Flutter compose surface + share-sheet delivery
4. Field-test protocol with consent + human review, before any metric claim
