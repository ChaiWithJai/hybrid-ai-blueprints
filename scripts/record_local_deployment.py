#!/usr/bin/env python3
"""Record the exact loaded Bonsai artifacts and sanitized LM Studio runtime."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.deployment_evidence import record_local_deployment, validate_deployment_record  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="27b@q1_0")
    parser.add_argument(
        "--output", default="evidence/local-deployment-current.json",
        help="Output path relative to the project root unless absolute.",
    )
    args = parser.parse_args()
    output = Path(args.output)
    if not output.is_absolute():
        output = ROOT / output
    report = record_local_deployment(args.model)
    errors = validate_deployment_record(report)
    if errors:
        raise RuntimeError("; ".join(errors))
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "output": str(output),
        "model": report["model"]["identifier"],
        "artifact_count": len(report["artifacts"]),
        "runtime_version": report["runtime"]["version"],
        "fitted_context_length": report["runtime"]["effective_config"]["fitted_context_length"],
        "bind_host": report["runtime"]["effective_config"]["bind_host"],
        "bind_port": report["runtime"]["effective_config"]["bind_port"],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
