"""Deterministic tests for demo 04 — no model server required."""

import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.abspath(os.path.join(HERE, "..", "..")))

import app  # noqa: E402
from edgekit import FixtureProvider  # noqa: E402
from edgekit.store import BundleError  # noqa: E402


class DictationComposeTests(unittest.TestCase):
    def setUp(self):
        self.fixture = app.load_fixture()

    def test_fixture_run_verdict_keep(self):
        card = app.run("fixture")
        self.assertEqual(card["verdict"], "keep",
                         [g for g in card["gates"] if not g["passed"]])
        self.assertEqual(card["mode"], "fixture")

    def test_register_and_language_routing_recorded(self):
        provider = FixtureProvider(self.fixture["fixture_cleaned"])
        store = app.make_store(provider, self.fixture)
        routes = set()
        for draft in app.high_confidence(self.fixture):
            res = store.create("compositions", dict(draft),
                               provider=provider)
            props = res["properties"]
            self.assertEqual(props["composeMode"], "model")
            self.assertTrue(props["cleanText"])
            routes.add((props["lang"], props["register"]))
        self.assertEqual(routes, {("bn", "formal"), ("bn", "familiar"),
                                  ("ur", "formal"), ("es", "familiar"),
                                  ("fr", "formal")})
        # every model call carried the requested register in its prompts
        for call, draft in zip(provider.calls,
                               app.high_confidence(self.fixture)):
            self.assertIn(draft["register"], call["system"])
            self.assertIn(f"({draft['lang']}/{draft['register']})",
                          call["user"])

    def test_low_confidence_clarifies_and_never_calls_model(self):
        provider = FixtureProvider(self.fixture["fixture_cleaned"])
        counting = app.CountingProvider(provider)
        store = app.make_store(counting, self.fixture)
        lows = app.low_confidence(self.fixture)
        self.assertEqual(len(lows), 1)
        res = store.create("compositions", dict(lows[0]), provider=counting)
        props = res["properties"]
        self.assertEqual(props["composeMode"], "clarify")
        self.assertIn(lows[0]["lowConfidenceSpan"], props["clarifyPrompt"])
        self.assertIsNone(props.get("cleanText"))
        self.assertEqual(counting.calls, 0)
        self.assertEqual(provider.calls, [])

    def test_clarify_span_defaults_to_last_three_words(self):
        provider = FixtureProvider(self.fixture["fixture_cleaned"])
        store = app.make_store(provider, self.fixture)
        draft = dict(app.low_confidence(self.fixture)[0])
        draft.pop("lowConfidenceSpan")
        res = store.create("compositions", draft, provider=provider)
        last3 = " ".join(draft["rawTranscript"].split()[-3:])
        self.assertIn(last3, res["properties"]["clarifyPrompt"])

    def test_client_only_resources_stay_local(self):
        provider = FixtureProvider(self.fixture["fixture_cleaned"])
        store = app.make_store(provider, self.fixture)
        for draft in app.high_confidence(self.fixture):
            res = store.create("compositions", dict(draft),
                               provider=provider)
            self.assertEqual(res["sync_state"], "local")
        self.assertEqual(store.sync(), 0)
        # even flipping connectivity moves nothing for sync_mode none
        store.set_online(False)
        res = store.create("compositions",
                           dict(app.high_confidence(self.fixture)[0]),
                           provider=provider)
        self.assertEqual(res["sync_state"], "local")
        store.set_online(True)
        self.assertEqual(store.sync(), 0)
        states = {r["sync_state"] for r in store.query("compositions")}
        self.assertEqual(states, {"local"})

    def test_guard_rejects_unrelated_output(self):
        bad = FixtureProvider({"default":
                               "CLEAN: qqxyzzy unrelated nonsense output"})
        store = app.make_store(bad, self.fixture)
        draft = app.high_confidence(self.fixture)[0]
        res = store.create("compositions", dict(draft), provider=bad)
        props = res["properties"]
        self.assertEqual(props["composeMode"], "fallback")
        self.assertEqual(props["cleanText"], draft["rawTranscript"])

    def test_missing_register_raises(self):
        provider = FixtureProvider(self.fixture["fixture_cleaned"])
        store = app.make_store(provider, self.fixture)
        draft = dict(app.high_confidence(self.fixture)[0])
        del draft["register"]
        with self.assertRaises(BundleError):
            store.create("compositions", draft, provider=provider)

    def test_bad_register_value_raises(self):
        provider = FixtureProvider(self.fixture["fixture_cleaned"])
        store = app.make_store(provider, self.fixture)
        draft = dict(app.high_confidence(self.fixture)[0])
        draft["register"] = "casual"
        with self.assertRaises(ValueError):
            store.create("compositions", draft, provider=provider)


if __name__ == "__main__":
    unittest.main()
