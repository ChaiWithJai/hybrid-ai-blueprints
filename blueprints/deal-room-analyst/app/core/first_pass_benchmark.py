"""Fail-closed validation for the first pass underwriting benchmark contract."""

from __future__ import annotations

import ast
import hashlib
import json
import math
import re
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

from core.nostr_event import nostr_event_errors


_SUPPORTED_SCHEMA_KEYS = {
    "$defs",
    "$id",
    "$ref",
    "$schema",
    "$comment",
    "additionalProperties",
    "const",
    "default",
    "deprecated",
    "description",
    "enum",
    "examples",
    "exclusiveMaximum",
    "exclusiveMinimum",
    "format",
    "items",
    "maxLength",
    "maximum",
    "minItems",
    "minLength",
    "minimum",
    "oneOf",
    "pattern",
    "properties",
    "readOnly",
    "required",
    "title",
    "type",
    "uniqueItems",
    "writeOnly",
}
_SUPPORTED_SCHEMA_TYPES = {
    "array", "boolean", "integer", "null", "number", "object", "string",
}
_SUPPORTED_SCHEMA_FORMATS = {"date-time"}
_SUPPORTED_META_SCHEMA = "https://json-schema.org/draft/2020-12/schema"


def _schema_number(value: Any) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, int):
        return True
    return isinstance(value, float) and math.isfinite(value)


def _json_equal(left: Any, right: Any) -> bool:
    """Compare values using JSON Schema data model equality."""
    if isinstance(left, bool) or isinstance(right, bool):
        return isinstance(left, bool) and isinstance(right, bool) and left == right
    if _schema_number(left) and _schema_number(right):
        return left == right
    if left is None or right is None:
        return left is None and right is None
    if isinstance(left, str) or isinstance(right, str):
        return isinstance(left, str) and isinstance(right, str) and left == right
    if isinstance(left, list) or isinstance(right, list):
        return (
            isinstance(left, list)
            and isinstance(right, list)
            and len(left) == len(right)
            and all(_json_equal(a, b) for a, b in zip(left, right))
        )
    if isinstance(left, dict) or isinstance(right, dict):
        return (
            isinstance(left, dict)
            and isinstance(right, dict)
            and left.keys() == right.keys()
            and all(_json_equal(left[key], right[key]) for key in left)
        )
    return left == right and type(left) is type(right)


def schema_definition_errors(
    schema: dict[str, Any],
    location: str = "$schema",
) -> list[str]:
    """Reject schema keywords that this local validator does not implement."""
    errors: list[str] = []
    for key in schema:
        if key not in _SUPPORTED_SCHEMA_KEYS:
            errors.append(f"{location}: unsupported schema keyword {key}")

    if "$schema" in schema and schema["$schema"] != _SUPPORTED_META_SCHEMA:
        errors.append(f"{location}.$schema: unsupported JSON Schema dialect")
    if "$ref" in schema and (
        not isinstance(schema["$ref"], str) or not schema["$ref"].startswith("#/")
    ):
        errors.append(f"{location}.$ref: only local JSON Pointer references are supported")

    declared_type = schema.get("type")
    if declared_type is not None:
        type_names = declared_type if isinstance(declared_type, list) else [declared_type]
        if (
            not type_names
            or any(not isinstance(item, str) or item not in _SUPPORTED_SCHEMA_TYPES for item in type_names)
            or len(type_names) != len(set(type_names))
        ):
            errors.append(f"{location}.type: unsupported or invalid type declaration")

    if "format" in schema and schema["format"] not in _SUPPORTED_SCHEMA_FORMATS:
        errors.append(f"{location}.format: unsupported format {schema['format']!r}")
    if "pattern" in schema:
        if not isinstance(schema["pattern"], str):
            errors.append(f"{location}.pattern: pattern must be a string")
        else:
            try:
                re.compile(schema["pattern"])
            except re.error:
                errors.append(f"{location}.pattern: invalid regular expression")

    for key in ("minLength", "maxLength", "minItems"):
        constraint = schema.get(key)
        if constraint is not None and (
            not isinstance(constraint, int) or isinstance(constraint, bool) or constraint < 0
        ):
            errors.append(f"{location}.{key}: value must be a nonnegative integer")
    for key in ("minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum"):
        if key in schema and not _schema_number(schema[key]):
            errors.append(f"{location}.{key}: value must be a number")
    if "uniqueItems" in schema and not isinstance(schema["uniqueItems"], bool):
        errors.append(f"{location}.uniqueItems: value must be boolean")

    required = schema.get("required")
    if required is not None and (
        not isinstance(required, list)
        or any(not isinstance(item, str) for item in required)
        or len(required) != len(set(required))
    ):
        errors.append(f"{location}.required: value must be a unique string array")
    enum = schema.get("enum")
    if enum is not None and (not isinstance(enum, list) or not enum):
        errors.append(f"{location}.enum: value must be a nonempty array")

    for container in ("$defs", "properties"):
        children = schema.get(container)
        if children is not None and (
            not isinstance(children, dict)
            or any(not isinstance(child, dict) for child in children.values())
        ):
            errors.append(f"{location}.{container}: value must map names to schemas")
    items = schema.get("items")
    if items is not None and not isinstance(items, dict):
        errors.append(f"{location}.items: only one item schema is supported")
    additional = schema.get("additionalProperties")
    if additional is not None and not isinstance(additional, (bool, dict)):
        errors.append(f"{location}.additionalProperties: value must be boolean or a schema")
    one_of = schema.get("oneOf")
    if one_of is not None and (
        not isinstance(one_of, list)
        or not one_of
        or any(not isinstance(child, dict) for child in one_of)
    ):
        errors.append(f"{location}.oneOf: value must be a nonempty schema array")

    for container in ("$defs", "properties"):
        children = schema.get(container, {})
        for name, child in children.items() if isinstance(children, dict) else ():
            if isinstance(child, dict):
                errors.extend(schema_definition_errors(child, f"{location}.{container}.{name}"))
    if isinstance(items, dict):
        errors.extend(schema_definition_errors(items, f"{location}.items"))
    if isinstance(additional, dict):
        errors.extend(schema_definition_errors(additional, f"{location}.additionalProperties"))
    for index, child in enumerate(one_of if isinstance(one_of, list) else []):
        if isinstance(child, dict):
            errors.extend(schema_definition_errors(child, f"{location}.oneOf[{index}]"))
    return errors


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _type_matches(value: Any, expected: str) -> bool:
    return {
        "object": isinstance(value, dict),
        "array": isinstance(value, list),
        "string": isinstance(value, str),
        "number": _schema_number(value),
        "integer": (
            isinstance(value, int) and not isinstance(value, bool)
        ) or (
            isinstance(value, float) and math.isfinite(value) and value.is_integer()
        ),
        "boolean": isinstance(value, bool),
        "null": value is None,
    }.get(expected, False)


def _resolve_ref(root: dict[str, Any], reference: str) -> dict[str, Any]:
    if not reference.startswith("#/"):
        raise ValueError(f"unsupported schema reference {reference}")
    value: Any = root
    for token in reference[2:].split("/"):
        value = value[token.replace("~1", "/").replace("~0", "~")]
    return value


