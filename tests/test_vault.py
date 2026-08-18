"""
Component tests for the Prism Vault local prototype.
Tests:
1. Research-catalog boundaries.
2. Current Deal Room parsing and coordinate preservation without claiming Docling.
3. AST Python Sandbox static auditing & isolated execution.
4. Hybrid AI Policy Router with local-only policy & PII sanitization.
5. Deal Room Analyzer with automated covenant checks & Arize evaluations.
6. Deterministic workflow selection and sandbox verification.
"""

import unittest
from core.doc_parser import DealRoomParser, ParsedTable, TableCell
from core.sandbox import SubprocessSandbox
from core.hybrid_router import HybridAIRouter
from core.arize_evals import ArizeEvaluationEngine, ArizeObservabilityTracer
from core.deal_room_analyzer import DealRoomAnalyzer
from core.coding_agent import DealRoomWorkflowAgent
from server import BONSAI_MODELS


class TestPrismVaultPlatform(unittest.TestCase):

    def test_research_model_catalog_omits_unmeasured_performance(self):
        prohibited = {
            "vram_weights_gb", "peak_vram_120k_gb", "bfcl_v3_score",
            "mmlu_score", "energy_mwh_per_tok",
        }
        for model in BONSAI_MODELS.values():
            self.assertTrue(prohibited.isdisjoint(model))
            self.assertEqual(model["measurement_state"], "unverified")
            self.assertEqual(model["status"], "catalog_only_not_runtime_discovery")
            self.assertIsNone(model["artifact_available"])
            self.assertIsNone(model["runtime_loaded"])

    def test_deal_room_parsing(self):
        parser = DealRoomParser()
        docs = parser.parse_deal_room_folder("deal_rooms/sample_ma_acquisition")
        self.assertEqual(len(docs), 4)

        csv_doc = next(d for d in docs if d.file_type == 'csv')
        self.assertEqual(len(csv_doc.extracted_tables), 1)
        tbl = csv_doc.extracted_tables[0]
        self.assertEqual(tbl.num_rows, 8)
        self.assertEqual(tbl.num_cols, 16)

    def test_sandbox_security_auditor(self):
        sandbox = SubprocessSandbox()
        
        # Test banned import rejection
        bad_code = "import os\nos.system('ls')"
        success, out, _ = sandbox.execute_script(bad_code)
        self.assertFalse(success)
        self.assertIn("Security Violation", out)

        # Test safe execution
        good_code = "a = 43.0\nb = 147.0\nleverage = b / a\nprint(f'Leverage: {leverage:.2f}')"
        success, out, locs = sandbox.execute_script(good_code)
        self.assertTrue(success)
        self.assertIn("isolation", locs)
        self.assertIn("Leverage: 3.42", out)

    def test_hybrid_router_local_only_policy(self):
        router = HybridAIRouter(default_local_only_policy=True)
        decision = router.evaluate_routing("Check NovaTech EBITDA and debt covenants", deal_room_active=True)
        self.assertEqual(decision.target_tier, "LOCAL_DETERMINISTIC_WORKFLOW")
        self.assertTrue(decision.is_local_only_policy)
        self.assertIsNone(decision.estimated_cost_usd)
        self.assertIsNone(decision.estimated_energy_mwh_per_token)
        self.assertFalse(decision.metadata["provider_configured"])
        self.assertIsNone(decision.metadata["model_loaded"])

    def test_deal_room_audit_and_arize_evals(self):
        analyzer = DealRoomAnalyzer("deal_rooms/sample_ma_acquisition")
        report = analyzer.run_full_audit()
        self.assertEqual(report.total_documents_analyzed, 4)
        self.assertGreater(len(report.covenant_findings), 0)
        self.assertEqual(report.evaluation_summary["faithfulness"], 0.0)
        self.assertFalse(report.evaluation_summary["all_evals_passed"])
        self.assertEqual(report.evaluation_summary["forbidden_string_check"], 1.0)
        self.assertEqual(report.evaluation_summary["tabular_fixture_cell_match"], 0.0)
        self.assertEqual(report.evaluation_summary["typed_field_schema_check"], 1.0)

    def test_missing_evaluation_evidence_never_scores_as_perfect(self):
        faith = ArizeEvaluationEngine.evaluate_faithfulness("answer", [], [])
        table = ArizeEvaluationEngine.evaluate_tabular_cell_fidelity([], 0, 0)
        schema = ArizeEvaluationEngine.evaluate_schema_compliance(None, ["result"])
        for metric in (faith, table, schema):
            self.assertEqual(metric.score, 0.0)
            self.assertFalse(metric.passed)
            self.assertIn(metric.metadata["measurement_state"], {
                "unverified", "not_applicable",
            })

    def test_lexical_claim_check_cannot_pass_without_source_support(self):
        claim = "Purchase price is $125 million."
        absent = ArizeEvaluationEngine.evaluate_faithfulness(
            claim,
            [{"content": "The target generated $87 million of revenue."}],
            [claim],
        )
        self.assertEqual(absent.name, "lexical_claim_reproduction")
        self.assertFalse(absent.passed)
        self.assertEqual(absent.score, 0.0)
        self.assertEqual(absent.metadata["missing_from_source"], [claim])
        self.assertFalse(absent.metadata["semantic_faithfulness_measured"])

    def test_lexical_claim_pass_discloses_that_semantics_are_unmeasured(self):
        claim = "Purchase price is $125 million."
        exact = ArizeEvaluationEngine.evaluate_faithfulness(
            f"Summary: {claim}",
            [{"content": f"Transaction terms. {claim}"}],
            [claim],
        )
        self.assertTrue(exact.passed)
        self.assertEqual(exact.score, 1.0)
        self.assertEqual(exact.threshold, 1.0)
        self.assertEqual(
            exact.metadata["measurement_state"],
            "exact_lexical_check_not_semantic_faithfulness",
        )
        self.assertIn("does not measure semantic faithfulness", exact.explanation)

    def test_tabular_self_reported_counts_cannot_create_a_pass(self):
        result = ArizeEvaluationEngine.evaluate_tabular_cell_fidelity([], 500, 500)
        self.assertFalse(result.passed)
        self.assertEqual(result.score, 0.0)
        self.assertEqual(result.name, "tabular_fixture_cell_match")
        self.assertEqual(result.metadata["measurement_state"], "unverified")
        self.assertEqual(result.metadata["legacy_verified_cell_count_ignored"], 500)

    def test_tabular_fixture_match_inspects_coordinate_and_exact_text(self):
        table = ParsedTable(
            id="sheet-1",
            caption="Sources",
            num_rows=2,
            num_cols=2,
            cells=[
                TableCell(row=0, col=0, text="Debt"),
                TableCell(row=0, col=1, text="$125.0M"),
            ],
        )
        fixture = [
            {"table_index": 0, "row": 0, "col": 0, "expected_text": "Debt"},
            {"table_index": 0, "row": 0, "col": 1, "expected_text": "$125.0M"},
        ]
        result = ArizeEvaluationEngine.evaluate_tabular_cell_fidelity(
            [table], 999, 999, expected_cells=fixture,
        )
        self.assertTrue(result.passed)
        self.assertEqual(result.score, 1.0)
        self.assertFalse(result.metadata["general_extraction_accuracy_measured"])
        self.assertIn("does not measure general extraction accuracy", result.explanation)

        wrong = [dict(fixture[0]), dict(fixture[1], expected_text="$999.0M")]
        rejected = ArizeEvaluationEngine.evaluate_tabular_cell_fidelity(
            [table], 2, 2, expected_cells=wrong,
        )
        self.assertFalse(rejected.passed)
        self.assertEqual(rejected.score, 0.5)
        self.assertEqual(rejected.metadata["mismatches"][0]["observed_texts"], ["$125.0M"])

    def test_forbidden_string_check_is_not_labeled_hallucination_detection(self):
        result = ArizeEvaluationEngine.evaluate_forbidden_strings(
            "The response mentions invented clause 99.", ["clause 99"],
        )
        self.assertFalse(result.passed)
        self.assertEqual(result.score, 0.0)
        self.assertFalse(result.metadata["hallucination_detection_measured"])
        self.assertEqual(result.metadata["matched_forbidden_strings"], ["clause 99"])
        self.assertNotIn("detected_hallucinations", result.metadata)

    def test_field_presence_does_not_claim_type_or_schema_validation(self):
        result = ArizeEvaluationEngine.evaluate_schema_compliance(
            {"findings_count": "not an integer"}, ["findings_count"],
        )
        self.assertTrue(result.passed)
        self.assertEqual(result.name, "required_field_presence")
        self.assertFalse(result.metadata["types_validated"])
        self.assertFalse(result.metadata["full_json_schema_validated"])
        self.assertIn("were not checked", result.explanation)

    def test_typed_field_schema_rejects_wrong_type_and_empty_schema(self):
        wrong = ArizeEvaluationEngine.evaluate_schema_compliance(
            {"findings_count": "12"}, {"findings_count": "integer"},
        )
        self.assertFalse(wrong.passed)
        self.assertEqual(wrong.name, "typed_field_schema_check")
        self.assertEqual(wrong.metadata["type_mismatches"][0]["observed_type"], "str")

        correct = ArizeEvaluationEngine.evaluate_schema_compliance(
            {"findings_count": 12, "reviewed": False},
            {"findings_count": "integer", "reviewed": "boolean"},
        )
        self.assertTrue(correct.passed)
        self.assertFalse(correct.metadata["full_json_schema_validated"])

        empty = ArizeEvaluationEngine.evaluate_schema_compliance({}, {})
        self.assertFalse(empty.passed)
        self.assertEqual(empty.metadata["measurement_state"], "unverified")

    def test_deal_room_workflow_agent(self):
        agent = DealRoomWorkflowAgent("deal_rooms/sample_ma_acquisition")
        res = agent.execute_task("Run sensitivity stress-test modeling 10% EBITDA drop")
        self.assertEqual(len(res.steps), 4)
        self.assertIn("SENSITIVITY ANALYSIS RESULTS", res.code_execution_stdout)
        self.assertEqual(res.routing_info.target_tier, "LOCAL_DETERMINISTIC_WORKFLOW")
        self.assertEqual(res.execution_mode, "deterministic_template")
        self.assertIsNone(res.model_name)

    def test_lbo_ai_guidance_does_not_turn_schedule_mismatch_into_legal_breach(self):
        guidance = DealRoomWorkflowAgent._task_method_guidance(
            "Run the LBO debt schedule and annual ECF sweep prepayments."
        )
        self.assertIn("MODEL_POLICY_MISMATCH", guidance)
        self.assertIn("Do not call that difference a covenant breach", guidance)

    def test_accretion_ai_guidance_excludes_unrelated_regulatory_conclusions(self):
        guidance = DealRoomWorkflowAgent._task_method_guidance(
            "Calculate transaction accretion and pro-forma EPS synergies."
        )
        self.assertIn("Do not compute or report regulatory", guidance)
        self.assertIn("CFIUS", guidance)
        self.assertIn("antitrust", guidance)

    def test_accretion_generated_script_scope_rejects_unrelated_findings(self):
        violations = DealRoomWorkflowAgent._generated_script_scope_violations(
            "Calculate transaction accretion and pro-forma EPS synergies.",
            "print('EPS: 3.31')\nprint('CFIUS clearance: pending')\nprint('Leverage Check')",
        )
        self.assertEqual(violations, ["cfius", "clearance", "leverage check"])

        self.assertEqual(
            DealRoomWorkflowAgent._generated_script_scope_violations(
                "Calculate transaction accretion and pro-forma EPS synergies.",
                "print('Cost Synergies ($/share): 0.3352')",
            ),
            ["synergies ($/share)"],
        )

    def test_accretion_generated_script_scope_accepts_bounded_calculation(self):
        violations = DealRoomWorkflowAgent._generated_script_scope_violations(
            "Calculate transaction accretion and pro-forma EPS synergies.",
            "print('AEROFLUX EPS: 3.31; accretion: 18.8%; cost synergy: 42.5')",
        )
        self.assertEqual(violations, [])

    def test_qoe_generated_script_scope_rejects_invented_policy(self):
        violations = DealRoomWorkflowAgent._generated_script_scope_violations(
            "Build the carve-out QoE and standalone EBITDA bridge.",
            "print('Benchmark Multiple: 5.0x')\nprint('policy threshold exceeded')",
        )
        self.assertEqual(violations, ["benchmark multiple", "policy threshold"])


if __name__ == "__main__":
    unittest.main()
