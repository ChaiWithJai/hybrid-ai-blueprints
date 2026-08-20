# CareLine implementation record

**Date:** 2026-08-19 · **Hardware:** MacBook Pro M4 Pro, 24 GB unified memory ·
**Context:** prototype rig for the GB10 hackathon (2026-08-22, AGI House), and
the first self-contained consumer-edge blueprint in this catalog.

Every latency claim below reproduces on the stated hardware with
`scripts/preflight`, `scripts/run`, and `scripts/verify`; the engineering
findings record what those numbers cost to obtain. This is a development
record, not release evidence (see `evals/benchmark.yaml` for release state).

## What it is

A voice check-in agent for care teams (B2B eldercare framing) with a consumer
twist: a **"call yourself" mode** that speaks in the user's own cloned voice —
a self-compassion ritual aimed at elder care, substance-abuse recovery, and
mental-health verticals. Everything runs on-device: LLMs, TTS, STT, voice
cloning, memory. No audio or text ever leaves the machine.

Core loop: call → transcript → fact extraction → SQLite memory → next call
references it ("you mentioned Emily's recital on Saturday") → keyword/threshold
decline detection → escalation webhook (OpenClaw/Telegram gateway on the GB10).

## The stack, and the seams that make it hybrid

| Slot | Consumer edge (this machine) | Enterprise edge (GB10, Saturday) | Seam |
|---|---|---|---|
| Fast LLM (routine turns) | Qwen2.5-7B, Ollama, Metal | Nemotron Nano 30B A3B NIM | `CARELINE_LLM_BASE_URL` (OpenAI-compat) |
| Strong LLM (concern + extraction) | **Ternary-Bonsai-27B** (~1.7 bpw), PrismML llama.cpp fork | same model, CUDA build | `CARELINE_LLM_STRONG_BASE_URL` |
| TTS | Kokoro-82M via mlx-audio | Magpie TTS NIM | `tts.TTSBackend` / `CARELINE_TTS_BACKEND` |
| Voice clone | CSM-1B via mlx-audio (`ref_audio`) | (same, CUDA) | `tts.CsmCloneBackend` |
| STT | Whisper large-v3-turbo via mlx-audio | Multilingual ASR NIM | `stt.STTBackend` / `CARELINE_STT_BACKEND` |
| Memory | SQLite, facts-per-call | mem0/Letta-compatible shape | module boundary |

The **by-stakes router** is the interesting architectural piece: routine turns
go to the fast model (~0.6 s); the moment the concern score rises above zero,
the strong 27B "leans in" for the delicate turns; end-of-call extraction always
uses the strong model with a thinking budget, because its latency is hidden
after hangup. If the strong endpoint is down the router falls back silently —
a router must never break a live call.

## Measured performance (final, warm)

| Stage | Latency |
|---|---|
| Start call (greeting precomputed on page load) | **0.002–0.03 s** |
| Routine turn (Qwen) | 0.6 s |
| Strong turn (Bonsai-27B, thinking off, 120-token cap) | 5–9 s |
| STT (Whisper turbo) | ~1 s |
| TTS (Kokoro) | 0.1–0.2 s |
| Clone TTS (CSM-1B), short sentence | ~5 s |
| Clone TTS, long reply (~18 s audio) | 55–70 s |
| Extraction (27B + 512-token thinking, post-hangup) | ~37 s |

Memory footprint with everything resident (Qwen 4.7 GB + Bonsai ~7 GB +
Kokoro + Whisper + CSM): comfortably inside 24 GB.

## Findings worth stealing (each cost real debugging time)

1. **Ternary/1-bit quants are fork-only.** Bonsai's `Q1_0`/`TQ2_0` (g128)
   formats exist only in PrismML's llama.cpp fork; stock Ollama fails with
   "tensor size overflow" — or worse, *appears* to import and then produces
   subtly broken output. Run Bonsai on the vendor fork's `llama-server`, never
   through Ollama.
2. **Thinking-off has exactly one working mechanism on Bonsai-27B.** Server
   `--reasoning-budget 0` and per-request `thinking_budget_tokens: 0` both
   fail: the model keeps reasoning into `reasoning_content` and, under a
   `max_tokens` cap, returns an **empty reply** (all tokens burned thinking).
   A small positive budget (64) is worse — truncated reasoning leaks into the
   spoken reply. The fix is template-level:
   `"chat_template_kwargs": {"enable_thinking": false}` (Qwen3-family
   template). This contradicts the vendor AGENTS.md ("0 = off") — reported
   upstream.
