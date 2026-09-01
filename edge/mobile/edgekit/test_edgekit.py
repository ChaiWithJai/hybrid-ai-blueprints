"""Platform tests — the contract every demo relies on."""

import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..")))

from edgekit import ActionRegistry, FamilyStore, FixtureProvider  # noqa: E402
from edgekit.store import BundleError  # noqa: E402

BUNDLE = {
    "slug": "things",
    "version": 1,
    "sync_mode": "always",
    "properties": {
        "name": {"type": "string", "required": True},
        "note": {"type": "string", "default": "-"},
    },
    "client_actions": [{"name": "stamp", "params": {"mark": "x"}}],
}


def make_store():
    reg = ActionRegistry()

    @reg.action("stamp")
    def stamp(props, params, ctx):
        props["note"] = params["mark"]

    store = FamilyStore(registry=reg)
    store.install_bundle(BUNDLE)
    return store


class StoreTests(unittest.TestCase):
    def test_required_field_enforced(self):
        store = make_store()
        with self.assertRaises(BundleError):
            store.create("things", {})

    def test_unknown_field_rejected(self):
        store = make_store()
        with self.assertRaises(BundleError):
            store.create("things", {"name": "a", "bogus": 1})

    def test_default_and_action_applied(self):
        store = make_store()
        res = store.create("things", {"name": "a"})
        self.assertEqual(res["properties"]["note"], "x")

    def test_unregistered_action_rejected_at_install(self):
        bad = dict(BUNDLE, slug="bad",
                   client_actions=[{"name": "nope", "params": {}}])
        with self.assertRaises(BundleError):
            make_store().install_bundle(bad)

    def test_offline_queue_semantics(self):
        store = make_store()
        store.set_online(False)
        res = store.create("things", {"name": "a"})
        self.assertEqual(res["sync_state"], "queued")
        self.assertEqual(store.sync(), 0)
        store.set_online(True)
        self.assertEqual(store.sync(), 1)
        self.assertEqual(store.get(res["id"])["sync_state"], "synced")

    def test_sync_mode_none_stays_local(self):
        store = make_store()
        store.install_bundle(dict(BUNDLE, slug="localonly",
                                  sync_mode="none"))
        res = store.create("localonly", {"name": "a"})
        self.assertEqual(res["sync_state"], "local")
        self.assertEqual(store.sync(), 0)

    def test_failed_action_writes_nothing(self):
        reg = ActionRegistry()

        @reg.action("boom")
        def boom(props, params, ctx):
            raise ValueError("no")

        store = FamilyStore(registry=reg)
        store.install_bundle(dict(BUNDLE, slug="b",
                                  client_actions=[{"name": "boom"}]))
        with self.assertRaises(ValueError):
            store.create("b", {"name": "a"})
        self.assertEqual(store.query("b"), [])


class ProviderTests(unittest.TestCase):
    def test_fixture_matches_by_key_and_raises_when_missing(self):
        p = FixtureProvider({"abc": "out1"})
        self.assertEqual(p.chat("s", "... abc ..."), "out1")
        from edgekit.provider import ProviderError
        with self.assertRaises(ProviderError):
            p.chat("s", "nothing matches")

    def test_fixture_records_calls(self):
        p = FixtureProvider({"default": "d"})
        p.chat("sys", "u1")
        self.assertEqual(len(p.calls), 1)


if __name__ == "__main__":
    unittest.main()
