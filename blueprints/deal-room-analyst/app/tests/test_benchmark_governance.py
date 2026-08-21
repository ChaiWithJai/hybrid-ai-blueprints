import copy
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from core.benchmark_governance import (
    GOVERNANCE_ROLES,
    GOVERNANCE_SCOPES,
    record_benchmark_governance_approval,
    scope_approved,
    validate_benchmark_governance,
)
from tests.governance_fixtures import signed_governance, write_signed_governance


ROOT = Path(__file__).resolve().parents[1]


class BenchmarkGovernanceTests(unittest.TestCase):
    def fixture(self, folder: str) -> Path:
        root = Path(folder)
        (root / "benchmarks").mkdir()
        shutil.copytree(ROOT / "benchmarks/first_pass", root / "benchmarks/first_pass")
        return root

    def test_checked_in_governance_is_honestly_unconfigured(self):
        report = validate_benchmark_governance(ROOT)
        self.assertTrue(report["valid"], report["errors"])
        self.assertFalse(report["configured"])
        self.assertFalse(scope_approved(report, "benchmark_contract"))
        self.assertEqual(report["receipt_count"], 0)

    def test_all_roles_must_sign_each_exact_material_scope(self):
        with tempfile.TemporaryDirectory() as folder:
            root = self.fixture(folder)
            write_signed_governance(root)
            report = validate_benchmark_governance(root)
            self.assertTrue(report["valid"], report["errors"])
            for scope in GOVERNANCE_SCOPES:
                self.assertTrue(scope_approved(report, scope))
                self.assertEqual(set(report["approvals"][scope]), set(GOVERNANCE_ROLES))

    def test_plain_manifest_approval_fields_have_no_authority(self):
        with tempfile.TemporaryDirectory() as folder:
            root = self.fixture(folder)
            manifest_path = root / "benchmarks/first_pass/benchmark_manifest.v2.json"
            manifest = json.loads(manifest_path.read_text())
            manifest["approvals"] = {
                "product_owner": "any-name",
                "domain_owner": "any-name",
                "strategy_owner": "any-name",
                "security_owner": "any-name",
                "thresholds_approved": True,
                "sealed_test_open_authorized": True,
            }
            manifest_path.write_text(json.dumps(manifest))
            report = validate_benchmark_governance(root)
            self.assertTrue(report["valid"], report["errors"])
            self.assertFalse(scope_approved(report, "benchmark_contract"))
            self.assertFalse(scope_approved(report, "release_thresholds"))
            self.assertFalse(scope_approved(report, "sealed_test_open"))

    def test_signed_receipts_fail_after_benchmark_material_changes(self):
        with tempfile.TemporaryDirectory() as folder:
            root = self.fixture(folder)
            write_signed_governance(root)
            rubric_path = root / "benchmarks/first_pass/rubric.v1.json"
            rubric = json.loads(rubric_path.read_text())
            rubric["tampered_threshold"] = 0.01
            rubric_path.write_text(json.dumps(rubric))
            report = validate_benchmark_governance(root)
            self.assertFalse(report["valid"])
            self.assertTrue(any("material hash differs" in item for item in report["errors"]))
            self.assertFalse(scope_approved(report, "release_thresholds"))

    def test_authority_assignment_edit_breaks_root_signature(self):
        with tempfile.TemporaryDirectory() as folder:
            root = self.fixture(folder)
            ledger = signed_governance(root)
            ledger["authority"]["role_assignments"][0]["actor_id"] = "substitute-owner"
            report = validate_benchmark_governance(root, ledger)
            self.assertFalse(report["valid"])
            self.assertTrue(any("authority event: Buzz event content differs" in item for item in report["errors"]))

    def test_role_labels_cannot_reuse_one_actor_or_signing_key(self):
        with tempfile.TemporaryDirectory() as folder:
            root = self.fixture(folder)
            ledger = signed_governance(root)
            first, second = ledger["authority"]["role_assignments"][:2]
            second["actor_id"] = first["actor_id"]
            second["buzz_pubkey"] = first["buzz_pubkey"]
            report = validate_benchmark_governance(root, ledger)
            self.assertFalse(report["valid"])
            self.assertIn("governance roles must have distinct actor IDs", report["errors"])
            self.assertIn("governance roles must have distinct Buzz keys", report["errors"])

    def test_event_replay_and_cross_role_substitution_fail(self):
        with tempfile.TemporaryDirectory() as folder:
            root = self.fixture(folder)
            ledger = signed_governance(root)
            ledger["receipts"][1]["approval_event"] = copy.deepcopy(
                ledger["receipts"][0]["approval_event"]
            )
            report = validate_benchmark_governance(root, ledger)
            self.assertFalse(report["valid"])
            self.assertTrue(any("replayed" in item for item in report["errors"]))
            self.assertTrue(any("signer differs" in item for item in report["errors"]))

    def test_atomic_recorder_rejects_duplicate_scope_and_role(self):
        with tempfile.TemporaryDirectory() as folder:
            root = self.fixture(folder)
            ledger = signed_governance(root)
            first = ledger["receipts"][0]
            ledger["receipts"] = []
            (root / "benchmarks/first_pass/benchmark_governance.v1.json").write_text(
                json.dumps(ledger)
            )
            record_benchmark_governance_approval(root, first)
            with self.assertRaisesRegex(ValueError, "already has a receipt"):
                record_benchmark_governance_approval(root, first)


if __name__ == "__main__":
    unittest.main()
