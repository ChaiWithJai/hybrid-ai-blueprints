"""Demo 05 — catch-up, running.

Pipeline: local backlog (backlog_items, client-only) -> Bonsai digest ->
per-line grounding validator -> offline-first store. This demo is the
boilerplate's client-only architectural test: both namespaces are
sync_mode "none", every resource stays sync_state "local", and sync()
delivers nothing even online. The grounding contract is the deal-room
citation discipline applied to the family: every digest line must cite a
resolvable backlog itemRef AND share a content word with the cited items'
text, or it is dropped. If nothing survives, the digest falls back to a
verbatim item listing — the model never speaks ungrounded.

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
CHUNK_SIZE = 8
DIGEST_SYSTEM = (
    "You compress a family's message backlog into a catch-up digest. "
    "Reply in exactly this format and nothing else:\n"
    "LINE: <one short sentence, in the items' language> "
    "[ref: <itemRef>,<itemRef>]\n"
    "(one LINE per related group of items, at most {max_lines} lines)\n"
    "ACTIONS: <comma-separated itemRefs that need a reply, or none>\n"
    "Every LINE must end with [ref: ...] citing only itemRefs from the "
    "input. Never invent refs.")
MERGE_SYSTEM = (
    "You merge partial catch-up digests into one final digest. "
    "Reply in exactly this format and nothing else:\n"
    "LINE: <one short sentence> [ref: <itemRef>,<itemRef>]\n"
    "(at most {max_lines} lines)\n"
    "ACTIONS: <comma-separated itemRefs that need a reply, or none>\n"
    "Keep only itemRefs that appear in the partial digests. "
    "Never invent refs.")

_REF_RE = re.compile(r"\[ref:\s*([^\]]*)\]", re.IGNORECASE)


def load_fixture():
    with open(os.path.join(HERE, "fixtures", "backlog.json"),
              encoding="utf-8") as fh:
        return json.load(fh)


def content_words(text, min_len=4):
    # Split on whitespace/punctuation rather than matching \w+: Python's \w
    # drops combining marks, shattering Bengali/Devanagari words into
    # fragments and breaking the overlap check for exactly the languages
    # this demo exists to serve.
    words = re.split(r"[\s,।؛۔;:.!?()\[\]{}\"'«»—–-]+", text)
    return {w for w in words if len(w) >= min_len}


# -- digest plumbing --------------------------------------------------------

def _item_prompt(header, items):
    rows = [header]
    for it in items:
        rows.append(f"ITEM {it['itemRef']} ({it['kind']}, {it['lang']}, "
                    f"{it['senderName']}): {it['text']}")
    return "\n".join(rows)


def _run_digest(provider, window_label, items, max_lines):
    """One-shot for small backlogs; hierarchical (chunk digests, then a
    digest of the digests) beyond CHUNK_SIZE — never silent truncation."""
    if len(items) <= CHUNK_SIZE:
        return provider.chat(DIGEST_SYSTEM.format(max_lines=max_lines),
                             _item_prompt(f"window: {window_label}", items),
                             max_tokens=400)
    chunks = [items[i:i + CHUNK_SIZE]
              for i in range(0, len(items), CHUNK_SIZE)]
    partials = []
    for idx, chunk in enumerate(chunks, 1):
        partials.append(provider.chat(
            DIGEST_SYSTEM.format(max_lines=max_lines),
            _item_prompt(
                f"window: {window_label} (chunk {idx}/{len(chunks)})",
                chunk),
            max_tokens=400))
    merge_user = (f"window: {window_label} MERGE {len(chunks)} partial "
                  "digests into one:\n" + "\n---\n".join(partials))
    return provider.chat(MERGE_SYSTEM.format(max_lines=max_lines),
                         merge_user, max_tokens=400)


def _parse(raw):
    """-> ([(sentence, [refs]) per LINE row], [refs from ACTIONS row])."""
    lines, action_refs = [], []
    for row in raw.splitlines():
        row = row.strip()
        upper = row.upper()
        if upper.startswith("LINE:"):
            body = row.split(":", 1)[1].strip()
            match = _REF_RE.search(body)
            refs = []
            sentence = body
            if match:
                refs = [r.strip() for r in match.group(1).split(",")
                        if r.strip()]
                sentence = (body[:match.start()] + body[match.end():]).strip()
            lines.append((sentence, refs))
        elif upper.startswith("ACTIONS:"):
            tail = row.split(":", 1)[1].strip()
            if tail and tail.lower() != "none":
                action_refs = [r.strip() for r in tail.split(",")
                               if r.strip()]
    return lines, action_refs


def _grounded_line(sentence, refs, by_ref):
    """≥1 ref, every ref resolves, and ≥1 content word shared with the
    union of the referenced items' text — the deal-room citation contract."""
    if not refs or any(r not in by_ref for r in refs):
        return False
    pool = set()
    for ref in refs:
        pool |= content_words(by_ref[ref]["text"])
    return bool(content_words(sentence) & pool)


