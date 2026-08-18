"""Recompute the evidence inventory behind a bounded model request."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Iterable

from core.doc_parser import ParsedDocument, evidence_node_text, iter_evidence_nodes


EVIDENCE_SCOPE_VERSION = "current_parser_inventory_v1"


def inline_xbrl_metadata_block(text: str) -> bool:
    """Identify hidden inline XBRL taxonomy and context payloads."""
    lowered = text.lower()
    return (
        "http://fasb.org/us-gaap/" in lowered
        or lowered.count("us-gaap:") >= 3
        or lowered.count("xbrli:") >= 2
    )


def build_evidence_inventory(
    documents: Iterable[ParsedDocument],
    *,
    source_snapshot_sha256: str,
) -> dict[str, Any]:
    """Hash every node that the current lexical retriever can admit."""
    document_list = list(documents)
    parsed_node_count = 0
    entries: list[dict[str, str]] = []
    citation_sources: dict[str, str] = {}
    for document in document_list:
        source_sha256 = str(document.metadata.get("source_sha256") or "")
        for node, section_titles in iter_evidence_nodes(document.root_node):
            parsed_node_count += 1
            text = evidence_node_text(node, section_titles, max_chars=1800)
            if not text or inline_xbrl_metadata_block(text):
                continue
            anchor = str(node.metadata.get("source_anchor") or f"node:{node.id}")
            citation = f"[{document.filename}#{anchor}]"
            entry = {
                "citation": citation,
                "source_sha256": source_sha256,
                "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
            }
            if citation in citation_sources:
                raise ValueError(f"duplicate parser citation: {citation}")
            entries.append(entry)
            citation_sources[citation] = source_sha256
    entries.sort(key=lambda item: (item["citation"], item["text_sha256"]))
    binding = {
        "scope_version": EVIDENCE_SCOPE_VERSION,
        "source_snapshot_sha256": source_snapshot_sha256,
        "entries": entries,
    }
    return {
        "scope_version": EVIDENCE_SCOPE_VERSION,
        "source_snapshot_sha256": source_snapshot_sha256,
        "document_count": len(document_list),
        "parsed_node_count": parsed_node_count,
        "searchable_node_count": len(entries),
        "inventory_sha256": hashlib.sha256(
            json.dumps(binding, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest(),
        "citation_sources": citation_sources,
    }


def evidence_scope_for_anchors(
    inventory: dict[str, Any],
    traced_anchors: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Return a current scope only when every traced passage still resolves."""
    citation_sources = inventory.get("citation_sources")
    if not isinstance(citation_sources, dict) or not isinstance(traced_anchors, list):
        return None
    admitted: dict[str, str] = {}
    for item in traced_anchors:
        if not isinstance(item, dict):
            return None
        citation = item.get("citation")
        source_sha256 = item.get("source_sha256")
        if (
            not isinstance(citation, str)
            or not isinstance(source_sha256, str)
            or citation_sources.get(citation) != source_sha256
        ):
            return None
        admitted[citation] = source_sha256
    return _scope_record(inventory, admitted)


def evidence_scope_for_citations(
    inventory: dict[str, Any], citations: list[str],
) -> dict[str, Any] | None:
    """Return a current scope only when every signed citation still resolves."""
    citation_sources = inventory.get("citation_sources")
    if not isinstance(citation_sources, dict) or not isinstance(citations, list):
        return None
    admitted: dict[str, str] = {}
    for citation in citations:
        if not isinstance(citation, str) or citation not in citation_sources:
            return None
        admitted[citation] = str(citation_sources[citation])
    return _scope_record(inventory, admitted)


def _scope_record(
    inventory: dict[str, Any], admitted: dict[str, str],
) -> dict[str, Any]:
    filenames = {
        citation[1:].split("#", 1)[0]
        for citation in admitted
        if citation.startswith("[") and "#" in citation
    }
    return {
        "scope_version": inventory["scope_version"],
        "source_snapshot_sha256": inventory["source_snapshot_sha256"],
        "inventory_sha256": inventory["inventory_sha256"],
        "corpus_document_count": inventory["document_count"],
        "corpus_parsed_node_count": inventory["parsed_node_count"],
        "corpus_searchable_node_count": inventory["searchable_node_count"],
        "admitted_passage_count": len(admitted),
        "admitted_document_count": len(filenames),
        "measurement_state": "current_parser_inventory_and_trace_bound_passage_selection",
        "semantic_coverage_measured": False,
        "full_document_review_claimed": False,
        "meaning": (
            "The model received the admitted passages, not every parsed node. "
            "These counts describe passage selection and do not measure semantic coverage."
        ),
    }
