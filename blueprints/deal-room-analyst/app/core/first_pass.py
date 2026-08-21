"""Evidence bounded first pass underwriting generation for Prism Vault."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
import re
from typing import Any

from core.ai_provider import OpenAICompatibleProvider, ProviderError
from scripts.query_deal_room import query as query_deal_room


DEFAULT_INVESTMENT_SCREEN = """Assess whether the deal should advance to deeper review.
Focus on transaction structure, valuation, financing, financial quality, material risks,
required approvals, missing information, and the next questions a deal team should answer."""
FIRST_PASS_GUARD_VERSION = "evidence_claim_v7"
EVIDENCE_FALLBACK_GUARD_VERSION = "source_excerpt_v2"

REQUIRED_HEADINGS = (
    "Recommendation",
    "Transaction",
    "Valuation and financing",
    "Financial quality",
    "Risks and approvals",
    "Missing or conflicting information",
    "Next review questions",
)

SEARCH_QUERIES = (
    "transaction parties purchase price structure consideration closing chronology",
    "financing debt preferred equity common equity cash leverage sources uses",
    "revenue EBITDA earnings cash debt valuation multiple financial projections adjustments",
    "material risks covenants litigation regulatory approvals competition termination",
    "diligence data room board recommendation conflicts missing information",
)

FALLBACK_SECTION_TERMS = {
    "Transaction": ("transaction", "target", "buyer", "seller", "merger", "sources", "consideration"),
    "Valuation and financing": (
        "valuation", "leverage", "debt", "equity", "financing", "sources", "multiple", "returns",
    ),
    "Financial quality": (
        "revenue", "ebitda", "margin", "cash flow", "income", "capex", "financial",
    ),
    "Risks and approvals": (
        "risk", "covenant", "default", "approval", "regulatory", "litigation", "termination", "restricted",
    ),
}

YEAR_TOKEN = re.compile(r"^20\d{2}[A-Za-z0-9_]*$")
VALUE_BEFORE_YEAR = re.compile(
    r"\$?(?P<value>\d[\d,]*(?:\.\d+)?)\s*(?:%|[mMxX]|M\s+USD)?\s*"
    r"(?:in|for|by|at|as\s+of)?\s*(?P<year>20\d{2}[A-Za-z0-9_]*)",
    re.I,
)
YEAR_BEFORE_VALUE = re.compile(
    r"(?P<year>20\d{2}[A-Za-z0-9_]*)\s*(?:is|of|at|:)?\s*"
    r"\$?(?P<value>\d[\d,]*(?:\.\d+)?)",
    re.I,
)
YOY_GROWTH_CLAIM = re.compile(
    r"(?:revenue|ebitda)[^.\n]*?from\s+\$?(?P<start>\d[\d,]*(?:\.\d+)?)"
    r"[^.\n]*?(?P<start_year>20\d{2}[A-Za-z0-9_]*)[^.\n]*?to\s+\$?"
    r"(?P<end>\d[\d,]*(?:\.\d+)?)[^.\n]*?(?P<end_year>20\d{2}[A-Za-z0-9_]*)"
    r"[^.\n]*?(?:representing|or)\s+(?:a\s+)?(?:"
    r"(?P<growth_before>\d+(?:\.\d+)?)%\s+YoY|"
    r"YoY\s+growth\s+rate\s+of\s+(?P<growth_after>\d+(?:\.\d+)?)%"
    r")",
    re.I,
)
LEVERAGE_CALC_CLAIM = re.compile(
    r"leverage\s+multiple\s+is\s+(?P<multiple>\d+(?:\.\d+)?)x"
    r"[^.\n]*?calculated\s+as[^.\n]*?total\s+sources\s*\(\$(?P<numerator>[\d,]+(?:\.\d+)?)"
    r"[^.\n]*?divided\s+by[^.\n]*?ebitda[^.\n]*?\$(?P<denominator>[\d,]+(?:\.\d+)?)",
    re.I,
)


class FirstPassError(RuntimeError):
    """Raised when a first pass draft cannot meet the product contract."""

    def __init__(self, message: str, metadata: dict[str, Any] | None = None):
        super().__init__(message)
        self.metadata = metadata or {}


@dataclass(frozen=True)
class FirstPassResult:
    markdown: str
    recommendation: str
    provider: str
    model: str
    latency_ms: float
    usage: dict[str, int]
    citations: list[str]
    retrieved_passages: list[dict[str, Any]]
    raw_metadata: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class EvidenceFallbackResult:
    markdown: str
    recommendation: str
    provider: str
    model: str
    latency_ms: float
    usage: dict[str, int]
    citations: list[str]
    retrieved_passages: list[dict[str, Any]]
    raw_metadata: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def restore_signed_first_pass(content: str) -> dict[str, Any] | None:
    """Restore a draft from its signed Buzz event without upgrading legacy evidence."""
    marker = re.search(r"<!-- prism:first-pass-draft ([^>]+) -->", content)
    if marker is None:
        return None
    attributes = marker.group(1)
    model = re.search(r"(?:^|\s)model=([^ ]+)", attributes)
    recommendation = re.search(r"(?:^|\s)recommendation=([^ ]+)", attributes)
    guard = re.search(r"(?:^|\s)guard=([^ ]+)", attributes)
    mode = re.search(r"(?:^|\s)mode=([^ ]+)", attributes)
    trace = re.search(r"(?:^|\s)trace=([^ ]+)", attributes)
    failed_trace = re.search(r"(?:^|\s)model_failure_trace=([^ ]+)", attributes)
    source_class = re.search(r"(?:^|\s)source_class=([^ ]+)", attributes)
    provenance = re.search(r"(?:^|\s)provenance=([0-9a-f]{64})(?:\s|$)", attributes)
    source_snapshot = re.search(
        r"(?:^|\s)source_snapshot=([0-9a-f]{64})(?:\s|$)", attributes,
    )
    markdown = re.sub(
        r"^<!-- prism:first-pass-draft[^>]*>\s*# (?:First pass underwriting draft|Evidence-safe first pass fallback)\s*",
        "",
        content,
        flags=re.S,
    ).strip()
    citations = sorted(set(re.findall(r"\[[^\]\n]+#[^\]\n]+\]", markdown)))
    guard_version = guard.group(1) if guard else None
    artifact_mode = mode.group(1) if mode else "model_draft"
    is_current_fallback = (
        artifact_mode == "evidence_safe_fallback"
        and guard_version == EVIDENCE_FALLBACK_GUARD_VERSION
        and source_class is not None
        and provenance is not None
        and source_snapshot is not None
    )
    has_current_provenance_binding = (
        source_class is not None and provenance is not None and source_snapshot is not None
    )
    return {
        "markdown": markdown,
        "recommendation": recommendation.group(1) if recommendation else "unknown",
        "model": model.group(1) if model else "unknown",
        "citations": citations,
        "acceptance_state": (
            "evidence_safe_fallback" if is_current_fallback
            else "accepted" if (
                guard_version == FIRST_PASS_GUARD_VERSION and has_current_provenance_binding
            )
            else "legacy_unverified"
        ),
        "guard_version": guard_version,
        "artifact_mode": artifact_mode,
        "authored_by": (
            "deterministic_evidence_renderer" if is_current_fallback else "local_bonsai"
        ),
        "trace_id": trace.group(1) if trace else None,
        "model_failure_trace_id": failed_trace.group(1) if failed_trace else None,
        "source_classification": source_class.group(1) if source_class else None,
        "source_provenance_sha256": provenance.group(1) if provenance else None,
        "source_snapshot_sha256": source_snapshot.group(1) if source_snapshot else None,
    }


def _fallback_excerpt(text: str, limit: int = 900) -> str:
    compact = " ".join(text.split())
    if len(compact) <= limit:
        return compact
    boundary = compact.rfind(" ", 0, limit)
    return compact[:boundary if boundary > 0 else limit].rstrip() + " … [excerpt truncated]"


def build_evidence_safe_fallback(
    passages: list[dict[str, Any]],
    model_failure_trace_id: str,
    investment_screen: str | None = None,
) -> EvidenceFallbackResult:
    """Build a reviewable source-excerpt artifact without promoting rejected model prose."""
    if not passages:
        raise FirstPassError("No admitted passages are available for an evidence-safe fallback")
    sections = [
        "## Recommendation\n\n"
        "Recommendation: PAUSE\n\n"
        "Prism generated this evidence-safe fallback because the Bonsai candidate failed "
        "deterministic evidence checks. PAUSE is a system safety disposition, not a model "
        "recommendation. The rejected model run remains a separate trace."
    ]
    used: dict[str, dict[str, Any]] = {}
    screen_passages = [
        passage for passage in passages
        if "investment_screen" in passage.get("retrieval_reasons", [])
    ][:3]
    if investment_screen and screen_passages:
        body = []
        for index, passage in enumerate(screen_passages, start=1):
            citation = str(passage["citation"])
            used[citation] = passage
            excerpt = _fallback_excerpt(str(passage.get("text", "")))
            body.append(f"### Screen-matched source excerpt {index}\n\n> {excerpt}\n\n{citation}")
        sections.append("## Investment screen evidence\n\n" + "\n\n".join(body))
    for heading, terms in FALLBACK_SECTION_TERMS.items():
        scored = []
        for passage in passages:
            if str(passage.get("citation", "")) in used:
                continue
            text = str(passage.get("text", ""))
            lowered = text.lower().replace("_", " ")
            matches = sum(1 for term in terms if term in lowered)
            if matches:
                scored.append((matches, float(passage.get("score", 0)), passage))
        selected = [item[2] for item in sorted(
            scored,
            key=lambda item: (-item[0], -item[1], item[2]["citation"]),
        )[:2]]
        body = []
        for index, passage in enumerate(selected, start=1):
            citation = str(passage["citation"])
            used[citation] = passage
            excerpt = _fallback_excerpt(str(passage.get("text", "")))
            body.append(f"### Source excerpt {index}\n\n> {excerpt}\n\n{citation}")
        if not body:
            body.append(
                "No admitted passage matched this section. This means the bounded retrieval set "
                "is insufficient; it does not prove the deal room lacks the information."
            )
        sections.append(f"## {heading}\n\n" + "\n\n".join(body))
    sections.extend([
        "## Missing or conflicting information\n\n"
        "This fallback does not infer missing facts or resolve conflicts. It contains only the "
        "bounded excerpts shown above. A human must inspect the cited source passages and the "
        "rest of the authorized folder before treating an omission as real.",
        "## Next review questions\n\n"
        "1. Which transaction parties, approvals, and closing conditions are explicitly disclosed?\n"
        "2. Which valuation and leverage definitions are stated, and which would require calculation?\n"
        "3. Which financial values conflict across source documents or periods?\n"
        "4. Which material risks require documents outside the admitted excerpts?",
    ])
    markdown = "\n\n".join(sections)
    return EvidenceFallbackResult(
        markdown=markdown,
        recommendation="pause",
        provider="prism_evidence_renderer",
        model="deterministic_source_excerpt_v2",
        latency_ms=0.0,
        usage={"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        citations=sorted(used),
        retrieved_passages=[used[citation] for citation in sorted(used)],
        raw_metadata={
            "artifact_mode": "evidence_safe_fallback",
            "authored_by": "deterministic_evidence_renderer",
            "model_failure_trace_id": model_failure_trace_id,
            "fallback_guard": EVIDENCE_FALLBACK_GUARD_VERSION,
            "investment_screen_retrieval": "screen_bound_v1",
            "investment_screen_passage_count": len(screen_passages),
        },
    )


def retrieve_first_pass_evidence(
    folder: str | Path,
    limit: int = 14,
    investment_screen: str | None = None,
) -> list[dict[str, Any]]:
    """Retrieve a bounded set that reserves evidence for the operator's screen."""
    resolved = Path(folder).resolve(strict=True)
    selected: dict[tuple[str, str], dict[str, Any]] = {}
    screen_keys: set[tuple[str, str]] = set()

    def collect(request: str, reason: str, per_query_limit: int) -> None:
        for passage in query_deal_room(resolved, request, limit=per_query_limit):
            if str(passage.get("source_anchor", "")).startswith("node:root_"):
                continue
            key = (passage["filename"], passage["source_anchor"])
            previous = selected.get(key)
            if previous is None:
                selected[key] = {**passage, "retrieval_reasons": [reason]}
            else:
                reasons = set(previous.get("retrieval_reasons", []))
                reasons.add(reason)
                if passage["score"] > previous["score"]:
                    selected[key] = {**passage, "retrieval_reasons": sorted(reasons)}
                else:
                    previous["retrieval_reasons"] = sorted(reasons)
            if reason == "investment_screen":
                screen_keys.add(key)

    screen = (investment_screen or "").strip()
    if screen:
        collect(screen, "investment_screen", min(6, limit))
    for index, request in enumerate(SEARCH_QUERIES, start=1):
        collect(request, f"underwriting_topic_{index}", 4)

    ranked = sorted(
        selected.values(),
        key=lambda item: (-float(item["score"]), item["filename"], item["source_anchor"]),
    )
    # A high-frequency generic topic must not crowd the user's stated screen
    # out of the bounded model context. Reserve up to four slots, then fill the
    # remainder by the ordinary cross-topic rank.
    screen_ranked = [
        passage for passage in ranked
        if (passage["filename"], passage["source_anchor"]) in screen_keys
    ][:min(4, limit)]
    reserved = {
        (passage["filename"], passage["source_anchor"])
        for passage in screen_ranked
    }
    return (screen_ranked + [
        passage for passage in ranked
        if (passage["filename"], passage["source_anchor"]) not in reserved
    ])[:limit]


