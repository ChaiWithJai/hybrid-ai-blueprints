"""Canonical Buzz attestations for human benchmark review records."""

from __future__ import annotations

import hashlib
import json
from typing import Any


def canonical_sha256(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def review_payload_sha256(record: dict[str, Any]) -> str:
    unsigned = {
        key: value for key, value in record.items()
        if key not in {"buzz_event_id"}
    }
    return canonical_sha256(unsigned)


def review_attestation_content(kind: str, record: dict[str, Any]) -> str:
    actor_field = next(
        (field for field in ("reviewer_id", "principal_reviewer_id", "domain_owner_id") if field in record),
        "reviewer_id",
    )
    record_id = next(
        (record.get(field) for field in ("review_id", "adjudication_id", "approval_id") if record.get(field)),
        None,
    )
    packet_hash = record.get("packet_sha256") or record.get("source_review_packet_sha256")
    return "\n".join([
        "PRISM_REVIEW_ATTESTATION_V1",
        f"kind={kind}",
        f"record_id={record_id}",
        f"actor_id={record.get(actor_field)}",
        f"packet_sha256={packet_hash}",
        f"payload_sha256={review_payload_sha256(record)}",
    ])


def validate_buzz_attestation(
    *,
    kind: str,
    record: dict[str, Any],
    expected_pubkey: str | None,
    signed_events: dict[str, dict[str, Any]] | None,
    location: str,
) -> list[str]:
    errors: list[str] = []
    event_id = record.get("buzz_event_id")
    reviewer_pubkey = record.get("reviewer_pubkey")
    if reviewer_pubkey != expected_pubkey:
        errors.append(f"{location}.reviewer_pubkey: key differs from the approved roster")
    event = (signed_events or {}).get(str(event_id))
    if event is None:
        errors.append(f"{location}.buzz_event_id: signed Buzz attestation was not supplied")
        return errors
    if event.get("id") != event_id:
        errors.append(f"{location}.buzz_event_id: event identity differs")
    if event.get("pubkey") != reviewer_pubkey:
        errors.append(f"{location}.reviewer_pubkey: Buzz event signer differs")
    if event.get("content") != review_attestation_content(kind, record):
        errors.append(f"{location}.buzz_event_id: Buzz attestation content differs from the record")
    return errors
