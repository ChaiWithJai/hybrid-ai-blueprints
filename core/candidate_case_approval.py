"""Fail-closed approval boundary between source review and case registration."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from core.candidate_source_review import (
    _decision_signature,
    _is_case_authorable,
    compare_source_reviews,
    draft_sources,
    load_source_reviewer_roster,
    packet_sha256,
    validate_source_adjudication,
)
from core.first_pass_benchmark import calculation_contract_errors, schema_errors
from core.review_signatures import validate_buzz_attestation


CITATION_PATTERN = re.compile(r"^\[([^#\]]+)#([^\]]+)\]$")


def _snapshot_sha256(sources: list[dict[str, Any]]) -> str:
    encoded = json.dumps(
        {item["filename"]: item["sha256"] for item in sources},
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def _citation_parts(token: str) -> tuple[str, str] | None:
    match = CITATION_PATTERN.fullmatch(token)
    return match.groups() if match else None


def _authoritative_decision(
    packet: dict[str, Any],
    submissions: list[dict[str, Any]],
    comparison: dict[str, Any],
    adjudication: dict[str, Any] | None,
    draft_id: str,
) -> tuple[dict[str, Any] | None, list[str], list[str], str | None, str | None]:
    candidates: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for submission in submissions:
        for decision in submission.get("drafts", []):
            if decision.get("draft_id") == draft_id:
                candidates.append((submission, decision))
    if draft_id in comparison.get("eligible_draft_ids", []):
        authorable = [item for item in candidates if _is_case_authorable(item[1])]
        if len(authorable) < 2 or len({_decision_signature(item[1]) for item in authorable}) != 1:
            return None, [], [], None, None
        return (
            authorable[0][1],
            sorted(item[0]["review_id"] for item in authorable),
            sorted(item[0]["buzz_event_id"] for item in authorable),
            None,
            None,
        )
    if adjudication is None:
        return None, [], [], None, None
    selection = next(
        (item for item in adjudication.get("decisions", []) if item.get("draft_id") == draft_id),
        None,
    )
    if selection is None:
        return None, [], [], None, None
    selected = next(
        (item for item in candidates if item[0].get("review_id") == selection.get("selected_review_id")),
        None,
    )
    if selected is None or not _is_case_authorable(selected[1]):
        return None, [], [], None, None
    return (
        selected[1],
        sorted(item[0]["review_id"] for item in candidates),
        sorted(item[0]["buzz_event_id"] for item in candidates),
        str(adjudication.get("adjudication_id")),
        str(adjudication.get("buzz_event_id")),
    )


def build_candidate_case_authoring_material(
    root: Path,
    packet: dict[str, Any],
    submissions: list[dict[str, Any]],
    adjudication: dict[str, Any] | None,
    draft_id: str,
    *,
    reviewer_roster: dict[str, Any] | None = None,
    signed_events: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Return the exact reviewed fields that an unsigned case must preserve."""
    roster = reviewer_roster or load_source_reviewer_roster(root)
    comparison = compare_source_reviews(root, packet, submissions, roster, signed_events)
    errors = list(comparison["errors"])
    if adjudication is not None:
        errors.extend(
            validate_source_adjudication(
                root, packet, comparison, adjudication, roster, signed_events,
            )
        )
    draft = next(
        (item for item in packet.get("drafts", []) if item.get("draft_id") == draft_id),
        None,
    )
    if draft is None:
        raise ValueError("candidate draft is absent from the source review packet")
    decision, review_ids, review_event_ids, adjudication_id, adjudication_event_id = (
        _authoritative_decision(packet, submissions, comparison, adjudication, draft_id)
    )
    if errors:
        raise ValueError("source review state is invalid: " + "; ".join(errors))
    if decision is None:
        raise ValueError("candidate draft has no affirmative independently reviewed decision")

    options = {item["citation"]: item for item in draft.get("evidence_options", [])}
    required_citations = []
    citation_ids: dict[str, str] = {}
    for index, token in enumerate(decision.get("supporting_citations", []), 1):
        parts = _citation_parts(token)
        option = options.get(token)
        if parts is None or option is None:
            raise ValueError("reviewed supporting citation is absent from packet evidence")
        citation_id = f"citation_{index}"
        citation_ids[token] = citation_id
        required_citations.append({
            "id": citation_id,
            "filename": parts[0],
            "anchor": parts[1],
            "source_sha256": option["source_sha256"],
            "evidence_excerpt_sha256": hashlib.sha256(option["excerpt"].encode()).hexdigest(),
        })
    required_claims = []
    for index, claim in enumerate(decision.get("expected_claims", []), 1):
        claim_citations = [
            citation_ids[token] for token in claim.get("citations", [])
            if token in citation_ids
        ]
        if len(claim_citations) != len(claim.get("citations", [])):
            raise ValueError("reviewed claim cites evidence outside the supporting set")
        required_claims.append({
            "id": f"claim_{index}",
            "text": claim["text"],
            "citation_ids": claim_citations,
        })
    return {
        "draft_id": draft_id,
        "candidate_id": draft["candidate_id"],
        "company": draft["company"],
        "source_review_packet_sha256": packet_sha256(packet),
        "source_review_ids": review_ids,
        "source_review_event_ids": review_event_ids,
        "source_adjudication_id": adjudication_id,
        "source_adjudication_event_id": adjudication_event_id,
        "question": decision["final_question"],
        "answer_policy": {
            "supported": "answer",
            "refuse_absent": "refuse_absent",
        }[decision["answer_policy"]],
        "reviewed_absence_basis": decision.get("absence_basis", ""),
        "task_family": draft["task_family"],
        "required_claims": required_claims,
        "required_citations": required_citations,
        "confusable_citations": sorted(decision.get("confusable_citations", [])),
        "source_snapshot_sha256": _snapshot_sha256(draft_sources(draft)),
        "source_count": len(draft_sources(draft)),
        "source_filenames": [item["filename"] for item in draft_sources(draft)],
        "allowed_splits": ["development", "calibration"],
        "sealed_test_repository_storage_allowed": False,
    }


