"""Development evaluation for the deal-room workspace.

The evaluator keeps retrieval, generation, workflows, and human review status
separate. A deterministic pass is never promoted to domain approval.
"""

from __future__ import annotations

import hashlib
import json
import re
import urllib.error
import urllib.request
from pathlib import Path
from statistics import mean
from typing import Any

from core.deal_room_chat import retrieve_deal_room_evidence, validate_deal_room_answer


def citation_for(passage: dict[str, Any]) -> str:
    return f"[{passage['filename']}#{passage['source_anchor']}]"


def score_retrieval(case: dict[str, Any], ranked_citations: list[str]) -> dict[str, Any]:
    relevant = list(case["relevant_citations"])
    top_k = ranked_citations[: int(case["k"])]
    found = [citation for citation in relevant if citation in top_k]
    ranks = [ranked_citations.index(citation) + 1 for citation in relevant if citation in ranked_citations]
    recall = len(found) / len(relevant) if relevant else 0.0
    reciprocal_rank = 1 / min(ranks) if ranks else 0.0
    two_hop = all(citation in top_k for citation in relevant) if case["query_type"] == "multi_hop" else None
    return {
        "case_id": case["id"],
        "query_type": case["query_type"],
        "k": case["k"],
        "relevant_citations": relevant,
        "retrieved_citations": ranked_citations,
        "recall_at_k": recall,
        "reciprocal_rank": reciprocal_rank,
        "two_hop_recall_at_k": two_hop,
        "passed": recall >= float(case["minimum_recall"]) and two_hop is not False,
    }


def _assertion_map(record: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        item["name"]: item
        for item in record.get("assertions", [])
        if isinstance(item, dict) and isinstance(item.get("name"), str)
    }


def _response_from_assertion(record: dict[str, Any], name: str) -> str:
    assertion = _assertion_map(record).get(name, {})
    observed = assertion.get("observed")
    return observed if isinstance(observed, str) else ""


def evaluate_generation(
    root: Path,
    folder: Path,
    case: dict[str, Any],
    response_override: str | None = None,
) -> dict[str, Any]:
    record = json.loads((root / case["evidence_file"]).read_text(encoding="utf-8"))
    response = response_override if response_override is not None else _response_from_assertion(
        record, case["response_assertion"]
    )
    rendered_response = re.sub(r"^<!-- prism:[^>]+ -->\s*", "", response)
    passages = retrieve_deal_room_evidence(folder, case["question"], limit=8)
    citation = case["citation"]
    guard_violations = validate_deal_room_answer(
        rendered_response,
        passages,
        {"capital_structure": [citation]},
        question=case["question"],
    )
    required_missing = [term for term in case["required_terms"] if term.casefold() not in rendered_response.casefold()]
    forbidden_hits = [term for term in case["forbidden_terms"] if term.casefold() in rendered_response.casefold()]
    citation_present = citation in rendered_response
    faithfulness_passed = citation_present and not guard_violations
    relevance_passed = not required_missing and not forbidden_hits
    return {
        "case_id": case["id"],
        "trace_source": case["evidence_file"],
        "response_sha256": hashlib.sha256(response.encode()).hexdigest(),
        "faithfulness": {
            "passed": faithfulness_passed,
            "citation_present": citation_present,
            "guard_violations": guard_violations,
            "meaning": "Numbers and material terms passed the deterministic source guard. Semantic faithfulness remains unreviewed.",
        },
        "answer_relevance": {
            "passed": relevance_passed,
            "missing_required_terms": required_missing,
            "forbidden_hits": forbidden_hits,
            "meaning": "The registered requested components are present and registered out-of-scope equity rows are absent.",
        },
        "passed": faithfulness_passed and relevance_passed,
        "human_validation": "pending",
    }


def evaluate_workflow(root: Path, workflow: dict[str, Any]) -> dict[str, Any]:
    path = root / workflow["evidence_file"]
    if not path.exists():
        return {
            "workflow_id": workflow["id"],
            "passed": False,
            "first_failure": "evidence_file_missing",
            "transitions": [],
            "evidence_file": workflow["evidence_file"],
        }
    record = json.loads(path.read_text(encoding="utf-8"))
    assertions = _assertion_map(record)
    transitions = []
    first_failure = None
    for transition in workflow["transitions"]:
        assertion = assertions.get(transition["assertion"])
        passed = bool(assertion and assertion.get("passed") is True)
        item = {**transition, "passed": passed, "observed": assertion.get("observed") if assertion else None}
        transitions.append(item)
        if not passed and first_failure is None:
            first_failure = f"{transition['from']} -> {transition['to']}"
    return {
        "workflow_id": workflow["id"],
        "description": workflow["description"],
        "evidence_file": workflow["evidence_file"],
        "passed": first_failure is None,
        "first_failure": first_failure,
        "transitions": transitions,
    }


def _fetch_chat_messages(base_url: str, room: str) -> list[dict[str, Any]]:
    url = f"{base_url.rstrip('/')}/api/workspace/messages?room={room}"
    try:
        with urllib.request.urlopen(url, timeout=5) as response:
            payload = json.load(response)
    except (OSError, urllib.error.URLError, json.JSONDecodeError):
        return []
    return payload.get("messages", []) if isinstance(payload, dict) else []


