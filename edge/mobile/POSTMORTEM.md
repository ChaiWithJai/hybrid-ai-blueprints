# Post-mortem — the three killed demos

Demos 02 (offline-translate), 05 (catch-up), and 06 (remittance-ledger)
were built, fully tested, run live against Bonsai 1.7b, killed on the
evidence, briefly parked, and then deleted from the working tree. This
document is their record. The code is one `git log` away (last present at
the commit that introduced `demos/parked/`); their live scorecards remain
in [evidence/](evidence/).

## What each one was, and what killed it

**02 offline-translate** — per-tier translation routing (LLM for
generative-tier languages, NLLB sidecar seam for low-resource ones).
Deterministic gates all passed. Live, all four LLM-tier pairs fell to the
echo-guard fallback: the model translated but never held the required
output format, and content probes showed number mangling ("cent mille" →
"a thousand") and kin-term errors ("Tonton" → "Watch") — disqualifying
for a remittance-adjacent product where numbers are sacred.

**05 catch-up** — grounded multi-item digests with mandatory source refs.
The grounding validator worked perfectly (fabricated refs dropped, drops
counted). Live, the model half-held the format (refs yes, `ACTIONS:` row
misspelled, partial coverage), and LM Studio's stream parser itself
rejected ~60% of the model's multilingual digest outputs with a
"peg-native format" 400 — a serving-stack defect worth reporting
upstream, preserved in `evidence/05-catch-up-live-attempt1-transient-400.json`.

**06 remittance-ledger** — single-turn money-fact extraction with digit
attestation and confirm-before-ledger. Live, English and Bengali
extracted; Spanish, Urdu, and French routed safely to confirm-needed; the
Bengali record got the amount right and the currency wrong (INR for BDT).
No wrong money fact ever entered a ledger — the guards did their job —
but a product that defers most of its extractions is not shippable.

## The common cause

One failure mode underneath all three: **base Bonsai 1.7b's
instruction-format compliance.** The models mostly *could* do the tasks;
they could not reliably speak the strict output contracts the guards
demand. That is precisely the cheapest thing small-model fine-tuning
fixes, which makes these kills the measured business case for the
per-corridor LoRA roadmap (Urdu and Bengali first) rather than three dead
ideas.

## Revival condition

Train the format/language LoRAs, restore any demo from git history, run
`python3 app.py auto` with its gates unweakened. A kill flips to keep
only on evidence, the same way it was killed.

## Lessons carried into the keeps

1. Guards must be designed to fail loudly before the model is trusted at
   all — every kill was caught by a guard, not a user.
2. Fixture-mode green means the *system* works; only live runs say
   anything about the *model*. Never conflate the two verdicts.
3. The serving stack is part of the model surface: an inference-server
   parser bug produced the same user-visible failure as a bad model.
