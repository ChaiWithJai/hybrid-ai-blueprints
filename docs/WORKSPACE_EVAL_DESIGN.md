# Workspace evaluation design

Date: August 17, 2026

## Decision supported by this evaluation

The evaluation asks whether Prism helps a deal team find evidence, understand a
source bound answer, complete a short workflow, and find mistakes in the room
conversation. It does not certify investment advice or Bonsai 27B as accurate
for private deal rooms.

The development benchmark has three tracks. The tracks remain separate because
one combined score would hide where a failure occurred.

## Retrieval and generation

The retrieval set contains six Project Titan questions. A person mapped each
question to one or two exact parser passages before the run. The set includes
debt structure, an excess cash flow sweep, a two document covenant check,
sponsor returns, value creation, and a builder basket.

The runner reports Recall at k for every case and mean reciprocal rank across
the set. The covenant question also reports whether both required passages
appear in the first three results. The runner evaluates generation only after
retrieval.

The generation set contains one saved Bonsai 27B debt answer. One binary check
asks whether the answer's numbers and material terms appear in the cited
passage. A second binary check asks whether the answer contains each registered
debt instrument and excludes the registered equity rows. The runner changes a
debt amount and removes a debt instrument as negative controls. Both changes
must fail the intended check.

The saved answer passes these deterministic checks. A deal professional has not
reviewed its meaning, completeness, or usefulness.

## Agentic workflows

The workflow score starts with end to end task success. Transition checks then
name the first failed step.

| Workflow | Required transitions |
| --- | --- |
| Source bound answer | Question to retrieved evidence, retrieved evidence to guarded answer, guarded answer to signed Buzz event, signed event to visible answer |
| Guard recovery | First generation to retained rejection, retry to publication guard pass, published event to restart restoration |
| Citation follow up | Citation to in place preview, preview to scoped composer, preview to exact full source |

The current saved evidence passes all three development workflows. The result
does not measure an open ended agent's ability to plan or recover across an
unknown deal room.

## Chat error discovery

The room contains 38 verified Buzz events. The review set selects ten events
from distinct strata, including requests, fallbacks, rejected drafts, an
operator review, a replay, and an accepted answer.

The agent produced 13 suggestions across these samples. The suggestions include
publication rejection, workflow noise, raw machine markup, and raw citation
wrappers. The product renderer already hides or groups several of these forms,
so a reviewer must inspect both the stored trace and the human view before
calling one a product error.

The review interface is a native Prism room view at
`/rooms/{room}/evaluation`. The main Prism server builds its sample from the
same Buzz room messages shown in Activity. It shows the full trace, metadata,
Pass, Fail, Defer, a free text note, a coverage map, and review progress. Every
saved label remains a development label. The interface does not prove the
reviewer's identity or domain qualification.

A synthetic browser replay verified the review flow on August 18. Five rapid
fixture judgments persisted across reload and unlocked the depth phase. The
replay also verified 38 corpus nodes, ten initial samples, five annotated
fixture nodes, a three trace breadth expansion, separate agent suggestions,
hash only observability, and a 390 pixel layout without horizontal overflow.
The replay found a lost update race between polling and annotation writes. The
client now serializes annotation writes and discards a stale refresh when local
review state changes during the request.

Local Phoenix accepted one marked synthetic trace with five OpenInference
evaluator spans. Each span excludes content, includes hashes, and states that
its feedback source is a synthetic fixture. The run verifies the transport and
field mapping. It provides no human or accuracy evidence.

## Current development result

| Track | Result | Boundary |
| --- | --- | --- |
| RAG retrieval | Recall at k 1.0, mean reciprocal rank 1.0, two hop pass rate 1.0 | Six manually mapped questions from a synthetic fixture |
| RAG generation | One of one answers passes both deterministic checks, and two of two negative controls fail as expected | Semantic faithfulness and domain accuracy remain unreviewed |
| Agentic workflows | Three of three recorded workflows pass | Saved paths, not open ended agent coverage |
| Chat error discovery | Ten traces loaded and 13 agent suggestions available | Zero human annotations |
| Release | Fail | Domain review and a cloud or hybrid comparison are absent |

The machine readable result is
[`workspace-eval-v1.json`](../evidence/workspace-eval-v1.json). The dataset is
[`workspace_eval_v1.json`](../benchmarks/workspace_eval_v1.json).

## Evaluation audit

### Error analysis

Status: Partial.

The project has real traces and observed failure examples. The ten trace sample
starts a systematic review, but no person has added a free text annotation.
Keep the release closed until reviewers identify the first failure in each
failed trace.

### Evaluator design

Status: Development checks are specific and binary.

The runner uses code for citations, registered terms, numbers, workflow states,
and transition presence. It does not use a broad helpfulness score or text
similarity score. Any later language model judge must target one observed
failure mode.

### Judge validation

Status: No judge is trusted.

The benchmark has no language model judge. Do not add one until human labels
exist. A later judge needs separate training, development, and test sets, plus
true positive and true negative rates.

### Human review

Status: Interface ready and review pending.

The interface renders the full trace rather than raw JSON in a spreadsheet. A
qualified reviewer still needs to inspect the samples. Agent suggestions remain
visually separate and require acceptance or dismissal.

### Labeled data

Status: Insufficient.

Ten samples support discovery, not a failure rate. The first review cycle should
mix the ten selected strata with random events. A later validation set needs
enough passing and failing examples to measure both kinds of judge error.

### Pipeline hygiene

Status: The benchmark is versioned and has negative controls.

Run error discovery again after a model, retrieval, prompt, or interface change.
Do not reuse this development score as release evidence after such a change.

## Human review protocol

First, review all ten samples without reading the agent suggestions. Record the
first failure and the evidence used for the judgment.

Second, open the suggestions and accept or dismiss each one. Revisit earlier
traces after a new failure mode appears.

Third, add random traces from the room history. Continue until new traces mostly
repeat known failures.

Fourth, ask a deal professional to review the same Bonsai, cloud, and hybrid
outputs without model labels. Record time, corrections, evidence quality,
decision usefulness, and preferred workflow.

## Writing rules used

The interface and these documents use a selected subset of the
[`mine-writing-rules` JSON](https://github.com/docwriter-org/mine-writing-rules/blob/main/writing-rules.json).

| Rule | Application |
| --- | --- |
| R001 and R008 | Use short, familiar words and remove copy that does not help the decision. |
| R055 | Use one term for source, citation, trace, and review throughout the workflow. |
| R067 | Describe what the software records and renders without claiming that it thinks or knows. |
| R163 and R166 | Use sentence case and no end punctuation in interface labels. |
| R397 and R403 | Use short headings that state the section's job. |
| R509 and R514 | Match each claim to the measured evidence and state the limit beside the result. |
| R527 to R532 | Keep observed results, inferences, missing evidence, and source types separate. |
| R724 | Use device neutral interaction words in instructions. |
| R729 | Use specific action labels such as **Preview**, **Ask about this**, and **Open full source**. |
| R742 | State the cause and next step in error messages. |

## Method sources

The design follows Hamel Husain's
[`LLM Evals FAQ`](https://hamel.dev/blog/posts/evals-faq/), especially the
sections on RAG, multi turn chat, and agentic workflows. It also follows the
[`ai-evals-course/evals-skills`](https://github.com/ai-evals-course/evals-skills)
workflows for RAG evaluation, error discovery, audit, and human review surfaces.
