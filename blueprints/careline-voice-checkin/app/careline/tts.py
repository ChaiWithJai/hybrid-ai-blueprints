"""Voice synthesis behind a dependency-inverted seam.

PLATFORM STRATEGY: CareLine targets two accelerator ecosystems. Apple Metal
(mlx-audio/MLX) serves the consumer install base and is the only configuration
that has been measured. NVIDIA NIM microservices serve enterprise and
data-centre hosts.

Callers depend only on TTSBackend, so selecting MagpieNimBackend with
CARELINE_TTS_BACKEND=nim moves synthesis to NVIDIA without touching the app or
the browser client. That path is implemented but has never been run against a
live NIM endpoint. The cloned-voice backends below are MLX-only and have no
NVIDIA equivalent. See docs/reference/hardware-matrix.md.
"""

import asyncio
import glob
import os
import tempfile
from abc import ABC, abstractmethod
from concurrent.futures import ThreadPoolExecutor

import httpx

from . import tracing


def normalize_for_speech(text: str) -> str:
    """Collapse whitespace before synthesis.

    LLM replies arrive with embedded newlines ("...today.  \nWhat's one thing").
    Speech models render those as pauses: measured on CSM-1B, the same 14 words
    took 5.20s with a newline and 4.64s without -- 0.56s of dead air the caller
    hears as the voice stalling mid-reply. Nothing downstream wants line breaks,
    so strip them once, here, rather than in each backend.
    """
    return " ".join((text or "").split())


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
        text = normalize_for_speech(text)
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

    # FEW-SHOT CONTEXT. CSM is a *conversational* model: generate() takes
    # `context: List[Segment]`, and a single ref_audio/ref_text pair is just the
    # degenerate one-segment case --
    #     if len(context) == 0 and ref_audio and ref_text:
    #         context = [Segment(speaker, ref_text, ref_audio)]
    # Passing several short real utterances instead conditions the model the way
    # it was designed to be conditioned. Point this at a directory of
    # <id>.wav + <id>.normalized.txt pairs (what scripts/record_voice_corpus.py
    # produces); empty or missing falls back to the single-reference path.
    CONTEXT_DIR = os.environ.get(
        "CARELINE_CLONE_CONTEXT_DIR",
        os.path.expanduser("~/careline-ft/recorded"),
    )
    CONTEXT_N = int(os.environ.get("CARELINE_CLONE_CONTEXT_N", "6"))
    # Only condition on clips in the target register. The corpus ends with a
    # phonetic-coverage section ("Thirty thieves thought they thrilled the
    # throne", numbers, consonant clusters) which is useful for TRAINING breadth
    # and actively wrong as conversational context for a warm check-in voice.
    # Sections are read from the corpus file so this self-corrects if it changes.
    CONTEXT_SECTIONS = tuple(
        x.strip() for x in os.environ.get("CARELINE_CLONE_CONTEXT_SECTIONS", "A,B").split(",")
    )
    CORPUS = os.environ.get(
        "CARELINE_CLONE_CORPUS",
        os.path.join(os.path.dirname(__file__), "..", "scripts", "voice_corpus", "prompts.txt"),
    )
    # Context costs tokens on every call, so prefer short clips: 2-4s carries
    # prosody without paying for a long prefix.
    CONTEXT_MIN_S = float(os.environ.get("CARELINE_CLONE_CONTEXT_MIN_S", "2.0"))
    CONTEXT_MAX_S = float(os.environ.get("CARELINE_CLONE_CONTEXT_MAX_S", "4.0"))

    def __init__(self):
        super().__init__()
        self._ref_text: str | None = None  # read lazily: the reference files are
        # personal biometric data, gitignored — a fresh clone must still boot.
        self._context = None  # built once on the MLX thread

    def _eligible_indices(self) -> set[int] | None:
        """Prompt indices belonging to CONTEXT_SECTIONS, or None if unknown.

        Recorded clips are named rec<NNN>_<hash>.wav where NNN is the prompt's
        position in the corpus, so the corpus file is the source of truth for
        which clips are in which register.
        """
        try:
            lines = open(self.CORPUS).read().splitlines()
        except OSError:
            return None
        keep, idx, section = set(), 0, None
        for line in lines:
            t = line.strip()
            if t.startswith("# ---- "):
                section = t.strip("# -").split(".")[0].strip()
                continue
            if not t or t.startswith("#"):
                continue
            if section in self.CONTEXT_SECTIONS:
                keep.add(idx)
            idx += 1
        return keep or None

    def _build_context(self):
        """Build few-shot Segments from a directory of wav+transcript pairs."""
        import glob as _glob
        import re as _re
        import wave as _wave

        if self._context is not None:
            return self._context
        self._context = []
        if not self.CONTEXT_DIR or not os.path.isdir(self.CONTEXT_DIR):
            return self._context

        eligible = self._eligible_indices()
        cands = []
        for wav in sorted(_glob.glob(os.path.join(self.CONTEXT_DIR, "*.wav"))):
            txt = wav[:-4] + ".normalized.txt"
            if not os.path.exists(txt):
                continue
            m = _re.search(r"rec(\d+)_", os.path.basename(wav))
            if eligible is not None and m and int(m.group(1)) not in eligible:
                continue  # wrong register for conversational conditioning
            try:
                with _wave.open(wav) as h:
                    dur = h.getnframes() / h.getframerate()
            except Exception:
                continue
            if self.CONTEXT_MIN_S <= dur <= self.CONTEXT_MAX_S:
                cands.append((wav, txt))

        # Spread the picks across the eligible range instead of taking the first
        # N consecutive ones: consecutive prompts share a contour (all greetings,
        # or all questions), and the point of context is prosodic variety.
        if cands and self.CONTEXT_N < len(cands):
            step = len(cands) / self.CONTEXT_N
            cands = [cands[int(i * step)] for i in range(self.CONTEXT_N)]

        for wav, txt in cands[: self.CONTEXT_N]:
            try:
                body = open(txt).read().strip()
                if not body:
                    continue
                self._context.append(
                    self._model.prepare_prompt(body, 0, wav, self._model.sample_rate)
                )
            except Exception:
                continue  # a bad clip must not break synthesis
        return self._context

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
        import io

        import numpy as np
        import soundfile as sf

        ctx = self._build_context()
        kwargs = dict(text=text, speaker=0)
        if ctx:
            kwargs["context"] = ctx
        else:
            # no context corpus available -> original single-reference behaviour
            kwargs["ref_audio"] = self.REF_AUDIO
            kwargs["ref_text"] = self._load_ref_text()
        # Budget the cap from the text: the 90s default lets a short reply run
        # away, and every extra second costs ~1.3x realtime to synthesize.
        kwargs["max_audio_length_ms"] = min(
            30_000.0, max(4_000.0, len(text.split()) / 165 * 60 * 1000 * 1.6)
        )

        chunks = [
            np.asarray(r.audio).reshape(-1)
            for r in self._model.generate(**kwargs)
            if getattr(r, "audio", None) is not None
        ]
        if not chunks:
            raise RuntimeError("csm clone produced no audio")
        wave_out = np.concatenate(chunks) if len(chunks) > 1 else chunks[0]
        buf = io.BytesIO()
        sf.write(buf, wave_out, int(self._model.sample_rate),
                 format="WAV", subtype="PCM_16")
        return buf.getvalue()

    async def synthesize(self, text: str) -> bytes:
        text = normalize_for_speech(text)
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
        text = normalize_for_speech(text)
        with tracing.span("tts.clone", kind="LLM",
                          **{"careline.backend": "f5", "careline.chars": len(text)}):
            async with self._lock:
                if self._model is None:
                    self._model = await self._run(self._load)
                return await self._run(self._generate, text)


