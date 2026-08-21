# Contributing

Contributions should make a use case, blueprint, shared package, example, or
document easier to run and verify.

## Add a blueprint

First, create or select a use case. Second, add the blueprint manifest and its
run commands. Third, add a safe demo and an evaluation contract. Finally, run
the catalog check and the blueprint tests.

A blueprint pull request must include:

- One named job and primary user
- One `blueprint.yaml` manifest
- One safe demo with a clear data classification
- One evaluation contract with failure thresholds
- Negative tests for important guards
- Reproducible run and verification commands
- A list of known limits
- An application inside the blueprint's own `app/` directory, with no
  dependency on `core/` or `server.py`, per
  [ADR 0003](docs/ADR_0003_CATALOG_SCALING_PATTERN.md). The deal room analyst
  predates this rule and is being migrated; do not copy its layout.

Run the repository checks with:

```bash
python3 tooling/catalog/validate_catalog.py
python3 tooling/documentation/validate_links.py
cd blueprints/deal-room-analyst/app && python3 -m unittest discover -s tests
```

## Write documentation

Use plain words and lead with the result. Give each page one main audience and
one purpose. Put tutorials, guides, explanations, and reference pages in their
matching folders. Keep each fact in one canonical document and link to it from
other pages.

The repository writing rules are based on the public
[Mine Writing Rules](https://github.com/docwriter-org/mine-writing-rules)
collection.

Follow the [documentation standard](docs/reference/documentation-standard.md).
Capture public demo images from the blueprint's own running demo fixture and
update that blueprint's screenshot manifest. Keep architecture diagrams in Mermaid and mark
optional or incomplete paths with dotted lines.

Run the documentation link and asset checks before you commit.
