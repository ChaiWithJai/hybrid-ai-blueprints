# Observability stewardship for human error discovery

## Decision

Prism keeps the local review ledger as the source of truth. An operator can
export a privacy limited copy of review telemetry to a local Arize Phoenix
collector. Prism does not send deal room data to a hosted service by default.

OpenTelemetry provides the transport. OpenInference provides the AI tracing
terms that Phoenix understands. Prism records each human review as an
OpenInference `EVALUATOR` span. Prism uses the `prism.eval.*` namespace for
review fields that have no stable upstream standard.

## Why this follows current stewardship

OpenTelemetry is a graduated Cloud Native Computing Foundation project. The
Cloud Native Computing Foundation is part of the Linux Foundation. The
OpenTelemetry GenAI group is defining shared conventions for model, retrieval,
tool, and agent telemetry.

Arize maintains OpenInference as a set of AI tracing conventions that works
with OpenTelemetry. Phoenix accepts OpenTelemetry traces and understands
OpenInference spans. The same instrumentation can therefore work with Phoenix
or another compatible backend.

Prism follows the same approach. The application owns the trace meaning, and
the collector stores and displays the telemetry. An observability vendor does
not own the product record.

## Data policy

The default export includes identifiers, labels, modes, timestamps, and hashes.
It does not include prompts, source text, generated answers, or reviewer notes.

An operator can include content with the `--include-content` option. The option
is explicit because deal room content and review notes can contain private
information. A remote collector also requires the `--allow-remote` option.

## Human and agent boundary

A human review has a Pass, Fail, or Defer label and a free text note. The local
reviewer name is self asserted because this development tool has no identity
provider.

An agent suggestion is a proposal. It does not become human feedback until a
reviewer accepts it. The exported span identifies the feedback source as human
only after the annotation exists in the local ledger.

A synthetic browser or exporter check must use `--fixture`. The exporter then
sets `prism.eval.synthetic_fixture` to true and changes
`prism.eval.feedback.source` to `synthetic_fixture`. The export receipt states
that no human review was performed and that reviewer identity was not verified.

Prism does not claim that a successful export proves reviewer identity, label
quality, deal accuracy, or evaluation saturation.

## Signals

Prism exports one root review session span and one evaluator span for each
human reviewed trace. The records include:

1. The trace record identifier and behavioral stratum.
2. The human label and confirmed failure modes.
3. The review start and update time.
4. Hashes for the reviewed content and the free text note.
5. The content inclusion policy used for the export.

The review application also reports the reviewed count, label counts, corpus
coverage, suggestion decisions, current breadth or depth phase, and whether a
second pass is recommended. Prism does not claim saturation until a larger
review set and a stable discovery rate have been checked.

## Standards boundary

OpenInference currently defines the `EVALUATOR` span kind. Prism uses that
stable term. Proposed names such as `gen_ai.eval.*` and
`gen_ai.task.feedback.*` remain outside the implementation because their
upstream designs are not stable.

The approach follows OpenTelemetry guidance to prototype conventions in real
instrumentation, keep sensitive or expensive fields optional, and avoid adding
new attributes without a clear use case.

## Current verification

The August 18 smoke project contains one root chain span and five evaluator
spans. Phoenix displayed all six spans. The evaluator spans preserved the
OpenInference `EVALUATOR` kind, the synthetic fixture marker, the synthetic
feedback source, and the content hash. Phoenix also displayed
`prism.eval.content.included` as false.

The evidence is stored in
[`phoenix-eval-export-v1.json`](../blueprints/deal-room-analyst/app/evidence/phoenix-eval-export-v1.json) and
[`phoenix-eval-ingestion-v1.json`](../blueprints/deal-room-analyst/app/evidence/phoenix-eval-ingestion-v1.json).
The smoke project contains synthetic data and provides no human or accuracy
evidence.

## Sources

1. [OpenTelemetry GenAI semantic conventions](https://github.com/open-telemetry/semantic-conventions-genai)
2. [OpenTelemetry semantic convention guidance](https://opentelemetry.io/docs/specs/semconv/how-to-write-conventions/)
3. [OpenTelemetry project status at CNCF](https://www.cncf.io/projects/opentelemetry/)
4. [Arize OpenInference](https://github.com/Arize-ai/openinference)
5. [OpenInference semantic conventions](https://github.com/Arize-ai/openinference/blob/main/spec/semantic_conventions.md)
6. [Phoenix tracing and evaluation](https://arize.com/docs/phoenix)
7. [Phoenix local Docker setup](https://arize.com/docs/phoenix/self-hosting/deployment-options/docker)
8. [Arize on traces, evaluations, feedback, and agent access](https://arize.com/blog/from-observability-to-context-whats-next-for-arize-phoenix/)
