import json
import tempfile
import unittest
from pathlib import Path

from core.arize_evals import ArizeObservabilityTracer
from scripts.remediate_trace_fixture_contamination import remediate
from tests.test_trace_persistence import _record


class TraceContaminationRemediationTests(unittest.TestCase):
    def test_saved_remediation_record_preserves_the_correction_boundary(self):
        record = json.loads(Path(
            "evidence/runtime-trace-contamination-remediation-v1.json"
        ).read_text(encoding="utf-8"))
        self.assertEqual(record["measurement_state"], "fixture_contamination_labelled")
        self.assertEqual(record["candidate_count"], 20)
        self.assertEqual(len(record["trace_ids"]), 20)
        self.assertEqual(len(set(record["trace_ids"])), 20)
        self.assertEqual(record["records_deleted"], 0)
        self.assertEqual(
            record["after"]["entry_count"] - record["before"]["entry_count"], 20,
        )
        self.assertNotEqual(
            record["after"]["head_sha256"], record["before"]["head_sha256"],
        )
        self.assertTrue(any(
            "not signed or externally anchored" in item
            for item in record["limitations"]
        ))

    def test_exact_fixture_pair_is_retained_labelled_and_excluded(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "traces.jsonl"
            tracer = ArizeObservabilityTracer(str(path))
            legitimate = _record("trc_legitimate")
            fixture = _record("trc_fixture")
            fixture.session_id = "agent_session"
            fixture.query = "Run sensitivity stress-test modeling a 10% and 20% drop in EBITDA."
            fixture.metadata.update({
                "execution_mode": "deterministic_template",
                "provider_id": None,
                "generation_attempts": 0,
            })
            tracer.record_trace(legitimate)
            tracer.record_trace(fixture)
            before = path.read_bytes()
            dry_run = remediate(path, expected_count=1, apply=False)
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(dry_run["records_deleted"], 0)

            applied = remediate(path, expected_count=1, apply=True)
            restored = ArizeObservabilityTracer(str(path))
            self.assertEqual(len(restored.snapshot()), 2)
            corrected = next(
                trace for trace in restored.snapshot() if trace.trace_id == "trc_fixture"
            )
            self.assertTrue(corrected.metadata["exclude_from_aggregate_metrics"])
            self.assertEqual(
                corrected.metadata["trace_provenance"]["state"],
                "verification_fixture_contamination",
            )
            self.assertEqual(applied["records_deleted"], 0)
            self.assertEqual(applied["after"]["entry_count"], 3)
            metrics = restored.get_aggregate_metrics()
            self.assertEqual(metrics["total_traces"], 2)
            self.assertEqual(metrics["aggregate_eligible_traces"], 1)
            self.assertEqual(metrics["excluded_trace_count"], 1)


if __name__ == "__main__":
    unittest.main()
