"""Voice synthesis behind a dependency-inverted seam.

PLATFORM STRATEGY (2026-08-19): CareLine targets two accelerator ecosystems.
Apple Metal (mlx-audio/MLX, Ollama) serves the consumer install base — which we
expect to grow substantially over the next 9 months — and is where PrismML
develops working demos. NVIDIA (NIM microservices) serves enterprise and the
GB10 competition build. Callers depend only on TTSBackend; on Saturday
(2026-08-22, AGI House hackathon) MagpieNimBackend is selected via
CARELINE_TTS_BACKEND=nim with zero changes to the app or the browser client.
"""

import asyncio
import glob
import os
import tempfile
from abc import ABC, abstractmethod
from concurrent.futures import ThreadPoolExecutor

import httpx


class TTSBackend(ABC):
    @abstractmethod
    async def synthesize(self, text: str) -> bytes:
        """Return WAV bytes for the given text."""


class _SingleThreadMlx:
    """MLX GPU streams are bound to the thread that created the model — all
    load/generate work for one model MUST run on one dedicated thread, or
    later calls die with 'There is no Stream(gpu, N) in current thread'."""

    def __init__(self):
        self._executor = ThreadPoolExecutor(max_workers=1)
        self._lock = asyncio.Lock()
        self._model = None

    async def _run(self, fn, *args):
        return await asyncio.get_running_loop().run_in_executor(self._executor, fn, *args)


class MlxAudioBackend(_SingleThreadMlx, TTSBackend):
    """Apple Metal path: Kokoro-82M via mlx-audio, loaded once, in-process."""

    MODEL_ID = os.environ.get("CARELINE_TTS_MODEL", "mlx-community/Kokoro-82M-bf16")
    VOICE = os.environ.get("CARELINE_TTS_VOICE", "af_heart")
    # ~/.cache/huggingface symlinks to the T7 drive, which is not always
    # mounted; fall back to the local cache dir so TTS never depends on it.
    LOCAL_HF_HOME = os.path.expanduser("~/.cache/huggingface-local")

    def _load(self):
        from mlx_audio.tts.utils import load_model

        try:
            return load_model(self.MODEL_ID)
        except (PermissionError, OSError):
            os.environ["HF_HOME"] = self.LOCAL_HF_HOME
            return load_model(self.MODEL_ID)

    def _generate(self, text: str) -> bytes:
        from mlx_audio.tts.generate import generate_audio

        with tempfile.TemporaryDirectory() as tmp:
            generate_audio(
                text=text,
                model=self._model,
                voice=self.VOICE,
                output_path=tmp,
                file_prefix="out",
                join_audio=True,
                save=True,
                verbose=False,
            )
            wavs = sorted(glob.glob(os.path.join(tmp, "*.wav")))
            if not wavs:
                raise RuntimeError("mlx-audio produced no audio file")
            with open(wavs[0], "rb") as f:
                return f.read()

    async def synthesize(self, text: str) -> bytes:
        async with self._lock:  # MLX generation is not concurrency-safe
            if self._model is None:
                self._model = await self._run(self._load)
            return await self._run(self._generate, text)


class CsmCloneBackend(_SingleThreadMlx, TTSBackend):
    """Self-voice cloning: CSM-1B conditioned on the user's own reference audio.

    Powers "call yourself" mode. Self-voice only by policy — cloning anyone
    else requires their documented consent and disclosure to the listener.
    Slower than Kokoro (clone-class model); the greeting precompute hides most
    of it, and this voice is opt-in per call.
    """

    MODEL_ID = os.environ.get("CARELINE_CLONE_MODEL", "mlx-community/csm-1b")
    REF_AUDIO = os.environ.get(
        "CARELINE_SELF_REF_AUDIO",
        os.path.join(os.path.dirname(__file__), "..", "voices", "self_ref.wav"),
    )
    REF_TEXT_PATH = os.environ.get(
        "CARELINE_SELF_REF_TEXT",
        os.path.join(os.path.dirname(__file__), "..", "voices", "self_ref.txt"),
    )
    LOCAL_HF_HOME = MlxAudioBackend.LOCAL_HF_HOME

    def __init__(self):
        super().__init__()
        self._ref_text: str | None = None  # read lazily: the reference files are
        # personal biometric data, gitignored — a fresh clone must still boot.

    def _load_ref_text(self) -> str:
        if self._ref_text is None:
            try:
                with open(self.REF_TEXT_PATH) as f:
                    self._ref_text = f.read().strip()
            except FileNotFoundError:
                raise RuntimeError(
                    "self-voice mode needs a reference recording: create "
                    "voices/self_ref.wav (~25s of clean speech) and "
                    "voices/self_ref.txt (its transcript)"
                )
        return self._ref_text

    def _load(self):
        from mlx_audio.tts.utils import load_model

        try:
            return load_model(self.MODEL_ID)
        except (PermissionError, OSError):
            os.environ["HF_HOME"] = self.LOCAL_HF_HOME
            return load_model(self.MODEL_ID)

    def _generate(self, text: str) -> bytes:
        from mlx_audio.tts.generate import generate_audio

        with tempfile.TemporaryDirectory() as tmp:
            generate_audio(
                text=text,
                model=self._model,
                ref_audio=self.REF_AUDIO,
                ref_text=self._load_ref_text(),
                output_path=tmp,
                file_prefix="out",
                join_audio=True,
                save=True,
                verbose=False,
            )
            wavs = sorted(glob.glob(os.path.join(tmp, "*.wav")))
            if not wavs:
                raise RuntimeError("csm clone produced no audio")
            with open(wavs[0], "rb") as f:
                return f.read()

    async def synthesize(self, text: str) -> bytes:
        async with self._lock:
            if self._model is None:
                self._model = await self._run(self._load)
            return await self._run(self._generate, text)


class MagpieNimBackend(TTSBackend):
    """NVIDIA path: Magpie TTS NIM on the GB10 (Saturday). Same seam, HTTP out."""

    NIM_URL = os.environ.get("CARELINE_TTS_NIM_URL", "")
    VOICE = os.environ.get("CARELINE_TTS_VOICE", "Magpie-Multilingual.EN-US.Female-1")

    async def synthesize(self, text: str) -> bytes:
        if not self.NIM_URL:
            raise RuntimeError("Set CARELINE_TTS_NIM_URL to the Magpie NIM endpoint")
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                self.NIM_URL, json={"text": text, "voice": self.VOICE, "encoding": "wav"}
            )
            resp.raise_for_status()
            return resp.content


def get_backend() -> TTSBackend:
    choice = os.environ.get("CARELINE_TTS_BACKEND", "mlx")
    return MagpieNimBackend() if choice == "nim" else MlxAudioBackend()
