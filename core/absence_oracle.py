"""Whole corpus deterministic audit for registered answer absence cases."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
from typing import Any

from core.doc_parser import DealRoomParser, evidence_node_text, iter_evidence_nodes


CONTRACT_KIND = "first_pass_whole_corpus_absence_contract.v1"


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def canonical_sha256(value: Any) -> str:
    return sha256_bytes(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    )


def load_absence_contract(root: Path) -> tuple[dict[str, Any], bytes]:
    path = root / "benchmarks" / "first_pass" / "development_absence_oracles.v1.json"
    raw = path.read_bytes()
    contract = json.loads(raw)
    errors = absence_contract_errors(root, contract)
    if errors:
        raise ValueError("invalid absence contract: " + "; ".join(errors))
    return contract, raw


def absence_contract_errors(root: Path, contract: Any) -> list[str]:
    errors: list[str] = []
    if not isinstance(contract, dict):
        return ["absence contract must be an object"]
    if contract.get("verification_kind") != CONTRACT_KIND:
        errors.append("unexpected absence contract kind")
    if not (
        contract.get("case_id") == "citrix_entry_leverage_absent"
        and contract.get("deal_id") == "citrix_2022"
        and contract.get("answer_policy") == "refuse_absent"
        and contract.get("room") == "citrix"
    ):
        errors.append("absence contract case identity differs")
    if not (
        contract.get("semantic_accuracy_state") == "unverified"
        and contract.get("domain_review", {}).get("status") == "not_reviewed"
        and contract.get("domain_review", {}).get("owner") is None
    ):
        errors.append("absence contract overstates domain review or semantic accuracy")
    for path_field, hash_field in (
        ("registry_path", "registry_sha256"),
        ("source_manifest_path", "source_manifest_sha256"),
    ):
        relative = contract.get(path_field)
        if not isinstance(relative, str):
            errors.append(f"{path_field} is required")
            continue
        path = (root / relative).resolve()
        try:
            path.relative_to(root.resolve())
            observed_hash = sha256_bytes(path.read_bytes())
        except (OSError, ValueError) as exc:
            errors.append(f"{path_field} is unavailable: {exc}")
        else:
            if observed_hash != contract.get(hash_field):
                errors.append(f"{hash_field} differs from the current file")
    sources = contract.get("sources")
    if not isinstance(sources, list) or not sources:
        errors.append("absence contract sources are required")
    else:
        filenames = [item.get("filename") for item in sources if isinstance(item, dict)]
        if len(filenames) != len(sources) or len(filenames) != len(set(filenames)):
            errors.append("absence contract source filenames must be unique")
        for item in sources:
            if not isinstance(item, dict) or not (
                re.fullmatch(r"[a-f0-9]{64}", str(item.get("sha256", "")))
                and isinstance(item.get("bytes"), int)
                and item.get("bytes", 0) > 0
            ):
                errors.append("absence contract source identity is invalid")
    patterns = contract.get("registered_direct_disclosure_patterns")
    if not isinstance(patterns, list) or not patterns:
        errors.append("registered direct disclosure patterns are required")
    else:
        ids = []
        for item in patterns:
            if not isinstance(item, dict):
                errors.append("direct disclosure pattern must be an object")
                continue
            ids.append(item.get("id"))
            try:
                re.compile(str(item.get("regex", "")))
            except re.error:
                errors.append(f"invalid direct disclosure pattern: {item.get('id')}")
        if len(ids) != len(set(ids)) or any(not isinstance(item, str) or not item for item in ids):
            errors.append("direct disclosure pattern IDs must be unique strings")
    confusable = contract.get("required_confusable_evidence")
    if not isinstance(confusable, list) or not confusable:
        errors.append("required confusable evidence is missing")
    elif any(
        not isinstance(item, dict)
        or not isinstance(item.get("filename"), str)
        or not isinstance(item.get("anchor"), str)
        or not isinstance(item.get("required_terms"), list)
        or not item.get("required_terms")
        for item in confusable
    ):
        errors.append("required confusable evidence is invalid")
    limitations = " ".join(str(item).casefold() for item in contract.get("limitations", []))
    for phrase in (
        "after inspecting the development corpus",
        "zero pattern count proves only",
        "unregistered synonym",
        "no domain approval",
    ):
        if phrase not in limitations:
            errors.append(f"absence contract limitation is missing: {phrase}")
    return errors


def audit_whole_corpus_absence(root: Path, contract: dict[str, Any]) -> dict[str, Any]:
    """Scan every admitted node in the exact registered folder."""
    errors = absence_contract_errors(root, contract)
    if errors:
        return {"passed": False, "errors": errors}
    folder = (root / contract["source_folder"]).resolve()
    try:
        folder.relative_to(root.resolve())
    except ValueError:
        return {"passed": False, "errors": ["absence source folder escapes project root"]}
    if not folder.is_dir():
        return {"passed": False, "errors": ["absence source folder is unavailable"]}
    expected_sources = {
        item["filename"]: item for item in contract["sources"]
    }
    actual_files = sorted(
        path.name for path in folder.iterdir()
        if path.is_file() and not path.name.startswith(".")
    )
    if actual_files != sorted(expected_sources):
        return {
            "passed": False,
            "errors": ["absence source folder does not equal the registered file set"],
            "expected_files": sorted(expected_sources),
            "actual_files": actual_files,
        }
    for filename, expected in expected_sources.items():
        path = folder / filename
        raw = path.read_bytes()
        if len(raw) != expected["bytes"] or sha256_bytes(raw) != expected["sha256"]:
            return {"passed": False, "errors": [f"{filename}: source identity differs"]}
    parser = DealRoomParser()
    documents = parser.parse_deal_room_folder(str(folder))
    if parser.last_warnings:
        return {"passed": False, "errors": ["absence source parser returned warnings"]}
    if sorted(item.filename for item in documents) != sorted(expected_sources):
        return {"passed": False, "errors": ["parser did not admit the complete registered file set"]}
    nodes: list[dict[str, Any]] = []
    for document in documents:
        for node, titles in iter_evidence_nodes(document.root_node):
            text = evidence_node_text(node, titles, max_chars=100000)
            anchor = node.metadata.get("source_anchor") or f"node:{node.id}"
            nodes.append({
                "filename": document.filename,
                "anchor": anchor,
                "text": text,
                "text_sha256": sha256_bytes(text.encode("utf-8")),
            })
    node_index = {(item["filename"], item["anchor"]): item for item in nodes}
    direct_hits = []
    for pattern in contract["registered_direct_disclosure_patterns"]:
        compiled = re.compile(pattern["regex"])
        for node in nodes:
            for match in compiled.finditer(node["text"]):
                direct_hits.append({
                    "pattern_id": pattern["id"],
                    "filename": node["filename"],
                    "anchor": node["anchor"],
                    "matched_text": match.group(0),
                    "matched_text_sha256": sha256_bytes(match.group(0).encode("utf-8")),
                })
    confusable_records = []
    confusable_errors = []
    for expected in contract["required_confusable_evidence"]:
        node = node_index.get((expected["filename"], expected["anchor"]))
        if node is None:
            confusable_errors.append(
                f"{expected['filename']}#{expected['anchor']}: confusable node is missing"
            )
            continue
        missing_terms = [
            term for term in expected["required_terms"]
            if term.casefold() not in node["text"].casefold()
        ]
        if missing_terms:
            confusable_errors.append(
                f"{expected['filename']}#{expected['anchor']}: confusable terms are missing"
            )
        confusable_records.append({
            "filename": expected["filename"],
            "anchor": expected["anchor"],
            "relation": expected["relation"],
            "required_terms": expected["required_terms"],
            "missing_terms": missing_terms,
            "text_sha256": node["text_sha256"],
            "excerpt": node["text"][:1200],
        })
    file_records = []
    for filename, expected in sorted(expected_sources.items()):
        file_nodes = [
            {"anchor": item["anchor"], "text_sha256": item["text_sha256"]}
            for item in nodes if item["filename"] == filename
        ]
        file_records.append({
            "filename": filename,
            "source_sha256": expected["sha256"],
            "bytes": expected["bytes"],
            "node_count": len(file_nodes),
            "parsed_node_manifest_sha256": canonical_sha256(file_nodes),
        })
    audit_errors = [*confusable_errors]
    if direct_hits:
        audit_errors.append("registered direct disclosure pattern matched the corpus")
    return {
        "passed": not audit_errors,
        "scope": "complete_registered_deal_folder",
        "case_id": contract["case_id"],
        "deal_id": contract["deal_id"],
        "contract_sha256": canonical_sha256(contract),
        "source_manifest_sha256": contract["source_manifest_sha256"],
        "source_file_count": len(file_records),
        "parsed_node_count": len(nodes),
        "files": file_records,
        "registered_pattern_count": len(contract["registered_direct_disclosure_patterns"]),
        "registered_direct_disclosure_hits": direct_hits,
        "required_confusable_evidence": confusable_records,
        "semantic_accuracy_state": "unverified",
        "domain_review_status": "not_reviewed",
        "errors": audit_errors,
        "limitations": contract["limitations"],
    }
