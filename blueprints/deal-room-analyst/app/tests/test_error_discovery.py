from __future__ import annotations

import unittest

from core.error_discovery import (
    changed_records,
    observability_snapshot,
    session_summary,
    validate_annotations,
    validate_patterns,
    validate_suggestions,
)


class ErrorDiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.samples = [
            {"id": f"r{index}", "stratum": "question" if index % 2 else "answer", "content": f"trace {index}"}
            for index in range(6)
        ]

    def test_annotations_are_server_timestamped_and_reviewer_identity_is_bounded(self):
        result = validate_annotations(
            {"r0": {"label": "fail", "note": "Wrong citation", "reviewer": "Babak"}},
            {sample["id"] for sample in self.samples},
        )
        self.assertEqual(result["r0"]["label"], "fail")
        self.assertEqual(result["r0"]["reviewer"], "Babak")
        self.assertEqual(result["r0"]["reviewer_identity_state"], "self_asserted_local_not_authenticated")
        self.assertIn("created_at", result["r0"])

    def test_unknown_samples_and_nonbinary_labels_fail_closed(self):
        with self.assertRaises(ValueError):
            validate_annotations({"missing": {"label": "pass"}}, {"r0"})
        with self.assertRaises(ValueError):
            validate_annotations({"r0": {"label": "mostly_good"}}, {"r0"})

    def test_agent_suggestions_remain_explicitly_non_ground_truth(self):
        result = validate_suggestions([{
            "id": "s1",
            "record_id": "r0",
            "mode": "citation_gap",
            "reason": "The answer has no exact source.",
            "state": "pending",
        }], {"r0"})
        self.assertEqual(result[0]["source"], "agent_suggestion_not_ground_truth")

    def test_patterns_require_agent_explanation(self):
        with self.assertRaises(ValueError):
            validate_patterns([{"name": "citation_gap"}])
        result = validate_patterns([{
            "name": "citation_gap",
            "description": "A requested claim has no exact citation.",
        }])
        self.assertEqual(result[0]["source"], "agent_organized_from_human_notes")

    def test_five_reviews_unlock_depth_without_claiming_saturation(self):
        annotations = {
            f"r{index}": {
                "label": "fail" if index == 0 else "pass",
                "confirmed_modes": ["citation_gap"] if index == 0 else [],
            }
            for index in range(5)
        }
        summary = session_summary(self.samples, self.samples, annotations, [], [])
        self.assertEqual(summary["phase"], "depth")
        self.assertTrue(summary["depth_scan_ready"])
        self.assertFalse(summary["saturation"]["claimed"])
        self.assertTrue(summary["rereview_recommended"])

    def test_observability_is_hash_only_by_default(self):
        annotations = {
            "r0": {
                "label": "fail",
                "note": "Sensitive reviewer note",
                "reviewer_identity_state": "self_asserted_local_not_authenticated",
                "confirmed_modes": ["citation_gap"],
                "created_at": "2026-08-17T00:00:00+00:00",
                "updated_at": "2026-08-17T00:01:00+00:00",
            }
        }
        summary = session_summary(self.samples, self.samples, annotations, [], [])
        snapshot = observability_snapshot(self.samples, annotations, summary)
        attributes = snapshot["records"][0]["attributes"]
        self.assertEqual(attributes["openinference.span.kind"], "EVALUATOR")
        self.assertNotIn("input.value", attributes)
        self.assertNotIn("output.value", attributes)
        self.assertEqual(snapshot["content_policy"], "hashes_only")

    def test_revision_diff_keeps_hashes_not_just_mutable_state(self):
        changes = changed_records(
            {"r0": {"label": "pass"}},
            {"r0": {"label": "fail"}},
        )
        self.assertEqual(len(changes), 1)
        self.assertNotEqual(changes[0]["previous_sha256"], changes[0]["current_sha256"])


if __name__ == "__main__":
    unittest.main()
