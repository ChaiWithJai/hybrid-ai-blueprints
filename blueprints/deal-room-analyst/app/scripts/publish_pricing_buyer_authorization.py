#!/usr/bin/env python3
"""Publish and restore one configured commercial-authority buyer approval."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.buzz_bridge import BuzzBridge, BuzzUnavailable  # noqa: E402
from core.nostr_event import public_key_from_private  # noqa: E402
from core.pricing_poc import (  # noqa: E402
    PricingBuyerAuthority,
    pricing_buyer_authorization_content,
)


def _resolve(value: str) -> Path:
    path = Path(value).expanduser()
    return path.resolve() if path.is_absolute() else (Path.cwd() / path).resolve()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--record", required=True, help="Unsigned pricing POC JSON.")
    parser.add_argument("--buzz-channel", required=True)
    parser.add_argument("--confirm-authorize-buyer", action="store_true")
    args = parser.parse_args()
    if not args.confirm_authorize_buyer:
        print(json.dumps({
            "published": False,
            "error": "--confirm-authorize-buyer is required",
        }, indent=2), file=sys.stderr)
        return 2
    try:
        record_path = _resolve(args.record)
        record_path.relative_to(ROOT)
        record = json.loads(record_path.read_text(encoding="utf-8"))
        if "buyer_authorization" in record or "buyer_attestation" in record:
            raise ValueError("input must be the unsigned browser or operator record")
        authority = PricingBuyerAuthority.from_env()
        if not authority.configured:
            raise ValueError(
                "PRISM_PRICING_AUTHORITY_PUBKEY and "
                "PRISM_PRICING_AUTHORITY_CHANNEL must be configured"
            )
        if args.buzz_channel != authority.channel_id:
            raise ValueError("--buzz-channel differs from the configured pricing authority channel")
        buyer_key = record.get("buyer", {}).get("buyer_pubkey")
        if buyer_key == authority.pubkey:
            raise ValueError("buyer and commercial authority keys must be distinct")
        private_key = os.environ.get("BUZZ_PRIVATE_KEY", "")
        if not private_key:
            raise ValueError("BUZZ_PRIVATE_KEY must contain the commercial authority private key")
        if public_key_from_private(private_key) != authority.pubkey:
            raise ValueError("BUZZ_PRIVATE_KEY does not match PRISM_PRICING_AUTHORITY_PUBKEY")
        content = pricing_buyer_authorization_content(record)
        bridge = BuzzBridge(ROOT)
        environment = os.environ.copy()
        environment.setdefault("BUZZ_RELAY_URL", bridge.relay_url)
        completed = subprocess.run(
            [
                str(bridge.binary), "messages", "send",
                "--channel", args.buzz_channel, "--content", "-",
            ],
            cwd=ROOT,
            env=environment,
            input=content,
            text=True,
            capture_output=True,
            timeout=20,
            check=False,
        )
        if completed.returncode != 0:
            raise BuzzUnavailable(
                completed.stderr.strip() or completed.stdout.strip() or "Buzz publish failed"
            )
        published = json.loads(completed.stdout)
        event_id = str(published.get("event_id") or published.get("id") or "")
        if not event_id:
            raise BuzzUnavailable("Buzz did not return an event ID")
        event = bridge.events_by_ids(
            {event_id}, channel_id=args.buzz_channel,
        ).get(event_id)
        if event is None:
            raise BuzzUnavailable("buyer authorization event was not restored from Buzz")
        if event.get("pubkey") != authority.pubkey or event.get("content") != content:
            raise BuzzUnavailable("restored buyer authorization differs from the configured statement")
    except (
        BuzzUnavailable, json.JSONDecodeError, OSError, subprocess.TimeoutExpired,
        TypeError, ValueError,
    ) as exc:
        print(json.dumps({"published": False, "error": str(exc)}, indent=2), file=sys.stderr)
        return 2
    print(json.dumps({
        "published": True,
        "poc_id": record.get("poc_id"),
        "buyer_id": record.get("buyer", {}).get("buyer_id"),
        "buyer_pubkey": buyer_key,
        "authority_pubkey": authority.pubkey,
        "channel_id": authority.channel_id,
        "buyer_authorization_event_id": event_id,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
