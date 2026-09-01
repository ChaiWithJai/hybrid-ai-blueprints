"""Deterministic tests for demo 06 — no model server required."""

import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.abspath(os.path.join(HERE, "..", "..")))

import app  # noqa: E402
from edgekit import FixtureProvider  # noqa: E402


class RemittanceLedgerTests(unittest.TestCase):
    def setUp(self):
        self.fixture = app.load_fixture()
        self.messages = self.fixture["messages"]

    def _store(self, provider=None):
        provider = provider or FixtureProvider(
            self.fixture["fixture_extractions"])
        return app.make_store(provider, self.fixture), provider

    def test_fixture_run_verdict_keep(self):
        card = app.run("fixture")
        self.assertEqual(card["verdict"], "keep",
                         [g for g in card["gates"] if not g["passed"]])
        self.assertEqual(card["mode"], "fixture")

    def test_digit_attestation(self):
        es_text = self.messages[0]["sourceText"]   # contains 3000
        self.assertTrue(app.amount_attested(300000, es_text))  # 3000 pesos
        self.assertTrue(app.amount_attested(3000, es_text))
        self.assertFalse(app.amount_attested(9999, es_text))
        self.assertFalse(app.amount_attested(0, es_text))
        self.assertFalse(app.amount_attested(None, es_text))
        # Bengali numerals normalize before matching (২০০০ টাকা).
        self.assertTrue(app.amount_attested(200000,
                                            self.messages[2]["sourceText"]))
        # Urdu textual form: پانچ سو = 500 → 50000 minor units.
        self.assertTrue(app.amount_attested(50000,
                                            self.messages[1]["sourceText"]))
        self.assertFalse(app.amount_attested(70000,
                                             self.messages[1]["sourceText"]))

    def test_all_five_clear_messages_extract_as_model(self):
        store, provider = self._store()
        langs = set()
        for msg in self.messages[:5]:
            res = store.create("remittance_records", dict(msg),
                               provider=provider)
            p = res["properties"]
            self.assertEqual(p["extractMode"], "model", msg["sourceRefId"])
            self.assertFalse(p["humanConfirmed"])
            self.assertTrue(app.amount_attested(p["amountMinor"],
                                                p["sourceText"]))
            langs.add(p["lang"])
        self.assertEqual(langs, {"es", "ur", "bn", "fr", "en"})

    def test_unattested_amount_becomes_confirm_needed(self):
        bad = FixtureProvider({"default":
                               "AMOUNT: 9999\nCURRENCY: MXN\n"
                               "CHANNEL: wallet\nPURPOSE: medicinas\n"
                               "CONFIDENCE: 0.95"})
        store, _ = self._store(bad)
        res = store.create("remittance_records", dict(self.messages[0]),
                           provider=bad)
        p = res["properties"]
        self.assertEqual(p["extractMode"], "confirm_needed")
        self.assertIsNone(p["amountMinor"])
        self.assertIsNone(p["currency"])
        self.assertFalse(p["humanConfirmed"])

    def test_vague_message_routes_to_confirm_card(self):
        store, provider = self._store()
        res = store.create("remittance_records", dict(self.messages[5]),
                           provider=provider)
        p = res["properties"]
        self.assertEqual(p["extractMode"], "confirm_needed")
        self.assertIsNone(p["amountMinor"])
        self.assertEqual(p["extractionConfidence"], 0.4)
        self.assertFalse(p["humanConfirmed"])

    def test_confirm_then_recall_flow(self):
        store, provider = self._store()
        es = store.create("remittance_records", dict(self.messages[0]),
                          provider=provider)
        store.create("remittance_records", dict(self.messages[3]),
                     provider=provider)
        question = "¿Cuánto mandamos para las medicinas de la abuela?"
        self.assertEqual(app.recall(store, None, question), app.NO_ANSWER)
        confirmed = app.confirm(store, es["id"])
        self.assertTrue(confirmed["properties"]["humanConfirmed"])
        answer = app.recall(store, None, question)
        self.assertIn("msg-011", answer)
        self.assertIn("300000", answer)
        self.assertNotIn("msg-014", answer)  # unconfirmed never appears
        self.assertNotIn("provisional", answer.lower())
        # An unconfirmed record never answers even as the only lexical match.
        fr_q = "Combien pour l'ordonnance de maman par Wave ?"
        self.assertEqual(app.recall(store, None, fr_q), app.NO_ANSWER)

    def test_unknown_channel_value_maps_to_unknown(self):
        odd = FixtureProvider({"default":
                               "AMOUNT: 300000\nCURRENCY: MXN\n"
                               "CHANNEL: paypal\nPURPOSE: medicinas\n"
                               "CONFIDENCE: 0.9"})
        store, _ = self._store(odd)
        res = store.create("remittance_records", dict(self.messages[0]),
                           provider=odd)
        p = res["properties"]
        self.assertEqual(p["channel"], "unknown")
        self.assertEqual(p["extractMode"], "model")  # channel is non-fatal

    def test_bad_currency_is_a_validation_miss(self):
        odd = FixtureProvider({"default":
                               "AMOUNT: 300000\nCURRENCY: US DOLLARS\n"
                               "CHANNEL: wallet\nPURPOSE: medicinas\n"
                               "CONFIDENCE: 0.9"})
        store, _ = self._store(odd)
        res = store.create("remittance_records", dict(self.messages[0]),
                           provider=odd)
        self.assertEqual(res["properties"]["extractMode"], "confirm_needed")


if __name__ == "__main__":
    unittest.main()
