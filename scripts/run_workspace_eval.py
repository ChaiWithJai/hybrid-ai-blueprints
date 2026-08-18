#!/usr/bin/env python3
"""Run the Prism workspace development evaluation and save its evidence."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.workspace_eval import run_workspace_eval


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="benchmarks/workspace_eval_v1.json")
    parser.add_argument("--output", default="evidence/workspace-eval-v1.json")
    parser.add_argument("--base-url", default="http://127.0.0.1:8787")
    args = parser.parse_args()
    report = run_workspace_eval(ROOT, ROOT / args.config, base_url=args.base_url)
    output = ROOT / args.output
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "output": str(output.relative_to(ROOT)),
        "rag_passed": report["rag"]["passed"],
        "generation_passed": report["generation"]["passed"],
        "agentic_workflows_passed": report["agentic_workflows"]["passed"],
        "human_review_state": report["chat_error_discovery"]["review_state"],
        "release_passed": report["release_decision"]["passed"],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
