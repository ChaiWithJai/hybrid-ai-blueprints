import copy
from pathlib import Path
import unittest

from core.absence_oracle import audit_whole_corpus_absence, load_absence_contract


class AbsenceOracleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = Path(__file__).resolve().parents[1]
        cls.contract, _ = load_absence_contract(cls.root)

    def test_current_citrix_whole_corpus_audit_passes_narrow_contract(self):
        result = audit_whole_corpus_absence(self.root, self.contract)
        self.assertTrue(result["passed"], result["errors"])
        self.assertEqual(result["scope"], "complete_registered_deal_folder")
        self.assertEqual(result["source_file_count"], 2)
        self.assertEqual(result["parsed_node_count"], 2401)
        self.assertEqual(result["registered_pattern_count"], 3)
        self.assertEqual(result["registered_direct_disclosure_hits"], [])
        self.assertEqual(len(result["required_confusable_evidence"]), 3)
        self.assertEqual(result["semantic_accuracy_state"], "unverified")
        self.assertEqual(result["domain_review_status"], "not_reviewed")

    def test_direct_disclosure_pattern_injection_fails(self):
        contract = copy.deepcopy(self.contract)
        contract["registered_direct_disclosure_patterns"].append({
            "id": "negative_control_known_valuation_text",
            "regex": r"(?i)CY2022E EBITDA Multiple for Citrix was 13\.0x",
        })
        result = audit_whole_corpus_absence(self.root, contract)
        self.assertFalse(result["passed"])
        self.assertTrue(result["registered_direct_disclosure_hits"])
        self.assertIn(
            "registered direct disclosure pattern matched the corpus", result["errors"]
        )

    def test_missing_registered_source_and_hash_drift_fail_closed(self):
        missing = copy.deepcopy(self.contract)
        missing["sources"] = missing["sources"][:1]
        result = audit_whole_corpus_absence(self.root, missing)
        self.assertFalse(result["passed"])
        self.assertIn("does not equal the registered file set", result["errors"][0])

        drifted = copy.deepcopy(self.contract)
        drifted["sources"][0]["sha256"] = "0" * 64
        result = audit_whole_corpus_absence(self.root, drifted)
        self.assertFalse(result["passed"])
        self.assertIn("source identity differs", result["errors"][0])


if __name__ == "__main__":
    unittest.main()
