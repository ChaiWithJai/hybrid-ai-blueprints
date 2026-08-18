"""Short-lived signed consent for cloud dispatch and deal-room context release."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from core.nostr_event import nostr_event_errors


CONSENT_LIFETIME_SECONDS = 15 * 60
SCOPES = ("cloud_dispatch", "deal_room_context")
RAW_EVENT_FIELDS = ("id", "pubkey", "created_at", "kind", "tags", "content", "sig")


@dataclass(frozen=True)
class CloudConsentAuthority:
    policy_pubkey: str | None
    context_pubkey: str | None
    channel_id: str | None

    @classmethod
    def from_env(cls) -> "CloudConsentAuthority":
        return cls(
            os.environ.get("PRISM_CLOUD_POLICY_PUBKEY"),
            os.environ.get("PRISM_CLOUD_CONTEXT_PUBKEY"),
            os.environ.get("PRISM_CLOUD_CONSENT_CHANNEL"),
        )

    @property
    def configured(self) -> bool:
        return bool(
            self.channel_id
            and re.fullmatch(r"[a-f0-9]{64}", self.policy_pubkey or "")
            and re.fullmatch(r"[a-f0-9]{64}", self.context_pubkey or "")
            and self.policy_pubkey != self.context_pubkey
        )


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def cloud_consent_material(
    *,
    scope: str,
    request_nonce: str,
    room_id: str,
    source_snapshot_sha256: str,
    prompt_sha256: str,
    provider_endpoint: str,
    provider_model: str,
    expires_at: int,
) -> dict[str, Any]:
    if scope not in SCOPES:
        raise ValueError("cloud consent scope is invalid")
    return {
        "scope": scope,
        "request_nonce": request_nonce,
        "room_id": room_id,
        "source_snapshot_sha256": source_snapshot_sha256,
        "prompt_sha256": prompt_sha256,
        "provider_endpoint": provider_endpoint,
        "provider_model": provider_model,
        "expires_at": expires_at,
    }


def cloud_consent_content(material: dict[str, Any]) -> str:
    return "\n".join([
        "PRISM_CLOUD_CONSENT_V1",
        f"scope={material.get('scope')}",
        f"request_nonce={material.get('request_nonce')}",
        f"room_id={material.get('room_id')}",
        f"source_snapshot_sha256={material.get('source_snapshot_sha256')}",
        f"prompt_sha256={material.get('prompt_sha256')}",
        f"provider_endpoint={material.get('provider_endpoint')}",
        f"provider_model={material.get('provider_model')}",
        f"expires_at={material.get('expires_at')}",
        f"payload_sha256={canonical_sha256(material)}",
    ])


def _validate_event(
    event: Any,
    *,
    expected_pubkey: str,
    channel_id: str,
    material: dict[str, Any],
    now: int,
) -> list[str]:
    if not isinstance(event, dict):
        return ["raw Buzz consent event is required"]
    errors = nostr_event_errors(event)
    if errors:
        return errors
    if event.get("pubkey") != expected_pubkey:
        errors.append("consent signer differs from the configured authority")
    channels = [
        tag[1] for tag in event.get("tags", [])
        if isinstance(tag, list) and len(tag) == 2 and tag[0] == "h"
    ]
    if channels != [channel_id]:
        errors.append("consent event channel differs")
    if event.get("content") != cloud_consent_content(material):
        errors.append("consent event content differs from the request")
    created_at = event.get("created_at")
    expires_at = material.get("expires_at")
    if not isinstance(created_at, int) or not isinstance(expires_at, int):
        errors.append("consent timestamps are invalid")
    elif not (created_at <= now <= expires_at):
        errors.append("consent is not currently valid")
    elif expires_at - created_at > CONSENT_LIFETIME_SECONDS:
        errors.append("consent lifetime exceeds 15 minutes")
    return errors


def validate_cloud_consent(
    *,
    authority: CloudConsentAuthority,
    bundle: Any,
    room_id: str,
    source_snapshot_sha256: str,
    prompt: str,
    provider_endpoint: str,
    provider_model: str,
    include_context: bool,
    restored_events: Any = None,
    require_relay_restoration: bool = True,
    now: int | None = None,
) -> dict[str, Any]:
    now = int(time.time()) if now is None else int(now)
    errors: list[str] = []
    if not authority.configured:
        return {"valid": False, "errors": ["cloud consent authorities are not configured"]}
    if not isinstance(bundle, dict):
        return {"valid": False, "errors": ["signed cloud consent bundle is required"]}
    nonce = bundle.get("request_nonce")
    expires_at = bundle.get("expires_at")
    if not isinstance(nonce, str) or not re.fullmatch(r"[a-f0-9]{32,64}", nonce):
        errors.append("cloud consent nonce is invalid")
    if not isinstance(expires_at, int):
        errors.append("cloud consent expiry is invalid")
    prompt_hash = hashlib.sha256(prompt.encode()).hexdigest()
    materials: dict[str, dict[str, Any]] = {}
    events: dict[str, Any] = {}
    required_scopes = ["cloud_dispatch", *(["deal_room_context"] if include_context else [])]
    for scope in required_scopes:
        material = cloud_consent_material(
            scope=scope,
            request_nonce=str(nonce or ""),
            room_id=room_id,
            source_snapshot_sha256=source_snapshot_sha256,
            prompt_sha256=prompt_hash,
            provider_endpoint=provider_endpoint,
            provider_model=provider_model,
            expires_at=expires_at if isinstance(expires_at, int) else 0,
        )
        event = bundle.get(f"{scope}_event")
        materials[scope] = material
        events[scope] = event
        expected_key = (
            authority.policy_pubkey if scope == "cloud_dispatch" else authority.context_pubkey
        )
        errors.extend(
            f"{scope}: {item}" for item in _validate_event(
                event,
                expected_pubkey=str(expected_key),
                channel_id=str(authority.channel_id),
                material=material,
                now=now,
            )
        )
    supplied_context = bundle.get("deal_room_context_event")
    if not include_context and supplied_context is not None:
        errors.append("deal-room context consent was supplied for a context-free request")
    event_ids = [
        event.get("id") for event in events.values() if isinstance(event, dict)
    ]
    if len(event_ids) != len(set(event_ids)):
        errors.append("one Buzz event cannot satisfy two cloud consent scopes")
    relay_restored = False
    if require_relay_restoration:
        if not isinstance(restored_events, dict):
            errors.append("cloud consent events must be restored from the configured Buzz relay")
        else:
            restoration_errors = []
            for scope, event in events.items():
                event_id = event.get("id") if isinstance(event, dict) else None
                restored = restored_events.get(event_id) if event_id else None
                if not isinstance(restored, dict):
                    restoration_errors.append(f"{scope}: signed event was not restored from Buzz")
                    continue
                if any(restored.get(field) != event.get(field) for field in RAW_EVENT_FIELDS):
                    restoration_errors.append(
                        f"{scope}: restored Buzz event differs from the submitted signed event"
                    )
            errors.extend(restoration_errors)
            relay_restored = not restoration_errors and len(events) == len(required_scopes)
    return {
        "valid": not errors,
        "errors": errors,
        "request_nonce": nonce,
        "expires_at": expires_at,
        "room_id": room_id,
        "source_snapshot_sha256": source_snapshot_sha256,
        "prompt_sha256": prompt_hash,
        "provider_endpoint": provider_endpoint,
        "provider_model": provider_model,
        "include_context": include_context,
        "relay_restored": relay_restored,
        "event_ids": event_ids,
        "material_sha256": {
            scope: canonical_sha256(material) for scope, material in materials.items()
        },
    }


def consume_cloud_consent(path: Path, report: dict[str, Any], *, consumed_at: int | None = None) -> dict[str, Any]:
    if report.get("valid") is not True:
        raise ValueError("invalid cloud consent cannot be consumed")
    if report.get("relay_restored") is not True:
        raise ValueError("cloud consent was not restored from Buzz")
    consumed_at = int(time.time()) if consumed_at is None else int(consumed_at)
    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_suffix(path.suffix + ".lock")
    with lock_path.open("a+") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        try:
            ledger = (
                json.loads(path.read_text(encoding="utf-8"))
                if path.exists() else {"schema_version": 1, "uses": []}
            )
            if ledger.get("schema_version") != 1 or not isinstance(ledger.get("uses"), list):
                raise ValueError("cloud consent use ledger is invalid")
            used_nonces = {item.get("request_nonce") for item in ledger["uses"]}
            used_events = {
                event_id for item in ledger["uses"] for event_id in item.get("event_ids", [])
            }
            if report["request_nonce"] in used_nonces or set(report["event_ids"]) & used_events:
                raise ValueError("cloud consent was already consumed")
            record = {
                "request_nonce": report["request_nonce"],
                "event_ids": report["event_ids"],
                "room_id": report["room_id"],
                "source_snapshot_sha256": report["source_snapshot_sha256"],
                "prompt_sha256": report["prompt_sha256"],
                "provider_endpoint": report["provider_endpoint"],
                "provider_model": report["provider_model"],
                "include_context": report["include_context"],
                "relay_restored": True,
                "expires_at": report["expires_at"],
                "consumed_at": consumed_at,
                "material_sha256": report["material_sha256"],
            }
            proposed = {"schema_version": 1, "uses": [*ledger["uses"], record]}
            descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
            try:
                with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                    json.dump(proposed, handle, indent=2, sort_keys=True)
                    handle.write("\n")
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temporary, path)
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)
            return record
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
