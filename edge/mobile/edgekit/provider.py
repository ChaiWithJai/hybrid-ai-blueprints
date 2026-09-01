"""Model providers.

BonsaiProvider speaks the OpenAI-compatible chat API on IPv4 loopback only,
mirroring the loopback constraint the deal-room blueprint enforces. The
FixtureProvider returns preregistered outputs so every demo's test suite is
deterministic with no model server running. Which provider served a run is
always recorded — a fixture run must never be mistaken for a model run.
"""

import json
import time
import urllib.request
import urllib.error

DEFAULT_BASE = "http://127.0.0.1:1234"
DEFAULT_MODEL = "1.7b"  # the strategy tier; see edge/mobile/README.md


class ProviderError(RuntimeError):
    pass


class BonsaiProvider:
    """Live model calls against a local LM Studio-compatible endpoint."""

    mode = "live"

    def __init__(self, base_url=DEFAULT_BASE, model=DEFAULT_MODEL, timeout=120):
        if not (base_url.startswith("http://127.0.0.1")
                or base_url.startswith("http://[::1]")):
            raise ProviderError("local provider must be a loopback address")
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self.last_latency_ms = None

    @classmethod
    def available(cls, base_url=DEFAULT_BASE, model=DEFAULT_MODEL):
        try:
            with urllib.request.urlopen(base_url.rstrip("/") + "/v1/models",
                                        timeout=3) as resp:
                ids = [m["id"] for m in json.load(resp).get("data", [])]
            return model in ids
        except (urllib.error.URLError, OSError, ValueError, KeyError):
            return False

    def chat(self, system, user, max_tokens=400, temperature=0.2):
        payload = json.dumps({
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "max_tokens": max_tokens,
            "temperature": temperature,
        }).encode("utf-8")
        req = urllib.request.Request(
            self.base_url + "/v1/chat/completions",
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        started = time.monotonic()
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                body = json.load(resp)
        except (urllib.error.URLError, OSError) as exc:
            raise ProviderError(f"model call failed: {exc}") from exc
        self.last_latency_ms = round((time.monotonic() - started) * 1000, 1)
        try:
            return body["choices"][0]["message"]["content"].strip()
        except (KeyError, IndexError) as exc:
            raise ProviderError(f"malformed completion: {body}") from exc


class FixtureProvider:
    """Deterministic provider for tests.

    `responses` maps a substring key to a canned output; the first key found
    in the user prompt wins. A `default` key catches the rest. Missing
    fixtures raise — silent fallthrough would hide broken routing.
    """

    mode = "fixture"
    model = "fixture"

    def __init__(self, responses):
        self.responses = dict(responses)
        self.calls = []
        self.last_latency_ms = 0.0

    def chat(self, system, user, max_tokens=400, temperature=0.2):
        self.calls.append({"system": system, "user": user})
        for key, out in self.responses.items():
            if key != "default" and key in user:
                return out
        if "default" in self.responses:
            return self.responses["default"]
        raise ProviderError(f"no fixture matches prompt: {user[:120]!r}")


def get_provider(fixtures=None, model=DEFAULT_MODEL):
    """Return (provider, mode). Live Bonsai when reachable, else fixtures.

    Tests that must be deterministic pass `fixtures` and get the
    FixtureProvider unconditionally.
    """
    if fixtures is not None:
        return FixtureProvider(fixtures), "fixture"
    if BonsaiProvider.available(model=model):
        return BonsaiProvider(model=model), "live"
    raise ProviderError(
        "no provider: model server unreachable and no fixtures supplied")
