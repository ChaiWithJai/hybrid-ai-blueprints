#!/usr/bin/env python3
"""Check the actual host dependencies for the local Prism/Buzz/Bonsai surface."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.operator_preflight import collect_preflight  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", choices=("host", "live"), default="host")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--output", help="Write the JSON report to this path")
    parser.add_argument(
        "--model-url", default=os.environ.get("PRISM_LOCAL_AI_URL", "http://127.0.0.1:1234")
    )
    parser.add_argument(
        "--model", default=os.environ.get("PRISM_LOCAL_AI_MODEL", "27b@q1_0")
    )
    parser.add_argument(
        "--buzz-url", default=os.environ.get("PRISM_BUZZ_HTTP_URL", "http://127.0.0.1:3030")
    )
    args = parser.parse_args()
    report = collect_preflight(
        ROOT, phase=args.phase, model_url=args.model_url, model=args.model,
        buzz_url=args.buzz_url,
    )
    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(f"Prism operator preflight ({args.phase})")
        for check in report["checks"]:
            marker = "PASS" if check["passed"] else ("WARN" if not check["required"] else "FAIL")
            print(f"[{marker}] {check['name']}: {check['state']}")
            if marker != "PASS" and check.get("remediation"):
                print(f"       {check['remediation']}")
        print("Required checks passed." if report["required_passed"] else "Required checks failed.")
        print("Boundary: same-host preflight; this is not clean-machine reproduction.")
    return 0 if report["required_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
