#!/usr/bin/env node

import crypto from "node:crypto";
import fs from "node:fs/promises";
import path from "node:path";
import process from "node:process";
import { firefox, webkit } from "playwright-core";

const ROOT = path.resolve(path.dirname(new URL(import.meta.url).pathname), "..");

function argument(name, fallback = null) {
  const index = process.argv.indexOf(name);
  return index >= 0 && process.argv[index + 1] ? process.argv[index + 1] : fallback;
}

async function fileRecord(file) {
  const bytes = await fs.readFile(file);
  return {
    path: path.relative(ROOT, file),
    bytes: bytes.length,
    sha256: crypto.createHash("sha256").update(bytes).digest("hex"),
  };
}

async function verifyEngine({ name, browserType, demoUrl, screenshot }) {
  const assertions = [];
  const consoleErrors = [];
  const failedRequests = [];
  const httpErrors = [];
  const browser = await browserType.launch({ headless: true });
  try {
    const context = await browser.newContext({ viewport: { width: 1280, height: 900 } });
    const page = await context.newPage();
    page.on("console", (message) => {
      if (message.type() === "error") consoleErrors.push(message.text());
    });
    page.on("requestfailed", (request) => {
      failedRequests.push({ url: request.url(), error: request.failure()?.errorText || "unknown" });
    });
    page.on("response", (response) => {
      if (response.status() >= 400) httpErrors.push({ url: response.url(), status: response.status() });
    });
    await page.goto(demoUrl, { waitUntil: "networkidle" });
    await page.locator("#draft-section").waitFor({ state: "visible" });
    assertions.push({
      name: "deal_brief_visible",
      passed: await page.locator("#first-pass-draft").isVisible()
        && await page.getByRole("button", { name: "Edit question", exact: true }).isVisible(),
    });
    assertions.push({
      name: "customer_navigation_visible",
      passed: JSON.stringify((await page.locator('.workspace-tabs > [role="tab"]').allTextContents()).map((item) => item.trim()))
        === JSON.stringify(["Overview", "Sources", "Activity", "Evaluation"]),
    });
    const citations = page.locator('.priority-source[data-source-citation]:visible');
    assertions.push({ name: "source_citation_controls_visible", passed: await citations.count() > 0 });
    assertions.push({
      name: "semantic_tab_contract_visible",
      passed: await page.locator('[role="tab"]').count() === 4
        && await page.locator('[role="tabpanel"]').count() === 4
        && await page.locator('[role="tab"][aria-selected="true"]').count() === 1,
    });
    const sourcesTab = page.getByRole("tab", { name: "Sources", exact: true });
    await sourcesTab.focus();
    await page.keyboard.press("ArrowRight");
    const activityTab = page.getByRole("tab", { name: "Activity", exact: true });
    assertions.push({
      name: "keyboard_tab_navigation_works",
      passed: await activityTab.getAttribute("aria-selected") === "true"
        && await activityTab.evaluate((element) => document.activeElement === element),
    });
    await page.goto(demoUrl, { waitUntil: "networkidle" });
    await page.locator("#draft-section").waitFor({ state: "visible" });
    const citation = page.locator('.priority-source[data-source-citation]:visible').first();
    const source = await citation.getAttribute("data-source");
    const anchor = await citation.getAttribute("data-anchor");
    await citation.focus();
    await page.keyboard.press("Enter");
    const citationPanel = page.locator("#citation-preview-panel");
    assertions.push({
      name: "keyboard_citation_preview_is_exact",
      passed: new URL(page.url()).pathname.endsWith("/first-pass")
        && await citationPanel.isVisible()
        && (await page.locator("#citation-preview-meta").innerText()).includes(source)
        && !((await page.locator("#citation-preview-content").innerText()).includes("Passage unavailable"))
        && (await page.locator("#citation-preview-content").innerText()).trim().length > 20,
      observed: page.url(),
    });
    assertions.push({
      name: "citation_preview_focus_is_contained",
      passed: await page.locator("#close-citation-preview").evaluate((element) => document.activeElement === element),
    });
    await page.getByRole("button", { name: "Open full source", exact: true }).click();
    const destination = new URL(page.url());
    const preview = page.locator("#source-preview");
    assertions.push({
      name: "citation_full_source_navigation_is_exact",
      passed: destination.pathname.endsWith("/files")
        && destination.searchParams.get("source") === source
        && destination.searchParams.get("anchor") === anchor
        && await preview.evaluate((element) => document.activeElement === element),
      observed: page.url(),
    });
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto(demoUrl, { waitUntil: "networkidle" });
    await page.locator("#draft-section").waitFor({ state: "visible" });
    const geometry = await page.evaluate(() => ({
      viewport: document.documentElement.clientWidth,
      document: document.documentElement.scrollWidth,
      body: document.body.scrollWidth,
    }));
    assertions.push({
      name: "mobile_width_has_no_page_overflow",
      passed: geometry.document <= geometry.viewport && geometry.body <= geometry.viewport,
      observed: geometry,
    });
    await fs.mkdir(path.dirname(screenshot), { recursive: true });
    await page.screenshot({ path: screenshot, fullPage: true });
    const failures = assertions.filter((item) => item.passed !== true);
    return {
      engine: name,
      version: browser.version(),
      passed: failures.length === 0 && consoleErrors.length === 0
        && failedRequests.length === 0 && httpErrors.length === 0,
      assertions,
      assertion_count: assertions.length,
      console_errors: consoleErrors,
      failed_requests: failedRequests,
      http_errors: httpErrors,
      screenshot: await fileRecord(screenshot),
    };
  } finally {
    await browser.close();
  }
}

async function main() {
  const baseUrl = argument("--base-url", "http://127.0.0.1:8787").replace(/\/$/, "");
  const room = argument("--room", "project_titan_lbo");
  const output = path.resolve(ROOT, argument("--output", "evidence/browser-cross-engine-customer-demo-v1.json"));
  const demoUrl = `${baseUrl}/rooms/${encodeURIComponent(room)}/first-pass`;
  const engineInputs = [
    {
      name: "firefox",
      browserType: firefox,
      screenshot: path.resolve(ROOT, "evidence/browser-cross-engine-customer-demo-firefox-v1.png"),
    },
    {
      name: "webkit",
      browserType: webkit,
      screenshot: path.resolve(ROOT, "evidence/browser-cross-engine-customer-demo-webkit-v1.png"),
    },
  ];
  const engines = [];
  for (const input of engineInputs) {
    engines.push(await verifyEngine({ ...input, demoUrl }));
  }
  const passed = engines.every((engine) => engine.passed);
  const record = {
    schema_version: 1,
    verification_kind: "cross_browser_real_deal_surface",
    semantic_state: passed
      ? "firefox_and_webkit_pass_not_safari_or_accuracy"
      : "failed",
    recorded_at: new Date().toISOString(),
    room,
    engines,
    engine_count: engines.length,
    assertion_count: engines.reduce((count, engine) => count + engine.assertion_count, 0),
    passed,
    limitations: [
      "The check covers Playwright Firefox and WebKit builds. It does not test Safari, Chrome, Edge, or installed user extensions.",
      "The check covers the current Project Titan demo and is not WCAG conformance or assistive technology review.",
      "The check does not assess deal accuracy or commercial demand.",
    ],
  };
  await fs.writeFile(output, `${JSON.stringify(record, null, 2)}\n`);
  process.stdout.write(`${JSON.stringify(record, null, 2)}\n`);
  if (!passed) process.exitCode = 1;
}

main().catch((error) => {
  console.error(error.stack || error.message);
  process.exitCode = 1;
});
