// Replay a recorded session through the detection pipeline.
//
//   node replay.mjs recordings/<file>.json [key=value ...]
//   node replay.mjs recordings/*.json extendAt=1.05 minPeakSpeed=1.8
//
// key=value pairs override CFG for the replay, so thresholds can be tuned
// against real labeled punches without touching the app.
import fs from "node:fs";
import { L, CFG, HandTracker, LandmarkSmoother } from "./punch.js";

const files = [];
for (const arg of process.argv.slice(2)) {
  const m = arg.match(/^([a-zA-Z]+)=(-?[\d.]+)$/);
  if (m) {
    if (!(m[1] in CFG)) { console.error(`unknown CFG key: ${m[1]}`); process.exit(1); }
    CFG[m[1]] = Number(m[2]);
    console.log(`override ${m[1]} = ${m[2]}`);
  } else files.push(arg);
}
if (!files.length) {
  console.error("usage: node replay.mjs recordings/<file>.json [cfgKey=value ...]");
  process.exit(1);
}

for (const file of files) {
  const rec = JSON.parse(fs.readFileSync(file, "utf8"));
  const hands = { L: new HandTracker("L"), R: new HandTracker("R") };
  const smoother = new LandmarkSmoother();
  const events = [];
  let frames = 0;

  for (const f of rec.frames) {
    frames++;
    const raw = [];
    for (const [i, p] of Object.entries(f.lm)) raw[i] = p;
    const lm = smoother.update(raw);
    const ls = lm.get(L.L_SHOULDER), rs = lm.get(L.R_SHOULDER);
    const sw = Math.hypot(ls.x - rs.x, ls.y - rs.y);
    if (sw < 0.02) continue;
    const ctx = { sw, hipY: (lm.get(L.L_HIP).y + lm.get(L.R_HIP).y) / 2 };
    for (const [hand, wi, ei, si] of [["L", L.L_WRIST, L.L_ELBOW, L.L_SHOULDER], ["R", L.R_WRIST, L.R_ELBOW, L.R_SHOULDER]]) {
      const ev = hands[hand].update(lm.get(wi), lm.get(ei), lm.get(si), ctx, f.t);
      if (ev) events.push({ t: f.t, ...ev });
    }
  }

  const t0 = rec.frames[0]?.t ?? 0;
  const counts = {};
  for (const e of events) counts[e.type] = (counts[e.type] || 0) + 1;
  console.log(`\n=== ${file}`);
  console.log(`label: "${rec.label}"  frames: ${frames}  duration: ${((rec.frames.at(-1)?.t - t0) / 1000).toFixed(1)}s`);
  console.log(`replay called ${events.length}:`, JSON.stringify(counts));
  for (const e of events) {
    console.log(`  ${((e.t - t0) / 1000).toFixed(2)}s  ${e.hand} ${e.type}  ${e.speed.toFixed(1)} sw/s`);
  }
  if (rec.events?.length || events.length) {
    const live = rec.events?.map((e) => e.type).join(" ") || "(none)";
    const now = events.map((e) => e.type).join(" ") || "(none)";
    if (live !== now) console.log(`live app called: ${live}\nreplay calls:    ${now}`);
    else console.log("replay matches what the live app called");
  }
}
