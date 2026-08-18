"""Recompute OCR accuracy from fixed text and raw observed OCR output."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Sequence


BENCHMARK_KIND = "public_ma_clean_raster_ocr_accuracy"
EVIDENCE_KIND = "public_ma_clean_raster_ocr_accuracy_measurement"


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def canonical_sha256(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return sha256_bytes(encoded)


def normalize_ocr_text(value: str) -> str:
    return " ".join(re.findall(r"[^\W_]+", value.casefold(), flags=re.UNICODE))


def edit_distance(expected: Sequence[Any], observed: Sequence[Any]) -> int:
    """Return Levenshtein distance without trusting an OCR engine score."""
    if len(expected) < len(observed):
        expected, observed = observed, expected
    previous = list(range(len(observed) + 1))
    for row, expected_item in enumerate(expected, start=1):
        current = [row]
        for column, observed_item in enumerate(observed, start=1):
            current.append(min(
                current[-1] + 1,
                previous[column] + 1,
                previous[column - 1] + (expected_item != observed_item),
            ))
        previous = current
    return previous[-1]


def _rate(distance: int, expected_count: int) -> float:
    return distance / expected_count if expected_count else (0.0 if distance == 0 else 1.0)


def _phrase_present(phrase: str, observed: str) -> bool:
    normalized = normalize_ocr_text(phrase)
    return bool(normalized) and f" {normalized} " in f" {observed} "


def benchmark_errors(benchmark: Any) -> list[str]:
    errors: list[str] = []
    if not isinstance(benchmark, dict):
        return ["$: OCR benchmark must be an object"]
    if benchmark.get("benchmark_kind") != BENCHMARK_KIND:
        errors.append("$.benchmark_kind: unexpected OCR benchmark kind")
    if benchmark.get("benchmark_version") not in {"1.0.0", "1.1.0", "1.2.0"}:
        errors.append("$.benchmark_version: unexpected OCR benchmark version")
    if benchmark.get("benchmark_version") in {"1.1.0", "1.2.0"}:
        corrections = benchmark.get("ground_truth_corrections")
        if not isinstance(corrections, list) or not corrections:
            errors.append("$.ground_truth_corrections: corrected benchmark needs history")
        elif any(
            not isinstance(item, dict)
            or item.get("thresholds_changed") is not False
            or item.get("domain_review_performed") is not False
            or not re.fullmatch(r"[a-f0-9]{64}", str(item.get("prior_benchmark_sha256", "")))
            for item in corrections
        ):
            errors.append("$.ground_truth_corrections: correction history is invalid")
    if benchmark.get("benchmark_version") == "1.2.0":
        changes = benchmark.get("implementation_changes")
        if not isinstance(changes, list) or not changes:
            errors.append("$.implementation_changes: revised OCR method needs history")
        elif any(
            not isinstance(item, dict)
            or item.get("thresholds_changed") is not False
            or item.get("source_pages_changed") is not False
            or item.get("expected_text_changed") is not False
            or item.get("document_specific_vocabulary_added") is not False
            or item.get("independent_test") is not False
            or not re.fullmatch(
                r"[a-f0-9]{64}", str(item.get("prior_failed_evidence_sha256", ""))
            )
            or not isinstance(item.get("diagnostic_record"), str)
            or not re.fullmatch(
                r"[a-f0-9]{64}", str(item.get("diagnostic_record_sha256", ""))
            )
            for item in changes
        ):
            errors.append("$.implementation_changes: implementation history is invalid")
    source = benchmark.get("source")
    if not isinstance(source, dict):
        errors.append("$.source: source contract is required")
    else:
        if not re.fullmatch(r"[a-f0-9]{64}", str(source.get("sha256", ""))):
            errors.append("$.source.sha256: fixed source hash is required")
        if not isinstance(source.get("bytes"), int) or source.get("bytes", 0) <= 0:
            errors.append("$.source.bytes: positive source size is required")
    derivative = benchmark.get("derivative_contract")
    if not isinstance(derivative, dict):
        errors.append("$.derivative_contract: derivative contract is required")
    elif not (
        derivative.get("kind") == "single_page_image_only_pdf"
        and derivative.get("render_dpi") == 200
        and derivative.get("embedded_text_must_be_empty") is True
    ):
        errors.append("$.derivative_contract: expected clean 200 DPI image-only PDF contract")
    recognition = benchmark.get("recognition_contract")
    if benchmark.get("benchmark_version") == "1.2.0" and not (
        isinstance(recognition, dict)
        and recognition.get("engine") == "apple_vision_vnrecognizetextrequest"
        and recognition.get("render_dpi") == 300
        and recognition.get("recognition_level") == "accurate"
        and recognition.get("language_correction") is True
        and recognition.get("document_specific_vocabulary") == []
    ):
        errors.append("$.recognition_contract: expected disclosed 300 DPI Vision contract")
    thresholds = benchmark.get("thresholds")
    if not isinstance(thresholds, dict):
        errors.append("$.thresholds: thresholds are required")
    else:
        for name in (
            "maximum_word_error_rate",
            "maximum_character_error_rate",
            "minimum_critical_phrase_recall",
        ):
            value = thresholds.get(name)
            if not isinstance(value, (int, float)) or isinstance(value, bool) or not 0 <= value <= 1:
                errors.append(f"$.thresholds.{name}: value must be between zero and one")
        if thresholds.get("every_case_must_pass") is not True:
            errors.append("$.thresholds.every_case_must_pass: every case must pass")
    cases = benchmark.get("cases")
    if not isinstance(cases, list) or not cases:
        return [*errors, "$.cases: at least one OCR case is required"]
    ids = []
    pages = []
    for index, case in enumerate(cases):
        location = f"$.cases[{index}]"
        if not isinstance(case, dict):
            errors.append(f"{location}: case must be an object")
            continue
        case_id = case.get("case_id")
        ids.append(case_id)
        pages.append(case.get("physical_page"))
        expected = case.get("expected_normalized_text")
        if not isinstance(case_id, str) or not case_id:
            errors.append(f"{location}.case_id: case ID is required")
        if not isinstance(case.get("physical_page"), int) or case.get("physical_page", 0) < 1:
            errors.append(f"{location}.physical_page: positive page is required")
        if not isinstance(expected, str) or not expected:
            errors.append(f"{location}.expected_normalized_text: expected text is required")
        elif normalize_ocr_text(expected) != expected:
            errors.append(f"{location}.expected_normalized_text: text is not normalized")
        elif sha256_bytes(expected.encode()) != case.get("expected_normalized_text_sha256"):
            errors.append(f"{location}.expected_normalized_text_sha256: hash differs from text")
        phrases = case.get("critical_phrases")
        if not isinstance(phrases, list) or not phrases or any(
            not isinstance(item, str) or not normalize_ocr_text(item) for item in phrases
        ):
            errors.append(f"{location}.critical_phrases: nonempty phrases are required")
    if len(ids) != len(set(ids)):
        errors.append("$.cases: case IDs must be unique")
    if len(pages) != len(set(pages)):
        errors.append("$.cases: physical pages must be unique")
    limitations = " ".join(str(item).casefold() for item in benchmark.get("limitations", []))
    for required in (
        "born digital text layer",
        "not naturally scanned customer documents",
        "no independent domain reviewer",
        "does not satisfy the human approved ocr release gate",
    ):
        if required not in limitations:
            errors.append(f"$.limitations: missing boundary: {required}")
    return errors


def evaluate_ocr_accuracy(
    benchmark: dict[str, Any],
    observations: list[dict[str, Any]],
) -> dict[str, Any]:
    errors = benchmark_errors(benchmark)
    expected_cases = {
        item["case_id"]: item for item in benchmark.get("cases", []) if isinstance(item, dict)
    }
    observed_cases = {
        item.get("case_id"): item for item in observations if isinstance(item, dict)
    }
    if len(observed_cases) != len(observations):
        errors.append("$.observations: case IDs must be unique objects")
    missing = sorted(set(expected_cases) - set(observed_cases))
    extra = sorted(set(observed_cases) - set(expected_cases))
    if missing:
        errors.append("$.observations: missing cases: " + ", ".join(missing))
    if extra:
        errors.append("$.observations: unexpected cases: " + ", ".join(extra))
    thresholds = benchmark.get("thresholds", {})
    evaluated = []
    total_word_distance = 0
    total_expected_words = 0
    total_character_distance = 0
    total_expected_characters = 0
    total_phrases = 0
    total_phrases_found = 0
    for case_id, expected_case in expected_cases.items():
        observed_case = observed_cases.get(case_id)
        if not isinstance(observed_case, dict):
            continue
        location = f"$.observations[{case_id}]"
        raw_text = observed_case.get("ocr_text")
        if not isinstance(raw_text, str):
            errors.append(f"{location}.ocr_text: raw OCR text is required")
            raw_text = ""
        if observed_case.get("engine") != "apple_vision_vnrecognizetextrequest":
            errors.append(f"{location}.engine: measured Apple Vision engine is required")
        if benchmark.get("benchmark_version") == "1.2.0":
            recognition = benchmark.get("recognition_contract", {})
            if observed_case.get("input_derivative_render_dpi") != 200:
                errors.append(
                    f"{location}.input_derivative_render_dpi: derivative DPI differs from contract"
                )
            if observed_case.get("ocr_render_dpi") != recognition.get("render_dpi"):
                errors.append(f"{location}.ocr_render_dpi: OCR DPI differs from contract")
            if observed_case.get("recognition_level") != recognition.get("recognition_level"):
                errors.append(
                    f"{location}.recognition_level: recognition level differs from contract"
                )
            if observed_case.get("language_correction") is not recognition.get(
                "language_correction"
            ):
                errors.append(
                    f"{location}.language_correction: language correction differs from contract"
                )
            if observed_case.get("document_specific_vocabulary") != []:
                errors.append(
                    f"{location}.document_specific_vocabulary: vocabulary injection is forbidden"
                )
        elif observed_case.get("render_dpi") != 200:
            errors.append(f"{location}.render_dpi: render DPI differs from contract")
        if observed_case.get("embedded_text_empty") is not True:
            errors.append(f"{location}.embedded_text_empty: input was not proved image-only")
        if not re.fullmatch(
            r"[a-f0-9]{64}", str(observed_case.get("input_derivative_sha256", ""))
        ):
            errors.append(f"{location}.input_derivative_sha256: derivative hash is required")
        observed = normalize_ocr_text(raw_text)
        expected = expected_case["expected_normalized_text"]
        expected_words = expected.split()
        observed_words = observed.split()
        word_distance = edit_distance(expected_words, observed_words)
        character_distance = edit_distance(expected, observed)
        word_error_rate = _rate(word_distance, len(expected_words))
        character_error_rate = _rate(character_distance, len(expected))
        phrase_checks = [
            {"phrase": phrase, "found": _phrase_present(phrase, observed)}
            for phrase in expected_case["critical_phrases"]
        ]
        phrase_recall = sum(item["found"] for item in phrase_checks) / len(phrase_checks)
        case_passed = (
            word_error_rate <= thresholds.get("maximum_word_error_rate", -1)
            and character_error_rate <= thresholds.get("maximum_character_error_rate", -1)
            and phrase_recall >= thresholds.get("minimum_critical_phrase_recall", 2)
        )
        evaluated.append({
            "case_id": case_id,
            "physical_page": expected_case["physical_page"],
            "expected_word_count": len(expected_words),
            "observed_word_count": len(observed_words),
            "word_edit_distance": word_distance,
            "word_error_rate": word_error_rate,
            "expected_character_count": len(expected),
            "character_edit_distance": character_distance,
            "character_error_rate": character_error_rate,
            "critical_phrase_recall": phrase_recall,
            "critical_phrase_checks": phrase_checks,
            "passed": case_passed,
        })
        total_word_distance += word_distance
        total_expected_words += len(expected_words)
        total_character_distance += character_distance
        total_expected_characters += len(expected)
        total_phrases += len(phrase_checks)
        total_phrases_found += sum(item["found"] for item in phrase_checks)
    aggregate_word_error_rate = _rate(total_word_distance, total_expected_words)
    aggregate_character_error_rate = _rate(
        total_character_distance, total_expected_characters
    )
    aggregate_phrase_recall = _rate(total_phrases_found, total_phrases)
    all_cases_present = len(evaluated) == len(expected_cases)
    passed = (
        not errors
        and all_cases_present
        and all(item["passed"] for item in evaluated)
        and aggregate_word_error_rate <= thresholds.get("maximum_word_error_rate", -1)
        and aggregate_character_error_rate <= thresholds.get("maximum_character_error_rate", -1)
        and aggregate_phrase_recall >= thresholds.get("minimum_critical_phrase_recall", 2)
    )
    return {
        "passed": passed,
        "errors": errors,
        "case_count": len(evaluated),
        "cases": evaluated,
        "aggregate": {
            "expected_word_count": total_expected_words,
            "word_edit_distance": total_word_distance,
            "word_error_rate": aggregate_word_error_rate,
            "expected_character_count": total_expected_characters,
            "character_edit_distance": total_character_distance,
            "character_error_rate": aggregate_character_error_rate,
            "critical_phrase_count": total_phrases,
            "critical_phrases_found": total_phrases_found,
            "critical_phrase_recall": aggregate_phrase_recall,
        },
        "thresholds": thresholds,
        "measurement_scope": "three clean 200 DPI raster derivatives of fixed public M&A pages",
        "human_approved_ocr_release_gate_passed": False,
    }


def resolution_diagnostic_errors(benchmark: dict[str, Any], record: Any) -> list[str]:
    """Validate the saved development diagnostic without treating it as a release test."""
    errors: list[str] = []
    if not isinstance(record, dict):
        return ["OCR resolution diagnostic must be an object"]
    if record.get("verification_kind") != "ocr_resolution_sweep_development_diagnostic":
        errors.append("OCR resolution diagnostic has an unexpected kind")
    if record.get("source") != benchmark.get("source"):
        errors.append("OCR resolution diagnostic source differs from benchmark")
    if not (
        record.get("physical_page") == 1
        and record.get("input_derivative_render_dpi") == 200
        and record.get("engine") == "apple_vision_vnrecognizetextrequest"
        and record.get("recognition_level") == "accurate"
        and record.get("language_correction") is True
        and record.get("document_specific_vocabulary") == []
    ):
        errors.append("OCR resolution diagnostic method differs from the recorded sweep")
    if not (
        record.get("selected_product_ocr_render_dpi") == 300
        and record.get("benchmark_used_for_selection") is True
        and record.get("independent_test") is False
        and record.get("human_approved_ocr_release_gate_passed") is False
    ):
        errors.append("OCR resolution diagnostic overstates its evidence boundary")
    settings = record.get("settings")
    if not isinstance(settings, list) or [
        item.get("ocr_render_dpi") for item in settings if isinstance(item, dict)
    ] != [150, 200, 250, 300, 400, 600]:
        errors.append("OCR resolution diagnostic settings differ from the required sweep")
        return errors
    by_dpi = {item["ocr_render_dpi"]: item for item in settings}
    for dpi, item in by_dpi.items():
        if not (
            isinstance(item.get("ocr_text"), str)
            and re.fullmatch(r"[a-f0-9]{64}", str(item.get("raster_sha256", "")))
            and isinstance(item.get("raster_bytes"), int)
            and item.get("raster_bytes", 0) > 0
        ):
            errors.append(f"OCR resolution diagnostic {dpi} DPI raw record is invalid")
    if not (
        by_dpi[200].get("contains_exact_cma_token") is False
        and by_dpi[200].get("contains_cmay_token") is True
    ):
        errors.append("OCR resolution diagnostic does not preserve the 200 DPI failure")
    for dpi in (250, 300, 400, 600):
        if not (
            by_dpi[dpi].get("contains_exact_cma_token") is True
            and by_dpi[dpi].get("contains_cmay_token") is False
        ):
            errors.append(f"OCR resolution diagnostic does not preserve the {dpi} DPI result")
    return errors


def validate_saved_ocr_accuracy(root: Path, evidence_path: Path) -> dict[str, Any]:
    benchmark_path = root / "benchmarks" / "ocr_accuracy_public.v1.json"
    errors: list[str] = []
    try:
        benchmark_bytes = benchmark_path.read_bytes()
        benchmark = json.loads(benchmark_bytes)
        evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"passed": False, "errors": [str(exc)]}
    if evidence.get("verification_kind") != EVIDENCE_KIND:
        errors.append("unexpected OCR evidence kind")
    if evidence.get("benchmark_sha256") != sha256_bytes(benchmark_bytes):
        errors.append("OCR evidence benchmark hash differs from current contract")
    if evidence.get("source") != benchmark.get("source"):
        errors.append("OCR evidence source contract differs from benchmark")
    if evidence.get("human_approved_ocr_release_gate_passed") is not False:
        errors.append("OCR engineering evidence claims a human approved release")
    for correction in benchmark.get("ground_truth_corrections", []):
        visual_relative = correction.get("visual_record")
        if not isinstance(visual_relative, str):
            errors.append("OCR ground truth correction lacks a visual record")
            continue
        visual_path = (root / visual_relative).resolve()
        try:
            visual_path.relative_to(root.resolve())
            visual_hash = sha256_bytes(visual_path.read_bytes())
        except (OSError, ValueError) as exc:
            errors.append(f"OCR ground truth visual record is unavailable: {exc}")
        else:
            if visual_hash != correction.get("visual_record_sha256"):
                errors.append("OCR ground truth visual record hash differs from correction")
    if benchmark.get("ground_truth_corrections"):
        correction_path = root / "evidence" / "ocr-ground-truth-correction-v1.json"
        try:
            correction_record = json.loads(correction_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f"OCR ground truth correction record is unavailable: {exc}")
        else:
            first = benchmark["ground_truth_corrections"][0]
            for field in (
                "prior_benchmark_sha256",
                "prior_failed_evidence_sha256",
                "visual_record_sha256",
            ):
                expected = (
                    first.get(field)
                    if field != "visual_record_sha256"
                    else first.get("visual_record_sha256")
                )
                observed = (
                    correction_record.get(field)
                    if field != "visual_record_sha256"
                    else correction_record.get("correction", {}).get(field)
                )
                if observed != expected:
                    errors.append(f"OCR ground truth correction record differs on {field}")
            if not (
                correction_record.get("domain_review_performed") is False
                and correction_record.get("human_approved_ocr_release_gate_passed") is False
                and correction_record.get("correction", {}).get("thresholds_changed") is False
            ):
                errors.append("OCR ground truth correction overstates its review boundary")
    for change in benchmark.get("implementation_changes", []):
        relative = change.get("diagnostic_record")
        if not isinstance(relative, str):
            errors.append("OCR implementation change lacks a diagnostic record")
            continue
        path = (root / relative).resolve()
        try:
            path.relative_to(root.resolve())
            diagnostic_bytes = path.read_bytes()
            diagnostic = json.loads(diagnostic_bytes)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            errors.append(f"OCR resolution diagnostic is unavailable: {exc}")
            continue
        if sha256_bytes(diagnostic_bytes) != change.get("diagnostic_record_sha256"):
            errors.append("OCR resolution diagnostic hash differs from implementation history")
        errors.extend(resolution_diagnostic_errors(benchmark, diagnostic))
    recomputed = evaluate_ocr_accuracy(benchmark, evidence.get("observations", []))
    if evidence.get("evaluation") != recomputed:
        errors.append("saved OCR evaluation differs from recomputed raw observations")
    return {
        "passed": not errors and not recomputed["errors"],
        "engineering_measurement_passed": recomputed["passed"],
        "human_approved_ocr_release_gate_passed": False,
        "benchmark_sha256": sha256_bytes(benchmark_bytes),
        "source_sha256": benchmark.get("source", {}).get("sha256"),
        "case_count": recomputed["case_count"],
        "aggregate": recomputed["aggregate"],
        "errors": [*errors, *recomputed["errors"]],
        "limitations": benchmark.get("limitations", []),
    }
