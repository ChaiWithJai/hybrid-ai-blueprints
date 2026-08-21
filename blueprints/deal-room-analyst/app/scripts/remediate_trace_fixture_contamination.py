#!/usr/bin/env python3
"""Retain and label traces created by the pre-isolation HTTP verification bug."""

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from core.arize_evals import ArizeObservabilityTracer, ArizeTraceRecord


SENSITIVITY_QUERY = "Run sensitivity stress-test modeling a 10% and 20% drop in EBITDA."
AUDIT_QUERY = "Execute M&A Deal Room Covenant & Regulatory Audit"


def is_known_fixture_contamination(trace: ArizeTraceRecord) -> bool:
    metadata = trace.metadata
    if metadata.get("exclude_from_aggregate_metrics") is True:
        return False
    if (
        trace.session_id == "agent_session"
        and trace.query == SENSITIVITY_QUERY
        and metadata.get("execution_mode") == "deterministic_template"
        and metadata.get("provider_id") is None
        and metadata.get("generation_attempts") == 0
    ):
        return True
    return (
        trace.session_id == "default_session"
        and trace.query == AUDIT_QUERY
        and metadata.get("execution_mode") == "reviewed_deterministic_profile"
        and metadata.get("profile_id") == "horizon_covenant_v1"
    )


def remediate(path: Path, *, expected_count: int, apply: bool) -> dict:
    original_bytes = path.read_bytes()
    tracer = ArizeObservabilityTracer(str(path))
    before = tracer.storage_status()
    candidates = [
        trace for trace in tracer.snapshot() if is_known_fixture_contamination(trace)
    ]
    if len(candidates) != expected_count:
        raise ValueError(
            f"expected {expected_count} unlabelled fixture traces, found {len(candidates)}"
        )
    if apply:
        for trace in candidates:
            trace.metadata["exclude_from_aggregate_metrics"] = True
            trace.metadata["trace_provenance"] = {
                "state": "verification_fixture_contamination",
                "reason": (
                    "Created by the local HTTP verification suite before the failed-bind "
                    "trace-store side-effect guard was added. Retained in the hash chain "
                    "and excluded from product metrics."
                ),
                "remediation": "metadata correction event; original ledger event retained",
                "prevention_guard": (
                    "test_operator_preflight.OperatorPreflightTests."
                    "test_failed_bind_does_not_open_or_migrate_trace_store"
                ),
            }
        tracer.persist()
    after_bytes = path.read_bytes()
    after = tracer.storage_status()
    return {
        "schema_version": 1,
        "measurement_state": (
            "fixture_contamination_labelled" if apply else "dry_run"
        ),
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "trace_store": str(path),
        "candidate_count": len(candidates),
        "trace_ids": sorted(trace.trace_id for trace in candidates),
        "records_deleted": 0,
        "before": {
            "bytes_sha256": hashlib.sha256(original_bytes).hexdigest(),
            "entry_count": before["entry_count"],
            "head_sha256": before["head_sha256"],
        },
        "after": {
            "bytes_sha256": hashlib.sha256(after_bytes).hexdigest(),
            "entry_count": after["entry_count"],
            "head_sha256": after["head_sha256"],
        },
        "limitations": [
            "The correction identifies one exact pair of repository-owned verification requests.",
            "The original events remain in the local chain; the correction does not erase history.",
            "The ledger is not signed or externally anchored and can be rewritten by a local administrator.",
        ],
    }


def write_record(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(record, handle, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--trace-store", type=Path, default=Path(".runtime/evals/traces.jsonl")
    )
    parser.add_argument("--expected-count", type=int, required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    record = remediate(
        args.trace_store.resolve(), expected_count=args.expected_count, apply=args.apply,
    )
    if args.output:
        write_record(args.output.resolve(), record)
    print(json.dumps(record, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
