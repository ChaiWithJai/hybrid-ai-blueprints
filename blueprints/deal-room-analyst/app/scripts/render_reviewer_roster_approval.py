#!/usr/bin/env python3
"""Render the exact reviewer admission that a configured owner must sign."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.reviewer_roster_authority import reviewer_roster_approval_content  # noqa: E402


ROSTER_FILES = {
    "source_review": "source_reviewer_roster.v1.json",
    "output_review": "output_reviewer_roster.v1.json",
}
ROLES = {
    "source_review": {
        "qualified_deal_source_reviewer", "principal_source_reviewer", "domain_case_owner",
    },
    "output_review": {
        "qualified_deal_output_reviewer", "principal_output_reviewer",
    },
}


def build_record(args: argparse.Namespace) -> tuple[dict, dict, str]:
    roster_path = ROOT / "benchmarks" / "first_pass" / ROSTER_FILES[args.scope]
    roster = json.loads(roster_path.read_text(encoding="utf-8"))
    authority = roster.get("authority", {})
    if authority.get("state") != "signed_buzz_authority":
        raise ValueError("reviewer roster authority is not configured")
    if args.role not in ROLES[args.scope]:
        raise ValueError("role is not allowed for this roster")
    if not re.fullmatch(r"[a-z0-9][a-z0-9._-]{2,79}", args.reviewer_id):
        raise ValueError("reviewer ID is invalid")
    if not re.fullmatch(r"[a-f0-9]{64}", args.buzz_pubkey):
        raise ValueError("reviewer Buzz public key is invalid")
    record = {
        "reviewer_id": args.reviewer_id,
        "display_name": args.display_name.strip(),
        "role": args.role,
        "qualification": args.qualification.strip(),
        "buzz_pubkey": args.buzz_pubkey,
        "approved_by": authority["authority_id"],
        "approved_at": args.approved_at,
        "active": True,
    }
    return record, authority, reviewer_roster_approval_content(args.scope, record)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scope", required=True, choices=sorted(ROSTER_FILES))
    parser.add_argument("--reviewer-id", required=True)
    parser.add_argument("--display-name", required=True)
    parser.add_argument("--role", required=True)
    parser.add_argument("--qualification", required=True)
    parser.add_argument("--buzz-pubkey", required=True)
    parser.add_argument("--approved-at", required=True)
    args = parser.parse_args()
    try:
        record, authority, content = build_record(args)
    except (OSError, json.JSONDecodeError, KeyError, ValueError) as exc:
        print(json.dumps({"rendered": False, "error": str(exc)}, indent=2), file=sys.stderr)
        return 2
    print(json.dumps({
        "rendered": True,
        "scope": args.scope,
        "authority_id": authority["authority_id"],
        "authority_pubkey": authority["buzz_pubkey"],
        "buzz_channel": authority["channel_id"],
        "reviewer": record,
        "content": content,
        "next_step": "Publish content with the authority key, then pass the restored event ID to the matching add reviewer command.",
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
