#!/usr/bin/env python3
"""Publish a reviewer-owned Buzz attestation and bind its verified event ID."""

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
from core.review_publication import (  # noqa: E402
    KIND_CONTRACTS,
    finalize_review_publication,
    prepare_review_publication,
)


def atomic_write(path: Path, value: dict) -> None:
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
    parser.add_argument("--kind", required=True, choices=sorted(KIND_CONTRACTS))
    parser.add_argument("--record", required=True)
    parser.add_argument("--buzz-channel", required=True)
    args = parser.parse_args()
    supplied_path = Path(args.record).expanduser()
    record_path = (
        supplied_path.resolve()
        if supplied_path.is_absolute()
        else (Path.cwd() / supplied_path).resolve()
    )
    try:
        record = json.loads(record_path.read_text(encoding="utf-8"))
        prepared = prepare_review_publication(ROOT, record, args.kind)
        private_key = os.environ.get("BUZZ_PRIVATE_KEY", "")
        if not private_key:
            raise ValueError("BUZZ_PRIVATE_KEY must contain the rostered reviewer's private key")
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
            input=prepared["content"],
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
        event_id = published.get("event_id") or published.get("id")
        restored = bridge.events_by_ids({str(event_id)}, channel_id=args.buzz_channel)
        event = restored.get(str(event_id))
        if event is None:
            raise BuzzUnavailable("published review attestation was not restored from Buzz")
        finalized = finalize_review_publication(
            record, args.kind, event, prepared["expected_pubkey"],
        )
        atomic_write(record_path, finalized)
    except (OSError, json.JSONDecodeError, ValueError, BuzzUnavailable, subprocess.TimeoutExpired) as exc:
        print(json.dumps({"published": False, "error": str(exc)}, indent=2), file=sys.stderr)
        return 2
    print(json.dumps({
        "published": True,
        "record": str(record_path),
        "buzz_event_id": finalized["buzz_event_id"],
        "reviewer_pubkey": prepared["expected_pubkey"],
        "actor_id": prepared["actor_id"],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
