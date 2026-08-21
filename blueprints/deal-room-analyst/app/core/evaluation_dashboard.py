"""Truthful, decision-oriented summary for the Prism Evaluation view."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _load_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def _mean(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 4) if values else None


def build_evaluation_dashboard(
    root: Path,
    *,
    room: str,
    review_snapshot: dict[str, Any],
    provider_statuses: list[dict[str, Any]],
    experiment_snapshot: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build one dashboard without treating missing evidence as a passing zero."""

    framework = _load_json(root / "benchmarks" / "evaluation_framework.v1.json", {})
    workspace = _load_json(root / "evidence" / "workspace-eval-v1.json", {})
    development = _load_json(
        root / "evidence" / "first-pass-development-evaluation-v2.json", {},
    )
    registry = _load_json(
        root / "benchmarks" / "first_pass" / "development_registry.v2.json", {},
    )

    providers = {str(item.get("provider_id")): item for item in provider_statuses}
    local = next((item for item in provider_statuses if item.get("kind") == "local"), None)
    cloud = next((item for item in provider_statuses if item.get("kind") == "cloud"), None)
    local = local or providers.get("local") or {}
    cloud = cloud or providers.get("cloud") or {}

    rag = workspace.get("rag", {})
    workflows = workspace.get("agentic_workflows", {})
    generation = workspace.get("generation", {})
    review_session = review_snapshot.get("session", {})
    annotations = review_snapshot.get("annotations", {})

    human_label_count = len(annotations) if isinstance(annotations, dict) else 0
    target_labels = int(framework.get("judge_validation", {}).get(
        "minimum_labels_per_failure_mode", 100,
    ))
    judge_ids = [
        str(item.get("id"))
        for item in framework.get("evaluator_registry", [])
        if item.get("kind") == "llm_judge"
    ]
    criterion_label_counts = {
        judge_id: sum(
            1 for annotation in annotations.values()
            if isinstance(annotation, dict)
            and isinstance(annotation.get("criterion_labels"), dict)
            and annotation["criterion_labels"].get(judge_id) in {"pass", "fail"}
        )
        for judge_id in judge_ids
    } if isinstance(annotations, dict) else {judge_id: 0 for judge_id in judge_ids}
    largest_criterion_set = max(criterion_label_counts.values(), default=0)
    judge_ready = largest_criterion_set >= target_labels
    domain_review_complete = bool(
        review_snapshot.get("domain_review", {}).get("completed")
    )
    local_configured = bool(local.get("configured"))
    cloud_configured = bool(cloud.get("configured"))

    rag_cases = rag.get("cases", []) if isinstance(rag.get("cases"), list) else []
    workflow_cases = workflows.get("cases", []) if isinstance(workflows.get("cases"), list) else []
    generation_cases = generation.get("cases", []) if isinstance(generation.get("cases"), list) else []
    first_pass_cases = registry.get("cases", []) if isinstance(registry.get("cases"), list) else []

    route_experiments = [
        {
            "mode": "local",
            "label": "Bonsai local",
            "state": "development_evidence" if local_configured else "not_configured",
            "configured": local_configured,
            "model": local.get("model"),
            "case_count": len(rag_cases) + len(generation_cases) + len(workflow_cases),
            "human_reviewed_cases": human_label_count,
            "quality_claim": "development_only",
            "privacy": "local_provider_loopback" if local_configured else "not_measured",
        },
        {
            "mode": "cloud",
            "label": "Cloud",
            "state": "not_measured" if not cloud_configured else "configured_no_experiment",
            "configured": cloud_configured,
            "model": cloud.get("model"),
            "case_count": 0,
            "human_reviewed_cases": 0,
            "quality_claim": "none",
            "privacy": "requires_signed_consent",
        },
        {
            "mode": "hybrid",
            "label": "Bonsai and cloud",
            "state": "not_measured",
            "configured": local_configured and cloud_configured,
            "model": None,
            "case_count": 0,
            "human_reviewed_cases": 0,
            "quality_claim": "none",
            "privacy": "requires_signed_consent_for_cloud_review",
        },
    ]

    experiments = [
        {
            "id": "workspace_eval_v1",
            "name": "Project Titan workspace development",
            "route_mode": "local",
            "dataset": workspace.get("benchmark_id", "prism_workspace_eval_v1"),
            "dataset_sha256": workspace.get("dataset_sha256"),
            "baseline": True,
            "state": workspace.get("measurement_state", "not_measured"),
            "release": workspace.get("release_decision", {}).get("passed") is True,
            "measures": [
                {"id": "retrieval_recall", "value": rag.get("mean_recall_at_k"), "state": "measured" if rag_cases else "not_measured"},
                {"id": "retrieval_mrr", "value": rag.get("mrr"), "state": "measured" if rag_cases else "not_measured"},
                {"id": "workflow_success", "value": workflows.get("end_to_end_pass_rate"), "state": "measured" if workflow_cases else "not_measured"},
                {"id": "human_usefulness", "value": None, "state": "not_measured"},
            ],
            "case_count": len(rag_cases) + len(generation_cases) + len(workflow_cases),
            "limitations": workspace.get("limitations", []),
        },
        {
            "id": "first_pass_development_v2",
            "name": "First pass underwriting development",
            "route_mode": "local",
            "dataset": "first_pass_development_registry_v2",
            "dataset_sha256": development.get("registry_sha256"),
            "baseline": False,
            "state": "development_not_accuracy_release",
            "release": development.get("accuracy_release_passed") is True,
            "measures": [
                {"id": "deterministic_case_pass", "value": None, "state": "available_in_case_results"},
                {"id": "semantic_quality", "value": None, "state": "unverified"},
                {"id": "human_usefulness", "value": None, "state": "not_measured"},
            ],
            "case_count": len(first_pass_cases),
            "limitations": development.get("release_blockers", []),
        },
    ]
    tracked = experiment_snapshot or {}
    tracked_runs = list((tracked.get("runs") or {}).values())
    for experiment in (tracked.get("experiments") or {}).values():
        runs = [
            run for run in tracked_runs
            if run.get("experiment_id") == experiment.get("experiment_id")
        ]
        measure_ids = sorted({
            metric
            for run in runs
            for metric in (run.get("metrics") or {})
        })
        experiments.append({
            "id": experiment.get("experiment_id"),
            "name": experiment.get("name"),
            "route_mode": experiment.get("route_mode"),
            "dataset": experiment.get("dataset_version"),
            "dataset_sha256": None,
            "comparison_contract_sha256": experiment.get("comparison_contract_sha256"),
            "baseline": not bool(experiment.get("baseline_experiment_id")),
            "baseline_experiment_id": experiment.get("baseline_experiment_id"),
            "state": "recorded" if runs else "created_no_runs",
            "release": False,
            "measures": [
                {"id": metric, "value": None, "state": "available_in_case_results"}
                for metric in measure_ids
            ] or [{"id": "run_results", "value": None, "state": "not_measured"}],
            "case_count": len({(run.get("case_id"), run.get("repetition")) for run in runs}),
            "run_count": len(runs),
            "limitations": ["No aggregate or release state is inferred from recorded runs."],
        })

    for route in route_experiments:
        route_runs = [run for run in tracked_runs if run.get("route_mode") == route["mode"]]
        route["tracked_run_count"] = len(route_runs)
        if route_runs:
            route["case_count"] += len({(run.get("case_id"), run.get("repetition")) for run in route_runs})
            route["state"] = "recorded_experiment"

    evaluator_registry = []
    for item in framework.get("evaluator_registry", []):
        evaluator = dict(item)
        if evaluator.get("kind") == "llm_judge":
            evaluator_labels = criterion_label_counts.get(str(evaluator.get("id")), 0)
            evaluator["status"] = "ready_for_calibration" if evaluator_labels >= target_labels else "blocked_on_human_labels"
            evaluator["labels_available"] = evaluator_labels
            evaluator["labels_required"] = target_labels
            evaluator["trusted_for_release"] = False
        elif evaluator.get("kind") == "blinded_domain_review":
            evaluator["labels_available"] = human_label_count
            evaluator["trusted_for_release"] = domain_review_complete
        else:
            evaluator["trusted_for_release"] = evaluator.get("status") == "active"
        evaluator_registry.append(evaluator)

    release_gates = [
        {
            "id": "source_integrity",
            "label": "Source integrity",
            "state": "development_pass" if generation_cases else "not_measured",
            "evidence": f"{len(generation_cases)} saved generation case",
            "hard_gate": True,
        },
        {
            "id": "retrieval_coverage",
            "label": "Retrieval coverage",
            "state": "development_pass" if rag.get("passed") is True else "not_measured",
            "evidence": f"{len(rag_cases)} mapped Project Titan cases",
            "hard_gate": True,
        },
        {
            "id": "human_error_analysis",
            "label": "Human error analysis",
            "state": "in_progress" if human_label_count else "not_started",
            "evidence": f"{human_label_count} of {review_session.get('sample_count', 0)} sampled traces reviewed",
            "hard_gate": True,
        },
        {
            "id": "judge_validation",
            "label": "Semantic judge validation",
            "state": "ready_for_calibration" if judge_ready else "blocked",
            "evidence": f"{largest_criterion_set} of {target_labels} criterion-specific labels for the largest judge set",
            "hard_gate": True,
        },
        {
            "id": "hybrid_comparison",
            "label": "Local, cloud, and hybrid comparison",
            "state": "not_started",
            "evidence": "Local development evidence exists. Cloud and hybrid runs are missing.",
            "hard_gate": False,
        },
        {
            "id": "business_value",
            "label": "Buyer value and pricing",
            "state": "not_started",
            "evidence": "No locked review or pricing rows exist.",
            "hard_gate": False,
        },
    ]

    readiness = {
        "document_and_retrieval_development": bool(rag.get("passed")),
        "human_error_analysis": human_label_count > 0,
        "judge_calibration": False,
        "three_route_comparison": False,
        "business_value": False,
        "accuracy_release": False,
    }
    next_action = (
        "Have domain reviewers label contextual room traces and describe the first failure in their own words."
        if human_label_count == 0
        else "Continue human review until one observed failure mode has enough balanced Pass and Fail labels for calibration."
    )

    business_measures = [
        {"id": "median_review_seconds", "value": None, "state": "not_measured"},
        {"id": "review_time_reduction", "value": None, "state": "not_measured"},
        {"id": "critical_corrections", "value": None, "state": "not_measured"},
        {"id": "evidence_quality", "value": None, "state": "not_measured"},
        {"id": "decision_usefulness", "value": None, "state": "not_measured"},
        {"id": "preferred_route", "value": None, "state": "not_measured"},
        {"id": "acceptable_price", "value": None, "state": "not_measured"},
        {"id": "paid_next_step", "value": None, "state": "not_measured"},
    ]

    return {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "framework_id": framework.get("framework_id"),
        "framework_version": framework.get("version"),
        "scope": {"kind": "room", "room": room},
        "business_job": framework.get("business_job"),
        "decision": {
            "state": "not_enough_evidence",
            "next_investment": None,
            "next_action": next_action,
            "allowed_investments": framework.get("investment_decision", []),
            "reason": "Human labels, three route comparisons, and buyer evidence are incomplete.",
        },
        "readiness": readiness,
        "release_gates": release_gates,
        "route_experiments": route_experiments,
        "experiments": experiments,
        "experiment_store": {
            "state": "ready" if experiment_snapshot is not None else "not_loaded",
            "event_count": tracked.get("event_count", 0),
            "head_sha256": tracked.get("head_sha256"),
        },
        "evaluators": evaluator_registry,
        "judge_validation": {
            **framework.get("judge_validation", {}),
            "labels_available": largest_criterion_set,
            "labels_by_criterion": criterion_label_counts,
            "calibration_state": "not_started",
            "candidate_judge": "Bonsai 27B",
            "trusted_for_release": False,
        },
        "review": {
            "corpus_count": review_session.get("corpus_count", 0),
            "sample_count": review_session.get("sample_count", 0),
            "reviewed_count": review_session.get("reviewed_count", 0),
            "phase": review_session.get("phase", "breadth"),
            "saturation_claimed": bool(review_session.get("saturation", {}).get("claimed")),
            "canonical_path": review_snapshot.get("canonical_path"),
        },
        "business_measures": business_measures,
        "layers": framework.get("evaluation_layers", []),
        "aggregation_policy": framework.get("aggregation_policy", {}),
        "boundaries": [
            "Development checks are not domain accuracy evidence.",
            "An uncalibrated LLM judge cannot control release or report a production pass rate.",
            "Missing cloud, hybrid, human, cost, energy, and pricing evidence is shown as not measured.",
            "No composite score can average away a hard failure.",
        ],
    }
