"""Human error-discovery state and privacy-safe observability helpers.

The human supplies trace-level judgments and free-text notes. Agent-generated
patterns and suggestions stay separate until a human accepts them.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from typing import Any


VALID_LABELS = frozenset({"pass", "fail", "defer"})
VALID_SUGGESTION_STATES = frozenset({"pending", "accepted", "dismissed"})
MAX_NOTE_LENGTH = 4_000
DEPTH_REVIEW_THRESHOLD = 5
SATURATION_REVIEW_THRESHOLD = 25


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def validate_annotations(
    value: Any,
    sample_ids: set[str],
    previous: dict[str, dict[str, Any]] | None = None,
) -> dict[str, dict[str, Any]]:
    """Validate a complete client annotation snapshot.

    Reviewer identity is a local claim, not authenticated identity. Timestamps
    are assigned by the server so the client cannot rewrite review chronology.
    """
    if not isinstance(value, dict):
        raise ValueError("annotations must be an object keyed by record id")
    previous = previous or {}
    now = _iso_now()
    output: dict[str, dict[str, Any]] = {}
    for record_id, annotation in value.items():
        if record_id not in sample_ids:
            raise ValueError(f"annotation refers to an unknown sample: {record_id}")
        if not isinstance(annotation, dict):
            raise ValueError(f"annotation for {record_id} must be an object")
        label = str(annotation.get("label") or "").strip().lower()
        if label not in VALID_LABELS:
            raise ValueError(f"annotation for {record_id} has an invalid label")
        note = str(annotation.get("note") or "").strip()
        if len(note) > MAX_NOTE_LENGTH:
            raise ValueError(f"annotation note for {record_id} exceeds {MAX_NOTE_LENGTH} characters")
        reviewer = str(annotation.get("reviewer") or "local reviewer").strip()[:120]
        prior = previous.get(record_id, {})
        modes = annotation.get("confirmed_modes", prior.get("confirmed_modes", []))
        if not isinstance(modes, list) or not all(isinstance(mode, str) for mode in modes):
            raise ValueError(f"confirmed modes for {record_id} must be a list of strings")
        output[record_id] = {
            "label": label,
            "note": note,
            "reviewer": reviewer or "local reviewer",
            "reviewer_identity_state": "self_asserted_local_not_authenticated",
            "confirmed_modes": sorted({mode.strip() for mode in modes if mode.strip()}),
            "created_at": prior.get("created_at") or now,
            "updated_at": now,
        }
    return output


def validate_suggestions(value: Any, known_record_ids: set[str]) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise ValueError("suggestions must be an array")
    output = []
    seen = set()
    for item in value:
        if not isinstance(item, dict):
            raise ValueError("each suggestion must be an object")
        identifier = str(item.get("id") or "").strip()
        record_id = str(item.get("record_id") or "").strip()
        mode = str(item.get("mode") or "uncategorized").strip()
        reason = str(item.get("reason") or "").strip()
        state = str(item.get("state") or "pending").strip().lower()
        if not identifier or identifier in seen:
            raise ValueError("suggestion ids must be non-empty and unique")
        if record_id not in known_record_ids:
            raise ValueError(f"suggestion refers to an unknown record: {record_id}")
        if state not in VALID_SUGGESTION_STATES:
            raise ValueError(f"suggestion {identifier} has an invalid state")
        if not reason:
            raise ValueError(f"suggestion {identifier} needs a reason")
        seen.add(identifier)
        output.append({
            "id": identifier,
            "record_id": record_id,
            "mode": mode or "uncategorized",
            "reason": reason[:2_000],
            "state": state,
            "source": "agent_suggestion_not_ground_truth",
        })
    return output


def validate_patterns(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise ValueError("patterns must be an array")
    output = []
    names = set()
    for item in value:
        if not isinstance(item, dict):
            raise ValueError("each pattern must be an object")
        name = str(item.get("name") or "").strip()
        description = str(item.get("description") or "").strip()
        if not name or name in names:
            raise ValueError("pattern names must be non-empty and unique")
        if not description:
            raise ValueError(f"pattern {name} needs a description")
        names.add(name)
        output.append({
            "name": name,
            "description": description[:2_000],
            "source": "agent_organized_from_human_notes",
            "updated_at": _iso_now(),
        })
    return output


def changed_records(
    before: dict[str, Any], after: dict[str, Any]
) -> list[dict[str, Any]]:
    changes = []
    for record_id in sorted(set(before) | set(after)):
        prior = before.get(record_id)
        current = after.get(record_id)
        if prior == current:
            continue
        changes.append({
            "record_id": record_id,
            "operation": "deleted" if current is None else "saved",
            "previous_sha256": _sha256(prior) if prior is not None else None,
            "current_sha256": _sha256(current) if current is not None else None,
            "current": current,
        })
    return changes


def session_summary(
    corpus: list[dict[str, Any]],
    samples: list[dict[str, Any]],
    annotations: dict[str, dict[str, Any]],
    suggestions: list[dict[str, Any]],
    patterns: list[dict[str, Any]],
) -> dict[str, Any]:
    sample_by_id = {sample["id"]: sample for sample in samples}
    labels = Counter(item.get("label") for item in annotations.values())
    reviewed_strata = Counter(
        sample_by_id[record_id].get("stratum", "other")
        for record_id in annotations if record_id in sample_by_id
    )
    sample_strata = Counter(sample.get("stratum", "other") for sample in samples)
    confirmed_modes = sorted({
        mode
        for annotation in annotations.values()
        for mode in annotation.get("confirmed_modes", [])
    })
    reviewed = len(annotations)
    phase = "depth" if reviewed >= DEPTH_REVIEW_THRESHOLD else "breadth"
    pending = sum(item.get("state") == "pending" for item in suggestions)
    accepted = sum(item.get("state") == "accepted" for item in suggestions)
    dismissed = sum(item.get("state") == "dismissed" for item in suggestions)
    return {
        "schema_version": 1,
        "measurement_state": "human_labels_separate_from_agent_suggestions",
        "phase": phase,
        "reviewed_count": reviewed,
        "sample_count": len(samples),
        "corpus_count": len(corpus),
        "remaining_count": max(0, len(samples) - reviewed),
        "labels": {label: labels.get(label, 0) for label in sorted(VALID_LABELS)},
        "coverage": [
            {
                "stratum": stratum,
                "reviewed": reviewed_strata.get(stratum, 0),
                "sampled": count,
            }
            for stratum, count in sorted(sample_strata.items())
        ],
        "suggestions": {
            "pending": pending,
            "accepted": accepted,
            "dismissed": dismissed,
            "ground_truth": False,
        },
        "taxonomy": {
            "agent_pattern_count": len(patterns),
            "human_confirmed_modes": confirmed_modes,
        },
        "depth_scan_ready": reviewed >= DEPTH_REVIEW_THRESHOLD,
        "rereview_recommended": reviewed >= DEPTH_REVIEW_THRESHOLD and bool(confirmed_modes),
        "saturation": {
            "claimed": False,
            "minimum_review_count": SATURATION_REVIEW_THRESHOLD,
            "reason": (
                "At least 25 reviews plus a stable discovery-rate window are required."
                if reviewed < SATURATION_REVIEW_THRESHOLD
                else "The discovery-rate window has not been independently validated."
            ),
        },
        "next_action": (
            "Review diverse traces until five distinct records have human judgments."
            if phase == "breadth"
            else "Scan the corpus for confirmed modes, then revisit earlier traces and add a breadth batch."
        ),
    }


def observability_snapshot(
    samples: list[dict[str, Any]],
    annotations: dict[str, dict[str, Any]],
    summary: dict[str, Any],
    *,
    include_content: bool = False,
) -> dict[str, Any]:
    """Return OpenInference-shaped evaluator records for an OTLP exporter.

    This is not an OTLP payload. The exporter creates real OpenTelemetry spans.
    Content is hash-only unless an operator explicitly requests inclusion.
    """
    sample_by_id = {sample["id"]: sample for sample in samples}
    records = []
    for record_id, annotation in sorted(annotations.items()):
        sample = sample_by_id.get(record_id, {})
        content = str(sample.get("content") or "")
        note = str(annotation.get("note") or "")
        attributes: dict[str, Any] = {
            "openinference.span.kind": "EVALUATOR",
            "session.id": "prism-milestone-8",
            "prism.eval.record.id": record_id,
            "prism.eval.label": annotation.get("label"),
            "prism.eval.feedback.source": "human",
            "prism.eval.reviewer.identity_state": annotation.get("reviewer_identity_state"),
            "prism.eval.sample.stratum": sample.get("stratum", "other"),
            "prism.eval.note.sha256": hashlib.sha256(note.encode()).hexdigest(),
            "prism.eval.content.sha256": hashlib.sha256(content.encode()).hexdigest(),
            "prism.eval.content.included": include_content,
            "prism.eval.human_confirmed_modes": annotation.get("confirmed_modes", []),
        }
        if include_content:
            attributes["input.value"] = content
            attributes["input.mime_type"] = "text/markdown"
            attributes["output.value"] = json.dumps({
                "label": annotation.get("label"),
                "note": note,
            })
            attributes["output.mime_type"] = "application/json"
        records.append({
            "name": "evaluate Prism workspace trace",
            "record_id": record_id,
            "started_at": annotation.get("created_at"),
            "ended_at": annotation.get("updated_at"),
            "attributes": attributes,
        })
    return {
        "schema_version": 1,
        "format": "openinference_evaluator_records_for_otlp",
        "project_name": "prism-error-discovery",
        "resource": {
            "service.name": "prism-eval-review",
            "service.version": "milestone-8-v1",
            "openinference.project.name": "prism-error-discovery",
        },
        "content_policy": "explicit_opt_in" if include_content else "hashes_only",
        "summary": summary,
        "records": records,
        "standards_boundary": {
            "transport": "OpenTelemetry OTLP via the optional exporter",
            "ai_semantics": "OpenInference EVALUATOR spans",
            "custom_attributes": "prism.eval.* attributes are local extensions",
            "unstable_conventions_not_claimed": ["gen_ai.eval.*", "gen_ai.task.feedback.*"],
        },
    }