def schema_errors(
    value: Any,
    schema: dict[str, Any],
    root: dict[str, Any] | None = None,
    location: str = "$",
    _definition_checked: bool = False,
) -> list[str]:
    """Validate the JSON Schema features used by the checked in contracts."""
    root = root or schema
    errors: list[str] = []
    if not _definition_checked:
        errors.extend(schema_definition_errors(root))
        if errors:
            return errors
    if "$ref" in schema:
        try:
            referenced_schema = _resolve_ref(root, schema["$ref"])
        except (KeyError, TypeError, ValueError):
            errors.append(f"{location}: schema reference cannot be resolved")
        else:
            errors.extend(
                schema_errors(
                    value,
                    referenced_schema,
                    root,
                    location,
                    _definition_checked=True,
                )
            )
    if "oneOf" in schema:
        alternatives = [
            schema_errors(value, item, root, location, _definition_checked=True)
            for item in schema["oneOf"]
        ]
        if sum(not item for item in alternatives) != 1:
            errors.append(f"{location}: value must match exactly one schema alternative")

    expected = schema.get("type")
    if expected:
        choices = expected if isinstance(expected, list) else [expected]
        if not any(_type_matches(value, item) for item in choices):
            errors.append(f"{location}: expected {' or '.join(choices)}")
            return errors

    if "const" in schema and not _json_equal(value, schema["const"]):
        errors.append(f"{location}: value must equal {schema['const']!r}")
    if "enum" in schema and not any(_json_equal(value, item) for item in schema["enum"]):
        errors.append(f"{location}: {value!r} is not an allowed value")
    if value is None:
        return errors
    if isinstance(value, str):
        if len(value) < schema.get("minLength", 0):
            errors.append(f"{location}: string is shorter than the minimum")
        if "maxLength" in schema and len(value) > schema["maxLength"]:
            errors.append(f"{location}: string is longer than the maximum")
        if schema.get("pattern") and not re.search(schema["pattern"], value):
            errors.append(f"{location}: string does not match {schema['pattern']}")
        if schema.get("format") == "date-time":
            try:
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
                if parsed.tzinfo is None or parsed.utcoffset() is None:
                    raise ValueError("date-time lacks a UTC offset")
            except ValueError:
                errors.append(f"{location}: invalid date-time")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            errors.append(f"{location}: number is below the minimum")
        if "maximum" in schema and value > schema["maximum"]:
            errors.append(f"{location}: number is above the maximum")
        if "exclusiveMinimum" in schema and value <= schema["exclusiveMinimum"]:
            errors.append(f"{location}: number is not above the exclusive minimum")
        if "exclusiveMaximum" in schema and value >= schema["exclusiveMaximum"]:
            errors.append(f"{location}: number is not below the exclusive maximum")
    if isinstance(value, list):
        if len(value) < schema.get("minItems", 0):
            errors.append(f"{location}: array has too few items")
        if schema.get("uniqueItems"):
            if any(
                _json_equal(item, other)
                for index, item in enumerate(value)
                for other in value[index + 1:]
            ):
                errors.append(f"{location}: array items are not unique")
        if "items" in schema:
            for index, item in enumerate(value):
                errors.extend(schema_errors(
                    item,
                    schema["items"],
                    root,
                    f"{location}[{index}]",
                    _definition_checked=True,
                ))
    if isinstance(value, dict):
        for field in schema.get("required", []):
            if field not in value:
                errors.append(f"{location}: missing required field {field}")
        properties = schema.get("properties", {})
        extra_fields = value.keys() - properties.keys()
        additional = schema.get("additionalProperties")
        if additional is False:
            for field in extra_fields:
                errors.append(f"{location}: unexpected field {field}")
        elif isinstance(additional, dict):
            for field in extra_fields:
                errors.extend(schema_errors(
                    value[field],
                    additional,
                    root,
                    f"{location}.{field}",
                    _definition_checked=True,
                ))
        for field, item in value.items():
            if field in properties:
                errors.extend(schema_errors(
                    item,
                    properties[field],
                    root,
                    f"{location}.{field}",
                    _definition_checked=True,
                ))
    return errors


