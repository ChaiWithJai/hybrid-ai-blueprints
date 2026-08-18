#!/usr/bin/env python3
"""Export a development review packet with model identity removed."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.first_pass_review import build_review_packet, packet_sha256  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--responses",
        default="evidence/bonsai-public-deal-battletest-responses.json",
    )
    parser.add_argument(
        "--output",
        default="evidence/first-pass-human-review-packet-v2.json",
    )
    args = parser.parse_args()
    packet = build_review_packet(ROOT, (ROOT / args.responses).resolve())
    output = (ROOT / args.output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(packet, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "output": str(output),
        "packet_sha256": packet_sha256(packet),
        "case_count": len(packet["cases"]),
        "blinded_to_model": packet["blinded_to_model"],
        "model_identity_included": packet["model_identity_included"],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
