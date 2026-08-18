#!/usr/bin/env python3
"""Validate real candidate source reviews without manufacturing approvals."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.candidate_source_review import (  # noqa: E402
    build_candidate_source_review_packet,
    evaluate_source_review_state,
)
from core.buzz_bridge import BuzzBridge, BuzzUnavailable  # noqa: E402


def _load_json_files(folder: Path) -> list[dict]:
    if not folder.exists():
        return []
    return [json.loads(path.read_text(encoding="utf-8")) for path in sorted(folder.glob("*.json"))]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--submissions-dir",
        default="benchmarks/first_pass/source_reviews",
    )
    parser.add_argument(
        "--adjudication",
        default="benchmarks/first_pass/source_review_adjudication.json",
    )
    parser.add_argument(
        "--buzz-channel",
        help="Private Buzz channel containing reviewer-signed attestation events.",
    )
    parser.add_argument(
        "--output",
        default="evidence/candidate-source-review-validation-v1.json",
    )
    args = parser.parse_args()
    packet = build_candidate_source_review_packet(ROOT)
    submissions = _load_json_files((ROOT / args.submissions_dir).resolve())
    adjudication_path = (ROOT / args.adjudication).resolve()
    adjudication = (
        json.loads(adjudication_path.read_text(encoding="utf-8"))
        if adjudication_path.exists() else None
    )
    signed_events = {}
    if submissions or adjudication is not None:
        if not args.buzz_channel:
            print(json.dumps({
                "validation_passed": False,
                "error": "--buzz-channel is required when review records exist",
            }, indent=2))
            return 2
        try:
            expected_event_ids = {
                item.get("buzz_event_id") for item in submissions
                if item.get("buzz_event_id")
            }
            if adjudication is not None:
                expected_event_ids.add(adjudication.get("buzz_event_id"))
            signed_events = BuzzBridge(ROOT).events_by_ids(
                expected_event_ids, channel_id=args.buzz_channel,
            )
        except (BuzzUnavailable, KeyError) as exc:
            print(json.dumps({"validation_passed": False, "error": str(exc)}, indent=2))
            return 2
    report = evaluate_source_review_state(
        ROOT, packet, submissions, adjudication, signed_events=signed_events,
    )
    output = (ROOT / args.output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["validation_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
