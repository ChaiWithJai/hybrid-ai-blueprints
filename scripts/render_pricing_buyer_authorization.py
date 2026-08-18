#!/usr/bin/env python3
"""Render the exact commercial-authority statement for one unsigned POC."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.pricing_poc import pricing_buyer_authorization_content  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("record", help="Unsigned pricing POC JSON inside the project.")
    parser.add_argument("--json", action="store_true", help="Print a JSON wrapper.")
    args = parser.parse_args()
    record_path = (ROOT / args.record).resolve()
    record_path.relative_to(ROOT)
    record = json.loads(record_path.read_text(encoding="utf-8"))
    if "buyer_authorization" in record or "buyer_attestation" in record:
        raise ValueError("the input must be an unsigned pricing POC")
    buyer = record.get("buyer", {}) if isinstance(record.get("buyer"), dict) else {}
    if not record.get("poc_id"):
        raise ValueError("the unsigned POC has no poc_id")
    if not re.fullmatch(r"[a-f0-9]{64}", str(buyer.get("buyer_pubkey") or "")):
        raise ValueError("the unsigned POC has no valid buyer_pubkey")
    content = pricing_buyer_authorization_content(record)
    if args.json:
        print(json.dumps({
            "authorization_kind": "pricing_buyer_authorization_v1",
            "record": str(record_path.relative_to(ROOT)),
            "content": content,
            "meaning": (
                "A configured commercial authority must publish this exact text "
                "to PRISM_PRICING_AUTHORITY_CHANNEL with its own Buzz key."
            ),
        }, indent=2))
    else:
        print(content)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
