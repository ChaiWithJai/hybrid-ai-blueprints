import unittest
from copy import deepcopy
from dataclasses import replace
from unittest import mock

from core.arize_evals import ArizeTraceRecord
import server as server_module
from server import (
    VaultHTTPRequestHandler,
    local_review_canvas_content,
    local_review_message_content,
    restore_trace_bound_first_pass,
    restore_trace_bound_local_review,
)


AGENT = "a" * 64
HUMAN = "b" * 64
ORIGINAL_EVENT = "1" * 64
COPIED_EVENT = "2" * 64
TRACE_ID = "trc_bound123456"
ROOM_ID = "project_titan_lbo"
REVIEW_EVENT = "3" * 64
CANVAS_EVENT = "4" * 64
OPERATOR = "b" * 64
MARKDOWN = "## Recommendation\n\nRecommendation: PAUSE [cim.md#node:terms]"
SOURCE_CLASS = "synthetic_engineering_fixture"
PROVENANCE = "c" * 64
SOURCE_SNAPSHOT = "d" * 64


def event(event_id=ORIGINAL_EVENT, pubkey=AGENT, trace=TRACE_ID, *, verified=True):
    trace_attribute = f" trace={trace}" if trace else ""
    return {
        "id": event_id,
        "pubkey": pubkey,
        "signature_verified": verified,
        "content": (
            "<!-- prism:first-pass-draft model=27b@q1_0 recommendation=pause "
            f"guard=evidence_claim_v7{trace_attribute} source_class={SOURCE_CLASS} "
            f"provenance={PROVENANCE} source_snapshot={SOURCE_SNAPSHOT} -->\n"
            "# First pass underwriting draft\n\n"
            f"{MARKDOWN}"
        ),
    }


def trace(event_id=ORIGINAL_EVENT):
    return ArizeTraceRecord(
        trace_id=TRACE_ID,
        session_id=ROOM_ID,
        timestamp=1.0,
        query="first_pass_underwriting",
        response=MARKDOWN,
        model_name="27b@q1_0",
        routed_tier="LOCAL_BONSAI_27B",
        total_tokens=10,
        prompt_tokens=8,
        completion_tokens=2,
        total_latency_ms=10.0,
        energy_per_token_mwh=None,
        total_energy_mwh=None,
        vram_peak_gb=None,
        metadata={
            "product_job": "first_pass_underwriting",
            "provider_id": "local_bonsai",
            "guard_version": "evidence_claim_v7",
            "draft_event_id": event_id,
            "citation_count": 1,
            "investment_screen": "Decide whether to advance.",
            "source_classification": SOURCE_CLASS,
            "source_provenance_sha256": PROVENANCE,
            "source_snapshot_sha256": SOURCE_SNAPSHOT,
        },
    )


def review():
    return {
        "review_actor": "local_operator",
        "reviewer_pubkey": OPERATOR,
        "authentication_scope": "local_operator_bridge",
        "benchmark_domain_review": False,
        "decision": "pause",
        "useful_starting_point": True,
        "critical_corrections": 0,
        "major_corrections": 1,
        "notes": "Confirm the leverage wording.",
        "review_event_id": REVIEW_EVENT,
        "canvas_event_id": CANVAS_EVENT,
        "canonical_path": f"/rooms/{ROOM_ID}/digest",
    }


def restored_draft():
    return restore_trace_bound_first_pass(
        [event()], [trace()], room_id=ROOM_ID, agent_pubkey=AGENT,
    )


def review_events(draft, claimed_review):
    return {
        REVIEW_EVENT: {
            "id": REVIEW_EVENT,
            "pubkey": OPERATOR,
            "kind": 9,
            "content": local_review_message_content(draft, claimed_review),
        },
        CANVAS_EVENT: {
            "id": CANVAS_EVENT,
            "pubkey": OPERATOR,
            "kind": 40100,
            "content": local_review_canvas_content(
                "Project Titan: $2.4B Sponsor-Backed LBO", draft, claimed_review,
            ),
        },
    }


