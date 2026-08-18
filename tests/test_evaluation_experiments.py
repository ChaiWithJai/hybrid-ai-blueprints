import json
import tempfile
import unittest
from pathlib import Path

from core.evaluation_experiments import ExperimentStore


SHA = "a" * 64


class EvaluationExperimentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = ExperimentStore(Path(self.temp.name))
        self.room = "project_titan_lbo"

    def tearDown(self):
        self.temp.cleanup()

    def experiment(self, experiment_id, route_mode, **changes):
        record = {
            "experiment_id": experiment_id,
            "name": experiment_id,
            "route_mode": route_mode,
            "dataset_version": "titan.v1",
            "workflow_family": "deal_room_first_pass",
            "source_snapshot_sha256": SHA,
            "question_sha256": "b" * 64,
            "evidence_packet_sha256": "c" * 64,
            "answer_contract_sha256": "d" * 64,
            "limits_sha256": "e" * 64,
            "answer_model": "bonsai-27b" if route_mode == "local" else "cloud-model",
            "judge_model": None,
            "evaluator_version": "eval.v1",
        }
        record.update(changes)
        return record

    def run_record(self, run_id, experiment_id, answer_model, score, **changes):
        record = {
            "run_id": run_id,
            "experiment_id": experiment_id,
            "case_id": "case-1",
            "repetition": 1,
            "answer_model": answer_model,
            "judge_model": None,
            "prompt_sha256": "f" * 64,
            "evaluator_version": "eval.v1",
            "source_snapshot_sha256": SHA,
            "retrieval_config_sha256": "1" * 64,
            "output_sha256": "2" * 64,
            "started_at": "2026-08-18T12:00:00Z",
            "ended_at": "2026-08-18T12:00:01Z",
            "latency_ms": 1000,
            "input_tokens": 100,
            "output_tokens": 50,
            "cost_usd": None,
            "energy_mwh_per_token": None,
            "egress_authorized": route_mode_for(experiment_id) == "local",
            "content_exposure": "local_only" if route_mode_for(experiment_id) == "local" else "approved_cloud",
            "runtime_error": None,
            "metrics": {"evidence_quality": score, "unmeasured_cost": None},
        }
        record.update(changes)
        return record

    def test_records_and_compares_paired_routes_without_composite(self):
        self.store.create_experiment(self.room, self.experiment("local-v1", "local"))
        self.store.create_experiment(self.room, self.experiment("cloud-v1", "cloud"))
        self.store.append_run(self.room, self.run_record("run-local", "local-v1", "bonsai-27b", 0.7))
        self.store.append_run(self.room, self.run_record("run-cloud", "cloud-v1", "cloud-model", 0.9))
        result = self.store.compare(self.room, "local-v1", "cloud-v1")
        self.assertEqual(result["paired_case_count"], 1)
        self.assertAlmostEqual(result["pairs"][0]["metric_deltas_right_minus_left"]["evidence_quality"], 0.2)
        self.assertIsNone(result["pairs"][0]["metric_deltas_right_minus_left"]["unmeasured_cost"])
        self.assertIn("no_composite", result["aggregation_policy"])

    def test_comparison_rejects_contract_drift(self):
        self.store.create_experiment(self.room, self.experiment("local-v1", "local"))
        self.store.create_experiment(
            self.room,
            self.experiment("cloud-v2", "cloud", evidence_packet_sha256="9" * 64),
        )
        with self.assertRaisesRegex(ValueError, "comparison contract"):
            self.store.compare(self.room, "local-v1", "cloud-v2")

    def test_tampering_breaks_hash_chain(self):
        self.store.create_experiment(self.room, self.experiment("local-v1", "local"))
        path = Path(self.temp.name) / f"{self.room}.json"
        ledger = json.loads(path.read_text())
        ledger["events"][0]["payload"]["name"] = "tampered"
        path.write_text(json.dumps(ledger))
        with self.assertRaisesRegex(ValueError, "event hash"):
            self.store.snapshot(self.room)

    def test_run_cannot_drift_from_experiment_model(self):
        self.store.create_experiment(self.room, self.experiment("local-v1", "local"))
        with self.assertRaisesRegex(ValueError, "answer model"):
            self.store.append_run(self.room, self.run_record("run-local", "local-v1", "other-model", 0.7))


def route_mode_for(experiment_id):
    return "local" if experiment_id.startswith("local") else "cloud"


if __name__ == "__main__":
    unittest.main()
