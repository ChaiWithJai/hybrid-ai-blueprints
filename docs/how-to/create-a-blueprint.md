# Create a blueprint

## Add the use case

Create `use-cases/<id>/README.md` and `use-case.yaml`. State the user, job,
value unit, task contracts, and required business evidence.

## Add the package

Create `blueprints/<id>/blueprint.yaml`. Pin the model, harness, interface,
evaluation, demos, commands, version, and release claim.

## Add a safe demo

Put the demo manifest under `blueprints/<id>/demos/<demo-id>/`. State whether
the data is synthetic, public, or private. Never commit private customer data.

## Add the evaluation

Name the required tasks, measures, critical failures, blind review method, and
release blockers. Keep deterministic checks separate from human and model based
evaluation.

## Add the catalog entry

Add the use case and blueprint to `CATALOG.yaml`, then run:

```bash
python3 tooling/catalog/validate_catalog.py
```

## Verify the blueprint

Run the blueprint verification command. Record the result under
`evidence/releases/<blueprint>/<version>/` only when every required check has
run against the pinned package.