class TraceBoundFirstPassRestorationTests(unittest.TestCase):
    def restore(self, messages, traces):
        return restore_trace_bound_first_pass(
            messages, traces, room_id=ROOM_ID, agent_pubkey=AGENT,
        )

    def test_restores_exact_agent_event_trace_binding(self):
        restored = self.restore([event()], [trace()])
        self.assertEqual(restored["draft_event_id"], ORIGINAL_EVENT)
        self.assertEqual(restored["trace_id"], TRACE_ID)
        self.assertEqual(restored["restoration_verification"]["state"], "verified")

    def test_human_signed_draft_marker_is_not_a_bonsai_draft(self):
        self.assertIsNone(self.restore([event(pubkey=HUMAN)], [trace()]))

    def test_unverified_message_is_rejected_even_when_content_matches(self):
        self.assertIsNone(self.restore([event(verified=False)], [trace()]))

    def test_copied_newer_event_cannot_shadow_original_trace_event(self):
        restored = self.restore(
            [event(), event(event_id=COPIED_EVENT)],
            [trace()],
        )
        self.assertEqual(restored["draft_event_id"], ORIGINAL_EVENT)

    def test_marker_without_trace_uses_unique_trace_event_binding(self):
        restored = self.restore([event(trace=None)], [trace()])
        self.assertEqual(restored["trace_id"], TRACE_ID)
        self.assertEqual(restored["draft_event_id"], ORIGINAL_EVENT)

    def test_ambiguous_event_binding_is_rejected(self):
        duplicate = replace(trace(), trace_id="trc_duplicate123")
        self.assertIsNone(self.restore([event(trace=None)], [trace(), duplicate]))

    def test_trace_semantic_mismatches_are_rejected(self):
        variants = {
            "room": replace(trace(), session_id="another_room"),
            "model": replace(trace(), model_name="another-model"),
            "response": replace(trace(), response="different response"),
            "query": replace(trace(), query="different_job"),
            "event": trace(COPIED_EVENT),
            "provider": replace(
                trace(), metadata={**trace().metadata, "provider_id": "cloud"},
            ),
            "guard": replace(
                trace(), metadata={**trace().metadata, "guard_version": "old_guard"},
            ),
            "source class": replace(
                trace(), metadata={
                    **trace().metadata,
                    "source_classification": "operator_selected_local_folder",
                },
            ),
            "provenance": replace(
                trace(), metadata={
                    **trace().metadata,
                    "source_provenance_sha256": "e" * 64,
                },
            ),
            "source snapshot": replace(
                trace(), metadata={
                    **trace().metadata,
                    "source_snapshot_sha256": "f" * 64,
                },
            ),
        }
        for name, altered_trace in variants.items():
            with self.subTest(name=name):
                self.assertIsNone(self.restore([event()], [altered_trace]))

    def test_current_room_provenance_or_snapshot_drift_blocks_restoration(self):
        self.assertIsNone(restore_trace_bound_first_pass(
            [event()], [trace()], room_id=ROOM_ID, agent_pubkey=AGENT,
            current_provenance={
                "classification": SOURCE_CLASS,
                "binding_sha256": "e" * 64,
            },
            current_source_snapshot=SOURCE_SNAPSHOT,
        ))
        self.assertIsNone(restore_trace_bound_first_pass(
            [event()], [trace()], room_id=ROOM_ID, agent_pubkey=AGENT,
            current_provenance={
                "classification": SOURCE_CLASS,
                "binding_sha256": PROVENANCE,
            },
            current_source_snapshot="f" * 64,
        ))


