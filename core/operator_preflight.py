"""Reality-based host and live-service checks for the local Prism surface."""

from __future__ import annotations

import json
import ipaddress
import os
import shutil
import stat
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from core.macos_ocr import ocr_toolchain_status


@dataclass(frozen=True)
class PreflightCheck:
    name: str
    required: bool
    passed: bool
    state: str
    observed: Any
    remediation: str | None = None


def evaluate_model_inventory(payload: dict[str, Any], model: str) -> dict[str, Any]:
    """Distinguish catalog presence from an actually loaded model instance."""
    models = payload.get("models", [])
    if not isinstance(models, list):
        return {"catalog_present": False, "loaded": False, "reasoning_off_supported": False}
    candidate = next(
        (item for item in models if isinstance(item, dict) and item.get("key") == model),
        None,
    )
    if candidate is None:
        return {"catalog_present": False, "loaded": False, "reasoning_off_supported": False}
    instances = candidate.get("loaded_instances", [])
    loaded = isinstance(instances, list) and any(
        isinstance(item, dict) and item.get("id") == model for item in instances
    )
    instance_ids = [
        item.get("id") for item in instances
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    ] if isinstance(instances, list) else []
    declared_contexts = [
        item.get("config", {}).get("context_length") for item in instances
        if isinstance(item, dict) and isinstance(item.get("config"), dict)
        and isinstance(item.get("config", {}).get("context_length"), int)
    ] if isinstance(instances, list) else []
    reasoning = candidate.get("capabilities", {}).get("reasoning", {})
    allowed = reasoning.get("allowed_options", []) if isinstance(reasoning, dict) else []
    return {
        "catalog_present": True,
        "loaded": loaded,
        "reasoning_off_supported": isinstance(allowed, list) and "off" in allowed,
        "display_name": candidate.get("display_name"),
        "api_advertised_max_context_length": candidate.get("max_context_length"),
        "api_declared_loaded_context_lengths": declared_contexts,
        "loaded_instance_ids": instance_ids,
    }


def required_checks_pass(checks: list[PreflightCheck]) -> bool:
    return all(check.passed for check in checks if check.required)


