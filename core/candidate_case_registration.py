"""Content-addressed, single-commit registration for approved public cases."""

from __future__ import annotations

import hashlib
import json
import os
import fcntl
from contextlib import contextmanager
from pathlib import Path
import re
import tempfile
import threading
from typing import Any, Callable

from core.candidate_case_approval import validate_candidate_case_approval
from core.candidate_source_review import draft_sources
from core.nostr_event import nostr_event_errors


LEDGER = "benchmarks/first_pass/candidate_case_registrations.v1.json"
APPROVAL_LEDGER = "benchmarks/first_pass/candidate_case_approval_records.v1.json"
ARTIFACT_DIR = "benchmarks/first_pass/signed_approval_artifacts"
SOURCE_DIR = "benchmarks/first_pass/registered_sources"
_LEDGER_THREAD_LOCK = threading.RLock()
GENESIS_SHA256 = "0" * 64
LEDGER_VERSION = "2.0.0"
APPROVAL_LEDGER_STATUS = "hash_chained_content_addressed_signed_approval_ledger"
REGISTRATION_LEDGER_STATUS = "hash_chained_content_addressed_registration_ledger"


def canonical_bytes(value: Any) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_once_content_addressed(path: Path, value: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != value:
            raise ValueError(f"content-addressed artifact collision at {path}")
        return
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(value)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temporary_name, path)
        except FileExistsError:
            if path.read_bytes() != value:
                raise ValueError(f"content-addressed artifact collision at {path}")
        os.unlink(temporary_name)
    except Exception:
        try:
            os.unlink(temporary_name)
        except OSError:
            pass
        raise


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(canonical_bytes(value))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except Exception:
        try:
            os.unlink(temporary_name)
        except OSError:
            pass
        raise


