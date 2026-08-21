"""CareLine API + demo UI server."""

import os

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel

from . import memory, stt, tts
from .agent import CallSession

import asyncio
from contextlib import asynccontextmanager

TTS = tts.get_backend()
STT = stt.get_backend()
CLONE_TTS = tts.get_clone_backend()  # "call yourself" voice; lazy-loads on first use


@asynccontextmanager
async def lifespan(app):
    async def warm():
        """Prewarm with a real synthesis, not just a weight load.

        Loading the model is only part of the first-call cost: the first actual
        synthesis also pays MLX graph compilation, reference-audio decode and
        RMS conditioning, and vocoder setup. Running one throwaway utterance at
        startup moves all of that off the demo's critical path.

        Only the clone voice is warmed. Kokoro is already ~1.5s cold, and
        warming it here would move the espeak-ng failure to STARTUP -- that path
        calls exit() in native C, so a missing system espeak would kill the
        server before it serves anything, which is harder to diagnose than
        failing on the first care-mode turn. scripts/preflight checks for it.
        """
        if hasattr(CLONE_TTS, "_preload"):
            await CLONE_TTS._preload()
        try:
            await CLONE_TTS.synthesize("Warming up.")
        except Exception:
            pass  # a cold first call is a slow demo, not a broken one

    asyncio.create_task(warm())
    yield
    # Shutdown (no-op for now)


app = FastAPI(title="CareLine", lifespan=lifespan)

SESSIONS: dict[str, CallSession] = {}
WEB_DIR = os.path.join(os.path.dirname(__file__), "..", "web")


class StartCall(BaseModel):
    resident_id: str
    name: str
    mode: str = "care"  # "care" (Dorothy demo, Kokoro voice) | "self" (cloned voice)


class Turn(BaseModel):
    text: str
    mode: str = "care"


@app.get("/")
async def index():
    return FileResponse(os.path.join(WEB_DIR, "index.html"))


# Pre-opened sessions keyed by resident: the UI calls /api/calls/prepare on
# page load, so "Start call" returns a ready greeting (text + cached audio)
# instead of paying LLM + TTS latency while the user waits.
PREPARED: dict[str, tuple[CallSession, str]] = {}
TTS_CACHE: dict[str, bytes] = {}


def _voice_for(mode: str) -> tts.TTSBackend:
    return CLONE_TTS if mode == "self" else TTS


@app.post("/api/calls/prepare")
async def prepare_call(body: StartCall):
    session = CallSession(body.resident_id, body.name, mode=body.mode)
    greeting = await session.open_call()
    try:
        # Key on the WHOLE greeting: the client requests one synthesis per reply,
        # so per-sentence keys would never be hit and the precompute would be
        # dead weight -- the greeting would pay full synthesis cost on click.
        voice = _voice_for(body.mode)
        TTS_CACHE[greeting] = await voice.synthesize(greeting)
        while len(TTS_CACHE) > 32:
            TTS_CACHE.pop(next(iter(TTS_CACHE)))
    except Exception:
        import logging

        logging.getLogger("careline").exception("prepare: greeting TTS failed")
    PREPARED[body.resident_id] = (session, greeting)
    return {"prepared": True}


@app.post("/api/calls")
async def start_call(body: StartCall):
    prepared = PREPARED.pop(body.resident_id, None)
    if prepared and prepared[0].mode == body.mode:
        session, greeting = prepared
    else:
        session = CallSession(body.resident_id, body.name, mode=body.mode)
        greeting = await session.open_call()
    SESSIONS[session.id] = session
    return {"call_id": session.id, "greeting": greeting}


@app.post("/api/calls/{call_id}/turn")
async def call_turn(call_id: str, body: Turn):
    session = SESSIONS.get(call_id)
    if not session:
        raise HTTPException(404, "unknown call")
    reply, alert = await session.turn(body.text)
    return {"reply": reply, "alert": alert, "concern_score": session.concern_score}


@app.post("/api/calls/{call_id}/end")
async def call_end(call_id: str):
    session = SESSIONS.pop(call_id, None)
    if not session:
        raise HTTPException(404, "unknown call")
    return await session.end()


@app.get("/api/residents/{resident_id}/memory")
async def resident_memory(resident_id: str):
    return {
        "facts": memory.recall(resident_id, limit=50),
        "calls": memory.recent_calls(resident_id),
    }


@app.get("/api/config")
async def config():
    """Client configuration.

    The self-voice identity is an operator setting, not a constant. A fresh
    clone has no reference recording, so the label stays generic until someone
    sets CARELINE_SELF_NAME -- otherwise every install would show whichever
    name happened to be committed.
    """
    name = os.environ.get("CARELINE_SELF_NAME", "").strip()
    return {
        "self": {
            "name": name or "You",
            "resident_id": "self-" + (name.lower().replace(" ", "-") or "operator"),
            "label": (
                f"Call yourself — {name} (your cloned voice)" if name
                else "Call yourself — your cloned voice"
            ),
        }
    }


@app.get("/api/alerts")
async def alerts():
    return {"alerts": memory.list_alerts()}


@app.post("/api/stt")
async def transcribe(request: Request):
    audio = await request.body()
    if not audio:
        raise HTTPException(400, "empty audio")
    try:
        text = await STT.transcribe(audio, request.headers.get("content-type", "audio/webm"))
    except Exception as e:
        raise HTTPException(503, f"stt backend unavailable: {e}")
    return {"text": text}


@app.post("/api/tts")
async def synthesize(body: Turn):
    cached = TTS_CACHE.pop(body.text, None)
    if cached:
        return Response(content=cached, media_type="audio/wav")
    try:
        wav = await _voice_for(body.mode).synthesize(body.text)
    except Exception as e:
        raise HTTPException(503, f"tts backend unavailable: {e}")
    return Response(content=wav, media_type="audio/wav")
