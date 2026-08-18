#!/usr/bin/env python3
"""Preflight or perform the one-time read of an external sealed bundle."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.sealed_test_control import open_sealed_test, sealed_test_preflight  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--control", type=Path)
    parser.add_argument("--secret-bundle", type=Path)
    parser.add_argument("--confirm-one-time-contact", action="store_true")
    args = parser.parse_args()
    control = args.control.resolve() if args.control else None

    if args.secret_bundle is None:
        report = sealed_test_preflight(ROOT, control)
    else:
        if not args.confirm_one_time_contact:
            parser.error("--secret-bundle requires --confirm-one-time-contact")
        secret_path = args.secret_bundle.resolve()
        report = open_sealed_test(ROOT, secret_path.read_bytes, control)
        report.pop("secret_bundle", None)

    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report.get("ready_to_open") or report.get("secret_bundle_valid") else 1


if __name__ == "__main__":
    raise SystemExit(main())
