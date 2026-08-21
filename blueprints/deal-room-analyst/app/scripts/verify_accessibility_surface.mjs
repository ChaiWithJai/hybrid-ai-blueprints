#!/usr/bin/env node

import crypto from "node:crypto";
import fs from "node:fs/promises";
import path from "node:path";
import process from "node:process";
import { chromium } from "playwright-core";

const ROOT = path.resolve(path.dirname(new URL(import.meta.url).pathname), "..");
const CHROME = process.env.PRISM_BROWSER_EXECUTABLE || chromium.executablePath();

function argument(name, fallback = null) {
  const index = process.argv.indexOf(name);
  return index >= 0 && process.argv[index + 1] ? process.argv[index + 1] : fallback;
}

async function sha256(file) {
  return crypto.createHash("sha256").update(await fs.readFile(file)).digest("hex");
}

async function main() {
  const baseUrl = argument("--base-url", "http://127.0.0.1:8787").replace(/\/$/, "");
  const room = argument("--room", "project_titan_lbo");
  const output = path.resolve(ROOT, argument("--output", "evidence/browser-accessibility-customer-demo-v1.json"));
  const screenshot = path.resolve(ROOT, argument("--screenshot", "evidence/browser-accessibility-customer-demo-v1.png"));
  const assertions = [];
  const consoleErrors = [];
  const failedRequests = [];
  const httpErrors = [];
  const browser = await chromium.launch({
    executablePath: CHROME,
    headless: true,
    args: ["--disable-background-networking"],
  });
  let record;
  try {
    const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
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

    const demoUrl = `${baseUrl}/rooms/${encodeURIComponent(room)}/first-pass`;
    await page.goto(demoUrl, { waitUntil: "networkidle" });
    await page.locator("#draft-section").waitFor({ state: "visible" });

    assertions.push({ name: "document_language_declared", passed: await page.locator("html").getAttribute("lang") === "en" });
    assertions.push({ name: "single_main_landmark", passed: await page.locator("main").count() === 1 });
    assertions.push({ name: "single_page_heading", passed: await page.locator("h1:visible").count() === 1 });
    const duplicateIds = await page.locator("[id]").evaluateAll((elements) => {
      const counts = new Map();
      for (const element of elements) counts.set(element.id, (counts.get(element.id) || 0) + 1);
      return [...counts].filter(([, count]) => count > 1).map(([id]) => id);
    });
    assertions.push({ name: "document_ids_unique", passed: duplicateIds.length === 0, observed: duplicateIds });

    const tabs = page.locator('[role="tab"]');
    assertions.push({
      name: "room_views_use_tab_contract",
      passed: await tabs.count() === 4
        && await page.locator('[role="tablist"]').count() === 1
        && await page.locator('[role="tabpanel"]').count() === 4,
    });
    assertions.push({
      name: "one_tab_selected_and_focusable",
      passed: await page.locator('[role="tab"][aria-selected="true"][tabindex="0"]').count() === 1
        && await page.locator('[role="tab"][aria-selected="false"][tabindex="-1"]').count() === 3,
    });
    assertions.push({
      name: "inactive_panels_hidden",
      passed: await page.locator('[role="tabpanel"][hidden]').count() === 3
        && await page.locator('[role="tabpanel"]:not([hidden])').count() === 1,
    });

    const unnamedControls = await page.locator("button:visible, a[href]:visible, input:visible, textarea:visible, select:visible").evaluateAll((elements) => elements.filter((element) => {
      const labels = element.labels ? [...element.labels].map((label) => label.innerText).join(" ") : "";
      const name = element.getAttribute("aria-label") || element.getAttribute("aria-labelledby")
        || labels || element.innerText || element.textContent || element.getAttribute("title");
      return !String(name || "").trim();
    }).map((element) => `${element.tagName.toLowerCase()}#${element.id || "(no-id)"}`));
    assertions.push({ name: "visible_controls_have_names", passed: unnamedControls.length === 0, observed: unnamedControls });

    const sourcesTab = page.getByRole("tab", { name: "Sources", exact: true });
    await sourcesTab.focus();
    await page.keyboard.press("ArrowRight");
    const activityTab = page.getByRole("tab", { name: "Activity", exact: true });
    assertions.push({
      name: "arrow_keys_move_and_activate_tabs",
      passed: await activityTab.evaluate((element) => document.activeElement === element)
        && await activityTab.getAttribute("aria-selected") === "true"
        && !await page.locator("#view-conversation").getAttribute("hidden"),
    });
    const focusStyle = await activityTab.evaluate((element) => {
      const style = getComputedStyle(element);
      return { outlineStyle: style.outlineStyle, outlineWidth: style.outlineWidth };
    });
    assertions.push({
      name: "keyboard_focus_is_visible",
      passed: focusStyle.outlineStyle !== "none" && Number.parseFloat(focusStyle.outlineWidth) >= 2,
      observed: focusStyle,
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
      name: "citation_preview_is_keyboard_operable",
      passed: new URL(page.url()).pathname.endsWith("/first-pass")
        && await citationPanel.isVisible()
        && await citationPanel.getAttribute("role") === "dialog"
        && await citationPanel.getAttribute("aria-modal") === "true",
      observed: page.url(),
    });
    assertions.push({
      name: "citation_preview_receives_and_traps_focus",
      passed: await page.locator("#close-citation-preview").evaluate((element) => document.activeElement === element),
    });
    assertions.push({
      name: "citation_preview_contains_exact_passage",
      passed: (await page.locator("#citation-preview-meta").innerText()).includes(source)
        && !((await page.locator("#citation-preview-content").innerText()).includes("Passage unavailable"))
        && (await page.locator("#citation-preview-content").innerText()).trim().length > 20,
    });
    await page.keyboard.press("Shift+Tab");
    assertions.push({
      name: "citation_preview_tab_loop_is_contained",
      passed: await page.locator("#open-full-source").evaluate((element) => document.activeElement === element),
    });
    await page.keyboard.press("Escape");
    const restoredCitationFocus = await page.evaluate(() => ({
      panel_hidden: document.querySelector("#citation-preview-panel")?.getAttribute("aria-hidden"),
      active_tag: document.activeElement?.tagName,
      active_text: document.activeElement?.textContent?.trim(),
      active_source: document.activeElement?.getAttribute("data-source"),
      active_anchor: document.activeElement?.getAttribute("data-anchor"),
    }));
    assertions.push({
      name: "citation_preview_escape_restores_trigger",
      passed: restoredCitationFocus.panel_hidden === "true"
        && restoredCitationFocus.active_source === source
        && restoredCitationFocus.active_anchor === anchor,
      observed: restoredCitationFocus,
    });
    await citation.press("Enter");
    await page.getByRole("button", { name: "Open full source", exact: true }).click();
    const preview = page.locator("#source-preview");
    assertions.push({
      name: "citation_full_source_is_exact",
      passed: new URL(page.url()).pathname.endsWith("/files")
        && new URL(page.url()).searchParams.get("source") === source
        && new URL(page.url()).searchParams.get("anchor") === anchor
        && await preview.evaluate((element) => document.activeElement === element),
      observed: page.url(),
    });

    await page.getByRole("button", { name: "Open folder", exact: true }).click();
    const dialog = page.locator("#folder-dialog");
    assertions.push({
      name: "folder_dialog_traps_initial_focus",
      passed: await dialog.evaluate((element) => element.open && element.contains(document.activeElement)),
    });
    await page.keyboard.press("Escape");
    assertions.push({
      name: "dialog_escape_restores_trigger_focus",
      passed: !await dialog.evaluate((element) => element.open)
        && await page.locator("#open-folder-button").evaluate((element) => document.activeElement === element),
    });

    await page.emulateMedia({ reducedMotion: "reduce" });
    const motionStyle = await page.locator("#context-panel").evaluate((element) => {
      const style = getComputedStyle(element);
      return { transitionDuration: style.transitionDuration, scrollBehavior: getComputedStyle(document.documentElement).scrollBehavior };
    });
    assertions.push({
      name: "reduced_motion_disables_animation",
      passed: motionStyle.transitionDuration === "0s" && motionStyle.scrollBehavior === "auto",
      observed: motionStyle,
    });

    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto(demoUrl, { waitUntil: "networkidle" });
    await page.locator("#draft-section").waitFor({ state: "visible" });
    const mobileGeometry = await page.evaluate(() => ({
      viewport: document.documentElement.clientWidth,
      document: document.documentElement.scrollWidth,
      body: document.body.scrollWidth,
    }));
    assertions.push({
      name: "mobile_page_has_no_unintended_horizontal_overflow",
      passed: mobileGeometry.document <= mobileGeometry.viewport && mobileGeometry.body <= mobileGeometry.viewport,
      observed: mobileGeometry,
    });
    const undersizedTargets = await page.locator("button:visible, a[href]:visible, input:visible, textarea:visible").evaluateAll((elements) => elements.filter((element) => {
      if (element.classList.contains("secondary-tab")) return false;
      if (element.closest("details:not([open])")) return false;
      const target = element.matches("input") && element.labels?.length ? element.labels[0] : element;
      const rect = target.getBoundingClientRect();
      return rect.width < 24 || rect.height < 24;
    }).map((element) => ({
      ...(element.matches("input") && element.labels?.length
        ? { measured_target: "associated-label" }
        : { measured_target: "control" }),
      target: `${element.tagName.toLowerCase()}#${element.id || element.getAttribute("aria-label") || element.textContent.trim().slice(0, 30)}`,
      class_name: element.className,
      parent_details_open: element.closest("details")?.open ?? null,
      width: Math.round((element.matches("input") && element.labels?.length ? element.labels[0] : element).getBoundingClientRect().width),
      height: Math.round((element.matches("input") && element.labels?.length ? element.labels[0] : element).getBoundingClientRect().height),
    })));
    assertions.push({ name: "visible_targets_are_at_least_24_pixels", passed: undersizedTargets.length === 0, observed: undersizedTargets });

    await fs.mkdir(path.dirname(screenshot), { recursive: true });
    await page.screenshot({ path: screenshot, fullPage: true });
    const browserVersion = browser.version();
    const failures = assertions.filter((assertion) => !assertion.passed);
    record = {
      schema_version: 1,
      verification_kind: "browser_accessibility_smoke",
      semantic_state: failures.length || consoleErrors.length || failedRequests.length || httpErrors.length
        ? "failed"
        : "accessibility_smoke_pass_not_conformance",
      recorded_at: new Date().toISOString(),
      room,
      browser: { engine: "chromium", version: browserVersion, executable: CHROME },
      assertions,
      assertion_count: assertions.length,
      console_errors: consoleErrors,
      failed_requests: failedRequests,
      http_errors: httpErrors,
      screenshot: {
        path: path.relative(ROOT, screenshot),
        bytes: (await fs.stat(screenshot)).size,
        sha256: await sha256(screenshot),
      },
      passed: failures.length === 0 && consoleErrors.length === 0
        && failedRequests.length === 0 && httpErrors.length === 0,
      limitations: [
        "This is an automated keyboard and semantic smoke check, not WCAG conformance or assistive-technology review.",
        "It covers one Chromium build and two viewport sizes. It does not test other browsers.",
        "It does not assess deal accuracy or commercial demand.",
      ],
    };
  } finally {
    await browser.close();
  }
  await fs.writeFile(output, `${JSON.stringify(record, null, 2)}\n`);
  process.stdout.write(`${JSON.stringify(record, null, 2)}\n`);
  if (!record.passed) process.exitCode = 1;
}

main().catch((error) => {
  console.error(error.stack || error.message);
  process.exitCode = 1;
});
