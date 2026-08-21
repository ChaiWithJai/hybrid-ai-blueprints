#!/usr/bin/env python3
"""Measure Apple Vision OCR on fixed image-only derivatives of public M&A pages."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.macos_ocr import OCR_RENDER_DPI, ocr_pdf_page, ocr_toolchain_status  # noqa: E402
from core.ocr_accuracy_benchmark import (  # noqa: E402
    EVIDENCE_KIND,
    benchmark_errors,
    evaluate_ocr_accuracy,
    sha256_bytes,
)


def command_version(command: str, *arguments: str) -> str:
    completed = subprocess.run(
        [command, *arguments], capture_output=True, text=True, timeout=10,
    )
    return (completed.stdout or completed.stderr).splitlines()[0].strip()


def atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent,
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(value, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except Exception:
        try:
            os.unlink(temporary_name)
        except OSError:
            pass
        raise


def run(root: Path, benchmark_path: Path, output_path: Path) -> dict:
    benchmark_bytes = benchmark_path.read_bytes()
    benchmark = json.loads(benchmark_bytes)
    errors = benchmark_errors(benchmark)
    if errors:
        raise ValueError("invalid OCR benchmark: " + "; ".join(errors))
    source = root / benchmark["source"]["local_path"]
    source_bytes = source.read_bytes()
    if len(source_bytes) != benchmark["source"]["bytes"]:
        raise ValueError("OCR source byte count differs from preregistered contract")
    if sha256_bytes(source_bytes) != benchmark["source"]["sha256"]:
        raise ValueError("OCR source hash differs from preregistered contract")
    pdftoppm = shutil.which("pdftoppm")
    pdftotext = shutil.which("pdftotext")
    sips = shutil.which("sips")
    if not pdftoppm or not pdftotext or not sips:
        raise RuntimeError("pdftoppm, pdftotext, and sips are required")
    toolchain = ocr_toolchain_status()
    if not toolchain["available"]:
        raise RuntimeError("the measured Apple Vision OCR toolchain is unavailable")
    observations = []
    with tempfile.TemporaryDirectory(prefix="prism-ocr-benchmark-") as folder:
        temporary = Path(folder)
        for case in benchmark["cases"]:
            prefix = temporary / case["case_id"]
            rendered = subprocess.run(
                [
                    pdftoppm,
                    "-f", str(case["physical_page"]),
                    "-l", str(case["physical_page"]),
                    "-singlefile",
                    "-png",
                    "-r", str(benchmark["derivative_contract"]["render_dpi"]),
                    str(source),
                    str(prefix),
                ],
                capture_output=True,
                text=True,
                timeout=60,
            )
            png_path = prefix.with_suffix(".png")
            if rendered.returncode != 0 or not png_path.is_file():
                raise RuntimeError(
                    f"{case['case_id']}: page rasterization failed: "
                    + (rendered.stderr.strip() or "no image produced")
                )
            scanned_pdf = prefix.with_suffix(".image-only.pdf")
            converted = subprocess.run(
                [sips, "-s", "format", "pdf", str(png_path), "--out", str(scanned_pdf)],
                capture_output=True,
                text=True,
                timeout=60,
            )
            if converted.returncode != 0 or not scanned_pdf.is_file():
                raise RuntimeError(
                    f"{case['case_id']}: image-only PDF conversion failed: "
                    + (converted.stderr.strip() or "no PDF produced")
                )
            embedded = subprocess.run(
                [pdftotext, str(scanned_pdf), "-"],
                capture_output=True,
                timeout=30,
            )
            if embedded.returncode != 0:
                raise RuntimeError(f"{case['case_id']}: embedded text check failed")
            if embedded.stdout.strip():
                raise RuntimeError(f"{case['case_id']}: derivative contains embedded text")
            ocr = ocr_pdf_page(scanned_pdf, 1)
            observations.append({
                "case_id": case["case_id"],
                "physical_page": case["physical_page"],
                "engine": ocr["engine"],
                "input_derivative_render_dpi": benchmark["derivative_contract"]["render_dpi"],
                "ocr_render_dpi": OCR_RENDER_DPI,
                "recognition_level": ocr.get("recognitionLevel"),
                "language_correction": ocr.get("languageCorrection"),
                "document_specific_vocabulary": [],
                "embedded_text_empty": True,
                "input_derivative_sha256": hashlib.sha256(scanned_pdf.read_bytes()).hexdigest(),
                "input_derivative_bytes": scanned_pdf.stat().st_size,
                "ocr_text": ocr["text"],
                "ocr_line_count": len(ocr["lines"]),
                "engine_mean_confidence": ocr.get("meanConfidence"),
                "engine_confidence_is_accuracy": False,
            })
    evaluation = evaluate_ocr_accuracy(benchmark, observations)
    record = {
        "schema_version": 1,
        "verification_kind": EVIDENCE_KIND,
        "measured_at": datetime.now(timezone.utc).astimezone().isoformat(),
        "benchmark_path": str(benchmark_path.relative_to(root)),
        "benchmark_sha256": sha256_bytes(benchmark_bytes),
        "source": benchmark["source"],
        "toolchain": {
            **toolchain,
            "pdftoppm_version": command_version(pdftoppm, "-v"),
            "pdftotext_version": command_version(pdftotext, "-v"),
            "sips_version": command_version(sips, "--version"),
        },
        "observations": observations,
        "evaluation": evaluation,
        "engineering_measurement_passed": evaluation["passed"],
        "human_approved_ocr_release_gate_passed": False,
        "limitations": benchmark["limitations"],
    }
    atomic_json(output_path, record)
    return record


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--benchmark", default="benchmarks/ocr_accuracy_public.v1.json",
    )
    parser.add_argument(
        "--output", default="evidence/macos-vision-public-ocr-accuracy-v1.json",
    )
    args = parser.parse_args()
    try:
        record = run(
            ROOT,
            (ROOT / args.benchmark).resolve(),
            (ROOT / args.output).resolve(),
        )
    except (OSError, json.JSONDecodeError, ValueError, RuntimeError) as exc:
        print(json.dumps({"recorded": False, "error": str(exc)}, indent=2), file=sys.stderr)
        return 2
    print(json.dumps({
        "recorded": True,
        "engineering_measurement_passed": record["engineering_measurement_passed"],
        "human_approved_ocr_release_gate_passed": False,
        "aggregate": record["evaluation"]["aggregate"],
        "case_results": [
            {"case_id": item["case_id"], "passed": item["passed"]}
            for item in record["evaluation"]["cases"]
        ],
    }, indent=2))
    return 0 if record["engineering_measurement_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
