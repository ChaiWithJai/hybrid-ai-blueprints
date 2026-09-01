"""Deterministic tests for demo 03 — no model server required."""

import base64
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.abspath(os.path.join(HERE, "..", "..")))

import app  # noqa: E402
from edgekit import FixtureProvider  # noqa: E402


class FamilyLineDemoTests(unittest.TestCase):
    def setUp(self):
        self.fixture = app.load_fixture()
        self.provider = FixtureProvider(self.fixture["fixture_summaries"])

    def test_fixture_run_verdict_keep(self):
        card = app.run("fixture")
        self.assertEqual(card["verdict"], "keep",
                         [g for g in card["gates"] if not g["passed"]])
        self.assertEqual(card["mode"], "fixture")
        self.assertEqual({g["gate"] for g in card["gates"]},
                         {"mailbox_blindness", "chaos_delivery",
                          "digest_after_decrypt", "tamper_fails_closed"})

    def test_cipher_roundtrip_and_blindness_property(self):
        for env in self.fixture["envelopes"]:
            blob = app.encrypt(app.FAMILY_KEY, env["plaintext"])
            self.assertEqual(app.decrypt(app.FAMILY_KEY, blob),
                             env["plaintext"])
            for word in app.content_words(env["plaintext"]):
                self.assertNotIn(word, blob)

    def test_stored_cipherblob_contains_no_plaintext(self):
        store = app.make_store(self.provider)
        for env in self.fixture["envelopes"]:
            res = store.create("envelopes", app.seal(env),
                               provider=self.provider)
            stored = store.get(res["id"])["properties"]["cipherBlob"]
            leaked = {w for w in app.content_words(env["plaintext"])
                      if w in stored}
            self.assertEqual(leaked, set(), f"leak in {env['lang']}")

    def test_all_four_languages_digested_after_decrypt(self):
        store = app.make_store(self.provider)
        langs = set()
        for env in self.fixture["envelopes"]:
            res = store.create("envelopes", app.seal(env),
                               provider=self.provider)
            props = res["properties"]
            self.assertEqual(props["transcript"], env["plaintext"])
            self.assertEqual(props["summaryMode"], "model")
            self.assertTrue(props["summary"])
            self.assertEqual(props["mediaType"], "voice")
            self.assertEqual(props["deliveredTo"], "")
            langs.add(props["lang"])
        self.assertEqual(langs, {"bn", "ur", "es", "fr"})

    def test_chaos_delivery_loses_nothing(self):
        # Deterministic on/off script — no randomness, no seed needed.
        store = app.make_store(self.provider)
        n = 50
        envelopes = [app.seal(self.fixture["envelopes"][i % 4])
                     for i in range(n)]
        pattern = [True, False, True, True, False, False, True, False]
        ids = app.deliver_round(store, self.provider, envelopes, pattern)
        self.assertEqual(len(ids), n)
        self.assertEqual(len(set(ids)), n)
        for rid in ids:
            self.assertEqual(store.get(rid)["sync_state"], "synced")
        self.assertEqual(len(store.query("envelopes")), n)

    def test_offline_create_queues_then_syncs(self):
        store = app.make_store(self.provider)
        store.set_online(False)
        res = store.create("envelopes", app.seal(self.fixture["envelopes"][0]),
                           provider=self.provider)
        self.assertEqual(res["sync_state"], "queued")
        self.assertEqual(store.sync(), 0)  # offline sync must deliver nothing
        store.set_online(True)
        self.assertEqual(store.sync(), 1)
        self.assertEqual(store.get(res["id"])["sync_state"], "synced")

    def test_tampered_cipherblob_fails_closed(self):
        store = app.make_store(self.provider)
        props = app.seal(self.fixture["envelopes"][1])
        raw = bytearray(base64.b64decode(props["cipherBlob"]))
        raw[len(raw) // 2] ^= 0xFF
        props["cipherBlob"] = base64.b64encode(bytes(raw)).decode("ascii")
        before = len(store.query("envelopes"))
        with self.assertRaises(ValueError):
            store.create("envelopes", props, provider=self.provider)
        self.assertEqual(len(store.query("envelopes")), before)

    def test_garbage_cipherblob_fails_closed(self):
        store = app.make_store(self.provider)
        props = app.seal(self.fixture["envelopes"][2])
        props["cipherBlob"] = "not!!valid@@base64%%"
        with self.assertRaises(ValueError):
            store.create("envelopes", props, provider=self.provider)
        self.assertEqual(len(store.query("envelopes")), 0)

    def test_missing_cipherblob_raises(self):
        store = app.make_store(self.provider)
        props = app.seal(self.fixture["envelopes"][0])
        props["cipherBlob"] = ""
        with self.assertRaises(ValueError):  # BundleError is a ValueError
            store.create("envelopes", props, provider=self.provider)
        del props["cipherBlob"]
        with self.assertRaises(ValueError):
            store.create("envelopes", props, provider=self.provider)

    def test_ungrounded_summary_falls_back_labeled(self):
        bad = FixtureProvider({"default":
                               "SUMMARY: qqxyzzy unrelated nonsense\n"
                               "NEEDS_REPLY: no"})
        store = app.make_store(bad)
        res = store.create("envelopes", app.seal(self.fixture["envelopes"][3]),
                           provider=bad)
        props = res["properties"]
        self.assertEqual(props["summaryMode"], "fallback")
        self.assertTrue(props["summary"].startswith("[transcript excerpt]"))

    def test_prototype_crypto_is_labeled(self):
        self.assertIn("NOT SECURITY", app.CRYPTO_STATUS)
        self.assertIn("PROTOTYPE", app.CRYPTO_STATUS.upper())


if __name__ == "__main__":
    unittest.main()
