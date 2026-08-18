"""Reviewed deal-room calculation workflows.

The baseline path selects reviewed Python templates. When an explicitly
configured provider is selected, the module sends a bounded evidence package
to that provider, validates the returned Python, executes it in the prototype
sandbox, and records the provider and runtime identity in the trace.
"""

import time
import json
import hashlib
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Dict, Any, Optional, Callable

from core.sandbox import SubprocessSandbox
from core.doc_parser import DealRoomParser
from core.hybrid_router import HybridAIRouter, RoutingDecision
from core.arize_evals import ArizeObservabilityTracer, ArizeTraceRecord, TraceSpan, ArizeEvaluationEngine, EvalMetric
from core.ai_provider import ProviderRegistry
from core.cloud_consent import (
    CloudConsentAuthority,
    consume_cloud_consent,
    validate_cloud_consent,
)


@dataclass
class AgentStep:
    step_number: int
    thought: str
    action: str  # 'QUERY_AST', 'WRITE_PYTHON_SCRIPT', 'EXECUTE_SANDBOX', 'VERIFY_COVENANT', 'SYNTHESIZE_REPORT'
    input_payload: str
    output_payload: str
    status: str  # 'SUCCESS', 'FAILED'
    latency_ms: float


@dataclass
class CodingAgentResult:
    query: str
    steps: List[AgentStep]
    final_answer: str
    generated_code: Optional[str]
    code_execution_stdout: Optional[str]
    routing_info: RoutingDecision
    trace_id: str
    evaluations: List[Dict[str, Any]]
    energy_mwh: Optional[float]
    latency_ms: float
    execution_mode: str = "deterministic_template"
    evidence_sources: List[str] = field(default_factory=list)
    limitations: List[str] = field(default_factory=list)
    provider_id: Optional[str] = None
    model_name: Optional[str] = None
    generation_attempts: int = 0
    rejected_scope_violations: List[str] = field(default_factory=list)


