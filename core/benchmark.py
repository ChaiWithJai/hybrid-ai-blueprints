"""Repeatable reliability benchmark for deal-room analysis runtimes."""

from __future__ import annotations

import json
import time
import hashlib
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from core.ai_provider import ProviderRegistry
from core.cloud_consent import CloudConsentAuthority
from core.arize_evals import ArizeObservabilityTracer
from core.coding_agent import DealRoomWorkflowAgent


@dataclass
class BenchmarkCaseResult:
    case_id: str
    passed: bool
    structured_check_coverage: float
    sandbox_success: bool
    matched_terms: List[str]
    missing_terms: List[str]
    forbidden_hits: List[str]
    cited_sources: List[str]
    missing_sources: List[str]
    source_attribution_coverage: float
    trace_id: Optional[str]
    execution_mode: str
    provider_id: Optional[str]
    model_name: Optional[str]
    latency_ms: float
    error: Optional[str] = None
    evaluation_mode: str = "legacy_exact_terms"
    observed_output: Optional[str] = None
    observed_generated_code: Optional[str] = None
    generation_attempts: int = 0
    rejected_scope_violations: List[str] = field(default_factory=list)
    grounding_measurement_state: str = "filename_presence_only_not_semantic_grounding"


@dataclass
class BenchmarkReport:
    benchmark_name: str
    benchmark_version: int
    runtime: str
    cloud_context_included: bool
    started_at: float
    dataset_sha256: str
    runtime_evidence: Dict[str, Any]
    total_cases: int
    passed_cases: int
    pass_rate: float
    mean_structured_check_coverage: float
    structured_check_measurement_state: str
    mean_source_attribution_coverage: float
    grounding_measurement_state: str
    mean_latency_ms: float
    cases: List[BenchmarkCaseResult] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def run_benchmark(
    dataset_path: str,
    deal_room_catalog: Dict[str, Dict[str, Any]],
    runtime: str = "baseline",
    providers: Optional[ProviderRegistry] = None,
    allow_cloud_context: bool = False,
    case_ids: Optional[List[str]] = None,
    cloud_consent_bundles: Optional[Dict[str, Dict[str, Any]]] = None,
    cloud_consent_authority: Optional[CloudConsentAuthority] = None,
    cloud_consent_ledger_path: Optional[Path] = None,
    cloud_consent_event_resolver: Optional[
        Callable[[set[str], str], dict[str, dict[str, Any]]]
    ] = None,
) -> BenchmarkReport:
    dataset = json.loads(Path(dataset_path).read_text(encoding="utf-8"))
    dataset_sha256 = hashlib.sha256(Path(dataset_path).read_bytes()).hexdigest()
    providers = providers or ProviderRegistry()
    tracer = ArizeObservabilityTracer()
    results: List[BenchmarkCaseResult] = []
    started_at = time.time()
    unavailable = None
    if runtime == "local" and not providers.local.configured:
        unavailable = "local runtime requested but PRISM_LOCAL_AI_URL is not configured"
    if runtime == "cloud" and not providers.cloud.configured:
        unavailable = "cloud runtime requested but PRISM_CLOUD_AI_URL/PRISM_CLOUD_AI_MODEL are not configured"

    cases = dataset["cases"]
    if case_ids:
        requested = set(case_ids)
        known = {case["id"] for case in cases}
        unknown = sorted(requested - known)
        if unknown:
            raise ValueError(f"Unknown benchmark case(s): {', '.join(unknown)}")
        cases = [case for case in cases if case["id"] in requested]

    for case in cases:
        if unavailable:
            results.append(BenchmarkCaseResult(
                case["id"], False, 0.0, False, [], case.get("expected_terms", []), [],
                [], case.get("required_sources", []), 0.0,
                None, "unavailable", None, None, 0.0, error=unavailable,
            ))
            continue
        room = deal_room_catalog[case["deal_room"]]["path"]
        agent = DealRoomWorkflowAgent(
            room,
            tracer=tracer,
            providers=providers,
            cloud_consent_authority=cloud_consent_authority,
            cloud_consent_ledger_path=cloud_consent_ledger_path,
            cloud_consent_event_resolver=cloud_consent_event_resolver,
        )
        case_started = time.perf_counter()
        try:
            use_cloud = runtime == "cloud"
            local_only_policy = runtime != "cloud"
            result = agent.execute_task(case["prompt"], force_cloud_override=use_cloud,
                                        local_only_policy=local_only_policy,
                                        force_baseline=runtime == "baseline",
                                        allow_cloud_context=allow_cloud_context,
                                        cloud_consent_bundle=(cloud_consent_bundles or {}).get(case["id"]),
                                        cloud_room_id=case["deal_room"])
            text = result.code_execution_stdout or ""
            structured = case.get("structured_expectations")
            if structured:
                checks: List[tuple[str, bool]] = []
                lowered = re.sub(r"[_-]+", " ", text.lower())
                lowered = re.sub(r"\s+", " ", lowered)
                for concept in structured.get("required_concepts", []):
                    alternatives = concept.get("any_of", [])
                    checks.append((
                        f"concept:{concept['id']}",
                        any(
                            re.sub(r"\s+", " ", re.sub(r"[_-]+", " ", str(term).lower()))
                            in lowered
                            for term in alternatives
                        ),
                    ))
                numeric_tokens = [
                    float(token.replace(",", ""))
                    for token in re.findall(r"(?<![\w.])-?\d[\d,]*(?:\.\d+)?", text)
                ]
                for numeric in structured.get("numeric_values", []):
                    expected_value = float(numeric["value"])
                    tolerance = float(numeric.get("tolerance", 0.01))
                    checks.append((
                        f"numeric:{numeric['id']}",
                        any(abs(value - expected_value) <= tolerance for value in numeric_tokens),
                    ))
                for pattern in structured.get("required_patterns", []):
                    checks.append((
                        f"pattern:{pattern['id']}",
                        bool(re.search(pattern["regex"], text, re.IGNORECASE | re.MULTILINE)),
                    ))
                matched = [check_id for check_id, passed_check in checks if passed_check]
                missing = [check_id for check_id, passed_check in checks if not passed_check]
                evaluation_mode = "structured_tolerance"
            else:
                expected = case.get("expected_terms", [])
                matched = [term for term in expected if term.lower() in text.lower()]
                missing = [term for term in expected if term not in matched]
                checks = [(term, term in matched) for term in expected]
                evaluation_mode = "legacy_exact_terms"
            forbidden = [term for term in case.get("forbidden_terms", []) if term.lower() in text.lower()]
            forbidden.extend(
                f"pattern:{pattern['id']}"
                for pattern in case.get("forbidden_patterns", [])
                if re.search(pattern["regex"], text, re.IGNORECASE | re.MULTILINE)
            )
            required_sources = case.get("required_sources", [])
            cited_sources = [source for source in required_sources if source.lower() in text.lower()]
            missing_sources = [source for source in required_sources if source not in cited_sources]
            sandbox_ok = any(s.action == "EXECUTE_SANDBOX" and s.status == "SUCCESS" for s in result.steps)
            accuracy = len(matched) / max(len(checks), 1)
            grounding = len(cited_sources) / max(len(required_sources), 1)
            passed = accuracy == 1.0 and grounding == 1.0 and not forbidden and sandbox_ok
            results.append(BenchmarkCaseResult(
                case["id"], passed, round(accuracy, 4), sandbox_ok, matched, missing,
                forbidden, cited_sources, missing_sources, round(grounding, 4),
                result.trace_id, result.execution_mode, result.provider_id,
                result.model_name, result.latency_ms,
                evaluation_mode=evaluation_mode,
                observed_output=text[:16000],
                observed_generated_code=(result.generated_code or "")[:16000],
                generation_attempts=result.generation_attempts,
                rejected_scope_violations=result.rejected_scope_violations,
            ))
        except Exception as exc:
            results.append(BenchmarkCaseResult(
                case["id"], False, 0.0, False, [], case.get("expected_terms", []), [],
                [], case.get("required_sources", []), 0.0,
                None, runtime, None, None, (time.perf_counter() - case_started) * 1000,
                error=str(exc),
            ))

    passed = sum(1 for result in results if result.passed)
    provider = providers.local if runtime == "local" else providers.cloud if runtime == "cloud" else None
    return BenchmarkReport(
        benchmark_name=dataset["name"],
        benchmark_version=int(dataset["version"]),
        runtime=runtime,
        cloud_context_included=bool(runtime == "cloud" and allow_cloud_context),
        started_at=started_at,
        dataset_sha256=dataset_sha256,
        runtime_evidence=(asdict(provider.status()) if provider else {
            "provider_id": None,
            "kind": "deterministic_baseline",
            "configured": True,
            "model": None,
            "endpoint": None,
        }),
        total_cases=len(results),
        passed_cases=passed,
        pass_rate=round(passed / max(len(results), 1), 4),
        mean_structured_check_coverage=round(
            sum(r.structured_check_coverage for r in results) / max(len(results), 1), 4
        ),
        structured_check_measurement_state=(
            "preregistered_rule_coverage_not_domain_accuracy"
        ),
        mean_source_attribution_coverage=round(
            sum(r.source_attribution_coverage for r in results) / max(len(results), 1), 4
        ),
        grounding_measurement_state="filename_presence_only_not_semantic_grounding",
        mean_latency_ms=round(sum(r.latency_ms for r in results) / max(len(results), 1), 2),
        cases=results,
    )