def _agent_suggestions(message: dict[str, Any]) -> list[dict[str, str]]:
    content = str(message.get("content") or message.get("display_content") or "")
    suggestions = []
    if message.get("prism_acceptance_state") == "quarantined_uncommitted":
        suggestions.append({"mode": "publication_rejection", "reason": "The candidate failed a source or publication guard."})
    if re.search(r"^<!-- prism:", content):
        suggestions.append({"mode": "machine_markup_in_raw_trace", "reason": "The stored trace begins with an internal Prism marker; the product renderer must hide it."})
    if "[SOURCE [" in content:
        suggestions.append({"mode": "raw_citation_wrapper", "reason": "The stored answer uses a machine citation wrapper; the product renderer must normalize it."})
    if re.search(r"(?:/Users/|[A-Za-z]:\\\\)", content):
        suggestions.append({"mode": "local_path_exposure", "reason": "The trace contains a local filesystem path."})
    if re.search(r"^## First pass requested", content):
        suggestions.append({"mode": "workflow_event_noise", "reason": "A workflow request should not dominate the human conversation."})
    return suggestions


def build_chat_review_sample(
    config: dict[str, Any], base_url: str
) -> dict[str, Any]:
    messages = _fetch_chat_messages(base_url, config["room"])
    by_id = {message.get("id"): message for message in messages}
    samples = []
    for requested in config["chat_review_sample_ids"]:
        message = by_id.get(requested["event_id"])
        if not message:
            continue
        samples.append({
            "id": message.get("id"),
            "stratum": requested["stratum"],
            "created_at": message.get("created_at"),
            "acceptance_state": message.get("prism_acceptance_state"),
            "content": message.get("display_content") or message.get("content") or "",
            "metadata": {
                "signature_verified": message.get("signature_verified"),
                "guard_version": message.get("prism_guard_version"),
            },
            "agent_suggestions": _agent_suggestions(message),
            "human_annotation": None,
        })
    return {
        "source_event_count": len(messages),
        "requested_sample_count": len(config["chat_review_sample_ids"]),
        "loaded_sample_count": len(samples),
        "sampling": "ten preselected strata spanning request, fallback, rejection, review, replay, and accepted answer",
        "samples": samples,
        "agent_suggestion_count": sum(len(item["agent_suggestions"]) for item in samples),
        "human_annotation_count": 0,
        "review_state": "awaiting_human_free_text_review",
    }


def run_workspace_eval(
    root: Path,
    config_path: Path,
    *,
    base_url: str = "http://127.0.0.1:8787",
) -> dict[str, Any]:
    config = json.loads(config_path.read_text(encoding="utf-8"))
    folder = root / config["folder"]
    retrieval_results = []
    for case in config["rag_cases"]:
        ranked = retrieve_deal_room_evidence(folder, case["question"], limit=8)
        retrieval_results.append(score_retrieval(case, [citation_for(item) for item in ranked]))

    generation_results = [
        evaluate_generation(root, folder, case) for case in config["generation_cases"]
    ]
    negative_controls = []
    for case in config["generation_cases"]:
        baseline = _response_from_assertion(
            json.loads((root / case["evidence_file"]).read_text(encoding="utf-8")),
            case["response_assertion"],
        )
        wrong_number = re.sub(r"\$900\.0", "$990.0", baseline, count=1)
        missing_component = baseline.replace("Subordinated Mezzanine Debt", "Unidentified tranche", 1)
        for control_id, value, expected_failure in (
            ("wrong_number", wrong_number, "faithfulness"),
            ("missing_component", missing_component, "answer_relevance"),
        ):
            result = evaluate_generation(root, folder, case, response_override=value)
            caught = not result[expected_failure]["passed"]
            negative_controls.append({
                "case_id": case["id"],
                "control": control_id,
                "expected_failure": expected_failure,
                "caught": caught,
            })

    workflow_results = [evaluate_workflow(root, workflow) for workflow in config["agentic_workflows"]]
    chat_review = build_chat_review_sample(config, base_url)
    report = {
        "schema_version": 1,
        "benchmark_id": config["benchmark_id"],
        "measurement_state": "development_evaluation_not_domain_certification",
        "dataset_sha256": hashlib.sha256(config_path.read_bytes()).hexdigest(),
        "rag": {
            "cases": retrieval_results,
            "mean_recall_at_k": mean(item["recall_at_k"] for item in retrieval_results),
            "mrr": mean(item["reciprocal_rank"] for item in retrieval_results),
            "two_hop_pass_rate": mean(
                1.0 if item["two_hop_recall_at_k"] else 0.0
                for item in retrieval_results if item["two_hop_recall_at_k"] is not None
            ),
            "passed": all(item["passed"] for item in retrieval_results),
        },
        "generation": {
            "cases": generation_results,
            "negative_controls": negative_controls,
            "passed": all(item["passed"] for item in generation_results)
            and all(item["caught"] for item in negative_controls),
            "human_validation": "pending",
        },
        "agentic_workflows": {
            "cases": workflow_results,
            "end_to_end_pass_rate": mean(1.0 if item["passed"] else 0.0 for item in workflow_results),
            "passed": all(item["passed"] for item in workflow_results),
        },
        "chat_error_discovery": chat_review,
        "release_decision": {
            "passed": False,
            "reason": "Development checks do not substitute for blinded domain review or validated human labels.",
        },
        "limitations": [
            "Project Titan is a synthetic engineering fixture.",
            "The retrieval set contains six manually mapped development questions and is not a sealed test set.",
            "The generation set contains one saved Bonsai answer and deterministic checks only.",
            "Agent suggestions in chat error discovery are not human labels.",
            "No cloud or hybrid comparison was run in this benchmark.",
        ],
    }
    return report
