import unittest
from pathlib import Path

from core.evaluation_dashboard import build_evaluation_dashboard


ROOT = Path(__file__).resolve().parent.parent


class EvaluationDashboardTests(unittest.TestCase):
    def snapshot(self, reviewed=0, criterion_reviewed=0):
        annotations = {
            f"trace-{index}": {
                "label": "pass" if index % 2 else "fail",
                **({
                    "criterion_labels": {
                        "material_claim_support": "pass" if index % 2 else "fail",
                    },
                } if index < criterion_reviewed else {}),
            }
            for index in range(reviewed)
        }
        return {
            "canonical_path": "/rooms/project_titan_lbo/evaluation",
            "annotations": annotations,
            "session": {
                "corpus_count": 38,
                "sample_count": 10,
                "reviewed_count": reviewed,
                "phase": "depth" if reviewed >= 5 else "breadth",
                "saturation": {"claimed": False},
            },
        }

    def test_missing_routes_and_business_evidence_are_not_zero_scores(self):
        result = build_evaluation_dashboard(
            ROOT,
            room="project_titan_lbo",
            review_snapshot=self.snapshot(),
            provider_statuses=[{"kind": "local", "configured": True, "model": "27b@q1_0"}],
        )
        routes = {item["mode"]: item for item in result["route_experiments"]}
        self.assertEqual(routes["cloud"]["state"], "not_measured")
        self.assertEqual(routes["hybrid"]["state"], "not_measured")
        self.assertTrue(all(item["state"] == "not_measured" for item in result["business_measures"]))
        self.assertIsNone(result["decision"]["next_investment"])

    def test_unvalidated_bonsai_judges_cannot_control_release(self):
        result = build_evaluation_dashboard(
            ROOT,
            room="project_titan_lbo",
            review_snapshot=self.snapshot(reviewed=10),
            provider_statuses=[{"kind": "local", "configured": True, "model": "27b@q1_0"}],
        )
        judges = [item for item in result["evaluators"] if item["kind"] == "llm_judge"]
        self.assertTrue(judges)
        self.assertTrue(all(item["trusted_for_release"] is False for item in judges))
        self.assertEqual(result["judge_validation"]["calibration_state"], "not_started")
        self.assertFalse(result["readiness"]["accuracy_release"])

    def test_label_target_changes_readiness_without_claiming_calibration(self):
        result = build_evaluation_dashboard(
            ROOT,
            room="project_titan_lbo",
            review_snapshot=self.snapshot(reviewed=100, criterion_reviewed=100),
            provider_statuses=[],
        )
        gate = next(item for item in result["release_gates"] if item["id"] == "judge_validation")
        self.assertEqual(gate["state"], "ready_for_calibration")
        self.assertFalse(result["judge_validation"]["trusted_for_release"])

    def test_general_trace_labels_do_not_count_as_judge_calibration(self):
        result = build_evaluation_dashboard(
            ROOT,
            room="project_titan_lbo",
            review_snapshot=self.snapshot(reviewed=100),
            provider_statuses=[],
        )
        gate = next(item for item in result["release_gates"] if item["id"] == "judge_validation")
        self.assertEqual(gate["state"], "blocked")
        self.assertEqual(result["judge_validation"]["labels_available"], 0)

    def test_framework_has_no_composite_score(self):
        result = build_evaluation_dashboard(
            ROOT,
            room="project_titan_lbo",
            review_snapshot=self.snapshot(),
            provider_statuses=[],
        )
        self.assertFalse(result["aggregation_policy"]["single_composite_score"])
        self.assertFalse(result["aggregation_policy"]["hard_failure_can_be_averaged_away"])


if __name__ == "__main__":
    unittest.main()
