#!/usr/bin/env python3
"""Run Bonsai on registered passages to localize deterministic failures."""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.ai_provider import ProviderRegistry, ProviderError  # noqa: E402
from core.absence_oracle import (  # noqa: E402
    audit_whole_corpus_absence,
    load_absence_contract,
)
from core.doc_parser import DealRoomParser, evidence_node_text, iter_evidence_nodes  # noqa: E402
from core.oracle_context_diagnostic import (  # noqa: E402
    EVIDENCE_KIND,
    assemble_case_record,
    absence_oracle_prompt,
    oracle_prompt,
    sha256_bytes,
    validate_saved_oracle_context,
)


REGISTRY = ROOT / "benchmarks" / "first_pass" / "development_registry.v2.json"
RESPONSES = ROOT / "evidence" / "bonsai-public-deal-battletest-responses.json"
DEAL_FOLDERS = {
    "anaplan_2022": ROOT / ".runtime" / "public-deal-corpus" / "anaplan",
    "citrix_2022": ROOT / ".runtime" / "public-deal-corpus" / "citrix",
    "microsoft_activision_2023": ROOT / ".runtime" / "public-deal-rooms" / "microsoft_activision",
}


def extract_registered_passages(case: dict) -> list[dict]:
    folder = DEAL_FOLDERS[case["deal_id"]]
    if not folder.is_dir():
        raise RuntimeError(f"source folder is unavailable for {case['deal_id']}")
    documents = DealRoomParser().parse_deal_room_folder(str(folder))
    passages = []
    for citation in case["required_citations"]:
        matches = []
        for document in documents:
            if document.filename != citation["filename"]:
                continue
            if document.metadata.get("source_sha256") != citation["source_sha256"]:
                raise RuntimeError(f"source hash differs for {citation['filename']}")
            for node, titles in iter_evidence_nodes(document.root_node):
                anchor = node.metadata.get("source_anchor") or f"node:{node.id}"
                if anchor == citation["anchor"]:
                    matches.append(evidence_node_text(node, titles, max_chars=12000))
        if len(matches) != 1 or not matches[0].strip():
            raise RuntimeError(
                f"expected one exact passage for {citation['filename']}#{citation['anchor']}"
            )
        passages.append({
            "filename": citation["filename"],
            "anchor": citation["anchor"],
            "citation": f"[{citation['filename']}#{citation['anchor']}]",
            "source_sha256": citation["source_sha256"],
            "text": matches[0],
        })
    return passages


def atomic_write(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(value, handle, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
    finally:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output", default="evidence/bonsai-oracle-context-diagnostic-v1.json"
    )
    args = parser.parse_args()
    registry_bytes = REGISTRY.read_bytes()
    responses_bytes = RESPONSES.read_bytes()
    registry = json.loads(registry_bytes)
    responses = json.loads(responses_bytes).get("responses", {})
    provider = ProviderRegistry().local
    if not provider.configured:
        raise RuntimeError("the local Bonsai provider is not configured")
    absence_contract, absence_contract_bytes = load_absence_contract(ROOT)
    absence_audit = audit_whole_corpus_absence(ROOT, absence_contract)
    cases = []
    for case in registry["cases"]:
        baseline = str(responses.get(case["id"], {}).get("response", ""))
        passages = extract_registered_passages(case)
        observation = None
        case_absence_audit = None
        prompt = None
        if case.get("answer_policy") == "answer":
            prompt = oracle_prompt(case, passages)
        elif case.get("id") == absence_contract.get("case_id") and absence_audit.get("passed"):
            case_absence_audit = absence_audit
            prompt = absence_oracle_prompt(case, passages, absence_audit)
        if prompt is not None:
            try:
                result = provider.complete(prompt, temperature=0.0)
                observation = {
                    "response": result.content.strip(),
                    "provider": result.provider_id,
                    "model": result.model,
                    "latency_ms": result.latency_ms,
                    "usage": result.usage,
                    "raw_metadata": result.raw_metadata,
                    "error": None,
                }
            except ProviderError as exc:
                observation = {
                    "response": "",
                    "provider": provider.provider_id,
                    "model": provider.model,
                    "latency_ms": None,
                    "usage": {},
                    "raw_metadata": {},
                    "error": str(exc),
                }
        cases.append(assemble_case_record(
            case, baseline, passages, observation,
            absence_audit=case_absence_audit,
        ))
        print(json.dumps({
            "case_id": case["id"],
            "eligible": cases[-1]["eligible"],
            "localization": cases[-1]["localization"],
        }))
    evidence = {
        "verification_kind": EVIDENCE_KIND,
        "recorded_at": datetime.now(timezone.utc).astimezone().isoformat(),
        "registry_sha256": sha256_bytes(registry_bytes),
        "baseline_responses_sha256": sha256_bytes(responses_bytes),
        "absence_contract_sha256": sha256_bytes(absence_contract_bytes),
        "semantic_accuracy_state": "unverified",
        "accuracy_release_passed": False,
        "cases": cases,
        "limitations": [
            "The registered development labels have no domain approval.",
            "The probe checks literal citation, number, and absence-policy tokens, not semantic accuracy or human usefulness.",
            "Supplying the registered passage changes context only; it does not prove why the normal system failed.",
            "The Citrix absence case scans all 2,401 admitted nodes in both registered files against three disclosed direct-disclosure patterns.",
            "The patterns were written after inspecting the development corpus and do not prove the absence of unregistered synonyms.",
        ],
    }
    output = (ROOT / args.output).resolve()
    atomic_write(output, evidence)
    validation = validate_saved_oracle_context(ROOT, output)
    print(json.dumps(validation, indent=2))
    return 0 if validation["passed"] and validation["engineering_diagnostic_completed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
