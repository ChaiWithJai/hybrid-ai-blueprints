# CareLine application

This is the application directory. The reader-facing documentation is one level
up and should be read first:

- [Blueprint README](../README.md) — what the agent does, the routes, the
  measured limits, tracing and evaluation.
- [VOICE_CLONE_SETUP.md](../VOICE_CLONE_SETUP.md) — the cloned "call yourself"
  voice, and fine-tuning.
- [IMPLEMENTATION.md](../IMPLEMENTATION.md) — engineering findings and latency
  tables.
- [Hardware matrix](../../../docs/reference/hardware-matrix.md) — which
  accelerators each route runs on.

This page covers only what a developer working inside `app/` needs.

## Run

Use the blueprint wrappers rather than starting uvicorn by hand. They check the
host first and export the environment the speech stack needs, including
`ESPEAK_DATA_PATH`, without which care-mode synthesis kills the server process:

```bash
../scripts/preflight
../scripts/run
open http://localhost:8100
```

Running the module directly works for iteration once preflight passes:

```bash
uv sync
uv run uvicorn careline.main:app --port 8100
```

`docker-compose.yml` builds the server for orchestration parity only. Models
stay native, because MLX needs direct access to Metal.

## End-to-end proof

With the server running:

```bash
uv run python scripts/demo_run.py
```

Three synthetic Dorothy calls, no real personal health information: a baseline
call, a recall call where the agent must reference the recital from call 1
unprompted, and a decline scenario that must fire exactly one escalation alert.
It also asserts the first-call greeting invents no shared history and that
healthy calls stay alert-free. Exits non-zero on any failure.

That last assertion exists because the agent did invent shared history on a
first call, and every automated evaluator passed the run anyway.

## Layout

| Path | Contents |
| --- | --- |
| `careline/` | the application: `main.py` routes, `agent.py` call loop, `llm.py` tiers, `tts.py`, `stt.py`, `memory.py`, `tracing.py` |
| `scripts/` | demo, corpus recording, dataset build, fine-tuning, checkpoint generation, similarity scoring, trace evaluation |
| `scripts/voice_corpus/` | the prompt list used to record a reference corpus |
| `web/` | browser client |
| `voices/` | reference audio and checkpoints. Gitignored: biometric data |
| `results*/` | training checkpoints. Gitignored: hundreds of megabytes each |

## Environment

Model tiers, speech backends, and tracing variables are documented in the
[blueprint README](../README.md). The rest:

| Variable | Default | Meaning |
| --- | --- | --- |
| `CARELINE_ALERT_THRESHOLD` | `3` | concern score at which an alert fires |
| `CARELINE_ALERT_WEBHOOK` | unset | optional POST sink for alerts |
| `CARELINE_DB` | `careline.db` beside this directory | SQLite path |
| `CARELINE_TTS_MODEL` | `mlx-community/Kokoro-82M-bf16` | care-voice model |

## Dependencies

`scripts/run` calls `uv sync`, which removes anything not declared in
`pyproject.toml`. Installing a package by hand and then running the server will
uninstall it, and the failure surfaces later as an HTTP 503 from a backend that
imported fine a moment earlier. Declare new runtime dependencies in
`pyproject.toml`.

Training dependencies are deliberately kept in a separate virtual environment
outside this directory for the same reason; see
[VOICE_CLONE_SETUP.md](../VOICE_CLONE_SETUP.md#fine-tuning).
