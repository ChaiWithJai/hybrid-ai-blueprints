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

---

# Session 2 (2026-08-20/21) — voice quality, and corrections to the record above

**Hardware:** the machine used for this session reports **48 GB** unified memory
(`sysctl hw.memsize`), not the 24 GB stated at the top of this document. Every
memory and latency claim above describes different hardware and should be
re-measured before being quoted.

## Corrections to claims above

| Claim above | Correction |
|---|---|
| Bonsai-27B is served on `:8081` | `:8081` serves `Qwen_Qwen3.6-35B-A3B-Q4_K_M.gguf`. The real Ternary-Bonsai-27B is in LM Studio on `:1234` as `27b@q1_0`. `llm.py`'s `bonsai-27b` alias therefore points at a Qwen model. |
| `chat_template_kwargs: {enable_thinking: false}` is *the* thinking-off fix | True for the llama.cpp fork on `:8081`. **LM Studio ignores it.** There, the model always reasons first, so `max_tokens` must cover reasoning *and* the answer — a 300-token cap returned an empty reply with every token spent thinking. 3000 worked. |
| "Clone TTS (CSM-1B) ~5 s short sentence / 55–70 s long reply" | Superseded: the clone backend is now F5-TTS. ~5 s of compute for ~4.6 s of audio (RTF ~1.2), including long replies. |

## CSM-1B → F5-TTS

CSM-1B was replaced for `mode: "self"`. Measured on one reference and sentence:

| | pitch range p10–p90 | speaker cosine | compute / 4.5 s audio |
|---|---|---|---|
| reference (real voice) | 118 Hz | — | — |
| **F5-TTS (MLX)** | **130 Hz** | 0.93 | **~5 s** |
| CSM-1B | 80 Hz (−32 %) | 0.92 | ~16 s |

The finding worth keeping: **both models reproduced speaker identity equally
well** (0.92 vs 0.93, and a different-speaker floor control sat at 0.47). What
CSM degraded was **prosody** — it compressed the pitch range by a third, heard
as monotone. Speaker-similarity metrics are blind to this, so a clone can score
at the ceiling and still sound bad. Identity and naturalness need separate
measurements.

## Two bugs that returned success while broken

1. **Silence as HTTP 200.** F5's duration predictor returned a total ≈ the
   reference length, leaving ~zero frames for new speech: 0.04 s of audio,
   status 200. `duration` is **total (reference + generated) in frames** and the
   caller slices the reference back off. Derive it from `estimated_duration()`;
   never leave it unset.
2. **The pause after every punctuation mark.** Each synthesized chunk carried
   300–500 ms of leading silence. The UI requests TTS **per sentence** and plays
   chunks back to back, so that silence was *added* to every natural pause.
   `_trim_edges()` in `tts.py` removes it (15 ms margin kept — plosives start
   quiet and clipping them sounds truncated). Verified 296–473 ms → 0 ms.

## What predicts clone quality

963 candidate segments across 10 recordings were scored acoustically, then a
clone was generated from each of the top 24 and measured against a centroid of
held-out real clips from 5 other recordings.

- **SNR and pitch stability did not predict clone quality.** The
  highest-SNR/steadiest candidate produced one of the worst clones.
- **Speaker-embedding similarity of the *reference* did** (r = 0.77 with the
  similarity of the clone it produced).
- **Transcript quality matters and acoustics cannot see it.** Silence-bounded
  cuts frequently land mid-sentence. Bonsai-27B, reading only transcripts,
  flagged references as "incomplete ending" / "truncated thought" that scored
  fine acoustically — and those had been chosen and shipped twice.
- **Within-recording variance ≈ between-recording variance** (one recording
  spanned rank 5 to rank 23 of 24). One clip does not characterise a session.
- **Scoring above the speaker's own band is channel overfitting**, not
  superhuman fidelity: the clone copies the reference's mic/room/codec, which
  embeddings are sensitive to. Controls (a floor speaker and a leave-one-out
  band) are what make the number mean anything.

**Multiple references do not help zero-shot.** Concatenating the top 3 into one
reference vs the best single clip, 5 seeds each: +0.003 (t = 0.34), i.e. noise.
F5 conditions on one reference; concatenation lengthens it, it does not weight
examples. It did cut variance (sd 0.019 → 0.006–0.012), so it buys consistency.

## Fine-tuning: implemented, not yet a win

`scripts/finetune_voice.py` + `scripts/build_ft_dataset.py`. 620 pairs /
52.5 min, lower 16 of 22 blocks frozen (102.0 M of 337.1 M trainable), lr 1e-5,
batch 2, 1500 steps in 15.5 min (~1.6 step/s).

**Result: negative.** At 250 steps speaker similarity fell 0.909 → 0.881
(Welch t = −3.46, significant). **Loss went NaN at step ~394**, and every
checkpoint after it is 100 % non-finite (140/140 tensors).

Not the data: 0 non-finite mels, 0 silent clips, 0 degenerate transcripts across
620 samples; weights are fp32. All 140 tensors going non-finite in one step is
the signature of **global gradient-norm clipping** — one overflowing gradient
makes the norm `inf`, every gradient becomes `NaN`, and a single update destroys
the model. The upstream trainer applies updates with no finite check, and F5's
flow-matching loss at batch 2 is very high variance (loss bounced 0.5–2.0
throughout, never converging).

Needed for a real attempt: skip-step on non-finite loss/grads, gradient
accumulation to effective batch 16–32, lr ~1e-6, eval every ~100 steps.

### `f5-tts-mlx`'s training path does not run as shipped

Six defects, all fixed in `scripts/finetune_voice.py` (on the instance, never in
`site-packages`, so `uv sync` cannot revert them):

