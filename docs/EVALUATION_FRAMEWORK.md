# Prism evaluation framework

Date: August 18, 2026

## Decision the framework supports

The framework must tell PrismML where to invest next. The allowed choices are
model quality, retrieval, interface design, document fidelity, and deployment
security. A dashboard is useful only when its evidence can distinguish those
choices.

The first workload is a source linked deal room review. The framework can later
cover coding agents, but a coding case cannot silently change the meaning of a
deal room metric.

## Reconciled method

Hamel Husain's method controls how Prism creates and validates metrics. The
team must first read representative traces and describe observed failures.
Each semantic judge checks one binary criterion. Human labels are split into
train, development, and test sets. A judge remains untrusted until it has
acceptable true positive and true negative rates on the held out test set.

Swyx's product and engineering lens controls how Prism records experiments.
Every run keeps its dataset, prompt, model, evaluator, route, source snapshot,
latency, cost, and result. The dashboard keeps experiment history and shows
paired changes against a named baseline.

Shreya Shankar's work controls how criteria change. Reviewers often understand
a criterion better after seeing model output. Prism therefore records every
rubric revision as a new version. A changed criterion invalidates the prior
judge calibration and starts a new development cycle.

The business lens controls priority. Prism measures review time, corrections,
evidence quality, decision usefulness, candidate preference, workflow
preference, and willingness to pay. A buyer's paid next step or recorded reason
to decline remains separate from model quality.

## Measurement layers

| Layer | Main question | Primary evidence |
| --- | --- | --- |
| Document fidelity | Did Prism preserve the source content and structure needed for the task? | Parser coverage, table accuracy, OCR error, and anchor resolution |
| Retrieval | Did the evidence packet contain every needed passage? | Recall at k, mean reciprocal rank, and two hop recall |
| Answer | Did the answer use the evidence correctly and complete the task? | Claim support, critical numbers, required components, and uncertainty |
| Workflow | Did the agent finish the task and recover safely? | End to end completion, first failed transition, tool errors, and guard recovery |
| Human use | Did the workflow reduce expert effort while preserving the decision? | Time, corrections, evidence quality, usefulness, and preference |
| Deployment | Did the route meet policy and operating needs? | Route success, authorization, exposure, latency, cost, and energy |
| Business value | Will a buyer fund the result? | Price range, value unit, package, paid next step, or decline reason |

No layer produces a universal quality score. A critical source or numerical
failure cannot be offset by lower latency or a better usefulness rating.

## Local, cloud, and hybrid experiments

Every route receives the same dataset, source snapshot, question, evidence
packet, output contract, and limits. Human reviewers do not see the route or
model name.

Local means that Bonsai writes the answer from the local evidence packet.
Cloud means that an approved cloud model writes the answer after the existing
consent checks pass. Hybrid means that Bonsai writes the first draft and an
approved cloud model reviews the draft against the same packet.

A failed route remains a failed route. Prism must not replace it with a copied,
simulated, or manually written answer.

## Bonsai as a judge

Bonsai 27B is a candidate semantic judge, but it is not yet a trusted judge.
Prism will start with four narrow criteria: material claim support, decision
task completion, material omission, and calibrated uncertainty.

Each criterion needs about 100 domain labels, with roughly 50 Pass and 50 Fail
examples. Fifteen percent of the labels supply few shot examples. Forty five
percent form the development set. Forty percent remain hidden until the final
test.

The target is a true positive rate above 90 percent and a true negative rate
above 90 percent, with no critical false pass. Prism reports both rates, the
confusion matrix, parse failures, the corrected production pass estimate, and
a 95 percent bootstrap interval. Raw judge agreement is not a release metric.

## Dashboard contract

The native Evaluation view contains the review queue and the Eval lab. The Eval
lab defaults to the active room and has five views.

1. Decision shows the current investment choice and the evidence that is still
   missing.
2. Experiments compares local, cloud, and hybrid runs with a named baseline.
3. Evaluators shows every code check, human review, and semantic judge together
   with its version and trust state.
4. Traces and review links failures back to full traces and human annotations.
5. Business value shows time, corrections, usefulness, preference, pricing,
   and paid next steps.

The dashboard shows `Not measured` when no evidence exists. It does not render
a missing cloud run as zero quality, and it does not render an uncalibrated
judge as ready.

## Implemented contracts

The room dashboard is served at
`/api/workspace/evaluation/dashboard?room={room_id}` and appears inside the
existing Evaluation tab. It does not create a second application.

The append only experiment ledger records room scoped experiment definitions
and runs. A comparison is allowed only when both experiments share the same
dataset, workflow, source snapshot, question, evidence packet, answer contract,
and limits. It reports paired case differences and never creates a composite
score. The local APIs are:

- `GET /api/workspace/evaluation/experiments?room={room_id}`
- `POST /api/workspace/evaluation/experiments`
- `POST /api/workspace/evaluation/runs`
- `GET /api/workspace/evaluation/experiments?room={room_id}&left={id}&right={id}`

The candidate judge prompts are versioned in
[`deal_room_semantic_judges.v1.json`](../blueprints/deal-room-analyst/app/benchmarks/judges/deal_room_semantic_judges.v1.json).
The runner strips route and answer model identity from the prompt, requires one
binary result, and rejects malformed output. Every result remains development
only until the matching criterion passes held out validation.

## Current state

Prism has six mapped Project Titan retrieval cases, one saved Bonsai generation
case, three recorded workflows, and 38 Buzz events. The canonical review ledger
has zero human annotations. The development first pass registry has five cases.
Cloud and hybrid candidate outputs do not exist, and no buyer pricing record
exists.

The current result supports engineering development. It does not support an
accuracy release, a model winner, a judge trust claim, or a willingness to pay
claim.

The machine readable contract is
[`evaluation_framework.v1.json`](../blueprints/deal-room-analyst/app/benchmarks/evaluation_framework.v1.json).

## Sources

The method draws from Hamel Husain's
[The Revenge of the Data Scientist](https://hamel.dev/blog/posts/revenge/index.html)
and [A Field Guide to Rapidly Improving AI Products](https://hamel.dev/blog/posts/field-guide/)
for error analysis, narrow binary judges, classifier validation, and business
specific metrics.

Shreya Shankar and colleagues' paper
[Who Validates the Validators?](https://arxiv.org/abs/2404.12272) informs the
human alignment loop and the treatment of criteria drift.

Swyx's discussions in
[Production AI Engineering starts with Evals](https://www.latent.space/p/braintrust)
and the [Agent Labs thesis](https://www.latent.space/p/unsupervised-learning-2026)
inform experiment history, shared comparison, observability, and the decision
to specialize only after the workload produces evidence.

[LangSmith evaluation concepts](https://docs.langchain.com/langsmith/evaluation-concepts)
and [experiment analysis](https://docs.langchain.com/langsmith/analyze-an-experiment)
inform the dataset, experiment, trace, evaluator, annotation queue, and baseline
structure. Prism uses those as design references, not as evidence that its own
evaluation is complete.
