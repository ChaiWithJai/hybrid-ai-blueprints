#!/usr/bin/env python3
"""Validate two blinded review submissions and report disagreements."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.first_pass_review import (  # noqa: E402
    compare_reviewers,
    packet_sha256,
    resolve_human_labels,
    validate_human_review_receipt,
    validate_principal_adjudication,
)
from core.buzz_bridge import BuzzBridge, BuzzUnavailable  # noqa: E402


def fetch_signed_events(
    submissions: list[dict],
    adjudication: dict | None,
    buzz_channel: str,
    bridge: BuzzBridge | None = None,
) -> dict[str, dict]:
    """Restore every submitted attestation, including agreement-only reviews."""
    expected_event_ids = {
        item.get("buzz_event_id") for item in submissions
        if item.get("buzz_event_id")
    }
    if adjudication is not None and adjudication.get("buzz_event_id"):
        expected_event_ids.add(adjudication["buzz_event_id"])
    return (bridge or BuzzBridge(ROOT)).events_by_ids(
        expected_event_ids, channel_id=buzz_channel,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--packet",
        default="evidence/first-pass-human-review-packet-v2.json",
    )
    parser.add_argument(
        "--adjudication",
        help="A principal adjudication JSON file, required when reviewers disagree.",
    )
    parser.add_argument(
        "--submission",
        action="append",
        required=True,
        help="A completed review JSON file. Supply this option once per reviewer.",
    )
    parser.add_argument("--output", default="evidence/first-pass-review-validation.json")
    parser.add_argument(
        "--buzz-channel",
        required=True,
        help="Private Buzz channel containing reviewer-signed attestation events.",
    )
    args = parser.parse_args()
    packet_path = (ROOT / args.packet).resolve()
    packet = json.loads(packet_path.read_text(encoding="utf-8"))
    submissions = [
        json.loads((ROOT / item).resolve().read_text(encoding="utf-8"))
        for item in args.submission
    ]
    adjudication = (
        json.loads((ROOT / args.adjudication).resolve().read_text(encoding="utf-8"))
        if args.adjudication else None
    )
    try:
        signed_events = fetch_signed_events(
            submissions, adjudication, args.buzz_channel,
        )
    except (BuzzUnavailable, KeyError) as exc:
        print(json.dumps({"review_gate_complete": False, "error": str(exc)}, indent=2))
        return 2
    comparison = compare_reviewers(ROOT, packet, submissions, signed_events=signed_events)
    adjudication_errors = []
    adjudication_supplied = bool(args.adjudication)
    if adjudication is not None:
        adjudication_errors = validate_principal_adjudication(
            ROOT,
            packet,
            comparison,
            [item.get("reviewer_id") for item in submissions],
            adjudication,
            signed_events=signed_events,
        )
    adjudication_complete = bool(
        not comparison["principal_adjudication_required"]
        or (adjudication_supplied and not adjudication_errors)
    )
    review_gate_complete = bool(
        comparison["valid"]
        and len(submissions) >= 2
        and adjudication_complete
    )
    resolved_labels = (
        resolve_human_labels(packet, submissions, comparison, adjudication)
        if review_gate_complete else []
    )
    resolved_labels_sha256 = (
        hashlib.sha256(json.dumps(
            resolved_labels, sort_keys=True, separators=(",", ":")
        ).encode()).hexdigest()
        if resolved_labels else None
    )
    receipt = {
        "verification_kind": "blinded_first_pass_review_validation",
        "packet_path": str(packet_path.relative_to(ROOT)),
        "packet_sha256": packet_sha256(packet),
        "submission_count": len(submissions),
        "reviewer_ids": [item.get("reviewer_id") for item in submissions],
        **comparison,
        "adjudication_supplied": adjudication_supplied,
        "adjudication_errors": adjudication_errors,
        "adjudication_complete": adjudication_complete,
        "review_gate_complete": review_gate_complete,
        "resolved_labels": resolved_labels,
        "resolved_labels_sha256": resolved_labels_sha256,
        "reviewer_roster_sha256": hashlib.sha256(
            (ROOT / "benchmarks" / "first_pass" / "output_reviewer_roster.v1.json").read_bytes()
        ).hexdigest(),
        "buzz_channel_id": args.buzz_channel,
        "submissions": submissions,
        "adjudication": adjudication,
        "signed_events": signed_events,
        "limitations": [
            "A valid pair records reviewer agreement. It does not approve the 120 case release set.",
            "Roster membership and a distinct Buzz signing key are enforced; legal identity verification remains a domain-owner responsibility.",
        ],
    }
    replay = validate_human_review_receipt(ROOT, receipt)
    if review_gate_complete and not replay["passed"]:
        receipt["review_gate_complete"] = False
        receipt["errors"] = [
            *receipt.get("errors", []),
            *(f"receipt replay: {item}" for item in replay["errors"]),
        ]
    output = (ROOT / args.output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(receipt, indent=2, sort_keys=True))
    return 0 if receipt["review_gate_complete"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
