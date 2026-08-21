#!/usr/bin/env python3
"""Verify source bytes, parser anchors, preregistered facts, and model responses."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.doc_parser import DealRoomParser, ParsedNode


MANIFEST = ROOT / "benchmarks" / "public_deal_corpus_manifest.json"
BENCHMARK = ROOT / "benchmarks" / "public_deal_battletest.json"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def node_text(node: ParsedNode) -> str:
    parts = [str(value) for value in (node.title, node.content) if value]
    if node.table_data:
        parts.append(node.table_data.to_markdown())
    return "\n".join(parts)


def anchor_map(node: ParsedNode) -> dict[str, str]:
    result: dict[str, str] = {}
    anchor = node.metadata.get("source_anchor")
    if anchor:
        result[str(anchor)] = node_text(node)
    for child in node.children:
        result.update(anchor_map(child))
    return result


def score_response(case: dict[str, Any], response: str) -> dict[str, Any]:
    lowered = response.lower()
    expected = case.get("expected_answer_terms", [])
    missing_terms = [term for term in expected if term.lower() not in lowered]
    citation_tokens = [
        f"[{citation['filename']}#{citation['anchor']}]"
        for citation in case.get("required_citations", [])
    ]
    missing_citations = [token for token in citation_tokens if token.lower() not in lowered]
    forbidden_hits = [
        pattern for pattern in case.get("forbidden_answer_patterns", [])
        if re.search(pattern, response, re.IGNORECASE)
    ]
    absence_ok = True
    if case.get("answer_policy") == "refuse_absent":
        absence_ok = any(
            term.lower() in lowered for term in case.get("acceptable_absence_terms", [])
        )
    passed = not missing_terms and not missing_citations and not forbidden_hits and absence_ok
    return {
        "passed": passed,
        "missing_answer_terms": missing_terms,
        "missing_citations": missing_citations,
        "forbidden_hits": forbidden_hits,
        "answer_absence_passed": absence_ok,
    }


def verify_pdf_renders(pdf_path: Path, physical_pages: list[int]) -> dict[str, Any]:
    """Render named pages and record machine checks without claiming visual review."""
    renderer = shutil.which("pdftoppm")
    if not renderer:
        return {
            "passed": False,
            "renderer": None,
            "source_sha256": sha256(pdf_path),
            "pages": [],
            "errors": ["pdftoppm is unavailable"],
            "meaning": "No PDF pages were rendered.",
        }

    page_results = []
    errors = []
    with tempfile.TemporaryDirectory(prefix="prism-pdf-render-") as folder:
        for page in physical_pages:
            output_prefix = Path(folder) / f"page-{page}"
            completed = subprocess.run(
                [
                    renderer,
                    "-f", str(page),
                    "-l", str(page),
                    "-singlefile",
                    "-r", "72",
                    "-png",
                    str(pdf_path),
                    str(output_prefix),
                ],
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )
            rendered = output_prefix.with_suffix(".png")
            page_result = {
                "physical_page": page,
                "renderer_exit_code": completed.returncode,
                "png_created": rendered.is_file(),
            }
            if rendered.is_file():
                payload = rendered.read_bytes()
                valid_header = (
                    len(payload) >= 24
                    and payload[:8] == b"\x89PNG\r\n\x1a\n"
                    and payload[12:16] == b"IHDR"
                )
                complete_png = len(payload) >= 12 and payload[-8:-4] == b"IEND"
                width, height = struct.unpack(">II", payload[16:24]) if valid_header else (0, 0)
                page_result.update({
                    "bytes": len(payload),
                    "sha256": hashlib.sha256(payload).hexdigest(),
                    "png_header_valid": valid_header,
                    "png_terminal_chunk_valid": complete_png,
                    "width_pixels": width,
                    "height_pixels": height,
                })
            page_result["passed"] = bool(
                completed.returncode == 0
                and page_result.get("png_header_valid")
                and page_result.get("png_terminal_chunk_valid")
                and page_result.get("width_pixels", 0) > 0
                and page_result.get("height_pixels", 0) > 0
            )
            if not page_result["passed"]:
                error = completed.stderr.strip() or f"page {page} did not produce a valid PNG"
                errors.append(error)
            page_results.append(page_result)
    return {
        "passed": bool(page_results) and all(item["passed"] for item in page_results),
        "renderer": renderer,
        "source_sha256": sha256(pdf_path),
        "pages": page_results,
        "errors": errors,
        "meaning": (
            "The named pages produced decodable PNG headers with nonzero dimensions. "
            "The check does not measure legibility, reading order, table fidelity, or page identity."
        ),
    }


def main() -> int:
    parser_args = argparse.ArgumentParser()
    parser_args.add_argument("--responses", help="Optional JSON artifact with a responses object keyed by case ID")
    parser_args.add_argument(
        "--output", default="evidence/public-deal-corpus-verification-v2.json",
        help="Evidence JSON path relative to the repository",
    )
    args = parser_args.parse_args()
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    benchmark = json.loads(BENCHMARK.read_text(encoding="utf-8"))
    parser = DealRoomParser(max_file_bytes=12 * 1024 * 1024)
    documents = {}
    corpus_results = []

    for item in manifest["documents"]:
        path = ROOT / item["path"]
        result = {
            "id": item["id"], "path": item["path"], "exists": path.is_file(),
            "expected_sha256": item["sha256"], "expected_bytes": item["bytes"],
        }
        if path.is_file():
            result["observed_sha256"] = sha256(path)
            result["observed_bytes"] = path.stat().st_size
            try:
                document = parser.parse_file(str(path))
                documents[(item["room"], item["filename"])] = document
                result.update({
                    "parser_admitted": True,
                    "file_type": document.file_type,
                    "source_sha256_from_parser": document.metadata.get("source_sha256"),
                    "estimated_tokens": document.estimated_token_count,
                    "table_count": len(document.extracted_tables),
                    "anchor_count": len(anchor_map(document.root_node)),
                    "declared_page_count": document.metadata.get("declared_page_count"),
                    "extracted_page_count": document.metadata.get("extracted_page_count"),
                })
            except ValueError as exc:
                result.update({"parser_admitted": False, "parser_error": str(exc)})
        result["passed"] = bool(
            result.get("exists")
            and result.get("observed_sha256") == item["sha256"]
            and result.get("observed_bytes") == item["bytes"]
            and result.get("parser_admitted")
            and result.get("source_sha256_from_parser") == item["sha256"]
            and (
                item["source_type"] != "pdf"
                or result.get("extracted_page_count") == item.get("declared_pages")
            )
        )
        corpus_results.append(result)

    fact_results = []
    for case in benchmark["cases"]:
        citation_checks = []
        for citation in case["required_citations"]:
            document = documents.get((case["room"], citation["filename"]))
            anchors = anchor_map(document.root_node) if document else {}
            text = anchors.get(citation["anchor"], "")
            normalized_text = re.sub(r"\s+", " ", text).strip().lower()
            missing = [
                term for term in case.get("source_evidence_terms", [])
                if re.sub(r"\s+", " ", term).strip().lower() not in normalized_text
            ]
            citation_checks.append({
                "filename": citation["filename"], "anchor": citation["anchor"],
                "anchor_found": citation["anchor"] in anchors,
                "missing_source_evidence_terms": missing,
                "passed": citation["anchor"] in anchors and not missing,
            })
        fact_results.append({
            "case_id": case["id"], "passed": all(check["passed"] for check in citation_checks),
            "citation_checks": citation_checks,
        })

    response_results = []
    response_artifact = None
    if args.responses:
        response_path = Path(args.responses).resolve()
        response_artifact = json.loads(response_path.read_text(encoding="utf-8"))
        for case in benchmark["cases"]:
            record = response_artifact.get("responses", {}).get(case["id"])
            if not record:
                response_results.append({"case_id": case["id"], "passed": False, "error": "missing response"})
                continue
            scored = score_response(case, str(record.get("response", "")))
            scored.update({
                "case_id": case["id"],
                "provider": record.get("provider"),
                "model": record.get("model"),
                "latency_ms": record.get("latency_ms"),
                "unauthorized_file_writes": record.get("unauthorized_file_writes", []),
            })
            scored["passed"] = scored["passed"] and not scored["unauthorized_file_writes"]
            response_results.append(scored)

    wrong_answer = "$293,122,501 and $586,245,001 [wrong-file#html:block:99999]"
    negative_control = score_response(benchmark["cases"][1], wrong_answer)
    poppler_version = None
    if shutil.which("pdftotext"):
        poppler_version = subprocess.run(
            ["pdftotext", "-v"], capture_output=True, text=True, check=False,
        ).stderr.splitlines()[0]
    corpus_passed = all(result["passed"] for result in corpus_results)
    facts_passed = all(result["passed"] for result in fact_results)
    responses_passed = bool(response_results) and all(result["passed"] for result in response_results)
    pdf_render_checks = []
    for item in manifest["documents"]:
        pages = item.get("render_check_physical_pages", [])
        if item.get("source_type") == "pdf" and pages:
            pdf_render_checks.append({
                "document": item["filename"],
                **verify_pdf_renders(ROOT / item["path"], pages),
            })
    report = {
        "schema": "prism.public_deal_battletest.evidence.v2",
        "recorded_at_unix": time.time(),
        "manifest_sha256": sha256(MANIFEST),
        "benchmark_sha256": sha256(BENCHMARK),
        "benchmark_preregistered_at": benchmark["preregistered_at"],
        "runtime": {"python": platform.python_version(), "platform": platform.platform(), "poppler": poppler_version},
        "corpus": {"passed": corpus_passed, "documents": corpus_results},
        "source_facts": {"passed": facts_passed, "cases": fact_results},
        "automated_pdf_render_check": {
            "passed": bool(pdf_render_checks) and all(
                item["passed"] for item in pdf_render_checks
            ),
            "documents": pdf_render_checks,
        },
        "pdf_visual_review": {
            "passed": None,
            "state": "not_recorded",
            "reviewer": None,
            "receipt": None,
            "note": (
                "No human visual review receipt is attached. Automated rendering is recorded "
                "separately and does not prove legibility or layout accuracy."
            ),
        },
        "negative_control": {
            "passed": not negative_control["passed"],
            "description": "A wrong numerical answer with a nonexistent citation must fail.",
            "evaluator_result": negative_control,
        },
        "model_responses": {
            "measured": bool(response_results),
            "passed": responses_passed if response_results else None,
            "artifact": args.responses,
            "cases": response_results,
        },
        "acceptance": {
            "ingestion_gate_passed": corpus_passed and facts_passed and not negative_control["passed"],
            "model_quality_gate_passed": responses_passed if response_results else False,
            "release_gate_passed": corpus_passed and facts_passed and not negative_control["passed"] and responses_passed,
        },
    }
    output = ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report["acceptance"], indent=2))
    return 0 if report["acceptance"]["ingestion_gate_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
