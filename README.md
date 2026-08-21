# Hybrid AI Blueprints

Hybrid AI Blueprints is a catalog of runnable AI agent systems. Each blueprint
combines a model, a harness, an interface, and evaluations for one defined job.

PrismML sponsors and stewards the project. The blueprint contracts remain
model and provider neutral, so a team can compare local, cloud, and hybrid
configurations without changing the task or the grading rules.

## Blueprints in this catalog

The catalog holds two blueprints. Each has its own README, preflight, run, and
verify commands, and a safe synthetic demo.

**[Deal room analyst](blueprints/deal-room-analyst/README.md)** reads an
authorized M&A folder and prepares a source linked first pass underwriting
brief that helps a deal professional decide whether to advance, pause, or stop
review. It uses Bonsai 27B locally, document parsing and evidence retrieval,
reproducible calculations, a shared Buzz workspace, and blind review with task
specific evaluations. It runs on the shared runtime (`core/`, `server.py`,
`packages/`).

![Project Titan deal room overview](docs/assets/screenshots/deal-room-overview.png)

The screenshot shows the synthetic Project Titan demo pausing a guarded result
because the model draft did not meet the source rules.

**[CareLine voice check-in](blueprints/careline-voice-checkin/README.md)** runs
a local voice check-in call that remembers earlier calls, detects decline
signals with a deterministic scorer, and escalates concerning calls to a human
care contact. It routes routine turns to a fast 7B model and delicate turns to
Ternary-Bonsai-27B, speaks with on-device speech models, and includes a
consented self-voice mode. It is self-contained per
[ADR 0003](docs/ADR_0003_CATALOG_SCALING_PATTERN.md).

## Get started

Clone the repository:

```bash
git clone https://github.com/ChaiWithJai/hybrid-ai-blueprints.git
cd hybrid-ai-blueprints
```

Each blueprint ships its own host check and run commands.

> **Read [GETTING_STARTED.md](GETTING_STARTED.md) first.** It records the
> verified path from clone to two running blueprints, plus 25 footguns hit and
> diagnosed on a real machine. Several of them fail in ways that look like
> something else: a missing `espeak-ng` kills the server process rather than the
> request, `uv sync` removes packages you installed by hand, silence gets
> returned as HTTP 200, and `docker exec psql` cannot verify a password.

**Deal room analyst** (verified setup: macOS, Python 3, Docker, and LM Studio
with Bonsai 27B loaded as `27b@q1_0`):

```bash
blueprints/deal-room-analyst/scripts/preflight
blueprints/deal-room-analyst/scripts/run
```

Open `http://127.0.0.1:8787/rooms/project_titan_lbo/first-pass`. Project Titan
is synthetic. It demonstrates the workflow, but it does not provide accuracy or
customer evidence. The
[getting started tutorial](docs/tutorials/run-the-deal-room-blueprint.md)
includes expected output, screenshots, verification, cleanup, and
troubleshooting. The [demo tour](docs/demo/README.md) explains each product
view.

**CareLine voice check-in** (verified setup: macOS on Apple Silicon, `uv`,
`ffmpeg`, Ollama):

```bash
blueprints/careline-voice-checkin/scripts/preflight
blueprints/careline-voice-checkin/scripts/run
```

Open `http://127.0.0.1:8100/`. The synthetic Dorothy demo and the verify
regression are described in the
[blueprint README](blueprints/careline-voice-checkin/README.md).

## Repository contents

Catalog areas:

| Area | Purpose |
| --- | --- |
| `CATALOG.yaml` | The canonical machine readable list of use cases and blueprints |
| `blueprints/deal-room-analyst/app/` | The deal room application, its tests, and its fixtures |
| `use-cases/` | Valuable jobs, users, tasks, and economic reasons |
| `blueprints/` | Runnable agent systems with evaluations |
| `models/` | Model cards and supported runtime profiles |
| `packages/` | Shared components a blueprint may adopt |
| `schemas/` | Manifest schemas |
| `tooling/` | Catalog and documentation validators |
| `GETTING_STARTED.md` | Verified setup path and the footguns worth knowing first |
| `docs/` | Tutorials, guides, concepts, reference, and decisions |
| `evidence/` | Versioned test and release records |
| `research/` | Source material that motivates use case selection |
| `examples/` | Small integration examples |

The deal room analyst predates the catalog, so its application still sits at
the repository root instead of inside its blueprint directory:

