# Deal room analyst — application

This directory is the application root and the Python import root. Modules import
`core` and `scripts` directly, and `Path(__file__).resolve().parents[1]` inside
them resolves here.

```
core/        analysis, evaluation, Buzz bridge, evidence   (49 modules)
scripts/     operator entry points, preflight, verification
tests/       unittest suite (526 tests)
web/         browser interface
server.py    API and static server
deal_rooms/  synthetic deal room fixtures
benchmarks/  first-pass underwriting benchmark and framework
evidence/    versioned test and release records
infra/       Buzz compose stack
tools/       operator tooling
prismctl/    control CLI
```

Run and verify from **this** directory:

```bash
python3 scripts/preflight.py --phase host
python3 -m unittest discover -s tests
```

Or via the blueprint wrappers, from anywhere:

```bash
blueprints/deal-room-analyst/scripts/run --port 8787
```

## Why a kebab-case blueprint directory still works

`blueprints/deal-room-analyst/` is not an importable Python package — a hyphen
cannot appear in a module path. That is why the application could not simply
become `blueprints.deal_room_analyst.app.core`. Instead this directory is placed
on `sys.path` and the existing `import core` statements are unchanged; the move
was a coordinated relocation of the whole subtree rather than a rewrite of 124
import sites. See [ADR 0003](../../../docs/ADR_0003_CATALOG_SCALING_PATTERN.md).

## Catalog resources stay at the repository root

`docs/`, `tooling/`, `models/`, `packages/`, `schemas/` and `use-cases/` belong to
the catalog, not to this application. Modules that need them compute

```python
REPO_ROOT = Path(__file__).resolve().parents[4]
```

alongside the application `ROOT`, so app-relative paths stay app-relative.
