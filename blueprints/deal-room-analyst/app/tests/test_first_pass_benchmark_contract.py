import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


# Catalog resources (docs/, tooling/) live at the repository root, which is four
# levels above this application after the issue #2 migration. ROOT stays the
# application root so app-relative paths are unaffected.


REPO_ROOT = Path(__file__).resolve().parents[4]
BENCHMARK_DIR = ROOT / "benchmarks" / "first_pass"


def load_json(name: str):
    with (BENCHMARK_DIR / name).open(encoding="utf-8") as handle:
        return json.load(handle)


class FirstPassBenchmarkContractTests(unittest.TestCase):
    def test_first_pass_manifest_counts_are_consistent(self):
        manifest = load_json("benchmark_manifest.v1.json")
        target = manifest["target"]
        self.assertEqual(sum(item["cases"] for item in target["splits"].values()), target["cases"])
        self.assertEqual(sum(target["task_families"].values()), target["cases"])
        self.assertEqual(
            sum(item["minimum_deals"] for item in target["splits"].values()),
            target["minimum_deals"],
        )
        self.assertEqual(manifest["split_policy"]["unit"], "deal")
        self.assertFalse(manifest["split_policy"]["sealed_answers_in_repository"])
        self.assertTrue(manifest["split_policy"]["test_contact_invalidates_version"])

    def test_first_pass_rubric_keeps_critical_gates_separate(self):
        rubric = load_json("rubric.v1.json")
        dimensions = {item["id"] for item in rubric["dimensions"]}
        self.assertEqual(dimensions, {
            "primary_decision_intent", "evidence_support", "numerical_correctness",
            "component_completeness", "calibrated_uncertainty", "source_integrity",
            "workflow_reliability", "human_usefulness",
        })
        self.assertFalse(rubric["aggregation_policy"]["single_composite_release_score"])
        self.assertFalse(rubric["aggregation_policy"]["hard_failure_can_be_averaged_away"])
        self.assertEqual(rubric["hard_gates"]["critical_numerical_accuracy"], 1.0)
        self.assertEqual(rubric["hard_gates"]["critical_answer_absence_recall"], 1.0)
        self.assertEqual(rubric["judge_gates"]["maximum_critical_false_passes"], 0)

    def test_public_cases_are_registered_only_as_development_data(self):
        registered = load_json("development_cases.v1.json")
        prior = json.loads((ROOT / "benchmarks" / "public_deal_battletest.json").read_text())
        self.assertEqual(registered["split"], "development")
        self.assertEqual(registered["domain_approval"], "not_reviewed")
        self.assertEqual(
            {item["id"] for item in registered["cases"]},
            {item["id"] for item in prior["cases"]},
        )
        self.assertEqual(sum(item["prior_result"]["label"] == "pass" for item in registered["cases"]), 2)
        self.assertEqual(sum(item["prior_result"]["label"] == "fail" for item in registered["cases"]), 3)

    def test_first_pass_schemas_and_documentation_exist(self):
        for filename in (
            "case.schema.json", "run_record.schema.json", "benchmark_manifest.v1.json",
            "rubric.v1.json", "development_cases.v1.json",
            "judge_calibration.schema.json", "sealed_test_manifest.schema.json",
            "sealed_test_manifest.v1.json", "sealed_test_control.schema.json",
            "sealed_test_control.v1.json", "README.md",
        ):
            self.assertTrue((BENCHMARK_DIR / filename).is_file(), filename)
        for filename in (
            "case.schema.json", "run_record.schema.json", "judge_calibration.schema.json",
            "sealed_test_manifest.schema.json", "sealed_test_control.schema.json"
        ):
            schema = load_json(filename)
            self.assertEqual(schema["$schema"], "https://json-schema.org/draft/2020-12/schema")
            self.assertFalse(schema["additionalProperties"])
        contract = REPO_ROOT / "docs" / "FIRST_PASS_UNDERWRITING_BENCHMARK.md"
        self.assertTrue(contract.is_file())
        text = contract.read_text(encoding="utf-8")
        self.assertIn("## The ten benchmark decisions", text)
        self.assertIn("## Pricing exercise", text)
        self.assertIn("## Evaluation layers", text)


if __name__ == "__main__":
    unittest.main()
