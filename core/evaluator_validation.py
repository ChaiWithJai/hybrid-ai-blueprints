"""Validate a binary semantic evaluator against held-out human labels.

The positive class is Pass. A false positive is therefore the dangerous case:
the judge says Pass when the human label says Fail.
"""

from __future__ import annotations

import random
from collections import Counter
from typing import Any, Iterable


VALID_LABELS = {"pass", "fail"}
VALID_SPLITS = {"train", "dev", "test"}


def _label(value: Any, *, allow_invalid: bool = False) -> str | None:
    normalized = str(value).strip().lower() if value is not None else ""
    if normalized in VALID_LABELS:
        return normalized
    if allow_invalid:
        return None
    raise ValueError("labels must be Pass or Fail")


def confusion_metrics(
    human_labels: Iterable[Any], judge_labels: Iterable[Any],
) -> dict[str, Any]:
    """Return classifier metrics with Pass as the positive class."""

    human = list(human_labels)
    judge = list(judge_labels)
    if len(human) != len(judge):
        raise ValueError("human and judge label counts differ")
    if not human:
        raise ValueError("at least one labeled example is required")

    counts = Counter({"tp": 0, "tn": 0, "fp": 0, "fn": 0, "parse_failures": 0})
    for human_value, judge_value in zip(human, judge):
        truth = _label(human_value)
        prediction = _label(judge_value, allow_invalid=True)
        if prediction is None:
            counts["parse_failures"] += 1
            continue
        if truth == "pass" and prediction == "pass":
            counts["tp"] += 1
        elif truth == "fail" and prediction == "fail":
            counts["tn"] += 1
        elif truth == "fail" and prediction == "pass":
            counts["fp"] += 1
        else:
            counts["fn"] += 1

    positive_total = counts["tp"] + counts["fn"]
    negative_total = counts["tn"] + counts["fp"]
    parsed = len(human) - counts["parse_failures"]
    return {
        **dict(counts),
        "sample_count": len(human),
        "parsed_count": parsed,
        "tpr": counts["tp"] / positive_total if positive_total else None,
        "tnr": counts["tn"] / negative_total if negative_total else None,
        "precision": counts["tp"] / (counts["tp"] + counts["fp"])
        if counts["tp"] + counts["fp"] else None,
        "parse_failure_rate": counts["parse_failures"] / len(human),
        "observed_judge_pass_rate": (
            (counts["tp"] + counts["fp"]) / parsed if parsed else None
        ),
        "critical_false_passes": counts["fp"],
        "positive_class": "pass",
    }


def bias_corrected_pass_rate(
    observed_judge_pass_rate: float,
    *,
    tpr: float,
    tnr: float,
) -> float:
    """Correct an observed judge pass rate for measured classifier error."""

    values = (observed_judge_pass_rate, tpr, tnr)
    if any(value < 0 or value > 1 for value in values):
        raise ValueError("rates must be between zero and one")
    denominator = tpr + tnr - 1
    if abs(denominator) < 1e-9:
        raise ValueError("judge discrimination is too weak for bias correction")
    corrected = (observed_judge_pass_rate + tnr - 1) / denominator
    return max(0.0, min(1.0, corrected))


def bootstrap_corrected_pass_interval(
    human_labels: Iterable[Any],
    judge_labels: Iterable[Any],
    *,
    confidence: float = 0.95,
    samples: int = 2000,
    seed: int = 17,
) -> dict[str, Any]:
    """Bootstrap the corrected pass rate without hiding invalid resamples."""

    human = list(human_labels)
    judge = list(judge_labels)
    if len(human) != len(judge) or not human:
        raise ValueError("human and judge labels must be nonempty and paired")
    if samples < 100:
        raise ValueError("at least 100 bootstrap samples are required")
    if confidence <= 0 or confidence >= 1:
        raise ValueError("confidence must be between zero and one")

    rng = random.Random(seed)
    estimates: list[float] = []
    invalid = 0
    for _ in range(samples):
        indexes = [rng.randrange(len(human)) for _ in human]
        metrics = confusion_metrics(
            [human[index] for index in indexes],
            [judge[index] for index in indexes],
        )
        try:
            if metrics["tpr"] is None or metrics["tnr"] is None:
                raise ValueError("resample lacks both classes")
            estimates.append(bias_corrected_pass_rate(
                metrics["observed_judge_pass_rate"],
                tpr=metrics["tpr"],
                tnr=metrics["tnr"],
            ))
        except (TypeError, ValueError):
            invalid += 1

    if len(estimates) < samples * 0.8:
        return {
            "state": "insufficient_valid_resamples",
            "confidence": confidence,
            "valid_resamples": len(estimates),
            "invalid_resamples": invalid,
            "lower": None,
            "upper": None,
        }
    estimates.sort()
    alpha = (1 - confidence) / 2
    lower_index = max(0, int(alpha * len(estimates)))
    upper_index = min(len(estimates) - 1, int((1 - alpha) * len(estimates)) - 1)
    return {
        "state": "measured",
        "confidence": confidence,
        "valid_resamples": len(estimates),
        "invalid_resamples": invalid,
        "lower": estimates[lower_index],
        "upper": estimates[upper_index],
    }


def validate_calibration_dataset(rows: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Validate disjoint, class-bearing train, dev, and test membership."""

    material = list(rows)
    seen: set[str] = set()
    counts = {split: Counter() for split in sorted(VALID_SPLITS)}
    errors: list[str] = []
    for index, row in enumerate(material):
        record_id = str(row.get("id") or "").strip()
        split = str(row.get("split") or "").strip().lower()
        try:
            label = _label(row.get("label"))
        except ValueError:
            label = None
            errors.append(f"row {index} has an invalid label")
        if not record_id:
            errors.append(f"row {index} is missing id")
        elif record_id in seen:
            errors.append(f"duplicate id: {record_id}")
        else:
            seen.add(record_id)
        if split not in VALID_SPLITS:
            errors.append(f"row {index} has an invalid split")
        elif label is not None:
            counts[split][label] += 1

    for split in sorted(VALID_SPLITS):
        if not counts[split]["pass"] or not counts[split]["fail"]:
            errors.append(f"{split} split must contain Pass and Fail labels")
    return {
        "valid": not errors,
        "row_count": len(material),
        "counts": {split: dict(counts[split]) for split in sorted(VALID_SPLITS)},
        "errors": errors,
    }


def judge_release_decision(
    metrics: dict[str, Any],
    *,
    minimum_tpr: float = 0.9,
    minimum_tnr: float = 0.9,
    maximum_critical_false_passes: int = 0,
) -> dict[str, Any]:
    """Make the release decision from explicit classifier gates."""

    failures: list[str] = []
    if metrics.get("tpr") is None or metrics["tpr"] < minimum_tpr:
        failures.append("tpr_below_target")
    if metrics.get("tnr") is None or metrics["tnr"] < minimum_tnr:
        failures.append("tnr_below_target")
    if metrics.get("critical_false_passes", 0) > maximum_critical_false_passes:
        failures.append("critical_false_pass_limit_exceeded")
    if metrics.get("parse_failures", 0):
        failures.append("judge_parse_failures_present")
    return {"trusted_for_release": not failures, "failures": failures}
