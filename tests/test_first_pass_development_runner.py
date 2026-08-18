import tempfile
import unittest
from pathlib import Path

from scripts.run_first_pass_development import investment_screens, source_scope, summarize_result
from scripts.run_public_deal_battletest import summarize_chat_result


class FirstPassDevelopmentRunnerTests(unittest.TestCase):
    def test_groups_registered_questions_by_deal_without_calling_it_accuracy(self):
        screens = investment_screens({"cases": [
            {"deal_id": "deal-a", "question": "Question one?"},
            {"deal_id": "deal-a", "question": "Question two?"},
            {"deal_id": "deal-b", "question": "Question three?"},
        ]})
        self.assertEqual(set(screens), {"deal-a", "deal-b"})
        self.assertIn("1. Question one?", screens["deal-a"])
        self.assertIn("2. Question two?", screens["deal-a"])
        self.assertIn("complete first-pass contract", screens["deal-a"])

    def test_summary_preserves_fallback_and_rejected_trace_identity(self):
        summary = summarize_result(201, {
            "acceptance_state": "evidence_safe_fallback",
            "artifact_mode": "evidence_safe_fallback",
            "trace_id": "trc_fallback",
            "model_failure_trace_id": "trc_failed",
            "draft_event_id": "event-fallback",
            "citations": ["[cim.md#node:terms]"],
        }, 10.0)
        self.assertEqual(summary["trace_id"], "trc_fallback")
        self.assertEqual(summary["model_failure_trace_id"], "trc_failed")
        self.assertEqual(summary["acceptance_state"], "evidence_safe_fallback")

    def test_source_scope_rejects_cross_deal_files(self):
        manifest = {"documents": [
            {"room": "deal-a", "filename": "deal-a.pdf"},
            {"room": "deal-b", "filename": "deal-b.pdf"},
        ]}
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "deal-a.pdf").write_text("a")
            (root / "deal-b.pdf").write_text("b")
            result = source_scope(root, "deal-a", manifest)
        self.assertFalse(result["passed"])
        self.assertEqual(result["unexpected_files"], ["deal-b.pdf"])

    def test_battletest_summary_does_not_count_signed_rejection_as_answer(self):
        summary = summarize_chat_result(201, {
            "event_id": "q" * 64,
            "agent_reply": {
                "answer_state": "rejected",
                "detail": "publication guard failed",
                "event_id": "r" * 64,
                "trace_id": "trc_123456789abc",
                "canonical_path": "/rooms/room/discussion?event=" + "r" * 64,
            },
        }, "room", 10.0)
        self.assertEqual(summary["answer_state"], "rejected")
        self.assertEqual(summary["error"], "publication guard failed")
        self.assertEqual(summary["response"], "")
        self.assertIsNone(summary["model"])

    def test_battletest_summary_marks_only_nonempty_201_reply_accepted(self):
        summary = summarize_chat_result(201, {
            "event_id": "q" * 64,
            "agent_reply": {
                "response": "Source-bound answer",
                "model": "27b@q1_0",
                "event_id": "a" * 64,
                "trace_id": "trc_123456789abc",
            },
        }, "room", 10.0)
        self.assertEqual(summary["answer_state"], "accepted")
        self.assertIsNone(summary["error"])


if __name__ == "__main__":
    unittest.main()
