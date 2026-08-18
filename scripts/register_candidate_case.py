#!/usr/bin/env python3
"""Atomically register one approved public candidate case in the ledger."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.buzz_bridge import BuzzBridge, BuzzUnavailable  # noqa: E402
from core.candidate_case_registration import (  # noqa: E402
    load_approval_record_bundle,
    register_candidate_case,
)
from core.candidate_source_review import (  # noqa: E402
    build_candidate_source_review_packet,
    load_source_reviewer_roster,
)


def resolve_path(value: str) -> Path:
    path = Path(value).expanduser()
    return path.resolve() if path.is_absolute() else (Path.cwd() / path).resolve()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--submission", action="append")
    parser.add_argument("--adjudication")
    parser.add_argument("--approval")
    parser.add_argument("--buzz-channel")
    parser.add_argument("--approval-record-id")
    parser.add_argument("--confirm-register-approved-case", action="store_true")
    args = parser.parse_args()
    if not args.confirm_register_approved_case:
        print(json.dumps({
            "registered": False,
            "error": "--confirm-register-approved-case is required for the ledger commit",
        }, indent=2))
        return 2
    try:
        if args.approval_record_id:
            if any((args.submission, args.adjudication, args.approval, args.buzz_channel)):
                raise ValueError(
                    "--approval-record-id cannot be combined with raw approval inputs"
                )
            bundle = load_approval_record_bundle(ROOT, args.approval_record_id)
            packet = bundle["packet"]
            submissions = bundle["submissions"]
            adjudication = bundle["adjudication"]
            approval = bundle["approval"]
            roster = bundle["reviewer_roster"]
            events = bundle["signed_events"]
        else:
            if not args.submission or not args.approval or not args.buzz_channel:
                raise ValueError(
                    "use --approval-record-id, or provide --submission, --approval, and --buzz-channel"
                )
            packet = build_candidate_source_review_packet(ROOT)
            submissions = [
                json.loads(resolve_path(path).read_text(encoding="utf-8"))
                for path in args.submission
            ]
            adjudication = (
                json.loads(resolve_path(args.adjudication).read_text(encoding="utf-8"))
                if args.adjudication else None
            )
            approval = json.loads(resolve_path(args.approval).read_text(encoding="utf-8"))
            event_ids = {
                item["buzz_event_id"] for item in submissions if item.get("buzz_event_id")
            }
            if adjudication and adjudication.get("buzz_event_id"):
                event_ids.add(adjudication["buzz_event_id"])
            event_ids.add(approval["buzz_event_id"])
            events = BuzzBridge(ROOT).events_by_ids(event_ids, channel_id=args.buzz_channel)
            roster = load_source_reviewer_roster(ROOT)
        entry = register_candidate_case(
            ROOT,
            packet=packet,
            submissions=submissions,
            adjudication=adjudication,
            approval=approval,
            reviewer_roster=roster,
            signed_events=events,
            registered_at=datetime.now(timezone.utc).isoformat(),
        )
    except (BuzzUnavailable, KeyError, OSError, json.JSONDecodeError, ValueError) as exc:
        print(json.dumps({"registered": False, "error": str(exc)}, indent=2))
        return 2
    print(json.dumps({
        "registered": True,
        "registration_id": entry["registration_id"],
        "case_id": entry["case_id"],
        "candidate_id": entry["candidate_id"],
        "source_path": entry["source_document"]["path"],
        "ledger": "benchmarks/first_pass/candidate_case_registrations.v1.json",
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
