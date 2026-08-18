import unittest

from core.evaluator_validation import (
    bias_corrected_pass_rate,
    bootstrap_corrected_pass_interval,
    confusion_metrics,
    judge_release_decision,
    validate_calibration_dataset,
)


class EvaluatorValidationTests(unittest.TestCase):
    def test_perfect_balanced_judge(self):
        metrics = confusion_metrics(
            ["pass", "pass", "fail", "fail"],
            ["pass", "pass", "fail", "fail"],
        )
        self.assertEqual(metrics["tpr"], 1)
        self.assertEqual(metrics["tnr"], 1)
        self.assertEqual(metrics["critical_false_passes"], 0)
        self.assertTrue(judge_release_decision(metrics)["trusted_for_release"])

    def test_lenient_judge_exposes_critical_false_passes(self):
        metrics = confusion_metrics(
            ["pass", "pass", "fail", "fail"],
            ["pass", "pass", "pass", "fail"],
        )
        self.assertEqual(metrics["fp"], 1)
        self.assertEqual(metrics["tnr"], 0.5)
        decision = judge_release_decision(metrics)
        self.assertFalse(decision["trusted_for_release"])
        self.assertIn("critical_false_pass_limit_exceeded", decision["failures"])

    def test_parse_failures_are_not_silently_coerced(self):
        metrics = confusion_metrics(["pass", "fail"], ["maybe", "fail"])
        self.assertEqual(metrics["parse_failures"], 1)
        self.assertEqual(metrics["parse_failure_rate"], 0.5)
        self.assertFalse(judge_release_decision(metrics)["trusted_for_release"])

    def test_bias_correction_rejects_non_discriminating_judge(self):
        with self.assertRaises(ValueError):
            bias_corrected_pass_rate(0.5, tpr=0.5, tnr=0.5)

    def test_bias_correction_and_bootstrap_are_bounded(self):
        corrected = bias_corrected_pass_rate(0.56, tpr=0.9, tnr=0.8)
        self.assertAlmostEqual(corrected, (0.56 + 0.8 - 1) / 0.7)
        human = ["pass"] * 50 + ["fail"] * 50
        judge = ["pass"] * 45 + ["fail"] * 5 + ["fail"] * 45 + ["pass"] * 5
        interval = bootstrap_corrected_pass_interval(human, judge, samples=300)
        self.assertEqual(interval["state"], "measured")
        self.assertGreaterEqual(interval["lower"], 0)
        self.assertLessEqual(interval["upper"], 1)

    def test_split_contract_rejects_duplicates_and_missing_class(self):
        result = validate_calibration_dataset([
            {"id": "a", "split": "train", "label": "pass"},
            {"id": "a", "split": "train", "label": "fail"},
            {"id": "b", "split": "dev", "label": "pass"},
            {"id": "c", "split": "test", "label": "fail"},
        ])
        self.assertFalse(result["valid"])
        self.assertTrue(any("duplicate" in error for error in result["errors"]))


if __name__ == "__main__":
    unittest.main()
