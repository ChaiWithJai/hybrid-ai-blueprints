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

    async def _preload(self):
        """Warm the model at startup. A clone model cold-loads in 10s+; paying
        that on the first spoken turn is what made "call yourself" feel broken.
        Never fatal: a backend that cannot warm still works on first use."""
        async with self._lock:
            if self._model is None:
                try:
                    self._model = await self._run(self._load)
                except Exception:
                    pass


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

    _response_cache = {}  # Cache common responses (greeting, acknowledgments)

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


def _trim_edges(x, sr: int, thresh: float = 0.006, margin_ms: float = 15.0):
    """Strip leading/trailing near-silence from a synthesized chunk.

    The UI speaks one HTTP request per sentence and plays the chunks back to
    back, so any silence baked into a chunk is ADDED to the natural pause at
    every punctuation mark. F5 emits 300-500 ms of leading silence (the
    duration estimate pads, and the conditioned reference starts with silence),
    which is what makes the delivery feel like it stalls after every period.
    Trimmed here rather than in the client so every consumer benefits.

    A margin is kept so the first phoneme is never clipped -- plosives start
    quiet and cutting them makes speech sound truncated.
    """
    import numpy as np

    if x.size == 0:
        return x
    fl = max(1, int(sr * 0.010))
    n = x.size // fl
    if n < 3:
        return x
    rms = np.sqrt((x[: n * fl].reshape(n, fl) ** 2).mean(axis=1))
    loud = np.nonzero(rms > thresh)[0]
    if loud.size == 0:
        return x  # all quiet: return untouched rather than emit an empty clip
    m = int(sr * margin_ms / 1000)
    start = max(0, loud[0] * fl - m)
    end = min(x.size, (loud[-1] + 1) * fl + m)
    return x[start:end]


class F5CloneBackend(_SingleThreadMlx, TTSBackend):
    """Apple Metal path: F5-TTS via MLX. The better-sounding clone.

    Measured against CsmCloneBackend on the same reference and sentence, CSM
    compressed the reference's pitch range from 118 Hz (p10..p90) to 80 Hz --
    a 32% flattening that reads as monotone. F5 reproduced it (130 Hz) and
    matched the reference's p10 to within 1 Hz. It is also faster: ~5.4 s of
    compute for 4.6 s of audio vs ~16 s for CSM.

    Two contract details cost real debugging time:
      * `duration` is in FRAMES (seconds * FRAMES_PER_SEC) and is the TOTAL of
        reference + generation -- the model conditions on the reference inline
        and the caller slices it back off. Leaving duration=None lets the
        duration predictor return total ~= reference length, which yields
        0.04 s of audio: silence, returned as success.
      * The reference MUST be 24 kHz or the model raises. No resample here on
        purpose: silently resampling a mismatched reference hides a bad input.
    """

    MODEL_ID = os.environ.get("CARELINE_F5_MODEL", "lucasnewman/f5-tts-mlx")
    # Optional fine-tuned weights, overlaid on the pretrained model. Holds only
    # the trainable parameters (the lower blocks stay frozen), so it MUST be
    # loaded with strict=False; a strict load rejects a partial state dict.
    # Unset or missing -> plain zero-shot, which is a supported configuration.
    CHECKPOINT = os.environ.get(
        "CARELINE_F5_CHECKPOINT",
        os.path.join(os.path.dirname(__file__), "..", "voices", "f5_finetuned.safetensors"),
    )
    # Same reference seam as the CSM clone: one recording serves both backends.
    REF_AUDIO = CsmCloneBackend.REF_AUDIO
    REF_TEXT_PATH = CsmCloneBackend.REF_TEXT_PATH
    STEPS = int(os.environ.get("CARELINE_F5_STEPS", "8"))
    SAMPLE_RATE = 24000

    def __init__(self):
        super().__init__()
        self._ref = None  # (mx.array audio, ref_text), loaded lazily: the
        # reference files are personal biometric data and are gitignored.

    def _load(self):
        import logging

        import mlx.core as mx
        from f5_tts_mlx.generate import F5TTS

        model = F5TTS.from_pretrained(self.MODEL_ID)
        if self.CHECKPOINT and os.path.exists(self.CHECKPOINT):
            params = mx.load(self.CHECKPOINT)
            if params:
                model.load_weights(list(params.items()), strict=False)
                model.eval()
                logging.getLogger("careline").info(
                    "f5 clone: overlaid %d fine-tuned tensors from %s",
                    len(params), os.path.basename(self.CHECKPOINT),
                )
        return model

    def _load_ref(self):
        if self._ref is not None:
            return self._ref
        import mlx.core as mx
        import soundfile as sf

        try:
            audio, sr = sf.read(self.REF_AUDIO)
            ref_text = open(self.REF_TEXT_PATH).read().strip()
        except FileNotFoundError as exc:
            raise RuntimeError(
                "self-voice mode needs a reference recording: create "
                "voices/self_ref.wav (24 kHz mono, ~10-15 s of clean speech) "
                "and voices/self_ref.txt (its exact transcript)"
            ) from exc
        if sr != self.SAMPLE_RATE:
            raise RuntimeError(
                f"reference must be {self.SAMPLE_RATE} Hz, got {sr}; re-cut it with "
                f"ffmpeg -ar {self.SAMPLE_RATE} -ac 1"
            )
        if not ref_text:
            raise RuntimeError("voices/self_ref.txt is empty; F5 needs the reference transcript")
        self._ref = (mx.array(audio), ref_text)
        return self._ref

    def _generate(self, text: str) -> bytes:
        import io

        import mlx.core as mx
        import numpy as np
        import soundfile as sf
        from f5_tts_mlx.generate import (
            FRAMES_PER_SEC,
            TARGET_RMS,
            convert_char_to_pinyin,
            estimated_duration,
        )

        audio, ref_text = self._load_ref()
        rms = mx.sqrt(mx.mean(mx.square(audio)))
        if rms < TARGET_RMS:
            audio = audio * TARGET_RMS / rms

        # Total (reference + generation), in frames. See the class docstring.
        total_s = estimated_duration(audio, ref_text, text)
        wave, _ = self._model.sample(
            mx.expand_dims(audio, axis=0),
            text=convert_char_to_pinyin([ref_text + " " + text]),
            duration=int(total_s * FRAMES_PER_SEC),
            steps=self.STEPS,
            method="rk4",
            cfg_strength=2.0,
            sway_sampling_coef=-1.0,
        )
        wave = wave[audio.shape[0] :]  # drop the conditioned reference prefix
        mx.eval(wave)
        if wave.shape[0] < self.SAMPLE_RATE // 10:
            raise RuntimeError(
                f"f5 produced {wave.shape[0] / self.SAMPLE_RATE:.3f}s of audio; "
                "refusing to return near-silence as success"
            )
        out = _trim_edges(np.array(wave), self.SAMPLE_RATE)
        buf = io.BytesIO()
        sf.write(buf, out, self.SAMPLE_RATE, format="WAV", subtype="PCM_16")
        return buf.getvalue()

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


def get_clone_backend() -> TTSBackend:
    """The "call yourself" voice. F5 by default -- see F5CloneBackend for the
    measured reason it replaced CSM. Set CARELINE_CLONE_BACKEND=csm to A/B."""
    choice = os.environ.get("CARELINE_CLONE_BACKEND", "f5")
    return CsmCloneBackend() if choice == "csm" else F5CloneBackend()
