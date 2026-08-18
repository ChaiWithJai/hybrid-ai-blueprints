"""Append-only, room-scoped experiment records for hybrid AI evaluation."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator


ID_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,127}$")
SHA256_RE = re.compile(r"^[a-f0-9]{64}$")
ROUTE_MODES = {"local", "cloud", "hybrid"}
COMPARISON_FIELDS = (
    "dataset_version",
    "workflow_family",
    "source_snapshot_sha256",
    "question_sha256",
    "evidence_packet_sha256",
    "answer_contract_sha256",
    "limits_sha256",
)
RUN_SHA_FIELDS = (
    "prompt_sha256",
    "source_snapshot_sha256",
    "retrieval_config_sha256",
    "output_sha256",
)


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _require_id(value: Any, name: str) -> str:
    text = str(value or "").strip()
    if not ID_RE.fullmatch(text):
        raise ValueError(f"{name} must be a stable identifier")
    return text


def _require_sha(value: Any, name: str) -> str:
    text = str(value or "").strip().lower()
    if not SHA256_RE.fullmatch(text):
        raise ValueError(f"{name} must be a lowercase SHA-256")
    return text


class ExperimentStore:
    """Persist an integrity-checked event ledger for each Prism room."""

    def __init__(self, base: Path):
        self.base = Path(base)

    def _path(self, room: str) -> Path:
        return self.base / f"{_require_id(room, 'room')}.json"

    @contextmanager
    def _locked(self, room: str) -> Iterator[Path]:
        self.base.mkdir(parents=True, exist_ok=True)
        lock_path = self.base / f"{_require_id(room, 'room')}.lock"
        with lock_path.open("a+", encoding="utf-8") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield self._path(room)
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def _read(self, path: Path, room: str) -> dict[str, Any]:
        if not path.exists():
            return {"schema_version": 1, "room": room, "events": [], "head_sha256": None}
        try:
            ledger = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"experiment ledger is unreadable: {exc}") from exc
        self._verify(ledger, room)
        return ledger

    def _verify(self, ledger: dict[str, Any], room: str) -> None:
        if ledger.get("schema_version") != 1 or ledger.get("room") != room:
            raise ValueError("experiment ledger identity is invalid")
        events = ledger.get("events")
        if not isinstance(events, list):
            raise ValueError("experiment ledger events are invalid")
        previous = None
        for index, event in enumerate(events):
            if not isinstance(event, dict) or event.get("sequence") != index + 1:
                raise ValueError("experiment ledger sequence is invalid")
            if event.get("previous_sha256") != previous:
                raise ValueError("experiment ledger hash chain is invalid")
            material = {key: value for key, value in event.items() if key != "event_sha256"}
            expected = _sha256(material)
            if event.get("event_sha256") != expected:
                raise ValueError("experiment ledger event hash is invalid")
            previous = expected
        if ledger.get("head_sha256") != previous:
            raise ValueError("experiment ledger head is invalid")

    def _write(self, path: Path, ledger: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(ledger, handle, indent=2, sort_keys=True)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def _append(self, ledger: dict[str, Any], kind: str, payload: dict[str, Any]) -> dict[str, Any]:
        event = {
            "sequence": len(ledger["events"]) + 1,
            "recorded_at": datetime.now(timezone.utc).isoformat(),
            "kind": kind,
            "payload": payload,
            "previous_sha256": ledger.get("head_sha256"),
        }
        event["event_sha256"] = _sha256(event)
        ledger["events"].append(event)
        ledger["head_sha256"] = event["event_sha256"]
        return event

    def create_experiment(self, room: str, record: dict[str, Any]) -> dict[str, Any]:
        payload = dict(record)
        payload["experiment_id"] = _require_id(payload.get("experiment_id"), "experiment_id")
        payload["name"] = str(payload.get("name") or "").strip()
        if not payload["name"]:
            raise ValueError("name is required")
        payload["route_mode"] = str(payload.get("route_mode") or "").strip().lower()
        if payload["route_mode"] not in ROUTE_MODES:
            raise ValueError("route_mode must be local, cloud, or hybrid")
        for field in COMPARISON_FIELDS:
            value = payload.get(field)
            if field.endswith("_sha256"):
                payload[field] = _require_sha(value, field)
            elif not str(value or "").strip():
                raise ValueError(f"{field} is required")
            else:
                payload[field] = str(value).strip()
        payload["comparison_contract_sha256"] = _sha256({
            field: payload[field] for field in COMPARISON_FIELDS
        })
        payload["baseline_experiment_id"] = (
            _require_id(payload["baseline_experiment_id"], "baseline_experiment_id")
            if payload.get("baseline_experiment_id") else None
        )
        payload["answer_model"] = str(payload.get("answer_model") or "").strip() or None
        payload["judge_model"] = str(payload.get("judge_model") or "").strip() or None
        payload["evaluator_version"] = str(payload.get("evaluator_version") or "").strip()
        if not payload["evaluator_version"]:
            raise ValueError("evaluator_version is required")

        with self._locked(room) as path:
            ledger = self._read(path, room)
            snapshot = self._snapshot(ledger)
            if payload["experiment_id"] in snapshot["experiments"]:
                raise ValueError("experiment_id already exists")
            if payload["baseline_experiment_id"] and payload["baseline_experiment_id"] not in snapshot["experiments"]:
                raise ValueError("baseline experiment does not exist in this room")
            if payload["baseline_experiment_id"] and (
                snapshot["experiments"][payload["baseline_experiment_id"]]["comparison_contract_sha256"]
                != payload["comparison_contract_sha256"]
            ):
                raise ValueError("baseline experiment has a different comparison contract")
            event = self._append(ledger, "experiment_created", payload)
            self._write(path, ledger)
            return event

    def append_run(self, room: str, record: dict[str, Any]) -> dict[str, Any]:
        payload = dict(record)
        payload["run_id"] = _require_id(payload.get("run_id"), "run_id")
        payload["experiment_id"] = _require_id(payload.get("experiment_id"), "experiment_id")
        payload["case_id"] = _require_id(payload.get("case_id"), "case_id")
        payload["repetition"] = int(payload.get("repetition", 1))
        if payload["repetition"] < 1:
            raise ValueError("repetition must be at least one")
        for field in RUN_SHA_FIELDS:
            payload[field] = _require_sha(payload.get(field), field)
        for field in ("answer_model", "evaluator_version", "started_at", "ended_at", "content_exposure"):
            payload[field] = str(payload.get(field) or "").strip()
            if not payload[field]:
                raise ValueError(f"{field} is required")
        payload["judge_model"] = str(payload.get("judge_model") or "").strip() or None
        for field in ("latency_ms", "input_tokens", "output_tokens"):
            if not isinstance(payload.get(field), (int, float)) or payload[field] < 0:
                raise ValueError(f"{field} must be a nonnegative number")
        for field in ("cost_usd", "energy_mwh_per_token"):
            if payload.get(field) is not None and (
                not isinstance(payload[field], (int, float)) or payload[field] < 0
            ):
                raise ValueError(f"{field} must be null or a nonnegative number")
        if not isinstance(payload.get("egress_authorized"), bool):
            raise ValueError("egress_authorized must be boolean")
        if payload.get("runtime_error") is not None:
            payload["runtime_error"] = str(payload["runtime_error"])
        metrics = payload.get("metrics", {})
        if not isinstance(metrics, dict) or any(
            value is not None and not isinstance(value, (int, float, bool, str))
            for value in metrics.values()
        ):
            raise ValueError("metrics must contain scalar or null values")

        with self._locked(room) as path:
            ledger = self._read(path, room)
            snapshot = self._snapshot(ledger)
            experiment = snapshot["experiments"].get(payload["experiment_id"])
            if experiment is None:
                raise ValueError("experiment does not exist in this room")
            if payload["source_snapshot_sha256"] != experiment["source_snapshot_sha256"]:
                raise ValueError("run source snapshot differs from the experiment contract")
            if payload["answer_model"] != experiment.get("answer_model"):
                raise ValueError("run answer model differs from the experiment contract")
            if payload["judge_model"] != experiment.get("judge_model"):
                raise ValueError("run judge model differs from the experiment contract")
            if payload["evaluator_version"] != experiment.get("evaluator_version"):
                raise ValueError("run evaluator version differs from the experiment contract")
            if payload["run_id"] in snapshot["runs"]:
                raise ValueError("run_id already exists")
            pair_key = (payload["experiment_id"], payload["case_id"], payload["repetition"])
            if any(
                (run["experiment_id"], run["case_id"], run["repetition"]) == pair_key
                for run in snapshot["runs"].values()
            ):
                raise ValueError("case repetition already exists in this experiment")
            payload["dataset_version"] = experiment["dataset_version"]
            payload["workflow_family"] = experiment["workflow_family"]
            payload["route_mode"] = experiment["route_mode"]
            payload["comparison_contract_sha256"] = experiment["comparison_contract_sha256"]
            event = self._append(ledger, "run_recorded", payload)
            self._write(path, ledger)
            return event

    def _snapshot(self, ledger: dict[str, Any]) -> dict[str, Any]:
        experiments: dict[str, dict[str, Any]] = {}
        runs: dict[str, dict[str, Any]] = {}
        for event in ledger["events"]:
            payload = dict(event["payload"])
            payload["event_sha256"] = event["event_sha256"]
            payload["recorded_at"] = event["recorded_at"]
            if event["kind"] == "experiment_created":
                experiments[payload["experiment_id"]] = payload
            elif event["kind"] == "run_recorded":
                runs[payload["run_id"]] = payload
        return {
            "schema_version": 1,
            "room": ledger["room"],
            "head_sha256": ledger["head_sha256"],
            "event_count": len(ledger["events"]),
            "experiments": experiments,
            "runs": runs,
        }

    def snapshot(self, room: str) -> dict[str, Any]:
        with self._locked(room) as path:
            return self._snapshot(self._read(path, room))

    def compare(self, room: str, left_id: str, right_id: str) -> dict[str, Any]:
        snapshot = self.snapshot(room)
        left = snapshot["experiments"].get(_require_id(left_id, "left_id"))
        right = snapshot["experiments"].get(_require_id(right_id, "right_id"))
        if left is None or right is None:
            raise ValueError("both experiments must exist in this room")
        if left["comparison_contract_sha256"] != right["comparison_contract_sha256"]:
            raise ValueError("experiments do not share the same comparison contract")

        def keyed(experiment_id: str) -> dict[tuple[str, int], dict[str, Any]]:
            return {
                (run["case_id"], run["repetition"]): run
                for run in snapshot["runs"].values()
                if run["experiment_id"] == experiment_id
            }

        left_runs = keyed(left_id)
        right_runs = keyed(right_id)
        common = sorted(set(left_runs) & set(right_runs))
        pairs = []
        for key in common:
            left_run, right_run = left_runs[key], right_runs[key]
            metric_names = sorted(set(left_run["metrics"]) | set(right_run["metrics"]))
            deltas = {}
            for name in metric_names:
                left_value = left_run["metrics"].get(name)
                right_value = right_run["metrics"].get(name)
                deltas[name] = (
                    right_value - left_value
                    if isinstance(left_value, (int, float))
                    and not isinstance(left_value, bool)
                    and isinstance(right_value, (int, float))
                    and not isinstance(right_value, bool)
                    else None
                )
            pairs.append({
                "case_id": key[0],
                "repetition": key[1],
                "left_run_id": left_run["run_id"],
                "right_run_id": right_run["run_id"],
                "metric_deltas_right_minus_left": deltas,
            })
        return {
            "room": room,
            "left_experiment_id": left_id,
            "right_experiment_id": right_id,
            "comparison_contract_sha256": left["comparison_contract_sha256"],
            "paired_case_count": len(pairs),
            "left_only_count": len(set(left_runs) - set(right_runs)),
            "right_only_count": len(set(right_runs) - set(left_runs)),
            "pairs": pairs,
            "aggregation_policy": "paired_case_deltas_only_no_composite",
        }
