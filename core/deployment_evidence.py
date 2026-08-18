"""Measure and validate the exact local model deployment without trusting labels."""

from __future__ import annotations

import hashlib
import json
import re
import shlex
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


SCHEMA_VERSION = 1
SANITIZED_VALUE_FLAGS = {
    "--host": "bind_host",
    "--port": "bind_port",
    "--fit-ctx": "fitted_context_length",
    "--parallel": "parallel_slots",
    "--cache-type-k": "key_cache_type",
    "--cache-type-v": "value_cache_type",
    "--flash-attn": "flash_attention",
    "--load-mode": "load_mode",
}


def sha256_file(path: Path, chunk_size: int = 8 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def parse_llama_processes(process_table: str, model_path: Path) -> list[dict[str, Any]]:
    """Return allowlisted runtime facts; never retain unknown flags or their values."""
    matches: list[dict[str, Any]] = []
    expected = str(model_path.resolve())
    for raw_line in process_table.splitlines():
        raw_line = raw_line.strip()
        if not raw_line:
            continue
        pid_text, separator, command = raw_line.partition(" ")
        if not separator or not pid_text.isdigit():
            continue
        try:
            tokens = shlex.split(command)
        except ValueError:
            continue
        if not tokens or Path(tokens[0]).name != "llama-server":
            continue
        try:
            observed_model = tokens[tokens.index("--model") + 1]
        except (ValueError, IndexError):
            continue
        if str(Path(observed_model).resolve()) != expected:
            continue
        record: dict[str, Any] = {
            "pid": int(pid_text),
            "runtime_executable": tokens[0],
        }
        version_match = re.search(r"-(\d+\.\d+\.\d+)/llama-server$", tokens[0])
        record["runtime_version"] = version_match.group(1) if version_match else None
        for flag, field in SANITIZED_VALUE_FLAGS.items():
            try:
                record[field] = tokens[tokens.index(flag) + 1]
            except (ValueError, IndexError):
                record[field] = None
        try:
            record["mmproj_path"] = tokens[tokens.index("--mmproj") + 1]
        except (ValueError, IndexError):
            record["mmproj_path"] = None
        matches.append(record)
    return matches


def verify_active_deployment_process(
    record: dict[str, Any], *, model_root: Path, process_table: str,
) -> dict[str, Any]:
    """Compare the current llama-server process with the saved allowlisted runtime facts."""
    models = model_root.resolve()
    artifacts = record.get("artifacts", [])
    weights = next(
        (
            item for item in artifacts
            if isinstance(item, dict) and item.get("role") == "model_weights"
        ),
        None,
    )
    projection = next(
        (
            item for item in artifacts
            if isinstance(item, dict) and item.get("role") == "vision_projection"
        ),
        None,
    )
    errors: list[str] = []
    logical_path = weights.get("logical_path") if isinstance(weights, dict) else None
    if not isinstance(logical_path, str):
        errors.append("deployment record has no model weights path")
        model_path = models / "missing"
    else:
        model_path = (models / logical_path).resolve()
        if not model_path.is_relative_to(models):
            errors.append("deployment model path escapes the model root")

    processes = parse_llama_processes(process_table, model_path)
    if len(processes) != 1:
        errors.append(
            f"expected one active llama-server for the measured weights, found {len(processes)}"
        )
        return {
            "verified": False,
            "process_count": len(processes),
            "runtime_version": None,
            "executable_bundle": None,
            "effective_config": {},
            "errors": errors,
        }

    process = processes[0]
    runtime = record.get("runtime", {})
    expected_config = runtime.get("effective_config", {})
    observed_config = {
        field: process.get(field)
        for field in SANITIZED_VALUE_FLAGS.values()
    }
    if process.get("runtime_version") != runtime.get("version"):
        errors.append("active llama-server version differs from the measured runtime")
    executable_bundle = Path(str(process.get("runtime_executable", ""))).parent.name
    if executable_bundle != runtime.get("executable_bundle"):
        errors.append("active llama-server executable bundle differs from the measured runtime")
    for field in SANITIZED_VALUE_FLAGS.values():
        if observed_config.get(field) != expected_config.get(field):
            errors.append(f"active llama-server {field} differs from the measured runtime")

    expected_projection = (
        (models / str(projection.get("logical_path"))).resolve()
        if isinstance(projection, dict) and isinstance(projection.get("logical_path"), str)
        else None
    )
    observed_projection = process.get("mmproj_path")
    if (
        expected_projection is None
        or not expected_projection.is_relative_to(models)
        or not isinstance(observed_projection, str)
        or Path(observed_projection).resolve() != expected_projection
    ):
        errors.append("active llama-server projection artifact differs from the measured runtime")

    return {
        "verified": not errors,
        "process_count": 1,
        "runtime_version": process.get("runtime_version"),
        "executable_bundle": executable_bundle,
        "effective_config": observed_config,
        "errors": errors,
    }


def _run_json(command: list[str], runner: Callable[..., subprocess.CompletedProcess[str]]) -> Any:
    completed = runner(command, capture_output=True, text=True, timeout=30, check=False)
    if completed.returncode:
        raise RuntimeError((completed.stderr or completed.stdout).strip() or "command failed")
    return json.loads(completed.stdout)


def _hardware(runner: Callable[..., subprocess.CompletedProcess[str]]) -> dict[str, str | None]:
    payload = _run_json(["system_profiler", "SPHardwareDataType", "-json"], runner)
    items = payload.get("SPHardwareDataType", []) if isinstance(payload, dict) else []
    item = items[0] if items and isinstance(items[0], dict) else {}
    return {
        "machine_model": item.get("machine_model"),
        "chip_type": item.get("chip_type"),
        "physical_memory": item.get("physical_memory"),
    }


def record_local_deployment(
    model: str,
    *,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    model_root: Path | None = None,
) -> dict[str, Any]:
    lms = shutil.which("lms")
    if not lms:
        raise RuntimeError("lms command not found")
    inventory = _run_json([lms, "ps", "--json"], runner)
    candidates = [
        item for item in inventory
        if isinstance(item, dict) and item.get("identifier") == model
    ] if isinstance(inventory, list) else []
    if len(candidates) != 1:
        raise RuntimeError(f"expected one loaded LM Studio instance for {model!r}, found {len(candidates)}")
    selected = candidates[0]
    if selected.get("type") != "llm" or selected.get("format") != "gguf":
        raise RuntimeError("loaded instance is not a GGUF language model")

    models = (model_root or (Path.home() / ".lmstudio" / "models")).resolve()
    logical_path = selected.get("path")
    if not isinstance(logical_path, str) or not logical_path:
        raise RuntimeError("LM Studio did not report a model path")
    artifact_path = (models / logical_path).resolve()
    if not artifact_path.is_relative_to(models) or not artifact_path.is_file():
        raise RuntimeError("reported model path is missing or outside the LM Studio model root")

    process_result = runner(
        ["ps", "-axo", "pid=,command="], capture_output=True, text=True,
        timeout=15, check=False,
    )
    if process_result.returncode:
        raise RuntimeError("could not inspect the local process table")
    processes = parse_llama_processes(process_result.stdout, artifact_path)
    if len(processes) != 1:
        raise RuntimeError(f"expected one backing llama-server process, found {len(processes)}")
    process = processes[0]

    artifacts = [{
        "role": "model_weights",
        "logical_path": logical_path,
        "size_bytes": artifact_path.stat().st_size,
        "sha256": sha256_file(artifact_path),
    }]
    mmproj_path_text = process.pop("mmproj_path")
    if mmproj_path_text:
        mmproj_path = Path(mmproj_path_text).resolve()
        if not mmproj_path.is_relative_to(models) or not mmproj_path.is_file():
            raise RuntimeError("backing process uses a missing or out-of-root projection artifact")
        artifacts.append({
            "role": "vision_projection",
            "logical_path": str(mmproj_path.relative_to(models)),
            "size_bytes": mmproj_path.stat().st_size,
            "sha256": sha256_file(mmproj_path),
        })

    executable = Path(str(process.pop("runtime_executable")))
    process.pop("pid", None)
    report = {
        "schema_version": SCHEMA_VERSION,
        "verification_kind": "measured_local_model_deployment",
        "measurement_state": "current_host_artifacts_and_process_measured",
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "passed": True,
        "model": {
            "identifier": selected.get("identifier"),
            "display_name": selected.get("displayName"),
            "publisher": selected.get("publisher"),
            "architecture": selected.get("architecture"),
            "quantization": selected.get("quantization"),
            "catalog_size_bytes": selected.get("sizeBytes"),
            "actual_artifact_size_bytes": artifacts[0]["size_bytes"],
            "catalog_size_matches_artifact": selected.get("sizeBytes") == artifacts[0]["size_bytes"],
        },
        "artifacts": artifacts,
        "runtime": {
            "name": "LM Studio llama.cpp",
            "version": process.pop("runtime_version"),
            "executable_bundle": executable.parent.name,
            "effective_config": process,
        },
        "hardware": _hardware(runner),
        "limitations": [
            "This identifies the artifacts and active backend on one host at one time; it is not clean-machine reproduction.",
            "The LM Studio catalog byte count differs from the filesystem byte count and is recorded rather than normalized away.",
            "The process command is reduced to an allowlist; API keys and unknown arguments are not stored.",
            "Artifact identity and runtime configuration do not prove model quality, power use, VRAM use, or network isolation.",
        ],
    }
    return report


def validate_deployment_record(
    record: dict[str, Any], *, model_root: Path | None = None, verify_files: bool = False,
) -> list[str]:
    errors: list[str] = []
    if record.get("schema_version") != SCHEMA_VERSION:
        errors.append("unexpected deployment evidence schema")
    if record.get("verification_kind") != "measured_local_model_deployment":
        errors.append("unexpected deployment verification kind")
    if record.get("measurement_state") != "current_host_artifacts_and_process_measured":
        errors.append("deployment measurement state is not current-host measured")
    if record.get("passed") is not True:
        errors.append("deployment record does not pass")
    model = record.get("model", {})
    if model.get("identifier") != "27b@q1_0":
        errors.append("deployment record does not identify the required Bonsai model")
    quantization = model.get("quantization", {})
    if quantization.get("name") != "Q1_0" or quantization.get("bits") != 1:
        errors.append("deployment record has unexpected quantization metadata")
    artifacts = record.get("artifacts", [])
    roles = {item.get("role") for item in artifacts if isinstance(item, dict)}
    if roles != {"model_weights", "vision_projection"}:
        errors.append("deployment record lacks the exact model artifact set")
    for item in artifacts if isinstance(artifacts, list) else []:
        if not re.fullmatch(r"[0-9a-f]{64}", str(item.get("sha256", ""))):
            errors.append(f"deployment artifact has invalid SHA-256: {item.get('role')}")
        if not isinstance(item.get("size_bytes"), int) or item["size_bytes"] <= 0:
            errors.append(f"deployment artifact has invalid size: {item.get('role')}")
        if verify_files:
            models = (model_root or (Path.home() / ".lmstudio" / "models")).resolve()
            logical_path = item.get("logical_path")
            candidate = (models / logical_path).resolve() if isinstance(logical_path, str) else None
            if candidate is None or not candidate.is_relative_to(models) or not candidate.is_file():
                errors.append(f"deployment artifact is missing or outside the model root: {item.get('role')}")
            elif candidate.stat().st_size != item.get("size_bytes"):
                errors.append(f"deployment artifact size differs from the file: {item.get('role')}")
            elif sha256_file(candidate) != item.get("sha256"):
                errors.append(f"deployment artifact SHA-256 differs from the file: {item.get('role')}")
    runtime = record.get("runtime", {})
    if not re.fullmatch(r"\d+\.\d+\.\d+", str(runtime.get("version", ""))):
        errors.append("deployment runtime version is missing")
    config = runtime.get("effective_config", {})
    if config.get("fitted_context_length") != "16384" or config.get("parallel_slots") != "4":
        errors.append("deployment effective fitted context or parallel slots differ from the measured target")
    if config.get("bind_host") != "127.0.0.1":
        errors.append("deployment runtime is not bound to the required loopback host")
    if not re.fullmatch(r"\d{1,5}", str(config.get("bind_port", ""))):
        errors.append("deployment runtime bind port is missing or invalid")
    elif not 1 <= int(config["bind_port"]) <= 65535:
        errors.append("deployment runtime bind port is outside the valid range")
    hardware = record.get("hardware", {})
    if not all(hardware.get(field) for field in ("machine_model", "chip_type", "physical_memory")):
        errors.append("deployment hardware identity is incomplete")
    serialized = json.dumps(record).lower()
    if "api-key" in serialized or "apikey" in serialized:
        errors.append("deployment record contains an API-key field")
    limitation_text = " ".join(str(item).lower() for item in record.get("limitations", []))
    for phrase in ("not clean-machine", "do not prove model quality", "not stored"):
        if phrase not in limitation_text:
            errors.append(f"deployment record lacks limitation: {phrase}")
    return errors
