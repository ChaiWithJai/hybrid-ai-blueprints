#!/usr/bin/env python3
"""Record one valid signed candidate case approval without registering it."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.buzz_bridge import BuzzBridge, BuzzUnavailable  # noqa: E402
from core.candidate_case_registration import record_candidate_case_approval  # noqa: E402
from core.candidate_source_review import (  # noqa: E402
    build_candidate_source_review_packet,
    load_source_reviewer_roster,
)


def resolve_path(value: str) -> Path:
    path = Path(value).expanduser()
    return path.resolve() if path.is_absolute() else (Path.cwd() / path).resolve()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--submission", action="append", required=True)
    parser.add_argument("--adjudication")
    parser.add_argument("--approval", required=True)
    parser.add_argument("--buzz-channel", required=True)
    parser.add_argument("--confirm-record-signed-approval", action="store_true")
    args = parser.parse_args()
    if not args.confirm_record_signed_approval:
        print(json.dumps({
            "recorded": False,
            "error": "--confirm-record-signed-approval is required for the approval ledger commit",
        }, indent=2))
        return 2
    try:
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
        entry = record_candidate_case_approval(
            ROOT,
            packet=build_candidate_source_review_packet(ROOT),
            submissions=submissions,
            adjudication=adjudication,
            approval=approval,
            reviewer_roster=load_source_reviewer_roster(ROOT),
            signed_events=events,
            recorded_at=datetime.now(timezone.utc).isoformat(),
        )
    except (BuzzUnavailable, KeyError, OSError, json.JSONDecodeError, ValueError) as exc:
        print(json.dumps({"recorded": False, "error": str(exc)}, indent=2))
        return 2
    print(json.dumps({
        "recorded": True,
        "approval_record_id": entry["approval_record_id"],
        "approval_id": entry["approval_id"],
        "case_id": entry["case_id"],
        "candidate_id": entry["candidate_id"],
        "ledger": "benchmarks/first_pass/candidate_case_approval_records.v1.json",
        "benchmark_case_registered": False,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
