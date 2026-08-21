import copy
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from core.candidate_source_review import load_source_reviewer_roster
from scripts.add_source_reviewer import add_reviewer
from core.reviewer_roster_authority import reviewer_roster_approval_content
from tests.nostr_signing import sign_event
from tests.roster_fixtures import (
    AUTHORITY_PRIVATE_KEY,
    CHANNEL_ID,
    configured_roster,
    signed_reviewer_arguments,
)


ROOT = Path(__file__).resolve().parents[1]


class SourceReviewerRosterTests(unittest.TestCase):
    def temp_root(self, folder):
        root = Path(folder)
        contract = root / "benchmarks" / "first_pass"
        contract.mkdir(parents=True)
        for name in (
            "source_reviewer_roster.v1.json",
            "source_reviewer_roster.schema.json",
            "output_reviewer_roster.v1.json",
        ):
            shutil.copy2(ROOT / "benchmarks" / "first_pass" / name, contract / name)
        for name in ("source_reviewer_roster.v1.json", "output_reviewer_roster.v1.json"):
            (contract / name).write_text(
                json.dumps(configured_roster(), indent=2, sort_keys=True) + "\n"
            )
        return root

    def test_roster_starts_empty_and_domain_owner_managed(self):
        roster = load_source_reviewer_roster(ROOT)
        self.assertEqual(roster["status"], "domain_owner_managed")
        self.assertEqual(roster["reviewers"], [])

    def test_add_requires_explicit_approval_and_prevents_identity_overwrite(self):
        with tempfile.TemporaryDirectory() as folder:
            root = self.temp_root(folder)
            arguments = signed_reviewer_arguments(
                "source_review",
                reviewer_id="reviewer.alex",
                display_name="Alex Reviewer",
                role="qualified_deal_source_reviewer",
                qualification="M&A source-document review experience.",
                reviewer_private_key="5".zfill(64),
                approved_at="2026-08-15T04:00:00+00:00",
                created_at=1786782001,
            )
            with self.assertRaisesRegex(ValueError, "explicit domain-owner approval"):
                add_reviewer(root, **arguments, approval_confirmed=False)
            record = add_reviewer(root, **arguments, approval_confirmed=True)
            self.assertEqual(record["reviewer_id"], "reviewer.alex")
            roster = load_source_reviewer_roster(root)
            self.assertEqual(len(roster["reviewers"]), 1)
            with self.assertRaisesRegex(ValueError, "explicit amendment workflow"):
                add_reviewer(root, **arguments, approval_confirmed=True)
            second = signed_reviewer_arguments(
                "source_review", reviewer_id="reviewer.sam",
                display_name="Sam Reviewer", role="qualified_deal_source_reviewer",
                qualification="M&A source-document review experience.",
                reviewer_private_key="5".zfill(64),
                approved_at="2026-08-15T04:01:00+00:00", created_at=1786782002,
            )
            with self.assertRaisesRegex(ValueError, "already belongs to another reviewer"):
                add_reviewer(root, **second, approval_confirmed=True)

    def test_invalid_roster_shape_fails_closed(self):
        with tempfile.TemporaryDirectory() as folder:
            root = self.temp_root(folder)
            path = root / "benchmarks" / "first_pass" / "source_reviewer_roster.v1.json"
            roster = json.loads(path.read_text())
            roster["reviewers"] = [{"reviewer_id": "unapproved"}]
            path.write_text(json.dumps(roster))
            with self.assertRaisesRegex(ValueError, "invalid source reviewer roster"):
                load_source_reviewer_roster(root)

    def test_duplicate_buzz_key_fails_closed(self):
        with tempfile.TemporaryDirectory() as folder:
            root = self.temp_root(folder)
            path = root / "benchmarks" / "first_pass" / "source_reviewer_roster.v1.json"
            roster = json.loads(path.read_text())
            base = {
                "display_name": "Reviewer",
                "role": "qualified_deal_source_reviewer",
                "qualification": "M&A source review experience.",
                "buzz_pubkey": "a" * 64,
                "approved_by": "domain.owner",
                "approved_at": "2026-08-15T04:00:00+00:00",
                "active": True,
            }
            roster["reviewers"] = [dict(base, reviewer_id="reviewer.one"), dict(base, reviewer_id="reviewer.two")]
            path.write_text(json.dumps(roster))
            with self.assertRaisesRegex(ValueError, "Buzz public keys must be unique"):
                load_source_reviewer_roster(root)

    def test_manually_edited_identity_fields_still_follow_creation_contract(self):
        with tempfile.TemporaryDirectory() as folder:
            root = self.temp_root(folder)
            path = root / "benchmarks" / "first_pass" / "source_reviewer_roster.v1.json"
            roster = json.loads(path.read_text())
            roster["reviewers"] = [{
                "reviewer_id": "Upper Case",
                "display_name": "   ",
                "role": "qualified_deal_source_reviewer",
                "qualification": "M&A source review experience.",
                "buzz_pubkey": "a" * 64,
                "approved_by": "domain.owner",
                "approved_at": "2026-08-15T04:00:00+00:00",
                "active": True,
            }]
            path.write_text(json.dumps(roster))
            with self.assertRaisesRegex(ValueError, "invalid source reviewer roster"):
                load_source_reviewer_roster(root)

    def test_signed_roster_approval_cannot_be_reused_after_payload_drift(self):
        with tempfile.TemporaryDirectory() as folder:
            root = self.temp_root(folder)
            arguments = signed_reviewer_arguments(
                "source_review", reviewer_id="reviewer.alex",
                display_name="Alex Reviewer", role="qualified_deal_source_reviewer",
                qualification="Original qualification.", reviewer_private_key="5".zfill(64),
                approved_at="2026-08-15T04:00:00+00:00", created_at=1786782201,
            )
            arguments["qualification"] = "Changed after signing."
            roster_path = root / "benchmarks/first_pass/source_reviewer_roster.v1.json"
            before = roster_path.read_bytes()
            with self.assertRaisesRegex(ValueError, "signed payload differs"):
                add_reviewer(root, **arguments, approval_confirmed=True)
            self.assertEqual(roster_path.read_bytes(), before)

    def test_wrong_authority_key_or_channel_cannot_approve_reviewer(self):
        with tempfile.TemporaryDirectory() as folder:
            root = self.temp_root(folder)
            arguments = signed_reviewer_arguments(
                "source_review", reviewer_id="reviewer.alex",
                display_name="Alex Reviewer", role="qualified_deal_source_reviewer",
                qualification="M&A source review experience.",
                reviewer_private_key="5".zfill(64),
                approved_at="2026-08-15T04:00:00+00:00", created_at=1786782301,
            )
            material = {
                **{key: value for key, value in arguments.items() if key != "approval_event"},
                "active": True,
            }
            wrong_signer = copy.deepcopy(arguments)
            wrong_signer["approval_event"] = sign_event({
                "created_at": 1786782302, "kind": 9, "tags": [["h", CHANNEL_ID]],
                "content": reviewer_roster_approval_content("source_review", material),
            }, "6".zfill(64))
            with self.assertRaisesRegex(ValueError, "signer differs"):
                add_reviewer(root, **wrong_signer, approval_confirmed=True)

            wrong_channel = copy.deepcopy(arguments)
            wrong_channel["approval_event"] = sign_event({
                "created_at": 1786782303, "kind": 9, "tags": [["h", "wrong-channel"]],
                "content": reviewer_roster_approval_content("source_review", material),
            }, AUTHORITY_PRIVATE_KEY)
            with self.assertRaisesRegex(ValueError, "channel differs"):
                add_reviewer(root, **wrong_channel, approval_confirmed=True)

    def test_unconfigured_authority_cannot_admit_a_reviewer(self):
        with tempfile.TemporaryDirectory() as folder:
            root = self.temp_root(folder)
            roster_path = root / "benchmarks/first_pass/source_reviewer_roster.v1.json"
            roster = json.loads((ROOT / "benchmarks/first_pass/source_reviewer_roster.v1.json").read_text())
            roster_path.write_text(json.dumps(roster, indent=2, sort_keys=True) + "\n")
            output_path = root / "benchmarks/first_pass/output_reviewer_roster.v1.json"
            output_roster = json.loads(
                (ROOT / "benchmarks/first_pass/output_reviewer_roster.v1.json").read_text()
            )
            output_path.write_text(
                json.dumps(output_roster, indent=2, sort_keys=True) + "\n"
            )
            before = roster_path.read_bytes()
            arguments = signed_reviewer_arguments(
                "source_review", reviewer_id="reviewer.alex",
                display_name="Alex Reviewer", role="qualified_deal_source_reviewer",
                qualification="M&A source review experience.",
                reviewer_private_key="5".zfill(64),
                approved_at="2026-08-15T04:00:00+00:00", created_at=1786782401,
            )
            with self.assertRaisesRegex(ValueError, "unconfigured authority"):
                add_reviewer(root, **arguments, approval_confirmed=True)
            self.assertEqual(roster_path.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
