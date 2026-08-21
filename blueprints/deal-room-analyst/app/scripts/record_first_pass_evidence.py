#!/usr/bin/env python3
"""Record a trace-linked first-pass product run without upgrading its accuracy state."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
from pathlib import Path
from urllib.request import urlopen


ROOT = Path(__file__).resolve().parents[1]


def fetch_json(url: str) -> dict:
    with urlopen(url, timeout=10) as response:
        if response.status != 200:
            raise RuntimeError(f"{url} returned HTTP {response.status}")
        return json.loads(response.read())


def file_hashes(folder: Path) -> list[dict[str, object]]:
    records = []
    for path in sorted(item for item in folder.iterdir() if item.is_file()):
        data = path.read_bytes()
        records.append({
            "filename": path.name,
            "bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
        })
    return records


def build_record(
    status: dict,
    first_pass: dict,
    evals: dict,
    source_folder: Path,
    recorded_at: float | None = None,
    require_screen_bound: bool = False,
) -> dict:
    draft = first_pass.get("draft")
    if not isinstance(draft, dict):
        raise RuntimeError("No first-pass draft is available")
    if draft.get("acceptance_state") not in {"accepted", "evidence_safe_fallback"}:
        raise RuntimeError("The latest first-pass artifact is not reviewable")
    trace_id = draft.get("trace_id")
    if not trace_id:
        raise RuntimeError("The Buzz-restored first-pass artifact has no trace identity")
    trace = next(
        (item for item in evals.get("traces", []) if item.get("trace_id") == trace_id),
        None,
    )
    if trace is None:
        raise RuntimeError(f"Trace {trace_id} is absent from /api/evals")
    event_id = draft.get("draft_event_id")
    restoration = draft.get("restoration_verification", {})
    if (
        restoration.get("state") != "verified"
        or restoration.get("event_id") != event_id
        or restoration.get("trace_id") != trace_id
    ):
        raise RuntimeError("The first-pass draft lacks exact Buzz-to-trace restoration proof")
    if trace.get("metadata", {}).get("draft_event_id") != event_id:
        raise RuntimeError("The trace is not bound to the restored Buzz draft event")
    if trace.get("session_id") != first_pass.get("room"):
        raise RuntimeError("The trace session is not bound to the deal room")
    markdown = str(draft.get("markdown", ""))
    if trace.get("response_sha256") != hashlib.sha256(markdown.encode("utf-8")).hexdigest():
        raise RuntimeError("The trace response does not match the restored Buzz draft")
    if trace.get("metadata", {}).get("guard_version") != draft.get("guard_version"):
        raise RuntimeError("The trace and draft guard versions do not match")
    if not status.get("buzz", {}).get("relay_live"):
        raise RuntimeError("Buzz relay is not live")
    if draft.get("artifact_mode") == "model_draft":
        if trace.get("metadata", {}).get("provider_id") != "local_bonsai":
            raise RuntimeError("The model draft trace does not identify the local Bonsai provider")
        if not trace.get("model_name") or trace.get("model_name") != draft.get("model"):
            raise RuntimeError("The model draft and trace model identities do not match")
    citations = draft.get("citations")
    if not isinstance(citations, list) or not citations:
        raise RuntimeError("The first-pass artifact has no admitted citations")
    if not source_folder.is_dir():
        raise RuntimeError(f"Source folder is unavailable: {source_folder}")
    trace_metadata = trace.get("metadata", {})
    model_failure_trace_id = trace_metadata.get("model_failure_trace_id")
    model_failure_trace = next(
        (
            item for item in evals.get("traces", [])
            if item.get("trace_id") == model_failure_trace_id
        ),
        None,
    ) if model_failure_trace_id else None
    if require_screen_bound:
        if trace_metadata.get("investment_screen_retrieval") != "screen_bound_v1":
            raise RuntimeError("The first-pass trace is not screen-bound retrieval evidence")
        if not isinstance(trace_metadata.get("investment_screen_passage_count"), int) or (
            trace_metadata["investment_screen_passage_count"] < 1
        ):
            raise RuntimeError("The first-pass trace has no screen-matched passage")
        if not isinstance(trace_metadata.get("source_snapshot_sha256"), str) or len(
            trace_metadata["source_snapshot_sha256"]
        ) != 64:
            raise RuntimeError("The first-pass trace has no source snapshot identity")
        if not re.fullmatch(
            r"[a-z0-9_]+", str(trace_metadata.get("source_classification", ""))
        ):
            raise RuntimeError("The first-pass trace has no source classification")
        if not re.fullmatch(
            r"[0-9a-f]{64}", str(trace_metadata.get("source_provenance_sha256", ""))
        ):
            raise RuntimeError("The first-pass trace has no provenance binding")
        if (
            draft.get("source_classification") != trace_metadata["source_classification"]
            or draft.get("source_provenance_sha256")
            != trace_metadata["source_provenance_sha256"]
            or draft.get("source_snapshot_sha256")
            != trace_metadata["source_snapshot_sha256"]
        ):
            raise RuntimeError("The restored first-pass provenance differs from its trace")
        if draft.get("artifact_mode") == "evidence_safe_fallback" and model_failure_trace is None:
            raise RuntimeError("The fallback has no saved rejected-model trace")

    human_review_evaluations = [
        evaluation
        for evaluation in trace.get("evaluations", [])
        if evaluation.get("name") == "human_accuracy_review"
    ]
    if len(human_review_evaluations) != 1:
        raise RuntimeError(
            "The trace must contain exactly one named human accuracy review evaluation"
        )
    human_review = human_review_evaluations[0]
    if not (
        human_review.get("passed") is False
        and human_review.get("metadata", {}).get("measurement_state")
        == "awaiting_human_review"
    ):
        raise RuntimeError(
            "The first-pass recorder requires an explicit pending human accuracy review"
        )
    return {
        "verification_kind": "trace_linked_first_pass_product_record",
        "recorded_at": recorded_at if recorded_at is not None else time.time(),
        "room": first_pass.get("room"),
        "canonical_path": first_pass.get("canonical_path"),
        "product_path_verified": True,
        "accuracy_release_passed": False,
        "human_review_state": "pending",
        "limitations": [
            "This record proves a trace-linked Buzz product artifact, not domain accuracy.",
            "Interactive browser behavior is not replayed by this recorder.",
            "The source set is synthetic and its expected conclusions lack domain-owner approval.",
        ],
        "runtime": {
            "configured_model": status.get("configured_local_model_name"),
            "last_invoked_model": status.get("last_invoked_local_model"),
            "invocation_evidence": "artifact_trace_id_bound_local_provider_record",
            "buzz_relay": status.get("buzz", {}).get("relay_url"),
            "buzz_relay_live": True,
        },
        "artifact": {
            "acceptance_state": draft.get("acceptance_state"),
            "artifact_mode": draft.get("artifact_mode"),
            "authored_by": draft.get("authored_by"),
            "guard_version": draft.get("guard_version"),
            "model": draft.get("model"),
            "recommendation": draft.get("recommendation"),
            "trace_id": trace_id,
            "draft_event_id": draft.get("draft_event_id"),
            "restored_from_buzz": bool(draft.get("restored_from_buzz")),
            "restoration_verification": restoration,
            "citations": citations,
            "markdown": draft.get("markdown"),
            "source_snapshot_sha256": trace_metadata.get("source_snapshot_sha256"),
            "source_classification": trace_metadata.get("source_classification"),
            "source_provenance_sha256": trace_metadata.get(
                "source_provenance_sha256"
            ),
            "source_provenance": trace_metadata.get("source_provenance"),
            "investment_screen_retrieval": trace_metadata.get("investment_screen_retrieval"),
            "investment_screen_passage_count": trace_metadata.get(
                "investment_screen_passage_count"
            ),
        },
        "investment_screen": draft.get("investment_screen"),
        "source_snapshot_scope": "absolute_local_path",
        "source_folder_resolved": str(source_folder.resolve()),
        "trace": trace,
        "model_failure_trace": model_failure_trace,
        "source_files": file_hashes(source_folder),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8787")
    parser.add_argument("--room", default="project_titan_lbo")
    parser.add_argument("--source-folder", default="deal_rooms/project_titan_lbo")
    parser.add_argument("--output", required=True)
    parser.add_argument("--require-screen-bound", action="store_true")
    args = parser.parse_args()

    base = args.base_url.rstrip("/")
    status = fetch_json(f"{base}/api/status")
    first_pass = fetch_json(f"{base}/api/workspace/first-pass?room={args.room}")
    evals = fetch_json(f"{base}/api/evals")
    record = build_record(
        status,
        first_pass,
        evals,
        (ROOT / args.source_folder).resolve(),
        require_screen_bound=args.require_screen_bound,
    )
    output = Path(args.output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
