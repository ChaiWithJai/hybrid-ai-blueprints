# Voice clone setup — "call yourself" mode

CareLine's `mode: "self"` speaks in the operator's own cloned voice. This is the
setup guide: prerequisites, how to build a reference recording, how to verify it
works, and what goes wrong.

**Self-voice only.** Cloning anyone else requires their documented consent and
disclosure to the listener. Reference audio is biometric data: it stays on the
operator's disk and is gitignored (see [SECURITY.md](../../SECURITY.md)).

## Prerequisites

| Requirement | Why |
|---|---|
| macOS on Apple Silicon | MLX runs on Metal |
| `uv` | dependency management |
| `ffmpeg` | audio decode and segment extraction |
| **`brew install espeak-ng`** | **required — see below** |
| Ollama with `qwen2.5:7b` | the conversation LLM |

`scripts/preflight` checks all of these.

### espeak-ng is not optional

Without a system espeak-ng, the **first care-mode synthesis kills the server
process.** Kokoro's phonemizer initialises espeak-ng through a wheel whose data
path is a baked-in CI build path (`/Users/runner/...`). When espeak cannot find
`phontab` it calls `exit()` in native C — no Python `except` can catch it, so
uvicorn dies mid-request and the browser sees a dropped connection.

`scripts/run` locates the data directory and exports `ESPEAK_DATA_PATH`
automatically. The value must be the **parent** of `espeak-ng-data`
(e.g. `/opt/homebrew/share`), and the wheel's own bundled copy does not satisfy
Kokoro — a system install does.

## Which model does the cloning

`mode: "self"` uses **F5-TTS via MLX** (`F5CloneBackend`). It replaced CSM-1B,
measured on the same reference and sentence:

| | pitch range (p10–p90) | speaker cosine | compute for ~4.5 s audio |
|---|---|---|---|
| your reference | 118 Hz | — | — |
| **F5-TTS** | **130 Hz** | 0.93 | **~5 s** |
| CSM-1B | 80 Hz (**−32 %**) | 0.92 | ~16 s |

Both reproduced *identity* equally well. What CSM degraded was **prosody**: it
compressed the pitch range by a third, which is heard as flat and monotone. That
is the reason for the swap — not similarity, which was already fine.

Switch back for comparison with `CARELINE_CLONE_BACKEND=csm`.

## Building a reference

You need two files:

```
app/voices/self_ref.wav    24 kHz mono, ~10–15 s, one speaker
app/voices/self_ref.txt    the EXACT transcript of that wav
```

The transcript must match the audio. F5 conditions on `ref_text + generated_text`
as one sequence; a mismatch degrades output in ways that are hard to attribute
afterwards. Always re-transcribe after trimming.

### From a recording you already have

```bash
# 1. find silence-bounded speech runs (single speaker, no crosstalk)
ffmpeg -i source.m4a -af "pan=mono|c0=0.5*c0+0.5*c1,silencedetect=noise=-33dB:d=0.6" \
  -f null - 2>&1 | grep silence_

# 2. cut a run, leaving headroom. NOTE: no aggressive highpass — a 300 Hz
#    highpass strips the fundamental of most male voices (F0 ~90–150 Hz) and
#    wrecks clone quality. 70 Hz removes rumble without touching speech.
ffmpeg -ss 901.4 -t 14 -i source.m4a \
  -af "pan=mono|c0=0.5*c0+0.5*c1,highpass=f=70,loudnorm=I=-20:TP=-3:LRA=11" \
  -ar 24000 -ac 1 -c:a pcm_s16le app/voices/self_ref.wav

# 3. transcribe with the same Whisper the app uses, so ref_text matches
curl -s -X POST http://127.0.0.1:8100/api/stt -H "Content-Type: audio/wav" \
  --data-binary @app/voices/self_ref.wav | python3 -c \
  'import json,sys; print(json.load(sys.stdin)["text"].strip())' > app/voices/self_ref.txt
```

### Recording fresh

```bash
ffmpeg -f avfoundation -i ":0" -t 20 -ar 24000 -ac 1 raw.wav   # list devices: -list_devices true
```
Read ~15 s of ordinary connected prose — not a word list. Quiet room, no music,
no second speaker.

