"""Dhaaga — demo 03's app, served.

Wraps the tested pipeline (app.py) behind a tiny stdlib HTTP server so the
critical workflow runs in a browser: one family thread across a
connectivity line. Each send is sealed on-device, crosses the relay as
ciphertext only, and is decrypted + digested on the receiving device.
Cut the wire and the thread keeps working: sends queue, then deliver
themselves when the pipe opens.

    python3 serve.py            # auto: live Bonsai 1.7b if up, else fixtures
    python3 serve.py fixture    # deterministic
    open http://127.0.0.1:8033
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

PORT = 8033
DESIGN = os.path.abspath(os.path.join(HERE, "..", "..", "design"))

# One person plays both ends of the family line. Each press of a speak
# button seals the next scripted line for that side through the REAL
# pipeline: encrypt -> create (relay stores ciphertext) -> decrypt_and_digest
# on the receiving device.
SEND_SCRIPTS = {
    "worker": [
        {"senderName": "Bilal", "lang": "bn",
         "plaintext": "মা, বেতন পেয়েছি। এই শুক্রবার টাকা পাঠাব, ছয়শো "
                      "দিরহাম। শরীরের যত্ন নিও।"},
        {"senderName": "Bilal", "lang": "ur",
         "plaintext": "امی، اوور ٹائم ملا ہے۔ اگلے ہفتے پیسے بھیجوں گا، "
                      "آپ فکر نہ کریں۔"},
        {"senderName": "Bilal", "lang": "es",
         "plaintext": "Mamá, ya cobré la quincena. El sábado te mando dos "
                      "mil pesos para la renta."},
    ],
    "home": [
        {"senderName": "Amma", "lang": "bn",
         "plaintext": "বাবা, টাকা পেয়েছি। ওষুধ কিনেছি, বাকিটা রেখে "
                      "দিয়েছি। ভালো থেকো।"},
        {"senderName": "Amma", "lang": "ur",
         "plaintext": "بیٹا، خط مل گیا۔ عدنان ساتھ گیا تھا، سب کام ہو "
                      "گیا۔ اللہ تمہیں سلامت رکھے۔"},
        {"senderName": "Amma", "lang": "es",
         "plaintext": "Mijo, llegó el depósito. La abuela ya está mejor. "
                      "Cuídate mucho y come bien."},
    ],
}

# Fixture summaries for the scripted lines (keyed on a substring unique to
# each line, grounded in its transcript). Merged BEFORE the fixture-file
# summaries so a shared word can never route to the wrong canned output.
SCRIPT_SUMMARIES = {
    "বেতন": "SUMMARY: বেতন পেয়েছে, শুক্রবার ছয়শো দিরহাম পাঠাবে।"
            "\nNEEDS_REPLY: no",
    "اوور": "SUMMARY: اوور ٹائم ملا، اگلے ہفتے پیسے بھیجے گا۔"
            "\nNEEDS_REPLY: no",
    "quincena": "SUMMARY: Cobró la quincena; el sábado manda dos mil pesos "
                "para la renta.\nNEEDS_REPLY: no",
    "ভালো থেকো": "SUMMARY: টাকা পৌঁছেছে, ওষুধ কেনা হয়েছে, বাকিটা রাখা আছে।"
                 "\nNEEDS_REPLY: no",
    "سلامت": "SUMMARY: خط مل گیا، عدنان ساتھ گیا تھا، سب کام ہو گیا۔"
             "\nNEEDS_REPLY: no",
    "Cuídate": "SUMMARY: Llegó el depósito; la abuela ya está mejor."
               "\nNEEDS_REPLY: no",
}


class AppState:
    def __init__(self, mode):
        self.lock = threading.Lock()
        self.fixture = app.load_fixture()
        if mode == "live":
            self.provider = BonsaiProvider()
        else:
            self.provider = FixtureProvider(
                {**SCRIPT_SUMMARIES, **self.fixture["fixture_summaries"]})
        self.mode = mode
        self.store = app.make_store(self.provider)
        self.script_i = {"worker": 0, "home": 0}

    def snapshot(self):
        envelopes = []
        for r in self.store.query("envelopes"):
            props = dict(r["properties"])
            # The wire bytes are shown only by /api/peek — the timeline
            # renders what the RECEIVING device holds after decryption.
            props.pop("cipherBlob", None)
            envelopes.append({"id": r["id"], "sync_state": r["sync_state"],
                              "who": r["source_ref"] or "worker", **props})
        return {
            "mode": self.mode,
            "model": getattr(self.provider, "model", "fixture"),
            "online": self.store.online,
            "crypto_status": app.CRYPTO_STATUS,
            "envelopes": envelopes,
        }

    def send(self, who):
        scripts = SEND_SCRIPTS[who]
        script = scripts[self.script_i[who] % len(scripts)]
        self.script_i[who] += 1
        return self.store.create("envelopes", app.seal(script),
                                 provider=self.provider, source_ref=who)

    def peek(self, resource_id):
        res = self.store.get(resource_id)
        return {"id": res["id"],
                "sync_state": res["sync_state"],
                "cipherBlob": res["properties"]["cipherBlob"]}


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
        elif self.path.startswith("/api/peek/"):
            try:
                rid = int(self.path.rsplit("/", 1)[1])
                with STATE.lock:
                    self._send(200, STATE.peek(rid))
            except (ValueError, KeyError):
                self._send(404, {"error": "no such envelope"})
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
            if self.path == "/api/send":
                who = body.get("who")
                if who not in SEND_SCRIPTS:
                    self._send(400, {"error": "who must be worker or home"})
                    return
                STATE.send(who)
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
    print(f"Dhaaga on http://127.0.0.1:{PORT}  (mode: {requested})")
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
