"""Reviewed deterministic audit profile for the bundled Horizon fixture."""

import time
import json
import re
from dataclasses import dataclass, asdict
from typing import List, Dict, Any, Optional

from core.doc_parser import DealRoomParser, ParsedDocument
from core.sandbox import SubprocessSandbox
from core.arize_evals import ArizeObservabilityTracer, ArizeTraceRecord, TraceSpan, ArizeEvaluationEngine, EvalMetric
from core.hybrid_router import HybridAIRouter


@dataclass
class CovenantAuditFinding:
    covenant_name: str
    section_ref: str
    threshold: str
    actual_value: str
    status: str  # 'COMPLIANT', 'WARNING', 'BREACH', 'ACTION_REQUIRED'
    risk_level: str  # 'LOW', 'MEDIUM', 'HIGH', 'CRITICAL'
    detail: str
    remediation: Optional[str] = None


@dataclass
class DealRoomAuditReport:
    report_id: str
    deal_name: str
    timestamp: float
    total_documents_analyzed: int
    total_tokens_ingested: int
    operational_vram_gb: Optional[float]
    covenant_findings: List[CovenantAuditFinding]
    executive_summary: str
    sandbox_execution_logs: List[str]
    arize_trace_id: str
    evaluation_summary: Dict[str, Any]


