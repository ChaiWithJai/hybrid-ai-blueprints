import copy
import hashlib
import json
import shutil
import tempfile
from concurrent.futures import ThreadPoolExecutor
import unittest
from pathlib import Path
from unittest.mock import patch

from core.sealed_test_control import open_sealed_test, sealed_test_preflight
from tests.governance_fixtures import write_signed_governance


ROOT = Path(__file__).resolve().parents[1]


def canonical_sha(value):
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def file_sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class SealedTestControlTests(unittest.TestCase):
    def fixture(self, folder):
        root = Path(folder)
        contract = root / "benchmarks" / "first_pass"
        contract.mkdir(parents=True)
        for name in (
            "benchmark_manifest.v2.json",
            "development_registry.v2.json",
            "candidate_case_registrations.v1.json",
            "case.schema.json",
            "sealed_test_manifest.schema.json",
            "sealed_test_control.schema.json",
            "rubric.v1.json",
            "benchmark_governance.v1.json",
        ):
            shutil.copy2(ROOT / "benchmarks" / "first_pass" / name, contract / name)

        manifest_path = contract / "benchmark_manifest.v2.json"
        manifest = json.loads(manifest_path.read_text())

        secret_cases = []
        descriptors = []
        families = list(manifest["target"]["task_families"])
        for index in range(40):
            deal_id = f"sealed-deal-{index // 4:02d}"
            source_snapshot_sha256 = hashlib.sha256(f"source-{index // 4}".encode()).hexdigest()
            task_family = families[index % len(families)]
            slices = ["multiple_documents"] if index % 2 else []
            case = {
                "id": f"sealed-{index:02d}",
                "version": "1",
                "deal_id": deal_id,
                "near_duplicate_family_id": None,
                "split": "sealed_test",
                "task_family": task_family,
                "question": f"External question {index}",
                "investment_screen": None,
                "answer_policy": "answer",
                "severity": "critical",
                "requested_components": ["answer"],
                "required_claims": [],
                "required_citations": [],
                "calculations": [],
                "acceptable_absence_terms": [],
                "forbidden_claims": [],
                "slices": slices,
                "source_snapshot_sha256": source_snapshot_sha256,
                "domain_review": {
                    "status": "approved",
                    "owner": "external-domain-owner",
                    "reviewed_at": "2026-08-15T12:00:00-04:00",
                },
            }
            secret_cases.append(case)
            descriptors.append({
                "case_id": case["id"],
                "case_version": "1",
                "deal_id": deal_id,
                "source_snapshot_sha256": source_snapshot_sha256,
                "task_family": task_family,
                "slices": slices,
                "near_duplicate_family_id": None,
                "secret_case_sha256": canonical_sha(case),
            })
        public = {
            "schema_version": 1,
            "benchmark_id": manifest["benchmark_id"],
            "benchmark_version": manifest["version"],
            "state": "registered_unopened",
            "cases": descriptors,
        }
        public_path = contract / "sealed_test_manifest.v1.json"
        public_path.write_text(json.dumps(public))

        evidence = root / "evidence"
        evidence.mkdir()
        calibration_path = evidence / "calibration.json"
        calibration_path.write_text("{}")
        frozen_path = evidence / "frozen.json"
        frozen_path.write_text(json.dumps({"runtime": "local", "selected_runtime_verified": True}))
        control = {
            "schema_version": 1,
            "benchmark_id": manifest["benchmark_id"],
            "benchmark_version": manifest["version"],
            "state": "authorized_unopened",
            "public_manifest": {"path": str(public_path.relative_to(root)), "sha256": file_sha(public_path)},
            "calibration_result": {"path": str(calibration_path.relative_to(root)), "sha256": file_sha(calibration_path)},
            "frozen_system_verification": {"path": str(frozen_path.relative_to(root)), "sha256": file_sha(frozen_path)},
            "audit_receipt_path": "evidence/sealed-contact.json",
        }
        control_path = contract / "sealed_test_control.v1.json"
        control_path.write_text(json.dumps(control))
        write_signed_governance(root)
        secret = {
            "benchmark_id": manifest["benchmark_id"],
            "benchmark_version": manifest["version"],
            "cases": secret_cases,
        }
        return root, control_path, public_path, json.dumps(secret).encode()

    def test_current_state_fails_before_secret_loader(self):
        calls = []
        result = open_sealed_test(ROOT, lambda: calls.append(True) or b"{}")
        self.assertFalse(result["ready_to_open"])
        self.assertFalse(result["secret_loader_invoked"])
        self.assertEqual(calls, [])
        self.assertTrue(any("not authorized" in item for item in result["errors"]))

    def test_valid_preflight_then_one_time_open(self):
        with tempfile.TemporaryDirectory() as folder:
            root, control_path, _, secret_bytes = self.fixture(folder)
            with patch("core.sealed_test_control.validate_contract", return_value={"structural_passed": True, "inventory": {}}), patch(
                "core.sealed_test_control.validate_saved_judge_calibration",
                return_value={"calibration_passed": True},
            ):
                preflight = sealed_test_preflight(root, control_path)
                self.assertTrue(preflight["ready_to_open"], preflight["errors"])
                calls = []
                opened = open_sealed_test(root, lambda: calls.append(True) or secret_bytes, control_path)
                self.assertTrue(opened["secret_loader_invoked"])
                self.assertTrue(opened["secret_bundle_valid"], opened["errors"])
                self.assertEqual(calls, [True])

                second_calls = []
                second = open_sealed_test(root, lambda: second_calls.append(True) or secret_bytes, control_path)
                self.assertFalse(second["secret_loader_invoked"])
                self.assertEqual(second_calls, [])
                self.assertTrue(any("already has a contact receipt" in item for item in second["errors"]))

    def test_public_manifest_rejects_secret_fields_before_read(self):
        with tempfile.TemporaryDirectory() as folder:
            root, control_path, public_path, _ = self.fixture(folder)
            public = json.loads(public_path.read_text())
            public["cases"][0]["question"] = "This must stay external"
            public_path.write_text(json.dumps(public))
            control = json.loads(control_path.read_text())
            control["public_manifest"]["sha256"] = file_sha(public_path)
            control_path.write_text(json.dumps(control))
            calls = []
            with patch("core.sealed_test_control.validate_contract", return_value={"structural_passed": True, "inventory": {}}), patch(
                "core.sealed_test_control.validate_saved_judge_calibration",
                return_value={"calibration_passed": True},
            ):
                result = open_sealed_test(root, lambda: calls.append(True) or b"{}", control_path)
            self.assertEqual(calls, [])
            self.assertTrue(any("forbidden secret field question" in item for item in result["errors"]))

    def test_bad_public_hash_fails_before_read(self):
        with tempfile.TemporaryDirectory() as folder:
            root, control_path, _, _ = self.fixture(folder)
            control = json.loads(control_path.read_text())
            control["public_manifest"]["sha256"] = "0" * 64
            control_path.write_text(json.dumps(control))
            calls = []
            result = open_sealed_test(root, lambda: calls.append(True) or b"{}", control_path)
            self.assertEqual(calls, [])
            self.assertTrue(any("public manifest hash differs" in item for item in result["errors"]))

    def test_secret_hash_mismatch_consumes_version_and_fails(self):
        with tempfile.TemporaryDirectory() as folder:
            root, control_path, _, secret_bytes = self.fixture(folder)
            secret = json.loads(secret_bytes)
            secret["cases"][0]["question"] = "tampered after registration"
            with patch("core.sealed_test_control.validate_contract", return_value={"structural_passed": True, "inventory": {}}), patch(
                "core.sealed_test_control.validate_saved_judge_calibration",
                return_value={"calibration_passed": True},
            ):
                result = open_sealed_test(root, lambda: json.dumps(secret).encode(), control_path)
            self.assertTrue(result["secret_loader_invoked"])
            self.assertFalse(result["secret_bundle_valid"])
            receipt = json.loads((root / "evidence" / "sealed-contact.json").read_text())
            self.assertEqual(receipt["state"], "contacted_invalid_version_consumed")
            self.assertTrue(any("secret case hash differs" in item for item in receipt["validation_errors"]))

    def test_concurrent_contact_invokes_only_one_loader(self):
        with tempfile.TemporaryDirectory() as folder:
            root, control_path, _, secret_bytes = self.fixture(folder)
            calls = []
            with patch("core.sealed_test_control.validate_contract", return_value={"structural_passed": True, "inventory": {}}), patch(
                "core.sealed_test_control.validate_saved_judge_calibration",
                return_value={"calibration_passed": True},
            ):
                with ThreadPoolExecutor(max_workers=2) as pool:
                    futures = [
                        pool.submit(
                            open_sealed_test,
                            root,
                            lambda: calls.append(True) or secret_bytes,
                            control_path,
                        )
                        for _ in range(2)
                    ]
                    results = [future.result() for future in futures]
            self.assertEqual(calls, [True])
            self.assertEqual(sum(item.get("secret_bundle_valid") is True for item in results), 1)
            self.assertEqual(sum(item.get("secret_loader_invoked") is False for item in results), 1)


if __name__ == "__main__":
    unittest.main()
