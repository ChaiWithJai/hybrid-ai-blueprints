"""Signed Buzz anchoring for the local Prism trace-ledger head."""

from __future__ import annotations

import hashlib
import ipaddress
import json
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from core.arize_evals import ArizeObservabilityTracer
from core.nostr_event import nostr_event_errors


ANCHOR_KIND = "prism_trace_ledger_anchor.v1"


def canonical_anchor_content(anchor: dict[str, Any]) -> str:
    payload = {
        "anchor_kind": ANCHOR_KIND,
        "entry_count": anchor["entry_count"],
        "head_sha256": anchor["head_sha256"],
        "ledger_format": anchor["ledger_format"],
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def relay_is_loopback(relay_url: str) -> bool:
    try:
        parsed = urlsplit(relay_url)
        address = ipaddress.ip_address(parsed.hostname or "")
    except ValueError:
        return False
    return address.is_loopback


def _ledger_prefix_matches(path: Path, entry_count: int, head_sha256: str) -> bool:
    if entry_count <= 0 or not path.is_file():
        return False
    observed = None
    count = 0
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            count += 1
            if count == entry_count:
                try:
                    observed = json.loads(line).get("entry_sha256")
                except (json.JSONDecodeError, AttributeError):
                    return False
                break
    return observed == head_sha256


def validate_trace_anchor_receipt(
    receipt: dict[str, Any],
    *,
    trace_store: str | Path,
) -> dict[str, Any]:
    errors: list[str] = []
    if receipt.get("verification_kind") != "signed_buzz_trace_anchor_receipt.v1":
        errors.append("unexpected trace-anchor verification kind")
    anchor = receipt.get("anchor")
    if not isinstance(anchor, dict):
        anchor = {}
        errors.append("trace-anchor payload is missing")
    head = str(anchor.get("head_sha256", ""))
    if len(head) != 64 or any(character not in "0123456789abcdef" for character in head):
        errors.append("trace-anchor head is not a lowercase SHA-256 digest")
    entry_count = anchor.get("entry_count")
    if not isinstance(entry_count, int) or isinstance(entry_count, bool) or entry_count <= 0:
        errors.append("trace-anchor entry count is invalid")
        entry_count = 0
    if anchor.get("ledger_format") != "hash_chained_local_jsonl_v1":
        errors.append("trace-anchor ledger format is unsupported")

    event = receipt.get("raw_buzz_event")
    if not isinstance(event, dict):
        event = {}
        errors.append("raw Buzz anchor event is missing")
    else:
        errors.extend(f"raw Buzz anchor event: {error}" for error in nostr_event_errors(event))
    if event.get("id") != receipt.get("event_id"):
        errors.append("trace-anchor event identity differs")
    if event.get("pubkey") != receipt.get("signer_pubkey"):
        errors.append("trace-anchor signer identity differs")
    channel_id = str(receipt.get("channel_id", ""))
    if ["h", channel_id] not in event.get("tags", []):
        errors.append("trace-anchor event is outside the recorded Buzz channel")
    try:
        expected_content = canonical_anchor_content(anchor)
    except (KeyError, TypeError, ValueError):
        expected_content = ""
        errors.append("trace-anchor content cannot be canonicalized")
    if event.get("content") != expected_content:
        errors.append("trace-anchor event content differs from the exact ledger anchor")
    if receipt.get("content_sha256") != hashlib.sha256(
        expected_content.encode("utf-8")
    ).hexdigest():
        errors.append("trace-anchor content digest differs")

    trace_path = Path(trace_store).resolve()
    try:
        status = ArizeObservabilityTracer(str(trace_path)).storage_status()
    except (OSError, ValueError) as exc:
        status = {}
        errors.append(f"trace ledger is invalid: {exc}")
    prefix_matches = _ledger_prefix_matches(trace_path, entry_count, head)
    if not prefix_matches:
        errors.append("signed head is not the recorded trace-ledger prefix")
    current_head_anchored = bool(
        prefix_matches
        and status.get("entry_count") == entry_count
        and status.get("head_sha256") == head
    )

    relay_url = str(receipt.get("relay_url", ""))
    loopback = relay_is_loopback(relay_url)
    if receipt.get("same_host_loopback_relay") is not loopback:
        errors.append("trace-anchor relay scope label differs from the relay URL")
    if receipt.get("external_trust_domain") is not False:
        errors.append("same-host Buzz anchor cannot claim an external trust domain")

    return {
        "passed": not errors,
        "signed_anchor_verified": not errors,
        "current_head_anchored": current_head_anchored,
        "anchored_prefix_entry_count": entry_count,
        "current_entry_count": status.get("entry_count"),
        "event_id": receipt.get("event_id"),
        "relay_url": relay_url,
        "same_host_loopback_relay": loopback,
        "externally_anchored": False,
        "errors": errors,
        "meaning": (
            "A verified Buzz signature binds one exact local-ledger prefix. The relay is on "
            "the same host, so this is not an independent external timestamp or immutable audit system."
        ),
    }
