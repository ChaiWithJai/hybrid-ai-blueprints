#!/usr/bin/env python3
"""Discover pre-proxy SEC financial filings without acquiring or registering cases."""

from __future__ import annotations

import argparse
from datetime import date
import json
from pathlib import Path
import re
import sys
import time
import urllib.request


ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "benchmarks" / "first_pass" / "candidate_deal_sources.v1.json"
DEFAULT_OUTPUT = (
    ROOT / "benchmarks" / "first_pass" / "candidate_companion_sources.v1.json"
)
USER_AGENT = "PrismML benchmark research engineering@prismml.ai"
FINANCIAL_FORMS = {"10-K", "10-Q"}


def filing_rows(payload: dict) -> list[dict]:
    recent = payload.get("filings", {}).get("recent", {})
    keys = (
        "accessionNumber", "filingDate", "reportDate", "form", "primaryDocument",
    )
    lengths = [len(recent.get(key, [])) for key in keys]
    if not lengths or len(set(lengths)) != 1:
        raise ValueError("SEC submissions columns have different lengths")
    return [
        {key: recent[key][index] for key in keys}
        for index in range(lengths[0])
    ]


def _valid_row(row: dict, candidate: dict) -> bool:
    try:
        filing_date = date.fromisoformat(str(row.get("filingDate", "")))
        proxy_date = date.fromisoformat(candidate["filing_date"])
    except ValueError:
        return False
    return bool(
        row.get("form") in FINANCIAL_FORMS
        and filing_date <= proxy_date
        and re.fullmatch(r"\d{10}-\d{2}-\d{6}", str(row.get("accessionNumber", "")))
        and re.fullmatch(r"[A-Za-z0-9._-]+\.(?:htm|html)", str(row.get("primaryDocument", "")))
    )


def select_companion(candidate: dict, payloads: list[dict]) -> dict | None:
    rows = [row for payload in payloads for row in filing_rows(payload)]
    eligible = [row for row in rows if _valid_row(row, candidate)]
    if not eligible:
        return None
    selected = max(
        eligible,
        key=lambda row: (row["filingDate"], row["accessionNumber"]),
    )
    accession_compact = selected["accessionNumber"].replace("-", "")
    cik_number = str(int(candidate["cik"]))
    archive = f"https://www.sec.gov/Archives/edgar/data/{cik_number}/{accession_compact}"
    return {
        "candidate_id": candidate["id"],
        "company": candidate["company"],
        "cik": candidate["cik"],
        "proxy_accession": candidate["accession"],
        "proxy_filing_date": candidate["filing_date"],
        "form": selected["form"],
        "accession": selected["accessionNumber"],
        "filing_date": selected["filingDate"],
        "report_date": selected["reportDate"],
        "primary_document": selected["primaryDocument"],
        "filing_url": f"{archive}/{selected['accessionNumber']}-index.html",
        "primary_url": f"{archive}/{selected['primaryDocument']}",
        "state": "discovered_not_acquired_not_registered",
        "benchmark_case_registered": False,
        "domain_review_status": "not_reviewed",
    }


def fetch_json(url: str) -> dict:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=30) as response:
        if response.status != 200:
            raise RuntimeError(f"HTTP {response.status} for {url}")
        body = response.read(15 * 1024 * 1024 + 1)
    if len(body) > 15 * 1024 * 1024:
        raise ValueError("SEC submissions response exceeds 15 MiB")
    return json.loads(body)


def submission_payloads(candidate: dict, offline_directory: Path | None) -> list[dict]:
    cik = candidate["cik"]
    if offline_directory:
        primary = json.loads((offline_directory / f"CIK{cik}.json").read_text())
    else:
        primary = fetch_json(f"https://data.sec.gov/submissions/CIK{cik}.json")
    payloads = [primary]
    if any(_valid_row(row, candidate) for row in filing_rows(primary)):
        return payloads
    for item in primary.get("filings", {}).get("files", []):
        name = item.get("name", "")
        if not re.fullmatch(r"CIK\d{10}-submissions-\d{3}\.json", name):
            continue
        if offline_directory:
            path = offline_directory / name
            if not path.exists():
                continue
            payloads.append(json.loads(path.read_text()))
        else:
            time.sleep(0.12)
            payloads.append(fetch_json(f"https://data.sec.gov/submissions/{name}"))
        if any(_valid_row(row, candidate) for row in filing_rows(payloads[-1])):
            break
    return payloads


def discover(registry: dict, offline_directory: Path | None = None) -> dict:
    companions = []
    missing = []
    for index, candidate in enumerate(registry.get("candidates", [])):
        if index and not offline_directory:
            time.sleep(0.12)
        companion = select_companion(
            candidate, submission_payloads(candidate, offline_directory),
        )
        if companion:
            companions.append(companion)
        else:
            missing.append(candidate["id"])
    return {
        "registry_kind": "first_pass_candidate_companion_sources",
        "version": "1.0.0",
        "status": "research_inventory_not_benchmark_data",
        "source_method": "SEC submissions JSON, latest 10-K or 10-Q filed on or before the deal proxy",
        "acceptance_boundary": (
            "A discovered filing contributes no source bytes, case, split, label, approval, "
            "or accuracy evidence until it is acquired, hashed, parsed, anchored, and reviewed."
        ),
        "candidate_count": len(registry.get("candidates", [])),
        "companion_count": len(companions),
        "missing_candidate_ids": missing,
        "companions": companions,
        "limitations": [
            "Filing form and date select a research candidate; they do not prove relevance to a benchmark question.",
            "The discovery step does not download filing bytes or inspect tables and source anchors.",
            "A 10-K or 10-Q is public company reporting and is not a private deal room document.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--offline-submissions-dir")
    args = parser.parse_args()
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    offline = Path(args.offline_submissions_dir).resolve() if args.offline_submissions_dir else None
    result = discover(registry, offline)
    output = Path(args.output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "output": str(output),
        "candidate_count": result["candidate_count"],
        "companion_count": result["companion_count"],
        "missing_candidate_ids": result["missing_candidate_ids"],
        "benchmark_case_registered": False,
    }, indent=2))
    return 0 if result["companion_count"] == result["candidate_count"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
