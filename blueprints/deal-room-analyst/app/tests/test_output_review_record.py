import json
import shutil
import subprocess
import unittest
from pathlib import Path

from core.first_pass_benchmark import schema_errors


ROOT = Path(__file__).resolve().parents[1]


class OutputReviewRecordTests(unittest.TestCase):
    def test_unsigned_output_review_is_complete_schema_valid_and_not_attested(self):
        node = shutil.which("node")
        self.assertIsNotNone(node)
        completed = subprocess.run(
            [node, "scripts/verify_output_review_record.mjs"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        result = json.loads(completed.stdout)
        self.assertTrue(result["passed"])
        record = result["record"]
        schema = json.loads(
            (ROOT / "benchmarks/first_pass/human_review_submission.schema.json").read_text()
        )
        self.assertEqual(schema_errors(record, schema), [])
        self.assertEqual(record["buzz_event_id"], "0" * 64)
        self.assertEqual(len(record["cases"]), 2)
        self.assertNotIn("provider", record)
        self.assertNotIn("model", record)


if __name__ == "__main__":
    unittest.main()
