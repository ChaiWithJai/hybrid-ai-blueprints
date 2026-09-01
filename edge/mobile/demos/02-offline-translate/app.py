"""Demo 02 — offline translate, running.

Pipeline: language-tier router -> (Bonsai translate | NLLB sidecar seam) ->
echo guard -> offline-first store. The tier map IS the strategy: Bonsai
1.7B generates only in its serviceable tier; sidecar languages (the pairs
Google/Yandex/Microsoft don't ship offline) belong to NLLB-200, which is
NOT installed on this host — that path is a clearly labeled fixture seam
(engine="sidecar-fixture", sidecarMode="fixture"), mirroring how demo 01
records asrMode="fixture". A fixture must never impersonate a live engine,
and the LLM must never speak in a language outside its tier.

Run: python3 app.py [fixture|auto]
"""

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.abspath(os.path.join(HERE, "..", "..")))

from edgekit import (ActionRegistry, BonsaiProvider, FamilyStore,  # noqa: E402
                     FixtureProvider, Gate, get_provider, run_gates,
                     write_evidence)

EVIDENCE_DIR = os.path.abspath(os.path.join(HERE, "..", "..", "evidence"))

# The tier map from DESIGN.md. generative: Bonsai 1.7B translates directly.
# marginal: Bonsai is attempted but flagged — per-pair winner is picked
# empirically (milestone 2). sidecar: NLLB-only; the LLM is never called.
LANG_TIER = {
    "es": "generative", "fr": "generative", "ru": "generative",
    "hi": "generative", "ar": "generative", "vi": "generative",
    "id": "generative", "en": "generative",
    "ur": "marginal", "bn": "marginal", "tl": "marginal", "uz": "marginal",
    "tg": "sidecar", "ky": "sidecar", "wo": "sidecar",
    "ha": "sidecar", "yo": "sidecar",
}
_TIER_RANK = {"generative": 0, "marginal": 1, "sidecar": 2}
ENGINE_FOR_TIER = {"generative": "model", "marginal": "model",
                   "sidecar": "sidecar-fixture"}

LANG_NAMES = {
    "es": "Spanish", "fr": "French", "ru": "Russian", "hi": "Hindi",
    "ar": "Arabic", "vi": "Vietnamese", "id": "Indonesian", "en": "English",
    "ur": "Urdu", "bn": "Bengali", "tl": "Tagalog", "uz": "Uzbek",
    "tg": "Tajik", "ky": "Kyrgyz", "wo": "Wolof", "ha": "Hausa",
    "yo": "Yoruba",
}

TRANSLATE_SYSTEM = (
    "You translate one short family message from {src} to {dst}. "
    "Reply with exactly one line in this format and nothing else:\n"
    "TRANSLATION: <the message translated into {dst}>")


def load_fixture():
    with open(os.path.join(HERE, "fixtures", "translations.json"),
              encoding="utf-8") as fh:
        return json.load(fh)


def pair_tier(src_lang, dst_lang):
    """A pair is as hard as its hardest side."""
    for lang in (src_lang, dst_lang):
        if lang not in LANG_TIER:
            raise ValueError(f"unsupported language {lang!r}")
    return max(LANG_TIER[src_lang], LANG_TIER[dst_lang],
               key=_TIER_RANK.__getitem__)


class CountingProvider:
    """Transparent wrapper that records every chat() call.

    Lets the sidecar-isolation gate assert 'the LLM was never called'
    against ANY inner provider — live Bonsai included, where the
    FixtureProvider.calls list does not exist.
    """

    def __init__(self, inner):
        self.inner = inner
        self.mode = inner.mode
        self.model = inner.model
        self.calls = []

    def chat(self, system, user, **kwargs):
        self.calls.append({"system": system, "user": user})
        return self.inner.chat(system, user, **kwargs)


