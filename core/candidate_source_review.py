"""Model-blind source review and promotion eligibility for candidate cases.

This module never registers a benchmark case. It verifies whether independent
source reviewers have produced enough hash-bound evidence for a later,
separate promotion step.
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from core.first_pass_benchmark import schema_errors, sha256
from core.reviewer_roster_authority import (
    paired_reviewer_roster_authority_errors,
    reviewer_roster_authority_errors,
)
from core.review_signatures import validate_buzz_attestation


FORBIDDEN_PACKET_KEYS = {
    "provider",
    "model",
    "served_id",
    "answer_model",
    "judge_model",
    "runtime",
    "latency_ms",
    "prompt_tokens",
    "completion_tokens",
    "retrieval_query",
    "score",
    "matched_terms",
}


def _contains_forbidden_key(value: Any) -> bool:
    if isinstance(value, dict):
        return bool(FORBIDDEN_PACKET_KEYS & value.keys()) or any(
            _contains_forbidden_key(item) for item in value.values()
        )
    if isinstance(value, list):
        return any(_contains_forbidden_key(item) for item in value)
    return False


def canonical_sha256(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def draft_sources(draft: dict[str, Any]) -> list[dict[str, Any]]:
    """Return every admitted source while accepting legacy single-source drafts."""
    sources = draft.get("sources")
    if isinstance(sources, list) and sources:
        return sources
    source = draft.get("source")
    return [source] if isinstance(source, dict) else []


def build_candidate_source_review_packet(root: Path) -> dict[str, Any]:
    root = root.resolve()
    drafts_path = root / "benchmarks" / "first_pass" / "candidate_question_drafts.v1.json"
    sources_path = root / "benchmarks" / "first_pass" / "candidate_deal_sources.v1.json"
    companion_sources_path = (
        root / "benchmarks" / "first_pass" / "candidate_companion_sources.v1.json"
    )
    drafts_registry = json.loads(drafts_path.read_text(encoding="utf-8"))
    drafts = []
    for draft in sorted(drafts_registry["drafts"], key=lambda item: item["id"]):
        sources = [
            {
                "filename": item["filename"],
                "sha256": item["sha256"],
                "acquisition_evidence_path": item["acquisition_evidence_path"],
                "acquisition_evidence_sha256": item["acquisition_evidence_sha256"],
            }
            for item in draft_sources(draft)
        ]
        evidence = [
            {
                "citation": item["citation"],
                "anchor": item["anchor"],
                "excerpt": item["excerpt"],
                "source_sha256": item["source_sha256"],
            }
            for item in draft["evidence_candidates"]
        ]
        evidence.sort(key=lambda item: item["citation"])
        drafts.append({
            "draft_id": draft["id"],
            "candidate_id": draft["candidate_id"],
            "company": draft["company"],
            "question_family": draft["question_family"],
            "task_family": draft["task_family"],
            "provisional_question": draft["provisional_question"],
            "source": sources[0],
            "sources": sources,
            "evidence_options": evidence,
        })
    packet = {
        "packet_kind": "blinded_candidate_source_review",
        "packet_version": "2.0.0",
        "blinded_to_model": True,
        "model_identity_included": False,
        "candidate_sources_sha256": sha256(sources_path),
        "candidate_companion_sources_sha256": sha256(companion_sources_path),
        "candidate_question_drafts_sha256": sha256(drafts_path),
        "candidate_deal_count": len({item["candidate_id"] for item in drafts}),
        "draft_count": len(drafts),
        "instructions": [
            "Check each proposed passage in the full source context before deciding.",
            "Select exact supporting and confusable citations; retrieval order is hidden.",
            "Write source claims, not a model answer, and record a source-absence basis when needed.",
            "Two distinct qualified reviewers must agree, or a distinct principal must adjudicate.",
            "A valid review makes a draft eligible for later case authoring; it does not register a case.",
            "A supported cross-document draft must cite every admitted document.",
        ],
        "drafts": drafts,
    }
    if _contains_forbidden_key(packet):
        raise ValueError("candidate source review packet contains forbidden ranking or identity metadata")
    return packet


def packet_sha256(packet: dict[str, Any]) -> str:
    return canonical_sha256(packet)


def _draft_index(packet: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {item["draft_id"]: item for item in packet["drafts"]}


def source_reviewer_roster_errors(root: Path, roster: Any) -> list[str]:
    contract = root / "benchmarks" / "first_pass"
    schema = json.loads((contract / "source_reviewer_roster.schema.json").read_text(encoding="utf-8"))
    errors = schema_errors(roster, schema)
    if not isinstance(roster, dict):
        return errors
    ids = [item.get("reviewer_id") for item in roster.get("reviewers", []) if isinstance(item, dict)]
    if len(ids) != len(set(ids)):
        errors.append("$.reviewers: reviewer IDs must be unique")
    pubkeys = [item.get("buzz_pubkey") for item in roster.get("reviewers", []) if isinstance(item, dict)]
    if len(pubkeys) != len(set(pubkeys)):
        errors.append("$.reviewers: Buzz public keys must be unique")
    errors.extend(reviewer_roster_authority_errors(roster, scope="source_review"))
    return errors


def load_source_reviewer_roster(root: Path) -> dict[str, Any]:
    contract = root / "benchmarks" / "first_pass"
    roster = json.loads((contract / "source_reviewer_roster.v1.json").read_text(encoding="utf-8"))
    errors = source_reviewer_roster_errors(root, roster)
    errors.extend(
        paired_reviewer_roster_authority_errors(root, roster, scope="source_review")
    )
    if errors:
        raise ValueError("invalid source reviewer roster: " + "; ".join(errors))
    return roster


def _decision_signature(record: dict[str, Any]) -> str:
    material = {
        "decision": record.get("decision"),
        "final_question": " ".join(str(record.get("final_question", "")).split()),
        "answer_policy": record.get("answer_policy"),
        "supporting_citations": sorted(record.get("supporting_citations", [])),
        "confusable_citations": sorted(record.get("confusable_citations", [])),
        "expected_claims": sorted(
            [
                {
                    "text": " ".join(str(item.get("text", "")).split()),
                    "citations": sorted(item.get("citations", [])),
                }
                for item in record.get("expected_claims", [])
            ],
            key=lambda item: (item["text"], item["citations"]),
        ),
        "absence_basis": " ".join(str(record.get("absence_basis", "")).split()),
    }
    return canonical_sha256(material)


def _is_case_authorable(record: dict[str, Any]) -> bool:
    return (
        record.get("decision") in {"approve", "revise"}
        and record.get("answer_policy") in {"supported", "refuse_absent"}
    )


def validate_source_review_submission(
    root: Path,
    packet: dict[str, Any],
    submission: dict[str, Any],
    reviewer_roster: dict[str, Any] | None = None,
    signed_events: dict[str, dict[str, Any]] | None = None,
) -> list[str]:
    schema_path = root / "benchmarks" / "first_pass" / "candidate_source_review_submission.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    errors = schema_errors(submission, schema)
    roster = reviewer_roster or load_source_reviewer_roster(root)
    approved_reviewers = {
        item["reviewer_id"]: item
        for item in roster.get("reviewers", [])
        if item.get("active") is True and item.get("role") == "qualified_deal_source_reviewer"
    }
    approved = approved_reviewers.get(submission.get("reviewer_id"))
    if approved is None:
        errors.append("$.reviewer_id: reviewer is not active on the domain-owner-managed roster")
    elif submission.get("qualification") != approved.get("qualification"):
        errors.append("$.qualification: qualification differs from the approved reviewer roster")
    if approved is not None:
        errors.extend(validate_buzz_attestation(
            kind="candidate_source_review",
            record=submission,
            expected_pubkey=approved.get("buzz_pubkey"),
            signed_events=signed_events,
            location="$",
        ))
    if submission.get("packet_sha256") != packet_sha256(packet):
        errors.append("$.packet_sha256: submission is not bound to the review packet")
    drafts = _draft_index(packet)
    records = submission.get("drafts", [])
    record_ids = [item.get("draft_id") for item in records if isinstance(item, dict)]
    if len(record_ids) != len(set(record_ids)):
        errors.append("$.drafts: duplicate draft IDs are not allowed")
    for index, record in enumerate(records):
        if not isinstance(record, dict):
            continue
        location = f"$.drafts[{index}]"
        draft = drafts.get(record.get("draft_id"))
        if draft is None:
            errors.append(f"{location}.draft_id: draft is not in the packet")
            continue
        expected_source_hashes = sorted(item["sha256"] for item in draft_sources(draft))
        if sorted(record.get("source_sha256s", [])) != expected_source_hashes:
            errors.append(f"{location}.source_sha256s: source hashes differ from the packet")
        allowed = {item["citation"] for item in draft["evidence_options"]}
        supporting = set(record.get("supporting_citations", []))
        confusable = set(record.get("confusable_citations", []))
        if supporting & confusable:
            errors.append(f"{location}: one citation cannot be both supporting and confusable")
        cited = supporting | confusable
        for claim in record.get("expected_claims", []):
            if isinstance(claim, dict):
                cited.update(claim.get("citations", []))
        if not cited.issubset(allowed):
            errors.append(f"{location}: citations must be selected from packet evidence options")
        decision = record.get("decision")
        policy = record.get("answer_policy")
        if decision in {"approve", "revise"} and not str(record.get("final_question", "")).strip():
            errors.append(f"{location}.final_question: approval or revision needs a question")
        if decision in {"approve", "revise"} and policy not in {"supported", "refuse_absent"}:
            errors.append(
                f"{location}.answer_policy: approval or revision must be case-authorable"
            )
        if policy == "supported":
            if not record.get("supporting_citations") or not record.get("expected_claims"):
                errors.append(f"{location}: supported answers need citations and expected claims")
            for claim in record.get("expected_claims", []):
                if isinstance(claim, dict) and not set(claim.get("citations", [])).issubset(supporting):
                    errors.append(f"{location}: claim citations must be included as supporting citations")
            supporting_hashes = {
                item["source_sha256"] for item in draft["evidence_options"]
                if item["citation"] in supporting
            }
            if len(expected_source_hashes) > 1 and supporting_hashes != set(expected_source_hashes):
                errors.append(
                    f"{location}: supported cross-document drafts must cite every admitted source"
                )
        if policy == "refuse_absent" and not str(record.get("absence_basis", "")).strip():
            errors.append(f"{location}.absence_basis: source absence needs a review basis")
        if decision == "reject" and (
            policy != "unresolved" or record.get("expected_claims") or record.get("supporting_citations")
        ):
            errors.append(f"{location}: rejected drafts must remain unresolved and unlabeled")
    return errors


def compare_source_reviews(
    root: Path,
    packet: dict[str, Any],
    submissions: list[dict[str, Any]],
    reviewer_roster: dict[str, Any] | None = None,
    signed_events: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    errors: list[str] = []
    seen_review_ids: set[str] = set()
    by_draft: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for index, submission in enumerate(submissions):
        review_id = submission.get("review_id")
        if review_id in seen_review_ids:
            errors.append(f"submission {index}: duplicate review_id {review_id}")
        seen_review_ids.add(review_id)
        submission_errors = validate_source_review_submission(
            root, packet, submission, reviewer_roster, signed_events,
        )
        errors.extend(f"submission {index}: {item}" for item in submission_errors)
        if submission_errors:
            continue
        for record in submission["drafts"]:
            by_draft[record["draft_id"]].append({
                "review_id": submission["review_id"],
                "reviewer_id": submission["reviewer_id"],
                "signature": _decision_signature(record),
                "record": record,
            })
    eligible: list[str] = []
    rejected: list[str] = []
    disagreements: list[dict[str, Any]] = []
    reviewed: list[str] = []
    for draft_id in _draft_index(packet):
        reviews = by_draft.get(draft_id, [])
        if reviews:
            reviewed.append(draft_id)
        unique_reviewers = {item["reviewer_id"] for item in reviews}
        if len(reviews) != len(unique_reviewers):
            errors.append(f"{draft_id}: one reviewer submitted more than one review")
            continue
        if len(unique_reviewers) < 2:
            continue
        signatures = {item["signature"] for item in reviews}
        if len(signatures) == 1:
            if _is_case_authorable(reviews[0]["record"]):
                eligible.append(draft_id)
            else:
                rejected.append(draft_id)
        else:
            disagreements.append({
                "draft_id": draft_id,
                "review_ids": sorted(item["review_id"] for item in reviews),
                "reviewer_ids": sorted(unique_reviewers),
                "authorable_review_ids": sorted(
                    item["review_id"] for item in reviews if _is_case_authorable(item["record"])
                ),
                "rejected_review_ids": sorted(
                    item["review_id"] for item in reviews if not _is_case_authorable(item["record"])
                ),
            })
    pending = sorted(
        set(_draft_index(packet))
        - set(eligible)
        - set(rejected)
        - {item["draft_id"] for item in disagreements}
    )
    return {
        "valid": not errors,
        "submission_count": len(submissions),
        "reviewed_draft_count": len(reviewed),
        "eligible_draft_ids": sorted(eligible),
        "eligible_draft_count": len(eligible),
        "rejected_draft_ids": sorted(rejected),
        "rejected_draft_count": len(rejected),
        "disagreements": disagreements,
        "disagreement_count": len(disagreements),
        "pending_draft_ids": pending,
        "pending_draft_count": len(pending),
        "errors": errors,
        "principal_adjudication_required": bool(disagreements),
        "benchmark_cases_registered": 0,
    }


def validate_source_adjudication(
    root: Path,
    packet: dict[str, Any],
    comparison: dict[str, Any],
    adjudication: dict[str, Any],
    reviewer_roster: dict[str, Any] | None = None,
    signed_events: dict[str, dict[str, Any]] | None = None,
) -> list[str]:
    schema_path = root / "benchmarks" / "first_pass" / "candidate_source_adjudication.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    errors = schema_errors(adjudication, schema)
    roster = reviewer_roster or load_source_reviewer_roster(root)
    approved_principals = {
        item["reviewer_id"]: item
        for item in roster.get("reviewers", [])
        if item.get("active") is True and item.get("role") == "principal_source_reviewer"
    }
    principal_record = approved_principals.get(adjudication.get("principal_reviewer_id"))
    if principal_record is None:
        errors.append("$.principal_reviewer_id: principal is not active on the approved roster")
    elif adjudication.get("qualification") != principal_record.get("qualification"):
        errors.append("$.qualification: qualification differs from the approved principal roster")
    if principal_record is not None:
        errors.extend(validate_buzz_attestation(
            kind="candidate_source_adjudication",
            record=adjudication,
            expected_pubkey=principal_record.get("buzz_pubkey"),
            signed_events=signed_events,
            location="$",
        ))
    if adjudication.get("packet_sha256") != packet_sha256(packet):
        errors.append("$.packet_sha256: adjudication is not bound to the review packet")
    expected = {item["draft_id"]: item for item in comparison.get("disagreements", [])}
    decisions = adjudication.get("decisions", [])
    decision_ids = [item.get("draft_id") for item in decisions if isinstance(item, dict)]
    if set(decision_ids) != set(expected) or len(decision_ids) != len(set(decision_ids)):
        errors.append("$.decisions: adjudication must resolve every disagreement exactly once")
    principal = adjudication.get("principal_reviewer_id")
    for record in decisions:
        disagreement = expected.get(record.get("draft_id"))
        if disagreement is None:
            continue
        if principal in disagreement["reviewer_ids"]:
            errors.append(
                f"$.decisions.{record.get('draft_id')}: principal must be distinct from source reviewers"
            )
        if record.get("selected_review_id") not in disagreement["review_ids"]:
            errors.append(
                f"$.decisions.{record.get('draft_id')}.selected_review_id: must select a disagreeing review"
            )
    return errors


def evaluate_source_review_state(
    root: Path,
    packet: dict[str, Any],
    submissions: list[dict[str, Any]],
    adjudication: dict[str, Any] | None = None,
    reviewer_roster: dict[str, Any] | None = None,
    signed_events: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Return the current authoring eligibility state without registering cases."""
    roster = reviewer_roster or load_source_reviewer_roster(root)
    comparison = compare_source_reviews(root, packet, submissions, roster, signed_events)
    adjudication_errors: list[str] = []
    adjudicated_draft_count = 0
    adjudicated_draft_ids: list[str] = []
    adjudicated_rejected_draft_ids: list[str] = []
    if adjudication is not None:
        adjudication_errors = validate_source_adjudication(
            root, packet, comparison, adjudication, roster, signed_events,
        )
        if not adjudication_errors:
            disagreements = {
                item["draft_id"]: item for item in comparison.get("disagreements", [])
            }
            for item in adjudication.get("decisions", []):
                disagreement = disagreements[item["draft_id"]]
                if item["selected_review_id"] in disagreement["authorable_review_ids"]:
                    adjudicated_draft_ids.append(item["draft_id"])
                else:
                    adjudicated_rejected_draft_ids.append(item["draft_id"])
            adjudicated_draft_ids.sort()
            adjudicated_rejected_draft_ids.sort()
            adjudicated_draft_count = len(adjudicated_draft_ids)
    validation_passed = comparison["valid"] and not adjudication_errors
    eligible_after_adjudication = (
        comparison["eligible_draft_count"] + adjudicated_draft_count
        if validation_passed else 0
    )
    return {
        "verification_kind": "candidate_source_review_validation",
        "packet_sha256": packet_sha256(packet),
        "draft_count": packet["draft_count"],
        "candidate_deal_count": packet["candidate_deal_count"],
        "submission_count": comparison["submission_count"],
        "active_source_reviewer_count": sum(
            item.get("active") is True and item.get("role") == "qualified_deal_source_reviewer"
            for item in roster.get("reviewers", [])
        ),
        "active_principal_reviewer_count": sum(
            item.get("active") is True and item.get("role") == "principal_source_reviewer"
            for item in roster.get("reviewers", [])
        ),
        "reviewed_draft_count": comparison["reviewed_draft_count"],
        "agreed_eligible_draft_count": comparison["eligible_draft_count"],
        "eligible_draft_ids": sorted(
            set(comparison["eligible_draft_ids"]) | set(adjudicated_draft_ids)
        ),
        "rejected_draft_ids": sorted(
            set(comparison["rejected_draft_ids"]) | set(adjudicated_rejected_draft_ids)
        ),
        "rejected_draft_count": (
            comparison["rejected_draft_count"] + len(adjudicated_rejected_draft_ids)
        ),
        "disagreement_count": comparison["disagreement_count"],
        "disagreements": comparison["disagreements"],
        "adjudication_present": adjudication is not None,
        "adjudicated_draft_count": adjudicated_draft_count,
        "eligible_for_case_authoring_count": eligible_after_adjudication,
        "pending_draft_count": (
            packet["draft_count"]
            - eligible_after_adjudication
            - comparison["rejected_draft_count"]
            - len(adjudicated_rejected_draft_ids)
        ),
        "benchmark_cases_registered": 0,
        "promotion_ready": eligible_after_adjudication > 0 and validation_passed,
        "validation_passed": validation_passed,
        "errors": comparison["errors"] + adjudication_errors,
        "limitations": [
            "Eligibility permits later case authoring; it does not register or approve a benchmark case.",
            "No model output or retrieval rank can substitute for qualified source review.",
        ],
    }
