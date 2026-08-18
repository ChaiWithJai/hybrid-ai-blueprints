"""Blinded review packet creation and fail-closed submission validation."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from core.first_pass_benchmark import schema_errors, sha256
from core.nostr_event import nostr_event_errors
from core.reviewer_roster_authority import (
    paired_reviewer_roster_authority_errors,
    reviewer_roster_authority_errors,
)
from core.review_signatures import validate_buzz_attestation


HUMAN_DIMENSIONS = {
    "primary_decision_intent",
    "evidence_support",
    "component_completeness",
    "calibrated_uncertainty",
    "human_usefulness",
}
FORBIDDEN_IDENTITY_KEYS = {
    "provider",
    "model",
    "served_id",
    "answer_model",
    "judge_model",
    "runtime",
    "latency_ms",
    "prompt_tokens",
    "completion_tokens",
}


def output_reviewer_roster_errors(root: Path, roster: Any) -> list[str]:
    contract = root / "benchmarks" / "first_pass"
    schema = json.loads(
        (contract / "output_reviewer_roster.schema.json").read_text(encoding="utf-8")
    )
    errors = schema_errors(roster, schema)
    if not isinstance(roster, dict):
        return errors
    ids = [
        item.get("reviewer_id")
        for item in roster.get("reviewers", [])
        if isinstance(item, dict)
    ]
    if len(ids) != len(set(ids)):
        errors.append("$.reviewers: reviewer IDs must be unique")
    pubkeys = [
        item.get("buzz_pubkey")
        for item in roster.get("reviewers", [])
        if isinstance(item, dict)
    ]
    if len(pubkeys) != len(set(pubkeys)):
        errors.append("$.reviewers: Buzz public keys must be unique")
    errors.extend(reviewer_roster_authority_errors(roster, scope="output_review"))
    return errors


def load_output_reviewer_roster(root: Path) -> dict[str, Any]:
    contract = root / "benchmarks" / "first_pass"
    roster = json.loads(
        (contract / "output_reviewer_roster.v1.json").read_text(encoding="utf-8")
    )
    errors = output_reviewer_roster_errors(root, roster)
    errors.extend(
        paired_reviewer_roster_authority_errors(root, roster, scope="output_review")
    )
    if errors:
        raise ValueError("invalid output reviewer roster: " + "; ".join(errors))
    return roster


def _contains_identity_key(value: Any) -> bool:
    if isinstance(value, dict):
        return bool(FORBIDDEN_IDENTITY_KEYS & value.keys()) or any(
            _contains_identity_key(item) for item in value.values()
        )
    if isinstance(value, list):
        return any(_contains_identity_key(item) for item in value)
    return False


def build_review_packet(root: Path, responses_path: Path) -> dict[str, Any]:
    registry_path = root / "benchmarks" / "first_pass" / "development_registry.v2.json"
    rubric_path = root / "benchmarks" / "first_pass" / "rubric.v1.json"
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    rubric = json.loads(rubric_path.read_text(encoding="utf-8"))
    response_artifact = json.loads(responses_path.read_text(encoding="utf-8"))
    responses = response_artifact.get("responses", {})
    cases = []
    for case in registry["cases"]:
        response = str(responses.get(case["id"], {}).get("response", ""))
        if not response:
            raise ValueError(f"{case['id']}: response is missing")
        cases.append({
            "case_id": case["id"],
            "case_version": case["version"],
            "deal_id": case["deal_id"],
            "split": case["split"],
            "task_family": case["task_family"],
            "question": case["question"],
            "answer_policy": case["answer_policy"],
            "severity": case["severity"],
            "requested_components": case["requested_components"],
            "required_claims": case["required_claims"],
            "required_citations": case["required_citations"],
            "calculations": case["calculations"],
            "forbidden_claims": case["forbidden_claims"],
            "response": response,
            "response_sha256": hashlib.sha256(response.encode()).hexdigest(),
            "dimensions_to_review": sorted(HUMAN_DIMENSIONS),
        })
    packet = {
        "packet_kind": "blinded_first_pass_development_review",
        "packet_version": "1.0.0",
        "blinded_to_model": True,
        "model_identity_included": False,
        "registry_sha256": sha256(registry_path),
        "rubric_sha256": sha256(rubric_path),
        "responses_sha256": sha256(responses_path),
        "instructions": [
            "Review each response without access to provider or model identity.",
            "Label every listed dimension pass or fail and explain every failure.",
            "Record usefulness, decision, review time, and correction counts.",
            "Do not use this development packet as sealed test evidence.",
        ],
        "rubric_dimensions": [
            item for item in rubric["dimensions"] if item["id"] in HUMAN_DIMENSIONS
        ],
        "cases": cases,
    }
    if _contains_identity_key(packet):
        raise ValueError("review packet contains forbidden model identity metadata")
    return packet


def packet_sha256(packet: dict[str, Any]) -> str:
    encoded = json.dumps(packet, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def validate_review_submission(
    root: Path,
    packet: dict[str, Any],
    submission: dict[str, Any],
    reviewer_roster: dict[str, Any] | None = None,
    signed_events: dict[str, dict[str, Any]] | None = None,
) -> list[str]:
    schema = json.loads(
        (root / "benchmarks" / "first_pass" / "human_review_submission.schema.json").read_text()
    )
    errors = schema_errors(submission, schema)
    roster = reviewer_roster or load_output_reviewer_roster(root)
    approved_reviewers = {
        item["reviewer_id"]: item
        for item in roster.get("reviewers", [])
        if item.get("active") is True
        and item.get("role") == "qualified_deal_output_reviewer"
    }
    approved = approved_reviewers.get(submission.get("reviewer_id"))
    if approved is None:
        errors.append("$.reviewer_id: reviewer is not active on the domain-owner-managed output roster")
    elif submission.get("qualification") != approved.get("qualification"):
        errors.append("$.qualification: qualification differs from the approved output reviewer roster")
    if approved is not None:
        errors.extend(validate_buzz_attestation(
            kind="blinded_output_review",
            record=submission,
            expected_pubkey=approved.get("buzz_pubkey"),
            signed_events=signed_events,
            location="$",
        ))
    if submission.get("packet_sha256") != packet_sha256(packet):
        errors.append("$.packet_sha256: submission is not bound to the review packet")
    if submission.get("rubric_sha256") != packet.get("rubric_sha256"):
        errors.append("$.rubric_sha256: submission is not bound to the review rubric")
    expected_cases = {item["case_id"]: item for item in packet["cases"]}
    submitted_cases = {
        item.get("case_id"): item for item in submission.get("cases", [])
        if isinstance(item, dict)
    }
    if set(submitted_cases) != set(expected_cases):
        errors.append("$.cases: submission must review every packet case exactly once")
    if len(submission.get("cases", [])) != len(submitted_cases):
        errors.append("$.cases: duplicate case IDs are not allowed")
    for case_id, expected in expected_cases.items():
        observed = submitted_cases.get(case_id)
        if not observed:
            continue
        if observed.get("case_version") != expected["case_version"]:
            errors.append(f"$.cases.{case_id}: case version differs from the packet")
        if observed.get("response_sha256") != expected["response_sha256"]:
            errors.append(f"$.cases.{case_id}: response hash differs from the packet")
        dimensions = observed.get("dimensions", [])
        names = [item.get("dimension") for item in dimensions if isinstance(item, dict)]
        if set(names) != HUMAN_DIMENSIONS or len(names) != len(HUMAN_DIMENSIONS):
            errors.append(f"$.cases.{case_id}: every human dimension must appear exactly once")
        for item in dimensions:
            if item.get("label") == "fail" and not str(item.get("critique", "")).strip():
                errors.append(f"$.cases.{case_id}.{item.get('dimension')}: failed label needs a critique")
    return errors


def compare_reviewers(
    root: Path,
    packet: dict[str, Any],
    submissions: list[dict[str, Any]],
    reviewer_roster: dict[str, Any] | None = None,
    signed_events: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    errors = []
    reviewer_ids = [item.get("reviewer_id") for item in submissions]
    if len(submissions) < 2:
        errors.append("at least two review submissions are required")
    if len(reviewer_ids) != len(set(reviewer_ids)):
        errors.append("reviewers must be distinct")
    for index, submission in enumerate(submissions):
        errors.extend(
            f"submission {index}: {item}"
            for item in validate_review_submission(
                root, packet, submission, reviewer_roster, signed_events
            )
        )
    disagreements = []
    if not errors:
        by_case = [
            {case["case_id"]: case for case in submission["cases"]}
            for submission in submissions
        ]
        for case in packet["cases"]:
            case_id = case["case_id"]
            dimension_maps = [
                {item["dimension"]: item["label"] for item in records[case_id]["dimensions"]}
                for records in by_case
            ]
            for dimension in sorted(HUMAN_DIMENSIONS):
                labels = [item[dimension] for item in dimension_maps]
                if len(set(labels)) > 1:
                    disagreements.append({"case_id": case_id, "dimension": dimension, "labels": labels})
    return {
        "valid": not errors,
        "reviewer_count": len(submissions),
        "errors": errors,
        "disagreements": disagreements,
        "principal_adjudication_required": bool(disagreements),
    }


def resolve_human_labels(
    packet: dict[str, Any],
    submissions: list[dict[str, Any]],
    comparison: dict[str, Any],
    adjudication: dict[str, Any] | None = None,
) -> list[dict[str, str]]:
    """Return one human reference label per case and dimension after review."""
    if not comparison.get("valid") or len(submissions) < 2:
        raise ValueError("valid submissions from at least two reviewers are required")
    disagreement_keys = {
        (item["case_id"], item["dimension"])
        for item in comparison.get("disagreements", [])
    }
    decisions = {
        (item.get("case_id"), item.get("dimension")): item.get("final_label")
        for item in (adjudication or {}).get("decisions", [])
        if isinstance(item, dict)
    }
    if disagreement_keys != set(decisions):
        if disagreement_keys:
            raise ValueError("a complete principal adjudication is required for disagreements")
        if decisions:
            raise ValueError("adjudication contains decisions without reviewer disagreements")

    by_submission = [
        {case["case_id"]: case for case in submission["cases"]}
        for submission in submissions
    ]
    resolved = []
    for case in packet["cases"]:
        case_id = case["case_id"]
        dimension_maps = [
            {item["dimension"]: item["label"] for item in records[case_id]["dimensions"]}
            for records in by_submission
        ]
        for dimension in sorted(HUMAN_DIMENSIONS):
            key = (case_id, dimension)
            labels = [item[dimension] for item in dimension_maps]
            if key in disagreement_keys:
                final_label = decisions[key]
                resolution = "principal_adjudication"
            else:
                if len(set(labels)) != 1:
                    raise ValueError(f"unrecorded disagreement for {case_id}.{dimension}")
                final_label = labels[0]
                resolution = "reviewer_agreement"
            resolved.append({
                "case_id": case_id,
                "deal_id": case["deal_id"],
                "split": case["split"],
                "dimension": dimension,
                "severity": case["severity"],
                "final_label": final_label,
                "resolution": resolution,
            })
    return resolved


def validate_principal_adjudication(
    root: Path,
    packet: dict[str, Any],
    comparison: dict[str, Any],
    reviewer_ids: list[str],
    adjudication: dict[str, Any],
    reviewer_roster: dict[str, Any] | None = None,
    signed_events: dict[str, dict[str, Any]] | None = None,
) -> list[str]:
    schema = json.loads(
        (root / "benchmarks" / "first_pass" / "principal_adjudication.schema.json").read_text()
    )
    errors = schema_errors(adjudication, schema)
    roster = reviewer_roster or load_output_reviewer_roster(root)
    approved_principals = {
        item["reviewer_id"]: item
        for item in roster.get("reviewers", [])
        if item.get("active") is True and item.get("role") == "principal_output_reviewer"
    }
    principal = approved_principals.get(adjudication.get("principal_reviewer_id"))
    if principal is None:
        errors.append("$.principal_reviewer_id: principal is not active on the approved output roster")
    elif adjudication.get("qualification") != principal.get("qualification"):
        errors.append("$.qualification: qualification differs from the approved output principal roster")
    if principal is not None:
        errors.extend(validate_buzz_attestation(
            kind="blinded_output_adjudication",
            record=adjudication,
            expected_pubkey=principal.get("buzz_pubkey"),
            signed_events=signed_events,
            location="$",
        ))
    if adjudication.get("packet_sha256") != packet_sha256(packet):
        errors.append("$.packet_sha256: adjudication is not bound to the review packet")
    if adjudication.get("principal_reviewer_id") in reviewer_ids:
        errors.append("$.principal_reviewer_id: principal must be distinct from both reviewers")
    expected = {
        (item["case_id"], item["dimension"])
        for item in comparison.get("disagreements", [])
    }
    decisions = adjudication.get("decisions", [])
    observed = {
        (item.get("case_id"), item.get("dimension"))
        for item in decisions if isinstance(item, dict)
    }
    if observed != expected or len(decisions) != len(observed):
        errors.append("$.decisions: adjudication must resolve every disagreement exactly once")
    return errors


def validate_human_review_receipt(root: Path, receipt: dict[str, Any]) -> dict[str, Any]:
    """Replay a saved review receipt from its submissions and raw signed events."""
    root = root.resolve()
    errors: list[str] = []
    packet_path_value = str(receipt.get("packet_path", ""))
    packet_path = (root / packet_path_value).resolve()
    try:
        packet_path.relative_to(root)
        packet = json.loads(packet_path.read_text(encoding="utf-8"))
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        packet = {}
        errors.append(f"packet is unavailable: {exc}")
    if packet and receipt.get("packet_sha256") != packet_sha256(packet):
        errors.append("packet hash differs from the receipt")

    roster_path = root / "benchmarks" / "first_pass" / "output_reviewer_roster.v1.json"
    try:
        roster = load_output_reviewer_roster(root)
        if receipt.get("reviewer_roster_sha256") != sha256(roster_path):
            errors.append("output reviewer roster hash differs from the receipt")
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        roster = {"reviewers": []}
        errors.append(f"output reviewer roster is unavailable: {exc}")

    signed_events = receipt.get("signed_events", {})
    if not isinstance(signed_events, dict):
        signed_events = {}
        errors.append("signed events must be an object keyed by event ID")
    channel_id = receipt.get("buzz_channel_id")
    for event_key, event in signed_events.items():
        if not isinstance(event, dict):
            errors.append(f"signed event {event_key} is not an object")
            continue
        if event.get("id") != event_key:
            errors.append(f"signed event key differs from event ID: {event_key}")
        errors.extend(
            f"signed event {event_key}: {item}" for item in nostr_event_errors(event)
        )
        if not channel_id or ["h", channel_id] not in event.get("tags", []):
            errors.append(f"signed event {event_key} is not bound to the review channel")

    submissions = receipt.get("submissions", [])
    if not isinstance(submissions, list):
        submissions = []
        errors.append("submissions must be an array")
    comparison = compare_reviewers(
        root, packet, submissions, roster, signed_events,
    ) if packet else {
        "valid": False,
        "errors": ["packet unavailable"],
        "disagreements": [],
        "principal_adjudication_required": False,
    }
    errors.extend(f"review comparison: {item}" for item in comparison.get("errors", []))

    adjudication = receipt.get("adjudication")
    adjudication_errors: list[str] = []
    if adjudication is not None and packet:
        adjudication_errors = validate_principal_adjudication(
            root,
            packet,
            comparison,
            [item.get("reviewer_id") for item in submissions],
            adjudication,
            roster,
            signed_events,
        )
        errors.extend(f"principal adjudication: {item}" for item in adjudication_errors)
    adjudication_complete = bool(
        not comparison.get("principal_adjudication_required")
        or (adjudication is not None and not adjudication_errors)
    )
    review_gate_complete = bool(
        comparison.get("valid")
        and len(submissions) >= 2
        and adjudication_complete
        and not errors
    )
    resolved_labels: list[dict[str, str]] = []
    if review_gate_complete:
        try:
            resolved_labels = resolve_human_labels(
                packet, submissions, comparison, adjudication,
            )
        except ValueError as exc:
            errors.append(str(exc))
            review_gate_complete = False
    expected_resolved = receipt.get("resolved_labels", [])
    if review_gate_complete and resolved_labels != expected_resolved:
        errors.append("resolved labels differ from replayed signed reviews")
        review_gate_complete = False
    resolved_hash = (
        hashlib.sha256(json.dumps(
            resolved_labels, sort_keys=True, separators=(",", ":")
        ).encode()).hexdigest()
        if resolved_labels else None
    )
    if review_gate_complete and receipt.get("resolved_labels_sha256") != resolved_hash:
        errors.append("resolved label hash differs from replayed signed reviews")
        review_gate_complete = False
    if receipt.get("review_gate_complete") is not review_gate_complete:
        errors.append("saved review gate state differs from replayed state")
    return {
        "passed": review_gate_complete and not errors,
        "errors": errors,
        "resolved_labels": resolved_labels,
        "resolved_labels_sha256": resolved_hash,
        "comparison": comparison,
        "adjudication_complete": adjudication_complete,
    }