def _command(name: str, *args: str) -> tuple[bool, str]:
    executable = shutil.which(name)
    if not executable:
        return False, "command not found"
    try:
        completed = subprocess.run(
            [executable, *args], capture_output=True, text=True, timeout=15, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, str(exc)
    output = (completed.stdout or completed.stderr).strip()
    return completed.returncode == 0, output[-1000:]


def _json_get(url: str, timeout: float = 3.0) -> tuple[bool, Any]:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            body = response.read(2 * 1024 * 1024 + 1)
            if response.status != 200 or len(body) > 2 * 1024 * 1024:
                return False, f"HTTP {response.status} or oversized response"
            return True, json.loads(body.decode("utf-8"))
    except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
        return False, str(exc)


def _status_get(url: str, timeout: float = 3.0) -> tuple[bool, Any]:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            body = response.read(4097)
            return response.status == 200 and len(body) <= 4096, {
                "http_status": response.status,
                "body": body[:256].decode("utf-8", errors="replace"),
            }
    except (OSError, urllib.error.URLError) as exc:
        return False, str(exc)


def _safe_loopback_origin(origin: str) -> bool:
    try:
        parsed = urllib.parse.urlsplit(origin)
        address = ipaddress.ip_address(parsed.hostname) if parsed.hostname else None
        _ = parsed.port
    except (ValueError, TypeError):
        return False
    return bool(
        parsed.scheme == "http"
        and address is not None
        and (
            (address.version == 4 and address.is_loopback)
            or address == ipaddress.IPv6Address("::1")
        )
        and parsed.username is None
        and parsed.password is None
        and not parsed.query
        and not parsed.fragment
    )


def collect_preflight(
    root: Path,
    *,
    phase: str,
    model_url: str,
    model: str,
    buzz_url: str,
) -> dict[str, Any]:
    if phase not in {"host", "live"}:
        raise ValueError("phase must be host or live")
    checks: list[PreflightCheck] = []
    checks.append(PreflightCheck(
        "python_version", True, sys.version_info >= (3, 11),
        "ready" if sys.version_info >= (3, 11) else "unsupported",
        ".".join(map(str, sys.version_info[:3])), "Install Python 3.11 or newer.",
    ))
    required_files = [
        root / "server.py", root / "infra" / "buzz" / "compose.yml",
        root / "scripts" / "buzz_up.py", root / "scripts" / "buzz_agent.py",
    ]
    missing_files = [str(path.relative_to(root)) for path in required_files if not path.is_file()]
    checks.append(PreflightCheck(
        "project_files", True, not missing_files,
        "ready" if not missing_files else "missing", missing_files,
        "Run from a complete Prism checkout.",
    ))
    ocr_status = ocr_toolchain_status()
    checks.append(PreflightCheck(
        "pdf_ocr_toolchain", True, bool(ocr_status["available"]),
        "ready" if ocr_status["available"] else "unavailable",
        ocr_status,
        "Run the measured prototype on macOS with Swift and Poppler pdftoppm installed.",
    ))
    sandbox_exec = shutil.which("sandbox-exec", path="/usr/bin:/bin")
    sandbox_exec_ok = True
    sandbox_exec_observed: Any = "not_applicable_on_this_platform"
    if sys.platform == "darwin":
        sandbox_exec_ok, probe_output = _command(
            "sandbox-exec", "-p", "(version 1) (allow default)", "/usr/bin/true",
        )
        sandbox_exec_observed = {
            "path": sandbox_exec,
            "profile_probe_passed": sandbox_exec_ok,
            "probe_output": probe_output,
        }
    checks.append(PreflightCheck(
        "macos_sandbox_profile", True, sandbox_exec_ok,
        "ready" if sandbox_exec_ok and sys.platform == "darwin" else (
            "not_applicable" if sys.platform != "darwin" else "unavailable"
        ),
        sandbox_exec_observed,
        "Run the measured macOS prototype on a host with working /usr/bin/sandbox-exec.",
    ))
    docker_cli = shutil.which("docker")
    checks.append(PreflightCheck(
        "docker_cli", True, bool(docker_cli), "ready" if docker_cli else "missing",
        docker_cli, "Install Docker Desktop or another Docker Engine with Compose.",
    ))
    daemon_ok, daemon_version = _command("docker", "version", "--format", "{{.Server.Version}}")
    checks.append(PreflightCheck(
        "docker_daemon", True, daemon_ok, "ready" if daemon_ok else "unavailable",
        daemon_version, "Start the Docker daemon and confirm the current user can access it.",
    ))
    compose_ok, compose_version = _command("docker", "compose", "version")
    checks.append(PreflightCheck(
        "docker_compose", True, compose_ok, "ready" if compose_ok else "unavailable",
        compose_version, "Install the Docker Compose plugin.",
    ))

    bin_dir = root / ".runtime" / "buzz" / "bin"
    binary_names = ("buzz", "buzz-agent", "buzz-acp", "buzz-dev-mcp")
    missing_binaries = [
        name for name in binary_names
        if not (bin_dir / name).is_file() or not os.access(bin_dir / name, os.X_OK)
    ]
    install_prereqs = all(shutil.which(name) for name in ("git", "bash"))
    binaries_required = phase == "live"
    binaries_ready = not missing_binaries
    checks.append(PreflightCheck(
        "buzz_binaries", binaries_required,
        binaries_ready if binaries_required else (binaries_ready or install_prereqs),
        "installed" if binaries_ready else "installation_required",
        {"missing": missing_binaries, "installer_prerequisites_present": install_prereqs},
        "Run python3 scripts/buzz_install_tools.py with network access on the first setup.",
    ))

    model_origin_ok = _safe_loopback_origin(model_url)
    checks.append(PreflightCheck(
        "model_endpoint_loopback", True, model_origin_ok,
        "ready" if model_origin_ok else "unsafe_or_invalid",
        model_url, "Use an HTTP loopback IP URL such as http://127.0.0.1:1234.",
    ))
    inventory_ok, inventory_payload = _json_get(f"{model_url.rstrip('/')}/api/v1/models")
    inventory = evaluate_model_inventory(inventory_payload, model) if inventory_ok else {
        "catalog_present": False, "loaded": False, "reasoning_off_supported": False,
    }
    checks.append(PreflightCheck(
        "bonsai_model_loaded", True, inventory_ok and inventory["loaded"],
        "loaded" if inventory_ok and inventory["loaded"] else (
            "catalog_only" if inventory_ok and inventory["catalog_present"] else "unavailable"
        ),
        inventory if inventory_ok else inventory_payload,
        f"Start LM Studio and load {model!r}; catalog presence alone is not sufficient.",
    ))
    checks.append(PreflightCheck(
        "reasoning_off_capability", True,
        inventory_ok and inventory["loaded"] and inventory["reasoning_off_supported"],
        "supported" if inventory_ok and inventory["reasoning_off_supported"] else "unproven",
        inventory.get("reasoning_off_supported"),
        "Use a loaded model/runtime that advertises the native reasoning-off option.",
    ))

    deployment_fields = {
        "artifact_sha256": os.environ.get("PRISM_LOCAL_AI_ARTIFACT_SHA256"),
        "runtime_name": os.environ.get("PRISM_LOCAL_AI_RUNTIME"),
        "runtime_version": os.environ.get("PRISM_LOCAL_AI_RUNTIME_VERSION"),
        "hardware": os.environ.get("PRISM_LOCAL_AI_HARDWARE"),
    }
    deployment_complete = all(deployment_fields.values())
    checks.append(PreflightCheck(
        "benchmark_deployment_metadata", False, deployment_complete,
        "complete" if deployment_complete else "optional_missing",
        deployment_fields,
        "Set the PRISM_LOCAL_AI_ARTIFACT_SHA256, RUNTIME, RUNTIME_VERSION, and HARDWARE variables before a benchmark claim.",
    ))

    if phase == "live":
        relay_origin_ok = _safe_loopback_origin(buzz_url)
        relay_ok, relay_payload = _status_get(f"{buzz_url.rstrip('/')}/_liveness") if relay_origin_ok else (False, "invalid origin")
        checks.append(PreflightCheck(
            "buzz_relay_live", True, relay_ok, "live" if relay_ok else "unavailable",
            relay_payload, "Run python3 scripts/buzz_up.py and inspect Docker service health.",
        ))
        identity_path = root / ".runtime" / "buzz" / "identities.env"
        identity_mode = stat.S_IMODE(identity_path.stat().st_mode) if identity_path.is_file() else None
        identity_ok = identity_path.is_file() and identity_mode == 0o600
        checks.append(PreflightCheck(
            "buzz_identity_permissions", True, identity_ok,
            "private" if identity_ok else "missing_or_unsafe",
            oct(identity_mode) if identity_mode is not None else None,
            "Regenerate or chmod .runtime/buzz/identities.env to mode 0600.",
        ))

    return {
        "verification_kind": "operator_preflight",
        "phase": phase,
        "measurement_state": "same_host_preflight_not_clean_machine_reproduction",
        "required_passed": required_checks_pass(checks),
        "checks": [asdict(check) for check in checks],
        "limitations": [
            "This checks the current host only. It does not prove a clean physical machine setup.",
            "A loaded model proves availability, not artifact identity, quality, or performance.",
            "LM Studio API context metadata does not prove the backend's effective fitted context or a workload at that length.",
            "Loopback endpoints do not prove zero egress or an air gap.",
            "Optional deployment metadata is required separately before benchmark claims.",
        ],
    }
