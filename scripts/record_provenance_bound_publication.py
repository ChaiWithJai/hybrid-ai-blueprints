#!/usr/bin/env python3
"""Record an independently restored provenance-bound Buzz publication."""

from __future__ import annotations

import argparse
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import re
import sys
import time
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import server
from core.arize_evals import ArizeObservabilityTracer
from core.buzz_bridge import nostr_event_errors


MARKER = re.compile(
    r"^<!-- prism:deal-room-answer model=([^\s]+) "
    r"guard=(deal_room_chat_guard_v\d+) trace=(trc_[0-9a-f]{12}) "
    r"source_class=([a-z0-9_]+) provenance=([0-9a-f]{64}) "
    r"source_snapshot=([0-9a-f]{64}) -->\n"
)


def get_json(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=60) as response:
        return json.load(response)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8787")
    parser.add_argument("--room", required=True)
    parser.add_argument("--event", required=True)
    parser.add_argument("--trace", required=True)
    parser.add_argument(
        "--output", default="evidence/provenance-bound-publication-v1.json",
    )
    args = parser.parse_args()

    status = get_json(f"{args.base_url}/api/status")
    room_api = get_json(
        f"{args.base_url}/api/deal-room?room={urllib.parse.quote(args.room)}"
    )
    messages = get_json(
        f"{args.base_url}/api/workspace/messages?room={urllib.parse.quote(args.room)}"
    )
    visible_event = next(
        (item for item in messages.get("messages", []) if item.get("id") == args.event),
        None,
    )
    raw_events = server.global_buzz.events_by_ids(
        {args.event}, channel_id=messages.get("channel_id")
    )
    event = raw_events.get(args.event)
    persisted_tracer = ArizeObservabilityTracer(
        str(ROOT / ".runtime" / "evals" / "traces.jsonl")
    )
    trace = next(
        (item for item in persisted_tracer.snapshot() if item.trace_id == args.trace),
        None,
    )
    room = server.all_deal_rooms().get(args.room)
    current_provenance = server.source_provenance_binding(room) if room else None
    current_snapshot = (
        server.inspect_local_deal_room(room["path"])["preview"]["preview_sha256"]
        if room else None
    )
    content = str((event or {}).get("content", ""))
    marker = MARKER.match(content)
    visible_response = content[marker.end():] if marker else None
    metadata = trace.metadata if trace else {}

    assertions = [
        {"name": "raw_event_restored", "passed": event is not None},
        {
            "name": "agent_signature_verified",
            "passed": bool(
                event
                and not nostr_event_errors(event)
                and event.get("pubkey") == status.get("buzz", {}).get("agent_pubkey")
            ),
        },
        {
            "name": "verified_message_matches_raw_event",
            "passed": bool(
                visible_event
                and event
                and all(
                    visible_event.get(field) == event.get(field)
                    for field in ("id", "pubkey", "created_at", "kind", "content", "tags")
                )
            ),
        },
        {"name": "provenance_marker_present", "passed": marker is not None},
        {
            "name": "trace_restored",
            "passed": bool(trace and trace.session_id == args.room),
        },
        {
            "name": "signed_response_matches_trace",
            "passed": bool(trace and visible_response == trace.response),
        },
        {
            "name": "event_trace_binding_matches",
            "passed": bool(trace and metadata.get("answer_event_id") == args.event),
        },
        {
            "name": "marker_trace_metadata_match",
            "passed": bool(
                marker
                and trace
                and marker.group(1) == trace.model_name
                and marker.group(2) == metadata.get("guard_version")
                and marker.group(3) == trace.trace_id
                and marker.group(4) == metadata.get("source_classification")
                and marker.group(5) == metadata.get("source_provenance_sha256")
                and marker.group(6) == metadata.get("source_snapshot_sha256")
            ),
        },
        {
            "name": "current_provenance_recomputed",
            "passed": bool(
                marker
                and current_provenance
                and marker.group(4) == current_provenance.get("classification")
                and marker.group(5) == current_provenance.get("binding_sha256")
            ),
        },
        {
            "name": "current_complete_folder_snapshot_recomputed",
            "passed": bool(marker and marker.group(6) == current_snapshot),
        },
        {
            "name": "public_integrity_visible",
            "passed": bool(
                room_api.get("source_provenance", {}).get("classification")
                == "public_filing_corpus"
                and room_api.get("source_provenance", {}).get("public_integrity", {}).get("passed")
                is True
            ),
        },
        {
            "name": "not_accuracy_or_buyer_evidence",
            "passed": bool(
                room_api.get("source_provenance", {}).get("accuracy_release_evidence")
                is False
                and room_api.get("source_provenance", {}).get("buyer_evidence") is False
            ),
        },
    ]
    record = {
        "verification_kind": "provenance_bound_publication",
        "schema_version": 1,
        "recorded_at_unix": time.time(),
        "passed": all(item["passed"] for item in assertions),
        "room": args.room,
        "source_folder": (
            str(Path(room["path"]).resolve().relative_to(ROOT))
            if room and Path(room["path"]).resolve().is_relative_to(ROOT)
            else str(Path(room["path"]).resolve()) if room else None
        ),
        "event_id": args.event,
        "trace_id": args.trace,
        "canonical_path": f"/rooms/{args.room}/discussion?event={args.event}",
        "source_classification": marker.group(4) if marker else None,
        "source_provenance_sha256": marker.group(5) if marker else None,
        "source_snapshot_sha256": marker.group(6) if marker else None,
        "public_integrity": room_api.get("source_provenance", {}).get("public_integrity"),
        "event": event,
        "trace": asdict(trace) if trace else None,
        "assertions": assertions,
        "limitations": [
            "This proves a signed local publication against an unchanged hash-verified public SEC folder.",
            "It is a structural provenance and durability check, not domain accuracy, private-customer, buyer, or pricing evidence.",
            "Buzz and the trace ledger are on the same host and are not independent external trust domains.",
        ],
    }
    output = ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "passed": record["passed"],
        "output": str(output),
        "sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
        "assertions": len(assertions),
    }, indent=2))
    return 0 if record["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