def build_registry():
    reg = ActionRegistry()

    @reg.action("translate")
    def translate(props, params, ctx):
        tier = pair_tier(props["srcLang"], props["dstLang"])
        props["tier"] = tier
        if tier == "sidecar":
            # NLLB-200 is not installed on the verified host; the sidecar
            # is a fixture seam and is recorded as such — never silently
            # presented as a live engine (mirrors demo 01's asrMode).
            props["sidecarMode"] = "fixture"
            canned = ctx["sidecar_translations"].get(props["jobId"])
            if canned is None:
                raise ValueError(
                    f"no sidecar fixture for job {props['jobId']!r}")
            out, engine = canned, "sidecar-fixture"
            note = ("canned NLLB-200 output from fixtures/translations.json;"
                    " no live sidecar ran")
        else:
            raw = ctx["provider"].chat(
                TRANSLATE_SYSTEM.format(src=LANG_NAMES[props["srcLang"]],
                                        dst=LANG_NAMES[props["dstLang"]]),
                f"[{props['jobId']}] ({props['srcLang']}->"
                f"{props['dstLang']}) {props['srcText']}",
                max_tokens=220)
            out, engine = _parse(raw), "model"
            note = ("Bonsai generative tier" if tier == "generative" else
                    "marginal pair — verify important details with sender")
        if _untranslated(out, props["srcText"]):
            # evidence-safe fallback, visibly labeled — never ship an
            # empty or echoed 'translation' as if it were one
            props.update(
                translation="[untranslated] " + props["srcText"],
                engine="fallback",
                confidenceNote="guard tripped: output empty or echoed the "
                               "source text")
        else:
            props.update(translation=out, engine=engine,
                         confidenceNote=note)

    return reg


def _parse(raw):
    for line in raw.splitlines():
        if line.strip().upper().startswith("TRANSLATION:"):
            return line.strip().split(":", 1)[1].strip()
    return ""


def _untranslated(out, src_text):
    return not out or out.strip().casefold() == src_text.strip().casefold()


def make_store(provider, fixture):
    store = FamilyStore(registry=build_registry())
    with open(os.path.join(HERE, "bundle.json"), encoding="utf-8") as fh:
        store.install_bundle(json.load(fh))
    store.ctx_extra["provider"] = provider
    store.ctx_extra["sidecar_translations"] = fixture["sidecar_translations"]
    return store


# -- gates ----------------------------------------------------------------

def gates(provider, fixture):
    def all_pairs_translate():
        store = make_store(provider, fixture)
        ok, details = True, []
        for job in fixture["jobs"]:
            res = store.create("translations", dict(job), provider=provider)
            props = res["properties"]
            expected = ENGINE_FOR_TIER[props["tier"]]
            if not props.get("translation") or props["engine"] != expected:
                ok = False
            details.append(f"{job['jobId']}({job['srcLang']}->"
                           f"{job['dstLang']}):{props['engine']}")
        return ok, "; ".join(details)

    def sidecar_never_calls_llm():
        counting = CountingProvider(provider)
        store = make_store(counting, fixture)
        engines = []
        for job in fixture["jobs"]:
            if pair_tier(job["srcLang"], job["dstLang"]) != "sidecar":
                continue
            res = store.create("translations", dict(job), provider=counting)
            engines.append(res["properties"]["engine"])
        if counting.calls:
            return False, (f"LLM called {len(counting.calls)}x for sidecar "
                           f"jobs: {counting.calls[0]['user'][:120]!r}")
        return (engines == ["sidecar-fixture", "sidecar-fixture"],
                f"llm_calls=0 engines={engines}")

    def echo_guard_trips():
        # Negative control: a provider that hands the source text straight
        # back must trip the guard into the labeled fallback, never pass
        # as a translation. Deterministic by construction — its own
        # FixtureProvider, whatever mode the run is in.
        job = dict(fixture["jobs"][0])
        echo = FixtureProvider(
            {job["jobId"]: "TRANSLATION: " + job["srcText"]})
        store = make_store(echo, fixture)
        res = store.create("translations", job, provider=echo)
        props = res["properties"]
        return (props["engine"] == "fallback"
                and props["translation"].startswith("[untranslated] "),
                f"engine={props['engine']}")

    return [
        Gate("all_pairs_translate_with_correct_engine", all_pairs_translate),
        Gate("sidecar_tier_never_calls_llm", sidecar_never_calls_llm),
        Gate("echo_guard_rejects_untranslated_output", echo_guard_trips),
    ]


def run(mode="fixture"):
    fixture = load_fixture()
    if mode == "fixture":
        provider = FixtureProvider(fixture["fixture_translations"])
        provider_mode, model = "fixture", "fixture"
    else:
        provider, provider_mode = get_provider()
        model = provider.model
    card = run_gates("02-offline-translate", gates(provider, fixture),
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