3. **Reasoning models ignore brevity instructions.** With thinking disabled,
   Bonsai free-runs 500–1500 content tokens at ~15 tok/s regardless of "one or
   two sentences" in the system prompt. A hard `max_tokens: 120` enforces the
   conversational register deterministically.
4. **Budget the thinking per path, not globally.** Live turns: thinking off.
   Post-hangup extraction: `thinking_budget_tokens: 512` (positive caps work
   fine). Same model, same server, ~6× latency difference where it matters.
5. **`--parallel 1` for single-caller voice agents.** Multi-slot llama-server
   picks slots by LRU, so consecutive turns land on different slots and lose
   the KV prefix cache. Single-slot made strong turns drop 8.8 → 6.0 → 5.2 s
   across a call.
6. **Precompute the greeting.** The first turn was the worst turn (LLM + TTS
   serial, 4–45 s depending on voice). Pre-opening the session on page load —
   greeting text *and* audio cached, re-prepared after every hangup — makes
   "start call" instant even in the cloned voice.
7. **Clone latency scales with output length, not input.** CSM-1B: ~5 s for a
   short sentence, ~70 s for a paragraph. A two-sentence reply cap isn't just
   style — it's what makes cloned-voice conversation viable at all.
8. **Deterministic beats clever for safety.** Decline detection is a weighted
   keyword scorer over the transcript, not an LLM judgment: it cannot be
   charmed out of escalating, it is explainable to a care team, and it costs
   nanoseconds. Alerts debounce per severity level per call.
9. **Guard the extraction path.** A reasoning model wraps JSON in fences and
   prose; a naive parser silently returned `{}` and dropped the memory write —
   the product's centerpiece — while every dashboard stayed green. Fix:
   brace-matching extraction plus retry-on-fallback-model. Memory writes must
   never fail silently.
10. **MLX models are thread-sticky.** MLX binds GPU streams to the thread that
    created the model. Dispatching inference through a default thread pool
    works on the first call and then dies with
    `RuntimeError: There is no Stream(gpu, N) in current thread` when a later
    call lands on a different thread — and a failed load can poison subsequent
    loads. Give every MLX model a dedicated single-thread executor
    (`ThreadPoolExecutor(max_workers=1)`) for its entire lifecycle.
11. **Environment hazards are real engineering.** This build survived: an
    uninstalled file-sync provider leaving `~/Documents` with reads that hang
    forever (moved the project out; diagnose with `sample <pid>` showing a
    process stuck in `read()`); an HF cache symlinked to a sometimes-unmounted
    external drive (code falls back to a local cache dir); and a port
    collision with an unrelated llama-server (made the vendor script's port
    env-overridable rather than killing an unknown workload).

## The high-end-consumer logic

**Mac (today's demo):** unified memory is the unlock. 24 GB holds a 27B-class
ternary model *plus* a 7B sidekick *plus* three speech models, all
Metal-accelerated, with ~273 GB/s bandwidth setting the decode ceiling. MLX is
the ecosystem bet — PrismML forked MLX itself to ship 1-bit/2-bit Metal
kernels, and mlx-audio gives TTS/STT/cloning in one package. This is the
fastest-growing install base for local AI, and it's where privacy-sensitive
consumer products (voice, health, memory) should demo.

**NVIDIA (Saturday):** the GB10's 128 GB and NVFP4 run the enterprise version
of the same architecture — NIM microservices for LLM/ASR/TTS, OpenShell
sandboxing, OpenClaw escalation — under competition constraints. Bonsai's fork
ships CUDA kernels too (third parties already benchmark 1.76× on H100), so
even the strong model can stay identical across tiers.

Because every seam is an interface, the tier flip is:
`CARELINE_LLM_BASE_URL`, `CARELINE_LLM_STRONG_BASE_URL`,
`CARELINE_TTS_BACKEND=nim`, `CARELINE_STT_BACKEND=nim`. The browser client and
the agent logic do not change by one line.

## Ethics posture ("call yourself" mode)

Self-voice cloning is consented by construction and disclosed in the product's
own prompt ("this call speaks in their cloned voice, and they know it"). Any
other person's voice requires documented consent **and** disclosure to the
listener — a cloned family voice presented as actually-them is a hard no.
Clinical claims stay modest: it is a wellness ritual with crisis-escalation
defaults, not a treatment. Voice references are biometric data and are
gitignored, never committed.
