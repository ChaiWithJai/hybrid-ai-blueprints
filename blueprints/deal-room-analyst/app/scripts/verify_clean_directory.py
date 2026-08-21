#!/usr/bin/env python3
"""Reproduce the deterministic product check from a fresh temporary directory."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
COPY_FILES = (
    "README.md",
    "package-lock.json",
    "package.json",
    "prismctl",
    "server.py",
)
COPY_DIRECTORIES = (
    "benchmarks", "core", "deal_rooms", "docs", "evidence", "infra", "scripts", "tests", "tools", "web"
)
GENERATED_RECORDS = {"evidence/clean-directory-baseline.json"}
RUNTIME_PUBLIC_SOURCES = (
    ".runtime/public-deal-corpus/citrix/01_citrix_defm14a.htm",
    ".runtime/public-deal-corpus/citrix/02_citrix_financing_supplement.htm",
    ".runtime/candidate-deal-sources/zendesk_2022/01_defm14a.htm",
    ".runtime/candidate-deal-sources/zendesk_2022/02_financial_10q.htm",
)


def copied_sources() -> list[Path]:
    paths = [PROJECT_ROOT / name for name in (*COPY_FILES, *RUNTIME_PUBLIC_SOURCES)]
    for directory in COPY_DIRECTORIES:
        paths.extend(
            path for path in (PROJECT_ROOT / directory).rglob("*")
            if path.is_file()
            and "__pycache__" not in path.parts
            and path.suffix != ".pyc"
            and path.relative_to(PROJECT_ROOT).as_posix() not in GENERATED_RECORDS
        )
    return sorted(set(paths))


def manifest_digest(paths: list[Path]) -> str:
    digest = hashlib.sha256()
    for path in paths:
        relative = path.relative_to(PROJECT_ROOT).as_posix().encode()
        digest.update(len(relative).to_bytes(4, "big"))
        digest.update(relative)
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output", default="evidence/clean-directory-baseline.json",
        help="Path for the reproduction record",
    )
    args = parser.parse_args()
    output_path = Path(args.output).resolve()
    sources = copied_sources()
    source_manifest_sha256 = manifest_digest(sources)

    with tempfile.TemporaryDirectory(prefix="prism-clean-copy-") as temp_name:
        clean_root = Path(temp_name) / "project"
        clean_root.mkdir()
        for name in COPY_FILES:
            shutil.copy2(PROJECT_ROOT / name, clean_root / name)
        for name in COPY_DIRECTORIES:
            shutil.copytree(
                PROJECT_ROOT / name,
                clean_root / name,
                ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".DS_Store"),
            )
        for name in RUNTIME_PUBLIC_SOURCES:
            destination = clean_root / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(PROJECT_ROOT / name, destination)

        clean_report = clean_root / "clean-baseline-report.json"
        environment = os.environ.copy()
        for key in list(environment):
            if key.startswith("PRISM_LOCAL_AI_") or key.startswith("PRISM_CLOUD_AI_"):
                environment.pop(key)
        environment["PRISM_VERIFY_RELOCATED_EVIDENCE"] = "1"
        completed = subprocess.run(
            [sys.executable, "scripts/verify_product.py", "--runtime", "baseline",
             "--output", str(clean_report)],
            cwd=clean_root,
            env=environment,
            capture_output=True,
            text=True,
            timeout=120,
        )
        verifier_report = (
            json.loads(clean_report.read_text(encoding="utf-8"))
            if clean_report.is_file() else {}
        )
        record = {
            "schema_version": 1,
            "measurement_state": "clean_directory_reproduced",
            "recorded_at": datetime.now(timezone.utc).isoformat(),
            "source_manifest_sha256": source_manifest_sha256,
            "copied_file_count": len(sources),
            "provider_environment_removed": True,
            "temporary_root_distinct_from_source": clean_root.resolve() != PROJECT_ROOT.resolve(),
            "temporary_copy_removed_after_run": True,
            "command": "python scripts/verify_product.py --runtime baseline --output clean-baseline-report.json",
            "exit_code": completed.returncode,
            "component_tests": verifier_report.get("component_tests"),
            "unsupported_claim_scan": verifier_report.get("unsupported_claim_scan"),
            "frontend_contract": verifier_report.get("frontend_contract"),
            "benchmark": {
                key: verifier_report.get("benchmark", {}).get(key)
                for key in ("dataset_sha256", "total_cases", "passed_cases", "pass_rate")
            },
            "selected_runtime_verified": verifier_report.get("selected_runtime_verified", False),
            "stderr_tail": completed.stderr[-4000:],
            "limitations": [
                "This proves relocation to a clean directory on the same machine, not a clean physical machine.",
                "The copied evidence records are inputs to reality guards; this run does not recreate live Bonsai evidence.",
                "Python and Node availability come from the host environment and are not provisioned by this script."
            ],
        }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(record, indent=2))
    return 0 if completed.returncode == 0 and record["selected_runtime_verified"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
