"""Cryptographic authorization for reviewer-roster entries."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from core.nostr_event import nostr_event_errors


AUTHORITY_STATES = {"unconfigured", "signed_buzz_authority"}
ROSTER_SCOPES = {"source_review", "output_review"}
ROSTER_SCOPE_FILES = {
    "source_review": "source_reviewer_roster.v1.json",
    "output_review": "output_reviewer_roster.v1.json",
}


def canonical_sha256(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def reviewer_approval_material(record: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in record.items() if key != "approval_event"}


def reviewer_roster_approval_content(scope: str, record: dict[str, Any]) -> str:
    if scope not in ROSTER_SCOPES:
        raise ValueError("reviewer roster scope is invalid")
    material = reviewer_approval_material(record)
    return "\n".join([
        "PRISM_REVIEWER_ROSTER_APPROVAL_V1",
        f"scope={scope}",
        f"reviewer_id={material.get('reviewer_id')}",
        f"role={material.get('role')}",
        f"reviewer_pubkey={material.get('buzz_pubkey')}",
        f"payload_sha256={canonical_sha256(material)}",
    ])


def reviewer_roster_authority_errors(
    roster: Any,
    *,
    scope: str,
) -> list[str]:
    errors: list[str] = []
    if not isinstance(roster, dict):
        return ["$.authority: roster must be an object"]
    authority = roster.get("authority")
    reviewers = roster.get("reviewers", [])
    if not isinstance(authority, dict):
        return ["$.authority: authority configuration is required"]
    state = authority.get("state")
    if state not in AUTHORITY_STATES:
        errors.append("$.authority.state: authority state is invalid")
        return errors
    if state == "unconfigured":
        if reviewers:
            errors.append("$.authority: an unconfigured authority cannot authorize reviewers")
        for field in ("authority_id", "display_name", "buzz_pubkey", "channel_id"):
            if authority.get(field) is not None:
                errors.append(f"$.authority.{field}: must be null while unconfigured")
        return errors

    authority_id = authority.get("authority_id")
    authority_name = authority.get("display_name")
    authority_pubkey = authority.get("buzz_pubkey")
    channel_id = authority.get("channel_id")
    if not isinstance(authority_id, str) or not authority_id.strip():
        errors.append("$.authority.authority_id: configured authority ID is required")
    if not isinstance(authority_name, str) or not authority_name.strip():
        errors.append("$.authority.display_name: configured authority name is required")
    if not isinstance(authority_pubkey, str) or not re.fullmatch(r"[a-f0-9]{64}", authority_pubkey):
        errors.append("$.authority.buzz_pubkey: configured authority key is invalid")
    if not isinstance(channel_id, str) or not channel_id.strip():
        errors.append("$.authority.channel_id: configured authority channel is required")
    if errors:
        return errors

    for index, reviewer in enumerate(reviewers):
        location = f"$.reviewers[{index}]"
        if not isinstance(reviewer, dict):
            continue
        if reviewer.get("approved_by") != authority_id:
            errors.append(f"{location}.approved_by: differs from the configured authority")
        event = reviewer.get("approval_event")
        if not isinstance(event, dict):
            errors.append(f"{location}.approval_event: raw Buzz event is required")
            continue
        event_errors = nostr_event_errors(event)
        if event_errors:
            errors.append(
                f"{location}.approval_event: raw Buzz event is invalid: "
                + "; ".join(event_errors)
            )
            continue
        if event.get("pubkey") != authority_pubkey:
            errors.append(f"{location}.approval_event: signer differs from the authority key")
        channel_tags = [
            tag[1]
            for tag in event.get("tags", [])
            if isinstance(tag, list) and len(tag) == 2 and tag[0] == "h"
        ]
        if channel_tags != [channel_id]:
            errors.append(f"{location}.approval_event: Buzz channel differs from authority scope")
        if event.get("content") != reviewer_roster_approval_content(scope, reviewer):
            errors.append(f"{location}.approval_event: signed payload differs from reviewer record")
    return errors


def paired_reviewer_roster_authority_errors(
    root: Path,
    roster: Any,
    *,
    scope: str,
) -> list[str]:
    """Fail closed unless both roster scopes name the same root of trust."""
    if scope not in ROSTER_SCOPES:
        return ["$.authority: reviewer roster scope is invalid"]
    if not isinstance(roster, dict) or not isinstance(roster.get("authority"), dict):
        return ["$.authority: authority configuration is required"]
    peer_scope = next(item for item in ROSTER_SCOPES if item != scope)
    peer_path = (
        root.resolve()
        / "benchmarks"
        / "first_pass"
        / ROSTER_SCOPE_FILES[peer_scope]
    )
    try:
        peer = json.loads(peer_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [f"$.authority: paired {peer_scope} roster is unavailable: {exc}"]
    if not isinstance(peer, dict) or not isinstance(peer.get("authority"), dict):
        return [f"$.authority: paired {peer_scope} authority is invalid"]
    if roster["authority"] != peer["authority"]:
        return [
            f"$.authority: differs from paired {peer_scope} roster authority; "
            "reviewer operations are closed until configuration is repaired"
        ]
    return []