class MagpieNimBackend(TTSBackend):
    """NVIDIA path: Magpie TTS NIM over HTTP. Same seam as the Metal backends.

    Implemented against the documented NIM request shape but never exercised
    against a live endpoint. Raises rather than falling back so a partial
    configuration fails loudly.
    """

    NIM_URL = os.environ.get("CARELINE_TTS_NIM_URL", "")
    VOICE = os.environ.get("CARELINE_TTS_VOICE", "Magpie-Multilingual.EN-US.Female-1")

    async def synthesize(self, text: str) -> bytes:
        text = normalize_for_speech(text)
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
    """The "call yourself" voice.

    CSM-1B via mlx-audio by default. The whole speech stack then runs on
    mlx-audio -- Kokoro for the care voice, Whisper for capture, CSM for the
    clone -- which keeps the demo on one PrismML-ecosystem library instead of
    mixing in a second inference path for one backend.

    F5 remains available (CARELINE_CLONE_BACKEND=f5) along with its fine-tuned
    checkpoint. Its measured advantages are real and recorded in
    F5CloneBackend: it preserved the reference pitch range where CSM compressed
    it ~32%, and it is roughly 3x faster. Those are the costs of this choice,
    not arguments against it -- so keep both paths working and A/B by ear.
    """
    choice = os.environ.get("CARELINE_CLONE_BACKEND", "csm")
    return F5CloneBackend() if choice == "f5" else CsmCloneBackend()
