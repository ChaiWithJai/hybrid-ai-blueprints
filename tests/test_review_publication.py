import copy
import unittest
from pathlib import Path

from core.review_publication import finalize_review_publication, prepare_review_publication


ROOT = Path(__file__).resolve().parents[1]
ROSTER = {
    "reviewers": [{
        "reviewer_id": "reviewer.one",
        "role": "qualified_deal_source_reviewer",
        "qualification": "M&A source review experience.",
        "buzz_pubkey": "b" * 64,
        "active": True,
    }],
}


def record():
    return {
        "review_id": "review-one",
        "reviewer_id": "reviewer.one",
        "reviewer_role": "qualified_deal_source_reviewer",
        "qualification": "M&A source review experience.",
        "blinded_to_model": True,
        "packet_sha256": "a" * 64,
        "reviewer_pubkey": "b" * 64,
        "buzz_event_id": "0" * 64,
        "reviewed_at": "2026-08-15T08:30:00+00:00",
        "drafts": [{
            "draft_id": "draft-one",
            "source_sha256s": ["c" * 64],
            "source_context_checked": True,
            "decision": "approve",
            "final_question": "What is the final consideration?",
            "answer_policy": "supported",
            "supporting_citations": ["[filing.htm#html:block:00100]"],
            "confusable_citations": [],
            "expected_claims": [{
                "text": "The final consideration is $42.00 per share.",
                "citations": ["[filing.htm#html:block:00100]"],
            }],
            "absence_basis": "",
            "rationale": "The operative agreement supports the claim.",
        }],
    }


class ReviewPublicationTests(unittest.TestCase):
    def test_verified_event_finalizes_the_unsigned_record(self):
        unsigned = record()
        prepared = prepare_review_publication(
            ROOT, unsigned, "candidate_source_review", roster=ROSTER,
        )
        event_id = "d" * 64
        event = {
            "id": event_id,
            "pubkey": "b" * 64,
            "content": prepared["content"],
        }
        finalized = finalize_review_publication(
            unsigned, "candidate_source_review", event, prepared["expected_pubkey"],
        )
        self.assertEqual(finalized["buzz_event_id"], event_id)
        self.assertEqual(unsigned["buzz_event_id"], "0" * 64)

    def test_wrong_roster_key_or_forged_event_cannot_finalize(self):
        unsigned = record()
        wrong = copy.deepcopy(unsigned)
        wrong["reviewer_pubkey"] = "f" * 64
        with self.assertRaisesRegex(ValueError, "differs from the approved roster"):
            prepare_review_publication(
                ROOT, wrong, "candidate_source_review", roster=ROSTER,
            )
        prepared = prepare_review_publication(
            ROOT, unsigned, "candidate_source_review", roster=ROSTER,
        )
        forged = {
            "id": "d" * 64,
            "pubkey": "f" * 64,
            "content": prepared["content"],
        }
        with self.assertRaisesRegex(ValueError, "Buzz event signer differs"):
            finalize_review_publication(
                unsigned, "candidate_source_review", forged, prepared["expected_pubkey"],
            )


if __name__ == "__main__":
    unittest.main()
