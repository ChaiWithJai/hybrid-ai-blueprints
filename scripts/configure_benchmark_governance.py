#!/usr/bin/env python3
"""Configure benchmark governance from one root-signed Buzz authority event."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.benchmark_governance import (  # noqa: E402
    GOVERNANCE_ROLES,
    configure_benchmark_governance,
    governance_authority_content,
)
from core.buzz_bridge import BuzzBridge, BuzzUnavailable  # noqa: E402
from core.nostr_event import public_key_from_private  # noqa: E402


def _publish_and_restore(bridge: BuzzBridge, channel: str, content: str) -> dict:
    environment = os.environ.copy()
    environment.setdefault("BUZZ_RELAY_URL", bridge.relay_url)
    completed = subprocess.run(
        [str(bridge.binary), "messages", "send", "--channel", channel, "--content", "-"],
        cwd=ROOT, env=environment, input=content, text=True,
        capture_output=True, timeout=20, check=False,
    )
    if completed.returncode != 0:
        raise BuzzUnavailable(completed.stderr.strip() or completed.stdout.strip() or "Buzz publish failed")
    published = json.loads(completed.stdout)
    event_id = str(published.get("event_id") or published.get("id") or "")
    event = bridge.events_by_ids({event_id}, channel_id=channel).get(event_id)
    if event is None:
        raise BuzzUnavailable("published governance authority event was not restored from Buzz")
    return event


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root-authority-id", required=True)
    parser.add_argument("--channel", required=True)
    for role in GOVERNANCE_ROLES:
        flag = role.replace("_", "-")
        parser.add_argument(f"--{flag}-id", required=True)
        parser.add_argument(f"--{flag}-pubkey", required=True)
    parser.add_argument("--confirm-new-benchmark-authority", action="store_true")
    args = parser.parse_args()
    try:
        if not args.confirm_new_benchmark_authority:
            raise ValueError("explicit new benchmark authority confirmation is required")
        private_key = os.environ.get("BUZZ_PRIVATE_KEY", "")
        if not private_key:
            raise ValueError("BUZZ_PRIVATE_KEY must contain the governance root private key")
        authority = {
            "state": "signed_buzz_authority",
            "root_authority_id": args.root_authority_id,
            "root_buzz_pubkey": public_key_from_private(private_key),
            "channel_id": args.channel,
            "role_assignments": [
                {
                    "role": role,
                    "actor_id": getattr(args, f"{role}_id"),
                    "buzz_pubkey": getattr(args, f"{role}_pubkey"),
                }
                for role in GOVERNANCE_ROLES
            ],
            "authority_event": None,
        }
        bridge = BuzzBridge(ROOT)
        authority["authority_event"] = _publish_and_restore(
            bridge, args.channel, governance_authority_content(authority)
        )
        configured = configure_benchmark_governance(ROOT, authority)
    except (OSError, ValueError, json.JSONDecodeError, subprocess.TimeoutExpired, BuzzUnavailable) as exc:
        print(json.dumps({"configured": False, "error": str(exc)}, indent=2), file=sys.stderr)
        return 2
    print(json.dumps({
        "configured": True,
        "benchmark_id": configured["benchmark_id"],
        "benchmark_version": configured["benchmark_version"],
        "authority_event_id": authority["authority_event"]["id"],
        "root_signature_verified": True,
        "relay_event_restored": True,
        "roles": [item["role"] for item in authority["role_assignments"]],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
