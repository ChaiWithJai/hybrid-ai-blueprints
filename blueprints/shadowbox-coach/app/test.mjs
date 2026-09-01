// Unit test for the punch state machine: run the synthetic sparring partner
// through the same pipeline the app uses and check the count and types.
//
//   node test.mjs
//
import { L, HandTracker, LandmarkSmoother, SYNTH, syntheticFrame } from "./punch.js";

const CYCLES = 5;
const FPS = 60;
const hands = { L: new HandTracker("L"), R: new HandTracker("R") };
const smoother = new LandmarkSmoother();
const events = [];

const totalMs = CYCLES * SYNTH.cycleMs;
for (let t = 0; t <= totalMs; t += 1000 / FPS) {
  const lm = smoother.update(syntheticFrame(t));
  const ls = lm.get(L.L_SHOULDER), rs = lm.get(L.R_SHOULDER);
  const sw = Math.hypot(ls.x - rs.x, ls.y - rs.y);
  for (const [hand, wi, si] of [["L", L.L_WRIST, L.L_SHOULDER], ["R", L.R_WRIST, L.R_SHOULDER]]) {
    const ev = hands[hand].update(lm.get(wi), lm.get(si), sw, t);
    if (ev) events.push(ev);
  }
}

const expected = [];
for (let c = 0; c < CYCLES; c++) for (const p of SYNTH.combo) expected.push(p.type);
const got = events.map((e) => e.type);

const counts = {};
for (const e of events) counts[e.type] = (counts[e.type] || 0) + 1;
console.log(`events: ${got.length} (expected ${expected.length})`);
console.log("counts:", counts);
console.log("speeds:", events.slice(0, 4).map((e) => e.speed.toFixed(1)).join(" "), "sw/s");

let ok = got.length === expected.length && got.every((t, i) => t === expected[i]);
if (!ok) {
  console.error("MISMATCH");
  console.error("expected:", expected.join(" "));
  console.error("got:     ", got.join(" "));
  process.exit(1);
}
console.log("OK — every synthetic punch counted and classified correctly");
