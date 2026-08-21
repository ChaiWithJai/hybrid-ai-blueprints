import unittest

from core.goal_completion import evaluate_goal_completion


class GoalCompletionGuardTests(unittest.TestCase):
    @staticmethod
    def milestones(passed=True):
        return {
            "M6g_measured_local_deployment": {"passed": passed},
            "M6h_live_inference_responsiveness": {"passed": passed},
            "M6i_titan_debt_chat_surface": {"passed": passed},
            "M4a_operator_review_durability": {"passed": passed},
            "M6l_customer_demo_scope": {"passed": passed},
            "M6m_customer_demo_surface": {"passed": passed},
            "M6n_job_content_graph": {"passed": passed},
        }

    def test_current_demo_milestones_complete_goal(self):
        result = evaluate_goal_completion(
            milestones=self.milestones(),
            benchmark_contract={"release_ready": False},
            pricing_evidence={"evidence_state": "not_recorded"},
        )
        self.assertTrue(result["passed"])
        self.assertEqual(result["decision"], "complete")
        self.assertEqual(result["missing_gates"], [])

    def test_missing_scope_fails_closed(self):
        milestones = self.milestones()
        milestones["M6l_customer_demo_scope"]["passed"] = False
        result = evaluate_goal_completion(milestones=milestones)
        self.assertFalse(result["passed"])
        self.assertIn("demo_scope_propagated", result["missing_gates"])
        self.assertIn("ideal_page_structure_documented", result["missing_gates"])

    def test_missing_fresh_browser_record_fails_closed(self):
        milestones = self.milestones()
        milestones["M6m_customer_demo_surface"]["passed"] = False
        result = evaluate_goal_completion(milestones=milestones)
        self.assertFalse(result["passed"])
        self.assertIn("understandable_customer_surface", result["missing_gates"])
        self.assertIn("fresh_demo_evidence", result["missing_gates"])
        self.assertIn("job_and_copy_alignment", result["missing_gates"])

    def test_missing_content_graph_fails_closed(self):
        milestones = self.milestones()
        milestones["M6n_job_content_graph"]["passed"] = False
        result = evaluate_goal_completion(milestones=milestones)
        self.assertFalse(result["passed"])
        self.assertIn("job_and_copy_alignment", result["missing_gates"])

    def test_missing_local_runtime_fails_closed(self):
        milestones = self.milestones()
        del milestones["M6h_live_inference_responsiveness"]
        result = evaluate_goal_completion(milestones=milestones)
        self.assertFalse(result["gates"]["local_bonsai_deal_room"]["passed"])

    def test_missing_team_durability_fails_closed(self):
        milestones = self.milestones()
        milestones["M4a_operator_review_durability"]["passed"] = False
        result = evaluate_goal_completion(milestones=milestones)
        self.assertFalse(result["gates"]["source_and_team_critical_path"]["passed"])

    def test_accuracy_and_pricing_do_not_control_current_goal(self):
        failed_external = evaluate_goal_completion(
            milestones=self.milestones(),
            benchmark_contract={"release_ready": False},
            pricing_evidence={"evidence_state": "not_recorded"},
            trace_anchor_evidence={"externally_anchored": False},
            network_observation_evidence={"zero_egress_proved": False},
            ocr_accuracy_evidence={"passed": False},
        )
        passing_external = evaluate_goal_completion(
            milestones=self.milestones(),
            benchmark_contract={"release_ready": True},
            pricing_evidence={"evidence_state": "verified"},
            trace_anchor_evidence={"externally_anchored": True},
            network_observation_evidence={"zero_egress_proved": True},
            ocr_accuracy_evidence={"passed": True},
        )
        self.assertTrue(failed_external["passed"])
        self.assertEqual(failed_external, passing_external)
        self.assertEqual(
            failed_external["excluded_programs"]["accuracy_certification"],
            "outside_current_goal",
        )
        self.assertEqual(
            failed_external["excluded_programs"]["commercial_proof"],
            "outside_current_goal",
        )


if __name__ == "__main__":
    unittest.main()
