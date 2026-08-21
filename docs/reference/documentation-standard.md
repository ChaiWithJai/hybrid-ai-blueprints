# Documentation standard

Documentation must help a reader complete one task and verify the result. The
repository keeps tutorials, guides, concepts, reference pages, and decisions
separate because each page serves a different need.

## Page types

Use the following page types:

| Page type | Reader need | Required content |
| --- | --- | --- |
| Tutorial | Learn by completing a working path | Result, requirements, ordered commands, expected output, verification, cleanup, troubleshooting |
| Guide | Complete one known task | Preconditions, ordered steps, checks, failure handling |
| Concept | Understand why the system works this way | Scope, design, tradeoffs, links to implementation and decisions |
| Reference | Look up an exact contract | Fields, valid values, defaults, limits, examples |
| Decision | Understand one accepted choice | Context, decision, consequences, status |

Do not combine all page types in one long README. Link to the canonical page
instead of copying the same explanation into several files.

## Getting started pages

A getting started page must include:

1. The result the reader will reach.
2. Supported and unverified environments.
3. Required software and external artifacts.
4. Commands that run from a named directory.
5. Expected output for important checks.
6. A canonical URL or artifact to inspect.
7. A verification command.
8. Cleanup instructions.
9. Troubleshooting for known failures.
10. The claim boundary for demo or benchmark evidence.

Commands must match the current repository. Do not use placeholders when a
working local value exists.

## Screenshots

Screenshots must come from the running application. Use synthetic or approved
public data and record the source commit, route, state, dimensions, and file
hash in a manifest.

Show the state a reader needs to recognize. Do not use a screenshot as the only
place that contains a command, result, warning, or requirement.

## Architecture diagrams

Store architecture diagrams as Mermaid in Markdown so GitHub can render and
review the diagram source. Each diagram must state whether a path works now or
is optional or incomplete.

Link important nodes to the code or manifest that implements them. Use solid
lines for working paths and dotted lines for optional or incomplete paths.

## Writing

Use plain words and complete sentences. Use one name for each concept. Put the
result before background details, and present workflows in the order a reader
will perform them.

Avoid marketing claims. Name the test, source, or review that supports each
capability statement.

## Verification

Every documentation change must pass:

```bash
python3 tooling/documentation/validate_links.py
cd blueprints/deal-room-analyst/app && python3 -m unittest tests.test_documentation_assets tests.test_platform_catalog
```

The link validator runs from the repository root. The unit tests run from the
blueprint application directory, because that is where `tests/` lives and there
is no root test package.

Run the full blueprint verification before a release claim.
