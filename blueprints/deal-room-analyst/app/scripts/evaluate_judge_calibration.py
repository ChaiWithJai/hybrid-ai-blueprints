#!/usr/bin/env python3
"""Evaluate a semantic judge against signed calibration labels."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.judge_calibration import evaluate_judge_calibration  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("record", help="Judge calibration input JSON.")
    parser.add_argument(
        "--output",
        default="evidence/first-pass-judge-calibration.json",
    )
    args = parser.parse_args()
    record_path = (ROOT / args.record).resolve()
    record = json.loads(record_path.read_text(encoding="utf-8"))
    result = evaluate_judge_calibration(ROOT, record)
    result["input_path"] = str(record_path.relative_to(ROOT))
    output = (ROOT / args.output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["calibration_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
