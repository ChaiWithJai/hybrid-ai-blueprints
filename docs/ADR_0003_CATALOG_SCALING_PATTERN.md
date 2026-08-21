# ADR 0003: Catalog scaling pattern

**Status:** accepted · **Date:** 2026-08-20

## Decision

The repository stays an integrated monorepo while the catalog is small. Every
new blueprint must be **self-contained under its own directory** (no reaches
into `core/` or `server.py`), so that any blueprint can graduate to its own
repository without modification. When the catalog reaches roughly ten
blueprints or gains its first sustained external contributor, blueprints
graduate to one repository each and `CATALOG.yaml` becomes generated metadata.

## The three patterns we studied

We inspected how three organizations that run use-case catalogs organize them
in git (2026-08-20):

| Org | Pattern | Contract | Catalog | Proven scale |
|---|---|---|---|---|
| NVIDIA (`NVIDIA-AI-Blueprints`, 37 repos) | **Federated org-as-catalog**: one repo per blueprint, no shared code | Service boundary (NIM containers/endpoints) | The org itself, plus a marketing site layered over it | ~40 |
| LangChain | **Scaffold-to-copy**: versioned framework libraries + thin template repos you copy and own | Dependency on versioned packages | Docs site + CLI (`langgraph new`) | Framework-scale |
| HashiCorp / Terraform | **Registry over convention-versioned modules**: one module per repo, strict naming, typed inputs/outputs, automated semver | `variables.tf`/`outputs.tf` schema + version protocol | Generated: the registry crawls repos by convention and tag | Thousands |

The cautionary tale is LangChain's deleted monorepo `templates/` directory:
a template catalog co-located with a fast-moving runtime rots — templates lag,
CI drags, ownership blurs — and they killed it. The lesson: **validation must
travel with the blueprint**, and the catalog must not depend on humans editing
a central file.

## How this repository applies the patterns

1. **Now (≤ ~10 blueprints): monorepo as standards body.** Contracts
   (`use-case.yaml`, task contracts, evaluation thresholds), schemas, and
   validators live here and are the product — our equivalent of Terraform's
   typed module contract. Shared packages under `packages/` are the optional
   runtime, not a requirement for inclusion.
2. **Every blueprint is written as if the repo boundary already existed.**
   Self-contained `app/`, commands relative to the blueprint root, models
   referenced by manifest. `careline-voice-checkin` is the first blueprint
   built this way and is the graduation test case.
3. **At the trigger, graduate.** One repo per blueprint under a naming
   convention (`hab-<blueprint>`), semver tags, and a shared CI action that
   runs these validators inside each blueprint repository. A crawler walks the
   org by convention and emits `CATALOG.yaml`; `web/` becomes a view over the
   generated index. Edge, cloud, and hybrid routes — plus vertical and model
   family — become catalog facets, which is how the hybrid AI narrative is
   browsed at 100 use cases.

## The root directory today does not match this decision

Adding a second blueprint exposed a structural problem that predates it. The
repository root is not a catalog root. It is the deal room application's own
root, which grew a catalog around itself:

| Root entry | What it actually is |
| --- | --- |
| `core/` (98 files) | Deal room application code (`deal_room_analyzer.py`, `doc_parser.py`, `first_pass.py`) |
| `server.py`, `web/` | The deal room server and browser interface |
| `deal_rooms/` | Deal room demo fixtures |
| `benchmarks/`, `scripts/`, `tests/`, `tools/`, `prismctl/`, `infra/` | Predominantly deal room evaluation and operations |

`blueprints/deal-room-analyst/app/` and `harness/` contain a `README.md` each
and no code; they point up at the root. `blueprints/careline-voice-checkin/app/`
contains the real application. So one blueprint **is** the repository and the
other lives inside `blueprints/`. That asymmetry is migration debt, not a
design. An earlier draft of this record described it as "two harness styles
coexisting by design," which rationalized an accident and is withdrawn.

## Target structure

The root holds catalog concerns only. Every blueprint owns its application:

```text
CATALOG.yaml, use-cases/, blueprints/, models/, packages/,
schemas/, tooling/, docs/, evidence/, research/, examples/
```

```text
blueprints/<blueprint>/
    blueprint.yaml, README.md, IMPLEMENTATION.md, CHANGELOG.md
    app/         the application, with its own project file and environment
    demos/       fixtures with a data classification
    evals/       the evaluation contract
    scripts/     preflight, run, verify
```

`careline-voice-checkin` already has this shape and is the reference.

## Why the deal room has not moved yet, and what moving requires

A blueprint directory name is kebab-case because the catalog validator requires
it (`ID_PATTERN`), and a kebab-case directory is not an importable Python
package. The deal room therefore cannot become
`blueprints.deal-room-analyst.app.core` by relocation alone. Each blueprint
application must instead be a standalone project with its own project file and
environment — which is exactly how CareLine is built and why CareLine could be
self-contained on day one.

Measured blast radius for the move: 124 Python files import `core`, 38 more
reference `server.py` or `scripts/`, 8 documents cite root application paths,
and the deal room manifest resolves seven `../../` paths. The deal room also
carries 526 tests. That work is a refactor of a working blueprint and belongs
in its own change, not in a change that adds a different blueprint.

Migration steps, in order:

1. Give the deal room application a project file and environment under
   `blueprints/deal-room-analyst/app/`, mirroring CareLine.
2. Move `core/`, `server.py`, `web/`, `deal_rooms/`, and the deal room parts of
   `benchmarks/`, `scripts/`, and `tests/` into that directory.
3. Rewrite imports to the app's own package root and update the manifest's
   `../../` paths.
4. Move genuinely shared code to `packages/` rather than leaving it in `core/`.
5. Update the repository contents table, the architecture diagrams, and the
   deal room tutorial.

Until step 5 lands, `README.md` states which root entries belong to the deal
room application so that the layout is not presented as a catalog convention.

## Consequences

- New blueprints must be self-contained; `deal-room-analyst` is a documented
  exception with a migration plan, not a second supported pattern.
- `CATALOG.yaml` is hand-maintained until the trigger; the validator keeps it
  honest in the meantime.
- Shared packages that blueprints adopt must eventually be published as
  versioned artifacts rather than imported by relative path.

## Status update (2026-08-21)

The deal room analyst now follows this pattern: its application, tests, and
fixtures live in `blueprints/deal-room-analyst/app/`, with a project file of
its own, and the repository root is a catalog root. See issue #2.

The move was a coordinated relocation rather than an import rewrite. A
kebab-case blueprint directory is not an importable package, so `core/` could
not become `blueprints.deal-room-analyst.app.core`. Instead `app/` is the
import root: all 124 `import core` sites and all 77
`Path(__file__).resolve().parents[1]` computations kept working untouched.
Only resources that cross into the catalog (`docs/`, `tooling/`) needed a
second anchor, `REPO_ROOT = parents[4]`, in six files.
