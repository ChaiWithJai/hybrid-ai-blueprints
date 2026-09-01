# Demo 03 — Family line

The messenger displacement: store-and-forward voice for families split
across a connectivity line, with encryption the incumbents never had and
intelligence none of them ship.

## Kill targets

| Target | Their position | Their gap |
| --- | --- | --- |
| IMO | 1B+ installs, ~200M users; #3 BD, #4 SA/QA | Bad-network codecs are its whole moat; no default E2EE (forensics recovered chats); no AI |
| Botim (UAE) | 150M registered claim; licensed VoIP monopoly built on the WhatsApp-call ban | Store-and-forward voice sidesteps the live-call ban entirely; zero migrant-language UIs |
| MAX (Russia) | 75M registered, preinstall-mandated | No E2EE, state-adjacent — on-device privacy is the counter-position |

## The user and the moment

A Bangladeshi crew in a Sharjah labor camp shares patchy Wi-Fi; live calls
home are blocked (UAE) or unaffordable. The moment we win: voice messages
flow both ways as bandwidth allows — recorded now, delivered when the pipe
opens — each arriving with a transcript and summary in Bengali, end-to-end
encrypted, with nothing intelligible to the relay.

## Business use case (violet-rails style)

- Namespace: `family_circles`
- Resources: `Family { id, name, members[] }`, `Member { deviceKeys[],
  langPref, roleHint: elder|migrant|child }`, `Envelope { familyId,
  senderId, cipherBlob, mediaType, queuedAt, deliveredAt[] }`
- Actions:
  - client `on-record`: encrypt to family device keys; enqueue
  - client `on-receive`: decrypt -> demo-01 pipeline (transcribe, summarize)
  - server `on-envelope`: durable queue + fan-out only — the server is a
    dumb, encrypted mailbox by design; it CANNOT run AI actions because it
    cannot read anything (this is the anti-WhatsApp/anti-MAX architecture,
    stated as a product claim)

## Serverpod design

This demo exercises Serverpod's streaming exactly where the asymptote
review said to be careful — design for reconnect from day one:

```yaml
class: Envelope
table: envelope
fields:
  familyId: int
  senderId: int
  cipherPath: String       # cloud storage; server never holds plaintext
  mediaType: String
  queuedAt: DateTime
indexes:
  envelope_family_queued_idx:
    fields: familyId, queuedAt
```

Endpoints: `enqueue`, `ackDelivered`, `pollSince` (the offline fallback).
Streaming: one `family_$id` channel via message central; Redis bridges
instances when the pod scales past one process (single-thread-per-process,
~64k conn ceiling per node — from the Serverpod asymptote review in this
repo's session notes). Client treats the stream as an optimization over
`pollSince`, never a requirement; server shutdown force-closes websockets,
so the client owns continuity.

## Bonsai role

Same on-device pipeline as demo 01, plus an elder mode: incoming envelopes
auto-play with Kokoro TTS in `langPref`, a zero-UI loop for the left-behind
parent (documented whitespace — no messenger ships this).

## Offline behavior

Both ends may be offline at once. Envelopes persist client-side, sync
opportunistically, and the family timeline renders entirely from the local
store. Target: a week of round-trips on end-of-month data droughts.

## Eval gates

- Delivery: no envelope loss across 1,000 simulated connect/disconnect
  cycles (scripted against a local pod)
- Crypto review gate before any real-user pilot — repo verification-gates
  conventions apply; prototype crypto is NOT a security claim
- The kill metric: usable round-trip on a 16kbps-equivalent trickle vs
  IMO's minimum viable call bandwidth

## Milestones

1. Serverpod encrypted-mailbox pod + two-device simulator, chaos toggle
2. Envelope client store + reconnect protocol in the Flutter shell
3. Demo-01 pipeline wired to received envelopes; elder mode
4. Camp-Wi-Fi network profile (shaped bandwidth) demo script
