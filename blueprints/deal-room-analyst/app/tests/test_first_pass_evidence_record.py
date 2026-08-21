import hashlib
import tempfile
import unittest
from pathlib import Path

from scripts.record_first_pass_evidence import build_record


class FirstPassEvidenceRecordTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.folder = Path(self.temp.name)
        (self.folder / "cim.md").write_text("Target evidence")
        self.status = {
            "buzz": {"relay_live": True, "relay_url": "ws://127.0.0.1:3030"},
            "configured_local_model_name": "27b@q1_0",
            "last_invoked_local_model": "27b@q1_0",
            "local_inference_invoked": True,
            "local_inference_invocation_evidence": "persisted_trace",
        }
        self.first_pass = {
            "room": "room",
            "canonical_path": "/rooms/room/first-pass",
            "draft": {
                "acceptance_state": "accepted",
                "artifact_mode": "model_draft",
                "authored_by": "local_bonsai",
                "guard_version": "evidence_claim_v7",
                "model": "27b@q1_0",
                "recommendation": "pause",
                "trace_id": "trc_test",
                "draft_event_id": "event-test",
                "restored_from_buzz": True,
                "restoration_verification": {
                    "state": "verified",
                    "event_id": "event-test",
                    "trace_id": "trc_test",
                },
                "citations": ["[cim.md#node:terms]"],
                "markdown": "Recommendation: PAUSE [cim.md#node:terms]",
            },
        }
        self.evals = {"traces": [{
            "trace_id": "trc_test",
            "session_id": "room",
            "response_sha256": hashlib.sha256(
                b"Recommendation: PAUSE [cim.md#node:terms]"
            ).hexdigest(),
            "model_name": "27b@q1_0",
            "metadata": {
                "provider_id": "local_bonsai",
                "draft_event_id": "event-test",
                "guard_version": "evidence_claim_v7",
            },
            "evaluations": [{
                "name": "human_accuracy_review",
                "passed": False,
                "metadata": {"measurement_state": "awaiting_human_review"},
            }],
        }]}

    def tearDown(self):
        self.temp.cleanup()

    def test_records_trace_linked_product_state_without_accuracy_upgrade(self):
        record = build_record(
            self.status, self.first_pass, self.evals, self.folder, recorded_at=1.0,
        )
        self.assertTrue(record["product_path_verified"])
        self.assertFalse(record["accuracy_release_passed"])
        self.assertEqual(record["human_review_state"], "pending")
        self.assertEqual(record["artifact"]["trace_id"], "trc_test")
        self.assertEqual(len(record["source_files"][0]["sha256"]), 64)

    def test_rejects_buzz_artifact_without_trace_identity(self):
        self.first_pass["draft"]["trace_id"] = None
        with self.assertRaisesRegex(RuntimeError, "no trace identity"):
            build_record(self.status, self.first_pass, self.evals, self.folder)

    def test_rejects_model_draft_with_unrelated_or_mismatched_trace(self):
        self.evals["traces"][0]["metadata"]["provider_id"] = "deterministic_baseline"
        with self.assertRaisesRegex(RuntimeError, "local Bonsai provider"):
            build_record(self.status, self.first_pass, self.evals, self.folder)

        self.evals["traces"][0]["metadata"]["provider_id"] = "local_bonsai"
        self.evals["traces"][0]["model_name"] = "some-other-model"
        with self.assertRaisesRegex(RuntimeError, "model identities do not match"):
            build_record(self.status, self.first_pass, self.evals, self.folder)

    def test_missing_or_ambiguous_human_review_signal_fails_closed(self):
        evaluation = self.evals["traces"][0]["evaluations"][0]
        variants = (
            ([], "exactly one named"),
            ([{**evaluation, "name": "some_other_check"}], "exactly one named"),
            ([{**evaluation, "passed": True}], "explicit pending"),
            ([{
                **evaluation,
                "metadata": {"measurement_state": "review_recorded"},
            }], "explicit pending"),
            ([evaluation, dict(evaluation)], "exactly one named"),
        )
        for evaluations, message in variants:
            with self.subTest(evaluations=evaluations):
                self.evals["traces"][0]["evaluations"] = evaluations
                with self.assertRaisesRegex(RuntimeError, message):
                    build_record(self.status, self.first_pass, self.evals, self.folder)

    def test_screen_bound_record_requires_retrieval_and_snapshot_proof(self):
        with self.assertRaisesRegex(RuntimeError, "not screen-bound"):
            build_record(
                self.status, self.first_pass, self.evals, self.folder,
                require_screen_bound=True,
            )
        self.evals["traces"][0]["metadata"].update({
            "investment_screen_retrieval": "screen_bound_v1",
            "investment_screen_passage_count": 1,
            "source_snapshot_sha256": "a" * 64,
            "source_classification": "synthetic_engineering_fixture",
            "source_provenance_sha256": "b" * 64,
            "source_provenance": {
                "classification": "synthetic_engineering_fixture",
                "binding_sha256": "b" * 64,
            },
        })
        self.first_pass["draft"].update({
            "source_snapshot_sha256": "a" * 64,
            "source_classification": "synthetic_engineering_fixture",
            "source_provenance_sha256": "b" * 64,
        })
        record = build_record(
            self.status, self.first_pass, self.evals, self.folder,
            require_screen_bound=True,
        )
        self.assertEqual(record["artifact"]["source_snapshot_sha256"], "a" * 64)
        self.assertEqual(
            record["artifact"]["source_classification"],
            "synthetic_engineering_fixture",
        )


if __name__ == "__main__":
    unittest.main()
