"""Demo 03 — family line, running.

Store-and-forward voice for families split across a connectivity line.
Envelopes are sealed on the sending device, cross the relay as ciphertext
only (the server is a dumb, encrypted mailbox — it cannot read anything),
and are decrypted + digested on the receiving device with the same strict
summarize contract and grounding guard as demo 01. Delivery is exercised
under flapping connectivity: queued offline, synced when the pipe opens,
zero envelopes lost.

Run: python3 app.py [fixture|auto]
"""

import base64
import hashlib
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.abspath(os.path.join(HERE, "..", "..")))

from edgekit import (ActionRegistry, BonsaiProvider, FamilyStore,  # noqa: E402
                     FixtureProvider, Gate, get_provider, run_gates,
                     write_evidence)

EVIDENCE_DIR = os.path.abspath(os.path.join(HERE, "..", "..", "evidence"))
SUMMARIZE_SYSTEM = (
    "You summarize one family voice message. Reply in the SAME language as "
    "the message, in exactly this format and nothing else:\n"
    "SUMMARY: <one line, under {max_words} words>\n"
    "NEEDS_REPLY: <yes or no>")

# ===========================================================================
# !!! LOUD WARNING — PROTOTYPE CRYPTO, NOT SECURITY !!!
#
# The "cipher" below is a toy: a SHA-256-derived XOR keystream plus a
# SHA-256 integrity tag, base64-encoded. It exists ONLY so the demo can
# exercise the architecture honestly — the relay stores ciphertext it
# cannot read, and a tampered blob fails closed. It provides NO real
# confidentiality (deterministic keystream, no nonce, no AEAD, no key
# exchange) and MUST NOT be presented or reused as encryption. DESIGN.md's
# crypto-review gate applies before any real-user pilot; until a reviewed
# implementation (e.g. libsodium sealed boxes) replaces this, the E2EE
# claim is an architecture statement, not a security claim.
# ===========================================================================
CRYPTO_STATUS = ("PROTOTYPE-ONLY: toy XOR+base64 cipher for architecture "
                 "demonstration. NOT SECURITY. Crypto-review gate required "
                 "before any real use (see DESIGN.md).")

# The shared family key would live in each member's device keystore; the
# demo pins one and hands it to actions via store.ctx_extra.
FAMILY_KEY = "demo-family-key-PROTOTYPE-ONLY"


def _keystream(family_key, n):
    out = bytearray()
    seed = family_key.encode("utf-8")
    counter = 0
    while len(out) < n:
        out.extend(hashlib.sha256(seed + counter.to_bytes(8, "big")).digest())
        counter += 1
    return bytes(out[:n])


def encrypt(family_key, text):
    """Seal plaintext into a base64 cipherBlob (toy — see CRYPTO_STATUS)."""
    plain = text.encode("utf-8")
    payload = hashlib.sha256(plain).digest() + plain  # 32-byte tag + body
    ks = _keystream(family_key, len(payload))
    return base64.b64encode(
        bytes(a ^ b for a, b in zip(payload, ks))).decode("ascii")


def decrypt(family_key, blob):
    """Open a cipherBlob; raises ValueError (fails closed) on any tamper."""
    try:
        cipher = base64.b64decode(blob, validate=True)
    except (ValueError, TypeError) as exc:  # binascii.Error is a ValueError
        raise ValueError(f"cipherBlob is not valid base64: {exc}") from exc
    if len(cipher) <= 32:
        raise ValueError("cipherBlob too short to carry an integrity tag")
    ks = _keystream(family_key, len(cipher))
    payload = bytes(a ^ b for a, b in zip(cipher, ks))
    tag, plain = payload[:32], payload[32:]
    if hashlib.sha256(plain).digest() != tag:
        raise ValueError(
            "cipherBlob failed integrity check — refusing to emit plaintext")
    try:
        return plain.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(f"decrypted payload is not UTF-8: {exc}") from exc


