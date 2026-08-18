#!/usr/bin/env python3
"""Search a local deal folder and return short passages with source anchors."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Iterable


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.doc_parser import (
    DealRoomParser,
    ParsedNode,
    evidence_node_text,
    iter_evidence_nodes,
)
from core.evidence_scope import inline_xbrl_metadata_block


STOPWORDS = {
    "a", "an", "and", "as", "at", "be", "by", "did", "do", "for", "from", "how",
    "in", "into", "is", "it", "of", "on", "or", "the", "to", "was", "what", "when",
    "which", "who", "with", "its", "this", "that", "source", "cite", "exact",
    "battletest", "retry", "direct", "create", "modify", "file", "block", "html",
    "htm", "any", "not",
    "shall", "have", "has", "had", "will", "would", "may",
}


def terms(value: str) -> list[str]:
    return [
        token for token in re.findall(r"[a-z0-9$%.]+", value.lower())
        if token not in STOPWORDS and any(character.isalnum() for character in token)
        and len(token) > 1
    ]


def ordered_phrase_bonus(query_terms: list[str], text_terms: list[str]) -> float:
    """Reward exact local wording without making it a required answer string.

    SEC filings repeat broad words such as merger, condition, and financing.
    A bag-of-words score therefore ranks tables of contents and unrelated
    financing clauses above a short sentence that contains the requested legal
    phrase. This bounded bonus uses only the operator's query and source text.
    """
    if len(query_terms) < 2 or len(text_terms) < 2:
        return 0.0
    text_ngrams = {
        size: {
            tuple(text_terms[index:index + size])
            for index in range(len(text_terms) - size + 1)
        }
        for size in range(2, min(6, len(query_terms), len(text_terms)) + 1)
    }
    for size in range(min(6, len(query_terms)), 1, -1):
        for index in range(len(query_terms) - size + 1):
            if tuple(query_terms[index:index + size]) in text_ngrams.get(size, set()):
                return round(size * size * 0.8, 3)
    return 0.0


def node_text(node: ParsedNode) -> str:
    """Compatibility wrapper for callers inspecting one node without hierarchy."""
    return evidence_node_text(node)


def walk(node: ParsedNode) -> Iterable[ParsedNode]:
    yield node
    for child in node.children:
        yield from walk(child)


def query(
    folder: Path,
    request: str,
    limit: int = 8,
    source_filenames: set[str] | None = None,
) -> list[dict]:
    """Search a folder, optionally admitting only exact relative filenames."""
    parser = DealRoomParser()
    query_terms = terms(request)
    results = []
    for document in parser.parse_deal_room_folder(str(folder)):
        relative = document.filename
        if source_filenames is not None and relative not in source_filenames:
            continue
        path_terms = set(terms(relative))
        for node, section_titles in iter_evidence_nodes(document.root_node):
            text = evidence_node_text(node, section_titles, max_chars=1800)
            if not text or inline_xbrl_metadata_block(text):
                continue
            lowered = text.lower()
            matched = [term for term in query_terms if term in lowered]
            if not matched:
                continue
            score = sum(1 + min(lowered.count(term), 4) * 0.2 for term in matched)
            score += ordered_phrase_bonus(query_terms, terms(text))
            score += sum(2 for term in query_terms if term in path_terms)
            score += sum(2 for term in matched if any(character.isdigit() for character in term))
            anchor = node.metadata.get("source_anchor") or f"node:{node.id}"
            parser_disclosure = None
            if document.file_type == "xlsx":
                parser_disclosure = (
                    "XLSX formulas were not recalculated. A bounded set of audited number formats "
                    "was applied; other formats remain raw. "
                    f"{document.metadata.get('cached_formula_cell_count', 0)} formula cells use "
                    "cached values and "
                    f"{document.metadata.get('unevaluated_formula_cell_count', 0)} formula cells "
                    "had no cached value. "
                    f"{document.metadata.get('formatted_numeric_cell_count', 0)} numeric cells were "
                    "formatted and "
                    f"{document.metadata.get('unsupported_number_format_cell_count', 0)} used "
                    "unsupported number formats."
                )
            elif node.metadata.get("text_extraction") == "ocr":
                parser_disclosure = (
                    "This page used Apple Vision OCR. OCR text and reading order may be wrong. "
                    "Tables, columns, merged cells, and document layout were not reconstructed. "
                    "The recorded engine confidence is not a measured accuracy score."
                )
            results.append({
                "filename": relative,
                "source_anchor": anchor,
                "citation": f"[{relative}#{anchor}]",
                "score": round(score, 3),
                "matched_terms": sorted(set(matched)),
                "text": text,
                "source_sha256": document.metadata.get("source_sha256"),
                "source_role": "supplemental_filing" if "supplement" in relative.lower() else "primary_source",
                "parser_disclosure": parser_disclosure,
            })
    results.sort(key=lambda result: (-result["score"], result["filename"], result["source_anchor"]))
    best_per_document = []
    seen_documents = set()
    for result in results:
        if result["filename"] not in seen_documents:
            best_per_document.append(result)
            seen_documents.add(result["filename"])
    selected = list(best_per_document)
    selected_keys = {(result["filename"], result["source_anchor"]) for result in selected}
    selected.extend(
        result for result in results
        if (result["filename"], result["source_anchor"]) not in selected_keys
    )
    return selected[:limit]


def main() -> int:
    cli = argparse.ArgumentParser()
    source_boundary = os.environ.get("PRISM_DEAL_ROOM_SOURCE")
    cli.add_argument("--folder", default=source_boundary or ".")
    cli.add_argument("--query", required=True)
    cli.add_argument("--limit", type=int, default=8)
    args = cli.parse_args()
    folder = Path(args.folder).resolve(strict=True)
    if not folder.is_dir():
        cli.error("folder is not a directory")
    if source_boundary and folder != Path(source_boundary).resolve(strict=True):
        cli.error("folder is outside the configured source boundary")
    if not 1 <= args.limit <= 20:
        cli.error("limit must be between 1 and 20")
    print(json.dumps({"query": args.query, "results": query(folder, args.query, args.limit)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
