# ADR 0003 — Kill and delete the live-failed edge demos

Status: accepted, 2026-08-31

## Context

The `edge/mobile` suite ran six demos through one scorecard: unit tests,
deterministic fixture gates with negative controls, and live gates against
Bonsai 1.7b on the verified host. Three demos (02 offline-translate,
05 catch-up, 06 remittance-ledger) passed everything deterministic and
failed live — a shared root cause of base-model instruction-format
compliance, plus one upstream inference-server parser bug. They were
parked first; keeping dead code in the active tree costs reader attention
and implies investment that is not happening.

## Decision

Delete the three demos from the working tree. Keep three artifacts of
record: their live evidence files under `edge/mobile/evidence/`, the
post-mortem at `edge/mobile/POSTMORTEM.md`, and the code itself in git
history. Revival is a restore-from-history plus a clean `app.py auto` run
with unweakened gates, contingent on the per-corridor LoRA work the kills
themselves justify.

## Consequences

- The active tree contains only demos that earn their place on live
  evidence; the portfolio sweep (`run_all.py`) reports 3/3, not 3-of-6.
- The LoRA roadmap owns the revival path; nothing else re-adds these
  demos.
- History, not the working tree, is the archive — consistent with this
  repository's evidence-first conventions.
