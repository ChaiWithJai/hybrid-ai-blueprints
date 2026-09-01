"""Demo 01 — voice-note intelligence, running.

Pipeline: (fixture ASR) -> Bonsai summarize -> grounding guard ->
offline-first store. The guard enforces the deal-room discipline: a summary
that shares no content word with its transcript is rejected and replaced by
an evidence-safe fallback (a labeled transcript excerpt) — the model never
speaks ungrounded on the family's behalf.

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
SUMMARIZE_SYSTEM = (
    "You summarize one family voice message. Reply in the SAME language as "
    "the message, in exactly this format and nothing else:\n"
    "SUMMARY: <one line, under {max_words} words>\n"
    "NEEDS_REPLY: <yes or no>")


def load_fixture():
    with open(os.path.join(HERE, "fixtures", "voice_notes.json"),
              encoding="utf-8") as fh:
        return json.load(fh)


def content_words(text, min_len=4):
    # Split on whitespace/punctuation rather than matching \w+: Python's \w
    # drops combining marks, shattering Bengali/Devanagari words into
    # fragments and breaking the overlap check for exactly the languages
    # this demo exists to serve.
    words = re.split(r"[\s,।؛۔;:.!?()\[\]{}\"'«»—–-]+", text)
    return {w for w in words if len(w) >= min_len}


def build_registry(fixture):
    reg = ActionRegistry()

    @reg.action("transcribe")
    def transcribe(props, params, ctx):
        # whisper.cpp is not installed on the verified host; ASR is a
        # fixture seam and is recorded as such — never silently faked.
        props["asrMode"] = params.get("asr", "fixture")
        if props.get("transcript"):
            return
        raise ValueError("no transcript available and no live ASR configured")

    @reg.action("summarize")
    def summarize(props, params, ctx):
        if props.get("direction") == "out":
            # Your own voice needs no summary — you said it. The model only
            # ever speaks about what OTHERS sent.
            props.update(summary=props["transcript"][:140], needsReply=False,
                         summaryMode="own")
            return
        raw = ctx["provider"].chat(
            SUMMARIZE_SYSTEM.format(max_words=params.get("max_words", 28)),
            f"[{props['audioRef']}] ({props['lang']}) {props['transcript']}",
            max_tokens=160)
        summary, needs_reply = _parse(raw)
        if _grounded(summary, props["transcript"]):
            props.update(summary=summary, needsReply=needs_reply,
                         summaryMode="model")
        else:  # evidence-safe fallback, visibly labeled
            props.update(
                summary="[transcript excerpt] " + props["transcript"][:140],
                needsReply=True, summaryMode="fallback")

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


def make_store(provider, fixture):
    store = FamilyStore(registry=build_registry(fixture))
    with open(os.path.join(HERE, "bundle.json"), encoding="utf-8") as fh:
        store.install_bundle(json.load(fh))
    store.ctx_extra["provider"] = provider
    return store


# -- gates ----------------------------------------------------------------

def gates(provider, fixture):
    def pipeline_summarizes():
        store = make_store(provider, fixture)
        modes = []
        for note in fixture["notes"]:
            res = store.create("voice_notes", dict(note), provider=provider)
            props = res["properties"]
            if not props.get("summary"):
                return False, f"no summary for {note['audioRef']}"
            modes.append(f"{note['audioRef']}:{props['summaryMode']}")
        return True, "; ".join(modes)

    def offline_queue_then_sync():
        store = make_store(provider, fixture)
        store.set_online(False)
        res = store.create("voice_notes", dict(fixture["notes"][0]),
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

    def guard_rejects_ungrounded():
        # Negative control: a provider that answers off-topic must trip the
        # grounding guard into the labeled fallback, never pass as a summary.
        bad = FixtureProvider({"default":
                               "SUMMARY: qqxyzzy unrelated nonsense output\n"
                               "NEEDS_REPLY: no"})
        store = make_store(bad, fixture)
        res = store.create("voice_notes", dict(fixture["notes"][3]),
                           provider=bad)
        props = res["properties"]
        return (props["summaryMode"] == "fallback"
                and props["summary"].startswith("[transcript excerpt]"),
                f"summaryMode={props['summaryMode']}")

    return [
        Gate("pipeline_summarizes_all_notes", pipeline_summarizes),
        Gate("offline_queue_then_sync", offline_queue_then_sync),
        Gate("grounding_guard_rejects_mutation", guard_rejects_ungrounded),
    ]


def run(mode="fixture"):
    fixture = load_fixture()
    if mode == "fixture":
        provider = FixtureProvider(fixture["fixture_summaries"])
        provider_mode, model = "fixture", "fixture"
    else:
        provider, provider_mode = get_provider()
        model = provider.model
    card = run_gates("01-voice-note-intelligence", gates(provider, fixture),
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
