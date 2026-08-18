import json
import shutil
import tempfile
import unittest
from pathlib import Path

from core.first_pass_benchmark import (
    calculation_contract_errors,
    evaluate_case_response,
    evaluate_development_responses,
    schema_definition_errors,
    schema_errors,
    validate_contract,
    validate_signed_delivery_evidence,
)


ROOT = Path(__file__).resolve().parents[1]


class FirstPassBenchmarkGuardTests(unittest.TestCase):
    @staticmethod
    def calculation_case() -> dict:
        return {
            "id": "revenue_growth",
            "version": "1.0.0",
            "severity": "major",
            "required_claims": [
                {
                    "id": "revenue_old_claim",
                    "text": "Revenue was $100.0 million in 2024.",
                    "citation_ids": [],
                },
                {
                    "id": "revenue_new_claim",
                    "text": "Revenue was $120.0 million in 2025.",
                    "citation_ids": [],
                },
            ],
            "required_citations": [],
            "calculations": [{
                "id": "revenue_growth_pct",
                "formula": "(revenue_new / revenue_old - 1) * 100",
                "expected_value": 20.0,
                "unit": "percent",
                "tolerance": 0.01,
                "input_claim_ids": ["revenue_old_claim", "revenue_new_claim"],
                "inputs": [
                    {
                        "name": "revenue_old",
                        "claim_id": "revenue_old_claim",
                        "value": 100.0,
                        "unit": "USD millions",
                    },
                    {
                        "name": "revenue_new",
                        "claim_id": "revenue_new_claim",
                        "value": 120.0,
                        "unit": "USD millions",
                    },
                ],
            }],
            "forbidden_claims": [],
            "acceptable_absence_terms": [],
            "answer_policy": "answer",
            "domain_review": {"status": "approved"},
        }

    def copied_contract(self, folder: str) -> Path:
        root = Path(folder)
        destination = root / "benchmarks" / "first_pass"
        destination.parent.mkdir(parents=True)
        shutil.copytree(ROOT / "benchmarks" / "first_pass", destination)
        shutil.copy2(
            ROOT / "benchmarks" / "public_deal_corpus_manifest.json",
            root / "benchmarks" / "public_deal_corpus_manifest.json",
        )
        (root / "evidence").mkdir()
        shutil.copy2(
            ROOT / "evidence" / "public-deal-corpus-verification-v2.json",
            root / "evidence" / "public-deal-corpus-verification-v2.json",
        )
        for evidence_path in (ROOT / "evidence").glob("candidate*-source-*.json"):
            shutil.copy2(evidence_path, root / "evidence" / evidence_path.name)
        return root

    def test_current_registry_is_structural_but_not_release_ready(self):
        report = validate_contract(ROOT)
        self.assertTrue(report["structural_passed"], report["structural_errors"])
        self.assertFalse(report["release_ready"])
        self.assertEqual(report["inventory"]["registered_cases"], 5)
        self.assertEqual(report["inventory"]["domain_approved_cases"], 0)
        self.assertIn("registered cases 5 of 120", report["release_failures"])
        self.assertIn("domain approved cases 0 of 5", report["release_failures"])

    def test_case_schema_rejects_missing_review_state(self):
        schema = json.loads(
            (ROOT / "benchmarks" / "first_pass" / "case.schema.json").read_text()
        )
        registry = json.loads(
            (ROOT / "benchmarks" / "first_pass" / "development_registry.v2.json").read_text()
        )
        case = dict(registry["cases"][0])
        case.pop("domain_review")
        errors = schema_errors(case, schema)
        self.assertTrue(any("missing required field domain_review" in item for item in errors))

    def test_case_schema_requires_source_bound_calculation_inputs(self):
        schema = json.loads(
            (ROOT / "benchmarks" / "first_pass" / "case.schema.json").read_text()
        )
        case = self.calculation_case()
        case["calculations"][0].pop("inputs")
        errors = schema_errors(case, schema)
        self.assertTrue(any("missing required field inputs" in item for item in errors))

    def test_checked_in_schemas_use_only_enforced_keywords(self):
        for path in sorted((ROOT / "benchmarks" / "first_pass").glob("*.schema.json")):
            with self.subTest(schema=path.name):
                schema = json.loads(path.read_text())
                self.assertEqual(schema_definition_errors(schema), [])

    def test_schema_validator_rejects_unsupported_assertion_keywords(self):
        errors = schema_errors([], {"type": "array", "maxItems": 1})
        self.assertIn("$schema: unsupported schema keyword maxItems", errors)

    def test_schema_validator_rejects_unsupported_keyword_forms(self):
        controls = (
            ({"type": "string", "format": "email"}, "unsupported format 'email'"),
            ({"type": "string", "maxLength": "10"}, "nonnegative integer"),
            ({"type": "mystery"}, "invalid type declaration"),
            ({"oneOf": []}, "nonempty schema array"),
            ({"$schema": "http://json-schema.org/draft-07/schema#"}, "unsupported JSON Schema dialect"),
        )
        for schema, expected in controls:
            with self.subTest(schema=schema):
                self.assertTrue(any(expected in item for item in schema_errors("x", schema)))

    def test_schema_validator_enforces_schema_valued_additional_properties(self):
        schema = {
            "type": "object",
            "properties": {"known": {"type": "string"}},
            "additionalProperties": {"type": "integer", "minimum": 1},
        }
        self.assertEqual(schema_errors({"known": "yes", "count": 2}, schema), [])
        errors = schema_errors({"known": "yes", "count": 0}, schema)
        self.assertTrue(any("$.count: number is below the minimum" in item for item in errors))

    def test_schema_validator_uses_json_schema_pattern_search_semantics(self):
        self.assertEqual(schema_errors("prefix-abc-suffix", {"pattern": "abc"}), [])
        self.assertTrue(schema_errors("prefix-suffix", {"pattern": "abc"}))

    def test_schema_validator_reports_unresolved_reference(self):
        schema = {"$defs": {}, "$ref": "#/$defs/missing"}
        self.assertIn("$: schema reference cannot be resolved", schema_errors("x", schema))

    def test_schema_validator_enforces_const_and_exclusive_bounds(self):
        self.assertTrue(schema_errors("changed", {"const": "fixed"}))
        self.assertTrue(schema_errors(0, {"type": "number", "exclusiveMinimum": 0}))
        self.assertTrue(schema_errors(10, {"type": "number", "exclusiveMaximum": 10}))
        self.assertEqual(schema_errors(1, {"const": 1, "exclusiveMinimum": 0}), [])

    def test_schema_validator_uses_json_value_equality(self):
        self.assertTrue(schema_errors(True, {"const": 1}))
        self.assertTrue(schema_errors(True, {"enum": [1]}))
        self.assertEqual(schema_errors(1.0, {"const": 1}), [])
        self.assertTrue(schema_errors([1, 1.0], {"type": "array", "uniqueItems": True}))
        self.assertEqual(
            schema_errors([True, 1], {"type": "array", "uniqueItems": True}),
            [],
        )

    def test_schema_validator_rejects_nonfinite_numbers(self):
        for value in (float("nan"), float("inf"), float("-inf")):
            with self.subTest(value=value):
                self.assertTrue(schema_errors(value, {"type": "number"}))
                self.assertTrue(schema_errors(value, {"type": "integer"}))
        self.assertEqual(schema_errors(1.0, {"type": "integer"}), [])

    def test_schema_validator_rejects_ambiguous_date_time(self):
        schema = {"type": "string", "format": "date-time"}
        self.assertTrue(schema_errors("2026-08-16T10:00:00", schema))
        self.assertEqual(schema_errors("2026-08-16T10:00:00-04:00", schema), [])

    def test_one_of_does_not_bypass_sibling_requirements(self):
        schema = {
            "type": "object",
            "required": ["required_sibling"],
            "properties": {"kind": {"type": "string"}},
            "oneOf": [
                {"properties": {"kind": {"const": "a"}}},
                {"properties": {"kind": {"const": "b"}}},
            ],
        }
        errors = schema_errors({"kind": "a"}, schema)
        self.assertTrue(any("missing required field required_sibling" in item for item in errors))

    def test_registered_calculation_contract_recomputes_expected_value(self):
        case = self.calculation_case()
        self.assertEqual(calculation_contract_errors(case), [])
        case["calculations"][0]["expected_value"] = 25.0
        self.assertTrue(any(
            "formula returns 20, not registered value 25" in item
            for item in calculation_contract_errors(case)
        ))

    def test_registered_calculation_input_must_exist_in_source_claim(self):
        case = self.calculation_case()
        case["calculations"][0]["inputs"][0]["value"] = 90.0
        errors = calculation_contract_errors(case)
        self.assertTrue(any(
            "input revenue_old value is absent from claim revenue_old_claim" in item
            for item in errors
        ))

    def test_calculation_response_requires_inputs_formula_result_and_unit(self):
        case = self.calculation_case()
        passed = evaluate_case_response(case, {
            "provider": "test",
            "model": "test",
            "response": (
                "Inputs: revenue_old = 100.0 USD millions and revenue_new = 120.0 USD "
                "millions. Formula: `(revenue_new / revenue_old - 1) * 100`. "
                "Result: 20.0 percent."
            ),
            "unauthorized_file_writes": [],
        })
        calculation = next(
            item for item in passed["evaluations"]
            if item["dimension"] == "calculation_reproducibility"
        )
        self.assertEqual(calculation["label"], "pass")

        failed = evaluate_case_response(case, {
            "provider": "test",
            "model": "test",
            "response": (
                "Inputs elsewhere: 100.0 and 120.0.\n\n"
                "Formula alone: `(revenue_new / revenue_old - 1) * 100`.\n\n"
                "Result elsewhere: 20.0 percent."
            ),
            "unauthorized_file_writes": [],
        })
        calculation = next(
            item for item in failed["evaluations"]
            if item["dimension"] == "calculation_reproducibility"
        )
        self.assertEqual(calculation["label"], "fail")
        self.assertTrue(failed["deterministic_hard_failure"])

    def test_source_hash_tamper_fails_structure(self):
        with tempfile.TemporaryDirectory() as folder:
            root = self.copied_contract(folder)
            registry_path = root / "benchmarks" / "first_pass" / "development_registry.v2.json"
            registry = json.loads(registry_path.read_text())
            registry["cases"][0]["required_citations"][0]["source_sha256"] = "0" * 64
            registry_path.write_text(json.dumps(registry))
            report = validate_contract(root)
        self.assertFalse(report["structural_passed"])
        self.assertTrue(any("citation source is absent" in item for item in report["structural_errors"]))

    def test_unverified_anchor_fails_structure(self):
        with tempfile.TemporaryDirectory() as folder:
            root = self.copied_contract(folder)
            evidence_path = root / "evidence" / "public-deal-corpus-verification-v2.json"
            evidence = json.loads(evidence_path.read_text())
            evidence["source_facts"]["cases"][0]["citation_checks"][0]["passed"] = False
            evidence_path.write_text(json.dumps(evidence))
            report = validate_contract(root)
        self.assertFalse(report["structural_passed"])
        self.assertTrue(any("required anchor lacks passing" in item for item in report["structural_errors"]))

    def test_source_evidence_schema_and_visual_review_state_fail_closed(self):
        variants = (
            (
                lambda evidence: evidence.update({"schema": "prism.public_deal_battletest.evidence.v1"}),
                "required v2 schema",
            ),
            (
                lambda evidence: evidence["automated_pdf_render_check"].update({"passed": False}),
                "passing automated PDF render check",
            ),
            (
                lambda evidence: evidence["pdf_visual_review"].update({
                    "state": "reviewed",
                    "passed": True,
                    "reviewer": "unverified-person",
                }),
                "claims or ambiguously records",
            ),
        )
        for mutate, expected_error in variants:
            with self.subTest(expected_error=expected_error), tempfile.TemporaryDirectory() as folder:
                root = self.copied_contract(folder)
                evidence_path = root / "evidence" / "public-deal-corpus-verification-v2.json"
                evidence = json.loads(evidence_path.read_text())
                mutate(evidence)
                evidence_path.write_text(json.dumps(evidence))
                report = validate_contract(root)
            self.assertFalse(report["structural_passed"])
            self.assertTrue(
                any(expected_error in item for item in report["structural_errors"]),
                report["structural_errors"],
            )

    def test_deal_split_leakage_fails_structure(self):
        with tempfile.TemporaryDirectory() as folder:
            root = self.copied_contract(folder)
            registry_path = root / "benchmarks" / "first_pass" / "development_registry.v2.json"
            registry = json.loads(registry_path.read_text())
            registry["cases"][0]["split"] = "calibration"
            registry_path.write_text(json.dumps(registry))
            report = validate_contract(root)
        self.assertFalse(report["structural_passed"])
        self.assertIn("anaplan_2022: one deal appears in multiple splits", report["structural_errors"])

    def test_near_duplicate_family_split_leakage_fails_structure(self):
        with tempfile.TemporaryDirectory() as folder:
            root = self.copied_contract(folder)
            registry_path = root / "benchmarks" / "first_pass" / "development_registry.v2.json"
            registry = json.loads(registry_path.read_text())
            registry["cases"][0]["near_duplicate_family_id"] = "shared-duplicate-family"
            registry["cases"][2]["near_duplicate_family_id"] = "shared-duplicate-family"
            registry["cases"][2]["split"] = "calibration"
            registry_path.write_text(json.dumps(registry))
            report = validate_contract(root)
        self.assertFalse(report["structural_passed"])
        self.assertIn(
            "shared-duplicate-family: one near-duplicate family appears in multiple splits",
            report["structural_errors"],
        )

    def test_false_domain_approval_fails_structure(self):
        with tempfile.TemporaryDirectory() as folder:
            root = self.copied_contract(folder)
            registry_path = root / "benchmarks" / "first_pass" / "development_registry.v2.json"
            registry = json.loads(registry_path.read_text())
            registry["cases"][0]["domain_review"]["status"] = "approved"
            registry_path.write_text(json.dumps(registry))
            report = validate_contract(root)
        self.assertFalse(report["structural_passed"])
        self.assertTrue(any("approved review lacks owner or date" in item for item in report["structural_errors"]))

    def test_candidate_sources_do_not_inflate_registered_inventory(self):
        report = validate_contract(ROOT)
        self.assertEqual(report["inventory"]["registered_deals"], 3)
        self.assertEqual(report["inventory"]["candidate_deals_not_acquired"], 0)
        self.assertEqual(report["inventory"]["candidate_deals_acquired_not_registered"], 29)
        self.assertEqual(report["inventory"]["candidate_question_drafts_not_registered"], 319)
        self.assertEqual(report["inventory"]["candidate_deals_with_question_drafts"], 29)
        self.assertEqual(report["inventory"]["sourcing_pipeline_deals"], 32)
        self.assertTrue(report["inventory"]["pipeline_task_family_capacity_ready"])
        self.assertGreaterEqual(
            report["inventory"]["pipeline_task_family_capacity"][
                "transaction_identity_structure_chronology"
            ],
            10,
        )
        self.assertGreaterEqual(
            report["inventory"]["pipeline_task_family_capacity"][
                "market_and_regulatory_findings"
            ],
            15,
        )
        self.assertIn("registered deals 3 of 30", report["release_failures"])

    def test_candidate_pipeline_must_be_able_to_fill_each_task_family(self):
        with tempfile.TemporaryDirectory() as folder:
            root = self.copied_contract(folder)
            path = root / "benchmarks" / "first_pass" / "candidate_question_drafts.v1.json"
            registry = json.loads(path.read_text())
            registry["question_families"] = [
                item for item in registry["question_families"]
                if item["task_family"] != "market_and_regulatory_findings"
            ]
            registry["drafts"] = [
                item for item in registry["drafts"]
                if item["task_family"] != "market_and_regulatory_findings"
            ]
            registry["draft_count"] = len(registry["drafts"])
            path.write_text(json.dumps(registry))
            report = validate_contract(root)
        self.assertFalse(report["structural_passed"])
        self.assertTrue(any(
            "candidate pipeline cannot meet task family targets" in item
            and "market_and_regulatory_findings" in item
            for item in report["structural_errors"]
        ))

    def test_candidate_draft_task_family_cannot_drift_from_question_family(self):
        with tempfile.TemporaryDirectory() as folder:
            root = self.copied_contract(folder)
            path = root / "benchmarks" / "first_pass" / "candidate_question_drafts.v1.json"
            registry = json.loads(path.read_text())
            registry["drafts"][0]["task_family"] = "market_and_regulatory_findings"
            path.write_text(json.dumps(registry))
            report = validate_contract(root)
        self.assertFalse(report["structural_passed"])
        self.assertTrue(any(
            "task family differs from its question family" in item
            for item in report["structural_errors"]
        ))

    def test_candidate_question_draft_cannot_create_answer_or_registration(self):
        with tempfile.TemporaryDirectory() as folder:
            root = self.copied_contract(folder)
            path = root / "benchmarks" / "first_pass" / "candidate_question_drafts.v1.json"
            drafts = json.loads(path.read_text())
            drafts["drafts"][0]["expected_answer"] = "$100.00"
            drafts["drafts"][1]["benchmark_case_registered"] = True
            path.write_text(json.dumps(drafts))
            report = validate_contract(root)
        self.assertFalse(report["structural_passed"])
        self.assertTrue(any("contains an answer or labels" in item for item in report["structural_errors"]))
        self.assertTrue(any("claims benchmark registration" in item for item in report["structural_errors"]))

    def test_financial_draft_cannot_bind_proxy_acquisition(self):
        with tempfile.TemporaryDirectory() as folder:
            root = self.copied_contract(folder)
            path = root / "benchmarks" / "first_pass" / "candidate_question_drafts.v1.json"
            drafts = json.loads(path.read_text())
            financial = next(
                item for item in drafts["drafts"]
                if item["question_family"] == "financial_statement_calculation"
            )
            proxy = next(
                item for item in drafts["drafts"]
                if item["candidate_id"] == financial["candidate_id"]
                and item["question_family"] == "transaction_consideration"
            )
            financial["source"] = proxy["source"]
            financial["evidence_candidates"] = proxy["evidence_candidates"]
            path.write_text(json.dumps(drafts))
            report = validate_contract(root)
        self.assertFalse(report["structural_passed"])
        self.assertTrue(any("source binding differs" in item for item in report["structural_errors"]))

    def test_candidate_source_cannot_claim_acquisition_or_labels(self):
        with tempfile.TemporaryDirectory() as folder:
            root = self.copied_contract(folder)
            path = root / "benchmarks" / "first_pass" / "candidate_deal_sources.v1.json"
            candidates = json.loads(path.read_text())
            candidates["candidates"][1].pop("evidence_path")
            candidates["candidates"][1].pop("evidence_sha256")
            candidates["candidates"][0]["label"] = "pass"
            path.write_text(json.dumps(candidates))
            report = validate_contract(root)
        self.assertFalse(report["structural_passed"])
        self.assertTrue(any("acquired source lacks evidence" in item for item in report["structural_errors"]))
        self.assertTrue(any("approval fields" in item for item in report["structural_errors"]))

    def test_saved_development_evaluation_stays_unverified(self):
        report = evaluate_development_responses(
            ROOT, ROOT / "evidence" / "bonsai-public-deal-battletest-responses.json"
        )
        self.assertEqual(report["case_count"], 5)
        self.assertEqual(report["deterministic_failure_count"], 0)
        self.assertEqual(report["semantic_unverified_count"], 5)
        self.assertFalse(report["accuracy_release_passed"])
        self.assertTrue(report["signed_delivery_evidence"]["passed"])
        self.assertEqual(report["signed_delivery_evidence"]["verified_case_count"], 5)
        self.assertEqual(
            report["signed_delivery_evidence"]["provenance_bound_case_count"], 5
        )
        workflow = [
            next(item for item in case["evaluations"] if item["dimension"] == "workflow_reliability")
            for case in report["cases"]
        ]
        self.assertTrue(all(item["label"] == "pass" for item in workflow))
        failed = [item["case_id"] for item in report["cases"] if item["deterministic_hard_failure"]]
        self.assertEqual(failed, [])

    def test_signed_delivery_evidence_rejects_raw_event_tampering(self):
        delivery_path = ROOT / "evidence/public-deal-buzz-event-verification.json"
        delivery = json.loads(delivery_path.read_text(encoding="utf-8"))
        first = delivery["cases"][0]
        answer_id = first["answer_event_id"]
        first["raw_events"][answer_id]["content"] += " tampered"
        with tempfile.NamedTemporaryFile(
            "w", suffix=".json", encoding="utf-8", dir=ROOT / "evidence"
        ) as handle:
            json.dump(delivery, handle)
            handle.flush()
            result = validate_signed_delivery_evidence(
                ROOT,
                ROOT / "evidence/bonsai-public-deal-battletest-responses.json",
                ROOT / "benchmarks/first_pass/development_registry.v2.json",
                Path(handle.name),
            )
        self.assertFalse(result["passed"])
        self.assertIn("NIP-01", " ".join(result["errors"]))

    def test_signed_delivery_rejects_trace_provenance_tampering(self):
        delivery = json.loads((
            ROOT / "evidence/public-deal-buzz-event-verification.json"
        ).read_text(encoding="utf-8"))
        delivery["cases"][0]["trace"]["metadata"][
            "source_provenance_sha256"
        ] = "0" * 64
        with tempfile.NamedTemporaryFile(
            "w", suffix=".json", encoding="utf-8", dir=ROOT / "evidence"
        ) as handle:
            json.dump(delivery, handle)
            handle.flush()
            result = validate_signed_delivery_evidence(
                ROOT,
                ROOT / "evidence/bonsai-public-deal-battletest-responses.json",
                ROOT / "benchmarks/first_pass/development_registry.v2.json",
                Path(handle.name),
            )
        self.assertFalse(result["passed"])
        self.assertIn("persisted trace differs", " ".join(result["errors"]))

    def test_legacy_unbound_response_cannot_pass_current_delivery_gate(self):
        responses = json.loads((
            ROOT / "evidence/bonsai-public-deal-battletest-responses.json"
        ).read_text(encoding="utf-8"))
        first = responses["responses"]["anaplan_vdr_timeline"]
        for field in (
            "source_classification", "source_provenance_sha256",
            "source_snapshot_sha256", "source_provenance",
        ):
            first.pop(field, None)
        with tempfile.NamedTemporaryFile(
            "w", suffix=".json", encoding="utf-8", dir=ROOT / "evidence"
        ) as handle:
            json.dump(responses, handle)
            handle.flush()
            result = validate_signed_delivery_evidence(
                ROOT,
                Path(handle.name),
                ROOT / "benchmarks/first_pass/development_registry.v2.json",
                ROOT / "evidence/public-deal-buzz-event-verification.json",
            )
        self.assertFalse(result["passed"])
        self.assertIn("public provenance binding", " ".join(result["errors"]))

    def test_deterministic_pass_cannot_become_accuracy_release(self):
        registry = json.loads(
            (ROOT / "benchmarks" / "first_pass" / "development_registry.v2.json").read_text()
        )
        case = next(item for item in registry["cases"] if item["id"] == "anaplan_termination_fees")
        response = {
            "provider": "test",
            "model": "test",
            "response": (
                "$293,122,500 and $586,245,000 "
                "[01_anaplan_defm14a.htm#html:block:00207]"
            ),
            "unauthorized_file_writes": [],
        }
        result = evaluate_case_response(case, response)
        self.assertFalse(result["deterministic_hard_failure"])
        self.assertEqual(result["semantic_state"], "unverified")
        self.assertEqual(result["release_decision"], "unverified")

    def test_missing_citation_and_false_absence_fail_deterministically(self):
        registry = json.loads(
            (ROOT / "benchmarks" / "first_pass" / "development_registry.v2.json").read_text()
        )
        case = next(item for item in registry["cases"] if item["id"] == "citrix_entry_leverage_absent")
        result = evaluate_case_response(case, {
            "provider": "test",
            "model": "test",
            "response": "The entry leverage multiple was 13.0x.",
            "unauthorized_file_writes": [],
        })
        failures = {
            item["dimension"] for item in result["evaluations"] if item["label"] == "fail"
        }
        self.assertEqual(failures, {"source_integrity", "calibrated_uncertainty"})


if __name__ == "__main__":
    unittest.main()
