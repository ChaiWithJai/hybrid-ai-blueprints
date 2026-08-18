import json
import multiprocessing
import os
import tempfile
import threading
import unittest
from dataclasses import asdict
from pathlib import Path
from unittest import mock

from core.arize_evals import (
    ArizeObservabilityTracer,
    ArizeTraceRecord,
    EvalMetric,
    evaluation_release_state,
)


def _record(trace_id="trc_persisted"):
    return ArizeTraceRecord(
        trace_id=trace_id,
        session_id="room-one",
        timestamp=1.0,
        query="first_pass_underwriting",
        response="reviewable draft",
        model_name="27b@q1_0",
        routed_tier="LOCAL_BONSAI_27B",
        total_tokens=42,
        prompt_tokens=30,
        completion_tokens=12,
        total_latency_ms=123.0,
        energy_per_token_mwh=None,
        total_energy_mwh=None,
        vram_peak_gb=None,
        evaluations=[EvalMetric(
            name="human_accuracy_review",
            score=0.0,
            threshold=1.0,
            passed=False,
            explanation="Awaiting review",
            metadata={"measurement_state": "awaiting_human_review"},
        )],
        metadata={"provider_id": "local_bonsai"},
    )


def _record_trace_in_process(path_text, index, result_queue):
    try:
        tracer = ArizeObservabilityTracer(path_text)
        tracer.record_trace(_record(f"trc_process_{index:02d}"))
        result_queue.put(None)
    except Exception as exc:  # pragma: no cover - asserted by parent
        result_queue.put(f"{type(exc).__name__}: {exc}")


