"""Deterministic tests for demo 02 — no model server required."""

import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.abspath(os.path.join(HERE, "..", "..")))

import app  # noqa: E402
from edgekit import FixtureProvider  # noqa: E402


class OfflineTranslateDemoTests(unittest.TestCase):
    def setUp(self):
        self.fixture = app.load_fixture()

    def _store(self, provider):
        return app.make_store(provider, self.fixture)

    def test_fixture_run_verdict_keep(self):
        card = app.run("fixture")
        self.assertEqual(card["verdict"], "keep",
                         [g for g in card["gates"] if not g["passed"]])
        self.assertEqual(card["mode"], "fixture")

    def test_tier_routing_all_three_tiers(self):
        provider = FixtureProvider(self.fixture["fixture_translations"])
        store = self._store(provider)
        expected = {
            "tj-001": ("generative", "model"),
            "tj-002": ("generative", "model"),
            "tj-003": ("marginal", "model"),
            "tj-004": ("marginal", "model"),
            "tj-005": ("sidecar", "sidecar-fixture"),
            "tj-006": ("sidecar", "sidecar-fixture"),
        }
        for job in self.fixture["jobs"]:
            res = store.create("translations", dict(job), provider=provider)
            props = res["properties"]
            self.assertEqual((props["tier"], props["engine"]),
                             expected[job["jobId"]], job["jobId"])
            self.assertTrue(props["translation"])
            self.assertNotEqual(props["translation"].strip(),
                                job["srcText"].strip())

    def test_sidecar_tier_never_calls_llm_and_is_labeled_fixture(self):
        provider = FixtureProvider(self.fixture["fixture_translations"])
        store = self._store(provider)
        for job in self.fixture["jobs"]:
            if app.pair_tier(job["srcLang"], job["dstLang"]) != "sidecar":
                continue
            res = store.create("translations", dict(job), provider=provider)
            props = res["properties"]
            self.assertEqual(props["engine"], "sidecar-fixture")
            self.assertEqual(props["sidecarMode"], "fixture")
        self.assertEqual(provider.calls, [],
                         "sidecar tier must never reach the LLM provider")

    def test_echo_negative_control_trips_guard(self):
        job = dict(self.fixture["jobs"][0])
        echo = FixtureProvider(
            {job["jobId"]: "TRANSLATION: " + job["srcText"]})
        store = self._store(echo)
        res = store.create("translations", job, provider=echo)
        props = res["properties"]
        self.assertEqual(props["engine"], "fallback")
        self.assertEqual(props["translation"],
                         "[untranslated] " + job["srcText"])

    def test_empty_output_trips_guard(self):
        job = dict(self.fixture["jobs"][1])
        mute = FixtureProvider({"default": "I cannot translate that."})
        store = self._store(mute)
        res = store.create("translations", job, provider=mute)
        self.assertEqual(res["properties"]["engine"], "fallback")

    def test_missing_srcText_raises(self):
        provider = FixtureProvider(self.fixture["fixture_translations"])
        store = self._store(provider)
        job = dict(self.fixture["jobs"][0])
        del job["srcText"]
        with self.assertRaises(ValueError):
            store.create("translations", job, provider=provider)

    def test_unsupported_language_fails_closed(self):
        provider = FixtureProvider(self.fixture["fixture_translations"])
        store = self._store(provider)
        job = dict(self.fixture["jobs"][0])
        job["srcLang"] = "xx"
        with self.assertRaises(ValueError):
            store.create("translations", job, provider=provider)


if __name__ == "__main__":
    unittest.main()
