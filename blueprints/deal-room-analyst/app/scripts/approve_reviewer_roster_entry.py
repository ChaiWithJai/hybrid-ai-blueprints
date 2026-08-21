#!/usr/bin/env python3
"""Publish and record one authority-signed reviewer admission."""

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
from scripts.add_output_reviewer import add_output_reviewer  # noqa: E402
from scripts.add_source_reviewer import add_reviewer  # noqa: E402
from scripts.render_reviewer_roster_approval import build_record  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scope", required=True, choices=("source_review", "output_review"))
    parser.add_argument("--reviewer-id", required=True)
    parser.add_argument("--display-name", required=True)
    parser.add_argument("--role", required=True)
    parser.add_argument("--qualification", required=True)
    parser.add_argument("--buzz-pubkey", required=True)
    parser.add_argument("--approved-at", required=True)
    parser.add_argument("--confirm-domain-owner-approval", action="store_true")
    args = parser.parse_args()
    try:
        if not args.confirm_domain_owner_approval:
            raise ValueError("explicit domain-owner approval confirmation is required")
        record, authority, content = build_record(args)
        private_key = os.environ.get("BUZZ_PRIVATE_KEY", "")
        if not private_key:
            raise ValueError("BUZZ_PRIVATE_KEY must contain the configured authority private key")
        if public_key_from_private(private_key) != authority["buzz_pubkey"]:
            raise ValueError("BUZZ_PRIVATE_KEY does not match the configured authority public key")
        bridge = BuzzBridge(ROOT)
        environment = os.environ.copy()
        environment.setdefault("BUZZ_RELAY_URL", bridge.relay_url)
        completed = subprocess.run(
            [
                str(bridge.binary), "messages", "send",
                "--channel", authority["channel_id"], "--content", "-",
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
        restored = bridge.events_by_ids({event_id}, channel_id=authority["channel_id"])
        event = restored.get(event_id)
        if event is None:
            raise BuzzUnavailable("published roster approval was not restored from Buzz")
        arguments = {
            **{key: value for key, value in record.items() if key != "active"},
            "approval_event": event,
            "approval_confirmed": True,
        }
        if args.scope == "source_review":
            admitted = add_reviewer(ROOT, **arguments)
        else:
            admitted = add_output_reviewer(ROOT, **arguments)
    except (
        OSError, json.JSONDecodeError, subprocess.TimeoutExpired,
        ValueError, BuzzUnavailable,
    ) as exc:
        print(json.dumps({"approved": False, "error": str(exc)}, indent=2), file=sys.stderr)
        return 2
    print(json.dumps({
        "approved": True,
        "scope": args.scope,
        "reviewer": admitted,
        "authority_event_id": event_id,
        "authority_signature_verified": True,
        "relay_event_restored": True,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
