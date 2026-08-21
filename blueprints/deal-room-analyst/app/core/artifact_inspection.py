"""Read-only evidence collection for a local model artifact.

Artifact presence is deliberately separate from provider configuration and
runtime invocation. This module never loads weights or starts a model server.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, Optional


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def inspect_model_artifact(path: str, backend_manifest: Optional[str] = None) -> Dict[str, Any]:
    artifact = Path(path).expanduser().resolve(strict=True)
    if not artifact.is_file():
        raise ValueError("artifact path is not a file")

    with artifact.open("rb") as handle:
        header = handle.read(8)
    format_name = "gguf" if header[:4] == b"GGUF" else artifact.suffix.lstrip(".").lower() or "unknown"
    gguf_version = int.from_bytes(header[4:8], "little") if format_name == "gguf" and len(header) == 8 else None
    digest = _sha256(artifact)

    sidecar = artifact.parent / ".cache" / "huggingface" / "download" / f"{artifact.name}.metadata"
    source_revision = None
    recorded_digest = None
    if sidecar.is_file():
        lines = sidecar.read_text(encoding="utf-8").splitlines()
        source_revision = lines[0].strip() if lines else None
        recorded_digest = lines[1].strip() if len(lines) > 1 else None

    backend = None
    if backend_manifest:
        manifest_path = Path(backend_manifest).expanduser().resolve(strict=True)
        backend = json.loads(manifest_path.read_text(encoding="utf-8"))
        backend = {
            "manifest_path": str(manifest_path),
            "name": backend.get("name"),
            "engine": backend.get("engine"),
            "version": backend.get("version"),
            "platform": backend.get("platform"),
            "cpu": backend.get("cpu"),
            "gpu": backend.get("gpu"),
            "supported_model_formats": backend.get("supported_model_formats"),
        }

    return {
        "measurement_state": "artifact_present_not_invoked",
        "artifact_path": str(artifact),
        "artifact_name": artifact.name,
        "size_bytes": artifact.stat().st_size,
        "format": format_name,
        "gguf_version": gguf_version,
        "sha256": digest,
        "source_revision": source_revision,
        "sidecar_digest": recorded_digest,
        "sidecar_digest_matches": bool(recorded_digest and recorded_digest == digest),
        "backend": backend,
        "limitations": [
            "Filesystem presence does not prove the model can be loaded.",
            "No provider request or model response was made.",
            "No latency, memory, energy, quality, or isolation claim was measured.",
        ],
    }
