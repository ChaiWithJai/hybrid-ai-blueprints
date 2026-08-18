#!/usr/bin/env python3
"""Validate the catalog and its local package references without dependencies."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
ID_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
VERSION_PATTERN = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")


def load_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"Missing file: {path.relative_to(ROOT)}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"Invalid JSON formatted YAML: {path.relative_to(ROOT)}: {exc}"
        ) from exc
    if not isinstance(value, dict):
        raise ValueError(f"Expected an object: {path.relative_to(ROOT)}")
    return value


def require_fields(value: dict[str, Any], fields: set[str], label: str) -> None:
    missing = sorted(fields - value.keys())
    if missing:
        raise ValueError(f"{label} is missing fields: {', '.join(missing)}")


def require_id(value: object, label: str) -> str:
    identifier = str(value or "")
    if not ID_PATTERN.fullmatch(identifier):
        raise ValueError(f"{label} has invalid id: {identifier!r}")
    return identifier


def require_path(path: Path, label: str) -> None:
    if not path.exists():
        raise ValueError(f"{label} does not exist: {path.relative_to(ROOT)}")


def resolve_relative(manifest: Path, relative: object, label: str) -> Path:
    if not isinstance(relative, str) or not relative:
        raise ValueError(f"{label} must be a nonempty path")
    path = (manifest.parent / relative).resolve()
    try:
        path.relative_to(ROOT.resolve())
    except ValueError as exc:
        raise ValueError(f"{label} leaves the repository: {relative}") from exc
    require_path(path, label)
    return path


def validate_use_case(path: Path, catalog_blueprints: set[str]) -> str:
    value = load_object(path)
    require_fields(
        value,
        {
            "schema_version",
            "id",
            "title",
            "status",
            "job",
            "primary_user",
            "value_unit",
            "task_contracts",
            "blueprints",
        },
        str(path.relative_to(ROOT)),
    )
    identifier = require_id(value["id"], str(path.relative_to(ROOT)))
    tasks = value["task_contracts"]
    if not isinstance(tasks, list) or not tasks:
        raise ValueError(f"Use case {identifier} needs at least one task contract")
    for task in tasks:
        task_path = resolve_relative(path, task, f"Task contract for {identifier}")
        task_value = load_object(task_path)
        require_fields(
            task_value,
            {"schema_version", "id", "title", "job", "required_output", "critical_failures"},
            str(task_path.relative_to(ROOT)),
        )
        require_id(task_value["id"], str(task_path.relative_to(ROOT)))
    listed = value["blueprints"]
    if not isinstance(listed, list) or not listed:
        raise ValueError(f"Use case {identifier} needs at least one blueprint")
    unknown = sorted(set(map(str, listed)) - catalog_blueprints)
    if unknown:
        raise ValueError(f"Use case {identifier} lists unknown blueprints: {', '.join(unknown)}")
    return identifier


def validate_blueprint(path: Path, catalog_use_cases: set[str]) -> str:
    value = load_object(path)
    require_fields(
        value,
        {
            "schema_version",
            "id",
            "title",
            "version",
            "status",
            "use_case",
            "model",
            "harness",
            "interface",
            "evaluation",
            "demos",
            "commands",
            "release_claim",
        },
        str(path.relative_to(ROOT)),
    )
    identifier = require_id(value["id"], str(path.relative_to(ROOT)))
    if not VERSION_PATTERN.fullmatch(str(value["version"])):
        raise ValueError(f"Blueprint {identifier} has an invalid version")
    if value["use_case"] not in catalog_use_cases:
        raise ValueError(f"Blueprint {identifier} has an unknown use case")

    model = value["model"]
    harness = value["harness"]
    evaluation = value["evaluation"]
    if not isinstance(model, dict) or not isinstance(harness, dict) or not isinstance(evaluation, dict):
        raise ValueError(f"Blueprint {identifier} has an invalid package section")

    resolve_relative(path, model.get("manifest"), f"Model manifest for {identifier}")
    resolve_relative(path, harness.get("source"), f"Harness source for {identifier}")
    resolve_relative(path, harness.get("entrypoint"), f"Entrypoint for {identifier}")
    resolve_relative(path, evaluation.get("contract"), f"Evaluation contract for {identifier}")
    resolve_relative(path, evaluation.get("implementation"), f"Evaluation implementation for {identifier}")

    components = harness.get("components")
    if not isinstance(components, list) or not components:
        raise ValueError(f"Blueprint {identifier} needs at least one shared component")
    for component in components:
        resolve_relative(path, component, f"Shared component for {identifier}")

    demos = value["demos"]
    if not isinstance(demos, list) or not demos:
        raise ValueError(f"Blueprint {identifier} needs at least one demo")
    for demo in demos:
        if not isinstance(demo, dict):
            raise ValueError(f"Blueprint {identifier} has an invalid demo entry")
        demo_path = resolve_relative(path, demo.get("manifest"), f"Demo manifest for {identifier}")
        demo_value = load_object(demo_path)
        require_fields(
            demo_value,
            {"schema_version", "id", "blueprint", "data_classification", "source", "start_url"},
            str(demo_path.relative_to(ROOT)),
        )
        if demo_value["blueprint"] != identifier:
            raise ValueError(f"Demo {demo_value.get('id')} names the wrong blueprint")
        resolve_relative(demo_path, demo_value["source"], f"Demo source for {identifier}")

    commands = value["commands"]
    if not isinstance(commands, dict):
        raise ValueError(f"Blueprint {identifier} has invalid commands")
    for name in ("preflight", "run", "verify"):
        command = commands.get(name)
        if not isinstance(command, str) or not command:
            raise ValueError(f"Blueprint {identifier} is missing the {name} command")
        require_path(ROOT / command, f"{name} command for {identifier}")
    return identifier


def validate() -> dict[str, Any]:
    catalog_path = ROOT / "CATALOG.yaml"
    catalog = load_object(catalog_path)
    require_fields(
        catalog,
        {"schema_version", "project", "sponsor", "steward", "use_cases", "blueprints"},
        "CATALOG.yaml",
    )
    if catalog["project"] != "hybrid-ai-blueprints":
        raise ValueError("CATALOG.yaml has the wrong project name")

    use_case_entries = catalog["use_cases"]
    blueprint_entries = catalog["blueprints"]
    if not isinstance(use_case_entries, list) or not isinstance(blueprint_entries, list):
        raise ValueError("CATALOG.yaml entries must be lists")

    use_case_ids = {require_id(item.get("id"), "Catalog use case") for item in use_case_entries}
    blueprint_ids = {require_id(item.get("id"), "Catalog blueprint") for item in blueprint_entries}
    if len(use_case_ids) != len(use_case_entries):
        raise ValueError("CATALOG.yaml contains duplicate use case ids")
    if len(blueprint_ids) != len(blueprint_entries):
        raise ValueError("CATALOG.yaml contains duplicate blueprint ids")

    validated_use_cases = set()
    for entry in use_case_entries:
        base = ROOT / str(entry.get("path", ""))
        require_path(base / "README.md", f"README for use case {entry.get('id')}")
        identifier = validate_use_case(base / "use-case.yaml", blueprint_ids)
        if identifier != entry["id"]:
            raise ValueError(f"Catalog path for use case {entry['id']} points to {identifier}")
        validated_use_cases.add(identifier)

    validated_blueprints = set()
    for entry in blueprint_entries:
        base = ROOT / str(entry.get("path", ""))
        require_path(base / "README.md", f"README for blueprint {entry.get('id')}")
        manifest = ROOT / str(entry.get("manifest", ""))
        identifier = validate_blueprint(manifest, use_case_ids)
        if identifier != entry["id"]:
            raise ValueError(f"Catalog path for blueprint {entry['id']} points to {identifier}")
        validated_blueprints.add(identifier)

    return {
        "project": catalog["project"],
        "use_cases": sorted(validated_use_cases),
        "blueprints": sorted(validated_blueprints),
    }


def main() -> int:
    try:
        result = validate()
    except ValueError as exc:
        print(f"catalog validation failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps({"status": "passed", **result}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
