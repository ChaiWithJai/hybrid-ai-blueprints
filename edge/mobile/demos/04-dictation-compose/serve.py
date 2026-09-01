"""Bol — demo 04's app, served.

Wraps the tested pipeline (app.py) behind a tiny stdlib HTTP server so the
critical workflow runs in a browser: hold to speak, a clean written message
comes back, hear it read aloud, send it. Client-only by construction —
`compositions` is sync_mode "none" — so the network toggle changes nothing
but the banner: nothing queues, everything keeps working.

    python3 serve.py            # auto: live Bonsai 1.7b if up, else fixtures
    python3 serve.py fixture    # deterministic
    open http://127.0.0.1:8034
"""

import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.abspath(os.path.join(HERE, "..", "..")))

import app  # noqa: E402
from edgekit import BonsaiProvider, FixtureProvider  # noqa: E402

PORT = 8034
DESIGN = os.path.abspath(os.path.join(HERE, "..", "..", "design"))

# When the user says the uncertain part again, the same words arrive at
# full confidence and go through the real pipeline. This fixture answers
# that repeat run in fixture mode; live mode lets Bonsai clean it for real.
RETRY_CLEANED = {
    "পরশু": ("CLEAN: আপা, টাকাটা কালকে পাঠাবো নাকি পরশু পাঠাবো "
             "বুঝতে পারছি না। তুমি জানাও।"),
}
RETRY_CONFIDENCE = 0.96


class AppState:
    def __init__(self, mode):
        self.lock = threading.Lock()
        self.fixture = app.load_fixture()
        if mode == "live":
            self.provider = BonsaiProvider()
        else:
            self.provider = FixtureProvider(
                {**self.fixture["fixture_cleaned"], **RETRY_CLEANED})
        self.mode = mode
        self.store = app.make_store(self.provider, self.fixture)
        self.pending = list(self.fixture["drafts"])
        self.superseded = set()  # clarify cards replaced by a repeat

    def snapshot(self):
        drafts = [d for d in self.store.query("compositions")
                  if d["id"] not in self.superseded]
        return {
            "mode": self.mode,
            "model": getattr(self.provider, "model", "fixture"),
            "online": self.store.online,
            "remaining": len(self.pending),
            "drafts": [self._row(d) for d in drafts],
        }

    @staticmethod
    def _row(res):
        return {"id": res["id"], "sync_state": res["sync_state"],
                **res["properties"]}

    def dictate_next(self):
        if not self.pending:  # rotate: the demo never runs dry
            self.pending = list(self.fixture["drafts"])
        draft = self.pending.pop(0)
        return self.store.create("compositions", dict(draft),
                                 provider=self.provider)

    def dictate_again(self, resource_id):
        """The user repeated the uncertain part: same words, heard well."""
        props = self.store.get(resource_id)["properties"]
        draft = {"rawTranscript": props["rawTranscript"],
                 "lang": props["lang"], "register": props["register"],
                 "asrConfidence": RETRY_CONFIDENCE}
        res = self.store.create("compositions", draft,
                                provider=self.provider)
        self.superseded.add(resource_id)
        return res

    def approve(self, resource_id):
        self.store.get(resource_id)  # KeyError if unknown
        return self.store.update(resource_id, {"approved": True})


STATE = None


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype="application/json"):
        data = body if isinstance(body, bytes) else \
            json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", f"{ctype}; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            with open(os.path.join(HERE, "web", "index.html"),
                      encoding="utf-8") as fh:
                html = fh.read()
            with open(os.path.join(DESIGN, "sprites.svg"),
                      encoding="utf-8") as fh:
                html = html.replace("<!--SPRITES-->", fh.read())
            self._send(200, html.encode("utf-8"), "text/html")
        elif self.path == "/tokens.css":
            with open(os.path.join(DESIGN, "tokens.css"), "rb") as fh:
                self._send(200, fh.read(), "text/css")
        elif self.path == "/api/state":
            with STATE.lock:
                self._send(200, STATE.snapshot())
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        try:
            body = json.loads(self.rfile.read(n) or b"{}") if n else {}
        except ValueError:
            self._send(400, {"error": "body must be a JSON object"})
            return
        with STATE.lock:
            if self.path == "/api/dictate":
                try:
                    res = (STATE.dictate_again(int(body["retry"]))
                           if body.get("retry") else STATE.dictate_next())
                except KeyError:
                    self._send(404, {"error": "no such draft"})
                    return
                self._send(200, {"draft": STATE._row(res),
                                 **STATE.snapshot()})
            elif self.path == "/api/approve":
                try:
                    res = STATE.approve(int(body.get("id", 0)))
                except KeyError:
                    self._send(404, {"error": "no such draft"})
                    return
                self._send(200, {"draft": STATE._row(res),
                                 **STATE.snapshot()})
            elif self.path == "/api/network":
                STATE.store.set_online(bool(body.get("online")))
                # sync_mode "none": sync() always moves 0 — Bol does not
                # care about the network, and this is the receipt.
                moved = STATE.store.sync()
                self._send(200, {"delivered": moved, **STATE.snapshot()})
            else:
                self._send(404, {"error": "not found"})

    def log_message(self, *a):  # keep the terminal quiet
        pass


def main():
    global STATE
    requested = sys.argv[1] if len(sys.argv) > 1 else "auto"
    if requested == "auto":
        requested = "live" if BonsaiProvider.available() else "fixture"
    STATE = AppState(requested)
    print(f"Bol on http://127.0.0.1:{PORT}  (mode: {requested})")
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
