# Hybrid AI Blueprints

Hybrid AI Blueprints is a catalog of runnable AI agent systems. Each blueprint
combines a model, a harness, an interface, and evaluations for one defined job.

PrismML sponsors and stewards the project. The blueprint contracts remain
model and provider neutral, so a team can compare local, cloud, and hybrid
configurations without changing the task or the grading rules.

## Blueprints in this catalog

Two blueprints. Each one is a job, a model, a harness, an interface, and its own
evaluations. Each has its own preflight, run, and verify commands and a safe
synthetic demo, so you can run either without touching the other.

### Deal room analyst

Reads an authorized M&A folder and prepares a source-linked first-pass
underwriting brief that helps a deal professional decide whether to advance,
pause, or stop review. Bonsai 27B locally, document parsing and evidence
retrieval, reproducible calculations, a shared Buzz workspace, and blind review
with task-specific evaluations.

[![The Project Titan deal room, showing a first pass paused because the model
draft did not satisfy the source rules](docs/assets/screenshots/deal-room-overview.png)](docs/tutorials/run-the-deal-room-blueprint.md)

The synthetic Project Titan demo, paused. "Not Ready To Advance" is the guard
working: the model's draft did not meet the source rules, so the product refuses
to present it as a finished brief rather than advancing quietly.

```bash
blueprints/deal-room-analyst/scripts/preflight
blueprints/deal-room-analyst/scripts/run

# once, in another terminal: give each demo room its own Buzz channel
cd blueprints/deal-room-analyst/app && python3 scripts/seed_fixture_room.py --all
```

Then open `http://127.0.0.1:8787/rooms/project_titan_lbo/first-pass` and select
**Review deal room**. Without the seeding step the page waits on "Opening
workspace", because a catalog room is listed before it has a workspace.

Verified setup: macOS, Python 3, Docker, and LM Studio with Bonsai 27B loaded as
`27b@q1_0`. Its application is stdlib-only Python, so it runs unchanged anywhere
that can reach an OpenAI-compatible model endpoint.

**Read next:** [blueprint README](blueprints/deal-room-analyst/README.md) ·
[tutorial](docs/tutorials/run-the-deal-room-blueprint.md) ·
[demo tour](docs/demo/README.md)

### CareLine voice check-in

Runs a local voice check-in call that remembers earlier calls, detects decline
signals with a deterministic scorer, and escalates concerning calls to a human
care contact. Routine turns go to Bonsai 4B, turns where concern registers to
Bonsai 8B, and post-call fact extraction to ternary Bonsai 27B. It speaks with
on-device speech models and includes a consented self-voice mode. Self-contained
per [ADR 0003](docs/ADR_0003_CATALOG_SCALING_PATTERN.md).

[![The CareLine console during a call: transcript on the left, escalation alerts
with their signals and scores top right, and dated facts recalled from earlier
calls below](docs/assets/screenshots/careline/careline-console.png)](blueprints/careline-voice-checkin/README.md)

A call with Dorothy, a synthetic resident. Three things are visible at once: the
live transcript, one escalation alert naming the exact signals that fired and the
score they produced, and the dated facts the agent carries between calls. The
score, not the model, decides whether a turn escalates.

```bash
blueprints/careline-voice-checkin/scripts/preflight
blueprints/careline-voice-checkin/scripts/run

# in another terminal: three scripted calls that prove the loop
cd blueprints/careline-voice-checkin/app && uv run python scripts/demo_run.py
```

Then open `http://127.0.0.1:8100/` and select **Start call**.

Verified setup: macOS on Apple Silicon, `uv`, `ffmpeg`, `espeak-ng`, and LM
Studio serving Bonsai `4b`, `8b`, and `27b@q1_0`.

**Read next:** [blueprint README](blueprints/careline-voice-checkin/README.md) ·
[voice cloning and fine-tuning](blueprints/careline-voice-checkin/VOICE_CLONE_SETUP.md)

## First time here

```bash
git clone https://github.com/ChaiWithJai/hybrid-ai-blueprints.git
cd hybrid-ai-blueprints
```

Then, in order:

1. **Read [GETTING_STARTED.md](GETTING_STARTED.md).** It records the verified
   path from clone to two running blueprints, plus 28 footguns hit and diagnosed
   on a real machine. Several fail in ways that look like something else: a
   missing `espeak-ng` kills the server process rather than the request, `uv
   sync` removes packages you installed by hand, a room page returns 200 with no
   workspace behind it, and `docker exec psql` cannot verify a password.
