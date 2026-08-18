#!/usr/bin/env python3
"""Restart Bionic and record a source-bound Bonsai verification run."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


PROJECT_ROOT = Path(__file__).resolve().parent.parent
BIONIC_EXECUTABLE = "/Applications/Bionic.app/Contents/MacOS/Bionic"
MODEL_IDENTIFIER = "27b@q1_0"
MODEL_ARTIFACT = Path(
    "/Users/jaibhagat/.lmstudio/models/lmstudio-community/27B/Bonsai-27B-Q1_0.gguf"
)
LMS = Path("/Users/jaibhagat/.lmstudio/bin/lms")
API_ENDPOINT = "http://127.0.0.1:1234"
COLD_BROWSER_RECORD = PROJECT_ROOT / "evidence" / "browser-first-pass-cold-restart.json"
COLD_BROWSER_SCREENSHOT = PROJECT_ROOT / "evidence" / "browser-first-pass-cold-restart.png"
CURRENT_BROWSER_RECORD = PROJECT_ROOT / "evidence" / "browser-first-pass-v7.json"
CURRENT_BROWSER_SCREENSHOT = PROJECT_ROOT / "evidence" / "browser-first-pass-v7.png"


def _dependent_commands() -> list[list[str]]:
    """Return commands whose outputs are bound to one cold restart record."""
    return [
        [sys.executable, "scripts/record_local_deployment.py"],
        [sys.executable, "scripts/record_live_inference_concurrency.py"],
        [sys.executable, "scripts/record_network_observation.py"],
        ["node", "scripts/verify_browser_surface.mjs"],
    ]


def _snapshot_browser_evidence() -> None:
    """Copy the refreshed browser record into paths owned by this restart record."""
    shutil.copyfile(CURRENT_BROWSER_RECORD, COLD_BROWSER_RECORD)
    shutil.copyfile(CURRENT_BROWSER_SCREENSHOT, COLD_BROWSER_SCREENSHOT)


def _run(command: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=PROJECT_ROOT,
        check=check,
        capture_output=True,
        text=True,
    )


def _wait_for(predicate: Callable[[], bool], description: str, timeout: float = 45.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.25)
    raise RuntimeError(f"timed out waiting for {description}")


def _port_open() -> bool:
    try:
        with socket.create_connection(("127.0.0.1", 1234), timeout=0.3):
            return True
    except OSError:
        return False


def _process_rows() -> list[dict[str, Any]]:
    completed = _run(["ps", "-axo", "pid=,lstart=,command="])
    rows = []
    pattern = re.compile(
        r"^\s*(\d+)\s+([A-Z][a-z]{2}\s+[A-Z][a-z]{2}\s+\d+\s+\d\d:\d\d:\d\d\s+\d{4})\s+(.*)$"
    )
    for line in completed.stdout.splitlines():
        match = pattern.match(line)
        if not match:
            continue
        rows.append({
            "pid": int(match.group(1)),
            "started": match.group(2),
            "command": match.group(3),
        })
    return rows


def _bionic_process() -> dict[str, Any] | None:
    matches = [row for row in _process_rows() if row["command"] == BIONIC_EXECUTABLE]
    if len(matches) > 1:
        raise RuntimeError("more than one Bionic application process is running")
    return matches[0] if matches else None


def _model_process() -> dict[str, Any] | None:
    artifact = str(MODEL_ARTIFACT)
    matches = [
        row for row in _process_rows()
        if "llama-server" in row["command"] and f"--model {artifact}" in row["command"]
    ]
    if len(matches) > 1:
        raise RuntimeError("more than one Bonsai 27B llama-server process is running")
    return matches[0] if matches else None


def _started_at(value: str) -> str:
    parsed = datetime.strptime(value, "%a %b %d %H:%M:%S %Y")
    return parsed.astimezone().isoformat()


def _models() -> dict[str, Any]:
    with urllib.request.urlopen(f"{API_ENDPOINT}/api/v1/models", timeout=3) as response:
        return json.loads(response.read().decode("utf-8"))


def _loaded_model() -> dict[str, Any] | None:
    for model in _models().get("models", []):
        if model.get("key") == MODEL_IDENTIFIER and model.get("loaded_instances"):
            return model
    return None


def _flag_value(command: str, flag: str) -> str | None:
    match = re.search(rf"(?:^|\s){re.escape(flag)}\s+(\S+)", command)
    return match.group(1) if match else None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--record",
        default="evidence/bonsai-cold-restart.json",
        help="Cold restart record path.",
    )
    parser.add_argument(
        "--verification-artifact",
        default="evidence/bonsai-local-product-verification-cold-restart.json",
        help="Post-restart product verification path.",
    )
    args = parser.parse_args()

    if not LMS.is_file() or not MODEL_ARTIFACT.is_file():
        raise RuntimeError("the pinned lms CLI or Bonsai artifact is missing")
    before_app = _bionic_process()
    before_model = _loaded_model() if _port_open() else None
    if before_app is None or before_model is None:
        raise RuntimeError("Bionic and the exact Bonsai model must be live before restart")

    before_pid = before_app["pid"]
    before = {
        "application": "Bionic",
        "pid": before_pid,
        "process_started_at": _started_at(before_app["started"]),
        "api_endpoint": API_ENDPOINT,
        "model_identifier": MODEL_IDENTIFIER,
        "api_advertised_context_length": before_model.get("max_context_length"),
        "parallel_slots": before_model["loaded_instances"][0]["config"].get("parallel"),
    }

    _run(["osascript", "-e", 'tell application "Bionic" to quit'])
    _wait_for(lambda: not any(row["pid"] == before_pid for row in _process_rows()), "old Bionic PID to exit")
    _wait_for(lambda: not _port_open(), "loopback model port to close")

    _run(["open", "-a", "/Applications/Bionic.app"])
    _wait_for(lambda: (_bionic_process() or {}).get("pid") not in {None, before_pid}, "new Bionic PID")
    _run([str(LMS), "server", "start", "--port", "1234", "--bind", "127.0.0.1"])
    _wait_for(_port_open, "LM Studio API port")
    _run([str(LMS), "unload", MODEL_IDENTIFIER], check=False)
    _run([
        str(LMS), "load", MODEL_IDENTIFIER,
        "--context-length", "16384",
        "--parallel", "4",
        "--identifier", MODEL_IDENTIFIER,
        "--yes",
    ])
    _wait_for(lambda: _loaded_model() is not None, "exact Bonsai model instance", timeout=90.0)
    _wait_for(lambda: _model_process() is not None, "Bonsai llama-server process", timeout=90.0)

    after_app = _bionic_process()
    after_model_process = _model_process()
    loaded = _loaded_model()
    if after_app is None or after_model_process is None or loaded is None:
        raise RuntimeError("post-restart Bionic or model identity is unavailable")
    model_command = after_model_process["command"]
    runtime_match = re.search(r"apple-metal-advsimd-([^/]+)/llama-server", model_command)
    runtime_version = runtime_match.group(1) if runtime_match else "unknown"
    context_requested = int(_flag_value(model_command, "--fit-ctx") or 0)
    parallel_slots = int(_flag_value(model_command, "--parallel") or 0)
    artifact_sha256 = hashlib.sha256(MODEL_ARTIFACT.read_bytes()).hexdigest()
    hardware = "Mac17,8; Apple M5 Pro; 48 GB"

    verification_path = (PROJECT_ROOT / args.verification_artifact).resolve()
    environment = os.environ.copy()
    environment.update({
        "PRISM_LOCAL_AI_URL": API_ENDPOINT,
        "PRISM_LOCAL_AI_MODEL": MODEL_IDENTIFIER,
        "PRISM_LOCAL_AI_PROTOCOL": "lmstudio-native",
        "PRISM_LOCAL_AI_KEY": "lm-studio",
        "PRISM_LOCAL_AI_PROMPT_SUFFIX": "/no_think",
        "PRISM_LOCAL_AI_ARTIFACT_SHA256": artifact_sha256,
        "PRISM_LOCAL_AI_RUNTIME": "LM Studio llama.cpp",
        "PRISM_LOCAL_AI_RUNTIME_VERSION": runtime_version,
        "PRISM_LOCAL_AI_HARDWARE": hardware,
        "PRISM_LOCAL_AI_TIMEOUT_SECONDS": "300",
        "PRISM_LOCAL_AI_MAX_TOKENS": "4096",
        "PRISM_LOCAL_AI_CONTEXT_TOKENS": str(context_requested),
        "PRISM_LOCAL_AI_ARTIFACT_PATH": str(MODEL_ARTIFACT),
    })

    # A Bionic restart assigns a new internal llama-server port. Refresh every
    # artifact that is intentionally bound to the measured deployment before
    # running the product verifier.
    for command in _dependent_commands():
        dependent = subprocess.run(
            command,
            cwd=PROJECT_ROOT,
            env=environment,
            capture_output=True,
            text=True,
        )
        if dependent.returncode != 0:
            raise RuntimeError(
                f"dependent evidence command failed: {' '.join(command)}\n"
                + dependent.stderr[-4000:]
            )
    _snapshot_browser_evidence()

    completed = subprocess.run(
        [sys.executable, "scripts/verify_product.py", "--runtime", "local",
         "--cold-restart-candidate",
         "--output", str(verification_path)],
        cwd=PROJECT_ROOT,
        env=environment,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            "post-restart verification failed\n" + completed.stderr[-4000:]
        )
    verification = json.loads(verification_path.read_text(encoding="utf-8"))
    verification_sha256 = hashlib.sha256(verification_path.read_bytes()).hexdigest()
    dependent_paths = {
        "local_deployment": PROJECT_ROOT / "evidence" / "local-deployment-current.json",
        "live_inference_concurrency": PROJECT_ROOT / "evidence" / "live-inference-concurrency-v1.json",
        "process_network_observation": PROJECT_ROOT / "evidence" / "process-network-observation-v1.json",
        "browser_surface": COLD_BROWSER_RECORD,
    }

    record_path = (PROJECT_ROOT / args.record).resolve()
    record = {
        "schema_version": 2,
        "measurement_state": "cold_restart_reproduced",
        "observed_at": datetime.now(timezone.utc).astimezone().isoformat(),
        "before": before,
        "stop_observation": {
            "graceful_quit_requested": True,
            "old_pid_exited": True,
            "loopback_port_1234_closed": True,
        },
        "restart_commands": [
            "open -a /Applications/Bionic.app",
            "$HOME/.lmstudio/bin/lms server start --port 1234 --bind 127.0.0.1",
            "$HOME/.lmstudio/bin/lms unload 27b@q1_0",
            "$HOME/.lmstudio/bin/lms load 27b@q1_0 --context-length 16384 --parallel 4 --identifier 27b@q1_0 --yes",
        ],
        "after": {
            "application": "Bionic",
            "pid": after_app["pid"],
            "process_started_at": _started_at(after_app["started"]),
            "api_endpoint": API_ENDPOINT,
            "model_process_pid": after_model_process["pid"],
            "model_process_started_at": _started_at(after_model_process["started"]),
            "model_identifier": MODEL_IDENTIFIER,
            "model_artifact": str(MODEL_ARTIFACT),
            "artifact_sha256": artifact_sha256,
            "runtime_name": "LM Studio llama.cpp",
            "runtime_version": runtime_version,
            "hardware": hardware,
            "context_length_requested": context_requested,
            "backend_fit_context_length": context_requested,
            "api_advertised_context_length": loaded.get("max_context_length"),
            "request_context_admission": "loaded_model_tokenizer_with_runtime_margin",
            "request_context_runtime_margin_tokens": 32,
            "request_reserved_output_tokens": 4096,
            "parallel_slots": parallel_slots,
        },
        "verification_artifact": str(verification_path.relative_to(PROJECT_ROOT)),
        "verification_artifact_sha256": verification_sha256,
        "benchmark_dataset_sha256": verification["benchmark"]["dataset_sha256"],
        "dependent_evidence": {
            name: {
                "path": str(path.relative_to(PROJECT_ROOT)),
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
            for name, path in dependent_paths.items()
        },
        "limitations": [
            "This proves one source-bound restart and repeat run on the recorded workstation, not clean-machine portability.",
            "The API advertises a 262,144 token model maximum. Prism admits requests against the 16,384 token fitted context with a 32 token runtime margin and a 4,096 token output reserve. This run does not prove a 262,144 token workload.",
            "No VRAM, power, energy, egress, or hardened-isolation claim was measured.",
            "The four benchmark cases are synthetic engineering regressions without deal-domain approval.",
            "Filename attribution coverage is not semantic grounding.",
        ],
    }
    record_path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "record": str(record_path),
        "before_pid": before_pid,
        "after_pid": after_app["pid"],
        "model_process_pid": after_model_process["pid"],
        "verification_artifact": str(verification_path),
        "verification_artifact_sha256": verification_sha256,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
