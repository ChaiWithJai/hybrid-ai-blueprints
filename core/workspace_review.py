"""Room scoped human error discovery for the Prism workspace."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.error_discovery import (
    changed_records,
    observability_snapshot,
    session_summary,
    validate_annotations,
    validate_suggestions,
)


ROOM_ID_PATTERN = re.compile(r"^[a-zA-Z0-9_-]{1,120}$")


def _read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def _atomic_write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(value, handle, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def _classify_role(message: dict[str, Any], agent_key: str, operator_key: str) -> str:
    content = str(message.get("display_content") or message.get("content") or "")
    if message.get("pubkey") == agent_key or message.get("prism_acceptance_state"):
        return "assistant"
    if message.get("pubkey") == operator_key:
        return "user"
    if content.startswith("<!-- prism:") or content.startswith("## First pass requested"):
        return "system"
    return "other"


def _infer_stratum(message: dict[str, Any], content: str) -> str:
    state = message.get("prism_acceptance_state")
    if state == "quarantined_uncommitted":
        return "rejection"
    if state == "accepted":
        return "accepted_answer"
    if state == "evidence_safe_fallback":
        return "fallback"
    folded = content.casefold()
    if "review" in folded and "decision" in folded:
        return "operator_review"
    if content.startswith("## First pass requested"):
        return "first_pass_request"
    if content.rstrip().endswith("?"):
        return "question"
    return "conversation"


def build_review_corpus(
    messages: list[dict[str, Any]],
    *,
    agent_key: str = "",
    operator_key: str = "",
) -> list[dict[str, Any]]:
    records = []
    for message in messages:
        if not isinstance(message, dict) or not message.get("id"):
            continue
        content = str(message.get("display_content") or message.get("content") or "")
        records.append({
            "id": str(message["id"]),
            "stratum": _infer_stratum(message, content),
            "created_at": message.get("created_at") or 0,
            "acceptance_state": message.get("prism_acceptance_state"),
            "content": content,
            "role": _classify_role(message, agent_key, operator_key),
            "metadata": {
                "signature_verified": message.get("signature_verified"),
                "guard_version": message.get("prism_guard_version"),
                "trace_id": message.get("prism_trace_id"),
            },
        })
    return sorted(records, key=lambda item: (item.get("created_at", 0), item["id"]))


def _built_in_suggestions(record: dict[str, Any]) -> list[dict[str, str]]:
    content = str(record.get("content") or "")
    suggestions = []
    if record.get("acceptance_state") == "quarantined_uncommitted":
        suggestions.append({
            "mode": "publication_rejection",
            "reason": "The candidate failed a source or publication guard.",
        })
    if content.startswith("<!-- prism:"):
        suggestions.append({
            "mode": "machine_markup_in_raw_trace",
            "reason": "The stored trace starts with internal machine markup.",
        })
    if "[SOURCE [" in content:
        suggestions.append({
            "mode": "raw_citation_wrapper",
            "reason": "The stored answer contains a machine citation wrapper.",
        })
    if "/Users/" in content or ":\\" in content:
        suggestions.append({
            "mode": "local_path_exposure",
            "reason": "The trace contains a local filesystem path.",
        })
    if content.startswith("## First pass requested"):
        suggestions.append({
            "mode": "workflow_event_noise",
            "reason": "A workflow request may dominate the human conversation.",
        })
    return suggestions


class WorkspaceReviewStore:
    """Persist review state under one canonical Prism room."""

    def __init__(self, base: Path, room_id: str, corpus: list[dict[str, Any]]):
        if not ROOM_ID_PATTERN.fullmatch(room_id):
            raise ValueError("invalid room id for review state")
        self.room_id = room_id
        self.corpus = corpus
        self.data = base.resolve() / room_id
        self.lock_path = self.data / ".review.lock"

    def _with_lock(self):
        self.data.mkdir(parents=True, exist_ok=True)
        handle = self.lock_path.open("a+", encoding="utf-8")
        os.chmod(self.lock_path, 0o600)
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        return handle

    def _append_event(self, event: dict[str, Any]) -> dict[str, Any]:
        path = self.data / "review-events.jsonl"
        lines = []
        try:
            lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line]
        except OSError:
            pass
        previous = json.loads(lines[-1]) if lines else None
        record = {
            "sequence": len(lines) + 1,
            "previous_event_sha256": previous.get("event_sha256") if previous else None,
            "recorded_at": datetime.now(timezone.utc).isoformat(),
            "room": self.room_id,
            **event,
        }
        payload = json.dumps(record, sort_keys=True, separators=(",", ":"))
        record["event_sha256"] = hashlib.sha256(payload.encode()).hexdigest()
        with path.open("a", encoding="utf-8") as handle:
            os.chmod(path, 0o600)
            handle.write(json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        return record

    def _initial_ids(self, limit: int = 10) -> list[str]:
        by_stratum: dict[str, list[dict[str, Any]]] = {}
        for record in self.corpus:
            by_stratum.setdefault(record.get("stratum", "other"), []).append(record)
        selected = []
        for stratum in sorted(by_stratum):
            if len(selected) >= limit:
                break
            selected.append(by_stratum[stratum][0]["id"])
        remaining = [
            record for record in self.corpus if record["id"] not in set(selected)
        ]
        remaining.sort(key=lambda item: hashlib.sha256(item["id"].encode()).hexdigest())
        selected.extend(record["id"] for record in remaining[: max(0, limit - len(selected))])
        return selected

    def selected_ids(self) -> list[str]:
        stored = _read_json(self.data / "samples.json", [])
        stored = stored if isinstance(stored, list) else []
        known = {record["id"] for record in self.corpus}
        return [
            record_id for record_id in dict.fromkeys(self._initial_ids() + [str(item) for item in stored])
            if record_id in known
        ]

    def samples(self) -> list[dict[str, Any]]:
        by_id = {record["id"]: record for record in self.corpus}
        positions = {record["id"]: index for index, record in enumerate(self.corpus)}
        samples = []
        for record_id in self.selected_ids():
            record = dict(by_id[record_id])
            index = positions[record_id]
            record["turns"] = [
                {key: turn.get(key) for key in (
                    "id", "role", "content", "created_at", "acceptance_state",
                )}
                for turn in self.corpus[max(0, index - 2): min(len(self.corpus), index + 3)]
            ]
            record["focus_turn_id"] = record_id
            samples.append(record)
        return samples

    def annotations(self) -> dict[str, dict[str, Any]]:
        value = _read_json(self.data / "annotations.json", {})
        return value if isinstance(value, dict) else {}

    def suggestions(self) -> list[dict[str, Any]]:
        selected = set(self.selected_ids())
        generated = []
        for record in self.corpus:
            if record["id"] not in selected:
                continue
            for index, suggestion in enumerate(_built_in_suggestions(record)):
                generated.append({
                    "id": f"{record['id']}:{suggestion['mode']}:{index}",
                    "record_id": record["id"],
                    **suggestion,
                    "state": "pending",
                    "source": "agent_suggestion_not_ground_truth",
                })
        saved = _read_json(self.data / "suggestions.json", [])
        by_id = {item["id"]: item for item in generated}
        if isinstance(saved, list):
            for item in saved:
                if isinstance(item, dict) and item.get("id"):
                    by_id[item["id"]] = item
        return list(by_id.values())

    def patterns(self) -> list[dict[str, Any]]:
        annotations = self.annotations()
        taxonomy: dict[str, dict[str, Any]] = {}
        for suggestion in self.suggestions():
            mode = suggestion.get("mode") or "uncategorized"
            item = taxonomy.setdefault(mode, {
                "name": mode,
                "description": suggestion.get("reason") or "Agent proposal awaiting review.",
                "source": "agent_suggestion_not_ground_truth",
                "suggested": 0,
                "confirmed": 0,
            })
            item["suggested"] += 1
            if suggestion.get("state") == "accepted":
                item["confirmed"] += 1
        for item in taxonomy.values():
            item["notes"] = [
                {"record_id": record_id, "text": annotation.get("note", "")}
                for record_id, annotation in annotations.items()
                if item["name"] in annotation.get("confirmed_modes", []) and annotation.get("note")
            ]
        return sorted(taxonomy.values(), key=lambda item: item["name"])

    def graph(self) -> list[dict[str, Any]]:
        selected = set(self.selected_ids())
        annotations = self.annotations()
        strata = sorted({record.get("stratum", "other") for record in self.corpus})
        x_positions = {name: index for index, name in enumerate(strata)}
        return [{
            "id": record["id"],
            "cluster": record.get("stratum", "other"),
            "x": 45 + x_positions[record.get("stratum", "other")] * (710 / max(1, len(strata) - 1)),
            "y": 45 + (index % 5) * 68,
            "sampled": record["id"] in selected,
            "annotated": record["id"] in annotations,
            "role": record.get("role", "other"),
        } for index, record in enumerate(self.corpus)]

    def summary(self) -> dict[str, Any]:
        return session_summary(
            self.corpus,
            self.samples(),
            self.annotations(),
            self.suggestions(),
            self.patterns(),
        )

    def snapshot(self, *, phoenix: dict[str, Any]) -> dict[str, Any]:
        samples = self.samples()
        annotations = self.annotations()
        summary = self.summary()
        return {
            "schema_version": 1,
            "room": self.room_id,
            "canonical_path": f"/rooms/{self.room_id}/evaluation",
            "samples": samples,
            "annotations": annotations,
            "suggestions": self.suggestions(),
            "patterns": self.patterns(),
            "graph": self.graph(),
            "session": summary,
            "observability": observability_snapshot(samples, annotations, summary),
            "phoenix": phoenix,
        }

    def observability(self, *, include_content: bool = False) -> dict[str, Any]:
        snapshot = observability_snapshot(
            self.samples(), self.annotations(), self.summary(), include_content=include_content,
        )
        return {"room": self.room_id, **snapshot}

    def upsert_annotation(self, payload: dict[str, Any]) -> dict[str, Any]:
        record_id = str(payload.get("record_id") or "")
        sample_ids = {sample["id"] for sample in self.samples()}
        if record_id not in sample_ids:
            raise ValueError("annotation refers to an unknown room sample")
        handle = self._with_lock()
        try:
            before = self.annotations()
            after = dict(before)
            if payload.get("delete") is True:
                after.pop(record_id, None)
            else:
                value = {key: payload.get(key) for key in (
                    "label", "note", "reviewer", "confirmed_modes",
                )}
                validated = validate_annotations(
                    {record_id: value}, sample_ids, {record_id: before.get(record_id, {})},
                )
                after[record_id] = validated[record_id]
            for change in changed_records(before, after):
                self._append_event({"kind": "human_annotation_revision", **change})
            _atomic_write(self.data / "annotations.json", after)
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            handle.close()
        return {"saved": True, "annotation": after.get(record_id), "session": self.summary()}

    def set_suggestion_state(self, payload: dict[str, Any]) -> dict[str, Any]:
        suggestion_id = str(payload.get("suggestion_id") or "")
        state = str(payload.get("state") or "")
        current = self.suggestions()
        if suggestion_id not in {item["id"] for item in current}:
            raise ValueError("unknown suggestion")
        updated = [
            {**item, "state": state} if item["id"] == suggestion_id else item
            for item in current
        ]
        validated = validate_suggestions(updated, {record["id"] for record in self.corpus})
        handle = self._with_lock()
        try:
            _atomic_write(self.data / "suggestions.json", validated)
            self._append_event({
                "kind": "agent_suggestion_decision",
                "suggestion_id": suggestion_id,
                "state": state,
                "ground_truth": False,
            })
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            handle.close()
        return {"saved": True, "session": self.summary()}

    def add_breadth(self, limit: int = 3) -> dict[str, Any]:
        selected = self.selected_ids()
        selected_set = set(selected)
        sample_counts: dict[str, int] = {}
        by_id = {record["id"]: record for record in self.corpus}
        for record_id in selected:
            stratum = by_id[record_id].get("stratum", "other")
            sample_counts[stratum] = sample_counts.get(stratum, 0) + 1
        candidates = [record for record in self.corpus if record["id"] not in selected_set]
        candidates.sort(key=lambda item: (
            sample_counts.get(item.get("stratum", "other"), 0),
            item.get("created_at", 0),
            item["id"],
        ))
        added = [record["id"] for record in candidates[:limit]]
        handle = self._with_lock()
        try:
            _atomic_write(self.data / "samples.json", selected + added)
            self._append_event({"kind": "breadth_sample_added", "record_ids": added})
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            handle.close()
        return {"added": added, "session": self.summary()}

    def scan(self) -> dict[str, Any]:
        if len(self.annotations()) < 5:
            raise ValueError("five human judgments are required before a depth scan")
        existing = {item["id"]: item for item in self.suggestions()}
        before = len(existing)
        for record in self.corpus:
            for index, suggestion in enumerate(_built_in_suggestions(record)):
                identifier = f"{record['id']}:{suggestion['mode']}:{index}"
                existing.setdefault(identifier, {
                    "id": identifier,
                    "record_id": record["id"],
                    **suggestion,
                    "state": "pending",
                    "source": "agent_suggestion_not_ground_truth",
                })
        validated = validate_suggestions(
            list(existing.values()), {record["id"] for record in self.corpus},
        )
        handle = self._with_lock()
        try:
            _atomic_write(self.data / "suggestions.json", validated)
            self._append_event({
                "kind": "agent_depth_scan",
                "added": len(existing) - before,
                "ground_truth": False,
            })
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            handle.close()
        return {"added": len(existing) - before, "session": self.summary()}