## Choosing between candidates

If you have several candidate clips, do not pick by SNR. Measured over 963
segments from 10 recordings, ranked by the fidelity of the clone each one
produced:

- **SNR and pitch-stability did not predict clone quality.** The
  highest-SNR candidate produced one of the *worst* clones.
- **Speaker-embedding similarity of the reference did predict it** (r = 0.77).
- **Transcript quality matters and is invisible to acoustics.** Silence-bounded
  cuts often land mid-sentence; a reference ending on a truncated thought
  measurably hurt. An LLM reading the transcript catches this — waveform
  metrics never can.
- **Within-recording variance was as large as between-recording.** Don't assume
  one clip represents a whole session.

The reliable method is empirical: clone from each candidate and measure the
clone.

```bash
# score clips against held-out real recordings of the speaker
uv run --with resemblyzer --with "setuptools<81" \
  python scripts/eval_voice_similarity.py ANCHOR_DIR clip1.wav clip2.wav
```

`ANCHOR_DIR` holds 3+ real clips of the speaker from recordings **not** used as
references. The script prints the speaker's own session-to-session band
(leave-one-out) so a number can be interpreted:

- **inside the band** → indistinguishable from a real recording, by this metric
- **above the band** → not superhuman; the clone is copying the reference's
  channel (mic/room/codec). Treat as channel overfitting.
- **below the band** → genuinely worse

Identity is not the whole story: CSM matched F5 on this metric while sounding
clearly worse. Use it alongside listening, never instead of it.

## Multiple references do not help

Concatenating the top 3 segments into one reference was tested against the best
single clip, 5 seeds each: **+0.003 (t = 0.34)** — indistinguishable from noise.
F5 zero-shot conditions on *one* reference; concatenating does not weight
examples, it just makes a longer clip.

