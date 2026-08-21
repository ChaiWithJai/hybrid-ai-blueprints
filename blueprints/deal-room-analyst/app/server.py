"""Local Prism Vault prototype HTTP server.

The server provides parsing, reviewed deterministic workflows, optional calls
to explicitly configured AI providers, sandbox execution, and local persistent traces.
It does not itself bundle or own model weights.
"""

import http.server
import socketserver
import fcntl
import json
import urllib.parse
import urllib.error
import urllib.request
import os
import re
import subprocess
import tempfile
import threading
import time
import hashlib
from contextlib import contextmanager
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Dict, Any, List

from core.deal_room_analyzer import DealRoomAnalyzer
from core.coding_agent import DealRoomWorkflowAgent
from core.hybrid_router import HybridAIRouter
from core.arize_evals import (
    ArizeObservabilityTracer,
    ArizeEvaluationEngine,
    ArizeTraceRecord,
    EvalMetric,
    evaluation_release_state,
)
from core.doc_parser import DealRoomParser, evidence_node_text
from core.macos_ocr import ocr_toolchain_status
from core.ai_provider import ProviderRegistry
from core.cloud_consent import CloudConsentAuthority
from core.benchmark import run_benchmark
from core.buzz_bridge import BuzzBridge, BuzzUnavailable
from core.deal_room_chat import (
    DEAL_ROOM_CHAT_GUARD_VERSION,
    DealRoomChatError,
    answer_deal_room_question,
)
from core.first_pass import (
    DEFAULT_INVESTMENT_SCREEN,
    EVIDENCE_FALLBACK_GUARD_VERSION,
    FIRST_PASS_GUARD_VERSION,
    FirstPassError,
    build_evidence_safe_fallback,
    generate_first_pass,
    retrieve_first_pass_evidence,
    restore_signed_first_pass,
)
from core.candidate_source_review import (
    build_candidate_source_review_packet,
    draft_sources,
    evaluate_source_review_state,
    load_source_reviewer_roster,
    packet_sha256 as candidate_review_packet_sha256,
    validate_source_review_submission,
)
from core.candidate_case_approval import build_candidate_case_authoring_material
from core.candidate_case_registration import APPROVAL_LEDGER_STATUS
from core.first_pass_benchmark import sha256, validate_contract
from core.first_pass_review import (
    build_review_packet,
    load_output_reviewer_roster,
    packet_sha256 as output_review_packet_sha256,
)
from core.judge_calibration import validate_saved_judge_calibration
from core.pricing_poc import validate_saved_pricing_poc
from core.oracle_context_diagnostic import validate_saved_oracle_context
from core.sealed_test_control import sealed_test_preflight
from core.deployment_evidence import (
    validate_deployment_record,
    verify_active_deployment_process,
)
from core.evidence_manifest import engineering_evidence_summary
from core.evidence_scope import (
    build_evidence_inventory,
    evidence_scope_for_anchors,
    evidence_scope_for_citations,
)
from core.workspace_review import WorkspaceReviewStore, build_review_corpus
from core.evaluation_dashboard import build_evaluation_dashboard
from core.evaluation_experiments import ExperimentStore

DEAL_ROOMS_BASE = "deal_rooms"
DEFAULT_ROOM = "project_titan_lbo"
PROJECT_ROOT = Path(__file__).resolve().parent
STATIC_DIR = str(PROJECT_ROOT / "web")
CANDIDATE_REVIEW_DIR = PROJECT_ROOT / "benchmarks" / "first_pass" / "source_reviews"
CANDIDATE_REVIEW_ADJUDICATION = (
    PROJECT_ROOT / "benchmarks" / "first_pass" / "source_review_adjudication.json"
)
BENCHMARK_REVIEW_CHANNEL = PROJECT_ROOT / ".runtime" / "buzz" / "benchmark-review-channel-id"
CASE_REGISTRATION_LEDGER = (
    PROJECT_ROOT / "benchmarks" / "first_pass" / "candidate_case_registrations.v1.json"
)
CASE_APPROVAL_LEDGER = (
    PROJECT_ROOT / "benchmarks" / "first_pass" / "candidate_case_approval_records.v1.json"
)
CUSTOM_DEAL_ROOM_REGISTRY = (
    PROJECT_ROOT / ".runtime" / "deal_rooms" / "registrations.v1.json"
)
LOCAL_DEPLOYMENT_EVIDENCE = PROJECT_ROOT / "evidence" / "local-deployment-current.json"
CURRENT_LOCAL_ENGINEERING_EVIDENCE = (
    PROJECT_ROOT / "evidence" / "bonsai-local-product-verification-current.json"
)
JUDGE_CALIBRATION_EVIDENCE = (
    PROJECT_ROOT / "evidence" / "first-pass-judge-calibration.json"
)
PRICING_POC_RECORD = PROJECT_ROOT / "evidence" / "first-pass-pricing-poc.json"
ORACLE_CONTEXT_EVIDENCE = (
    PROJECT_ROOT / "evidence" / "bonsai-oracle-context-diagnostic-v1.json"
)
FIRST_PASS_REVIEW_RESPONSES = (
    PROJECT_ROOT / "evidence" / "bonsai-public-deal-battletest-responses.json"
)
WORKSPACE_REVIEW_DATA = Path(os.environ.get(
    "PRISM_EVAL_REVIEW_DATA",
    str(PROJECT_ROOT / ".runtime" / "eval-review"),
)).resolve()
EVALUATION_EXPERIMENT_DATA = Path(os.environ.get(
    "PRISM_EVALUATION_EXPERIMENT_DATA",
    str(PROJECT_ROOT / ".runtime" / "evaluation" / "experiments"),
)).resolve()
PHOENIX_ENDPOINT = os.environ.get(
    "PRISM_PHOENIX_ENDPOINT", "http://127.0.0.1:6006",
).rstrip("/")
_DEPLOYMENT_VERIFICATION_LOCK = threading.Lock()


@lru_cache(maxsize=2)
def _measured_local_deployment_for_file(
    record_path_text: str,
    record_bytes: bytes,
    model_root_text: str,
    artifact_stat_fingerprint: tuple[tuple[Any, ...], ...],
) -> Dict[str, Any]:
    """Verify artifacts once for each exact record and filesystem fingerprint."""
    del artifact_stat_fingerprint
    record_path = Path(record_path_text)
    try:
        record = json.loads(record_bytes)
    except json.JSONDecodeError as exc:
        return {
            "verified": False,
            "measurement_state": "deployment_evidence_unavailable",
            "record": str(record_path),
            "errors": [str(exc)],
        }
    errors = validate_deployment_record(
        record, model_root=Path(model_root_text), verify_files=True,
    )
    artifacts = record.get("artifacts", [])
    weights = next(
        (item for item in artifacts if isinstance(item, dict) and item.get("role") == "model_weights"),
        {},
    )
    return {
        "verified": not errors,
        "measurement_state": record.get("measurement_state"),
        "record": str(record_path.relative_to(PROJECT_ROOT))
        if record_path.is_relative_to(PROJECT_ROOT) else str(record_path),
        "record_sha256": hashlib.sha256(record_bytes).hexdigest(),
        "verified_at": datetime.now(timezone.utc).isoformat(),
        "cache_basis": "record_bytes_plus_artifact_device_inode_size_mtime_ctime",
        "model": record.get("model", {}).get("identifier"),
        "artifact_sha256": weights.get("sha256"),
        "artifact_count": len(artifacts) if isinstance(artifacts, list) else 0,
        "runtime": record.get("runtime", {}),
        "hardware": record.get("hardware", {}),
        "catalog_size_matches_artifact": record.get("model", {}).get(
            "catalog_size_matches_artifact"
        ),
        "errors": errors,
        "limitations": record.get("limitations", []),
        "meaning": (
            "The current files match the saved deployment hashes. This is separate from "
            "provider configuration, invocation, quality, and clean-machine reproduction."
            if not errors else
            "The saved deployment record does not match the current model files."
        ),
    }


