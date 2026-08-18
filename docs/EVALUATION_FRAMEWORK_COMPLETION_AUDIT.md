# Evaluation framework completion audit

Date: August 18, 2026

## Scope of this audit

This audit asks whether Prism now has the requested evaluation framework and
native dashboard. It does not ask whether the human pilot, cloud comparison,
or pricing study has produced results. Those studies remain deliberately empty
until real participants and authorized providers create evidence.

## Requirement evidence

| Requirement | Authoritative evidence | Result |
| --- | --- | --- |
| Define the deal room job before scoring it | `benchmarks/evaluation_framework.v1.json` names the job as helping a team advance, pause, or stop a deal and identify the next evidence or action. | Complete |
| Apply Hamel's trace first and classifier validation method | `docs/EVALUATION_FRAMEWORK.md`, the room Review queue, and `core/evaluator_validation.py` require observed failures, narrow binary criteria, disjoint splits, TPR, TNR, parse failures, and critical false pass counts. | Complete as a framework. Human calibration evidence is still empty. |
| Make Bonsai usable as an LLM judge without trusting it prematurely | `benchmarks/judges/deal_room_semantic_judges.v1.json` contains four versioned binary criteria. `core/semantic_judge.py` runs an explicit provider, hides route identity, requires strict JSON, and marks every result development only. | Complete as a candidate judge. Release trust remains false. |
| Provide a LangSmith style master evaluation view | The existing room Evaluation tab contains Review queue and Eval lab modes. The Eval lab shows the decision, route comparison, gates, experiment history, evaluator registry, judge calibration, evidence layers, buyer measures, and truth boundaries. | Complete |
| Track local, cloud, and hybrid AI | `core/evaluation_experiments.py` stores room scoped experiment and run events in an append only SHA-256 chain. The API creates experiments, records runs, returns snapshots, and compares paired cases only when their contracts match. | Complete. The live store has zero cloud and hybrid runs. |
| Preserve missing evidence instead of turning it into a zero or pass | `core/evaluation_dashboard.py` returns `not_measured` for missing routes and buyer measures. The UI renders that phrase. Unit and browser checks cover the behavior. | Complete |
| Let business value choose the next investment | The framework keeps time, corrections, evidence quality, decision usefulness, preference, price, and paid next step separate from model metrics. It limits the next investment to model quality, retrieval, interface design, document fidelity, or deployment security. | Complete as a decision contract. Buyer evidence is still empty. |
| Handle Shreya Shankar's criteria drift | Every judge criterion and prompt is versioned. The framework invalidates calibration after criterion, prompt, model, quantization, retrieval, workload, or time changes. General trace labels do not count as criterion labels. | Complete |
| Show where the framework expands | The workload registry makes deal room first pass active and coding agent work next. The seven evidence layers remain stable while task specific measures change. | Complete |
| Keep one user facing product | The Eval lab is inside `/rooms/{room_id}/evaluation`. Buzz remains the signed collaboration substrate and Phoenix remains optional technical observability. No fifth primary tab or second application was added. | Complete |
| Verify the real surface | All 519 Python tests pass. The live browser check covers the same room URL, subtab continuity, truthful empty states, judge trust, buyer measures, no horizontal overflow at 390 pixels, and zero browser warnings or errors. The refreshed canonical customer demo record passes 16 assertions at 390, 768, and 1440 pixels. | Complete |

## Current measured state

- Local development evidence contains ten Project Titan cases.
- The canonical room review has zero human annotations.
- Every Bonsai judge criterion has zero of 100 calibration labels.
- Cloud has no configured model and no recorded run.
- Hybrid has no recorded run.
- Buyer value and pricing have no recorded measures.
- The dashboard therefore makes no model winner, accuracy release, judge trust,
  next investment, or willingness to pay claim.

## Evidence files

- `evidence/browser-hybrid-eval-lab-v1.json`
- `evidence/browser-customer-demo-v1.json`
- `evidence/browser-customer-demo-desktop-v1.png`
- `evidence/browser-customer-demo-mobile-v1.png`
- `docs/GOAL_REPORT_CARD.md`
- `docs/THREE_WORKFLOW_BLIND_PILOT.md`

## Next evidence cycle

The framework is ready. The next work is not another dashboard feature.

1. Keep the four view room surface frozen.
2. Review the ten sampled room traces and record the first observed failures.
3. Generate the three frozen workflows through Bonsai, an authorized cloud
   model, and the hybrid route.
4. Have four qualified participants review the nine candidates blindly.
5. Run the pricing interview immediately after use.
6. Use the preset rules to select one investment area or record that the
   evidence is split.
