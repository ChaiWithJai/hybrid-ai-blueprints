#!/usr/bin/env python3
"""Publish and verify the current local trace-ledger head in Buzz."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.arize_evals import ArizeObservabilityTracer
from core.buzz_bridge import BuzzBridge
from core.trace_anchor import canonical_anchor_content, relay_is_loopback, validate_trace_anchor_receipt

def atomic_write(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(value, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if temporary.exists():
            temporary.unlink()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trace-store", default=".runtime/evals/traces.jsonl")
    parser.add_argument(
        "--channel-file", default=".runtime/buzz/benchmark-review-channel-id"
    )
    parser.add_argument("--output", default="evidence/trace-ledger-buzz-anchor-v1.json")
    args = parser.parse_args()

    trace_store = (ROOT / args.trace_store).resolve()
    channel_id = (ROOT / args.channel_file).read_text(encoding="utf-8").strip()
    status = ArizeObservabilityTracer(str(trace_store)).storage_status()
    if status.get("verified") is not True or not status.get("head_sha256"):
        raise RuntimeError("the trace ledger is not verified and nonempty")
    anchor = {
        "ledger_format": status["format"],
        "entry_count": status["entry_count"],
        "head_sha256": status["head_sha256"],
    }
    content = canonical_anchor_content(anchor)
    buzz = BuzzBridge(ROOT)
    result = buzz.send(channel_id, content)
    event_id = result["event_id"]
    raw_event = buzz.events_by_ids({event_id}, channel_id=channel_id)[event_id]
    loopback = relay_is_loopback(buzz.relay_url)
    receipt = {
        "verification_kind": "signed_buzz_trace_anchor_receipt.v1",
        "recorded_at": datetime.now(timezone.utc).astimezone().isoformat(),
        "anchor": anchor,
        "content_sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
        "channel_id": channel_id,
        "event_id": event_id,
        "signer_pubkey": buzz.identities["PRISM_BUZZ_OWNER_PUBLIC_KEY"],
        "relay_url": buzz.relay_url,
        "same_host_loopback_relay": loopback,
        "external_trust_domain": False,
        "raw_buzz_event": raw_event,
        "limitations": [
            "The signed event binds one exact trace-ledger prefix.",
            "The Buzz relay is on the same host and is not an independent timestamp authority.",
            "A local administrator can rewrite the ledger and operate the relay; this is not immutable audit storage.",
        ],
    }
    verification = validate_trace_anchor_receipt(receipt, trace_store=trace_store)
    if not verification["passed"] or not verification["current_head_anchored"]:
        raise RuntimeError("the published trace anchor did not verify against the current ledger")
    receipt["verification"] = verification
    output = (ROOT / args.output).resolve()
    atomic_write(output, receipt)
    print(json.dumps({"record": str(output), **verification}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
