# CareLine — eldercare voice check-in agent (Mac prototype)

B2B wellness check-in agent for home-health / senior-living care teams. This is
the **M4 Pro prototype rig** for the GB10 hackathon (2026-08-22): it proves the
logic loop — scripted call → transcript → memory write → next call references
it → decline detection → escalation alert — with Mac-friendly component swaps.
It is **not** the submission; the submission runs the NIM blueprint stack on the
GB10 with OpenShell (sandbox) + OpenClaw (escalation gateway).

> Note: this project lives in `~/projects/careline` (NOT `~/Documents`) because
> a broken file-sync provider on this machine hangs reads under
> `~/Documents/qedc` — see `brctl status` (blocked-app-uninstalled).

## Platform strategy — dependency inversion at the voice seam

CareLine runs on two accelerator ecosystems on purpose: **Apple Metal**
(mlx-audio/MLX + Ollama) for the consumer base — which we expect to grow
substantially over the next 9 months, and where PrismML builds working demos —
and **NVIDIA** (NIM microservices) for enterprise and the GB10 competition
build. Every hardware-touching capability sits behind an interface
(`tts.TTSBackend`, the OpenAI-compatible LLM client): the app and browser code
depend on the abstraction, never the vendor. Saturday (2026-08-22, AGI House
hackathon w/ LM Studio ecosystem) we flip `CARELINE_TTS_BACKEND=nim` +
`CARELINE_LLM_BASE_URL=<NIM>` and the same app runs under competition
constraints on the GB10.

Bonsai models (imported from local GGUFs, `bonsai-8b` in Ollama) are part of
the ecosystem story (Prince Canuma, mlx-audio's author, is a strong community
user) and are used as **super-scoped coding subagents** for MLX/NVIDIA snippet
tasks: one small function per prompt, always reviewed — they produce subtle
bugs (off-by-one clipping, duplicated tokens) when asked to reason at length.

## Component map

| Slot | GB10 (submission) | This prototype |
|---|---|---|
| LLM | Nemotron 3 Nano 30B A3B (NIM, NVFP4) | Qwen2.5-7B via Ollama (native, Metal) |
| ASR | Multilingual ASR NIM | Browser Web Speech API (→ MLX Whisper next) |
| TTS | Magpie TTS NIM (`CARELINE_TTS_BACKEND=nim`) | Kokoro-82M via mlx-audio on Metal (default) |
| Memory | mem0/Letta | SQLite (`careline.db`), same fact-per-call shape |
| Escalation | OpenClaw → Telegram | Alert log + optional `CARELINE_ALERT_WEBHOOK` |
| Sandbox | OpenShell | n/a on Mac |

## Run (native, fastest for dev)

```bash
ollama pull qwen2.5:7b          # once
uv sync
uv run uvicorn careline.main:app --port 8100
open http://localhost:8100      # care-team console UI
```

## Run (Docker parity — orchestration only, models stay native)

```bash
docker compose up --build
```

## End-to-end proof

With the server running:

```bash
uv run python scripts/demo_run.py
```

Runs three synthetic Dorothy calls (no real PHI): a fine baseline call, a
recall call where the agent should mention the recital from call 1, and a
decline scenario that must fire exactly one escalation alert. Also asserts the
first-call greeting invents no shared history and healthy calls stay
alert-free. Exits non-zero on any failure.

## Env

- `CARELINE_LLM_BASE_URL` (default `http://localhost:11434/v1`) — any OpenAI-compatible endpoint; point at the Nemotron NIM on the GB10.
- `CARELINE_LLM_MODEL` (default `qwen2.5:7b`)
- `CARELINE_ALERT_WEBHOOK` — optional POST sink for alerts (OpenClaw/Telegram stand-in)
- `CARELINE_ALERT_THRESHOLD` (default 3)
- `CARELINE_DB` — SQLite path
