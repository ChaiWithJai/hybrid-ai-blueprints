import copy
import hashlib
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from core.first_pass_review import HUMAN_DIMENSIONS, packet_sha256, resolve_human_labels
from core.judge_calibration import evaluate_judge_calibration, validate_saved_judge_calibration
from core.nostr_event import public_key_from_private
from core.review_signatures import review_attestation_content
from tests.nostr_signing import sign_event
from tests.roster_fixtures import configured_roster, signed_reviewer_arguments


ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "benchmarks" / "first_pass"
SEMANTIC_DIMENSIONS = (
    "primary_decision_intent",
    "evidence_support",
    "component_completeness",
    "calibrated_uncertainty",
)


def canonical_sha(value):
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


class JudgeCalibrationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        target = self.root / "benchmarks" / "first_pass"
        target.mkdir(parents=True)
        for name in (
            "judge_calibration.schema.json",
            "rubric.v1.json",
            "benchmark_manifest.v2.json",
            "human_review_submission.schema.json",
            "principal_adjudication.schema.json",
            "output_reviewer_roster.schema.json",
        ):
            shutil.copy(CONTRACT / name, target / name)

        private_keys = ["1".zfill(64), "2".zfill(64)]
        pubkeys = [public_key_from_private(item) for item in private_keys]
        self.private_keys = private_keys
        self.pubkeys = pubkeys
        roster = configured_roster()
        for index, private_key in enumerate(private_keys):
            arguments = signed_reviewer_arguments(
                "output_review",
                reviewer_id=f"reviewer-{index + 1}",
                display_name=f"Reviewer {index + 1}",
                role="qualified_deal_output_reviewer",
                qualification="Experienced M&A output reviewer.",
                reviewer_private_key=private_key,
                approved_at="2026-08-15T11:00:00-04:00",
                created_at=1786809000 + index,
            )
            roster["reviewers"].append({**arguments, "active": True})
        roster_path = target / "output_reviewer_roster.v1.json"
        roster_path.write_text(json.dumps(roster), encoding="utf-8")
        source_roster = configured_roster()
        (target / "source_reviewer_roster.v1.json").write_text(
            json.dumps(source_roster), encoding="utf-8"
        )

        rubric_sha = hashlib.sha256((target / "rubric.v1.json").read_bytes()).hexdigest()
        cases = []
        for case_index in range(20):
            cases.append({
                "case_id": f"case-{case_index:02d}",
                "case_version": "1.0.0",
                "deal_id": f"deal-{case_index % 5}",
                "split": "calibration",
                "task_family": "purchase_price_and_valuation",
                "severity": "critical" if case_index == 0 else "major",
                "response_sha256": hashlib.sha256(f"response-{case_index}".encode()).hexdigest(),
            })
        packet = {
            "packet_kind": "blinded_first_pass_calibration_review",
            "packet_version": "1.0.0",
            "blinded_to_model": True,
            "model_identity_included": False,
            "rubric_sha256": rubric_sha,
            "cases": cases,
        }
        packet_path = self.root / "evidence" / "calibration-packet.json"
        packet_path.parent.mkdir()
        packet_path.write_text(json.dumps(packet), encoding="utf-8")
        self.packet_path = packet_path

        submissions = []
        signed_events = {}
        channel_id = "calibration-review-channel"
        self.channel_id = channel_id
        for reviewer_index, (private_key, pubkey) in enumerate(zip(private_keys, pubkeys)):
            review = {
                "review_id": f"review-{reviewer_index + 1}",
                "reviewer_id": f"reviewer-{reviewer_index + 1}",
                "reviewer_role": "qualified_deal_output_reviewer",
                "qualification": "Experienced M&A output reviewer.",
                "blinded_to_model": True,
                "packet_sha256": packet_sha256(packet),
                "rubric_sha256": rubric_sha,
                "reviewer_pubkey": pubkey,
                "buzz_event_id": "0" * 64,
                "reviewed_at": "2026-08-15T12:00:00-04:00",
                "cases": [],
            }
            for case_index, case in enumerate(cases):
                dimensions = []
                for dimension_index, dimension in enumerate(sorted(HUMAN_DIMENSIONS)):
                    label = (
                        "fail"
                        if (
                            case_index == 0 and dimension == "primary_decision_intent"
                        ) or (case_index + dimension_index) % 7 == 0
                        else "pass"
                    )
                    dimensions.append({
                        "dimension": dimension,
                        "label": label,
                        "severity": case["severity"],
                        "critique": "Required correction." if label == "fail" else "",
                    })
                review["cases"].append({
                    "case_id": case["case_id"],
                    "case_version": case["case_version"],
                    "response_sha256": case["response_sha256"],
                    "dimensions": dimensions,
                    "useful_starting_point": True,
                    "decision": "advance",
                    "review_time_seconds": 60,
                    "critical_corrections": 0,
                    "major_corrections": 0,
                    "critique": "",
                })
            event = sign_event({
                "pubkey": pubkey,
                "created_at": 1786810000 + reviewer_index,
                "kind": 9,
                "tags": [["h", channel_id]],
                "content": review_attestation_content("blinded_output_review", review),
            }, private_key)
            review["buzz_event_id"] = event["id"]
            submissions.append(review)
            signed_events[event["id"]] = event

        comparison = {
            "valid": True,
            "disagreements": [],
        }
        resolved = resolve_human_labels(packet, submissions, comparison)
        receipt = {
            "verification_kind": "blinded_first_pass_review_validation",
            "packet_path": "evidence/calibration-packet.json",
            "packet_sha256": packet_sha256(packet),
            "reviewer_roster_sha256": hashlib.sha256(roster_path.read_bytes()).hexdigest(),
            "buzz_channel_id": channel_id,
            "submissions": submissions,
            "adjudication": None,
            "signed_events": signed_events,
            "submission_count": 2,
            "reviewer_ids": [item["reviewer_id"] for item in submissions],
            "valid": True,
            "errors": [],
            "disagreements": [],
            "principal_adjudication_required": False,
            "adjudication_complete": True,
            "review_gate_complete": True,
            "resolved_labels": resolved,
            "resolved_labels_sha256": canonical_sha(resolved),
        }
        receipt_path = self.root / "evidence" / "human-review.json"
        receipt_path.parent.mkdir(exist_ok=True)
        receipt_path.write_text(json.dumps(receipt), encoding="utf-8")

        semantic = [item for item in resolved if item["dimension"] in SEMANTIC_DIMENSIONS]
        self.record = {
            "schema_version": 1,
            "calibration_id": "calibration-test",
            "split": "calibration",
            "recorded_at": "2026-08-15T12:00:00-04:00",
            "rubric_sha256": rubric_sha,
            "human_review_receipt": {
                "path": "evidence/human-review.json",
                "sha256": hashlib.sha256(receipt_path.read_bytes()).hexdigest(),
                "resolved_labels_sha256": receipt["resolved_labels_sha256"],
            },
            "judge": {
                "provider": "local_bonsai",
                "served_id": "27b@q1_0",
                "artifact_sha256": "a" * 64,
                "quantization": "Q1_0",
                "prompt_sha256": "b" * 64,
                "sampling": {"temperature": 0},
            },
            "labels": [
                {
                    "case_id": item["case_id"],
                    "dimension": item["dimension"],
                    "judge_label": item["final_label"],
                    "critique": "",
                }
                for item in semantic
            ],
            "pairwise_trials": [
                {
                    "trial_id": f"trial-{case_index:02d}",
                    "case_id": f"case-{case_index:02d}",
                    "canonical_first_sha256": "c" * 64,
                    "canonical_second_sha256": "d" * 64,
                    "forward_choice": "first",
                    "reversed_choice": "first",
                }
                for case_index in range(20)
            ],
        }

    def tearDown(self):
        self.temporary.cleanup()

    def test_perfect_calibration_passes_every_gate(self):
        result = evaluate_judge_calibration(self.root, self.record)
        self.assertTrue(result["input_valid"], result["errors"])
        self.assertTrue(result["calibration_passed"])
        self.assertEqual(result["case_count"], 20)
        self.assertEqual(result["deal_count"], 5)
        self.assertTrue(all(item["passed"] for item in result["gates"].values()))

    def test_critical_false_pass_and_parse_failure_fail_closed(self):
        changed = copy.deepcopy(self.record)
        critical = next(
            item for item in changed["labels"]
            if item["case_id"] == "case-00"
            and item["dimension"] == "primary_decision_intent"
        )
        critical["judge_label"] = "pass"
        changed["labels"][1]["judge_label"] = "unparseable"
        result = evaluate_judge_calibration(self.root, changed)
        self.assertFalse(result["calibration_passed"])
        self.assertEqual(result["gates"]["critical_false_passes"]["observed"], 1)
        self.assertFalse(result["gates"]["parse_failure_rate"]["passed"])
        self.assertIsNone(result["gates"]["cohens_kappa"]["observed"])

    def test_order_flip_and_missing_case_trial_fail(self):
        changed = copy.deepcopy(self.record)
        changed["pairwise_trials"][0]["reversed_choice"] = "second"
        changed["pairwise_trials"].pop()
        result = evaluate_judge_calibration(self.root, changed)
        self.assertFalse(result["input_valid"])
        self.assertTrue(any("every calibration case" in item for item in result["errors"]))
        self.assertFalse(result["gates"]["pairwise_order_flip_rate"]["passed"])

    def test_receipt_hash_tamper_and_missing_judge_labels_are_rejected(self):
        changed = copy.deepcopy(self.record)
        changed["human_review_receipt"]["sha256"] = "0" * 64
        changed["labels"] = changed["labels"][:4]
        result = evaluate_judge_calibration(self.root, changed)
        self.assertFalse(result["input_valid"])
        self.assertTrue(any("receipt hash" in item for item in result["errors"]))
        self.assertTrue(any("match every calibrated human label" in item for item in result["errors"]))

    def test_forged_receipt_and_updated_binding_cannot_replace_signed_labels(self):
        receipt_path = self.root / "evidence" / "human-review.json"
        receipt = json.loads(receipt_path.read_text())
        receipt["resolved_labels"][0]["final_label"] = (
            "pass" if receipt["resolved_labels"][0]["final_label"] == "fail" else "fail"
        )
        receipt["resolved_labels_sha256"] = canonical_sha(receipt["resolved_labels"])
        receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
        changed = copy.deepcopy(self.record)
        changed["human_review_receipt"] = {
            "path": "evidence/human-review.json",
            "sha256": hashlib.sha256(receipt_path.read_bytes()).hexdigest(),
            "resolved_labels_sha256": receipt["resolved_labels_sha256"],
        }
        result = evaluate_judge_calibration(self.root, changed)
        self.assertFalse(result["input_valid"])
        self.assertTrue(any(
            "resolved labels differ from replayed signed reviews" in item
            for item in result["errors"]
        ))

    def test_small_human_calibration_sample_is_rejected(self):
        receipt_path = self.root / "evidence" / "human-review.json"
        receipt = json.loads(receipt_path.read_text())
        packet = json.loads(self.packet_path.read_text())
        packet["cases"] = packet["cases"][:1]
        self.packet_path.write_text(json.dumps(packet), encoding="utf-8")
        new_events = {}
        for index, review in enumerate(receipt["submissions"]):
            review["cases"] = review["cases"][:1]
            review["packet_sha256"] = packet_sha256(packet)
            review["buzz_event_id"] = "0" * 64
            event = sign_event({
                "pubkey": self.pubkeys[index],
                "created_at": 1786811000 + index,
                "kind": 9,
                "tags": [["h", self.channel_id]],
                "content": review_attestation_content("blinded_output_review", review),
            }, self.private_keys[index])
            review["buzz_event_id"] = event["id"]
            new_events[event["id"]] = event
        receipt["packet_sha256"] = packet_sha256(packet)
        receipt["signed_events"] = new_events
        receipt["resolved_labels"] = resolve_human_labels(
            packet,
            receipt["submissions"],
            {"valid": True, "disagreements": []},
        )
        receipt["resolved_labels_sha256"] = canonical_sha(receipt["resolved_labels"])
        receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
        changed = copy.deepcopy(self.record)
        changed["human_review_receipt"] = {
            "path": "evidence/human-review.json",
            "sha256": hashlib.sha256(receipt_path.read_bytes()).hexdigest(),
            "resolved_labels_sha256": receipt["resolved_labels_sha256"],
        }
        changed["labels"] = [
            item for item in changed["labels"] if item["case_id"] == "case-00"
        ]
        changed["pairwise_trials"] = changed["pairwise_trials"][:1]
        result = evaluate_judge_calibration(self.root, changed)
        self.assertFalse(result["input_valid"])
        self.assertTrue(any("at least 20 cases" in item for item in result["errors"]))

    def test_saved_result_is_recomputed_and_tampering_fails(self):
        input_path = self.root / "evidence" / "judge-input.json"
        input_path.write_text(json.dumps(self.record), encoding="utf-8")
        result = evaluate_judge_calibration(self.root, self.record)
        result["input_path"] = "evidence/judge-input.json"
        result_path = self.root / "evidence" / "judge-result.json"
        result_path.write_text(json.dumps(result), encoding="utf-8")
        valid = validate_saved_judge_calibration(self.root, result_path)
        self.assertEqual(valid["evidence_state"], "verified")
        self.assertTrue(valid["calibration_passed"])

        result["metrics"]["missed_fail"] = 999
        result_path.write_text(json.dumps(result), encoding="utf-8")
        tampered = validate_saved_judge_calibration(self.root, result_path)
        self.assertEqual(tampered["evidence_state"], "invalid")
        self.assertFalse(tampered["calibration_passed"])


if __name__ == "__main__":
    unittest.main()