| Area | Purpose |
| --- | --- |
| `core/` | Deal room application modules |
| `server.py`, `web/` | Deal room server and browser interface |
| `deal_rooms/` | Deal room demo fixtures |
| `benchmarks/`, `tests/`, `scripts/`, `tools/`, `prismctl/`, `infra/` | Deal room evaluations, tests, and operations |

This layout is migration debt rather than a catalog convention. New blueprints
keep their application inside their own directory, as
`blueprints/careline-voice-checkin/` does.
[ADR 0003](docs/ADR_0003_CATALOG_SCALING_PATTERN.md) records the target
structure and the steps that move the deal room into it.

## Why the project evaluates agents

[Agents' Last Exam](https://agents-last-exam.org/) evaluates a complete agent
on long professional tasks. The agent keeps its model, tools, memory, action
loop, and interface. The grader checks whether the work was completed.

Hybrid AI Blueprints follows the same unit of analysis. A model response is one
part of a run. The blueprint is the system under test.

The [economic frontier study](research/agents-last-exam-economic-frontier/README.md)
ranks 153 published Agents' Last Exam tasks by estimated economic value and
agent readiness. The study helps select useful work. It does not prove that a
model or blueprint can complete that work.

## What a blueprint contains

Every blueprint pins:

1. The model and runtime.
2. The harness, tools, and policies.
3. The user interface and deployment profile.
4. The task set and source data contract.
5. The evaluation and human review rules.
6. The release evidence and known limits.

[Read the blueprint concept](docs/concepts/agentic-blueprints.md).

## Architecture

Architecture is per blueprint, in one of two styles recorded in
[ADR 0003](docs/ADR_0003_CATALOG_SCALING_PATTERN.md). The deal room analyst
uses the shared runtime: the working local path connects the browser
workspace, Python server, authorized folder, Bonsai runtime, Buzz relay, and
local evaluation store. Cloud dispatch is optional and requires a configured
HTTPS provider and signed consent. Cloud and hybrid comparisons remain
unmeasured. CareLine is self-contained under its own directory and describes
its architecture in its blueprint README.

[Read the architecture guide](docs/architecture/README.md) for the system
context, request sequence, routing policy, evaluation flow, and repository
boundaries.

## Hybrid AI

Hybrid AI assigns work to local and cloud models under an explicit policy. A
local route can keep private source data on customer controlled hardware. A
cloud route can be used when policy permits it. A hybrid route records which
model handled each step and why.

The project records traces with OpenTelemetry compatible data and uses
OpenInference terms understood by Arize Phoenix. Content export is off by
default. Human feedback remains separate from automated evaluation.

[Read the Hybrid AI architecture](docs/concepts/hybrid-ai.md) and the
[observability and evaluation design](docs/concepts/observability-and-evaluation.md).

## Current status

Both blueprints are local engineering prototypes. The product paths and many
structural checks work, but the repository does not contain enough domain
review, private customer evidence, cloud comparisons, or pricing evidence for
an accuracy or commercial release. Each blueprint records its own status:
[deal room analyst](blueprints/deal-room-analyst/IMPLEMENTATION.md) and
[CareLine voice check-in](blueprints/careline-voice-checkin/IMPLEMENTATION.md).
See also the [release evidence policy](docs/reference/evidence-policy.md).

## Documentation

- [Browse all documentation](docs/README.md)
- [Run the deal room blueprint](docs/tutorials/run-the-deal-room-blueprint.md)
- [Tour the demo](docs/demo/README.md)
- [Understand the architecture](docs/architecture/README.md)
- [Create a blueprint](docs/how-to/create-a-blueprint.md)
- [Read the use case specification](docs/reference/use-case-spec.md)
- [Read the blueprint specification](docs/reference/blueprint-spec.md)
- [Review the platform decision](docs/decisions/0001-hybrid-ai-blueprints-repository.md)
- [Read project stewardship](GOVERNANCE.md)

## Contributing

A new blueprint must name the job, include a safe demo, define its evaluation,
state its limits, and provide commands that another person can run.

See [CONTRIBUTING.md](CONTRIBUTING.md).

## Security and license

Do not commit customer files, credentials, private model weights, or raw traces
that contain confidential content. See [SECURITY.md](SECURITY.md).

No public software license has been selected for this repository. Copyright
and redistribution terms remain reserved until the steward records a license
decision.
