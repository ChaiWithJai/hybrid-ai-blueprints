"""Deterministic tests for demo 05 — no model server required."""

import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.abspath(os.path.join(HERE, "..", "..")))

import app  # noqa: E402
from edgekit import FixtureProvider  # noqa: E402
from edgekit.store import BundleError  # noqa: E402


class CatchupDemoTests(unittest.TestCase):
    def setUp(self):
        self.fixture = app.load_fixture()

    def _seeded_store(self, provider, items=None):
        store = app.make_store(provider, self.fixture)
        app.seed_backlog(store, items or self.fixture["items"], provider)
        return store

    def test_fixture_run_verdict_keep(self):
        card = app.run("fixture")
        self.assertEqual(card["verdict"], "keep",
                         [g for g in card["gates"] if not g["passed"]])
        self.assertEqual(card["mode"], "fixture")

    def test_digest_refs_resolve_and_survive(self):
        provider = FixtureProvider(self.fixture["fixture_digests"])
        store = self._seeded_store(provider)
        res = store.create("catchups",
                           {"windowLabel": self.fixture["window_label"]},
                           provider=provider)
        props = res["properties"]
        self.assertEqual(props["digestMode"], "model")
        self.assertEqual(props["droppedCount"], 0)
        valid = {it["itemRef"] for it in self.fixture["items"]}
        grounded = set(filter(None, props["groundedRefs"].split(",")))
        self.assertEqual(grounded, valid)  # every item covered, none invented
        self.assertEqual(props["actionsNeeded"], "it-002,it-003,it-005")
        self.assertEqual(len(props["digestText"].splitlines()), 5)

    def test_fabricated_ref_line_is_dropped_and_counted(self):
        bad = FixtureProvider({"default": (
            "LINE: Lupita sent 3000 pesos via Spin [ref: it-006]\n"
            "LINE: grandma won the qqxyzzy lottery [ref: it-999]\n"
            "ACTIONS: it-999")})
        store = self._seeded_store(bad)
        res = store.create("catchups", {"windowLabel": "negative-control"},
                           provider=bad)
        props = res["properties"]
        self.assertEqual(props["droppedCount"], 1)
        self.assertEqual(props["groundedRefs"], "it-006")
        self.assertEqual(props["digestMode"], "model")
        self.assertNotIn("it-999", props["digestText"])
        self.assertEqual(props["actionsNeeded"], "")

    def test_no_shared_content_word_is_dropped(self):
        # Valid ref but zero content-word overlap: still ungrounded.
        bad = FixtureProvider({"default": (
            "LINE: qqxyzzy unrelated nonsense output [ref: it-001]\n"
            "ACTIONS: none")})
        store = self._seeded_store(bad)
        res = store.create("catchups", {"windowLabel": "overlap-control"},
                           provider=bad)
        props = res["properties"]
        self.assertEqual(props["digestMode"], "fallback")
        self.assertEqual(props["droppedCount"], 1)
        self.assertEqual(props["groundedRefs"], "")
        for it in self.fixture["items"]:
            self.assertIn(f"- {it['senderName']}: ", props["digestText"])

    def test_client_only_never_syncs_even_online(self):
        provider = FixtureProvider(self.fixture["fixture_digests"])
        store = self._seeded_store(provider)
        res = store.create("catchups",
                           {"windowLabel": self.fixture["window_label"]},
                           provider=provider)
        store.set_online(True)
        states = {r["sync_state"] for r in store.query("backlog_items")}
        states.add(res["sync_state"])
        self.assertEqual(states, {"local"})
        self.assertEqual(store.sync(), 0)

    def test_required_fields_are_enforced(self):
        provider = FixtureProvider(self.fixture["fixture_digests"])
        store = app.make_store(provider, self.fixture)
        for missing in ("kind", "senderName", "lang", "text", "itemRef"):
            item = dict(self.fixture["items"][0])
            item[missing] = ""
            with self.assertRaises(BundleError, msg=missing):
                store.create("backlog_items", item, provider=provider)
        with self.assertRaises(BundleError):  # catchup needs a windowLabel
            store.create("catchups", {}, provider=provider)

    def test_hierarchical_chunking_makes_multiple_calls(self):
        items = [dict(it) for it in self.fixture["items"]]
        for i, base in enumerate(self.fixture["items"][:5]):
            dup = dict(base)
            dup["itemRef"] = f"it-{8 + i:03d}"
            items.append(dup)
        chunky = FixtureProvider(self.fixture["fixture_chunked"])
        store = self._seeded_store(chunky, items)
        res = store.create("catchups", {"windowLabel": "backlog-week"},
                           provider=chunky)
        self.assertEqual(len(chunky.calls), 3)  # 2 chunks + 1 merge
        props = res["properties"]
        self.assertEqual(props["digestMode"], "model")
        self.assertEqual(props["droppedCount"], 0)
        self.assertIn("it-008", props["groundedRefs"])


if __name__ == "__main__":
    unittest.main()
