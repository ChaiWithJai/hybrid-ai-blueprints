"""Process-scoped socket observation without claiming packet-level zero egress."""

from __future__ import annotations

import ipaddress
import re
from typing import Any
from urllib.parse import urlparse


def _host_from_endpoint(endpoint: str) -> str | None:
    value = endpoint.strip()
    if value.startswith("[") and "]" in value:
        return value[1:value.index("]")]
    if ":" not in value:
        return None
    return value.rsplit(":", 1)[0]


def classify_socket_name(name: str) -> dict[str, Any]:
    """Classify every IP endpoint in one numeric lsof socket name."""
    endpoints = [part.strip() for part in name.split("->") if part.strip()]
    hosts: list[str] = []
    invalid: list[str] = []
    wildcard_hosts: list[str] = []
    for endpoint in endpoints:
        host = _host_from_endpoint(endpoint)
        if host is None:
            continue
        if host == "*":
            wildcard_hosts.append(host)
            continue
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            invalid.append(host)
        else:
            hosts.append(str(address))
    non_loopback = [host for host in hosts if not ipaddress.ip_address(host).is_loopback]
    return {
        "name": name,
        "hosts": hosts,
        "invalid_hosts": invalid,
        "wildcard_hosts": wildcard_hosts,
        "loopback_only": bool(hosts) and not non_loopback and not invalid and not wildcard_hosts,
        "non_loopback_hosts": non_loopback,
    }


def parse_lsof_fields(output: str) -> list[dict[str, Any]]:
    """Parse the process, command, and socket-name fields emitted by lsof -FpcnT."""
    process_id: int | None = None
    command: str | None = None
    records: list[dict[str, Any]] = []
    for line in output.splitlines():
        if not line:
            continue
        field, value = line[0], line[1:]
        if field == "p" and value.isdigit():
            process_id = int(value)
            command = None
        elif field == "c":
            command = value
        elif field == "n" and process_id is not None:
            records.append({
                "pid": process_id,
                "command": command,
                **classify_socket_name(value),
            })
    return records


def validate_network_observation(
    record: dict[str, Any], *, require_pass_label: bool = True
) -> dict[str, Any]:
    errors: list[str] = []
    if record.get("verification_kind") != "process_socket_observation.v1":
        errors.append("unexpected network-observation kind")
    samples = record.get("samples")
    if not isinstance(samples, list) or len(samples) < 3:
        errors.append("at least three socket samples are required")
        samples = []
    observed: list[dict[str, Any]] = []
    for sample in samples:
        if not isinstance(sample, dict) or not isinstance(sample.get("lsof_output"), str):
            errors.append("socket sample is malformed")
            continue
        observed.extend(parse_lsof_fields(sample["lsof_output"]))
    non_loopback = sorted({
        host for item in observed for host in item["non_loopback_hosts"]
    })
    invalid_hosts = sorted({host for item in observed for host in item["invalid_hosts"]})
    wildcard_hosts = sorted({host for item in observed for host in item["wildcard_hosts"]})
    required_roles = {"prism_server", "bionic_app", "bonsai_llama_server"}
    roles = record.get("processes", {})
    if not isinstance(roles, dict) or not required_roles.issubset(roles):
        errors.append("required process roles are missing")
        role_pids: set[int] = set()
    else:
        role_pids = {
            item.get("pid") for name, item in roles.items()
            if name in required_roles and isinstance(item, dict)
            and isinstance(item.get("pid"), int) and item["pid"] > 0
        }
        if len(role_pids) != len(required_roles):
            errors.append("required process roles must have distinct positive PIDs")
        for name in required_roles:
            item = roles.get(name, {})
            command = item.get("command", "") if isinstance(item, dict) else ""
            if not isinstance(command, str) or not command:
                errors.append(f"{name} is missing sanitized process identity")
            if "--api-key " in command and "--api-key [REDACTED]" not in command:
                errors.append(f"{name} contains an unredacted API key")
    observed_pids = {item["pid"] for item in observed}
    missing_observed_pids = sorted(role_pids - observed_pids)
    if missing_observed_pids:
        errors.append(f"required process PIDs have no observed sockets: {missing_observed_pids}")
    request = record.get("request", {})
    if not isinstance(request, dict) or request.get("http_status") != 200:
        errors.append("the measured local model request did not complete")
        request = {}
    endpoint = urlparse(str(request.get("endpoint", "")))
    if not (
        endpoint.scheme == "http" and endpoint.hostname == "127.0.0.1"
        and endpoint.port == 1234 and endpoint.path == "/api/v1/chat"
    ):
        errors.append("the measured request was not the pinned loopback native-chat endpoint")
    if request.get("protocol") != "lmstudio_native_chat":
        errors.append("the measured request protocol is not LM Studio native chat")
    if request.get("model") != "27b@q1_0" or request.get("model_instance_id") != "27b@q1_0":
        errors.append("the measured request is not bound to the exact Bonsai model instance")
    if request.get("reasoning_requested") != "off" or request.get("reasoning_output_tokens") != 0:
        errors.append("the measured request did not prove reasoning-off behavior")
    if request.get("response_matched_requested_text") is not True:
        errors.append("the measured request did not return its exact bounded response")
    declared = record.get("observation", {})
    if declared.get("non_loopback_hosts") != non_loopback:
        errors.append("declared non-loopback hosts differ from parsed samples")
    if declared.get("invalid_hosts") != invalid_hosts:
        errors.append("declared invalid hosts differ from parsed samples")
    if declared.get("wildcard_hosts") != wildcard_hosts:
        errors.append("declared wildcard hosts differ from parsed samples")
    if record.get("packet_capture_used") is not False:
        errors.append("process socket observation cannot claim packet capture")
    if record.get("zero_egress_proved") is not False:
        errors.append("sampled sockets cannot prove zero egress")
    if record.get("air_gap_proved") is not False:
        errors.append("sampled sockets cannot prove an air gap")
    observation_passed = not non_loopback and not invalid_hosts and not wildcard_hosts and not errors
    if require_pass_label:
        declared_pass = record.get("passed")
        if not isinstance(declared_pass, bool):
            errors.append("network-observation pass label is required")
        elif declared_pass is not observation_passed:
            errors.append("network-observation pass label differs from parsed evidence")
    elif "passed" in record:
        errors.append("pass-label derivation input must not contain a declared pass label")
    return {
        "passed": not errors and observation_passed,
        "sample_count": len(samples),
        "observed_socket_count": len(observed),
        "non_loopback_hosts": non_loopback,
        "invalid_hosts": invalid_hosts,
        "wildcard_hosts": wildcard_hosts,
        "zero_egress_proved": False,
        "air_gap_proved": False,
        "errors": errors,
        "meaning": (
            "No non-loopback endpoint was present in the sampled sockets for the named processes. "
            "Sampling can miss short-lived connections and does not inspect packets or Docker guest traffic."
        ),
    }
