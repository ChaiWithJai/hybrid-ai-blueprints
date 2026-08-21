import copy
import unittest

from core.nostr_event import event_id, nostr_event_errors, verify_schnorr


EVENT = {
    "id": "74b8fb3109bd934443e7fd4cc9078f884ed546e1cc8bbced2fbc43b39e973124",
    "pubkey": "23279b7b640cdae783e992d24a79f46bc9bef1b55f2ddf437b0b7cbda8b27876",
    "created_at": 1786774871,
    "kind": 9,
    "tags": [["h", "ef611df4-6d68-4c22-99bb-e2f3521374ad"]],
    "content": "The final per-share merger consideration is $77.50 in cash, without interest, subject to any required tax withholding. [01_defm14a.htm#html:block:01077]",
    "sig": "a915a19c5c203cdf901c17a9e5512b4903f25646b858d6778b0f8efbfc7999ccd8df997d309d299474bd565e57ff43dc2417de4b5f194e1b920e06e7a467b4e5",
}


class NostrEventTests(unittest.TestCase):
    def test_real_buzz_event_hash_and_signature_replay(self):
        self.assertEqual(event_id(EVENT), EVENT["id"])
        self.assertTrue(verify_schnorr(EVENT["pubkey"], EVENT["id"], EVENT["sig"]))
        self.assertEqual(nostr_event_errors(EVENT), [])

    def test_content_or_signature_tamper_fails(self):
        content_tamper = copy.deepcopy(EVENT)
        content_tamper["content"] += " altered"
        self.assertTrue(any("event ID differs" in item for item in nostr_event_errors(content_tamper)))
        signature_tamper = copy.deepcopy(EVENT)
        signature_tamper["sig"] = "0" * 128
        self.assertTrue(any("invalid BIP-340" in item for item in nostr_event_errors(signature_tamper)))


if __name__ == "__main__":
    unittest.main()
