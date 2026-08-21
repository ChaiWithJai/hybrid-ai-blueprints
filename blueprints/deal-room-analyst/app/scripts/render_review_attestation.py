#!/usr/bin/env python3
"""Render the exact content a reviewer must sign and publish through Buzz."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.review_signatures import review_attestation_content  # noqa: E402


KINDS = (
    "candidate_source_review",
    "candidate_source_adjudication",
    "blinded_output_review",
    "blinded_output_adjudication",
)


def render(record_path: Path, kind: str) -> str:
    record = json.loads(record_path.read_text(encoding="utf-8"))
    actor = record.get("reviewer_id") or record.get("principal_reviewer_id")
    record_id = record.get("review_id") or record.get("adjudication_id")
    if not actor or not record_id or not record.get("packet_sha256"):
        raise ValueError("record needs an actor ID, record ID, and packet_sha256")
    if not record.get("reviewer_pubkey"):
        raise ValueError("record needs the roster-bound reviewer_pubkey")
    return review_attestation_content(kind, record)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--kind", required=True, choices=KINDS)
    parser.add_argument("--record", required=True)
    args = parser.parse_args()
    try:
        print(render((ROOT / args.record).resolve(), args.kind))
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(json.dumps({"rendered": False, "error": str(exc)}, indent=2), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
