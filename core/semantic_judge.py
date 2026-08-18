"""Run an unvalidated, narrow deal-room judge through an explicit provider."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from core.ai_provider import OpenAICompatibleProvider, ProviderResult


class SemanticJudgeError(ValueError):
    pass


def load_judge_bundle(path: Path) -> dict[str, Any]:
    try:
        bundle = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SemanticJudgeError(f"judge bundle is unreadable: {exc}") from exc
    if bundle.get("status") != "candidate_unvalidated":
        raise SemanticJudgeError("judge bundle must state candidate_unvalidated")
    judges = bundle.get("judges")
    if not isinstance(judges, list) or not judges:
        raise SemanticJudgeError("judge bundle has no criteria")
    if len({item.get("id") for item in judges}) != len(judges):
        raise SemanticJudgeError("judge identifiers must be unique")
    return bundle


def build_judge_messages(
    bundle: dict[str, Any],
    criterion_id: str,
    *,
    task: str,
    evidence_packet: str,
    answer: str,
) -> tuple[list[dict[str, str]], dict[str, Any]]:
    criterion = next(
        (item for item in bundle.get("judges", []) if item.get("id") == criterion_id),
        None,
    )
    if criterion is None:
        raise SemanticJudgeError("unknown judge criterion")
    contract = bundle.get("input_contract", {})
    values = {"task": task, "evidence_packet": evidence_packet, "answer": answer}
    if any(not isinstance(value, str) or not value.strip() for value in values.values()):
        raise SemanticJudgeError("task, evidence packet, and answer are required")
    if len(evidence_packet) > int(contract.get("maximum_evidence_characters", 0)):
        raise SemanticJudgeError("evidence packet exceeds the judge contract")
    if len(answer) > int(contract.get("maximum_answer_characters", 0)):
        raise SemanticJudgeError("answer exceeds the judge contract")

    payload = {
        "criterion_id": criterion["id"],
        "criterion_version": criterion["version"],
        "criterion": criterion["criterion"],
        **values,
    }
    messages = [
        {"role": "system", "content": str(bundle["system_prompt"])},
        {"role": "user", "content": json.dumps(payload, sort_keys=True, ensure_ascii=False)},
    ]
    metadata = {
        "bundle_id": bundle["bundle_id"],
        "bundle_version": bundle["version"],
        "criterion_id": criterion["id"],
        "criterion_version": criterion["version"],
        "prompt_sha256": hashlib.sha256(
            json.dumps(messages, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        ).hexdigest(),
        "trusted_for_release": False,
    }
    return messages, metadata


def parse_judge_output(content: str) -> dict[str, Any]:
    try:
        value = json.loads(content)
    except (TypeError, json.JSONDecodeError) as exc:
        raise SemanticJudgeError("judge output is not valid JSON") from exc
    if not isinstance(value, dict) or set(value) != {"label", "rationale", "evidence"}:
        raise SemanticJudgeError("judge output must contain exactly label, rationale, and evidence")
    if value["label"] not in {"pass", "fail"}:
        raise SemanticJudgeError("judge label must be pass or fail")
    if not isinstance(value["rationale"], str) or not value["rationale"].strip() or len(value["rationale"]) > 600:
        raise SemanticJudgeError("judge rationale is invalid")
    if (
        not isinstance(value["evidence"], list)
        or len(value["evidence"]) > 5
        or any(not isinstance(item, str) or not item.strip() for item in value["evidence"])
    ):
        raise SemanticJudgeError("judge evidence is invalid")
    return value


def run_semantic_judge(
    provider: OpenAICompatibleProvider,
    bundle: dict[str, Any],
    criterion_id: str,
    *,
    task: str,
    evidence_packet: str,
    answer: str,
) -> dict[str, Any]:
    """Run the candidate judge while preserving its untrusted status."""

    messages, metadata = build_judge_messages(
        bundle,
        criterion_id,
        task=task,
        evidence_packet=evidence_packet,
        answer=answer,
    )
    result: ProviderResult = provider.complete(messages, temperature=0)
    parsed = parse_judge_output(result.content)
    return {
        **metadata,
        **parsed,
        "judge_provider_id": result.provider_id,
        "judge_model": result.model,
        "latency_ms": result.latency_ms,
        "usage": result.usage,
        "trusted_for_release": False,
        "decision_use": "development_only_until_calibrated",
    }
