# Blueprint manifest reference

Each `blueprint.yaml` file is JSON formatted YAML. The manifest identifies the
complete agent system used for a run.

Required fields are `schema_version`, `id`, `title`, `version`, `status`,
`use_case`, `model`, `harness`, `interface`, `evaluation`, `demos`, `commands`,
and `release_claim`.

Paths are relative to the blueprint manifest. Commands are relative to the
repository root. A release record must store the manifest hash.
