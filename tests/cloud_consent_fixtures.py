from __future__ import annotations

import hashlib
import time

from core.cloud_consent import (
    CloudConsentAuthority,
    cloud_consent_content,
    cloud_consent_material,
)
from core.nostr_event import public_key_from_private
from tests.nostr_signing import sign_event


POLICY_PRIVATE_KEY = "51" * 32
CONTEXT_PRIVATE_KEY = "52" * 32
CHANNEL_ID = "prism-cloud-consent-test"


def authority() -> CloudConsentAuthority:
    return CloudConsentAuthority(
        public_key_from_private(POLICY_PRIVATE_KEY),
        public_key_from_private(CONTEXT_PRIVATE_KEY),
        CHANNEL_ID,
    )


def relay_events(bundle: dict) -> dict[str, dict]:
    events = [
        bundle.get("cloud_dispatch_event"),
        bundle.get("deal_room_context_event"),
    ]
    return {
        event["id"]: event
        for event in events
        if isinstance(event, dict) and isinstance(event.get("id"), str)
    }


def signed_bundle(
    *, agent, prompt: str, room_id: str, provider, include_context: bool,
    now: int | None = None, nonce: str = "ab" * 16,
) -> dict:
    now = int(time.time()) if now is None else now
    expires_at = now + 300
    status = provider.status()
    bundle = {"request_nonce": nonce, "expires_at": expires_at}
    scopes = ["cloud_dispatch", *(["deal_room_context"] if include_context else [])]
    for scope in scopes:
        material = cloud_consent_material(
            scope=scope,
            request_nonce=nonce,
            room_id=room_id,
            source_snapshot_sha256=agent._source_snapshot_sha256(),
            prompt_sha256=hashlib.sha256(prompt.encode()).hexdigest(),
            provider_endpoint=str(status.endpoint),
            provider_model=str(status.model),
            expires_at=expires_at,
        )
        private_key = POLICY_PRIVATE_KEY if scope == "cloud_dispatch" else CONTEXT_PRIVATE_KEY
        bundle[f"{scope}_event"] = sign_event({
            "created_at": now,
            "kind": 1,
            "tags": [["h", CHANNEL_ID]],
            "content": cloud_consent_content(material),
        }, private_key)
    return bundle
