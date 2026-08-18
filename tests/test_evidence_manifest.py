import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.evidence_manifest import (
    engineering_evidence_summary,
    engineering_source_manifest,
    source_manifest_errors,
)
from server import VaultHTTPRequestHandler
from scripts.verify_clean_directory import COPY_DIRECTORIES, COPY_FILES
from scripts.verify_product import (
    finalize_report_output,
    local_verification_cold_gate,
    runtime_network_observation_gate,
    runtime_trace_anchor_gate,
)


class EvidenceManifestTests(unittest.TestCase):
    def test_local_verification_requires_cold_restart_except_candidate(self):
        self.assertFalse(local_verification_cold_gate("local", False, {"passed": False}))
        self.assertTrue(local_verification_cold_gate("local", False, {"passed": True}))
        self.assertTrue(local_verification_cold_gate("local", True, {"passed": False}))
        self.assertTrue(local_verification_cold_gate("baseline", False, {"passed": False}))

    def test_live_trace_anchor_is_required_only_for_local_runtime(self):
        self.assertFalse(runtime_trace_anchor_gate("local", {"passed": False}))
        self.assertTrue(runtime_trace_anchor_gate("local", {"passed": True}))
        self.assertTrue(runtime_trace_anchor_gate("baseline", {"passed": False}))
        self.assertTrue(runtime_trace_anchor_gate("cloud", {"passed": False}))

    def test_process_network_observation_is_required_only_for_local_runtime(self):
        self.assertFalse(runtime_network_observation_gate("local", {"passed": False}))
        self.assertTrue(runtime_network_observation_gate("local", {"passed": True}))
        self.assertTrue(runtime_network_observation_gate("baseline", {"passed": False}))
        self.assertTrue(runtime_network_observation_gate("cloud", {"passed": False}))

    @staticmethod
    def project(root: Path) -> None:
        for directory in ("benchmarks", "core", "deal_rooms", "scripts", "tests", "web"):
            (root / directory).mkdir(parents=True)
            (root / directory / "source.txt").write_text(directory, encoding="utf-8")
        for name in ("server.py", "package.json", "package-lock.json"):
            (root / name).write_text(name, encoding="utf-8")

    def test_source_manifest_detects_same_size_implementation_change(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.project(root)
            saved = engineering_source_manifest(root)
            self.assertEqual(source_manifest_errors(saved, root), [])
            (root / "core" / "source.txt").write_text("CORE", encoding="utf-8")
            self.assertTrue(any(
                "differs from the current implementation" in error
                for error in source_manifest_errors(saved, root)
            ))

    def test_clean_directory_copies_every_top_level_manifest_input(self):
        self.assertTrue({"server.py", "package.json", "package-lock.json"}.issubset(COPY_FILES))
        self.assertIn("infra", COPY_DIRECTORIES)

    def test_current_report_validates_exact_saved_bytes_in_one_run(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / "current.json"
            output.write_text('{"stale": true}\n', encoding="utf-8")
            report = {
                "runtime": "local",
                "verification_phase": "complete_verification",
                "selected_runtime_verified": True,
                "current_local_engineering_evidence": {"passed": False, "stale": True},
            }
            validation = {
                "passed": True,
                "record": str(output),
                "errors": [],
            }
            with patch(
                "scripts.verify_product.validate_current_local_product_evidence",
                return_value=validation,
            ) as validate:
                finalized = finalize_report_output(
                    report, output, canonical_current_path=output,
                )

            saved = json.loads(output.read_text(encoding="utf-8"))
            saved_mode = output.stat().st_mode & 0o777
        self.assertEqual(validate.call_count, 2)
        self.assertEqual(saved, finalized)
        self.assertEqual(saved["current_local_engineering_evidence"], validation)
        self.assertTrue(saved["selected_runtime_verified"])
        self.assertEqual(saved_mode, 0o600)

    def test_failed_current_run_preserves_canonical_and_writes_attempt_record(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / "current.json"
            original = b'{"last_known_good": true}\n'
            output.write_bytes(original)
            failed = {
                "runtime": "local",
                "verification_phase": "complete_verification",
                "selected_runtime_verified": False,
                "component_tests": {"passed": False},
            }
            finalized = finalize_report_output(
                failed, output, canonical_current_path=output,
            )
            attempt = Path(folder) / "current-failed-attempt.json"
            saved_attempt = json.loads(attempt.read_text(encoding="utf-8"))

            self.assertEqual(output.read_bytes(), original)
            self.assertTrue(attempt.exists())
            self.assertEqual(attempt.stat().st_mode & 0o777, 0o600)
            self.assertEqual(saved_attempt, finalized)
            self.assertFalse(finalized["canonical_commit"]["committed"])

    def test_summary_rejects_stale_evidence_and_preserves_release_boundary(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.project(root)
            record = {
                "verification_kind": "evidence_based_product_check",
                "runtime": "local",
                "selected_runtime_verified": True,
                "component_tests": {
                    "passed": True,
                    "tests_skipped": 0,
                    "required_reality_tests_present": True,
                },
                "engineering_source_manifest": engineering_source_manifest(root),
                "benchmark": {
                    "benchmark_version": 3,
                    "total_cases": 4,
                    "passed_cases": 4,
                    "pass_rate": 1.0,
                    "mean_structured_check_coverage": 1.0,
                    "structured_check_measurement_state": "preregistered_rule_coverage_not_domain_accuracy",
                    "mean_source_attribution_coverage": 1.0,
                    "grounding_measurement_state": "filename_presence_only_not_semantic_grounding",
                    "dataset_sha256": "a" * 64,
                    "runtime_evidence": {
                        "provider_id": "local_bonsai",
                        "model": "27b@q1_0",
                        "protocol": "lmstudio_native_chat",
                    },
                },
                "first_pass_benchmark_contract": {"release_ready": False},
                "target_architecture_complete": False,
            }
            current = engineering_evidence_summary(record, root)
            self.assertTrue(current["verified"])
            self.assertTrue(current["evidence_verified"])
            self.assertTrue(current["benchmark_passed"])
            self.assertEqual(
                current["measurement_state"],
                "source_bound_synthetic_engineering_regression_passed",
            )
            self.assertFalse(current["accuracy_release_ready"])

            record["selected_runtime_verified"] = False
            record["benchmark"].update({
                "passed_cases": 3,
                "pass_rate": 0.75,
                "mean_structured_check_coverage": 0.8889,
                "mean_source_attribution_coverage": 0.75,
            })
            failed = engineering_evidence_summary(record, root)
            self.assertTrue(failed["evidence_verified"])
            self.assertFalse(failed["benchmark_passed"])
            self.assertEqual(
                failed["measurement_state"],
                "source_bound_synthetic_engineering_regression_failed",
            )

            (root / "web" / "source.txt").write_text("changed", encoding="utf-8")
            self.assertFalse(engineering_evidence_summary(record, root)["verified"])
            record["first_pass_benchmark_contract"]["release_ready"] = True
            self.assertFalse(engineering_evidence_summary(record, root)["verified"])

    def test_build_vs_buy_reports_valid_failed_regression_without_quality_claim(self):
        summary = {
            "verified": True,
            "evidence_verified": True,
            "benchmark_passed": False,
            "passed_cases": 3,
            "total_cases": 4,
        }
        with patch("server.engineering_evidence_summary", return_value=summary):
            data = VaultHTTPRequestHandler._get_build_vs_buy_data(None)
        layer = data["layer_1_compute"]
        self.assertIn("failed: 3/4 cases passed", layer["rationale"])
        self.assertIn("valid negative evidence", layer["rationale"])
        self.assertNotIn("deal-room quality", layer["rationale"].split("failed:")[0])

    def test_build_vs_buy_makes_no_claim_from_invalid_evidence(self):
        summary = {
            "verified": False,
            "evidence_verified": False,
            "benchmark_passed": None,
        }
        with patch("server.engineering_evidence_summary", return_value=summary):
            data = VaultHTTPRequestHandler._get_build_vs_buy_data(None)
        rationale = data["layer_1_compute"]["rationale"]
        self.assertIn("makes no Bonsai benchmark claim", rationale)
        self.assertNotIn("cases passed", rationale)


if __name__ == "__main__":
    unittest.main()
