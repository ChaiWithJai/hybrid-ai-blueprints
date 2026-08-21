"""Fail-closed oracle-context diagnostics for first-pass development cases.

An oracle-context run gives the answer model the registered supporting passage
instead of the normal retrieved set. It can localize deterministic failures. It
cannot create or replace a human semantic label.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from core.absence_oracle import canonical_sha256 as absence_canonical_sha256


EVIDENCE_KIND = "first_pass_oracle_context_diagnostic.v1"


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def canonical_sha256(value: Any) -> str:
    return sha256_bytes(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    )


def normalize(value: str) -> str:
    return " ".join(re.findall(r"[^\W_]+", value.casefold(), flags=re.UNICODE))


def _numeric_tokens(case: dict[str, Any]) -> list[str]:
    tokens: set[str] = set()
    for claim in case.get("required_claims", []):
        for token in re.findall(r"\$?\d[\d,.]*(?:\s*(?:percent|%|x|million|billion))?", claim.get("text", ""), re.I):
            normalized = re.sub(r"\s+", " ", token.casefold()).strip().rstrip(".,")
            if normalized:
                tokens.add(normalized)
    return sorted(tokens)


def deterministic_probe(case: dict[str, Any], response: str) -> dict[str, Any]:
    """Measure only literal development-contract properties.

    These checks are deliberately not called meaning, completeness, or
    accuracy. The registered cases have not received domain approval.
    """
    response = response or ""
    lowered = response.casefold()
    normalized = normalize(response)
    citations = [
        f"[{item['filename']}#{item['anchor']}]"
        for item in case.get("required_citations", [])
    ]
    missing_citations = [item for item in citations if item.casefold() not in lowered]
    numeric_tokens = _numeric_tokens(case)
    missing_numbers = [
        token for token in numeric_tokens
        if normalize(token) not in normalized
    ]
    forbidden_hits = [
        item for item in case.get("forbidden_claims", [])
        if normalize(item) and normalize(item) in normalized
    ]
    absence_terms = case.get("acceptable_absence_terms", [])
    absence_passed = None
    if case.get("answer_policy") == "refuse_absent":
        absence_passed = bool(absence_terms) and all(
            normalize(item) in normalized for item in absence_terms
        ) and not forbidden_hits
    passed = bool(response.strip()) and not missing_citations and not missing_numbers
    if absence_passed is not None:
        passed = passed and absence_passed
    return {
        "passed": passed,
        "response_present": bool(response.strip()),
        "citation_token_presence": {
            "passed": not missing_citations,
            "required": citations,
            "missing": missing_citations,
        },
        "registered_numeric_token_presence": {
            "passed": not missing_numbers,
            "required": numeric_tokens,
            "missing": missing_numbers,
        },
        "registered_absence_phrase_policy": {
            "passed": absence_passed,
            "required": absence_terms,
            "forbidden_hits": forbidden_hits,
        },
        "semantic_accuracy_state": "unverified",
    }


def oracle_prompt(case: dict[str, Any], passages: list[dict[str, Any]]) -> list[dict[str, str]]:
    evidence = "\n\n".join(
        f"SOURCE {item['citation']}\n{item['text']}" for item in passages
    )
    return [
        {
            "role": "system",
            "content": (
                "Answer the question using only the supplied source passages. "
                "Answer every requested part. Copy each citation token exactly after the "
                "claim it supports. Do not infer missing facts or numbers. Keep the answer "
                "under 180 words."
            ),
        },
        {
            "role": "user",
            "content": f"QUESTION\n{case['question']}\n\nORACLE SOURCE PASSAGES\n{evidence}",
        },
    ]


def absence_oracle_prompt(
    case: dict[str, Any],
    passages: list[dict[str, Any]],
    absence_audit: dict[str, Any],
) -> list[dict[str, str]]:
    """Build a development prompt from a complete deterministic corpus audit."""
    evidence = "\n\n".join(
        f"SOURCE {item['citation']}\n{item['text']}" for item in passages
    )
    confusable = "\n".join(
        f"- [{item['filename']}#{item['anchor']}] is classified as {item['relation']}."
        for item in absence_audit.get("required_confusable_evidence", [])
    )
    required_absence = " and ".join(case.get("acceptable_absence_terms", []))
    return [
        {
            "role": "system",
            "content": (
                "Answer the question using only the supplied passage and deterministic folder audit. "
                "The audit covered every admitted node in the registered folder. It found no match "
                "for the registered direct disclosure patterns. Do not convert a valuation multiple "
                "or financing amount into an entry leverage multiple. State both registered absence "
                f"phrases exactly: {required_absence}. Copy the required citation token exactly. "
                "This is a development diagnostic, not a domain accuracy decision."
            ),
        },
        {
            "role": "user",
            "content": (
                f"QUESTION\n{case['question']}\n\nREQUIRED SOURCE PASSAGE\n{evidence}\n\n"
                "COMPLETE FOLDER AUDIT\n"
                f"files={absence_audit.get('source_file_count')} "
                f"nodes={absence_audit.get('parsed_node_count')} "
                f"registered_pattern_hits={len(absence_audit.get('registered_direct_disclosure_hits', []))}\n"
                f"CONFUSABLE EVIDENCE\n{confusable}"
            ),
        },
    ]


def localization(baseline: dict[str, Any], oracle: dict[str, Any]) -> str:
    if baseline.get("passed") is True:
        return (
            "no_deterministic_baseline_failure"
            if oracle.get("passed") is True
            else "oracle_context_regressed_deterministic_contract"
        )
    if oracle.get("passed") is True:
        return "deterministic_failure_repaired_with_registered_oracle_context"
    return "deterministic_failure_persists_with_registered_oracle_context"


def assemble_case_record(
    case: dict[str, Any],
    baseline_response: str,
    passages: list[dict[str, Any]],
    oracle_observation: dict[str, Any] | None,
    absence_audit: dict[str, Any] | None = None,
) -> dict[str, Any]:
    baseline = deterministic_probe(case, baseline_response)
    is_absence_oracle = bool(
        case.get("answer_policy") == "refuse_absent"
        and isinstance(absence_audit, dict)
        and absence_audit.get("passed") is True
    )
    if case.get("answer_policy") != "answer" and not is_absence_oracle:
        return {
            "case_id": case["id"],
            "eligible": False,
            "reason": "answer-absence cases require a whole-corpus absence oracle",
            "baseline_response_sha256": sha256_bytes(baseline_response.encode("utf-8")),
            "baseline_probe": baseline,
            "oracle": None,
            "localization": "not_run_absence_oracle_not_implemented",
        }
    observation = dict(oracle_observation or {})
    response = str(observation.get("response", ""))
    prompt = (
        absence_oracle_prompt(case, passages, absence_audit or {})
        if is_absence_oracle else oracle_prompt(case, passages)
    )
    normalized_passages = [
        {
            "filename": item["filename"],
            "anchor": item["anchor"],
            "citation": item["citation"],
            "source_sha256": item["source_sha256"],
            "text": item["text"],
            "text_sha256": sha256_bytes(item["text"].encode("utf-8")),
        }
        for item in passages
    ]
    oracle_probe = deterministic_probe(case, response)
    result = {
        "case_id": case["id"],
        "eligible": True,
        "reason": None,
        "baseline_response_sha256": sha256_bytes(baseline_response.encode("utf-8")),
        "baseline_probe": baseline,
        "oracle": {
            "context_kind": (
                "whole_corpus_registered_pattern_absence_audit"
                if is_absence_oracle else "registered_positive_passages"
            ),
            "passages": normalized_passages,
            "prompt_sha256": canonical_sha256(prompt),
            "response": response,
            "response_sha256": sha256_bytes(response.encode("utf-8")),
            "provider": observation.get("provider"),
            "model": observation.get("model"),
            "latency_ms": observation.get("latency_ms"),
            "usage": observation.get("usage", {}),
            "raw_metadata": observation.get("raw_metadata", {}),
            "error": observation.get("error"),
            "probe": oracle_probe,
        },
        "localization": localization(baseline, oracle_probe),
    }
    if is_absence_oracle:
        result["absence_audit"] = absence_audit
        result["absence_audit_sha256"] = absence_canonical_sha256(absence_audit)
    return result


def validate_saved_oracle_context(root: Path, evidence_path: Path) -> dict[str, Any]:
    from core.absence_oracle import audit_whole_corpus_absence, load_absence_contract

    registry_path = root / "benchmarks" / "first_pass" / "development_registry.v2.json"
    responses_path = root / "evidence" / "bonsai-public-deal-battletest-responses.json"
    errors: list[str] = []
    try:
        registry_bytes = registry_path.read_bytes()
        responses_bytes = responses_path.read_bytes()
        registry = json.loads(registry_bytes)
        responses = json.loads(responses_bytes).get("responses", {})
        evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"passed": False, "errors": [str(exc)]}
    if evidence.get("verification_kind") != EVIDENCE_KIND:
        errors.append("unexpected oracle-context evidence kind")
    if evidence.get("registry_sha256") != sha256_bytes(registry_bytes):
        errors.append("oracle-context registry hash differs from the current registry")
    if evidence.get("baseline_responses_sha256") != sha256_bytes(responses_bytes):
        errors.append("oracle-context baseline response hash differs from the current artifact")
    if evidence.get("semantic_accuracy_state") != "unverified":
        errors.append("oracle-context evidence claims semantic accuracy")
    if evidence.get("accuracy_release_passed") is not False:
        errors.append("oracle-context evidence claims an accuracy release")
    has_absence_case = any(
        item.get("answer_policy") == "refuse_absent"
        for item in registry.get("cases", []) if isinstance(item, dict)
    )
    absence_contract: dict[str, Any] = {}
    absence_contract_bytes = b""
    if has_absence_case:
        try:
            absence_contract, absence_contract_bytes = load_absence_contract(root)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            errors.append(f"whole-corpus absence contract is unavailable: {exc}")
        if evidence.get("absence_contract_sha256") != sha256_bytes(absence_contract_bytes):
            errors.append("oracle-context absence contract hash differs from the current contract")
    saved_cases = evidence.get("cases")
    if not isinstance(saved_cases, list):
        return {"passed": False, "errors": [*errors, "oracle-context cases must be a list"]}
    by_id = {item.get("case_id"): item for item in saved_cases if isinstance(item, dict)}
    if len(by_id) != len(saved_cases):
        errors.append("oracle-context case IDs must be unique objects")
    recomputed: list[dict[str, Any]] = []
    for case in registry.get("cases", []):
        saved = by_id.get(case.get("id"))
        if not isinstance(saved, dict):
            errors.append(f"{case.get('id')}: oracle-context case is missing")
            continue
        baseline_response = str(responses.get(case["id"], {}).get("response", ""))
        saved_oracle = saved.get("oracle")
        passages: list[dict[str, Any]] = []
        observation = None
        if isinstance(saved_oracle, dict):
            for passage in saved_oracle.get("passages", []):
                if not isinstance(passage, dict):
                    errors.append(f"{case['id']}: invalid oracle passage")
                    continue
                text = str(passage.get("text", ""))
                if passage.get("text_sha256") != sha256_bytes(text.encode("utf-8")):
                    errors.append(f"{case['id']}: oracle passage text hash differs")
                passages.append({key: passage.get(key) for key in (
                    "filename", "anchor", "citation", "source_sha256", "text"
                )})
            expected_citations = {
                (item["filename"], item["anchor"], item["source_sha256"])
                for item in case.get("required_citations", [])
            }
            observed_citations = {
                (item.get("filename"), item.get("anchor"), item.get("source_sha256"))
                for item in passages
            }
            if observed_citations != expected_citations:
                errors.append(f"{case['id']}: oracle passages differ from registered citations")
            observation = {
                "response": saved_oracle.get("response", ""),
                "provider": saved_oracle.get("provider"),
                "model": saved_oracle.get("model"),
                "latency_ms": saved_oracle.get("latency_ms"),
                "usage": saved_oracle.get("usage", {}),
                "raw_metadata": saved_oracle.get("raw_metadata", {}),
                "error": saved_oracle.get("error"),
            }
        absence_audit = None
        if (
            case.get("answer_policy") == "refuse_absent"
            and case.get("id") == absence_contract.get("case_id")
        ):
            absence_audit = audit_whole_corpus_absence(root, absence_contract)
        current = assemble_case_record(
            case, baseline_response, passages, observation,
            absence_audit=absence_audit,
        )
        recomputed.append(current)
        if saved != current:
            errors.append(f"{case['id']}: saved oracle result differs from recomputation")
    extra = sorted(set(by_id) - {item.get("id") for item in registry.get("cases", [])})
    if extra:
        errors.append("unexpected oracle-context cases: " + ", ".join(extra))
    eligible = [item for item in recomputed if item.get("eligible") is True]
    completed = [
        item for item in eligible
        if item.get("oracle", {}).get("response")
        and not item.get("oracle", {}).get("error")
    ]
    return {
        "passed": not errors,
        "engineering_diagnostic_completed": len(completed) == len(eligible) and bool(eligible),
        "eligible_case_count": len(eligible),
        "completed_case_count": len(completed),
        "semantic_accuracy_state": "unverified",
        "accuracy_release_passed": False,
        "localization_counts": {
            name: sum(item.get("localization") == name for item in recomputed)
            for name in sorted({item.get("localization") for item in recomputed})
        },
        "errors": errors,
    }
