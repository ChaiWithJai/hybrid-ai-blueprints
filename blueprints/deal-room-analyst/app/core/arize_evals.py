"""
Arize Phoenix-inspired local evaluation and trace schema.
Records execution spans and optional token/hardware metrics. Included evaluators
are lightweight prototype checks and must not be presented as Arize services or
as general hallucination detection.
"""

import time
import uuid
import json
import re
import os
import threading
import fcntl
import hashlib
from contextlib import contextmanager
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import List, Dict, Any, Optional


PENDING_REVIEW_STATES = frozenset({
    "awaiting_human_review",
    "awaiting_domain_review",
})
UNVERIFIED_EVALUATION_STATES = frozenset({
    "unverified",
    "not_applicable",
})

TRACE_LEDGER_VERSION = 1
TRACE_LEDGER_GENESIS = "0" * 64
_TRACE_STORE_THREAD_LOCK = threading.RLock()


@dataclass
class EvalMetric:
    name: str
    score: float  # 0.0 to 1.0 or specific scale
    threshold: float
    passed: bool
    explanation: str
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class TraceSpan:
    span_id: str
    parent_span_id: Optional[str]
    name: str
    span_kind: str  # 'CHAIN', 'AGENT', 'TOOL', 'LLM', 'PARSER', 'SANDBOX', 'EVAL'
    start_time_ms: float
    end_time_ms: float
    duration_ms: float
    status: str  # 'OK', 'ERROR', 'WARNING'
    attributes: Dict[str, Any] = field(default_factory=dict)
    events: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class ArizeTraceRecord:
    trace_id: str
    session_id: str
    timestamp: float
    query: str
    response: str
    model_name: str
    routed_tier: str  # 'LOCAL_BONSAI_27B', 'LOCAL_BONSAI_8B', 'CLOUD_FRONTIER'
    total_tokens: Optional[int]
    prompt_tokens: Optional[int]
    completion_tokens: Optional[int]
    total_latency_ms: float
    energy_per_token_mwh: Optional[float]
    total_energy_mwh: Optional[float]
    vram_peak_gb: Optional[float]
    spans: List[TraceSpan] = field(default_factory=list)
    evaluations: List[EvalMetric] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


def evaluation_release_state(evaluations: List[EvalMetric]) -> Dict[str, str]:
    """Separate failed checks, missing evidence, and pending review."""
    if not evaluations:
        return {
            "state": "unverified",
            "label": "No evaluations",
            "explanation": "No evaluations were recorded for this trace.",
        }
    failed = [evaluation for evaluation in evaluations if evaluation.passed is False]
    hard_failures = [
        evaluation for evaluation in failed
        if evaluation.metadata.get("measurement_state")
        not in PENDING_REVIEW_STATES | UNVERIFIED_EVALUATION_STATES
    ]
    if hard_failures:
        return {
            "state": "rejected",
            "label": "Guard rejected",
            "explanation": hard_failures[0].explanation,
        }
    unverified = [
        evaluation for evaluation in failed
        if evaluation.metadata.get("measurement_state") in UNVERIFIED_EVALUATION_STATES
    ]
    if unverified:
        return {
            "state": "unverified",
            "label": "Evidence incomplete",
            "explanation": unverified[0].explanation,
        }
    pending = [
        evaluation for evaluation in failed
        if evaluation.metadata.get("measurement_state") in PENDING_REVIEW_STATES
    ]
    if pending:
        return {
            "state": "awaiting_review",
            "label": "Review pending",
            "explanation": pending[0].explanation,
        }
    return {
        "state": "checks_passed",
        "label": "Checks passed",
        "explanation": "All recorded evaluations passed.",
    }