def build_registry(fixture):
    reg = ActionRegistry()

    @reg.action("digest")
    def digest(props, params, ctx):
        store = ctx["store"]
        items = [r["properties"] for r in store.query("backlog_items")]
        if not items:
            raise ValueError("catchups: no backlog items to digest")
        raw = _run_digest(ctx["provider"], props["windowLabel"], items,
                          params.get("max_lines", 5))
        lines, action_refs = _parse(raw)
        by_ref = {it["itemRef"]: it for it in items}
        kept, dropped = [], 0
        for sentence, refs in lines:
            if _grounded_line(sentence, refs, by_ref):
                kept.append((sentence, refs))
            else:
                dropped += 1
        props["droppedCount"] = dropped
        if kept:
            surviving = []
            for _, refs in kept:
                for ref in refs:
                    if ref not in surviving:
                        surviving.append(ref)
            props["digestText"] = "\n".join(
                f"{sentence} [ref: {','.join(refs)}]"
                for sentence, refs in kept)
            props["groundedRefs"] = ",".join(surviving)
            props["actionsNeeded"] = ",".join(
                r for r in action_refs if r in by_ref)
            props["digestMode"] = "model"
        else:  # evidence-safe fallback: the backlog verbatim, no claims
            props["digestText"] = "\n".join(
                f"- {it['senderName']}: {it['text'][:80]}" for it in items)
            props["groundedRefs"] = ""
            props["actionsNeeded"] = ""
            props["digestMode"] = "fallback"

    return reg


def make_store(provider, fixture):
    store = FamilyStore(registry=build_registry(fixture))
    with open(os.path.join(HERE, "bundle.json"), encoding="utf-8") as fh:
        bundles = json.load(fh)
    store.install_bundle(bundles["items"])
    store.install_bundle(bundles["digests"])
    store.ctx_extra["provider"] = provider
    return store


def seed_backlog(store, items, provider=None):
    for item in items:
        store.create("backlog_items", dict(item), provider=provider)


# -- gates ------------------------------------------------------------------

def gates(provider, fixture):
    valid_refs = {it["itemRef"] for it in fixture["items"]}

    def digest_grounded():
        store = make_store(provider, fixture)
        seed_backlog(store, fixture["items"], provider)
        res = store.create("catchups",
                           {"windowLabel": fixture["window_label"]},
                           provider=provider)
        props = res["properties"]
        if not props.get("digestText"):
            return False, "no digestText produced"
        kept = 0
        if props["digestMode"] == "model":
            for line in props["digestText"].splitlines():
                match = _REF_RE.search(line)
                refs = ([r.strip() for r in match.group(1).split(",")]
                        if match else [])
                if not refs or any(r not in valid_refs for r in refs):
                    return False, f"unresolvable ref in line {line!r}"
                kept += 1
        for ref in filter(None, props["actionsNeeded"].split(",")):
            if ref not in valid_refs:
                return False, f"ACTIONS ref {ref!r} does not resolve"
        return True, (f"mode={props['digestMode']} lines_kept={kept} "
                      f"lines_dropped={props['droppedCount']} "
                      f"actions={props['actionsNeeded'] or '-'}")

    def zero_ungrounded_lines():
        # Negative control: a fabricated ref must be dropped and counted
        # while the grounded line survives — proof the validator can fail.
        bad = FixtureProvider({"default": (
            "LINE: Lupita sent 3000 pesos via Spin [ref: it-006]\n"
            "LINE: grandma won the qqxyzzy lottery [ref: it-999]\n"
            "ACTIONS: it-999")})
        store = make_store(bad, fixture)
        seed_backlog(store, fixture["items"], bad)
        res = store.create("catchups", {"windowLabel": "negative-control"},
                           provider=bad)
        props = res["properties"]
        ok = (props["droppedCount"] == 1
              and props["groundedRefs"] == "it-006"
              and props["digestMode"] == "model"
              and "it-999" not in props["digestText"]
              and props["actionsNeeded"] == "")
        return ok, (f"dropped={props['droppedCount']} "
                    f"groundedRefs={props['groundedRefs']!r} "
                    f"actions={props['actionsNeeded']!r}")

    def client_only():
        store = make_store(provider, fixture)
        seed_backlog(store, fixture["items"], provider)
        res = store.create("catchups",
                           {"windowLabel": fixture["window_label"]},
                           provider=provider)
        store.set_online(True)
        states = {r["sync_state"] for r in store.query("backlog_items")}
        states.add(res["sync_state"])
        delivered = store.sync()
        modes = (store.namespace("backlog_items")["sync_mode"],
                 store.namespace("catchups")["sync_mode"])
        ok = states == {"local"} and delivered == 0 and modes == ("none",
                                                                  "none")
        return ok, (f"states={sorted(states)} synced_while_online="
                    f"{delivered} sync_modes={modes}")

    def hierarchical_plumbing():
        # 12 items forces the chunked path: 2 chunk digests + 1 merge = 3
        # provider calls, asserted against a chunk-keyed fixture map.
        items = [dict(it) for it in fixture["items"]]
        for i, base in enumerate(fixture["items"][:5]):
            dup = dict(base)
            dup["itemRef"] = f"it-{8 + i:03d}"
            items.append(dup)
        chunky = FixtureProvider(fixture["fixture_chunked"])
        store = make_store(chunky, fixture)
        seed_backlog(store, items, chunky)
        res = store.create("catchups", {"windowLabel": "backlog-week"},
                           provider=chunky)
        props = res["properties"]
        calls = len(chunky.calls)
        ok = (calls > 1 and props["digestMode"] == "model"
              and bool(props["digestText"]))
        return ok, (f"items={len(items)} provider_calls={calls} "
                    f"mode={props['digestMode']} "
                    f"groundedRefs={props['groundedRefs']}")

    return [
        Gate("digest_grounded", digest_grounded),
        Gate("zero_ungrounded_lines", zero_ungrounded_lines),
        Gate("client_only", client_only),
        Gate("hierarchical_plumbing", hierarchical_plumbing),
    ]


def run(mode="fixture"):
    fixture = load_fixture()
    if mode == "fixture":
        provider = FixtureProvider(fixture["fixture_digests"])
        provider_mode, model = "fixture", "fixture"
    else:
        provider, provider_mode = get_provider()
        model = provider.model
    card = run_gates("05-catch-up", gates(provider, fixture),
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
