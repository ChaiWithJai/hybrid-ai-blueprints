"""Dependency-free NIP-01 event hashing and BIP-340 signature verification."""

from __future__ import annotations

import hashlib
import json
from typing import Any


FIELD_PRIME = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEFFFFFC2F
GROUP_ORDER = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141
GENERATOR = (
    0x79BE667EF9DCBBAC55A06295CE870B07029BFCDB2DCE28D959F2815B16F81798,
    0x483ADA7726A3C4655DA4FBFC0E1108A8FD17B448A68554199C47D08FFB10D4B8,
)


def _point_add(
    left: tuple[int, int] | None, right: tuple[int, int] | None,
) -> tuple[int, int] | None:
    if left is None:
        return right
    if right is None:
        return left
    x1, y1 = left
    x2, y2 = right
    if x1 == x2 and (y1 != y2 or y1 == 0):
        return None
    slope = (
        (3 * x1 * x1) * pow(2 * y1, FIELD_PRIME - 2, FIELD_PRIME)
        if left == right
        else (y2 - y1) * pow(x2 - x1, FIELD_PRIME - 2, FIELD_PRIME)
    ) % FIELD_PRIME
    x3 = (slope * slope - x1 - x2) % FIELD_PRIME
    return x3, (slope * (x1 - x3) - y1) % FIELD_PRIME


def _point_mul(scalar: int, point: tuple[int, int] | None) -> tuple[int, int] | None:
    result = None
    addend = point
    while scalar:
        if scalar & 1:
            result = _point_add(result, addend)
        addend = _point_add(addend, addend)
        scalar >>= 1
    return result


def _lift_x(x: int) -> tuple[int, int] | None:
    if x >= FIELD_PRIME:
        return None
    value = (pow(x, 3, FIELD_PRIME) + 7) % FIELD_PRIME
    y = pow(value, (FIELD_PRIME + 1) // 4, FIELD_PRIME)
    if pow(y, 2, FIELD_PRIME) != value:
        return None
    return x, y if y % 2 == 0 else FIELD_PRIME - y


def _tagged_hash(tag: str, value: bytes) -> bytes:
    tag_hash = hashlib.sha256(tag.encode()).digest()
    return hashlib.sha256(tag_hash + tag_hash + value).digest()


def public_key_from_private(private_key: str) -> str:
    try:
        scalar = int(private_key, 16)
    except ValueError as exc:
        raise ValueError("private key must be hexadecimal") from exc
    if scalar <= 0 or scalar >= GROUP_ORDER:
        raise ValueError("private key scalar is out of range")
    point = _point_mul(scalar, GENERATOR)
    if point is None:
        raise ValueError("private key did not produce a public point")
    return point[0].to_bytes(32, "big").hex()


def event_id(event: dict[str, Any]) -> str:
    serialized = json.dumps(
        [
            0,
            event["pubkey"],
            event["created_at"],
            event["kind"],
            event["tags"],
            event["content"],
        ],
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(serialized).hexdigest()


def verify_schnorr(public_key: str, message_hash: str, signature: str) -> bool:
    try:
        public_bytes = bytes.fromhex(public_key)
        message = bytes.fromhex(message_hash)
        signature_bytes = bytes.fromhex(signature)
    except ValueError:
        return False
    if len(public_bytes) != 32 or len(message) != 32 or len(signature_bytes) != 64:
        return False
    point = _lift_x(int.from_bytes(public_bytes, "big"))
    if point is None:
        return False
    r = int.from_bytes(signature_bytes[:32], "big")
    s = int.from_bytes(signature_bytes[32:], "big")
    if r >= FIELD_PRIME or s >= GROUP_ORDER:
        return False
    challenge = int.from_bytes(
        _tagged_hash("BIP0340/challenge", signature_bytes[:32] + public_bytes + message),
        "big",
    ) % GROUP_ORDER
    negative = (point[0], (-point[1]) % FIELD_PRIME)
    result = _point_add(_point_mul(s, GENERATOR), _point_mul(challenge, negative))
    return result is not None and result[1] % 2 == 0 and result[0] == r


def nostr_event_errors(event: dict[str, Any]) -> list[str]:
    required = {"id", "pubkey", "created_at", "kind", "tags", "content", "sig"}
    missing = sorted(required - event.keys())
    if missing:
        return [f"raw Nostr event lacks fields {missing}"]
    try:
        computed = event_id(event)
    except (KeyError, TypeError, ValueError) as exc:
        return [f"raw Nostr event cannot be serialized: {exc}"]
    errors: list[str] = []
    if computed != event.get("id"):
        errors.append("raw Nostr event ID differs from its NIP-01 serialization")
    if not verify_schnorr(str(event.get("pubkey")), computed, str(event.get("sig"))):
        errors.append("raw Nostr event has an invalid BIP-340 signature")
    return errors
