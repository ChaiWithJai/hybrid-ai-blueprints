"""Deterministic tests for demo 01 — no model server required."""

import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.abspath(os.path.join(HERE, "..", "..")))

import app  # noqa: E402
from edgekit import FixtureProvider  # noqa: E402


class VoiceNoteDemoTests(unittest.TestCase):
    def setUp(self):
        self.fixture = app.load_fixture()

    def test_fixture_run_verdict_keep(self):
        card = app.run("fixture")
        self.assertEqual(card["verdict"], "keep",
                         [g for g in card["gates"] if not g["passed"]])
        self.assertEqual(card["mode"], "fixture")

    def test_all_five_languages_summarized(self):
        provider = FixtureProvider(self.fixture["fixture_summaries"])
        store = app.make_store(provider, self.fixture)
        langs = set()
        for note in self.fixture["notes"]:
            res = store.create("voice_notes", dict(note), provider=provider)
            self.assertEqual(res["properties"]["summaryMode"], "model")
            langs.add(res["properties"]["lang"])
        self.assertEqual(langs, {"bn", "ur", "hi", "es", "fr"})

    def test_offline_resources_never_sync_silently(self):
        provider = FixtureProvider(self.fixture["fixture_summaries"])
        store = app.make_store(provider, self.fixture)
        store.set_online(False)
        res = store.create("voice_notes", dict(self.fixture["notes"][1]),
                           provider=provider)
        self.assertEqual(res["sync_state"], "queued")
        self.assertEqual(store.sync(), 0)
        store.set_online(True)
        self.assertEqual(store.sync(), 1)

    def test_grounding_guard_is_capable_of_failing(self):
        bad = FixtureProvider({"default": "SUMMARY: zzz\nNEEDS_REPLY: no"})
        store = app.make_store(bad, self.fixture)
        res = store.create("voice_notes", dict(self.fixture["notes"][0]),
                           provider=bad)
        self.assertEqual(res["properties"]["summaryMode"], "fallback")

    def test_missing_transcript_fails_closed(self):
        provider = FixtureProvider(self.fixture["fixture_summaries"])
        store = app.make_store(provider, self.fixture)
        note = dict(self.fixture["notes"][0])
        note["transcript"] = ""
        with self.assertRaises(ValueError):
            store.create("voice_notes", note, provider=provider)


if __name__ == "__main__":
    unittest.main()
