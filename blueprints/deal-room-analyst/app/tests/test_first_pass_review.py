import copy
import json
import unittest
from pathlib import Path

from core.first_pass_review import (
    FORBIDDEN_IDENTITY_KEYS,
    HUMAN_DIMENSIONS,
    build_review_packet,
    compare_reviewers,
    packet_sha256,
    resolve_human_labels,
    validate_principal_adjudication,
    validate_review_submission,
)
from core.review_signatures import review_attestation_content
from scripts.validate_first_pass_reviews import fetch_signed_events
from tests.roster_fixtures import reviewer_pubkey, signed_roster


ROOT = Path(__file__).resolve().parents[1]
RESPONSES = ROOT / "evidence" / "bonsai-public-deal-battletest-responses.json"
TEST_OUTPUT_ROSTER = signed_roster("output_review", [
        {
            "reviewer_id": "reviewer-a",
            "display_name": "Reviewer A",
            "role": "qualified_deal_output_reviewer",
            "qualification": "Experienced M&A output reviewer.",
            "approved_at": "2026-08-15T04:00:00+00:00",
            "active": True,
        },
        {
            "reviewer_id": "reviewer-b",
            "display_name": "Reviewer B",
            "role": "qualified_deal_output_reviewer",
            "qualification": "Experienced M&A output reviewer.",
            "approved_at": "2026-08-15T04:00:00+00:00",
            "active": True,
        },
        {
            "reviewer_id": "principal-c",
            "display_name": "Principal C",
            "role": "principal_output_reviewer",
            "qualification": "M&A output adjudication principal.",
            "approved_at": "2026-08-15T04:00:00+00:00",
            "active": True,
        },
])


def all_keys(value):
    if isinstance(value, dict):
        result = set(value)
        for item in value.values():
            result.update(all_keys(item))
        return result
    if isinstance(value, list):
        result = set()
        for item in value:
            result.update(all_keys(item))
        return result
    return set()


def submission(packet, reviewer_id):
    pubkeys = {name: reviewer_pubkey(name) for name in ("reviewer-a", "reviewer-b")}
    event_ids = {"reviewer-a": "4" * 64, "reviewer-b": "5" * 64}
    return {
        "review_id": f"review-{reviewer_id}",
        "reviewer_id": reviewer_id,
        "reviewer_role": "qualified_deal_output_reviewer",
        "qualification": "Experienced M&A output reviewer.",
        "blinded_to_model": True,
        "packet_sha256": packet_sha256(packet),
        "rubric_sha256": packet["rubric_sha256"],
        "reviewer_pubkey": pubkeys[reviewer_id],
        "buzz_event_id": event_ids[reviewer_id],
        "reviewed_at": "2026-08-15T05:00:00+00:00",
        "cases": [
            {
                "case_id": case["case_id"],
                "case_version": case["case_version"],
                "response_sha256": case["response_sha256"],
                "dimensions": [
                    {
                        "dimension": dimension,
                        "label": "pass",
                        "severity": case["severity"],
                        "critique": "",
                    }
                    for dimension in sorted(HUMAN_DIMENSIONS)
                ],
                "useful_starting_point": True,
                "decision": "advance",
                "review_time_seconds": 60,
                "critical_corrections": 0,
                "major_corrections": 0,
                "critique": "",
            }
            for case in packet["cases"]
        ],
    }


def signed_events(*records, kind="blinded_output_review"):
    return {
        record["buzz_event_id"]: {
            "id": record["buzz_event_id"],
            "pubkey": record["reviewer_pubkey"],
            "content": review_attestation_content(kind, record),
        }
        for record in records
    }


class FirstPassReviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.packet = build_review_packet(ROOT, RESPONSES)

    def test_packet_is_hash_bound_and_contains_no_model_identity_keys(self):
        self.assertTrue(self.packet["blinded_to_model"])
        self.assertFalse(self.packet["model_identity_included"])
        self.assertFalse(FORBIDDEN_IDENTITY_KEYS & all_keys(self.packet))
        self.assertEqual(len(packet_sha256(self.packet)), 64)

    def test_saved_packet_matches_current_registry_rubric_and_responses(self):
        saved = json.loads(
            (ROOT / "evidence" / "first-pass-human-review-packet-v2.json").read_text()
        )
        self.assertEqual(saved, self.packet)

    def test_complete_blinded_submission_is_structurally_valid(self):
        review = submission(self.packet, "reviewer-a")
        self.assertEqual(
            validate_review_submission(
                ROOT, self.packet, review, TEST_OUTPUT_ROSTER, signed_events(review)
            ), []
        )

    def test_response_tamper_and_missing_dimension_are_rejected(self):
        review = submission(self.packet, "reviewer-a")
        review["cases"][0]["response_sha256"] = "0" * 64
        review["cases"][1]["dimensions"].pop()
        errors = validate_review_submission(
            ROOT, self.packet, review, TEST_OUTPUT_ROSTER, signed_events(review)
        )
        self.assertTrue(any("response hash differs" in item for item in errors))
        self.assertTrue(any("every human dimension" in item for item in errors))

    def test_duplicate_reviewer_cannot_satisfy_two_reviewer_gate(self):
        review = submission(self.packet, "reviewer-a")
        result = compare_reviewers(
            ROOT, self.packet, [review, copy.deepcopy(review)], TEST_OUTPUT_ROSTER,
            signed_events(review),
        )
        self.assertFalse(result["valid"])
        self.assertIn("reviewers must be distinct", result["errors"])

    def test_disagreement_requires_principal_adjudication(self):
        first = submission(self.packet, "reviewer-a")
        second = submission(self.packet, "reviewer-b")
        second["cases"][0]["dimensions"][0]["label"] = "fail"
        second["cases"][0]["dimensions"][0]["critique"] = "Required correction."
        result = compare_reviewers(
            ROOT, self.packet, [first, second], TEST_OUTPUT_ROSTER,
            signed_events(first, second),
        )
        self.assertTrue(result["valid"], result["errors"])
        self.assertTrue(result["principal_adjudication_required"])
        self.assertEqual(len(result["disagreements"]), 1)

    def test_agreement_resolves_to_canonical_human_labels(self):
        first = submission(self.packet, "reviewer-a")
        second = submission(self.packet, "reviewer-b")
        comparison = compare_reviewers(
            ROOT, self.packet, [first, second], TEST_OUTPUT_ROSTER,
            signed_events(first, second),
        )
        labels = resolve_human_labels(self.packet, [first, second], comparison)
        self.assertEqual(
            len(labels),
            len(self.packet["cases"]) * len(HUMAN_DIMENSIONS),
        )
        self.assertTrue(all(item["final_label"] == "pass" for item in labels))
        self.assertTrue(all(item["resolution"] == "reviewer_agreement" for item in labels))

    def test_disagreement_cannot_resolve_without_complete_adjudication(self):
        first = submission(self.packet, "reviewer-a")
        second = submission(self.packet, "reviewer-b")
        second["cases"][0]["dimensions"][0]["label"] = "fail"
        second["cases"][0]["dimensions"][0]["critique"] = "Required correction."
        comparison = compare_reviewers(
            ROOT, self.packet, [first, second], TEST_OUTPUT_ROSTER,
            signed_events(first, second),
        )
        with self.assertRaisesRegex(ValueError, "complete principal adjudication"):
            resolve_human_labels(self.packet, [first, second], comparison)

    def test_principal_adjudication_is_distinct_and_complete(self):
        first = submission(self.packet, "reviewer-a")
        second = submission(self.packet, "reviewer-b")
        second["cases"][0]["dimensions"][0]["label"] = "fail"
        second["cases"][0]["dimensions"][0]["critique"] = "Required correction."
        comparison = compare_reviewers(
            ROOT, self.packet, [first, second], TEST_OUTPUT_ROSTER,
            signed_events(first, second),
        )
        disagreement = comparison["disagreements"][0]
        adjudication = {
            "adjudication_id": "adjudication-1",
            "principal_reviewer_id": "principal-c",
            "qualification": "M&A output adjudication principal.",
            "packet_sha256": packet_sha256(self.packet),
            "reviewer_pubkey": reviewer_pubkey("principal-c"),
            "buzz_event_id": "6" * 64,
            "adjudicated_at": "2026-08-15T06:00:00+00:00",
            "decisions": [{
                "case_id": disagreement["case_id"],
                "dimension": disagreement["dimension"],
                "final_label": "fail",
                "rationale": "The response omitted a required part.",
            }],
        }
        self.assertEqual(
            validate_principal_adjudication(
                ROOT, self.packet, comparison, ["reviewer-a", "reviewer-b"], adjudication,
                TEST_OUTPUT_ROSTER,
                signed_events(adjudication, kind="blinded_output_adjudication"),
            ),
            [],
        )
        adjudication["principal_reviewer_id"] = "reviewer-a"
        adjudication["decisions"] = []
        errors = validate_principal_adjudication(
            ROOT, self.packet, comparison, ["reviewer-a", "reviewer-b"], adjudication,
            TEST_OUTPUT_ROSTER,
            signed_events(adjudication, kind="blinded_output_adjudication"),
        )
        self.assertTrue(any("principal must be distinct" in item for item in errors))
        self.assertTrue(any("resolve every disagreement" in item for item in errors))

    def test_self_asserted_output_reviewer_and_principal_are_rejected(self):
        empty = {"version": "test", "status": "domain_owner_managed", "reviewers": []}
        review = submission(self.packet, "reviewer-a")
        errors = validate_review_submission(ROOT, self.packet, review, empty, {})
        self.assertTrue(any("not active on the domain-owner-managed output roster" in item for item in errors))

        first = submission(self.packet, "reviewer-a")
        second = submission(self.packet, "reviewer-b")
        second["cases"][0]["dimensions"][0]["label"] = "fail"
        second["cases"][0]["dimensions"][0]["critique"] = "Required correction."
        comparison = compare_reviewers(
            ROOT, self.packet, [first, second], TEST_OUTPUT_ROSTER,
            signed_events(first, second),
        )
        disagreement = comparison["disagreements"][0]
        adjudication = {
            "adjudication_id": "unrostered-principal",
            "principal_reviewer_id": "principal-c",
            "qualification": "M&A output adjudication principal.",
            "packet_sha256": packet_sha256(self.packet),
            "reviewer_pubkey": reviewer_pubkey("principal-c"),
            "buzz_event_id": "7" * 64,
            "adjudicated_at": "2026-08-15T06:00:00+00:00",
            "decisions": [{
                "case_id": disagreement["case_id"],
                "dimension": disagreement["dimension"],
                "final_label": "fail",
                "rationale": "The response omitted a required part.",
            }],
        }
        errors = validate_principal_adjudication(
            ROOT, self.packet, comparison, ["reviewer-a", "reviewer-b"], adjudication,
            empty, {},
        )
        self.assertTrue(any("not active on the approved output roster" in item for item in errors))

    def test_missing_or_forged_buzz_attestation_is_rejected(self):
        review = submission(self.packet, "reviewer-a")
        missing = validate_review_submission(
            ROOT, self.packet, review, TEST_OUTPUT_ROSTER, {}
        )
        self.assertTrue(any("signed Buzz attestation was not supplied" in item for item in missing))
        forged = signed_events(review)
        forged[review["buzz_event_id"]]["pubkey"] = "f" * 64
        errors = validate_review_submission(
            ROOT, self.packet, review, TEST_OUTPUT_ROSTER, forged
        )
        self.assertTrue(any("Buzz event signer differs" in item for item in errors))

    def test_agreement_only_review_restores_events_without_adjudication(self):
        class RecordingBridge:
            def __init__(self):
                self.ids = None
                self.channel = None

            def events_by_ids(self, event_ids, channel_id):
                self.ids = event_ids
                self.channel = channel_id
                return {item: {"id": item} for item in event_ids}

        first = submission(self.packet, "reviewer-a")
        second = submission(self.packet, "reviewer-b")
        bridge = RecordingBridge()
        events = fetch_signed_events(
            [first, second], None, "private-review-channel", bridge=bridge,
        )
        self.assertEqual(
            bridge.ids,
            {first["buzz_event_id"], second["buzz_event_id"]},
        )
        self.assertEqual(bridge.channel, "private-review-channel")
        self.assertEqual(set(events), bridge.ids)


if __name__ == "__main__":
    unittest.main()
