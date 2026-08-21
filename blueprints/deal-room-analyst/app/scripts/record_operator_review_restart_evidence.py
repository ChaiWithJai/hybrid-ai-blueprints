#!/usr/bin/env python3
"""Record a local operator review restored after a Prism process restart."""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path
from urllib.request import urlopen


def fetch_json(url: str) -> dict:
    with urlopen(url, timeout=15) as response:
        if response.status != 200:
            raise RuntimeError(f"{url} returned HTTP {response.status}")
        return json.loads(response.read())


def expected_review_message(draft: dict, review: dict) -> str:
    evidence_packet = draft.get("artifact_mode") == "evidence_safe_fallback"
    heading = "Source evidence packet reviewed" if evidence_packet else "First pass draft reviewed"
    subject = "deterministic source evidence packet" if evidence_packet else "Bonsai first pass draft"
    return (
        f"## {heading}\n\n"
        f"Review subject: {subject}\n\n"
        f"Artifact mode: {draft.get('artifact_mode', 'model_draft')}\n\n"
        f"Decision: {str(review['decision']).upper()}\n\n"
        f"Useful starting point: {'Yes' if review['useful_starting_point'] else 'No'}\n\n"
        f"Critical corrections: {review['critical_corrections']}\n\n"
        f"Major corrections: {review['major_corrections']}\n\n"
        f"Notes: {review['notes'] or 'None recorded.'}"
    )


def build_record(
    status: dict,
    first_pass: dict,
    messages_payload: dict,
    digest: dict,
    evals: dict,
    source_folder: Path,
    *,
    recorded_at: float | None = None,
) -> dict:
    if not source_folder.is_dir():
        raise RuntimeError(f"Source folder is unavailable: {source_folder}")
    draft = first_pass.get("draft")
    if not isinstance(draft, dict) or not isinstance(draft.get("review"), dict):
        raise RuntimeError("The room has no restored local operator review")
    review = draft["review"]
    verification = review.get("signature_verification", {})
    if (
        review.get("restored_from_buzz") is not True
        or verification.get("state") != "verified"
        or verification.get("review_event_id") != review.get("review_event_id")
        or verification.get("canvas_event_id") != review.get("canvas_event_id")
    ):
        raise RuntimeError("The local operator review lacks signed restoration proof")
    operator_pubkey = status.get("buzz", {}).get("operator_pubkey")
    if review.get("reviewer_pubkey") != operator_pubkey:
        raise RuntimeError("The review signer is not the configured local operator")
    if review.get("benchmark_domain_review") is not False:
        raise RuntimeError("A local operator review must not claim benchmark domain review")

    review_event = next(
        (
            event for event in messages_payload.get("messages", [])
            if event.get("id") == review.get("review_event_id")
        ),
        None,
    )
    if not isinstance(review_event, dict):
        raise RuntimeError("The signed review message is absent from the Buzz room")
    if (
        review_event.get("signature_verified") is not True
        or review_event.get("pubkey") != operator_pubkey
        or review_event.get("content") != expected_review_message(draft, review)
    ):
        raise RuntimeError("The Buzz review message does not match the restored review")
    process_started_at = status.get("server_process_started_at")
    if not isinstance(process_started_at, (int, float)) or not isinstance(
        review_event.get("created_at"), int
    ) or review_event["created_at"] >= process_started_at:
        raise RuntimeError("The review event does not predate the current Prism process")

    if (
        digest.get("event_id") != review.get("canvas_event_id")
        or digest.get("signature_verification", {}).get("state") != "verified"
        or digest.get("signature_verification", {}).get("author_pubkey") != operator_pubkey
    ):
        raise RuntimeError("The current Buzz canvas is not the signed reviewed canvas")
    trace = next(
        (
            item for item in evals.get("traces", [])
            if item.get("trace_id") == draft.get("trace_id")
        ),
        None,
    )
    durable_review = {
        key: value for key, value in review.items()
        if key not in {"restored_from_buzz", "signature_verification"}
    }
    if not isinstance(trace, dict) or trace.get("metadata", {}).get(
        "human_review"
    ) != durable_review:
        raise RuntimeError("The persisted trace review does not match the restored review")

    return {
        "verification_kind": "signed_operator_review_restart_record",
        "recorded_at": recorded_at if recorded_at is not None else time.time(),
        "room": first_pass.get("room"),
        "canonical_path": first_pass.get("canonical_path"),
        "trace_id": draft.get("trace_id"),
        "draft_event_id": draft.get("draft_event_id"),
        "artifact_mode": draft.get("artifact_mode", "model_draft"),
        "review_subject": (
            "source_evidence_packet"
            if draft.get("artifact_mode") == "evidence_safe_fallback"
            else "bonsai_first_pass_draft"
        ),
        "review": review,
        "review_event_created_at": review_event.get("created_at"),
        "server_process_started_at": process_started_at,
        "review_predates_server_process": True,
        "digest_event_id": digest.get("event_id"),
        "source_folder": (
            str(source_folder.relative_to(Path.cwd()))
            if source_folder.is_relative_to(Path.cwd()) else str(source_folder)
        ),
        "source_files": [
            {
                "filename": path.name,
                "bytes": path.stat().st_size,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
            for path in sorted(source_folder.iterdir()) if path.is_file()
        ],
        "accuracy_release_passed": False,
        "limitations": [
            "The action is a local operator durability smoke review, not domain review.",
            "The review does not assess the accuracy or usefulness of the fallback.",
            "The source is a public SEC filing, not a private virtual data room.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8787")
    parser.add_argument("--room", required=True)
    parser.add_argument("--source-folder", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    base = args.base_url.rstrip("/")
    room_query = f"room={args.room}"
    record = build_record(
        fetch_json(f"{base}/api/status"),
        fetch_json(f"{base}/api/workspace/first-pass?{room_query}"),
        fetch_json(f"{base}/api/workspace/messages?{room_query}"),
        fetch_json(f"{base}/api/workspace/digest?{room_query}"),
        fetch_json(f"{base}/api/evals"),
        Path(args.source_folder).resolve(),
    )
    output = Path(args.output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
