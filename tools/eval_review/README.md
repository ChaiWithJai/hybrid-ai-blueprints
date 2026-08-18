# Prism room evaluation

Run the workspace benchmark first. Then start Prism.

```bash
python3 scripts/run_workspace_eval.py
python3 scripts/run_v0.py
```

Open `http://127.0.0.1:8787/rooms/project_titan_lbo/evaluation`.

Evaluation is a native view in each Prism room. It loads a diverse sample from
that room and shows the
surrounding conversation for each selected event. A reviewer chooses Pass,
Fail, or Defer and writes a free text note. Every change is saved to
`.runtime/eval-review/<room>/annotations.json`. Prism also appends a hash
chained revision record to the same room directory.

The review follows two phases. First, the reviewer reads diverse traces. After
five traces have human judgments, the application enables a corpus scan for
the confirmed failure modes. The reviewer can also add another breadth sample
and revisit earlier traces as the review criteria change.

Agent suggestions remain proposals until a reviewer accepts them. The product
does not claim human review, reviewer qualification, or evaluation saturation
from agent suggestions.

## Arize Phoenix

The room view reports the status of a local Phoenix instance. Set the endpoint
when starting Prism.

```bash
PRISM_PHOENIX_ENDPOINT=http://127.0.0.1:6006 \
python3 scripts/run_v0.py
```

Export the current human review records with:

```bash
python3 scripts/export_eval_review_to_phoenix.py
```

Use a separate project and the required fixture marker for a synthetic check:

```bash
python3 scripts/export_eval_review_to_phoenix.py \
  --review-url http://127.0.0.1:8787 \
  --room project_titan_lbo \
  --project prism-error-discovery-smoke \
  --fixture
```

The fixture marker changes the exported feedback source to
`synthetic_fixture`. The receipt also states that no human review was
performed. A fixture export must never share a project with human review.

The exporter uses OpenTelemetry OTLP and OpenInference evaluator spans. The
default export includes hashes and labels, but it excludes trace content and
reviewer notes. See
[`docs/OBSERVABILITY_STEWARDSHIP.md`](../../docs/OBSERVABILITY_STEWARDSHIP.md)
for the data policy and standards boundary.

The integrated room browser check covers rapid saves, reload persistence,
corpus coverage, the depth gate, mobile width, and the Phoenix status. The
review API saves one record at a time, and the client serializes writes. One
reviewer action cannot replace another record's saved annotation.
