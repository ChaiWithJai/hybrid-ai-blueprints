# Shadowbox Coach

A webcam shadow-boxing trainer that runs entirely on your machine — the boxing answer to
the "RepGuard" pushup tracker. A lightweight pose model does the perception, plain
JavaScript does the judging, and a local Bonsai model does the talking.

**The hybrid split, in one line:** MediaPipe Pose (~5 MB) finds 33 body landmarks per
frame; a per-hand state machine counts and classifies punches from geometry; Bonsai on
LM Studio turns each round's stats into corner-coach advice between rounds. No frames,
no stats, and no audio ever leave the machine.

## What it does

- Live skeleton overlay on your webcam feed (mirrored, selfie-style)
- Counts punches **at the moment of impact** and classifies them: **jab, cross, hook, uppercut**
- **Power score (5–99) per punch** from the kinetic chain: hand speed + torso rotation
  (read from the shoulders' relative depth). Arm-punching — a power punch thrown
  without turning the body — is tracked and reported to the coach
- CompuBox-style scorecard: jabs vs power punches, plus a round-by-round table
- Punches-per-minute, fastest-hand speed (in shoulder-widths/sec — scale-invariant)
- **Cross-session trends**: every round is logged to localStorage; a sparkline shows
  your output per round across sessions
- Orthodox/southpaw stance toggle; `?model=lite|full|heavy` A/Bs the pose model
  (inference ms shows in the debug panel)
- **Latency-tuned pipeline**: the camera is asked for 60 fps, pose inference runs
  in a Web Worker (`pose-worker.js`, one frame in flight, stale frames skipped —
  main-thread HUD work can never delay a detection; falls back inline if workers
  fail), and the detector can score **predictively** on the reach-velocity
  turnover (`predVel`) instead of waiting for the reach to visibly drop
- 3:00 round / 1:00 rest timer; the coach speaks between rounds
- **Corner coach:** round stats go to whatever model LM Studio has loaded
  (`http://localhost:1234`). No LM Studio? It falls back to canned corner talk.
  The coach receives **pre-digested form telemetry** — average power score,
  arm-punch %, retraction time, guard height — never raw traces, so the judge
  model coaches from stats instead of re-scoring punches itself (the guardrail
  against LLM-judge drift).

## Run it

```bash
cd blueprints/shadowbox-coach/app
node server.mjs
# open http://localhost:4790 and allow camera access
```

For live coaching, start LM Studio's local server with a model loaded (Bonsai 1.7B is
plenty — the coach prompt is ~100 tokens each way) and enable **CORS** in LM Studio's
server settings.

## No camera? Synthetic sparring partner

```
http://localhost:4790/?synthetic=1
```

Feeds a scripted skeleton — jab, cross, lead hook, rear uppercut on a loop — through the
exact same detection pipeline. This is how the counting logic is tested: the expected
count is deterministic (4 punches per ~3.2 s cycle, one of each type).

The same feed backs the unit test — the detection core (`punch.js`) has no DOM or
MediaPipe dependency, so it runs straight in Node:

```bash
node test.mjs   # 5 combo cycles → expects 20 punches, exact type sequence
```

## How punch detection works

Everything is normalized by shoulder width, so distance from the camera doesn't matter.

1. **Reach** = 3D wrist-to-shoulder distance (MediaPipe's relative depth `z` catches
   straights thrown at the camera, which barely move in 2D).
2. Each hand runs a tiny state machine: *guard → extended → retracting*. The punch is
   **scored at impact** — the frame the reach curve turns over at peak extension — not
   when the hand returns to guard, so the count lands CompuBox-fast (~50 ms after peak
   in the synthetic test). A minimum peak hand speed gates out slow reaches, and a
   re-arm path catches double jabs thrown off a half retraction that never gets back
   to guard.
3. Classification compares the extension vector against guard position: mostly toward
   the camera → jab/cross, mostly lateral → hook, mostly upward → uppercut.

Guard rails against real-world noise: a punch must launch **from guard** within the
last 500 ms at arming speed (hanging arms and fidgeting never score), must peak above
hip height, and hooks are identified by a **bent elbow at peak** (3D elbow angle)
rather than displacement direction — which real crosses fooled.

Press **`d`** in the app for a live debug readout of reach/speed/elbow-angle/phase per
hand — the thresholds live at the top of `punch.js`.

## Calibrate against your own punches (record → replay)