2. **Check your machine** against the [hardware matrix](docs/reference/hardware-matrix.md).
   Both blueprints are verified on Apple Silicon. NVIDIA paths exist in code and
   are marked unverified rather than claimed.
3. **Run one blueprint** using the commands above. Run its `preflight` first —
   it names the missing prerequisite instead of failing later inside a request.
4. **Then read the demo tour** for the blueprint you ran, so the screens above
   have names.

## Coming back

| You want to | Go to |
| --- | --- |
| Run the deal room demo end to end | [Tutorial](docs/tutorials/run-the-deal-room-blueprint.md) |
| Understand a screen in the deal room | [Demo tour](docs/demo/README.md) |
| See traces and grade them | [CareLine traces and evaluation](blueprints/careline-voice-checkin/README.md#traces-and-evaluation) |
| Record a voice corpus, fine-tune, and score candidates | [Voice clone setup](blueprints/careline-voice-checkin/VOICE_CLONE_SETUP.md) |
| Size a machine, or move to NVIDIA | [Hardware matrix](docs/reference/hardware-matrix.md) |
| Diagnose a failure you have hit before | [GETTING_STARTED footguns](GETTING_STARTED.md) |
| Add a blueprint of your own | [Create a blueprint](docs/how-to/create-a-blueprint.md) |
| Add or change an evaluation | [Evaluation framework](docs/EVALUATION_FRAMEWORK.md) |
| Refresh a screenshot after a UI change | [Update demo screenshots](docs/how-to/update-demo-screenshots.md) |
| Know what is and is not proven | [Architecture reality matrix](docs/ARCHITECTURE_REALITY_MATRIX.md) |
| Browse everything | [Documentation index](docs/README.md) |

## Hardware

The catalog targets local AI on consumer hardware first, then larger cloud
machines. One host has been measured: an Apple M5 Pro with 48 GB of unified
memory on macOS 26.5. Every number in this repository comes from it.

| Blueprint | Apple Silicon | NVIDIA consumer | NVIDIA cloud (H100 class) |
| --- | --- | --- | --- |
| Deal room analyst | Verified | Expected, unverified. No scanned-PDF OCR | Expected, unverified. No scanned-PDF OCR |
| CareLine voice check-in | Verified | Care mode: implemented via NVIDIA NIM, unverified. Cloned voice: no NVIDIA backend | Same as consumer |

The deal room analyst is portable because its application imports only the
Python standard library and reaches its model over HTTP, so moving hardware
means pointing `PRISM_LOCAL_AI_URL` at a different OpenAI-compatible server.
CareLine puts every model behind a backend seam, so its care-mode call path
moves to NVIDIA NIM microservices through environment variables alone. Those
NIM backends are written but have never been run against an endpoint. The
cloned self-voice has no NVIDIA backend, because both cloning models are
MLX-only.

Ternary quantization is what puts a 27B model on a laptop. Bonsai 27B Q1_0 is
3.54 GB on disk against 16.55 GB for a comparable non-ternary 27B at Q4_K_M.
Weights are not the binding constraint, though: serving that model at a 262,144
token context with four parallel slots held 21.9 GB of resident memory on the
verified host.

Read the [hardware matrix](docs/reference/hardware-matrix.md) for per-model
footprints, memory sizing, the NVIDIA porting path, and what remains unmeasured
on cloud hardware.

## Repository contents

Catalog areas:

| Area | Purpose |
| --- | --- |
| `CATALOG.yaml` | The canonical machine readable list of use cases and blueprints |
| `use-cases/` | Valuable jobs, users, tasks, and economic reasons |
| `blueprints/` | Runnable agent systems with evaluations |
| `models/` | Model cards and supported runtime profiles |
| `packages/` | Shared components a blueprint may adopt |
| `schemas/` | Manifest schemas |
| `tooling/` | Catalog and documentation validators |
| `GETTING_STARTED.md` | Verified setup path and the footguns worth knowing first |
| `docs/` | Tutorials, guides, concepts, reference, and decisions |
| `blueprints/<name>/app/evidence/` | Versioned test and release records |
| `research/` | Source material that motivates use case selection |
| `examples/` | Small integration examples |

Both blueprints now keep their application inside their own directory, as
[ADR 0003](docs/ADR_0003_CATALOG_SCALING_PATTERN.md) requires:

| Area | Purpose |
| --- | --- |
| `blueprints/<name>/app/` | The application, its tests, and its fixtures |
| `blueprints/<name>/scripts/` | `preflight`, `run`, and `verify` wrappers |

Documentation under `docs/` that names a module path such as `core/first_pass.py`
means a path relative to that blueprint's `app/` directory.

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
