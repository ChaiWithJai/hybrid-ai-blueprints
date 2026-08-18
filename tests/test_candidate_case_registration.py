import copy
import hashlib
import json
import multiprocessing
from pathlib import Path
import shutil
import tempfile
import time
import unittest
from unittest import mock

from core.candidate_case_registration import (
    _mutate_json_ledger,
    record_candidate_case_approval,
    register_candidate_case,
    validate_approval_ledger,
    validate_registration_ledger,
)
from core.candidate_source_review import build_candidate_source_review_packet
from core.first_pass_benchmark import validate_contract
from core.nostr_event import public_key_from_private
from core.review_signatures import review_attestation_content
from tests.nostr_signing import sign_event
from tests import test_candidate_case_approval as approval_fixtures


ROOT = Path(__file__).resolve().parents[1]
CHANNEL = "12345678-1234-4234-8234-123456789abc"
PRIVATE_KEYS = {
    "reviewer-a": "1".zfill(64),
    "reviewer-b": "2".zfill(64),
    "domain-owner": "3".zfill(64),
}


def append_ledger_value_in_process(path_text, value):
    path = Path(path_text)

    def append(ledger):
        items = list(ledger["items"])
        time.sleep(0.015)
        items.append(value)
        ledger["items"] = items
        return ledger, value

    _mutate_json_ledger(path, append)


def raw_attestation(record, kind, private_key, created_at):
    event = sign_event({
        "created_at": created_at,
        "kind": 9,
        "tags": [["h", CHANNEL]],
        "content": review_attestation_content(kind, record),
    }, private_key)
    record["buzz_event_id"] = event["id"]
    return event


class CandidateCaseRegistrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        approval_fixtures.CandidateCaseApprovalTests.setUpClass()
        cls.fixture = approval_fixtures.CandidateCaseApprovalTests(methodName="records")
        cls.fixture.packet = approval_fixtures.CandidateCaseApprovalTests.packet
        cls.fixture.draft = approval_fixtures.CandidateCaseApprovalTests.draft
        cls.base_draft_id = cls.fixture.draft["draft_id"]
        cls.base_candidate_id = cls.fixture.draft["candidate_id"]
        cls.base_source = copy.deepcopy(cls.fixture.draft["source"])

    def approved_records(self, packet, draft):
        self.fixture.packet = packet
        self.fixture.draft = draft
        submissions, approval, _ = self.fixture.records()
        roster = copy.deepcopy(approval_fixtures.ROSTER)
        roster_by_id = {item["reviewer_id"]: item for item in roster["reviewers"]}
        events = {}
        for index, submission in enumerate(submissions, 1):
            private_key = PRIVATE_KEYS[submission["reviewer_id"]]
            public_key = public_key_from_private(private_key)
            submission["reviewer_pubkey"] = public_key
            roster_by_id[submission["reviewer_id"]]["buzz_pubkey"] = public_key
            event = raw_attestation(
                submission, "candidate_source_review", private_key, 1786780000 + index,
            )
            events[event["id"]] = event
        approval["source_review_event_ids"] = [item["buzz_event_id"] for item in submissions]
        owner_key = PRIVATE_KEYS["domain-owner"]
        owner_public = public_key_from_private(owner_key)
        approval["reviewer_pubkey"] = owner_public
        roster_by_id["domain-owner"]["buzz_pubkey"] = owner_public
        approval_event = raw_attestation(
            approval, "candidate_case_approval", owner_key, 1786780010,
        )
        events[approval_event["id"]] = approval_event
        return submissions, approval, roster, events

    def temp_root(self, folder):
        root = Path(folder)
        shutil.copytree(ROOT / "benchmarks" / "first_pass", root / "benchmarks" / "first_pass")
        shutil.copy2(
            ROOT / "benchmarks" / "public_deal_corpus_manifest.json",
            root / "benchmarks" / "public_deal_corpus_manifest.json",
        )
        (root / "evidence").mkdir()
        shutil.copy2(
            ROOT / "evidence" / "public-deal-corpus-verification-v2.json",
            root / "evidence" / "public-deal-corpus-verification-v2.json",
        )
        for path in (ROOT / "evidence").glob("candidate*-source-*.json"):
            shutil.copy2(path, root / "evidence" / path.name)
        candidate_id = self.base_candidate_id
        acquisition_path = root / self.base_source["acquisition_evidence_path"]
        acquisition = json.loads(acquisition_path.read_text())
        relative_source = Path(acquisition["source"]["path"])
        destination = root / relative_source
        destination.parent.mkdir(parents=True)
        shutil.copy2(ROOT / "tests/fixtures/candidate_registration_source.htm", destination)
        source_bytes = destination.read_bytes()
        source_hash = hashlib.sha256(source_bytes).hexdigest()
        acquisition["source"]["sha256"] = source_hash
        acquisition["source"]["bytes"] = len(source_bytes)
        acquisition_path.write_text(json.dumps(acquisition, indent=2, sort_keys=True) + "\n")
        evidence_hash = hashlib.sha256(acquisition_path.read_bytes()).hexdigest()
        registry_path = root / "benchmarks/first_pass/candidate_deal_sources.v1.json"
        registry = json.loads(registry_path.read_text())
        candidate = next(item for item in registry["candidates"] if item["id"] == candidate_id)
        candidate["evidence_sha256"] = evidence_hash
        registry_path.write_text(json.dumps(registry, indent=2, sort_keys=True) + "\n")
        drafts_path = root / "benchmarks/first_pass/candidate_question_drafts.v1.json"
        drafts = json.loads(drafts_path.read_text())
        drafts["source_registry_sha256"] = hashlib.sha256(registry_path.read_bytes()).hexdigest()
        for item in drafts["drafts"]:
            if (
                item["candidate_id"] != candidate_id
                or item["source"]["acquisition_evidence_path"]
                != self.base_source["acquisition_evidence_path"]
            ):
                continue
            item["source"]["sha256"] = source_hash
            item["source"]["acquisition_evidence_sha256"] = evidence_hash
            for admitted_source in item["sources"]:
                if (
                    admitted_source["acquisition_evidence_path"]
                    == self.base_source["acquisition_evidence_path"]
                ):
                    admitted_source["sha256"] = source_hash
                    admitted_source["acquisition_evidence_sha256"] = evidence_hash
            for option in item["evidence_candidates"]:
                if option["source_sha256"] == self.base_source["sha256"]:
                    option["source_sha256"] = source_hash
        drafts_path.write_text(json.dumps(drafts, indent=2, sort_keys=True) + "\n")
        packet = build_candidate_source_review_packet(root)
        draft = next(item for item in packet["drafts"] if item["draft_id"] == self.base_draft_id)
        return root, packet, draft

    def cross_document_temp_root(self, folder):
        root = Path(folder)
        shutil.copytree(ROOT / "benchmarks" / "first_pass", root / "benchmarks" / "first_pass")
        shutil.copy2(
            ROOT / "benchmarks" / "public_deal_corpus_manifest.json",
            root / "benchmarks" / "public_deal_corpus_manifest.json",
        )
        (root / "evidence").mkdir()
        shutil.copy2(
            ROOT / "evidence" / "public-deal-corpus-verification-v2.json",
            root / "evidence" / "public-deal-corpus-verification-v2.json",
        )
        for path in (ROOT / "evidence").glob("candidate*-source-*.json"):
            shutil.copy2(path, root / "evidence" / path.name)
        drafts_path = root / "benchmarks/first_pass/candidate_question_drafts.v1.json"
        drafts_registry = json.loads(drafts_path.read_text())
        draft_record = next(
            item for item in drafts_registry["drafts"] if len(item["sources"]) == 2
        )
        source_registry_path = root / "benchmarks/first_pass/candidate_deal_sources.v1.json"
        source_registry = json.loads(source_registry_path.read_text())
        companion_registry_path = (
            root / "benchmarks/first_pass/candidate_companion_sources.v1.json"
        )
        companion_registry = json.loads(companion_registry_path.read_text())
        fixture_bytes = (ROOT / "tests/fixtures/candidate_registration_source.htm").read_bytes()
        replacements = {}
        for source_index, source in enumerate(draft_record["sources"]):
            evidence_path = root / source["acquisition_evidence_path"]
            acquisition = json.loads(evidence_path.read_text())
            relative_source = Path(acquisition["source"]["path"])
            destination = root / relative_source
            destination.parent.mkdir(parents=True, exist_ok=True)
            source_bytes = fixture_bytes + f"\n<!-- source {source_index + 1} -->\n".encode()
            destination.write_bytes(source_bytes)
            old_hash = source["sha256"]
            new_hash = hashlib.sha256(source_bytes).hexdigest()
            acquisition["source"]["sha256"] = new_hash
            acquisition["source"]["bytes"] = len(source_bytes)
            evidence_path.write_text(json.dumps(acquisition, indent=2, sort_keys=True) + "\n")
            evidence_hash = hashlib.sha256(evidence_path.read_bytes()).hexdigest()
            replacements[source["acquisition_evidence_path"]] = (
                old_hash, new_hash, evidence_hash, len(source_bytes)
            )
            if source_index == 0:
                record = next(
                    item for item in source_registry["candidates"]
                    if item["id"] == draft_record["candidate_id"]
                )
                record["evidence_sha256"] = evidence_hash
            else:
                record = next(
                    item for item in companion_registry["companions"]
                    if item["candidate_id"] == draft_record["candidate_id"]
                )
                record["source_sha256"] = new_hash
                record["source_bytes"] = len(source_bytes)
                record["evidence_sha256"] = evidence_hash
        source_registry_path.write_text(
            json.dumps(source_registry, indent=2, sort_keys=True) + "\n"
        )
        companion_registry_path.write_text(
            json.dumps(companion_registry, indent=2, sort_keys=True) + "\n"
        )
        for item in drafts_registry["drafts"]:
            for admitted_source in item["sources"]:
                replacement = replacements.get(admitted_source["acquisition_evidence_path"])
                if replacement:
                    old_hash, new_hash, evidence_hash, _ = replacement
                    admitted_source["sha256"] = new_hash
                    admitted_source["acquisition_evidence_sha256"] = evidence_hash
                    if item["source"]["acquisition_evidence_path"] == admitted_source["acquisition_evidence_path"]:
                        item["source"] = copy.deepcopy(admitted_source)
                    for option in item["evidence_candidates"]:
                        if option["source_sha256"] == old_hash:
                            option["source_sha256"] = new_hash
        drafts_registry["source_registry_sha256"] = hashlib.sha256(
            source_registry_path.read_bytes()
        ).hexdigest()
        drafts_registry["companion_source_registry_sha256"] = hashlib.sha256(
            companion_registry_path.read_bytes()
        ).hexdigest()
        drafts_path.write_text(json.dumps(drafts_registry, indent=2, sort_keys=True) + "\n")
        packet = build_candidate_source_review_packet(root)
        draft = next(item for item in packet["drafts"] if item["draft_id"] == draft_record["id"])
        return root, packet, draft

    def record_approval(self, root, packet, submissions, approval, roster, events):
        return record_candidate_case_approval(
            root,
            packet=packet,
            submissions=submissions,
            adjudication=None,
            approval=approval,
            reviewer_roster=roster,
            signed_events=events,
            recorded_at="2026-08-15T08:59:00+00:00",
        )

    def test_ledger_transaction_preserves_updates_from_distinct_processes(self):
        with tempfile.TemporaryDirectory() as folder:
            ledger = Path(folder) / "ledger.json"
            ledger.write_text('{"items": []}\n', encoding="utf-8")
            context = multiprocessing.get_context("spawn")
            processes = [
                context.Process(
                    target=append_ledger_value_in_process,
                    args=(str(ledger), value),
                )
                for value in range(12)
            ]
            for process in processes:
                process.start()
            for process in processes:
                process.join(20)
                self.assertEqual(process.exitcode, 0)

            restored = json.loads(ledger.read_text(encoding="utf-8"))
            self.assertEqual(sorted(restored["items"]), list(range(12)))
            lock_path = ledger.with_name(f".{ledger.name}.lock")
            self.assertEqual(lock_path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(list(ledger.parent.glob("*.tmp")), [])

    def test_signed_approval_registers_through_one_ledger_commit(self):
        with tempfile.TemporaryDirectory() as folder:
            root, packet, draft = self.temp_root(folder)
            submissions, approval, roster, events = self.approved_records(packet, draft)
            approval_record = self.record_approval(
                root, packet, submissions, approval, roster, events,
            )
            entry = register_candidate_case(
                root,
                packet=packet,
                submissions=submissions,
                adjudication=None,
                approval=approval,
                reviewer_roster=roster,
                signed_events=events,
                registered_at="2026-08-15T09:00:00+00:00",
            )
            report = validate_contract(root)
            ledger = json.loads(
                (root / "benchmarks/first_pass/candidate_case_registrations.v1.json").read_text()
            )
            self.assertEqual(len(ledger["registrations"]), 1)
            self.assertEqual(entry["case_id"], approval["case"]["id"])
            self.assertEqual(entry["approval_record_id"], approval_record["approval_record_id"])
            self.assertTrue((root / entry["source_document"]["path"]).is_file())
            self.assertTrue(report["structural_passed"], report["structural_errors"])
            self.assertEqual(report["inventory"]["registered_cases"], 6)
            self.assertEqual(report["inventory"]["registered_deals"], 4)
            self.assertEqual(report["inventory"]["domain_approved_cases"], 1)
            self.assertEqual(report["inventory"]["candidate_deals_acquired_not_registered"], 28)
            self.assertEqual(report["inventory"]["candidate_question_drafts_not_registered"], 318)

    def test_duplicate_approval_cannot_register_twice(self):
        with tempfile.TemporaryDirectory() as folder:
            root, packet, draft = self.temp_root(folder)
            submissions, approval, roster, events = self.approved_records(packet, draft)
            self.record_approval(root, packet, submissions, approval, roster, events)
            arguments = dict(
                packet=packet, submissions=submissions, adjudication=None,
                approval=approval, reviewer_roster=roster, signed_events=events,
                registered_at="2026-08-15T09:00:00+00:00",
            )
            register_candidate_case(root, **arguments)
            before = (root / "benchmarks/first_pass/candidate_case_registrations.v1.json").read_bytes()
            with self.assertRaisesRegex(ValueError, "already registered"):
                register_candidate_case(root, **arguments)
            self.assertEqual(
                (root / "benchmarks/first_pass/candidate_case_registrations.v1.json").read_bytes(),
                before,
            )

    def test_cross_document_approval_registers_both_sources_atomically(self):
        with tempfile.TemporaryDirectory() as folder:
            root, packet, draft = self.cross_document_temp_root(folder)
            submissions, approval, roster, events = self.approved_records(packet, draft)
            self.record_approval(root, packet, submissions, approval, roster, events)
            entry = register_candidate_case(
                root,
                packet=packet,
                submissions=submissions,
                adjudication=None,
                approval=approval,
                reviewer_roster=roster,
                signed_events=events,
                registered_at="2026-08-15T09:00:00+00:00",
            )
            report = validate_contract(root)
        self.assertEqual(len(entry["source_documents"]), 2)
        self.assertEqual(
            {item["filename"] for item in entry["source_documents"]},
            {item["filename"] for item in draft["sources"]},
        )
        self.assertTrue(report["structural_passed"], report["structural_errors"])
        self.assertEqual(report["inventory"]["slice_counts"]["multiple_documents"], 1)
        self.assertEqual(
            report["inventory"]["task_family_counts"][
                "cross_document_synthesis_and_recommendation"
            ],
            1,
        )

    def test_failed_commit_leaves_ledger_unchanged(self):
        with tempfile.TemporaryDirectory() as folder:
            root, packet, draft = self.temp_root(folder)
            submissions, approval, roster, events = self.approved_records(packet, draft)
            self.record_approval(root, packet, submissions, approval, roster, events)
            ledger = root / "benchmarks/first_pass/candidate_case_registrations.v1.json"
            before = ledger.read_bytes()
            with mock.patch(
                "core.candidate_case_registration._atomic_json",
                side_effect=OSError("simulated commit failure"),
            ):
                with self.assertRaisesRegex(OSError, "simulated commit failure"):
                    register_candidate_case(
                        root, packet=packet, submissions=submissions,
                        adjudication=None, approval=approval, reviewer_roster=roster,
                        signed_events=events,
                        registered_at="2026-08-15T09:00:00+00:00",
                    )
            self.assertEqual(ledger.read_bytes(), before)

    def test_registered_source_or_artifact_tamper_breaks_contract(self):
        with tempfile.TemporaryDirectory() as folder:
            root, packet, draft = self.temp_root(folder)
            submissions, approval, roster, events = self.approved_records(packet, draft)
            self.record_approval(root, packet, submissions, approval, roster, events)
            entry = register_candidate_case(
                root, packet=packet, submissions=submissions,
                adjudication=None, approval=approval, reviewer_roster=roster,
                signed_events=events,
                registered_at="2026-08-15T09:00:00+00:00",
            )
            source_path = root / entry["source_document"]["path"]
            source_path.write_bytes(source_path.read_bytes() + b"tamper")
            report = validate_contract(root)
            self.assertFalse(report["structural_passed"])
            self.assertTrue(any("registered source bytes differ" in item for item in report["structural_errors"]))

    def test_signed_approval_is_recorded_without_registering_a_case(self):
        with tempfile.TemporaryDirectory() as folder:
            root, packet, draft = self.temp_root(folder)
            submissions, approval, roster, events = self.approved_records(packet, draft)
            entry = self.record_approval(root, packet, submissions, approval, roster, events)
            report = validate_contract(root)
            ledger = json.loads(
                (root / "benchmarks/first_pass/candidate_case_approval_records.v1.json").read_text()
            )
            self.assertEqual(len(ledger["records"]), 1)
            self.assertEqual(entry["approval_id"], approval["approval_id"])
            self.assertEqual(report["inventory"]["candidate_approvals_recorded"], 1)
            self.assertEqual(report["inventory"]["candidate_approvals_unregistered"], 1)
            self.assertEqual(report["inventory"]["registered_cases"], 5)

    def test_registration_rejects_valid_but_unrecorded_approval(self):
        with tempfile.TemporaryDirectory() as folder:
            root, packet, draft = self.temp_root(folder)
            submissions, approval, roster, events = self.approved_records(packet, draft)
            with self.assertRaisesRegex(ValueError, "recorded exactly once"):
                register_candidate_case(
                    root, packet=packet, submissions=submissions,
                    adjudication=None, approval=approval, reviewer_roster=roster,
                    signed_events=events, registered_at="2026-08-15T09:00:00+00:00",
                )

    def test_recorded_approval_artifact_tamper_breaks_contract(self):
        with tempfile.TemporaryDirectory() as folder:
            root, packet, draft = self.temp_root(folder)
            submissions, approval, roster, events = self.approved_records(packet, draft)
            entry = self.record_approval(root, packet, submissions, approval, roster, events)
            approval_ref = entry["artifact_refs"]["case_approval"]
            (root / approval_ref["path"]).write_bytes(b"{}\n")
            ledger = json.loads(
                (root / "benchmarks/first_pass/candidate_case_approval_records.v1.json").read_text()
            )
            result = validate_approval_ledger(root, ledger)
            self.assertFalse(result["valid"])
            self.assertTrue(any("artifact hash differs" in item for item in result["errors"]))

    def test_duplicate_signed_approval_cannot_be_recorded_twice(self):
        with tempfile.TemporaryDirectory() as folder:
            root, packet, draft = self.temp_root(folder)
            submissions, approval, roster, events = self.approved_records(packet, draft)
            self.record_approval(root, packet, submissions, approval, roster, events)
            ledger = root / "benchmarks/first_pass/candidate_case_approval_records.v1.json"
            before = ledger.read_bytes()
            with self.assertRaisesRegex(ValueError, "already recorded"):
                self.record_approval(root, packet, submissions, approval, roster, events)
            self.assertEqual(ledger.read_bytes(), before)

    def test_failed_approval_record_commit_leaves_ledger_unchanged(self):
        with tempfile.TemporaryDirectory() as folder:
            root, packet, draft = self.temp_root(folder)
            submissions, approval, roster, events = self.approved_records(packet, draft)
            ledger = root / "benchmarks/first_pass/candidate_case_approval_records.v1.json"
            before = ledger.read_bytes()
            with mock.patch(
                "core.candidate_case_registration._atomic_json",
                side_effect=OSError("simulated approval commit failure"),
            ):
                with self.assertRaisesRegex(OSError, "simulated approval commit failure"):
                    self.record_approval(root, packet, submissions, approval, roster, events)
            self.assertEqual(ledger.read_bytes(), before)

    def test_approval_ledger_shape_fails_closed(self):
        result = validate_approval_ledger(
            ROOT,
            {"version": "0.0.0", "status": "unknown", "records": {}},
        )
        self.assertFalse(result["valid"])
        self.assertIn("approval ledger version is not 2.0.0", result["errors"])
        self.assertIn("approval ledger records must be an array", result["errors"])

    def test_approval_ledger_tail_deletion_breaks_chain_header(self):
        with tempfile.TemporaryDirectory() as folder:
            root, packet, draft = self.temp_root(folder)
            submissions, approval, roster, events = self.approved_records(packet, draft)
            self.record_approval(root, packet, submissions, approval, roster, events)
            ledger = json.loads(
                (root / "benchmarks/first_pass/candidate_case_approval_records.v1.json").read_text()
            )
            ledger["records"] = []
            result = validate_approval_ledger(root, ledger)
            self.assertFalse(result["valid"])
            self.assertIn("approval ledger entry count differs from records", result["errors"])
            self.assertIn("approval ledger head differs from append chain", result["errors"])

    def test_registration_ledger_tail_deletion_breaks_chain_header(self):
        with tempfile.TemporaryDirectory() as folder:
            root, packet, draft = self.temp_root(folder)
            submissions, approval, roster, events = self.approved_records(packet, draft)
            self.record_approval(root, packet, submissions, approval, roster, events)
            register_candidate_case(
                root, packet=packet, submissions=submissions,
                adjudication=None, approval=approval, reviewer_roster=roster,
                signed_events=events, registered_at="2026-08-15T09:00:00+00:00",
            )
            ledger = json.loads(
                (root / "benchmarks/first_pass/candidate_case_registrations.v1.json").read_text()
            )
            ledger["registrations"] = []
            result = validate_registration_ledger(root, ledger)
            self.assertFalse(result["valid"])
            self.assertIn(
                "registration ledger entry count differs from registrations",
                result["errors"],
            )
            self.assertIn("registration ledger head differs from append chain", result["errors"])

    def test_corrupt_approval_chain_fails_before_append(self):
        with tempfile.TemporaryDirectory() as folder:
            root, packet, draft = self.temp_root(folder)
            ledger_path = (
                root / "benchmarks/first_pass/candidate_case_approval_records.v1.json"
            )
            ledger = json.loads(ledger_path.read_text())
            ledger["head_sha256"] = "f" * 64
            ledger_path.write_text(json.dumps(ledger, indent=2, sort_keys=True) + "\n")
            before = ledger_path.read_bytes()
            submissions, approval, roster, events = self.approved_records(packet, draft)
            with self.assertRaisesRegex(ValueError, "ledger is invalid"):
                self.record_approval(root, packet, submissions, approval, roster, events)
            self.assertEqual(ledger_path.read_bytes(), before)

    def test_sealed_case_cannot_enter_approval_ledger(self):
        with tempfile.TemporaryDirectory() as folder:
            root, packet, draft = self.temp_root(folder)
            submissions, approval, roster, events = self.approved_records(packet, draft)
            approval["case"]["split"] = "sealed_test"
            owner_key = PRIVATE_KEYS["domain-owner"]
            approval_event = raw_attestation(
                approval, "candidate_case_approval", owner_key, 1786780020,
            )
            events = {
                event_id: event for event_id, event in events.items()
                if event.get("pubkey") != approval["reviewer_pubkey"]
            }
            events[approval_event["id"]] = approval_event
            with self.assertRaisesRegex(ValueError, "sealed expected answers"):
                self.record_approval(root, packet, submissions, approval, roster, events)


if __name__ == "__main__":
    unittest.main()
