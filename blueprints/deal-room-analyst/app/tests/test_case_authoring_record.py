import json
import shutil
import subprocess
import unittest
from pathlib import Path

from core.first_pass_benchmark import schema_errors


ROOT = Path(__file__).resolve().parents[1]


class CaseAuthoringRecordTests(unittest.TestCase):
    def test_unsigned_case_approval_is_schema_valid_and_not_an_attestation(self):
        node = shutil.which("node")
        self.assertIsNotNone(node)
        completed = subprocess.run(
            [node, "scripts/verify_case_authoring_record.mjs"],
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
        approval_schema = json.loads(
            (ROOT / "benchmarks/first_pass/candidate_case_approval.schema.json").read_text()
        )
        case_schema = json.loads(
            (ROOT / "benchmarks/first_pass/case.schema.json").read_text()
        )
        self.assertEqual(schema_errors(record, approval_schema), [])
        self.assertEqual(schema_errors(record["case"], case_schema), [])
        self.assertEqual(record["buzz_event_id"], "0" * 64)
        self.assertNotEqual(record["buzz_event_id"], record["source_review_event_ids"][0])


if __name__ == "__main__":
    unittest.main()