1. Training extras undeclared (`mlx-data`, `pillow`, `matplotlib`, `wandb`).
2. `_to_mel_spec` stores an **mlx** array into an mlx.data sample; batching then
   fails with `Contiguous buffer expected`. Store contiguous numpy.
3. `mel_len` batches to `(b, 1)`; the model's einx expression wants `(b,)` →
   `RankError`.
4. MLX ops inside `.prefetch()` worker threads **abort the process**:
   `There is no Stream(gpu, N) in current thread`. Same hazard `_SingleThreadMlx`
   guards against in `tts.py`, one layer down. Do not prefetch.
5. `self._scale_factor = 1 / mx.sqrt(dim_head)` is an **mlx array** passed to
   `mx.fast.scaled_dot_product_attention`, which wants `scale: float`. A concrete
   0-d array converts implicitly, so **inference works and only training fails**
   — under `nn.value_and_grad` it is a tracer with no concrete value.
6. `save_checkpoint(step, finetune=False)` never reads `finetune`; dead
   parameter, no separate fine-tune save path. Checkpoints hold only
   `trainable_parameters()`, so they must be overlaid on pretrained weights with
   `strict=False`.

## Operational lessons

- **A 27B left loaded in LM Studio held 22 GB while idle** — weights are only
  4.73 GB; the rest was KV cache for a 262144-token context × 4 parallel slots.
  Unloading took free memory from 48 % to 90 %. Check `lms ps` before any
  multi-GB job.
- **This machine has zero swap** (`vm.swapusage total = 0.00M`). Overcommit is an
  immediate kill, not a slowdown. `CARELINE_FT_MEM_LIMIT_GB` sets an MLX limit so
  an over-large config raises instead of taking the host down.
- **Sequence length is the strongest memory lever**, because attention is O(n²):
  6 s clips cost 1.66 GB of attention activations where 10 s cost 4.61 GB. That
  beat layer freezing (5.02 GB → 2.40 GB optimizer floor).
- **The loader silently drops samples longer than `max_duration`.** A dataset of
  10 s clips would train on nothing while looking healthy. `build_ft_dataset.py`
  verifies the contract instead of assuming it.
- **Derived artifacts do not belong in `/tmp`.** A reboot cleared a 620-pair
  dataset and ~26 minutes of 27B labelling. Datasets now live in
  `~/careline-ft/` and every build step is resumable.

## Oversampling by file duplication — what it broke

**Shipping:** `results_combined/f5tts_375.safetensors`, selected by listening test.

The in-domain corpus (79 purpose-recorded prompts, 3.66 min) had to be weighted
against the mined lecture set (620 clips, 52.5 min) or it would have been ~7% of
steps and the style signal would have been swamped. The weighting was implemented
the lazy way: **each recorded clip was copied 6× as separate files** on disk,
giving 474 + 620 = 1094 clips and a 43% in-domain share.

That worked as a share calculation and failed in three measurable ways.

**1. Gradient pathology.** Norms reached **1.47e17**, against a maximum of
**61,268** across 800 steps of the mined-only run at *identical* block depth
(lower 16/22 frozen). Six identical copies can land inside one 8-micro-batch
accumulation window; the window then averages near-duplicate gradients, gradient
diversity collapses, and the norm explodes. Every spike was clipped and the
skip-step guard held — all 8 checkpoints finite — but a norm distribution
spanning 5e3 to 1e17 means the objective was badly conditioned throughout.

Note this corrected an earlier misattribution: the spikes were first blamed on
unfreezing more blocks. They recur at the original depth, so the cause is the
data, not the depth. Unfreezing only explained the memory change
(9.9 GB -> 12.7 GB peak).

**2. Early peak, then decay.** Quality peaks near step 375 and degrades after;
ck750 and ck1000 are audibly worse than ck250. Later steps re-fit the same 79
utterances rather than learning anything new. The run was ~2.7x longer than
useful, and weight drift had saturated at 1.03e-02 by step 720 in any case —
two independent signals to stop early that were both visible in the logs.

**3. Phoneme-level overfitting, caught by ear.** The operator localised the
ck500 regression to a single diphthong: the /aʊ/ in "how". The corpus contains
"how" in **8 of 79 prompts (10%)**, three of them sentence-initial; multiplied by
6 that is one of the densest patterns in the whole training signal. By step 500
the model had over-fit the sentence-initial realisation and stopped generalising
to mid-sentence "how", which is exactly where the evaluation sentence uses it.
No automated check surfaced this; a human ear localised it to the phoneme.

### The fix

- **Weight by sampling, not duplication.** Sample the minority set more often
  *without replacement within an accumulation window*, or raise the window so
  repeats cannot cluster. Never duplicate files.
- **Stop near 400 steps** for this configuration, or flatten the LR schedule so
  later steps still contribute.
- **Diversify the corpus** — vary sentence openings and phoneme contexts instead
  of repeating the same interrogative frames.

### The evaluation lesson, restated

Speaker-embedding cosine contributed **nothing** to any decision today. It rated
every combined-run checkpoint a tie (mean 0.894, sd 0.009, all inside the
0.781–0.942 speaker band) and had earlier rated the winning ck600 a tie with
zero-shot, which the operator described as "wayyy better". The metric measures
speaker *identity*, and identity was never the gap — zero-shot already sat inside
the speaker's own cross-session band. Prosody was the gap, and cosine is
deliberately invariant to it.

Keep the metric as a **guardrail** — it proves identity has not drifted and that
a checkpoint is not silence — and treat the listening test as the decision
procedure. A pipeline that promotes on cosine alone would have shipped zero-shot
and stopped.
