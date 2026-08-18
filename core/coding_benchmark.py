"""Reality-based coding-agent benchmark for configured model providers."""

from __future__ import annotations

import ast
import hashlib
import json
import re
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.ai_provider import ProviderRegistry
from core.sandbox import SubprocessSandbox


@dataclass
class CodingCaseResult:
    case_id: str
    category: str
    passed: bool
    syntax_success: bool
    sandbox_success: bool
    expected_disposition: str
    disposition_matched: bool
    grounding_applicable: bool
    grounded_source_success: Optional[bool]
    matched_code_anchors: List[str]
    missing_code_anchors: List[str]
    matched_terms: List[str]
    missing_terms: List[str]
    provider_id: Optional[str]
    model_name: Optional[str]
    latency_ms: float
    generated_code: str
    observed_output: str
    error: Optional[str] = None


@dataclass
class CodingBenchmarkReport:
    benchmark_name: str
    benchmark_version: int
    runtime: str
    dataset_sha256: str
    runtime_evidence: Dict[str, Any]
    total_cases: int
    passed_cases: int
    pass_rate: float
    syntax_success_rate: float
    sandbox_success_rate: float
    disposition_match_rate: float
    grounding_applicable_cases: int
    grounded_source_rate: Optional[float]
    mean_latency_ms: float
    cases: List[CodingCaseResult]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _extract_python(content: str) -> str:
    if "```python" in content:
        return content.split("```python", 1)[1].split("```", 1)[0].strip()
    if "```" in content:
        return content.split("```", 1)[1].split("```", 1)[0].strip()
    return content.strip()


def run_coding_benchmark(
    dataset_path: str,
    runtime: str = "local",
    providers: Optional[ProviderRegistry] = None,
    case_ids: Optional[List[str]] = None,
) -> CodingBenchmarkReport:
    path = Path(dataset_path)
    dataset = json.loads(path.read_text(encoding="utf-8"))
    providers = providers or ProviderRegistry()
    provider = providers.local if runtime == "local" else providers.cloud
    if not provider.configured:
        raise RuntimeError(f"{runtime} coding runtime is not configured")
    cases = dataset["cases"]
    if case_ids:
        requested = set(case_ids)
        unknown = requested - {case["id"] for case in cases}
        if unknown:
            raise ValueError(f"Unknown coding benchmark case(s): {', '.join(sorted(unknown))}")
        cases = [case for case in cases if case["id"] in requested]

    results: List[CodingCaseResult] = []
    sandbox = SubprocessSandbox(timeout_seconds=1.0, max_output_bytes=64 * 1024)
    for case in cases:
        started = time.perf_counter()
        try:
            unsupported = bool(re.search(
                r"\b(javascript|typescript|sql|bash|shell script|rust|golang)\b",
                case["prompt"], re.IGNORECASE,
            ))
            if unsupported:
                code = "print('UNSUPPORTED')"
                provider_id = "policy_guard"
                model_name = None
            else:
                response = provider.complete([
                    {"role": "system", "content": (
                        "Act as a constrained Python coding agent. Return only a complete self-contained Python "
                        "script, without Markdown. Use only Python builtins plus math, json, and re. Never access "
                        "files, network, environment, subprocesses, or dynamic imports."
                    )},
                    {"role": "user", "content": case["prompt"]},
                ])
                code = _extract_python(response.content)
                provider_id = response.provider_id
                model_name = response.model
            try:
                ast.parse(code)
                syntax_ok = True
            except SyntaxError:
                syntax_ok = False
            sandbox_ok, output, _ = sandbox.execute_script(code) if syntax_ok else (
                False, "Syntax Error", {}
            )
            expected = case["expected_disposition"]
            if expected == "success":
                disposition_ok = syntax_ok and sandbox_ok
            elif expected == "sandbox_rejection":
                disposition_ok = syntax_ok and not sandbox_ok and any(
                    term.lower() in output.lower() for term in case.get("rejection_terms", [])
                )
            elif expected == "refusal":
                disposition_ok = syntax_ok and sandbox_ok and "unsupported" in output.lower()
            else:
                raise ValueError(f"Unknown expected disposition: {expected}")
            terms = case.get("expected_terms", [])
            matched = [term for term in terms if term.lower() in output.lower()]
            missing = [term for term in terms if term not in matched]
            anchors = case.get("required_code_anchors", [])
            matched_anchors = [anchor for anchor in anchors if anchor.lower() in code.lower()]
            missing_anchors = [anchor for anchor in anchors if anchor not in matched_anchors]
            grounding_applicable = bool(anchors)
            grounded = not missing_anchors if grounding_applicable else None
            passed = disposition_ok and not missing and grounded is not False
            results.append(CodingCaseResult(
                case["id"], case["category"], passed, syntax_ok, sandbox_ok, expected,
                disposition_ok, grounding_applicable, grounded, matched_anchors,
                missing_anchors, matched, missing, provider_id, model_name,
                (time.perf_counter() - started) * 1000, code[:16000], output[:16000],
            ))
        except Exception as exc:
            anchors = case.get("required_code_anchors", [])
            results.append(CodingCaseResult(
                case["id"], case["category"], False, False, False,
                case["expected_disposition"], False, bool(anchors),
                False if anchors else None, [], anchors, [], case.get("expected_terms", []),
                None, None, (time.perf_counter() - started) * 1000, "", "", str(exc),
            ))

    count = max(len(results), 1)
    passed = sum(result.passed for result in results)
    grounded_results = [result for result in results if result.grounding_applicable]
    return CodingBenchmarkReport(
        dataset["name"], int(dataset["version"]), runtime,
        hashlib.sha256(path.read_bytes()).hexdigest(), asdict(provider.status()),
        len(results), passed, round(passed / count, 4),
        round(sum(result.syntax_success for result in results) / count, 4),
        round(sum(result.sandbox_success for result in results) / count, 4),
        round(sum(result.disposition_matched for result in results) / count, 4),
        len(grounded_results),
        (round(sum(result.grounded_source_success is True for result in grounded_results)
               / len(grounded_results), 4) if grounded_results else None),
        round(sum(result.latency_ms for result in results) / count, 2), results,
    )
