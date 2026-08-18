import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from core.candidate_source_review import (
    FORBIDDEN_PACKET_KEYS,
    build_candidate_source_review_packet,
    compare_source_reviews,
    evaluate_source_review_state,
    packet_sha256,
    validate_source_adjudication,
    validate_source_review_submission,
)
from core.review_signatures import review_attestation_content
from tests.roster_fixtures import reviewer_pubkey, signed_roster


ROOT = Path(__file__).resolve().parents[1]


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()
TEST_ROSTER = signed_roster("source_review", [
        {
            "reviewer_id": "reviewer-a",
            "display_name": "Reviewer A",
            "role": "qualified_deal_source_reviewer",
            "qualification": "Experienced M&A source-document reviewer.",
            "approved_at": "2026-08-15T06:00:00+00:00",
            "active": True,
        },
        {
            "reviewer_id": "reviewer-b",
            "display_name": "Reviewer B",
            "role": "qualified_deal_source_reviewer",
            "qualification": "Experienced M&A source-document reviewer.",
            "approved_at": "2026-08-15T06:00:00+00:00",
            "active": True,
        },
        {
            "reviewer_id": "principal-c",
            "display_name": "Principal C",
            "role": "principal_source_reviewer",
            "qualification": "M&A benchmark principal reviewer.",
            "approved_at": "2026-08-15T06:00:00+00:00",
            "active": True,
        },
])


def all_keys(value):
    if isinstance(value, dict):
        keys = set(value)
        for item in value.values():
            keys.update(all_keys(item))
        return keys
    if isinstance(value, list):
        keys = set()
        for item in value:
            keys.update(all_keys(item))
        return keys
    return set()


def review_record(draft):
    citations = [
        next(
            item["citation"] for item in draft["evidence_options"]
            if item["source_sha256"] == source["sha256"]
        )
        for source in draft["sources"]
    ]
    return {
        "draft_id": draft["draft_id"],
        "source_sha256s": sorted(item["sha256"] for item in draft["sources"]),
        "source_context_checked": True,
        "decision": "approve",
        "final_question": draft["provisional_question"],
        "answer_policy": "supported",
        "supporting_citations": citations,
        "confusable_citations": [],
        "expected_claims": [{"text": "Source-grounded expected claim.", "citations": citations}],
        "absence_basis": "",
        "rationale": "The cited source context supports this question and claim.",
    }


def submission(packet, reviewer_id, drafts=None):
    selected = packet["drafts"][:1] if drafts is None else drafts
    pubkeys = {name: reviewer_pubkey(name) for name in ("reviewer-a", "reviewer-b")}
    event_ids = {"reviewer-a": "1" * 64, "reviewer-b": "2" * 64}
    return {
        "review_id": f"review-{reviewer_id}",
        "reviewer_id": reviewer_id,
        "reviewer_role": "qualified_deal_source_reviewer",
        "qualification": "Experienced M&A source-document reviewer.",
        "blinded_to_model": True,
        "packet_sha256": packet_sha256(packet),
        "reviewer_pubkey": pubkeys[reviewer_id],
        "buzz_event_id": event_ids[reviewer_id],
        "reviewed_at": "2026-08-15T07:00:00+00:00",
        "drafts": [review_record(item) for item in selected],
    }


def signed_events(*records, kind="candidate_source_review"):
    return {
        record["buzz_event_id"]: {
            "id": record["buzz_event_id"],
            "pubkey": record["reviewer_pubkey"],
            "content": review_attestation_content(kind, record),
        }
        for record in records
    }


class CandidateSourceReviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.packet = build_candidate_source_review_packet(ROOT)

    def test_packet_is_model_blind_hash_bound_and_complete(self):
        self.assertEqual(self.packet["draft_count"], 319)
        self.assertEqual(self.packet["candidate_deal_count"], 29)
        self.assertTrue(self.packet["blinded_to_model"])
        self.assertFalse(FORBIDDEN_PACKET_KEYS & all_keys(self.packet))
        self.assertEqual(len(packet_sha256(self.packet)), 64)

    def test_saved_packet_matches_current_candidate_registry(self):
        saved = json.loads(
            (ROOT / "evidence" / "candidate-source-review-packet-v1.json").read_text()
        )
        self.assertEqual(saved, self.packet)

    def test_tampered_packet_source_and_citation_are_rejected(self):
        review = submission(self.packet, "reviewer-a")
        review["packet_sha256"] = "0" * 64
        review["drafts"][0]["source_sha256s"] = ["1" * 64]
        review["drafts"][0]["supporting_citations"] = ["[invented#anchor]"]
        review["drafts"][0]["expected_claims"][0]["citations"] = ["[invented#anchor]"]
        errors = validate_source_review_submission(
            ROOT, self.packet, review, TEST_ROSTER, signed_events(review)
        )
        self.assertTrue(any("not bound" in item for item in errors))
        self.assertTrue(any("source hashes differ" in item for item in errors))
        self.assertTrue(any("packet evidence options" in item for item in errors))

    def test_cross_document_review_requires_support_from_both_sources(self):
        draft = next(item for item in self.packet["drafts"] if len(item["sources"]) == 2)
        review = submission(self.packet, "reviewer-a", [draft])
        kept = review["drafts"][0]["supporting_citations"][:1]
        review["drafts"][0]["supporting_citations"] = kept
        review["drafts"][0]["expected_claims"][0]["citations"] = kept
        errors = validate_source_review_submission(
            ROOT, self.packet, review, TEST_ROSTER, signed_events(review)
        )
        self.assertTrue(any("cite every admitted source" in item for item in errors))

    def test_single_reviewer_cannot_make_a_draft_eligible(self):
        result = compare_source_reviews(
            ROOT, self.packet, [submission(self.packet, "reviewer-a")], TEST_ROSTER,
            signed_events(submission(self.packet, "reviewer-a")),
        )
        self.assertTrue(result["valid"], result["errors"])
        self.assertEqual(result["eligible_draft_count"], 0)
        self.assertEqual(result["pending_draft_count"], 319)

    def test_self_asserted_qualification_cannot_bypass_empty_roster(self):
        review = submission(self.packet, "reviewer-a")
        errors = validate_source_review_submission(
            ROOT,
            self.packet,
            review,
            {"version": "test", "status": "domain_owner_managed", "reviewers": []},
            {},
        )
        self.assertTrue(any("not active on the domain-owner-managed roster" in item for item in errors))

    def test_duplicate_reviewer_cannot_satisfy_two_reviewer_gate(self):
        first = submission(self.packet, "reviewer-a")
        second = copy.deepcopy(first)
        second["review_id"] = "review-reviewer-a-second"
        second["buzz_event_id"] = "9" * 64
        result = compare_source_reviews(
            ROOT, self.packet, [first, second], TEST_ROSTER, signed_events(first, second)
        )
        self.assertFalse(result["valid"])
        self.assertTrue(any("one reviewer submitted more than one" in item for item in result["errors"]))
        self.assertEqual(result["eligible_draft_count"], 0)

    def test_missing_or_forged_buzz_attestation_is_rejected(self):
        review = submission(self.packet, "reviewer-a")
        missing = validate_source_review_submission(
            ROOT, self.packet, review, TEST_ROSTER, {}
        )
        self.assertTrue(any("signed Buzz attestation was not supplied" in item for item in missing))
        forged = signed_events(review)
        forged[review["buzz_event_id"]]["pubkey"] = "f" * 64
        errors = validate_source_review_submission(
            ROOT, self.packet, review, TEST_ROSTER, forged
        )
        self.assertTrue(any("Buzz event signer differs" in item for item in errors))

    def test_two_agreeing_reviewers_make_only_the_draft_eligible(self):
        reviews = [submission(self.packet, "reviewer-a"), submission(self.packet, "reviewer-b")]
        result = compare_source_reviews(
            ROOT,
            self.packet,
            reviews,
            TEST_ROSTER,
            signed_events(*reviews),
        )
        self.assertTrue(result["valid"], result["errors"])
        self.assertEqual(result["eligible_draft_count"], 1)
        self.assertEqual(result["benchmark_cases_registered"], 0)
        state = evaluate_source_review_state(
            ROOT, self.packet, reviews, reviewer_roster=TEST_ROSTER,
            signed_events=signed_events(*reviews),
        )
        self.assertTrue(state["promotion_ready"])
        self.assertEqual(state["eligible_for_case_authoring_count"], 1)
        self.assertEqual(state["benchmark_cases_registered"], 0)

    def test_two_agreeing_rejections_do_not_make_a_draft_eligible(self):
        reviews = [submission(self.packet, "reviewer-a"), submission(self.packet, "reviewer-b")]
        for review in reviews:
            decision = review["drafts"][0]
            decision.update({
                "decision": "reject",
                "final_question": "",
                "answer_policy": "unresolved",
                "supporting_citations": [],
                "confusable_citations": [],
                "expected_claims": [],
                "absence_basis": "",
                "rationale": "The source cannot support a stable benchmark question.",
            })
        result = compare_source_reviews(
            ROOT, self.packet, reviews, TEST_ROSTER, signed_events(*reviews)
        )
        self.assertTrue(result["valid"], result["errors"])
        self.assertEqual(result["eligible_draft_count"], 0)
        self.assertEqual(result["rejected_draft_count"], 1)
        state = evaluate_source_review_state(
            ROOT, self.packet, reviews, reviewer_roster=TEST_ROSTER,
            signed_events=signed_events(*reviews),
        )
        self.assertFalse(state["promotion_ready"])
        self.assertEqual(state["eligible_for_case_authoring_count"], 0)
        self.assertEqual(state["rejected_draft_count"], 1)

    def test_approval_with_unresolved_policy_is_not_valid_review(self):
        review = submission(self.packet, "reviewer-a")
        review["drafts"][0]["answer_policy"] = "unresolved"
        errors = validate_source_review_submission(
            ROOT, self.packet, review, TEST_ROSTER, signed_events(review)
        )
        self.assertTrue(any("must be case-authorable" in item for item in errors))

    def test_disagreement_requires_a_distinct_principal(self):
        first = submission(self.packet, "reviewer-a")
        second = submission(self.packet, "reviewer-b")
        second["drafts"][0]["expected_claims"][0]["text"] = "A materially different claim."
        comparison = compare_source_reviews(
            ROOT, self.packet, [first, second], TEST_ROSTER, signed_events(first, second)
        )
        self.assertTrue(comparison["valid"], comparison["errors"])
        self.assertTrue(comparison["principal_adjudication_required"])
        self.assertEqual(comparison["disagreement_count"], 1)
        disagreement = comparison["disagreements"][0]
        adjudication = {
            "adjudication_id": "source-adjudication-1",
            "principal_reviewer_id": "principal-c",
            "qualification": "M&A benchmark principal reviewer.",
            "packet_sha256": packet_sha256(self.packet),
            "reviewer_pubkey": reviewer_pubkey("principal-c"),
            "buzz_event_id": "3" * 64,
            "adjudicated_at": "2026-08-15T08:00:00+00:00",
            "decisions": [{
                "draft_id": disagreement["draft_id"],
                "selected_review_id": disagreement["review_ids"][0],
                "rationale": "This review follows the filing's final terms.",
            }],
        }
        self.assertEqual(
            validate_source_adjudication(
                ROOT, self.packet, comparison, adjudication, TEST_ROSTER,
                signed_events(adjudication, kind="candidate_source_adjudication"),
            ), []
        )
        adjudication["principal_reviewer_id"] = "reviewer-a"
        adjudication["decisions"][0]["selected_review_id"] = "unknown-review"
        errors = validate_source_adjudication(
            ROOT, self.packet, comparison, adjudication, TEST_ROSTER,
            signed_events(adjudication, kind="candidate_source_adjudication"),
        )
        self.assertTrue(any("principal must be distinct" in item for item in errors))
        self.assertTrue(any("must select a disagreeing review" in item for item in errors))

    def test_principal_selection_of_rejection_resolves_without_eligibility(self):
        first = submission(self.packet, "reviewer-a")
        second = submission(self.packet, "reviewer-b")
        second["drafts"][0].update({
            "decision": "reject",
            "final_question": "",
            "answer_policy": "unresolved",
            "supporting_citations": [],
            "confusable_citations": [],
            "expected_claims": [],
            "absence_basis": "",
            "rationale": "The source cannot support a stable benchmark question.",
        })
        comparison = compare_source_reviews(
            ROOT, self.packet, [first, second], TEST_ROSTER, signed_events(first, second)
        )
        self.assertTrue(comparison["valid"], comparison["errors"])
        self.assertEqual(comparison["eligible_draft_count"], 0)
        adjudication = {
            "adjudication_id": "source-adjudication-reject",
            "principal_reviewer_id": "principal-c",
            "qualification": "M&A benchmark principal reviewer.",
            "packet_sha256": packet_sha256(self.packet),
            "reviewer_pubkey": reviewer_pubkey("principal-c"),
            "buzz_event_id": "4" * 64,
            "adjudicated_at": "2026-08-15T08:00:00+00:00",
            "decisions": [{
                "draft_id": comparison["disagreements"][0]["draft_id"],
                "selected_review_id": second["review_id"],
                "rationale": "The rejection correctly identifies insufficient support.",
            }],
        }
        state = evaluate_source_review_state(
            ROOT, self.packet, [first, second], adjudication,
            reviewer_roster=TEST_ROSTER,
            signed_events={
                **signed_events(first, second),
                **signed_events(adjudication, kind="candidate_source_adjudication"),
            },
        )
        self.assertTrue(state["validation_passed"], state["errors"])
        self.assertFalse(state["promotion_ready"])
        self.assertEqual(state["eligible_for_case_authoring_count"], 0)
        self.assertEqual(state["rejected_draft_count"], 1)

    def test_packet_rejects_candidate_registry_tamper(self):
        with tempfile.TemporaryDirectory() as folder:
            temp_root = Path(folder)
            (temp_root / "benchmarks" / "first_pass").mkdir(parents=True)
            for name in (
                "candidate_question_drafts.v1.json",
                "candidate_deal_sources.v1.json",
                "candidate_companion_sources.v1.json",
            ):
                source = ROOT / "benchmarks" / "first_pass" / name
                (temp_root / "benchmarks" / "first_pass" / name).write_bytes(source.read_bytes())
            registry = temp_root / "benchmarks" / "first_pass" / "candidate_deal_sources.v1.json"
            registry.write_text(registry.read_text() + " ")
            tampered = build_candidate_source_review_packet(temp_root)
            self.assertNotEqual(
                tampered["candidate_sources_sha256"], self.packet["candidate_sources_sha256"]
            )

    def test_packet_binds_companion_source_registry(self):
        path = ROOT / "benchmarks" / "first_pass" / "candidate_companion_sources.v1.json"
        self.assertEqual(self.packet["candidate_companion_sources_sha256"], sha256(path))


if __name__ == "__main__":
    unittest.main()