class DealRoomAnalyzer:
    """
    Runs a reviewed Horizon audit profile or an honest generic inventory.
    """

    def __init__(self, folder_path: str):
        self.folder_path = folder_path
        self.parser = DealRoomParser()
        self.sandbox = SubprocessSandbox(
            timeout_seconds=3.0,
            protected_read_roots=[self.folder_path],
        )
        self.tracer = ArizeObservabilityTracer()
        self.router = HybridAIRouter(default_local_only_policy=True)
        self.documents: List[ParsedDocument] = []
        self._load_documents()

    def _load_documents(self):
        self.documents = self.parser.parse_deal_room_folder(self.folder_path)

    def _document(self, filename: str) -> ParsedDocument:
        return next(doc for doc in self.documents if doc.filename == filename)

    @staticmethod
    def _number(value: str) -> float:
        return float(str(value).strip().replace(",", "").replace("$", "").replace("x", ""))

    def _source_text(self, filename: str) -> str:
        def walk(node):
            parts = [str(value) for value in (node.title, node.content) if value]
            if node.table_data:
                parts.append(node.table_data.to_markdown())
            for child in node.children:
                parts.append(walk(child))
            return "\n".join(parts)
        return walk(self._document(filename).root_node)

    def _load_horizon_profile(self) -> Dict[str, Any]:
        ledger = self._document("02_Consolidated_Financial_Ledger_2025_2026.csv")
        matrix = ledger.extracted_tables[0].to_matrix()
        columns = {name: index for index, name in enumerate(matrix[0])}
        q2 = next(row for row in matrix[1:] if row[0] == "Q2-2026")
        with open(
            self._document("04_Regulatory_Compliance_Disclosure.json").file_path,
            "r", encoding="utf-8",
        ) as handle:
            disclosure = json.load(handle)
        credit = self._source_text("01_Senior_Credit_Agreement.md")

        def credit_number(pattern: str) -> float:
            match = re.search(pattern, credit, re.IGNORECASE | re.DOTALL)
            if not match:
                raise ValueError(f"credit term not found: {pattern}")
            return self._number(match.group(1))

        litigation = disclosure["ip_and_material_litigation"]
        covenant = disclosure["pro_forma_covenant_summary"]
        antitrust = disclosure["antitrust_review"]
        sanctions = disclosure["sanctions_and_export_controls"]
        return {
            "ebitda": self._number(q2[columns["Adjusted_EBITDA_USD_M"]]),
            "interest": self._number(q2[columns["Cash_Interest_Expense_USD_M"]]),
            "net_debt": self._number(q2[columns["Net_Debt_USD_M"]]),
            "historical_leverage": self._number(q2[columns["Calculated_Leverage_Ratio"]]),
            "historical_coverage": self._number(q2[columns["Calculated_Interest_Coverage"]]),
            "historical_leverage_cap": self._number(q2[columns["Covenant_Leverage_Cap"]]),
            "coverage_floor": self._number(q2[columns["Covenant_Coverage_Floor"]]),
            "proforma_leverage": float(covenant["pro_forma_leverage_ratio"]),
            "proforma_cap": float(covenant["covenant_limit"]),
            "equity_cure": float(covenant["equity_cure_amount_required_usd"]) / 1e6,
            "transaction_value": float(antitrust["transaction_value_usd"]) / 1e6,
            "acquisition_threshold": credit_number(r"single acquisition exceeding.*?\$([0-9,]+)" ) / 1e6,
            "lender_approval_pct": credit_number(r"holding at least\s+([0-9.]+)%"),
            "litigation_claim": float(litigation["quantum_sensor_infringement_claim_usd"]) / 1e6,
            "litigation_threshold": credit_number(r"potential liabilities exceeding.*?\$([0-9,]+)") / 1e6,
            "notice_limit_days": int(credit_number(r"within five \(([0-9]+)\) business days")),
            "notice_delivered": bool(litigation["section_4_02_lender_notice_delivered"]),
            "notice_delivery_date": str(litigation["notice_delivery_date"]),
            "ofac_adverse": int(sanctions["adverse_findings"]),
            "hsr_status": str(antitrust["filing_status"]),
        }

    def run_full_audit(self, session_id: str = "default_session") -> DealRoomAuditReport:
        start_time = time.time()
        trace_id = self.tracer.start_trace(session_id, "Comprehensive M&A Deal Room Covenant Audit")
        spans: List[TraceSpan] = []
        filenames = {doc.filename for doc in self.documents}
        required_profile_files = {
            "01_Senior_Credit_Agreement.md",
            "02_Consolidated_Financial_Ledger_2025_2026.csv",
            "03_Board_Minutes_Q4_Authorization.md",
            "04_Regulatory_Compliance_Disclosure.json",
        }
        profile_supported = required_profile_files.issubset(filenames)
        profile_error = None
        profile = None
        if profile_supported:
            try:
                profile = self._load_horizon_profile()
            except (KeyError, StopIteration, ValueError, OSError, json.JSONDecodeError) as exc:
                profile_supported = False
                profile_error = str(exc)

        # 1. Document Ingestion Span
        ingest_start = time.time()
        total_tokens = sum(doc.estimated_token_count for doc in self.documents)
        total_tables = sum(len(doc.extracted_tables) for doc in self.documents)
        ingest_span = TraceSpan(
            span_id="span_ingest_01",
            parent_span_id=None,
            name="Local_Structured_Folder_Ingestion",
            span_kind="PARSER",
            start_time_ms=ingest_start * 1000,
            end_time_ms=time.time() * 1000,
            duration_ms=(time.time() - ingest_start) * 1000,
            status="OK",
            attributes={
                "doc_count": len(self.documents),
                "total_tokens": total_tokens,
                "table_count": total_tables,
                "network_isolation": "not_measured",
            }
        )
        spans.append(ingest_span)

        # 2. Hybrid AI Routing Span
        route_start = time.time()
        routing_dec = self.router.evaluate_routing(
            "Execute complete compliance audit of senior credit agreement, debt ratios, and acquisition resolutions.",
            deal_room_active=True
        )
        route_span = TraceSpan(
            span_id="span_route_02",
            parent_span_id="span_ingest_01",
            name="Hybrid_AI_Policy_Router",
            span_kind="CHAIN",
            start_time_ms=route_start * 1000,
            end_time_ms=time.time() * 1000,
            duration_ms=(time.time() - route_start) * 1000,
            status="OK",
            attributes={
                "target_tier": routing_dec.target_tier,
                "is_local_only_policy": routing_dec.is_local_only_policy,
                "sanitization_applied": routing_dec.redaction_applied
            }
        )
        spans.append(route_span)

        # 3. Python Sandbox Calculation Span (AST Verified)
        sandbox_start = time.time()
        sandbox_script = """
# Recalculate Q2-2026 Interest Coverage and Pro-Forma NovaTech Leverage
ebitda_q2_2026 = 24.9
interest_q2_2026 = 6.4
actual_coverage = ebitda_q2_2026 / interest_q2_2026

proforma_net_debt = 147.0
proforma_ebitda = 43.0
actual_proforma_leverage = proforma_net_debt / proforma_ebitda

covenant_coverage_floor = 4.00
covenant_proforma_cap = 3.25

coverage_breached = actual_coverage < covenant_coverage_floor
leverage_breached = actual_proforma_leverage > covenant_proforma_cap

equity_cure_needed = (proforma_net_debt - (proforma_ebitda * covenant_proforma_cap))
print(f"Q2-2026 Coverage: {actual_coverage:.2f}x (Floor: {covenant_coverage_floor:.2f}x) -> Breached: {coverage_breached}")
print(f"Pro-Forma Leverage: {actual_proforma_leverage:.2f}x (Cap: {covenant_proforma_cap:.2f}x) -> Breached: {leverage_breached}")
print(f"Required Equity Cure: ${equity_cure_needed:.1f}M USD")
"""
        if profile_supported:
            sandbox_script = f"""
ebitda_q2_2026 = {profile['ebitda']!r}
interest_q2_2026 = {profile['interest']!r}
actual_coverage = ebitda_q2_2026 / interest_q2_2026
actual_proforma_leverage = {profile['proforma_leverage']!r}
covenant_coverage_floor = {profile['coverage_floor']!r}
covenant_proforma_cap = {profile['proforma_cap']!r}
equity_cure_needed = {profile['equity_cure']!r}
print(f"Q2-2026 Coverage: {{actual_coverage:.2f}}x (Floor: {{covenant_coverage_floor:.2f}}x) -> Breached: {{actual_coverage < covenant_coverage_floor}}")
print(f"Pro-Forma Leverage: {{actual_proforma_leverage:.2f}}x (Cap: {{covenant_proforma_cap:.2f}}x) -> Breached: {{actual_proforma_leverage > covenant_proforma_cap}}")
print(f"Required Equity Cure (source disclosure): ${{equity_cure_needed:.1f}}M USD")
"""
        else:
            sandbox_script = "print('No reviewed covenant calculation profile matched this folder.')"
        success, stdout_out, execution_metadata = self.sandbox.execute_script(sandbox_script)
        sandbox_span = TraceSpan(
            span_id="span_sandbox_03",
            parent_span_id="span_route_02",
            name="AST_Sandboxed_Financial_Math",
            span_kind="SANDBOX",
            start_time_ms=sandbox_start * 1000,
            end_time_ms=time.time() * 1000,
            duration_ms=(time.time() - sandbox_start) * 1000,
            status="OK" if success else "ERROR",
            attributes={
                "script_success": success,
                "stdout": stdout_out.strip(),
                "source_bound_profile": profile_supported,
                "isolation": execution_metadata.get("isolation"),
            }
        )
        spans.append(sandbox_span)

        # 4. Synthesize Audit Findings
        findings: List[CovenantAuditFinding] = ([
            CovenantAuditFinding(
                covenant_name="Maximum Consolidated Leverage Ratio",
                section_ref="Credit Agreement Section 2.01",
                threshold=f"≤ {profile['historical_leverage_cap']:.2f}x (Q2 2026) / ≤ {profile['proforma_cap']:.2f}x (Post-Acquisition)",
                actual_value=f"{profile['historical_leverage']:.2f}x (Historical Q2-2026) / {profile['proforma_leverage']:.2f}x (Pro-Forma)",
                status=("ACTION_REQUIRED" if profile["proforma_leverage"] > profile["proforma_cap"] else "COMPLIANT"),
                risk_level=("HIGH" if profile["proforma_leverage"] > profile["proforma_cap"] else "LOW"),
                detail=(f"Pro-forma leverage of {profile['proforma_leverage']:.2f}x exceeds the {profile['proforma_cap']:.2f}x acquisition covenant cap under Section 3.01."
                        if profile["proforma_leverage"] > profile["proforma_cap"] else
                        f"Pro-forma leverage of {profile['proforma_leverage']:.2f}x is within the {profile['proforma_cap']:.2f}x cap."),
                remediation=(f"Source disclosure identifies a ${profile['equity_cure']:.1f}M equity cure; obtain lender and legal review before closing."
                             if profile["proforma_leverage"] > profile["proforma_cap"] else None)
            ),
            CovenantAuditFinding(
                covenant_name="Minimum Interest Coverage Ratio",
                section_ref="Credit Agreement Section 2.02",
                threshold=f"≥ {profile['coverage_floor']:.2f} : 1.00",
                actual_value=f"{profile['historical_coverage']:.2f} : 1.00 (Q2-2026)",
                status=("BREACH" if profile["historical_coverage"] < profile["coverage_floor"] else "COMPLIANT"),
                risk_level=("CRITICAL" if profile["historical_coverage"] < profile["coverage_floor"] else "LOW"),
                detail=(f"Q2-2026 interest coverage is {profile['historical_coverage']:.2f}x on ${profile['interest']:.1f}M interest expense, below the {profile['coverage_floor']:.2f}x floor."
                        if profile["historical_coverage"] < profile["coverage_floor"] else
                        f"Q2-2026 interest coverage of {profile['historical_coverage']:.2f}x meets the {profile['coverage_floor']:.2f}x floor."),
                remediation=("Obtain lender and legal review; no remediation amount is calculated by this profile."
                             if profile["historical_coverage"] < profile["coverage_floor"] else None)
            ),
            CovenantAuditFinding(
                covenant_name="Permitted Acquisition Approval Threshold",
                section_ref="Credit Agreement Section 3.01",
                threshold=f"Prior Written Consent for Transactions > ${profile['acquisition_threshold']:.1f}M",
                actual_value=f"${profile['transaction_value']:.1f}M Enterprise Value (NovaTech)",
                status=("ACTION_REQUIRED" if profile["transaction_value"] > profile["acquisition_threshold"] else "COMPLIANT"),
                risk_level=("HIGH" if profile["transaction_value"] > profile["acquisition_threshold"] else "LOW"),
                detail=(f"NovaTech purchase price (${profile['transaction_value']:.1f}M) exceeds the ${profile['acquisition_threshold']:.1f}M limit, requiring {profile['lender_approval_pct']:.2f}% lender approval."
                        if profile["transaction_value"] > profile["acquisition_threshold"] else
                        f"Transaction value of ${profile['transaction_value']:.1f}M does not exceed the ${profile['acquisition_threshold']:.1f}M consent threshold."),
                remediation=("Deliver formal compliance certificate and secure written consent from Meridian Global Capital Bank."
                             if profile["transaction_value"] > profile["acquisition_threshold"] else None)
            ),
            CovenantAuditFinding(
                covenant_name="Material Litigation Disclosure",
                section_ref="Credit Agreement Section 4.02",
                threshold=f"Disclose proceedings > ${profile['litigation_threshold']:.1f}M within {profile['notice_limit_days']} business days",
                actual_value=f"${profile['litigation_claim']:.1f}M claim; delivery recorded {profile['notice_delivery_date']}",
                status=("REVIEW_REQUIRED" if profile["litigation_claim"] > profile["litigation_threshold"] else "SOURCE_REPORTED_COMPLIANT"),
                risk_level=("HIGH" if profile["litigation_claim"] > profile["litigation_threshold"] else "LOW"),
                detail=("The disclosure records lender notice delivery, but the source set does not establish an unambiguous notice-start/service date. Timeliness cannot be verified."
                        if profile["litigation_claim"] > profile["litigation_threshold"] else
                        "The reported claim does not exceed the Section 4.02 disclosure threshold."),
                remediation=("Confirm the service/notice date from docket evidence before asserting Section 4.02 compliance."
                             if profile["litigation_claim"] > profile["litigation_threshold"] else None)
            ),
            CovenantAuditFinding(
                covenant_name="Regulatory & Sanctions Clearance",
                section_ref="Regulatory Disclosure REG-DISCL-2026-004",
                threshold="Zero adverse OFAC findings / HSR Pre-Merger Filing",
                actual_value=f"OFAC adverse findings: {profile['ofac_adverse']} | HSR: {profile['hsr_status']}",
                status="SOURCE_REPORTED_COMPLIANT",
                risk_level="LOW",
                detail="The regulatory disclosure reports the values above; this profile does not independently query OFAC or HSR systems.",
                remediation="Verify current regulatory status with authoritative systems before closing."
            )
        ] if profile_supported else [])

        if profile_supported:
            executive_summary = (
                f"REVIEWED PROFILE RESULT: The source files report a ${profile['transaction_value']:.1f}M NovaTech acquisition, "
                f"Q2 interest coverage of {profile['historical_coverage']:.2f}x versus a {profile['coverage_floor']:.2f}x floor, "
                f"and pro-forma leverage of {profile['proforma_leverage']:.2f}x versus a {profile['proforma_cap']:.2f}x cap. "
                f"The disclosure identifies a ${profile['equity_cure']:.1f}M cure. Litigation notice delivery is recorded, "
                "but timeliness remains unverified because the notice-start date is ambiguous. Domain, lender, and legal review are required."
            )
        else:
            executive_summary = (
                f"INGESTION COMPLETE: Parsed {len(self.documents)} documents from {self.folder_path}. "
                "No reviewed covenant audit profile matches this folder, so no legal or financial "
                "conclusions were generated. Use a configured AI provider or add a versioned reviewed profile. "
                + (f"Profile extraction error: {profile_error}" if profile_error else "")
            )

        # 5. Arize Evaluations
        full_response_text = executive_summary + "\n" + "\n".join([
            f"### {f.covenant_name} ({f.section_ref})\n"
            f"- Status: {f.status} | Risk: {f.risk_level}\n"
            f"- Threshold: {f.threshold}\n"
            f"- Actual Value: {f.actual_value}\n"
            f"- Analysis: {f.detail}\n"
            f"- Remediation: {f.remediation}\n"
            for f in findings
        ])
        faith_eval = EvalMetric(
            name="faithfulness", score=0.0, threshold=0.85, passed=False,
            explanation="Not independently measured by this deterministic audit. Run the versioned benchmark.",
            metadata={"measurement_state": "unverified", "profile_supported": profile_supported},
        )
        forbidden_eval = ArizeEvaluationEngine.evaluate_forbidden_strings(full_response_text)
        table_eval = EvalMetric(
            name="tabular_fixture_cell_match", score=0.0, threshold=1.0, passed=False,
            explanation=(
                "Not independently measured for this ad-hoc audit. The regression suite compares "
                "fixture cells with source files, but that result is not transferable to this run."
            ),
            metadata={"measurement_state": "unverified"},
        )
        schema_eval = ArizeEvaluationEngine.evaluate_schema_compliance(
            {"deal_name": "Apex-NovaTech" if profile_supported else self.folder_path,
             "status": "ACTION_REQUIRED" if profile_supported else "UNREVIEWED",
             "findings_count": len(findings)},
            {"deal_name": "string", "status": "string", "findings_count": "integer"}
        )

        evaluations = [faith_eval, forbidden_eval, table_eval, schema_eval]

        # No model is invoked by this audit profile.
        total_latency_ms = (time.time() - start_time) * 1000
        peak_vram = None
        energy_mwh_per_token = None
        total_energy_mwh = None

        # Record Trace Record
        trace_record = ArizeTraceRecord(
            trace_id=trace_id,
            session_id=session_id,
            timestamp=time.time(),
            query="Execute M&A Deal Room Covenant & Regulatory Audit",
            response=full_response_text,
            model_name="No model (reviewed deterministic audit profile)",
            routed_tier=routing_dec.target_tier,
            total_tokens=None,
            prompt_tokens=None,
            completion_tokens=None,
            total_latency_ms=total_latency_ms,
            energy_per_token_mwh=energy_mwh_per_token,
            total_energy_mwh=total_energy_mwh,
            vram_peak_gb=peak_vram,
            spans=spans,
            evaluations=evaluations,
            metadata={
                "execution_mode": "reviewed_deterministic_profile" if profile_supported else "ingestion_only",
                "profile_id": "horizon_covenant_v1" if profile_supported else None,
                "source_files": sorted(filenames),
                "profile_error": profile_error,
                "sandbox_isolation": execution_metadata.get("isolation"),
            },
        )
        self.tracer.record_trace(trace_record)

        return DealRoomAuditReport(
            report_id=f"AUD-{trace_id[:8].upper()}",
            deal_name=("Project Horizon: Apex Industrial / NovaTech Acquisition"
                       if profile_supported else self.folder_path.rstrip("/").split("/")[-1]),
            timestamp=time.time(),
            total_documents_analyzed=len(self.documents),
            total_tokens_ingested=total_tokens,
            operational_vram_gb=None,
            covenant_findings=findings,
            executive_summary=executive_summary,
            sandbox_execution_logs=[stdout_out.strip()],
            arize_trace_id=trace_id,
            evaluation_summary={
                "faithfulness": faith_eval.score,
                "forbidden_string_check": forbidden_eval.score,
                "tabular_fixture_cell_match": table_eval.score,
                "typed_field_schema_check": schema_eval.score,
                "all_evals_passed": all(ev.passed for ev in evaluations)
            }
        )
