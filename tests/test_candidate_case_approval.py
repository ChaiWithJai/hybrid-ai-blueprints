import copy
import hashlib
import json
import unittest
from pathlib import Path

from core.candidate_case_approval import (
    build_candidate_case_authoring_material,
    candidate_case_approval_report,
    validate_candidate_case_approval,
)
from core.candidate_source_review import build_candidate_source_review_packet, packet_sha256
from core.review_signatures import review_attestation_content
from tests.roster_fixtures import reviewer_pubkey, signed_roster


ROOT = Path(__file__).resolve().parents[1]
ROSTER = signed_roster("source_review", [
        {
            "reviewer_id": "reviewer-a", "display_name": "Reviewer A",
            "role": "qualified_deal_source_reviewer",
            "qualification": "Experienced M&A source reviewer.",
            "approved_at": "2026-08-15T06:00:00+00:00", "active": True,
        },
        {
            "reviewer_id": "reviewer-b", "display_name": "Reviewer B",
            "role": "qualified_deal_source_reviewer",
            "qualification": "Experienced M&A source reviewer.",
            "approved_at": "2026-08-15T06:00:00+00:00", "active": True,
        },
        {
            "reviewer_id": "domain-owner", "display_name": "Domain Owner",
            "role": "domain_case_owner",
            "qualification": "Accountable M&A benchmark domain owner.",
            "approved_at": "2026-08-15T06:00:00+00:00", "active": True,
        },
])


def signed_event(record, kind):
    return {
        "id": record["buzz_event_id"],
        "pubkey": record["reviewer_pubkey"],
        "content": review_attestation_content(kind, record),
    }


class CandidateCaseApprovalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.packet = build_candidate_source_review_packet(ROOT)
        cls.draft = cls.packet["drafts"][0]

    def records(self):
        options = [
            next(
                item for item in self.draft["evidence_options"]
                if item["source_sha256"] == source["sha256"]
            )
            for source in self.draft["sources"]
        ]
        citations = [item["citation"] for item in options]
        decision = {
            "draft_id": self.draft["draft_id"],
            "source_sha256s": sorted(item["sha256"] for item in self.draft["sources"]),
            "source_context_checked": True,
            "decision": "revise",
            "final_question": "What final transaction term is supported by the cited passage?",
            "answer_policy": "supported",
            "supporting_citations": citations,
            "confusable_citations": [],
            "expected_claims": [{
                "text": "The cited passage states the reviewed final transaction term.",
                "citations": citations,
            }],
            "absence_basis": "",
            "rationale": "The revised question is directly supported by the selected passage.",
        }
        submissions = []
        for reviewer_id, event_id in (
            ("reviewer-a", "1" * 64),
            ("reviewer-b", "2" * 64),
        ):
            submissions.append({
                "review_id": f"review-{reviewer_id}",
                "reviewer_id": reviewer_id,
                "reviewer_role": "qualified_deal_source_reviewer",
                "qualification": "Experienced M&A source reviewer.",
                "blinded_to_model": True,
                "packet_sha256": packet_sha256(self.packet),
                "reviewer_pubkey": reviewer_pubkey(reviewer_id),
                "buzz_event_id": event_id,
                "reviewed_at": "2026-08-15T07:00:00+00:00",
                "drafts": [copy.deepcopy(decision)],
            })
        snapshot = hashlib.sha256(json.dumps(
            {item["filename"]: item["sha256"] for item in self.draft["sources"]},
            sort_keys=True, separators=(",", ":"),
        ).encode()).hexdigest()
        approval = {
            "approval_id": "approval-one",
            "draft_id": self.draft["draft_id"],
            "source_review_packet_sha256": packet_sha256(self.packet),
            "source_review_ids": [item["review_id"] for item in submissions],
            "source_review_event_ids": [item["buzz_event_id"] for item in submissions],
            "source_adjudication_id": None,
            "source_adjudication_event_id": None,
            "domain_owner_id": "domain-owner",
            "qualification": "Accountable M&A benchmark domain owner.",
            "reviewer_pubkey": reviewer_pubkey("domain-owner"),
            "buzz_event_id": "3" * 64,
            "approved_at": "2026-08-15T08:00:00+00:00",
            "confusable_citations": [],
            "case": {
                "id": "candidate_case_one",
                "version": "1.0.0",
                "deal_id": self.draft["candidate_id"],
                "near_duplicate_family_id": None,
                "split": "development",
                "task_family": self.draft["task_family"],
                "question": decision["final_question"],
                "investment_screen": "initial_pricing_screen",
                "answer_policy": "answer",
                "severity": "critical",
                "requested_components": ["reviewed_final_transaction_term"],
                "required_claims": [{
                    "id": "claim_one", "text": decision["expected_claims"][0]["text"],
                    "severity": "critical",
                    "citation_ids": [f"citation_{index}" for index in range(1, len(options) + 1)],
                }],
                "required_citations": [
                    {
                        "id": f"citation_{index}",
                        "filename": option["citation"][1:-1].split("#", 1)[0],
                        "anchor": option["citation"][1:-1].split("#", 1)[1],
                        "source_sha256": option["source_sha256"],
                        "evidence_excerpt_sha256": hashlib.sha256(
                            option["excerpt"].encode()
                        ).hexdigest(),
                    }
                    for index, option in enumerate(options, 1)
                ],
                "calculations": [],
                "acceptable_absence_terms": [],
                "forbidden_claims": [],
                "slices": [
                    "multiple_documents" if len(self.draft["sources"]) > 1
                    else "single_document"
                ],
                "source_snapshot_sha256": snapshot,
                "domain_review": {
                    "status": "approved", "owner": "domain-owner",
                    "reviewed_at": "2026-08-15T08:00:00+00:00",
                },
            },
        }
        events = {
            item["buzz_event_id"]: signed_event(item, "candidate_source_review")
            for item in submissions
        }
        events[approval["buzz_event_id"]] = signed_event(approval, "candidate_case_approval")
        return submissions, approval, events

    def test_independent_reviews_and_owner_signature_authorize_case_artifact(self):
        submissions, approval, events = self.records()
        errors = validate_candidate_case_approval(
            ROOT, self.packet, submissions, None, approval,
            reviewer_roster=ROSTER, signed_events=events,
        )
        self.assertEqual(errors, [])
        report = candidate_case_approval_report(
            ROOT, self.packet, submissions, None, approval,
            reviewer_roster=ROSTER, signed_events=events,
        )
        self.assertTrue(report["approval_valid"])
        self.assertFalse(report["benchmark_case_registered"])

    def test_question_or_excerpt_drift_fails_approval(self):
        submissions, approval, events = self.records()
        approval["case"]["question"] = "A different question"
        approval["case"]["required_citations"][0]["evidence_excerpt_sha256"] = "0" * 64
        events[approval["buzz_event_id"]] = signed_event(approval, "candidate_case_approval")
        errors = validate_candidate_case_approval(
            ROOT, self.packet, submissions, None, approval,
            reviewer_roster=ROSTER, signed_events=events,
        )
        self.assertTrue(any("question" in item and "differs" in item for item in errors))
        self.assertTrue(any("excerpt hash differs" in item for item in errors))

    def test_owner_cannot_approve_a_calculation_with_unbound_inputs(self):
        submissions, approval, events = self.records()
        approval["case"]["calculations"] = [{
            "id": "invented_calculation",
            "formula": "source_value * 2",
            "expected_value": 84.0,
            "unit": "USD",
            "tolerance": 0.01,
            "input_claim_ids": ["claim_one"],
            "inputs": [{
                "name": "source_value",
                "claim_id": "claim_one",
                "value": 42.0,
                "unit": "USD",
            }],
        }]
        events[approval["buzz_event_id"]] = signed_event(
            approval, "candidate_case_approval",
        )
        errors = validate_candidate_case_approval(
            ROOT, self.packet, submissions, None, approval,
            reviewer_roster=ROSTER, signed_events=events,
        )
        self.assertTrue(any(
            "input source_value value is absent from claim claim_one" in item
            for item in errors
        ))

    def test_missing_owner_attestation_fails_closed(self):
        submissions, approval, events = self.records()
        events.pop(approval["buzz_event_id"])
        errors = validate_candidate_case_approval(
            ROOT, self.packet, submissions, None, approval,
            reviewer_roster=ROSTER, signed_events=events,
        )
        self.assertTrue(any("signed Buzz attestation was not supplied" in item for item in errors))

    def test_authoring_material_is_derived_from_agreed_reviews(self):
        submissions, approval, events = self.records()
        material = build_candidate_case_authoring_material(
            ROOT, self.packet, submissions, None, self.draft["draft_id"],
            reviewer_roster=ROSTER, signed_events=events,
        )
        decision = submissions[0]["drafts"][0]
        self.assertEqual(material["question"], decision["final_question"])
        self.assertEqual(material["answer_policy"], "answer")
        self.assertEqual(
            [item["text"] for item in material["required_claims"]],
            [item["text"] for item in decision["expected_claims"]],
        )
        self.assertEqual(material["source_review_ids"], approval["source_review_ids"])
        self.assertEqual(material["allowed_splits"], ["development", "calibration"])
        self.assertFalse(material["sealed_test_repository_storage_allowed"])

    def test_rejected_reviews_cannot_create_authoring_material(self):
        submissions, _, events = self.records()
        for submission in submissions:
            decision = submission["drafts"][0]
            decision["decision"] = "reject"
            decision["answer_policy"] = "unresolved"
            decision["supporting_citations"] = []
            decision["expected_claims"] = []
            events[submission["buzz_event_id"]] = signed_event(
                submission, "candidate_source_review",
            )
        with self.assertRaisesRegex(ValueError, "no affirmative"):
            build_candidate_case_authoring_material(
                ROOT, self.packet, submissions, None, self.draft["draft_id"],
                reviewer_roster=ROSTER, signed_events=events,
            )


if __name__ == "__main__":
    unittest.main()