Press **`r`** to start recording, throw one punch type ~10 times, press **`r`** again
and name what you threw (e.g. `jab x10`). The raw landmarks plus every call the app
made land in `recordings/` via the local server. Then replay offline:

```bash
node replay.mjs recordings/<file>.json                 # what would be called, punch by punch
node replay.mjs recordings/*.json minPeakSpeed=1.8     # re-run with threshold overrides
```

Real labeled punches become regression data: tune the config until every recording
scores correctly, then bake the winning values into `punch.js`.

## The optimization loop (verifiable rewards, RLVR-style)

The detector's 12+ thresholds aren't hand-tuned anymore — they're searched. The
algorithm is boring; the reward function is everything:

- **`eval.mjs`** — the reward function: ~10 synthetic scenario templates × 2
  framerates (30/60 fps) × seeds, spanning body sizes (small/far ↔ big/close),
  punch speeds (flurries ↔ slow-sloppy), landmark noise, double jabs — plus
  **negative scenarios** (hanging arms while walking, slow reaches, guard jitter)
  that must call zero. Reward = correct calls − 1.25·phantoms − misses − latency
  penalty. `node eval.mjs` prints the report at the current config.
- **`sweep.mjs`** — random search over the whole config space (both the EMA and
  One Euro smoothers compete). Shardable: run N panes in tmux.
- **`aggregate.mjs`** — merges shards and re-validates finalists on **held-out
  seeds** before crowning a champion, so the winner didn't just overfit the
  training seeds.

```bash
tmux new-session -d -s opt -c app 'node sweep.mjs --shard 0 --of 8 --n 5000 --out results/shard-0.json'
# ...split 7 more panes, then:
node aggregate.mjs
```

Labeled recordings are folded into the reward automatically (weighted 3× — real
clips outrank synthetic ones), so once you've recorded your own punches, every
sweep tunes the detector to *your* body and camera.

## Regression gate (CI)

```bash
node check.mjs   # unit tests + eval suite against hard thresholds
```

Gates: F1 ≥ 0.99, ≤ 3 missed punches, ≤ 4 phantoms, ≤ 80 ms impact latency.
The ready-made workflow lives at `ci/shadowbox-eval.yml`; activate it with

```bash
git mv blueprints/shadowbox-coach/ci/shadowbox-eval.yml .github/workflows/
```

(pushing workflow files needs `gh auth refresh -s workflow` once). It then runs
the gate on every PR touching the blueprint — a threshold "fix" can never
silently regress detection again.

## Eval environment on Arize Phoenix

Every eval run can be published to a local Phoenix instance as a versioned
dataset, following the same conventions as the deal-room-analyst blueprint
(loopback-only endpoint, atomic evidence JSON):

```bash
# start Phoenix (either)
docker run -p 6006:6006 arizephoenix/phoenix
python -m phoenix.server.main serve

node phoenix_export.mjs                 # run suite → upload dataset + write evidence/
node phoenix_export.mjs --dry-run       # evidence JSON only
```

How it works:

1. `eval.mjs` runs every synthetic scenario (per seed) **and every labeled
   recorded clip** through the detector at the current config.
2. Each case becomes one Phoenix dataset example — input: scenario descriptor +
   expected punch sequence; output: the sequence the detector called; metadata:
   counts + the config hash.
3. The dataset name encodes the config hash (`shadowbox-punch-eval-<hash>`), so
   every config you ever ship is a comparable dataset in the Phoenix UI — diff
   two configs by diffing their datasets, exactly like comparing two model
   checkpoints on a benchmark.
4. A self-contained evidence JSON always lands in `../evidence/`, so runs are
   reproducible with no Phoenix running.

The loop in practice: throw punches → mislabeled call → record the clip (`r`) →
it joins the reward function → re-sweep → new champion → CI gate + Phoenix
dataset prove the fix — and prove nothing else regressed.

## What the recordings do (and don't) capture

Clips store **pose landmarks, not video** — so replays are deterministic, files
are ~100 KB, and nothing resembling footage ever exists on disk. The trade-off:
the eval covers everything downstream of MediaPipe (state machine, thresholds,
classification) but cannot re-litigate MediaPipe's own perception errors, and a
clip can't be re-run through a *different* pose model. To A/B pose models, record
separate clips per model (`?model=full` etc.) and replay each.

## Honest limits

2D pose with relative depth is an approximate judge: very fast punches can blur past
landmark detection, gloves hide wrists, and "power" is a speed proxy, not force. Treat
it as a rep counter and rhythm coach, not a referee.