class TracePersistenceTests(unittest.TestCase):
    def test_legacy_jsonl_migrates_to_verified_hash_chain(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "traces.jsonl"
            path.write_text(
                json.dumps(asdict(_record("trc_legacy_one")), sort_keys=True) + "\n"
                + json.dumps(asdict(_record("trc_legacy_two")), sort_keys=True) + "\n",
                encoding="utf-8",
            )
            tracer = ArizeObservabilityTracer(str(path))
            status = tracer.storage_status()
            entries = [json.loads(line) for line in path.read_text().splitlines()]
            self.assertEqual([trace.trace_id for trace in tracer.snapshot()], [
                "trc_legacy_one", "trc_legacy_two",
            ])
            self.assertEqual(status["format"], "hash_chained_local_jsonl_v1")
            self.assertEqual(status["entry_count"], 2)
            self.assertEqual(entries[0]["operation"], "legacy_import")
            self.assertEqual(entries[1]["previous_entry_sha256"], entries[0]["entry_sha256"])
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_hash_tamper_and_internal_entry_deletion_fail_closed(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "traces.jsonl"
            tracer = ArizeObservabilityTracer(str(path))
            for index in range(3):
                tracer.record_trace(_record(f"trc_chain_{index}"))
            original = path.read_text(encoding="utf-8")
            lines = original.splitlines()
            first = json.loads(lines[0])
            first["record"]["response"] = "tampered"
            path.write_text(json.dumps(first, sort_keys=True) + "\n" + "\n".join(lines[1:]) + "\n")
            with self.assertRaisesRegex(ValueError, "hash mismatch"):
                ArizeObservabilityTracer(str(path))
            with self.assertRaisesRegex(ValueError, "hash mismatch"):
                tracer.snapshot()

            path.write_text(original, encoding="utf-8")
            lines = original.splitlines()
            path.write_text("\n".join([lines[0], lines[2]]) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "sequence mismatch"):
                ArizeObservabilityTracer(str(path))

    def test_competing_processes_append_every_trace(self):
        if "fork" not in multiprocessing.get_all_start_methods():
            self.skipTest("fork multiprocessing is unavailable")
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "traces.jsonl"
            live_reader = ArizeObservabilityTracer(str(path))
            context = multiprocessing.get_context("fork")
            result_queue = context.Queue()
            workers = [
                context.Process(
                    target=_record_trace_in_process,
                    args=(str(path), index, result_queue),
                )
                for index in range(12)
            ]
            for worker in workers:
                worker.start()
            for worker in workers:
                worker.join(timeout=10)
            results = [result_queue.get(timeout=2) for _ in workers]
            self.assertEqual(results, [None] * len(workers))
            self.assertTrue(all(worker.exitcode == 0 for worker in workers))
            restored = ArizeObservabilityTracer(str(path))
            self.assertEqual(
                {trace.trace_id for trace in restored.snapshot()},
                {f"trc_process_{index:02d}" for index in range(12)},
            )
            self.assertEqual(restored.storage_status()["entry_count"], 12)
            self.assertEqual(len(live_reader.snapshot()), 12)
            lock_path = path.with_name(f".{path.name}.lock")
            self.assertEqual(lock_path.stat().st_mode & 0o777, 0o600)

    def test_conflicting_review_update_and_failed_append_preserve_history(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "traces.jsonl"
            writer = ArizeObservabilityTracer(str(path))
            writer.record_trace(_record())
            first = ArizeObservabilityTracer(str(path))
            second = ArizeObservabilityTracer(str(path))
            first.traces[0].metadata["review"] = "first"
            first.persist()
            committed = path.read_bytes()
            second.traces[0].metadata["review"] = "second"
            with self.assertRaisesRegex(ValueError, "concurrent trace update conflict"):
                second.persist()
            self.assertEqual(path.read_bytes(), committed)

            with mock.patch("core.arize_evals.os.replace", side_effect=OSError("disk full")):
                with self.assertRaisesRegex(OSError, "disk full"):
                    first.record_trace(_record("trc_failed_append"))
            self.assertEqual(path.read_bytes(), committed)
            restored = ArizeObservabilityTracer(str(path))
            self.assertEqual([trace.trace_id for trace in restored.snapshot()], ["trc_persisted"])
            self.assertEqual(restored.traces[0].metadata["review"], "first")

    def test_empty_aggregate_metrics_remain_unmeasured(self):
        empty = ArizeObservabilityTracer().get_aggregate_metrics()
        for field in (
            "avg_faithfulness",
            "avg_forbidden_string_check",
            "avg_tabular_fixture_cell_match",
            "avg_latency_ms",
            "avg_energy_mwh_per_token",
            "local_routing_percentage",
        ):
            self.assertIsNone(empty[field])
        self.assertEqual(set(empty["metric_sample_counts"].values()), {0})

        tracer = ArizeObservabilityTracer()
        tracer.record_trace(_record())
        pending_only = tracer.get_aggregate_metrics()
        self.assertIsNone(pending_only["avg_faithfulness"])
        self.assertIsNone(pending_only["avg_forbidden_string_check"])
        self.assertIsNone(pending_only["avg_tabular_fixture_cell_match"])
        self.assertIsNone(pending_only["avg_energy_mwh_per_token"])
        self.assertEqual(pending_only["avg_latency_ms"], 123.0)
        self.assertEqual(pending_only["local_routing_percentage"], 100.0)
        self.assertEqual(pending_only["metric_sample_counts"]["latency"], 1)
        self.assertEqual(pending_only["metric_sample_counts"]["routing"], 1)

    def test_excluded_fixture_remains_visible_but_does_not_change_aggregates(self):
        tracer = ArizeObservabilityTracer()
        included = _record("trc_included")
        excluded = _record("trc_excluded")
        excluded.total_latency_ms = 999999.0
        excluded.metadata["exclude_from_aggregate_metrics"] = True
        excluded.metadata["trace_provenance"] = {
            "state": "verification_fixture_contamination",
            "reason": "Retained correction record",
        }
        tracer.record_trace(included)
        tracer.record_trace(excluded)
        metrics = tracer.get_aggregate_metrics()
        self.assertEqual(len(tracer.snapshot()), 2)
        self.assertEqual(metrics["total_traces"], 2)
        self.assertEqual(metrics["aggregate_eligible_traces"], 1)
        self.assertEqual(metrics["excluded_trace_count"], 1)
        self.assertEqual(metrics["avg_latency_ms"], 123.0)

    def test_trace_release_state_distinguishes_rejection_pending_and_unverified(self):
        passed = EvalMetric("guard", 1.0, 1.0, True, "Guard passed")
        pending_domain = EvalMetric(
            "human_accuracy_review", 0.0, 1.0, False, "Awaiting domain review",
            {"measurement_state": "awaiting_domain_review"},
        )
        pending_human = EvalMetric(
            "human_accuracy_review", 0.0, 1.0, False, "Awaiting human review",
            {"measurement_state": "awaiting_human_review"},
        )
        rejected = EvalMetric(
            "publication_guard", 0.0, 1.0, False, "Citation missing",
            {"measurement_state": "rejected"},
        )
        unverified = EvalMetric(
            "faithfulness", 0.0, 1.0, False, "Faithfulness was not measured",
            {"measurement_state": "unverified"},
        )
        not_applicable = EvalMetric(
            "schema", 0.0, 1.0, False, "No structured output was supplied",
            {"measurement_state": "not_applicable"},
        )

        self.assertEqual(
            evaluation_release_state([passed, pending_domain])["state"],
            "awaiting_review",
        )
        self.assertEqual(
            evaluation_release_state([passed, pending_human])["state"],
            "awaiting_review",
        )
        self.assertEqual(
            evaluation_release_state([passed, pending_domain, rejected]),
            {
                "state": "rejected",
                "label": "Guard rejected",
                "explanation": "Citation missing",
            },
        )
        self.assertEqual(evaluation_release_state([])["state"], "unverified")
        self.assertEqual(evaluation_release_state([passed])["state"], "checks_passed")
        self.assertEqual(
            evaluation_release_state([passed, unverified]),
            {
                "state": "unverified",
                "label": "Evidence incomplete",
                "explanation": "Faithfulness was not measured",
            },
        )
        self.assertEqual(
            evaluation_release_state([passed, pending_domain, unverified])["state"],
            "unverified",
        )
        self.assertEqual(
            evaluation_release_state([passed, not_applicable])["state"],
            "unverified",
        )
        self.assertEqual(
            evaluation_release_state([unverified, rejected])["state"],
            "rejected",
        )

    def test_record_and_review_update_survive_restart(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "traces.jsonl"
            tracer = ArizeObservabilityTracer(str(path))
            tracer.record_trace(_record())
            self.assertEqual(
                [item.trace_id for item in tracer.traces_from_current_process()],
                ["trc_persisted"],
            )

            restarted = ArizeObservabilityTracer(str(path))
            self.assertEqual(len(restarted.traces), 1)
            self.assertEqual(restarted.traces[0].model_name, "27b@q1_0")
            self.assertEqual(restarted.traces[0].evaluations[0].metadata["measurement_state"], "awaiting_human_review")
            self.assertEqual(restarted.traces_from_current_process(), [])
            self.assertEqual(restarted.loaded_trace_ids, {"trc_persisted"})

            restarted.traces[0].metadata["human_review"] = {"decision": "pause"}
            restarted.persist()
            after_review = ArizeObservabilityTracer(str(path))
            self.assertEqual(after_review.traces[0].metadata["human_review"]["decision"], "pause")
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_corrupt_trace_store_fails_closed(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "traces.jsonl"
            path.write_text(json.dumps({"trace_id": "incomplete"}) + "\n")
            with self.assertRaisesRegex(ValueError, "Invalid trace record"):
                ArizeObservabilityTracer(str(path))

    def test_duplicate_trace_id_is_rejected(self):
        tracer = ArizeObservabilityTracer()
        tracer.record_trace(_record())
        with self.assertRaisesRegex(ValueError, "already recorded"):
            tracer.record_trace(_record())

    def test_concurrent_records_persist_without_loss_or_jsonl_corruption(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "traces.jsonl"
            tracer = ArizeObservabilityTracer(str(path))
            errors = []

            def write(index):
                try:
                    tracer.record_trace(_record(f"trc_concurrent_{index:02d}"))
                except Exception as exc:  # pragma: no cover - asserted below
                    errors.append(str(exc))

            workers = [threading.Thread(target=write, args=(index,)) for index in range(20)]
            for worker in workers:
                worker.start()
            for worker in workers:
                worker.join(timeout=5)

            self.assertEqual(errors, [])
            self.assertTrue(all(not worker.is_alive() for worker in workers))
            self.assertEqual(len(tracer.snapshot()), 20)
            restarted = ArizeObservabilityTracer(str(path))
            self.assertEqual(len(restarted.snapshot()), 20)
            self.assertEqual(
                {trace.trace_id for trace in restarted.snapshot()},
                {f"trc_concurrent_{index:02d}" for index in range(20)},
            )


if __name__ == "__main__":
    unittest.main()
