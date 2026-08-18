import copy
import json
from pathlib import Path
import tempfile
import unittest

from core.oracle_context_diagnostic import (
    EVIDENCE_KIND,
    assemble_case_record,
    deterministic_probe,
    localization,
    sha256_bytes,
    validate_saved_oracle_context,
)


def fixture_case(answer_policy="answer"):
    return {
        "id": "price_case",
        "question": "What is the purchase price?",
        "answer_policy": answer_policy,
        "required_claims": [{"text": "The purchase price is $95 million."}],
        "required_citations": [{
            "filename": "deal.txt",
            "anchor": "node:price",
            "source_sha256": "a" * 64,
        }],
        "acceptable_absence_terms": (
            ["not disclosed", "cannot be calculated"] if answer_policy == "refuse_absent" else []
        ),
        "forbidden_claims": ["The purchase price is $85 million."],
    }


def passage():
    return [{
        "filename": "deal.txt",
        "anchor": "node:price",
        "citation": "[deal.txt#node:price]",
        "source_sha256": "a" * 64,
        "text": "The purchase price is $95 million.",
    }]


class OracleContextDiagnosticTests(unittest.TestCase):
    def test_wrong_baseline_and_correct_oracle_localize_context_sensitive_failure(self):
        case = fixture_case()
        result = assemble_case_record(
            case,
            "The purchase price is $85 million. [deal.txt#node:price]",
            passage(),
            {
                "response": "The purchase price is $95 million. [deal.txt#node:price]",
                "provider": "local_bonsai",
                "model": "fixture-model",
            },
        )
        self.assertEqual(
            result["localization"],
            "deterministic_failure_repaired_with_registered_oracle_context",
        )
        self.assertFalse(result["baseline_probe"]["passed"])
        self.assertTrue(result["oracle"]["probe"]["passed"])
        self.assertEqual(result["oracle"]["probe"]["semantic_accuracy_state"], "unverified")

    def test_wrong_oracle_output_cannot_create_a_repaired_result(self):
        case = fixture_case()
        failed = deterministic_probe(
            case, "The purchase price is $85 million. [deal.txt#node:price]"
        )
        forged = copy.deepcopy(failed)
        forged["passed"] = True
        self.assertEqual(
            localization(failed, deterministic_probe(case, "No answer.")),
            "deterministic_failure_persists_with_registered_oracle_context",
        )
        self.assertNotEqual(localization(failed, forged), localization(failed, failed))

    def test_baseline_pass_followed_by_oracle_failure_is_a_regression(self):
        case = fixture_case()
        baseline = deterministic_probe(
            case, "The purchase price is $95 million. [deal.txt#node:price]"
        )
        oracle = deterministic_probe(case, "The purchase price is $95 million.")
        self.assertTrue(baseline["passed"])
        self.assertFalse(oracle["passed"])
        self.assertEqual(
            localization(baseline, oracle),
            "oracle_context_regressed_deterministic_contract",
        )

    def test_absence_case_is_not_run_with_one_positive_passage(self):
        result = assemble_case_record(
            fixture_case("refuse_absent"), "", passage(), None,
        )
        self.assertFalse(result["eligible"])
        self.assertEqual(result["localization"], "not_run_absence_oracle_not_implemented")
        self.assertIsNone(result["oracle"])

    def test_absence_case_runs_only_with_passing_whole_corpus_audit(self):
        case = fixture_case("refuse_absent")
        case["required_claims"] = [{
            "text": "The purchase price is not disclosed and cannot be calculated."
        }]
        audit = {
            "passed": True,
            "source_file_count": 2,
            "parsed_node_count": 10,
            "registered_direct_disclosure_hits": [],
            "required_confusable_evidence": [],
        }
        result = assemble_case_record(
            case,
            "The price is not disclosed. [deal.txt#node:price]",
            passage(),
            {
                "response": (
                    "The price is not disclosed and cannot be calculated from the cited "
                    "evidence alone. [deal.txt#node:price]"
                ),
                "provider": "local_bonsai",
                "model": "fixture-model",
            },
            absence_audit=audit,
        )
        self.assertTrue(result["eligible"])
        self.assertEqual(
            result["oracle"]["context_kind"],
            "whole_corpus_registered_pattern_absence_audit",
        )
        self.assertTrue(result["oracle"]["probe"]["passed"])
        failed = assemble_case_record(
            case, "", passage(), None, absence_audit={**audit, "passed": False},
        )
        self.assertFalse(failed["eligible"])

    def test_saved_raw_response_tamper_is_recomputed_and_fails(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            contract = root / "benchmarks" / "first_pass"
            evidence_folder = root / "evidence"
            contract.mkdir(parents=True)
            evidence_folder.mkdir()
            case = fixture_case()
            registry_bytes = (json.dumps({"cases": [case]}, indent=2) + "\n").encode()
            responses_bytes = (json.dumps({
                "responses": {case["id"]: {
                    "response": "The purchase price is $85 million. [deal.txt#node:price]"
                }}
            }, indent=2) + "\n").encode()
            (contract / "development_registry.v2.json").write_bytes(registry_bytes)
            (evidence_folder / "bonsai-public-deal-battletest-responses.json").write_bytes(
                responses_bytes
            )
            saved_case = assemble_case_record(
                case,
                "The purchase price is $85 million. [deal.txt#node:price]",
                passage(),
                {
                    "response": "The purchase price is $95 million. [deal.txt#node:price]",
                    "provider": "local_bonsai",
                    "model": "fixture-model",
                },
            )
            record = {
                "verification_kind": EVIDENCE_KIND,
                "registry_sha256": sha256_bytes(registry_bytes),
                "baseline_responses_sha256": sha256_bytes(responses_bytes),
                "semantic_accuracy_state": "unverified",
                "accuracy_release_passed": False,
                "cases": [saved_case],
            }
            record_path = evidence_folder / "oracle.json"
            record_path.write_text(json.dumps(record))
            self.assertTrue(validate_saved_oracle_context(root, record_path)["passed"])
            record["cases"][0]["oracle"]["response"] = "The price is $85 million."
            record_path.write_text(json.dumps(record))
            result = validate_saved_oracle_context(root, record_path)
            self.assertFalse(result["passed"])
            self.assertTrue(any(
                "saved oracle result differs from recomputation" in item
                for item in result["errors"]
            ))


if __name__ == "__main__":
    unittest.main()
