"""Voice capture (speech-to-text) behind the same dependency-inverted seam as tts.py.

Apple Metal path: Whisper via mlx-audio, in-process. This is the measured one.
NVIDIA path: the Multilingual ASR NIM behind CARELINE_STT_NIM_URL, implemented
but never run against a live endpoint. The browser records audio and POSTs it to
/api/stt either way -- the client never knows which accelerator transcribed it.
"""

import asyncio
import os
import tempfile
from abc import ABC, abstractmethod

import httpx

from . import tracing
from .tts import _SingleThreadMlx  # MLX work must stay on one dedicated thread


class STTBackend(ABC):
    @abstractmethod
    async def transcribe(self, audio: bytes, mime: str) -> str:
        """Return the transcript for an audio blob (wav/webm/ogg)."""


class MlxWhisperBackend(_SingleThreadMlx, STTBackend):
    MODEL_ID = os.environ.get(
        "CARELINE_STT_MODEL", "mlx-community/whisper-large-v3-turbo-asr-fp16"
    )
    LOCAL_HF_HOME = os.path.expanduser("~/.cache/huggingface-local")  # same T7 fallback as tts.py

    _EXT = {"audio/webm": ".webm", "audio/ogg": ".ogg", "audio/wav": ".wav", "audio/mp4": ".mp4"}

    def _load(self):
        from mlx_audio.stt.generate import load_model

        try:
            return load_model(self.MODEL_ID)
        except (PermissionError, OSError):
            os.environ["HF_HOME"] = self.LOCAL_HF_HOME
            return load_model(self.MODEL_ID)

    def _transcribe(self, audio: bytes, mime: str) -> str:
        from mlx_audio.stt.generate import generate_transcription

        suffix = self._EXT.get(mime.split(";")[0], ".webm")
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as f:
            f.write(audio)
            path = f.name
        try:
            with tempfile.TemporaryDirectory() as tmp:
                result = generate_transcription(
                    model=self._model,
                    audio=path,
                    output_path=os.path.join(tmp, "transcript"),
                    format="txt",
                    verbose=False,
                )
            return (getattr(result, "text", "") or "").strip()
        finally:
            os.unlink(path)

    async def transcribe(self, audio: bytes, mime: str) -> str:
        with tracing.span("stt.whisper", kind="LLM",
                          **{"careline.backend": "mlx-whisper", "careline.bytes": len(audio)}):
            async with self._lock:
                if self._model is None:
                    self._model = await self._run(self._load)
                return await self._run(self._transcribe, audio, mime)


class NimAsrBackend(STTBackend):
    """NVIDIA path: Multilingual ASR NIM over HTTP.

    Implemented against the documented NIM request shape but never exercised
    against a live endpoint. Raises rather than falling back so a partial
    configuration fails loudly.
    """

    NIM_URL = os.environ.get("CARELINE_STT_NIM_URL", "")

    async def transcribe(self, audio: bytes, mime: str) -> str:
        if not self.NIM_URL:
            raise RuntimeError("Set CARELINE_STT_NIM_URL to the ASR NIM endpoint")
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(self.NIM_URL, content=audio, headers={"Content-Type": mime})
            resp.raise_for_status()
            return resp.json().get("text", "")


def get_backend() -> STTBackend:
    choice = os.environ.get("CARELINE_STT_BACKEND", "mlx")
    return NimAsrBackend() if choice == "nim" else MlxWhisperBackend()
