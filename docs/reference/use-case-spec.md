# Use case manifest reference

Each `use-case.yaml` file is JSON formatted YAML so the repository can validate
it without an extra parser.

Required fields are `schema_version`, `id`, `title`, `status`, `job`,
`primary_user`, `value_unit`, `task_contracts`, and `blueprints`.

Every task contract path is relative to the use case manifest. Every blueprint
identifier must exist in `CATALOG.yaml`.
