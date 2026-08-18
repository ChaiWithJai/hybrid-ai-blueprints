# Deal room analyst

The deal room analyst prepares a source linked first pass underwriting brief
from an authorized M&A folder. The blueprint packages the existing Prism Vault
runtime as the first Hybrid AI Blueprint.

## Job

The blueprint helps a deal professional decide whether to advance, pause, or
stop review and states what should happen next.

[Read the use case](../../use-cases/deal-room-underwriting/README.md).

![Project Titan deal room overview](../../docs/assets/screenshots/deal-room-overview.png)

## Package contents

| Part | Current implementation |
| --- | --- |
| Local model | Bonsai 27B served by LM Studio or Bionic |
| Harness | Parsing, retrieval, calculations, policy routing, and publication in `core/` |
| Interface | Prism browser workspace in `web/` and Buzz collaboration |
| Evaluation | First pass contracts in `benchmarks/first_pass/` and room evaluation tools |
| Demo | Synthetic Project Titan files in `deal_rooms/project_titan_lbo/` |
| Evidence | Local trace ledger, deterministic checks, browser checks, and review records |

The [blueprint manifest](blueprint.yaml) is the canonical package definition.

## Run

From the repository root, check the host:

```bash
blueprints/deal-room-analyst/scripts/preflight
```

Start the blueprint:

```bash
blueprints/deal-room-analyst/scripts/run
```

Open `http://127.0.0.1:8787/rooms/project_titan_lbo/first-pass`.

Follow the [getting started tutorial](../../docs/tutorials/run-the-deal-room-blueprint.md)
for expected output, screenshots, and troubleshooting. The
[architecture guide](../../docs/architecture/README.md) shows the runtime and
evaluation paths.

## Verify

Run the repository tests:

```bash
blueprints/deal-room-analyst/scripts/verify
```

The tests cover software behavior. They do not replace domain review, private
customer testing, cloud comparison, or buyer research.

## Routes

The local route sends the evidence packet to Bonsai on a loopback endpoint.
The cloud route requires an approved HTTPS provider and signed consent. The
hybrid route uses Bonsai for the first draft and an approved cloud model for a
review step.

Cloud and hybrid quality comparisons have not been completed. The interface
must display missing runs as not measured.

## Evaluation

The first evaluation covers transaction chronology, financing analysis, and
regulatory analysis. Reviewers compare local, cloud, and hybrid outputs without
seeing the route name.

[Read the evaluation contract](evals/README.md).

## Demo data

Project Titan is synthetic and safe for a guided product demo. Public filings
support development checks. Neither source is private customer evidence.

[Read the Project Titan demo](demos/project-titan/README.md).

## Current limits

- The local runtime has been tested on one workstation.
- The repository does not bundle Bonsai weights.
- Human domain review is incomplete.
- The benchmark does not contain a valid sealed release set.
- Cloud and hybrid comparisons are not complete.
- The sandbox is not a production isolation boundary.

The [implementation record](IMPLEMENTATION.md) contains the detailed evidence
and earlier engineering history.