def _extract_recommendation(markdown: str) -> str | None:
    match = re.search(r"\bRecommendation\s*:\s*(ADVANCE|PAUSE|STOP)\b", markdown, re.I)
    return match.group(1).lower() if match else None


def _validate_draft(markdown: str, admitted_citations: set[str]) -> tuple[str, list[str]]:
    missing_headings = [
        heading for heading in REQUIRED_HEADINGS
        if not re.search(rf"^##\s+{re.escape(heading)}\s*$", markdown, re.I | re.M)
    ]
    if missing_headings:
        raise FirstPassError(
            "Bonsai omitted required first pass sections: " + ", ".join(missing_headings)
        )
    recommendation = _extract_recommendation(markdown)
    if recommendation is None:
        raise FirstPassError("Bonsai did not return an ADVANCE, PAUSE, or STOP recommendation")
    used = sorted(citation for citation in admitted_citations if citation in markdown)
    if not used:
        raise FirstPassError("Bonsai returned a first pass draft without an admitted citation")
    return recommendation, used


def _normalized(value: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", value.lower().replace("_", " ")))


def _pipe_table(text: str) -> tuple[list[str], list[tuple[str, list[str]]]] | None:
    """Recover the simple row/column relation from a flattened Markdown table."""
    cells = [cell.strip() for cell in text.split("|") if cell.strip()]
    header_start = next(
        (index for index, cell in enumerate(cells) if _normalized(cell) in {"line item usd m", "line item"}),
        None,
    )
    if header_start is None:
        return None
    years = []
    cursor = header_start + 1
    while cursor < len(cells) and YEAR_TOKEN.match(cells[cursor]):
        years.append(cells[cursor])
        cursor += 1
    width = len(years) + 1
    if not years or cursor + width > len(cells):
        return None
    if all(set(cell.replace(" ", "")) <= {"-", ":"} for cell in cells[cursor:cursor + width]):
        cursor += width
    rows = []
    while cursor + width <= len(cells):
        row = cells[cursor:cursor + width]
        rows.append((row[0], row[1:]))
        cursor += width
    return years, rows


def numeric_relation_issues(markdown: str, passages: list[dict[str, Any]]) -> list[str]:
    """Find year/value claims that contradict their cited flattened source table."""
    issues: list[str] = []
    cited_tables = {
        passage["citation"]: _pipe_table(str(passage.get("text", "")))
        for passage in passages
        if passage.get("citation") and "|" in str(passage.get("text", ""))
    }
    for sentence in re.split(r"(?<=[.!?])\s+|\n+", markdown):
        sentence_citations = [citation for citation in cited_tables if citation in sentence]
        if not sentence_citations:
            continue
        relation_text = re.sub(r"\[[^\]\n]+#[^\]\n]+\]", "", sentence)
        for citation in sentence_citations:
            table = cited_tables[citation]
            if table is None:
                continue
            years, rows = table
            candidates = []
            for label, values in rows:
                tokens = re.findall(r"[a-z0-9]+", label.lower())
                if not tokens:
                    continue
                variants = [tokens]
                if "yoy" in tokens:
                    variants.append([token for token in tokens if token != "yoy"])
                matches = []
                for variant in variants:
                    pattern = re.compile(
                        r"\b" + r"[\s_-]+".join(map(re.escape, variant)) + r"\b",
                        re.I,
                    )
                    match = pattern.search(relation_text)
                    if match:
                        matches.append(match)
                if matches:
                    match = min(matches, key=lambda item: item.start())
                    candidates.append((match.start(), match.end(), len(tokens), label, values))
            if not candidates:
                continue
            # Prefer the most specific row label when labels overlap at one position,
            # such as Revenue and Revenue_YoY_Growth.
            by_start = {}
            for candidate in candidates:
                previous = by_start.get(candidate[0])
                if previous is None or candidate[2] > previous[2]:
                    by_start[candidate[0]] = candidate
            ordered = sorted(by_start.values(), key=lambda candidate: candidate[0])
            year_positions = {_normalized(year): index for index, year in enumerate(years)}
            for candidate_index, (start, _end, _specificity, label, values) in enumerate(ordered):
                clause_end = (
                    ordered[candidate_index + 1][0]
                    if candidate_index + 1 < len(ordered)
                    else len(relation_text)
                )
                clause = relation_text[start:clause_end]
                pairs = {
                    (_normalized(match.group("year")), float(match.group("value").replace(",", "")))
                    for pattern in (VALUE_BEFORE_YEAR, YEAR_BEFORE_VALUE)
                    for match in pattern.finditer(clause)
                }
                for year, observed in pairs:
                    if year not in year_positions:
                        continue
                    expected_cell = values[year_positions[year]]
                    expected_numbers = [
                        float(value.replace(",", ""))
                        for value in re.findall(r"\d[\d,]*(?:\.\d+)?", expected_cell)
                    ]
                    if expected_numbers and not any(
                        abs(observed - expected) <= 1e-6 for expected in expected_numbers
                    ):
                        issues.append(
                            f"{label}: {year} was paired with {observed:g}, but "
                            f"{citation} records {expected_cell}"
                        )
    return sorted(set(issues))


def evidence_claim_issues(markdown: str, passages: list[dict[str, Any]]) -> list[str]:
    """Reject malformed citations, false arithmetic, and unsupported approval claims."""
    issues: list[str] = []
    if re.search(r"\[\s*SOURCE\s+\[", markdown, re.I):
        issues.append("Citations must use exact [filename#anchor] markup without a SOURCE wrapper")

    for match in YOY_GROWTH_CLAIM.finditer(markdown):
        start = float(match.group("start").replace(",", ""))
        end = float(match.group("end").replace(",", ""))
        claimed = float(match.group("growth_before") or match.group("growth_after"))
        if start == 0:
            issues.append("YoY growth cannot be verified from a zero starting value")
            continue
        expected = (end / start - 1.0) * 100.0
        if abs(claimed - expected) > 0.15:
            issues.append(
                f"{match.group('start_year')} to {match.group('end_year')} YoY growth was "
                f"stated as {claimed:g}%, but {start:g} to {end:g} implies {expected:.1f}%"
            )

    for match in LEVERAGE_CALC_CLAIM.finditer(markdown):
        stated = float(match.group("multiple"))
        numerator = float(match.group("numerator").replace(",", ""))
        denominator = float(match.group("denominator").replace(",", ""))
        if denominator == 0:
            issues.append("A stated leverage calculation divides by zero")
            continue
        implied = numerator / denominator
        if abs(stated - implied) > 0.05:
            issues.append(
                f"The stated {stated:g}x leverage calculation uses {numerator:g} divided by "
                f"{denominator:g}, which implies {implied:.2f}x"
            )

    passage_by_citation = {
        str(passage.get("citation")): "\n".join(
            value for value in (
                str(passage.get("text", "")),
                str(passage.get("parser_disclosure", "")),
            ) if value
        ).lower()
        for passage in passages if passage.get("citation")
    }
    for target in re.finditer(
        r"transaction\s+involves\s+(?P<name>.+?)\s+as\s+the\s+target[^\n]*?"
        r"(?P<citation>\[[^\]\n]+#[^\]\n]+\])",
        markdown,
        re.I,
    ):
        cited_text = passage_by_citation.get(target.group("citation"), "")
        if _normalized(target.group("name")) not in _normalized(cited_text):
            issues.append("The named target is not supported by the source passage cited in its sentence")
    for sentence in re.split(r"(?<=[.!?])\s+|\n+", markdown):
        lowered = sentence.lower()
        if (
            re.search(r"\d", sentence)
            and not sentence.lstrip().startswith("#")
            and not sentence.rstrip().endswith("?")
            and not any(citation in sentence for citation in passage_by_citation)
        ):
            issues.append("A numeric factual claim has no admitted citation in its sentence")
        cited_text = " ".join(
            text for citation, text in passage_by_citation.items() if citation in sentence
        )
        spreadsheet_cited = any(
            passage.get("citation") in sentence
            and "XLSX" in str(passage.get("parser_disclosure") or "")
            for passage in passages
        )
        if spreadsheet_cited and not (
            "cached" in lowered and "not recalculat" in lowered
        ):
            issues.append(
                "An XLSX-derived claim does not disclose cached, non-recalculated formula state"
            )
        ocr_cited = any(
            passage.get("citation") in sentence
            and "OCR" in str(passage.get("parser_disclosure") or "")
            for passage in passages
        )
        if ocr_cited and not (
            "ocr" in lowered
            and "wrong" in lowered
            and ("layout" in lowered or "table" in lowered)
        ):
            issues.append("An OCR-derived claim does not disclose OCR error and layout limits")
        if not re.search(
            r"\b(?:requires?\s+approval|subject\s+to\s+approval|"
            r"approval\s+(?:from|by|of)|shareholder\s+approval)\b",
            lowered,
        ):
            continue
        if not cited_text or "approval" not in cited_text:
            issues.append(
                "An approval claim is not supported by the source passage cited in its sentence"
            )
        elif "shareholder" in lowered and "shareholder" not in cited_text:
            issues.append(
                "A shareholder-approval claim is not supported by the source passage cited in its sentence"
            )
    return sorted(set(issues))


def generate_first_pass(
    folder: str | Path,
    investment_screen: str,
    provider: OpenAICompatibleProvider,
    evidence_limit: int = 14,
) -> FirstPassResult:
    """Generate one reviewable first pass draft from bounded local evidence."""
    if not provider.configured:
        raise FirstPassError("The local Bonsai provider is not configured")
    screen = investment_screen.strip()
    if not screen:
        raise FirstPassError("An investment screen is required")
    if len(screen) > 8_000:
        raise FirstPassError("The investment screen exceeds 8,000 characters")

    passages = retrieve_first_pass_evidence(
        folder, limit=evidence_limit, investment_screen=screen,
    )
    if not passages:
        raise FirstPassError("No source passage matched the first pass evidence queries")
    evidence = "\n\n".join(
        f"CITATION_TOKEN {item['citation']} ROLE={item.get('source_role', 'primary_source')}\n"
        + (f"PARSER_DISCLOSURE {item['parser_disclosure']}\n" if item.get("parser_disclosure") else "")
        + f"{item['text']}"
        for item in passages
    )
    headings = "\n".join(f"## {heading}" for heading in REQUIRED_HEADINGS)
    messages = [
        {
            "role": "system",
            "content": (
                "You prepare a first pass M&A underwriting draft for human review. Use only the "
                "admitted source passages. Cite every material factual claim by copying only the exact "
                "CITATION_TOKEN value after the claim, such as [file#anchor]. Never prefix or wrap a "
                "citation with SOURCE. Never treat a transaction valuation multiple as a debt "
                "multiple. Report a disclosed leverage ratio as a sourced fact; do not invent or "
                "reverse-engineer its formula unless the cited passage explicitly provides that formula. "
                "When PARSER_DISCLOSURE says a spreadsheet formula was not recalculated, treat its "
                "value as cached source state and state that limit if the value affects the recommendation. "
                "When PARSER_DISCLOSURE identifies OCR text, state that OCR text and reading order "
                "may be wrong and that tables and layout were not reconstructed. "
                "Never infer a missing number. Do not use filename-only or section-title passages as "
                "factual support. Name all disclosed parties. When evidence "
                "is absent or conflicting, say so. Do not assert an approval requirement unless the "
                "cited passage explicitly states it. Do not claim there are no conflicts unless you "
                "have compared the cited values. Recalculate every stated growth rate from its endpoints. "
                "Separate source facts, calculations, inferences, "
                "and unknowns. Return Markdown with every required heading exactly once. Under the "
                "Recommendation heading, begin with exactly one of Recommendation: ADVANCE, "
                "Recommendation: PAUSE, or Recommendation: STOP. Keep the draft under 1,200 words."
            ),
        },
        {
            "role": "user",
            "content": (
                f"INVESTMENT SCREEN\n{screen}\n\nREQUIRED HEADINGS\n{headings}\n\n"
                f"ADMITTED SOURCE PASSAGES\n{evidence}"
            ),
        },
    ]
    try:
        generated = provider.complete(messages, temperature=0.0)
    except ProviderError as exc:
        raise FirstPassError(str(exc)) from exc

    admitted = {item["citation"] for item in passages}
    markdown = generated.content.strip()
    recommendation, citations = _validate_draft(markdown, admitted)
    relation_issues = numeric_relation_issues(markdown, passages)
    claim_issues = evidence_claim_issues(markdown, passages)
    guard_issues = sorted(set(relation_issues + claim_issues))
    repair_attempted = False
    if guard_issues:
        repair_attempted = True
        initial_generated = generated
        correction = {
            "role": "user",
            "content": (
                "The deterministic evidence guard rejected these claims:\n- "
                + "\n- ".join(guard_issues)
                + "\nReturn the complete corrected draft with the same required headings and citations."
            ),
        }
        previous_response_id = None
        if getattr(provider, "supports_previous_response_id", False):
            candidate = generated.raw_metadata.get("request_id")
            if isinstance(candidate, str) and candidate.strip():
                previous_response_id = candidate.strip()
        if previous_response_id:
            # LM Studio already has the original turn. Send only the correction and
            # system contract so the rejected answer is not duplicated as user text.
            repair_messages = [messages[0], correction]
        else:
            # The native adapter serializes these role labels explicitly when the
            # local endpoint is configured not to retain response state.
            repair_messages = messages + [
                {"role": "assistant", "content": markdown},
                correction,
            ]
        try:
            repaired = provider.complete(
                repair_messages,
                temperature=0.0,
                previous_response_id=previous_response_id,
            )
        except ProviderError as exc:
            raise FirstPassError(
                f"Bonsai repair attempt failed: {exc}",
                metadata={
                    "first_pass_repair_attempted": True,
                    "first_pass_initial_relation_issues": relation_issues,
                    "first_pass_initial_guard_issues": guard_issues,
                    "provider_id": generated.provider_id,
                    "model": generated.model,
                    "latency_ms": generated.latency_ms,
                    "usage": generated.usage,
                },
            ) from exc
        markdown = repaired.content.strip()
        recommendation, citations = _validate_draft(markdown, admitted)
        remaining_relation_issues = numeric_relation_issues(markdown, passages)
        remaining_claim_issues = evidence_claim_issues(markdown, passages)
        remaining_issues = sorted(set(remaining_relation_issues + remaining_claim_issues))
        if remaining_issues:
            raise FirstPassError(
                "Bonsai failed the deterministic evidence guard after one repair: "
                + "; ".join(remaining_issues),
                metadata={
                    "first_pass_repair_attempted": True,
                    "first_pass_initial_relation_issues": relation_issues,
                    "first_pass_initial_guard_issues": guard_issues,
                    "first_pass_remaining_relation_issues": remaining_relation_issues,
                    "first_pass_remaining_guard_issues": remaining_issues,
                    "first_pass_repair_transport": (
                        "previous_response_id" if previous_response_id else "explicit_role_transcript"
                    ),
                    "provider_id": repaired.provider_id,
                    "model": repaired.model,
                    "latency_ms": generated.latency_ms + repaired.latency_ms,
                    "usage": {
                        key: generated.usage.get(key, 0) + repaired.usage.get(key, 0)
                        for key in set(generated.usage) | set(repaired.usage)
                    },
                    **repaired.raw_metadata,
                },
            )
        repaired.latency_ms += initial_generated.latency_ms
        repaired.usage = {
            key: initial_generated.usage.get(key, 0) + repaired.usage.get(key, 0)
            for key in set(initial_generated.usage) | set(repaired.usage)
        }
        repaired.raw_metadata = {
            **repaired.raw_metadata,
            "first_pass_repair_attempted": True,
            "first_pass_initial_relation_issues": relation_issues,
            "first_pass_initial_guard_issues": guard_issues,
            "first_pass_repair_transport": (
                "previous_response_id" if previous_response_id else "explicit_role_transcript"
            ),
        }
        generated = repaired
    return FirstPassResult(
        markdown=markdown,
        recommendation=recommendation,
        provider=generated.provider_id,
        model=generated.model,
        latency_ms=generated.latency_ms,
        usage=generated.usage,
        citations=citations,
        retrieved_passages=passages,
        raw_metadata={
            **generated.raw_metadata,
            "first_pass_repair_attempted": repair_attempted,
            "numeric_relation_guard": "passed",
            "evidence_claim_guard": "passed",
            "investment_screen_retrieval": "screen_bound_v1",
            "investment_screen_passage_count": sum(
                "investment_screen" in passage.get("retrieval_reasons", [])
                for passage in passages
            ),
        },
    )