class ArizeEvaluationEngine:
    """Small local evaluators whose evidence boundaries are caller supplied."""

    _SOURCE_TEXT_FIELDS = frozenset({
        "content", "text", "title", "raw_csv", "display_value",
    })

    @staticmethod
    def _source_text_values(value: Any, field_name: str | None = None) -> List[str]:
        """Collect only declared source text fields, never mapping keys or arbitrary metadata."""
        if isinstance(value, str):
            return [value] if field_name in ArizeEvaluationEngine._SOURCE_TEXT_FIELDS else []
        if isinstance(value, list):
            values: List[str] = []
            for item in value:
                values.extend(ArizeEvaluationEngine._source_text_values(item, field_name))
            return values
        if isinstance(value, dict):
            values = []
            for key, item in value.items():
                values.extend(ArizeEvaluationEngine._source_text_values(item, str(key)))
            return values
        return []

    @staticmethod
    def _normalize_lexical_text(value: str) -> str:
        return re.sub(r"\s+", " ", value).strip().casefold()

    @staticmethod
    def evaluate_faithfulness(
        response_text: str,
        source_context_nodes: List[Dict[str, Any]],
        ground_truth_claims: List[str]
    ) -> EvalMetric:
        """Check exact claim reproduction without claiming semantic faithfulness.

        The method name remains for compatibility. It requires every supplied
        claim to appear in both a declared source text field and the response.
        Exact lexical overlap cannot establish meaning, entailment, or accuracy.
        """
        total_claims = len(ground_truth_claims)
        if total_claims == 0:
            return EvalMetric(
                name="lexical_claim_reproduction",
                score=0.0,
                threshold=1.0,
                passed=False,
                explanation="No claims were supplied, so exact lexical reproduction is unverified.",
                metadata={
                    "measurement_state": "unverified",
                    "reason": "no_claims",
                    "semantic_faithfulness_measured": False,
                },
            )
        source_values = ArizeEvaluationEngine._source_text_values(source_context_nodes)
        if not source_values:
            return EvalMetric(
                name="lexical_claim_reproduction",
                score=0.0,
                threshold=1.0,
                passed=False,
                explanation=(
                    "No declared source text fields were supplied, so exact lexical reproduction "
                    "is unverified."
                ),
                metadata={
                    "measurement_state": "unverified",
                    "reason": "no_declared_source_text",
                    "semantic_faithfulness_measured": False,
                },
            )
        response = ArizeEvaluationEngine._normalize_lexical_text(response_text)
        sources = [
            ArizeEvaluationEngine._normalize_lexical_text(value)
            for value in source_values if value.strip()
        ]
        reproduced_claims = []
        missing_from_response = []
        missing_from_source = []
        for claim in ground_truth_claims:
            normalized = ArizeEvaluationEngine._normalize_lexical_text(str(claim))
            in_response = bool(normalized) and normalized in response
            in_source = bool(normalized) and any(normalized in source for source in sources)
            if in_response and in_source:
                reproduced_claims.append(claim)
            else:
                if not in_response:
                    missing_from_response.append(claim)
                if not in_source:
                    missing_from_source.append(claim)

        score = len(reproduced_claims) / total_claims
        passed = score == 1.0

        return EvalMetric(
            name="lexical_claim_reproduction",
            score=round(score, 4),
            threshold=1.0,
            passed=passed,
            explanation=(
                f"Exactly reproduced {len(reproduced_claims)} of {total_claims} supplied claims "
                "in both declared source text and the response. This does not measure semantic "
                "faithfulness or accuracy."
            ),
            metadata={
                "measurement_state": "exact_lexical_check_not_semantic_faithfulness",
                "semantic_faithfulness_measured": False,
                "reproduced_claims": reproduced_claims,
                "missing_from_response": missing_from_response,
                "missing_from_source": missing_from_source,
                "declared_source_text_value_count": len(sources),
            },
        )

    @staticmethod
    def evaluate_forbidden_strings(
        response_text: str,
        known_forbidden_entities: List[str] = None
    ) -> EvalMetric:
        """Check a small explicit denylist; this is not hallucination detection."""
        if known_forbidden_entities is None:
            # Prototype phrases that must not appear in the reviewed workflows.
            known_forbidden_entities = [
                "Section 18.04", "Lehman Brothers", "interest coverage 6.50",
                "purchase price 250M", "100% cloud telemetry enabled", "unrestricted internet access"
            ]

        matched_forbidden_strings = []
        for ent in known_forbidden_entities:
            if ent.lower() in response_text.lower():
                matched_forbidden_strings.append(ent)

        score = 1.0 if not matched_forbidden_strings else 0.0
        passed = not matched_forbidden_strings

        return EvalMetric(
            name="forbidden_string_check",
            score=round(score, 4),
            threshold=1.0,
            passed=passed,
            explanation="No configured forbidden strings were found." if passed
            else f"Forbidden-string match: {len(matched_forbidden_strings)} matches ({', '.join(matched_forbidden_strings)})",
            metadata={
                "measurement_state": "exact_configured_denylist_check_not_hallucination_detection",
                "hallucination_detection_measured": False,
                "matched_forbidden_strings": matched_forbidden_strings,
                "configured_forbidden_string_count": len(known_forbidden_entities),
            },
        )

    @staticmethod
    def evaluate_tabular_cell_fidelity(
        extracted_tables: List[Dict[str, Any]],
        verified_cell_count: Optional[int] = None,
        total_cells_checked: Optional[int] = None,
        *,
        expected_cells: Optional[List[Dict[str, Any]]] = None,
    ) -> EvalMetric:
        """Compare extracted cells with an explicit coordinate-and-text fixture.

        The legacy count arguments are retained for call compatibility but can
        never produce a pass. A passing result requires this method to inspect
        each expected coordinate and exact value in ``extracted_tables``.
        This is a fixture match, not general extraction accuracy.
        """
        if not expected_cells:
            return EvalMetric(
                name="tabular_fixture_cell_match",
                score=0.0,
                threshold=1.0,
                passed=False,
                explanation=(
                    "No coordinate-and-text fixture was supplied. Caller-provided pass counts "
                    "are not accepted as evidence."
                ),
                metadata={
                    "measurement_state": "unverified",
                    "reason": "no_expected_cell_fixture",
                    "legacy_verified_cell_count_ignored": verified_cell_count,
                    "legacy_total_cells_checked_ignored": total_cells_checked,
                    "general_extraction_accuracy_measured": False,
                },
            )

        actual_cells: Dict[tuple[int, int, int], List[str]] = {}
        for table_index, table in enumerate(extracted_tables):
            cells = table.get("cells", []) if isinstance(table, dict) else getattr(table, "cells", [])
            for cell in cells:
                if isinstance(cell, dict):
                    row, col, text = cell.get("row"), cell.get("col"), cell.get("text")
                else:
                    row = getattr(cell, "row", None)
                    col = getattr(cell, "col", None)
                    text = getattr(cell, "text", None)
                if isinstance(row, int) and isinstance(col, int) and text is not None:
                    actual_cells.setdefault((table_index, row, col), []).append(str(text))

        matched_cells = []
        mismatches = []
        for index, expected in enumerate(expected_cells):
            if not isinstance(expected, dict):
                mismatches.append({"fixture_index": index, "reason": "fixture_entry_not_an_object"})
                continue
            table_index = expected.get("table_index")
            row = expected.get("row")
            col = expected.get("col")
            expected_text = expected.get("expected_text")
            if not (
                isinstance(table_index, int) and table_index >= 0
                and isinstance(row, int) and row >= 0
                and isinstance(col, int) and col >= 0
                and isinstance(expected_text, str)
            ):
                mismatches.append({"fixture_index": index, "reason": "invalid_fixture_entry"})
                continue
            coordinate = (table_index, row, col)
            observed = actual_cells.get(coordinate, [])
            if observed == [expected_text]:
                matched_cells.append({
                    "table_index": table_index, "row": row, "col": col,
                    "expected_text": expected_text,
                })
            else:
                mismatches.append({
                    "fixture_index": index,
                    "table_index": table_index,
                    "row": row,
                    "col": col,
                    "expected_text": expected_text,
                    "observed_texts": observed,
                    "reason": "missing_ambiguous_or_different_cell",
                })

        score = len(matched_cells) / len(expected_cells)
        passed = not mismatches and len(matched_cells) == len(expected_cells)

        return EvalMetric(
            name="tabular_fixture_cell_match",
            score=round(score, 4),
            threshold=1.0,
            passed=passed,
            explanation=(
                f"Exactly matched {len(matched_cells)} of {len(expected_cells)} fixture cells by "
                "table index, row, column, and text. This does not measure general extraction accuracy."
            ),
            metadata={
                "measurement_state": "exact_preregistered_fixture_match_not_general_extraction_accuracy",
                "general_extraction_accuracy_measured": False,
                "matched_cells": matched_cells,
                "mismatches": mismatches,
                "expected_cell_count": len(expected_cells),
                "observed_coordinate_count": len(actual_cells),
                "legacy_verified_cell_count_ignored": verified_cell_count,
                "legacy_total_cells_checked_ignored": total_cells_checked,
            },
        )

    @staticmethod
    def evaluate_schema_compliance(
        tool_call_json: Optional[Dict[str, Any]],
        required_schema_fields: Any,
    ) -> EvalMetric:
        """Check field presence or bounded top level JSON types.

        A list of field names checks presence only. A mapping of field names to
        JSON type names checks presence and exact top level types. This helper
        does not implement full JSON Schema validation.
        """
        if tool_call_json is None:
            return EvalMetric(
                name="required_field_presence",
                score=0.0,
                threshold=1.0,
                passed=False,
                explanation="No structured output was supplied, so the field check is not applicable.",
                metadata={
                    "measurement_state": "not_applicable",
                    "reason": "no_structured_output",
                    "full_json_schema_validated": False,
                },
            )
        if not isinstance(tool_call_json, dict):
            return EvalMetric(
                name="required_field_presence",
                score=0.0,
                threshold=1.0,
                passed=False,
                explanation="The supplied structured output is not an object.",
                metadata={
                    "measurement_state": "invalid_input",
                    "reason": "structured_output_not_an_object",
                    "full_json_schema_validated": False,
                },
            )

        if isinstance(required_schema_fields, list):
            if not required_schema_fields or not all(
                isinstance(field, str) and field for field in required_schema_fields
            ):
                return EvalMetric(
                    name="required_field_presence",
                    score=0.0,
                    threshold=1.0,
                    passed=False,
                    explanation="No valid required field list was supplied.",
                    metadata={
                        "measurement_state": "unverified",
                        "reason": "empty_or_invalid_required_field_list",
                        "types_validated": False,
                        "full_json_schema_validated": False,
                    },
                )
            missing_fields = [field for field in required_schema_fields if field not in tool_call_json]
            score = (len(required_schema_fields) - len(missing_fields)) / len(required_schema_fields)
            passed = not missing_fields
            return EvalMetric(
                name="required_field_presence",
                score=round(score, 4),
                threshold=1.0,
                passed=passed,
                explanation=(
                    "All caller-required fields are present. Field types and full JSON Schema "
                    "compliance were not checked."
                    if passed else f"Required fields are missing: {missing_fields}"
                ),
                metadata={
                    "measurement_state": "required_field_presence_not_schema_or_type_validation",
                    "missing_fields": missing_fields,
                    "types_validated": False,
                    "full_json_schema_validated": False,
                },
            )

        if not isinstance(required_schema_fields, dict) or not required_schema_fields:
            return EvalMetric(
                name="typed_field_schema_check",
                score=0.0,
                threshold=1.0,
                passed=False,
                explanation="No valid typed field schema was supplied.",
                metadata={
                    "measurement_state": "unverified",
                    "reason": "empty_or_invalid_typed_field_schema",
                    "full_json_schema_validated": False,
                },
            )

        type_checks = {
            "string": lambda value: isinstance(value, str),
            "integer": lambda value: isinstance(value, int) and not isinstance(value, bool),
            "number": lambda value: isinstance(value, (int, float)) and not isinstance(value, bool),
            "boolean": lambda value: isinstance(value, bool),
            "object": lambda value: isinstance(value, dict),
            "array": lambda value: isinstance(value, list),
            "null": lambda value: value is None,
        }
        missing_fields = []
        type_mismatches = []
        unsupported_types = []
        matched_fields = []
        for field, expected_type in required_schema_fields.items():
            if (
                not isinstance(field, str) or not field
                or not isinstance(expected_type, str) or expected_type not in type_checks
            ):
                unsupported_types.append({
                    "field": str(field), "expected_type": str(expected_type),
                })
                continue
            if field not in tool_call_json:
                missing_fields.append(field)
                continue
            value = tool_call_json[field]
            if type_checks[expected_type](value):
                matched_fields.append(field)
            else:
                type_mismatches.append({
                    "field": field,
                    "expected_type": expected_type,
                    "observed_type": type(value).__name__,
                })

        total_fields = len(required_schema_fields)
        score = len(matched_fields) / total_fields
        passed = not missing_fields and not type_mismatches and not unsupported_types
        return EvalMetric(
            name="typed_field_schema_check",
            score=round(score, 4),
            threshold=1.0,
            passed=passed,
            explanation=(
                f"Matched {len(matched_fields)} of {total_fields} required top level JSON field "
                "types. Nested constraints and full JSON Schema compliance were not checked."
            ),
            metadata={
                "measurement_state": "bounded_top_level_json_type_check_not_full_json_schema",
                "missing_fields": missing_fields,
                "type_mismatches": type_mismatches,
                "unsupported_types": unsupported_types,
                "matched_fields": matched_fields,
                "full_json_schema_validated": False,
            },
        )


