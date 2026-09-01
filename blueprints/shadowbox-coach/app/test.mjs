// Unit tests for the punch state machine. Run: node test.mjs
//
// 1. Synthetic combo: 5 cycles of jab/cross/hook/uppercut — exact count,
//    exact type sequence, AND CompuBox-grade timing: every punch must score
//    within 150 ms of true peak extension (impact), not on return to guard.
// 2. Double jab: two jabs with only a half retraction between them — the
//    re-arm path must catch both.
//
import { L, HandTracker, makeSmoother, SYNTH, syntheticFrame } from "./punch.js";

const FPS = 60;
let failed = false;

function runFeed(frameFn, totalMs) {
  const hands = { L: new HandTracker("L"), R: new HandTracker("R") };
  const smoother = makeSmoother();
  const events = [];
  for (let t = 0; t <= totalMs; t += 1000 / FPS) {
    const lm = smoother.update(frameFn(t), t);
    const ls = lm.get(L.L_SHOULDER), rs = lm.get(L.R_SHOULDER);
    const sw = Math.hypot(ls.x - rs.x, ls.y - rs.y);
    const ctx = { sw, hipY: (lm.get(L.L_HIP).y + lm.get(L.R_HIP).y) / 2 };
    for (const [hand, wi, ei, si] of [["L", L.L_WRIST, L.L_ELBOW, L.L_SHOULDER], ["R", L.R_WRIST, L.R_ELBOW, L.R_SHOULDER]]) {
      const ev = hands[hand].update(lm.get(wi), lm.get(ei), lm.get(si), ctx, t);
      if (ev) events.push({ t, ...ev });
    }
  }
  return events;
}

function check(name, cond, detail) {
  if (!cond) { failed = true; console.error(`FAIL ${name}: ${detail}`); }
  else console.log(`ok   ${name}`);
}

// ---- 1. combo cycles + impact latency ----
{
  const CYCLES = 5;
  const slotMs = SYNTH.punchMs + SYNTH.gapMs;
  const events = runFeed(syntheticFrame, CYCLES * SYNTH.cycleMs);

  const expected = [];
  for (let c = 0; c < CYCLES; c++) for (const p of SYNTH.combo) expected.push(p.type);
  const got = events.map((e) => e.type);
  check("combo count", got.length === expected.length, `${got.length} events, expected ${expected.length}`);
  check("combo types", got.every((t, i) => t === expected[i]),
    `expected ${expected.join(" ")}, got ${got.join(" ")}`);

  const latencies = events.map((e, i) => {
    const truePeak = i * slotMs + SYNTH.punchMs / 2; // triangle wave peaks mid-window
    return e.t - truePeak;
  });
  const worst = Math.max(...latencies.map(Math.abs));
  console.log(`     impact latency: avg ${(latencies.reduce((a, b) => a + b, 0) / latencies.length).toFixed(0)}ms, worst ${worst.toFixed(0)}ms`);
  check("scores at impact", latencies.every((l) => l >= 0 && l <= 150),
    `latencies ${latencies.map((l) => l.toFixed(0)).join(" ")}ms — must be 0..150ms after peak`);
}

// ---- 2. double jab off a half retraction ----
{
  const d = SYNTH.combo[0].d; // jab delta
  const guard = { x: 0.60, y: 0.30, z: -0.05 };
  // extension fraction k over time: full, back to 0.7, full again, home
  const keys = [[0, 0], [150, 1], [280, 0.7], [380, 1], [600, 0], [900, 0]];
  const kAt = (t) => {
    for (let i = 1; i < keys.length; i++) {
      if (t <= keys[i][0]) {
        const [t0, k0] = keys[i - 1], [t1, k1] = keys[i];
        return k0 + (k1 - k0) * ((t - t0) / (t1 - t0));
      }
    }
    return 0;
  };
  const frameFn = (t) => {
    const lm = syntheticFrame(SYNTH.punchMs + 1); // any frame with both hands in guard
    const k = kAt(t);
    lm[L.L_WRIST] = {
      x: guard.x + d.x * SYNTH.sw * k,
      y: guard.y + d.y * SYNTH.sw * k,
      z: guard.z + d.z * SYNTH.sw * k,
    };
    lm[L.R_WRIST] = { x: 0.40, y: 0.30, z: -0.05 };
    // jabs straighten the arm — elbow tracks toward the shoulder–wrist midpoint
    const s = lm[L.L_SHOULDER], e = lm[L.L_ELBOW], w = lm[L.L_WRIST];
    e.x += ((s.x + w.x) / 2 - e.x) * k;
    e.y += ((s.y + w.y) / 2 - e.y) * k;
    e.z += ((s.z + w.z) / 2 - e.z) * k;
    return lm;
  };
  const events = runFeed(frameFn, 900);
  check("double jab", events.length === 2 && events.every((e) => e.type === "JAB"),
    `expected JAB JAB, got ${events.map((e) => e.type).join(" ") || "(none)"}`);
}

if (failed) process.exit(1);
console.log("OK — scored at impact, double jabs included");
