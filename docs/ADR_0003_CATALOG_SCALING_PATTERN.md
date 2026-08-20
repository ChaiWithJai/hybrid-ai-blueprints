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

## Consequences

- Two harness styles coexist during the monorepo phase (shared-runtime
  blueprints like `deal-room-analyst`, self-contained ones like
  `careline-voice-checkin`). This is accepted and documented per blueprint.
- `CATALOG.yaml` is hand-maintained until the trigger; the validator keeps it
  honest in the meantime.
- Shared packages that blueprints adopt must eventually be published as
  versioned artifacts rather than imported by relative path.
