#!/usr/bin/env python3
"""Export the reproducible, model-blind candidate source review packet."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.candidate_source_review import (  # noqa: E402
    build_candidate_source_review_packet,
    packet_sha256,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        default="evidence/candidate-source-review-packet-v1.json",
    )
    args = parser.parse_args()
    output = (ROOT / args.output).resolve()
    packet = build_candidate_source_review_packet(ROOT)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(packet, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "output": str(output),
        "packet_sha256": packet_sha256(packet),
        "candidate_deal_count": packet["candidate_deal_count"],
        "draft_count": packet["draft_count"],
        "review_submissions": 0,
        "benchmark_cases_registered": 0,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

