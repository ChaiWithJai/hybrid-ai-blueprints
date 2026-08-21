# Getting started

The honest path from `git clone` to two running blueprints, and every trap that
cost real time. Each entry below was hit and diagnosed on a real machine — none
of it is hypothetical.

Read [Footguns](#footguns) before you debug anything. Several failures here look
like something other than what they are.

## What is in here

| Blueprint | Runs on | Port |
|---|---|---|
| `blueprints/careline-voice-checkin` | Bonsai 4b/8b/27b + mlx-audio (CSM-1B, Kokoro, Whisper) | 8100 |
| `blueprints/deal-room-analyst` | Bonsai 27b@q1_0 + Buzz relay | 8787 |
| Phoenix (Arize) — traces + evals for both | Docker | 6006 |

## Prerequisites

macOS on Apple Silicon. Both blueprints run models locally.

```bash
brew install ffmpeg espeak-ng          # espeak-ng is NOT optional -- see footgun 1
# uv:      https://docs.astral.sh/uv/
# Docker Desktop (Buzz relay, Phoenix)
# LM Studio, with the Bonsai family loaded (4b, 8b, 27b@q1_0)
```

Then, always:

```bash
blueprints/careline-voice-checkin/scripts/preflight   # voice blueprint
python3 scripts/preflight.py --phase host             # deal room
```

Preflight is the fastest way to find a missing prerequisite. Both fail loudly
rather than degrading.

## CareLine voice check-in

```bash
blueprints/careline-voice-checkin/scripts/run      # http://127.0.0.1:8100
blueprints/careline-voice-checkin/scripts/verify   # conversation + voice regressions
```

For the cloned voice you must supply your own reference recording — it is
biometric data and is never committed:

```bash
cd blueprints/careline-voice-checkin/app
.venv/bin/python scripts/record_voice_corpus.py --list        # find your mic
.venv/bin/python scripts/record_voice_corpus.py --device 3    # ~12 min, resumable
```

See [VOICE_CLONE_SETUP.md](blueprints/careline-voice-checkin/VOICE_CLONE_SETUP.md).

## Deal room analyst

```bash
docker start phoenix
blueprints/deal-room-analyst/scripts/run --port 8787
```

The application lives in `blueprints/deal-room-analyst/app/`, which is also its
Python import root. Run its suite from there:

```bash
cd blueprints/deal-room-analyst/app && python3 -m unittest discover -s tests
```

A deal room is only usable after its folder is **opened**, which creates the Buzz
workspace room. Fixture registration alone is not enough (footgun 13):

```bash
# preview -> capture preview_sha256 -> open
curl -s -XPOST localhost:8787/api/deal-room/preview -H 'Content-Type: application/json' \
  -d '{"folder_path":"'"$PWD"'/deal_rooms/project_titan_lbo"}'
curl -s -XPOST localhost:8787/api/deal-room/open -H 'Content-Type: application/json' \
  -d '{"folder_path":"'"$PWD"'/deal_rooms/project_titan_lbo","preview_sha256":"<from preview>"}'
```

The room lands at `/rooms/local_<hash>`, **not** `/rooms/project_titan_lbo`.

## Observability

```bash
docker start phoenix                                            # :6006
CARELINE_TRACE=1 blueprints/careline-voice-checkin/scripts/run   # emit traces
cd blueprints/careline-voice-checkin/app
.venv/bin/python scripts/evaluate_traces.py --annotate          # evals onto spans
```

Traces show which Bonsai tier served each turn; evaluations are derived from the
use case's declared `critical_failures`, not invented metrics.

---

# Footguns

## Environment

**1. Missing `espeak-ng` kills the server process, not the request.**
Kokoro's phonemizer initialises espeak-ng through a wheel whose data path is a
baked-in CI path (`/Users/runner/...`). When it cannot find `phontab` it calls
`exit()` in native C — no Python `except` can catch it, so uvicorn dies
mid-request and the browser just sees a dropped connection. `brew install
espeak-ng`; `scripts/run` then exports `ESPEAK_DATA_PATH`, which must be the
**parent** of `espeak-ng-data` (e.g. `/opt/homebrew/share`). The wheel's own
bundled data does not satisfy Kokoro.

**2. A missing spaCy model exits the server at first synthesis.**
`misaki` needs `en_core_web_sm` and tries to download-and-install it at runtime,
inside the server process, which exits 1. It is installed on first use now, but
if you see an unexplained exit on the first care-mode call, this is it.

**3. `uv sync` silently removes anything not in `pyproject.toml`.**
`scripts/run` calls `uv sync`. A package you installed by hand is gone on the
next start, and the symptom is a 503 (`No module named ...`) long after the
install "worked". Declare dependencies in the manifest. This bit twice: once for
`f5-tts-mlx`, once for the training extras.

**4. Training dependencies live in a separate venv on purpose.**
Because of footgun 3, fine-tuning deps are installed in `~/careline-ft/.venv`,
not the app venv, so the app's `uv sync` cannot strip them.

## Memory, on a machine with no swap

**5. Check `sysctl vm.swapusage` before running anything large.**
On the reference machine it is **zero**. With no swap, overcommit is an
immediate kill — not a slowdown — so a job that would merely thrash on Linux
takes the machine down here.

**6. An idle model in LM Studio can hold 22 GB.**
A 27B at q1_0 is only 4.73 GB of weights; the rest was KV cache for a
262144-token context with 4 parallel slots. It stays resident after the job that
needed it. `~/.lmstudio/bin/lms ps` before starting anything big;
`lms unload --all` frees it.

**7. `lms load -c <ctx>` may be ignored.**
A saved per-model config wins over the CLI flag, so the model reloads at its
configured context (and memory) regardless. Change the context in the LM Studio
UI if you need it smaller.

**8. Fine-tuning cost is dominated by sequence length, not parameter count.**
Attention is O(n²): 6 s clips cost 1.66 GB of attention activations where 10 s
cost 4.61 GB. Cutting clip length beat freezing layers (5.02 GB → 2.40 GB
optimizer floor).

## Data you will lose

**9. Do not keep derived artifacts in `/tmp`.**
A reboot cleared a 620-pair dataset and ~26 minutes of 27B labelling output.
Datasets live under `~/careline-ft/`, and every build step is resumable.

**10. Multi-GB checkpoints are one `git add` from being committed.**
`.gitignore` globs `blueprints/*/app/results*/` because an explicit list missed
`results_combined/` — 3 GB nearly went in. Check `git status --porcelain` size
before committing after any training run.

## Buzz / Postgres

**11. `docker exec psql` cannot verify a password.**
`pg_hba.conf` has `local all all trust`, so a *deliberately wrong* password
succeeds over the socket. The relay connects over TCP where
`host all all all scram-sha-256` is enforced. To test a credential properly, go
over TCP:

```bash
docker run --rm --network prism-vault-buzz_default -e PGPASSWORD=... \
  postgres:17-alpine psql -h postgres -U buzz -d buzz -c 'select 1'
```

If the role password drifted from `.env` (a volume initialised by another repo),
fix the role, not the data: `ALTER USER buzz WITH PASSWORD '<from .env>';`

**12. The Buzz compose project is shared across repos.**
`infra/buzz/compose.yml` declares `name: prism-vault-buzz`, so this repo and any
other using that name share containers *and volumes*. Changing the postgres
password here can break the other repo's relay. Give each repo its own `name:`.

## Deal room

**13. A fixture room is listed but has no workspace until a Buzz channel is
bound to it, and `/rooms/<id>` returns 200 either way.**

The four demo rooms in `DEAL_ROOM_CATALOG` appear in the room list immediately.
That is only catalog metadata. Until a channel is bound, the browser sits on
"Opening workspace" forever and the API says so plainly:

```bash
curl -s 'http://127.0.0.1:8787/api/workspace?room=project_titan_lbo'
# {"error": "workspace_not_bound", "room": "project_titan_lbo"}
```

Three things make this hard to diagnose:

*The page is not a check.* `GET /rooms/project_titan_lbo` returns the
single-page shell and answers **200 whether or not anything is bound**. Curling
the route proves the server is up and nothing else. Check
`/api/workspace?room=<id>` instead.

*Opening the folder produces a different room.* That path keys the room by the
folder's absolute path, so the Titan fixture folder registers as
`local_cedf07e82624`, not `project_titan_lbo`. You get a working room at a URL
that no tutorial, screenshot manifest, or link mentions. Move the repository and
the hash changes, which is why an older registration can linger under a second
`local_` id after the application directory moves.

*One channel cannot serve two rooms.* The server does try to bind the default
room at startup:

```python
_demo_channel = PROJECT_ROOT / ".runtime" / "buzz" / "demo-channel-id"
if _demo_channel.exists() and global_buzz.room(DEFAULT_ROOM) is None:
    global_buzz.bind_existing_room(DEFAULT_ROOM, _demo_channel.read_text().strip())
```

but handing it a channel that already belongs to another room raises
`BuzzUnavailable: Buzz room registry assigns one channel to multiple rooms`, and
the `except BuzzUnavailable: pass` around that call swallows it. Startup stays
silent and the room stays unbound. The invariant is correct — two rooms sharing
one conversation would be worse — but reusing an existing channel is not the
workaround it looks like.

The fix is to give each fixture its own channel:

```bash
cd blueprints/deal-room-analyst/app
python3 scripts/seed_fixture_room.py --all     # or: project_titan_lbo
python3 scripts/seed_fixture_room.py --list    # show every fixture and its binding
```

That calls the same `BuzzBridge.ensure_room` the application uses, so the
channel is created private, the agent identity is added as a `bot` member, and
the initial canvas is written. It is idempotent. Verify with the workspace API:

```bash
curl -s 'http://127.0.0.1:8787/api/workspace?room=project_titan_lbo' \
  | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d["room_name"], d["total_documents"], "documents")'
# Project Titan: $2.4B Sponsor-Backed LBO 4 documents
```

**14. Do not put a textual `@Bonsai` in a message.**
buzz-cli parses `@handle` mentions from the body and resolves them against
channel members, but `channels add-member` accepts only `--pubkey`/`--role` —
members have no names — so a textual mention can never resolve and the send
fails with `mention '@bonsai' does not match a current channel member`.
Addressing the agent is done by the server via `--mention <agent_pubkey>`. Both
the client and the server now strip the literal text.

**15. `pkill -f run_v0.py` leaves the server running.**
The supervisor dies; its `server.py` child keeps holding port 8787, so
`/api/status` returns 200 from **stale code** and your fix appears not to work.
Kill both, and check `server_process_pid` against the file mtime:

```bash
pkill -f run_v0.py; pkill -f "server.py --port 8787"
```

**16. The deal room preflight needs the model *loaded*, not merely present.**
`bonsai_model_loaded: catalog_only` means LM Studio has it in the catalog but
not in memory: `lms load 27b@q1_0`.

**17. Six tests already fail on `main`** (`test_absence_oracle`,
`test_reality_guards`). Do not read them as breakage you introduced.

## Voice

**18. Silence can be returned as HTTP 200.**
F5's `duration` is the **total** (reference + generated) length in frames, and
the caller slices the reference back off. Left unset, the predictor returned
≈ the reference length, so generation produced 0.04 s of audio — status 200,
nothing audible. Always derive duration from `estimated_duration()`.

**19. A blocked autoplay looks exactly like a dead server.**
`a.play().catch(() => resolve())` swallowed the rejection: audio arrived, was
never played, nothing logged. Browsers block audio not tied to a user gesture,
and an awaited fetch can lose that gesture. The UI now surfaces it and offers a
tap-to-play button.

**20. Synthesizing per sentence is slower than synthesizing the whole reply.**
Every call re-conditions on the full reference (a fixed ~3.5 s cost). Measured on
a three-sentence reply: per-sentence 13.74 s wall with 3.7/3.1/2.3 s of dead air
between sentences; one call 5.53 s with none. Time-to-first-audio is the same
either way.

**21. Newlines in a reply become pauses — or worse.**
CSM-1B's `split_pattern` defaults to `'\n+'`, so it *splits generation* at
newlines and synthesizes each fragment separately: a gap plus restarted prosody
mid-reply. LLM replies contain newlines constantly. Whitespace is normalised
before synthesis now.

**22. `max_audio_length_ms` defaults to 90 seconds.**
A short reply can run away. Budget it from the text length.

**23. Cap LLM reply length or the voice will monologue.**
An uncapped fast tier produced a 70-word greeting — 23 s of audio, ~10 s to
synthesize. Speech runs ~170 wpm, so budget backwards from the audio you want:
~14 words ≈ 5 s ≈ 35 tokens.

## Evaluation

**24. Speaker-similarity cosine measures identity, not prosody.**
It rated every fine-tuned candidate a tie, including the one an operator
described as "wayyy better", because identity was already at ceiling and the
metric is deliberately invariant to prosody. Keep it as a guardrail (identity
has not drifted, output is not silence) and decide by listening.

**25. A green evaluation suite can still describe a broken experience.**
The trace evaluator reported `VERIFIED — Guards passed` while the greeting was
inventing prior contact on a first call, because no evaluator covered invented
memory. Absence of a check is not evidence of correctness.

## After the issue #2 migration

**26. A seeded deal room is keyed by absolute path, so moving fixtures
invalidates it.** Room ids are `local_<sha256(absolute folder path)[:12]>`. After
the application moved, the existing room resolved to a folder that no longer
existed and every `ask_bonsai` message returned 409
`deal_room_source_unavailable: folder does not exist`. Re-run preview + open
against the new path; the room gets a new id.

**27. `.runtime/` must move with the application, or Buzz regenerates its
secrets.** `scripts/buzz_up.py` derives its root from
`Path(__file__).resolve().parents[1]`. Once it moved into `app/scripts/`, it
looked for `app/.runtime/` — found nothing — and wrote a **fresh `.env` with a new
random `POSTGRES_PASSWORD`**, while the postgres volume still held the old one.
The relay then crash-looped on `password authentication failed`. `.runtime/` also
holds the compiled Buzz binaries, so moving it avoids a ~10 minute rebuild.

**28. The documentation link validator will walk anything you add under
`blueprints/`.** It has now been caught twice: once on a blueprint's `.venv/`,
once on `.runtime/`'s vendored Rust checkouts. Both were third-party markdown
linking inside their own upstream repositories. If a new failure names a path you
did not author, add its directory to `VENDORED_PARTS` in
`tooling/documentation/validate_links.py` rather than chasing the link.
