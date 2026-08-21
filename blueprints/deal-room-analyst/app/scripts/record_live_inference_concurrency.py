#!/usr/bin/env python3
"""Record that the live surface stays responsive during a real Bonsai request."""

from __future__ import annotations

import argparse
import hashlib
import json
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def get_json(base_url: str, path: str, timeout: float = 10) -> tuple[dict, float]:
    started = time.monotonic()
    with urllib.request.urlopen(f"{base_url}{path}", timeout=timeout) as response:
        if response.status != 200:
            raise RuntimeError(f"GET {path} returned {response.status}")
        body = json.load(response)
    return body, (time.monotonic() - started) * 1000


def post_question(base_url: str, room: str, prompt: str) -> tuple[int, dict]:
    payload = json.dumps({
        "room": room, "content": prompt, "ask_bonsai": True,
    }).encode()
    request = urllib.request.Request(
        f"{base_url}/api/workspace/messages", data=payload, method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            return response.status, json.load(response)
    except urllib.error.HTTPError as exc:
        return exc.code, json.load(exc)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8787")
    parser.add_argument("--room", default="local_bbfa4e91f7ee")
    parser.add_argument(
        "--prompt",
        default=(
            "Report the stored first-year ROI for the ML Platform scenario. Use the exact "
            "admitted workbook citation and explicitly say the formula is cached and was not recalculated."
        ),
    )
    parser.add_argument("--output", default="evidence/live-inference-concurrency-v1.json")
    args = parser.parse_args()
    base_url = args.base_url.rstrip("/")

    warm_status, _ = get_json(base_url, "/api/status")
    deployment = warm_status.get("measured_local_deployment", {})
    if deployment.get("verified") is not True:
        raise RuntimeError("measured local deployment is not verified")
    before_messages, _ = get_json(
        base_url, f"/api/workspace/messages?room={args.room}",
    )
    before_ids = {item.get("id") for item in before_messages.get("messages", [])}

    probes = []
    request_started = time.monotonic()
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(post_question, base_url, args.room, args.prompt)
        while not future.done():
            status_body, latency_ms = get_json(base_url, "/api/status", timeout=5)
            probes.append({
                "latency_ms": round(latency_ms, 3),
                "http_status": 200,
                "product_stage": status_body.get("product_stage"),
                "deployment_verified": status_body.get(
                    "measured_local_deployment", {}
                ).get("verified"),
                "request_was_in_flight": not future.done(),
            })
            if not future.done():
                time.sleep(0.05)
        post_status, post_body = future.result()
    request_duration_ms = (time.monotonic() - request_started) * 1000

    reply = post_body.get("agent_reply", {})
    question_event_id = post_body.get("event_id")
    answer_event_id = reply.get("event_id")
    trace_id = reply.get("trace_id")
    messages, _ = get_json(base_url, f"/api/workspace/messages?room={args.room}")
    evals, _ = get_json(base_url, "/api/evals")
    by_event = {item.get("id"): item for item in messages.get("messages", [])}
    trace = next(
        (item for item in evals.get("traces", []) if item.get("trace_id") == trace_id),
        None,
    )
    question = by_event.get(question_event_id, {})
    answer = by_event.get(answer_event_id, {})
    new_ids = set(by_event) - before_ids
    response_text = str(reply.get("response", ""))
    max_status_latency_ms = max((item["latency_ms"] for item in probes), default=None)
    passed = bool(
        post_status == 201
        and reply.get("answer_state") != "rejected"
        and question_event_id in new_ids
        and answer_event_id in new_ids
        and question.get("signature_verified") is True
        and answer.get("signature_verified") is True
        and trace
        and trace.get("metadata", {}).get("result_state") == "guard_passed_and_signed_to_buzz"
        and trace.get("metadata", {}).get("provider_id") == "local_bonsai"
        and trace.get("model_name") == "27b@q1_0"
        and trace.get("metadata", {}).get("context_admission")
        == "loaded_model_tokenizer_with_runtime_margin"
        and trace.get("metadata", {}).get("fitted_context_tokens") == 16_384
        and trace.get("metadata", {}).get("context_runtime_margin_tokens") == 32
        and trace.get("metadata", {}).get("reserved_output_tokens") == 4_096
        and isinstance(trace.get("metadata", {}).get("admitted_input_tokens"), int)
        and trace.get("metadata", {}).get("runtime_input_tokens", 0)
        <= trace.get("metadata", {}).get("admitted_input_tokens", -1)
        and trace.get("metadata", {}).get("admitted_input_tokens", 0) + 4_096 <= 16_384
        and probes
        and any(item["request_was_in_flight"] for item in probes)
        and max_status_latency_ms is not None
        and max_status_latency_ms < 2_000
        and all(item["deployment_verified"] is True for item in probes)
    )
    record = {
        "schema_version": 1,
        "verification_kind": "live_inference_http_concurrency",
        "measurement_state": "real_bonsai_request_with_concurrent_status_probes",
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "passed": passed,
        "base_url": base_url,
        "room": args.room,
        "request": {
            "prompt_sha256": hashlib.sha256(args.prompt.encode()).hexdigest(),
            "http_status": post_status,
            "duration_ms": round(request_duration_ms, 3),
            "answer_state": reply.get("answer_state", "accepted"),
            "response_sha256": hashlib.sha256(response_text.encode()).hexdigest(),
        },
        "product_evidence": {
            "question_event_id": question_event_id,
            "answer_event_id": answer_event_id,
            "trace_id": trace_id,
            "question_signature_verified": question.get("signature_verified"),
            "answer_signature_verified": answer.get("signature_verified"),
            "trace_result_state": trace.get("metadata", {}).get("result_state") if trace else None,
            "provider_id": trace.get("metadata", {}).get("provider_id") if trace else None,
            "model": trace.get("model_name") if trace else None,
            "model_latency_ms": trace.get("total_latency_ms") if trace else None,
            "context_admission": trace.get("metadata", {}).get("context_admission") if trace else None,
            "admitted_input_tokens": trace.get("metadata", {}).get("admitted_input_tokens") if trace else None,
            "runtime_input_tokens": trace.get("metadata", {}).get("runtime_input_tokens") if trace else None,
            "runtime_completion_tokens": trace.get("metadata", {}).get("runtime_completion_tokens") if trace else None,
            "context_runtime_margin_tokens": trace.get("metadata", {}).get("context_runtime_margin_tokens") if trace else None,
            "reserved_output_tokens": trace.get("metadata", {}).get("reserved_output_tokens") if trace else None,
            "fitted_context_tokens": trace.get("metadata", {}).get("fitted_context_tokens") if trace else None,
        },
        "responsiveness": {
            "probe_count": len(probes),
            "in_flight_probe_count": sum(item["request_was_in_flight"] for item in probes),
            "max_status_latency_ms": max_status_latency_ms,
            "threshold_ms": 2_000,
            "probes": probes,
        },
        "deployment_record_sha256": deployment.get("record_sha256"),
        "limitations": [
            "This proves status responsiveness during one real local inference request, not a load or soak test.",
            "The accepted answer passed a structural publication guard and remains unverified for domain accuracy.",
            "Signed-event booleans come from the independently signature-checking Buzz bridge; raw-event checks are covered by separate evidence.",
            "The 2,000 ms status threshold is a prototype responsiveness guard, not a production service-level objective.",
            "The loaded-model tokenizer count includes an explicit 32-token runtime-wrapper margin because Bionic's reported input can differ from the direct llama.cpp template count.",
        ],
    }
    output = Path(args.output)
    if not output.is_absolute():
        output = ROOT / output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "output": str(output), "passed": passed,
        "request_duration_ms": record["request"]["duration_ms"],
        "probe_count": len(probes), "max_status_latency_ms": max_status_latency_ms,
        "trace_id": trace_id,
    }, indent=2))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