def measured_local_deployment_status(
    record_path: Path = LOCAL_DEPLOYMENT_EVIDENCE,
    *,
    model_root: Path | None = None,
    process_runner=None,
) -> Dict[str, Any]:
    try:
        record_bytes = record_path.read_bytes()
        record = json.loads(record_bytes)
    except (OSError, json.JSONDecodeError) as exc:
        return {
            "verified": False,
            "measurement_state": "deployment_evidence_unavailable",
            "record": str(record_path),
            "errors": [str(exc)],
        }
    models = (model_root or (Path.home() / ".lmstudio" / "models")).resolve()
    fingerprint: list[tuple[Any, ...]] = []
    artifacts = record.get("artifacts", [])
    if not isinstance(artifacts, list):
        artifacts = []
    for item in artifacts:
        role = item.get("role") if isinstance(item, dict) else None
        logical_path = item.get("logical_path") if isinstance(item, dict) else None
        try:
            candidate = (models / str(logical_path)).resolve()
            if not isinstance(logical_path, str) or not candidate.is_relative_to(models):
                raise ValueError("unsafe artifact path")
            stat_result = candidate.stat()
            fingerprint.append((
                role,
                str(candidate),
                stat_result.st_dev,
                stat_result.st_ino,
                stat_result.st_size,
                stat_result.st_mtime_ns,
                stat_result.st_ctime_ns,
            ))
        except (OSError, ValueError) as exc:
            fingerprint.append((role, str(logical_path), "unavailable", str(exc)))
    with _DEPLOYMENT_VERIFICATION_LOCK:
        artifact_status = _measured_local_deployment_for_file(
            str(record_path.resolve()), record_bytes, str(models), tuple(fingerprint),
        )
    runner = process_runner or subprocess.run
    try:
        process_result = runner(
            ["ps", "-axo", "pid=,command="],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        if process_result.returncode:
            raise OSError("process table command failed")
        active_runtime = verify_active_deployment_process(
            record, model_root=models, process_table=process_result.stdout,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        active_runtime = {
            "verified": False,
            "process_count": None,
            "runtime_version": None,
            "executable_bundle": None,
            "effective_config": {},
            "errors": [f"active runtime inspection failed: {exc}"],
        }
    active_runtime["checked_at"] = datetime.now(timezone.utc).isoformat()
    artifacts_verified = artifact_status.get("verified") is True
    deployment_verified = artifacts_verified and active_runtime.get("verified") is True
    return {
        **artifact_status,
        "verified": deployment_verified,
        "artifact_files_verified": artifacts_verified,
        "active_runtime": active_runtime,
        "meaning": (
            "The current files and active llama-server match the saved deployment. This is "
            "separate from provider invocation, quality, and clean-machine reproduction."
            if deployment_verified else
            "The saved deployment does not match the current artifact files or active runtime."
        ),
    }

# Available Deal Rooms
DEAL_ROOM_CATALOG = {
    "project_titan_lbo": {
        "id": "project_titan_lbo",
        "name": "Project Titan: $2.4B Sponsor-Backed LBO",
        "target": "CloudScale Networks Inc.",
        "type": "Leveraged Buyout (LBO)",
        "path": "deal_rooms/project_titan_lbo",
        "description": "5-year LBO financial model with Term Loan B, Senior Notes, ECF sweeps, and returns sensitivity (IRR/MoIC)."
    },
    "project_aeroflux_crossborder_ma": {
        "id": "project_aeroflux_crossborder_ma",
        "name": "Project AeroFlux: €850M Strategic Cross-Border M&A",
        "target": "AeroDynamics SA (Toulouse, France)",
        "type": "Strategic Acquisition",
        "path": "deal_rooms/project_aeroflux_crossborder_ma",
        "description": "Cross-border SPA, multi-currency financials (EUR/USD), Section 338(g) tax election, CFIUS & EC merger clearance."
    },
    "project_biovanguard_carveout": {
        "id": "project_biovanguard_carveout",
        "name": "Project BioVanguard: $620M Corporate Carve-Out",
        "target": "Oncology Diagnostics Division",
        "type": "Corporate Divestiture",
        "path": "deal_rooms/project_biovanguard_carveout",
        "description": "12-month Transition Services Agreement (TSA), stranded corporate overhead elimination, standalone QoE EBITDA bridge."
    },
    "sample_ma_acquisition": {
        "id": "sample_ma_acquisition",
        "name": "Project Horizon: $140M Industrial Bolt-On",
        "target": "NovaTech Dynamics Inc.",
        "type": "Bolt-On Acquisition",
        "path": "deal_rooms/sample_ma_acquisition",
        "description": "Senior credit agreement covenant compliance audit, interest coverage floor, patent litigation materiality review."
    }
}


@lru_cache(maxsize=1024)
def _sha256_for_file_identity(
    path_text: str,
    device: int,
    inode: int,
    size: int,
    modified_ns: int,
    changed_ns: int,
) -> str:
    del device, inode, size, modified_ns, changed_ns
    digest = hashlib.sha256()
    with Path(path_text).open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _current_file_sha256(path: Path) -> str:
    stat = path.stat()
    return _sha256_for_file_identity(
        str(path), stat.st_dev, stat.st_ino, stat.st_size,
        stat.st_mtime_ns, stat.st_ctime_ns,
    )


def _public_source_registry() -> dict[Path, dict[str, Any]]:
    """Return public source identities backed by checked-in acquisition records."""
    registry: dict[Path, dict[str, Any]] = {}

    direct_manifest_path = PROJECT_ROOT / "benchmarks" / "public_deal_corpus_manifest.json"
    direct_manifest = json.loads(direct_manifest_path.read_text(encoding="utf-8"))
    for item in direct_manifest.get("documents", []):
        source = (PROJECT_ROOT / str(item.get("path", ""))).resolve()
        if (
            re.fullmatch(r"[0-9a-f]{64}", str(item.get("sha256", "")))
            and isinstance(item.get("bytes"), int)
            and item["bytes"] >= 0
        ):
            registry[source] = {
                "sha256": item["sha256"],
                "bytes": item["bytes"],
                "authority": item.get("publisher"),
                "canonical_url": item.get("canonical_url"),
                "registry_path": str(direct_manifest_path.relative_to(PROJECT_ROOT)),
            }

    acquisition_specs = (
        (
            PROJECT_ROOT / "benchmarks" / "first_pass" / "candidate_deal_sources.v1.json",
            "candidates",
        ),
        (
            PROJECT_ROOT / "benchmarks" / "first_pass" / "candidate_companion_sources.v1.json",
            "companions",
        ),
    )
    for manifest_path, collection in acquisition_specs:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        for item in manifest.get(collection, []):
            evidence_path = PROJECT_ROOT / str(item.get("evidence_path", ""))
            expected_evidence_sha = str(item.get("evidence_sha256", ""))
            if (
                not evidence_path.is_file()
                or not re.fullmatch(r"[0-9a-f]{64}", expected_evidence_sha)
                or _current_file_sha256(evidence_path) != expected_evidence_sha
            ):
                continue
            evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
            source_record = evidence.get("source", evidence)
            source_path = source_record.get("path", source_record.get("source_path"))
            source_sha = source_record.get("sha256", source_record.get("source_sha256"))
            source_bytes = source_record.get("bytes", source_record.get("source_bytes"))
            if (
                not isinstance(source_path, str)
                or not re.fullmatch(r"[0-9a-f]{64}", str(source_sha or ""))
                or not isinstance(source_bytes, int)
                or source_bytes < 0
            ):
                continue
            source = (PROJECT_ROOT / source_path).resolve()
            registry[source] = {
                "sha256": source_sha,
                "bytes": source_bytes,
                "authority": "U.S. Securities and Exchange Commission",
                "canonical_url": source_record.get(
                    "primary_url", source_record.get("filing_url")
                ),
                "registry_path": str(manifest_path.relative_to(PROJECT_ROOT)),
                "evidence_path": str(evidence_path.relative_to(PROJECT_ROOT)),
                "evidence_sha256": expected_evidence_sha,
            }
    return registry


def _public_folder_integrity(
    folder: Path,
    registry: dict[Path, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Verify that every visible file in a public folder is registered and unchanged."""
    registry = registry if registry is not None else _public_source_registry()
    folder = folder.resolve()
    expected = {
        path: record for path, record in registry.items()
        if path.is_relative_to(folder)
    }
    actual: set[Path] = set()
    errors: list[str] = []
    try:
        for path in folder.rglob("*"):
            relative = path.relative_to(folder)
            if any(part.startswith(".") for part in relative.parts):
                continue
            if path.is_symlink():
                errors.append(f"symlink_not_admitted:{relative}")
            elif path.is_file():
                actual.add(path.resolve())
    except OSError as exc:
        errors.append(f"folder_unavailable:{exc}")

    for path in sorted(actual - set(expected)):
        errors.append(f"unregistered_file:{path.relative_to(folder)}")
    for path in sorted(set(expected) - actual):
        errors.append(f"registered_file_missing:{path.relative_to(folder)}")
    for path in sorted(actual & set(expected)):
        record = expected[path]
        try:
            if path.stat().st_size != record["bytes"]:
                errors.append(f"byte_count_mismatch:{path.relative_to(folder)}")
            elif _current_file_sha256(path) != record["sha256"]:
                errors.append(f"sha256_mismatch:{path.relative_to(folder)}")
        except OSError as exc:
            errors.append(f"source_unavailable:{path.relative_to(folder)}:{exc}")
    if not expected:
        errors.append("no_registered_public_sources")

    snapshot_items = [
        {
            "path": str(path.relative_to(folder)),
            "sha256": record["sha256"],
            "bytes": record["bytes"],
            "registry_path": record["registry_path"],
        }
        for path, record in sorted(expected.items())
    ]
    snapshot_sha256 = hashlib.sha256(
        json.dumps(snapshot_items, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return {
        "passed": not errors,
        "source_count": len(expected),
        "snapshot_sha256": snapshot_sha256,
        "registry_paths": sorted({item["registry_path"] for item in expected.values()}),
        "errors": errors,
    }


def room_source_provenance(room: dict[str, Any]) -> dict[str, Any]:
    """Classify a room from framework-owned path and catalog facts.

    This classification is deliberately separate from document content. A
    filename, model response, or operator label cannot promote a synthetic or
    public room into private customer evidence.
    """
    room_id = str(room.get("id", ""))
    if room_id in DEAL_ROOM_CATALOG:
        return {
            "classification": "synthetic_engineering_fixture",
            "label": "Synthetic demonstration fixture",
            "synthetic_fixture": True,
            "public_source": False,
            "operator_selected": False,
            "customer_data_verified": False,
            "accuracy_release_evidence": False,
            "buyer_evidence": False,
            "meaning": (
                "Prism ships these fabricated files for engineering demonstrations. "
                "They are not a real transaction, customer data, domain accuracy evidence, "
                "or buyer evidence."
            ),
        }

    path = Path(str(room.get("path", "")))
    public_root = PROJECT_ROOT / ".runtime" / "public-deal-corpus"
    managed_roots = (
        public_root,
        PROJECT_ROOT / ".runtime" / "public-deal-rooms",
        PROJECT_ROOT / ".runtime" / "candidate-deal-sources",
    )
    try:
        resolved_path = path.resolve()
        is_managed_public_path = path.is_absolute() and any(
            resolved_path.is_relative_to(root.resolve()) for root in managed_roots
        )
    except (OSError, RuntimeError):
        resolved_path = path
        is_managed_public_path = False
    public_integrity = (
        _public_folder_integrity(resolved_path)
        if is_managed_public_path else None
    )
    if public_integrity and public_integrity["passed"]:
        return {
            "classification": "public_filing_corpus",
            "label": "Hash-verified public filing corpus",
            "synthetic_fixture": False,
            "public_source": True,
            "operator_selected": False,
            "customer_data_verified": False,
            "accuracy_release_evidence": False,
            "buyer_evidence": False,
            "manifest_bound": True,
            "public_integrity": public_integrity,
            "meaning": (
                "Every visible file in this folder matches a checked-in public acquisition "
                "record by path, byte count, and SHA-256. This can demonstrate the workflow "
                "but is not private customer, accuracy-release, or buyer evidence."
            ),
        }
    if is_managed_public_path:
        return {
            "classification": "public_corpus_integrity_failed",
            "label": "Public corpus integrity failed",
            "synthetic_fixture": False,
            "public_source": False,
            "operator_selected": False,
            "customer_data_verified": False,
            "accuracy_release_evidence": False,
            "buyer_evidence": False,
            "manifest_bound": False,
            "public_integrity": public_integrity,
            "meaning": (
                "This folder is under a managed public-corpus path, but its complete visible "
                "file set did not match the registered acquisition evidence. Prism will not "
                "call it public or customer data."
            ),
        }
    return {
        "classification": "operator_selected_local_folder",
        "label": "Operator-selected local folder",
        "synthetic_fixture": False,
        "public_source": False,
        "operator_selected": True,
        "customer_data_verified": False,
        "accuracy_release_evidence": False,
        "buyer_evidence": False,
        "meaning": (
            "Prism verifies the selected local path and source snapshot. It does not "
            "independently verify authorization, customer identity, or private origin."
        ),
    }


SOURCE_PROVENANCE_BINDING_VERSION = "room_source_provenance_v1"


def source_provenance_binding(room: dict[str, Any]) -> dict[str, Any]:
    """Return the small canonical provenance claim persisted with an artifact.

    Human-facing labels and explanations are deliberately excluded. The binding
    contains only server-derived facts whose meaning is stable across copy,
    export, and restoration.
    """
    provenance = room_source_provenance(room)
    public_integrity = provenance.get("public_integrity") or {}
    claim = {
        "version": SOURCE_PROVENANCE_BINDING_VERSION,
        "classification": provenance["classification"],
        "synthetic_fixture": provenance.get("synthetic_fixture") is True,
        "public_source": provenance.get("public_source") is True,
        "operator_selected": provenance.get("operator_selected") is True,
        "customer_data_verified": provenance.get("customer_data_verified") is True,
        "accuracy_release_evidence": provenance.get("accuracy_release_evidence") is True,
        "buyer_evidence": provenance.get("buyer_evidence") is True,
        "manifest_bound": provenance.get("manifest_bound") is True,
        "public_snapshot_sha256": public_integrity.get("snapshot_sha256"),
        "public_source_count": public_integrity.get("source_count", 0),
    }
    binding_sha256 = hashlib.sha256(
        json.dumps(claim, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return {**claim, "binding_sha256": binding_sha256}
def _validated_local_room_record(room: dict[str, Any]) -> dict[str, Any]:
    required = {"id", "name", "target", "type", "path", "description"}
    if set(room) != required or not all(isinstance(room[field], str) for field in required):
        raise ValueError("custom deal-room registry contains an invalid room record")
    resolved = Path(room["path"])
    if not resolved.is_absolute():
        raise ValueError("custom deal-room registry paths must be absolute")
    expected_id = "local_" + hashlib.sha256(str(resolved).encode("utf-8")).hexdigest()[:12]
    if room["id"] != expected_id or room["id"] in DEAL_ROOM_CATALOG:
        raise ValueError("custom deal-room registry contains an invalid room identity")
    return dict(room)


def load_local_deal_rooms(
    registry_path: Path | None = None,
) -> Dict[str, Dict[str, Any]]:
    registry_path = registry_path or CUSTOM_DEAL_ROOM_REGISTRY
    if not registry_path.exists():
        return {}
    value = json.loads(registry_path.read_text(encoding="utf-8"))
    if value.get("schema_version") != 1 or not isinstance(value.get("rooms"), list):
        raise ValueError("custom deal-room registry has an invalid schema")
    rooms: Dict[str, Dict[str, Any]] = {}
    for item in value["rooms"]:
        if not isinstance(item, dict):
            raise ValueError("custom deal-room registry contains a non-object room")
        room = _validated_local_room_record(item)
        if room["id"] in rooms:
            raise ValueError("custom deal-room registry contains a duplicate room")
        rooms[room["id"]] = room
    return rooms


def persist_local_deal_rooms(
    rooms: Dict[str, Dict[str, Any]],
    registry_path: Path | None = None,
) -> None:
    registry_path = registry_path or CUSTOM_DEAL_ROOM_REGISTRY
    validated = [_validated_local_room_record(room) for _, room in sorted(rooms.items())]
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f"{registry_path.name}.", suffix=".tmp", dir=registry_path.parent,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(
                {"schema_version": 1, "rooms": validated},
                handle,
                indent=2,
                sort_keys=True,
            )
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, registry_path)
        directory_fd = os.open(registry_path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if temporary.exists():
            temporary.unlink()


def _local_registry_identity(path: Path) -> tuple[int, int, int, int, int] | None:
    try:
        stat = path.stat()
    except FileNotFoundError:
        return None
    return (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)


CUSTOM_DEAL_ROOMS: Dict[str, Dict[str, Any]] = load_local_deal_rooms()
CUSTOM_DEAL_ROOM_REGISTRY_IDENTITY = _local_registry_identity(CUSTOM_DEAL_ROOM_REGISTRY)
CUSTOM_DEAL_ROOM_LOCK = threading.RLock()


@contextmanager
def local_deal_room_registry_transaction(registry_path: Path):
    """Serialize one folder-registry transaction across local processes."""
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = registry_path.with_name(f".{registry_path.name}.lock")
    with CUSTOM_DEAL_ROOM_LOCK:
        descriptor = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
        with os.fdopen(descriptor, "a+b") as handle:
            os.chmod(lock_path, 0o600)
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def restore_trace_bound_first_pass(
    messages: List[Dict[str, Any]],
    traces: List[ArizeTraceRecord],
    *,
    room_id: str,
    agent_pubkey: str,
    current_provenance: Dict[str, Any] | None = None,
    current_source_snapshot: str | None = None,
    current_evidence_inventory: Dict[str, Any] | None = None,
) -> Dict[str, Any] | None:
    """Restore only an agent-authored Buzz draft bound to one exact trace."""
    if not re.fullmatch(r"[0-9a-f]{64}", agent_pubkey or ""):
        return None

    traces_by_id = {trace.trace_id: trace for trace in traces}
    traces_by_event: Dict[str, List[ArizeTraceRecord]] = {}
    for trace in traces:
        event_id = str(trace.metadata.get("draft_event_id", ""))
        if event_id:
            traces_by_event.setdefault(event_id, []).append(trace)

    for message in reversed(messages):
        event_id = str(message.get("id", ""))
        if (
            message.get("signature_verified") is not True
            or message.get("pubkey") != agent_pubkey
            or not re.fullmatch(r"[0-9a-f]{64}", event_id)
        ):
            continue
        restored = restore_signed_first_pass(str(message.get("content", "")))
        if restored is None or restored.get("acceptance_state") not in {
            "accepted", "evidence_safe_fallback",
        }:
            continue

        marker_trace_id = restored.get("trace_id")
        if marker_trace_id:
            trace = traces_by_id.get(str(marker_trace_id))
            candidates = [trace] if trace is not None else []
        else:
            candidates = traces_by_event.get(event_id, [])
        if len(candidates) != 1:
            continue
        trace = candidates[0]
        metadata = trace.metadata
        if (
            metadata.get("draft_event_id") != event_id
            or trace.session_id != room_id
            or trace.model_name != restored.get("model")
            or trace.response.strip() != str(restored.get("markdown", "")).strip()
            or metadata.get("guard_version") != restored.get("guard_version")
            or metadata.get("citation_count") != len(restored.get("citations", []))
            or metadata.get("source_classification")
            != restored.get("source_classification")
            or metadata.get("source_provenance_sha256")
            != restored.get("source_provenance_sha256")
            or metadata.get("source_snapshot_sha256")
            != restored.get("source_snapshot_sha256")
        ):
            continue
        if current_provenance is not None and (
            current_provenance.get("classification")
            != restored.get("source_classification")
            or current_provenance.get("binding_sha256")
            != restored.get("source_provenance_sha256")
        ):
            continue
        if (
            current_source_snapshot is not None
            and current_source_snapshot != restored.get("source_snapshot_sha256")
        ):
            continue

        artifact_mode = restored.get("artifact_mode")
        if artifact_mode == "model_draft":
            if (
                trace.query != "first_pass_underwriting"
                or metadata.get("product_job") != "first_pass_underwriting"
                or metadata.get("provider_id") != "local_bonsai"
            ):
                continue
        elif artifact_mode == "evidence_safe_fallback":
            if (
                trace.query != "evidence_safe_fallback"
                or metadata.get("product_job") != "first_pass_underwriting_fallback"
                or metadata.get("artifact_mode") != "evidence_safe_fallback"
                or metadata.get("authored_by") != "deterministic_evidence_renderer"
                or metadata.get("model_failure_trace_id")
                != restored.get("model_failure_trace_id")
            ):
                continue
        else:
            continue

        evidence_scope = None
        if current_evidence_inventory is not None:
            evidence_scope = evidence_scope_for_citations(
                current_evidence_inventory,
                list(restored.get("citations", [])),
            )
            if evidence_scope is None:
                continue

        return {
            **restored,
            "trace_id": trace.trace_id,
            "draft_event_id": event_id,
            "provider": metadata.get("provider_id", "deterministic_local"),
            "investment_screen": metadata.get("investment_screen"),
            "canonical_path": f"/rooms/{room_id}/first-pass",
            "review": None,
            "evidence_scope": evidence_scope,
            "restored_from_buzz": True,
            "restoration_verification": {
                "state": "verified",
                "author": agent_pubkey,
                "event_id": event_id,
                "trace_id": trace.trace_id,
                "bindings": [
                    "nip01_event_id_plus_bip340",
                    "configured_agent_author",
                    "trace_draft_event_id",
                    "room_id",
                    "model",
                    "guard_version",
                    "artifact_mode",
                    "response_text",
                    "source_classification",
                    "source_provenance_sha256",
                    "source_snapshot_sha256",
                ],
            },
        }
    return None


def trace_bound_deal_room_message_state(
    message: Dict[str, Any],
    traces: List[ArizeTraceRecord],
    *,
    room_id: str,
    agent_pubkey: str,
    current_provenance: Dict[str, Any],
    current_source_snapshot: str,
    current_evidence_inventory: Dict[str, Any] | None = None,
) -> str | None:
    """Classify one Prism chat event only when its trace and source still match."""
    event_id = str(message.get("id") or message.get("event_id") or "")
    if (
        message.get("signature_verified") is not True
        or message.get("pubkey") != agent_pubkey
        or not re.fullmatch(r"[0-9a-f]{64}", event_id)
    ):
        return None
    marker = re.match(
        r"^<!-- prism:deal-room-answer (?P<attributes>[^>]+) -->\n(?P<body>.*)$",
        str(message.get("content", "")),
        re.S,
    )
    if marker is None:
        return None
    attributes = marker.group("attributes")

    def attribute(name: str) -> str | None:
        match = re.search(rf"(?:^|\s){re.escape(name)}=([^ ]+)", attributes)
        return match.group(1) if match else None

    trace_id = attribute("trace")
    candidates = [trace for trace in traces if trace.trace_id == trace_id]
    if len(candidates) != 1:
        return None
    trace = candidates[0]
    metadata = trace.metadata
    if (
        trace.session_id != room_id
        or attribute("guard") != DEAL_ROOM_CHAT_GUARD_VERSION
        or metadata.get("guard_version") != DEAL_ROOM_CHAT_GUARD_VERSION
        or attribute("source_class") != metadata.get("source_classification")
        or attribute("provenance") != metadata.get("source_provenance_sha256")
        or attribute("source_snapshot") != metadata.get("source_snapshot_sha256")
    ):
        return None
    body = marker.group("body").strip()
    model = attribute("model")
    if model == "rejected":
        expected = (
            "**Bonsai answer rejected**\n\n"
            + str(metadata.get("rejection_explanation", ""))
            + f"\n\nTrace: `{trace.trace_id}`. No answer or accuracy claim was accepted."
        )
        if (
            metadata.get("rejection_event_id") != event_id
            or not str(metadata.get("result_state", "")).startswith("rejected_")
            or body != expected
        ):
            return None
        return "rejected"
    if (
        attribute("source_class") != current_provenance.get("classification")
        or attribute("provenance") != current_provenance.get("binding_sha256")
        or attribute("source_snapshot") != current_source_snapshot
        or metadata.get("answer_event_id") != event_id
        or metadata.get("result_state") != "guard_passed_and_signed_to_buzz"
        or trace.model_name != model
        or trace.response.strip() != body
    ):
        return None
    if current_evidence_inventory is not None and evidence_scope_for_anchors(
        current_evidence_inventory,
        metadata.get("retrieved_anchors", []),
    ) is None:
        return None
    return "accepted"


def local_review_message_content(
    draft: Dict[str, Any], review: Dict[str, Any],
) -> str:
    """Return the exact signed Buzz message for one local operator review.

    A deterministic evidence packet is reviewable, but it is never renamed to
    a first pass brief. Keeping the review subject in the signed text prevents
    an operator action from laundering a rejected model run into a product
    success artifact.
    """
    evidence_packet = draft.get("artifact_mode") == "evidence_safe_fallback"
    heading = "Source evidence packet reviewed" if evidence_packet else "First pass draft reviewed"
    subject = "deterministic source evidence packet" if evidence_packet else "Bonsai first pass draft"
    return (
        f"## {heading}\n\n"
        f"Review subject: {subject}\n\n"
        f"Artifact mode: {draft.get('artifact_mode', 'model_draft')}\n\n"
        f"Decision: {str(review['decision']).upper()}\n\n"
        f"Useful starting point: {'Yes' if review['useful_starting_point'] else 'No'}\n\n"
        f"Critical corrections: {review['critical_corrections']}\n\n"
        f"Major corrections: {review['major_corrections']}\n\n"
        f"Notes: {review['notes'] or 'None recorded.'}"
    )


def local_review_canvas_content(
    room_name: str,
    draft: Dict[str, Any],
    review: Dict[str, Any],
) -> str:
    """Return the exact Buzz canvas published for one local operator review."""
    evidence_packet = draft.get("artifact_mode") == "evidence_safe_fallback"
    reviewed_heading = (
        "Reviewed source evidence packet" if evidence_packet else "Reviewed first pass draft"
    )
    boundary = (
        "This canvas contains a deterministic source-excerpt packet created after the "
        "Bonsai draft was rejected. Operator review does not convert it into an "
        "underwriting brief or a model pass."
        if evidence_packet else
        "This is a locally reviewed Bonsai draft. It is not independent benchmark domain review."
    )
    return (
        f"# {room_name}\n\n"
        "## Local operator review\n\n"
        f"Decision: {str(review['decision']).upper()}\n\n"
        f"Useful starting point: {'Yes' if review['useful_starting_point'] else 'No'}\n\n"
        f"Critical corrections: {review['critical_corrections']}\n\n"
        f"Major corrections: {review['major_corrections']}\n\n"
        f"Operator notes: {review['notes'] or 'None recorded.'}\n\n"
        f"Draft event: {draft.get('draft_event_id', 'unknown')}\n\n"
        f"Artifact mode: {draft.get('artifact_mode', 'model_draft')}\n\n"
        f"Authored by: {draft.get('authored_by', 'local_bonsai')}\n\n"
        f"Rejected model trace: {draft.get('model_failure_trace_id', 'Not applicable')}\n\n"
        f"Review boundary: {boundary}\n\n"
        f"## {reviewed_heading}\n\n"
        f"{draft['markdown']}"
    )


def restore_trace_bound_local_review(
    claimed_review: Dict[str, Any],
    *,
    draft: Dict[str, Any],
    room_id: str,
    room_name: str,
    operator_pubkey: str,
    review_event: Dict[str, Any],
    canvas_event: Dict[str, Any],
) -> Dict[str, Any]:
    """Validate a persisted review against its two signed Buzz events."""
    required_fields = {
        "review_actor",
        "reviewer_pubkey",
        "authentication_scope",
        "benchmark_domain_review",
        "decision",
        "useful_starting_point",
        "critical_corrections",
        "major_corrections",
        "notes",
        "review_event_id",
        "canvas_event_id",
        "canonical_path",
    }
    if set(claimed_review) != required_fields:
        raise BuzzUnavailable("Persisted local review has an invalid shape")
    if (
        claimed_review.get("review_actor") != "local_operator"
        or claimed_review.get("reviewer_pubkey") != operator_pubkey
        or claimed_review.get("authentication_scope") != "local_operator_bridge"
        or claimed_review.get("benchmark_domain_review") is not False
        or claimed_review.get("decision") not in {"advance", "pause", "stop"}
        or not isinstance(claimed_review.get("useful_starting_point"), bool)
        or claimed_review.get("canonical_path") != f"/rooms/{room_id}/digest"
    ):
        raise BuzzUnavailable("Persisted local review identity or decision is invalid")
    for field in ("critical_corrections", "major_corrections"):
        value = claimed_review.get(field)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise BuzzUnavailable(f"Persisted local review has invalid {field}")
    notes = claimed_review.get("notes")
    if not isinstance(notes, str) or len(notes) > 8_000:
        raise BuzzUnavailable("Persisted local review notes are invalid")

    review_event_id = str(claimed_review.get("review_event_id", ""))
    canvas_event_id = str(claimed_review.get("canvas_event_id", ""))
    if not re.fullmatch(r"[0-9a-f]{64}", review_event_id) or not re.fullmatch(
        r"[0-9a-f]{64}", canvas_event_id
    ):
        raise BuzzUnavailable("Persisted local review event identity is invalid")
    if (
        review_event.get("id") != review_event_id
        or review_event.get("pubkey") != operator_pubkey
        or review_event.get("content") != local_review_message_content(draft, claimed_review)
    ):
        raise BuzzUnavailable("Signed local review message does not match the persisted review")
    if (
        canvas_event.get("id") != canvas_event_id
        or canvas_event.get("kind") != 40100
        or canvas_event.get("pubkey") != operator_pubkey
        or canvas_event.get("content")
        != local_review_canvas_content(room_name, draft, claimed_review)
    ):
        raise BuzzUnavailable("Signed local review canvas does not match the persisted review")
    return {
        **claimed_review,
        "restored_from_buzz": True,
        "signature_verification": {
            "state": "verified",
            "scheme": "nip01_event_id_plus_bip340",
            "author_pubkey": operator_pubkey,
            "review_event_id": review_event_id,
            "canvas_event_id": canvas_event_id,
        },
    }


def all_deal_rooms() -> Dict[str, Dict[str, Any]]:
    """Return built-in and persisted operator-selected folders."""
    global CUSTOM_DEAL_ROOM_REGISTRY_IDENTITY
    with CUSTOM_DEAL_ROOM_LOCK:
        current_identity = _local_registry_identity(CUSTOM_DEAL_ROOM_REGISTRY)
        if current_identity != CUSTOM_DEAL_ROOM_REGISTRY_IDENTITY:
            restored = load_local_deal_rooms(CUSTOM_DEAL_ROOM_REGISTRY)
            CUSTOM_DEAL_ROOMS.clear()
            CUSTOM_DEAL_ROOMS.update(restored)
            CUSTOM_DEAL_ROOM_REGISTRY_IDENTITY = current_identity
        rooms = {**DEAL_ROOM_CATALOG, **CUSTOM_DEAL_ROOMS}
        return {
            room_id: {**room, "source_provenance": room_source_provenance(room)}
            for room_id, room in rooms.items()
        }


def prepare_local_deal_room(folder_path: str) -> Dict[str, Any]:
    """Validate a local folder and prepare a durable room record."""
    return inspect_local_deal_room(folder_path)["room"]


def inspect_local_deal_room(folder_path: str) -> Dict[str, Any]:
    """Parse a folder without registration or Buzz writes and bind a preview hash."""
    if not isinstance(folder_path, str) or not folder_path.strip():
        raise ValueError("folder_path is required")
    requested = Path(os.path.expanduser(folder_path.strip()))
    if not requested.exists():
        raise FileNotFoundError("folder does not exist")
    resolved = requested.resolve(strict=True)
    if not resolved.is_dir():
        raise NotADirectoryError("folder_path is not a directory")
    if not os.access(resolved, os.R_OK | os.X_OK):
        raise PermissionError("folder is not readable")

    parser = DealRoomParser()
    docs = parser.parse_deal_room_folder(str(resolved))
    room_id = "local_" + hashlib.sha256(str(resolved).encode("utf-8")).hexdigest()[:12]
    room = {
        "id": room_id,
        "name": resolved.name or str(resolved),
        "target": "Operator-selected local folder",
        "type": "Private folder",
        "path": str(resolved),
        "description": (
            f"Persisted local folder registration: {len(docs)} supported files; "
            f"{len(parser.last_warnings)} parse warnings."
        ),
    }
    files = [
        {
            "filename": document.filename,
            "file_type": document.file_type,
            "raw_size_bytes": document.raw_size_bytes,
            "estimated_tokens": document.estimated_token_count,
            "table_count": len(document.extracted_tables),
            "source_sha256": document.metadata.get("source_sha256"),
        }
        for document in docs
    ]
    binding = {
        "schema_version": 1,
        "folder_path": str(resolved),
        "room_id": room_id,
        "files": files,
        "warnings": parser.last_warnings,
    }
    preview_sha256 = hashlib.sha256(
        json.dumps(binding, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return {
        "room": room,
        "documents": docs,
        "warnings": list(parser.last_warnings),
        "preview": {
            "verification_kind": "local_deal_room_preview",
            "preview_state": "ready" if docs else "blocked_no_supported_files",
            "preview_sha256": preview_sha256,
            "room_id": room_id,
            "room_name": room["name"],
            "source_provenance": room_source_provenance(room),
            "folder_path": str(resolved),
            "document_count": len(files),
            "total_size_bytes": sum(item["raw_size_bytes"] for item in files),
            "estimated_tokens": sum(item["estimated_tokens"] for item in files),
            "files": files,
            "warnings": list(parser.last_warnings),
            "source_files_stay_local": True,
            "buzz_write_performed": False,
            "room_registered": False,
        },
    }


def commit_local_deal_room(
    room: Dict[str, Any], registry_path: Path | None = None,
) -> None:
    """Persist one room without losing registrations from concurrent requests."""
    global CUSTOM_DEAL_ROOM_REGISTRY_IDENTITY
    registry_path = registry_path or CUSTOM_DEAL_ROOM_REGISTRY
    admitted = _validated_local_room_record(room)
    with local_deal_room_registry_transaction(registry_path):
        current = load_local_deal_rooms(registry_path)
        existing = current.get(admitted["id"])
        if existing is not None and existing != admitted:
            raise ValueError("custom deal-room registration differs for the canonical room ID")
        updated = {**current, admitted["id"]: admitted}
        persist_local_deal_rooms(updated, registry_path)
        CUSTOM_DEAL_ROOMS.clear()
        CUSTOM_DEAL_ROOMS.update(updated)
        if registry_path.resolve() == CUSTOM_DEAL_ROOM_REGISTRY.resolve():
            CUSTOM_DEAL_ROOM_REGISTRY_IDENTITY = _local_registry_identity(registry_path)

# Research catalog. This is not runtime discovery or performance evidence.
BONSAI_MODELS = {
    "ternary_bonsai_27b": {
        "id": "ternary_bonsai_27b",
        "name": "Ternary Bonsai 27B",
        "tier_role": "Research candidate for deal-room and coding workloads",
        "is_flagship": True
    },
    "1bit_bonsai_27b": {
        "id": "1bit_bonsai_27b",
        "name": "1-Bit Bonsai 27B",
        "tier_role": "Unverified research candidate for constrained-memory deployment",
        "is_flagship": False
    },
    "ternary_bonsai_8b": {
        "id": "ternary_bonsai_8b",
        "name": "Ternary Bonsai 8B",
        "tier_role": "Unverified research candidate for smaller local tasks",
        "is_flagship": False
    },
    "bonsai_image_4b": {
        "id": "bonsai_image_4b",
        "name": "Bonsai Image 4B (FLUX.2 Klein)",
        "tier_role": "Unverified research candidate for visual workflows",
        "is_flagship": False
    }
}

for _model in BONSAI_MODELS.values():
    _model["artifact_available"] = None
    _model["runtime_loaded"] = None
    _model["status"] = "catalog_only_not_runtime_discovery"
    _model["measurement_state"] = "unverified"
    _model["warning"] = (
        "Catalog membership does not prove artifact presence, model loading, quality, or performance."
    )

# Shared state
SERVER_PROCESS_STARTED_AT = time.time()
global_tracer = ArizeObservabilityTracer()
global_router = HybridAIRouter(default_local_only_policy=True)
global_providers = ProviderRegistry()
global_buzz = BuzzBridge(PROJECT_ROOT)
global_evaluation_experiments = ExperimentStore(EVALUATION_EXPERIMENT_DATA)
_demo_channel = PROJECT_ROOT / ".runtime" / "buzz" / "demo-channel-id"
try:
    if _demo_channel.exists() and global_buzz.room(DEFAULT_ROOM) is None:
        global_buzz.bind_existing_room(DEFAULT_ROOM, _demo_channel.read_text().strip())
except BuzzUnavailable:
    # Status and workspace APIs expose the registry error. Startup does not
    # overwrite or reinterpret corrupt persistent state.
    pass


class VaultHTTPRequestHandler(http.server.SimpleHTTPRequestHandler):
    MAX_REQUEST_BYTES = 1024 * 1024

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=STATIC_DIR, **kwargs)

    def end_headers(self):
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'none'",
        )
        if self.path.startswith("/api/"):
            self.send_header("Cache-Control", "no-store")
        elif urllib.parse.urlparse(self.path).path.endswith(".html"):
            self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def _local_request_headers(self) -> bool:
        """Reject DNS-rebinding/cross-origin API requests to the loopback service."""
        allowed = {"127.0.0.1", "localhost", "::1"}
        host = urllib.parse.urlsplit("//" + self.headers.get("Host", "")).hostname
        if host not in allowed:
            return False
        origin = self.headers.get("Origin")
        if origin and urllib.parse.urlsplit(origin).hostname not in allowed:
            return False
        return True

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        query_params = urllib.parse.parse_qs(parsed.query)

        if path.startswith("/api/") and not self._local_request_headers():
            self._send_json({"error": "local_origin_required"}, status=403)
            return

        if path == "/api/status":
            try:
                self._send_json(self._get_status_data())
            except ValueError as exc:
                self._send_json({
                    "error": "trace_store_integrity_error",
                    "detail": str(exc),
                }, status=503)
        elif path == "/api/deal-rooms":
            self._send_json(list(all_deal_rooms().values()))
        elif path == "/api/models":
            self._send_json({
                "provider_status": [status.__dict__ for status in global_providers.statuses()],
                "meaning": (
                    "Configured provider metadata only. This endpoint does not prove reachability, "
                    "a loaded model, invocation, quality, or performance."
                ),
                "research_catalog_path": "/api/research/model-catalog",
            })
        elif path == "/api/research/model-catalog":
            self._send_json({
                "measurement_state": "unverified_research_catalog",
                "models": list(BONSAI_MODELS.values()),
                "warning": (
                    "Catalog entries are product research candidates and are not runtime discovery."
                ),
            })
        elif path == "/api/deal-room":
            room_id = query_params.get("room", [DEFAULT_ROOM])[0]
            if room_id not in all_deal_rooms():
                self._send_json({"error": "unknown_deal_room", "deal_room": room_id}, status=404)
            else:
                self._send_json(self._get_deal_room_data(room_id))
        elif path == "/api/evals":
            try:
                self._send_json(self._get_evals_data())
            except ValueError as exc:
                self._send_json({
                    "error": "trace_store_integrity_error",
                    "detail": str(exc),
                }, status=503)
        elif path == "/api/build-vs-buy":
            self._send_json(self._get_build_vs_buy_data())
        elif path == "/api/workspace":
            room_id = query_params.get("room", [DEFAULT_ROOM])[0]
            self._send_workspace(room_id)
        elif path == "/api/workspace/messages":
            room_id = query_params.get("room", [DEFAULT_ROOM])[0]
            self._send_workspace_messages(room_id)
        elif path == "/api/workspace/digest":
            room_id = query_params.get("room", [DEFAULT_ROOM])[0]
            self._send_workspace_digest(room_id)
        elif path == "/api/workspace/first-pass":
            room_id = query_params.get("room", [DEFAULT_ROOM])[0]
            self._send_workspace_first_pass(room_id)
        elif path == "/api/workspace/evaluation":
            room_id = query_params.get("room", [DEFAULT_ROOM])[0]
            self._send_workspace_evaluation(room_id)
        elif path == "/api/workspace/evaluation/dashboard":
            room_id = query_params.get("room", [DEFAULT_ROOM])[0]
            self._send_workspace_evaluation_dashboard(room_id)
        elif path == "/api/workspace/evaluation/experiments":
            room_id = query_params.get("room", [DEFAULT_ROOM])[0]
            if room_id not in all_deal_rooms():
                self._send_json({"error": "unknown_deal_room", "room": room_id}, status=404)
            else:
                left = query_params.get("left", [None])[0]
                right = query_params.get("right", [None])[0]
                try:
                    result = (
                        global_evaluation_experiments.compare(room_id, left, right)
                        if left and right else global_evaluation_experiments.snapshot(room_id)
                    )
                    self._send_json(result)
                except ValueError as exc:
                    self._send_json({"error": "invalid_experiment_record", "detail": str(exc)}, status=409)
        elif path == "/api/workspace/evaluation/observability":
            room_id = query_params.get("room", [DEFAULT_ROOM])[0]
            include_content = query_params.get("include_content", ["false"])[0] == "true"
            self._send_workspace_evaluation_observability(room_id, include_content)
        elif path == "/api/benchmark/source-review":
            draft_id = query_params.get("draft", [None])[0]
            self._send_candidate_source_review(draft_id)
        elif path == "/api/benchmark/source-review/context":
            draft_id = query_params.get("draft", [None])[0]
            citation = query_params.get("citation", [None])[0]
            self._send_candidate_source_context(draft_id, citation)
        elif path == "/api/benchmark/pipeline":
            self._send_benchmark_pipeline()
        elif path == "/api/benchmark/oracle-diagnostic":
            self._send_oracle_context_diagnostic()
        elif path == "/api/benchmark/case-authoring":
            draft_id = query_params.get("draft", [None])[0]
            self._send_candidate_case_authoring(draft_id)
        elif path == "/api/benchmark/output-review":
            case_id = query_params.get("case", [None])[0]
            self._send_output_review(case_id)
        elif path == "/api/benchmark/pricing-poc":
            self._send_pricing_poc()
        elif path == "/favicon.ico":
            # Browsers request this implicitly. An explicit empty response keeps
            # the verified workspace free of a misleading static-file 404.
            self.send_response(204)
            self.send_header("Content-Length", "0")
            self.end_headers()
        elif path == "/benchmark/source-review":
            self.path = "/source-review.html"
            super().do_GET()
        elif path == "/benchmark/case-authoring":
            self.path = "/case-authoring.html"
            super().do_GET()
        elif path == "/benchmark/output-review":
            self.path = "/output-review.html"
            super().do_GET()
        elif path == "/benchmark/pricing-poc":
            self.path = "/pricing-poc.html"
            super().do_GET()
        elif path == "/" or path.startswith("/rooms/") or path.startswith("/runs/"):
            self.path = "/index.html"
            super().do_GET()
        else:
            super().do_GET()

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        if path.startswith("/api/") and not self._local_request_headers():
            self._send_json({"error": "local_origin_required"}, status=403)
            return
        try:
            content_len = int(self.headers.get("Content-Length", 0))
        except ValueError:
            self._send_json({"error": "invalid_content_length"}, status=400)
            return
        if content_len < 0 or content_len > self.MAX_REQUEST_BYTES:
            self._send_json({"error": "request_too_large"}, status=413)
            return
        body = self.rfile.read(content_len).decode("utf-8") if content_len > 0 else "{}"
        try:
            payload = json.loads(body)
            if not isinstance(payload, dict):
                raise ValueError("JSON body must be an object")
        except (json.JSONDecodeError, UnicodeDecodeError, ValueError) as exc:
            self._send_json({"error": "invalid_json", "detail": str(exc)}, status=400)
            return

        if path == "/api/audit":
            room_id = payload.get("deal_room", DEFAULT_ROOM)
            rooms = all_deal_rooms()
            if room_id not in rooms:
                self._send_json({"error": "unknown_deal_room", "deal_room": room_id}, status=404)
                return
            room_path = rooms[room_id]["path"]
            analyzer = DealRoomAnalyzer(room_path)
            report = analyzer.run_full_audit()
            
            report_dict = {
                "report_id": report.report_id,
                "deal_name": rooms[room_id].get("name", report.deal_name),
                "timestamp": report.timestamp,
                "total_documents_analyzed": report.total_documents_analyzed,
                "total_tokens_ingested": report.total_tokens_ingested,
                "operational_vram_gb": report.operational_vram_gb,
                "covenant_findings": [
                    {
                        "covenant_name": f.covenant_name,
                        "section_ref": f.section_ref,
                        "threshold": f.threshold,
                        "actual_value": f.actual_value,
                        "status": f.status,
                        "risk_level": f.risk_level,
                        "detail": f.detail,
                        "remediation": f.remediation,
                    }
                    for f in report.covenant_findings
                ],
                "executive_summary": report.executive_summary,
                "sandbox_execution_logs": report.sandbox_execution_logs,
                "arize_trace_id": report.arize_trace_id,
                "evaluation_summary": report.evaluation_summary,
            }
            # Record in global tracer
            if analyzer.tracer.traces:
                global_tracer.record_trace(analyzer.tracer.traces[0])
            self._send_json(report_dict)

        elif path == "/api/agent/run":
            prompt = str(payload.get("prompt", "")).strip()
            room_id = payload.get("deal_room", DEFAULT_ROOM)
            if not prompt:
                self._send_json({"error": "prompt_required"}, status=400)
                return
            rooms = all_deal_rooms()
            if room_id not in rooms:
                self._send_json({"error": "unknown_deal_room", "deal_room": room_id}, status=404)
                return
            room_path = rooms[room_id]["path"]

            force_cloud = bool(payload.get("force_cloud_override", False))
            local_only_policy = bool(payload.get("local_only_policy", True))
            runtime = payload.get("runtime", "auto")
            if runtime not in {"auto", "baseline", "local", "cloud"}:
                self._send_json({"error": "invalid_runtime"}, status=400)
                return
            if runtime == "local" and not global_providers.local.configured:
                self._send_json({"error": "local_provider_not_configured"}, status=409)
                return
            if runtime == "cloud" and not global_providers.cloud.configured:
                self._send_json({"error": "cloud_provider_not_configured"}, status=409)
                return
            force_cloud = force_cloud or runtime == "cloud"
            local_only_policy = False if runtime == "cloud" else local_only_policy
            agent = DealRoomWorkflowAgent(
                room_path,
                tracer=global_tracer,
                providers=global_providers,
                cloud_consent_event_resolver=lambda event_ids, channel_id: (
                    global_buzz.events_by_ids(event_ids, channel_id=channel_id)
                ),
            )
            try:
                res = agent.execute_task(prompt, force_cloud_override=force_cloud,
                                         local_only_policy=local_only_policy,
                                         force_baseline=runtime == "baseline",
                                         allow_cloud_context=bool(payload.get("allow_cloud_context", False)),
                                         cloud_consent_bundle=payload.get("cloud_consent"),
                                         cloud_room_id=str(room_id))
            except ValueError as exc:
                if "cloud dispatch denied before provider invocation" in str(exc):
                    self._send_json({
                        "error": "cloud_consent_required",
                        "detail": str(exc),
                    }, status=403)
                    return
                self._send_json({"error": "agent_execution_failed", "detail": str(exc)}, status=502)
                return
            except Exception as exc:
                self._send_json({"error": "agent_execution_failed", "detail": str(exc)}, status=502)
                return
            
            res_dict = {
                "query": res.query,
                "model_used": res.model_name,
                "provider_id": res.provider_id,
                "execution_mode": res.execution_mode,
                "generation_attempts": res.generation_attempts,
                "rejected_scope_violations": res.rejected_scope_violations,
                "evidence_sources": res.evidence_sources,
                "limitations": res.limitations,
                "deal_room": rooms[room_id].get("name", room_id),
                "steps": [
                    {
                        "step_number": s.step_number,
                        "thought": s.thought,
                        "action": s.action,
                        "input_payload": s.input_payload,
                        "output_payload": s.output_payload,
                        "status": s.status,
                        "latency_ms": s.latency_ms,
                    }
                    for s in res.steps
                ],
                "final_answer": res.final_answer,
                "generated_code": res.generated_code,
                "code_execution_stdout": res.code_execution_stdout,
                "routing_info": {
                    "target_tier": res.routing_info.target_tier,
                    "reason": res.routing_info.reason,
                    "is_local_only_policy": res.routing_info.is_local_only_policy,
                    "redaction_applied": res.routing_info.redaction_applied,
                    "sanitized_prompt": res.routing_info.sanitized_prompt,
                    "estimated_cost_usd": res.routing_info.estimated_cost_usd,
                    "estimated_energy_mwh_per_token": res.routing_info.estimated_energy_mwh_per_token,
                },
                "trace_id": res.trace_id,
                "evaluations": res.evaluations,
                "energy_mwh": res.energy_mwh,
                "latency_ms": res.latency_ms,
            }
            self._send_json(res_dict)

        elif path == "/api/benchmark":
            runtime = payload.get("runtime", "baseline")
            if runtime not in {"baseline", "local", "cloud"}:
                self._send_json({"error": "invalid_runtime"}, status=400)
                return
            if runtime == "local" and not global_providers.local.configured:
                self._send_json({"error": "local_provider_not_configured"}, status=409)
                return
            if runtime == "cloud" and not global_providers.cloud.configured:
                self._send_json({"error": "cloud_provider_not_configured"}, status=409)
                return
            report = run_benchmark(
                "benchmarks/deal_room_reliability.json", DEAL_ROOM_CATALOG,
                runtime=runtime, providers=global_providers,
                allow_cloud_context=bool(payload.get("allow_cloud_context", False)),
                cloud_consent_bundles=payload.get("cloud_consents"),
                cloud_consent_event_resolver=lambda event_ids, channel_id: (
                    global_buzz.events_by_ids(event_ids, channel_id=channel_id)
                ),
            )
            self._send_json(report.to_dict())

        elif path == "/api/deal-room/preview":
            try:
                inspection = inspect_local_deal_room(payload.get("folder_path", ""))
            except FileNotFoundError as exc:
                self._send_json({"error": "folder_not_found", "detail": str(exc)}, status=404)
                return
            except (ValueError, NotADirectoryError, PermissionError, OSError) as exc:
                self._send_json({"error": "folder_unavailable", "detail": str(exc)}, status=400)
                return
            self._send_json(inspection["preview"])

        elif path == "/api/deal-room/open":
            try:
                inspection = inspect_local_deal_room(payload.get("folder_path", ""))
                room = inspection["room"]
                documents = inspection["documents"]
                warnings = inspection["warnings"]
                preview = inspection["preview"]
                if not documents:
                    self._send_json({
                        "error": "no_supported_files",
                        "detail": "No supported files were available to index.",
                        "preview": preview,
                    }, status=400)
                    return
                supplied_preview = payload.get("preview_sha256")
                if not supplied_preview:
                    self._send_json({
                        "error": "deal_room_preview_required",
                        "detail": "Preview the folder before creating its Buzz room.",
                        "preview": preview,
                    }, status=409)
                    return
                if supplied_preview != preview["preview_sha256"]:
                    self._send_json({
                        "error": "deal_room_changed_since_preview",
                        "detail": "The folder changed after preview. Review the updated files before creating the room.",
                        "preview": preview,
                    }, status=409)
                    return
                workspace = global_buzz.ensure_room(
                    room,
                    len(documents),
                    len(warnings),
                )
                commit_local_deal_room(room)
                data = self._get_deal_room_data(room["id"])
            except FileNotFoundError as exc:
                self._send_json({"error": "folder_not_found", "detail": str(exc)}, status=404)
                return
            except BuzzUnavailable as exc:
                self._send_json({"error": "buzz_unavailable", "detail": str(exc)}, status=503)
                return
            except (ValueError, NotADirectoryError, PermissionError, OSError) as exc:
                self._send_json({"error": "folder_unavailable", "detail": str(exc)}, status=400)
                return
            data["workspace"] = workspace
            data["canonical_path"] = f"/rooms/{room['id']}"
            self._send_json(data, status=201)

        elif path == "/api/workspace/messages":
            room_id = str(payload.get("room", DEFAULT_ROOM))
            content = str(payload.get("content", "")).strip()
            # Strip textual "@Bonsai" mentions. buzz-cli parses @handle mentions
            # out of the message body and resolves them against channel members,
            # but `channels add-member` accepts only --pubkey/--role -- members
            # have no names -- so a textual mention can NEVER resolve and the
            # send fails with "mention '@bonsai' does not match a current
            # channel member". Addressing the agent is done properly below via
            # ask_bonsai -> `--mention <agent_pubkey>`. Stripped here rather
            # than only in the client so a cached app.js, another caller, or an
            # operator typing "@bonsai" by hand cannot break sending.
            content = re.sub(r"(?i)(?:^|\s)@bonsai\b[,:]?\s*", " ", content).strip()
            if not content:
                self._send_json({"error": "message_required"}, status=400)
                return
            if len(content) > 20_000:
                self._send_json({"error": "message_too_large"}, status=413)
                return
            binding_ok, workspace = self._buzz_room_binding(room_id)
            if not binding_ok:
                return
            if workspace is None:
                self._send_json({"error": "workspace_not_bound", "room": room_id}, status=409)
                return
            try:
                event = global_buzz.send(
                    workspace["channel_id"], content, ask_bonsai=False,
                )
            except BuzzUnavailable as exc:
                self._send_json({"error": "buzz_unavailable", "detail": str(exc)}, status=503)
                return
            event["canonical_path"] = (
                f"/rooms/{room_id}/discussion?event={event.get('event_id', '')}"
            )
            if bool(payload.get("ask_bonsai", False)):
                room = all_deal_rooms().get(room_id)
                if room is None:
                    self._send_json({"error": "unknown_deal_room", "room": room_id}, status=404)
                    return
                try:
                    initial_source_snapshot = inspect_local_deal_room(
                        room["path"],
                    )["preview"]["preview_sha256"]
                    initial_provenance = source_provenance_binding(room)
                except (FileNotFoundError, ValueError, NotADirectoryError, PermissionError, OSError) as exc:
                    self._send_json({
                        "error": "deal_room_source_unavailable",
                        "detail": str(exc),
                        "question_event": event,
                    }, status=409)
                    return
                started_at = time.time()
                trace_id = global_tracer.start_trace(room_id, "deal_room_chat")
                try:
                    answer = answer_deal_room_question(
                        room["path"], content, global_providers.local,
                    )
                    try:
                        current_source_snapshot = inspect_local_deal_room(
                            room["path"],
                        )["preview"]["preview_sha256"]
                        current_provenance = source_provenance_binding(room)
                    except (
                        FileNotFoundError, ValueError, NotADirectoryError,
                        PermissionError, OSError,
                    ) as snapshot_exc:
                        raise DealRoomChatError(
                            "The deal room became unavailable before answer publication",
                            metadata={
                                "source_snapshot_state": "unavailable_during_chat",
                                "source_snapshot_before": initial_source_snapshot,
                                "source_snapshot_after": None,
                                "source_snapshot_error": str(snapshot_exc),
                                "rejected_response": answer.response,
                                "usage": answer.usage,
                                "model": answer.model,
                                "provider_id": answer.provider,
                            },
                        ) from snapshot_exc
                    if (
                        current_source_snapshot != initial_source_snapshot
                        or current_provenance != initial_provenance
                    ):
                        raise DealRoomChatError(
                            "The deal room or its provenance changed before answer publication",
                            metadata={
                                "source_snapshot_state": "changed_during_chat",
                                "source_snapshot_before": initial_source_snapshot,
                                "source_snapshot_after": current_source_snapshot,
                                "source_provenance_before": initial_provenance,
                                "source_provenance_after": current_provenance,
                                "rejected_response": answer.response,
                                "usage": answer.usage,
                                "model": answer.model,
                                "provider_id": answer.provider,
                            },
                        )
                    reply_content = (
                        f"<!-- prism:deal-room-answer model={answer.model} "
                        f"guard={answer.guard_version} trace={trace_id} "
                        f"source_class={initial_provenance['classification']} "
                        f"provenance={initial_provenance['binding_sha256']} "
                        f"source_snapshot={initial_source_snapshot} -->\n"
                        f"{answer.response}"
                    )
                    reply_event = global_buzz.send_as_agent(
                        workspace["channel_id"], reply_content,
                    )
                    try:
                        post_publish_source_snapshot = inspect_local_deal_room(
                            room["path"],
                        )["preview"]["preview_sha256"]
                        post_publish_provenance = source_provenance_binding(room)
                    except (
                        FileNotFoundError, ValueError, NotADirectoryError,
                        PermissionError, OSError,
                    ) as snapshot_exc:
                        raise DealRoomChatError(
                            "The deal room became unavailable during answer publication",
                            metadata={
                                "source_snapshot_state": "unavailable_during_publication",
                                "source_snapshot_before": initial_source_snapshot,
                                "source_snapshot_after": None,
                                "source_snapshot_error": str(snapshot_exc),
                                "published_answer_event_id": reply_event.get("event_id"),
                                "rejected_response": answer.response,
                                "usage": answer.usage,
                                "model": answer.model,
                                "provider_id": answer.provider,
                            },
                        ) from snapshot_exc
                    if (
                        post_publish_source_snapshot != initial_source_snapshot
                        or post_publish_provenance != initial_provenance
                    ):
                        raise DealRoomChatError(
                            "The deal room or its provenance changed during answer publication",
                            metadata={
                                "source_snapshot_state": "changed_during_publication",
                                "source_snapshot_before": initial_source_snapshot,
                                "source_snapshot_after": post_publish_source_snapshot,
                                "source_provenance_before": initial_provenance,
                                "source_provenance_after": post_publish_provenance,
                                "published_answer_event_id": reply_event.get("event_id"),
                                "rejected_response": answer.response,
                                "usage": answer.usage,
                                "model": answer.model,
                                "provider_id": answer.provider,
                            },
                        )
                except DealRoomChatError as exc:
                    rejection_metadata = getattr(exc, "metadata", {})
                    rejected_response = str(rejection_metadata.get("rejected_response", ""))
                    rejected_usage = rejection_metadata.get("usage", {})
                    published_candidate = rejection_metadata.get("published_answer_event_id")
                    rejection_explanation = (
                        "Prism published a signed candidate event, but did not accept it because "
                        "the source binding changed during publication. The workspace quarantines "
                        "that candidate event."
                        if published_candidate else
                        "Prism saved the question but did not publish the model draft because it "
                        f"failed the evidence guard: {exc}"
                    )
                    rejection_content = (
                        f"<!-- prism:deal-room-answer model=rejected "
                        f"guard={DEAL_ROOM_CHAT_GUARD_VERSION} trace={trace_id} "
                        f"source_class={initial_provenance['classification']} "
                        f"provenance={initial_provenance['binding_sha256']} "
                        f"source_snapshot={initial_source_snapshot} -->\n"
                        "**Bonsai answer rejected**\n\n"
                        f"{rejection_explanation}\n\n"
                        f"Trace: `{trace_id}`. No answer or accuracy claim was accepted."
                    )
                    try:
                        rejection_event = global_buzz.send_as_agent(
                            workspace["channel_id"], rejection_content,
                        )
                    except BuzzUnavailable as buzz_exc:
                        self._send_json({
                            "error": "buzz_unavailable", "detail": str(buzz_exc),
                            "question_event": event, "trace_id": trace_id,
                        }, status=503)
                        return
                    global_tracer.record_trace(ArizeTraceRecord(
                        trace_id=trace_id,
                        session_id=room_id,
                        timestamp=started_at,
                        query=content,
                        response=rejected_response,
                        model_name=str(
                            rejection_metadata.get("model")
                            or global_providers.local.model
                            or "unknown"
                        ),
                        routed_tier="LOCAL_BONSAI_27B",
                        total_tokens=rejected_usage.get("total_tokens"),
                        prompt_tokens=rejected_usage.get("prompt_tokens"),
                        completion_tokens=rejected_usage.get("completion_tokens"),
                        total_latency_ms=(
                            rejection_metadata.get("latency_ms")
                            or (time.time() - started_at) * 1000
                        ),
                        energy_per_token_mwh=None,
                        total_energy_mwh=None,
                        vram_peak_gb=None,
                        evaluations=[EvalMetric(
                            name="deal_room_chat_publication_guard",
                            score=0.0,
                            threshold=1.0,
                            passed=False,
                            explanation=str(exc),
                            metadata={"measurement_state": "rejected"},
                        )],
                        metadata={
                            "product_job": "deal_room_chat",
                            "guard_version": DEAL_ROOM_CHAT_GUARD_VERSION,
                            "provider_id": (
                                rejection_metadata.get("provider_id")
                                or global_providers.local.provider_id
                            ),
                            "question_event_id": event.get("event_id"),
                            "rejection_event_id": rejection_event.get("event_id"),
                            "result_state": (
                                "rejected_after_buzz_candidate_due_source_change"
                                if published_candidate else "rejected_before_buzz_answer"
                            ),
                            "orphaned_answer_event_id": published_candidate,
                            "rejection_explanation": rejection_explanation,
                            "error": str(exc),
                            "rejected_response_sha256": hashlib.sha256(
                                rejected_response.encode("utf-8")
                            ).hexdigest(),
                            "inference_attempts": rejection_metadata.get("inference_attempts"),
                            "guard_violations": rejection_metadata.get("violations", []),
                            "retrieved_anchors": rejection_metadata.get("retrieved_anchors", []),
                            "source_snapshot_sha256": initial_source_snapshot,
                            "source_classification": initial_provenance["classification"],
                            "source_provenance_sha256": initial_provenance["binding_sha256"],
                            "source_provenance": initial_provenance,
                            "source_snapshot_state": rejection_metadata.get(
                                "source_snapshot_state", "stable"
                            ),
                        },
                    ))
                    event["agent_reply"] = {
                        "answer_state": "rejected",
                        "detail": str(exc),
                        "event_id": rejection_event.get("event_id"),
                        "trace_id": trace_id,
                        "canonical_path": (
                            f"/rooms/{room_id}/discussion?event="
                            f"{rejection_event.get('event_id', '')}"
                        ),
                    }
                    self._send_json(event, status=201)
                    return
                except BuzzUnavailable as exc:
                    self._send_json({
                        "error": "buzz_unavailable", "detail": str(exc),
                        "question_event": event,
                    }, status=503)
                    return
                usage = answer.usage
                global_tracer.record_trace(ArizeTraceRecord(
                    trace_id=trace_id,
                    session_id=room_id,
                    timestamp=started_at,
                    query=content,
                    response=answer.response,
                    model_name=answer.model,
                    routed_tier="LOCAL_BONSAI_27B",
                    total_tokens=usage.get("total_tokens"),
                    prompt_tokens=usage.get("prompt_tokens"),
                    completion_tokens=usage.get("completion_tokens"),
                    total_latency_ms=answer.latency_ms,
                    energy_per_token_mwh=None,
                    total_energy_mwh=None,
                    vram_peak_gb=None,
                    evaluations=[
                        EvalMetric(
                            name="deal_room_chat_publication_guard",
                            score=1.0,
                            threshold=1.0,
                            passed=True,
                            explanation=(
                                "Every detected requested part had a same-line citation to "
                                "qualifying retrieved evidence, claimed numbers appeared in "
                                "the cited passage, and material terms came from the source or "
                                "the user's question. This is a structural guard, not an accuracy score."
                            ),
                            metadata={
                                "guard_version": answer.guard_version,
                                "requested_parts": answer.requested_parts,
                                "part_citations": answer.part_citations,
                            },
                        ),
                        EvalMetric(
                            name="human_accuracy_review",
                            score=0.0,
                            threshold=1.0,
                            passed=False,
                            explanation="Unverified until a domain reviewer checks the answer.",
                            metadata={"measurement_state": "awaiting_domain_review"},
                        ),
                    ],
                    metadata={
                        "product_job": "deal_room_chat",
                        "guard_version": answer.guard_version,
                        "provider_id": answer.provider,
                        "question_event_id": event.get("event_id"),
                        "answer_event_id": reply_event.get("event_id"),
                        "result_state": "guard_passed_and_signed_to_buzz",
                        "requested_parts": answer.requested_parts,
                        "part_citations": answer.part_citations,
                        "retrieved_anchors": [
                            {
                                "citation": item["citation"],
                                "source_sha256": item.get("source_sha256"),
                                "requested_parts": item.get("requested_parts", []),
                            }
                            for item in answer.retrieved_passages
                        ],
                        "inference_attempts": answer.inference_attempts,
                        "runtime_input_tokens": usage.get("prompt_tokens"),
                        "runtime_completion_tokens": usage.get("completion_tokens"),
                        "source_snapshot_sha256": initial_source_snapshot,
                        "source_classification": initial_provenance["classification"],
                        "source_provenance_sha256": initial_provenance["binding_sha256"],
                        "source_provenance": initial_provenance,
                        "source_snapshot_state": "stable",
                        **answer.raw_metadata,
                    },
                ))
                event["agent_reply"] = {
                    **answer.to_dict(),
                    "event_id": reply_event.get("event_id"),
                    "trace_id": trace_id,
                    "source_snapshot_sha256": initial_source_snapshot,
                    "source_classification": initial_provenance["classification"],
                    "source_provenance_sha256": initial_provenance["binding_sha256"],
                    "source_provenance": initial_provenance,
                    "canonical_path": (
                        f"/rooms/{room_id}/discussion?event={reply_event.get('event_id', '')}"
                    ),
                }
            self._send_json(event, status=201)

        elif path == "/api/workspace/digest":
            room_id = str(payload.get("room", DEFAULT_ROOM))
            content = str(payload.get("content", "")).strip()
            if not content:
                self._send_json({"error": "digest_required"}, status=400)
                return
            binding_ok, workspace = self._buzz_room_binding(room_id)
            if not binding_ok:
                return
            if workspace is None:
                self._send_json({"error": "workspace_not_bound", "room": room_id}, status=409)
                return
            try:
                event = global_buzz.set_canvas(workspace["channel_id"], content)
            except BuzzUnavailable as exc:
                self._send_json({"error": "buzz_unavailable", "detail": str(exc)}, status=503)
                return
            event["canonical_path"] = f"/rooms/{room_id}/digest"
            self._send_json(event)

        elif path == "/api/workspace/first-pass":
            action = str(payload.get("action", "run"))
            room_id = str(payload.get("room", DEFAULT_ROOM))
            rooms = all_deal_rooms()
            if room_id not in rooms:
                self._send_json({"error": "unknown_deal_room", "room": room_id}, status=404)
                return
            binding_ok, workspace = self._buzz_room_binding(room_id)
            if not binding_ok:
                return
            if workspace is None:
                self._send_json({"error": "workspace_not_bound", "room": room_id}, status=409)
                return
            if action == "run":
                screen = str(payload.get("investment_screen", "")).strip()
                if not screen:
                    self._send_json({"error": "investment_screen_required"}, status=400)
                    return
                try:
                    initial_source_snapshot = inspect_local_deal_room(
                        rooms[room_id]["path"],
                    )["preview"]["preview_sha256"]
                    initial_provenance = source_provenance_binding(rooms[room_id])
                except (FileNotFoundError, ValueError, NotADirectoryError, PermissionError, OSError) as exc:
                    self._send_json({
                        "error": "deal_room_source_unavailable",
                        "detail": str(exc),
                    }, status=409)
                    return
                try:
                    question_event = global_buzz.send(
                        workspace["channel_id"],
                        "## First pass requested\n\n" + screen,
                    )
                    started_at = time.time()
                    result = generate_first_pass(
                        rooms[room_id]["path"], screen, global_providers.local,
                    )
                    try:
                        current_source_snapshot = inspect_local_deal_room(
                            rooms[room_id]["path"],
                        )["preview"]["preview_sha256"]
                        current_provenance = source_provenance_binding(rooms[room_id])
                    except (FileNotFoundError, ValueError, NotADirectoryError, PermissionError, OSError) as snapshot_exc:
                        raise FirstPassError(
                            "The deal room became unavailable while the first pass was running",
                            metadata={
                                "source_snapshot_state": "unavailable_during_run",
                                "source_snapshot_before": initial_source_snapshot,
                                "source_snapshot_after": None,
                                "source_snapshot_error": str(snapshot_exc),
                            },
                        ) from snapshot_exc
                    if current_source_snapshot != initial_source_snapshot:
                        raise FirstPassError(
                            "The deal room changed while the first pass was running",
                            metadata={
                                "source_snapshot_state": "changed_during_run",
                                "source_snapshot_before": initial_source_snapshot,
                                "source_snapshot_after": current_source_snapshot,
                            },
                        )
                    if current_provenance != initial_provenance:
                        raise FirstPassError(
                            "The deal room provenance changed while the first pass was running",
                            metadata={
                                "source_snapshot_state": "provenance_changed_during_run",
                                "source_snapshot_before": initial_source_snapshot,
                                "source_snapshot_after": current_source_snapshot,
                                "source_provenance_before": initial_provenance,
                                "source_provenance_after": current_provenance,
                            },
                        )
                    trace_id = global_tracer.start_trace(room_id, "first_pass_underwriting")
                    draft_content = (
                        f"<!-- prism:first-pass-draft model={result.model} "
                        f"recommendation={result.recommendation} guard={FIRST_PASS_GUARD_VERSION} "
                        f"trace={trace_id} "
                        f"source_class={initial_provenance['classification']} "
                        f"provenance={initial_provenance['binding_sha256']} "
                        f"source_snapshot={initial_source_snapshot} -->\n"
                        "# First pass underwriting draft\n\n"
                        f"{result.markdown}"
                    )
                    draft_event = global_buzz.send_as_agent(
                        workspace["channel_id"], draft_content,
                    )
                    try:
                        post_publish_source_snapshot = inspect_local_deal_room(
                            rooms[room_id]["path"],
                        )["preview"]["preview_sha256"]
                        post_publish_provenance = source_provenance_binding(rooms[room_id])
                    except (FileNotFoundError, ValueError, NotADirectoryError, PermissionError, OSError) as snapshot_exc:
                        raise FirstPassError(
                            "The deal room became unavailable during first pass publication",
                            metadata={
                                "source_snapshot_state": "unavailable_during_publication",
                                "source_snapshot_before": initial_source_snapshot,
                                "source_snapshot_after": None,
                                "source_snapshot_error": str(snapshot_exc),
                                "published_draft_event_id": draft_event.get("event_id"),
                                "provider_id": result.provider,
                                "model": result.model,
                                "latency_ms": result.latency_ms,
                                "usage": result.usage,
                            },
                        ) from snapshot_exc
                    if (
                        post_publish_source_snapshot != initial_source_snapshot
                        or post_publish_provenance != initial_provenance
                    ):
                        raise FirstPassError(
                            "The deal room or its provenance changed during first pass publication",
                            metadata={
                                "source_snapshot_state": "changed_during_publication",
                                "source_snapshot_before": initial_source_snapshot,
                                "source_snapshot_after": post_publish_source_snapshot,
                                "source_provenance_before": initial_provenance,
                                "source_provenance_after": post_publish_provenance,
                                "published_draft_event_id": draft_event.get("event_id"),
                                "provider_id": result.provider,
                                "model": result.model,
                                "latency_ms": result.latency_ms,
                                "usage": result.usage,
                            },
                        )
                except FirstPassError as exc:
                    failure_metadata = dict(exc.metadata)
                    if "source_snapshot_state" not in failure_metadata:
                        try:
                            failure_snapshot = inspect_local_deal_room(
                                rooms[room_id]["path"],
                            )["preview"]["preview_sha256"]
                        except (FileNotFoundError, ValueError, NotADirectoryError, PermissionError, OSError):
                            failure_snapshot = None
                        if failure_snapshot != initial_source_snapshot:
                            failure_metadata.update({
                                "source_snapshot_state": "changed_during_run",
                                "source_snapshot_before": initial_source_snapshot,
                                "source_snapshot_after": failure_snapshot,
                            })
                        else:
                            failure_metadata["source_snapshot_state"] = "stable"
                            failure_metadata["source_snapshot_before"] = initial_source_snapshot
                            failure_metadata["source_snapshot_after"] = failure_snapshot
                    failure_usage = failure_metadata.pop("usage", {})
                    failure_trace_id = global_tracer.start_trace(
                        room_id, "first_pass_underwriting_rejected",
                    )
                    global_tracer.record_trace(ArizeTraceRecord(
                        trace_id=failure_trace_id,
                        session_id=room_id,
                        timestamp=started_at,
                        query="first_pass_underwriting",
                        response="",
                        model_name=str(
                            failure_metadata.get("model")
                            or global_providers.local.model
                            or "unknown"
                        ),
                        routed_tier="LOCAL_BONSAI_27B",
                        total_tokens=failure_usage.get("total_tokens"),
                        prompt_tokens=failure_usage.get("prompt_tokens"),
                        completion_tokens=failure_usage.get("completion_tokens"),
                        total_latency_ms=float(
                            failure_metadata.get("latency_ms", (time.time() - started_at) * 1000)
                        ),
                        energy_per_token_mwh=None,
                        total_energy_mwh=None,
                        vram_peak_gb=None,
                        evaluations=[EvalMetric(
                            name="first_pass_acceptance",
                            score=0.0,
                            threshold=1.0,
                            passed=False,
                            explanation=str(exc),
                            metadata={"measurement_state": "rejected"},
                        )],
                        metadata={
                            "product_job": "first_pass_underwriting",
                            "guard_version": FIRST_PASS_GUARD_VERSION,
                            "provider_id": failure_metadata.get("provider_id", "local_bonsai"),
                            "question_event_id": question_event.get("event_id"),
                            "investment_screen": screen,
                            "result_state": (
                                "rejected_after_buzz_candidate_due_source_change"
                                if failure_metadata.get("published_draft_event_id")
                                else "rejected_before_buzz_draft"
                            ),
                            "orphaned_draft_event_id": failure_metadata.get(
                                "published_draft_event_id"
                            ),
                            "error": str(exc),
                            "source_classification": initial_provenance["classification"],
                            "source_provenance_sha256": initial_provenance["binding_sha256"],
                            "source_provenance": initial_provenance,
                            **failure_metadata,
                        },
                    ))
                    if failure_metadata["source_snapshot_state"] != "stable":
                        self._send_json({
                            "error": "source_changed_during_first_pass",
                            "detail": "The deal room changed before publication. Run a new first pass against the current folder.",
                            "trace_id": failure_trace_id,
                            "source_snapshot_before": initial_source_snapshot,
                            "source_snapshot_after": failure_metadata.get("source_snapshot_after"),
                        }, status=409)
                        return
                    try:
                        fallback = build_evidence_safe_fallback(
                            retrieve_first_pass_evidence(
                                rooms[room_id]["path"], investment_screen=screen,
                            ),
                            failure_trace_id,
                            investment_screen=screen,
                        )
                        try:
                            fallback_source_snapshot = inspect_local_deal_room(
                                rooms[room_id]["path"],
                            )["preview"]["preview_sha256"]
                        except (FileNotFoundError, ValueError, NotADirectoryError, PermissionError, OSError) as snapshot_exc:
                            raise FirstPassError(
                                "The deal room became unavailable while the evidence fallback was being prepared",
                                metadata={
                                    "source_snapshot_state": "unavailable_during_fallback",
                                    "source_snapshot_before": initial_source_snapshot,
                                    "source_snapshot_after": None,
                                    "source_snapshot_error": str(snapshot_exc),
                                },
                            ) from snapshot_exc
                        if fallback_source_snapshot != initial_source_snapshot:
                            raise FirstPassError(
                                "The deal room changed while the evidence fallback was being prepared",
                                metadata={
                                    "source_snapshot_state": "changed_during_fallback",
                                    "source_snapshot_before": initial_source_snapshot,
                                    "source_snapshot_after": fallback_source_snapshot,
                                },
                            )
                        fallback_provenance = source_provenance_binding(rooms[room_id])
                        if fallback_provenance != initial_provenance:
                            raise FirstPassError(
                                "The deal room provenance changed while the evidence fallback was being prepared",
                                metadata={
                                    "source_snapshot_state": "provenance_changed_during_fallback",
                                    "source_snapshot_before": initial_source_snapshot,
                                    "source_snapshot_after": fallback_source_snapshot,
                                    "source_provenance_before": initial_provenance,
                                    "source_provenance_after": fallback_provenance,
                                },
                            )
                        fallback_trace_id = global_tracer.start_trace(
                            room_id, "evidence_safe_fallback",
                        )
                        fallback_content = (
                            f"<!-- prism:first-pass-draft model={fallback.model} "
                            f"recommendation={fallback.recommendation} "
                            f"guard={EVIDENCE_FALLBACK_GUARD_VERSION} "
                            "mode=evidence_safe_fallback "
                            f"trace={fallback_trace_id} "
                            f"model_failure_trace={failure_trace_id} "
                            f"source_class={initial_provenance['classification']} "
                            f"provenance={initial_provenance['binding_sha256']} "
                            f"source_snapshot={initial_source_snapshot} -->\n"
                            "# Evidence-safe first pass fallback\n\n"
                            f"{fallback.markdown}"
                        )
                        fallback_event = global_buzz.send_as_agent(
                            workspace["channel_id"], fallback_content,
                        )
                        try:
                            post_fallback_snapshot = inspect_local_deal_room(
                                rooms[room_id]["path"],
                            )["preview"]["preview_sha256"]
                            post_fallback_provenance = source_provenance_binding(rooms[room_id])
                        except (FileNotFoundError, ValueError, NotADirectoryError, PermissionError, OSError) as snapshot_exc:
                            raise FirstPassError(
                                "The deal room became unavailable during fallback publication",
                                metadata={
                                    "source_snapshot_state": "unavailable_during_publication",
                                    "source_snapshot_before": initial_source_snapshot,
                                    "source_snapshot_after": None,
                                    "source_snapshot_error": str(snapshot_exc),
                                    "published_draft_event_id": fallback_event.get("event_id"),
                                },
                            ) from snapshot_exc
                        if (
                            post_fallback_snapshot != initial_source_snapshot
                            or post_fallback_provenance != initial_provenance
                        ):
                            raise FirstPassError(
                                "The deal room or its provenance changed during fallback publication",
                                metadata={
                                    "source_snapshot_state": "changed_during_publication",
                                    "source_snapshot_before": initial_source_snapshot,
                                    "source_snapshot_after": post_fallback_snapshot,
                                    "source_provenance_before": initial_provenance,
                                    "source_provenance_after": post_fallback_provenance,
                                    "published_draft_event_id": fallback_event.get("event_id"),
                                },
                            )
                    except (FirstPassError, BuzzUnavailable) as fallback_exc:
                        fallback_metadata = getattr(fallback_exc, "metadata", {})
                        if fallback_metadata.get("source_snapshot_state"):
                            fallback_failure_trace_id = global_tracer.start_trace(
                                room_id, "evidence_safe_fallback_rejected",
                            )
                            global_tracer.record_trace(ArizeTraceRecord(
                                trace_id=fallback_failure_trace_id,
                                session_id=room_id,
                                timestamp=time.time(),
                                query="evidence_safe_fallback",
                                response="",
                                model_name="deterministic_source_excerpt_v2",
                                routed_tier="DETERMINISTIC_LOCAL",
                                total_tokens=0,
                                prompt_tokens=0,
                                completion_tokens=0,
                                total_latency_ms=0.0,
                                energy_per_token_mwh=None,
                                total_energy_mwh=None,
                                vram_peak_gb=None,
                                evaluations=[EvalMetric(
                                    name="source_snapshot_stability",
                                    score=0.0,
                                    threshold=1.0,
                                    passed=False,
                                    explanation=str(fallback_exc),
                                    metadata={"measurement_state": "rejected"},
                                )],
                                metadata={
                                    "product_job": "first_pass_underwriting_fallback",
                                    "artifact_mode": "evidence_safe_fallback",
                                    "result_state": (
                                        "rejected_after_buzz_candidate_due_source_change"
                                        if fallback_metadata.get("published_draft_event_id")
                                        else "rejected_before_buzz_draft"
                                    ),
                                    "orphaned_draft_event_id": fallback_metadata.get(
                                        "published_draft_event_id"
                                    ),
                                    "model_failure_trace_id": failure_trace_id,
                                    **fallback_metadata,
                                },
                            ))
                            self._send_json({
                                "error": "source_changed_during_first_pass",
                                "detail": "The deal room changed before fallback publication. Run a new first pass against the current folder.",
                                "trace_id": failure_trace_id,
                                "fallback_trace_id": fallback_failure_trace_id,
                                "source_snapshot_before": initial_source_snapshot,
                                "source_snapshot_after": fallback_metadata.get("source_snapshot_after"),
                            }, status=409)
                            return
                        self._send_json({
                            "error": "first_pass_rejected",
                            "detail": str(exc),
                            "trace_id": failure_trace_id,
                            "fallback_error": str(fallback_exc),
                        }, status=502)
                        return
                    global_tracer.record_trace(ArizeTraceRecord(
                        trace_id=fallback_trace_id,
                        session_id=room_id,
                        timestamp=time.time(),
                        query="evidence_safe_fallback",
                        response=fallback.markdown,
                        model_name=fallback.model,
                        routed_tier="DETERMINISTIC_LOCAL",
                        total_tokens=0,
                        prompt_tokens=0,
                        completion_tokens=0,
                        total_latency_ms=0.0,
                        energy_per_token_mwh=None,
                        total_energy_mwh=None,
                        vram_peak_gb=None,
                        evaluations=[
                            EvalMetric(
                                name="source_excerpt_provenance",
                                score=1.0,
                                threshold=1.0,
                                passed=True,
                                explanation=(
                                    f"Rendered {len(fallback.citations)} admitted citations "
                                    "without using the rejected model prose."
                                ),
                                metadata={"citations": fallback.citations},
                            ),
                            EvalMetric(
                                name="human_accuracy_review",
                                score=0.0,
                                threshold=1.0,
                                passed=False,
                                explanation="Evidence-safe fallback awaits human usefulness review.",
                                metadata={"measurement_state": "awaiting_human_review"},
                            ),
                        ],
                        metadata={
                            "product_job": "first_pass_underwriting_fallback",
                            "artifact_mode": "evidence_safe_fallback",
                            "authored_by": "deterministic_evidence_renderer",
                            "guard_version": EVIDENCE_FALLBACK_GUARD_VERSION,
                            "model_failure_trace_id": failure_trace_id,
                            "question_event_id": question_event.get("event_id"),
                            "draft_event_id": fallback_event.get("event_id"),
                            "investment_screen": screen,
                            "citation_count": len(fallback.citations),
                            "source_snapshot_sha256": initial_source_snapshot,
                            "source_classification": initial_provenance["classification"],
                            "source_provenance_sha256": initial_provenance["binding_sha256"],
                            "source_provenance": initial_provenance,
                            **fallback.raw_metadata,
                        },
                    ))
                    record = {
                        **fallback.to_dict(),
                        "trace_id": fallback_trace_id,
                        "model_failure_trace_id": failure_trace_id,
                        "model_failure_detail": str(exc),
                        "question_event_id": question_event.get("event_id"),
                        "draft_event_id": fallback_event.get("event_id"),
                        "canonical_path": f"/rooms/{room_id}/first-pass",
                        "investment_screen": screen,
                        "review": None,
                        "acceptance_state": "evidence_safe_fallback",
                        "artifact_mode": "evidence_safe_fallback",
                        "authored_by": "deterministic_evidence_renderer",
                        "guard_version": EVIDENCE_FALLBACK_GUARD_VERSION,
                        "source_snapshot_sha256": initial_source_snapshot,
                        "source_classification": initial_provenance["classification"],
                        "source_provenance_sha256": initial_provenance["binding_sha256"],
                        "source_provenance": initial_provenance,
                    }
                    self._send_json(record, status=201)
                    return
                except BuzzUnavailable as exc:
                    self._send_json({
                        "error": "buzz_unavailable", "detail": str(exc),
                    }, status=503)
                    return

                completed_at = time.time()
                evaluations = [
                    EvalMetric(
                        name="first_pass_structure",
                        score=1.0,
                        threshold=1.0,
                        passed=True,
                        explanation="All required first pass headings and a recommendation were present.",
                    ),
                    EvalMetric(
                        name="citation_presence",
                        score=1.0,
                        threshold=1.0,
                        passed=True,
                        explanation=f"The draft used {len(result.citations)} admitted source citations.",
                        metadata={"citations": result.citations},
                    ),
                    EvalMetric(
                        name="human_accuracy_review",
                        score=0.0,
                        threshold=1.0,
                        passed=False,
                        explanation="Unverified until a human records corrections and usefulness.",
                        metadata={"measurement_state": "awaiting_human_review"},
                    ),
                ]
                global_tracer.record_trace(ArizeTraceRecord(
                    trace_id=trace_id,
                    session_id=room_id,
                    timestamp=started_at,
                    query="first_pass_underwriting",
                    response=result.markdown,
                    model_name=result.model,
                    routed_tier="LOCAL_BONSAI_27B",
                    total_tokens=result.usage.get("total_tokens"),
                    prompt_tokens=result.usage.get("prompt_tokens"),
                    completion_tokens=result.usage.get("completion_tokens"),
                    total_latency_ms=result.latency_ms,
                    energy_per_token_mwh=None,
                    total_energy_mwh=None,
                    vram_peak_gb=None,
                    evaluations=evaluations,
                    metadata={
                        "product_job": "first_pass_underwriting",
                        "guard_version": FIRST_PASS_GUARD_VERSION,
                        "provider_id": result.provider,
                        "draft_event_id": draft_event.get("event_id"),
                        "question_event_id": question_event.get("event_id"),
                        "investment_screen": screen,
                        "citation_count": len(result.citations),
                        "retrieved_passage_count": len(result.retrieved_passages),
                        "source_snapshot_sha256": initial_source_snapshot,
                        "source_classification": initial_provenance["classification"],
                        "source_provenance_sha256": initial_provenance["binding_sha256"],
                        "source_provenance": initial_provenance,
                        "started_at": started_at,
                        "completed_at": completed_at,
                        **result.raw_metadata,
                    },
                ))
                record = {
                    **result.to_dict(),
                    "trace_id": trace_id,
                    "question_event_id": question_event.get("event_id"),
                    "draft_event_id": draft_event.get("event_id"),
                    "canonical_path": f"/rooms/{room_id}/first-pass",
                    "investment_screen": screen,
                    "review": None,
                    "acceptance_state": "accepted",
                    "guard_version": FIRST_PASS_GUARD_VERSION,
                    "source_snapshot_sha256": initial_source_snapshot,
                    "source_classification": initial_provenance["classification"],
                    "source_provenance_sha256": initial_provenance["binding_sha256"],
                    "source_provenance": initial_provenance,
                }
                self._send_json(record, status=201)
                return

            if action == "review":
                try:
                    latest = self._first_pass_record(room_id, workspace)
                except BuzzUnavailable as exc:
                    self._send_json({
                        "error": "first_pass_review_unavailable", "detail": str(exc),
                    }, status=503)
                    return
                if latest is None:
                    self._send_json({"error": "first_pass_draft_required"}, status=409)
                    return
                if latest.get("acceptance_state") not in {
                    "accepted", "evidence_safe_fallback",
                }:
                    self._send_json({
                        "error": "first_pass_not_reviewable",
                        "detail": (
                            "This draft predates the current deterministic evidence guard. "
                            "Run a new accepted first pass before local operator review."
                        ),
                    }, status=409)
                    return
                decision = str(payload.get("decision", "")).lower()
                if decision not in {"advance", "pause", "stop"}:
                    self._send_json({"error": "review_decision_required"}, status=400)
                    return
                useful = bool(payload.get("useful_starting_point", False))
                try:
                    critical = max(0, int(payload.get("critical_corrections", 0)))
                    major = max(0, int(payload.get("major_corrections", 0)))
                except (TypeError, ValueError):
                    self._send_json({"error": "invalid_correction_count"}, status=400)
                    return
                notes = str(payload.get("notes", "")).strip()
                if len(notes) > 8_000:
                    self._send_json({"error": "review_notes_too_large"}, status=413)
                    return
                review_fields = {
                    "decision": decision,
                    "useful_starting_point": useful,
                    "critical_corrections": critical,
                    "major_corrections": major,
                    "notes": notes,
                }
                review_markdown = local_review_canvas_content(
                    rooms[room_id]["name"], latest, review_fields,
                )
                try:
                    canvas_event = global_buzz.set_canvas(
                        workspace["channel_id"], review_markdown,
                    )
                    review_event = global_buzz.send(
                        workspace["channel_id"],
                        local_review_message_content(latest, review_fields),
                    )
                    operator_pubkey = global_buzz.status().get("operator_pubkey")
                except BuzzUnavailable as exc:
                    self._send_json({
                        "error": "buzz_unavailable", "detail": str(exc),
                    }, status=503)
                    return
                review = {
                    "review_actor": "local_operator",
                    "reviewer_pubkey": operator_pubkey,
                    "authentication_scope": "local_operator_bridge",
                    "benchmark_domain_review": False,
                    "decision": decision,
                    "useful_starting_point": useful,
                    "critical_corrections": critical,
                    "major_corrections": major,
                    "notes": notes,
                    "review_event_id": review_event.get("event_id"),
                    "canvas_event_id": canvas_event.get("event_id"),
                    "canonical_path": f"/rooms/{room_id}/digest",
                }
                reviewed_trace = next(
                    (
                        trace for trace in global_tracer.snapshot()
                        if trace.trace_id == latest.get("trace_id")
                    ),
                    None,
                )
                if reviewed_trace is not None:
                    reviewed_trace.evaluations.extend([
                        EvalMetric(
                            name="human_usefulness",
                            score=1.0 if useful else 0.0,
                            threshold=1.0,
                            passed=useful,
                            explanation=(
                                "Recorded by the configured local Buzz operator. This is a "
                                "product decision, not independently authenticated domain review."
                            ),
                        ),
                        EvalMetric(
                            name="critical_correction_gate",
                            score=1.0 if critical == 0 else 0.0,
                            threshold=1.0,
                            passed=critical == 0,
                            explanation=f"The reviewer recorded {critical} critical corrections.",
                        ),
                        EvalMetric(
                            name="major_correction_gate",
                            score=1.0 if major == 0 else 0.0,
                            threshold=1.0,
                            passed=major == 0,
                            explanation=f"The reviewer recorded {major} major corrections.",
                        ),
                    ])
                    reviewed_trace.metadata["human_review"] = review
                    global_tracer.persist()
                try:
                    verified_latest = self._first_pass_record(room_id, workspace)
                except BuzzUnavailable as exc:
                    self._send_json({
                        "error": "first_pass_review_unavailable",
                        "detail": (
                            "The review was published but its durable evidence chain could not "
                            f"be restored: {exc}"
                        ),
                    }, status=503)
                    return
                if verified_latest is None or not isinstance(
                    verified_latest.get("review"), dict
                ):
                    self._send_json({
                        "error": "first_pass_review_unavailable",
                        "detail": "The published review did not restore from its durable evidence chain",
                    }, status=503)
                    return
                self._send_json(verified_latest["review"], status=201)
                return

            self._send_json({"error": "invalid_first_pass_action"}, status=400)
            return

        elif path == "/api/workspace/evaluation/annotation":
            room_id = str(payload.get("room") or DEFAULT_ROOM)
            store = self._workspace_review_store(room_id)
            if store is None:
                return
            try:
                self._send_json(store.upsert_annotation(payload))
            except ValueError as exc:
                self._send_json({"error": "invalid_review_annotation", "detail": str(exc)}, status=400)
            return

        elif path == "/api/workspace/evaluation/suggestion":
            room_id = str(payload.get("room") or DEFAULT_ROOM)
            store = self._workspace_review_store(room_id)
            if store is None:
                return
            try:
                self._send_json(store.set_suggestion_state(payload))
            except ValueError as exc:
                self._send_json({"error": "invalid_review_suggestion", "detail": str(exc)}, status=400)
            return

        elif path == "/api/workspace/evaluation/next-samples":
            room_id = str(payload.get("room") or DEFAULT_ROOM)
            store = self._workspace_review_store(room_id)
            if store is None:
                return
            self._send_json(store.add_breadth())
            return

        elif path == "/api/workspace/evaluation/scan":
            room_id = str(payload.get("room") or DEFAULT_ROOM)
            store = self._workspace_review_store(room_id)
            if store is None:
                return
            try:
                self._send_json(store.scan())
            except ValueError as exc:
                self._send_json({"error": "review_depth_not_ready", "detail": str(exc)}, status=409)
            return

        elif path == "/api/workspace/evaluation/experiments":
            room_id = str(payload.get("room") or DEFAULT_ROOM)
            if room_id not in all_deal_rooms():
                self._send_json({"error": "unknown_deal_room", "room": room_id}, status=404)
                return
            try:
                event = global_evaluation_experiments.create_experiment(
                    room_id, {key: value for key, value in payload.items() if key != "room"},
                )
                self._send_json(event, status=201)
            except ValueError as exc:
                self._send_json({"error": "invalid_experiment_record", "detail": str(exc)}, status=400)
            return

        elif path == "/api/workspace/evaluation/runs":
            room_id = str(payload.get("room") or DEFAULT_ROOM)
            if room_id not in all_deal_rooms():
                self._send_json({"error": "unknown_deal_room", "room": room_id}, status=404)
                return
            try:
                event = global_evaluation_experiments.append_run(
                    room_id, {key: value for key, value in payload.items() if key != "room"},
                )
                self._send_json(event, status=201)
            except ValueError as exc:
                self._send_json({"error": "invalid_experiment_run", "detail": str(exc)}, status=400)
            return

        elif path == "/api/route":
            query = payload.get("query", "")
            local_only_policy = payload.get("local_only_policy", True)
            cloud_override = payload.get("force_cloud_override", False)
            decision = global_router.evaluate_routing(
                query,
                deal_room_active=not cloud_override,
                force_cloud_override=cloud_override,
                local_only_policy_override=local_only_policy,
                local_ai_available=global_providers.local.configured,
                cloud_ai_available=global_providers.cloud.configured,
                cloud_dispatch_authorized=False,
            )
            self._send_json({
                "target_tier": decision.target_tier,
                "reason": decision.reason,
                "is_local_only_policy": decision.is_local_only_policy,
                "redaction_applied": decision.redaction_applied,
                "sanitized_prompt": decision.sanitized_prompt,
                "estimated_cost_usd": decision.estimated_cost_usd,
                "estimated_energy_mwh_per_token": decision.estimated_energy_mwh_per_token,
                "metadata": decision.metadata,
            })
        elif path == "/api/benchmark/source-review":
            self._receive_candidate_source_review(payload)
        else:
            self.send_error(404, "Endpoint not found")

    def _send_json(self, data: Any, status: int = 200):
        body = json.dumps(data, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            # The client abandoned this response. The underlying operation and
            # its trace keep their real outcome; avoid turning a disconnect
            # into an unrelated server traceback.
            return

    def _buzz_room_binding(self, room_id: str) -> tuple[bool, Dict[str, str] | None]:
        try:
            return True, global_buzz.room(room_id)
        except BuzzUnavailable as exc:
            self._send_json({
                "error": "buzz_registry_unavailable",
                "detail": str(exc),
            }, status=503)
            return False, None

    @staticmethod
    def _candidate_review_material():
        packet = build_candidate_source_review_packet(PROJECT_ROOT)
        roster = load_source_reviewer_roster(PROJECT_ROOT)
        submissions = []
        if CANDIDATE_REVIEW_DIR.exists():
            for path in sorted(CANDIDATE_REVIEW_DIR.glob("*.json")):
                submissions.append(json.loads(path.read_text(encoding="utf-8")))
        adjudication = (
            json.loads(CANDIDATE_REVIEW_ADJUDICATION.read_text(encoding="utf-8"))
            if CANDIDATE_REVIEW_ADJUDICATION.exists() else None
        )
        signed_events = {}
        channel_id = (
            os.environ.get("PRISM_BENCHMARK_REVIEW_CHANNEL_ID", "").strip()
            or (
                BENCHMARK_REVIEW_CHANNEL.read_text(encoding="utf-8").strip()
                if BENCHMARK_REVIEW_CHANNEL.exists() else ""
            )
        )
        if submissions or adjudication is not None:
            if not channel_id:
                raise ValueError("signed review files exist but no benchmark review channel is configured")
            event_ids = {
                item.get("buzz_event_id") for item in submissions if item.get("buzz_event_id")
            }
            if adjudication and adjudication.get("buzz_event_id"):
                event_ids.add(adjudication["buzz_event_id"])
            signed_events = BuzzBridge(PROJECT_ROOT).events_by_ids(
                event_ids, channel_id=channel_id,
            )
        state = evaluate_source_review_state(
            PROJECT_ROOT, packet, submissions, adjudication, roster, signed_events,
        )
        return packet, roster, submissions, adjudication, state, channel_id, signed_events

    @staticmethod
    def _pipeline_state(review_state: dict, roster: dict, channel_id: str) -> dict:
        contract = validate_contract(PROJECT_ROOT)
        manifest = json.loads(
            (PROJECT_ROOT / "benchmarks" / "first_pass" / "benchmark_manifest.v2.json")
            .read_text(encoding="utf-8")
        )
        sealed_control = json.loads(
            (PROJECT_ROOT / "benchmarks" / "first_pass" / "sealed_test_control.v1.json")
            .read_text(encoding="utf-8")
        )
        sealed_preflight = sealed_test_preflight(PROJECT_ROOT)
        output_roster = load_output_reviewer_roster(PROJECT_ROOT)
        calibration = validate_saved_judge_calibration(
            PROJECT_ROOT, JUDGE_CALIBRATION_EVIDENCE,
        )
        pricing = validate_saved_pricing_poc(
            PROJECT_ROOT,
            PRICING_POC_RECORD,
            event_resolver=lambda event_ids, channel_id: global_buzz.events_by_ids(
                event_ids, channel_id=channel_id,
            ),
        )
        diagnostic = validate_saved_oracle_context(
            PROJECT_ROOT, ORACLE_CONTEXT_EVIDENCE,
        )
        ledger = json.loads(CASE_REGISTRATION_LEDGER.read_text(encoding="utf-8"))
        registrations = ledger.get("registrations", [])
        source_owners = sum(
            item.get("active") is True and item.get("role") == "domain_case_owner"
            for item in roster.get("reviewers", [])
        )
        inventory = contract["inventory"]
        qualified_output_reviewers = sum(
            item.get("active") is True
            and item.get("role") == "qualified_deal_output_reviewer"
            for item in output_roster.get("reviewers", [])
        )
        principal_output_reviewers = sum(
            item.get("active") is True
            and item.get("role") == "principal_output_reviewer"
            for item in output_roster.get("reviewers", [])
        )
        pipeline = {
            "source_review": {
                "submission_count": review_state["submission_count"],
                "eligible_count": review_state["eligible_for_case_authoring_count"],
                "rejected_count": review_state.get("rejected_draft_count", 0),
                "disagreement_count": review_state["disagreement_count"],
                "pending_count": review_state["pending_draft_count"],
                "validation_passed": review_state["validation_passed"],
            },
            "case_approval": {
                "roster_authority_state": roster.get("authority", {}).get(
                    "state", "invalid"
                ),
                "active_domain_case_owner_count": source_owners,
                "recorded_approval_count": inventory["candidate_approvals_recorded"],
                "unregistered_approval_count": inventory["candidate_approvals_unregistered"],
                "registered_approval_count": len(registrations),
                "storage": APPROVAL_LEDGER_STATUS,
            },
            "registration": {
                "ledger_valid": contract["structural_passed"],
                "candidate_cases_registered": len(registrations),
                "total_cases_registered": inventory["registered_cases"],
                "total_deals_registered": inventory["registered_deals"],
            },
            "calibration": {
                "reviewer_roster_authority_state": output_roster.get(
                    "authority", {}
                ).get("state", "invalid"),
                "evaluator_available": True,
                "registered_case_count": inventory["calibration_cases"],
                "registered_deal_count": inventory["calibration_deals"],
                "required_case_count": inventory["target_calibration_cases"],
                "required_deal_count": inventory["target_calibration_deals"],
                "qualified_output_reviewer_count": qualified_output_reviewers,
                "principal_output_reviewer_count": principal_output_reviewers,
                **calibration,
            },
            "release": {
                "accuracy_release_ready": contract["release_ready"],
                "domain_approved_cases": inventory["domain_approved_cases"],
                "target_cases": inventory["target_cases"],
                "target_deals": inventory["target_deals"],
                "blocker_count": len(contract["release_failures"]),
            },
            "buzz_review_channel": {
                "configured": bool(channel_id),
                "channel_id": channel_id or None,
                "signature_verification": "nip01_event_id_plus_bip340",
            },
        }
        source_reviewers = sum(
            item.get("active") is True
            and item.get("role") == "qualified_deal_source_reviewer"
            for item in roster.get("reviewers", [])
        )
        source_principals = sum(
            item.get("active") is True
            and item.get("role") == "principal_source_reviewer"
            for item in roster.get("reviewers", [])
        )
        governance = contract.get("governance", {})
        governance_approvals = governance.get("approvals", {})
        governance_roles = (
            "product_owner", "domain_owner", "strategy_owner", "security_owner",
        )
        governance_scopes = (
            "benchmark_contract", "release_thresholds", "sealed_test_open",
        )
        governance_ledger = json.loads(
            (PROJECT_ROOT / "benchmarks/first_pass/benchmark_governance.v1.json").read_text(
                encoding="utf-8"
            )
        )
        authority = governance_ledger.get("authority", {})
        assignments = {
            item.get("role"): item
            for item in authority.get("role_assignments", [])
            if isinstance(item, dict)
        }
        pipeline["governance"] = {
            "configured": governance.get("configured") is True,
            "valid": governance.get("valid") is True,
            "receipt_count": governance.get("receipt_count", 0),
            "required_receipt_count": 12,
            "signature_verification": "nip01_event_id_plus_bip340_material_bound",
            "root_authority_id": authority.get("root_authority_id"),
            "roles": [
                {
                    "role": role,
                    "actor_id": assignments.get(role, {}).get("actor_id"),
                    "actor_pubkey": assignments.get(role, {}).get("buzz_pubkey"),
                }
                for role in governance_roles
            ],
            "scopes": [
                {
                    "scope": scope,
                    "material_sha256": governance.get("material_sha256", {}).get(scope),
                    "verified_role_count": sum(
                        governance_approvals.get(scope, {}).get(role) is True
                        for role in governance_roles
                    ),
                    "required_role_count": len(governance_roles),
                    "roles": [
                        {
                            "role": role,
                            "approved": governance_approvals.get(scope, {}).get(role) is True,
                        }
                        for role in governance_roles
                    ],
                }
                for scope in governance_scopes
            ],
            "authority_boundary": (
                "The checked-in trust root is local configuration. Each promotion receipt must still be "
                "signed by its assigned role over the exact benchmark material hash."
            ),
        }
        targets = manifest.get("target", {})
        target_families = targets.get("task_families", {})
        target_slices = targets.get("minimum_slice_fractions", {})
        coverage_ready = (
            inventory["registered_cases"] >= inventory["target_cases"]
            and inventory["registered_deals"] >= inventory["target_deals"]
            and all(
                inventory["task_family_counts"].get(family, 0) >= required
                for family, required in target_families.items()
            )
            and all(
                inventory["slice_fractions"].get(slice_name, 0) >= required
                for slice_name, required in target_slices.items()
            )
        )
        contract_approvals = governance_approvals.get("benchmark_contract", {})
        threshold_approvals = governance_approvals.get("release_thresholds", {})
        owner_approved = bool(
            governance.get("valid")
            and contract_approvals.get("product_owner") is True
            and contract_approvals.get("domain_owner") is True
        )
        thresholds_approved = bool(
            governance.get("valid")
            and all(threshold_approvals.get(role) is True for role in governance_roles)
        )
        label_authority_ready = (
            roster.get("authority", {}).get("state") == "signed_buzz_authority"
            and output_roster.get("authority", {}).get("state") == "signed_buzz_authority"
            and source_reviewers >= 2
            and source_principals >= 1
            and qualified_output_reviewers >= 2
            and principal_output_reviewers >= 1
        )
        domain_severity_ready = (
            inventory["registered_cases"] > 0
            and inventory["domain_approved_cases"] == inventory["registered_cases"]
        )
        sealed_ready = sealed_preflight.get("ready_to_open") is True
        calibration_ready = calibration.get("calibration_passed") is True
        private_pilot_recorded = pricing.get("evidence_state") == "verified"
        decisions = [
            {
                "number": 1,
                "key": "job_under_certification",
                "title": "Job under certification",
                "state": "approved" if owner_approved else "awaiting_owner_approval",
                "release_satisfied": owner_approved,
                "evidence": manifest.get("certified_job"),
                "blocker": None if owner_approved else "Signed, material-bound product and domain owner approvals are missing.",
            },
            {
                "number": 2,
                "key": "label_authority",
                "title": "Label authority",
                "state": "ready" if label_authority_ready else "awaiting_qualified_reviewers",
                "release_satisfied": label_authority_ready,
                "evidence": (
                    f"{source_reviewers} source reviewers, {source_principals} source principals, "
                    f"{qualified_output_reviewers} output reviewers, "
                    f"{principal_output_reviewers} output principals"
                ),
                "blocker": None if label_authority_ready else "Signed authorities and qualified independent reviewers are missing.",
            },
            {
                "number": 3,
                "key": "error_severity",
                "title": "Error severity",
                "state": "approved" if domain_severity_ready else "contract_only",
                "release_satisfied": domain_severity_ready,
                "evidence": f"{inventory['domain_approved_cases']} of {inventory['registered_cases']} cases have domain approval.",
                "blocker": None if domain_severity_ready else "Domain owners have not approved case severity and expected results.",
            },
            {
                "number": 4,
                "key": "dataset_size_and_coverage",
                "title": "Dataset size and coverage",
                "state": "ready" if coverage_ready else "dataset_incomplete",
                "release_satisfied": coverage_ready,
                "evidence": f"{inventory['registered_cases']} of {inventory['target_cases']} cases across {inventory['registered_deals']} of {inventory['target_deals']} deals.",
                "blocker": None if coverage_ready else "Registered case, deal, task family, or required slice coverage is incomplete.",
            },
            {
                "number": 5,
                "key": "leakage_control",
                "title": "Leakage control",
                "state": "ready" if sealed_ready else "sealed_set_unavailable",
                "release_satisfied": sealed_ready,
                "evidence": f"{inventory['sealed_test_cases']} sealed cases. Controller state: {sealed_control.get('state', 'invalid')}. Preflight: {'ready' if sealed_ready else 'blocked'}.",
                "blocker": None if sealed_ready else "The full sealed test preflight is blocked before external bytes are read.",
            },
            {
                "number": 6,
                "key": "model_roles",
                "title": "Model roles",
                "state": "calibrated" if calibration_ready else "roles_incomplete",
                "release_satisfied": calibration_ready and label_authority_ready,
                "evidence": f"Judge calibration: {calibration.get('evidence_state', 'invalid')}. Human labels remain authoritative.",
                "blocker": None if calibration_ready and label_authority_ready else "Independent human labels and judge calibration are incomplete.",
            },
            {
                "number": 7,
                "key": "failure_localization",
                "title": "Failure localization",
                "state": "engineering_diagnostic_only" if diagnostic.get("passed") else "diagnostic_invalid",
                "release_satisfied": diagnostic.get("passed") is True and calibration_ready,
                "evidence": "Five development cases have a recomputed oracle context diagnostic." if diagnostic.get("passed") else "The saved oracle context diagnostic is invalid.",
                "blocker": None if diagnostic.get("passed") is True and calibration_ready else "Semantic localization lacks calibrated human labels.",
            },
            {
                "number": 8,
                "key": "private_data_and_evaluation_records",
                "title": "Private data and evaluation records",
                "state": "private_pilot_recorded" if private_pilot_recorded else "private_pilot_not_recorded",
                "release_satisfied": private_pilot_recorded,
                "evidence": f"Signed private pilot evidence: {pricing.get('evidence_state', 'invalid')}.",
                "blocker": None if private_pilot_recorded else "No authorized buyer signed private deal room record exists.",
            },
            {
                "number": 9,
                "key": "required_comparisons",
                "title": "Required comparisons",
                "state": "release_comparison_ready" if contract["release_ready"] and calibration_ready else "engineering_comparison_only",
                "release_satisfied": contract["release_ready"] and calibration_ready,
                "evidence": "The deterministic baseline and local Bonsai engineering comparison exist.",
                "blocker": None if contract["release_ready"] and calibration_ready else "No frozen, labeled release comparison exists.",
            },
            {
                "number": 10,
                "key": "release_thresholds",
                "title": "Release thresholds",
                "state": "release_ready" if contract["release_ready"] and calibration_ready else "thresholds_unapproved",
                "release_satisfied": contract["release_ready"] and calibration_ready,
                "evidence": f"Signed threshold approvals: {thresholds_approved}. Accuracy release: {contract['release_ready']}.",
                "blocker": None if contract["release_ready"] and calibration_ready else "Threshold approval, calibration, or the release contract is incomplete.",
            },
        ]
        pipeline["benchmark_decisions"] = {
            "decision_count": len(decisions),
            "release_satisfied_count": sum(item["release_satisfied"] for item in decisions),
            "all_release_satisfied": all(item["release_satisfied"] for item in decisions),
            "decisions": decisions,
            "meaning": "Each decision reports current evidence and its next blocker. A contract or engineering diagnostic does not count as human or release evidence.",
        }
        return pipeline

    def _send_benchmark_pipeline(self):
        try:
            _, roster, _, _, review_state, channel_id, _ = self._candidate_review_material()
            pipeline = self._pipeline_state(review_state, roster, channel_id)
        except (BuzzUnavailable, OSError, json.JSONDecodeError, ValueError) as exc:
            self._send_json({"error": "benchmark_pipeline_invalid", "detail": str(exc)}, status=409)
            return
        self._send_json(pipeline)

    def _send_oracle_context_diagnostic(self):
        validation = validate_saved_oracle_context(
            PROJECT_ROOT, ORACLE_CONTEXT_EVIDENCE,
        )
        if not validation.get("passed"):
            self._send_json({
                "error": "oracle_context_evidence_invalid",
                "detail": "; ".join(validation.get("errors", [])),
            }, status=409)
            return
        try:
            record = json.loads(ORACLE_CONTEXT_EVIDENCE.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            self._send_json({
                "error": "oracle_context_evidence_unavailable", "detail": str(exc),
            }, status=409)
            return
        cases = []
        for item in record.get("cases", []):
            oracle = item.get("oracle") if isinstance(item.get("oracle"), dict) else None
            absence_audit = (
                item.get("absence_audit")
                if isinstance(item.get("absence_audit"), dict) else None
            )
            cases.append({
                "case_id": item.get("case_id"),
                "eligible": item.get("eligible") is True,
                "localization": item.get("localization"),
                "baseline_probe_passed": item.get("baseline_probe", {}).get("passed"),
                "oracle_probe_passed": oracle.get("probe", {}).get("passed") if oracle else None,
                "oracle_response": oracle.get("response") if oracle else None,
                "missing_citations": (
                    oracle.get("probe", {}).get("citation_token_presence", {}).get("missing", [])
                    if oracle else []
                ),
                "missing_registered_numbers": (
                    oracle.get("probe", {}).get(
                        "registered_numeric_token_presence", {}
                    ).get("missing", []) if oracle else []
                ),
                "absence_phrase_policy_passed": (
                    oracle.get("probe", {}).get(
                        "registered_absence_phrase_policy", {}
                    ).get("passed") if oracle else None
                ),
                "absence_audit": ({
                    "passed": absence_audit.get("passed") is True,
                    "scope": absence_audit.get("scope"),
                    "source_file_count": absence_audit.get("source_file_count"),
                    "parsed_node_count": absence_audit.get("parsed_node_count"),
                    "registered_pattern_count": absence_audit.get(
                        "registered_pattern_count"
                    ),
                    "direct_disclosure_hit_count": len(
                        absence_audit.get("registered_direct_disclosure_hits", [])
                    ),
                    "semantic_accuracy_state": absence_audit.get(
                        "semantic_accuracy_state"
                    ),
                    "domain_review_status": absence_audit.get("domain_review_status"),
                } if absence_audit else None),
                "reason": item.get("reason"),
            })
        oracle_passes = sum(item.get("oracle_probe_passed") is True for item in cases)
        self._send_json({
            "verification_state": "validated_saved_engineering_diagnostic",
            **validation,
            "oracle_probe_pass_count": oracle_passes,
            "cases": cases,
            "meaning": (
                "This localizes literal development-contract behavior. It does not prove "
                "semantic accuracy, retrieval fault, model fault, or human usefulness."
            ),
            "limitations": record.get("limitations", []),
        })

    def _send_pricing_poc(self):
        result = validate_saved_pricing_poc(
            PROJECT_ROOT,
            PRICING_POC_RECORD,
            event_resolver=lambda event_ids, channel_id: global_buzz.events_by_ids(
                event_ids, channel_id=channel_id,
            ),
        )
        result["requirements"] = [
            {
                "id": "buyer_and_success_contract",
                "label": "Buyer and success contract",
                "requirement": "Named workflow and economic-buyer roles, budget authority, buyer effort, authorized access, and agreed success criteria",
            },
            {
                "id": "paid_poc",
                "label": "Paid proof of concept",
                "requirement": "The initial historical-deal review is paid; free public demos do not qualify",
            },
            {
                "id": "private_historical_deals",
                "label": "Two private historical deals",
                "requirement": "Two distinct, authorized, closed customer deal rooms",
            },
            {
                "id": "setup_and_transfer_design",
                "label": "Setup and transfer",
                "requirement": "One correction deal and one transfer deal with no case-specific change",
            },
            {
                "id": "useful_starting_point",
                "label": "Expert usefulness",
                "requirement": "At least 80% of pilot deals are useful starting points",
            },
            {
                "id": "median_review_time_reduction",
                "label": "Review-time reduction",
                "requirement": "Median first-review time falls at least 30% from the customer's measured baseline",
            },
            {
                "id": "transfer_deal_quality",
                "label": "Transfer-deal quality",
                "requirement": "The transfer deal is accepted with zero critical corrections",
            },
            {
                "id": "post_use_price_range",
                "label": "Post-use price range",
                "requirement": "After use, the buyer records acceptable, expensive, and prohibitively expensive prices for one accepted review",
            },
            {
                "id": "paid_next_step_or_reason",
                "label": "Commercial next step",
                "requirement": "A paid next step or a concrete reason for declining is recorded",
            },
            {
                "id": "buyer_signature",
                "label": "Buyer attestation",
                "requirement": "A distinct configured commercial authority approves the buyer key, and Prism restores both exact events from the authority channel before verifying their signatures and payloads",
            },
        ]
        result["record_expected_at"] = str(PRICING_POC_RECORD.relative_to(PROJECT_ROOT))
        result["public_demo_boundary"] = (
            "The 29 public SEC dossiers demonstrate workflow breadth. They do not count as "
            "private customer evidence or willingness-to-pay evidence. A configured authority "
            "proves control of an approval key, not the buyer's legal identity or employment."
        )
        self._send_json(result)

    def _send_candidate_source_review(self, draft_id: str | None):
        try:
            packet, roster, submissions, _, review_state, channel_id, signed_events = (
                self._candidate_review_material()
            )
            pipeline = self._pipeline_state(review_state, roster, channel_id)
        except (BuzzUnavailable, OSError, json.JSONDecodeError, ValueError) as exc:
            self._send_json({"error": "source_review_state_invalid", "detail": str(exc)}, status=409)
            return
        drafts = {item["draft_id"]: item for item in packet["drafts"]}
        if draft_id and draft_id not in drafts:
            self._send_json({"error": "unknown_candidate_draft", "draft_id": draft_id}, status=404)
            return
        review_counts = {item["draft_id"]: 0 for item in packet["drafts"]}
        for submission in submissions:
            if validate_source_review_submission(
                PROJECT_ROOT, packet, submission, roster, signed_events,
            ):
                continue
            for item in submission.get("drafts", []):
                if item.get("draft_id") in review_counts:
                    review_counts[item["draft_id"]] += 1
        qualified_reviewers = [
            {
                "reviewer_id": item["reviewer_id"],
                "display_name": item["display_name"],
                "qualification": item["qualification"],
                "buzz_pubkey": item["buzz_pubkey"],
            }
            for item in roster["reviewers"]
            if item["active"] and item["role"] == "qualified_deal_source_reviewer"
        ]
        registered_draft_ids = {
            item.get("draft_id")
            for item in json.loads(CASE_REGISTRATION_LEDGER.read_text(encoding="utf-8")).get(
                "registrations", []
            )
        }
        summaries = [{
            "draft_id": item["draft_id"],
            "candidate_id": item["candidate_id"],
            "company": item["company"],
            "question_family": item["question_family"],
            "task_family": item["task_family"],
            "provisional_question": item["provisional_question"],
            "review_count": review_counts[item["draft_id"]],
            "status": (
                "registered_case"
                if item["draft_id"] in registered_draft_ids
                else "eligible_for_case_authoring"
                if item["draft_id"] in review_state.get("eligible_draft_ids", [])
                else "rejected_by_source_review"
                if item["draft_id"] in review_state.get("rejected_draft_ids", [])
                else "review_disagreement"
                if any(
                    conflict.get("draft_id") == item["draft_id"]
                    for conflict in review_state.get("disagreements", [])
                )
                else "awaiting_independent_reviews"
            ),
        } for item in packet["drafts"]]
        self._send_json({
            "packet_sha256": candidate_review_packet_sha256(packet),
            "packet_version": packet["packet_version"],
            "candidate_deal_count": packet["candidate_deal_count"],
            "draft_count": packet["draft_count"],
            "review_state": review_state,
            "qualified_reviewers": qualified_reviewers,
            "reviewer_roster_ready": len(qualified_reviewers) >= 2,
            "reviewer_authentication_ready": False,
            "submission_ready": False,
            "pipeline": pipeline,
            "drafts": summaries,
            "draft": drafts.get(draft_id) if draft_id else None,
            "canonical_path": (
                f"/benchmark/source-review?draft={urllib.parse.quote(draft_id)}"
                if draft_id else "/benchmark/source-review"
            ),
            "limitations": [
                "This surface creates source-review evidence, not benchmark registration or accuracy evidence.",
                "Only domain-owner-rostered reviewers can submit decisions.",
            ],
        })

    def _send_output_review(self, case_id: str | None):
        try:
            packet = build_review_packet(PROJECT_ROOT, FIRST_PASS_REVIEW_RESPONSES)
            roster = load_output_reviewer_roster(PROJECT_ROOT)
            _, source_roster, _, _, source_state, channel_id, _ = (
                self._candidate_review_material()
            )
            pipeline = self._pipeline_state(source_state, source_roster, channel_id)
        except (BuzzUnavailable, OSError, json.JSONDecodeError, ValueError) as exc:
            self._send_json({
                "error": "output_review_state_invalid", "detail": str(exc),
            }, status=409)
            return
        cases = {item["case_id"]: item for item in packet["cases"]}
        if case_id and case_id not in cases:
            self._send_json({
                "error": "unknown_output_review_case", "case_id": case_id,
            }, status=404)
            return
        reviewers = [
            {
                "reviewer_id": item["reviewer_id"],
                "display_name": item["display_name"],
                "qualification": item["qualification"],
                "buzz_pubkey": item["buzz_pubkey"],
            }
            for item in roster.get("reviewers", [])
            if item.get("active") is True
            and item.get("role") == "qualified_deal_output_reviewer"
        ]
        summaries = [
            {
                "case_id": item["case_id"],
                "deal_id": item["deal_id"],
                "task_family": item["task_family"],
                "severity": item["severity"],
                "question": item["question"],
            }
            for item in packet["cases"]
        ]
        self._send_json({
            "packet_kind": packet["packet_kind"],
            "packet_version": packet["packet_version"],
            "packet_sha256": output_review_packet_sha256(packet),
            "rubric_sha256": packet["rubric_sha256"],
            "blinded_to_model": packet["blinded_to_model"],
            "model_identity_included": packet["model_identity_included"],
            "case_count": len(packet["cases"]),
            "qualified_reviewers": reviewers,
            "reviewer_roster_ready": len(reviewers) >= 2,
            "browser_reviewer_authentication_ready": False,
            "unsigned_export_ready": bool(reviewers),
            "pipeline": pipeline,
            "cases": summaries,
            "case": cases.get(case_id) if case_id else None,
            "canonical_path": (
                f"/benchmark/output-review?case={urllib.parse.quote(case_id)}"
                if case_id else "/benchmark/output-review"
            ),
            "limitations": [
                "The browser prepares an unsigned blinded review record and does not sign or submit it.",
                "The five cases are development data and do not satisfy the calibration sample requirement.",
                "Two distinct rostered reviewers and a distinct principal for disagreements remain required.",
            ],
        })

    def _send_candidate_case_authoring(self, draft_id: str | None):
        try:
            packet, roster, submissions, adjudication, review_state, channel_id, signed_events = (
                self._candidate_review_material()
            )
            pipeline = self._pipeline_state(review_state, roster, channel_id)
            approval_ledger = json.loads(CASE_APPROVAL_LEDGER.read_text(encoding="utf-8"))
            registration_ledger = json.loads(CASE_REGISTRATION_LEDGER.read_text(encoding="utf-8"))
        except (BuzzUnavailable, OSError, json.JSONDecodeError, ValueError) as exc:
            self._send_json({"error": "case_authoring_state_invalid", "detail": str(exc)}, status=409)
            return
        drafts = {item["draft_id"]: item for item in packet["drafts"]}
        if draft_id and draft_id not in drafts:
            self._send_json({"error": "unknown_candidate_draft", "draft_id": draft_id}, status=404)
            return
        eligible_ids = set(review_state.get("eligible_draft_ids", []))
        rejected_ids = set(review_state.get("rejected_draft_ids", []))
        approved_ids = {
            item.get("draft_id") for item in approval_ledger.get("records", [])
        }
        registered_ids = {
            item.get("draft_id") for item in registration_ledger.get("registrations", [])
        }
        owners = [
            {
                "reviewer_id": item["reviewer_id"],
                "display_name": item["display_name"],
                "qualification": item["qualification"],
                "buzz_pubkey": item["buzz_pubkey"],
            }
            for item in roster.get("reviewers", [])
            if item.get("active") is True and item.get("role") == "domain_case_owner"
        ]
        summaries = []
        for item in packet["drafts"]:
            item_id = item["draft_id"]
            status = (
                "registered_case" if item_id in registered_ids
                else "approval_recorded" if item_id in approved_ids
                else "eligible_for_case_authoring" if item_id in eligible_ids
                else "rejected_by_source_review" if item_id in rejected_ids
                else "blocked_by_source_review"
            )
            summaries.append({
                "draft_id": item_id,
                "candidate_id": item["candidate_id"],
                "company": item["company"],
                "question_family": item["question_family"],
                "task_family": item["task_family"],
                "provisional_question": item["provisional_question"],
                "status": status,
            })
        response = {
            "packet_sha256": candidate_review_packet_sha256(packet),
            "eligible_draft_count": len(eligible_ids),
            "eligible_drafts": [item for item in summaries if item["draft_id"] in eligible_ids],
            "domain_case_owners": owners,
            "owner_roster_ready": bool(owners),
            "browser_owner_authentication_ready": False,
            "unsigned_export_ready": bool(eligible_ids and owners),
            "pipeline": pipeline,
            "drafts": summaries,
            "authoring_material": None,
            "canonical_path": (
                f"/benchmark/case-authoring?draft={urllib.parse.quote(draft_id)}"
                if draft_id else "/benchmark/case-authoring"
            ),
            "limitations": [
                "The browser can prepare an unsigned owner approval but cannot sign it.",
                "Only development and calibration cases can be stored in this repository.",
                "A signed approval must be recorded before a separate registration commit.",
            ],
        }
        if not draft_id:
            self._send_json(response)
            return
        summary = next(item for item in summaries if item["draft_id"] == draft_id)
        if draft_id not in eligible_ids:
            self._send_json({
                "error": "draft_not_eligible_for_case_authoring",
                "draft_id": draft_id,
                "status": summary["status"],
                "pipeline": pipeline,
            }, status=409)
            return
        try:
            response["authoring_material"] = build_candidate_case_authoring_material(
                PROJECT_ROOT,
                packet,
                submissions,
                adjudication,
                draft_id,
                reviewer_roster=roster,
                signed_events=signed_events,
            )
        except ValueError as exc:
            self._send_json({"error": "case_authoring_material_invalid", "detail": str(exc)}, status=409)
            return
        self._send_json(response)

    def _send_candidate_source_context(self, draft_id: str | None, citation: str | None):
        if not draft_id or not citation:
            self._send_json({"error": "draft_and_citation_required"}, status=400)
            return
        try:
            packet = build_candidate_source_review_packet(PROJECT_ROOT)
            draft = next(item for item in packet["drafts"] if item["draft_id"] == draft_id)
        except StopIteration:
            self._send_json({"error": "unknown_candidate_draft", "draft_id": draft_id}, status=404)
            return
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            self._send_json({"error": "source_review_state_invalid", "detail": str(exc)}, status=409)
            return
        option = next(
            (item for item in draft["evidence_options"] if item["citation"] == citation), None,
        )
        if option is None:
            self._send_json({"error": "citation_not_in_review_packet"}, status=400)
            return
        source = next(
            (
                item for item in draft_sources(draft)
                if item.get("sha256") == option.get("source_sha256")
                and option.get("citation", "").startswith(f"[{item.get('filename')}#")
            ),
            None,
        )
        if source is None:
            self._send_json({"error": "citation_source_not_admitted"}, status=409)
            return
        evidence_path = (PROJECT_ROOT / source["acquisition_evidence_path"]).resolve()
        try:
            evidence_path.relative_to(PROJECT_ROOT)
            if sha256(evidence_path) != source["acquisition_evidence_sha256"]:
                raise ValueError("acquisition evidence hash differs from the review packet")
            acquisition = json.loads(evidence_path.read_text(encoding="utf-8"))
            source_path = (PROJECT_ROOT / acquisition["source"]["path"]).resolve()
            source_path.relative_to(PROJECT_ROOT)
            if sha256(source_path) != source["sha256"]:
                raise ValueError("source hash differs from the review packet")
            document = DealRoomParser().parse_file(str(source_path))
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            self._send_json({"error": "source_context_unavailable", "detail": str(exc)}, status=409)
            return
        nodes = []

        def collect(node):
            anchor = node.metadata.get("source_anchor")
            parts = [str(item) for item in (node.title, node.content) if item]
            if node.table_data is not None:
                parts.append(node.table_data.to_markdown())
            text = "\n".join(parts).strip()
            if anchor and text:
                nodes.append({"anchor": anchor, "text": text[:8_000]})
            for child in node.children:
                collect(child)

        collect(document.root_node)
        match_index = next(
            (index for index, item in enumerate(nodes) if item["anchor"] == option["anchor"]), None,
        )
        if match_index is None:
            self._send_json({"error": "source_anchor_not_found"}, status=409)
            return
        start = max(0, match_index - 2)
        end = min(len(nodes), match_index + 3)
        self._send_json({
            "draft_id": draft_id,
            "citation": citation,
            "source_filename": source["filename"],
            "source_sha256": source["sha256"],
            "selected_anchor": option["anchor"],
            "context": [
                {**item, "selected": index == match_index}
                for index, item in enumerate(nodes[start:end], start=start)
            ],
            "context_is_source_parsed": True,
            "context_window": "two parsed nodes before and after the selected anchor",
        })

    def _receive_candidate_source_review(self, payload: dict[str, Any]):
        allowed = {
            "draft_id", "reviewer_id", "source_context_checked", "decision",
            "final_question", "answer_policy", "supporting_citations",
            "confusable_citations", "expected_claims", "absence_basis", "rationale",
        }
        unexpected = set(payload) - allowed
        if unexpected:
            self._send_json({"error": "unexpected_review_fields", "fields": sorted(unexpected)}, status=400)
            return
        try:
            packet, roster, submissions, _, _, _, _ = self._candidate_review_material()
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            self._send_json({"error": "source_review_state_invalid", "detail": str(exc)}, status=409)
            return
        reviewer = next(
            (
                item for item in roster["reviewers"]
                if item["reviewer_id"] == payload.get("reviewer_id")
                and item["active"]
                and item["role"] == "qualified_deal_source_reviewer"
            ),
            None,
        )
        if reviewer is None:
            self._send_json({"error": "reviewer_not_rostered"}, status=403)
            return
        self._send_json({
            "error": "signed_reviewer_attestation_required",
            "detail": (
                "Browser submission is disabled until the two-phase Buzz signing flow is "
                "implemented. Use a rostered reviewer key and the validation CLI."
            ),
        }, status=501)
        return

    def _send_workspace(self, room_id: str):
        rooms = all_deal_rooms()
        if room_id not in rooms:
            self._send_json({"error": "unknown_deal_room", "deal_room": room_id}, status=404)
            return
        binding_ok, workspace = self._buzz_room_binding(room_id)
        if not binding_ok:
            return
        if workspace is None:
            self._send_json({"error": "workspace_not_bound", "room": room_id}, status=409)
            return
        room_data = self._get_deal_room_data(room_id)
        room_data["workspace"] = workspace
        room_data["buzz"] = global_buzz.status()
        room_data["canonical_path"] = f"/rooms/{room_id}"
        self._send_json(room_data)

    def _workspace_messages_payload(self, room_id: str) -> Dict[str, Any] | None:
        binding_ok, workspace = self._buzz_room_binding(room_id)
        if not binding_ok:
            return
        if workspace is None:
            self._send_json({"error": "workspace_not_bound", "room": room_id}, status=409)
            return
        try:
            messages = global_buzz.verified_messages(workspace["channel_id"])
        except BuzzUnavailable as exc:
            self._send_json({"error": "buzz_unavailable", "detail": str(exc)}, status=503)
            return
        room = all_deal_rooms().get(room_id)
        if room is not None:
            current_evidence_inventory = None
            try:
                inspection = inspect_local_deal_room(room["path"])
                current_source_snapshot = inspection["preview"]["preview_sha256"]
                current_provenance = source_provenance_binding(room)
                current_evidence_inventory = build_evidence_inventory(
                    inspection["documents"],
                    source_snapshot_sha256=current_source_snapshot,
                )
            except (FileNotFoundError, ValueError, NotADirectoryError, PermissionError, OSError):
                current_source_snapshot = None
                current_provenance = None
            agent_pubkey = str(global_buzz.status().get("agent_pubkey") or "")
            traces = global_tracer.snapshot()
            message_views = []
            for message in messages:
                view = dict(message)
                content = str(message.get("content", ""))
                is_prism_agent_artifact = (
                    message.get("pubkey") == agent_pubkey
                    and content.startswith((
                        "<!-- prism:deal-room-answer ",
                        "<!-- prism:first-pass-draft ",
                    ))
                )
                acceptance_state = None
                if is_prism_agent_artifact and current_provenance is not None:
                    if content.startswith("<!-- prism:deal-room-answer "):
                        acceptance_state = trace_bound_deal_room_message_state(
                            message,
                            traces,
                            room_id=room_id,
                            agent_pubkey=agent_pubkey,
                            current_provenance=current_provenance,
                            current_source_snapshot=str(current_source_snapshot),
                            current_evidence_inventory=current_evidence_inventory,
                        )
                        if acceptance_state == "accepted":
                            trace_match = re.search(r"(?:^|\s)trace=(trc_[0-9a-f]{12})", content)
                            trace = next((
                                item for item in traces
                                if trace_match and item.trace_id == trace_match.group(1)
                            ), None)
                            if trace is not None:
                                view["prism_evidence_scope"] = evidence_scope_for_anchors(
                                    current_evidence_inventory,
                                    trace.metadata.get("retrieved_anchors", []),
                                )
                    else:
                        restored = restore_trace_bound_first_pass(
                            [message],
                            traces,
                            room_id=room_id,
                            agent_pubkey=agent_pubkey,
                            current_provenance=current_provenance,
                            current_source_snapshot=str(current_source_snapshot),
                            current_evidence_inventory=current_evidence_inventory,
                        )
                        acceptance_state = (
                            restored.get("acceptance_state") if restored else None
                        )
                        if restored is not None:
                            view["prism_evidence_scope"] = restored.get("evidence_scope")
                if is_prism_agent_artifact and acceptance_state is None:
                    view["prism_acceptance_state"] = "quarantined_uncommitted"
                    view["display_content"] = (
                        "**Uncommitted agent event quarantined**\n\n"
                        "Buzz verified this signed event, but Prism found no matching trace and "
                        "current source binding. The candidate content is not presented as an answer."
                    )
                elif acceptance_state is not None:
                    view["prism_acceptance_state"] = acceptance_state
                    if content.startswith("<!-- prism:deal-room-answer "):
                        view["prism_guard_version"] = DEAL_ROOM_CHAT_GUARD_VERSION
                message_views.append(view)
            messages = message_views
        return {
            "room": room_id,
            "channel_id": workspace["channel_id"],
            "messages": messages,
            "signature_verification": {
                "state": "verified",
                "scheme": "nip01_event_id_plus_bip340",
                "verified_event_count": len(messages),
            },
        }

    def _send_workspace_messages(self, room_id: str):
        payload = self._workspace_messages_payload(room_id)
        if payload is not None:
            self._send_json(payload)

    def _phoenix_status(self) -> Dict[str, Any]:
        live = False
        try:
            with urllib.request.urlopen(PHOENIX_ENDPOINT, timeout=1.5) as response:
                live = response.status < 500
        except (OSError, urllib.error.URLError):
            live = False
        return {
            "configured": bool(PHOENIX_ENDPOINT),
            "live": live,
            "endpoint": PHOENIX_ENDPOINT or None,
            "export_policy": "manual_explicit_export_only",
            "content_policy": "hashes_only_unless_operator_opts_in",
        }

    def _workspace_review_store(self, room_id: str) -> WorkspaceReviewStore | None:
        if room_id not in all_deal_rooms():
            self._send_json({"error": "unknown_deal_room", "room": room_id}, status=404)
            return None
        messages = self._workspace_messages_payload(room_id)
        if messages is None:
            return None
        buzz = global_buzz.status()
        corpus = build_review_corpus(
            messages["messages"],
            agent_key=str(buzz.get("agent_pubkey") or ""),
            operator_key=str(buzz.get("operator_pubkey") or ""),
        )
        return WorkspaceReviewStore(WORKSPACE_REVIEW_DATA, room_id, corpus)

    def _send_workspace_evaluation(self, room_id: str):
        store = self._workspace_review_store(room_id)
        if store is not None:
            self._send_json(store.snapshot(phoenix=self._phoenix_status()))

    def _send_workspace_evaluation_dashboard(self, room_id: str):
        store = self._workspace_review_store(room_id)
        if store is None:
            return
        review = store.snapshot(phoenix=self._phoenix_status())
        try:
            experiments = global_evaluation_experiments.snapshot(room_id)
        except ValueError as exc:
            self._send_json({
                "error": "experiment_store_integrity_error",
                "detail": str(exc),
            }, status=503)
            return
        self._send_json(build_evaluation_dashboard(
            PROJECT_ROOT,
            room=room_id,
            review_snapshot=review,
            provider_statuses=[status.__dict__ for status in global_providers.statuses()],
            experiment_snapshot=experiments,
        ))

    def _send_workspace_evaluation_observability(
        self, room_id: str, include_content: bool,
    ):
        store = self._workspace_review_store(room_id)
        if store is not None:
            self._send_json(store.observability(include_content=include_content))

    def _send_workspace_digest(self, room_id: str):
        binding_ok, workspace = self._buzz_room_binding(room_id)
        if not binding_ok:
            return
        if workspace is None:
            self._send_json({"error": "workspace_not_bound", "room": room_id}, status=409)
            return
        try:
            digest = global_buzz.verified_canvas(workspace["channel_id"])
        except BuzzUnavailable as exc:
            self._send_json({"error": "buzz_unavailable", "detail": str(exc)}, status=503)
            return
        # A signed canvas write is necessary but not sufficient for a completed
        # local review. Publishing the canvas, review message, and trace update
        # spans separate stores. If a later write fails, the canvas can exist
        # without the evidence chain that authorizes Prism to present it as the
        # reviewed brief. Fail closed until the exact canvas event is restored
        # through the trace-bound review transaction.
        if "## Local operator review" in str(digest.get("markdown", "")):
            try:
                committed = self._first_pass_record(room_id, workspace)
            except BuzzUnavailable as exc:
                self._send_json({
                    "error": "reviewed_digest_unavailable",
                    "detail": f"The reviewed canvas did not restore from its evidence chain: {exc}",
                }, status=503)
                return
            review = committed.get("review") if isinstance(committed, dict) else None
            if (
                not isinstance(review, dict)
                or review.get("canvas_event_id") != digest.get("event_id")
            ):
                self._send_json({
                    "error": "uncommitted_review_canvas",
                    "detail": (
                        "Buzz contains a signed review canvas, but Prism has no matching "
                        "trace-bound review commit. The canvas is not presented as a reviewed brief."
                    ),
                    "canvas_event_id": digest.get("event_id"),
                }, status=409)
                return
        self._send_json({
            "room": room_id,
            "channel_id": workspace["channel_id"],
            **digest,
        })

    def _first_pass_record(
        self,
        room_id: str,
        workspace: Dict[str, str] | None = None,
    ) -> Dict[str, Any] | None:
        if workspace is None:
            workspace = global_buzz.room(room_id)
        if workspace is None:
            return None
        try:
            messages = global_buzz.verified_messages(workspace["channel_id"])
        except BuzzUnavailable:
            return None
        room = all_deal_rooms().get(room_id)
        if room is None:
            return None
        try:
            inspection = inspect_local_deal_room(room["path"])
            current_source_snapshot = inspection["preview"]["preview_sha256"]
            current_provenance = source_provenance_binding(room)
            current_evidence_inventory = build_evidence_inventory(
                inspection["documents"],
                source_snapshot_sha256=current_source_snapshot,
            )
        except (FileNotFoundError, ValueError, NotADirectoryError, PermissionError, OSError):
            return None
        restored = restore_trace_bound_first_pass(
            messages,
            global_tracer.snapshot(),
            room_id=room_id,
            agent_pubkey=str(global_buzz.status().get("agent_pubkey") or ""),
            current_provenance=current_provenance,
            current_source_snapshot=current_source_snapshot,
            current_evidence_inventory=current_evidence_inventory,
        )
        if restored is None:
            return None
        trace = next(
            (item for item in global_tracer.snapshot() if item.trace_id == restored["trace_id"]),
            None,
        )
        claimed_review = trace.metadata.get("human_review") if trace is not None else None
        if claimed_review is not None:
            if not isinstance(claimed_review, dict):
                raise BuzzUnavailable("Persisted local review is not an object")
            event_ids = {
                str(claimed_review.get("review_event_id", "")),
                str(claimed_review.get("canvas_event_id", "")),
            }
            raw_events = global_buzz.events_by_ids(
                event_ids, channel_id=workspace["channel_id"],
            )
            if set(raw_events) != event_ids:
                raise BuzzUnavailable("Buzz did not restore both local review events")
            restored["review"] = restore_trace_bound_local_review(
                claimed_review,
                draft=restored,
                room_id=room_id,
                room_name=all_deal_rooms()[room_id]["name"],
                operator_pubkey=str(global_buzz.status().get("operator_pubkey") or ""),
                review_event=raw_events[str(claimed_review["review_event_id"])],
                canvas_event=raw_events[str(claimed_review["canvas_event_id"])],
            )
        return restored

    def _send_workspace_first_pass(self, room_id: str):
        if room_id not in all_deal_rooms():
            self._send_json({"error": "unknown_deal_room", "room": room_id}, status=404)
            return
        binding_ok, workspace = self._buzz_room_binding(room_id)
        if not binding_ok:
            return
        if workspace is None:
            self._send_json({"error": "workspace_not_bound", "room": room_id}, status=409)
            return
        try:
            draft = self._first_pass_record(room_id, workspace)
        except BuzzUnavailable as exc:
            self._send_json({
                "error": "first_pass_review_unavailable", "detail": str(exc),
            }, status=503)
            return
        self._send_json({
            "room": room_id,
            "default_investment_screen": DEFAULT_INVESTMENT_SCREEN,
            "draft": draft,
            "canonical_path": f"/rooms/{room_id}/first-pass",
        })

    def _get_status_data(self) -> Dict[str, Any]:
        cloud_authority = CloudConsentAuthority.from_env()
        buzz_status = global_buzz.status()
        cloud_ledger_path = Path(os.environ.get(
            "PRISM_CLOUD_CONSENT_LEDGER",
            str(PROJECT_ROOT / ".runtime" / "cloud-consent-uses.v1.json"),
        ))
        recorded_local_invocations = [
            trace for trace in global_tracer.snapshot()
            if trace.metadata.get("provider_id") == "local_bonsai"
        ]
        current_process_local_invocations = [
            trace for trace in global_tracer.traces_from_current_process()
            if trace.metadata.get("provider_id") == "local_bonsai"
        ]
        recorded_local_invocation = bool(recorded_local_invocations)
        current_process_local_invocation = bool(current_process_local_invocations)

        return {
            "product_stage": "local_prototype",
            "server_process_pid": os.getpid(),
            "server_process_started_at": SERVER_PROCESS_STARTED_AT,
            "buzz": buzz_status,
            "buzz_acp_scope": {
                "configured": bool(os.environ.get("PRISM_BUZZ_ACP_ROOM_ID")),
                "experimental": os.environ.get("PRISM_BUZZ_ACP_EXPERIMENTAL") == "true",
                "room_id": os.environ.get("PRISM_BUZZ_ACP_ROOM_ID"),
                "channel_id": os.environ.get("PRISM_BUZZ_ACP_CHANNEL_ID"),
                "source_scope": os.environ.get("PRISM_BUZZ_ACP_SOURCE_SCOPE"),
                "subscription": "single_room_mentions" if os.environ.get("PRISM_BUZZ_ACP_ROOM_ID") else None,
                "respond_to": "owner_only" if os.environ.get("PRISM_BUZZ_ACP_ROOM_ID") else None,
                "memory": "disabled" if os.environ.get("PRISM_BUZZ_ACP_ROOM_ID") else None,
                "meaning": (
                    "Direct Buzz mentions are served only for this exact room and source folder. "
                    "The Prism WebUI provider path remains separately source-scoped per request."
                    if os.environ.get("PRISM_BUZZ_ACP_ROOM_ID") else
                    "No direct Buzz ACP process was declared by this server launcher."
                ),
            },
            "local_inference_configured": global_providers.local.configured,
            "local_inference_invoked_in_process": current_process_local_invocation,
            "local_inference_invoked": recorded_local_invocation,
            "local_inference_recorded_history": recorded_local_invocation,
            "local_inference_invocation_evidence": (
                "current_process_trace"
                if current_process_local_invocation
                else "recorded_trace_history"
                if recorded_local_invocation
                else None
            ),
            "configured_local_provider_id": (
                "local_bonsai" if global_providers.local.configured else None
            ),
            "configured_local_provider_network_scope": (
                global_providers.local.status().network_scope
                if global_providers.local.configured else None
            ),
            "last_invoked_local_model": (
                recorded_local_invocations[-1].model_name
                if recorded_local_invocations else None
            ),
            "current_process_local_model": (
                current_process_local_invocations[-1].model_name
                if current_process_local_invocations else None
            ),
            "providers": [s.__dict__ for s in global_providers.statuses()],
            "cloud_consent": {
                "authority_configured": cloud_authority.configured,
                "provider_configured": global_providers.cloud.configured,
                "dispatch_ready_for_signed_request": bool(
                    cloud_authority.configured and global_providers.cloud.configured
                    and buzz_status.get("workspace_ready") is True
                ),
                "dispatch_configured_for_signed_request": bool(
                    cloud_authority.configured and global_providers.cloud.configured
                ),
                "context_release_requires_distinct_signature": True,
                "relay_restoration_required": True,
                "maximum_consent_lifetime_seconds": 900,
                "replay_ledger": str(cloud_ledger_path),
                "default": "deny_before_network",
                "meaning": (
                    "Cloud dispatch needs a short-lived policy Buzz signature. Deal-room context "
                    "needs a second signature from a distinct configured data-owner key. Prism must "
                    "restore each exact event from Buzz before consuming it or calling the provider. "
                    "Both bind the prompt hash, room snapshot, provider, model, nonce, and expiry."
                ),
            },
            "measured_local_deployment": measured_local_deployment_status(),
            "trace_store": global_tracer.storage_status(),
            "document_ingestion": {
                "supported_types": ["md", "txt", "csv", "json", "html", "xlsx", "pdf"],
                "pdf_ocr": ocr_toolchain_status(),
                "meaning": (
                    "PDF pages without usable embedded text use bounded Apple Vision OCR when "
                    "the measured macOS toolchain is available. OCR does not reconstruct tables "
                    "or document layout, and its accuracy has not been benchmarked."
                ),
            },
            "analysis_engine": (
                "provider_backed_agent_with_deterministic_baseline"
                if global_providers.local.configured or global_providers.cloud.configured
                else "deterministic_template_runner"
            ),
            "configured_local_model_name": (
                global_providers.local.model if global_providers.local.configured else None
            ),
            "local_only_policy": True,
            "network_binding": "loopback_only",
            "network_binding_scope": "prism_http_server",
            "sandbox_level": "AST validation, subprocess limits, and a macOS sandbox-exec profile when available",
            "limitations": [
                ("The local provider URL uses an HTTP loopback IP literal, but configuration "
                 "alone does not prove reachability or a loaded artifact; use an invocation "
                 "trace or saved benchmark."
                 if global_providers.local.configured else
                 "No local AI provider endpoint is configured for this server process."),
                "Loopback binding is not certified network isolation.",
                "The macOS profile denies child network access, process forks, and reads under /Users, /Volumes, and /Network. It confines writes to one temporary run directory, but it is not a hardened multi-tenant security boundary.",
                (
                    "A prior local invocation exists in the trace history, but this server "
                    "process has not invoked the provider."
                    if recorded_local_invocation and not current_process_local_invocation
                    else "Current process invocation state is reported separately from trace history."
                ),
            ],
            "loopback_host": "127.0.0.1",
        }

    def _get_deal_room_data(self, room_id: str) -> Dict[str, Any]:
        rooms = all_deal_rooms()
        if room_id not in rooms:
            raise KeyError(room_id)
        room_info = rooms[room_id]
        folder_path = room_info["path"]
        
        parser = DealRoomParser()
        docs = parser.parse_deal_room_folder(folder_path)
        docs_summary = []

        for doc in docs:
            anchors: Dict[str, str] = {}
            preview_parts: List[str] = []
            structured_preview = None

            def collect_node_preview(node, section_titles=()):
                text = evidence_node_text(node, section_titles, max_chars=4_000)
                if text:
                    source_anchor = node.metadata.get("source_anchor")
                    anchors[str(source_anchor) if source_anchor else f"node:{node.id}"] = text
                    preview_parts.append(text)
                child_titles = section_titles
                if node.node_type == "section" and node.title:
                    child_titles = (*section_titles, str(node.title))
                for child in node.children:
                    collect_node_preview(child, child_titles)

            collect_node_preview(doc.root_node)
            tables_data = []
            for tbl in doc.extracted_tables:
                tables_data.append({
                    "id": tbl.id,
                    "caption": tbl.caption,
                    "num_rows": tbl.num_rows,
                    "num_cols": tbl.num_cols,
                    "matrix": tbl.to_matrix(),
                    "raw_csv": tbl.raw_csv,
                })

            if doc.file_type == "json" and doc.raw_size_bytes <= 12_000:
                try:
                    with open(doc.file_path, "r", encoding="utf-8") as source_file:
                        structured_preview = json.load(source_file)
                except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                    structured_preview = None

            docs_summary.append({
                "doc_id": doc.doc_id,
                "filename": doc.filename,
                "file_type": doc.file_type,
                "raw_size_bytes": doc.raw_size_bytes,
                "estimated_tokens": doc.estimated_token_count,
                "table_count": len(doc.extracted_tables),
                "tables": tables_data,
                "parser_facts": {
                    key: doc.metadata[key]
                    for key in (
                        "source_sha256",
                        "citation_scheme",
                        "sheet_count",
                        "nonempty_cell_count",
                        "formula_cell_count",
                        "cached_formula_cell_count",
                        "unevaluated_formula_cell_count",
                        "formatted_numeric_cell_count",
                        "unsupported_number_format_cell_count",
                        "formula_policy",
                        "formatting_policy",
                        "external_relationships_followed",
                        "macros_executed",
                        "declared_page_count",
                        "extracted_page_count",
                        "ocr_applied",
                        "ocr_page_numbers",
                        "ocr_engine",
                        "ocr_render_dpi",
                        "ocr_recognition_level",
                        "ocr_language_correction",
                        "ocr_mean_confidence",
                        "ocr_accuracy_measured",
                        "ocr_layout_reconstruction",
                        "ocr_limitations",
                    )
                    if key in doc.metadata
                },
                "anchors": anchors,
                "structured_preview": structured_preview,
                "preview_text": "\n\n".join(preview_parts)[:12_000]
                or "No text-bearing parser node was available.",
            })

        return {
            "room_id": room_id,
            "room_name": room_info["name"],
            "deal_type": room_info["type"],
            "description": room_info["description"],
            "source_provenance": room_info.get("source_provenance")
            or room_source_provenance(room_info),
            "folder_path": folder_path,
            "total_documents": len(docs_summary),
            "total_tokens": sum(d["estimated_tokens"] for d in docs_summary),
            "documents": docs_summary,
            "parse_warnings": parser.last_warnings,
        }

    def _get_evals_data(self) -> Dict[str, Any]:
        traces_data = []
        for t in global_tracer.snapshot():
            excluded = t.metadata.get("exclude_from_aggregate_metrics") is True
            evaluation_state = (
                {
                    "state": "excluded",
                    "label": "Excluded fixture",
                    "explanation": str(
                        t.metadata.get("trace_provenance", {}).get(
                            "reason", "This trace is retained in history but excluded from metrics."
                        )
                    ),
                }
                if excluded else evaluation_release_state(t.evaluations)
            )
            traces_data.append({
                "trace_id": t.trace_id,
                "session_id": t.session_id,
                "timestamp": t.timestamp,
                "query": t.query,
                "response_sha256": hashlib.sha256(t.response.encode("utf-8")).hexdigest(),
                "model_name": t.model_name,
                "routed_tier": t.routed_tier,
                "total_tokens": t.total_tokens,
                "total_latency_ms": round(t.total_latency_ms, 2),
                "energy_per_token_mwh": (round(t.energy_per_token_mwh, 4)
                                         if t.energy_per_token_mwh is not None else None),
                "total_energy_mwh": (round(t.total_energy_mwh, 2)
                                     if t.total_energy_mwh is not None else None),
                "vram_peak_gb": round(t.vram_peak_gb, 2) if t.vram_peak_gb is not None else None,
                "metadata": t.metadata,
                "evaluation_state": evaluation_state,
                "spans": [
                    {
                        "span_id": s.span_id,
                        "name": s.name,
                        "kind": s.span_kind,
                        "duration_ms": round(s.duration_ms, 2),
                        "status": s.status,
                    }
                    for s in t.spans
                ],
                "evaluations": [
                    {
                        "name": ev.name,
                        "score": ev.score,
                        "passed": ev.passed,
                        "explanation": ev.explanation,
                        "metadata": ev.metadata,
                    }
                    for ev in t.evaluations
                ],
            })

        aggregate_traces = [
            trace for trace in traces_data
            if trace.get("metadata", {}).get("exclude_from_aggregate_metrics") is not True
        ]
        faith_scores = [
            ev["score"] for t in aggregate_traces for ev in t["evaluations"]
            if ev["name"] == "faithfulness" and ev.get("metadata", {}).get("measurement_state") != "unverified"
        ]
        denylist_scores = [ev["score"] for t in aggregate_traces for ev in t["evaluations"] if ev["name"] == "forbidden_string_check"]
        table_scores = [
            ev["score"] for t in aggregate_traces for ev in t["evaluations"]
            if ev["name"] == "tabular_fixture_cell_match" and ev.get("metadata", {}).get("measurement_state") != "unverified"
        ]

        return {
            "total_recorded_traces": len(traces_data),
            "aggregate_eligible_traces": len(aggregate_traces),
            "excluded_trace_count": len(traces_data) - len(aggregate_traces),
            "avg_faithfulness": round(sum(faith_scores) / len(faith_scores), 4) if faith_scores else None,
            "avg_forbidden_string_check": round(sum(denylist_scores) / len(denylist_scores), 4) if denylist_scores else None,
            "avg_tabular_fixture_cell_match": round(sum(table_scores) / len(table_scores), 4) if table_scores else None,
            "traces": traces_data,
        }

    def _get_build_vs_buy_data(self) -> Dict[str, Any]:
        try:
            engineering_record = json.loads(
                CURRENT_LOCAL_ENGINEERING_EVIDENCE.read_text(encoding="utf-8")
            )
            engineering = engineering_evidence_summary(engineering_record, PROJECT_ROOT)
        except (OSError, json.JSONDecodeError) as exc:
            engineering = {
                "verified": False,
                "evidence_verified": False,
                "measurement_state": "engineering_evidence_unavailable",
                "errors": [str(exc)],
            }
        if engineering.get("evidence_verified"):
            benchmark_result = (
                f"{engineering.get('passed_cases')}/{engineering.get('total_cases')} cases passed"
            )
            if engineering.get("benchmark_passed"):
                engineering_rationale = (
                    f"The latest source-bound synthetic engineering regression passed: "
                    f"{benchmark_result}. It does not measure deal-room quality or domain accuracy. "
                    "Fused kernels, VRAM, and energy remain unmeasured."
                )
            else:
                engineering_rationale = (
                    f"The latest source-bound synthetic engineering regression failed: "
                    f"{benchmark_result}. This is valid negative evidence, not a reliability or "
                    "accuracy release. Fused kernels, VRAM, and energy remain unmeasured."
                )
        else:
            engineering_rationale = (
                "The checked-in engineering artifact is missing, stale, or invalid, so this "
                "endpoint makes no Bonsai benchmark claim."
            )
        return {
            "layer_1_compute": {
                "title": "Layer 1: Low-Bit LLM Compute & Edge Acceleration",
                "decision": "ADOPTED FOR PILOT: LM Studio native serving for the named Bonsai artifact; custom kernels remain deferred",
                "engineering_evidence": engineering,
                "rationale": engineering_rationale,
            },
            "layer_2_ingestion": {
                "title": "Layer 2: Document Ingestion & Structural Extraction",
                "decision": "CURRENT: internal MD/TXT/CSV/JSON parser; RESEARCH TARGET: evaluate Docling for richer formats",
                "rationale": "Docling is not installed. Any PDF/layout accuracy or licensing claim requires a separate dependency decision and fixture benchmark.",
            },
            "layer_3_sandboxing": {
                "title": "Layer 3: Agent Execution Sandboxing & Runtime Isolation",
                "decision": "CURRENT: AST allowlist, subprocess limits, and a macOS sandbox-exec profile; TARGET: evaluate hardened VM or container isolation",
                "rationale": "The measured macOS profile denies child network access, process forks, reads under /Users, /Volumes, and /Network, and writes outside one temporary run directory. Other readable system paths remain available. Firecracker and gVisor are not installed, and the current boundary is not safe for hostile multi-tenant code.",
            },
        }


class PrismHTTPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    """Keep status, files, and collaboration responsive during local inference."""

    allow_reuse_address = True
    daemon_threads = True
    block_on_close = True


def run_server(port: int = 8080):
    global global_tracer
    handler = VaultHTTPRequestHandler
    try:
        httpd = PrismHTTPServer(("127.0.0.1", port), handler)
    except OSError as exc:
        raise RuntimeError(
            f"Prism could not bind 127.0.0.1:{port}; the requested port is unavailable. "
            "Refusing to select a different port because that could advertise or open "
            "a different server than the operator intended."
        ) from exc
    try:
        if global_tracer.storage_path is None:
            trace_store = os.environ.get(
                "PRISM_TRACE_STORE",
                str(PROJECT_ROOT / ".runtime" / "evals" / "traces.jsonl"),
            )
            global_tracer = ArizeObservabilityTracer(trace_store)
        with httpd:
            print(f"Prism Vault local prototype listening at http://127.0.0.1:{port}")
            httpd.serve_forever()
    except Exception:
        httpd.server_close()
        raise


if __name__ == "__main__":
    import sys
    port = 8080
    if "--port" in sys.argv:
        idx = sys.argv.index("--port")
        if idx + 1 < len(sys.argv):
            port = int(sys.argv[idx + 1])
    elif len(sys.argv) > 1 and sys.argv[1].isdigit():
        port = int(sys.argv[1])
    run_server(port)
