# Shared packages

Shared packages provide code and contracts that blueprints may adopt as they
mature; a blueprint is not required to use them (see
[ADR 0003](../docs/ADR_0003_CATALOG_SCALING_PATTERN.md)). The first repository
version keeps the working Python modules in `core/` and documents the package
boundaries here. The blueprint manifest points to the canonical source.

Currently adopted by `deal-room-analyst`. `careline-voice-checkin` is
intentionally self-contained; its planned convergence path is `hybrid-router`
first, then `evaluation`.

A later source move must preserve imports, tests, manifests, and release
records. The move must not create a second copy of a component.
