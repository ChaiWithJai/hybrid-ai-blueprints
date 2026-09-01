"""Demo 06 — remittance ledger, running.

Pipeline: family chat/voice message -> Bonsai extract (single-turn strict
line format; the BFCL finding) -> attestation guard -> offline-first store.
Money facts are the highest-stakes surface in the suite: an amount enters
the ledger only if its digits (or an obvious textual number form) appear in
the source message, and anything below the confidence floor — or any
validation miss — routes to the one-tap confirm card (extractMode
"confirm_needed", amount fields left null) instead of a silent write.
Recall is pure lexical scoring over CONFIRMED records only, and every
answer cites its sourceRefId.

Run: python3 app.py [fixture|auto]
"""

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
EXTRACT_SYSTEM = (
    "You extract one remittance fact from one family chat or voice message. "
    "Reply in exactly this format and nothing else:\n"
    "AMOUNT: <integer minor units or UNKNOWN>\n"
    "CURRENCY: <ISO code or UNKNOWN>\n"
    "CHANNEL: <remitly|wise|wallet|cash|informal|unknown>\n"
    "PURPOSE: <short phrase or UNKNOWN>\n"
    "CONFIDENCE: <0.0-1.0>")

CHANNELS = {"remitly", "wise", "wallet", "cash", "informal", "unknown"}
NO_ANSWER = "NO_ANSWER: no confirmed remittance record matches this question."

# Native-numeral digits normalized to ASCII so attestation works for the
# scripts this demo exists to serve (Bengali, Devanagari, Arabic-Indic).
_DIGIT_TRANS = {}
for _block in ("০১২৩৪৫৬৭৮৯", "०१२३४५६७८९", "٠١٢٣٤٥٦٧٨٩", "۰۱۲۳۴۵۶۷۸۹"):
    for _i, _ch in enumerate(_block):
        _DIGIT_TRANS[ord(_ch)] = str(_i)

# Obvious textual number forms seen in remittance chatter. Deliberately a
# small allowlist: an amount whose textual form is not here simply fails
# attestation and routes to the confirm card — fail toward the human.
_NUMBER_PHRASES = {
    "tres mil": 3000, "dos mil": 2000, "quinientos": 500,
    "پانچ سو": 500, "پانچسو": 500,
    "পাঁচশো": 500, "পাঁচ শত": 500, "দুই হাজার": 2000,
    "cent cinquante mille": 150000, "soixante-quinze mille": 75000,
    "five hundred": 500, "two hundred fifty": 250,
    "two hundred and fifty": 250,
}


def load_fixture():
    with open(os.path.join(HERE, "fixtures", "remittances.json"),
              encoding="utf-8") as fh:
        return json.load(fh)


def content_words(text, min_len=4):
    # Split on whitespace/punctuation rather than matching \w+: Python's \w
    # drops combining marks, shattering Bengali/Devanagari words into
    # fragments and breaking the overlap check for exactly the languages
    # this demo exists to serve.
    words = re.split(r"[\s,।؛۔;:.!?()\[\]{}\"'«»—–-]+", text)
    return {w for w in words if len(w) >= min_len}


