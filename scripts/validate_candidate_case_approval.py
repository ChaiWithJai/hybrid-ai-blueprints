#!/usr/bin/env python3
"""Validate a domain-owner-signed candidate case without registering it."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.buzz_bridge import BuzzBridge, BuzzUnavailable  # noqa: E402
from core.candidate_case_approval import candidate_case_approval_report  # noqa: E402
from core.candidate_source_review import build_candidate_source_review_packet  # noqa: E402


def resolve_path(value: str) -> Path:
    path = Path(value).expanduser()
    return path.resolve() if path.is_absolute() else (Path.cwd() / path).resolve()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--submission", action="append", required=True)
    parser.add_argument("--adjudication")
    parser.add_argument("--approval", required=True)
    parser.add_argument("--buzz-channel", required=True)
    parser.add_argument("--output")
    args = parser.parse_args()
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
        expected_event_ids = {
            item.get("buzz_event_id") for item in submissions if item.get("buzz_event_id")
        }
        if adjudication and adjudication.get("buzz_event_id"):
            expected_event_ids.add(adjudication["buzz_event_id"])
        if approval.get("buzz_event_id"):
            expected_event_ids.add(approval["buzz_event_id"])
        events = BuzzBridge(ROOT).events_by_ids(
            expected_event_ids, channel_id=args.buzz_channel,
        )
        report = candidate_case_approval_report(
            ROOT,
            build_candidate_source_review_packet(ROOT),
            submissions,
            adjudication,
            approval,
            signed_events=events,
        )
    except (OSError, json.JSONDecodeError, BuzzUnavailable, ValueError) as exc:
        print(json.dumps({"approval_valid": False, "error": str(exc)}, indent=2))
        return 2
    if args.output:
        output = resolve_path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["approval_valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
