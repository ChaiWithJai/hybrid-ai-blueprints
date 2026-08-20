# Changelog

## 0.1.0 — 2026-08-20

Initial prototype, built and profiled in one day on an M4 Pro (24 GB).

- Voice loop: browser mic → Whisper (mlx-audio) → two-model LLM router →
  Kokoro TTS, all local. Sentence-pipeline playback.
- By-stakes router: fast 7B for routine turns; Ternary-Bonsai-27B for
  concern-flagged turns and end-of-call fact extraction, with silent fallback.
- Cross-session memory: dated fact extraction per call, recalled into the next
  call's system prompt. Guarded against silent extraction failure.
- Deterministic decline scoring with per-severity alert debounce and a webhook
  escalation gateway.
- "Call yourself" mode: consented self-voice cloning (CSM-1B) with an instant
  precomputed greeting.
- Findings and measured latencies: see IMPLEMENTATION.md.
