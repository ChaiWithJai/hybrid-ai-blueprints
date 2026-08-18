# Observability and evaluation

Hybrid AI Blueprints records enough information to explain what an agent did,
which route it used, and why an evaluation passed or failed. The local product
record remains the source of truth.

## Project stewardship

[Arize Phoenix](https://arize.com/docs/phoenix) is an open source observability
and evaluation application built by Arize AI and community contributors.
Phoenix accepts OpenTelemetry traces and uses
[OpenInference](https://github.com/Arize-ai/openinference) conventions for AI
operations.

[OpenTelemetry](https://opentelemetry.io/docs/what-is-opentelemetry/) is a Cloud
Native Computing Foundation project. The Cloud Native Computing Foundation is
part of the Linux Foundation ecosystem. OpenTelemetry reached graduated status
in May 2026 after a governance, security, adoption, stability, and documentation
review. [CNCF records the project status](https://www.cncf.io/projects/opentelemetry/).

The Linux Foundation relationship applies to OpenTelemetry through CNCF. The
sources reviewed for this document do not establish Linux Foundation governance
of Arize AI, Phoenix, or OpenInference.

## Working group alignment

The OpenTelemetry Generative AI group develops shared terms for model calls,
retrieval, agents, workflows, plans, and tool execution. Some agent conventions
remain in development, so this project treats them as evolving standards.

The project follows the working group's main practices:

- Record one trace across the full agent run.
- Use spans for model, retrieval, tool, workflow, and evaluation operations.
- Keep provider names separate from model names.
- Record duration, status, errors, and token counts when available.
- Make prompts, answers, source text, and reviewer notes optional.
- Use vendor neutral transport so the collector can change.
- Keep custom fields in a project namespace until an upstream term is stable.

The current implementation uses OpenInference span kinds such as `LLM`, `TOOL`,
`CHAIN`, and `EVALUATOR`. Project specific evaluation fields use the
`prism.eval.*` namespace.

## Phoenix integration

An operator can export a privacy limited copy of evaluation telemetry to a
local Phoenix collector. The default export includes identifiers, labels,
timestamps, modes, and hashes. It excludes prompts, source text, answers, and
reviewer notes.

Phoenix is a view and analysis tool. It does not replace the signed Buzz
records, local trace chain, source snapshot, or benchmark release record.

## Evaluation layers

The project separates:

1. Document fidelity.
2. Retrieval quality.
3. Answer quality.
4. Workflow completion.
5. Human usefulness.
6. Deployment behavior.
7. Business value.

No average score can offset a critical source, number, citation, or policy
failure.

## Human feedback

Human labels remain separate from automated checks and agent suggestions. A
suggestion becomes human feedback only after a reviewer accepts it. Synthetic
browser tests must identify themselves as fixtures and cannot count as human
review.

## Evaluator validation

Deterministic checks use ordinary software tests. A model based evaluator must
be compared with qualified human labels on separate development and test data.
The release report includes true positive rate, true negative rate, parse
failures, and critical false passes.

The detailed implementation and privacy controls are in
[the observability stewardship record](../OBSERVABILITY_STEWARDSHIP.md) and
[the evaluation framework](../EVALUATION_FRAMEWORK.md).

## Sources

- [Phoenix documentation](https://arize.com/docs/phoenix)
- [Phoenix evaluation documentation](https://arize.com/docs/phoenix/evaluation/llm-evals/evaluator-traces)
- [OpenInference repository](https://github.com/Arize-ai/openinference)
- [OpenInference semantic conventions](https://github.com/Arize-ai/openinference/blob/main/spec/semantic_conventions.md)
- [OpenTelemetry project description](https://opentelemetry.io/docs/what-is-opentelemetry/)
- [OpenTelemetry CNCF status](https://www.cncf.io/projects/opentelemetry/)
- [OpenTelemetry GenAI semantic conventions](https://github.com/open-telemetry/semantic-conventions-genai)
- [OpenTelemetry agent span proposal](https://github.com/open-telemetry/semantic-conventions-genai/blob/main/docs/gen-ai/gen-ai-agent-spans.md)
