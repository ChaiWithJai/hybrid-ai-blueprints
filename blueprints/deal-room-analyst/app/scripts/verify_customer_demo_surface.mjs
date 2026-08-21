#!/usr/bin/env node

import crypto from "node:crypto";
import fs from "node:fs/promises";
import path from "node:path";
import process from "node:process";
import { chromium } from "playwright-core";

const ROOT = path.resolve(path.dirname(new URL(import.meta.url).pathname), "..");
const CHROME = process.env.PRISM_BROWSER_EXECUTABLE || chromium.executablePath();

function argument(name, fallback) {
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

async function main() {
  const baseUrl = argument("--base-url", "http://127.0.0.1:8787").replace(/\/$/, "");
  const room = argument("--room", "project_titan_lbo");
  const output = path.resolve(ROOT, argument("--output", "evidence/browser-customer-demo-v1.json"));
  const desktopScreenshot = path.resolve(ROOT, "evidence/browser-customer-demo-desktop-v1.png");
  const mobileScreenshot = path.resolve(ROOT, "evidence/browser-customer-demo-mobile-v1.png");
  const roomUrl = `${baseUrl}/rooms/${encodeURIComponent(room)}/first-pass`;
  const assertions = [];
  const consoleErrors = [];
  const failedRequests = [];
  const httpErrors = [];
  const viewports = [];
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

    await page.goto(roomUrl, { waitUntil: "networkidle" });
    await page.locator("#room-name").waitFor();
    await page.locator("#draft-section").waitFor({ state: "visible" });

    const roomName = (await page.locator("#room-name").innerText()).trim();
    assertions.push({
      name: "room_identity_is_clear",
      passed: roomName.includes("Project Titan")
        && await page.locator("#copy-room-link").isVisible()
        && await page.locator("#toggle-context").isVisible(),
      observed: roomName,
    });
    const modelInitiallyVisible = await page.locator("#context-panel").evaluate((element) => element.classList.contains("open"));
    await page.locator("#toggle-context").click();
    const modelVisibleInDetails = await page.locator("#context-panel").evaluate((element) => element.classList.contains("open"));
    assertions.push({
      name: "strategy_state_is_secondary",
      passed: !modelInitiallyVisible && modelVisibleInDetails
        && (await page.locator("#model-name").innerText()).trim() === "Bonsai 27B",
    });
    await page.locator("#toggle-context").click();

    const primaryTabs = page.locator('.workspace-tabs > [role="tab"]');
    const primaryTabLabels = await primaryTabs.allTextContents();
    assertions.push({
      name: "primary_navigation_is_plain",
      passed: JSON.stringify(primaryTabLabels.map((item) => item.trim()))
        === JSON.stringify(["Overview", "Sources", "Activity", "Evaluation"]),
      observed: primaryTabLabels,
    });
    const tabAreaText = await page.locator(".workspace-tabs").innerText();
    assertions.push({
      name: "retired_programs_are_outside_primary_navigation",
      passed: !/benchmark|pricing/i.test(tabAreaText),
      observed: tabAreaText,
    });
    const decisionPath = await page.evaluate(() => {
      const ids = [
        "#draft-recommendation",
        '[data-content-id="segment.pause_reason"]',
        '[data-content-id="segment.decision_question_result"]',
        '[data-content-id="segment.priority_sources"]',
        '[data-content-id="segment.team_decision"]',
      ];
      const elements = ids.map((selector) => document.querySelector(selector));
      return {
        visible: elements.every((element) => element && getComputedStyle(element).display !== "none"),
        order: elements.map((element) => element?.getBoundingClientRect().top ?? -1),
        title: document.querySelector("#draft-recommendation")?.textContent?.trim(),
        editor_hidden: getComputedStyle(document.querySelector(".first-pass-grid")).display === "none",
      };
    });
    assertions.push({
      name: "decision_status_has_priority",
      passed: decisionPath.visible && decisionPath.editor_hidden
        && decisionPath.title === "Not ready to advance"
        && decisionPath.order.every((top, index) => index === 0 || top > decisionPath.order[index - 1])
        && await page.getByRole("button", { name: "Edit question", exact: true }).isVisible(),
      observed: decisionPath,
    });
    assertions.push({
      name: "decision_question_is_specific",
      passed: await page.getByText(
        "Should Project Titan advance despite the mismatch between debt paydown and the Section 2.02 cash sweep terms?",
        { exact: true },
      ).isVisible(),
    });
    const prioritySources = page.locator('[data-content-id="segment.priority_sources"] [data-source-citation]');
    const prioritySourceGroup = page.locator('[data-content-id="segment.priority_sources"]');
    assertions.push({
      name: "priority_sources_are_grouped",
      passed: await prioritySources.count() === 4
        && await prioritySourceGroup.getByText("Debt terms", { exact: true }).isVisible()
        && await prioritySourceGroup.getByText("Financial model", { exact: true }).isVisible()
        && await prioritySourceGroup.getByText("Sponsor returns", { exact: true }).isVisible()
        && await prioritySourceGroup.getByText("Deal overview", { exact: true }).isVisible(),
      observed: await prioritySources.allTextContents(),
    });

    const firstCitation = prioritySources.first();
    const expectedSource = await firstCitation.getAttribute("data-source");
    const expectedAnchor = await firstCitation.getAttribute("data-anchor");
    const overviewUrl = page.url();
    await firstCitation.click();
    const citationPanel = page.locator("#citation-preview-panel");
    assertions.push({
      name: "citation_preview_preserves_current_view",
      passed: page.url() === overviewUrl
        && await citationPanel.isVisible()
        && await citationPanel.getAttribute("role") === "dialog"
        && await citationPanel.getAttribute("aria-hidden") === "false"
        && await page.locator("#close-citation-preview").evaluate((element) => document.activeElement === element)
        && (await page.locator("#citation-preview-meta").innerText()).includes(expectedSource)
        && (await page.locator("#citation-preview-content").innerText()).trim().length > 20,
      observed: { url: page.url(), source: expectedSource, anchor: expectedAnchor },
    });

    await page.getByRole("button", { name: "Ask about this", exact: true }).click();
    const composerContextObserved = {
      panel_hidden: await citationPanel.getAttribute("aria-hidden"),
      context_visible: await page.locator("#composer-context").isVisible(),
      context_label: await page.locator("#composer-context-label").innerText(),
      input_focused: await page.locator("#message-input").evaluate((element) => document.activeElement === element),
    };
    assertions.push({
      name: "citation_context_reaches_persistent_composer",
      passed: composerContextObserved.panel_hidden === "true"
        && composerContextObserved.context_visible
        && composerContextObserved.context_label.includes("Debt terms")
        && composerContextObserved.input_focused,
      observed: composerContextObserved,
    });

    await firstCitation.click();
    await page.getByRole("button", { name: "Open full source", exact: true }).click();
    const citationUrl = new URL(page.url());
    assertions.push({
      name: "citation_preview_opens_exact_full_source",
      passed: citationUrl.pathname.endsWith("/files")
        && citationUrl.searchParams.get("source") === expectedSource
        && citationUrl.searchParams.get("anchor") === expectedAnchor
        && await page.locator("#source-preview").evaluate((element) => document.activeElement === element)
        && (await page.locator("#source-preview").innerText()).includes(expectedSource),
      observed: page.url(),
    });

    await page.locator('[data-file-index="2"]').click();
    const csvRows = await page.locator("#source-preview .source-table tbody tr").count();
    await page.locator('[data-file-index="3"]').click();
    const jsonFields = await page.locator("#source-preview .json-object > div").count();
    assertions.push({
      name: "supported_source_formats_render_semantically",
      passed: csvRows > 1 && jsonFields > 1
        && await page.locator("#source-preview pre").count() === 0,
      observed: { csv_rows: csvRows, json_fields: jsonFields },
    });

    await page.getByRole("tab", { name: "Activity", exact: true }).click();
    const activityUrl = new URL(page.url());
    assertions.push({
      name: "activity_keeps_canonical_room_url",
      passed: activityUrl.pathname === `/rooms/${room}/discussion`
        && await page.locator("#message-form").isVisible()
        && await page.getByText("Ask Bonsai", { exact: true }).isVisible(),
      observed: page.url(),
    });
    const backgroundHistory = page.locator("#conversation .activity-history");
    assertions.push({
      name: "activity_separates_background_events",
      passed: await backgroundHistory.count() === 1
        && /background events/i.test(await backgroundHistory.locator("summary").innerText())
        && await page.locator("#conversation .message-stream .message").count() > 0
        && !/\[SOURCE\s+\[/i.test(await page.locator("#conversation .message-stream").innerText()),
    });

    const composerViews = {};
    for (const view of ["Overview", "Sources", "Activity", "Evaluation"]) {
      await page.getByRole("tab", { name: view, exact: true }).click();
      composerViews[view] = await page.locator("#message-form").isVisible();
    }
    assertions.push({
      name: "composer_is_available_in_all_primary_views",
      passed: Object.values(composerViews).every(Boolean),
      observed: composerViews,
    });

    const decisionNotes = page.getByRole("button", { name: "Decision notes", exact: true });
    const technicalDetails = page.getByRole("button", { name: "Technical details", exact: true });
    const secondaryInitiallyHidden = !await page.locator("#context-panel").evaluate((element) => element.classList.contains("open"));
    await page.locator("#toggle-context").click();
    assertions.push({
      name: "secondary_views_are_in_room_details",
      passed: secondaryInitiallyHidden
        && await page.locator("#context-panel").evaluate((element) => element.classList.contains("open"))
        && await decisionNotes.isVisible() && await technicalDetails.isVisible(),
    });

    for (const width of [390, 768, 1440]) {
      await page.setViewportSize({ width, height: width === 390 ? 844 : 1000 });
      await page.goto(roomUrl, { waitUntil: "networkidle" });
      await page.locator("#draft-section").waitFor({ state: "visible" });
      viewports.push(await page.evaluate(() => ({
        width: window.innerWidth,
        scroll_width: document.documentElement.scrollWidth,
        selected_view: document.querySelector('[role="tab"][aria-selected="true"]')?.textContent?.trim(),
      })));
      if (width === 1440) {
        await fs.mkdir(path.dirname(desktopScreenshot), { recursive: true });
        await page.screenshot({ path: desktopScreenshot, fullPage: true });
      }
      if (width === 390) {
        await fs.mkdir(path.dirname(mobileScreenshot), { recursive: true });
        await page.screenshot({ path: mobileScreenshot, fullPage: true });
      }
    }
    assertions.push({
      name: "required_viewports_have_no_horizontal_overflow",
      passed: viewports.length === 3
        && viewports.every((item) => item.width === item.scroll_width && item.selected_view === "Overview"),
      observed: viewports,
    });

    const failures = assertions.filter((item) => item.passed !== true);
    const screenshots = [
      await fileRecord(desktopScreenshot),
      await fileRecord(mobileScreenshot),
    ];
    const passed = failures.length === 0 && consoleErrors.length === 0
      && failedRequests.length === 0 && httpErrors.length === 0;
    record = {
      schema_version: 1,
      verification_kind: "customer_demo_browser_surface.v1",
      semantic_state: passed ? "current_customer_demo_surface" : "failed",
      recorded_at: new Date().toISOString(),
      asset_version: "hybrid-eval-lab-v1",
      room,
      canonical_url: roomUrl,
      browser: { engine: "chromium", version: browser.version(), executable: CHROME },
      assertions,
      assertion_count: assertions.length,
      viewports,
      console_errors: consoleErrors,
      failed_requests: failedRequests,
      http_errors: httpErrors,
      screenshots,
      passed,
      limitations: [
        "The browser replay checks the current demo contract. It is not a human usability study.",
        "The replay does not certify deal accuracy, commercial demand, production security, or browser support outside this Chromium build.",
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