def load_fixture():
    with open(os.path.join(HERE, "fixtures", "envelopes.json"),
              encoding="utf-8") as fh:
        return json.load(fh)


def seal(envelope, family_key=FAMILY_KEY):
    """Fixture plaintext -> creatable envelope properties (sender side)."""
    return {
        "senderName": envelope["senderName"],
        "lang": envelope["lang"],
        "cipherBlob": encrypt(family_key, envelope["plaintext"]),
    }


def content_words(text, min_len=4):
    # Split on whitespace/punctuation rather than matching \w+: Python's \w
    # drops combining marks, shattering Bengali/Devanagari words into
    # fragments and breaking the overlap check for exactly the languages
    # this demo exists to serve. (Same rationale as demo 01, kept local.)
    words = re.split(r"[\s,।؛۔;:.!?()\[\]{}\"'«»—–-]+", text)
    return {w for w in words if len(w) >= min_len}


def build_registry():
    reg = ActionRegistry()

    @reg.action("decrypt_and_digest")
    def decrypt_and_digest(props, params, ctx):
        key = ctx.get("family_key")
        if not key:
            raise ValueError("no family key in device context")
        # Fails closed: a raise here aborts the create, nothing is written.
        props["transcript"] = decrypt(key, props["cipherBlob"])
        raw = ctx["provider"].chat(
            SUMMARIZE_SYSTEM.format(max_words=params.get("max_words", 28)),
            f"({props['lang']}) {props['transcript']}",
            max_tokens=160)
        summary, _needs_reply = _parse(raw)
        if _grounded(summary, props["transcript"]):
            props.update(summary=summary, summaryMode="model")
        else:  # evidence-safe fallback, visibly labeled
            props.update(
                summary="[transcript excerpt] " + props["transcript"][:140],
                summaryMode="fallback")

    return reg


def _parse(raw):
    summary, needs_reply = "", True
    for line in raw.splitlines():
        if line.upper().startswith("SUMMARY:"):
            summary = line.split(":", 1)[1].strip()
        elif line.upper().startswith("NEEDS_REPLY:"):
            needs_reply = "yes" in line.split(":", 1)[1].strip().lower()
    return summary, needs_reply


def _grounded(summary, transcript, min_overlap=1):
    overlap = content_words(summary) & content_words(transcript)
    return bool(summary) and len(overlap) >= min_overlap


def make_store(provider, family_key=FAMILY_KEY):
    store = FamilyStore(registry=build_registry())
    with open(os.path.join(HERE, "bundle.json"), encoding="utf-8") as fh:
        store.install_bundle(json.load(fh))
    store.ctx_extra["provider"] = provider
    store.ctx_extra["family_key"] = family_key
    return store


def deliver_round(store, provider, envelopes, offline_periods):
    """Simulate the sending device pushing envelopes while its link flaps.

    offline_periods is a sequence of bools (True = offline during that
    create), cycled over the envelopes — a deterministic connectivity
    script, no randomness. Asserts the honest transitions: offline creates
    queue, online creates sync immediately, and every queued envelope moves
    queued->synced once connectivity returns and sync() runs. Returns the
    created resource ids.
    """
    ids, backlog = [], []
    for i, props in enumerate(envelopes):
        offline = bool(offline_periods[i % len(offline_periods)])
        store.set_online(not offline)
        if not offline and backlog:
            store.sync()  # reconnect flushes the queue before new sends
            for rid in backlog:
                state = store.get(rid)["sync_state"]
                if state != "synced":
                    raise AssertionError(
                        f"envelope {rid} stuck {state!r} after reconnect")
            backlog = []
        res = store.create("envelopes", dict(props), provider=provider)
        expected = "queued" if offline else "synced"
        if res["sync_state"] != expected:
            raise AssertionError(
                f"envelope {res['id']}: expected {expected!r}, "
                f"got {res['sync_state']!r}")
        ids.append(res["id"])
        if offline:
            backlog.append(res["id"])
    store.set_online(True)
    store.sync()
    return ids


