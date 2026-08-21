# Hardware matrix

This page records which hardware each blueprint has been measured on, which
hardware it should run on but has not been verified on, and which hardware it
cannot run on today. Use it to size a machine before you clone the repository.

The catalog targets two deployment classes:

- **Local AI on consumer edge.** One person's machine holds the weights and the
  private source data. Apple Silicon and NVIDIA consumer cards are the two
  install bases that matter here.
- **Cloud NVIDIA.** Larger machines, up to H100 class, for batch evaluation and
  for serving many rooms. Nothing in this repository has been run there yet.

## Verified environment

One host has been measured. Every latency, memory, and pass or fail number in
this repository comes from it.

| Field | Value |
| --- | --- |
| Chip | Apple M5 Pro |
| Memory | 48 GB unified |
| Operating system | macOS 26.5 (build 25F71) |
| Model server | LM Studio, OpenAI-compatible endpoint on `127.0.0.1:1234` |
| Python | 3.11 or newer |

Everything else in this page is reasoning from the code, not measurement. It is
labelled as such.

## Blueprint support

| Blueprint | Apple Silicon | NVIDIA consumer | NVIDIA cloud (H100 class) |
| --- | --- | --- | --- |
| [Deal room analyst](../../blueprints/deal-room-analyst/README.md) | Verified | Expected to run, unverified. Scanned-PDF OCR unavailable | Expected to run, unverified. Scanned-PDF OCR unavailable |
| [CareLine voice check-in](../../blueprints/careline-voice-checkin/README.md) | Verified | Care mode implemented via NIM, unverified. Cloned voice has no backend | Same as consumer |

### Why the deal room analyst is portable

`core/` and `server.py` import only the Python standard library. An AST scan of
`core/*.py`, `server.py`, and `scripts/*.py` finds one external package,
`opentelemetry`, and only in the five optional Phoenix export scripts. There is
no PyTorch, no CUDA call, and no MLX call anywhere in the blueprint.

The blueprint reaches its model over HTTP, so the hardware question is entirely
a question about the model server, not about the application:

```
core/ai_provider.py -> http://127.0.0.1:1234/v1 -> any OpenAI-compatible server
```

Two paths are platform specific, and both fail closed rather than crashing:

- **Apple Vision OCR** for scanned PDF pages. `core/macos_ocr.py` reports
  `available: false` when `platform.system()` is not `Darwin` or when
  `pdftoppm` and `swiftc` are missing. PDFs that carry embedded text still
  parse. Scanned pages are skipped rather than guessed at, and the limitation is
  disclosed in the model prompt and the web interface.
- **`sandbox-exec` isolation** for the coding-agent pilot. The profile is macOS
  specific and Apple has deprecated the interface.

Neither has been exercised on Linux, so "expected to run" is a reading of the
code, not a test result.

### What CareLine needs on NVIDIA

CareLine puts each model behind an abstract backend and selects the
implementation from the environment, so the care-mode call path needs no code
change to move to NVIDIA. `careline/tts.py` and `careline/stt.py` already ship
NIM clients.

| Component | Apple default | NVIDIA selection | State |
| --- | --- | --- | --- |
| Language model | Bonsai tiers over HTTP | `CARELINE_LLM_BASE_URL` | Portable. Nothing to port |
| Speech to text | Whisper large-v3-turbo via MLX | `CARELINE_STT_BACKEND=nim` with `CARELINE_STT_NIM_URL` | Implemented, never run against an endpoint |
| Care voice | Kokoro-82M via MLX | `CARELINE_TTS_BACKEND=nim` with `CARELINE_TTS_NIM_URL` and `CARELINE_TTS_VOICE` | Implemented, never run against an endpoint |
| Cloned self-voice | CSM-1B, or F5 via `CARELINE_CLONE_BACKEND=f5` | None | `get_clone_backend()` accepts only `csm` and `f5`, and both are MLX-only |

So a full care-mode call runs on NVIDIA in principle:

```bash
export CARELINE_STT_BACKEND=nim CARELINE_STT_NIM_URL=http://nim-host/asr
export CARELINE_TTS_BACKEND=nim CARELINE_TTS_NIM_URL=http://nim-host/tts
export CARELINE_LLM_BASE_URL=http://nim-host/v1
```

Both NIM clients raise immediately when their URL is unset, so a partial
configuration fails loudly rather than silently falling back to Metal.

The consented self-voice mode is the one feature with no NVIDIA path. Adding one
means implementing a third `TTSBackend` against a CUDA-capable cloning model;
the seam is already there, so it is a new class rather than a refactor.

Two further paths in this blueprint are Apple-specific:

- `mlx-audio` and `f5-tts-mlx` are the only cloning implementations, as above.
- `espeak-ng` is required by the Kokoro path and calls `exit()` in native code
  when its data files are missing, which kills the server process rather than
  the request. `scripts/preflight` checks for it. This is a packaging
  requirement, not a hardware one.

## Model footprint

Sizes measured on the verified host with `stat` against the GGUF files. The
Bonsai family is ternary, which is why a 27B model fits in 3.54 GB.

| Model | Role | On disk |
| --- | --- | --- |
| Bonsai 1.7B Q1_0 | Smallest available tier | 0.23 GB |
| Bonsai 4B Q1_0 | CareLine routine turns | 0.53 GB |
| Bonsai 8B Q1_0 | CareLine concerning turns | 1.08 GB |
| Bonsai 27B Q1_0 | Deal room analysis, CareLine post-call extraction | 3.54 GB |
| Bonsai 27B Q4_1 | Alternate 27B build | 1.66 GB |
| Bonsai 27B vision projector | Optional, for image input | 0.59 GB to 0.87 GB |
| Qwen3.8-27B Q4_K_M | Non-ternary 27B, for size comparison only | 16.55 GB |

