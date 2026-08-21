"""CareLine API + demo UI server."""

import os
import re

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
    # Warm the clone model so the first spoken turn does not pay the cold load.
    if hasattr(CLONE_TTS, "_preload"):
        asyncio.create_task(CLONE_TTS._preload())
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


def _split_sentences(text: str) -> list[str]:
    # Must mirror splitSentences() in web/index.html — the UI requests TTS
    # per sentence, so the greeting cache has to be keyed the same way.
    parts = re.findall(r"[^.!?]+[.!?]+[\"'”]?|[^.!?]+$", text)
    return [p.strip() for p in parts if p.strip()] or [text]


@app.post("/api/calls/prepare")
async def prepare_call(body: StartCall):
    session = CallSession(body.resident_id, body.name, mode=body.mode)
    greeting = await session.open_call()
    try:
        for sentence in _split_sentences(greeting):
            TTS_CACHE[sentence] = await _voice_for(body.mode).synthesize(sentence)
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
