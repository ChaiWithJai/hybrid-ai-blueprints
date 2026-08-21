#!/usr/bin/env python3
"""Provision the local root key allowed to authorize reviewer admissions."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.candidate_source_review import source_reviewer_roster_errors  # noqa: E402
from core.first_pass_review import output_reviewer_roster_errors  # noqa: E402
from core.reviewer_roster_authority import paired_reviewer_roster_authority_errors  # noqa: E402
from core.reviewer_roster_ledger import mutate_reviewer_roster  # noqa: E402


ROSTERS = (
    ("source_reviewer_roster.v1.json", source_reviewer_roster_errors),
    ("output_reviewer_roster.v1.json", output_reviewer_roster_errors),
)


def configure_authority(
    root: Path,
    *,
    authority_id: str,
    display_name: str,
    buzz_pubkey: str,
    channel_id: str,
    identity_checked_out_of_band: bool,
) -> dict:
    if not identity_checked_out_of_band:
        raise ValueError("explicit out-of-band authority identity confirmation is required")
    if not re.fullmatch(r"[a-z0-9][a-z0-9._-]{2,79}", authority_id):
        raise ValueError("authority ID is invalid")
    if not display_name.strip() or len(display_name) > 160:
        raise ValueError("authority display name must contain 1-160 characters")
    if not re.fullmatch(r"[a-f0-9]{64}", buzz_pubkey):
        raise ValueError("authority Buzz public key is invalid")
    if not channel_id.strip() or len(channel_id) > 200:
        raise ValueError("authority Buzz channel must contain 1-200 characters")
    authority = {
        "state": "signed_buzz_authority",
        "authority_id": authority_id,
        "display_name": display_name.strip(),
        "buzz_pubkey": buzz_pubkey,
        "channel_id": channel_id.strip(),
    }
    contract = root / "benchmarks" / "first_pass"
    current = []
    for filename, validate in ROSTERS:
        path = contract / filename
        roster = json.loads(path.read_text(encoding="utf-8"))
        errors = validate(root, roster)
        if errors:
            raise ValueError(f"current {filename} is invalid: " + "; ".join(errors))
        if roster.get("reviewers"):
            raise ValueError("authority cannot be replaced after reviewer admission")
        existing = roster.get("authority")
        if existing.get("state") == "signed_buzz_authority" and existing != authority:
            raise ValueError("a different reviewer roster authority is already configured")
        current.append((path, validate))

    for path, validate in current:
        def mutate(roster: dict, *, selected=authority) -> dict:
            if roster.get("reviewers"):
                raise ValueError("authority cannot be replaced after reviewer admission")
            existing = roster.get("authority")
            if (
                isinstance(existing, dict)
                and existing.get("state") == "signed_buzz_authority"
                and existing != selected
            ):
                raise ValueError(
                    "a different reviewer roster authority won the concurrent commit"
                )
            roster["authority"] = selected
            return selected

        mutate_reviewer_roster(root, path, validate=lambda value, check=validate: check(root, value), mutate=mutate)
    for (path, _), scope in zip(current, ("source_review", "output_review"), strict=True):
        roster = json.loads(path.read_text(encoding="utf-8"))
        errors = paired_reviewer_roster_authority_errors(root, roster, scope=scope)
        if errors:
            raise ValueError("reviewer authority pair commit is incomplete: " + "; ".join(errors))
    return authority


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--authority-id", required=True)
    parser.add_argument("--display-name", required=True)
    parser.add_argument("--buzz-pubkey", required=True)
    parser.add_argument("--buzz-channel", required=True)
    parser.add_argument("--confirm-out-of-band-authority-identity", action="store_true")
    args = parser.parse_args()
    try:
        authority = configure_authority(
            ROOT,
            authority_id=args.authority_id,
            display_name=args.display_name,
            buzz_pubkey=args.buzz_pubkey,
            channel_id=args.buzz_channel,
            identity_checked_out_of_band=args.confirm_out_of_band_authority_identity,
        )
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(json.dumps({"configured": False, "error": str(exc)}, indent=2), file=sys.stderr)
        return 2
    print(json.dumps({
        "configured": True,
        "authority": authority,
        "boundary": "This provisions a local root of trust after an operator attests to an out-of-band identity check. It does not itself verify legal identity or qualification.",
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
