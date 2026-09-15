// Export the punch-detector eval run to Arize Phoenix as a versioned dataset.
//
//   node phoenix_export.mjs [--endpoint http://localhost:6006] [--dry-run]
//
// How the eval environment works end to end:
//   1. eval.mjs runs every synthetic scenario (per seed) and every labeled
//      recorded clip through the detector at the CURRENT config.
//   2. Each case becomes one Phoenix dataset example:
//        input    = scenario name, fps, noise, actor params, expected sequence
//        output   = the sequence the detector actually called
//        metadata = tp / fp / fn / mean impact latency + the config hash
//   3. The dataset is uploaded via Phoenix's REST API (loopback only, unless
//      --allow-remote) under a name that encodes the config hash, so every
//      config you ever ship is a comparable dataset version in the Phoenix UI.
//   4. A self-contained evidence JSON is always written to evidence/ — the
//      same pattern as the deal-room-analyst Phoenix exports — so the run is
//      reproducible even with no Phoenix running.
import fs from "node:fs";
import path from "node:path";
import crypto from "node:crypto";
import { fileURLToPath } from "node:url";
import { CFG } from "./punch.js";
import { makeScenarios, runScenario, loadRecordingCases, runRecordingCase, runSuite } from "./eval.mjs";

const APP = path.dirname(fileURLToPath(import.meta.url));
const arg = (name, dflt) => {
  const i = process.argv.indexOf(`--${name}`);
  return i > -1 ? (process.argv[i + 1] ?? true) : dflt;
};
const ENDPOINT = String(arg("endpoint", "http://localhost:6006")).replace(/\/$/, "");
const DRY = process.argv.includes("--dry-run");
const ALLOW_REMOTE = process.argv.includes("--allow-remote");

const host = new URL(ENDPOINT).hostname;
if (!DRY && !ALLOW_REMOTE && host !== "localhost" && host !== "127.0.0.1" && host !== "::1") {
  console.error(`refusing non-loopback endpoint ${ENDPOINT} without --allow-remote`);
  process.exit(1);
}

const SEEDS = [1, 2, 3, 11, 12, 13];
const cfgHash = crypto.createHash("sha256").update(JSON.stringify(CFG)).digest("hex").slice(0, 8);

// ---- run every case and build examples ----
const inputs = [], outputs = [], metadata = [];
function addCase(name, kind, params, expected, events) {
  const exp = expected.map((e) => e.type), got = events.map((e) => e.type);
  // simple counts here; the suite-level F1 comes from runSuite below
  inputs.push({ case: name, kind, ...params, expected_sequence: exp.join(" ") || "(none)" });
  outputs.push({ called_sequence: got.join(" ") || "(none)", calls: got.length });
  metadata.push({ expected_count: exp.length, called_count: got.length, config_hash: cfgHash });
}
for (const seed of SEEDS) {
  for (const scn of makeScenarios()) {
    const { expected, events } = runScenario(scn, seed);
    addCase(scn.name, "synthetic", { seed, fps: scn.fps, noise: scn.noise ?? 0.003 }, expected, events);
  }
}
for (const rc of loadRecordingCases()) {
  const { expected, events } = runRecordingCase(rc);
  addCase(rc.name, "recorded", { frames: rc.frames.length }, expected, events);
}
const suite = runSuite(SEEDS);
const datasetName = `shadowbox-punch-eval-${cfgHash}`;

// ---- evidence JSON (always) ----
const evidence = {
  dataset: datasetName,
  exported_at: new Date().toISOString(),
  config: CFG,
  config_hash: cfgHash,
  suite: { f1: suite.f1, reward: suite.reward, tp: suite.tp, fp: suite.fp, fn: suite.fn, mean_latency_ms: suite.meanLat },
  examples: inputs.map((inp, i) => ({ input: inp, output: outputs[i], metadata: metadata[i] })),
};
const evDir = path.join(APP, "..", "evidence");
fs.mkdirSync(evDir, { recursive: true });
const evPath = path.join(evDir, `phoenix-shadowbox-eval-${cfgHash}.json`);
const tmp = evPath + ".tmp";
fs.writeFileSync(tmp, JSON.stringify(evidence, null, 2) + "\n");
fs.renameSync(tmp, evPath);
console.log(`evidence → ${path.relative(process.cwd(), evPath)} (${inputs.length} examples)`);
console.log(`suite: F1 ${suite.f1.toFixed(3)}  tp ${suite.tp} fp ${suite.fp} fn ${suite.fn}  lat ${suite.meanLat.toFixed(0)}ms  config ${cfgHash}`);

// ---- push to Phoenix ----
if (DRY) { console.log("dry-run: skipping Phoenix upload"); process.exit(0); }
try {
  const res = await fetch(`${ENDPOINT}/v1/datasets/upload?sync=true`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    signal: AbortSignal.timeout(15000),
    body: JSON.stringify({
      action: "create",
      name: datasetName,
      description: `Shadowbox punch-detector eval @ config ${cfgHash} — F1 ${suite.f1.toFixed(3)}, tp ${suite.tp}, fp ${suite.fp}, fn ${suite.fn}, mean latency ${suite.meanLat.toFixed(0)}ms`,
      inputs, outputs, metadata,
    }),
  });
  if (!res.ok) throw new Error(`${res.status} ${await res.text()}`);
  const body = await res.json().catch(() => ({}));
  console.log(`phoenix: dataset "${datasetName}" uploaded → ${ENDPOINT}/datasets`, body.data?.dataset_id ?? "");
} catch (e) {
  console.error(`phoenix upload failed (${e.message}) — evidence JSON is still complete.`);
  console.error(`start Phoenix locally with: python -m phoenix.server.main serve  (or docker run -p 6006:6006 arizephoenix/phoenix)`);
  process.exit(2);
}
