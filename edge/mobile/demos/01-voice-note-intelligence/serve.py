"""Awaaz — demo 01's app, served.

Wraps the tested pipeline (app.py) behind a tiny stdlib HTTP server so the
critical workflow runs in a browser: voice notes arrive, transcripts and
summaries are made on-device, replies queue offline and send themselves.

    python3 serve.py            # auto: live Bonsai 1.7b if up, else fixtures
    python3 serve.py fixture    # deterministic
    open http://127.0.0.1:8031
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

PORT = 8031
DESIGN = os.path.abspath(os.path.join(HERE, "..", "..", "design"))

REPLY_SCRIPTS = [
    {"lang": "bn", "senderName": "You",
     "transcript": "টাকা পেয়েছি মা, ওষুধ কাল কিনব। চিন্তা কোরো না।"},
    {"lang": "es", "senderName": "You",
     "transcript": "Recibido, mija. Aparto lo de las medicinas y te aviso."},
    {"lang": "ur", "senderName": "You",
     "transcript": "ٹھیک ہے بیٹا، جمعرات کو عدنان کے ساتھ چلی جاؤں گی۔"},
]


class AppState:
    def __init__(self, mode):
        self.lock = threading.Lock()
        self.fixture = app.load_fixture()
        if mode == "live":
            self.provider = BonsaiProvider()
        else:
            self.provider = FixtureProvider(self.fixture["fixture_summaries"])
        self.mode = mode
        self.store = app.make_store(self.provider, self.fixture)
        self.pending = list(self.fixture["notes"])
        self.reply_i = 0

    def snapshot(self):
        notes = self.store.query("voice_notes")
        return {
            "mode": self.mode,
            "model": getattr(self.provider, "model", "fixture"),
            "online": self.store.online,
            "remaining": len(self.pending),
            "notes": [{"id": n["id"], "sync_state": n["sync_state"],
                       **n["properties"]} for n in notes],
        }

    def receive_next(self):
        if not self.pending:
            return None
        note = self.pending.pop(0)
        return self.store.create("voice_notes", dict(note),
                                 provider=self.provider)

    def reply(self):
        script = dict(REPLY_SCRIPTS[self.reply_i % len(REPLY_SCRIPTS)])
        self.reply_i += 1
        script.update(audioRef=f"reply-{self.reply_i:03d}.ogg",
                      durationMs=9000, direction="out")
        return self.store.create("voice_notes", script,
                                 provider=self.provider)


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
        body = json.loads(self.rfile.read(n) or b"{}") if n else {}
        with STATE.lock:
            if self.path == "/api/receive":
                res = STATE.receive_next()
                self._send(200, {"received": bool(res), **STATE.snapshot()})
            elif self.path == "/api/reply":
                STATE.reply()
                self._send(200, STATE.snapshot())
            elif self.path == "/api/network":
                STATE.store.set_online(bool(body.get("online")))
                delivered = STATE.store.sync()
                self._send(200, {"delivered": delivered, **STATE.snapshot()})
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
    print(f"Awaaz on http://127.0.0.1:{PORT}  (mode: {requested})")
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
