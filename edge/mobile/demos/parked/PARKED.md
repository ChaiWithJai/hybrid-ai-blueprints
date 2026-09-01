# Parked demos

These three demos passed every deterministic gate but were killed on their
live scorecards against base Bonsai 1.7b (see `../../evidence/*-live.json`).
Parked means: code and evidence stay, the portfolio stops investing until
the revival condition is met, then `python3 app.py auto` re-runs the same
unweakened gates.

| Demo | Live kill reason (measured, not asserted) | Revival condition |
| --- | --- | --- |
| 02-offline-translate | All four LLM-tier pairs fell to fallback: format non-compliance, plus number mangling ("cent mille" → "a thousand") and kin-term errors in content probes | Per-pair translation LoRAs (ur/bn first), or a format-tuned base; sidecar tier needs the real NLLB-600M artifact |
| 05-catch-up | Grounded-digest format half-held (refs yes, ACTIONS row no); LM Studio stream parser also 400s on ~60% of 1.7b multilingual digest outputs | Format-tuned 1.7b + LM Studio parser fix (report upstream); grounding validator already proven |
| 06-remittance-ledger | es/ur/fr extraction routed to confirm_needed; bn extracted the amount but misassigned currency (INR for BDT) | Per-corridor extraction LoRA with currency supervision; the attestation guard held and stays as-is |

The common cause across all three is instruction-format compliance in the
base model — precisely the cheapest thing small-model fine-tuning fixes.
The kills are the measured business case for the LoRA roadmap, and the
guards (labeled fallbacks, confirm-required records, dropped ungrounded
lines) worked under real failure in every run.
