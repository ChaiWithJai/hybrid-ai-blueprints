"""Minimal deterministic BIP-340 signer used only to create test fixtures."""

from __future__ import annotations

from core.nostr_event import (
    FIELD_PRIME,
    GENERATOR,
    GROUP_ORDER,
    _point_mul,
    _tagged_hash,
    event_id,
    public_key_from_private,
)


def sign_event(event: dict, private_key: str) -> dict:
    scalar = int(private_key, 16)
    point = _point_mul(scalar, GENERATOR)
    if point is None:
        raise ValueError("invalid private key")
    if point[1] % 2:
        scalar = GROUP_ORDER - scalar
    public_key = public_key_from_private(private_key)
    value = {**event, "pubkey": public_key}
    message_hash = event_id(value)
    private_bytes = scalar.to_bytes(32, "big")
    aux = _tagged_hash("BIP0340/aux", bytes(32))
    masked = bytes(left ^ right for left, right in zip(private_bytes, aux))
    nonce = int.from_bytes(
        _tagged_hash(
            "BIP0340/nonce",
            masked + bytes.fromhex(public_key) + bytes.fromhex(message_hash),
        ),
        "big",
    ) % GROUP_ORDER
    if nonce == 0:
        raise ValueError("invalid deterministic nonce")
    nonce_point = _point_mul(nonce, GENERATOR)
    if nonce_point is None:
        raise ValueError("invalid nonce point")
    if nonce_point[1] % 2:
        nonce = GROUP_ORDER - nonce
        nonce_point = (nonce_point[0], FIELD_PRIME - nonce_point[1])
    r_bytes = nonce_point[0].to_bytes(32, "big")
    challenge = int.from_bytes(
        _tagged_hash(
            "BIP0340/challenge",
            r_bytes + bytes.fromhex(public_key) + bytes.fromhex(message_hash),
        ),
        "big",
    ) % GROUP_ORDER
    signature = r_bytes + ((nonce + challenge * scalar) % GROUP_ORDER).to_bytes(32, "big")
    return {**value, "id": message_hash, "sig": signature.hex()}
