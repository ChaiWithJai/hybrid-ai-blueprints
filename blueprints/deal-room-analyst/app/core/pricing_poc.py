"""Fail-closed evaluation for the paid first-pass pricing proof of concept."""

from __future__ import annotations

import hashlib
import json
import os
import re
import statistics
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from core.first_pass_benchmark import schema_errors
from core.nostr_event import nostr_event_errors


VALUE_UNIT = "accepted_first_pass_review_per_deal_room"
RAW_EVENT_FIELDS = ("id", "pubkey", "created_at", "kind", "tags", "content", "sig")


@dataclass(frozen=True)
class PricingBuyerAuthority:
    pubkey: str | None
    channel_id: str | None

    @classmethod
    def from_env(cls) -> "PricingBuyerAuthority":
        return cls(
            os.environ.get("PRISM_PRICING_AUTHORITY_PUBKEY"),
            os.environ.get("PRISM_PRICING_AUTHORITY_CHANNEL"),
        )

    @property
    def configured(self) -> bool:
        return bool(
            re.fullmatch(r"[a-f0-9]{64}", self.pubkey or "")
            and isinstance(self.channel_id, str)
            and self.channel_id.strip()
        )


def _canonical_sha256(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def pricing_payload(record: dict[str, Any]) -> dict[str, Any]:
    """Return the exact buyer-attested payload without the recursive signature."""
    return {key: value for key, value in record.items() if key != "buyer_attestation"}


def pricing_buyer_authorization_content(record: dict[str, Any]) -> str:
    buyer = record.get("buyer", {}) if isinstance(record.get("buyer"), dict) else {}
    material = {
        "poc_id": record.get("poc_id"),
        "buyer_id": buyer.get("buyer_id"),
        "buyer_pubkey": buyer.get("buyer_pubkey"),
        "workflow_owner_role": buyer.get("workflow_owner_role"),
        "economic_buyer_role": buyer.get("economic_buyer_role"),
        "budget_authority_confirmed": buyer.get("budget_authority_confirmed"),
    }
    return "\n".join([
        "PRISM_PRICING_BUYER_AUTHORIZATION_V1",
        f"poc_id={material['poc_id']}",
        f"buyer_id={material['buyer_id']}",
        f"buyer_pubkey={material['buyer_pubkey']}",
        f"payload_sha256={_canonical_sha256(material)}",
    ])


def pricing_attestation_content(record: dict[str, Any]) -> str:
    return "\n".join([
        "PRISM_PRICING_POC_ATTESTATION_V1",
        f"poc_id={record.get('poc_id')}",
        f"buyer_id={record.get('buyer', {}).get('buyer_id')}",
        f"payload_sha256={_canonical_sha256(pricing_payload(record))}",
    ])


def finalize_pricing_poc(
    root: Path,
    unsigned_record: dict[str, Any],
    buyer_event: dict[str, Any],
    *,
    channel_id: str,
    authority: PricingBuyerAuthority,
    authority_event: dict[str, Any],
    restored_events: Mapping[str, dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Bind an exact buyer event restored from Buzz to one pricing POC."""
    if "buyer_attestation" in unsigned_record or "buyer_authorization" in unsigned_record:
        raise ValueError(
            "unsigned pricing POC must not contain buyer_authorization or buyer_attestation"
        )
    if not authority.configured:
        raise ValueError("pricing buyer authority is not configured")
    authorized_record = {
        **unsigned_record,
        "buyer_authorization": {
            "channel_id": channel_id,
            "event": authority_event,
        },
    }
    expected_content = pricing_attestation_content(authorized_record)
    event_errors = nostr_event_errors(buyer_event)
    if event_errors:
        raise ValueError("buyer Buzz event is invalid: " + "; ".join(event_errors))
    buyer_key = unsigned_record.get("buyer", {}).get("buyer_pubkey")
    if buyer_event.get("pubkey") != buyer_key:
        raise ValueError("buyer Buzz event signer differs from buyer_pubkey")
    if buyer_event.get("content") != expected_content:
        raise ValueError("buyer Buzz event content differs from the exact pricing POC payload")
    finalized = {
        **authorized_record,
        "buyer_attestation": {"channel_id": channel_id, "event": buyer_event},
    }
    result = evaluate_pricing_poc(
        root,
        finalized,
        authority=authority,
        restored_events=restored_events,
    )
    if not result["input_valid"]:
        raise ValueError(
            "buyer-attested pricing POC is structurally invalid: "
            + "; ".join(result["errors"])
        )
    return finalized, result


def _gate(observed: Any, threshold: Any, passed: bool) -> dict[str, Any]:
    return {"observed": observed, "threshold": threshold, "passed": bool(passed)}


def evaluate_pricing_poc(
    root: Path,
    record: dict[str, Any],
    *,
    authority: PricingBuyerAuthority | None = None,
    restored_events: Mapping[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Validate one buyer-attested POC and evaluate the product-value gates."""
    schema = json.loads(
        (root / "benchmarks" / "first_pass" / "pricing_poc.schema.json").read_text()
    )
    errors = schema_errors(record, schema)
    buyer = record.get("buyer", {}) if isinstance(record.get("buyer"), dict) else {}
    contract = (
        record.get("success_contract", {})
        if isinstance(record.get("success_contract"), dict) else {}
    )
    deals = [item for item in record.get("deals", []) if isinstance(item, dict)]
    price = (
        record.get("price_research", {})
        if isinstance(record.get("price_research"), dict) else {}
    )
    next_step = record.get("next_step", {}) if isinstance(record.get("next_step"), dict) else {}

    configured_authority = authority or PricingBuyerAuthority.from_env()
    authorization = (
        record.get("buyer_authorization", {})
        if isinstance(record.get("buyer_authorization"), dict) else {}
    )
    authorization_channel = authorization.get("channel_id")
    authorization_event = authorization.get("event", {})
    buyer_authority_verified = False
    authority_relay_restored = False
    if not configured_authority.configured:
        errors.append("$.buyer_authorization: pricing buyer authority is not configured")
    elif configured_authority.pubkey == buyer.get("buyer_pubkey"):
        errors.append("$.buyer_authorization: authority and buyer keys must be distinct")
    if isinstance(authorization_event, dict):
        errors.extend(
            f"$.buyer_authorization.event: {item}"
            for item in nostr_event_errors(authorization_event)
        )
        if authorization_event.get("pubkey") != configured_authority.pubkey:
            errors.append("$.buyer_authorization.event.pubkey: signer differs from configured authority")
        if authorization_event.get("content") != pricing_buyer_authorization_content(record):
            errors.append("$.buyer_authorization.event.content: authorization payload differs")
        if authorization_channel != configured_authority.channel_id:
            errors.append("$.buyer_authorization.channel_id: differs from configured authority channel")
        authority_channel_tags = [
            tag[1] for tag in authorization_event.get("tags", [])
            if isinstance(tag, list) and len(tag) == 2 and tag[0] == "h"
        ]
        if authorization_channel == configured_authority.channel_id and authority_channel_tags != [authorization_channel]:
            errors.append("$.buyer_authorization.event.tags: event is not bound to the authority channel")
        restored_authority = (restored_events or {}).get(
            str(authorization_event.get("id") or "")
        )
        if not isinstance(restored_authority, Mapping):
            errors.append("$.buyer_authorization.event: exact event was not restored from Buzz")
        elif any(
            restored_authority.get(field) != authorization_event.get(field)
            for field in RAW_EVENT_FIELDS
        ):
            errors.append("$.buyer_authorization.event: restored Buzz event differs from saved event")
        elif ["h", authorization_channel] not in restored_authority.get("tags", []):
            errors.append("$.buyer_authorization.event: restored event is in a different Buzz channel")
        else:
            authority_relay_restored = True
    else:
        errors.append("$.buyer_authorization.event: raw signed authority event is required")
    buyer_authority_verified = bool(
        configured_authority.configured
        and authority_relay_restored
        and not any(item.startswith("$.buyer_authorization") for item in errors)
    )

    attestation = (
        record.get("buyer_attestation", {})
        if isinstance(record.get("buyer_attestation"), dict) else {}
    )
    channel_id = attestation.get("channel_id")
    event = attestation.get("event", {})
    buyer_relay_restored = False
    if isinstance(event, dict):
        errors.extend(f"$.buyer_attestation.event: {item}" for item in nostr_event_errors(event))
        if event.get("pubkey") != buyer.get("buyer_pubkey"):
            errors.append("$.buyer_attestation.event.pubkey: signer differs from buyer key")
        if event.get("content") != pricing_attestation_content(record):
            errors.append("$.buyer_attestation.event.content: attestation payload differs")
        if not isinstance(channel_id, str) or not channel_id.strip():
            errors.append("$.buyer_attestation.channel_id: Buzz channel is required")
        elif channel_id != configured_authority.channel_id:
            errors.append("$.buyer_attestation.channel_id: differs from configured authority channel")
        buyer_channel_tags = [
            tag[1] for tag in event.get("tags", [])
            if isinstance(tag, list) and len(tag) == 2 and tag[0] == "h"
        ]
        if isinstance(channel_id, str) and channel_id and buyer_channel_tags != [channel_id]:
            errors.append("$.buyer_attestation.event.tags: event is not bound to the Buzz channel")
        restored = (restored_events or {}).get(str(event.get("id") or ""))
        if not isinstance(restored, Mapping):
            errors.append("$.buyer_attestation.event: exact event was not restored from Buzz")
        elif any(restored.get(field) != event.get(field) for field in RAW_EVENT_FIELDS):
            errors.append("$.buyer_attestation.event: restored Buzz event differs from saved event")
        elif ["h", channel_id] not in restored.get("tags", []):
            errors.append("$.buyer_attestation.event: restored event is in a different Buzz channel")
        else:
            buyer_relay_restored = True
    else:
        errors.append("$.buyer_attestation.event: raw signed event is required")

    deal_ids = [item.get("deal_id") for item in deals]
    source_hashes = [item.get("source_snapshot_sha256") for item in deals]
    if len(deal_ids) != len(set(deal_ids)):
        errors.append("$.deals: deal IDs must be unique")
    if len(source_hashes) != len(set(source_hashes)):
        errors.append("$.deals: source snapshots must be distinct")

    private_closed = all(
        item.get("closed_historical") is True and item.get("private_folder") is True
        for item in deals
    )
    roles = {item.get("experiment_role") for item in deals}
    required_roles = {"setup_and_correction", "transfer_without_case_specific_change"}
    reductions = [
        1 - (item.get("prism_review_minutes", 0) / item.get("historical_review_minutes", 1))
        for item in deals
        if isinstance(item.get("historical_review_minutes"), (int, float))
        and item.get("historical_review_minutes", 0) > 0
        and isinstance(item.get("prism_review_minutes"), (int, float))
    ]
    median_reduction = statistics.median(reductions) if reductions else None
    useful_fraction = (
        sum(item.get("useful_starting_point") is True for item in deals) / len(deals)
        if deals else 0.0
    )
    transfer = [
        item for item in deals
        if item.get("experiment_role") == "transfer_without_case_specific_change"
    ]
    transfer_critical = sum(item.get("critical_corrections", 0) for item in transfer)
    transfer_accepted = bool(transfer) and all(item.get("accepted_review") is True for item in transfer)
    price_values = [
        price.get("acceptable_price"), price.get("expensive_price"),
        price.get("prohibitively_expensive_price"),
    ]
    price_ordered = (
        all(isinstance(value, (int, float)) and value > 0 for value in price_values)
        and price_values[0] < price_values[1] < price_values[2]
    )
    next_step_recorded = (
        next_step.get("decision") == "agreed_paid_next_step"
        and isinstance(next_step.get("paid_amount_usd"), (int, float))
        and next_step.get("paid_amount_usd", 0) > 0
    ) or (
        next_step.get("decision") == "declined"
        and isinstance(next_step.get("declined_reason"), str)
        and bool(next_step.get("declined_reason", "").strip())
    )

    gates = {
        "buyer_and_success_contract": _gate(
            {
                "budget_authority_confirmed": buyer.get("budget_authority_confirmed"),
                "buyer_effort_committed": contract.get("buyer_effort_committed"),
                "authorized_source_access": contract.get("authorized_source_access"),
                "success_criteria_approved": contract.get("success_criteria_approved"),
            },
            "all true",
            all([
                buyer.get("budget_authority_confirmed") is True,
                contract.get("buyer_effort_committed") is True,
                contract.get("authorized_source_access") is True,
                contract.get("success_criteria_approved") is True,
            ]),
        ),
        "paid_poc": _gate(
            contract.get("paid_amount_usd"), "> 0 USD and poc_paid=true",
            contract.get("poc_paid") is True
            and isinstance(contract.get("paid_amount_usd"), (int, float))
            and contract.get("paid_amount_usd", 0) > 0,
        ),
        "private_historical_deals": _gate(
            len(deals), ">= 2 distinct closed private deal rooms",
            len(deals) >= 2 and private_closed and len(source_hashes) == len(set(source_hashes)),
        ),
        "setup_and_transfer_design": _gate(
            sorted(str(item) for item in roles), sorted(required_roles),
            required_roles.issubset(roles),
        ),
        "useful_starting_point": _gate(
            round(useful_fraction, 6), ">= 0.80", useful_fraction >= 0.80,
        ),
        "median_review_time_reduction": _gate(
            None if median_reduction is None else round(median_reduction, 6),
            ">= 0.30", median_reduction is not None and median_reduction >= 0.30,
        ),
        "transfer_deal_quality": _gate(
            {"critical_corrections": transfer_critical, "accepted": transfer_accepted},
            "0 critical corrections and accepted review",
            transfer_critical == 0 and transfer_accepted,
        ),
        "post_use_price_range": _gate(
            price_values, "0 < acceptable < expensive < prohibitively expensive",
            price.get("asked_after_use") is True
            and price.get("value_unit") == VALUE_UNIT and price_ordered,
        ),
        "paid_next_step_or_reason": _gate(
            next_step.get("decision"), "paid next step or recorded decline reason",
            next_step_recorded,
        ),
        "buyer_signature": _gate(
            event.get("id") if isinstance(event, dict) else None,
            "distinct configured authority approval plus exact Buzz-restored buyer event bound to the POC payload and channel",
            not any(
                item.startswith(("$.buyer_authorization", "$.buyer_attestation"))
                for item in errors
            ),
        ),
    }
    return {
        "verification_kind": "first_pass_pricing_poc_evaluation",
        "evidence_state": "verified" if not errors else "invalid",
        "buyer_authority_configured": configured_authority.configured,
        "buyer_authority_verified": buyer_authority_verified,
        "authority_relay_restored": authority_relay_restored,
        "buyer_relay_restored": buyer_relay_restored,
        "relay_restored": bool(authority_relay_restored and buyer_relay_restored),
        "poc_id": record.get("poc_id"),
        "input_valid": not errors,
        "errors": errors,
        "deal_count": len(deals),
        "gates": gates,
        "pricing_poc_passed": bool(not errors and all(item["passed"] for item in gates.values())),
        "limitations": [
            "This evaluates one buyer-attested proof of concept. It does not establish a market-wide price.",
            "The configured commercial authority proves control of a separate approval key, not legal identity or employment.",
            "The signed buyer event must be restored exactly from its saved Buzz channel on every evaluation.",
            "A valid price range records willingness to pay after use; it is not booked revenue.",
            "Product-value evidence does not replace benchmark accuracy or security approval.",
        ],
    }


def validate_saved_pricing_poc(
    root: Path,
    record_path: Path,
    *,
    authority: PricingBuyerAuthority | None = None,
    event_resolver: Callable[[set[str], str], Mapping[str, dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    """Return an explicit empty state or recompute an exact saved POC record."""
    configured_authority = authority or PricingBuyerAuthority.from_env()
    if not record_path.exists():
        return {
            "verification_kind": "first_pass_pricing_poc_evaluation",
            "evidence_state": "not_recorded",
            "pricing_poc_passed": False,
            "relay_restored": False,
            "buyer_authority_configured": configured_authority.configured,
            "buyer_authority_verified": False,
            "deal_count": 0,
            "gates": {},
            "errors": [],
            "limitations": [
                "No buyer-attested paid proof of concept has been recorded.",
                "Public SEC workflow evidence cannot prove private-folder willingness to pay.",
            ],
        }
    try:
        record = json.loads(record_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {
            "verification_kind": "first_pass_pricing_poc_evaluation",
            "evidence_state": "invalid",
            "pricing_poc_passed": False,
            "relay_restored": False,
            "buyer_authority_configured": configured_authority.configured,
            "buyer_authority_verified": False,
            "deal_count": 0,
            "gates": {},
            "errors": [str(exc)],
            "limitations": [],
        }
    restored_events: Mapping[str, dict[str, Any]] = {}
    restoration_error: str | None = None
    attestation = record.get("buyer_attestation", {}) if isinstance(record, dict) else {}
    authorization = record.get("buyer_authorization", {}) if isinstance(record, dict) else {}
    buyer_event = attestation.get("event", {}) if isinstance(attestation, dict) else {}
    authority_event = authorization.get("event", {}) if isinstance(authorization, dict) else {}
    event_ids = {
        str(item.get("id"))
        for item in (buyer_event, authority_event)
        if isinstance(item, dict) and item.get("id")
    }
    buyer_channel = attestation.get("channel_id") if isinstance(attestation, dict) else None
    authority_channel = authorization.get("channel_id") if isinstance(authorization, dict) else None
    if event_resolver is None:
        restoration_error = "Buzz event resolver is not configured"
    elif buyer_channel != authority_channel:
        restoration_error = "buyer and authority events name different Buzz channels"
    elif event_ids and isinstance(authority_channel, str) and authority_channel:
        try:
            restored_events = event_resolver(event_ids, authority_channel)
        except (OSError, RuntimeError, TypeError, ValueError) as exc:
            restoration_error = str(exc)
    result = evaluate_pricing_poc(
        root,
        record,
        authority=configured_authority,
        restored_events=restored_events,
    )
    if restoration_error:
        result["errors"].append(
            "$.buyer_attestation.event: Buzz restoration failed: " + restoration_error
        )
        result["evidence_state"] = "invalid"
        result["pricing_poc_passed"] = False
        result["relay_restored"] = False
    result["record_path"] = str(record_path.relative_to(root))
    result["record_sha256"] = hashlib.sha256(record_path.read_bytes()).hexdigest()
    return result
