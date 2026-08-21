#!/usr/bin/env python3
"""Build a source-anchored review queue without creating benchmark labels."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.deal_room_chat import retrieve_deal_room_evidence  # noqa: E402


QUESTION_FAMILIES = (
    {
        "id": "transaction_identity_and_chronology",
        "source_kind": "proxy",
        "task_family": "transaction_identity_structure_chronology",
        "question": (
            "Who are the transaction parties, what legal structure is disclosed, and what are "
            "the key signing, vote, and expected closing dates? Distinguish completed events "
            "from expected milestones and state which dates are not disclosed."
        ),
        "retrieval_query": (
            "agreement plan merger parent merger sub surviving corporation signed special "
            "meeting stockholder vote expected closing effective time"
        ),
    },
    {
        "id": "transaction_consideration",
        "source_kind": "proxy",
        "task_family": "purchase_price_and_valuation",
        "question": (
            "What is the final per-share merger consideration, its form, and the transaction "
            "structure? Distinguish final agreement terms from proposal history."
        ),
    },
    {
        "id": "financing",
        "source_kind": "proxy",
        "task_family": "financing_and_capital_structure",
        "question": (
            "What committed debt, equity, or preferred financing sources and amounts are "
            "disclosed? State what is not disclosed."
        ),
    },
    {
        "id": "termination_fees",
        "source_kind": "proxy",
        "task_family": "contract_terms_covenants_and_approvals",
        "question": (
            "What company and parent termination fees are stated, and under what conditions may "
            "each be payable? Distinguish final agreement terms from negotiation history."
        ),
    },
    {
        "id": "closing_conditions",
        "source_kind": "proxy",
        "task_family": "contract_terms_covenants_and_approvals",
        "question": (
            "What material closing conditions are disclosed, including stockholder and regulatory "
            "approvals and any financing condition?"
        ),
    },
    {
        "id": "market_and_regulatory_requirements",
        "source_kind": "proxy",
        "task_family": "market_and_regulatory_findings",
        "question": (
            "What competition, foreign investment, industry, or other regulatory approvals are "
            "disclosed? State the named jurisdictions, any stated timing or remedy commitments, "
            "and which requested regulatory conclusions are not disclosed."
        ),
        "retrieval_query": (
            "regulatory approval antitrust competition HSR CFIUS foreign investment waiting "
            "period jurisdiction clearance remedy divestiture efforts covenant"
        ),
    },
    {
        "id": "financial_performance_and_adjustments",
        "source_kind": "financial",
        "task_family": "financial_quality_and_earnings_adjustments",
        "question": (
            "What revenue, operating income or loss, cash flow trend, and material restructuring "
            "or non-GAAP adjustments are disclosed for the latest reported period? State what is "
            "not disclosed."
        ),
        "retrieval_query": (
            "total revenue income loss from operations net cash provided used operating "
            "activities non-GAAP reconciliation restructuring"
        ),
    },
    {
        "id": "financial_statement_calculation",
        "source_kind": "financial",
        "task_family": "financial_quality_and_earnings_adjustments",
        "question": (
            "Using cited financial statement values, calculate year-over-year revenue growth and "
            "operating margin for the latest comparable periods. State the units, source values, "
            "and formula."
        ),
        "retrieval_query": (
            "total revenues income loss from operations consolidated statements of operations "
            "three months six months year ended"
        ),
    },
    {
        "id": "financial_risks_and_missing_information",
        "source_kind": "financial",
        "task_family": "risks_conflicts_and_missing_information",
        "question": (
            "What material liquidity, customer concentration, restructuring, going-concern, or "
            "other financial risks are disclosed, and which requested risk categories are not "
            "disclosed?"
        ),
        "retrieval_query": (
            "liquidity cash requirements customer concentration restructuring going concern "
            "credit risk material risk"
        ),
    },
    {
        "id": "cross_document_underwriting_synthesis",
        "source_kind": "multi",
        "task_family": "cross_document_synthesis_and_recommendation",
        "question": (
            "Reconcile the final transaction terms in the proxy with the latest pre-transaction "
            "financial performance. Which cited facts support or weaken an advance decision, and "
            "what remains unknown? Cite both documents and separate source facts from inference."
        ),
        "retrieval_queries": {
            "proxy": (
                "merger consideration transaction financing closing conditions recommendation"
            ),
            "financial": (
                "total revenues income loss from operations net cash operating activities risk"
            ),
        },
    },
    {
        "id": "cross_document_financing_capacity",
        "source_kind": "multi",
        "task_family": "financing_and_capital_structure",
        "question": (
            "Reconcile the consideration and financing disclosures in the proxy with the latest "
            "pre-transaction balance sheet, liquidity, and cash flow evidence. Which cited facts "
            "bear on financing capacity or liquidity risk, and what remains unknown? Cite both "
            "documents and separate disclosed facts from inference."
        ),
        "retrieval_queries": {
            "proxy": (
                "merger consideration financing commitment debt equity available funds closing"
            ),
            "financial": (
                "cash cash equivalents debt liquidity working capital cash flows credit facility"
            ),
        },
    },
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_drafts(root: Path = ROOT) -> dict:
    registry_path = root / "benchmarks" / "first_pass" / "candidate_deal_sources.v1.json"
    companion_registry_path = (
        root / "benchmarks" / "first_pass" / "candidate_companion_sources.v1.json"
    )
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    companion_registry = json.loads(companion_registry_path.read_text(encoding="utf-8"))
    companions = {
        item["candidate_id"]: item for item in companion_registry["companions"]
    }
    drafts = []
    for candidate in sorted(registry["candidates"], key=lambda item: item["id"]):
        if candidate.get("state") != "acquired_parser_verified_not_registered":
            continue
        companion = companions.get(candidate["id"])
        if not companion or companion.get("state") != "acquired_parser_verified_not_registered":
            raise ValueError(f"{candidate['id']}: financial companion is not acquired")
        source_records = {}
        for source_kind, record in (("proxy", candidate), ("financial", companion)):
            evidence_path = root / record["evidence_path"]
            if sha256(evidence_path) != record["evidence_sha256"]:
                raise ValueError(
                    f"{candidate['id']} {source_kind}: acquisition evidence hash differs"
                )
            acquisition = json.loads(evidence_path.read_text(encoding="utf-8"))
            source = acquisition["source"]
            source_path = root / source["path"]
            if sha256(source_path) != source["sha256"]:
                raise ValueError(
                    f"{candidate['id']} {source_kind}: source hash differs from acquisition evidence"
                )
            source_records[source_kind] = (record, source, source_path)
        for family in QUESTION_FAMILIES:
            source_kinds = (
                ("proxy", "financial")
                if family["source_kind"] == "multi"
                else (family["source_kind"],)
            )
            selected_sources = [source_records[source_kind] for source_kind in source_kinds]
            passages = []
            for source_kind, (record, source, source_path) in zip(
                source_kinds, selected_sources, strict=True,
            ):
                retrieval_query = family.get("retrieval_queries", {}).get(
                    source_kind, family.get("retrieval_query", family["question"])
                )
                source_passages = retrieve_deal_room_evidence(
                    source_path.parent,
                    retrieval_query,
                    limit=3 if family["source_kind"] == "multi" else 4,
                    source_filenames={source_path.name},
                )
                if not source_passages:
                    raise ValueError(
                        f"{candidate['id']} {family['id']}: no {source_kind} evidence candidate"
                    )
                if any(
                    item["filename"] != source_path.name
                    or item["source_sha256"] != source["sha256"]
                    for item in source_passages
                ):
                    raise ValueError(
                        f"{candidate['id']} {family['id']}: retrieval escaped admitted source"
                    )
                passages.extend(source_passages)
            if not passages:
                raise ValueError(f"{candidate['id']} {family['id']}: no evidence candidate")
            admitted_sources = [
                {
                    "filename": source_path.name,
                    "sha256": source["sha256"],
                    "acquisition_evidence_path": record["evidence_path"],
                    "acquisition_evidence_sha256": record["evidence_sha256"],
                }
                for record, source, source_path in selected_sources
            ]
            drafts.append({
                "id": f"{candidate['id']}__{family['id']}",
                "candidate_id": candidate["id"],
                "company": candidate["company"],
                "question_family": family["id"],
                "task_family": family["task_family"],
                "provisional_question": family["question"],
                "state": "source_anchored_question_draft_not_registered",
                "benchmark_case_registered": False,
                "domain_review_status": "not_reviewed",
                "expected_answer": None,
                "labels": [],
                "source": admitted_sources[0],
                "sources": admitted_sources,
                "evidence_candidates": [
                    {
                        "citation": passage["citation"],
                        "anchor": passage["source_anchor"],
                        "score": passage["score"],
                        "matched_terms": passage["matched_terms"],
                        "retrieval_query": passage.get("retrieval_query"),
                        "excerpt": passage["text"][:700],
                        "source_sha256": passage["source_sha256"],
                    }
                    for passage in passages
                ],
                "review_requirements": [
                    "A domain reviewer must select the supporting and confusable anchors.",
                    "A domain reviewer must write the expected claims and answer-absence policy.",
                    "Split assignment and labels occur only after approval.",
                    *(
                        ["A supported cross-document decision must cite both admitted documents."]
                        if family["source_kind"] == "multi" else []
                    ),
                ],
            })
    return {
        "version": "3.0.0",
        "status": "evidence_candidates_not_benchmark_cases",
        "benchmark_case_registered": False,
        "domain_review_status": "not_reviewed",
        "source_registry_sha256": sha256(registry_path),
        "companion_source_registry_sha256": sha256(companion_registry_path),
        "candidate_deal_count": len({item["candidate_id"] for item in drafts}),
        "draft_count": len(drafts),
        "question_families": list(QUESTION_FAMILIES),
        "drafts": drafts,
        "limitations": [
            "Retrieval rank is not a domain label and may surface proposal history or nearby text.",
            "No expected answer, case split, score, approval, or accuracy evidence is created.",
            "These excerpts support reviewer triage only; source documents remain authoritative.",
            "Single-source drafts admit one source. Cross-document drafts admit exactly the proxy and its pre-transaction financial companion.",
            "A calculation prompt does not count as table or calculation coverage until approved and registered.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        default="benchmarks/first_pass/candidate_question_drafts.v1.json",
    )
    args = parser.parse_args()
    output = (ROOT / args.output).resolve()
    record = build_drafts(ROOT)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "output": str(output),
        "candidate_deal_count": record["candidate_deal_count"],
        "draft_count": record["draft_count"],
        "benchmark_case_registered": record["benchmark_case_registered"],
        "domain_review_status": record["domain_review_status"],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
