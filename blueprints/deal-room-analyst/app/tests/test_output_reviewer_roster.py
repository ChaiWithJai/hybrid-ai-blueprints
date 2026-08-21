import json
import shutil
import tempfile
import unittest
from pathlib import Path

from core.first_pass_review import load_output_reviewer_roster
from scripts.add_output_reviewer import add_output_reviewer
from tests.roster_fixtures import configured_roster, signed_reviewer_arguments


ROOT = Path(__file__).resolve().parents[1]


class OutputReviewerRosterTests(unittest.TestCase):
    def temp_root(self, folder):
        root = Path(folder)
        contract = root / "benchmarks" / "first_pass"
        contract.mkdir(parents=True)
        for name in (
            "output_reviewer_roster.v1.json",
            "output_reviewer_roster.schema.json",
            "source_reviewer_roster.v1.json",
        ):
            shutil.copy2(ROOT / "benchmarks" / "first_pass" / name, contract / name)
        for name in ("source_reviewer_roster.v1.json", "output_reviewer_roster.v1.json"):
            (contract / name).write_text(
                json.dumps(configured_roster(), indent=2, sort_keys=True) + "\n"
            )
        return root

    def test_output_roster_starts_empty(self):
        roster = load_output_reviewer_roster(ROOT)
        self.assertEqual(roster["status"], "domain_owner_managed")
        self.assertEqual(roster["reviewers"], [])

    def test_add_output_reviewer_requires_approval_and_prevents_overwrite(self):
        with tempfile.TemporaryDirectory() as folder:
            root = self.temp_root(folder)
            arguments = signed_reviewer_arguments(
                "output_review",
                reviewer_id="reviewer.output",
                display_name="Output Reviewer",
                role="qualified_deal_output_reviewer",
                qualification="M&A output review experience.",
                reviewer_private_key="6".zfill(64),
                approved_at="2026-08-15T04:00:00+00:00",
                created_at=1786782101,
            )
            with self.assertRaisesRegex(ValueError, "explicit domain-owner approval"):
                add_output_reviewer(root, **arguments, approval_confirmed=False)
            add_output_reviewer(root, **arguments, approval_confirmed=True)
            self.assertEqual(len(load_output_reviewer_roster(root)["reviewers"]), 1)
            with self.assertRaisesRegex(ValueError, "explicit amendment workflow"):
                add_output_reviewer(root, **arguments, approval_confirmed=True)
            second = signed_reviewer_arguments(
                "output_review", reviewer_id="reviewer.second",
                display_name="Second Output Reviewer",
                role="qualified_deal_output_reviewer",
                qualification="M&A output review experience.",
                reviewer_private_key="6".zfill(64),
                approved_at="2026-08-15T04:01:00+00:00", created_at=1786782102,
            )
            with self.assertRaisesRegex(ValueError, "already belongs to another reviewer"):
                add_output_reviewer(root, **second, approval_confirmed=True)

    def test_invalid_output_roster_fails_closed(self):
        with tempfile.TemporaryDirectory() as folder:
            root = self.temp_root(folder)
            path = root / "benchmarks" / "first_pass" / "output_reviewer_roster.v1.json"
            roster = json.loads(path.read_text())
            roster["reviewers"] = [{"reviewer_id": "unapproved"}]
            path.write_text(json.dumps(roster))
            with self.assertRaisesRegex(ValueError, "invalid output reviewer roster"):
                load_output_reviewer_roster(root)

    def test_duplicate_buzz_key_fails_closed(self):
        with tempfile.TemporaryDirectory() as folder:
            root = self.temp_root(folder)
            path = root / "benchmarks" / "first_pass" / "output_reviewer_roster.v1.json"
            roster = json.loads(path.read_text())
            base = {
                "display_name": "Reviewer",
                "role": "qualified_deal_output_reviewer",
                "qualification": "M&A output review experience.",
                "buzz_pubkey": "b" * 64,
                "approved_by": "domain.owner",
                "approved_at": "2026-08-15T04:00:00+00:00",
                "active": True,
            }
            roster["reviewers"] = [dict(base, reviewer_id="reviewer.one"), dict(base, reviewer_id="reviewer.two")]
            path.write_text(json.dumps(roster))
            with self.assertRaisesRegex(ValueError, "Buzz public keys must be unique"):
                load_output_reviewer_roster(root)

    def test_manually_edited_identity_fields_still_follow_creation_contract(self):
        with tempfile.TemporaryDirectory() as folder:
            root = self.temp_root(folder)
            path = root / "benchmarks" / "first_pass" / "output_reviewer_roster.v1.json"
            roster = json.loads(path.read_text())
            roster["reviewers"] = [{
                "reviewer_id": "Upper Case",
                "display_name": "   ",
                "role": "qualified_deal_output_reviewer",
                "qualification": "M&A output review experience.",
                "buzz_pubkey": "b" * 64,
                "approved_by": "domain.owner",
                "approved_at": "2026-08-15T04:00:00+00:00",
                "active": True,
            }]
            path.write_text(json.dumps(roster))
            with self.assertRaisesRegex(ValueError, "invalid output reviewer roster"):
                load_output_reviewer_roster(root)


if __name__ == "__main__":
    unittest.main()
