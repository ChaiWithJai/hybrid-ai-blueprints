#!/usr/bin/env python3
"""Evaluate saved development responses without claiming semantic accuracy."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.first_pass_benchmark import evaluate_development_responses  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--responses",
        default="evidence/bonsai-public-deal-battletest-responses.json",
    )
    parser.add_argument(
        "--output",
        default="evidence/first-pass-development-evaluation-v2.json",
    )
    args = parser.parse_args()
    responses = (ROOT / args.responses).resolve()
    report = evaluate_development_responses(ROOT, responses)
    output = (ROOT / args.output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "output": str(output),
        "case_count": report["case_count"],
        "deterministic_failure_count": report["deterministic_failure_count"],
        "semantic_unverified_count": report["semantic_unverified_count"],
        "accuracy_release_passed": report["accuracy_release_passed"],
    }, indent=2))
    return 0 if report["contract_structural_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
