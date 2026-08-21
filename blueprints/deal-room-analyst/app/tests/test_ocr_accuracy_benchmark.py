import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from core.ocr_accuracy_benchmark import (
    EVIDENCE_KIND,
    benchmark_errors,
    evaluate_ocr_accuracy,
    normalize_ocr_text,
    resolution_diagnostic_errors,
    validate_saved_ocr_accuracy,
)


def fixture_benchmark() -> dict:
    expected = normalize_ocr_text("Total purchase price: 95 million dollars")
    return {
        "benchmark_kind": "public_ma_clean_raster_ocr_accuracy",
        "benchmark_version": "1.0.0",
        "preregistered_at": "2026-08-16T00:26:00-04:00",
        "source": {
            "document_id": "fixture",
            "publisher": "Fixture publisher",
            "canonical_url": "https://example.invalid/fixed.pdf",
            "local_path": ".runtime/fixed.pdf",
            "sha256": "a" * 64,
            "bytes": 100,
        },
        "derivative_contract": {
            "kind": "single_page_image_only_pdf",
            "render_dpi": 200,
            "renderer": "pdftoppm",
            "image_to_pdf": "sips",
            "embedded_text_must_be_empty": True,
        },
        "thresholds": {
            "maximum_word_error_rate": 0.1,
            "maximum_character_error_rate": 0.1,
            "minimum_critical_phrase_recall": 1.0,
            "every_case_must_pass": True,
        },
        "cases": [{
            "case_id": "purchase_price",
            "physical_page": 1,
            "expected_normalized_text": expected,
            "expected_normalized_text_sha256": hashlib.sha256(expected.encode()).hexdigest(),
            "critical_phrases": ["95 million", "purchase price"],
        }],
        "limitations": [
            "The reference comes from a born digital text layer.",
            "These are not naturally scanned customer documents.",
            "No independent domain reviewer approved the labels.",
            "A pass does not satisfy the human approved OCR release gate.",
        ],
    }


def observation(text: str) -> dict:
    return {
        "case_id": "purchase_price",
        "engine": "apple_vision_vnrecognizetextrequest",
        "render_dpi": 200,
        "embedded_text_empty": True,
        "input_derivative_sha256": "b" * 64,
        "ocr_text": text,
    }