class TraceBoundLocalReviewRestorationTests(unittest.TestCase):
    def test_fallback_review_is_never_named_a_first_pass_brief(self):
        draft = {
            **restored_draft(),
            "artifact_mode": "evidence_safe_fallback",
            "authored_by": "deterministic_evidence_renderer",
            "model_failure_trace_id": "trc_rejected",
        }
        claimed_review = review()
        message = local_review_message_content(draft, claimed_review)
        canvas = local_review_canvas_content("Test room", draft, claimed_review)
        self.assertIn("Source evidence packet reviewed", message)
        self.assertIn("Review subject: deterministic source evidence packet", message)
        self.assertNotIn("First pass reviewed", message)
        self.assertIn("Reviewed source evidence packet", canvas)
        self.assertIn("does not convert it into an underwriting brief", canvas)

    def test_review_survives_process_cache_loss_from_signed_buzz_events(self):
        claimed_review = review()
        bound_trace = trace()
        bound_trace.metadata["human_review"] = claimed_review
        draft = restored_draft()
        raw_events = review_events(draft, claimed_review)

        class FakeBuzz:
            def verified_messages(self, _channel_id):
                return [event()]

            def status(self):
                return {"agent_pubkey": AGENT, "operator_pubkey": OPERATOR}

            def events_by_ids(self, event_ids, *, channel_id=None):
                self.assert_channel = channel_id
                return {event_id: raw_events[event_id] for event_id in event_ids}

        class FakeTracer:
            def snapshot(self):
                return [bound_trace]

        with (
            mock.patch.object(server_module, "global_buzz", FakeBuzz()),
            mock.patch.object(server_module, "global_tracer", FakeTracer()),
            mock.patch.object(
                server_module, "inspect_local_deal_room",
                return_value={
                    "preview": {"preview_sha256": SOURCE_SNAPSHOT},
                    "documents": [],
                },
            ),
            mock.patch.object(
                server_module, "build_evidence_inventory",
                return_value={
                    "scope_version": "current_parser_inventory_v1",
                    "source_snapshot_sha256": SOURCE_SNAPSHOT,
                    "inventory_sha256": "e" * 64,
                    "document_count": 1,
                    "parsed_node_count": 1,
                    "searchable_node_count": 1,
                    "citation_sources": {"[cim.md#node:terms]": "f" * 64},
                },
            ),
            mock.patch.object(
                server_module, "source_provenance_binding",
                return_value={
                    "classification": SOURCE_CLASS,
                    "binding_sha256": PROVENANCE,
                },
            ),
        ):
            restored = VaultHTTPRequestHandler._first_pass_record(
                object(), ROOM_ID, {"channel_id": "channel-test"},
            )
        self.assertEqual(restored["review"]["decision"], "pause")
        self.assertTrue(restored["review"]["restored_from_buzz"])
        self.assertEqual(restored["review"]["signature_verification"]["state"], "verified")

    def test_review_rejects_metadata_or_signed_event_drift(self):
        draft = restored_draft()
        claimed_review = review()
        originals = review_events(draft, claimed_review)
        mutations = {
            "review author": lambda r, e: e[REVIEW_EVENT].update(pubkey=AGENT),
            "review content": lambda r, e: e[REVIEW_EVENT].update(content="changed"),
            "canvas content": lambda r, e: e[CANVAS_EVENT].update(content="changed"),
            "canvas kind": lambda r, e: e[CANVAS_EVENT].update(kind=9),
            "decision": lambda r, e: r.update(decision="unknown"),
            "review event id": lambda r, e: r.update(review_event_id="invalid"),
        }
        for name, mutate in mutations.items():
            with self.subTest(name=name):
                altered_review = deepcopy(claimed_review)
                altered_events = deepcopy(originals)
                mutate(altered_review, altered_events)
                with self.assertRaisesRegex(Exception, "local review"):
                    restore_trace_bound_local_review(
                        altered_review,
                        draft=draft,
                        room_id=ROOM_ID,
                        room_name="Project Titan: $2.4B Sponsor-Backed LBO",
                        operator_pubkey=OPERATOR,
                        review_event=altered_events[REVIEW_EVENT],
                        canvas_event=altered_events[CANVAS_EVENT],
                    )


if __name__ == "__main__":
    unittest.main()
