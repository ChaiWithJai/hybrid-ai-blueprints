"""Demo 04 — dictation compose, running.

Pipeline: (fixture ASR transcript) -> confidence gate -> Bonsai clean/register
rewrite -> grounding guard -> client-only store. Two disciplines from the
design doc are load-bearing here:

1. The refusal rule: if ASR confidence is below the floor, the model is
   never called — the draft comes back as a clarify prompt naming the
   uncertain span. We never send silently-wrong text on a low-literacy
   user's behalf; the harm asymmetry is the design constraint.
2. Client-only mode: `compositions` is sync_mode "none" — the boilerplate's
   client-only rule test. Every resource must stay sync_state "local" and
   sync() must move nothing.

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
CLEAN_SYSTEM = (
    "You clean up one dictated message so it can be sent as written text. "
    "Reply in the SAME language as the message, in the {register} register, "
    "in exactly this format and nothing else:\n"
    "CLEAN: <one cleaned message>\n"
    "Fix punctuation, capitalization, and sentence breaks only. Keep every "
    "fact exactly as dictated; add no new facts, names, or numbers.")


def load_fixture():
    with open(os.path.join(HERE, "fixtures", "compositions.json"),
              encoding="utf-8") as fh:
        return json.load(fh)


def content_words(text, min_len=4):
    # Split on whitespace/punctuation rather than matching \w+: Python's \w
    # drops combining marks, shattering Bengali/Devanagari words into
    # fragments and breaking the overlap check for exactly the languages
    # this demo exists to serve.
    words = re.split(r"[\s,।؛۔;:.!?()\[\]{}\"'«»—–-]+", text)
    return {w for w in words if len(w) >= min_len}


class CountingProvider:
    """Transparent wrapper so gates can assert call counts against any
    provider — fixture or live — without conflating the two."""

    def __init__(self, inner):
        self.inner = inner
        self.mode = inner.mode
        self.model = inner.model
        self.calls = 0

    def chat(self, system, user, **kwargs):
        self.calls += 1
        return self.inner.chat(system, user, **kwargs)


def build_registry(fixture):
    reg = ActionRegistry()

    @reg.action("clean_compose")
    def clean_compose(props, params, ctx):
        if props["register"] not in ("formal", "familiar"):
            raise ValueError(
                f"register must be formal|familiar, got {props['register']!r}")
        floor = params.get("confidence_floor", 0.75)
        if props["asrConfidence"] < floor:
            # Refusal rule: below the floor the model is NEVER called.
            # Name the uncertain span and ask; do not compose.
            span = props.get("lowConfidenceSpan") \
                or " ".join(props["rawTranscript"].split()[-3:])
            props.update(
                composeMode="clarify",
                clarifyPrompt=("I did not hear this part clearly: "
                               f"“{span}”. Please say it again "
                               "before I write the message."))
            return
        raw = ctx["provider"].chat(
            CLEAN_SYSTEM.format(register=props["register"]),
            f"({props['lang']}/{props['register']}) {props['rawTranscript']}",
            max_tokens=220)
        clean = _parse(raw)
        if _grounded(clean, props["rawTranscript"]):
            props.update(cleanText=clean, composeMode="model")
        else:  # evidence-safe fallback: the user's own words, verbatim
            props.update(cleanText=props["rawTranscript"],
                         composeMode="fallback")

    return reg


def _parse(raw):
    for line in raw.splitlines():
        if line.upper().startswith("CLEAN:"):
            return line.split(":", 1)[1].strip()
    return ""


def _grounded(clean, raw_transcript, min_overlap=2):
    overlap = content_words(clean) & content_words(raw_transcript)
    return bool(clean) and len(overlap) >= min_overlap


def make_store(provider, fixture):
    store = FamilyStore(registry=build_registry(fixture))
    with open(os.path.join(HERE, "bundle.json"), encoding="utf-8") as fh:
        store.install_bundle(json.load(fh))
    store.ctx_extra["provider"] = provider
    return store


def high_confidence(fixture):
    return [d for d in fixture["drafts"] if d["asrConfidence"] >= 0.75]


def low_confidence(fixture):
    return [d for d in fixture["drafts"] if d["asrConfidence"] < 0.75]


# -- gates ----------------------------------------------------------------

def gates(provider, fixture):
    def high_confidence_composed():
        store = make_store(provider, fixture)
        modes = []
        for draft in high_confidence(fixture):
            res = store.create("compositions", dict(draft),
                               provider=provider)
            props = res["properties"]
            if not props.get("cleanText"):
                return False, f"no cleanText for ({props['lang']}/" \
                              f"{props['register']})"
            mode = props.get("composeMode")
            if mode == "model":
                if not _grounded(props["cleanText"], props["rawTranscript"]):
                    return False, "labeled model but fails grounding"
            elif mode == "fallback":
                if props["cleanText"] != props["rawTranscript"]:
                    return False, "labeled fallback but not verbatim"
            else:
                return False, f"bad composeMode {mode!r}"
            modes.append(f"{props['lang']}/{props['register']}:{mode}")
        return True, "; ".join(modes)

    def low_confidence_clarifies_without_model():
        counting = CountingProvider(provider)
        store = make_store(counting, fixture)
        for draft in low_confidence(fixture):
            res = store.create("compositions", dict(draft),
                               provider=counting)
            props = res["properties"]
            if props.get("composeMode") != "clarify":
                return False, f"expected clarify, got {props.get('composeMode')}"
            span = draft.get("lowConfidenceSpan") \
                or " ".join(draft["rawTranscript"].split()[-3:])
            if span not in props.get("clarifyPrompt", ""):
                return False, "clarifyPrompt does not name the span"
        if counting.calls != 0:
            return False, f"provider called {counting.calls}x on low confidence"
        return True, "0 provider calls; clarify prompt names uncertain span"

    def client_only_rule():
        store = make_store(provider, fixture)
        for draft in high_confidence(fixture):
            store.create("compositions", dict(draft), provider=provider)
        states = {r["sync_state"]
                  for r in store.query("compositions")}
        if states != {"local"}:
            return False, f"non-local states: {sorted(states)}"
        moved = store.sync()
        after = {r["sync_state"] for r in store.query("compositions")}
        return (moved == 0 and after == {"local"},
                f"sync moved {moved}; states after sync: {sorted(after)}")

    def guard_rejects_ungrounded():
        # Negative control: a provider that answers with an unrelated
        # sentence must trip the guard into verbatim fallback, never pass
        # as a cleaned message.
        bad = FixtureProvider({"default":
                               "CLEAN: qqxyzzy unrelated nonsense output"})
        store = make_store(bad, fixture)
        draft = high_confidence(fixture)[0]
        res = store.create("compositions", dict(draft), provider=bad)
        props = res["properties"]
        return (props["composeMode"] == "fallback"
                and props["cleanText"] == draft["rawTranscript"],
                f"composeMode={props['composeMode']}")

    return [
        Gate("high_confidence_items_composed", high_confidence_composed),
        Gate("low_confidence_never_reaches_model",
             low_confidence_clarifies_without_model),
        Gate("client_only_rule_stays_local", client_only_rule),
        Gate("grounding_guard_rejects_mutation", guard_rejects_ungrounded),
    ]


def run(mode="fixture"):
    fixture = load_fixture()
    if mode == "fixture":
        provider = FixtureProvider(fixture["fixture_cleaned"])
        provider_mode, model = "fixture", "fixture"
    else:
        provider, provider_mode = get_provider()
        model = provider.model
    card = run_gates("04-dictation-compose", gates(provider, fixture),
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
