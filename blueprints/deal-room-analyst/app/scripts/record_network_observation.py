#!/usr/bin/env python3
"""Sample sockets for the exact local Prism, Bionic, and Bonsai processes.

This is deliberately process-scoped sampling. It does not capture packets,
cover Docker guest traffic, prove an air gap, or prove zero egress.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.network_observation import parse_lsof_fields, validate_network_observation


BIONIC_EXECUTABLE = "/Applications/Bionic.app/Contents/MacOS/Bionic"
MODEL_IDENTIFIER = "27b@q1_0"
MODEL_ARTIFACT = Path(
    "/Users/jaibhagat/.lmstudio/models/lmstudio-community/27B/Bonsai-27B-Q1_0.gguf"
)
MODEL_URL = "http://127.0.0.1:1234"
PRISM_URL = "http://127.0.0.1:8787"


def sanitized_process(row: dict[str, Any]) -> dict[str, Any]:
    command = re.sub(r"(?<=--api-key )\S+", "[REDACTED]", row["command"])
    return {**row, "command": command}


def atomic_write(path: Path, value: dict[str, Any]) -> None:
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


def process_rows() -> list[dict[str, Any]]:
    completed = subprocess.run(
        ["ps", "-axo", "pid=,ppid=,command="], check=True, capture_output=True, text=True
    )
    rows: list[dict[str, Any]] = []
    for line in completed.stdout.splitlines():
        match = re.match(r"^\s*(\d+)\s+(\d+)\s+(.*)$", line)
        if match:
            rows.append({
                "pid": int(match.group(1)),
                "ppid": int(match.group(2)),
                "command": match.group(3),
            })
    return rows


def one_process(rows: list[dict[str, Any]], predicate, label: str) -> dict[str, Any]:
    matches = [row for row in rows if predicate(row)]
    if len(matches) != 1:
        raise RuntimeError(f"expected exactly one {label} process, found {len(matches)}")
    return matches[0]


def listener_pid(port: int) -> int:
    completed = subprocess.run(
        ["/usr/sbin/lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-t"],
        check=True,
        capture_output=True,
        text=True,
    )
    pids = {int(value) for value in completed.stdout.split() if value.isdigit()}
    if len(pids) != 1:
        raise RuntimeError(f"expected exactly one TCP listener on port {port}, found {sorted(pids)}")
    return next(iter(pids))


def descendants(rows: list[dict[str, Any]], roots: set[int]) -> set[int]:
    selected = set(roots)
    changed = True
    while changed:
        changed = False
        for row in rows:
            if row["ppid"] in selected and row["pid"] not in selected:
                selected.add(row["pid"])
                changed = True
    return selected


def socket_sample(root_pids: set[int]) -> dict[str, Any]:
    rows = process_rows()
    pids = sorted(descendants(rows, root_pids))
    completed = subprocess.run(
        [
            "/usr/sbin/lsof", "-nP", "-a", "-p", ",".join(map(str, pids)),
            "-iTCP", "-iUDP", "-FpcnT",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode not in {0, 1}:
        raise RuntimeError(f"lsof failed with exit code {completed.returncode}: {completed.stderr}")
    return {
        "sampled_at": datetime.now(timezone.utc).astimezone().isoformat(),
        "pids": pids,
        "lsof_output": completed.stdout,
        "lsof_stderr": completed.stderr,
        "lsof_exit_code": completed.returncode,
    }


def local_request(result: dict[str, Any]) -> None:
    prompt = "Return exactly SOCKET_OBSERVATION_OK and nothing else."
    body = {
        "model": MODEL_IDENTIFIER,
        "input": prompt,
        "system_prompt": "Follow the user instruction exactly.",
        "reasoning": "off",
        "temperature": 0,
        "max_output_tokens": 32,
        "store": False,
    }
    request = urllib.request.Request(
        f"{MODEL_URL}/api/v1/chat",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            raw = response.read(1024 * 1024)
            result["http_status"] = response.status
        parsed = json.loads(raw.decode("utf-8"))
        content = "\n".join(
            item.get("content", "") for item in parsed.get("output", [])
            if isinstance(item, dict) and item.get("type") == "message"
        )
        result.update({
            "completed": True,
            "latency_ms": round((time.perf_counter() - started) * 1000, 3),
            "model_instance_id": parsed.get("model_instance_id"),
            "response_sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
            "response_matched_requested_text": content.strip() == "SOCKET_OBSERVATION_OK",
            "reasoning_output_tokens": parsed.get("stats", {}).get("reasoning_output_tokens"),
        })
    except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
        result.update({
            "completed": False,
            "http_status": getattr(exc, "code", None),
            "latency_ms": round((time.perf_counter() - started) * 1000, 3),
            "error": str(exc),
        })


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="evidence/process-network-observation-v1.json")
    parser.add_argument("--sample-interval", type=float, default=0.10)
    args = parser.parse_args()
    if args.sample_interval <= 0 or args.sample_interval > 1:
        raise RuntimeError("sample interval must be greater than zero and at most one second")

    # The API status read proves the named product surface is live before PID selection.
    with urllib.request.urlopen(f"{PRISM_URL}/api/status", timeout=5) as response:
        if response.status != 200:
            raise RuntimeError("Prism status endpoint did not return HTTP 200")
        prism_status_sha256 = hashlib.sha256(response.read()).hexdigest()

    rows = process_rows()
    prism_pid = listener_pid(8787)
    prism = one_process(rows, lambda row: row["pid"] == prism_pid, "Prism server")
    bionic = one_process(rows, lambda row: row["command"] == BIONIC_EXECUTABLE, "Bionic app")
    artifact = str(MODEL_ARTIFACT.resolve())
    llama = one_process(
        rows,
        lambda row: "llama-server" in row["command"] and f"--model {artifact}" in row["command"],
        "exact Bonsai llama-server",
    )
    if listener_pid(1234) != bionic["pid"]:
        raise RuntimeError("the Bionic app is not the unique loopback API listener")

    processes = {
        "prism_server": sanitized_process(prism),
        "bionic_app": sanitized_process(bionic),
        "bonsai_llama_server": sanitized_process(llama),
    }
    roots = {item["pid"] for item in processes.values()}
    samples = [socket_sample(roots)]
    request_result: dict[str, Any] = {}
    worker = threading.Thread(target=local_request, args=(request_result,), daemon=True)
    worker.start()
    while worker.is_alive():
        samples.append(socket_sample(roots))
        time.sleep(args.sample_interval)
    worker.join()
    samples.append(socket_sample(roots))
    while len(samples) < 3:
        samples.append(socket_sample(roots))

    observed = [
        item for sample in samples for item in parse_lsof_fields(sample["lsof_output"])
    ]
    observation = {
        "non_loopback_hosts": sorted({
            host for item in observed for host in item["non_loopback_hosts"]
        }),
        "invalid_hosts": sorted({
            host for item in observed for host in item["invalid_hosts"]
        }),
        "wildcard_hosts": sorted({
            host for item in observed for host in item["wildcard_hosts"]
        }),
    }
    record: dict[str, Any] = {
        "verification_kind": "process_socket_observation.v1",
        "recorded_at": datetime.now(timezone.utc).astimezone().isoformat(),
        "scope": "named host processes and descendants during one direct local-model request",
        "processes": processes,
        "prism_status_sha256": prism_status_sha256,
        "request": {
            "endpoint": f"{MODEL_URL}/api/v1/chat",
            "protocol": "lmstudio_native_chat",
            "model": MODEL_IDENTIFIER,
            "reasoning_requested": "off",
            **request_result,
        },
        "samples": samples,
        "observation": observation,
        "packet_capture_used": False,
        "zero_egress_proved": False,
        "air_gap_proved": False,
        "limitations": [
            "Socket snapshots can miss short-lived connections between samples.",
            "No packet bodies or DNS activity were captured.",
            "Docker guest traffic and unrelated host processes are outside this record's scope.",
            "This is not whole-host monitoring, firewall enforcement, or DLP evidence.",
            "No zero-egress, air-gap, or production network-isolation claim follows from this record.",
        ],
    }
    preliminary = validate_network_observation(record, require_pass_label=False)
    record["passed"] = preliminary["passed"]
    verification = validate_network_observation(record)
    record["verification"] = verification
    output = Path(args.output)
    if not output.is_absolute():
        output = ROOT / output
    atomic_write(output, record)
    print(json.dumps({"record": str(output), **verification}, indent=2))
    return 0 if verification["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
