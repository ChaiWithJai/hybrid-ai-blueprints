"""Signed benchmark-governance fixtures. Test private keys never enter product artifacts."""

from __future__ import annotations

import json
from pathlib import Path

from core.benchmark_governance import (
    GOVERNANCE_ROLES,
    GOVERNANCE_SCOPES,
    benchmark_material_sha256,
    governance_approval_content,
    governance_authority_content,
)
from core.nostr_event import public_key_from_private
from tests.nostr_signing import sign_event


ROOT_PRIVATE_KEY = "41" * 32
ROLE_PRIVATE_KEYS = {
    role: f"{42 + index:02x}" * 32 for index, role in enumerate(GOVERNANCE_ROLES)
}
CHANNEL_ID = "prism-benchmark-governance-test"


def _event(private_key: str, content: str, created_at: int) -> dict:
    return sign_event({
        "created_at": created_at,
        "kind": 1,
        "tags": [["h", CHANNEL_ID]],
        "content": content,
    }, private_key)


def signed_governance(root: Path) -> dict:
    manifest = json.loads(
        (root / "benchmarks/first_pass/benchmark_manifest.v2.json").read_text()
    )
    authority = {
        "state": "signed_buzz_authority",
        "root_authority_id": "benchmark-governance-root",
        "root_buzz_pubkey": public_key_from_private(ROOT_PRIVATE_KEY),
        "channel_id": CHANNEL_ID,
        "role_assignments": [
            {
                "role": role,
                "actor_id": f"test-{role.replace('_', '-')}",
                "buzz_pubkey": public_key_from_private(ROLE_PRIVATE_KEYS[role]),
            }
            for role in GOVERNANCE_ROLES
        ],
        "authority_event": None,
    }
    authority["authority_event"] = _event(
        ROOT_PRIVATE_KEY, governance_authority_content(authority), 1786852800,
    )
    receipts = []
    sequence = 0
    for scope in GOVERNANCE_SCOPES:
        for assignment in authority["role_assignments"]:
            role = assignment["role"]
            receipt = {
                "approval_id": f"approval-{scope}-{role}",
                "scope": scope,
                "role": role,
                "actor_id": assignment["actor_id"],
                "actor_pubkey": assignment["buzz_pubkey"],
                "benchmark_id": manifest["benchmark_id"],
                "benchmark_version": manifest["version"],
                "material_sha256": benchmark_material_sha256(root, scope),
                "approved_at": f"2026-08-16T12:{sequence:02d}:00Z",
                "approval_event": None,
            }
            receipt["approval_event"] = _event(
                ROLE_PRIVATE_KEYS[role], governance_approval_content(receipt),
                1786852860 + sequence,
            )
            receipts.append(receipt)
            sequence += 1
    return {
        "schema_version": 1,
        "benchmark_id": manifest["benchmark_id"],
        "benchmark_version": manifest["version"],
        "authority": authority,
        "receipts": receipts,
    }


def write_signed_governance(root: Path) -> dict:
    ledger = signed_governance(root)
    path = root / "benchmarks/first_pass/benchmark_governance.v1.json"
    path.write_text(json.dumps(ledger, indent=2) + "\n")
    return ledger
