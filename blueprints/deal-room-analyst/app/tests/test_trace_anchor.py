import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from core.arize_evals import ArizeObservabilityTracer, ArizeTraceRecord
from core.trace_anchor import canonical_anchor_content, validate_trace_anchor_receipt
from tests.nostr_signing import sign_event


class TraceAnchorTests(unittest.TestCase):
    @staticmethod
    def trace(trace_id):
        return ArizeTraceRecord(
            trace_id=trace_id,
            session_id="anchor-fixture",
            timestamp=1.0,
            query="anchor",
            response="anchor fixture",
            model_name="deterministic_baseline",
            routed_tier="DETERMINISTIC_BASELINE",
            total_tokens=None,
            prompt_tokens=None,
            completion_tokens=None,
            total_latency_ms=0.0,
            energy_per_token_mwh=None,
            total_energy_mwh=None,
            vram_peak_gb=None,
        )

    def fixture(self, root: Path):
        store = root / "traces.jsonl"
        tracer = ArizeObservabilityTracer(str(store))
        tracer.record_trace(self.trace("trc_anchor_fixture"))
        status = tracer.storage_status()
        anchor = {
            "ledger_format": status["format"],
            "entry_count": status["entry_count"],
            "head_sha256": status["head_sha256"],
        }
        content = canonical_anchor_content(anchor)
        event = sign_event({
            "created_at": 1786846000,
            "kind": 9,
            "tags": [["h", "anchor-channel"]],
            "content": content,
        }, "1" * 64)
        receipt = {
            "verification_kind": "signed_buzz_trace_anchor_receipt.v1",
            "anchor": anchor,
            "content_sha256": hashlib.sha256(content.encode()).hexdigest(),
            "channel_id": "anchor-channel",
            "event_id": event["id"],
            "signer_pubkey": event["pubkey"],
            "relay_url": "ws://127.0.0.1:3030",
            "same_host_loopback_relay": True,
            "external_trust_domain": False,
            "raw_buzz_event": event,
        }
        return store, receipt

    def test_signed_anchor_binds_current_ledger_head_without_external_claim(self):
        with tempfile.TemporaryDirectory() as folder:
            store, receipt = self.fixture(Path(folder))
            result = validate_trace_anchor_receipt(receipt, trace_store=store)
        self.assertTrue(result["passed"])
        self.assertTrue(result["current_head_anchored"])
        self.assertFalse(result["externally_anchored"])

    def test_event_content_tamper_fails(self):
        with tempfile.TemporaryDirectory() as folder:
            store, receipt = self.fixture(Path(folder))
            receipt["raw_buzz_event"]["content"] += "tampered"
            result = validate_trace_anchor_receipt(receipt, trace_store=store)
        self.assertFalse(result["passed"])
        self.assertTrue(any("event" in error for error in result["errors"]))

    def test_rewritten_ledger_cannot_reuse_signed_anchor(self):
        with tempfile.TemporaryDirectory() as folder:
            store, receipt = self.fixture(Path(folder))
            line = json.loads(store.read_text(encoding="utf-8"))
            line["entry_sha256"] = "0" * 64
            store.write_text(json.dumps(line) + "\n", encoding="utf-8")
            result = validate_trace_anchor_receipt(receipt, trace_store=store)
        self.assertFalse(result["passed"])
        self.assertTrue(any("ledger" in error for error in result["errors"]))

    def test_new_entries_preserve_prefix_but_make_current_head_unanchored(self):
        with tempfile.TemporaryDirectory() as folder:
            store, receipt = self.fixture(Path(folder))
            tracer = ArizeObservabilityTracer(str(store))
            tracer.record_trace(self.trace("trc_after_anchor"))
            result = validate_trace_anchor_receipt(receipt, trace_store=store)
        self.assertTrue(result["passed"])
        self.assertFalse(result["current_head_anchored"])
        self.assertEqual(result["anchored_prefix_entry_count"], 1)
        self.assertEqual(result["current_entry_count"], 2)


if __name__ == "__main__":
    unittest.main()
