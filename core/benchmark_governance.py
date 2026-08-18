"""Cryptographic governance receipts for benchmark promotion decisions."""

from __future__ import annotations

import hashlib
import fcntl
import json
import os
import re
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from core.nostr_event import nostr_event_errors


GOVERNANCE_ROLES = ("product_owner", "domain_owner", "strategy_owner", "security_owner")
GOVERNANCE_SCOPES = (
    "benchmark_contract",
    "release_thresholds",
    "sealed_test_open",
)
MATERIAL_FILES = (
    "benchmark_manifest.v2.json",
    "case.schema.json",
    "rubric.v1.json",
    "sealed_test_control.v1.json",
    "sealed_test_control.schema.json",
    "sealed_test_manifest.v1.json",
    "sealed_test_manifest.schema.json",
)


def canonical_sha256(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def benchmark_material(root: Path, scope: str) -> dict[str, Any]:
    if scope not in GOVERNANCE_SCOPES:
        raise ValueError("benchmark governance scope is invalid")
    contract = root.resolve() / "benchmarks" / "first_pass"
    files: dict[str, str] = {}
    for name in MATERIAL_FILES:
        path = contract / name
        files[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    manifest = json.loads((contract / "benchmark_manifest.v2.json").read_text(encoding="utf-8"))
    return {
        "scope": scope,
        "benchmark_id": manifest.get("benchmark_id"),
        "benchmark_version": manifest.get("version"),
        "files": files,
    }


def benchmark_material_sha256(root: Path, scope: str) -> str:
    return canonical_sha256(benchmark_material(root, scope))


def _authority_material(authority: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in authority.items() if key != "authority_event"}


def governance_authority_content(authority: dict[str, Any]) -> str:
    material = _authority_material(authority)
    return "\n".join([
        "PRISM_BENCHMARK_GOVERNANCE_AUTHORITY_V1",
        f"root_authority_id={material.get('root_authority_id')}",
        f"channel_id={material.get('channel_id')}",
        f"payload_sha256={canonical_sha256(material)}",
    ])


def _receipt_material(receipt: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in receipt.items() if key != "approval_event"}


def governance_approval_content(receipt: dict[str, Any]) -> str:
    material = _receipt_material(receipt)
    return "\n".join([
        "PRISM_BENCHMARK_GOVERNANCE_APPROVAL_V1",
        f"approval_id={material.get('approval_id')}",
        f"scope={material.get('scope')}",
        f"role={material.get('role')}",
        f"actor_id={material.get('actor_id')}",
        f"benchmark_id={material.get('benchmark_id')}",
        f"benchmark_version={material.get('benchmark_version')}",
        f"material_sha256={material.get('material_sha256')}",
        f"payload_sha256={canonical_sha256(material)}",
    ])


def _event_errors(event: Any, *, pubkey: str, channel_id: str, content: str) -> list[str]:
    if not isinstance(event, dict):
        return ["raw Buzz event is required"]
    errors = nostr_event_errors(event)
    if errors:
        return errors
    if event.get("pubkey") != pubkey:
        errors.append("Buzz event signer differs")
    channels = [
        tag[1] for tag in event.get("tags", [])
        if isinstance(tag, list) and len(tag) == 2 and tag[0] == "h"
    ]
    if channels != [channel_id]:
        errors.append("Buzz event channel differs")
    if event.get("content") != content:
        errors.append("Buzz event content differs")
    return errors


def validate_benchmark_governance(root: Path, ledger: Any | None = None) -> dict[str, Any]:
    root = root.resolve()
    manifest = json.loads(
        (root / "benchmarks" / "first_pass" / "benchmark_manifest.v2.json").read_text(encoding="utf-8")
    )
    if ledger is None:
        ledger = json.loads(
            (root / "benchmarks" / "first_pass" / "benchmark_governance.v1.json").read_text(encoding="utf-8")
        )
    errors: list[str] = []
    if not isinstance(ledger, dict):
        return {"valid": False, "configured": False, "errors": ["governance ledger must be an object"], "approvals": {}}
    if ledger.get("schema_version") != 1:
        errors.append("governance ledger schema version is not 1")
    if ledger.get("benchmark_id") != manifest.get("benchmark_id"):
        errors.append("governance benchmark ID differs")
    if ledger.get("benchmark_version") != manifest.get("version"):
        errors.append("governance benchmark version differs")
    authority = ledger.get("authority")
    receipts = ledger.get("receipts")
    if not isinstance(authority, dict):
        errors.append("governance authority must be an object")
        authority = {}
    if not isinstance(receipts, list):
        errors.append("governance receipts must be an array")
        receipts = []
    state = authority.get("state")
    configured = state == "signed_buzz_authority"
    if state not in {"unconfigured", "signed_buzz_authority"}:
        errors.append("governance authority state is invalid")
    if not configured:
        for field in ("root_authority_id", "root_buzz_pubkey", "channel_id", "authority_event"):
            if authority.get(field) is not None:
                errors.append(f"unconfigured governance authority field {field} must be null")
        if authority.get("role_assignments") != []:
            errors.append("unconfigured governance authority cannot assign roles")
        if receipts:
            errors.append("unconfigured governance authority cannot contain receipts")
        return {
            "valid": not errors,
            "configured": False,
            "errors": errors,
            "approvals": {},
            "receipt_count": len(receipts),
            "material_sha256": {
                scope: benchmark_material_sha256(root, scope) for scope in GOVERNANCE_SCOPES
            },
        }

    root_id = authority.get("root_authority_id")
    root_key = authority.get("root_buzz_pubkey")
    channel_id = authority.get("channel_id")
    assignments = authority.get("role_assignments")
    if not isinstance(root_id, str) or not root_id.strip():
        errors.append("governance root authority ID is required")
    if not isinstance(root_key, str) or not re.fullmatch(r"[a-f0-9]{64}", root_key):
        errors.append("governance root authority key is invalid")
    if not isinstance(channel_id, str) or not channel_id.strip():
        errors.append("governance channel ID is required")
    if not isinstance(assignments, list):
        errors.append("governance role assignments must be an array")
        assignments = []
    assignment_by_role: dict[str, dict[str, Any]] = {}
    for index, assignment in enumerate(assignments):
        if not isinstance(assignment, dict):
            errors.append(f"role assignment {index} must be an object")
            continue
        role = assignment.get("role")
        if role not in GOVERNANCE_ROLES:
            errors.append(f"role assignment {index} has an invalid role")
            continue
        if role in assignment_by_role:
            errors.append(f"governance role {role} is assigned more than once")
        actor_id = assignment.get("actor_id")
        actor_key = assignment.get("buzz_pubkey")
        if not isinstance(actor_id, str) or not actor_id.strip():
            errors.append(f"governance role {role} lacks an actor ID")
        if not isinstance(actor_key, str) or not re.fullmatch(r"[a-f0-9]{64}", actor_key):
            errors.append(f"governance role {role} has an invalid Buzz key")
        assignment_by_role[role] = assignment
    missing_roles = sorted(set(GOVERNANCE_ROLES) - set(assignment_by_role))
    if missing_roles:
        errors.append(f"governance roles are unassigned: {', '.join(missing_roles)}")
    actor_ids = [item.get("actor_id") for item in assignment_by_role.values()]
    actor_keys = [item.get("buzz_pubkey") for item in assignment_by_role.values()]
    if len(actor_ids) != len(set(actor_ids)):
        errors.append("governance roles must have distinct actor IDs")
    if len(actor_keys) != len(set(actor_keys)):
        errors.append("governance roles must have distinct Buzz keys")
    if root_key in actor_keys:
        errors.append("governance root key cannot also sign a role approval")
    if isinstance(root_key, str) and isinstance(channel_id, str):
        errors.extend(
            "governance authority event: " + item
            for item in _event_errors(
                authority.get("authority_event"), pubkey=root_key,
                channel_id=channel_id, content=governance_authority_content(authority),
            )
        )

    approvals: dict[str, dict[str, bool]] = {
        scope: {role: False for role in GOVERNANCE_ROLES} for scope in GOVERNANCE_SCOPES
    }
    seen_pairs: set[tuple[str, str]] = set()
    seen_ids: set[str] = set()
    seen_events: set[str] = set()
    for index, receipt in enumerate(receipts):
        location = f"governance receipt {index}"
        if not isinstance(receipt, dict):
            errors.append(f"{location} must be an object")
            continue
        scope, role = receipt.get("scope"), receipt.get("role")
        pair = (str(scope), str(role))
        if scope not in GOVERNANCE_SCOPES or role not in GOVERNANCE_ROLES:
            errors.append(f"{location} has an invalid scope or role")
            continue
        approval_id = receipt.get("approval_id")
        event = receipt.get("approval_event")
        event_id = event.get("id") if isinstance(event, dict) else None
        if not isinstance(approval_id, str) or not approval_id.strip() or approval_id in seen_ids:
            errors.append(f"{location} approval ID is missing or duplicated")
        if pair in seen_pairs:
            errors.append(f"{location} duplicates approval for {scope}/{role}")
        if not isinstance(event_id, str) or event_id in seen_events:
            errors.append(f"{location} Buzz event ID is missing or replayed")
        seen_ids.add(str(approval_id))
        seen_pairs.add(pair)
        seen_events.add(str(event_id))
        assignment = assignment_by_role.get(str(role), {})
        if receipt.get("actor_id") != assignment.get("actor_id"):
            errors.append(f"{location} actor differs from the assigned role")
        if receipt.get("actor_pubkey") != assignment.get("buzz_pubkey"):
            errors.append(f"{location} actor key differs from the assigned role")
        if receipt.get("benchmark_id") != manifest.get("benchmark_id"):
            errors.append(f"{location} benchmark ID differs")
        if receipt.get("benchmark_version") != manifest.get("version"):
            errors.append(f"{location} benchmark version differs")
        try:
            expected_material = benchmark_material_sha256(root, str(scope))
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            errors.append(f"{location} material is unavailable: {exc}")
            expected_material = None
        if receipt.get("material_sha256") != expected_material:
            errors.append(f"{location} material hash differs")
        receipt_errors = _event_errors(
            event,
            pubkey=str(assignment.get("buzz_pubkey", "")),
            channel_id=str(channel_id or ""),
            content=governance_approval_content(receipt),
        )
        errors.extend(f"{location}: {item}" for item in receipt_errors)
        if not any(item.startswith(location) for item in errors):
            approvals[str(scope)][str(role)] = True
    return {
        "valid": not errors,
        "configured": True,
        "errors": errors,
        "approvals": approvals,
        "receipt_count": len(receipts),
        "material_sha256": {
            scope: benchmark_material_sha256(root, scope) for scope in GOVERNANCE_SCOPES
        },
    }


def scope_approved(report: dict[str, Any], scope: str, roles: tuple[str, ...] = GOVERNANCE_ROLES) -> bool:
    return bool(
        report.get("valid")
        and all(report.get("approvals", {}).get(scope, {}).get(role) is True for role in roles)
    )


@contextmanager
def _governance_lock(path: Path):
    lock_path = path.with_suffix(path.suffix + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(value, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
    finally:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)


def configure_benchmark_governance(root: Path, authority: dict[str, Any]) -> dict[str, Any]:
    root = root.resolve()
    path = root / "benchmarks" / "first_pass" / "benchmark_governance.v1.json"
    manifest = json.loads((root / "benchmarks/first_pass/benchmark_manifest.v2.json").read_text())
    with _governance_lock(path):
        current = json.loads(path.read_text(encoding="utf-8"))
        if current.get("authority", {}).get("state") != "unconfigured" or current.get("receipts"):
            raise ValueError("benchmark governance is already configured; amendments require a new benchmark version")
        proposed = {
            "schema_version": 1,
            "benchmark_id": manifest["benchmark_id"],
            "benchmark_version": manifest["version"],
            "authority": authority,
            "receipts": [],
        }
        report = validate_benchmark_governance(root, proposed)
        if not report["valid"] or not report["configured"]:
            raise ValueError("invalid signed governance authority: " + "; ".join(report["errors"]))
        _atomic_json(path, proposed)
    return proposed


def record_benchmark_governance_approval(root: Path, receipt: dict[str, Any]) -> dict[str, Any]:
    root = root.resolve()
    path = root / "benchmarks" / "first_pass" / "benchmark_governance.v1.json"
    with _governance_lock(path):
        current = json.loads(path.read_text(encoding="utf-8"))
        if any(
            item.get("scope") == receipt.get("scope") and item.get("role") == receipt.get("role")
            for item in current.get("receipts", []) if isinstance(item, dict)
        ):
            raise ValueError("this governance scope and role already has a receipt")
        proposed = {**current, "receipts": [*current.get("receipts", []), receipt]}
        report = validate_benchmark_governance(root, proposed)
        if not report["valid"]:
            raise ValueError("invalid governance approval: " + "; ".join(report["errors"]))
        _atomic_json(path, proposed)
    return receipt
