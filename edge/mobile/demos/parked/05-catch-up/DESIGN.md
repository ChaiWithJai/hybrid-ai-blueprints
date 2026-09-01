# Demo 05 — Catch-up

"Who called and why" answered inside the family context, offline.

## Kill targets

| Target | Their position | Their gap |
| --- | --- | --- |
| Truecaller (India) | 350M+ MAU India of 500M global; IN Play #8 | Answers "who is this number" from a crowd-sourced directory; cannot answer "what did my family need while I was gone" |
| (segment) the data-drought gap | 3.1B covered-but-offline | When data returns, incumbents dump a backlog; nothing digests it |

## The user and the moment

Suresh drives twelve-hour shifts in Dubai with his phone in a locker. His
family in Kerala sent forty messages, three voice notes, and two missed
calls across two apps. The moment we win: he opens the app once and reads —
or hears, in Malayalam — five lines: what happened, what needs an answer,
what can wait. Generated on his phone the moment it wakes, no server round
trip.

## Business use case (violet-rails style)

- Namespace: `catchups`
- Resources: `CatchupDigest { familyId, windowStart, windowEnd, items[],
  digestText, actionsNeeded[], generatedOnDevice: true }`,
  `DigestItem { sourceRef, kind: message|voice|missed_call|remittance,
  oneLine, needsReply: bool }`
- Actions (client-side, on-unlock or on-reconnect trigger):
  1. `collect` — gather everything since last digest from the local family
     store (demo 01/03/06 feed it; notification-listener integration for
     wrapped incumbents is a later, permission-gated milestone)
  2. `digest` — Bonsai 1.7B: summarize, rank by needs-reply, honor
     langPref; strict grounding — every digest line must cite a source
     item (deal-room citation discipline, applied to the family)
  3. `speak` — optional Kokoro TTS playback for elder/low-literacy mode
- Server-side actions: none. Digests never leave the device by default.

## Serverpod design

Nothing new server-side — this demo is the payoff of the shared local
store the other demos populate. It exercises the boilerplate's rule that a
namespace can be client-only: the `catchups` namespace registers zero
endpoints and still gets the shared store, sync hooks (off), and eval
harness. If the boilerplate can't express that cleanly, the boilerplate is
wrong — this demo is its test.

## Bonsai role

Multi-item summarization with grounding — the RULER-style strength of the
size class. Context budget: digest windows are chunked to fit a 4K on-device
context; long backlogs digest hierarchically (chunk summaries -> summary of
summaries), never by truncating silently.

## Offline behavior

The entire feature is an offline feature: it runs at the moment
connectivity is worst (just reconnected or still offline). No degraded
mode exists because there is no connected mode.

## Eval gates

- Grounding: zero digest lines without a resolvable source item
  (deterministic check, same contract as the deal-room citation validator)
- Needs-reply precision/recall on a labeled family-thread corpus
- The kill metric: time-to-caught-up vs scrolling the raw backlog,
  measured; and languages served vs Truecaller's directory-lookup model

## Milestones

1. Digest CLI over a synthetic family week (fixture corpus, preregistered)
2. Grounding validator + human review queue
3. On-unlock trigger + TTS playback in the Flutter shell
4. Notification-listener ingestion spike (Android; explicit consent gate)
