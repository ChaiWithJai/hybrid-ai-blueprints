#!/usr/bin/env python3
"""Acquire one SEC candidate filing without registering a benchmark case."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
import urllib.parse
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.doc_parser import DealRoomParser, ParsedNode  # noqa: E402


REGISTRY = ROOT / "benchmarks" / "first_pass" / "candidate_deal_sources.v1.json"
USER_AGENT = "PrismML benchmark research engineering@prismml.ai"


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def resolve_primary_document(index_html: str, candidate: dict) -> str:
    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", index_html, re.IGNORECASE | re.DOTALL)
    matches = []
    for row in rows:
        text = re.sub(r"<[^>]+>", " ", row)
        text = re.sub(r"\s+", " ", text).strip()
        if not re.search(r"\bDEFM14A\b", text, re.IGNORECASE):
            continue
        hrefs = re.findall(r'href=["\']([^"\']+)["\']', row, re.IGNORECASE)
        matches.extend(item for item in hrefs if item.lower().endswith((".htm", ".html")))
    matches = list(dict.fromkeys(matches))
    if len(matches) != 1:
        raise ValueError(f"expected one primary DEFM14A document, found {len(matches)}")
    base = "https://www.sec.gov"
    url = urllib.parse.urljoin(base, matches[0])
    parsed = urllib.parse.urlparse(url)
    accession_compact = candidate["accession"].replace("-", "")
    expected_prefix = f"/Archives/edgar/data/{int(candidate['cik'])}/{accession_compact}/"
    if parsed.scheme != "https" or parsed.hostname != "www.sec.gov":
        raise ValueError("primary document is not on www.sec.gov")
    if not parsed.path.startswith(expected_prefix):
        raise ValueError("primary document path does not match the candidate CIK and accession")
    return url


def fetch(url: str, maximum_bytes: int = 12 * 1024 * 1024) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=30) as response:
        if response.status != 200:
            raise RuntimeError(f"HTTP {response.status} for {url}")
        declared = int(response.headers.get("Content-Length", "0") or 0)
        if declared > maximum_bytes:
            raise ValueError(f"source exceeds {maximum_bytes} bytes")
        body = response.read(maximum_bytes + 1)
    if len(body) > maximum_bytes:
        raise ValueError(f"source exceeds {maximum_bytes} bytes")
    return body


def anchor_count(node: ParsedNode) -> int:
    return int(bool(node.metadata.get("source_anchor"))) + sum(
        anchor_count(child) for child in node.children
    )


def record_acquisition_in_registry(
    registry_path: Path,
    evidence_path: Path,
    candidate_id: str,
    project_root: Path = ROOT,
) -> str:
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    evidence_bytes = evidence_path.read_bytes()
    evidence = json.loads(evidence_bytes)
    if evidence.get("candidate_id") != candidate_id:
        raise ValueError("candidate evidence identity does not match the registry target")
    if evidence.get("benchmark_case_registered") is not False:
        raise ValueError("candidate acquisition evidence cannot register a benchmark case")
    if evidence.get("domain_review_status") != "not_reviewed":
        raise ValueError("candidate acquisition evidence cannot claim domain review")
    if evidence.get("parser", {}).get("passed") is not True:
        raise ValueError("candidate acquisition evidence did not pass parser verification")
    matches = [item for item in registry.get("candidates", []) if item.get("id") == candidate_id]
    if len(matches) != 1:
        raise ValueError(f"candidate registry identity is not unique: {candidate_id}")
    try:
        relative_evidence = evidence_path.resolve().relative_to(project_root.resolve()).as_posix()
    except ValueError as exc:
        raise ValueError("candidate evidence must be stored inside the project") from exc
    evidence_sha256 = sha256_bytes(evidence_bytes)
    matches[0].update({
        "state": "acquired_parser_verified_not_registered",
        "evidence_path": relative_evidence,
        "evidence_sha256": evidence_sha256,
    })
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=registry_path.parent, delete=False,
    ) as handle:
        handle.write(json.dumps(registry, indent=2) + "\n")
        temporary = Path(handle.name)
    os.replace(temporary, registry_path)
    return evidence_sha256


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate", required=True)
    parser.add_argument("--output")
    args = parser.parse_args()
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    candidates = {item["id"]: item for item in registry["candidates"]}
    if args.candidate not in candidates:
        raise ValueError(f"unknown candidate {args.candidate}")
    candidate = candidates[args.candidate]
    index_bytes = fetch(candidate["filing_url"], maximum_bytes=3 * 1024 * 1024)
    primary_url = resolve_primary_document(index_bytes.decode("utf-8", "replace"), candidate)
    source_bytes = fetch(primary_url)
    destination = ROOT / ".runtime" / "candidate-deal-sources" / candidate["id"] / "01_defm14a.htm"
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=destination.parent, delete=False) as handle:
        handle.write(source_bytes)
        temporary = Path(handle.name)
    os.replace(temporary, destination)
    document = DealRoomParser(max_file_bytes=12 * 1024 * 1024).parse_file(str(destination))
    report = {
        "verification_kind": "candidate_source_acquisition",
        "candidate_id": candidate["id"],
        "benchmark_case_registered": False,
        "domain_review_status": "not_reviewed",
        "source": {
            "index_url": candidate["filing_url"],
            "primary_url": primary_url,
            "cik": candidate["cik"],
            "accession": candidate["accession"],
            "path": str(destination.relative_to(ROOT)),
            "bytes": len(source_bytes),
            "sha256": sha256_bytes(source_bytes),
        },
        "parser": {
            "passed": document.metadata.get("source_sha256") == sha256_bytes(source_bytes),
            "file_type": document.file_type,
            "estimated_tokens": document.estimated_token_count,
            "table_count": len(document.extracted_tables),
            "anchor_count": anchor_count(document.root_node),
        },
        "limitations": [
            "Source acquisition and parser admission do not create a benchmark case or expected answer.",
            "The filing still needs question design, evidence review, split assignment, and domain approval.",
        ],
    }
    output = (
        (ROOT / args.output).resolve()
        if args.output
        else ROOT / "evidence" / f"candidate-source-{candidate['id']}.json"
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    evidence_sha256 = record_acquisition_in_registry(
        REGISTRY, output, candidate["id"],
    )
    print(json.dumps({
        "output": str(output),
        "candidate_id": candidate["id"],
        "primary_url": primary_url,
        "bytes": len(source_bytes),
        "sha256": report["source"]["sha256"],
        "parser_passed": report["parser"]["passed"],
        "benchmark_case_registered": False,
        "registry_state": "acquired_parser_verified_not_registered",
        "evidence_sha256": evidence_sha256,
    }, indent=2))
    return 0 if report["parser"]["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
