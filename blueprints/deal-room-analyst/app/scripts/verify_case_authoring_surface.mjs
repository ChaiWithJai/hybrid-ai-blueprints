#!/usr/bin/env node

import crypto from "node:crypto";
import fs from "node:fs/promises";
import path from "node:path";
import process from "node:process";
import { chromium } from "playwright-core";

const ROOT = path.resolve(path.dirname(new URL(import.meta.url).pathname), "..");
const CHROME = process.env.PRISM_BROWSER_EXECUTABLE || chromium.executablePath();

async function main() {
  const baseUrl = (process.env.PRISM_BASE_URL || "http://127.0.0.1:8787").replace(/\/$/, "");
  const output = path.resolve(ROOT, "evidence/browser-case-authoring-v1.json");
  const screenshot = path.resolve(ROOT, "evidence/browser-case-authoring-v1.png");
  const consoleErrors = [];
  const failedRequests = [];
  const httpErrors = [];
  const assertions = [];
  const browser = await chromium.launch({
    executablePath: CHROME,
    headless: true,
    args: ["--disable-background-networking"],
  });
  let record;
  try {
    const context = await browser.newContext({ viewport: { width: 1600, height: 1100 } });
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

    const authoringResponse = await context.request.get(`${baseUrl}/api/benchmark/case-authoring`);
    if (!authoringResponse.ok()) {
      throw new Error(`case authoring API returned ${authoringResponse.status()}`);
    }
    const authoring = await authoringResponse.json();
    await page.goto(`${baseUrl}/benchmark/case-authoring`, { waitUntil: "networkidle" });
    await page.getByText("No drafts have cleared source review", { exact: true }).waitFor();

    const assertVisible = async (name, value) => {
      assertions.push({ name, passed: await page.getByText(value, { exact: true }).isVisible() });
    };
    await assertVisible(
      "empty_source_review_gate",
      "No drafts have cleared source review",
    );
    await assertVisible(
      "queue_count_matches_api",
      `${authoring.eligible_draft_count} eligible · ${authoring.drafts.length} total`,
    );
    await assertVisible(
      "approval_and_registration_truth",
      `${authoring.eligible_draft_count} eligible · ${authoring.pipeline.case_approval.recorded_approval_count} approvals recorded · ${authoring.pipeline.registration.candidate_cases_registered} registered`,
    );
    assertions.push({
      name: "owner_control_closed",
      passed: await page.locator("#domain-owner-id").isDisabled(),
    });
    assertions.push({
      name: "unsigned_export_closed",
      passed: await page.getByRole("button", { name: "Download unsigned approval" }).isDisabled(),
    });
    assertions.push({
      name: "no_preselected_evaluation_slice",
      passed: await page.locator('.slice-options input:checked').count() === 0,
    });
    assertions.push({
      name: "api_preserves_stage_boundaries",
      passed: authoring.browser_owner_authentication_ready === false
        && authoring.unsigned_export_ready === false
        && authoring.pipeline.calibration.calibration_passed === false
        && authoring.pipeline.release.accuracy_release_ready === false,
    });

    await fs.mkdir(path.dirname(screenshot), { recursive: true });
    await page.screenshot({ path: screenshot, fullPage: true });
    const screenshotBytes = await fs.readFile(screenshot);
    const passed = assertions.every((item) => item.passed)
      && !consoleErrors.length && !failedRequests.length && !httpErrors.length;
    record = {
      verification_kind: "replayable_case_authoring_browser_check",
      recorded_at: new Date().toISOString(),
      passed,
      base_url: baseUrl,
      assertions,
      observed_state: {
        eligible_draft_count: authoring.eligible_draft_count,
        total_draft_count: authoring.drafts.length,
        owner_roster_ready: authoring.owner_roster_ready,
        browser_owner_authentication_ready: authoring.browser_owner_authentication_ready,
        unsigned_export_ready: authoring.unsigned_export_ready,
        pipeline: authoring.pipeline,
      },
      console_errors: consoleErrors,
      failed_requests: failedRequests,
      http_errors: httpErrors,
      screenshot: {
        path: path.relative(ROOT, screenshot),
        bytes: screenshotBytes.length,
        sha256: crypto.createHash("sha256").update(screenshotBytes).digest("hex"),
      },
      limitations: [
        "This verifies the rendered empty gate and unsigned export boundary, not domain accuracy.",
        "No source reviews or case approvals have been created by this browser check.",
      ],
    };
    await context.close();
  } finally {
    await browser.close();
  }
  await fs.writeFile(output, `${JSON.stringify(record, null, 2)}\n`);
  console.log(JSON.stringify({ output, passed: record.passed, assertions: record.assertions.length }, null, 2));
  return record.passed ? 0 : 1;
}

process.exit(await main());