A ternary 27B is 4.7 times smaller on disk than the same parameter count at
Q4_K_M. That ratio is the reason a 27B model is a consumer-edge proposition at
all.

Speech models, measured in the Hugging Face cache:

| Model | Role | On disk |
| --- | --- | --- |
| CSM-1B | Cloned voice, few-shot conditioned | 5.8 GB |
| Whisper large-v3-turbo, fp16 | Speech to text | 1.5 GB |
| F5-TTS-MLX | Alternate cloning backend | 1.3 GB |
| Kokoro-82M, bf16 | Care voice | 0.34 GB |

## Sizing memory

Weights are not the binding constraint. Key and value cache is.

Bonsai 27B Q1_0 is 3.54 GB on disk. On the verified host, serving it from LM
Studio at the advertised 262,144 token context with four parallel slots held
**21.9 GB** resident. Weights were 16 percent of that; the cache was the rest.

Two consequences:

1. Size for the context you configure, not for the file on disk. Reduce context
   length or parallel slots before you reduce model size.
2. macOS with no swap file will hard-stall rather than page. Loading the 27B at
   full context alongside the speech models exhausted 48 GB of unified memory
   and required a reboot. `GETTING_STARTED.md` records this.

Suggested starting points, reasoned from the footprints above rather than
measured on each configuration:

| Available memory | What fits |
| --- | --- |
| 8 GB | Bonsai 4B or 8B at a short context. Deal room analyst only |
| 16 GB | Bonsai 27B Q1_0 at a reduced context. Deal room analyst comfortably |
| 32 GB | Bonsai 27B plus the CareLine speech stack |
| 48 GB and above | The verified configuration, with headroom for fine-tuning runs |

On NVIDIA consumer cards the same table applies to VRAM, with the caveat that
Apple unified memory is shared with the operating system while VRAM is not.

## Unified-memory NVIDIA boxes

Between a consumer card and a data-centre card sits a class of machine with
large unified memory rather than discrete VRAM: GB10-based systems such as DGX
Spark, quoted at 128 GB. That class matters for this catalog because it removes
the constraint that shapes the tables above — a 27B model, three tiers loaded at
once, and the speech stack all fit without competing for a 24 GB card.

CareLine's implementation notes name a GB10-class box as the intended
enterprise-edge target, and the NIM backends were written for it. Nothing has
been run on one. Treat every row above as unchanged: implemented, unverified.

The reason to record the class separately is that its memory behaviour resembles
Apple Silicon more than it resembles a discrete GPU. The sizing advice in
[Sizing memory](#sizing-memory) transfers; the advice to keep weights under a
fixed VRAM ceiling does not.

## Serving the model on NVIDIA

The application code needs no change. Point it at a different endpoint:

```bash
# Deal room analyst
export PRISM_LOCAL_AI_URL=http://127.0.0.1:8000

# CareLine
export CARELINE_LLM_BASE_URL=http://127.0.0.1:8000/v1
export CARELINE_LLM_MODEL=4b
export CARELINE_LLM_STRONG_MODEL=8b
export CARELINE_LLM_EXTRACT_MODEL=27b@q1_0
```

Any OpenAI-compatible server works. `llama.cpp` built with CUDA serves the same
GGUF files the verified host uses, which makes it the closest match to the
measured setup. vLLM, TGI, and NVIDIA NIM expose the same API shape but expect
different weight formats.

### Recording which hardware served a response

The deal room analyst already carries hardware provenance into its deployment
evidence and traces, so a local run and a cloud run stay distinguishable after
the fact. Set these when you serve the model:

| Variable | Meaning |
| --- | --- |
| `PRISM_LOCAL_AI_HARDWARE` | Free-text hardware label, for example `apple-m5-pro-48gb` or `rtx-4090-24gb` |
| `PRISM_LOCAL_AI_RUNTIME` | Serving runtime, for example `llama.cpp` or `vllm` |
| `PRISM_LOCAL_AI_RUNTIME_VERSION` | Runtime version string |
| `PRISM_LOCAL_AI_MODEL` | Model identifier the server exposes |
| `PRISM_LOCAL_AI_CONTEXT_TOKENS` | Active context length, not the advertised maximum |

`core/ai_provider.py` copies these into the deployment evidence attached to each
response, and `core/operator_preflight.py` reports them before a run. Leaving
them unset is allowed; the fields record as null, and a comparison between two
machines then has no hardware label to join on.

The deal room analyst constrains the local provider URL to an IPv4 loopback
address or the exact IPv6 `::1` address. A model server on another host is
rejected by `core/ai_provider.py` unless you configure the cloud route with
signed consent, which is a separate path described in
[Hybrid AI](../concepts/hybrid-ai.md).

## Cloud NVIDIA

No part of this repository has run on cloud NVIDIA hardware. The catalog states
this in several places and it remains true: cloud and hybrid comparisons are
unmeasured. Specifically absent:

- No throughput, latency, or cost measurement on H100 or any other data-centre card.
- No batch evaluation run. The evaluation store contains zero cloud and zero
  hybrid runs, as recorded in
  [the evaluation framework audit](../EVALUATION_FRAMEWORK_COMPLETION_AUDIT.md).
- No multi-tenant or hardened serving boundary. See
  [the architecture reality matrix](../ARCHITECTURE_REALITY_MATRIX.md).

The work that would close this gap is a paired local and cloud run of the same
first-pass contract, recorded through the existing experiment store so the two
routes are comparable under one grading rule.

## Verification

```bash
python3 tooling/documentation/validate_links.py
cd blueprints/deal-room-analyst/app && python3 -m unittest tests.test_documentation_assets tests.test_platform_catalog
```
