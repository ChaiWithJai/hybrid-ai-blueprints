#!/usr/bin/env python3
"""Publish and record one role-specific benchmark governance approval."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.benchmark_governance import (  # noqa: E402
    GOVERNANCE_ROLES,
    GOVERNANCE_SCOPES,
    benchmark_material_sha256,
    governance_approval_content,
    record_benchmark_governance_approval,
    validate_benchmark_governance,
)
from core.buzz_bridge import BuzzBridge, BuzzUnavailable  # noqa: E402
from core.nostr_event import public_key_from_private  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scope", required=True, choices=GOVERNANCE_SCOPES)
    parser.add_argument("--role", required=True, choices=GOVERNANCE_ROLES)
    parser.add_argument("--confirm-approval", action="store_true")
    args = parser.parse_args()
    try:
        if not args.confirm_approval:
            raise ValueError("explicit benchmark governance approval confirmation is required")
        ledger_path = ROOT / "benchmarks/first_pass/benchmark_governance.v1.json"
        ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
        current = validate_benchmark_governance(ROOT, ledger)
        if not current["valid"] or not current["configured"]:
            raise ValueError("benchmark governance authority is not valid and configured")
        assignment = next(
            item for item in ledger["authority"]["role_assignments"] if item["role"] == args.role
        )
        private_key = os.environ.get("BUZZ_PRIVATE_KEY", "")
        if not private_key:
            raise ValueError("BUZZ_PRIVATE_KEY must contain the assigned role private key")
        if public_key_from_private(private_key) != assignment["buzz_pubkey"]:
            raise ValueError("BUZZ_PRIVATE_KEY does not match the assigned role public key")
        material_hash = benchmark_material_sha256(ROOT, args.scope)
        receipt = {
            "approval_id": f"gov-{args.scope}-{args.role}-{material_hash[:16]}",
            "scope": args.scope,
            "role": args.role,
            "actor_id": assignment["actor_id"],
            "actor_pubkey": assignment["buzz_pubkey"],
            "benchmark_id": ledger["benchmark_id"],
            "benchmark_version": ledger["benchmark_version"],
            "material_sha256": material_hash,
            "approved_at": datetime.now(timezone.utc).isoformat(),
            "approval_event": None,
        }
        bridge = BuzzBridge(ROOT)
        environment = os.environ.copy()
        environment.setdefault("BUZZ_RELAY_URL", bridge.relay_url)
        completed = subprocess.run(
            [str(bridge.binary), "messages", "send", "--channel", ledger["authority"]["channel_id"], "--content", "-"],
            cwd=ROOT, env=environment, input=governance_approval_content(receipt),
            text=True, capture_output=True, timeout=20, check=False,
        )
        if completed.returncode != 0:
            raise BuzzUnavailable(completed.stderr.strip() or completed.stdout.strip() or "Buzz publish failed")
        published = json.loads(completed.stdout)
        event_id = str(published.get("event_id") or published.get("id") or "")
        event = bridge.events_by_ids(
            {event_id}, channel_id=ledger["authority"]["channel_id"]
        ).get(event_id)
        if event is None:
            raise BuzzUnavailable("published governance approval was not restored from Buzz")
        receipt["approval_event"] = event
        record_benchmark_governance_approval(ROOT, receipt)
    except (OSError, StopIteration, ValueError, json.JSONDecodeError, subprocess.TimeoutExpired, BuzzUnavailable) as exc:
        print(json.dumps({"approved": False, "error": str(exc)}, indent=2), file=sys.stderr)
        return 2
    print(json.dumps({
        "approved": True,
        "scope": args.scope,
        "role": args.role,
        "approval_id": receipt["approval_id"],
        "approval_event_id": receipt["approval_event"]["id"],
        "material_sha256": material_hash,
        "role_signature_verified": True,
        "relay_event_restored": True,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
