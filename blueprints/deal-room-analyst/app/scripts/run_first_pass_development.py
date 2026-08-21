#!/usr/bin/env python3
"""Run full first-pass product paths on the three inspected public deal dossiers."""

from __future__ import annotations

import argparse
import hashlib
import json
import time
import urllib.error
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CASES = ROOT / "benchmarks" / "first_pass" / "development_cases.v1.json"
MANIFEST = ROOT / "benchmarks" / "first_pass" / "benchmark_manifest.v1.json"
SOURCE_MANIFEST = ROOT / "benchmarks" / "public_deal_corpus_manifest.json"
DEALS = {
    "anaplan_2022": ROOT / ".runtime" / "public-deal-corpus" / "anaplan",
    "citrix_2022": ROOT / ".runtime" / "public-deal-corpus" / "citrix",
    "microsoft_activision_2023": ROOT / ".runtime" / "public-deal-rooms" / "microsoft_activision",
}
DEAL_ROOMS = {
    "anaplan_2022": "anaplan",
    "citrix_2022": "citrix",
    "microsoft_activision_2023": "microsoft_activision",
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def post(url: str, payload: dict, timeout: int = 420) -> tuple[int, dict]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, json.load(response)
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read())


def file_state(folder: Path) -> dict[str, dict[str, object]]:
    return {
        str(path.relative_to(folder)): {
            "sha256": sha256(path),
            "bytes": path.stat().st_size,
            "mtime_ns": path.stat().st_mtime_ns,
        }
        for path in sorted(item for item in folder.rglob("*") if item.is_file())
    }


def all_deal_file_state() -> dict[str, dict[str, object]]:
    combined = {}
    for deal_id, folder in DEALS.items():
        for path, record in file_state(folder).items():
            combined[f"{deal_id}/{path}"] = record
    return combined


def investment_screens(case_contract: dict) -> dict[str, str]:
    grouped: dict[str, list[dict]] = {}
    for case in case_contract["cases"]:
        grouped.setdefault(case["deal_id"], []).append(case)
    screens = {}
    for deal_id, cases in grouped.items():
        questions = " ".join(f"{index}. {case['question']}" for index, case in enumerate(cases, 1))
        screens[deal_id] = (
            "Decide whether this transaction should advance to deeper underwriting. "
            "Produce the complete first-pass contract with explicit unknowns and exact citations. "
            "Give special attention to these preregistered development questions: " + questions
        )
    return screens


def source_scope(folder: Path, room_name: str, source_manifest: dict) -> dict:
    expected = sorted(
        item["filename"] for item in source_manifest["documents"]
        if item["room"] == room_name
    )
    observed = sorted(
        str(path.relative_to(folder)) for path in folder.rglob("*") if path.is_file()
    )
    unexpected = sorted(set(observed) - set(expected))
    missing = sorted(set(expected) - set(observed))
    return {
        "passed": bool(expected) and not unexpected and not missing,
        "expected_files": expected,
        "observed_files": observed,
        "unexpected_files": unexpected,
        "missing_files": missing,
    }


def summarize_result(status: int, payload: dict, elapsed_ms: float) -> dict:
    return {
        "http_status": status,
        "acceptance_state": payload.get("acceptance_state"),
        "artifact_mode": payload.get("artifact_mode", "model_draft"),
        "authored_by": payload.get("authored_by"),
        "model": payload.get("model"),
        "guard_version": payload.get("guard_version"),
        "trace_id": payload.get("trace_id"),
        "model_failure_trace_id": payload.get("model_failure_trace_id"),
        "draft_event_id": payload.get("draft_event_id"),
        "canonical_path": payload.get("canonical_path"),
        "citations": payload.get("citations", []),
        "markdown": payload.get("markdown"),
        "latency_ms": payload.get("latency_ms", elapsed_ms),
        "error": payload.get("detail") or payload.get("error") if status != 201 else None,
    }