def _snapshot_hash(documents: list[dict[str, Any]]) -> str:
    payload = {
        item["filename"]: item["sha256"]
        for item in sorted(documents, key=lambda item: item["filename"])
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def validate_contract(root: Path) -> dict[str, Any]:
    from core.benchmark_governance import scope_approved, validate_benchmark_governance
    from core.candidate_case_registration import (
        validate_approval_ledger,
        validate_registration_ledger,
    )

    root = root.resolve()
    contract_dir = root / "benchmarks" / "first_pass"
    paths = {
        "manifest": contract_dir / "benchmark_manifest.v2.json",
        "registry": contract_dir / "development_registry.v2.json",
        "case_schema": contract_dir / "case.schema.json",
        "rubric": contract_dir / "rubric.v1.json",
        "source_manifest": root / "benchmarks" / "public_deal_corpus_manifest.json",
        "source_evidence": root / "evidence" / "public-deal-corpus-verification-v2.json",
        "candidate_sources": contract_dir / "candidate_deal_sources.v1.json",
        "candidate_companion_sources": contract_dir / "candidate_companion_sources.v1.json",
        "candidate_question_drafts": contract_dir / "candidate_question_drafts.v1.json",
        "source_reviewer_roster": contract_dir / "source_reviewer_roster.v1.json",
        "source_reviewer_roster_schema": contract_dir / "source_reviewer_roster.schema.json",
        "output_reviewer_roster": contract_dir / "output_reviewer_roster.v1.json",
        "output_reviewer_roster_schema": contract_dir / "output_reviewer_roster.schema.json",
        "candidate_approval_ledger": contract_dir / "candidate_case_approval_records.v1.json",
        "candidate_registration_ledger": contract_dir / "candidate_case_registrations.v1.json",
        "sealed_test_public_manifest": contract_dir / "sealed_test_manifest.v1.json",
        "sealed_test_public_manifest_schema": contract_dir / "sealed_test_manifest.schema.json",
        "sealed_test_control": contract_dir / "sealed_test_control.v1.json",
        "sealed_test_control_schema": contract_dir / "sealed_test_control.schema.json",
        "benchmark_governance": contract_dir / "benchmark_governance.v1.json",
    }
    loaded = {name: json.loads(path.read_text(encoding="utf-8")) for name, path in paths.items()}
    manifest = loaded["manifest"]
    registry = loaded["registry"]
    case_schema = loaded["case_schema"]
    source_manifest = loaded["source_manifest"]
    source_evidence = loaded["source_evidence"]
    candidate_sources = loaded["candidate_sources"]
    candidate_companion_sources = loaded["candidate_companion_sources"]
    candidate_question_drafts = loaded["candidate_question_drafts"]
    source_reviewer_roster = loaded["source_reviewer_roster"]
    source_reviewer_roster_schema = loaded["source_reviewer_roster_schema"]
    output_reviewer_roster = loaded["output_reviewer_roster"]
    output_reviewer_roster_schema = loaded["output_reviewer_roster_schema"]
    approval_ledger = loaded["candidate_approval_ledger"]
    registration_ledger = loaded["candidate_registration_ledger"]
    sealed_public_manifest = loaded["sealed_test_public_manifest"]
    sealed_public_schema = loaded["sealed_test_public_manifest_schema"]
    sealed_control = loaded["sealed_test_control"]
    sealed_control_schema = loaded["sealed_test_control_schema"]
    governance = validate_benchmark_governance(root, loaded["benchmark_governance"])
    approval_result = validate_approval_ledger(root, approval_ledger)
    registration_result = validate_registration_ledger(root, registration_ledger)
    cases = [*registry.get("cases", []), *registration_result["cases"]]
    structural_errors: list[str] = []
    structural_errors.extend(approval_result["errors"])
    structural_errors.extend(registration_result["errors"])
    structural_errors.extend(governance["errors"])
    structural_errors.extend(
        schema_errors(
            sealed_public_manifest,
            sealed_public_schema,
            sealed_public_schema,
            "$.sealed_test_public_manifest",
        )
    )
    structural_errors.extend(
        schema_errors(
            sealed_control,
            sealed_control_schema,
            sealed_control_schema,
            "$.sealed_test_control",
        )
    )
    if sealed_public_manifest.get("benchmark_id") != manifest.get("benchmark_id"):
        structural_errors.append("sealed public manifest benchmark ID differs")
    if sealed_public_manifest.get("benchmark_version") != manifest.get("version"):
        structural_errors.append("sealed public manifest benchmark version differs")
    sealed_public_cases = sealed_public_manifest.get("cases", [])
    if sealed_public_manifest.get("state") == "not_registered" and sealed_public_cases:
        structural_errors.append("unregistered sealed manifest contains cases")
    if sealed_public_manifest.get("state") == "registered_unopened" and len(sealed_public_cases) != manifest["target"]["splits"]["sealed_test"]["cases"]:
        structural_errors.append("registered sealed manifest does not contain the target case count")
    if sealed_control.get("benchmark_id") != manifest.get("benchmark_id"):
        structural_errors.append("sealed control benchmark ID differs")
    if sealed_control.get("benchmark_version") != manifest.get("version"):
        structural_errors.append("sealed control benchmark version differs")
    public_binding = sealed_control.get("public_manifest", {})
    if public_binding.get("path") != "benchmarks/first_pass/sealed_test_manifest.v1.json":
        structural_errors.append("sealed control public manifest path differs")
    elif public_binding.get("sha256") != sha256(paths["sealed_test_public_manifest"]):
        structural_errors.append("sealed control public manifest hash differs")
    recorded_approval_ids = {
        item.get("approval_id") for item in approval_result["approvals"]
    }
    registered_approval_ids = {
        item.get("approval_id") for item in registration_ledger.get("registrations", [])
    }
    if not registered_approval_ids.issubset(recorded_approval_ids):
        structural_errors.append("candidate registrations exist without recorded approvals")
    registered_candidate_case_ids = {
        item.get("case_id") for item in registration_ledger.get("registrations", [])
    }
    registered_candidate_ids = {
        item.get("candidate_id") for item in registration_ledger.get("registrations", [])
    }
    registered_candidate_draft_ids = {
        item.get("draft_id") for item in registration_ledger.get("registrations", [])
    }

    structural_errors.extend(
        schema_errors(
            source_reviewer_roster,
            source_reviewer_roster_schema,
            source_reviewer_roster_schema,
            "$.source_reviewer_roster",
        )
    )
    reviewer_ids = [
        item.get("reviewer_id")
        for item in source_reviewer_roster.get("reviewers", [])
        if isinstance(item, dict)
    ]
    if len(reviewer_ids) != len(set(reviewer_ids)):
        structural_errors.append("source reviewer roster IDs are not unique")
    structural_errors.extend(
        schema_errors(
            output_reviewer_roster,
            output_reviewer_roster_schema,
            output_reviewer_roster_schema,
            "$.output_reviewer_roster",
        )
    )
    output_reviewer_ids = [
        item.get("reviewer_id")
        for item in output_reviewer_roster.get("reviewers", [])
        if isinstance(item, dict)
    ]
    if len(output_reviewer_ids) != len(set(output_reviewer_ids)):
        structural_errors.append("output reviewer roster IDs are not unique")

    target = manifest["target"]
    if sum(item["cases"] for item in target["splits"].values()) != target["cases"]:
        structural_errors.append("target split counts do not add up to the case target")
    if sum(target["task_families"].values()) != target["cases"]:
        structural_errors.append("target task family counts do not add up to the case target")
    if sum(item["minimum_deals"] for item in target["splits"].values()) != target["minimum_deals"]:
        structural_errors.append("target split deal counts do not add up to the deal target")
    if registry.get("benchmark_id") != manifest.get("benchmark_id"):
        structural_errors.append("registry and manifest benchmark IDs differ")
    expected_inventory_sources = {
        "base_case_registry": "development_registry.v2.json",
        "candidate_approval_ledger": "candidate_case_approval_records.v1.json",
        "candidate_registration_ledger": "candidate_case_registrations.v1.json",
        "candidate_deal_sources": "candidate_deal_sources.v1.json",
        "candidate_companion_sources": "candidate_companion_sources.v1.json",
        "candidate_question_drafts": "candidate_question_drafts.v1.json",
        "sealed_test_public_manifest": "sealed_test_manifest.v1.json",
        "sealed_test_control": "sealed_test_control.v1.json",
        "benchmark_governance": "benchmark_governance.v1.json",
        "source_manifest": "../public_deal_corpus_manifest.json",
    }
    if manifest.get("inventory_sources") != expected_inventory_sources:
        structural_errors.append("manifest inventory sources differ from the executable contract")
    candidates = candidate_sources.get("candidates", [])
    candidate_ids = [item.get("id") for item in candidates if isinstance(item, dict)]
    candidate_accessions = [item.get("accession") for item in candidates if isinstance(item, dict)]
    if candidate_sources.get("status") != "research_inventory_not_benchmark_data":
        structural_errors.append("candidate source registry has an invalid status")
    if len(candidate_ids) != len(set(candidate_ids)):
        structural_errors.append("candidate source IDs are not unique")
    if len(candidate_accessions) != len(set(candidate_accessions)):
        structural_errors.append("candidate SEC accessions are not unique")
    forbidden_candidate_fields = {
        "split", "question", "label", "required_claims", "domain_review", "approved"
    }
    candidate_acquisitions: dict[str, dict[str, Any]] = {}
    for index, candidate in enumerate(candidates):
        if not isinstance(candidate, dict):
            structural_errors.append(f"candidate {index}: record is not an object")
            continue
        missing_candidate_fields = {
            "id", "company", "cik", "accession", "filing_date", "filing_url", "state"
        } - candidate.keys()
        if missing_candidate_fields:
            structural_errors.append(
                f"candidate {index}: missing fields {sorted(missing_candidate_fields)}"
            )
        if forbidden_candidate_fields & candidate.keys():
            structural_errors.append(f"candidate {index}: contains benchmark case or approval fields")
        state = candidate.get("state")
        if state not in {
            "source_index_identified_not_acquired",
            "acquired_parser_verified_not_registered",
        }:
            structural_errors.append(f"candidate {index}: invalid source state")
        if not re.fullmatch(r"\d{10}", str(candidate.get("cik", ""))):
            structural_errors.append(f"candidate {index}: invalid SEC CIK")
        if not re.fullmatch(r"\d{10}-\d{2}-\d{6}", str(candidate.get("accession", ""))):
            structural_errors.append(f"candidate {index}: invalid SEC accession")
        if not str(candidate.get("filing_url", "")).startswith(
            "https://www.sec.gov/Archives/edgar/data/"
        ):
            structural_errors.append(f"candidate {index}: filing URL is not an SEC archive URL")
        evidence_fields = {"evidence_path", "evidence_sha256"}
        if state == "source_index_identified_not_acquired":
            if evidence_fields & candidate.keys():
                structural_errors.append(f"candidate {index}: unacquired source has evidence fields")
        elif state == "acquired_parser_verified_not_registered":
            if not evidence_fields.issubset(candidate):
                structural_errors.append(f"candidate {index}: acquired source lacks evidence fields")
            else:
                evidence_path = (root / str(candidate["evidence_path"])).resolve()
                try:
                    evidence_path.relative_to(root)
                    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
                except (ValueError, OSError, json.JSONDecodeError) as exc:
                    structural_errors.append(f"candidate {index}: acquisition evidence unavailable: {exc}")
                else:
                    if sha256(evidence_path) != candidate["evidence_sha256"]:
                        structural_errors.append(f"candidate {index}: acquisition evidence hash differs")
                    if (
                        evidence.get("verification_kind") != "candidate_source_acquisition"
                        or evidence.get("candidate_id") != candidate.get("id")
                        or evidence.get("benchmark_case_registered") is not False
                        or evidence.get("parser", {}).get("passed") is not True
                    ):
                        structural_errors.append(f"candidate {index}: acquisition evidence is not valid")
                    else:
                        candidate_acquisitions[str(candidate.get("id"))] = evidence

    companions = candidate_companion_sources.get("companions", [])
    companion_ids = [
        item.get("candidate_id") for item in companions if isinstance(item, dict)
    ]
    companion_accessions = [
        item.get("accession") for item in companions if isinstance(item, dict)
    ]
    if candidate_companion_sources.get("status") != "research_inventory_not_benchmark_data":
        structural_errors.append("candidate companion source registry has an invalid status")
    if candidate_companion_sources.get("candidate_count") != len(candidates):
        structural_errors.append("candidate companion source candidate count differs")
    if candidate_companion_sources.get("companion_count") != len(companions):
        structural_errors.append("candidate companion source count differs")
    if len(companion_ids) != len(set(companion_ids)):
        structural_errors.append("candidate companion source IDs are not unique")
    if set(companion_ids) != set(candidate_ids):
        structural_errors.append("candidate companion sources do not cover every candidate deal")
    if len(companion_accessions) != len(set(companion_accessions)):
        structural_errors.append("candidate companion SEC accessions are not unique")
    companion_acquisitions: dict[str, dict[str, Any]] = {}
    for index, companion in enumerate(companions):
        if not isinstance(companion, dict):
            structural_errors.append(f"candidate companion {index}: record is not an object")
            continue
        candidate_id = str(companion.get("candidate_id", ""))
        if companion.get("benchmark_case_registered") is not False:
            structural_errors.append(f"candidate companion {index}: claims benchmark registration")
        if companion.get("domain_review_status") != "not_reviewed":
            structural_errors.append(f"candidate companion {index}: claims domain review")
        if companion.get("form") not in {"10-K", "10-Q"}:
            structural_errors.append(f"candidate companion {index}: unsupported filing form")
        if companion.get("state") != "acquired_parser_verified_not_registered":
            structural_errors.append(f"candidate companion {index}: source is not acquired")
            continue
        required_fields = {
            "source_path", "source_bytes", "source_sha256", "evidence_path",
            "evidence_sha256", "parser_table_count", "parser_anchor_count",
        }
        if not required_fields.issubset(companion):
            structural_errors.append(f"candidate companion {index}: acquired source lacks evidence fields")
            continue
        evidence_path = (root / str(companion["evidence_path"])).resolve()
        try:
            evidence_path.relative_to(root)
            evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
        except (ValueError, OSError, json.JSONDecodeError) as exc:
            structural_errors.append(
                f"candidate companion {index}: acquisition evidence unavailable: {exc}"
            )
            continue
        if sha256(evidence_path) != companion.get("evidence_sha256"):
            structural_errors.append(f"candidate companion {index}: evidence hash differs")
        source = evidence.get("source", {})
        parser = evidence.get("parser", {})
        if (
            evidence.get("verification_kind") != "candidate_companion_source_acquisition"
            or evidence.get("candidate_id") != candidate_id
            or evidence.get("benchmark_case_registered") is not False
            or evidence.get("domain_review_status") != "not_reviewed"
            or parser.get("passed") is not True
            or parser.get("product_file_limit_bytes") != 10 * 1024 * 1024
            or source.get("path") != companion.get("source_path")
            or source.get("bytes") != companion.get("source_bytes")
            or source.get("sha256") != companion.get("source_sha256")
            or parser.get("table_count") != companion.get("parser_table_count")
            or parser.get("anchor_count") != companion.get("parser_anchor_count")
        ):
            structural_errors.append(
                f"candidate companion {index}: acquisition evidence is not valid"
            )
        else:
            companion_acquisitions[candidate_id] = evidence
    if candidate_companion_sources.get("acquired_count") != len(companion_acquisitions):
        structural_errors.append("candidate companion acquired count differs")
    if candidate_companion_sources.get("parser_verified_count") != len(companion_acquisitions):
        structural_errors.append("candidate companion parser verified count differs")

    drafts = candidate_question_drafts.get("drafts", [])
    if candidate_question_drafts.get("status") != "evidence_candidates_not_benchmark_cases":
        structural_errors.append("candidate question draft registry has an invalid status")
    if candidate_question_drafts.get("benchmark_case_registered") is not False:
        structural_errors.append("candidate question drafts claim benchmark registration")
    if candidate_question_drafts.get("domain_review_status") != "not_reviewed":
        structural_errors.append("candidate question drafts claim domain review")
    if candidate_question_drafts.get("source_registry_sha256") != sha256(paths["candidate_sources"]):
        structural_errors.append("candidate question drafts are not bound to the source registry")
    if candidate_question_drafts.get("companion_source_registry_sha256") != sha256(
        paths["candidate_companion_sources"]
    ):
        structural_errors.append(
            "candidate question drafts are not bound to the companion source registry"
        )
    if candidate_question_drafts.get("draft_count") != len(drafts):
        structural_errors.append("candidate question draft count does not match its records")
    if candidate_question_drafts.get("candidate_deal_count") != len(candidate_acquisitions):
        structural_errors.append("candidate question deal count does not match acquired candidates")
    draft_ids = [item.get("id") for item in drafts if isinstance(item, dict)]
    if len(draft_ids) != len(set(draft_ids)):
        structural_errors.append("candidate question draft IDs are not unique")
    question_family_records = [
        item for item in candidate_question_drafts.get("question_families", [])
        if isinstance(item, dict)
    ]
    expected_families = {item.get("id") for item in question_family_records}
    family_source_kinds = {
        item.get("id"): item.get("source_kind") for item in question_family_records
    }
    family_task_families = {
        item.get("id"): item.get("task_family") for item in question_family_records
    }
    if any(kind not in {"proxy", "financial", "multi"} for kind in family_source_kinds.values()):
        structural_errors.append("candidate question family has an invalid source kind")
    if any(
        family not in target["task_families"]
        for family in family_task_families.values()
    ):
        structural_errors.append("candidate question family has an invalid task family")
    candidate_records = {item.get("id"): item for item in candidates}
    companion_records = {item.get("candidate_id"): item for item in companions}
    drafts_by_candidate: dict[str, set[str]] = {}
    for index, draft in enumerate(drafts):
        if not isinstance(draft, dict):
            structural_errors.append(f"candidate draft {index}: record is not an object")
            continue
        candidate_id = str(draft.get("candidate_id", ""))
        question_family = str(draft.get("question_family", ""))
        source_kind = family_source_kinds.get(question_family)
        if draft.get("task_family") != family_task_families.get(question_family):
            structural_errors.append(
                f"candidate draft {index}: task family differs from its question family"
            )
        admitted = {
            "proxy": (
                candidate_records.get(candidate_id, {}),
                candidate_acquisitions.get(candidate_id),
            ),
            "financial": (
                companion_records.get(candidate_id, {}),
                companion_acquisitions.get(candidate_id),
            ),
        }
        admitted_kinds = (
            ("proxy", "financial") if source_kind == "multi" else (source_kind,)
        )
        expected_source_pairs = [admitted.get(kind, ({}, None)) for kind in admitted_kinds]
        drafts_by_candidate.setdefault(candidate_id, set()).add(str(draft.get("question_family", "")))
        if any(acquisition is None for _, acquisition in expected_source_pairs):
            structural_errors.append(
                f"candidate draft {index}: admitted {source_kind or 'unknown'} source is not acquired"
            )
            continue
        if draft.get("state") != "source_anchored_question_draft_not_registered":
            structural_errors.append(f"candidate draft {index}: invalid draft state")
        if draft.get("benchmark_case_registered") is not False:
            structural_errors.append(f"candidate draft {index}: claims benchmark registration")
        if draft.get("domain_review_status") != "not_reviewed":
            structural_errors.append(f"candidate draft {index}: claims domain review")
        if draft.get("expected_answer") is not None or draft.get("labels") != []:
            structural_errors.append(f"candidate draft {index}: contains an answer or labels")
        if {"split", "required_claims", "approved", "release_decision"} & draft.keys():
            structural_errors.append(f"candidate draft {index}: contains benchmark case fields")
        sources = draft.get("sources", [])
        if not isinstance(sources, list):
            sources = []
        expected_sources = []
        for source_record, acquisition in expected_source_pairs:
            acquired_source = acquisition.get("source", {}) if acquisition else {}
            expected_sources.append({
                "filename": Path(str(acquired_source.get("path", ""))).name,
                "sha256": acquired_source.get("sha256"),
                "acquisition_evidence_path": source_record.get("evidence_path"),
                "acquisition_evidence_sha256": source_record.get("evidence_sha256"),
            })
        if sources != expected_sources or draft.get("source") != (expected_sources or [{}])[0]:
            structural_errors.append(f"candidate draft {index}: source binding differs")
        admitted_by_filename = {item.get("filename"): item for item in expected_sources}
        evidence_candidates = draft.get("evidence_candidates", [])
        if not evidence_candidates:
            structural_errors.append(f"candidate draft {index}: has no evidence candidates")
        for passage_index, passage in enumerate(evidence_candidates):
            citation_filename = str(passage.get("citation", "")).split("#", 1)[0].lstrip("[")
            admitted_source = admitted_by_filename.get(citation_filename, {})
            citation = f"[{citation_filename}#{passage.get('anchor')}]"
            if (
                passage.get("citation") != citation
                or passage.get("source_sha256") != admitted_source.get("sha256")
                or not passage.get("retrieval_query")
                or not passage.get("excerpt")
                or len(str(passage.get("excerpt", ""))) > 700
            ):
                structural_errors.append(
                    f"candidate draft {index} evidence {passage_index}: invalid source candidate"
                )
        observed_evidence_sources = {
            item.get("source_sha256") for item in evidence_candidates if isinstance(item, dict)
        }
        if source_kind == "multi" and observed_evidence_sources != {
            item.get("sha256") for item in expected_sources
        }:
            structural_errors.append(
                f"candidate draft {index}: cross-document evidence does not cover both sources"
            )
    for candidate_id in candidate_acquisitions:
        if drafts_by_candidate.get(candidate_id) != expected_families:
            structural_errors.append(
                f"{candidate_id}: candidate question family coverage is incomplete"
            )
    if source_evidence.get("manifest_sha256") != sha256(paths["source_manifest"]):
        structural_errors.append("source evidence is not bound to the current source manifest")
    if source_evidence.get("schema") != "prism.public_deal_battletest.evidence.v2":
        structural_errors.append("source evidence does not use the required v2 schema")
    if source_evidence.get("acceptance", {}).get("ingestion_gate_passed") is not True:
        structural_errors.append("saved source ingestion evidence did not pass")
    render_check = source_evidence.get("automated_pdf_render_check", {})
    render_documents = render_check.get("documents", [])
    if not (
        render_check.get("passed") is True
        and isinstance(render_documents, list)
        and render_documents
        and all(item.get("passed") is True for item in render_documents)
    ):
        structural_errors.append("source evidence lacks a passing automated PDF render check")
    visual_review = source_evidence.get("pdf_visual_review", {})
    if not (
        visual_review.get("state") == "not_recorded"
        and visual_review.get("passed") is None
        and visual_review.get("reviewer") is None
        and visual_review.get("receipt") is None
    ):
        structural_errors.append(
            "source evidence claims or ambiguously records a human PDF visual review"
        )
    source_fact_records = {
        item.get("case_id"): item
        for item in source_evidence.get("source_facts", {}).get("cases", [])
    }

    case_ids = [case.get("id") for case in cases]
    if len(case_ids) != len(set(case_ids)):
        structural_errors.append("case IDs are not unique")
    documents_by_filename: dict[str, list[dict[str, Any]]] = {}
    all_source_documents = [
        *source_manifest["documents"], *registration_result["documents"],
    ]
    for document in all_source_documents:
        documents_by_filename.setdefault(document["filename"], []).append(document)

    deal_splits: dict[str, set[str]] = {}
    near_duplicate_splits: dict[str, set[str]] = {}
    family_counts: Counter[str] = Counter()
    split_counts: Counter[str] = Counter()
    split_deals: dict[str, set[str]] = {}
    approved_count = 0
    observed_deals = set()
    for index, case in enumerate(cases):
        structural_errors.extend(
            schema_errors(case, case_schema, case_schema, f"$.cases[{index}]")
        )
        case_id = case.get("id", f"case-{index}")
        split = case.get("split")
        deal_id = case.get("deal_id")
        observed_deals.add(deal_id)
        deal_splits.setdefault(str(deal_id), set()).add(str(split))
        near_duplicate = case.get("near_duplicate_family_id")
        if near_duplicate:
            near_duplicate_splits.setdefault(str(near_duplicate), set()).add(str(split))
        split_counts[str(split)] += 1
        split_deals.setdefault(str(split), set()).add(str(deal_id))
        family_counts[str(case.get("task_family"))] += 1

        citation_ids = [item.get("id") for item in case.get("required_citations", [])]
        claim_ids = [item.get("id") for item in case.get("required_claims", [])]
        if len(citation_ids) != len(set(citation_ids)):
            structural_errors.append(f"{case_id}: citation IDs are not unique")
        if len(claim_ids) != len(set(claim_ids)):
            structural_errors.append(f"{case_id}: claim IDs are not unique")
        structural_errors.extend(calculation_contract_errors(case))
        admitted_citations = set(citation_ids)
        fact_record = source_fact_records.get(case_id)
        if case_id not in registered_candidate_case_ids:
            if not fact_record or fact_record.get("passed") is not True:
                structural_errors.append(f"{case_id}: no passing source anchor evidence")
            else:
                verified_anchors = {
                    (item.get("filename"), item.get("anchor"))
                    for item in fact_record.get("citation_checks", [])
                    if item.get("passed") is True
                }
                required_anchors = {
                    (item.get("filename"), item.get("anchor"))
                    for item in case.get("required_citations", [])
                }
                if not required_anchors.issubset(verified_anchors):
                    structural_errors.append(f"{case_id}: required anchor lacks passing source evidence")
        elif fact_record and fact_record.get("passed") is not True:
            structural_errors.append(f"{case_id}: conflicting saved source evidence failed")
        for claim in case.get("required_claims", []):
            unknown = set(claim.get("citation_ids", [])) - admitted_citations
            if unknown:
                structural_errors.append(f"{case_id}: claim references unknown citations {sorted(unknown)}")

        cited_documents = []
        citation_rooms = set()
        for citation in case.get("required_citations", []):
            matches = [
                item for item in documents_by_filename.get(citation.get("filename"), [])
                if item.get("sha256") == citation.get("source_sha256")
            ]
            if len(matches) != 1:
                structural_errors.append(
                    f"{case_id}: citation source is absent or ambiguous in the source manifest"
                )
                continue
            cited_documents.extend(matches)
            citation_rooms.add(matches[0]["room"])
        if len(citation_rooms) != 1:
            structural_errors.append(f"{case_id}: citations do not resolve to one deal room")
        elif cited_documents:
            room = next(iter(citation_rooms))
            room_documents = [item for item in all_source_documents if item["room"] == room]
            if case.get("source_snapshot_sha256") != _snapshot_hash(room_documents):
                structural_errors.append(f"{case_id}: source snapshot hash does not match its deal room")

        review = case.get("domain_review", {})
        status = review.get("status")
        if status == "approved":
            approved_count += 1
            if not review.get("owner") or not review.get("reviewed_at"):
                structural_errors.append(f"{case_id}: approved review lacks owner or date")
        elif status == "not_reviewed" and (review.get("owner") or review.get("reviewed_at")):
            structural_errors.append(f"{case_id}: unreviewed case has approval metadata")

    for deal_id, splits in deal_splits.items():
        if len(splits) != 1:
            structural_errors.append(f"{deal_id}: one deal appears in multiple splits")
    for family_id, splits in near_duplicate_splits.items():
        if len(splits) != 1:
            structural_errors.append(
                f"{family_id}: one near-duplicate family appears in multiple splits"
            )

    expected_inventory = {
        "registered_cases": len(cases),
        "registered_deals": len(observed_deals),
        "development_cases": split_counts["development"],
            "calibration_cases": split_counts["calibration"],
            "calibration_deals": len(split_deals.get("calibration", set())),
            "sealed_test_cases": split_counts["sealed_test"],
        "domain_approved_cases": approved_count,
    }
    not_acquired_count = sum(
        item.get("state") == "source_index_identified_not_acquired" for item in candidates
    )
    acquired_unregistered_count = sum(
        item.get("state") == "acquired_parser_verified_not_registered"
        and item.get("id") not in registered_candidate_ids
        for item in candidates
    )
    unregistered_draft_count = sum(
        item.get("id") not in registered_candidate_draft_ids for item in drafts
    )
    candidate_family_counts: Counter[str] = Counter(
        str(item.get("task_family")) for item in drafts if isinstance(item, dict)
    )
    pipeline_family_capacity = {
        family: family_counts[family] + candidate_family_counts[family]
        for family in target["task_families"]
    }
    insufficient_pipeline_families = {
        family: {
            "available": pipeline_family_capacity[family],
            "required": required,
        }
        for family, required in target["task_families"].items()
        if pipeline_family_capacity[family] < required
    }
    if insufficient_pipeline_families:
        structural_errors.append(
            "candidate pipeline cannot meet task family targets: "
            + ", ".join(
                f"{family} {counts['available']} of {counts['required']}"
                for family, counts in sorted(insufficient_pipeline_families.items())
            )
        )

    slice_counts = {
        "answer_absence": sum(case.get("answer_policy") == "refuse_absent" for case in cases),
        "tables_or_calculations": sum(bool(case.get("calculations")) for case in cases),
        "multiple_documents": sum(
            len({item.get("filename") for item in case.get("required_citations", [])}) > 1
            for case in cases
        ),
        "conflicting_or_confusable_evidence": sum(
            "confusable_evidence" in case.get("slices", []) for case in cases
        ),
    }
    slice_fractions = {
        key: round(value / len(cases), 4) if cases else 0.0
        for key, value in slice_counts.items()
    }
    release_failures = []
    if len(cases) != target["cases"]:
        release_failures.append(f"registered cases {len(cases)} of {target['cases']}")
    if len(observed_deals) < target["minimum_deals"]:
        release_failures.append(f"registered deals {len(observed_deals)} of {target['minimum_deals']}")
    for split, expected in target["splits"].items():
        if split_counts[split] != expected["cases"]:
            release_failures.append(f"{split} cases {split_counts[split]} of {expected['cases']}")
    for family, expected in target["task_families"].items():
        if family_counts[family] != expected:
            release_failures.append(f"{family} cases {family_counts[family]} of {expected}")
    for name, minimum in target["minimum_slice_fractions"].items():
        if slice_fractions[name] < minimum:
            release_failures.append(f"{name} fraction {slice_fractions[name]:.4f} below {minimum:.4f}")
    if approved_count != len(cases):
        release_failures.append(f"domain approved cases {approved_count} of {len(cases)}")
    if not scope_approved(governance, "benchmark_contract"):
        release_failures.append("signed benchmark contract approvals are incomplete")
    if not scope_approved(governance, "release_thresholds"):
        release_failures.append("signed release threshold approvals are incomplete")

    return {
        "verification_kind": "first_pass_benchmark_contract",
        "structural_passed": not structural_errors,
        "release_ready": not structural_errors and not release_failures,
        "governance": governance,
        "files": {name: {"path": str(path.relative_to(root)), "sha256": sha256(path)} for name, path in paths.items()},
        "inventory": {
            **expected_inventory,
            "candidate_cases_registered": len(registration_result["cases"]),
            "candidate_approvals_recorded": len(recorded_approval_ids),
            "candidate_approvals_unregistered": len(recorded_approval_ids - registered_approval_ids),
            "candidate_deals_not_acquired": not_acquired_count,
            "candidate_deals_acquired_not_registered": acquired_unregistered_count,
            "candidate_question_drafts_not_registered": unregistered_draft_count,
            "candidate_deals_with_question_drafts": len(drafts_by_candidate),
            "candidate_companion_sources_discovered": len(companions),
            "candidate_companion_sources_acquired": len(companion_acquisitions),
            "candidate_companion_sources_with_tables": sum(
                evidence.get("parser", {}).get("table_count", 0) > 0
                for evidence in companion_acquisitions.values()
            ),
            "candidate_deals_with_multiple_acquired_documents": len(
                set(candidate_acquisitions) & set(companion_acquisitions)
            ),
            "sourcing_pipeline_deals": len(observed_deals | set(candidate_ids)),
            "target_cases": target["cases"],
            "target_deals": target["minimum_deals"],
            "target_calibration_cases": target["splits"]["calibration"]["cases"],
            "target_calibration_deals": target["splits"]["calibration"]["minimum_deals"],
            "task_family_counts": dict(sorted(family_counts.items())),
            "candidate_task_family_counts": dict(sorted(candidate_family_counts.items())),
            "pipeline_task_family_capacity": pipeline_family_capacity,
            "pipeline_task_family_capacity_ready": not insufficient_pipeline_families,
            "slice_counts": slice_counts,
            "slice_fractions": slice_fractions,
        },
        "structural_errors": structural_errors,
        "release_failures": release_failures,
    }


def _normalized_text(value: str) -> str:
    value = value.lower().replace("%", " percent ")
    value = re.sub(r"(?<=\d)[\u2010-\u2015-](?=\d)", " to ", value)
    value = re.sub(r"[^a-z0-9.$]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def _numeric_tokens(value: str) -> list[float]:
    tokens = []
    for match in re.finditer(r"(?<![A-Za-z0-9_])[-+]?\d[\d,]*(?:\.\d+)?", value):
        try:
            number = float(match.group(0).replace(",", ""))
        except ValueError:
            continue
        if math.isfinite(number):
            tokens.append(number)
    return tokens


def _contains_number(value: str, expected: float, tolerance: float) -> bool:
    return any(abs(item - expected) <= tolerance for item in _numeric_tokens(value))


def evaluate_registered_formula(formula: str, variables: dict[str, float]) -> float:
    """Evaluate the benchmark arithmetic language without Python eval or calls."""
    if not isinstance(formula, str) or not formula.strip() or len(formula) > 500:
        raise ValueError("formula must contain at most 500 characters")
    try:
        tree = ast.parse(formula, mode="eval")
    except SyntaxError as exc:
        raise ValueError("formula is not valid arithmetic") from exc

    def visit(node: ast.AST) -> float:
        if isinstance(node, ast.Expression):
            return visit(node.body)
        if isinstance(node, ast.Constant):
            if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
                raise ValueError("formula constants must be numbers")
            result = float(node.value)
        elif isinstance(node, ast.Name):
            if node.id not in variables:
                raise ValueError(f"formula uses undeclared input {node.id}")
            result = float(variables[node.id])
        elif isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            operand = visit(node.operand)
            result = operand if isinstance(node.op, ast.UAdd) else -operand
        elif isinstance(node, ast.BinOp) and isinstance(
            node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Pow),
        ):
            left = visit(node.left)
            right = visit(node.right)
            if isinstance(node.op, ast.Add):
                result = left + right
            elif isinstance(node.op, ast.Sub):
                result = left - right
            elif isinstance(node.op, ast.Mult):
                result = left * right
            elif isinstance(node.op, ast.Div):
                if right == 0:
                    raise ValueError("formula divides by zero")
                result = left / right
            else:
                if abs(right) > 12:
                    raise ValueError("formula exponent is outside the bounded range")
                result = left ** right
        else:
            raise ValueError(f"formula contains unsupported syntax {type(node).__name__}")
        if not math.isfinite(result) or abs(result) > 1e18:
            raise ValueError("formula result is outside the bounded numeric range")
        return result

    return visit(tree)


def calculation_contract_errors(case: dict[str, Any]) -> list[str]:
    """Verify that each registered calculation is source bound and executable."""
    errors: list[str] = []
    claims = {
        str(item.get("id")): item
        for item in case.get("required_claims", []) if isinstance(item, dict)
    }
    calculation_ids: set[str] = set()
    for index, calculation in enumerate(case.get("calculations", [])):
        location = f"{case.get('id', 'case')}.calculations[{index}]"
        if not isinstance(calculation, dict):
            errors.append(f"{location}: calculation is not an object")
            continue
        calculation_id = str(calculation.get("id") or "")
        if calculation_id in calculation_ids:
            errors.append(f"{location}: calculation ID is not unique")
        calculation_ids.add(calculation_id)
        inputs = calculation.get("inputs", [])
        if not isinstance(inputs, list) or not inputs:
            errors.append(f"{location}: registered inputs are required")
            continue
        names = [item.get("name") for item in inputs if isinstance(item, dict)]
        if len(names) != len(inputs) or len(names) != len(set(names)):
            errors.append(f"{location}: input names must be present and unique")
            continue
        input_claim_ids = [
            item.get("claim_id") for item in inputs if isinstance(item, dict)
        ]
        if set(input_claim_ids) != set(calculation.get("input_claim_ids", [])):
            errors.append(f"{location}: input claim IDs differ from registered inputs")
        variables: dict[str, float] = {}
        for item in inputs:
            name = str(item.get("name") or "")
            claim_id = str(item.get("claim_id") or "")
            value = item.get("value")
            claim = claims.get(claim_id)
            if claim is None:
                errors.append(f"{location}: input {name} references unknown claim {claim_id}")
                continue
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                errors.append(f"{location}: input {name} value is not numeric")
                continue
            numeric_value = float(value)
            if not math.isfinite(numeric_value):
                errors.append(f"{location}: input {name} value is not finite")
                continue
            if not _contains_number(str(claim.get("text", "")), numeric_value, 1e-9):
                errors.append(
                    f"{location}: input {name} value is absent from claim {claim_id}"
                )
            variables[name] = numeric_value
        try:
            observed = evaluate_registered_formula(str(calculation.get("formula", "")), variables)
        except ValueError as exc:
            errors.append(f"{location}: {exc}")
            continue
        expected = calculation.get("expected_value")
        tolerance = calculation.get("tolerance")
        if (
            isinstance(expected, bool) or not isinstance(expected, (int, float))
            or isinstance(tolerance, bool) or not isinstance(tolerance, (int, float))
        ):
            continue
        if abs(observed - float(expected)) > float(tolerance):
            errors.append(
                f"{location}: formula returns {observed:g}, not registered value {float(expected):g}"
            )
    return errors


def _compact_formula(value: str) -> str:
    return re.sub(r"[\s`]", "", value).replace("×", "*").replace("÷", "/").lower()


def _required_numeric_facts(case: dict[str, Any]) -> list[str]:
    facts = []
    patterns = (
        r"\$[\d,]+(?:\.\d+)?(?:\s+(?:million|billion))?",
        r"\b(?:january|february|march|april|may|june|july|august|september|october|november|december)\s+\d{1,2},\s+\d{4}\b",
        r"\b\d+(?:\.\d+)?\s+to\s+\d+(?:\.\d+)?\s+percent\b",
        r"\b\d+(?:\.\d+)?x\b",
    )
    for claim in case.get("required_claims", []):
        for pattern in patterns:
            facts.extend(re.findall(pattern, claim.get("text", ""), re.IGNORECASE))
    return list(dict.fromkeys(_normalized_text(item) for item in facts))


def validate_signed_delivery_evidence(
    root: Path,
    responses_path: Path,
    registry_path: Path,
    delivery_path: Path | None = None,
) -> dict[str, Any]:
    """Verify saved product delivery from embedded raw Buzz events, offline."""
    delivery_path = delivery_path or root / "evidence/public-deal-buzz-event-verification.json"
    execution_path = root / "benchmarks/public_deal_battletest.json"
    errors: list[str] = []
    try:
        delivery = json.loads(delivery_path.read_text(encoding="utf-8"))
        responses = json.loads(responses_path.read_text(encoding="utf-8"))
        registry = json.loads(registry_path.read_text(encoding="utf-8"))
        execution = json.loads(execution_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"passed": False, "errors": [str(exc)], "cases": {}}
    if delivery.get("schema") != "prism.public_deal_buzz_event_verification.v3":
        errors.append("signed delivery evidence has an unexpected schema")
    if delivery.get("passed") is not True:
        errors.append("signed delivery evidence does not pass")
    for field, path in (
        ("responses_sha256", responses_path),
        ("registry_sha256", registry_path),
        ("execution_benchmark_sha256", execution_path),
    ):
        if delivery.get(field) != sha256(path):
            errors.append(f"signed delivery {field} differs from its artifact")
    owner = delivery.get("owner_pubkey")
    agent = delivery.get("agent_pubkey")
    if (
        not re.fullmatch(r"[0-9a-f]{64}", str(owner or ""))
        or not re.fullmatch(r"[0-9a-f]{64}", str(agent or ""))
        or owner == agent
    ):
        errors.append("signed delivery lacks distinct owner and agent identities")
    registry_ids = {case["id"] for case in registry.get("cases", [])}
    prompts = {case["id"]: case["prompt"] for case in execution.get("cases", [])}
    delivery_cases = {
        case.get("case_id"): case for case in delivery.get("cases", [])
        if isinstance(case, dict) and isinstance(case.get("case_id"), str)
    }
    if set(delivery_cases) != registry_ids or set(prompts) != registry_ids:
        errors.append("signed delivery case inventory differs from the registry")
    verified: dict[str, bool] = {}
    response_records = responses.get("responses", {})
    for case_id in sorted(registry_ids):
        case_errors: list[str] = []
        saved = response_records.get(case_id, {})
        delivered = delivery_cases.get(case_id, {})
        question_id = saved.get("question_event_id")
        answer_id = saved.get("answer_event_id")
        channel = delivered.get("buzz_channel_id")
        raw_events = delivered.get("raw_events", {})
        if delivered.get("question_event_id") != question_id:
            case_errors.append("question event identity differs")
        if delivered.get("answer_event_id") != answer_id:
            case_errors.append("answer event identity differs")
        if delivered.get("canonical_path") != saved.get("canonical_path"):
            case_errors.append("canonical path differs")
        if set(raw_events) != {question_id, answer_id}:
            case_errors.append("raw event inventory differs")
        for event_id in (question_id, answer_id):
            event = raw_events.get(event_id, {})
            if event.get("id") != event_id:
                case_errors.append(f"raw event {event_id} identity differs")
                continue
            case_errors.extend(nostr_event_errors(event))
            if ["h", channel] not in event.get("tags", []):
                case_errors.append(f"raw event {event_id} channel differs")
        question = raw_events.get(question_id, {})
        answer = raw_events.get(answer_id, {})
        if question.get("pubkey") != owner or question.get("content") != prompts.get(case_id):
            case_errors.append("owner-signed question differs from the execution benchmark")
        answer_content = str(answer.get("content", ""))
        marker = re.match(
            r"^<!-- prism:deal-room-answer model=([^\s]+) "
            r"guard=(deal_room_chat_guard_v\d+) trace=(trc_[0-9a-f]{12}) "
            r"source_class=([a-z0-9_]+) provenance=([0-9a-f]{64}) "
            r"source_snapshot=([0-9a-f]{64}) -->\n",
            answer_content,
        )
        if answer.get("pubkey") != agent:
            case_errors.append("answer event is not signed by the expected agent")
        if saved.get("answer_state") != "accepted":
            case_errors.append("saved outcome is not an accepted answer")
        if not marker:
            case_errors.append("answer event lacks the Prism model, guard, and trace marker")
            visible_answer = answer_content
        else:
            visible_answer = answer_content[marker.end():]
            if marker.group(1) != saved.get("model"):
                case_errors.append("answer event model marker differs from the saved response")
            if marker.group(3) != saved.get("trace_id"):
                case_errors.append("answer event trace marker differs from the saved response")
            if marker.group(4) != saved.get("source_classification"):
                case_errors.append("answer event source classification differs from the saved response")
            if marker.group(5) != saved.get("source_provenance_sha256"):
                case_errors.append("answer event provenance binding differs from the saved response")
            if marker.group(6) != saved.get("source_snapshot_sha256"):
                case_errors.append("answer event source snapshot differs from the saved response")
        if visible_answer != saved.get("response"):
            case_errors.append("agent-signed visible answer differs from the saved response")
        provenance = saved.get("source_provenance", {})
        if (
            saved.get("source_classification") != "public_filing_corpus"
            or not re.fullmatch(
                r"[0-9a-f]{64}", str(saved.get("source_provenance_sha256", ""))
            )
            or not re.fullmatch(
                r"[0-9a-f]{64}", str(saved.get("source_snapshot_sha256", ""))
            )
            or provenance.get("classification") != "public_filing_corpus"
            or provenance.get("binding_sha256")
            != saved.get("source_provenance_sha256")
            or provenance.get("public_source") is not True
            or provenance.get("accuracy_release_evidence") is not False
            or provenance.get("buyer_evidence") is not False
        ):
            case_errors.append("saved answer lacks an honest public provenance binding")
        trace = delivered.get("trace", {})
        trace_metadata = trace.get("metadata", {}) if isinstance(trace, dict) else {}
        if (
            delivered.get("trace_integrity_passed") is not True
            or trace.get("trace_id") != saved.get("trace_id")
            or trace.get("session_id") != saved.get("room_id")
            or trace.get("query") != prompts.get(case_id)
            or trace.get("response") != saved.get("response")
            or trace.get("model_name") != saved.get("model")
            or trace_metadata.get("answer_event_id") != answer_id
            or trace_metadata.get("question_event_id") != question_id
            or trace_metadata.get("source_classification")
            != saved.get("source_classification")
            or trace_metadata.get("source_provenance_sha256")
            != saved.get("source_provenance_sha256")
            or trace_metadata.get("source_snapshot_sha256")
            != saved.get("source_snapshot_sha256")
        ):
            case_errors.append("persisted trace differs from the provenance-bound answer")
        if delivered.get("question_matches_execution_benchmark") is not True:
            case_errors.append("delivery did not confirm the execution question")
        if (
            delivered.get("answer_event_marker_matches_trace") is not True
            or delivered.get("answer_event_integrity_passed") is not True
            or delivered.get("accepted_answer_matches_saved_response") is not True
            or delivered.get("passed") is not True
        ):
            case_errors.append("delivery did not confirm the saved answer")
        verified[case_id] = not case_errors
        errors.extend(f"{case_id}: {item}" for item in case_errors)
    limitations = delivery.get("limitations", [])
    if not limitations or "not semantic accuracy" not in " ".join(limitations).lower():
        errors.append("signed delivery evidence lacks its semantic-accuracy limitation")
    return {
        "passed": not errors and all(verified.values()),
        "record": str(delivery_path),
        "verified_case_count": sum(verified.values()),
        "provenance_bound_case_count": sum(
            1 for case_id in verified
            if response_records.get(case_id, {}).get("source_provenance_sha256")
        ),
        "cases": verified,
        "errors": errors,
        "limitations": limitations,
    }


def evaluate_case_response(
    case: dict[str, Any],
    response_record: dict[str, Any] | None,
    *,
    signed_delivery_verified: bool = False,
) -> dict[str, Any]:
    """Run deterministic checks without manufacturing semantic ground truth."""
    response_record = response_record or {}
    response = str(response_record.get("response", ""))
    normalized = _normalized_text(response)
    expected_citations = [
        f"[{item['filename']}#{item['anchor']}]"
        for item in case.get("required_citations", [])
    ]
    missing_citations = [item for item in expected_citations if item.lower() not in response.lower()]
    numeric_facts = _required_numeric_facts(case)
    missing_numeric_facts = [item for item in numeric_facts if item not in normalized]
    forbidden_hits = [
        item for item in case.get("forbidden_claims", [])
        if _normalized_text(item) in normalized
    ]
    absence_terms = case.get("acceptable_absence_terms", [])
    absence_passed = (
        any(_normalized_text(item) in normalized for item in absence_terms)
        and not forbidden_hits
    ) if case.get("answer_policy") == "refuse_absent" else None
    unauthorized_writes = response_record.get("unauthorized_file_writes", [])

    calculation_failures: list[str] = []
    for calculation in case.get("calculations", []):
        formula = str(calculation.get("formula", ""))
        expected_value = float(calculation.get("expected_value", 0.0))
        tolerance = float(calculation.get("tolerance", 0.0))
        unit = str(calculation.get("unit", ""))
        formula_blocks = [
            block for block in re.split(r"\n\s*\n", response)
            if _compact_formula(formula) in _compact_formula(block)
        ]
        if not formula_blocks:
            calculation_failures.append(
                f"{calculation.get('id')}: registered formula is not shown"
            )
            continue
        matching_block = next((
            block for block in formula_blocks
            if all(
                _contains_number(block, float(item.get("value", 0.0)), 1e-9)
                for item in calculation.get("inputs", [])
            )
            and _contains_number(block, expected_value, tolerance)
            and _normalized_text(unit) in _normalized_text(block)
        ), None)
        if matching_block is None:
            calculation_failures.append(
                f"{calculation.get('id')}: one calculation block must show every input, "
                f"the formula, result {expected_value:g}, and unit {unit!r}"
            )

    evaluations = [
        {
            "dimension": "source_integrity",
            "label": "pass" if response and not missing_citations else "fail",
            "score": 1.0 if response and not missing_citations else 0.0,
            "severity": case.get("severity", "critical"),
            "critique": "All required citation tokens are present and their registered anchors have verified source evidence." if not missing_citations else f"Missing citations: {missing_citations}",
            "evaluator": "deterministic_citation_token_v1",
        },
        {
            "dimension": "numerical_correctness",
            "label": "not_applicable" if not numeric_facts else ("pass" if not missing_numeric_facts else "fail"),
            "score": None if not numeric_facts else (1.0 if not missing_numeric_facts else 0.0),
            "severity": case.get("severity", "critical"),
            "critique": "No registered numeric fact for deterministic matching." if not numeric_facts else ("All registered numeric tokens are present." if not missing_numeric_facts else f"Missing numeric facts: {missing_numeric_facts}"),
            "evaluator": "deterministic_numeric_token_v1",
        },
        {
            "dimension": "calibrated_uncertainty",
            "label": "not_applicable" if absence_passed is None else ("pass" if absence_passed else "fail"),
            "score": None if absence_passed is None else (1.0 if absence_passed else 0.0),
            "severity": case.get("severity", "critical"),
            "critique": "The case does not require an answer absence decision." if absence_passed is None else ("The response states the registered absence and avoids forbidden claims." if absence_passed else f"Required absence language is missing or a forbidden claim appears: {forbidden_hits}"),
            "evaluator": "deterministic_absence_guard_v1",
        },
        {
            "dimension": "calculation_reproducibility",
            "label": (
                "not_applicable" if not case.get("calculations")
                else ("pass" if not calculation_failures else "fail")
            ),
            "score": (
                None if not case.get("calculations")
                else (1.0 if not calculation_failures else 0.0)
            ),
            "severity": case.get("severity", "critical"),
            "critique": (
                "The case has no registered calculation."
                if not case.get("calculations")
                else (
                    "Every registered input, formula, result, and unit appears in one calculation block."
                    if not calculation_failures
                    else "; ".join(calculation_failures)
                )
            ),
            "evaluator": "deterministic_registered_calculation_v1",
        },
        {
            "dimension": "workflow_reliability",
            "label": (
                "fail" if not response or unauthorized_writes
                else ("pass" if signed_delivery_verified else "unverified")
            ),
            "score": (
                0.0 if not response or unauthorized_writes
                else (1.0 if signed_delivery_verified else None)
            ),
            "severity": "critical",
            "critique": (
                "The response is missing or the source folder changed."
                if not response or unauthorized_writes
                else (
                    "The owner question and agent answer match independently verified raw Buzz events."
                    if signed_delivery_verified
                    else "The saved response has no verified per-case signed Buzz delivery record."
                )
            ),
            "evaluator": "deterministic_signed_delivery_guard_v2",
        },
    ]
    for dimension in (
        "primary_decision_intent",
        "evidence_support",
        "component_completeness",
        "human_usefulness",
    ):
        evaluations.append({
            "dimension": dimension,
            "label": "unverified",
            "score": None,
            "severity": case.get("severity", "critical"),
            "critique": "No approved human label exists for this semantic dimension.",
            "evaluator": "human_label_required_v1",
        })
    deterministic_failure = any(
        item["label"] == "fail" for item in evaluations
        if item["evaluator"] != "human_label_required_v1"
    )
    return {
        "case_id": case["id"],
        "case_version": case["version"],
        "answer_model": {
            "provider": response_record.get("provider"),
            "served_id": response_record.get("model"),
        },
        "response_sha256": hashlib.sha256(response.encode()).hexdigest() if response else None,
        "evaluations": evaluations,
        "deterministic_hard_failure": deterministic_failure,
        "semantic_state": "unverified",
        "domain_review_status": case["domain_review"]["status"],
        "release_decision": "unverified",
    }


def evaluate_development_responses(root: Path, responses_path: Path) -> dict[str, Any]:
    contract = validate_contract(root)
    registry_path = root / "benchmarks" / "first_pass" / "development_registry.v2.json"
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    response_artifact = json.loads(responses_path.read_text(encoding="utf-8"))
    responses = response_artifact.get("responses", {})
    signed_delivery = validate_signed_delivery_evidence(
        root, responses_path, registry_path,
    )
    cases = [
        evaluate_case_response(
            case,
            responses.get(case["id"]),
            signed_delivery_verified=signed_delivery.get("cases", {}).get(case["id"], False),
        )
        for case in registry["cases"]
    ]
    unauthorized_writes = response_artifact.get("unauthorized_file_writes", [])
    source_state_unchanged = (
        response_artifact.get("corpus_state_before")
        == response_artifact.get("corpus_state_after")
    )
    label_counts: Counter[str] = Counter(
        evaluation["label"] for case in cases for evaluation in case["evaluations"]
    )
    return {
        "verification_kind": "first_pass_development_evaluation",
        "contract_structural_passed": contract["structural_passed"],
        "contract_release_ready": contract["release_ready"],
        "registry_sha256": sha256(registry_path),
        "responses_path": str(responses_path.relative_to(root)),
        "responses_sha256": sha256(responses_path),
        "case_count": len(cases),
        "deterministic_failure_count": sum(item["deterministic_hard_failure"] for item in cases),
        "semantic_unverified_count": sum(item["semantic_state"] == "unverified" for item in cases),
        "unauthorized_source_writes": unauthorized_writes,
        "source_state_unchanged": source_state_unchanged,
        "artifact_integrity_passed": not unauthorized_writes and source_state_unchanged,
        "signed_delivery_evidence": signed_delivery,
        "label_counts": dict(sorted(label_counts.items())),
        "accuracy_release_passed": False,
        "release_blockers": [
            "Every case lacks approved semantic and usefulness labels.",
            *(
                [] if signed_delivery["passed"] else
                ["The saved responses lack complete verified per-case signed product delivery records."]
            ),
            *( ["The saved response artifact changed source files."] if unauthorized_writes or not source_state_unchanged else [] ),
            *contract["release_failures"],
        ],
        "cases": cases,
    }
