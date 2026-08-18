"""Fail closed completion decision for the current customer demo goal."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


REQUIRED_GOAL_GATES = (
    "demo_scope_propagated",
    "ideal_page_structure_documented",
    "local_bonsai_deal_room",
    "understandable_customer_surface",
    "source_and_team_critical_path",
    "fresh_demo_evidence",
    "job_and_copy_alignment",
)


def _gate(passed: bool, evidence: list[str], boundary: str) -> dict[str, Any]:
    return {"passed": bool(passed), "evidence": evidence, "boundary": boundary}


def _milestone_passed(milestones: Mapping[str, Any], name: str) -> bool:
    milestone = milestones.get(name, {})
    return isinstance(milestone, Mapping) and milestone.get("passed") is True


def evaluate_goal_completion(
    *,
    milestones: Mapping[str, Any],
    benchmark_contract: Mapping[str, Any] | None = None,
    pricing_evidence: Mapping[str, Any] | None = None,
    trace_anchor_evidence: Mapping[str, Any] | None = None,
    network_observation_evidence: Mapping[str, Any] | None = None,
    ocr_accuracy_evidence: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Evaluate only the accepted customer demo goal.

    The optional arguments preserve the caller contract used by the broader
    engineering report. Benchmark, pricing, production security, network,
    trace anchoring, and OCR records are historical programs. Their state does
    not raise or lower the customer demo decision.
    """

    scope_passed = _milestone_passed(milestones, "M6l_customer_demo_scope")
    demo_passed = _milestone_passed(milestones, "M6m_customer_demo_surface")
    content_graph_passed = _milestone_passed(milestones, "M6n_job_content_graph")
    local_room_passed = all(
        _milestone_passed(milestones, name)
        for name in (
            "M6g_measured_local_deployment",
            "M6h_live_inference_responsiveness",
            "M6i_titan_debt_chat_surface",
            "M6m_customer_demo_surface",
        )
    )
    team_path_passed = all(
        _milestone_passed(milestones, name)
        for name in (
            "M4a_operator_review_durability",
            "M6m_customer_demo_surface",
        )
    )

    gates = {
        "demo_scope_propagated": _gate(
            scope_passed,
            [
                "the PRD, RFC, surface contract, verification gates, and status page name the customer demo as the current goal",
                "accuracy certification and commercial proof do not control the demo decision",
            ],
            "Historical benchmark and pricing work remains available outside the main customer path.",
        ),
        "ideal_page_structure_documented": _gate(
            scope_passed,
            [
                "the page structure states where the user is, what the user can do, and what the user should do next",
                "the document defines the Overview, Sources, Activity, Decision notes, and Technical details hierarchy",
            ],
            "The document defines the current demo structure. It is not a general design system.",
        ),
        "local_bonsai_deal_room": _gate(
            local_room_passed,
            [
                "the measured local Bonsai deployment identity",
                "a completed local Bonsai request through the signed room path",
                "the Project Titan deal room path",
            ],
            "The gate proves the local demo path. It does not certify model accuracy or production deployment.",
        ),
        "understandable_customer_surface": _gate(
            demo_passed,
            [
                "one visible starting action",
                "plain main navigation",
                "a result first decision status",
                "technical detail kept in secondary views",
            ],
            "The browser checks the stated page contract. A human usability study remains separate work.",
        ),
        "source_and_team_critical_path": _gate(
            team_path_passed,
            [
                "one action from a brief citation to the exact source",
                "a canonical room URL",
                "Buzz backed team activity and a durable team decision",
            ],
            "The path proves continuity inside the selected room. It does not prove outside identity or immutable storage.",
        ),
        "fresh_demo_evidence": _gate(
            demo_passed,
            [
                "current asset version and current navigation labels",
                "390, 768, and 1440 pixel viewport checks",
                "no browser console, failed request, or HTTP errors",
            ],
            "The record covers the current customer demo and does not promote older browser records by implication.",
        ),
        "job_and_copy_alignment": _gate(
            content_graph_passed and demo_passed,
            [
                "every visible segment is connected to the root deal decision job",
                "every governed phrase has an owner and a written defense",
                "strategy and runtime language stay outside the primary decision path",
            ],
            "The graph governs the current deal room surface. Human research must still test whether the job and words match real deal work.",
        ),
    }
    missing = [name for name in REQUIRED_GOAL_GATES if not gates[name]["passed"]]
    return {
        "verification_kind": "prism_customer_demo_goal_completion.v3",
        "passed": not missing,
        "decision": "complete" if not missing else "incomplete",
        "required_gate_count": len(REQUIRED_GOAL_GATES),
        "passed_gate_count": len(REQUIRED_GOAL_GATES) - len(missing),
        "missing_gates": missing,
        "gates": gates,
        "excluded_programs": {
            "accuracy_certification": "outside_current_goal",
            "commercial_proof": "outside_current_goal",
            "production_hardening": "outside_current_goal",
        },
        "meaning": (
            "The current customer demo goal has direct evidence for every required gate."
            if not missing
            else "The customer demo remains incomplete until every current demo gate has direct evidence."
        ),
    }
