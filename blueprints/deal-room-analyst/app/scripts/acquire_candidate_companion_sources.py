#!/usr/bin/env python3
"""Acquire parser-bounded SEC financial companions without registering cases."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import time
import urllib.parse
import urllib.request


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.doc_parser import DealRoomParser, ParsedNode  # noqa: E402


REGISTRY = ROOT / "benchmarks" / "first_pass" / "candidate_companion_sources.v1.json"
USER_AGENT = "PrismML benchmark research engineering@prismml.ai"
MAXIMUM_BYTES = 10 * 1024 * 1024


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def anchor_count(node: ParsedNode) -> int:
    return int(bool(node.metadata.get("source_anchor"))) + sum(
        anchor_count(child) for child in node.children
    )


def validate_primary_url(companion: dict) -> None:
    parsed = urllib.parse.urlparse(companion.get("primary_url", ""))
    accession = str(companion.get("accession", ""))
    primary_document = str(companion.get("primary_document", ""))
    if not re.fullmatch(r"\d{10}-\d{2}-\d{6}", accession):
        raise ValueError("companion accession is invalid")
    if not re.fullmatch(r"[A-Za-z0-9._-]+\.(?:htm|html)", primary_document):
        raise ValueError("companion primary document is invalid")
    expected_path = (
        f"/Archives/edgar/data/{int(companion['cik'])}/"
        f"{accession.replace('-', '')}/{primary_document}"
    )
    if (
        parsed.scheme != "https"
        or parsed.hostname != "www.sec.gov"
        or parsed.path != expected_path
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("companion primary URL is outside its exact SEC filing path")


def fetch(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=45) as response:
        if response.status != 200:
            raise RuntimeError(f"HTTP {response.status} for {url}")
        declared = int(response.headers.get("Content-Length", "0") or 0)
        if declared > MAXIMUM_BYTES:
            raise ValueError(f"source exceeds the {MAXIMUM_BYTES} byte product parser limit")
        body = response.read(MAXIMUM_BYTES + 1)
    if len(body) > MAXIMUM_BYTES:
        raise ValueError(f"source exceeds the {MAXIMUM_BYTES} byte product parser limit")
    return body


def _atomic_json(path: Path, value: dict) -> None:
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


def acquire_one(companion: dict) -> tuple[dict, dict]:
    validate_primary_url(companion)
    form_slug = companion["form"].lower().replace("-", "")
    destination = (
        ROOT / ".runtime" / "candidate-deal-sources" / companion["candidate_id"]
        / f"02_financial_{form_slug}.htm"
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    expected_sha = companion.get("source_sha256")
    if destination.exists() and expected_sha and sha256_bytes(destination.read_bytes()) == expected_sha:
        source_bytes = destination.read_bytes()
        acquisition_state = "already_verified"
    else:
        source_bytes = fetch(companion["primary_url"])
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=".financial_companion.", suffix=".tmp", dir=destination.parent,
        )
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(source_bytes)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_name, destination)
        except Exception:
            try:
                os.unlink(temporary_name)
            except OSError:
                pass
            raise
        acquisition_state = "downloaded_verified"
    source_sha = sha256_bytes(source_bytes)
    document = DealRoomParser(max_file_bytes=MAXIMUM_BYTES).parse_file(str(destination))
    parser_passed = document.metadata.get("source_sha256") == source_sha
    evidence = {
        "verification_kind": "candidate_companion_source_acquisition",
        "candidate_id": companion["candidate_id"],
        "benchmark_case_registered": False,
        "domain_review_status": "not_reviewed",
        "source": {
            "form": companion["form"],
            "filing_date": companion["filing_date"],
            "report_date": companion["report_date"],
            "accession": companion["accession"],
            "primary_url": companion["primary_url"],
            "path": destination.relative_to(ROOT).as_posix(),
            "bytes": len(source_bytes),
            "sha256": source_sha,
        },
        "parser": {
            "passed": parser_passed,
            "file_type": document.file_type,
            "estimated_tokens": document.estimated_token_count,
            "table_count": len(document.extracted_tables),
            "anchor_count": anchor_count(document.root_node),
            "product_file_limit_bytes": MAXIMUM_BYTES,
        },
        "limitations": [
            "Acquisition and parser admission do not create a benchmark case or expected answer.",
            "The filing still needs question design, source review, split assignment, and domain approval.",
            "Parser table detection does not prove that a table supports any benchmark claim.",
        ],
    }
    if not parser_passed:
        raise ValueError("parser source hash differs from the acquired bytes")
    evidence_path = ROOT / "evidence" / f"candidate-companion-source-{companion['candidate_id']}.json"
    _atomic_json(evidence_path, evidence)
    updated = dict(companion)
    updated.update({
        "state": "acquired_parser_verified_not_registered",
        "source_path": destination.relative_to(ROOT).as_posix(),
        "source_bytes": len(source_bytes),
        "source_sha256": source_sha,
        "evidence_path": evidence_path.relative_to(ROOT).as_posix(),
        "evidence_sha256": sha256_bytes(evidence_path.read_bytes()),
        "parser_table_count": evidence["parser"]["table_count"],
        "parser_anchor_count": evidence["parser"]["anchor_count"],
    })
    return updated, {
        "candidate_id": companion["candidate_id"],
        "status": acquisition_state,
        "bytes": len(source_bytes),
        "sha256": source_sha,
        "table_count": evidence["parser"]["table_count"],
        "anchor_count": evidence["parser"]["anchor_count"],
        "benchmark_case_registered": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate")
    args = parser.parse_args()
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    selected = [
        item for item in registry["companions"]
        if not args.candidate or item["candidate_id"] == args.candidate
    ]
    if not selected:
        raise ValueError("no matching companion source")
    updated_by_id = {}
    results = []
    for index, companion in enumerate(selected):
        if index:
            time.sleep(0.12)
        try:
            updated, result = acquire_one(companion)
            updated_by_id[companion["candidate_id"]] = updated
            results.append(result)
        except Exception as exc:
            results.append({
                "candidate_id": companion["candidate_id"],
                "status": "failed",
                "error": str(exc),
                "benchmark_case_registered": False,
            })
    registry["companions"] = [
        updated_by_id.get(item["candidate_id"], item)
        for item in registry["companions"]
    ]
    registry["acquired_count"] = sum(
        item.get("state") == "acquired_parser_verified_not_registered"
        for item in registry["companions"]
    )
    registry["parser_verified_count"] = registry["acquired_count"]
    _atomic_json(REGISTRY, registry)
    print(json.dumps({
        "candidate_count": registry["candidate_count"],
        "acquired_count": registry["acquired_count"],
        "parser_verified_count": registry["parser_verified_count"],
        "results": results,
    }, indent=2))
    return 1 if any(item["status"] == "failed" for item in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