# -- gates ----------------------------------------------------------------

def gates(provider, fixture):
    def mailbox_blindness():
        # The server-blindness claim, tested structurally: the only field
        # that crosses the relay is cipherBlob, and the stored cipherBlob
        # must contain no content word of the plaintext. (transcript and
        # summary exist only after on-device decryption.)
        store = make_store(provider)
        for env in fixture["envelopes"]:
            res = store.create("envelopes", seal(env), provider=provider)
            blob = store.get(res["id"])["properties"]["cipherBlob"]
            leaked = {w for w in content_words(env["plaintext"]) if w in blob}
            if leaked:
                return False, (f"{env['lang']}: plaintext leaked into "
                               f"cipherBlob: {sorted(leaked)[:3]}")
        return True, (f"{len(fixture['envelopes'])} envelopes: no content "
                      "word of any plaintext appears in its stored cipherBlob")

    def chaos_delivery():
        store = make_store(provider)
        n = 50
        envelopes = [seal(fixture["envelopes"][i % len(fixture["envelopes"])])
                     for i in range(n)]
        # Deterministic flap script: True = offline for that create.
        pattern = [True, False, True, True, False, False, True, False]
        ids = deliver_round(store, provider, envelopes, pattern)
        states = [store.get(rid)["sync_state"] for rid in ids]
        lost = [rid for rid, s in zip(ids, states) if s != "synced"]
        count = len(store.query("envelopes"))
        ok = len(ids) == n and not lost and count == n
        return ok, (f"{n} connect/disconnect-scripted creates: "
                    f"{states.count('synced')}/{n} synced, {len(lost)} lost, "
                    f"store count {count}")

    def digest_after_decrypt():
        store = make_store(provider)
        modes = []
        for env in fixture["envelopes"]:
            res = store.create("envelopes", seal(env), provider=provider)
            props = res["properties"]
            if props.get("transcript") != env["plaintext"]:
                return False, f"{env['lang']}: decrypt round-trip mismatch"
            if not props.get("summary"):
                return False, f"{env['lang']}: no summary"
            modes.append(f"{env['lang']}:{props['summaryMode']}")
        return True, "; ".join(modes)

    def tamper_fails_closed():
        # Negative control: flip a byte inside a valid cipherBlob; the
        # action must raise and the store must gain no resource.
        store = make_store(provider)
        props = seal(fixture["envelopes"][0])
        raw = bytearray(base64.b64decode(props["cipherBlob"]))
        raw[len(raw) // 2] ^= 0xFF
        props["cipherBlob"] = base64.b64encode(bytes(raw)).decode("ascii")
        before = len(store.query("envelopes"))
        try:
            store.create("envelopes", props, provider=provider)
        except ValueError as exc:
            after = len(store.query("envelopes"))
            return (after == before,
                    f"raised as required ({exc}); "
                    f"store count {before}->{after}")
        return False, "tampered cipherBlob was accepted"

    return [
        Gate("mailbox_blindness", mailbox_blindness),
        Gate("chaos_delivery", chaos_delivery),
        Gate("digest_after_decrypt", digest_after_decrypt),
        Gate("tamper_fails_closed", tamper_fails_closed),
    ]


def run(mode="fixture"):
    fixture = load_fixture()
    if mode == "fixture":
        provider = FixtureProvider(fixture["fixture_summaries"])
        provider_mode, model = "fixture", "fixture"
    else:
        provider, provider_mode = get_provider()
        model = provider.model
    card = run_gates("03-family-line", gates(provider, fixture),
                     provider_mode, model)
    return card


if __name__ == "__main__":
    requested = sys.argv[1] if len(sys.argv) > 1 else "fixture"
    if requested == "auto":
        requested = "live" if BonsaiProvider.available() else "fixture"
    card = run(requested)
    print(json.dumps(card, indent=2, ensure_ascii=False))
    print("evidence:", write_evidence(card, EVIDENCE_DIR))
    sys.exit(0 if card["verdict"] == "keep" else 1)
