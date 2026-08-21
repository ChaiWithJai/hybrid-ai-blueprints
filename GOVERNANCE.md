# Project stewardship

PrismML sponsors and stewards Hybrid AI Blueprints. The project name describes
the technical work, while the sponsor line states who funds and maintains the
initial implementation.

## Steward responsibilities

The steward maintains the repository, reviews changes, publishes releases, and
states which claims the evidence supports. The steward also keeps the blueprint
formats open to local and cloud models from more than one provider.

## Technical decisions

Important technical decisions require an architecture decision record in
`docs/decisions/`. A decision record states the problem, the decision, the
alternatives, and the evidence that could change the decision.

## Blueprint ownership

Every blueprint names a maintainer, a use case owner, and an evaluation owner.
One person may fill more than one role during development. A release cannot
claim domain accuracy until a qualified domain owner has approved the task and
reviewed the required evidence.

## Future governance

The catalog graduates from one repository to one repository per blueprint at
roughly ten blueprints or the first sustained external contributor, whichever
comes first. See [ADR 0003](docs/ADR_0003_CATALOG_SCALING_PATTERN.md) for the
rationale. At that point `CATALOG.yaml` becomes generated and this document is
updated to describe per-repository stewardship.

The current repository is sponsored and maintained by PrismML. It is not a
foundation governed project. If outside maintainers begin to share ownership,
the steward will publish a separate governance proposal before changing the
decision process.
