import unittest

from scripts.export_eval_review_to_phoenix import build_receipt


class PhoenixEvalExportTests(unittest.TestCase):
    def test_fixture_receipt_never_claims_human_review(self):
        receipt = build_receipt(
            {"content_policy": "hashes_only", "records": [{"record_id": "fixture-1"}]},
            endpoint="http://127.0.0.1:6006/v1/traces",
            project="prism-error-discovery-smoke",
            fixture=True,
        )

        self.assertEqual(receipt["review_record_count"], 1)
        self.assertEqual(receipt["record_provenance"], "synthetic_fixture")
        self.assertTrue(receipt["synthetic_fixture"])
        self.assertFalse(receipt["reviewer_identity_verified"])
        self.assertFalse(receipt["human_review_performed_claimed"])
        self.assertNotIn("human_label_claimed", receipt)

    def test_local_ledger_receipt_still_bounds_reviewer_identity(self):
        receipt = build_receipt(
            {"content_policy": "hashes_only", "records": []},
            endpoint="http://127.0.0.1:6006/v1/traces",
            project="prism-error-discovery",
            fixture=False,
        )

        self.assertEqual(
            receipt["record_provenance"],
            "local_review_ledger_self_asserted_reviewer",
        )
        self.assertFalse(receipt["reviewer_identity_verified"])
        self.assertFalse(receipt["human_review_performed_claimed"])


if __name__ == "__main__":
    unittest.main()
