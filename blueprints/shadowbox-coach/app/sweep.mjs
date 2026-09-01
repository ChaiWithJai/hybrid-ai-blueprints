// Random-search sweep over the detector config, scored by eval.mjs.
//
//   node sweep.mjs --shard 0 --of 8 --n 5000 --out results/shard-0.json
//
// Samples candidates across the full threshold space (both smoothers
// compete), evaluates each on the TRAIN seeds, keeps the top 30.
// aggregate.mjs re-validates winners on held-out seeds.
import fs from "node:fs";
import { CFG } from "./punch.js";
import { runSuite, mulberry32 } from "./eval.mjs";

const arg = (name, dflt) => {
  const i = process.argv.indexOf(`--${name}`);
  return i > -1 ? process.argv[i + 1] : dflt;
};
const SHARD = Number(arg("shard", 0));
const N = Number(arg("n", 3000));
const OUT = arg("out", `results/shard-${SHARD}.json`);
export const TRAIN_SEEDS = [1, 2, 3];

const rng = mulberry32(1337 + SHARD * 99991);
const uni = (lo, hi) => lo + rng() * (hi - lo);
const pick = (a) => a[Math.floor(rng() * a.length)];

function sample() {
  const extendAt = uni(1.0, 1.3);
  const c = {
    extendAt,
    returnAt: Math.min(extendAt - 0.1, uni(0.75, 1.05)),
    peakDrop: uni(0.04, 0.15),
    rearm: uni(0.12, 0.32),
    minPeakSpeed: uni(1.4, 3.2),
    armSpeed: uni(0.6, 2.4),
    guardWindowMs: uni(300, 900),
    elbowArm: uni(145, 168),
    elbowStraight: uni(120, 152),
    cooldownMs: uni(70, 170),
    zWeight: uni(0.45, 0.95),
    speedAlpha: uni(0.35, 1.0),
    armFrames: pick([1, 1, 2, 2, 3]),
    smoother: pick(["ema", "ema", "oneeuro"]),
    smooth: uni(0.35, 0.85),
    minCutoff: uni(0.6, 3.0),
    euroBeta: uni(0.005, 0.12),
  };
  if (c.elbowStraight > c.elbowArm - 8) c.elbowStraight = c.elbowArm - 8;
  return c;
}

const BASELINE = { ...CFG };
Object.assign(CFG, BASELINE);
const baseline = runSuite(TRAIN_SEEDS);
console.log(`[shard ${SHARD}] baseline reward ${baseline.reward.toFixed(1)} F1 ${baseline.f1.toFixed(3)}`);

const top = [];
const t0 = Date.now();
for (let i = 0; i < N; i++) {
  const cand = sample();
  Object.assign(CFG, BASELINE, cand);
  const res = runSuite(TRAIN_SEEDS);
  top.push({ cand, reward: res.reward, f1: res.f1, tp: res.tp, fp: res.fp, fn: res.fn, meanLat: res.meanLat });
  top.sort((a, b) => b.reward - a.reward);
  if (top.length > 30) top.length = 30;
  if ((i + 1) % 500 === 0) {
    const rate = (i + 1) / ((Date.now() - t0) / 1000);
    console.log(`[shard ${SHARD}] ${i + 1}/${N}  best ${top[0].reward.toFixed(1)} (F1 ${top[0].f1.toFixed(3)})  ${rate.toFixed(0)}/s`);
  }
}

fs.mkdirSync("results", { recursive: true });
fs.writeFileSync(OUT, JSON.stringify({ shard: SHARD, n: N, baseline, top }, null, 1));
console.log(`[shard ${SHARD}] done → ${OUT}  best ${top[0].reward.toFixed(1)}`);
