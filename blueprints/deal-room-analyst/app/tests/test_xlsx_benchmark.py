import unittest
from pathlib import Path

from core.xlsx_benchmark import evaluate_xlsx_display_benchmark


DATASET = Path(__file__).resolve().parent.parent / "benchmarks" / "xlsx_display_fidelity.v1.json"


class XlsxDisplayBenchmarkTests(unittest.TestCase):
    def test_preregistered_display_contract_passes_end_to_end(self):
        report = evaluate_xlsx_display_benchmark(DATASET)
        self.assertTrue(report["passed"], report)
        self.assertEqual(report["passed_cases"], 9)
        self.assertEqual(report["total_cases"], 9)

    def test_wrong_expected_display_fails_the_evaluator(self):
        report = evaluate_xlsx_display_benchmark(DATASET, mutate_case="cached_percent_formula")
        self.assertFalse(report["passed"])
        failed = [case for case in report["cases"] if not case["passed"]]
        self.assertEqual([case["case_id"] for case in failed], ["cached_percent_formula"])
        self.assertFalse(failed[0]["checks"]["display_value"])

    def test_measurement_state_does_not_claim_excel_parity(self):
        report = evaluate_xlsx_display_benchmark(DATASET)
        self.assertEqual(
            report["measurement_state"],
            "spec_derived_parser_regression_not_excel_parity",
        )
        self.assertTrue(any("not full Excel" in item for item in report["limitations"]))


if __name__ == "__main__":
    unittest.main()
