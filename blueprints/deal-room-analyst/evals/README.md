# Deal room analyst evaluation

The evaluation measures whether the complete blueprint finishes three deal
room tasks with useful and reviewable evidence.

## Tasks

The first evaluation covers transaction chronology, financing analysis, and
regulatory analysis. Each task has required output fields and critical failure
conditions in the use case directory.

## Compared routes

Local, cloud, and hybrid routes receive the same source snapshot, question,
evidence packet, output contract, and limits. Reviewers do not see the route or
model name.

## Measures

The evaluation records:

- Task completion
- Material factual accuracy
- Citation correctness and completeness
- Retrieval coverage
- Calculation reproduction
- Treatment of missing information
- Critical errors
- Human correction time and count
- Decision usefulness
- Workflow preference
- Route policy compliance

No weighted score can hide a critical factual, numerical, citation, or routing
failure.

## Evaluation order

First, deterministic checks reject malformed or unsupported output. Second,
qualified reviewers label the remaining outputs. Third, calibrated automated
judges may help classify repeated failures. Human labels remain the authority.

The current repository has development checks and an annotation interface. It
does not have enough qualified blind review to issue an accuracy release.

The detailed implementation remains in
[`docs/FIRST_PASS_UNDERWRITING_BENCHMARK.md`](../../../docs/FIRST_PASS_UNDERWRITING_BENCHMARK.md)
and [`benchmarks/first_pass/`](../app/benchmarks/first_pass/).
