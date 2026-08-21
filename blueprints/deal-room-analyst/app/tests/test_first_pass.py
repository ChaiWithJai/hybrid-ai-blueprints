import tempfile
import unittest
from pathlib import Path
from unittest import mock

from core.ai_provider import ProviderResult
from core.first_pass import (
    EVIDENCE_FALLBACK_GUARD_VERSION,
    FirstPassError,
    REQUIRED_HEADINGS,
    build_evidence_safe_fallback,
    evidence_claim_issues,
    generate_first_pass,
    numeric_relation_issues,
    retrieve_first_pass_evidence,
    restore_signed_first_pass,
)


class _ConfiguredProvider:
    configured = True

    def __init__(self, content):
        self.content = content
        self.messages = None
        self.previous_response_id = None

    @property
    def supports_previous_response_id(self):
        return False

    def complete(self, messages, temperature=0.0, previous_response_id=None):
        self.messages = messages
        self.previous_response_id = previous_response_id
        return ProviderResult(
            provider_id="local_bonsai",
            model="27b@q1_0",
            content=self.content,
            latency_ms=42.0,
            usage={"total_tokens": 25},
            raw_metadata={"reasoning_disabled": True},
        )


class _SequenceProvider(_ConfiguredProvider):
    def __init__(self, contents):
        super().__init__(contents[0])
        self.contents = list(contents)
        self.calls = 0
        self.call_arguments = []

    def complete(self, messages, temperature=0.0, previous_response_id=None):
        self.content = self.contents[self.calls]
        self.calls += 1
        self.call_arguments.append((messages, previous_response_id))
        return super().complete(messages, temperature, previous_response_id)


def _draft(citation="[merger.html#section:terms]"):
    sections = []
    for heading in REQUIRED_HEADINGS:
        body = "Recommendation: PAUSE" if heading == "Recommendation" else f"Evidence is incomplete {citation}"
        sections.append(f"## {heading}\n\n{body}")
    return "\n\n".join(sections)


TABLE_CITATION = "[model.csv#node:table]"
TABLE_PASSAGE = {
    "filename": "model.csv",
    "source_anchor": "node:table",
    "citation": TABLE_CITATION,
    "score": 5.0,
    "source_role": "primary_source",
    "text": (
        "Financial Ledger | Line_Item_USD_M | 2024A | 2028E_LBO_Y3 | 2030E_LBO_Y5 | "
        "--- | --- | --- | --- | Adjusted_EBITDA | 150.0 | 375.8 | 512.3 | "
        "Gross_Margin | 70.0% | 75.0% | 76.0%"
    ),
}


def _financial_draft(financial_sentence):
    sections = []
    for heading in REQUIRED_HEADINGS:
        if heading == "Recommendation":
            body = "Recommendation: PAUSE"
        elif heading == "Financial quality":
            body = financial_sentence
        else:
            body = f"Evidence is incomplete {TABLE_CITATION}"
        sections.append(f"## {heading}\n\n{body}")
    return "\n\n".join(sections)


class FirstPassTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.folder = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_nested_room_routes_use_root_relative_assets(self):
        html = (Path(__file__).parents[1] / "web" / "index.html").read_text()
        self.assertIn('href="/style.css?', html)
        self.assertIn('src="/app.js?', html)

    def test_signed_draft_guard_version_controls_reviewability(self):
        body = "# First pass underwriting draft\n\n" + _draft()
        legacy = restore_signed_first_pass(
            "<!-- prism:first-pass-draft model=27b@q1_0 recommendation=pause -->\n" + body
        )
        current = restore_signed_first_pass(
            "<!-- prism:first-pass-draft model=27b@q1_0 recommendation=pause "
            "guard=evidence_claim_v7 trace=trc_current "
            "source_class=synthetic_engineering_fixture "
            f"provenance={'c' * 64} source_snapshot={'d' * 64} -->\n" + body
        )

        self.assertEqual(legacy["acceptance_state"], "legacy_unverified")
        self.assertIsNone(legacy["guard_version"])
        self.assertEqual(current["acceptance_state"], "accepted")
        self.assertEqual(current["guard_version"], "evidence_claim_v7")
        self.assertEqual(current["trace_id"], "trc_current")

        unbound_current = restore_signed_first_pass(
            "<!-- prism:first-pass-draft model=27b@q1_0 recommendation=pause "
            "guard=evidence_claim_v7 trace=trc_unbound -->\n" + body
        )
        self.assertEqual(unbound_current["acceptance_state"], "legacy_unverified")

        fallback_body = "# Evidence-safe first pass fallback\n\n" + _draft()
        fallback = restore_signed_first_pass(
            "<!-- prism:first-pass-draft model=deterministic_source_excerpt_v2 "
            "recommendation=pause guard=source_excerpt_v2 mode=evidence_safe_fallback "
            "trace=trc_fallback model_failure_trace=trc_failed "
            "source_class=synthetic_engineering_fixture "
            f"provenance={'c' * 64} source_snapshot={'d' * 64} -->\n" + fallback_body
        )
        self.assertEqual(fallback["acceptance_state"], "evidence_safe_fallback")
        self.assertEqual(fallback["guard_version"], EVIDENCE_FALLBACK_GUARD_VERSION)
        self.assertEqual(fallback["trace_id"], "trc_fallback")
        self.assertEqual(fallback["model_failure_trace_id"], "trc_failed")
        self.assertEqual(fallback["authored_by"], "deterministic_evidence_renderer")

    def test_evidence_fallback_uses_source_excerpts_not_rejected_model_prose(self):
        passages = [
            {
                **TABLE_PASSAGE,
                "text": (
                    "The transaction uses $900.0M of first lien debt. Revenue is $520.0M. "
                    "The borrower is subject to a leverage covenant."
                ),
            }
        ]
        result = build_evidence_safe_fallback(passages, "trc_rejected")

        self.assertEqual(result.recommendation, "pause")
        self.assertEqual(result.provider, "prism_evidence_renderer")
        self.assertEqual(result.usage["total_tokens"], 0)
        self.assertIn(passages[0]["text"], result.markdown)
        self.assertIn(TABLE_CITATION, result.markdown)
        self.assertIn("system safety disposition, not a model recommendation", result.markdown)
        self.assertNotIn("trc_rejected", result.markdown)
        self.assertEqual(result.raw_metadata["model_failure_trace_id"], "trc_rejected")

    def test_evidence_fallback_surfaces_screen_matched_source_before_generic_sections(self):
        screen_passage = {
            **TABLE_PASSAGE,
            "citation": "[commercial.md#node:customer]",
            "filename": "commercial.md",
            "source_anchor": "node:customer",
            "text": "Acme contributes thirty-four percent of annual recurring value.",
            "retrieval_reasons": ["investment_screen"],
        }
        result = build_evidence_safe_fallback(
            [screen_passage, TABLE_PASSAGE],
            "trc_rejected",
            investment_screen="Assess Acme renewal exposure.",
        )

        self.assertIn("## Investment screen evidence", result.markdown)
        self.assertIn(screen_passage["text"], result.markdown)
        self.assertEqual(result.raw_metadata["investment_screen_passage_count"], 1)

    @mock.patch("core.first_pass.query_deal_room")
    def test_generates_bounded_cited_draft(self, query):
        query.return_value = [{
            "filename": "merger.html",
            "source_anchor": "section:terms",
            "citation": "[merger.html#section:terms]",
            "score": 3.0,
            "text": "The merger agreement discloses the consideration.",
            "source_role": "primary_source",
        }]
        provider = _ConfiguredProvider(_draft())

        result = generate_first_pass(self.folder, "Decide whether to advance.", provider)

        self.assertEqual(result.recommendation, "pause")
        self.assertEqual(result.citations, ["[merger.html#section:terms]"])
        self.assertEqual(len(result.retrieved_passages), 1)
        self.assertEqual(query.call_count, 6)
        self.assertEqual(provider.messages[1]["role"], "user")
        self.assertIn("ADMITTED SOURCE PASSAGES", provider.messages[1]["content"])
        self.assertEqual(result.raw_metadata["investment_screen_retrieval"], "screen_bound_v1")

    @mock.patch("core.first_pass.query_deal_room")
    def test_investment_screen_reserves_matching_evidence_in_bounded_context(self, query):
        screen = "Assess customer concentration and the Acme renewal risk."
        screen_passage = {
            "filename": "commercial/customer-risk.md",
            "source_anchor": "node:renewal",
            "citation": "[commercial/customer-risk.md#node:renewal]",
            "score": 1.0,
            "text": "Acme represents 34% of revenue and renews next quarter.",
        }
        generic_passages = [{
            "filename": f"generic-{index}.md",
            "source_anchor": "node:terms",
            "citation": f"[generic-{index}.md#node:terms]",
            "score": 100.0 - index,
            "text": "Generic transaction financing terms.",
        } for index in range(8)]
        query.side_effect = lambda _folder, request, limit: (
            [screen_passage] if request == screen else generic_passages[:limit]
        )

        passages = retrieve_first_pass_evidence(
            self.folder, limit=3, investment_screen=screen,
        )

        self.assertEqual(passages[0]["citation"], screen_passage["citation"])
        self.assertIn("investment_screen", passages[0]["retrieval_reasons"])
        self.assertEqual(len(passages), 3)
        query.assert_any_call(self.folder.resolve(), screen, limit=3)

    @mock.patch("core.first_pass.query_deal_room")
    def test_rejects_structurally_incomplete_model_output(self, query):
        query.return_value = [{
            "filename": "merger.html",
            "source_anchor": "section:terms",
            "citation": "[merger.html#section:terms]",
            "score": 3.0,
            "text": "The merger agreement discloses the consideration.",
        }]
        provider = _ConfiguredProvider("## Recommendation\n\nRecommendation: ADVANCE [merger.html#section:terms]")

        with self.assertRaisesRegex(FirstPassError, "omitted required"):
            generate_first_pass(self.folder, "Decide whether to advance.", provider)

    @mock.patch("core.first_pass.query_deal_room", return_value=[])
    def test_rejects_empty_retrieval_without_invoking_model(self, _query):
        provider = _ConfiguredProvider(_draft())

        with self.assertRaisesRegex(FirstPassError, "No source passage"):
            generate_first_pass(self.folder, "Decide whether to advance.", provider)
        self.assertIsNone(provider.messages)

    def test_detects_live_year_value_relation_failure(self):
        draft = _financial_draft(
            "Adjusted EBITDA grows from $150.0M in 2024A to $512.3M by "
            f"2028E_LBO_Y3 {TABLE_CITATION}. Gross Margin rises from 70.0% in "
            f"2024A to 76.0% by 2028E_LBO_Y3 {TABLE_CITATION}."
        )

        issues = numeric_relation_issues(draft, [TABLE_PASSAGE])

        self.assertTrue(any("Adjusted_EBITDA" in issue and "375.8" in issue for issue in issues))
        self.assertTrue(any("Gross_Margin" in issue and "75.0%" in issue for issue in issues))

    def test_numeric_relation_guard_scopes_pairs_to_each_metric_clause(self):
        draft = _financial_draft(
            "Revenue YoY Growth declines from 22.0% in 2024A to 12.0% in 2030E_LBO_Y5, "
            "while EBITDA Margin expands from 35.9% in 2024A to 47.0% in "
            f"2030E_LBO_Y5 {TABLE_CITATION}."
        )
        self.assertEqual(numeric_relation_issues(draft, [TABLE_PASSAGE]), [])
        natural_alias = draft.replace("Revenue YoY Growth", "Revenue Growth")
        self.assertEqual(numeric_relation_issues(natural_alias, [TABLE_PASSAGE]), [])

    def test_detects_live_yoy_arithmetic_and_unsupported_approval(self):
        draft = _financial_draft(
            "Revenue grows from $418.0M in 2024A to $520.0M in 2025A, representing "
            f"22.0% YoY growth {TABLE_CITATION}. The transaction requires shareholder "
            f"approval {TABLE_CITATION}."
        )

        issues = evidence_claim_issues(draft, [TABLE_PASSAGE])

        self.assertTrue(any("implies 24.4%" in issue for issue in issues))
        self.assertTrue(any("approval claim" in issue for issue in issues))

        alternate = _financial_draft(
            "Revenue grows from $418.0M in 2024A to $520.0M in 2025A, representing "
            f"a YoY growth rate of 22.0% {TABLE_CITATION}."
        )
        self.assertTrue(any(
            "implies 24.4%" in issue for issue in evidence_claim_issues(alternate, [TABLE_PASSAGE])
        ))

    def test_detects_uncited_numbers_and_false_leverage_calculation(self):
        passage = {
            **TABLE_PASSAGE,
            "text": TABLE_PASSAGE["text"] + " Total Sources $2,400.0; gross leverage 7.20x.",
        }
        draft = _financial_draft(
            "Gross leverage multiple is 7.20x, calculated as Total Sources ($2,400.0M) "
            f"divided by projected exit EBITDA of $375.8M {TABLE_CITATION}. "
            "Net leverage is 6.00x based on a negative $881.7M denominator."
        )
        issues = evidence_claim_issues(draft, [passage])
        self.assertTrue(any("implies 6.39x" in issue for issue in issues))
        self.assertTrue(any("no admitted citation" in issue for issue in issues))

    def test_detects_source_wrapped_citation_markup(self):
        issues = evidence_claim_issues(
            _draft(f"[SOURCE {TABLE_CITATION}]"),
            [TABLE_PASSAGE],
        )
        self.assertTrue(any("SOURCE wrapper" in issue for issue in issues))

    def test_detects_target_name_cited_only_to_a_filename_node(self):
        citation = "[cim.md#node:root_cim.md]"
        passage = {**TABLE_PASSAGE, "citation": citation, "text": "cim.md"}
        issues = evidence_claim_issues(
            _draft(citation).replace(
                "Evidence is incomplete " + citation,
                "The transaction involves CloudScale Networks Inc. as the target entity " + citation,
                1,
            ),
            [passage],
        )
        self.assertTrue(any("named target" in issue for issue in issues))

    @mock.patch("core.first_pass.query_deal_room")
    def test_repairs_one_failed_numeric_relation_then_accepts(self, query):
        query.return_value = [TABLE_PASSAGE]
        bad = _financial_draft(
            f"Adjusted EBITDA grows to $512.3M by 2028E_LBO_Y3 {TABLE_CITATION}."
        )
        corrected = _financial_draft(
            f"Adjusted EBITDA grows to $375.8M by 2028E_LBO_Y3 {TABLE_CITATION}."
        )
        provider = _SequenceProvider([bad, corrected])

        result = generate_first_pass(self.folder, "Decide whether to advance.", provider)

        self.assertEqual(provider.calls, 2)
        roles = [message["role"] for message in provider.call_arguments[1][0]]
        self.assertEqual(roles, ["system", "user", "assistant", "user"])
        self.assertIsNone(provider.call_arguments[1][1])
        self.assertIn("$375.8M", result.markdown)
        self.assertTrue(result.raw_metadata["first_pass_repair_attempted"])
        self.assertEqual(
            result.raw_metadata["first_pass_repair_transport"],
            "explicit_role_transcript",
        )
        self.assertEqual(result.raw_metadata["numeric_relation_guard"], "passed")

    @mock.patch("core.first_pass.query_deal_room")
    def test_stateful_repair_sends_only_correction_after_response_id(self, query):
        query.return_value = [TABLE_PASSAGE]
        bad = _financial_draft(
            f"Adjusted EBITDA grows to $512.3M by 2028E_LBO_Y3 {TABLE_CITATION}."
        )
        corrected = _financial_draft(
            f"Adjusted EBITDA grows to $375.8M by 2028E_LBO_Y3 {TABLE_CITATION}."
        )

        class StatefulProvider(_SequenceProvider):
            @property
            def supports_previous_response_id(self):
                return True

            def complete(self, messages, temperature=0.0, previous_response_id=None):
                result = super().complete(messages, temperature, previous_response_id)
                if self.calls == 1:
                    result.raw_metadata["request_id"] = "resp-first"
                return result

        provider = StatefulProvider([bad, corrected])
        result = generate_first_pass(self.folder, "Decide whether to advance.", provider)

        roles = [message["role"] for message in provider.call_arguments[1][0]]
        self.assertEqual(roles, ["system", "user"])
        self.assertEqual(provider.call_arguments[1][1], "resp-first")
        self.assertEqual(
            result.raw_metadata["first_pass_repair_transport"],
            "previous_response_id",
        )

    @mock.patch("core.first_pass.query_deal_room")
    def test_second_relation_failure_exposes_traceable_metadata(self, query):
        query.return_value = [TABLE_PASSAGE]
        bad = _financial_draft(
            f"Adjusted EBITDA grows to $512.3M by 2028E_LBO_Y3 {TABLE_CITATION}."
        )
        provider = _SequenceProvider([bad, bad])

        with self.assertRaises(FirstPassError) as raised:
            generate_first_pass(self.folder, "Decide whether to advance.", provider)

        metadata = raised.exception.metadata
        self.assertTrue(metadata["first_pass_repair_attempted"])
        self.assertIn("375.8", metadata["first_pass_remaining_relation_issues"][0])
        self.assertEqual(metadata["usage"]["total_tokens"], 50)
        self.assertEqual(metadata["latency_ms"], 84.0)


if __name__ == "__main__":
    unittest.main()
