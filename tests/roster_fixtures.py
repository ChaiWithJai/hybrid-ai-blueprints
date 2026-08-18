"""Signed reviewer-roster fixtures with an explicit synthetic authority."""

from __future__ import annotations

from copy import deepcopy

from core.nostr_event import public_key_from_private
from core.reviewer_roster_authority import reviewer_roster_approval_content
from tests.nostr_signing import sign_event


AUTHORITY_PRIVATE_KEY = "4".zfill(64)
AUTHORITY_ID = "synthetic-domain-owner"
CHANNEL_ID = "87654321-4321-4321-8321-cba987654321"
REVIEWER_PRIVATE_KEYS = {
    "reviewer-a": "1".zfill(64),
    "reviewer-b": "2".zfill(64),
    "principal-c": "3".zfill(64),
    "domain-owner": "3".zfill(64),
}


def reviewer_pubkey(reviewer_id: str) -> str:
    return public_key_from_private(REVIEWER_PRIVATE_KEYS[reviewer_id])


def configured_roster() -> dict:
    return {
        "version": "test",
        "status": "domain_owner_managed",
        "authority": {
            "state": "signed_buzz_authority",
            "authority_id": AUTHORITY_ID,
            "display_name": "Synthetic Domain Owner",
            "buzz_pubkey": public_key_from_private(AUTHORITY_PRIVATE_KEY),
            "channel_id": CHANNEL_ID,
        },
        "reviewers": [],
    }


def signed_reviewer_arguments(
    scope: str,
    *,
    reviewer_id: str,
    display_name: str,
    role: str,
    qualification: str,
    reviewer_private_key: str,
    approved_at: str,
    created_at: int,
) -> dict:
    record = {
        "reviewer_id": reviewer_id,
        "display_name": display_name,
        "role": role,
        "qualification": qualification,
        "buzz_pubkey": public_key_from_private(reviewer_private_key),
        "approved_by": AUTHORITY_ID,
        "approved_at": approved_at,
        "active": True,
    }
    event = sign_event({
        "created_at": created_at,
        "kind": 9,
        "tags": [["h", CHANNEL_ID]],
        "content": reviewer_roster_approval_content(scope, record),
    }, AUTHORITY_PRIVATE_KEY)
    return {
        **{key: value for key, value in record.items() if key != "active"},
        "approval_event": event,
    }


def signed_roster(scope: str, reviewers: list[dict]) -> dict:
    result = configured_roster()
    for index, supplied in enumerate(reviewers, start=1):
        record = deepcopy(supplied)
        record["buzz_pubkey"] = reviewer_pubkey(record["reviewer_id"])
        record["approved_by"] = AUTHORITY_ID
        event = sign_event({
            "created_at": 1786781000 + index,
            "kind": 9,
            "tags": [["h", CHANNEL_ID]],
            "content": reviewer_roster_approval_content(scope, record),
        }, AUTHORITY_PRIVATE_KEY)
        record["approval_event"] = event
        result["reviewers"].append(record)
    return result
