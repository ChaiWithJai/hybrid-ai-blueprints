#!/usr/bin/env python3
"""Validate benchmark structure and report release readiness separately."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.first_pass_benchmark import validate_contract  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        default="evidence/first-pass-benchmark-contract-v2.json",
    )
    args = parser.parse_args()
    report = validate_contract(ROOT)
    output = (ROOT / args.output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["structural_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
