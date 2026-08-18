#!/usr/bin/env python3
"""Record the OCR resolution sweep used to diagnose the public CMA failure."""

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

from core.macos_ocr import ensure_ocr_binary  # noqa: E402
from core.ocr_accuracy_benchmark import normalize_ocr_text  # noqa: E402


RESOLUTIONS = (150, 200, 250, 300, 400, 600)


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


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


def run(output_path: Path) -> dict:
    benchmark_path = ROOT / "benchmarks" / "ocr_accuracy_public.v1.json"
    benchmark = json.loads(benchmark_path.read_text(encoding="utf-8"))
    source = ROOT / benchmark["source"]["local_path"]
    if sha256_file(source) != benchmark["source"]["sha256"]:
        raise ValueError("OCR source hash differs from benchmark")
    pdftoppm = shutil.which("pdftoppm")
    sips = shutil.which("sips")
    if not pdftoppm or not sips:
        raise RuntimeError("pdftoppm and sips are required")
    binary = ensure_ocr_binary()
    settings = []
    with tempfile.TemporaryDirectory(prefix="prism-ocr-resolution-") as folder:
        temporary = Path(folder)
        source_image = temporary / "source.png"
        source_prefix = source_image.with_suffix("")
        rendered = subprocess.run(
            [
                pdftoppm, "-f", "1", "-l", "1", "-singlefile", "-png",
                "-r", "200", str(source), str(source_prefix),
            ],
            capture_output=True, text=True, timeout=60,
        )
        if rendered.returncode != 0 or not source_image.is_file():
            raise RuntimeError("cover page rasterization failed")
        image_only_pdf = temporary / "image-only.pdf"
        converted = subprocess.run(
            [sips, "-s", "format", "pdf", str(source_image), "--out", str(image_only_pdf)],
            capture_output=True, text=True, timeout=60,
        )
        if converted.returncode != 0 or not image_only_pdf.is_file():
            raise RuntimeError("image-only PDF conversion failed")
        for dpi in RESOLUTIONS:
            prefix = temporary / f"ocr-{dpi}"
            rendered = subprocess.run(
                [
                    pdftoppm, "-f", "1", "-l", "1", "-singlefile", "-png",
                    "-r", str(dpi), str(image_only_pdf), str(prefix),
                ],
                capture_output=True, text=True, timeout=60,
            )
            image = prefix.with_suffix(".png")
            if rendered.returncode != 0 or not image.is_file():
                raise RuntimeError(f"{dpi} DPI diagnostic rasterization failed")
            recognized = subprocess.run(
                [str(binary), str(image)], capture_output=True, text=True, timeout=60,
            )
            if recognized.returncode != 0:
                raise RuntimeError(f"{dpi} DPI Vision request failed")
            result = json.loads(recognized.stdout)
            normalized = normalize_ocr_text(result["text"])
            settings.append({
                "ocr_render_dpi": dpi,
                "raster_sha256": sha256_file(image),
                "raster_bytes": image.stat().st_size,
                "ocr_text": result["text"],
                "ocr_line_count": len(result["lines"]),
                "engine_mean_confidence": result.get("meanConfidence"),
                "contains_exact_cma_token": "cma" in normalized.split(),
                "contains_cmay_token": "cmay" in normalized.split(),
            })
        record = {
            "schema_version": 1,
            "verification_kind": "ocr_resolution_sweep_development_diagnostic",
            "recorded_at": datetime.now(timezone.utc).astimezone().isoformat(),
            "source": benchmark["source"],
            "physical_page": 1,
            "input_derivative_render_dpi": 200,
            "input_derivative_sha256": sha256_file(image_only_pdf),
            "input_derivative_bytes": image_only_pdf.stat().st_size,
            "engine": "apple_vision_vnrecognizetextrequest",
            "recognition_level": "accurate",
            "language_correction": True,
            "document_specific_vocabulary": [],
            "settings": settings,
            "selected_product_ocr_render_dpi": 300,
            "benchmark_used_for_selection": True,
            "independent_test": False,
            "human_approved_ocr_release_gate_passed": False,
            "limitations": [
                "The implementation team ran this diagnostic after the cover page failed.",
                "The same public page was used to select and verify the product setting.",
                "The diagnostic does not measure natural scans, reading order, tables, or layout.",
            ],
        }
    atomic_json(output_path, record)
    return record


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output", default="evidence/ocr-resolution-diagnostic-v1.json",
    )
    args = parser.parse_args()
    try:
        record = run((ROOT / args.output).resolve())
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as exc:
        print(json.dumps({"recorded": False, "error": str(exc)}, indent=2), file=sys.stderr)
        return 2
    print(json.dumps({
        "recorded": True,
        "selected_product_ocr_render_dpi": record["selected_product_ocr_render_dpi"],
        "settings": [
            {
                "ocr_render_dpi": item["ocr_render_dpi"],
                "contains_exact_cma_token": item["contains_exact_cma_token"],
                "contains_cmay_token": item["contains_cmay_token"],
            }
            for item in record["settings"]
        ],
        "independent_test": False,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