def main() -> int:
    cli = argparse.ArgumentParser()
    cli.add_argument("--base-url", default="http://127.0.0.1:8787")
    cli.add_argument(
        "--output", default="evidence/bonsai-first-pass-public-development-v1.json",
    )
    args = cli.parse_args()

    contract = json.loads(CASES.read_text(encoding="utf-8"))
    source_manifest = json.loads(SOURCE_MANIFEST.read_text(encoding="utf-8"))
    screens = investment_screens(contract)
    missing = [deal_id for deal_id, folder in DEALS.items() if not folder.is_dir()]
    if missing:
        raise RuntimeError(
            "Public corpus is unavailable for " + ", ".join(missing)
            + "; run scripts/acquire_public_deal_corpus.py first"
        )

    before = all_deal_file_state()
    opened_rooms = {}
    results = {}
    source_scopes = {}
    started_at = time.time()
    for deal_id, folder in DEALS.items():
        source_scopes[deal_id] = source_scope(folder, DEAL_ROOMS[deal_id], source_manifest)
        if not source_scopes[deal_id]["passed"]:
            results[deal_id] = {
                "http_status": None,
                "acceptance_state": None,
                "error": "deal source scope is contaminated or incomplete",
                "citations": [],
            }
            continue
        preview_status, preview = post(
            f"{args.base_url}/api/deal-room/preview",
            {"folder_path": str(folder)}, timeout=60,
        )
        if preview_status != 200 or preview.get("preview_state") != "ready":
            results[deal_id] = summarize_result(preview_status, preview, 0.0)
            continue
        open_status, opened = post(
            f"{args.base_url}/api/deal-room/open",
            {"folder_path": str(folder), "preview_sha256": preview["preview_sha256"]},
            timeout=60,
        )
        if open_status != 201:
            results[deal_id] = summarize_result(open_status, opened, 0.0)
            continue
        room_id = opened["room_id"]
        opened_rooms[deal_id] = room_id
        run_started = time.time()
        run_status, payload = post(
            f"{args.base_url}/api/workspace/first-pass",
            {"room": room_id, "action": "run", "investment_screen": screens[deal_id]},
        )
        results[deal_id] = summarize_result(
            run_status, payload, (time.time() - run_started) * 1000,
        )
        print(json.dumps({
            "deal_id": deal_id,
            "http_status": run_status,
            "acceptance_state": results[deal_id]["acceptance_state"],
            "model": results[deal_id]["model"],
            "trace_id": results[deal_id]["trace_id"],
        }), flush=True)

    after = all_deal_file_state()
    changed = sorted(
        set(before) ^ set(after)
        | {path for path in before.keys() & after.keys() if before[path] != after[path]}
    )
    for result in results.values():
        result["unauthorized_source_writes"] = changed
    product_path_complete = len(results) == len(DEALS) and all(
        result["http_status"] == 201
        and result["acceptance_state"] in {"accepted", "evidence_safe_fallback"}
        and result["trace_id"]
        and result["draft_event_id"]
        and result["citations"]
        for result in results.values()
    ) and all(scope["passed"] for scope in source_scopes.values()) and not changed
    artifact = {
        "schema": "prism.first_pass.public_development.v1",
        "measurement_state": "development_product_path",
        "benchmark_manifest_sha256": sha256(MANIFEST),
        "development_cases_sha256": sha256(CASES),
        "source_manifest_sha256": sha256(SOURCE_MANIFEST),
        "run_started_at_unix": started_at,
        "run_finished_at_unix": time.time(),
        "deal_count": len(DEALS),
        "registered_question_count": len(contract["cases"]),
        "domain_approval": contract["domain_approval"],
        "product_path_complete": product_path_complete,
        "accuracy_release_passed": False,
        "human_review_performed": False,
        "limitations": [
            "These are three inspected public dossiers, not private virtual data rooms.",
            "The run tests full first-pass delivery but does not score semantic accuracy.",
            "The registered questions and model failure history were previously inspected.",
            "No domain owner reviewed the generated briefs.",
        ],
        "opened_rooms": opened_rooms,
        "source_scope": source_scopes,
        "source_state_before": before,
        "source_state_after": after,
        "unauthorized_source_writes": changed,
        "results": results,
    }
    output = (ROOT / args.output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(artifact, indent=2, sort_keys=True) + "\n")
    print(json.dumps({
        "output": str(output),
        "product_path_complete": product_path_complete,
        "accuracy_release_passed": False,
        "unauthorized_source_writes": changed,
    }, indent=2))
    return 0 if product_path_complete else 1


if __name__ == "__main__":
    raise SystemExit(main())
