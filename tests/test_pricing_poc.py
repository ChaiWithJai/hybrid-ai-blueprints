import copy
import json
import tempfile
import unittest
from pathlib import Path

from core.nostr_event import public_key_from_private
from core.pricing_poc import (
    PricingBuyerAuthority,
    evaluate_pricing_poc,
    finalize_pricing_poc,
    pricing_attestation_content,
    pricing_buyer_authorization_content,
    validate_saved_pricing_poc,
)
from tests.nostr_signing import sign_event


ROOT = Path(__file__).resolve().parents[1]


class PricingPocTests(unittest.TestCase):
    @staticmethod
    def authority():
        return PricingBuyerAuthority(
            public_key_from_private("8".zfill(64)),
            "pricing-poc-private-channel",
        )

    def valid_record(self):
        private_key = "7".zfill(64)
        pubkey = public_key_from_private(private_key)
        record = {
            "schema_version": 1,
            "poc_id": "poc-private-equity-001",
            "status": "completed",
            "recorded_at": "2026-08-15T14:00:00-04:00",
            "buyer": {
                "buyer_id": "buyer-pseudonym-001",
                "workflow_owner_role": "private_equity_vice_president",
                "economic_buyer_role": "private_equity_partner",
                "budget_authority_confirmed": True,
                "buyer_pubkey": pubkey,
            },
            "success_contract": {
                "buyer_effort_committed": True,
                "authorized_source_access": True,
                "success_criteria_approved": True,
                "poc_paid": True,
                "paid_amount_usd": 5000,
            },
            "package_hypothesis": {
                "value_unit": "accepted_first_pass_review_per_deal_room",
                "deployment": "customer_controlled_local",
                "included_review_allowance": 2,
                "collaboration_included": True,
                "policy_controls_included": True,
                "deployment_support_included": True,
            },
            "deals": [
                {
                    "deal_id": "closed-deal-setup",
                    "experiment_role": "setup_and_correction",
                    "closed_historical": True,
                    "private_folder": True,
                    "source_snapshot_sha256": "a" * 64,
                    "historical_review_minutes": 240,
                    "prism_review_minutes": 120,
                    "useful_starting_point": True,
                    "accepted_review": True,
                    "critical_corrections": 1,
                },
                {
                    "deal_id": "closed-deal-transfer",
                    "experiment_role": "transfer_without_case_specific_change",
                    "closed_historical": True,
                    "private_folder": True,
                    "source_snapshot_sha256": "b" * 64,
                    "historical_review_minutes": 200,
                    "prism_review_minutes": 100,
                    "useful_starting_point": True,
                    "accepted_review": True,
                    "critical_corrections": 0,
                },
            ],
            "price_research": {
                "asked_after_use": True,
                "currency": "USD",
                "value_unit": "accepted_first_pass_review_per_deal_room",
                "acceptable_price": 1000,
                "expensive_price": 2500,
                "prohibitively_expensive_price": 5000,
            },
            "next_step": {
                "decision": "agreed_paid_next_step",
                "paid_amount_usd": 10000,
                "declined_reason": None,
            },
        }
        authority_event = sign_event({
            "pubkey": self.authority().pubkey,
            "created_at": 1786816799,
            "kind": 9,
            "tags": [["h", "pricing-poc-private-channel"]],
            "content": pricing_buyer_authorization_content(record),
        }, "8".zfill(64))
        record["buyer_authorization"] = {
            "channel_id": "pricing-poc-private-channel",
            "event": authority_event,
        }
        buyer_event = sign_event({
            "pubkey": pubkey,
            "created_at": 1786816800,
            "kind": 9,
            "tags": [["h", "pricing-poc-private-channel"]],
            "content": pricing_attestation_content(record),
        }, private_key)
        record["buyer_attestation"] = {
            "channel_id": "pricing-poc-private-channel",
            "event": buyer_event,
        }
        return record

    @staticmethod
    def restored(record):
        events = [
            record["buyer_authorization"]["event"],
            record["buyer_attestation"]["event"],
        ]
        return {event["id"]: copy.deepcopy(event) for event in events}

    def test_buyer_attested_paid_poc_passes_all_value_gates(self):
        record = self.valid_record()
        result = evaluate_pricing_poc(
            ROOT, record, authority=self.authority(), restored_events=self.restored(record),
        )
        self.assertTrue(result["input_valid"], result["errors"])
        self.assertTrue(result["pricing_poc_passed"])
        self.assertEqual(result["deal_count"], 2)
        self.assertTrue(all(item["passed"] for item in result["gates"].values()))
        self.assertTrue(result["buyer_authority_verified"])

    def test_self_issued_buyer_key_cannot_become_commercial_evidence(self):
        record = self.valid_record()
        result = evaluate_pricing_poc(
            ROOT,
            record,
            authority=PricingBuyerAuthority(None, None),
            restored_events=self.restored(record),
        )
        self.assertFalse(result["input_valid"])
        self.assertFalse(result["pricing_poc_passed"])
        self.assertFalse(result["buyer_authority_verified"])
        self.assertFalse(result["gates"]["buyer_signature"]["passed"])
        self.assertTrue(any("authority is not configured" in item for item in result["errors"]))

    def test_buyer_cannot_act_as_its_own_commercial_authority(self):
        record = self.valid_record()
        buyer_key = record["buyer"]["buyer_pubkey"]
        result = evaluate_pricing_poc(
            ROOT,
            record,
            authority=PricingBuyerAuthority(
                buyer_key, "pricing-poc-private-channel",
            ),
            restored_events=self.restored(record),
        )
        self.assertFalse(result["pricing_poc_passed"])
        self.assertFalse(result["buyer_authority_verified"])
        self.assertTrue(any("keys must be distinct" in item for item in result["errors"]))

    def test_authority_event_cannot_claim_multiple_buzz_channels(self):
        record = self.valid_record()
        record["buyer_authorization"]["event"] = sign_event({
            "pubkey": self.authority().pubkey,
            "created_at": 1786816805,
            "kind": 9,
            "tags": [
                ["h", "pricing-poc-private-channel"],
                ["h", "second-channel"],
            ],
            "content": pricing_buyer_authorization_content(record),
        }, "8".zfill(64))
        record["buyer_attestation"]["event"] = sign_event({
            "pubkey": record["buyer"]["buyer_pubkey"],
            "created_at": 1786816806,
            "kind": 9,
            "tags": [["h", "pricing-poc-private-channel"]],
            "content": pricing_attestation_content(record),
        }, "7".zfill(64))
        result = evaluate_pricing_poc(
            ROOT,
            record,
            authority=self.authority(),
            restored_events=self.restored(record),
        )
        self.assertFalse(result["pricing_poc_passed"])
        self.assertTrue(any("authority channel" in item for item in result["errors"]))

    def test_signed_but_unpublished_buyer_event_is_rejected(self):
        record = self.valid_record()
        result = evaluate_pricing_poc(ROOT, record, authority=self.authority())
        self.assertFalse(result["input_valid"])
        self.assertFalse(result["pricing_poc_passed"])
        self.assertFalse(result["relay_restored"])
        self.assertTrue(any("not restored from Buzz" in item for item in result["errors"]))

    def test_changed_restored_buyer_event_is_rejected(self):
        record = self.valid_record()
        restored = self.restored(record)
        restored_event = restored[record["buyer_attestation"]["event"]["id"]]
        restored_event["content"] += "\nchanged"
        result = evaluate_pricing_poc(
            ROOT, record, authority=self.authority(), restored_events=restored,
        )
        self.assertFalse(result["input_valid"])
        self.assertFalse(result["relay_restored"])
        self.assertTrue(any("differs from saved event" in item for item in result["errors"]))

    def test_saved_record_requires_live_buzz_resolver(self):
        record = self.valid_record()
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            path = Path(directory) / "pricing.json"
            path.write_text(json.dumps(record), encoding="utf-8")
            without_resolver = validate_saved_pricing_poc(ROOT, path)
            with_resolver = validate_saved_pricing_poc(
                ROOT,
                path,
                authority=self.authority(),
                event_resolver=lambda event_ids, channel_id: self.restored(record),
            )
        self.assertFalse(without_resolver["pricing_poc_passed"])
        self.assertFalse(without_resolver["relay_restored"])
        self.assertTrue(with_resolver["pricing_poc_passed"], with_resolver["errors"])
        self.assertTrue(with_resolver["relay_restored"])

    def test_payload_tamper_invalidates_buyer_signature(self):
        record = self.valid_record()
        record["price_research"]["acceptable_price"] = 1200
        result = evaluate_pricing_poc(
            ROOT, record, authority=self.authority(), restored_events=self.restored(record),
        )
        self.assertFalse(result["input_valid"])
        self.assertFalse(result["pricing_poc_passed"])
        self.assertTrue(any("attestation payload differs" in item for item in result["errors"]))

    def test_transfer_critical_correction_fails_product_value(self):
        record = self.valid_record()
        record["deals"][1]["critical_corrections"] = 1
        private_key = "7".zfill(64)
        record["buyer_attestation"]["event"] = sign_event({
            "pubkey": record["buyer"]["buyer_pubkey"],
            "created_at": 1786816801,
            "kind": 9,
            "tags": [["h", "pricing-poc-private-channel"]],
            "content": pricing_attestation_content(record),
        }, private_key)
        result = evaluate_pricing_poc(
            ROOT, record, authority=self.authority(), restored_events=self.restored(record),
        )
        self.assertTrue(result["input_valid"], result["errors"])
        self.assertFalse(result["pricing_poc_passed"])
        self.assertFalse(result["gates"]["transfer_deal_quality"]["passed"])

    def test_buyer_refusal_to_price_is_valid_negative_evidence(self):
        record = self.valid_record()
        record["success_contract"]["poc_paid"] = False
        record["success_contract"]["paid_amount_usd"] = 0
        record["price_research"]["asked_after_use"] = False
        record["price_research"]["acceptable_price"] = None
        record["price_research"]["expensive_price"] = None
        record["price_research"]["prohibitively_expensive_price"] = None
        record["next_step"] = {
            "decision": "declined",
            "paid_amount_usd": None,
            "declined_reason": "Buyer would not fund a pilot at this stage.",
        }
        private_key = "7".zfill(64)
        record["buyer_attestation"]["event"] = sign_event({
            "pubkey": record["buyer"]["buyer_pubkey"],
            "created_at": 1786816804,
            "kind": 9,
            "tags": [["h", "pricing-poc-private-channel"]],
            "content": pricing_attestation_content(record),
        }, private_key)
        result = evaluate_pricing_poc(
            ROOT, record, authority=self.authority(), restored_events=self.restored(record),
        )
        self.assertTrue(result["input_valid"], result["errors"])
        self.assertFalse(result["pricing_poc_passed"])
        self.assertFalse(result["gates"]["paid_poc"]["passed"])
        self.assertFalse(result["gates"]["post_use_price_range"]["passed"])
        self.assertTrue(result["gates"]["paid_next_step_or_reason"]["passed"])

    def test_price_range_must_be_ordered_after_use(self):
        record = self.valid_record()
        record["price_research"]["expensive_price"] = 500
        private_key = "7".zfill(64)
        record["buyer_attestation"]["event"] = sign_event({
            "pubkey": record["buyer"]["buyer_pubkey"],
            "created_at": 1786816802,
            "kind": 9,
            "tags": [["h", "pricing-poc-private-channel"]],
            "content": pricing_attestation_content(record),
        }, private_key)
        result = evaluate_pricing_poc(
            ROOT, record, authority=self.authority(), restored_events=self.restored(record),
        )
        self.assertTrue(result["input_valid"], result["errors"])
        self.assertFalse(result["gates"]["post_use_price_range"]["passed"])

    def test_missing_record_is_explicitly_not_recorded(self):
        with tempfile.TemporaryDirectory() as directory:
            result = validate_saved_pricing_poc(
                ROOT, Path(directory) / "missing-pricing-poc.json"
            )
        self.assertEqual(result["evidence_state"], "not_recorded")
        self.assertFalse(result["pricing_poc_passed"])
        self.assertEqual(result["deal_count"], 0)

    def test_finalize_binds_exact_buyer_event(self):
        final = self.valid_record()
        unsigned = {
            key: value for key, value in final.items()
            if key not in {"buyer_authorization", "buyer_attestation"}
        }
        event = final["buyer_attestation"]["event"]
        authority_event = final["buyer_authorization"]["event"]
        recorded, result = finalize_pricing_poc(
            ROOT,
            unsigned,
            event,
            channel_id="pricing-poc-private-channel",
            authority=self.authority(),
            authority_event=authority_event,
            restored_events=self.restored(final),
        )
        self.assertTrue(result["pricing_poc_passed"])
        self.assertEqual(recorded["buyer_attestation"]["event"]["id"], event["id"])

        changed = copy.deepcopy(unsigned)
        changed["price_research"]["acceptable_price"] = 1100
        with self.assertRaisesRegex(ValueError, "exact pricing POC payload"):
            finalize_pricing_poc(
                ROOT,
                changed,
                event,
                channel_id="pricing-poc-private-channel",
                authority=self.authority(),
                authority_event=authority_event,
                restored_events=self.restored(final),
            )

    def test_finalize_records_valid_failed_poc_without_promoting_it(self):
        final = self.valid_record()
        unsigned = {
            key: value for key, value in final.items()
            if key not in {"buyer_authorization", "buyer_attestation"}
        }
        unsigned["deals"][1]["critical_corrections"] = 2
        authority_event = final["buyer_authorization"]["event"]
        authorized = {
            **unsigned,
            "buyer_authorization": {
                "channel_id": "pricing-poc-private-channel",
                "event": authority_event,
            },
        }
        private_key = "7".zfill(64)
        event = sign_event({
            "pubkey": unsigned["buyer"]["buyer_pubkey"],
            "created_at": 1786816803,
            "kind": 9,
            "tags": [["h", "pricing-poc-private-channel"]],
            "content": pricing_attestation_content(authorized),
        }, private_key)
        recorded, result = finalize_pricing_poc(
            ROOT,
            unsigned,
            event,
            channel_id="pricing-poc-private-channel",
            authority=self.authority(),
            authority_event=authority_event,
            restored_events={authority_event["id"]: authority_event, event["id"]: event},
        )
        self.assertFalse(result["pricing_poc_passed"])
        self.assertFalse(result["gates"]["transfer_deal_quality"]["passed"])
        self.assertEqual(recorded["deals"][1]["critical_corrections"], 2)


if __name__ == "__main__":
    unittest.main()