class ArizeObservabilityTracer:
    """
    Collects traces, spans, optional telemetry, and evaluation records.
    """

    def __init__(self, storage_path: Optional[str] = None):
        self._lock = threading.RLock()
        self.traces: List[ArizeTraceRecord] = []
        self.loaded_trace_ids: set[str] = set()
        self.recorded_trace_ids_in_process: set[str] = set()
        self._baseline_record_hashes: Dict[str, str] = {}
        self._ledger_head_sha256 = TRACE_LEDGER_GENESIS
        self._ledger_entry_count = 0
        self._storage_identity: Optional[tuple[int, int, int, int, int]] = None
        self.storage_path = Path(storage_path).resolve() if storage_path else None
        if self.storage_path is not None:
            self.storage_path.parent.mkdir(parents=True, exist_ok=True)
            if self.storage_path.exists():
                with self._storage_transaction():
                    records, head, entry_count, legacy = self._read_storage_unlocked()
                    if legacy:
                        self._rewrite_as_ledger_unlocked(records)
                        records, head, entry_count, legacy = self._read_storage_unlocked()
                    self._install_storage_state(records, head, entry_count)

    @staticmethod
    def _from_dict(payload: Dict[str, Any]) -> ArizeTraceRecord:
        data = dict(payload)
        data["spans"] = [TraceSpan(**span) for span in data.get("spans", [])]
        data["evaluations"] = [EvalMetric(**evaluation) for evaluation in data.get("evaluations", [])]
        return ArizeTraceRecord(**data)

    @staticmethod
    def _canonical_json(payload: Dict[str, Any]) -> str:
        return json.dumps(
            payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        )

    @classmethod
    def _record_hash(cls, record: ArizeTraceRecord) -> str:
        return hashlib.sha256(
            cls._canonical_json(asdict(record)).encode("utf-8")
        ).hexdigest()

    @classmethod
    def _ledger_entry(
        cls,
        record: ArizeTraceRecord,
        *,
        sequence: int,
        previous_entry_sha256: str,
        operation: str,
    ) -> Dict[str, Any]:
        unsigned = {
            "ledger_version": TRACE_LEDGER_VERSION,
            "sequence": sequence,
            "operation": operation,
            "previous_entry_sha256": previous_entry_sha256,
            "record": asdict(record),
        }
        return {
            **unsigned,
            "entry_sha256": hashlib.sha256(
                cls._canonical_json(unsigned).encode("utf-8")
            ).hexdigest(),
        }

    @contextmanager
    def _storage_transaction(self):
        if self.storage_path is None:
            yield
            return
        lock_path = self.storage_path.with_name(f".{self.storage_path.name}.lock")
        with _TRACE_STORE_THREAD_LOCK:
            descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
            try:
                os.fchmod(descriptor, 0o600)
                fcntl.flock(descriptor, fcntl.LOCK_EX)
                yield
            finally:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
                os.close(descriptor)

    def _read_storage_unlocked(
        self,
    ) -> tuple[List[ArizeTraceRecord], str, int, bool]:
        if self.storage_path is None or not self.storage_path.exists():
            return [], TRACE_LEDGER_GENESIS, 0, False
        parsed_lines: List[tuple[int, Dict[str, Any]]] = []
        with self.storage_path.open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                try:
                    payload = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ValueError(
                        f"Invalid trace ledger JSON at {self.storage_path}:{line_number}: {exc}"
                    ) from exc
                if not isinstance(payload, dict):
                    raise ValueError(
                        f"Invalid trace ledger entry at {self.storage_path}:{line_number}: "
                        "expected an object"
                    )
                parsed_lines.append((line_number, payload))
        if not parsed_lines:
            return [], TRACE_LEDGER_GENESIS, 0, False

        ledger_flags = ["ledger_version" in payload for _, payload in parsed_lines]
        if any(ledger_flags) and not all(ledger_flags):
            raise ValueError(f"Mixed legacy and chained trace records in {self.storage_path}")
        if not any(ledger_flags):
            records: List[ArizeTraceRecord] = []
            seen = set()
            for line_number, payload in parsed_lines:
                try:
                    record = self._from_dict(payload)
                except (TypeError, ValueError) as exc:
                    raise ValueError(
                        f"Invalid trace record at {self.storage_path}:{line_number}: {exc}"
                    ) from exc
                if record.trace_id in seen:
                    raise ValueError(
                        f"Duplicate trace_id {record.trace_id!r} in {self.storage_path}"
                    )
                seen.add(record.trace_id)
                records.append(record)
            return records, TRACE_LEDGER_GENESIS, 0, True

        ordered_ids: List[str] = []
        records_by_id: Dict[str, ArizeTraceRecord] = {}
        previous = TRACE_LEDGER_GENESIS
        for expected_sequence, (line_number, entry) in enumerate(parsed_lines, start=1):
            unsigned = {key: value for key, value in entry.items() if key != "entry_sha256"}
            expected_hash = hashlib.sha256(
                self._canonical_json(unsigned).encode("utf-8")
            ).hexdigest()
            if entry.get("ledger_version") != TRACE_LEDGER_VERSION:
                raise ValueError(
                    f"Unsupported trace ledger version at {self.storage_path}:{line_number}"
                )
            if entry.get("sequence") != expected_sequence:
                raise ValueError(
                    f"Trace ledger sequence mismatch at {self.storage_path}:{line_number}"
                )
            if entry.get("previous_entry_sha256") != previous:
                raise ValueError(
                    f"Trace ledger chain mismatch at {self.storage_path}:{line_number}"
                )
            if entry.get("entry_sha256") != expected_hash:
                raise ValueError(
                    f"Trace ledger hash mismatch at {self.storage_path}:{line_number}"
                )
            if entry.get("operation") not in {
                "legacy_import", "record_created", "record_updated",
            }:
                raise ValueError(
                    f"Unsupported trace ledger operation at {self.storage_path}:{line_number}"
                )
            try:
                record = self._from_dict(entry.get("record"))
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    f"Invalid trace record at {self.storage_path}:{line_number}: {exc}"
                ) from exc
            if entry["operation"] in {"legacy_import", "record_created"}:
                if record.trace_id in records_by_id:
                    raise ValueError(
                        f"Duplicate trace creation for {record.trace_id!r} in {self.storage_path}"
                    )
                ordered_ids.append(record.trace_id)
            elif record.trace_id not in records_by_id:
                raise ValueError(
                    f"Trace update precedes creation for {record.trace_id!r} in {self.storage_path}"
                )
            records_by_id[record.trace_id] = record
            previous = expected_hash
        return (
            [records_by_id[trace_id] for trace_id in ordered_ids],
            previous,
            len(parsed_lines),
            False,
        )

    def _install_storage_state(
        self,
        records: List[ArizeTraceRecord],
        head: str,
        entry_count: int,
    ) -> None:
        self.traces = records
        self.loaded_trace_ids = {record.trace_id for record in records}
        self._baseline_record_hashes = {
            record.trace_id: self._record_hash(record) for record in records
        }
        self._ledger_head_sha256 = head
        self._ledger_entry_count = entry_count
        self._storage_identity = self._current_storage_identity()

    def _current_storage_identity(self) -> Optional[tuple[int, int, int, int, int]]:
        if self.storage_path is None or not self.storage_path.exists():
            return None
        stat = self.storage_path.stat()
        return (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)

    def _refresh_if_storage_changed_unlocked(self) -> None:
        if self.storage_path is None:
            return
        if self._current_storage_identity() == self._storage_identity:
            return
        dirty = [
            trace.trace_id for trace in self.traces
            if trace.trace_id in self._baseline_record_hashes
            and self._record_hash(trace) != self._baseline_record_hashes[trace.trace_id]
        ]
        if dirty:
            raise ValueError(
                "trace ledger changed while local updates were uncommitted: "
                + ", ".join(sorted(dirty))
            )
        with self._storage_transaction():
            if self._current_storage_identity() == self._storage_identity:
                return
            records, head, entry_count, legacy = self._read_storage_unlocked()
            if legacy:
                raise ValueError("trace ledger was replaced by unchained legacy JSONL")
            self._install_storage_state(records, head, entry_count)

    def _sync_directory_unlocked(self) -> None:
        if self.storage_path is None:
            return
        directory_fd = os.open(self.storage_path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)

    def _rewrite_as_ledger_unlocked(self, records: List[ArizeTraceRecord]) -> None:
        if self.storage_path is None:
            return
        temporary = self.storage_path.with_name(self.storage_path.name + ".migrate.tmp")
        previous = TRACE_LEDGER_GENESIS
        with temporary.open("w", encoding="utf-8") as handle:
            for sequence, record in enumerate(records, start=1):
                entry = self._ledger_entry(
                    record,
                    sequence=sequence,
                    previous_entry_sha256=previous,
                    operation="legacy_import",
                )
                handle.write(self._canonical_json(entry) + "\n")
                previous = entry["entry_sha256"]
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, self.storage_path)
        self._sync_directory_unlocked()

    def _append_entries_unlocked(self, entries: List[Dict[str, Any]]) -> None:
        if self.storage_path is None or not entries:
            return
        temporary = self.storage_path.with_name(self.storage_path.name + ".append.tmp")
        existing = self.storage_path.read_bytes() if self.storage_path.exists() else b""
        payload = "".join(self._canonical_json(entry) + "\n" for entry in entries)
        with temporary.open("wb") as handle:
            handle.write(existing)
            handle.write(payload.encode("utf-8"))
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, self.storage_path)
        self._sync_directory_unlocked()

    def start_trace(self, session_id: str, query: str) -> str:
        trace_id = f"trc_{uuid.uuid4().hex[:12]}"
        return trace_id

    def record_trace(self, record: ArizeTraceRecord):
        with self._lock:
            if self.storage_path is None:
                if any(existing.trace_id == record.trace_id for existing in self.traces):
                    raise ValueError(f"trace_id {record.trace_id!r} is already recorded")
                self.traces.append(record)
                self.recorded_trace_ids_in_process.add(record.trace_id)
                return
            dirty = [
                trace.trace_id for trace in self.traces
                if trace.trace_id in self._baseline_record_hashes
                and self._record_hash(trace) != self._baseline_record_hashes[trace.trace_id]
            ]
            if dirty:
                raise ValueError(
                    "uncommitted trace updates must be persisted before recording a new trace: "
                    + ", ".join(sorted(dirty))
                )
            with self._storage_transaction():
                records, head, entry_count, legacy = self._read_storage_unlocked()
                if legacy:
                    self._rewrite_as_ledger_unlocked(records)
                    records, head, entry_count, _ = self._read_storage_unlocked()
                if any(existing.trace_id == record.trace_id for existing in records):
                    raise ValueError(f"trace_id {record.trace_id!r} is already recorded")
                entry = self._ledger_entry(
                    record,
                    sequence=entry_count + 1,
                    previous_entry_sha256=head,
                    operation="record_created",
                )
                self._append_entries_unlocked([entry])
                records.append(record)
                self._install_storage_state(
                    records, entry["entry_sha256"], entry_count + 1,
                )
                self.recorded_trace_ids_in_process.add(record.trace_id)

    def traces_from_current_process(self) -> List[ArizeTraceRecord]:
        """Return records added after this tracer loaded its persisted history."""
        with self._lock:
            self._refresh_if_storage_changed_unlocked()
            return [
                trace for trace in self.traces
                if trace.trace_id in self.recorded_trace_ids_in_process
            ]

    def snapshot(self) -> List[ArizeTraceRecord]:
        """Return a stable shallow snapshot for concurrent status and evaluation reads."""
        with self._lock:
            self._refresh_if_storage_changed_unlocked()
            return list(self.traces)

    def persist(self) -> int:
        """Append local trace updates after checking for concurrent conflicts."""
        with self._lock:
            return self._persist_unlocked()

    def _persist_unlocked(self) -> int:
        if self.storage_path is None:
            return len(self.traces)
        local_by_id = {trace.trace_id: trace for trace in self.traces}
        if len(local_by_id) != len(self.traces):
            raise ValueError("duplicate trace IDs in local state")
        if set(self._baseline_record_hashes) - set(local_by_id):
            raise ValueError("trace deletion is not supported by the append-only ledger")
        untracked = set(local_by_id) - set(self._baseline_record_hashes)
        if untracked:
            raise ValueError(
                "new traces must be committed with record_trace: " + ", ".join(sorted(untracked))
            )
        changed = [
            trace_id for trace_id, record in local_by_id.items()
            if self._record_hash(record) != self._baseline_record_hashes[trace_id]
        ]
        with self._storage_transaction():
            disk_records, head, entry_count, legacy = self._read_storage_unlocked()
            if legacy:
                self._rewrite_as_ledger_unlocked(disk_records)
                disk_records, head, entry_count, _ = self._read_storage_unlocked()
            disk_by_id = {record.trace_id: record for record in disk_records}
            entries = []
            for trace_id in changed:
                if trace_id not in disk_by_id:
                    raise ValueError(f"trace {trace_id!r} disappeared from the persisted ledger")
                disk_hash = self._record_hash(disk_by_id[trace_id])
                if disk_hash != self._baseline_record_hashes[trace_id]:
                    raise ValueError(
                        f"concurrent trace update conflict for {trace_id!r}; refusing to overwrite"
                    )
                entry = self._ledger_entry(
                    local_by_id[trace_id],
                    sequence=entry_count + len(entries) + 1,
                    previous_entry_sha256=(
                        entries[-1]["entry_sha256"] if entries else head
                    ),
                    operation="record_updated",
                )
                entries.append(entry)
                disk_by_id[trace_id] = local_by_id[trace_id]
            self._append_entries_unlocked(entries)
            merged = [disk_by_id[record.trace_id] for record in disk_records]
            final_head = entries[-1]["entry_sha256"] if entries else head
            self._install_storage_state(
                merged, final_head, entry_count + len(entries),
            )
            return len(self.traces)

    def storage_status(self) -> Dict[str, Any]:
        if self.storage_path is None:
            return {
                "format": "memory_only",
                "integrity": "ephemeral_unpersisted",
                "signed": False,
                "externally_anchored": False,
                "entry_count": 0,
                "head_sha256": None,
                "meaning": "This tracer is in memory only and has no durable audit history.",
            }
        with self._lock:
            self._refresh_if_storage_changed_unlocked()
            return {
                "format": "hash_chained_local_jsonl_v1",
                "integrity": "hash_chained_not_signed_not_externally_anchored",
                "verified": True,
                "signed": False,
                "externally_anchored": False,
                "entry_count": self._ledger_entry_count,
                "head_sha256": self._ledger_head_sha256,
                "meaning": (
                    "Every creation and update is hash chained and verified on load. "
                    "The ledger detects edits, reordering, and internal deletion, but a local "
                    "administrator can rewrite or truncate the file because the head is not "
                    "signed or anchored outside this machine. Signed Buzz events are verified separately."
                ),
            }

    def export_jsonl(self, path: str) -> int:
        """Persist traces in an append-friendly, Arize-style JSONL interchange."""
        with self._lock:
            with open(path, "w", encoding="utf-8") as handle:
                for trace in self.traces:
                    handle.write(json.dumps(asdict(trace), sort_keys=True) + "\n")
            return len(self.traces)

    def get_aggregate_metrics(self) -> Dict[str, Any]:
        all_traces = self.snapshot()
        traces = [
            trace for trace in all_traces
            if trace.metadata.get("exclude_from_aggregate_metrics") is not True
        ]
        excluded_count = len(all_traces) - len(traces)
        if not traces:
            return {
                "total_traces": len(all_traces),
                "aggregate_eligible_traces": 0,
                "excluded_trace_count": excluded_count,
                "avg_faithfulness": None,
                "avg_forbidden_string_check": None,
                "avg_tabular_fixture_cell_match": None,
                "avg_latency_ms": None,
                "avg_energy_mwh_per_token": None,
                "local_routing_percentage": None,
                "metric_sample_counts": {
                    "faithfulness": 0,
                    "forbidden_string_check": 0,
                    "tabular_fixture_cell_match": 0,
                    "latency": 0,
                    "energy": 0,
                    "routing": 0,
                },
            }

        total = len(traces)
        faith_scores = []
        denylist_scores = []
        table_scores = []

        for t in traces:
            for ev in t.evaluations:
                if (
                    ev.name == "faithfulness"
                    and ev.metadata.get("measurement_state") != "unverified"
                ):
                    faith_scores.append(ev.score)
                elif ev.name == "forbidden_string_check":
                    denylist_scores.append(ev.score)
                elif (
                    ev.name == "tabular_fixture_cell_match"
                    and ev.metadata.get("measurement_state") != "unverified"
                ):
                    table_scores.append(ev.score)

        local_count = sum(1 for t in traces if "LOCAL" in t.routed_tier)
        energy_values = [
            t.energy_per_token_mwh for t in traces
            if t.energy_per_token_mwh is not None
        ]

        return {
            "total_traces": len(all_traces),
            "aggregate_eligible_traces": total,
            "excluded_trace_count": excluded_count,
            "avg_faithfulness": (
                round(sum(faith_scores) / len(faith_scores), 4) if faith_scores else None
            ),
            "avg_forbidden_string_check": (
                round(sum(denylist_scores) / len(denylist_scores), 4) if denylist_scores else None
            ),
            "avg_tabular_fixture_cell_match": (
                round(sum(table_scores) / len(table_scores), 4) if table_scores else None
            ),
            "avg_latency_ms": round(sum(t.total_latency_ms for t in traces) / total, 2),
            "avg_energy_mwh_per_token": (
                round(sum(energy_values) / len(energy_values), 4)
                if energy_values else None
            ),
            "local_routing_percentage": round((local_count / total) * 100.0, 1),
            "metric_sample_counts": {
                "faithfulness": len(faith_scores),
                "forbidden_string_check": len(denylist_scores),
                "tabular_fixture_cell_match": len(table_scores),
                "latency": total,
                "energy": len(energy_values),
                "routing": total,
            },
        }
