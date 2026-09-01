// Regression gate: unit tests + the eval suite, with hard thresholds.
// A threshold "fix" can never silently regress detection again.
//
//   node check.mjs        → exit 0 only if everything passes
//
import { spawnSync } from "node:child_process";
import { runSuite, loadRecordingCases } from "./eval.mjs";

const GATES = {
  minF1: 0.99,    // overall F1 across the synthetic suite (+ recordings)
  maxFN: 3,       // missed punches across all seeds
  maxFP: 4,       // phantom punches across all seeds
  maxMeanLat: 80, // ms from true peak to the scored call
};

let failed = false;
const gate = (name, ok, detail) => {
  console.log(`${ok ? "ok  " : "FAIL"} ${name}  ${detail}`);
  if (!ok) failed = true;
};

console.log("== unit tests ==");
const t = spawnSync("node", ["test.mjs"], { stdio: "inherit", cwd: new URL(".", import.meta.url).pathname });
if (t.status !== 0) failed = true;

console.log("\n== eval suite ==");
const res = runSuite([1, 2, 3, 11, 12, 13]);
gate("F1", res.f1 >= GATES.minF1, `${res.f1.toFixed(3)} (gate ≥ ${GATES.minF1})`);
gate("missed punches", res.fn <= GATES.maxFN, `${res.fn} (gate ≤ ${GATES.maxFN})`);
gate("phantom punches", res.fp <= GATES.maxFP, `${res.fp} (gate ≤ ${GATES.maxFP})`);
gate("impact latency", Math.abs(res.meanLat) <= GATES.maxMeanLat, `${res.meanLat.toFixed(0)}ms (gate ≤ ${GATES.maxMeanLat}ms)`);
const recs = loadRecordingCases();
console.log(`(recorded ground-truth clips included: ${recs.length})`);

if (failed) { console.error("\nGATE FAILED — this change regresses punch detection."); process.exit(1); }
console.log("\nGATE PASSED");
