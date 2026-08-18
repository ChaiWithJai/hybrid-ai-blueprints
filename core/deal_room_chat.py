"""Bounded retrieval and guarded local model answering for Buzz deal rooms."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
import re
from typing import Any, Callable

from core.ai_provider import OpenAICompatibleProvider, ProviderError
from scripts.query_deal_room import query as query_deal_room


class DealRoomChatError(RuntimeError):
    def __init__(self, message: str, metadata: dict[str, Any] | None = None):
        super().__init__(message)
        self.metadata = metadata or {}


DEAL_ROOM_CHAT_GUARD_VERSION = "deal_room_chat_guard_v1"


@dataclass(frozen=True)
class RequestedPart:
    key: str
    label: str
    pattern: re.Pattern[str]
    retrieval_query: str
    evidence_match: Callable[[str], bool]


def _has_all(text: str, *values: str) -> bool:
    lowered = text.lower()
    return all(value in lowered for value in values)


_CAPITAL_STRUCTURE_DEBT_MARKERS = (
    "revolving credit", "term loan", "senior notes", "mezzanine debt",
)

_ABSENCE_POLICY_WORDS = {
    "exact", "entry", "debt", "ebitda", "debt-to-ebitda", "leverage", "multiple", "not",
    "disclosed", "cannot", "calculate", "calculated", "determine",
    "determined", "cited", "evidence", "passage", "alone", "insufficient",
    "provided",
}


_REQUESTED_PARTS: tuple[RequestedPart, ...] = (
    RequestedPart(
        "consideration", "Per-share consideration",
        re.compile(r"\b(per[- ]share|share price|purchase price|merger consideration|consideration)\b", re.I),
        "merger consideration per share cash without interest right receive",
        lambda text: bool(re.search(r"\$\s*\d", text)) and (
            "per share" in text.lower() or "merger consideration" in text.lower()
        ),
    ),
    RequestedPart(
        "closing_conditions", "Closing conditions",
        re.compile(r"\bclosing conditions?\b|\bconditions? to (?:the )?clos(?:e|ing)\b", re.I),
        "conditions each party obligation effect merger fulfillment waiver effective time",
        lambda text: _has_all(text, "condition", "merger") and any(
            marker in text.lower() for marker in (
                "stockholder approval", "hsr act", "cfIUS".lower(),
                "restrains, enjoins", "conditions to each party",
            )
        ),
    ),
    RequestedPart(
        "stockholder_approval", "Stockholder approval",
        re.compile(r"\b(?:stockholder|shareholder)s?\b.{0,40}\bapprovals?\b", re.I),
        "company stockholder approval shall have been obtained",
        lambda text: bool(re.search(
            r"stockholder approval\s+shall\s+have\s+been\s+obtained", text, re.I,
        )),
    ),
    RequestedPart(
        "regulatory_approval", "Regulatory approval",
        re.compile(r"\bregulatory approvals?\b|\bHSR\b|\bCFIUS\b", re.I),
        "HSR CFIUS approval waiting period consents Regulatory Law obtained",
        lambda text: (
            "hsr" in text.lower() or "cfius" in text.lower()
        ) and (
            "waiting period" in text.lower() or "approval" in text.lower()
        ),
    ),
    RequestedPart(
        "financing_condition", "Financing condition",
        re.compile(r"\bfinancing conditions?\b|\bfinancing condition\b", re.I),
        "obligation consummate merger not subject any financing condition",
        lambda text: "financing condition" in text.lower(),
    ),
    RequestedPart(
        "termination_fee", "Termination fee",
        re.compile(r"\b(reverse termination fee|termination fee|break fee)\b", re.I),
        "company termination fee parent reverse termination fee funding",
        lambda text: "reverse termination fee" in text.lower()
        and len(re.findall(r"\$\s*\d", text)) >= 2,
    ),
    RequestedPart(
        "entry_leverage_absence", "Entry debt-to-EBITDA disclosure",
        re.compile(
            r"\b(?:exact\s+)?entry\s+(?:debt(?:[- ]to[- ])?|debt\s*/\s*)ebitda\b"
            r"|\bentry\s+(?:debt[- ]to[- ]ebitda\s+)?leverage\s+multiple\b",
            re.I,
        ),
        "debt commitment preferred equity common equity financing aggregate amount",
        lambda text: _has_all(text, "debt commitment", "preferred equity", "common equity"),
    ),
    RequestedPart(
        "capital_structure", "Debt tranches and amounts",
        re.compile(
            r"\b(debt tranches?|debt stack|capital structure|financing structure|sources of funds)\b",
            re.I,
        ),
        (
            "transaction financing structure sources of funds amount term loan "
            "senior notes mezzanine debt revolving credit facility"
        ),
        lambda text: "sources of funds" in text.lower() and sum(
            marker in text.lower() for marker in _CAPITAL_STRUCTURE_DEBT_MARKERS
        ) >= 2,
    ),
    RequestedPart(
        "financing", "Financing",
        re.compile(r"\b(debt commitment|equity commitment|financing amount|financing sources?)\b", re.I),
        "debt financing equity financing preferred equity commitment aggregate amount",
        lambda text: "financing" in text.lower() and any(
            marker in text.lower() for marker in ("commitment", "term loan", "equity contribution")
        ),
    ),
)


def requested_parts(question: str) -> list[RequestedPart]:
    parts = [part for part in _REQUESTED_PARTS if part.pattern.search(question)]
    if any(part.key == "closing_conditions" for part in parts) and len(parts) > 1:
        parts = [part for part in parts if part.key != "closing_conditions"]
    return parts


def retrieve_deal_room_evidence(
    folder: str | Path,
    question: str,
    limit: int = 8,
    source_filenames: set[str] | None = None,
) -> list[dict[str, Any]]:
    """Retrieve multi-part M&A evidence without inventing query-specific facts.

    The expansion phrases are visible domain vocabulary, not hidden expected
    answers. Each triggered concept receives a separate search so a long prompt
    cannot let one highly repeated topic crowd every other requested part out.
    """
    resolved = Path(folder).resolve(strict=True)
    parts = requested_parts(question)
    per_search = 20
    ranked: list[dict[str, Any]] = []
    positions: dict[tuple[str, str], int] = {}

    for part in parts:
        matches = [
            passage for passage in query_deal_room(
                resolved,
                part.retrieval_query,
                limit=per_search,
                source_filenames=source_filenames,
            )
            if part.evidence_match(passage["text"])
        ]
        if not matches:
            continue
        passage = matches[0]
        key = (passage["filename"], passage["source_anchor"])
        if key in positions:
            ranked[positions[key]]["requested_parts"].append(part.key)
        else:
            positions[key] = len(ranked)
            ranked.append({
                **passage,
                "retrieval_query": part.retrieval_query,
                "requested_parts": [part.key],
            })

    generic = query_deal_room(
        resolved,
        question,
        limit=per_search,
        source_filenames=source_filenames,
    )
    for passage in generic:
        key = (passage["filename"], passage["source_anchor"])
        if key in positions:
            continue
        positions[key] = len(ranked)
        ranked.append({**passage, "retrieval_query": question, "requested_parts": []})
        if len(ranked) >= limit:
            break
    return ranked


@dataclass
class DealRoomChatResult:
    response: str
    provider: str
    model: str
    latency_ms: float
    usage: dict[str, int]
    citations: list[str]
    retrieved_passages: list[dict[str, Any]]
    raw_metadata: dict[str, Any]
    requested_parts: list[str]
    part_citations: dict[str, list[str]]
    guard_version: str
    inference_attempts: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def answer_deal_room_question(
    folder: str | Path,
    question: str,
    provider: OpenAICompatibleProvider,
    limit: int = 8,
) -> DealRoomChatResult:
    if not provider.configured:
        raise DealRoomChatError("The local Bonsai provider is not configured")
    retrieval_question = re.split(r"\b[Cc]ite\b", question, maxsplit=1)[0].strip()
    if retrieval_question.lower().startswith("battletest") and ":" in retrieval_question:
        retrieval_question = retrieval_question.split(":", 1)[1].strip()
    parts = requested_parts(retrieval_question)
    passages = retrieve_deal_room_evidence(folder, retrieval_question, limit=limit)
    if not passages:
        raise DealRoomChatError("No source passage matched the question")
    part_citations = {
        part.key: [
            item["citation"] for item in passages
            if part.key in item.get("requested_parts", [])
        ]
        for part in parts
    }
    missing_evidence = [part.label for part in parts if not part_citations[part.key]]
    if missing_evidence:
        raise DealRoomChatError(
            "No qualifying source passage was retrieved for requested part(s): "
            + ", ".join(missing_evidence)
        )
    evidence = "\n\n".join(
        f"SOURCE {item['citation']} ROLE={item.get('source_role', 'primary_source')} "
        f"PARTS={','.join(item.get('requested_parts', [])) or 'background'}\n{item['text']}"
        + (f"\nPARSER_DISCLOSURE {item['parser_disclosure']}" if item.get("parser_disclosure") else "")
        for item in passages
    )
    part_contract_lines = []
    for part in parts:
        if part.key == "entry_leverage_absence":
            part_contract_lines.append(
                f"- **{part.label}:** use this sentence exactly, then append one source tagged "
                f"PARTS={part.key}: The exact entry debt-to-EBITDA leverage multiple is not "
                "disclosed and cannot be calculated from the cited passage alone."
            )
        elif part.key == "termination_fee":
            part_contract_lines.append(
                f"- **{part.label}:** state both the company termination fee and the reverse "
                f"termination fee with their amounts from one source tagged PARTS={part.key}. "
                "Cite that source once on the same bullet."
            )
        elif part.key == "capital_structure":
            part_contract_lines.append(
                f"- **{part.label}:** list every debt instrument row in the source tagged "
                f"PARTS={part.key}. Include undrawn or zero-funded facilities and any stated "
                "commitment. Exclude equity rows. Cite the table once on the same bullet."
            )
        else:
            part_contract_lines.append(
                f"- **{part.label}:** cite one source tagged PARTS={part.key}"
            )
    part_contract = "\n".join(part_contract_lines) or (
        "- answer: Answer the single question with an admitted citation"
    )
    messages = [
        {
            "role": "system",
            "content": (
                "You answer questions about a private deal folder. Use only the supplied source "
                "passages. Copy the shortest source clause that answers each requested part, with "
                "only light grammar changes. Do not add adjacent facts or explanation. Copy citation "
                "strings exactly after each claim. If the passages do not "
                "provide the answer, say the answer is not disclosed and cite the closest passage. "
                "Do not infer a missing number. Answer every requested part, including named parties. "
                "If a spreadsheet PARSER_DISCLOSURE applies to an answer, state that cached formulas "
                "were not recalculated. If an OCR PARSER_DISCLOSURE applies, state that OCR text and "
                "reading order may be wrong and that tables and layout were not reconstructed. "
                "Write one bullet for each requested part. Start it with the exact human-readable "
                "bold label shown under REQUIRED PARTS. Put its citation on the same bullet. "
                "When a supplemental filing and a primary filing state the same fact, cite the "
                "supplemental filing. Keep a legal term written in full, followed by its acronym if "
                "useful. Return no more than 160 words."
            ),
        },
        {
            "role": "user",
            "content": (
                f"QUESTION\n{question}\n\nREQUIRED PARTS\n{part_contract}"
                f"\n\nADMITTED SOURCE PASSAGES\n{evidence}"
            ),
        },
    ]
    generated = None
    violations: list[str] = []
    for attempt in range(1, 3):
        try:
            generated = provider.complete(messages, temperature=0.0)
        except ProviderError as exc:
            raise DealRoomChatError(str(exc)) from exc
        violations = validate_deal_room_answer(
            generated.content, passages, part_citations, question=question,
        )
        if not violations:
            break
        if attempt == 1:
            messages = [
                messages[0],
                messages[1],
                {"role": "assistant", "content": generated.content},
                {
                    "role": "user",
                    "content": (
                        "The draft failed the publication guard:\n- "
                        + "\n- ".join(violations)
                        + "\nRewrite it. Keep one source-cited bullet per required part."
                    ),
                },
            ]
    if generated is None or violations:
        raise DealRoomChatError(
            "Bonsai answer failed the publication guard: " + "; ".join(violations),
            metadata={
                "rejected_response": generated.content.strip() if generated else "",
                "provider_id": generated.provider_id if generated else provider.provider_id,
                "model": generated.model if generated else provider.model,
                "latency_ms": generated.latency_ms if generated else None,
                "usage": generated.usage if generated else {},
                "inference_attempts": 2 if generated else 0,
                "violations": list(violations),
                "retrieved_anchors": [
                    {
                        "citation": item["citation"],
                        "source_sha256": item.get("source_sha256"),
                        "requested_parts": item.get("requested_parts", []),
                    }
                    for item in passages
                ],
            },
        )
    citations = [item["citation"] for item in passages if item["citation"] in generated.content]
    return DealRoomChatResult(
        response=generated.content.strip(),
        provider=generated.provider_id,
        model=generated.model,
        latency_ms=generated.latency_ms,
        usage=generated.usage,
        citations=citations,
        retrieved_passages=passages,
        raw_metadata=generated.raw_metadata,
        requested_parts=[part.key for part in parts],
        part_citations=part_citations,
        guard_version=DEAL_ROOM_CHAT_GUARD_VERSION,
        inference_attempts=attempt,
    )


def validate_deal_room_answer(
    response: str,
    passages: list[dict[str, Any]],
    part_citations: dict[str, list[str]],
    *,
    question: str = "",
) -> list[str]:
    """Check publication shape and numeric support, not semantic accuracy."""
    admitted = {
        item["citation"]: "\n".join(
            value for value in (item["text"], item.get("parser_disclosure")) if value
        )
        for item in passages
    }
    violations: list[str] = []
    used = [citation for citation in admitted if citation in response]
    if not used:
        return ["no admitted citation appears in the answer"]
    lines = [line.strip() for line in response.splitlines() if line.strip()]
    factual_lines = [line for line in lines if re.search(r"[A-Za-z]", line)]
    function_words = {
        "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
        "must", "and", "or", "of", "to", "for", "from", "in", "on", "at", "by",
        "with", "without", "that", "this", "these", "those", "one", "as", "any",
        "required", "source", "citation", "but",
    }
    def question_word_root(word: str) -> str:
        lowered = word.lower().removesuffix("'s")
        if len(lowered) > 4 and lowered.endswith("ed"):
            return lowered[:-2]
        if len(lowered) > 5 and lowered.endswith("ing"):
            return lowered[:-3]
        return lowered
    question_word_roots = {
        question_word_root(word)
        for word in re.findall(r"[A-Za-z][A-Za-z'-]*", question.lower())
    }
    for line in factual_lines:
        line_citations = [citation for citation in admitted if citation in line]
        if not line_citations:
            violations.append(f"uncited answer line: {line[:80]}")
            continue
        claim = line
        for citation in line_citations:
            claim = claim.replace(citation, "")
        claim_numbers = set(re.findall(r"(?<![A-Za-z])\$?\d[\d,.]*(?:%|\b)", claim))
        support = " ".join(admitted[citation] for citation in line_citations)
        missing_numbers = sorted(number for number in claim_numbers if number not in support)
        if missing_numbers:
            violations.append(
                f"number(s) {', '.join(missing_numbers)} are absent from the cited passage"
            )
        unlabeled_claim = re.sub(
            r"^[*+-]\s*(?:\*\*)?[A-Za-z_ -]+(?:\*\*)?:\s*", "", claim,
        )
        claim_words = {
            word for word in re.findall(r"[A-Za-z][A-Za-z'-]*", unlabeled_claim.lower())
            if len(word) > 2
            and word not in function_words
            and question_word_root(word) not in question_word_roots
        }
        if any(
            part == "entry_leverage_absence" and any(citation in line for citation in citations)
            for part, citations in part_citations.items()
        ):
            claim_words -= _ABSENCE_POLICY_WORDS
        support_words = set(re.findall(r"[A-Za-z][A-Za-z'-]*", support.lower()))
        unsupported_words = sorted(claim_words - support_words)
        if unsupported_words:
            violations.append(
                "material term(s) absent from the cited passage: "
                + ", ".join(unsupported_words[:8])
            )
        disclosure_citations = [
            citation for citation in line_citations
            if next(
                (item.get("parser_disclosure") for item in passages
                 if item.get("citation") == citation),
                None,
            )
        ]
        for citation in disclosure_citations:
            disclosure = next(
                str(item.get("parser_disclosure") or "")
                for item in passages if item.get("citation") == citation
            )
            if "XLSX" in disclosure and not (
                "cached" in line.lower() and "not recalculat" in line.lower()
            ):
                violations.append(
                    "XLSX-derived claim does not disclose cached, non-recalculated formula state"
                )
            if "OCR" in disclosure and not (
                "ocr" in line.lower()
                and "wrong" in line.lower()
                and ("layout" in line.lower() or "table" in line.lower())
            ):
                violations.append(
                    "OCR-derived claim does not disclose OCR error and layout limits"
                )
    for part, citations in part_citations.items():
        matching_lines = [line for line in factual_lines if any(citation in line for citation in citations)]
        if not matching_lines:
            violations.append(f"requested part {part} has no same-line supporting citation")
        elif part == "entry_leverage_absence":
            answer_text = " ".join(matching_lines).lower()
            absence_stated = any(
                marker in answer_text for marker in (
                    "not disclosed", "cannot determine", "cannot be determined",
                    "insufficient evidence", "not provided",
                )
            )
            cannot_calculate = (
                "cannot" in answer_text or "insufficient evidence" in answer_text
            )
            if not absence_stated or not cannot_calculate:
                violations.append(
                    "requested part entry_leverage_absence must refuse the absent exact multiple"
                )
            if re.search(r"\b\d+(?:\.\d+)?\s*x\b", answer_text, re.I):
                violations.append(
                    "requested part entry_leverage_absence invents or substitutes a multiple"
                )
        elif any("not disclosed" in line.lower() for line in matching_lines):
            violations.append(f"requested part {part} contradicts retrieved qualifying evidence")
        elif part == "capital_structure":
            cited_support = " ".join(admitted[citation] for citation in citations).lower()
            answer_text = " ".join(matching_lines).lower()
            missing_instruments = [
                marker for marker in _CAPITAL_STRUCTURE_DEBT_MARKERS
                if marker in cited_support and marker not in answer_text
            ]
            if missing_instruments:
                violations.append(
                    "requested part capital_structure omits source debt instrument(s): "
                    + ", ".join(missing_instruments)
                )
        elif part == "termination_fee":
            cited_support = " ".join(admitted[citation] for citation in citations)
            answer_text = " ".join(matching_lines)
            disclosed_amounts = set(re.findall(r"\$\s*\d[\d,]*(?:\.\d+)?", cited_support))
            missing_amounts = sorted(
                amount for amount in disclosed_amounts if amount not in answer_text
            )
            if missing_amounts:
                violations.append(
                    "requested part termination_fee omits source fee amount(s): "
                    + ", ".join(missing_amounts)
                )
    return list(dict.fromkeys(violations))
