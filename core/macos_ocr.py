"""Bounded local OCR adapter for image-only PDF pages on macOS."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import platform
import shutil
import subprocess
import tempfile
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parent.parent
OCR_SOURCE = PROJECT_ROOT / "tools" / "macos_vision_ocr.swift"
OCR_RUNTIME_DIR = PROJECT_ROOT / ".runtime" / "tools"
# Vision's text recognizer is sensitive to the raster scale even when the input
# PDF contains the same source pixels. The fixed public OCR regression corpus
# showed a repeatable CMAY -> CMA error at 200 DPI and correct recognition at
# 250 DPI and above. Use 300 DPI to leave margin without hard-coding vocabulary.
OCR_RENDER_DPI = 300
OCR_PAGE_TIMEOUT_SECONDS = 60
_OCR_BUILD_THREAD_LOCK = threading.Lock()


def ocr_toolchain_status() -> dict[str, Any]:
    commands = {
        "pdftoppm": shutil.which("pdftoppm"),
        "swiftc": shutil.which("swiftc"),
    }
    available = (
        platform.system() == "Darwin"
        and OCR_SOURCE.is_file()
        and all(commands.values())
    )
    return {
        "available": available,
        "platform": platform.system(),
        "engine": "apple_vision_vnrecognizetextrequest" if available else None,
        "render_dpi": OCR_RENDER_DPI if available else None,
        "commands": {name: bool(path) for name, path in commands.items()},
        "source_present": OCR_SOURCE.is_file(),
        "local_only": True,
        "limitations": [
            "OCR text is ordered by recognized bounding boxes; reading order can be wrong.",
            "OCR does not reconstruct tables, merged cells, columns, or document layout.",
            "Recognition confidence is engine output, not a measured accuracy score.",
            "This adapter is available only on the measured macOS prototype toolchain.",
        ],
    }


def _source_sha256() -> str:
    return hashlib.sha256(OCR_SOURCE.read_bytes()).hexdigest()


def _binary_path() -> Path:
    return OCR_RUNTIME_DIR / f"macos_vision_ocr-{_source_sha256()[:16]}"


@contextmanager
def _build_transaction():
    OCR_RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    lock_path = OCR_RUNTIME_DIR / ".macos_vision_ocr.lock"
    with _OCR_BUILD_THREAD_LOCK:
        descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
        try:
            os.fchmod(descriptor, 0o600)
            fcntl.flock(descriptor, fcntl.LOCK_EX)
            yield
        finally:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
            os.close(descriptor)


def ensure_ocr_binary() -> Path:
    status = ocr_toolchain_status()
    if not status["available"]:
        raise RuntimeError("macOS Vision OCR toolchain is unavailable")
    binary = _binary_path()
    with _build_transaction():
        if binary.is_file() and os.access(binary, os.X_OK):
            return binary
        temporary = binary.with_name(binary.name + ".tmp")
        completed = subprocess.run(
            [
                shutil.which("swiftc") or "swiftc",
                str(OCR_SOURCE),
                "-O",
                "-framework", "Vision",
                "-framework", "ImageIO",
                "-o", str(temporary),
            ],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if completed.returncode != 0:
            raise RuntimeError(
                "macOS Vision OCR helper compilation failed: "
                + (completed.stderr.strip() or "unknown compiler error")
            )
        os.chmod(temporary, 0o700)
        os.replace(temporary, binary)
        directory_fd = os.open(OCR_RUNTIME_DIR, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    return binary


def ocr_pdf_page(pdf_path: Path, page_number: int) -> dict[str, Any]:
    if page_number < 1:
        raise ValueError("PDF page number must be positive")
    binary = ensure_ocr_binary()
    pdftoppm = shutil.which("pdftoppm")
    if not pdftoppm:
        raise RuntimeError("pdftoppm is unavailable")
    with tempfile.TemporaryDirectory(prefix="prism-ocr-") as folder:
        prefix = Path(folder) / "page"
        rendered = subprocess.run(
            [
                pdftoppm,
                "-f", str(page_number),
                "-l", str(page_number),
                "-singlefile",
                "-png",
                "-r", str(OCR_RENDER_DPI),
                str(pdf_path),
                str(prefix),
            ],
            capture_output=True,
            text=True,
            timeout=OCR_PAGE_TIMEOUT_SECONDS,
        )
        image_path = prefix.with_suffix(".png")
        if rendered.returncode != 0 or not image_path.is_file():
            raise RuntimeError(
                f"PDF page {page_number} rasterization failed: "
                + (rendered.stderr.strip() or "no image produced")
            )
        recognized = subprocess.run(
            [str(binary), str(image_path)],
            capture_output=True,
            text=True,
            timeout=OCR_PAGE_TIMEOUT_SECONDS,
        )
        if recognized.returncode != 0:
            raise RuntimeError(
                f"PDF page {page_number} OCR failed: "
                + (recognized.stderr.strip() or "unknown OCR error")
            )
        try:
            result = json.loads(recognized.stdout)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"PDF page {page_number} OCR returned invalid JSON") from exc
        if result.get("engine") != "apple_vision_vnrecognizetextrequest":
            raise RuntimeError(f"PDF page {page_number} OCR returned an unexpected engine")
        if result.get("schemaVersion") != 1 or not isinstance(result.get("text"), str):
            raise RuntimeError(f"PDF page {page_number} OCR returned an invalid result schema")
        if not isinstance(result.get("lines"), list):
            raise RuntimeError(f"PDF page {page_number} OCR returned invalid line data")
        mean_confidence = result.get("meanConfidence")
        if mean_confidence is not None and not isinstance(mean_confidence, (int, float)):
            raise RuntimeError(f"PDF page {page_number} OCR returned invalid confidence data")
        return result
