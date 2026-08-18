# Shared packages

Shared packages provide code and contracts used by more than one blueprint.
The first repository version keeps the working Python modules in `core/` and
documents the package boundaries here. The blueprint manifest points to the
canonical source.

A later source move must preserve imports, tests, manifests, and release
records. The move must not create a second copy of a component.
