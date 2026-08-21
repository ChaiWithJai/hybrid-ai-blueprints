#!/usr/bin/env python3
"""Verify that every saved battletest answer exists as a signed Buzz agent event."""

from __future__ import annotations

import argparse
from dataclasses import asdict
import hashlib
import json
import sys
import time
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.buzz_bridge import BuzzBridge  # noqa: E402
from core.arize_evals import ArizeObservabilityTracer  # noqa: E402
LEGACY_ROOM_IDS = {
    "anaplan_vdr_timeline": "local_a6f2e0313e17",
    "anaplan_termination_fees": "local_a6f2e0313e17",
    "citrix_financing_mix": "local_3e826d45a754",
    "citrix_entry_leverage_absent": "local_3e826d45a754",
    "cma_competition_conclusion": "local_b86b73e5442f",
}


def main() -> int:
    cli = argparse.ArgumentParser()
    cli.add_argument("--responses", default="evidence/bonsai-public-deal-battletest-responses.json")
    cli.add_argument("--output", default="evidence/public-deal-buzz-event-verification.json")
    args = cli.parse_args()
    responses = json.loads((ROOT / args.responses).read_text(encoding="utf-8"))
    registry = json.loads(
        (ROOT / "benchmarks/first_pass/development_registry.v2.json").read_text(
            encoding="utf-8"
        )
    )
    execution_benchmark_path = ROOT / "benchmarks/public_deal_battletest.json"
    execution_benchmark = json.loads(execution_benchmark_path.read_text(encoding="utf-8"))
    questions = {case["id"]: case["prompt"] for case in execution_benchmark["cases"]}
    registry_ids = {case["id"] for case in registry["cases"]}
    if set(questions) != registry_ids or set(LEGACY_ROOM_IDS) != registry_ids:
        raise RuntimeError("execution benchmark, development registry, and room map differ")
    bridge = BuzzBridge(ROOT)
    status = bridge.status()
    expected_pubkey = status["agent_pubkey"]
    expected_owner = status["operator_pubkey"]
    rooms = json.loads((ROOT / ".runtime/buzz/rooms.json").read_text(encoding="utf-8"))
    traces = {
        trace.trace_id: trace
        for trace in ArizeObservabilityTracer(
            str(ROOT / ".runtime/evals/traces.jsonl")
        ).snapshot()
    }
    cases = []
    for case_id, legacy_room_id in LEGACY_ROOM_IDS.items():
        saved = responses["responses"][case_id]
        room_id = saved.get("room_id") or legacy_room_id
        room = rooms.get(room_id, {})
        channel_id = room.get("channel_id")
        question_event_id = saved["question_event_id"]
        answer_event_id = saved["answer_event_id"]
        raw_events = bridge.events_by_ids(
            {question_event_id, answer_event_id}, channel_id=channel_id,
        )
        question_event = raw_events[question_event_id]
        answer_event = raw_events[answer_event_id]
        question_matches = (
            question_event.get("pubkey") == expected_owner
            and question_event.get("content") == questions[case_id]
        )
        answer_content = str(answer_event.get("content", ""))
        marker = re.match(
            r"^<!-- prism:deal-room-answer model=([^\s]+) "
            r"guard=(deal_room_chat_guard_v\d+) trace=(trc_[0-9a-f]{12}) "
            r"source_class=([a-z0-9_]+) provenance=([0-9a-f]{64}) "
            r"source_snapshot=([0-9a-f]{64}) -->\n",
            answer_content,
        )
        marker_matches = bool(
            marker
            and marker.group(3) == saved.get("trace_id")
            and marker.group(4) == saved.get("source_classification")
            and marker.group(5) == saved.get("source_provenance_sha256")
            and marker.group(6) == saved.get("source_snapshot_sha256")
            and (
                (saved.get("answer_state") == "accepted" and marker.group(1) == saved.get("model"))
                or (saved.get("answer_state") == "rejected" and marker.group(1) == "rejected")
            )
        )
        visible_content = answer_content[marker.end():] if marker else answer_content
        trace = traces.get(str(saved.get("trace_id", "")))
        trace_metadata = trace.metadata if trace else {}
        trace_integrity = bool(
            marker
            and trace
            and trace.session_id == room_id
            and trace.query == questions[case_id]
            and trace.response == visible_content
            and trace.model_name == saved.get("model")
            and trace_metadata.get("product_job") == "deal_room_chat"
            and trace_metadata.get("answer_event_id") == answer_event_id
            and trace_metadata.get("question_event_id") == question_event_id
            and trace_metadata.get("guard_version") == marker.group(2)
            and trace_metadata.get("source_classification") == marker.group(4)
            and trace_metadata.get("source_provenance_sha256") == marker.group(5)
            and trace_metadata.get("source_snapshot_sha256") == marker.group(6)
        )
        event_integrity = answer_event.get("pubkey") == expected_pubkey and marker_matches
        accepted_answer_matches = (
            saved.get("answer_state") == "accepted"
            and event_integrity
            and visible_content == saved.get("response")
        )
        rejection_matches = (
            saved.get("answer_state") == "rejected"
            and event_integrity
            and "**Bonsai answer rejected**" in visible_content
            and str(saved.get("error") or "") in visible_content
        )
        cases.append({
            "case_id": case_id,
            "room_id": room_id,
            "buzz_channel_id": channel_id,
            "question_event_id": question_event_id,
            "answer_event_id": answer_event_id,
            "canonical_path": saved.get("canonical_path"),
            "question_matches_execution_benchmark": question_matches,
            "answer_state": saved.get("answer_state"),
            "answer_event_marker_matches_trace": marker_matches,
            "answer_event_integrity_passed": event_integrity,
            "trace_integrity_passed": trace_integrity,
            "accepted_answer_matches_saved_response": accepted_answer_matches,
            "rejection_event_matches_saved_outcome": rejection_matches,
            "raw_events": raw_events,
            "trace": asdict(trace) if trace else None,
            "passed": question_matches and accepted_answer_matches and trace_integrity,
        })
    report = {
        "schema": "prism.public_deal_buzz_event_verification.v3",
        "recorded_at_unix": time.time(),
        "responses_sha256": hashlib.sha256((ROOT / args.responses).read_bytes()).hexdigest(),
        "registry_sha256": hashlib.sha256(
            (ROOT / "benchmarks/first_pass/development_registry.v2.json").read_bytes()
        ).hexdigest(),
        "execution_benchmark_sha256": hashlib.sha256(
            execution_benchmark_path.read_bytes()
        ).hexdigest(),
        "relay_live_at_recording": status["relay_live"],
        "persistence": status["persistence"],
        "owner_pubkey": expected_owner,
        "agent_pubkey": expected_pubkey,
        "passed": status["relay_live"] and all(case["passed"] for case in cases),
        "cases": cases,
        "limitations": [
            "This proves signed product delivery and exact saved-response linkage, not semantic accuracy or usefulness.",
            "The relay was live when this artifact was recorded; offline verification uses the embedded raw events.",
            "The registered development cases still require qualified blinded human review.",
        ],
    }
    (ROOT / args.output).write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"passed": report["passed"], "cases": len(cases)}, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
