#!/usr/bin/env python3
"""Download the pinned public deal corpus and reject changed source bytes."""

from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "benchmarks" / "public_deal_corpus_manifest.json"


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def acquire(document: dict) -> dict:
    destination = ROOT / document["path"]
    destination.parent.mkdir(parents=True, exist_ok=True)
    expected = document["sha256"]
    if destination.is_file() and digest(destination) == expected:
        return {"id": document["id"], "status": "already_verified", "sha256": expected}

    errors = []
    for url in document["retrieval_urls"]:
        request = urllib.request.Request(
            url,
            headers={"User-Agent": "PrismVaultResearch/0.1 public-deal-evaluation"},
        )
        temp_path = None
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                with tempfile.NamedTemporaryFile(delete=False, dir=destination.parent) as temp:
                    temp_path = Path(temp.name)
                    while chunk := response.read(1024 * 1024):
                        temp.write(chunk)
            observed = digest(temp_path)
            if observed != expected:
                errors.append(f"{url}: sha256 {observed} did not match")
                temp_path.unlink(missing_ok=True)
                continue
            if temp_path.stat().st_size != document["bytes"]:
                errors.append(f"{url}: byte count did not match")
                temp_path.unlink(missing_ok=True)
                continue
            os.replace(temp_path, destination)
            return {"id": document["id"], "status": "downloaded_verified", "url": url, "sha256": observed}
        except (OSError, urllib.error.URLError) as exc:
            if temp_path:
                temp_path.unlink(missing_ok=True)
            errors.append(f"{url}: {exc}")
    raise RuntimeError("; ".join(errors))


def main() -> int:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    results = []
    for document in manifest["documents"]:
        try:
            results.append(acquire(document))
        except RuntimeError as exc:
            results.append({"id": document["id"], "status": "failed", "error": str(exc)})
    print(json.dumps({"manifest_version": manifest["version"], "results": results}, indent=2))
    return 1 if any(result["status"] == "failed" for result in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