@contextmanager
def _ledger_lock(path: Path):
    """Serialize one ledger transaction across threads and local processes."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_name(f".{path.name}.lock")
    with _LEDGER_THREAD_LOCK:
        descriptor = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
        with os.fdopen(descriptor, "a+b") as handle:
            os.chmod(lock_path, 0o600)
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _mutate_json_ledger(
    path: Path,
    mutate: Callable[[dict[str, Any]], tuple[dict[str, Any], Any]],
) -> Any:
    """Reread, validate, and replace a JSON ledger under one process lock."""
    with _ledger_lock(path):
        ledger = json.loads(path.read_text(encoding="utf-8"))
        updated, result = mutate(ledger)
        _atomic_json(path, updated)
        return result


def _store_json(root: Path, value: Any) -> dict[str, str]:
    encoded = canonical_bytes(value)
    digest = sha256_bytes(encoded)
    relative = f"{ARTIFACT_DIR}/{digest}.json"
    _write_once_content_addressed(root / relative, encoded)
    return {"path": relative, "sha256": digest}


def _candidate_records(
    root: Path, candidate_id: str, draft_id: str,
) -> tuple[dict, dict, list[dict[str, Any]]]:
    contract = root / "benchmarks" / "first_pass"
    candidates = json.loads((contract / "candidate_deal_sources.v1.json").read_text())
    drafts = json.loads((contract / "candidate_question_drafts.v1.json").read_text())
    candidate_matches = [
        item for item in candidates.get("candidates", []) if item.get("id") == candidate_id
    ]
    draft_matches = [item for item in drafts.get("drafts", []) if item.get("id") == draft_id]
    if len(candidate_matches) != 1 or len(draft_matches) != 1:
        raise ValueError("candidate and draft identities must each resolve exactly once")
    candidate = candidate_matches[0]
    draft = draft_matches[0]
    if draft.get("candidate_id") != candidate_id:
        raise ValueError("draft does not belong to the approved candidate")
    acquisitions = []
    for source in draft_sources(draft):
        evidence_path = (root / source["acquisition_evidence_path"]).resolve()
        evidence_path.relative_to(root)
        evidence_bytes = evidence_path.read_bytes()
        if sha256_bytes(evidence_bytes) != source.get("acquisition_evidence_sha256"):
            raise ValueError("candidate acquisition evidence hash differs")
        acquisition = json.loads(evidence_bytes)
        acquired_source = acquisition.get("source", {})
        if (
            Path(str(acquired_source.get("path", ""))).name != source.get("filename")
            or acquired_source.get("sha256") != source.get("sha256")
        ):
            raise ValueError("candidate acquisition differs from the reviewed draft")
        acquisitions.append(acquisition)
    if not acquisitions:
        raise ValueError("reviewed draft has no admitted source")
    return candidate, draft, acquisitions


def record_candidate_case_approval(
    root: Path,
    *,
    packet: dict[str, Any],
    submissions: list[dict[str, Any]],
    adjudication: dict[str, Any] | None,
    approval: dict[str, Any],
    reviewer_roster: dict[str, Any],
    signed_events: dict[str, dict[str, Any]],
    recorded_at: str,
) -> dict[str, Any]:
    """Persist one valid signed approval chain without registering its case."""
    root = root.resolve()
    errors = validate_candidate_case_approval(
        root, packet, submissions, adjudication, approval,
        reviewer_roster=reviewer_roster, signed_events=signed_events,
    )
    if errors:
        raise ValueError("case approval is invalid: " + "; ".join(errors))
    if approval.get("case", {}).get("split") == "sealed_test":
        raise ValueError("sealed expected answers cannot be recorded in the repository ledger")
    for event_id, event in signed_events.items():
        event_errors = nostr_event_errors(event)
        if event_errors or event.get("id") != event_id:
            raise ValueError(f"raw Buzz event {event_id} is invalid: {'; '.join(event_errors)}")

    draft = next(
        item for item in packet.get("drafts", [])
        if item.get("draft_id") == approval.get("draft_id")
    )
    ledger_path = root / APPROVAL_LEDGER
    artifact_refs = {
        "source_review_packet": _store_json(root, packet),
        "source_reviews": _store_json(root, submissions),
        "source_adjudication": _store_json(root, adjudication) if adjudication else None,
        "case_approval": _store_json(root, approval),
        "reviewer_roster_snapshot": _store_json(root, reviewer_roster),
        "raw_buzz_events": _store_json(root, signed_events),
    }
    record_material = {
        "recorded_at": recorded_at,
        "candidate_id": draft["candidate_id"],
        "draft_id": approval["draft_id"],
        "case_id": approval["case"]["id"],
        "approval_id": approval["approval_id"],
        "artifact_refs": artifact_refs,
    }

    def append_approval(ledger: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
        validation = validate_approval_ledger(root, ledger)
        if not validation["valid"]:
            raise ValueError(
                "candidate approval ledger is invalid: " + "; ".join(validation["errors"])
            )
        records = ledger.get("records", [])
        duplicate_fields = {
            "approval_id": approval.get("approval_id"),
            "draft_id": approval.get("draft_id"),
            "case_id": approval.get("case", {}).get("id"),
        }
        for field, value in duplicate_fields.items():
            if any(item.get(field) == value for item in records):
                raise ValueError(f"case approval {field} is already recorded")
        material = {
            "sequence": len(records) + 1,
            "previous_entry_sha256": ledger["head_sha256"],
            **record_material,
        }
        approval_record_id = sha256_bytes(canonical_bytes(material))
        entry = {"approval_record_id": approval_record_id, **material}
        ledger["records"] = [*records, entry]
        ledger["entry_count"] = len(ledger["records"])
        ledger["head_sha256"] = approval_record_id
        return ledger, entry

    return _mutate_json_ledger(ledger_path, append_approval)


def load_approval_record_bundle(
    root: Path,
    approval_record_id: str,
) -> dict[str, Any]:
    ledger = json.loads((root / APPROVAL_LEDGER).read_text(encoding="utf-8"))
    matches = [
        item for item in ledger.get("records", [])
        if item.get("approval_record_id") == approval_record_id
    ]
    if len(matches) != 1:
        raise ValueError("approval record ID must resolve exactly once")
    entry = matches[0]
    refs = entry["artifact_refs"]
    return {
        "entry": entry,
        "packet": load_artifact(root, refs["source_review_packet"]),
        "submissions": load_artifact(root, refs["source_reviews"]),
        "adjudication": (
            load_artifact(root, refs["source_adjudication"])
            if refs.get("source_adjudication") else None
        ),
        "approval": load_artifact(root, refs["case_approval"]),
        "reviewer_roster": load_artifact(root, refs["reviewer_roster_snapshot"]),
        "signed_events": load_artifact(root, refs["raw_buzz_events"]),
    }


def register_candidate_case(
    root: Path,
    *,
    packet: dict[str, Any],
    submissions: list[dict[str, Any]],
    adjudication: dict[str, Any] | None,
    approval: dict[str, Any],
    reviewer_roster: dict[str, Any],
    signed_events: dict[str, dict[str, Any]],
    registered_at: str,
) -> dict[str, Any]:
    """Write collision-checked inputs, then atomically append one ledger entry."""
    root = root.resolve()
    errors = validate_candidate_case_approval(
        root, packet, submissions, adjudication, approval,
        reviewer_roster=reviewer_roster, signed_events=signed_events,
    )
    if errors:
        raise ValueError("case approval is invalid: " + "; ".join(errors))
    for event_id, event in signed_events.items():
        event_errors = nostr_event_errors(event)
        if event_errors:
            raise ValueError(f"raw Buzz event {event_id} is invalid: {'; '.join(event_errors)}")
        if event.get("id") != event_id:
            raise ValueError("raw Buzz event map key differs from event ID")

    approval_ledger = json.loads((root / APPROVAL_LEDGER).read_text(encoding="utf-8"))
    approval_result = validate_approval_ledger(root, approval_ledger)
    if not approval_result["valid"]:
        raise ValueError("candidate approval ledger is invalid: " + "; ".join(approval_result["errors"]))
    approval_matches = [
        item for item in approval_result["approvals"]
        if item.get("approval_id") == approval.get("approval_id")
    ]
    if len(approval_matches) != 1:
        raise ValueError("case approval must be recorded exactly once before registration")
    approval_record = approval_matches[0]
    recorded_bundle = load_approval_record_bundle(root, approval_record["approval_record_id"])
    expected_bundle = {
        "packet": packet,
        "submissions": submissions,
        "adjudication": adjudication,
        "approval": approval,
        "reviewer_roster": reviewer_roster,
        "signed_events": signed_events,
    }
    if any(recorded_bundle[field] != value for field, value in expected_bundle.items()):
        raise ValueError("registration inputs differ from the recorded signed approval bundle")

    case = approval["case"]
    if case.get("split") == "sealed_test":
        raise ValueError("sealed expected answers cannot be registered in the repository ledger")
    candidate_id = str(case["deal_id"])
    draft_id = str(approval["draft_id"])
    candidate, draft, acquisitions = _candidate_records(root, candidate_id, draft_id)

    ledger_path = root / LEDGER
    base_case_ids = {
        item.get("id")
        for item in json.loads(
            (root / "benchmarks" / "first_pass" / "development_registry.v2.json").read_text()
        ).get("cases", [])
    }

    source_documents = []
    for source_index, acquisition in enumerate(acquisitions, start=1):
        source = acquisition.get("source", {})
        source_path = (root / str(source.get("path", ""))).resolve()
        source_path.relative_to(root)
        if not source_path.is_file() or sha256_path(source_path) != source.get("sha256"):
            raise ValueError("acquired candidate source bytes are missing or changed")
        filename = Path(str(source["path"])).name
        if not re.fullmatch(r"[A-Za-z0-9._-]+", filename):
            raise ValueError("registered source filename is unsafe")
        source_relative = f"{SOURCE_DIR}/{source['sha256']}/{filename}"
        _write_once_content_addressed(root / source_relative, source_path.read_bytes())
        source_documents.append({
            "id": f"candidate_{candidate_id}_{source['sha256'][:12]}_{source_index}",
            "room": candidate_id,
            "filename": filename,
            "path": source_relative,
            "publisher": "U.S. Securities and Exchange Commission",
            "canonical_url": source["primary_url"],
            "retrieval_urls": list(dict.fromkeys(
                value for value in (source.get("primary_url"), source.get("index_url"))
                if value
            )),
            "sha256": source["sha256"],
            "bytes": source["bytes"],
            "source_type": acquisition.get("parser", {}).get("file_type"),
        })
    artifact_refs = {
        "source_review_packet": _store_json(root, packet),
        "source_reviews": _store_json(root, submissions),
        "source_adjudication": _store_json(root, adjudication) if adjudication else None,
        "case_approval": _store_json(root, approval),
        "reviewer_roster_snapshot": _store_json(root, reviewer_roster),
        "raw_buzz_events": _store_json(root, signed_events),
    }
    registration_material = {
        "registered_at": registered_at,
        "candidate_id": candidate_id,
        "draft_id": draft_id,
        "case_id": case["id"],
        "approval_id": approval["approval_id"],
        "approval_record_id": approval_record["approval_record_id"],
        "case": case,
        "source_document": source_documents[0],
        "source_documents": source_documents,
        "artifact_refs": artifact_refs,
    }

    def append_registration(
        ledger: dict[str, Any],
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        validation = validate_registration_ledger(root, ledger)
        if not validation["valid"]:
            raise ValueError(
                "candidate registration ledger is invalid: "
                + "; ".join(validation["errors"])
            )
        registrations = ledger.get("registrations", [])
        existing_cases = {*base_case_ids}
        existing_cases.update(item.get("case_id") for item in registrations)
        if case["id"] in existing_cases:
            raise ValueError("case ID is already registered")
        if any(item.get("approval_id") == approval["approval_id"] for item in registrations):
            raise ValueError("case approval is already registered")
        if any(item.get("draft_id") == draft_id for item in registrations):
            raise ValueError("candidate draft is already registered")
        deal_splits = {
            item.get("case", {}).get("split") for item in registrations
            if item.get("candidate_id") == candidate_id
        }
        if deal_splits and case["split"] not in deal_splits:
            raise ValueError("candidate deal is already registered in a different split")
        material = {
            "sequence": len(registrations) + 1,
            "previous_entry_sha256": ledger["head_sha256"],
            **registration_material,
        }
        registration_id = sha256_bytes(canonical_bytes(material))
        entry = {"registration_id": registration_id, **material}
        ledger["registrations"] = [*registrations, entry]
        ledger["entry_count"] = len(ledger["registrations"])
        ledger["head_sha256"] = registration_id
        return ledger, entry

    return _mutate_json_ledger(ledger_path, append_registration)


def load_artifact(root: Path, reference: dict[str, str]) -> Any:
    path = (root / reference["path"]).resolve()
    try:
        path.relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError("registration artifact escapes the project") from exc
    value = path.read_bytes()
    if sha256_bytes(value) != reference.get("sha256"):
        raise ValueError(f"registration artifact hash differs: {reference.get('path')}")
    return json.loads(value)


def validate_approval_ledger(root: Path, ledger: dict[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    approvals: list[dict[str, Any]] = []
    if ledger.get("version") != LEDGER_VERSION:
        errors.append(f"approval ledger version is not {LEDGER_VERSION}")
    if ledger.get("status") != APPROVAL_LEDGER_STATUS:
        errors.append("approval ledger status is invalid")
    records = ledger.get("records")
    if not isinstance(records, list):
        return {
            "valid": False,
            "approvals": [],
            "errors": [*errors, "approval ledger records must be an array"],
        }
    seen_record_ids: set[str] = set()
    seen_approval_ids: set[str] = set()
    seen_case_ids: set[str] = set()
    seen_draft_ids: set[str] = set()
    previous_entry_sha256 = GENESIS_SHA256
    for index, entry in enumerate(records):
        location = f"approval record {index}"
        if not isinstance(entry, dict):
            errors.append(f"{location}: entry must be an object")
            continue
        if entry.get("sequence") != index + 1:
            errors.append(f"{location}: sequence does not match append order")
        if entry.get("previous_entry_sha256") != previous_entry_sha256:
            errors.append(f"{location}: previous entry hash differs")
        for field, seen in (
            ("approval_record_id", seen_record_ids),
            ("approval_id", seen_approval_ids),
            ("case_id", seen_case_ids),
            ("draft_id", seen_draft_ids),
        ):
            value = entry.get(field)
            if value in seen:
                errors.append(f"{location}: duplicate {field}")
            seen.add(value)
        try:
            bundle = load_approval_record_bundle(root, entry["approval_record_id"])
            approval_errors = validate_candidate_case_approval(
                root,
                bundle["packet"],
                bundle["submissions"],
                bundle["adjudication"],
                bundle["approval"],
                reviewer_roster=bundle["reviewer_roster"],
                signed_events=bundle["signed_events"],
            )
            if approval_errors:
                raise ValueError("; ".join(approval_errors))
            approval = bundle["approval"]
            draft = next(
                item for item in bundle["packet"].get("drafts", [])
                if item.get("draft_id") == approval.get("draft_id")
            )
            expected = {
                "candidate_id": draft.get("candidate_id"),
                "draft_id": approval.get("draft_id"),
                "case_id": approval.get("case", {}).get("id"),
                "approval_id": approval.get("approval_id"),
            }
            for field, value in expected.items():
                if entry.get(field) != value:
                    raise ValueError(f"{field} differs from the signed approval bundle")
            event_ids = {
                item.get("buzz_event_id") for item in bundle["submissions"]
                if item.get("buzz_event_id")
            }
            if bundle["adjudication"] and bundle["adjudication"].get("buzz_event_id"):
                event_ids.add(bundle["adjudication"]["buzz_event_id"])
            event_ids.add(approval.get("buzz_event_id"))
            if set(bundle["signed_events"]) != event_ids:
                raise ValueError("stored raw events differ from the exact approval chain")
            material = {key: value for key, value in entry.items() if key != "approval_record_id"}
            if sha256_bytes(canonical_bytes(material)) != entry.get("approval_record_id"):
                raise ValueError("approval record ID differs from ledger content")
        except (KeyError, OSError, json.JSONDecodeError, StopIteration, TypeError, ValueError) as exc:
            errors.append(f"{location}: {exc}")
            continue
        approvals.append(entry)
        previous_entry_sha256 = entry["approval_record_id"]
    if ledger.get("entry_count") != len(records):
        errors.append("approval ledger entry count differs from records")
    if ledger.get("head_sha256") != previous_entry_sha256:
        errors.append("approval ledger head differs from append chain")
    return {"valid": not errors, "approvals": approvals, "errors": errors}


def validate_registration_ledger(root: Path, ledger: dict[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    cases: list[dict[str, Any]] = []
    documents: list[dict[str, Any]] = []
    if ledger.get("version") != LEDGER_VERSION:
        errors.append(f"registration ledger version is not {LEDGER_VERSION}")
    if ledger.get("status") != REGISTRATION_LEDGER_STATUS:
        errors.append("registration ledger status is invalid")
    registrations = ledger.get("registrations")
    if not isinstance(registrations, list):
        return {
            "valid": False,
            "cases": [],
            "documents": [],
            "errors": [*errors, "registration ledger registrations must be an array"],
        }
    seen_registration_ids: set[str] = set()
    seen_case_ids: set[str] = set()
    seen_draft_ids: set[str] = set()
    previous_entry_sha256 = GENESIS_SHA256
    for index, entry in enumerate(registrations):
        location = f"registration {index}"
        if not isinstance(entry, dict):
            errors.append(f"{location}: entry must be an object")
            continue
        if entry.get("sequence") != index + 1:
            errors.append(f"{location}: sequence does not match append order")
        if entry.get("previous_entry_sha256") != previous_entry_sha256:
            errors.append(f"{location}: previous entry hash differs")
        registration_id = entry.get("registration_id")
        if registration_id in seen_registration_ids:
            errors.append(f"{location}: duplicate registration ID")
        seen_registration_ids.add(registration_id)
        if entry.get("case_id") in seen_case_ids:
            errors.append(f"{location}: duplicate case ID")
        seen_case_ids.add(entry.get("case_id"))
        if entry.get("draft_id") in seen_draft_ids:
            errors.append(f"{location}: duplicate draft ID")
        seen_draft_ids.add(entry.get("draft_id"))
        try:
            refs = entry["artifact_refs"]
            packet = load_artifact(root, refs["source_review_packet"])
            submissions = load_artifact(root, refs["source_reviews"])
            adjudication = (
                load_artifact(root, refs["source_adjudication"])
                if refs.get("source_adjudication") else None
            )
            approval = load_artifact(root, refs["case_approval"])
            roster = load_artifact(root, refs["reviewer_roster_snapshot"])
            events = load_artifact(root, refs["raw_buzz_events"])
            recorded_bundle = load_approval_record_bundle(root, entry["approval_record_id"])
            if (
                recorded_bundle["packet"] != packet
                or recorded_bundle["submissions"] != submissions
                or recorded_bundle["adjudication"] != adjudication
                or recorded_bundle["approval"] != approval
                or recorded_bundle["reviewer_roster"] != roster
                or recorded_bundle["signed_events"] != events
            ):
                raise ValueError("registered artifacts differ from the recorded approval bundle")
            for event_id, event in events.items():
                event_errors = nostr_event_errors(event)
                if event_errors or event.get("id") != event_id:
                    raise ValueError(
                        f"raw event {event_id} failed replay: {'; '.join(event_errors)}"
                    )
            approval_errors = validate_candidate_case_approval(
                root, packet, submissions, adjudication, approval,
                reviewer_roster=roster, signed_events=events,
            )
            if approval_errors:
                raise ValueError("; ".join(approval_errors))
            if approval.get("case") != entry.get("case"):
                raise ValueError("ledger case differs from its signed approval")
            if approval.get("draft_id") != entry.get("draft_id"):
                raise ValueError("ledger draft differs from its signed approval")
            draft = next(
                item for item in packet.get("drafts", [])
                if item.get("draft_id") == approval.get("draft_id")
            )
            if entry.get("candidate_id") != draft.get("candidate_id"):
                raise ValueError("ledger candidate differs from the reviewed packet")
            expected_event_ids = {
                item.get("buzz_event_id") for item in submissions
                if item.get("buzz_event_id")
            }
            if adjudication and adjudication.get("buzz_event_id"):
                expected_event_ids.add(adjudication["buzz_event_id"])
            expected_event_ids.add(approval.get("buzz_event_id"))
            if set(events) != expected_event_ids:
                raise ValueError("stored raw events differ from the exact approval chain")
            channel_tags = {
                tag[1]
                for event in events.values()
                for tag in event.get("tags", [])
                if isinstance(tag, list) and len(tag) == 2 and tag[0] == "h"
            }
            if len(channel_tags) != 1:
                raise ValueError("approval-chain events do not share exactly one Buzz channel")
            reviewed_sources = draft_sources(draft)
            registered_documents = entry.get("source_documents", [entry["source_document"]])
            registered_identity = sorted(
                (item.get("filename"), item.get("sha256")) for item in registered_documents
            )
            reviewed_identity = sorted(
                (item.get("filename"), item.get("sha256")) for item in reviewed_sources
            )
            if registered_identity != reviewed_identity:
                raise ValueError("registered source documents differ from the reviewed packet")
            for document in registered_documents:
                source_path = root / document["path"]
                if sha256_path(source_path) != document.get("sha256"):
                    raise ValueError("registered source bytes differ")
            material = {key: value for key, value in entry.items() if key != "registration_id"}
            if sha256_bytes(canonical_bytes(material)) != registration_id:
                raise ValueError("registration ID differs from ledger content")
        except (KeyError, OSError, json.JSONDecodeError, StopIteration, TypeError, ValueError) as exc:
            errors.append(f"{location}: {exc}")
            continue
        cases.append(entry["case"])
        documents.extend(entry.get("source_documents", [entry["source_document"]]))
        previous_entry_sha256 = entry["registration_id"]
    if ledger.get("entry_count") != len(registrations):
        errors.append("registration ledger entry count differs from registrations")
    if ledger.get("head_sha256") != previous_entry_sha256:
        errors.append("registration ledger head differs from append chain")
    return {"valid": not errors, "cases": cases, "documents": documents, "errors": errors}
