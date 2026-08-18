#!/usr/bin/env python3
"""Add a domain-owner-approved person to the blinded output reviewer roster."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.first_pass_review import output_reviewer_roster_errors  # noqa: E402
from core.buzz_bridge import BuzzBridge, BuzzUnavailable  # noqa: E402
from core.reviewer_roster_authority import paired_reviewer_roster_authority_errors  # noqa: E402
from core.reviewer_roster_ledger import mutate_reviewer_roster  # noqa: E402


def add_output_reviewer(
    root: Path,
    *,
    reviewer_id: str,
    display_name: str,
    role: str,
    qualification: str,
    buzz_pubkey: str,
    approved_by: str,
    approved_at: str,
    approval_event: dict,
    approval_confirmed: bool,
) -> dict:
    if not approval_confirmed:
        raise ValueError("explicit domain-owner approval confirmation is required")
    if not re.fullmatch(r"[a-z0-9][a-z0-9._-]{2,79}", reviewer_id):
        raise ValueError("reviewer_id must be 3-80 lowercase letters, numbers, dots, underscores, or hyphens")
    if role not in {"qualified_deal_output_reviewer", "principal_output_reviewer"}:
        raise ValueError("role is not an allowed output reviewer role")
    if not re.fullmatch(r"[a-f0-9]{64}", buzz_pubkey):
        raise ValueError("buzz_pubkey must be a 64-character lowercase hex Nostr public key")
    for label, value, maximum in (
        ("display_name", display_name, 160),
        ("qualification", qualification, 1_000),
        ("approved_by", approved_by, 160),
    ):
        if not value.strip() or len(value) > maximum:
            raise ValueError(f"{label} must contain 1-{maximum} characters")
    roster_path = root / "benchmarks" / "first_pass" / "output_reviewer_roster.v1.json"
    record = {
        "reviewer_id": reviewer_id,
        "display_name": display_name.strip(),
        "role": role,
        "qualification": qualification.strip(),
        "buzz_pubkey": buzz_pubkey,
        "approved_by": approved_by.strip(),
        "approved_at": approved_at,
        "active": True,
        "approval_event": approval_event,
    }
    def mutate(roster: dict) -> dict:
        if any(item["reviewer_id"] == reviewer_id for item in roster["reviewers"]):
            raise ValueError(
                "reviewer_id already exists; roster changes require an explicit amendment workflow"
            )
        if any(item["buzz_pubkey"] == buzz_pubkey for item in roster["reviewers"]):
            raise ValueError("buzz_pubkey already belongs to another reviewer")
        roster["reviewers"].append(record)
        roster["reviewers"].sort(key=lambda item: item["reviewer_id"])
        return record

    return mutate_reviewer_roster(
        root,
        roster_path,
        validate=lambda roster: [
            *output_reviewer_roster_errors(root, roster),
            *paired_reviewer_roster_authority_errors(
                root, roster, scope="output_review"
            ),
        ],
        mutate=mutate,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reviewer-id", required=True)
    parser.add_argument("--display-name", required=True)
    parser.add_argument(
        "--role",
        required=True,
        choices=["qualified_deal_output_reviewer", "principal_output_reviewer"],
    )
    parser.add_argument("--qualification", required=True)
    parser.add_argument("--buzz-pubkey", required=True)
    parser.add_argument("--approved-by", required=True)
    parser.add_argument("--approved-at", required=True)
    parser.add_argument("--approval-event-id", required=True)
    parser.add_argument("--buzz-channel", required=True)
    parser.add_argument("--confirm-domain-owner-approval", action="store_true")
    args = parser.parse_args()
    try:
        bridge = BuzzBridge(ROOT)
        restored = bridge.events_by_ids(
            {args.approval_event_id}, channel_id=args.buzz_channel,
        )
        approval_event = restored.get(args.approval_event_id)
        if approval_event is None:
            raise ValueError("signed roster approval was not restored from Buzz")
        record = add_output_reviewer(
            ROOT,
            reviewer_id=args.reviewer_id,
            display_name=args.display_name,
            role=args.role,
            qualification=args.qualification,
            buzz_pubkey=args.buzz_pubkey,
            approved_by=args.approved_by,
            approved_at=args.approved_at,
            approval_event=approval_event,
            approval_confirmed=args.confirm_domain_owner_approval,
        )
    except (ValueError, BuzzUnavailable) as exc:
        print(json.dumps({"added": False, "error": str(exc)}, indent=2))
        return 2
    print(json.dumps({"added": True, "reviewer": record}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
