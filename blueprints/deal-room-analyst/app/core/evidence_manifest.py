"""Bind engineering benchmark evidence to the source files that produced it."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any


ENGINEERING_SOURCE_FILES = (
    "server.py",
    "package.json",
    "package-lock.json",
)
ENGINEERING_SOURCE_DIRECTORIES = (
    "benchmarks",
    "core",
    "deal_rooms",
    "scripts",
    "tests",
    "tools",
    "web",
)


def engineering_source_files(project_root: Path) -> list[Path]:
    root = project_root.resolve()
    files = [root / name for name in ENGINEERING_SOURCE_FILES]
    for directory in ENGINEERING_SOURCE_DIRECTORIES:
        base = root / directory
        files.extend(
            path for path in base.rglob("*")
            if path.is_file()
            and "__pycache__" not in path.parts
            and path.suffix != ".pyc"
            and ".runtime" not in path.parts
        )
    return sorted(set(files))


def engineering_source_manifest(project_root: Path) -> dict[str, Any]:
    root = project_root.resolve()
    files = engineering_source_files(root)
    digest = hashlib.sha256()
    for path in files:
        relative = path.relative_to(root).as_posix().encode("utf-8")
        digest.update(len(relative).to_bytes(4, "big"))
        digest.update(relative)
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return {
        "kind": "engineering_verifier_source_manifest_v1",
        "sha256": digest.hexdigest(),
        "file_count": len(files),
    }


def source_manifest_errors(saved: Any, project_root: Path) -> list[str]:
    current = engineering_source_manifest(project_root)
    if not isinstance(saved, dict):
        return ["engineering evidence has no source manifest"]
    errors = []
    if saved.get("kind") != current["kind"]:
        errors.append("engineering evidence has an unexpected source manifest kind")
    if saved.get("sha256") != current["sha256"]:
        errors.append("engineering evidence source manifest differs from the current implementation")
    if saved.get("file_count") != current["file_count"]:
        errors.append("engineering evidence source file count differs from the current implementation")
    return errors


def engineering_evidence_summary(record: Any, project_root: Path) -> dict[str, Any]:
    record = record if isinstance(record, dict) else {}
    errors = source_manifest_errors(
        record.get("engineering_source_manifest"),
        project_root,
    )
    benchmark = record.get("benchmark", {})
    runtime = benchmark.get("runtime_evidence", {}) if isinstance(benchmark, dict) else {}
    component_tests = record.get("component_tests", {})
    contract = record.get("first_pass_benchmark_contract", {}) if isinstance(record, dict) else {}
    if not (
        record.get("verification_kind") == "evidence_based_product_check"
        and record.get("runtime") == "local"
    ):
        errors.append("engineering evidence is not a local product verification report")
    if not (
        component_tests.get("passed") is True
        and component_tests.get("tests_skipped") == 0
        and component_tests.get("required_reality_tests_present") is True
    ):
        errors.append("engineering evidence does not record a complete required component suite")
    if not (
        benchmark.get("benchmark_version") == 3
        and benchmark.get("total_cases") == 4
    ):
        errors.append("engineering evidence does not record the four-case version 3 regression")
    if not (
        runtime.get("provider_id") == "local_bonsai"
        and runtime.get("model") == "27b@q1_0"
        and runtime.get("protocol") == "lmstudio_native_chat"
    ):
        errors.append("engineering evidence does not identify the required local Bonsai runtime")
    if contract.get("release_ready") is not False:
        errors.append("engineering evidence does not preserve the blocked accuracy release")
    if record.get("target_architecture_complete") is not False:
        errors.append("engineering evidence does not preserve the incomplete target architecture state")

    benchmark_passed = bool(
        benchmark.get("passed_cases") == 4
        and benchmark.get("pass_rate") == 1.0
        and benchmark.get("mean_structured_check_coverage") == 1.0
        and benchmark.get("structured_check_measurement_state")
            == "preregistered_rule_coverage_not_domain_accuracy"
        and benchmark.get("mean_source_attribution_coverage") == 1.0
        and benchmark.get("grounding_measurement_state")
            == "filename_presence_only_not_semantic_grounding"
    )
    product_verification_passed = record.get("selected_runtime_verified") is True
    if product_verification_passed and not benchmark_passed:
        errors.append("product verification claims success although the benchmark failed")

    evidence_verified = not errors
    if not evidence_verified:
        measurement_state = "stale_or_invalid_engineering_evidence"
    elif benchmark_passed:
        measurement_state = "source_bound_synthetic_engineering_regression_passed"
    else:
        measurement_state = "source_bound_synthetic_engineering_regression_failed"
    return {
        # `verified` is retained for API compatibility and means the evidence is
        # current and internally consistent. It does not mean the model passed.
        "verified": evidence_verified,
        "evidence_verified": evidence_verified,
        "benchmark_passed": benchmark_passed if evidence_verified else None,
        "product_verification_passed": product_verification_passed if evidence_verified else None,
        "measurement_state": measurement_state,
        "model": runtime.get("model"),
        "benchmark_version": benchmark.get("benchmark_version"),
        "passed_cases": benchmark.get("passed_cases"),
        "total_cases": benchmark.get("total_cases"),
        "dataset_sha256": benchmark.get("dataset_sha256"),
        "mean_structured_check_coverage": benchmark.get("mean_structured_check_coverage"),
        "structured_check_measurement_state": benchmark.get("structured_check_measurement_state"),
        "mean_source_attribution_coverage": benchmark.get("mean_source_attribution_coverage"),
        "grounding_measurement_state": benchmark.get("grounding_measurement_state"),
        "source_manifest": record.get("engineering_source_manifest"),
        "accuracy_release_ready": contract.get("release_ready"),
        "target_architecture_complete": record.get("target_architecture_complete"),
        "errors": errors,
        "limitations": [
            "The four cases are synthetic engineering regressions without deal-domain approval.",
            "The result is not a reliability or accuracy release.",
            "The source manifest binds repository inputs, not the external model weights or active runtime.",
        ],
    }
