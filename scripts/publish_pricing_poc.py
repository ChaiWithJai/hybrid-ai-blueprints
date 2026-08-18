#!/usr/bin/env python3
"""Publish, restore, verify, and atomically record one buyer pricing POC."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.buzz_bridge import BuzzBridge, BuzzUnavailable  # noqa: E402
from core.nostr_event import public_key_from_private  # noqa: E402
from core.pricing_poc import (  # noqa: E402
    PricingBuyerAuthority,
    finalize_pricing_poc,
    pricing_attestation_content,
    pricing_buyer_authorization_content,
)


def _resolve(value: str) -> Path:
    path = Path(value).expanduser()
    return path.resolve() if path.is_absolute() else (Path.cwd() / path).resolve()


def _atomic_write(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent,
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(value, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
    except Exception:
        try:
            os.unlink(temporary_name)
        except OSError:
            pass
        raise


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--record", required=True, help="Unsigned buyer POC JSON.")
    parser.add_argument("--buzz-channel", required=True)
    parser.add_argument(
        "--buyer-authorization-event",
        required=True,
        help="Event ID for the configured commercial authority's buyer approval.",
    )
    parser.add_argument(
        "--output", default="evidence/first-pass-pricing-poc.json",
        help="Canonical verified record path.",
    )
    parser.add_argument("--confirm-record-buyer-evidence", action="store_true")
    parser.add_argument("--confirm-replace-existing", action="store_true")
    args = parser.parse_args()
    if not args.confirm_record_buyer_evidence:
        print(json.dumps({
            "recorded": False,
            "error": "--confirm-record-buyer-evidence is required",
        }, indent=2), file=sys.stderr)
        return 2
    try:
        record_path = _resolve(args.record)
        output_path = _resolve(args.output)
        record_path.relative_to(ROOT)
        output_path.relative_to(ROOT)
        if output_path.exists() and not args.confirm_replace_existing:
            raise ValueError(
                "pricing POC evidence already exists; use --confirm-replace-existing "
                "only for an intentional new evidence version"
            )
        unsigned = json.loads(record_path.read_text(encoding="utf-8"))
        if "buyer_attestation" in unsigned or "buyer_authorization" in unsigned:
            raise ValueError("input must be the unsigned browser or operator record")
        authority = PricingBuyerAuthority.from_env()
        if not authority.configured:
            raise ValueError(
                "PRISM_PRICING_AUTHORITY_PUBKEY and "
                "PRISM_PRICING_AUTHORITY_CHANNEL must be configured"
            )
        if args.buzz_channel != authority.channel_id:
            raise ValueError("--buzz-channel differs from the configured pricing authority channel")
        private_key = os.environ.get("BUZZ_PRIVATE_KEY", "")
        if not private_key:
            raise ValueError("BUZZ_PRIVATE_KEY must contain the buyer's private key")
        derived_key = public_key_from_private(private_key)
        expected_key = unsigned.get("buyer", {}).get("buyer_pubkey")
        if derived_key != expected_key:
            raise ValueError("BUZZ_PRIVATE_KEY does not match buyer_pubkey")
        if expected_key == authority.pubkey:
            raise ValueError("buyer and commercial authority keys must be distinct")
        bridge = BuzzBridge(ROOT)
        authority_events = bridge.events_by_ids(
            {args.buyer_authorization_event}, channel_id=args.buzz_channel,
        )
        authority_event = authority_events.get(args.buyer_authorization_event)
        if authority_event is None:
            raise BuzzUnavailable("buyer authorization event was not restored from Buzz")
        if authority_event.get("pubkey") != authority.pubkey:
            raise ValueError("buyer authorization signer differs from the configured authority")
        if authority_event.get("content") != pricing_buyer_authorization_content(unsigned):
            raise ValueError("buyer authorization payload differs from the unsigned POC")
        authority_channels = [
            tag[1] for tag in authority_event.get("tags", [])
            if isinstance(tag, list) and len(tag) == 2 and tag[0] == "h"
        ]
        if authority_channels != [args.buzz_channel]:
            raise ValueError("buyer authorization event has an ambiguous Buzz channel")
        authorized_record = {
            **unsigned,
            "buyer_authorization": {
                "channel_id": args.buzz_channel,
                "event": authority_event,
            },
        }
        environment = os.environ.copy()
        environment.setdefault("BUZZ_RELAY_URL", bridge.relay_url)
        completed = subprocess.run(
            [
                str(bridge.binary), "messages", "send",
                "--channel", args.buzz_channel, "--content", "-",
            ],
            cwd=ROOT,
            env=environment,
            input=pricing_attestation_content(authorized_record),
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
        restored = bridge.events_by_ids(
            {args.buyer_authorization_event, event_id}, channel_id=args.buzz_channel,
        )
        event = restored.get(event_id)
        if event is None:
            raise BuzzUnavailable("buyer event was not restored from Buzz")
        finalized, evaluation = finalize_pricing_poc(
            ROOT,
            unsigned,
            event,
            channel_id=args.buzz_channel,
            authority=authority,
            authority_event=authority_event,
            restored_events=restored,
        )
        _atomic_write(output_path, finalized)
    except (
        BuzzUnavailable, json.JSONDecodeError, OSError, subprocess.TimeoutExpired,
        TypeError, ValueError,
    ) as exc:
        print(json.dumps({"recorded": False, "error": str(exc)}, indent=2), file=sys.stderr)
        return 2
    print(json.dumps({
        "recorded": True,
        "record": str(output_path.relative_to(ROOT)),
        "poc_id": finalized["poc_id"],
        "buyer_event_id": finalized["buyer_attestation"]["event"]["id"],
        "buyer_authorization_event_id": finalized["buyer_authorization"]["event"]["id"],
        "deal_count": evaluation["deal_count"],
        "pricing_poc_passed": evaluation["pricing_poc_passed"],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