It did reduce *variance* (sd 0.006–0.012 vs 0.019, worst case 0.914 vs 0.892),
so it buys consistency, not accuracy. Genuine multi-example weighting needs
fine-tuning — see [Fine-tuning](#fine-tuning).

## Testing

```bash
scripts/verify          # conversation regression + voice regression
```

The voice half (`app/scripts/verify_voice.py`) checks the things that broke in
practice:

| Check | Catches |
|---|---|
| `import/f5-declared-in-manifest` | `uv sync` removing an undeclared dependency |
| `reference/contract` | wrong sample rate, empty transcript, bad length |
| `clone/not-silence` | 0.04 s of audio returned as HTTP 200 |
| `clone/no-leading-gap` | per-chunk silence inflating every pause |
| `care-mode/server-survives` | espeak's native `exit()` killing the process |
| `clone/latency` | real-time factor above 3× |

Manual smoke test:

```bash
curl -s -X POST http://127.0.0.1:8100/api/tts -H "Content-Type: application/json" \
  -d '{"text":"Hey, just checking in.","mode":"self"}' --output out.wav && afplay out.wav
```

## Troubleshooting

| Symptom | Cause |
|---|---|
| Server dies on first care-mode call | espeak-ng missing → `brew install espeak-ng` |
| `503 tts backend unavailable: No module named 'f5_tts_mlx'` | `uv sync` stripped it; it must be in `pyproject.toml`, not installed ad hoc |
| ~0.04 s of audio, HTTP 200 | F5's duration predictor returned total ≈ reference length. `duration` is **total (reference + generated) in frames**; the backend derives it from `estimated_duration()` |
| `reference must be 24000 Hz` | re-cut with `-ar 24000 -ac 1`. Not resampled silently on purpose — a mismatched reference is a config error |
| Long pause after every sentence | leading silence in each chunk. The UI requests TTS per sentence and concatenates, so chunk silence adds to every punctuation pause. `_trim_edges()` removes it |
| Robotic / flat delivery | check `CARELINE_CLONE_BACKEND` — `csm` compresses pitch range ~32 % |
| `There is no Stream(gpu, N) in current thread` | MLX work ran off its owning thread. All load/generate for one model must stay on one thread (`_SingleThreadMlx`) |
| Clone sounds like a different person | reference likely has crosstalk or is atypical of the speaker. Score it against anchors before blaming the model |

## Fine-tuning

`scripts/finetune_guarded.py` fine-tunes F5 on one speaker on Metal;
`scripts/build_ft_dataset.py` builds a dataset from existing recordings, and
`scripts/record_voice_corpus.py` records a purpose-built one with exact
transcripts.

**A fine-tuned checkpoint now ships** (`voices/f5_finetuned.safetensors`), loaded
as a `strict=False` overlay on the pretrained weights because it holds only the
trainable parameters. Delete the file and the app falls back to zero-shot, which
remains supported.

### What worked

- **Recording purpose-built data beat mining more archive audio.** 11.8 h of
  existing recordings are all lecture delivery; the target register is a warm
  check-in. 3.66 min of in-domain prompts moved the result more than the extra
  hours would have. Reading prompts also gives exact transcripts, removing both
  ASR error and the mid-thought truncation that Bonsai flagged in mined clips.
- **A guarded training loop.** The upstream trainer applies updates with no
  finite check and clips by global norm, so one `inf` gradient turns every tensor
  to NaN in a single step — measured, 33% of raw steps produce non-finite
  gradients. Skip-step plus gradient accumulation took fine-tuning from
  "significantly degrades the voice" to "wins the listening test".
- **Selection by ear.** Every checkpoint that shipped was chosen by listening.

### What failed, and why

**Do not weight a minority dataset by duplicating files.** Copying each recorded
clip 6x to reach a 43% share produced gradient norms of 1.47e17 (versus 61,268
max without it), quality that peaks near step 375 and decays after, and
phoneme-level overfitting — the /aʊ/ in "how", present in 10% of prompts and
multiplied by 6, regressed audibly by step 500. Weight by *sampling* instead, and
keep repeats out of a single accumulation window.

**Do not promote on speaker-embedding cosine.** It rated every checkpoint a tie
and rated the eventual winner a tie with zero-shot. It measures identity, which
was never the gap. Use it as a guardrail — identity has not drifted, output is
not silence — and decide by listening. Full detail in
[IMPLEMENTATION.md](IMPLEMENTATION.md).

### Practical settings

Stop near 400 steps for this configuration; weight drift saturates around 700 and
later steps contribute nothing. Training deps live in a **separate venv** so the
app's `uv sync` cannot strip them:

```bash
uv venv --python 3.12 ~/careline-ft/.venv
uv pip install --python ~/careline-ft/.venv/bin/python f5-tts-mlx mlx-data pillow matplotlib wandb soundfile
```

`f5-tts-mlx`'s training path needs six fixes to run at all; they live in
`scripts/finetune_voice.py` and are documented in IMPLEMENTATION.md.

## Memory

Voice models are large and macOS may have **no swap** (`sysctl vm.swapusage`),
in which case overcommit is an immediate kill, not a slowdown. Before training:

- unload other local models (`~/.lmstudio/bin/lms unload --all`) — a 27B at a
  262 k context held **22 GB**, mostly KV cache, while idle
- stop the careline server (it holds F5 + Whisper + Kokoro)
- `CARELINE_FT_MEM_LIMIT_GB` caps MLX so an over-large config raises instead of
  taking the machine down

Attention is O(n²) in sequence length, so clip duration is the strongest lever:
6 s clips cost 1.66 GB of attention activations where 10 s cost 4.61 GB.

## Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `CARELINE_CLONE_BACKEND` | `f5` | `f5` or `csm` |
| `CARELINE_F5_MODEL` | `lucasnewman/f5-tts-mlx` | clone model |
| `CARELINE_F5_STEPS` | `8` | ODE sampling steps |
| `CARELINE_SELF_REF_AUDIO` | `voices/self_ref.wav` | reference audio |
| `CARELINE_SELF_REF_TEXT` | `voices/self_ref.txt` | reference transcript |
| `ESPEAK_DATA_PATH` | auto-detected | parent of `espeak-ng-data` |
| `CARELINE_TTS_BACKEND` | `mlx` | care-mode voice (`mlx`/`nim`) |