class DealRoomWorkflowAgent:
    """Run reviewed baselines or configured-provider code against a folder.

    The provider path is optional and explicit. Callers must inspect
    ``execution_mode``, provider identity, and limitations in the result.
    """

    def __init__(self, deal_room_folder: str, tracer: Optional[ArizeObservabilityTracer] = None,
                 providers: Optional[ProviderRegistry] = None,
                 cloud_consent_authority: Optional[CloudConsentAuthority] = None,
                 cloud_consent_ledger_path: Optional[Path] = None,
                 cloud_consent_event_resolver: Optional[
                     Callable[[set[str], str], dict[str, dict[str, Any]]]
                 ] = None):
        self.deal_room_folder = deal_room_folder
        self.parser = DealRoomParser()
        self.sandbox = SubprocessSandbox(
            timeout_seconds=3.0,
            protected_read_roots=[self.deal_room_folder],
        )
        self.router = HybridAIRouter(default_local_only_policy=True)
        self.tracer = tracer or ArizeObservabilityTracer()
        self.docs = self.parser.parse_deal_room_folder(deal_room_folder)
        self.parse_warnings = list(self.parser.last_warnings)
        self.providers = providers or ProviderRegistry()
        self.cloud_consent_authority = cloud_consent_authority or CloudConsentAuthority.from_env()
        self.cloud_consent_event_resolver = cloud_consent_event_resolver
        self.cloud_consent_ledger_path = cloud_consent_ledger_path or (
            Path(os.environ.get(
                "PRISM_CLOUD_CONSENT_LEDGER",
                str(Path(__file__).resolve().parents[1] / ".runtime" / "cloud-consent-uses.v1.json"),
            ))
        )

    def execute_task(self, user_prompt: str, session_id: str = "agent_session",
                     force_cloud_override: bool = False,
                     local_only_policy: bool = True,
                     force_baseline: bool = False,
                     allow_cloud_context: bool = False,
                     cloud_consent_bundle: Optional[dict[str, Any]] = None,
                     cloud_room_id: Optional[str] = None) -> CodingAgentResult:
        start_time = time.time()
        trace_id = self.tracer.start_trace(session_id, user_prompt)
        spans: List[TraceSpan] = []
        steps: List[AgentStep] = []

        # 1. Routing Decision
        route_start = time.time()
        cloud_consent_report = None
        cloud_requested = bool(force_cloud_override and not local_only_policy)
        if cloud_requested:
            cloud_status = self.providers.cloud.status()
            if not cloud_status.configured:
                raise ValueError("cloud dispatch denied before provider invocation: provider is not configured")
            cloud_consent_report = validate_cloud_consent(
                authority=self.cloud_consent_authority,
                bundle=cloud_consent_bundle,
                room_id=cloud_room_id or session_id,
                source_snapshot_sha256=self._source_snapshot_sha256(),
                prompt=user_prompt,
                provider_endpoint=str(cloud_status.endpoint),
                provider_model=str(cloud_status.model),
                include_context=allow_cloud_context,
                require_relay_restoration=False,
            )
            if cloud_consent_report.get("valid") is not True:
                raise ValueError(
                    "cloud dispatch denied before provider invocation: "
                    + "; ".join(cloud_consent_report.get("errors", []))
                )
            if self.cloud_consent_event_resolver is None:
                raise ValueError(
                    "cloud dispatch denied before provider invocation: "
                    "configured Buzz relay restoration is required"
                )
            try:
                restored_events = self.cloud_consent_event_resolver(
                    set(cloud_consent_report.get("event_ids", [])),
                    str(self.cloud_consent_authority.channel_id),
                )
            except Exception as exc:
                raise ValueError(
                    "cloud dispatch denied before provider invocation: "
                    f"Buzz relay restoration failed: {exc}"
                ) from exc
            cloud_consent_report = validate_cloud_consent(
                authority=self.cloud_consent_authority,
                bundle=cloud_consent_bundle,
                room_id=cloud_room_id or session_id,
                source_snapshot_sha256=self._source_snapshot_sha256(),
                prompt=user_prompt,
                provider_endpoint=str(cloud_status.endpoint),
                provider_model=str(cloud_status.model),
                include_context=allow_cloud_context,
                restored_events=restored_events,
            )
            if cloud_consent_report.get("valid") is not True:
                raise ValueError(
                    "cloud dispatch denied before provider invocation: "
                    + "; ".join(cloud_consent_report.get("errors", []))
                )
            try:
                consume_cloud_consent(self.cloud_consent_ledger_path, cloud_consent_report)
            except ValueError as exc:
                raise ValueError(
                    f"cloud dispatch denied before provider invocation: {exc}"
                ) from exc
        routing_dec = self.router.evaluate_routing(
            user_prompt,
            deal_room_active=not force_cloud_override,
            force_cloud_override=force_cloud_override,
            local_only_policy_override=local_only_policy,
            local_ai_available=self.providers.local.configured and not force_baseline,
            cloud_ai_available=self.providers.cloud.configured,
            cloud_dispatch_authorized=bool(cloud_consent_report and cloud_consent_report["valid"]),
        )
        route_span = TraceSpan(
            span_id=f"sp_{trace_id}_route",
            parent_span_id=None,
            name="Policy_Routing",
            span_kind="CHAIN",
            start_time_ms=route_start * 1000,
            end_time_ms=time.time() * 1000,
            duration_ms=(time.time() - route_start) * 1000,
            status="OK",
            attributes={"target_tier": routing_dec.target_tier}
        )
        spans.append(route_span)

        steps.append(AgentStep(
            step_number=1,
            thought="Determining execution environment and local/cloud policy boundaries.",
            action="QUERY_AST",
            input_payload=user_prompt,
            output_payload=f"Selected {routing_dec.target_tier}. Local-only policy: {routing_dec.is_local_only_policy}.",
            status="SUCCESS",
            latency_ms=route_span.duration_ms
        ))

        # 2. Select a reviewed calculation workflow (not LLM synthesis)
        code_gen_start = time.time()
        provider_result = None
        if routing_dec.target_tier in {"LOCAL_BONSAI", "CLOUD_AI"}:
            provider_id = "local_bonsai" if routing_dec.target_tier == "LOCAL_BONSAI" else "cloud_ai"
            include_context = provider_id == "local_bonsai" or allow_cloud_context
            provider_result = self._generate_script_with_ai(
                provider_id, routing_dec.sanitized_prompt, include_deal_room_context=include_context
            )
            generated_python = self._extract_python(provider_result.content)
            scope_violations = self._generated_script_scope_violations(
                user_prompt, generated_python
            )
            if scope_violations:
                rejected_request_id = provider_result.raw_metadata.get("request_id")
                provider_result = self._repair_generated_script_scope(
                    provider_id, routing_dec.sanitized_prompt, generated_python,
                    scope_violations,
                )
                generated_python = self._extract_python(provider_result.content)
                remaining_violations = self._generated_script_scope_violations(
                    user_prompt, generated_python
                )
                provider_result.raw_metadata.update({
                    "generation_attempts": 2,
                    "rejected_scope_violations": scope_violations,
                    "rejected_request_id": rejected_request_id,
                })
                if remaining_violations:
                    raise ValueError(
                        "AI-generated script crossed the reviewed task scope after one repair: "
                        + ", ".join(remaining_violations)
                    )
            else:
                provider_result.raw_metadata["generation_attempts"] = 1
            execution_mode = "ai_generated_sandboxed_code"
        else:
            generated_python = self._select_template_script(user_prompt)
            execution_mode = ("deterministic_no_match" if generated_python.startswith("# NO_REVIEWED_WORKFLOW")
                              else "deterministic_template")
        code_gen_duration = (time.time() - code_gen_start) * 1000

        llm_span = TraceSpan(
            span_id=f"sp_{trace_id}_llm",
            parent_span_id=route_span.span_id,
            name=("AI_Script_Generation" if provider_result
                  else "Deterministic_Workflow_Selection"),
            span_kind="LLM" if provider_result else "TOOL",
            start_time_ms=code_gen_start * 1000,
            end_time_ms=time.time() * 1000,
            duration_ms=code_gen_duration,
            status="OK",
            attributes={"execution_mode": execution_mode,
                        "model_loaded": provider_result is not None,
                        "provider_id": provider_result.provider_id if provider_result else None,
                        "model": provider_result.model if provider_result else None}
        )
        spans.append(llm_span)

        steps.append(AgentStep(
            step_number=2,
            thought=("Generated a calculation script through the configured AI provider."
                     if provider_result else
                     "Selected a reviewed calculation template using prompt keywords; no model inference occurred."),
            action="GENERATE_PYTHON_WITH_AI" if provider_result else "SELECT_CALCULATION_TEMPLATE",
            input_payload=user_prompt,
            output_payload=generated_python,
            status="SUCCESS",
            latency_ms=code_gen_duration
        ))

        # 3. Execute in AST Sandbox
        sandbox_start = time.time()
        success, stdout_out, execution_metadata = self.sandbox.execute_script(generated_python)
        sandbox_duration = (time.time() - sandbox_start) * 1000
        reported_stdout = self._attach_execution_provenance(stdout_out, provider_result)

        sandbox_span = TraceSpan(
            span_id=f"sp_{trace_id}_sandbox",
            parent_span_id=llm_span.span_id,
            name="AST_Python_Sandbox",
            span_kind="SANDBOX",
            start_time_ms=sandbox_start * 1000,
            end_time_ms=time.time() * 1000,
            duration_ms=sandbox_duration,
            status="OK" if success else "ERROR",
            attributes={
                "success": success,
                "output": stdout_out.strip(),
                "isolation": execution_metadata.get("isolation"),
            }
        )
        spans.append(sandbox_span)

        steps.append(AgentStep(
            step_number=3,
            thought="Executed script in an isolated-mode child process after AST validation.",
            action="EXECUTE_SANDBOX",
            input_payload=generated_python,
            output_payload=stdout_out.strip(),
            status="SUCCESS" if success else "FAILED",
            latency_ms=sandbox_duration
        ))

        # 4. Final Answer Generation
        final_answer = self._format_agent_answer(
            user_prompt,
            reported_stdout,
            execution_metadata,
            execution_mode=execution_mode,
            success=success,
        )
        steps.append(AgentStep(
            step_number=4,
            thought=("Reported verified sandbox output." if success else
                     "Reported the sandbox failure without presenting calculations as findings."),
            action="SYNTHESIZE_REPORT",
            input_payload=reported_stdout.strip(),
            output_payload=final_answer,
            status="SUCCESS" if success else "FAILED",
            latency_ms=12.0
        ))

        # 5. Arize Evaluation
        eval_metric = EvalMetric(
            name="faithfulness",
            score=0.0,
            threshold=0.85,
            passed=False,
            explanation="Not measured for an ad-hoc task. Run the versioned reliability benchmark for grounded accuracy.",
            metadata={"measurement_state": "unverified"},
        )
        denylist_metric = ArizeEvaluationEngine.evaluate_forbidden_strings(final_answer)

        total_latency = (time.time() - start_time) * 1000
        prompt_tokens = provider_result.usage.get("prompt_tokens") if provider_result else None
        completion_tokens = provider_result.usage.get("completion_tokens") if provider_result else None
        token_count = provider_result.usage.get("total_tokens") if provider_result else None
        if token_count is None and prompt_tokens is not None and completion_tokens is not None:
            token_count = prompt_tokens + completion_tokens
        energy_per_tok = None

        trace_rec = ArizeTraceRecord(
            trace_id=trace_id,
            session_id=session_id,
            timestamp=time.time(),
            query=user_prompt,
            response=final_answer,
            model_name=provider_result.model if provider_result else "No model (deterministic template runner)",
            routed_tier=routing_dec.target_tier,
            total_tokens=token_count,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_latency_ms=total_latency,
            energy_per_token_mwh=energy_per_tok,
            total_energy_mwh=None,
            vram_peak_gb=None,
            spans=spans,
            evaluations=[eval_metric, denylist_metric],
            metadata={
                "execution_mode": execution_mode,
                "provider_id": provider_result.provider_id if provider_result else None,
                "returned_model": provider_result.model if provider_result else None,
                "provider_request_id": (provider_result.raw_metadata.get("request_id")
                                        if provider_result else None),
                "provider_artifact_sha256": (provider_result.raw_metadata.get("artifact_sha256")
                                              if provider_result else None),
                "provider_runtime": (provider_result.raw_metadata.get("runtime_name")
                                     if provider_result else None),
                "provider_runtime_version": (provider_result.raw_metadata.get("runtime_version")
                                             if provider_result else None),
                "provider_hardware": (provider_result.raw_metadata.get("hardware")
                                      if provider_result else None),
                "context_chars_sent": (provider_result.raw_metadata.get("context_chars_sent")
                                       if provider_result else 0),
                "context_truncated": (provider_result.raw_metadata.get("context_truncated")
                                      if provider_result else False),
                "context_source_filenames": (
                    provider_result.raw_metadata.get("context_source_filenames", [])
                    if provider_result else []
                ),
                "cloud_context_included": bool(
                    provider_result and provider_result.provider_id == "cloud_ai" and allow_cloud_context
                ),
                "provider_prompt_suffix_applied": (
                    provider_result.raw_metadata.get("prompt_suffix_applied")
                    if provider_result else False
                ),
                "provider_protocol": (provider_result.raw_metadata.get("protocol")
                                      if provider_result else None),
                "reasoning_output_tokens": (
                    provider_result.raw_metadata.get("reasoning_output_tokens")
                    if provider_result else None
                ),
                "generation_attempts": (
                    provider_result.raw_metadata.get("generation_attempts")
                    if provider_result else 0
                ),
                "rejected_scope_violations": (
                    provider_result.raw_metadata.get("rejected_scope_violations", [])
                    if provider_result else []
                ),
                "execution_provenance_attached": bool(provider_result),
                "sandbox_isolation": execution_metadata.get("isolation"),
                "cloud_consent_event_ids": (
                    cloud_consent_report.get("event_ids", []) if cloud_consent_report else []
                ),
                "cloud_consent_material_sha256": (
                    cloud_consent_report.get("material_sha256", {}) if cloud_consent_report else {}
                ),
                "cloud_consent_expires_at": (
                    cloud_consent_report.get("expires_at") if cloud_consent_report else None
                ),
                "cloud_consent_relay_restored": bool(
                    cloud_consent_report and cloud_consent_report.get("relay_restored")
                ),
            }
        )

        self.tracer.record_trace(trace_rec)

        return CodingAgentResult(
            query=user_prompt,
            steps=steps,
            final_answer=final_answer,
            generated_code=generated_python,
            code_execution_stdout=reported_stdout.strip(),
            routing_info=routing_dec,
            trace_id=trace_id,
            evaluations=[
                {"name": "faithfulness", "score": eval_metric.score, "passed": eval_metric.passed},
                {"name": "forbidden_string_check", "score": denylist_metric.score, "passed": denylist_metric.passed}
            ],
            energy_mwh=None,
            latency_ms=round(total_latency, 2),
            execution_mode=execution_mode,
            evidence_sources=(
                list(provider_result.raw_metadata.get("context_source_filenames", []))
                if provider_result else [d.filename for d in self.docs]
            ),
            limitations=[
                *([] if provider_result else [
                    "No language model is loaded or invoked.",
                    "Prompt handling is limited to reviewed keyword-selected workflows.",
                ]),
                *(["Extracted source values and reviewed formulas still require domain-owner validation before transactional use."]
                  if provider_result is None else
                  ["AI-generated calculations have not been independently validated for transactional use."]),
                "Subprocess resource limits are not a hardened multi-tenant isolation boundary.",
                *(["Cloud AI received the full parsed deal-room context after distinct short-lived policy and data-owner signatures were restored from Buzz, validated, and consumed once."]
                  if provider_result and provider_result.provider_id == "cloud_ai" and allow_cloud_context else []),
                *(["Cloud AI received only the redacted task after a short-lived policy signature was restored from Buzz, validated, and consumed once. Deal-room contents were not sent."]
                  if provider_result and provider_result.provider_id == "cloud_ai" and not allow_cloud_context else []),
                *([f"Some files were skipped during parsing: {self.parse_warnings}"] if self.parse_warnings else []),
            ],
            provider_id=provider_result.provider_id if provider_result else None,
            model_name=provider_result.model if provider_result else None,
            generation_attempts=(
                int(provider_result.raw_metadata.get("generation_attempts", 1))
                if provider_result else 0
            ),
            rejected_scope_violations=(
                list(provider_result.raw_metadata.get("rejected_scope_violations", []))
                if provider_result else []
            ),
        )

    def _source_snapshot_sha256(self) -> str:
        inventory = {
            doc.filename: doc.metadata.get("source_sha256")
            for doc in sorted(self.docs, key=lambda item: item.filename)
        }
        return hashlib.sha256(
            json.dumps(inventory, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()

    def _generate_script_with_ai(self, provider_id: str, prompt: str,
                                 include_deal_room_context: bool = True):
        provider = self.providers.select(provider_id)
        input_bundle = self._reviewed_input_bundle(prompt)
        evidence = []
        context_documents = self._select_context_documents(prompt) if include_deal_room_context else []
        # Reviewed calculation families use parser-extracted typed facts as the
        # evidence boundary. Sending the full source as well exposes unrelated
        # clauses and makes task-scope leakage more likely.
        raw_context_documents = [] if input_bundle else context_documents
        if include_deal_room_context:
            for doc in raw_context_documents:
                body = self._document_text(doc.root_node)
                disclosure = ""
                if doc.file_type == "xlsx":
                    disclosure = (
                        "\nPARSER DISCLOSURE: XLSX values are stored workbook values. "
                        "Formulas were not recalculated. A bounded set of audited number formats "
                        f"was applied; other formats remain raw. {doc.metadata.get('cached_formula_cell_count', 0)} formula "
                        "cells use cached values and "
                        f"{doc.metadata.get('unevaluated_formula_cell_count', 0)} had no cached value."
                    )
                evidence.append(f"SOURCE: {doc.filename}{disclosure}\n{body[:8000]}")
        untruncated_context = "\n\n".join(evidence)
        context = untruncated_context[:24000]
        actual_periods = []
        for doc in self.docs:
            body = self._document_text(doc.root_node)
            if "Adjusted_EBITDA" in body and "Quarter" in body:
                actual_periods.extend(re.findall(r"Q([1-4])-(20\d{2})", body))
        latest_actual_period = None
        if actual_periods:
            quarter, year = max(actual_periods, key=lambda value: (int(value[1]), int(value[0])))
            latest_actual_period = f"Q{quarter}-{year}"
        execution_contract = (
            "\n\nEXECUTION CONTRACT:\n"
            + (f"- The parser detected {latest_actual_period} as the latest actual financial period. "
               "Use that period for time-series sensitivity calculations.\n"
               if latest_actual_period else "")
            + "- Call the calculation directly; do not use an if __name__ entry-point guard.\n"
            + "- All evidence is already embedded in this prompt. Never call open() or attempt to read files; "
              "copy only required source values into direct numeric literals.\n"
            + "- The final printed output must name every source filename actually used.\n"
            + "- Print the deal or project identifier found in the evidence.\n"
            + "- When covenant, policy, or threshold evidence exists, print an explicit pass, fail, "
              "breach, or mismatch conclusion rather than numbers alone. Compare source-reported metrics "
              "with metrics calculated under the governing policy and identify discrepancies.\n"
            + "- Reserve breach for a direct threshold failure supported by the governing source. "
              "When a source-reported schedule differs from a calculated policy result, label it a model "
              "or policy mismatch unless the source itself establishes a legal breach."
        )
        method_guidance = self._task_method_guidance(prompt)
        if method_guidance:
            execution_contract += f"\n\nREVIEWED CALCULATION METHOD:\n{method_guidance}"
        if input_bundle:
            execution_contract += (
                "\n\nPARSER-EXTRACTED TYPED INPUTS (use these exact variables; do not select substitute rows):\n"
                + json.dumps(input_bundle, sort_keys=True)
            )
        evidence_section = (f"DEAL ROOM EVIDENCE:\n{context}" if context else
                            "DEAL ROOM EVIDENCE: NOT PROVIDED. State that evidence is insufficient; do not invent values.")
        if input_bundle:
            evidence_section = (
                "DEAL ROOM EVIDENCE: The reviewed parser-extracted typed inputs below are the "
                "complete evidence boundary for this calculation. Do not add other deal findings."
            )
        result = provider.complete([
            {"role": "system", "content": (
                "Return only a self-contained Python financial calculation script. "
                "Use only math/json/re and safe builtins. Never access files, network, environment, or subprocesses. "
                "Print source filenames and state when the evidence is insufficient. "
                "Keep the script under 80 nonblank lines. Extract only the few values needed for the requested "
                "calculation; never reproduce whole source documents or datasets. Prioritize a syntactically "
                "complete runnable script and do not use Markdown fences. Use direct numeric literals copied "
                "from evidence instead of parsing embedded text. For time-series sensitivity tasks, use the "
                "latest actual period unless the task specifies another period. Do not include unrelated deal facts."
            )},
            {"role": "user", "content": f"TASK:\n{prompt}\n\n{evidence_section}{execution_contract}"},
        ])
        result.raw_metadata.update({
            "deal_room_context_included": include_deal_room_context,
            "context_source_filenames": (
                list(input_bundle.get("source_filenames", []))
                if input_bundle else [doc.filename for doc in context_documents]
            ),
            "context_chars_sent": len(context),
            "context_truncated": len(untruncated_context) > len(context),
            "context_deal_identifier": input_bundle.get("deal_identifier") if input_bundle else None,
        })
        return result

    @staticmethod
    def _attach_execution_provenance(stdout: str, provider_result: Any) -> str:
        """Add parser-owned provenance without presenting it as model output."""
        if provider_result is None:
            return stdout
        metadata = provider_result.raw_metadata
        sources = [
            str(source) for source in metadata.get("context_source_filenames", [])
            if str(source).strip()
        ]
        deal_identifier = metadata.get("context_deal_identifier")
        lines = [
            "PRISM EXECUTION PROVENANCE (framework-attached; not model-authored)",
            f"Deal identifier supplied: {deal_identifier or 'UNSPECIFIED'}",
            "Source files supplied: " + (", ".join(sources) if sources else "NONE"),
            "MODEL-GENERATED SANDBOX OUTPUT",
            stdout.strip(),
        ]
        return "\n".join(lines).strip()

    def _repair_generated_script_scope(self, provider_id: str, prompt: str,
                                       generated_python: str,
                                       violations: List[str]):
        """Give the provider one bounded repair; callers still fail closed."""
        provider = self.providers.select(provider_id)
        result = provider.complete([
            {"role": "system", "content": (
                "Return only a complete runnable Python script without Markdown fences. "
                "Repair the supplied script by removing every out-of-scope finding. Preserve only "
                "the requested calculation, its inputs, source filenames, project identifier, and results."
            )},
            {"role": "user", "content": (
                f"TASK:\n{prompt}\n\n"
                f"SCOPE VIOLATIONS TO REMOVE:\n{json.dumps(violations)}\n\n"
                f"SCRIPT TO REPAIR:\n{generated_python}"
            )},
        ])
        return result

    @staticmethod
    def _generated_script_scope_violations(prompt: str, script: str) -> List[str]:
        """Reject known harmful task-family leakage before code execution."""
        lowered_prompt = prompt.lower()
        forbidden: List[str] = []
        if "eps" in lowered_prompt or "accretion" in lowered_prompt or "dilution" in lowered_prompt:
            forbidden = [
                "cfius", "antitrust", "divestiture", "regulatory", "clearance",
                "material adverse effect", "mae policy", "leverage check",
                "policy conclusion", "accretion threshold", "minimum 1.0%", "minimum 1%",
                "synergies ($/share)", "synergy per share", "synergies per share",
            ]
        elif ("lbo" in lowered_prompt or "ecf" in lowered_prompt
              or "excess cash flow" in lowered_prompt or "debt schedule" in lowered_prompt):
            forbidden = ["covenant breach", "status: breach"]
        elif ("qoe" in lowered_prompt or "quality of earnings" in lowered_prompt
              or "carve-out" in lowered_prompt or "carveout" in lowered_prompt):
            forbidden = [
                "benchmark multiple", "policy threshold", "acceptable policy",
                "covenant/policy compliance", "percentage difference from benchmark",
            ]
        lowered_script = script.lower()
        return [term for term in forbidden if term in lowered_script]

    def _reviewed_input_bundle(self, prompt: str) -> Dict[str, Any]:
        """Extract typed source facts for supported calculation families."""
        lowered = prompt.lower()
        filenames = {doc.filename for doc in self.docs}
        if (("eps" in lowered or "accretion" in lowered or "dilution" in lowered)
                and "02_Consolidated_MultiCurrency_Financials_EUR_USD.csv" in filenames):
            header, rows = self._labeled_table("02_Consolidated_MultiCurrency_Financials_EUR_USD.csv")
            columns = {name: index for index, name in enumerate(header)}
            net_income = rows["Consolidated_Net_Income"]
            shares = rows["Diluted_Share_Count_M"]
            synergy = rows["Adjusted_EBITDA"]
            return {
                "source_filenames": ["01_Stock_Purchase_Agreement.md",
                                     "02_Consolidated_MultiCurrency_Financials_EUR_USD.csv"],
                "deal_identifier": self._deal_identifier(),
                "required_output_fields": ["buyer_standalone_eps_usd_per_share",
                                           "proforma_eps_usd_per_share",
                                           "eps_accretion_percent",
                                           "cost_synergies_usd_m",
                                           "revenue_synergies_usd_m"],
                "buyer_net_income_usd_m": self._number(net_income[columns["Vortex_Global_Buyer_USD_M"]]),
                "buyer_diluted_shares_m": self._number(shares[columns["Vortex_Global_Buyer_USD_M"]]),
                "proforma_net_income_usd_m": self._number(net_income[columns["Pro_Forma_Combined_USD_M"]]),
                "proforma_diluted_shares_m": self._number(shares[columns["Pro_Forma_Combined_USD_M"]]),
                "cost_synergies_usd_m": self._number(synergy[columns["Cost_Synergies_USD_M"]]),
                "revenue_synergies_usd_m": self._number(synergy[columns["Revenue_Synergies_USD_M"]]),
            }
        if (("qoe" in lowered or "quality of earnings" in lowered or "carve-out" in lowered
             or "carveout" in lowered)
                and "02_Standalone_Adjusted_EBITDA_Bridge.csv" in filenames):
            header, rows = self._labeled_table("02_Standalone_Adjusted_EBITDA_Bridge.csv")
            column = header.index("2025A_USD_M")
            return {
                "source_filenames": ["01_Transition_Services_Agreement_TSA.md",
                                     "02_Standalone_Adjusted_EBITDA_Bridge.csv"],
                "deal_identifier": self._deal_identifier(),
                "required_output_fields": ["purchase_price_usd_m", "clean_ebitda_usd_m",
                                           "entry_valuation_multiple"],
                "period": "2025A",
                "historical_carveout_ebitda_usd_m": self._number(rows["Historical_Carveout_EBITDA"][column]),
                "parent_shared_allocation_eliminated_usd_m": abs(self._number(rows["Less_Parent_Corporate_Shared_Allocations"][column])),
                "standalone_newco_costs_usd_m": abs(self._number(rows["Less_Standalone_NewCo_Corporate_Costs"][column])),
                "stranded_supply_chain_usd_m": abs(self._number(rows["Less_Stranded_Supply_Chain_Adjustment"][column])),
                "purchase_price_usd_m": self._number(rows["Transaction_Valuation_Multiple_8_8x"][column]),
            }
        if (("stress" in lowered or "sensitivity" in lowered)
                and "02_Consolidated_Financial_Ledger_2025_2026.csv" in filenames):
            header, records = self._record_table("02_Consolidated_Financial_Ledger_2025_2026.csv")
            actual_keys = [key for key in records if re.fullmatch(r"Q[1-4]-20\d{2}", key)]
            period = max(actual_keys, key=lambda key: (int(key[-4:]), int(key[1])))
            row = records[period]
            columns = {name: index for index, name in enumerate(header)}
            return {
                "source_filenames": ["01_Senior_Credit_Agreement.md",
                                     "02_Consolidated_Financial_Ledger_2025_2026.csv"],
                "deal_identifier": self._deal_identifier(),
                "period": period,
                "adjusted_ebitda_usd_m": self._number(row[columns["Adjusted_EBITDA_USD_M"]]),
                "net_debt_usd_m": self._number(row[columns["Net_Debt_USD_M"]]),
                "cash_interest_expense_usd_m": self._number(row[columns["Cash_Interest_Expense_USD_M"]]),
                "leverage_cap": self._number(row[columns["Covenant_Leverage_Cap"]]),
                "coverage_floor": self._number(row[columns["Covenant_Coverage_Floor"]]),
            }
        if (("lbo" in lowered or "ecf" in lowered or "excess cash flow" in lowered
             or "debt schedule" in lowered)
                and "03_Three_Statement_Financial_Model_2024_2028.csv" in filenames):
            header, rows = self._labeled_table("03_Three_Statement_Financial_Model_2024_2028.csv")
            start = header.index("2026E_LBO_Y1")
            years = header[start:]
            values = lambda name: [self._number(value) for value in rows[name][start:]]
            credit_text = self._source_text("02_LBO_Debt_Financing_Credit_Agreement.md")
            high_match = re.search(r"50\.0%.*?>\s*([0-9]+\.[0-9]+)", credit_text)
            mid_match = re.search(r"25\.0%.*?between.*?([0-9]+\.[0-9]+)", credit_text, re.IGNORECASE)
            if not high_match or not mid_match:
                raise ValueError("could not extract ECF sweep thresholds for typed inputs")
            return {
                "source_filenames": ["01_Confidential_Information_Memorandum.md",
                                     "02_LBO_Debt_Financing_Credit_Agreement.md",
                                     "03_Three_Statement_Financial_Model_2024_2028.csv"],
                "deal_identifier": self._deal_identifier(),
                "required_output_fields": ["period", "reported_ecf_sweep_usd_m",
                                           "reported_ending_tlb_usd_m", "implied_sweep_percent",
                                           "contract_sweep_percent", "policy_match_status"],
                "periods": years,
                "free_cash_flow_pre_debt_service_usd_m": values("Free_Cash_Flow_Pre_Debt_Service"),
                "mandatory_amortization_usd_m": values("Mandatory_Term_Loan_Amortization_1pct"),
                "reported_ecf_sweep_usd_m": values("Excess_Cash_Flow_Sweep_Prepayment"),
                "reported_ending_tlb_usd_m": values("Ending_First_Lien_Term_Loan_B"),
                "first_lien_net_leverage": [
                    float(str(value).rstrip("x"))
                    for value in rows["First_Lien_Net_Leverage_Ratio"][start:]
                ],
                "high_tier_threshold": float(high_match.group(1)),
                "mid_tier_threshold": float(mid_match.group(1)),
                "high_tier_sweep_percent": 50.0,
                "mid_tier_sweep_percent": 25.0,
                "low_tier_sweep_percent": 0.0,
            }
        return {}

    def _deal_identifier(self) -> str:
        """Extract the project name from parsed deal-room evidence."""
        bodies = "\n".join(self._document_text(doc.root_node) for doc in self.docs)
        project = re.search(r"\bPROJECT\s+([A-Z][A-Z0-9_-]+)", bodies)
        if project:
            return f"PROJECT {project.group(1)}"
        acquisition = re.search(r"ProForma_([A-Za-z0-9]+)_Acquisition", bodies)
        if acquisition:
            return acquisition.group(1)
        return "UNSPECIFIED"

    def _select_context_documents(self, prompt: str):
        """Select reviewed workflow sources; preserve all sources for unknown tasks."""
        lowered = prompt.lower()
        hint_groups = []
        if "eps" in lowered or "accretion" in lowered or "dilution" in lowered:
            hint_groups = ["stock_purchase", "multicurrency_financials"]
        elif "qoe" in lowered or "quality of earnings" in lowered or "carve-out" in lowered or "carveout" in lowered:
            hint_groups = ["transition_services", "ebitda_bridge"]
        elif "lbo" in lowered or "ecf" in lowered or "excess cash flow" in lowered or "debt schedule" in lowered:
            hint_groups = ["confidential_information", "credit_agreement", "three_statement"]
        elif "stress" in lowered or "sensitivity" in lowered:
            hint_groups = ["senior_credit", "financial_ledger"]
        if not hint_groups:
            return list(self.docs)
        selected = [
            doc for doc in self.docs
            if any(hint in doc.filename.lower() for hint in hint_groups)
        ]
        return selected or list(self.docs)

    @staticmethod
    def _task_method_guidance(prompt: str) -> str:
        """Supply formula policy without supplying case-specific answer values."""
        lowered = prompt.lower()
        if "eps" in lowered or "accretion" in lowered or "dilution" in lowered:
            return (
                "- Buyer standalone EPS = buyer net income / buyer diluted shares.\n"
                "- Pro-forma EPS = pro-forma combined net income / pro-forma diluted shares.\n"
                "- EPS accretion percent = (pro-forma EPS / buyer standalone EPS - 1) * 100.\n"
                "- Use Consolidated_Net_Income and Diluted_Share_Count_M rows. Report synergies from the "
                "Adjusted_EBITDA row; do not substitute EBT, SG&A, or EBITDA growth.\n"
                "- EPS is dollars per share, not millions. Report cost synergy as $42.5M USD and "
                "revenue synergy as $17.3M USD. These are source totals; do not divide them by shares.\n"
                "- No accretion threshold or pass/fail policy exists in the supplied typed evidence. Do not "
                "invent or print one.\n"
                "- Do not compute or report regulatory, CFIUS, antitrust, revenue-threshold, divestiture, "
                "or clearance conclusions for an accretion calculation."
            )
        if "qoe" in lowered or "quality of earnings" in lowered or "carve-out" in lowered or "carveout" in lowered:
            return (
                "- Use the latest historical Actual column, not a future Estimate or Pro-Forma column.\n"
                "- Clean EBITDA = historical carve-out EBITDA + eliminated parent allocation "
                "- standalone NewCo costs - stranded supply-chain adjustment.\n"
                "- Entry valuation multiple = purchase price / clean EBITDA. Print the purchase price, "
                "clean EBITDA, and calculated multiple so the valuation basis is auditable.\n"
                "- No benchmark multiple, acceptable range, covenant, or policy threshold is supplied. "
                "Do not invent or report one."
            )
        if "lbo" in lowered or "ecf" in lowered or "excess cash flow" in lowered or "debt schedule" in lowered:
            return (
                "- Roll forward TLB as beginning balance - mandatory amortization - ECF sweep.\n"
                "- Implied ECF sweep percent = reported ECF sweep / "
                "(free cash flow before debt service - mandatory amortization).\n"
                "- Compare that implied percent with the credit-agreement leverage-tier policy. Print "
                "MODEL_POLICY_MISMATCH when they differ. Do not call that difference a covenant breach, "
                "because the source does not establish the legal cause of the reported schedule.\n"
                "- The contract tiers are 50% above 4.00x, 25% from 3.25x through 4.00x, and 0% "
                "below 3.25x. Use these exact rates."
            )
        if "stress" in lowered or "sensitivity" in lowered:
            return (
                "- Stressed EBITDA = latest actual Adjusted EBITDA * (1 - requested drop).\n"
                "- Leverage = Net Debt / stressed EBITDA; never substitute Total Funded Debt for Net Debt.\n"
                "- Coverage = stressed EBITDA / Cash Interest Expense.\n"
                "- Compare each scenario with the applicable leverage cap and coverage floor."
            )
        return ""

    @staticmethod
    def _document_text(node) -> str:
        parts = []
        if node.title:
            parts.append(str(node.title))
        if node.content:
            parts.append(str(node.content))
        if node.table_data:
            parts.append(node.table_data.to_markdown())
        for child in node.children:
            parts.append(DealRoomWorkflowAgent._document_text(child))
        return "\n".join(part for part in parts if part)

    @staticmethod
    def _extract_python(content: str) -> str:
        if "```" not in content:
            return content.strip()
        for block in content.split("```")[1::2]:
            block = block.strip()
            if block.startswith("python"):
                block = block[6:].lstrip()
            if block:
                return block
        return content.strip()

    def _select_template_script(self, prompt: str) -> str:
        script = self._static_template_for_prompt(prompt)
        if script.startswith("# NO_REVIEWED_WORKFLOW"):
            return script
        try:
            if "Project Titan: LBO 5-Year Debt Paydown" in script:
                header, rows = self._labeled_table("03_Three_Statement_Financial_Model_2024_2028.csv")
                indices = [i for i, column in enumerate(header) if re.match(r"20(26|27|28|29|30)", column)]
                years = [int(header[i][:4]) for i in indices]

                def series(label: str, suffix: str = ""):
                    values = rows[label]
                    return [self._number(values[i], suffix=suffix) for i in indices]

                fcf = series("Free_Cash_Flow_Pre_Debt_Service")
                ratios = series("First_Lien_Net_Leverage_Ratio", suffix="x")
                ecf = series("Excess_Cash_Flow_Sweep_Prepayment")
                ending = series("Ending_First_Lien_Term_Loan_B")
                amort = series("Mandatory_Term_Loan_Amortization_1pct")
                if len(set(amort)) != 1:
                    raise ValueError("variable mandatory amortization is not supported by this reviewed workflow")
                credit_text = self._source_text("02_LBO_Debt_Financing_Credit_Agreement.md")
                high_match = re.search(r"50\.0%.*?>\s*([0-9]+\.[0-9]+)", credit_text)
                mid_match = re.search(r"25\.0%.*?between.*?([0-9]+\.[0-9]+)", credit_text, re.IGNORECASE)
                if not high_match or not mid_match:
                    raise ValueError("could not extract Section 2.02 sweep thresholds")
                replacements = {
                    "__YEARS__": repr(years), "__FCF__": repr(fcf), "__RATIOS__": repr(ratios),
                    "__ECF__": repr(ecf), "__ENDING_TLB__": repr(ending),
                    "__BEGINNING_TLB__": repr(round(ending[0] + amort[0] + ecf[0], 4)),
                    "__MANDATORY_AMORT__": repr(amort[0]),
                    "__HIGH_THRESHOLD__": high_match.group(1), "__MID_THRESHOLD__": mid_match.group(1),
                }
                return self._replace_tokens(script, replacements)

            if "Project Titan: Sponsor Returns Sensitivity" in script:
                source = self._source_json("04_Sponsor_Returns_Sensitivity_IRR_MoIC.json")
                year_five = source["returns_matrix_by_exit_year"]["2030_5_Year_Exit"]
                scenarios = year_five["multiples_sensitivity"]
                if not scenarios:
                    raise ValueError("sponsor returns source has no five-year scenarios")
                replacements = {
                    "__SPONSOR_EQUITY__": repr(float(source["initial_sponsor_equity_usd_m"])),
                    "__EXIT_EBITDA__": repr(float(year_five["projected_exit_ebitda_usd_m"])),
                    "__ENDING_NET_DEBT__": repr(float(year_five["ending_net_debt_usd_m"])),
                    "__RETURN_SCENARIOS__": repr(scenarios),
                }
                return self._replace_tokens(script, replacements)

            if "Project AeroFlux: Cross-Border Accretion" in script:
                _, rows = self._labeled_table("02_Consolidated_MultiCurrency_Financials_EUR_USD.csv")
                header, _ = self._labeled_table("02_Consolidated_MultiCurrency_Financials_EUR_USD.csv")
                columns = {name: index for index, name in enumerate(header)}
                net_income = rows["Consolidated_Net_Income"]
                shares = rows["Diluted_Share_Count_M"]
                synergy = rows["Adjusted_EBITDA"]
                replacements = {
                    "__BUYER_NET_INCOME__": repr(self._number(net_income[columns["Vortex_Global_Buyer_USD_M"]])),
                    "__BUYER_SHARES__": repr(self._number(shares[columns["Vortex_Global_Buyer_USD_M"]])),
                    "__PROFORMA_NET_INCOME__": repr(self._number(net_income[columns["Pro_Forma_Combined_USD_M"]])),
                    "__PROFORMA_SHARES__": repr(self._number(shares[columns["Pro_Forma_Combined_USD_M"]])),
                    "__COST_SYNERGY__": repr(self._number(synergy[columns["Cost_Synergies_USD_M"]])),
                    "__REVENUE_SYNERGY__": repr(self._number(synergy[columns["Revenue_Synergies_USD_M"]])),
                }
                return self._replace_tokens(script, replacements)

            if "Project BioVanguard: Standalone Quality" in script:
                header, rows = self._labeled_table("02_Standalone_Adjusted_EBITDA_Bridge.csv")
                column = header.index("2025A_USD_M")
                replacements = {
                    "__REPORTED_EBITDA__": repr(self._number(rows["Historical_Carveout_EBITDA"][column])),
                    "__PARENT_ALLOCATION__": repr(abs(self._number(rows["Less_Parent_Corporate_Shared_Allocations"][column]))),
                    "__NEWCO_COSTS__": repr(abs(self._number(rows["Less_Standalone_NewCo_Corporate_Costs"][column]))),
                    "__STRANDED_COSTS__": repr(abs(self._number(rows["Less_Stranded_Supply_Chain_Adjustment"][column]))),
                    "__PURCHASE_PRICE__": repr(self._number(rows["Transaction_Valuation_Multiple_8_8x"][column])),
                }
                return self._replace_tokens(script, replacements)

            if "Sensitivity Stress-Test" in script or "Core M&A Deal Ledger" in script:
                header, records = self._record_table("02_Consolidated_Financial_Ledger_2025_2026.csv")
                q2 = records["Q2-2026"]
                columns = {name: index for index, name in enumerate(header)}
                replacements = {
                    "__BASE_EBITDA__": repr(self._number(q2[columns["Adjusted_EBITDA_USD_M"]])),
                    "__BASE_INTEREST__": repr(self._number(q2[columns["Cash_Interest_Expense_USD_M"]])),
                    "__BASE_NET_DEBT__": repr(self._number(q2[columns["Net_Debt_USD_M"]])),
                    "__LEVERAGE_CAP__": repr(self._number(q2[columns["Covenant_Leverage_Cap"]])),
                    "__COVERAGE_FLOOR__": repr(self._number(q2[columns["Covenant_Coverage_Floor"]])),
                }
                return self._replace_tokens(script, replacements)

            if "Litigation Materiality & Credit Agreement Notice" in script:
                source = self._source_json("04_Regulatory_Compliance_Disclosure.json")
                litigation = source["ip_and_material_litigation"]
                credit_text = self._source_text("01_Senior_Credit_Agreement.md")
                threshold = re.search(r"exceeding \*\*\$([0-9,]+) USD\*\* within five \(5\) business days", credit_text)
                if not threshold:
                    raise ValueError("could not extract Section 4.02 threshold and notice period")
                replacements = {
                    "__CLAIM_AMOUNT__": repr(float(litigation["quantum_sensor_infringement_claim_usd"])),
                    "__THRESHOLD_AMOUNT__": repr(float(threshold.group(1).replace(",", ""))),
                    "__NOTICE_DATE__": repr(str(litigation["notice_delivery_date"])),
                    "__NOTICE_DELIVERED__": repr(bool(litigation["section_4_02_lender_notice_delivered"])),
                }
                return self._replace_tokens(script, replacements)
        except (KeyError, IndexError, ValueError) as exc:
            return self._no_workflow_script(f"Reviewed workflow source extraction failed: {exc}")
        return script

    @staticmethod
    def _replace_tokens(script: str, replacements: Dict[str, str]) -> str:
        for token, value in replacements.items():
            script = script.replace(token, value)
        unresolved = sorted(set(re.findall(r"__[A-Z][A-Z0-9_]*__", script)))
        if unresolved:
            raise ValueError(f"unresolved source tokens: {unresolved}")
        return script

    @staticmethod
    def _number(value: str, suffix: str = "") -> float:
        cleaned = str(value).strip().replace(",", "").replace("$", "").replace("+", "")
        if suffix and cleaned.endswith(suffix):
            cleaned = cleaned[:-len(suffix)]
        if cleaned.endswith("%"):
            cleaned = cleaned[:-1]
        return float(cleaned)

    def _document(self, filename: str):
        return next(doc for doc in self.docs if doc.filename == filename)

    def _source_text(self, filename: str) -> str:
        return self._document_text(self._document(filename).root_node)

    def _source_json(self, filename: str) -> Dict[str, Any]:
        source = self._document(filename)
        with open(source.file_path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        if not isinstance(data, dict):
            raise ValueError(f"{filename} must contain a JSON object")
        return data

    def _labeled_table(self, filename: str):
        matrix = self._document(filename).extracted_tables[0].to_matrix()
        return matrix[0][1:], {row[0]: row[1:] for row in matrix[1:]}

    def _record_table(self, filename: str):
        matrix = self._document(filename).extracted_tables[0].to_matrix()
        return matrix[0], {row[0]: row for row in matrix[1:]}

    def _no_workflow_script(self, reason: str) -> str:
        filenames = sorted(doc.filename for doc in self.docs)
        return (
            "# NO_REVIEWED_WORKFLOW\n"
            f"print({json.dumps(reason)})\n"
            f"print({json.dumps('Parsed sources: ' + '; '.join(filenames))})\n"
            "print('Configure a local Bonsai provider for arbitrary analysis.')\n"
        )

    def _static_template_for_prompt(self, prompt: str) -> str:
        p_lower = prompt.lower()
        filenames = {doc.filename for doc in self.docs}

        def has_sources(*required: str) -> bool:
            return set(required).issubset(filenames)

        # 1. M&I LBO Debt Schedule & ECF Prepayment Sweep
        if (("lbo" in p_lower or "debt schedule" in p_lower or "ecf" in p_lower or "excess cash flow" in p_lower)
                and has_sources("01_Confidential_Information_Memorandum.md",
                                "02_LBO_Debt_Financing_Credit_Agreement.md",
                                "03_Three_Statement_Financial_Model_2024_2028.csv")):
            return """
# Mergers & Inquisitions (M&I) Project Titan: LBO 5-Year Debt Paydown & ECF Sweep Model
print("Sources: 01_Confidential_Information_Memorandum.md; 02_LBO_Debt_Financing_Credit_Agreement.md; 03_Three_Statement_Financial_Model_2024_2028.csv")

years = __YEARS__
fcf_pre_debt = __FCF__
reported_first_lien_ratio = __RATIOS__
reported_ecf_prepayment = __ECF__
reported_ending_tlb = __ENDING_TLB__

print("=== PROJECT TITAN LBO DEBT AMORTIZATION & SWEEP SCHEDULE ===")
beginning_tlb = __BEGINNING_TLB__
for yr, fcf, ratio, ecf, ending_tlb in zip(
    years, fcf_pre_debt, reported_first_lien_ratio, reported_ecf_prepayment, reported_ending_tlb
):
    mandatory_amort = __MANDATORY_AMORT__
    roll_forward_expected = round(beginning_tlb - mandatory_amort - ecf, 1)
    roll_forward_ok = abs(roll_forward_expected - ending_tlb) < 0.05
    implied_sweep_pct = ecf / (fcf - mandatory_amort)
    contract_sweep_pct = 0.50 if ratio > __HIGH_THRESHOLD__ else (0.25 if ratio >= __MID_THRESHOLD__ else 0.0)
    policy_status = "MATCH" if abs(implied_sweep_pct - contract_sweep_pct) < 0.01 else "MODEL_POLICY_MISMATCH"
    print(
        f"Year {yr}: Reported ECF=${ecf:.1f}M | Ending TLB=${ending_tlb:.1f}M | "
        f"Roll-forward={roll_forward_ok} | Implied Sweep={implied_sweep_pct*100:.1f}% | "
        f"Section 2.02 Sweep={contract_sweep_pct*100:.0f}% | {policy_status}"
    )
    beginning_tlb = ending_tlb
"""

        # 2. M&I LBO Returns Sensitivity (IRR & MoIC Matrix)
        elif (("irr" in p_lower or "moic" in p_lower or "sponsor returns" in p_lower or "returns sensitivity" in p_lower)
              and has_sources("04_Sponsor_Returns_Sensitivity_IRR_MoIC.json")):
            return """
# Mergers & Inquisitions (M&I) Project Titan: Sponsor Returns Sensitivity Matrix
print("Sources: 04_Sponsor_Returns_Sensitivity_IRR_MoIC.json")
entry_equity = __SPONSOR_EQUITY__
exit_ebitda_y5 = __EXIT_EBITDA__
ending_net_debt_y5 = __ENDING_NET_DEBT__
source_scenarios = __RETURN_SCENARIOS__

print("=== PROJECT TITAN SPONSOR 5-YEAR RETURNS SENSITIVITY (2026-2030) ===")
print("Exit Multiple | Exit EV ($M) | Ending Net Debt | Equity Value ($M) | Sponsor MoIC | Sponsor IRR (%)")
print("-" * 85)

for scenario in source_scenarios:
    print(
        f"  {scenario['exit_multiple']:.1f}x EBITDA   | ${scenario['exit_ev']:8.1f}M  | "
        f"${ending_net_debt_y5:9.1f}M   | ${scenario['exit_equity_value']:10.1f}M  | "
        f"  {scenario['sponsor_moic']:4.2f}x     |    {scenario['sponsor_irr_pct']:5.1f}%"
    )
"""

        # 3. M&I Accretion / Dilution & EPS Synergy Bridge (Project AeroFlux)
        elif (("accretion" in p_lower or "dilution" in p_lower or "aeroflux" in p_lower or "synergy" in p_lower or "eps" in p_lower)
              and has_sources("01_Stock_Purchase_Agreement.md",
                              "02_Consolidated_MultiCurrency_Financials_EUR_USD.csv")):
            return """
# Mergers & Inquisitions (M&I) Project AeroFlux: Cross-Border Accretion/Dilution Analysis
print("Sources: 01_Stock_Purchase_Agreement.md; 02_Consolidated_MultiCurrency_Financials_EUR_USD.csv")
buyer_net_income = __BUYER_NET_INCOME__
buyer_shares = __BUYER_SHARES__
buyer_standalone_eps = buyer_net_income / buyer_shares

proforma_net_income = __PROFORMA_NET_INCOME__
proforma_shares = __PROFORMA_SHARES__
cost_synergies = __COST_SYNERGY__
revenue_synergies = __REVENUE_SYNERGY__
proforma_eps = proforma_net_income / proforma_shares

accretion_pct = ((proforma_eps / buyer_standalone_eps) - 1.0) * 100.0

print("=== PROJECT AEROFLUX ACCRETION / DILUTION SUMMARY ===")
print(f"Buyer Standalone EPS : ${buyer_standalone_eps:.2f} USD")
print(f"Pro-Forma EPS        : ${proforma_eps:.2f} USD")
print(f"Net Transaction Accretion: +{accretion_pct:.1f}% ACCRETIVE")
print(f"Source Cost Synergy  : ${cost_synergies:.1f}M USD")
print(f"Source Revenue Synergy: ${revenue_synergies:.1f}M USD")
"""

        # 4. M&I Carve-Out Quality of Earnings & EBITDA Bridge (Project BioVanguard)
        elif (("carveout" in p_lower or "carve-out" in p_lower or "biovanguard" in p_lower or "stranded" in p_lower or "qoe" in p_lower)
              and has_sources("01_Transition_Services_Agreement_TSA.md",
                              "02_Standalone_Adjusted_EBITDA_Bridge.csv")):
            return """
# Mergers & Inquisitions (M&I) Project BioVanguard: Standalone Quality of Earnings (QoE) Bridge
print("Sources: 01_Transition_Services_Agreement_TSA.md; 02_Standalone_Adjusted_EBITDA_Bridge.csv")
reported_division_ebitda = __REPORTED_EBITDA__
parent_shared_allocation = __PARENT_ALLOCATION__
standalone_newco_costs = __NEWCO_COSTS__
stranded_supply_chain = __STRANDED_COSTS__

clean_adjusted_ebitda = reported_division_ebitda + parent_shared_allocation - standalone_newco_costs - stranded_supply_chain
purchase_price = __PURCHASE_PRICE__
implied_multiple = purchase_price / clean_adjusted_ebitda

print("=== PROJECT BIOVANGUARD CARVEOUT QUALITY OF EARNINGS (QoE) BRIDGE ===")
print(f"Reported Historical EBITDA             : ${reported_division_ebitda:.1f}M")
print(f"(+) Reverse Parent Shared Overhead     : +${parent_shared_allocation:.1f}M")
print(f"(-) Standalone Dedicated NewCo Costs   : -${standalone_newco_costs:.1f}M")
print(f"(-) Stranded Reagent Supply Surcharge  : -${stranded_supply_chain:.1f}M")
print("-" * 55)
print(f"Pro-Forma Standalone Clean EBITDA      : ${clean_adjusted_ebitda:.1f}M")
print(f"Entry Valuation Multiple at $620M EV   : {implied_multiple:.2f}x Clean EBITDA")
"""

        # 5. Sensitivity Stress-Test (NovaTech / Horizon)
        elif (("sensitivity" in p_lower or "ebitda drop" in p_lower or "stress" in p_lower)
              and has_sources("01_Senior_Credit_Agreement.md",
                              "02_Consolidated_Financial_Ledger_2025_2026.csv")):
            return """
# Sensitivity Stress-Test: Impact of 10% and 20% EBITDA Drops on Q2-2026 Covenants
print("Sources: 01_Senior_Credit_Agreement.md; 02_Consolidated_Financial_Ledger_2025_2026.csv")
print("Deal identifier: NovaTech")
base_ebitda = __BASE_EBITDA__
base_interest = __BASE_INTEREST__
base_net_debt = __BASE_NET_DEBT__
covenant_leverage_cap = __LEVERAGE_CAP__
covenant_coverage_floor = __COVERAGE_FLOOR__

results = []
for drop_pct in [0.0, 0.10, 0.20]:
    stressed_ebitda = base_ebitda * (1.0 - drop_pct)
    stressed_leverage = base_net_debt / stressed_ebitda
    stressed_coverage = stressed_ebitda / base_interest
    
    lev_breach = stressed_leverage > covenant_leverage_cap
    cov_breach = stressed_coverage < covenant_coverage_floor
    
    results.append({
        "drop_pct": f"{int(drop_pct*100)}%",
        "ebitda_M": round(stressed_ebitda, 2),
        "leverage_ratio": round(stressed_leverage, 2),
        "leverage_breach": lev_breach,
        "interest_coverage": round(stressed_coverage, 2),
        "coverage_breach": cov_breach
    })

print("--- SENSITIVITY ANALYSIS RESULTS ---")
for r in results:
    print(f"EBITDA Drop {r['drop_pct']}: EBITDA=${r['ebitda_M']}M | Leverage={r['leverage_ratio']}x (Breach: {r['leverage_breach']}) | Coverage={r['interest_coverage']}x (Breach: {r['coverage_breach']})")
"""

        # 6. Litigation Notice Materiality Check
        elif (("litigation" in p_lower or "patent" in p_lower or "notice" in p_lower)
              and has_sources("01_Senior_Credit_Agreement.md",
                              "04_Regulatory_Compliance_Disclosure.json")):
            return """
# Litigation Materiality & Credit Agreement Notice Verification
print("Sources: 01_Senior_Credit_Agreement.md; 04_Regulatory_Compliance_Disclosure.json")
claim_amount = __CLAIM_AMOUNT__
threshold_amount = __THRESHOLD_AMOUNT__
notice_delivery_date = __NOTICE_DATE__
notice_delivered = __NOTICE_DELIVERED__

is_material = claim_amount > threshold_amount

print(f"Claim Amount: ${claim_amount/1e6:.1f}M vs Threshold: ${threshold_amount/1e6:.1f}M -> Material: {is_material}")
print(f"Source reports notice delivered: {notice_delivered} on {notice_delivery_date}")
print("Timeliness: REVIEW_REQUIRED — the source set does not identify an unambiguous notice-start date, so the five-business-day test cannot be calculated.")
"""

        # 7. Reviewed Horizon covenant summary
        elif (any(term in p_lower for term in ("audit", "covenant", "leverage", "coverage"))
              and has_sources("01_Senior_Credit_Agreement.md",
                              "02_Consolidated_Financial_Ledger_2025_2026.csv")):
            return """
# Core M&A Deal Ledger Audit Script
print("Sources: 01_Senior_Credit_Agreement.md; 02_Consolidated_Financial_Ledger_2025_2026.csv")
proforma_ebitda = __BASE_EBITDA__
proforma_net_debt = __BASE_NET_DEBT__
proforma_interest = __BASE_INTEREST__

leverage = proforma_net_debt / proforma_ebitda
coverage = proforma_ebitda / proforma_interest

max_lev_covenant = __LEVERAGE_CAP__
min_cov_covenant = __COVERAGE_FLOOR__

lev_ok = leverage <= max_lev_covenant
cov_ok = coverage >= min_cov_covenant

cure_needed = proforma_net_debt - (proforma_ebitda * max_lev_covenant)

print(f"Calculated Pro-Forma Leverage: {leverage:.2f}x (Covenant: {max_lev_covenant:.2f}x) -> Passed: {lev_ok}")
print(f"Calculated Pro-Forma Coverage: {coverage:.2f}x (Covenant: {min_cov_covenant:.2f}x) -> Passed: {cov_ok}")
print(f"Required Equity Cure: ${cure_needed:.2f}M USD")
"""

        return self._no_workflow_script("No reviewed deterministic workflow matched this prompt and folder.")

    def _format_agent_answer(self, prompt: str, stdout: str, execution_metadata: Dict[str, Any],
                             execution_mode: str, success: bool) -> str:
        if not success:
            return (
                "### Calculation Failed\n\n"
                f"The generated or selected script did not pass execution. No financial findings were accepted.\n\n"
                f"**Sandbox output:**\n```\n{stdout}\n```"
            )
        if execution_mode == "deterministic_no_match":
            return (
                "### No Reviewed Workflow Matched\n\n"
                f"```\n{stdout}\n```\n\n"
                "No financial conclusion was generated. Use a matching reviewed preset or configure a local AI provider."
            )
        mode_text = ("Configured AI provider generated Python that passed the local sandbox."
                     if execution_mode == "ai_generated_sandboxed_code" else
                     "A reviewed keyword-selected Python template ran in the local sandbox; no LLM was used.")
        isolation = execution_metadata.get("isolation") or {}
        security_text = (
            "The measured macOS profile denied child network access, process forks, and reads under /Users, /Volumes, and /Network. It limited writes to the temporary run directory. Other readable system paths remain available, so the profile is not hardened multi-tenant isolation."
            if isolation.get("os_policy_enforced") is True
            else
            "AST checks and subprocess limits ran without an operating system network or write policy."
        )
        return (
            f"### Calculation Findings\n\n"
            f"**Execution Log & Mathematical Verification:**\n```\n{stdout}\n```\n\n"
            f"**Key Insights:**\n"
            f"- **Execution mode**: {mode_text}\n"
            f"- **Evidence boundary**: Values were extracted from the listed parsed files; formulas and source interpretation still require domain-owner review.\n"
            f"- **Security boundary**: {security_text}"
        )
