# Inventory

The competitive research behind the demo suite, enumerated as data.

| File | Contents |
| --- | --- |
| [part-a-language-mismatches.yaml](part-a-language-mismatches.yaml) | 40+ named cases where a country's top apps are not in the language its people speak — app, chart rank, missing language, speaker count, and how a 1.7B on-device model reaches that language (generative / LoRA / NLLB sidecar / honest deferral) |
| [part-b-kill-list.yaml](part-b-kill-list.yaml) | 28 incumbents classed kill / displace / ride / partner / benchmark, each with dated numbers and the demo that carries the attack |

Compiled 2026-08-31 from six parallel research sweeps across Google Play and
the iOS App Store in 20 corridor countries (18 charted; Tajikistan has no
public chart source, Myanmar Play is uncovered). Chart positions are a
one-week snapshot. Company-claimed figures are marked as claims. Full
narrative, sources, and flags live in the two published companion artifacts:

- The Corridor Ledger — strategy + Shapley corridor model (rev 2)
- The Kill Sheet — the inventory with per-row sources

Every demo DESIGN.md in [../demos/](../demos/) cites its targets from
part-b; the language routing in every demo follows part-a's `serve_tier`.
