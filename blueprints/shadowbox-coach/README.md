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
- CompuBox-style scorecard: jabs vs power punches, plus a round-by-round table
- Punches-per-minute, fastest-hand speed (in shoulder-widths/sec — scale-invariant)
- 3:00 round / 1:00 rest timer; the coach speaks between rounds
- **Corner coach:** round stats go to whatever model LM Studio has loaded
  (`http://localhost:1234`). No LM Studio? It falls back to canned corner talk.

## Run it

```bash
cd blueprints/shadowbox-coach/app
python3 -m http.server 4790
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

Press **`d`** in the app for a live debug readout of reach/speed/phase per hand — use it
to tune the thresholds at the top of `app.js` for your setup.

## Honest limits

2D pose with relative depth is an approximate judge: very fast punches can blur past
landmark detection, gloves hide wrists, and "power" is a speed proxy, not force. Treat
it as a rep counter and rhythm coach, not a referee.
