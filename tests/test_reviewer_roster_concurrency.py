import json
import multiprocessing
import shutil
import tempfile
import unittest
from pathlib import Path

from core.candidate_source_review import load_source_reviewer_roster
from core.first_pass_review import load_output_reviewer_roster
from scripts.add_output_reviewer import add_output_reviewer
from scripts.add_source_reviewer import add_reviewer
from tests.roster_fixtures import configured_roster, signed_reviewer_arguments


ROOT = Path(__file__).resolve().parents[1]


def _add_output(root_text: str, index: int) -> None:
    arguments = signed_reviewer_arguments(
        "output_review",
        reviewer_id=f"output.reviewer.{index}",
        display_name=f"Output Reviewer {index}",
        role=(
            "principal_output_reviewer" if index == 3
            else "qualified_deal_output_reviewer"
        ),
        qualification="Recorded M&A output review experience.",
        reviewer_private_key=f"{index + 5:x}".zfill(64),
        approved_at=f"2026-08-15T04:0{index}:00+00:00",
        created_at=1786783000 + index,
    )
    add_output_reviewer(
        Path(root_text), **arguments,
        approval_confirmed=True,
    )


def _add_source(root_text: str, index: int) -> None:
    arguments = signed_reviewer_arguments(
        "source_review",
        reviewer_id=f"source.reviewer.{index}",
        display_name=f"Source Reviewer {index}",
        role=("domain_case_owner" if index == 3 else "qualified_deal_source_reviewer"),
        qualification="Recorded M&A source review experience.",
        reviewer_private_key=f"{index + 9:x}".zfill(64),
        approved_at=f"2026-08-15T05:0{index}:00+00:00",
        created_at=1786783100 + index,
    )
    add_reviewer(
        Path(root_text), **arguments,
        approval_confirmed=True,
    )


class ReviewerRosterConcurrencyTests(unittest.TestCase):
    def temp_root(self, folder: str) -> Path:
        root = Path(folder)
        contract = root / "benchmarks" / "first_pass"
        contract.mkdir(parents=True)
        for name in (
            "output_reviewer_roster.v1.json",
            "output_reviewer_roster.schema.json",
            "source_reviewer_roster.v1.json",
            "source_reviewer_roster.schema.json",
        ):
            shutil.copy2(ROOT / "benchmarks" / "first_pass" / name, contract / name)
        for name in ("source_reviewer_roster.v1.json", "output_reviewer_roster.v1.json"):
            (contract / name).write_text(
                json.dumps(configured_roster(), indent=2, sort_keys=True) + "\n"
            )
        return root

    def run_concurrent(self, worker, root: Path) -> None:
        context = multiprocessing.get_context("spawn")
        processes = [context.Process(target=worker, args=(str(root), index)) for index in range(4)]
        for process in processes:
            process.start()
        for process in processes:
            process.join(10)
            self.assertEqual(process.exitcode, 0)

    def test_concurrent_output_approvals_preserve_every_reviewer(self):
        with tempfile.TemporaryDirectory() as folder:
            root = self.temp_root(folder)
            self.run_concurrent(_add_output, root)
            roster = load_output_reviewer_roster(root)
            self.assertEqual(len(roster["reviewers"]), 4)
            self.assertEqual(len({item["buzz_pubkey"] for item in roster["reviewers"]}), 4)

    def test_concurrent_source_approvals_preserve_every_reviewer(self):
        with tempfile.TemporaryDirectory() as folder:
            root = self.temp_root(folder)
            self.run_concurrent(_add_source, root)
            roster = load_source_reviewer_roster(root)
            self.assertEqual(len(roster["reviewers"]), 4)
            self.assertEqual(len({item["buzz_pubkey"] for item in roster["reviewers"]}), 4)


if __name__ == "__main__":
    unittest.main()
