#!/usr/bin/env node
/**
 * Capture the CareLine console screenshots used in the documentation.
 *
 * Drives the real browser client against a running server, so a screenshot can
 * never show a state the product cannot reach. It writes the PNG files and a
 * manifest recording the route, state, viewport, and SHA-256 of each file.
 *
 * Requirements:
 *   - the server running on --base-url (blueprints/careline-voice-checkin/scripts/run)
 *   - one demo cycle already run, so memory and one alert exist:
 *       uv run python scripts/demo_run.py
 *   - playwright-core and its chromium:
 *       (cd ../../deal-room-analyst/app && npm install && npm run setup:browser)
 *
 * Point CARELINE_DB at a scratch file before the demo run to capture the state a
 * reader reaches on a first pass, rather than an accumulation of local runs.
 *
 * Usage:
 *   node scripts/capture_screenshots.mjs \
 *     --base-url http://127.0.0.1:8100 \
 *     --out ../../../docs/assets/screenshots/careline
 */

import crypto from "node:crypto";
import fs from "node:fs/promises";
import path from "node:path";
import process from "node:process";
import { execFileSync } from "node:child_process";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const APP = path.resolve(path.dirname(new URL(import.meta.url).pathname), "..");
const DEAL_ROOM_APP = path.resolve(APP, "..", "..", "deal-room-analyst", "app");

function argument(name, fallback) {
  const index = process.argv.indexOf(name);
  return index >= 0 && process.argv[index + 1] ? process.argv[index + 1] : fallback;
}

// playwright-core is declared by the deal room application. Resolving from there
// keeps this blueprint free of a second node dependency tree for one script.
function loadChromium() {
  try {
    return require(path.join(DEAL_ROOM_APP, "node_modules", "playwright-core")).chromium;
  } catch {
    throw new Error(
      `playwright-core not found. Run: (cd ${DEAL_ROOM_APP} && npm install && npm run setup:browser)`
    );
  }
}

const VIEWPORT = { width: 1440, height: 900 };

// The resident's line is scripted so the concern signals, and therefore the
// severity and score shown in the alert panel, are the same on every capture.
const RESIDENT_REPLY =
  "I felt dizzy this morning and I had a little fall in the kitchen. It gave me a fright.";

const SHOTS = [
  {
    id: "careline_console",
    file: "careline-console.png",
    route: "/",
    state:
      "Care demo mid-call: memory-aware greeting, the resident's reply, the agent's " +
      "follow-up, one escalation alert with its signals and score, and dated facts " +
      "recalled from earlier calls.",
  },
];

async function main() {
  const baseUrl = argument("--base-url", "http://127.0.0.1:8100").replace(/\/$/, "");
  const outDir = path.resolve(APP, argument("--out", "../../../docs/assets/screenshots/careline"));
  const chromium = loadChromium();

  await fs.mkdir(outDir, { recursive: true });
  const browser = await chromium.launch({
    executablePath: process.env.PRISM_BROWSER_EXECUTABLE || chromium.executablePath(),
  });

  const written = [];
  try {
    const page = await browser.newPage({ viewport: VIEWPORT, deviceScaleFactor: 2 });
    page.on("console", (m) => {
      if (m.type() === "error") console.error(`  browser console error: ${m.text()}`);
    });

    await page.goto(`${baseUrl}/`, { waitUntil: "networkidle" });

    // The generic self-voice label must survive: a captured screenshot showing
    // one operator's name would be wrong for everyone else.
    const selfLabel = (await page.locator('#mode option[value="self"]').textContent()) || "";
    if (/—\s*\S+\s*\(your cloned voice\)/.test(selfLabel)) {
      throw new Error(
        `refusing to capture: the self-voice option names an operator (${selfLabel.trim()}). ` +
          "Unset CARELINE_SELF_NAME before capturing."
      );
    }

    await page.click("#start");
    await page.waitForFunction(() => document.querySelectorAll("#log > *").length >= 1, {
      timeout: 120000,
    });

    await page.fill("#text", RESIDENT_REPLY);
    await page.click("#send");
    await page.waitForFunction(() => document.querySelectorAll("#log > *").length >= 3, {
      timeout: 180000,
    });

    // The alert and memory panels are what make the shot worth taking.
    await page.waitForFunction(
      () => !document.querySelector("#alerts .empty") && !document.querySelector("#facts .empty"),
      { timeout: 60000 }
    );

    for (const shot of SHOTS) {
      const target = path.join(outDir, shot.file);
      await page.screenshot({ path: target, fullPage: false });
      const bytes = await fs.readFile(target);
      written.push({
        id: shot.id,
        path: shot.file,
        route: shot.route,
        state: shot.state,
        width: VIEWPORT.width * 2,
        height: VIEWPORT.height * 2,
        sha256: crypto.createHash("sha256").update(bytes).digest("hex"),
      });
      console.log(`  wrote ${shot.file} (${bytes.length} bytes)`);
    }
  } finally {
    await browser.close();
  }

  let commit = "unknown";
  try {
    commit = execFileSync("git", ["rev-parse", "HEAD"], { cwd: APP }).toString().trim();
  } catch {}

  const manifest = {
    schema_version: "1.0",
    blueprint: "careline-voice-checkin",
    captured_at: new Date().toISOString(),
    source_commit: commit,
    application_url: `${baseUrl}/`,
    fixture: "dorothy_synthetic_resident",
    fixture_class: "synthetic_demo",
    viewport: VIEWPORT,
    screenshots: written,
    claim_boundary:
      "Dorothy is a synthetic resident and the transcript is generated. These " +
      "images show the product path only. They are not accuracy, clinical, or " +
      "customer evidence, and the escalation scoring they display is a " +
      "deterministic keyword and threshold rule, not a clinical assessment.",
  };
  const manifestPath = path.join(outDir, "manifest.json");
  await fs.writeFile(manifestPath, JSON.stringify(manifest, null, 2) + "\n");
  console.log(`  wrote ${path.relative(APP, manifestPath)}`);
}

main().catch((error) => {
  console.error(error.message || error);
  process.exit(1);
});