class OcrAccuracyBenchmarkTests(unittest.TestCase):
    def test_exact_raw_ocr_text_passes_recomputed_metrics(self):
        result = evaluate_ocr_accuracy(
            fixture_benchmark(), [observation("Total purchase price: 95 million dollars")],
        )
        self.assertTrue(result["passed"], result["errors"])
        self.assertEqual(result["aggregate"]["word_error_rate"], 0)
        self.assertEqual(result["aggregate"]["critical_phrase_recall"], 1)
        self.assertFalse(result["human_approved_ocr_release_gate_passed"])

    def test_wrong_material_number_fails_error_and_phrase_thresholds(self):
        result = evaluate_ocr_accuracy(
            fixture_benchmark(), [observation("Total purchase price: 85 million dollars")],
        )
        self.assertFalse(result["passed"])
        self.assertGreater(result["aggregate"]["word_error_rate"], 0.1)
        self.assertLess(result["aggregate"]["critical_phrase_recall"], 1)

    def test_ground_truth_text_cannot_drift_from_preregistered_hash(self):
        benchmark = fixture_benchmark()
        benchmark["cases"][0]["expected_normalized_text"] = normalize_ocr_text(
            "Total purchase price: 85 million dollars"
        )
        self.assertTrue(any(
            "hash differs from text" in item for item in benchmark_errors(benchmark)
        ))

    def test_revised_method_rejects_wrong_ocr_dpi_or_vocabulary_injection(self):
        benchmark = fixture_benchmark()
        benchmark["benchmark_version"] = "1.2.0"
        benchmark["ground_truth_corrections"] = [{
            "thresholds_changed": False,
            "domain_review_performed": False,
            "prior_benchmark_sha256": "c" * 64,
        }]
        benchmark["implementation_changes"] = [{
            "thresholds_changed": False,
            "source_pages_changed": False,
            "expected_text_changed": False,
            "document_specific_vocabulary_added": False,
            "independent_test": False,
            "prior_failed_evidence_sha256": "d" * 64,
        }]
        benchmark["recognition_contract"] = {
            "engine": "apple_vision_vnrecognizetextrequest",
            "render_dpi": 300,
            "recognition_level": "accurate",
            "language_correction": True,
            "document_specific_vocabulary": [],
        }
        observed = observation("Total purchase price: 95 million dollars")
        observed.pop("render_dpi")
        observed.update({
            "input_derivative_render_dpi": 200,
            "ocr_render_dpi": 200,
            "recognition_level": "accurate",
            "language_correction": True,
            "document_specific_vocabulary": ["purchase price"],
        })
        result = evaluate_ocr_accuracy(benchmark, [observed])
        self.assertFalse(result["passed"])
        self.assertTrue(any("OCR DPI differs" in item for item in result["errors"]))
        self.assertTrue(any("vocabulary injection" in item for item in result["errors"]))

    def test_resolution_diagnostic_preserves_failure_and_development_boundary(self):
        root = Path(__file__).resolve().parents[1]
        benchmark = json.loads(
            (root / "benchmarks" / "ocr_accuracy_public.v1.json").read_text()
        )
        diagnostic = json.loads(
            (root / "evidence" / "ocr-resolution-diagnostic-v1.json").read_text()
        )
        self.assertEqual(resolution_diagnostic_errors(benchmark, diagnostic), [])
        tampered = copy.deepcopy(diagnostic)
        tampered["settings"][1]["contains_exact_cma_token"] = True
        self.assertTrue(any(
            "200 DPI failure" in item
            for item in resolution_diagnostic_errors(benchmark, tampered)
        ))
        promoted = copy.deepcopy(diagnostic)
        promoted["independent_test"] = True
        self.assertTrue(any(
            "overstates" in item
            for item in resolution_diagnostic_errors(benchmark, promoted)
        ))

    def test_saved_scores_are_recomputed_and_tampering_fails(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            benchmark_path = root / "benchmarks" / "ocr_accuracy_public.v1.json"
            benchmark_path.parent.mkdir(parents=True)
            benchmark = fixture_benchmark()
            benchmark_bytes = (json.dumps(benchmark, indent=2) + "\n").encode()
            benchmark_path.write_bytes(benchmark_bytes)
            observations = [observation("Total purchase price: 95 million dollars")]
            evaluation = evaluate_ocr_accuracy(benchmark, observations)
            evidence = {
                "verification_kind": EVIDENCE_KIND,
                "benchmark_sha256": hashlib.sha256(benchmark_bytes).hexdigest(),
                "source": benchmark["source"],
                "human_approved_ocr_release_gate_passed": False,
                "observations": observations,
                "evaluation": evaluation,
            }
            evidence_path = root / "evidence.json"
            evidence_path.write_text(json.dumps(evidence))
            self.assertTrue(validate_saved_ocr_accuracy(root, evidence_path)["passed"])

            tampered = copy.deepcopy(evidence)
            tampered["evaluation"]["aggregate"]["word_error_rate"] = 0.5
            evidence_path.write_text(json.dumps(tampered))
            result = validate_saved_ocr_accuracy(root, evidence_path)
            self.assertFalse(result["passed"])
            self.assertIn(
                "saved OCR evaluation differs from recomputed raw observations",
                result["errors"],
            )

            forged = copy.deepcopy(evidence)
            forged["observations"][0]["ocr_text"] = "Total purchase price 85 million dollars"
            evidence_path.write_text(json.dumps(forged))
            result = validate_saved_ocr_accuracy(root, evidence_path)
            self.assertFalse(result["passed"])
            self.assertFalse(result["engineering_measurement_passed"])


if __name__ == "__main__":
    unittest.main()
