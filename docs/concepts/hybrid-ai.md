# Hybrid AI

Hybrid AI uses local and cloud models in one governed system. A routing policy
decides where each step runs, and the trace records the decision.

## Goals

The architecture supports private local work, access to approved cloud models,
and direct comparison between routes. The same task and evaluation apply to
each route.

## Route definitions

The local route sends the approved evidence packet to a model on customer
controlled hardware. The cloud route sends approved content to an HTTPS model
provider after the consent checks pass. The hybrid route uses both and records
which model handled each step.

The first deal room blueprint defines hybrid as a local Bonsai draft followed
by an approved cloud review against the same evidence packet. Later blueprints
may define a different split, but their manifests must state it.

## Routing inputs

The router can use:

- Data classification
- User and data owner consent
- Task type
- Required model capability
- Latency and cost limits
- Deployment policy
- Provider availability

A route failure remains a failure. The system must not replace a failed local
or cloud run with a copied or simulated answer.

## Private data

The local route does not send the evidence packet to a cloud model. A cloud or
hybrid route requires a signed policy decision. Private deal room context also
requires a separate data owner decision.

The current checks enforce this application path. They do not prove a network
air gap, provider trust, complete redaction, or production isolation.

## Evaluation

Reviewers compare route outputs without seeing the model or route name. The
evaluation records quality, time, corrections, cost, and policy compliance.
Missing runs are reported as not measured.

## Observability

Every route should emit the same core trace structure for model calls,
retrieval, tools, workflow steps, and evaluations. Sensitive content remains
optional and off by default.

[Read the observability and evaluation design](observability-and-evaluation.md).
