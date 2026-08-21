"""Fail-closed calibration metrics for a semantic benchmark judge."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from core.first_pass_benchmark import schema_errors, sha256
from core.first_pass_review import validate_human_review_receipt


def _canonical_sha256(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(payload).hexdigest()


def _safe_project_path(root: Path, relative: str) -> Path:
    path = (root / relative).resolve()
    try:
        path.relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError("human review receipt resolves outside the project") from exc
    return path


def _cohens_kappa(human: list[str], judge: list[str]) -> float:
    count = len(human)
    observed = sum(left == right for left, right in zip(human, judge)) / count
    human_pass = human.count("pass") / count
    judge_pass = judge.count("pass") / count
    expected = human_pass * judge_pass + (1 - human_pass) * (1 - judge_pass)
    if expected == 1:
        return 1.0 if observed == 1 else 0.0
    return (observed - expected) / (1 - expected)


def evaluate_judge_calibration(root: Path, record: dict[str, Any]) -> dict[str, Any]:
    """Validate one calibration record and evaluate every registered judge gate."""
    root = root.resolve()
    contract = root / "benchmarks" / "first_pass"
    schema = json.loads((contract / "judge_calibration.schema.json").read_text())
    rubric_path = contract / "rubric.v1.json"
    manifest_path = contract / "benchmark_manifest.v2.json"
    rubric = json.loads(rubric_path.read_text())
    manifest = json.loads(manifest_path.read_text())
    errors = schema_errors(record, schema)

    if record.get("rubric_sha256") != sha256(rubric_path):
        errors.append("$.rubric_sha256: calibration is not bound to the current rubric")

    binding = record.get("human_review_receipt", {})
    receipt: dict[str, Any] = {}
    try:
        receipt_path = _safe_project_path(root, str(binding.get("path", "")))
        receipt_bytes = receipt_path.read_bytes()
        if hashlib.sha256(receipt_bytes).hexdigest() != binding.get("sha256"):
            errors.append("$.human_review_receipt.sha256: receipt hash does not match")
        receipt = json.loads(receipt_bytes)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        errors.append(f"$.human_review_receipt: {exc}")

    receipt_validation = validate_human_review_receipt(root, receipt) if receipt else {
        "passed": False, "errors": ["receipt unavailable"], "resolved_labels": [],
        "resolved_labels_sha256": None,
    }
    errors.extend(
        f"$.human_review_receipt: {item}" for item in receipt_validation["errors"]
    )
    resolved = receipt_validation["resolved_labels"] if receipt_validation["passed"] else []
    resolved_sha = receipt_validation["resolved_labels_sha256"]
    if resolved_sha != binding.get("resolved_labels_sha256"):
        errors.append("$.human_review_receipt.resolved_labels_sha256: binding does not match")

    judge_dimensions = {
        item["id"] for item in rubric["dimensions"]
        if "semantic_judge" in item["method"]
    }
    reference_items = [
        item for item in resolved
        if isinstance(item, dict) and item.get("dimension") in judge_dimensions
    ]
    reference = {
        (item.get("case_id"), item.get("dimension")): item
        for item in reference_items
    }
    if len(reference) != len(reference_items):
        errors.append("$.human_review_receipt: resolved human label keys are not unique")
    if reference_items and any(item.get("split") != "calibration" for item in reference_items):
        errors.append("$.human_review_receipt: every referenced case must be in calibration")

    observed_items = record.get("labels", [])
    observed = {
        (item.get("case_id"), item.get("dimension")): item
        for item in observed_items if isinstance(item, dict)
    }
    if len(observed) != len(observed_items):
        errors.append("$.labels: case and dimension keys must be unique")
    if set(observed) != set(reference):
        errors.append("$.labels: judge labels must match every calibrated human label exactly once")

    case_ids = {item.get("case_id") for item in reference_items}
    deal_ids = {item.get("deal_id") for item in reference_items}
    target = manifest["target"]["splits"]["calibration"]
    if len(case_ids) < target["cases"]:
        errors.append(f"$.labels: calibration requires at least {target['cases']} cases")
    if len(deal_ids) < target["minimum_deals"]:
        errors.append(f"$.labels: calibration requires at least {target['minimum_deals']} deals")
    if {item.get("final_label") for item in reference_items} != {"pass", "fail"}:
        errors.append("$.human_review_receipt: calibration needs both pass and fail labels")

    pairwise = record.get("pairwise_trials", [])
    trial_ids = [item.get("trial_id") for item in pairwise if isinstance(item, dict)]
    if len(trial_ids) != len(set(trial_ids)):
        errors.append("$.pairwise_trials: trial IDs must be unique")
    pair_case_ids = {item.get("case_id") for item in pairwise if isinstance(item, dict)}
    if not case_ids.issubset(pair_case_ids):
        errors.append("$.pairwise_trials: every calibration case needs an order trial")

    label_parse_failures = sum(
        item.get("judge_label") == "unparseable" for item in observed_items
    )
    pair_parse_failures = sum(
        choice == "unparseable"
        for item in pairwise if isinstance(item, dict)
        for choice in (item.get("forward_choice"), item.get("reversed_choice"))
    )
    parse_observations = len(observed_items) + 2 * len(pairwise)
    parse_failure_count = label_parse_failures + pair_parse_failures
    parse_failure_rate = parse_failure_count / parse_observations if parse_observations else 1.0

    paired = [
        item for item in pairwise
        if item.get("forward_choice") != "unparseable"
        and item.get("reversed_choice") != "unparseable"
    ]
    pairwise_flip_count = sum(
        item["forward_choice"] != item["reversed_choice"] for item in paired
    )
    pairwise_flip_rate = pairwise_flip_count / len(paired) if paired else None

    parsed_keys = [key for key in reference if observed.get(key, {}).get("judge_label") in {"pass", "fail"}]
    human_labels = [reference[key]["final_label"] for key in parsed_keys]
    judge_labels = [observed[key]["judge_label"] for key in parsed_keys]
    true_fail = sum(human == judge == "fail" for human, judge in zip(human_labels, judge_labels))
    false_fail = sum(human == "pass" and judge == "fail" for human, judge in zip(human_labels, judge_labels))
    missed_fail = sum(human == "fail" and judge == "pass" for human, judge in zip(human_labels, judge_labels))
    fail_recall = true_fail / (true_fail + missed_fail) if true_fail + missed_fail else 0.0
    fail_precision = true_fail / (true_fail + false_fail) if true_fail + false_fail else 0.0
    critical_false_passes = sum(
        reference[key].get("severity") == "critical"
        and reference[key].get("final_label") == "fail"
        and observed.get(key, {}).get("judge_label") == "pass"
        for key in reference
    )
    kappa = (
        _cohens_kappa(human_labels, judge_labels)
        if human_labels and len(parsed_keys) == len(reference) else None
    )

    thresholds = rubric["judge_gates"]
    gates = {
        "critical_false_passes": {
            "observed": critical_false_passes,
            "threshold": thresholds["maximum_critical_false_passes"],
            "passed": critical_false_passes <= thresholds["maximum_critical_false_passes"],
        },
        "fail_recall": {
            "observed": round(fail_recall, 6),
            "threshold": thresholds["minimum_fail_recall"],
            "passed": fail_recall >= thresholds["minimum_fail_recall"],
        },
        "fail_precision": {
            "observed": round(fail_precision, 6),
            "threshold": thresholds["minimum_fail_precision"],
            "passed": fail_precision >= thresholds["minimum_fail_precision"],
        },
        "cohens_kappa": {
            "observed": None if kappa is None else round(kappa, 6),
            "threshold": thresholds["minimum_cohens_kappa"],
            "passed": kappa is not None and kappa >= thresholds["minimum_cohens_kappa"],
        },
        "parse_failure_rate": {
            "observed": round(parse_failure_rate, 6),
            "threshold": thresholds["maximum_parse_failure_rate"],
            "passed": parse_failure_rate <= thresholds["maximum_parse_failure_rate"],
        },
        "pairwise_order_flip_rate": {
            "observed": None if pairwise_flip_rate is None else round(pairwise_flip_rate, 6),
            "threshold": thresholds["maximum_pairwise_order_flip_rate"],
            "passed": (
                pairwise_flip_rate is not None
                and pairwise_flip_rate <= thresholds["maximum_pairwise_order_flip_rate"]
            ),
        },
    }
    return {
        "verification_kind": "first_pass_semantic_judge_calibration",
        "calibration_id": record.get("calibration_id"),
        "input_valid": not errors,
        "errors": errors,
        "case_count": len(case_ids),
        "deal_count": len(deal_ids),
        "label_count": len(observed_items),
        "pairwise_trial_count": len(pairwise),
        "judge": record.get("judge"),
        "metrics": {
            "true_fail": true_fail,
            "false_fail": false_fail,
            "missed_fail": missed_fail,
            "parse_failure_count": parse_failure_count,
            "pairwise_flip_count": pairwise_flip_count,
        },
        "gates": gates,
        "calibration_passed": bool(not errors and all(item["passed"] for item in gates.values())),
        "limitations": [
            "Calibration measures the recorded semantic judge against signed human labels. It does not measure the answer model.",
            "Passing calibration does not authorize a sealed test or an accuracy release.",
        ],
    }


def validate_saved_judge_calibration(root: Path, result_path: Path) -> dict[str, Any]:
    """Recompute a saved calibration result from its exact input and dependencies."""
    root = root.resolve()
    result_path = result_path.resolve()
    if not result_path.exists():
        return {
            "evidence_state": "not_recorded",
            "calibration_passed": False,
            "errors": [],
        }
    errors: list[str] = []
    try:
        result_path.relative_to(root)
        saved = json.loads(result_path.read_text(encoding="utf-8"))
        input_path = _safe_project_path(root, str(saved.get("input_path", "")))
        record = json.loads(input_path.read_text(encoding="utf-8"))
        recomputed = evaluate_judge_calibration(root, record)
        recomputed["input_path"] = str(input_path.relative_to(root))
        if saved != recomputed:
            errors.append("saved calibration result differs from recomputed input and dependencies")
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        saved = {}
        recomputed = {}
        errors.append(str(exc))
    return {
        "evidence_state": "verified" if not errors else "invalid",
        "calibration_passed": bool(
            not errors and recomputed.get("calibration_passed") is True
        ),
        "case_count": recomputed.get("case_count"),
        "deal_count": recomputed.get("deal_count"),
        "gates": recomputed.get("gates", {}),
        "judge": recomputed.get("judge"),
        "errors": errors,
    }
