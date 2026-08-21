#!/usr/bin/env python3
"""Run the preregistered public deal cases through the live web and Buzz path."""

from __future__ import annotations

import argparse
import hashlib
import json
import time
import urllib.error
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BENCHMARK = ROOT / "benchmarks" / "public_deal_battletest.json"
ROOMS = {
    "anaplan": ROOT / ".runtime" / "public-deal-corpus" / "anaplan",
    "citrix": ROOT / ".runtime" / "public-deal-corpus" / "citrix",
    "microsoft_activision": ROOT / ".runtime" / "public-deal-rooms" / "microsoft_activision",
}


def post(url: str, payload: dict, timeout: int = 300) -> tuple[int, dict]:
    request = urllib.request.Request(
        url, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, json.load(response)
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read())


def file_state(folder: Path) -> dict[str, dict]:
    result = {}
    for path in sorted(item for item in folder.rglob("*") if item.is_file()):
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        result[str(path.relative_to(folder))] = {
            "sha256": digest, "bytes": path.stat().st_size, "mtime_ns": path.stat().st_mtime_ns,
        }
    return result


def summarize_chat_result(
    status: int, payload: dict, room_id: str, elapsed_ms: float,
) -> dict:
    reply = payload.get("agent_reply", {})
    response = reply.get("response", "")
    answer_state = reply.get("answer_state") or (
        "accepted" if status == 201 and response else "missing"
    )
    return {
        "room_id": room_id,
        "answer_state": answer_state,
        "response": response,
        "provider": reply.get("provider"),
        "model": reply.get("model"),
        "latency_ms": reply.get("latency_ms", elapsed_ms),
        "usage": reply.get("usage", {}),
        "raw_metadata": reply.get("raw_metadata", {}),
        "retrieved_passages": reply.get("retrieved_passages", []),
        "question_event_id": payload.get("event_id") or payload.get("question_event", {}).get("event_id"),
        "answer_event_id": reply.get("event_id"),
        "trace_id": reply.get("trace_id"),
        "source_snapshot_sha256": reply.get("source_snapshot_sha256"),
        "source_classification": reply.get("source_classification"),
        "source_provenance_sha256": reply.get("source_provenance_sha256"),
        "source_provenance": reply.get("source_provenance"),
        "canonical_path": reply.get("canonical_path"),
        "http_status": status,
        "error": reply.get("detail") or payload.get("detail") if answer_state != "accepted" else None,
        "unauthorized_file_writes": [],
    }


def main() -> int:
    cli = argparse.ArgumentParser()
    cli.add_argument("--base-url", default="http://127.0.0.1:8787")
    cli.add_argument("--output", default="evidence/bonsai-public-deal-battletest-responses.json")
    args = cli.parse_args()
    benchmark = json.loads(BENCHMARK.read_text(encoding="utf-8"))
    room_ids = {}
    for name, folder in ROOMS.items():
        preview_status, preview = post(
            f"{args.base_url}/api/deal-room/preview", {"folder_path": str(folder)}, 60,
        )
        if preview_status != 200 or preview.get("preview_state") != "ready":
            raise RuntimeError(f"could not preview {name}: {preview_status} {preview}")
        status, opened = post(
            f"{args.base_url}/api/deal-room/open",
            {"folder_path": str(folder), "preview_sha256": preview["preview_sha256"]},
            60,
        )
        if status != 201:
            raise RuntimeError(f"could not open {name}: {status} {opened}")
        room_ids[name] = opened["room_id"]

    before = file_state(ROOT / ".runtime" / "public-deal-corpus")
    responses = {}
    started = time.time()
    for case in benchmark["cases"]:
        case_started = time.time()
        status, payload = post(
            f"{args.base_url}/api/workspace/messages",
            {"room": room_ids[case["room"]], "ask_bonsai": True, "content": case["prompt"]},
        )
        responses[case["id"]] = summarize_chat_result(
            status, payload, room_ids[case["room"]], (time.time() - case_started) * 1000,
        )
        print(json.dumps({
            "case_id": case["id"], "http_status": status,
            "answer_state": responses[case["id"]]["answer_state"],
            "model": responses[case["id"]]["model"],
            "latency_ms": responses[case["id"]]["latency_ms"],
            "answer_event_id": responses[case["id"]]["answer_event_id"],
        }), flush=True)

    after = file_state(ROOT / ".runtime" / "public-deal-corpus")
    changed = sorted(set(before) ^ set(after) | {path for path in before.keys() & after.keys() if before[path] != after[path]})
    for record in responses.values():
        record["unauthorized_file_writes"] = changed
    artifact = {
        "schema": "prism.public_deal_battletest.responses.v1",
        "benchmark": "benchmarks/public_deal_battletest.json",
        "benchmark_version": benchmark["version"],
        "run_started_at_unix": started,
        "run_finished_at_unix": time.time(),
        "runtime": {
            "surface": "Prism web API to bounded retrieval to LM Studio to Buzz signed event",
            "endpoint": "http://127.0.0.1:1234",
            "source_scope_read_only": True,
        },
        "corpus_state_before": before,
        "corpus_state_after": after,
        "unauthorized_file_writes": changed,
        "responses": responses,
    }
    output = ROOT / args.output
    output.write_text(json.dumps(artifact, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(output), "changed_source_files": changed}, indent=2))
    return 1 if changed or any(
        record["http_status"] != 201 or record["answer_state"] != "accepted"
        for record in responses.values()
    ) else 0


if __name__ == "__main__":
    raise SystemExit(main())