def validate_candidate_case_approval(
    root: Path,
    packet: dict[str, Any],
    submissions: list[dict[str, Any]],
    adjudication: dict[str, Any] | None,
    approval: dict[str, Any],
    *,
    reviewer_roster: dict[str, Any] | None = None,
    signed_events: dict[str, dict[str, Any]] | None = None,
) -> list[str]:
    """Validate an approved case artifact without registering or mutating it."""
    contract = root / "benchmarks" / "first_pass"
    approval_schema = json.loads(
        (contract / "candidate_case_approval.schema.json").read_text(encoding="utf-8")
    )
    case_schema = json.loads((contract / "case.schema.json").read_text(encoding="utf-8"))
    errors = schema_errors(approval, approval_schema)
    case = approval.get("case", {})
    errors.extend(schema_errors(case, case_schema, case_schema, "$.case"))
    if isinstance(case, dict):
        errors.extend(
            f"$.case: {item}" for item in calculation_contract_errors(case)
        )

    roster = reviewer_roster or load_source_reviewer_roster(root)
    owners = {
        item["reviewer_id"]: item
        for item in roster.get("reviewers", [])
        if item.get("active") is True and item.get("role") == "domain_case_owner"
    }
    owner = owners.get(approval.get("domain_owner_id"))
    if owner is None:
        errors.append("$.domain_owner_id: owner is not active in the domain-case-owner role")
    else:
        if approval.get("qualification") != owner.get("qualification"):
            errors.append("$.qualification: qualification differs from the approved owner roster")
        errors.extend(validate_buzz_attestation(
            kind="candidate_case_approval",
            record=approval,
            expected_pubkey=owner.get("buzz_pubkey"),
            signed_events=signed_events,
            location="$",
        ))

    if approval.get("source_review_packet_sha256") != packet_sha256(packet):
        errors.append("$.source_review_packet_sha256: approval is not bound to the packet")
    comparison = compare_source_reviews(
        root, packet, submissions, roster, signed_events,
    )
    errors.extend(f"source review: {item}" for item in comparison["errors"])
    if adjudication is not None:
        errors.extend(
            f"source adjudication: {item}"
            for item in validate_source_adjudication(
                root, packet, comparison, adjudication, roster, signed_events,
            )
        )
    draft_id = approval.get("draft_id")
    draft = next((item for item in packet.get("drafts", []) if item.get("draft_id") == draft_id), None)
    if draft is None:
        errors.append("$.draft_id: draft is absent from the source-review packet")
        return errors
    decision, review_ids, review_event_ids, adjudication_id, adjudication_event_id = (
        _authoritative_decision(packet, submissions, comparison, adjudication, str(draft_id))
    )
    if decision is None:
        errors.append("$.draft_id: no affirmative independently reviewed decision authorizes a case")
        return errors
    if sorted(approval.get("source_review_ids", [])) != review_ids:
        errors.append("$.source_review_ids: IDs differ from the authoritative review set")
    if sorted(approval.get("source_review_event_ids", [])) != review_event_ids:
        errors.append("$.source_review_event_ids: event IDs differ from the authoritative review set")
    if approval.get("source_adjudication_id") != adjudication_id:
        errors.append("$.source_adjudication_id: value differs from the authoritative resolution")
    if approval.get("source_adjudication_event_id") != adjudication_event_id:
        errors.append("$.source_adjudication_event_id: value differs from the authoritative resolution")

    expected_policy = {"supported": "answer", "refuse_absent": "refuse_absent"}[
        decision["answer_policy"]
    ]
    expected_pairs = {
        token: _citation_parts(token) for token in decision.get("supporting_citations", [])
    }
    if any(parts is None for parts in expected_pairs.values()):
        errors.append("source review: supporting citation has an invalid token")
        return errors
    case_citations = case.get("required_citations", [])
    case_tokens = {
        f"[{item.get('filename')}#{item.get('anchor')}]": item for item in case_citations
    }
    if set(case_tokens) != set(expected_pairs):
        errors.append("$.case.required_citations: citations differ from the reviewed support set")
    options = {item["citation"]: item for item in draft.get("evidence_options", [])}
    for token, citation in case_tokens.items():
        option = options.get(token)
        if option is None:
            errors.append(f"$.case.required_citations: {token} is absent from packet evidence")
            continue
        excerpt_hash = hashlib.sha256(option["excerpt"].encode()).hexdigest()
        if citation.get("source_sha256") != option.get("source_sha256"):
            errors.append(f"$.case.required_citations: {token} source hash differs")
        if citation.get("evidence_excerpt_sha256") != excerpt_hash:
            errors.append(f"$.case.required_citations: {token} excerpt hash differs")
    citation_token_by_id = {
        item.get("id"): f"[{item.get('filename')}#{item.get('anchor')}]"
        for item in case_citations
    }
    observed_claims = sorted(
        (
            " ".join(str(item.get("text", "")).split()),
            sorted(citation_token_by_id.get(value, "") for value in item.get("citation_ids", [])),
        )
        for item in case.get("required_claims", [])
    )
    expected_claims = sorted(
        (
            " ".join(str(item.get("text", "")).split()),
            sorted(item.get("citations", [])),
        )
        for item in decision.get("expected_claims", [])
    )
    if observed_claims != expected_claims:
        errors.append("$.case.required_claims: claims differ from the reviewed expected claims")
    if sorted(approval.get("confusable_citations", [])) != sorted(
        decision.get("confusable_citations", [])
    ):
        errors.append("$.confusable_citations: passages differ from the reviewed confusable set")

    expected_snapshot = _snapshot_sha256(draft_sources(draft))
    expected_case_values = {
        "deal_id": draft["candidate_id"],
        "task_family": draft["task_family"],
        "question": decision["final_question"],
        "answer_policy": expected_policy,
        "source_snapshot_sha256": expected_snapshot,
    }
    for field, expected in expected_case_values.items():
        if case.get(field) != expected:
            errors.append(f"$.case.{field}: value differs from the reviewed source decision")
    review = case.get("domain_review", {})
    if review != {
        "status": "approved",
        "owner": approval.get("domain_owner_id"),
        "reviewed_at": approval.get("approved_at"),
    }:
        errors.append("$.case.domain_review: approval metadata differs from the signed owner record")

    registry = json.loads((contract / "development_registry.v2.json").read_text(encoding="utf-8"))
    if any(item.get("id") == case.get("id") for item in registry.get("cases", [])):
        errors.append("$.case.id: case ID already exists in the benchmark registry")
    existing_splits = {
        item.get("split") for item in registry.get("cases", [])
        if item.get("deal_id") == case.get("deal_id")
    }
    if existing_splits and case.get("split") not in existing_splits:
        errors.append("$.case.split: deal is already assigned to a different split")
    return errors


def candidate_case_approval_report(
    root: Path,
    packet: dict[str, Any],
    submissions: list[dict[str, Any]],
    adjudication: dict[str, Any] | None,
    approval: dict[str, Any],
    *,
    reviewer_roster: dict[str, Any] | None = None,
    signed_events: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    errors = validate_candidate_case_approval(
        root,
        packet,
        submissions,
        adjudication,
        approval,
        reviewer_roster=reviewer_roster,
        signed_events=signed_events,
    )
    return {
        "verification_kind": "candidate_case_approval",
        "approval_id": approval.get("approval_id"),
        "draft_id": approval.get("draft_id"),
        "case_id": approval.get("case", {}).get("id"),
        "approval_valid": not errors,
        "benchmark_case_registered": False,
        "errors": errors,
        "limitations": [
            "A valid approval authorizes a separate atomic registration step; it does not mutate the registry.",
            "Model output and retrieval rank are not inputs to case approval.",
        ],
    }
