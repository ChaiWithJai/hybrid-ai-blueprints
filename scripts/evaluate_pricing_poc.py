#!/usr/bin/env python3
"""Evaluate one buyer-attested paid proof of concept record."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.buzz_bridge import BuzzBridge  # noqa: E402
from core.pricing_poc import validate_saved_pricing_poc  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("record", help="Pricing POC input JSON relative to the project root.")
    parser.add_argument("--output", default="evidence/first-pass-pricing-poc-evaluation.json")
    args = parser.parse_args()
    record_path = (ROOT / args.record).resolve()
    record_path.relative_to(ROOT)
    bridge = BuzzBridge(ROOT)
    result = validate_saved_pricing_poc(
        ROOT,
        record_path,
        event_resolver=lambda event_ids, channel_id: bridge.events_by_ids(
            event_ids, channel_id=channel_id,
        ),
    )
    output = (ROOT / args.output).resolve()
    output.relative_to(ROOT)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["pricing_poc_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
