"""Preflight and finalize reviewer-owned Buzz attestations."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from core.candidate_source_review import load_source_reviewer_roster
from core.first_pass_benchmark import schema_errors
from core.first_pass_review import load_output_reviewer_roster
from core.review_signatures import review_attestation_content, validate_buzz_attestation


ZERO_EVENT_ID = "0" * 64
KIND_CONTRACTS = {
    "candidate_source_review": (
        "candidate_source_review_submission.schema.json",
        "reviewer_id",
        "qualified_deal_source_reviewer",
        "source",
    ),
    "candidate_source_adjudication": (
        "candidate_source_adjudication.schema.json",
        "principal_reviewer_id",
        "principal_source_reviewer",
        "source",
    ),
    "blinded_output_review": (
        "human_review_submission.schema.json",
        "reviewer_id",
        "qualified_deal_output_reviewer",
        "output",
    ),
    "blinded_output_adjudication": (
        "principal_adjudication.schema.json",
        "principal_reviewer_id",
        "principal_output_reviewer",
        "output",
    ),
    "candidate_case_approval": (
        "candidate_case_approval.schema.json",
        "domain_owner_id",
        "domain_case_owner",
        "source",
    ),
}


def prepare_review_publication(
    root: Path,
    record: dict[str, Any],
    kind: str,
    *,
    roster: dict[str, Any] | None = None,
) -> dict[str, str]:
    if kind not in KIND_CONTRACTS:
        raise ValueError(f"unsupported review attestation kind: {kind}")
    schema_name, actor_field, required_role, roster_kind = KIND_CONTRACTS[kind]
    schema = json.loads(
        (root / "benchmarks" / "first_pass" / schema_name).read_text(encoding="utf-8")
    )
    errors = schema_errors(record, schema)
    if kind == "candidate_case_approval" and isinstance(record.get("case"), dict):
        case_schema = json.loads(
            (root / "benchmarks" / "first_pass" / "case.schema.json").read_text(encoding="utf-8")
        )
        errors.extend(schema_errors(record["case"], case_schema, case_schema, "$.case"))
    if errors:
        raise ValueError("review record is not schema valid: " + "; ".join(errors))
    if record.get("buzz_event_id") != ZERO_EVENT_ID:
        raise ValueError("buzz_event_id must be the 64-zero unsigned placeholder")
    approved_roster = roster or (
        load_source_reviewer_roster(root)
        if roster_kind == "source" else load_output_reviewer_roster(root)
    )
    actor_id = record.get(actor_field)
    approved = next(
        (
            item for item in approved_roster.get("reviewers", [])
            if item.get("reviewer_id") == actor_id
            and item.get("role") == required_role
            and item.get("active") is True
        ),
        None,
    )
    if approved is None:
        raise ValueError("review actor is not active in the required domain-owner roster role")
    if record.get("reviewer_pubkey") != approved.get("buzz_pubkey"):
        raise ValueError("reviewer_pubkey differs from the approved roster")
    if record.get("qualification") != approved.get("qualification"):
        raise ValueError("qualification differs from the approved roster")
    return {
        "actor_id": str(actor_id),
        "expected_pubkey": str(approved["buzz_pubkey"]),
        "content": review_attestation_content(kind, record),
    }


def finalize_review_publication(
    record: dict[str, Any],
    kind: str,
    event: dict[str, Any],
    expected_pubkey: str,
) -> dict[str, Any]:
    event_id = event.get("id") or event.get("event_id")
    if not isinstance(event_id, str) or len(event_id) != 64:
        raise ValueError("Buzz did not return a 64-character event ID")
    finalized = json.loads(json.dumps(record))
    finalized["buzz_event_id"] = event_id
    normalized_event = {**event, "id": event_id}
    errors = validate_buzz_attestation(
        kind=kind,
        record=finalized,
        expected_pubkey=expected_pubkey,
        signed_events={event_id: normalized_event},
        location="$",
    )
    if errors:
        raise ValueError("published Buzz attestation failed verification: " + "; ".join(errors))
    return finalized
