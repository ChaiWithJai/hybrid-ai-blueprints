// Merge sweep shards, re-validate the winners on HELD-OUT seeds (the
// anti-overfit step), and print the champion config.
//
//   node aggregate.mjs
//
import fs from "node:fs";
import { CFG } from "./punch.js";
import { runSuite } from "./eval.mjs";

const HOLDOUT_SEEDS = [11, 12, 13];
const BASELINE = { ...CFG };

const shards = fs.readdirSync("results").filter((f) => f.startsWith("shard-"));
if (!shards.length) { console.error("no results/shard-*.json found"); process.exit(1); }
let all = [];
for (const f of shards) {
  const j = JSON.parse(fs.readFileSync(`results/${f}`, "utf8"));
  all.push(...j.top);
}
all.sort((a, b) => b.reward - a.reward);
console.log(`${shards.length} shards, ${all.length} finalists; best train reward ${all[0].reward.toFixed(1)}`);

Object.assign(CFG, BASELINE);
const baseHold = runSuite(HOLDOUT_SEEDS);
console.log(`baseline holdout: reward ${baseHold.reward.toFixed(1)} F1 ${baseHold.f1.toFixed(3)} (tp ${baseHold.tp} fp ${baseHold.fp} fn ${baseHold.fn}, lat ${baseHold.meanLat.toFixed(0)}ms)`);

const finalists = all.slice(0, 60);
const validated = [];
for (const f of finalists) {
  Object.assign(CFG, BASELINE, f.cand);
  const res = runSuite(HOLDOUT_SEEDS);
  validated.push({ ...f, holdout: { reward: res.reward, f1: res.f1, tp: res.tp, fp: res.fp, fn: res.fn, meanLat: res.meanLat } });
}
validated.sort((a, b) => b.holdout.reward - a.holdout.reward);

console.log("\ntop 5 by HOLDOUT reward:");
for (const v of validated.slice(0, 5)) {
  console.log(`  train ${v.reward.toFixed(1)} | holdout ${v.holdout.reward.toFixed(1)} F1 ${v.holdout.f1.toFixed(3)} (tp ${v.holdout.tp} fp ${v.holdout.fp} fn ${v.holdout.fn}, lat ${v.holdout.meanLat.toFixed(0)}ms) | ${v.cand.smoother}`);
}
const best = validated[0];
fs.writeFileSync("results/best.json", JSON.stringify(best, null, 2));
console.log("\nchampion config → results/best.json");
console.log(JSON.stringify(best.cand, null, 2));