def amount_attested(amount_minor, source_text):
    """A money fact never enters the ledger unattested.

    True only when the amount's digit-string — as minor units or the
    major-unit form (amount // 100) — or an obvious textual number form of
    it appears in the source message.
    """
    if not isinstance(amount_minor, int) or isinstance(amount_minor, bool) \
            or amount_minor <= 0:
        return False
    text = source_text.translate(_DIGIT_TRANS)
    candidates = {amount_minor}
    if amount_minor % 100 == 0:
        candidates.add(amount_minor // 100)
    for value in candidates:
        if re.search(r"(?<![\d.,])" + str(value) + r"(?![\d])", text):
            return True
    lowered = text.lower()
    return any(phrase in lowered and value in candidates
               for phrase, value in _NUMBER_PHRASES.items())


def _parse(raw):
    """Defensive parse of the strict five-line format (single turn only)."""
    fields = {"AMOUNT": None, "CURRENCY": None, "CHANNEL": None,
              "PURPOSE": None, "CONFIDENCE": None}
    for line in raw.splitlines():
        line = line.strip().lstrip("*-#> ").strip()
        for key in fields:
            if fields[key] is None and line.upper().startswith(key + ":"):
                fields[key] = line.split(":", 1)[1].strip()

    amount = None
    if fields["AMOUNT"] and fields["AMOUNT"].upper() != "UNKNOWN":
        cleaned = fields["AMOUNT"].replace(",", "").replace(" ", "")
        if re.fullmatch(r"\d{1,12}", cleaned) and int(cleaned) > 0:
            amount = int(cleaned)

    currency = None  # None = validation miss; "UNKNOWN" is a legal value
    if fields["CURRENCY"]:
        cur = fields["CURRENCY"].strip().upper()
        if cur == "UNKNOWN" or re.fullmatch(r"[A-Z]{3}", cur):
            currency = cur

    channel = (fields["CHANNEL"] or "unknown").strip().lower()
    if channel not in CHANNELS:
        channel = "unknown"

    purpose = fields["PURPOSE"] or None
    if purpose and purpose.upper() == "UNKNOWN":
        purpose = None

    confidence = 0.0  # unparseable confidence fails toward the confirm card
    if fields["CONFIDENCE"]:
        try:
            val = float(fields["CONFIDENCE"])
        except ValueError:
            val = 0.0
        if 0.0 <= val <= 1.0:
            confidence = val

    return amount, currency, channel, purpose, confidence


def build_registry(fixture):
    reg = ActionRegistry()

    @reg.action("extract")
    def extract(props, params, ctx):
        floor = params.get("confidence_floor", 0.8)
        raw = ctx["provider"].chat(
            EXTRACT_SYSTEM,
            f"[{props['sourceRefId']}] ({props['lang']}) "
            f"{props['sourceText']}",
            max_tokens=160)
        amount, currency, channel, purpose, confidence = _parse(raw)

        valid = (amount is not None
                 and amount_attested(amount, props["sourceText"])
                 and currency is not None
                 and confidence >= floor)
        if valid:
            props.update(amountMinor=amount, currency=currency,
                         channel=channel, purpose=purpose,
                         extractionConfidence=confidence,
                         extractMode="model", humanConfirmed=False)
        else:  # the one-tap confirm card seam: amount fields stay null
            props.update(amountMinor=None, currency=None,
                         channel=channel, purpose=purpose,
                         extractionConfidence=confidence,
                         extractMode="confirm_needed", humanConfirmed=False)

    return reg


def confirm(store, resource_id):
    """The one-tap confirm: a human vouches for the record."""
    return store.update(resource_id, {"humanConfirmed": True})


def recall(store, provider_unused, question, family_id=1):
    """Grounded recall: pure lexical scoring over CONFIRMED records only.

    Deterministic, stdlib, no embeddings, and the model is never consulted —
    parametric memory is never trusted for money facts. The best-overlapping
    confirmed record is returned as an answer that always cites its
    sourceRefId; unconfirmed records are never eligible.
    """
    q_words = content_words(question)
    best, best_score = None, 0
    for rec in store.query("remittance_records", family_id=family_id):
        p = rec["properties"]
        if p.get("humanConfirmed") is not True:
            continue  # unconfirmed money facts never surface in answers
        haystack = " ".join(str(p.get(k) or "") for k in
                            ("sourceText", "purpose", "channel", "currency"))
        score = len(q_words & content_words(haystack))
        if score > best_score:
            best, best_score = rec, score
    if best is None:
        return NO_ANSWER
    p = best["properties"]
    parts = [f"Confirmed record [{p['sourceRefId']}]"]
    if p.get("amountMinor") is not None:
        parts.append(f"amount {p['amountMinor']} minor units "
                     f"{p.get('currency') or 'UNKNOWN'}")
    parts.append(f"channel {p.get('channel') or 'unknown'}")
    if p.get("purpose"):
        parts.append(f"purpose: {p['purpose']}")
    parts.append(f"source: \"{p['sourceText']}\"")
    return " — ".join(parts)


def make_store(provider, fixture):
    store = FamilyStore(registry=build_registry(fixture))
    with open(os.path.join(HERE, "bundle.json"), encoding="utf-8") as fh:
        store.install_bundle(json.load(fh))
    store.ctx_extra["provider"] = provider
    return store


# -- gates ----------------------------------------------------------------

def gates(provider, fixture):
    clear, vague = fixture["messages"][:5], fixture["messages"][5]

    def extraction_all():
        # Evaluates every message (no short-circuit) so the evidence shows
        # per-language extraction quality; still passes only if all five
        # clear messages land as attested model records AND the vague one
        # routes to the confirm card.
        store = make_store(provider, fixture)
        details, ok = [], True
        for msg in clear:
            res = store.create("remittance_records", dict(msg),
                               provider=provider)
            p = res["properties"]
            attested = amount_attested(p["amountMinor"], p["sourceText"])
            ok = ok and p["extractMode"] == "model" and attested
            details.append(f"{msg['sourceRefId']}:{p['lang']}:"
                           f"{p['extractMode']}:{p['amountMinor']} "
                           f"{p['currency']}")
        res = store.create("remittance_records", dict(vague),
                           provider=provider)
        p = res["properties"]
        ok = ok and (p["extractMode"] == "confirm_needed"
                     and p["amountMinor"] is None)
        details.append(f"{vague['sourceRefId']}:{p['lang']}:"
                       f"{p['extractMode']}:{p['amountMinor']}")
        return ok, "; ".join(details)

    def unattested_amount_rejected():
        # Negative control: the evaluator can fail. The source says 3000;
        # a provider asserting 9999 must be routed to the confirm card.
        bad = FixtureProvider({"default":
                               "AMOUNT: 9999\nCURRENCY: MXN\n"
                               "CHANNEL: wallet\nPURPOSE: medicinas\n"
                               "CONFIDENCE: 0.95"})
        store = make_store(bad, fixture)
        res = store.create("remittance_records", dict(clear[0]),
                           provider=bad)
        p = res["properties"]
        return (p["extractMode"] == "confirm_needed"
                and p["amountMinor"] is None
                and p["humanConfirmed"] is False,
                f"extractMode={p['extractMode']} amount={p['amountMinor']}")

    def recall_only_confirmed():
        store = make_store(provider, fixture)
        es = store.create("remittance_records", dict(clear[0]),
                          provider=provider)
        store.create("remittance_records", dict(clear[3]), provider=provider)
        question = "¿Cuánto mandamos para las medicinas de la abuela?"
        before = recall(store, None, question)
        if before != NO_ANSWER:
            return False, f"answered before any confirm: {before!r}"
        confirm(store, es["id"])
        after = recall(store, None, question)
        if "msg-011" not in after:
            return False, f"answer does not cite msg-011: {after!r}"
        if "msg-014" in after:
            return False, f"unconfirmed record surfaced: {after!r}"
        if "provisional" in after.lower():
            return False, f"confirmed answer marked provisional: {after!r}"
        return True, after

    def opt_in_sync():
        store = make_store(provider, fixture)
        store.set_online(False)
        res = store.create("remittance_records", dict(clear[4]),
                           provider=provider)
        if res["sync_state"] != "queued":
            return False, f"expected queued, got {res['sync_state']}"
        if store.sync() != 0:
            return False, "sync delivered while offline"
        store.set_online(True)
        delivered = store.sync()
        state = store.get(res["id"])["sync_state"]
        return (delivered == 1 and state == "synced",
                f"delivered={delivered} state={state}")

    return [
        Gate("extraction_all", extraction_all),
        Gate("unattested_amount_rejected", unattested_amount_rejected),
        Gate("recall_only_confirmed", recall_only_confirmed),
        Gate("opt_in_sync", opt_in_sync),
    ]


def run(mode="fixture"):
    fixture = load_fixture()
    if mode == "fixture":
        provider = FixtureProvider(fixture["fixture_extractions"])
        provider_mode, model = "fixture", "fixture"
    else:
        provider, provider_mode = get_provider()
        model = provider.model
    card = run_gates("06-remittance-ledger", gates(provider, fixture),
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
