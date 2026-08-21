import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest import mock

from core.candidate_source_review import load_source_reviewer_roster
from core.first_pass_review import load_output_reviewer_roster
from core.nostr_event import public_key_from_private
import scripts.configure_reviewer_roster_authority as authority_script
from scripts.add_source_reviewer import add_reviewer
from scripts.configure_reviewer_roster_authority import configure_authority
from tests.roster_fixtures import signed_reviewer_arguments


ROOT = Path(__file__).resolve().parents[1]


class ReviewerRosterAuthorityTests(unittest.TestCase):
    def temp_root(self, folder: str) -> Path:
        root = Path(folder)
        contract = root / "benchmarks" / "first_pass"
        contract.mkdir(parents=True)
        for name in (
            "source_reviewer_roster.v1.json",
            "source_reviewer_roster.schema.json",
            "output_reviewer_roster.v1.json",
            "output_reviewer_roster.schema.json",
        ):
            shutil.copy2(ROOT / "benchmarks" / "first_pass" / name, contract / name)
        return root

    def arguments(self) -> dict:
        return {
            "authority_id": "domain.owner",
            "display_name": "Domain Owner",
            "buzz_pubkey": public_key_from_private("7".zfill(64)),
            "channel_id": "authority-review-channel",
        }

    def test_configuration_requires_out_of_band_identity_confirmation(self):
        with tempfile.TemporaryDirectory() as folder:
            root = self.temp_root(folder)
            with self.assertRaisesRegex(ValueError, "out-of-band authority identity"):
                configure_authority(
                    root, **self.arguments(), identity_checked_out_of_band=False,
                )
            for name in (
                "source_reviewer_roster.v1.json", "output_reviewer_roster.v1.json",
            ):
                roster = json.loads((root / "benchmarks/first_pass" / name).read_text())
                self.assertEqual(roster["authority"]["state"], "unconfigured")

    def test_one_configuration_binds_both_rosters_to_the_same_key_and_channel(self):
        with tempfile.TemporaryDirectory() as folder:
            root = self.temp_root(folder)
            authority = configure_authority(
                root, **self.arguments(), identity_checked_out_of_band=True,
            )
            for name in (
                "source_reviewer_roster.v1.json", "output_reviewer_roster.v1.json",
            ):
                roster = json.loads((root / "benchmarks/first_pass" / name).read_text())
                self.assertEqual(roster["authority"], authority)
                self.assertEqual(roster["reviewers"], [])

    def test_configured_authority_cannot_be_silently_replaced(self):
        with tempfile.TemporaryDirectory() as folder:
            root = self.temp_root(folder)
            configure_authority(root, **self.arguments(), identity_checked_out_of_band=True)
            changed = self.arguments()
            changed["buzz_pubkey"] = public_key_from_private("8".zfill(64))
            with self.assertRaisesRegex(ValueError, "different reviewer roster authority"):
                configure_authority(
                    root, **changed, identity_checked_out_of_band=True,
                )

    def test_partial_pair_commit_closes_both_rosters_until_same_authority_repairs_it(self):
        with tempfile.TemporaryDirectory() as folder:
            root = self.temp_root(folder)
            original_mutate = authority_script.mutate_reviewer_roster
            call_count = 0

            def fail_second_commit(*args, **kwargs):
                nonlocal call_count
                call_count += 1
                if call_count == 2:
                    raise OSError("simulated second roster commit failure")
                return original_mutate(*args, **kwargs)

            with mock.patch.object(
                authority_script,
                "mutate_reviewer_roster",
                side_effect=fail_second_commit,
            ):
                with self.assertRaisesRegex(OSError, "second roster commit failure"):
                    configure_authority(
                        root, **self.arguments(), identity_checked_out_of_band=True,
                    )

            with self.assertRaisesRegex(ValueError, "differs from paired"):
                load_source_reviewer_roster(root)
            with self.assertRaisesRegex(ValueError, "differs from paired"):
                load_output_reviewer_roster(root)

            source_path = root / "benchmarks/first_pass/source_reviewer_roster.v1.json"
            output_path = root / "benchmarks/first_pass/output_reviewer_roster.v1.json"
            before = (source_path.read_bytes(), output_path.read_bytes())
            reviewer = signed_reviewer_arguments(
                "source_review",
                reviewer_id="reviewer.blocked",
                display_name="Blocked Reviewer",
                role="qualified_deal_source_reviewer",
                qualification="M&A source review experience.",
                reviewer_private_key="5".zfill(64),
                approved_at="2026-08-16T04:00:00+00:00",
                created_at=1786852800,
            )
            with self.assertRaisesRegex(ValueError, "differs from paired"):
                add_reviewer(root, **reviewer, approval_confirmed=True)
            self.assertEqual(
                (source_path.read_bytes(), output_path.read_bytes()),
                before,
            )

            repaired = configure_authority(
                root, **self.arguments(), identity_checked_out_of_band=True,
            )
            self.assertEqual(load_source_reviewer_roster(root)["authority"], repaired)
            self.assertEqual(load_output_reviewer_roster(root)["authority"], repaired)

    def test_stale_precheck_cannot_overwrite_authority_that_wins_locked_commit(self):
        with tempfile.TemporaryDirectory() as folder:
            root = self.temp_root(folder)
            source_path = root / "benchmarks/first_pass/source_reviewer_roster.v1.json"
            original_mutate = authority_script.mutate_reviewer_roster
            competing = self.arguments()
            competing["authority_id"] = "competing.owner"
            competing["display_name"] = "Competing Owner"
            competing["buzz_pubkey"] = public_key_from_private("8".zfill(64))
            competing_authority = {
                "state": "signed_buzz_authority",
                "authority_id": competing["authority_id"],
                "display_name": competing["display_name"],
                "buzz_pubkey": competing["buzz_pubkey"],
                "channel_id": competing["channel_id"],
            }
            injected = False

            def inject_competing_commit(*args, **kwargs):
                nonlocal injected
                if not injected:
                    injected = True
                    roster = json.loads(source_path.read_text())
                    roster["authority"] = competing_authority
                    source_path.write_text(
                        json.dumps(roster, indent=2, sort_keys=True) + "\n"
                    )
                return original_mutate(*args, **kwargs)

            with mock.patch.object(
                authority_script,
                "mutate_reviewer_roster",
                side_effect=inject_competing_commit,
            ):
                with self.assertRaisesRegex(ValueError, "won the concurrent commit"):
                    configure_authority(
                        root, **self.arguments(), identity_checked_out_of_band=True,
                    )

            source = json.loads(source_path.read_text())
            self.assertEqual(source["authority"], competing_authority)
            with self.assertRaisesRegex(ValueError, "differs from paired"):
                load_source_reviewer_roster(root)


if __name__ == "__main__":
    unittest.main()
