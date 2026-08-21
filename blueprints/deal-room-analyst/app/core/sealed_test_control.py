"""Fail-before-read controls for a one-time, externally held sealed test."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from core.first_pass_benchmark import schema_errors, sha256, validate_contract
from core.judge_calibration import validate_saved_judge_calibration
from core.benchmark_governance import scope_approved, validate_benchmark_governance


FORBIDDEN_SECRET_FIELDS = {
    "answer",
    "answers",
    "calculations",
    "citations",
    "expected",
    "expected_answer",
    "label",
    "labels",
    "prompt",
    "question",
    "required_citations",
    "required_claims",
    "source_text",
}


def _canonical_sha256(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _safe_path(root: Path, relative: str) -> Path:
    path = (root / relative).resolve()
    try:
        path.relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError("path resolves outside the project") from exc
    return path


def _load_bound_json(root: Path, binding: Any, label: str, errors: list[str]) -> tuple[Path | None, dict[str, Any]]:
    if not isinstance(binding, dict):
        errors.append(f"{label} is not bound")
        return None, {}
    try:
        path = _safe_path(root, str(binding.get("path", "")))
        if sha256(path) != binding.get("sha256"):
            errors.append(f"{label} hash differs")
            return path, {}
        return path, json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        errors.append(f"{label} unavailable: {exc}")
        return None, {}


def _forbidden_fields(value: Any, location: str = "$") -> list[str]:
    errors: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            if key.lower() in FORBIDDEN_SECRET_FIELDS:
                errors.append(f"{location}: public manifest contains forbidden secret field {key}")
            errors.extend(_forbidden_fields(item, f"{location}.{key}"))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            errors.extend(_forbidden_fields(item, f"{location}[{index}]"))
    return errors


def sealed_test_preflight(root: Path, control_path: Path | None = None) -> dict[str, Any]:
    """Verify every gate needed before external sealed bytes may be requested."""
    root = root.resolve()
    contract_dir = root / "benchmarks" / "first_pass"
    control_path = (control_path or contract_dir / "sealed_test_control.v1.json").resolve()
    errors: list[str] = []
    try:
        control = json.loads(control_path.read_text(encoding="utf-8"))
        control_schema = json.loads((contract_dir / "sealed_test_control.schema.json").read_text())
        errors.extend(schema_errors(control, control_schema))
    except (OSError, json.JSONDecodeError) as exc:
        return {"verification_kind": "sealed_test_preflight", "ready_to_open": False, "errors": [str(exc)]}

    benchmark_manifest = json.loads((contract_dir / "benchmark_manifest.v2.json").read_text())
    if control.get("benchmark_id") != benchmark_manifest.get("benchmark_id"):
        errors.append("control benchmark ID differs")
    if control.get("benchmark_version") != benchmark_manifest.get("version"):
        errors.append("control benchmark version differs")
    if control.get("state") != "authorized_unopened":
        errors.append("sealed test is not authorized and unopened")

    public_path, public = _load_bound_json(root, control.get("public_manifest"), "public manifest", errors)
    if public:
        public_schema = json.loads((contract_dir / "sealed_test_manifest.schema.json").read_text())
        errors.extend(schema_errors(public, public_schema))
        errors.extend(_forbidden_fields(public))
        if public.get("benchmark_id") != benchmark_manifest.get("benchmark_id"):
            errors.append("public manifest benchmark ID differs")
        if public.get("benchmark_version") != benchmark_manifest.get("version"):
            errors.append("public manifest benchmark version differs")
        if public.get("state") != "registered_unopened":
            errors.append("sealed inventory is not registered and unopened")

        cases = public.get("cases", []) if isinstance(public.get("cases"), list) else []
        target = benchmark_manifest["target"]["splits"]["sealed_test"]
        case_ids = [item.get("case_id") for item in cases if isinstance(item, dict)]
        deal_ids = {item.get("deal_id") for item in cases if isinstance(item, dict)}
        secret_hashes = [item.get("secret_case_sha256") for item in cases if isinstance(item, dict)]
        if len(cases) != target["cases"]:
            errors.append(f"sealed inventory has {len(cases)} of {target['cases']} cases")
        if len(deal_ids) < target["minimum_deals"]:
            errors.append(f"sealed inventory has {len(deal_ids)} of {target['minimum_deals']} deals")
        if len(case_ids) != len(set(case_ids)):
            errors.append("sealed case IDs are not unique")
        if len(secret_hashes) != len(set(secret_hashes)):
            errors.append("sealed secret case hashes are not unique")

        contract = validate_contract(root)
        registry = json.loads((contract_dir / "development_registry.v2.json").read_text())
        registered = json.loads((contract_dir / "candidate_case_registrations.v1.json").read_text())
        visible_cases = [*registry.get("cases", []), *[item.get("case", {}) for item in registered.get("registrations", [])]]
        visible_deals = {item.get("deal_id") for item in visible_cases}
        visible_families = {item.get("near_duplicate_family_id") for item in visible_cases if item.get("near_duplicate_family_id")}
        sealed_families = {item.get("near_duplicate_family_id") for item in cases if isinstance(item, dict) and item.get("near_duplicate_family_id")}
        if deal_ids & visible_deals:
            errors.append("sealed deals overlap development or calibration inventory")
        if sealed_families & visible_families:
            errors.append("sealed near-duplicate families overlap development or calibration inventory")
        if not contract.get("structural_passed"):
            errors.append("benchmark contract is structurally invalid")

    governance = validate_benchmark_governance(root)
    errors.extend(f"benchmark governance: {item}" for item in governance["errors"])
    if not scope_approved(governance, "benchmark_contract"):
        errors.append("signed benchmark contract approvals are incomplete")
    if not scope_approved(governance, "release_thresholds"):
        errors.append("signed release threshold approvals are incomplete")
    if not scope_approved(governance, "sealed_test_open"):
        errors.append("signed sealed test opening approvals are incomplete")

    calibration_path, _ = _load_bound_json(root, control.get("calibration_result"), "calibration result", errors)
    calibration = validate_saved_judge_calibration(root, calibration_path) if calibration_path else {"calibration_passed": False}
    if calibration.get("calibration_passed") is not True:
        errors.append("judge calibration has not passed")

    _, frozen = _load_bound_json(root, control.get("frozen_system_verification"), "frozen system verification", errors)
    if frozen:
        if frozen.get("selected_runtime_verified") is not True:
            errors.append("frozen system verification did not pass")
        if frozen.get("runtime") not in {"local", "hybrid"}:
            errors.append("frozen system runtime is not an allowed evaluated runtime")

    try:
        audit_path = _safe_path(root, str(control.get("audit_receipt_path", "")))
        if audit_path.exists():
            errors.append("sealed version already has a contact receipt")
    except ValueError as exc:
        audit_path = None
        errors.append(f"audit receipt path invalid: {exc}")

    return {
        "verification_kind": "sealed_test_preflight",
        "benchmark_id": control.get("benchmark_id"),
        "benchmark_version": control.get("benchmark_version"),
        "ready_to_open": not errors,
        "secret_loader_invoked": False,
        "public_manifest_path": str(public_path.relative_to(root)) if public_path else None,
        "public_case_count": len(public.get("cases", [])) if public else 0,
        "audit_receipt_path": str(audit_path.relative_to(root)) if audit_path else None,
        "errors": errors,
    }


def open_sealed_test(root: Path, secret_loader: Callable[[], bytes], control_path: Path | None = None) -> dict[str, Any]:
    """Open one sealed version once. Failed preflight returns before calling loader."""
    root = root.resolve()
    preflight = sealed_test_preflight(root, control_path)
    if not preflight["ready_to_open"]:
        return preflight

    audit_path = root / preflight["audit_receipt_path"]
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    started = {
        "schema_version": 1,
        "verification_kind": "sealed_test_contact_receipt",
        "benchmark_id": preflight["benchmark_id"],
        "benchmark_version": preflight["benchmark_version"],
        "contacted_at": datetime.now(timezone.utc).isoformat(),
        "state": "contact_started_version_consumed",
        "secret_bundle_sha256": None,
        "secret_case_count": None,
        "validation_errors": [],
    }
    try:
        descriptor = os.open(audit_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        return {
            **preflight,
            "ready_to_open": False,
            "secret_loader_invoked": False,
            "sealed_version_consumed": True,
            "errors": ["sealed version contact receipt was created concurrently"],
        }
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        json.dump(started, handle, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())

    errors: list[str] = []
    payload = b""
    secret: dict[str, Any] = {}
    try:
        payload = secret_loader()
        secret = json.loads(payload)
    except Exception as exc:  # the receipt must survive loader and decode failures
        errors.append(f"secret bundle load failed: {exc}")

    if secret:
        public = json.loads((root / preflight["public_manifest_path"]).read_text())
        case_schema = json.loads(
            (root / "benchmarks" / "first_pass" / "case.schema.json").read_text()
        )
        descriptors = {item["case_id"]: item for item in public["cases"]}
        cases = secret.get("cases", []) if isinstance(secret.get("cases"), list) else []
        if secret.get("benchmark_id") != preflight["benchmark_id"]:
            errors.append("secret bundle benchmark ID differs")
        if secret.get("benchmark_version") != preflight["benchmark_version"]:
            errors.append("secret bundle benchmark version differs")
        if {item.get("id") for item in cases if isinstance(item, dict)} != set(descriptors):
            errors.append("secret case IDs differ from public inventory")
        for case in cases:
            case_id = case.get("id") if isinstance(case, dict) else None
            descriptor_item = descriptors.get(case_id, {})
            errors.extend(
                f"{case_id}: {item}"
                for item in schema_errors(case, case_schema, case_schema)
            )
            if case.get("split") != "sealed_test":
                errors.append(f"{case_id}: secret case is not in sealed_test split")
            for secret_field, public_field in (
                ("version", "case_version"),
                ("deal_id", "deal_id"),
                ("source_snapshot_sha256", "source_snapshot_sha256"),
                ("task_family", "task_family"),
                ("slices", "slices"),
                ("near_duplicate_family_id", "near_duplicate_family_id"),
            ):
                if case.get(secret_field) != descriptor_item.get(public_field):
                    errors.append(f"{case_id}: {secret_field} differs from public inventory")
            review = case.get("domain_review", {})
            if (
                review.get("status") != "approved"
                or not review.get("owner")
                or not review.get("reviewed_at")
            ):
                errors.append(f"{case_id}: secret case lacks completed domain approval")
            if _canonical_sha256(case) != descriptor_item.get("secret_case_sha256"):
                errors.append(f"{case_id}: secret case hash differs")

    started.update({
        "state": "contacted_validated" if not errors else "contacted_invalid_version_consumed",
        "secret_bundle_sha256": hashlib.sha256(payload).hexdigest() if payload else None,
        "secret_case_count": len(secret.get("cases", [])) if secret else None,
        "validation_errors": errors,
    })
    temporary = audit_path.with_suffix(audit_path.suffix + ".tmp")
    temporary.write_text(json.dumps(started, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, audit_path)
    return {
        **preflight,
        "ready_to_open": False,
        "secret_loader_invoked": True,
        "sealed_version_consumed": True,
        "secret_bundle_valid": not errors,
        "secret_bundle": secret if not errors else None,
        "errors": errors,
    }
