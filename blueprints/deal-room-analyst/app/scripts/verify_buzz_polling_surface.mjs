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

async function main() {
  const baseUrl = argument("--base-url", "http://127.0.0.1:8787").replace(/\/$/, "");
  const room = argument("--room", "project_titan_lbo");
  const output = path.resolve(ROOT, argument("--output", "evidence/browser-buzz-polling-v1.json"));
  const screenshot = path.resolve(ROOT, argument("--screenshot", "evidence/browser-buzz-polling-v1.png"));
  const delayMs = 4000;
  let activeReads = 0;
  let maxConcurrentReads = 0;
  let requestCount = 0;
  const requestTimeline = [];
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
    await page.route("**/api/workspace/messages?room=*", async (route) => {
      requestCount += 1;
      const index = requestCount;
      const startedAt = Date.now();
      activeReads += 1;
      maxConcurrentReads = Math.max(maxConcurrentReads, activeReads);
      try {
        // The second read is the first interval poll after initial workspace
        // loading. Hold it past the next 3.5 second timer tick.
        if (index === 2) await new Promise((resolve) => setTimeout(resolve, delayMs));
        const response = await route.fetch();
        await route.fulfill({ response });
      } finally {
        activeReads -= 1;
        requestTimeline.push({ index, started_at_ms: startedAt, finished_at_ms: Date.now() });
      }
    });

    await page.goto(`${baseUrl}/rooms/${encodeURIComponent(room)}/discussion`, {
      waitUntil: "networkidle",
    });
    await page.locator("#relay-label").getByText("Buzz workspace ready", { exact: true }).waitFor();
    await page.waitForFunction(() => window.performance.now() > 0);
    const deadline = Date.now() + 16000;
    while ((requestCount < 3 || activeReads !== 0) && Date.now() < deadline) {
      await new Promise((resolve) => setTimeout(resolve, 50));
    }
    await page.evaluate(() => {
      Object.defineProperty(document, "visibilityState", {
        configurable: true,
        get: () => "hidden",
      });
      document.dispatchEvent(new Event("visibilitychange"));
    });
    const hiddenRequestCount = requestCount;
    await new Promise((resolve) => setTimeout(resolve, 3800));
    const hiddenPollSuppressed = requestCount === hiddenRequestCount;
    await page.evaluate(() => {
      Object.defineProperty(document, "visibilityState", {
        configurable: true,
        get: () => "visible",
      });
      document.dispatchEvent(new Event("visibilitychange"));
    });
    const visibleDeadline = Date.now() + 5000;
    while ((requestCount === hiddenRequestCount || activeReads !== 0) && Date.now() < visibleDeadline) {
      await new Promise((resolve) => setTimeout(resolve, 50));
    }
    const statusResponse = await context.request.get(`${baseUrl}/api/status`);
    const status = statusResponse.ok() ? await statusResponse.json() : {};
    const assertions = [
      { name: "delayed_poll_crossed_timer_interval", passed: requestTimeline.some((item) => item.index === 2 && item.finished_at_ms - item.started_at_ms >= 3500) },
      { name: "no_overlapping_message_requests", passed: maxConcurrentReads === 1, observed: maxConcurrentReads },
      { name: "queued_refresh_executed", passed: requestCount >= 3, observed: requestCount },
      { name: "server_reports_inflight_only_policy", passed: status.buzz?.message_reads?.policy === "coalesce_exact_inflight_no_stale_message_cache", observed: status.buzz?.message_reads },
      { name: "verified_messages_remain_visible", passed: await page.locator("#conversation article.message[id^='event-']").count() > 0 },
      { name: "hidden_tab_poll_suppressed", passed: hiddenPollSuppressed, observed: { before: hiddenRequestCount, after: requestCount } },
      { name: "visible_tab_refresh_resumed", passed: requestCount > hiddenRequestCount, observed: { hidden_count: hiddenRequestCount, visible_count: requestCount } },
    ];
    await fs.mkdir(path.dirname(screenshot), { recursive: true });
    await page.screenshot({ path: screenshot, fullPage: true });
    const screenshotBytes = await fs.readFile(screenshot);
    const passed = assertions.every((item) => item.passed)
      && !consoleErrors.length && !failedRequests.length && !httpErrors.length;
    record = {
      verification_kind: "behavioral_buzz_polling_browser_check",
      recorded_at: new Date().toISOString(),
      passed,
      base_url: baseUrl,
      room,
      browser: { engine: "chromium", version: browser.version(), executable: CHROME },
      timing: {
        configured_poll_interval_ms: 3500,
        injected_second_request_delay_ms: delayMs,
        request_count: requestCount,
        max_concurrent_message_requests: maxConcurrentReads,
        timeline: requestTimeline,
        hidden_request_count: hiddenRequestCount,
      },
      observed_server_message_read_policy: status.buzz?.message_reads,
      assertions,
      console_errors: consoleErrors,
      failed_requests: failedRequests,
      http_errors: httpErrors,
      screenshot: {
        path: path.relative(ROOT, screenshot),
        bytes: screenshotBytes.length,
        sha256: crypto.createHash("sha256").update(screenshotBytes).digest("hex"),
      },
      limitations: [
        "This is one Chromium timing control on one workstation, not a Buzz load or soak test.",
        "The delayed response is injected in the browser route; relay latency is not claimed.",
        "The server coalesces only identical in-flight reads and deliberately does not cache completed message lists.",
      ],
    };
    await context.close();
  } finally {
    await browser.close();
  }
  await fs.mkdir(path.dirname(output), { recursive: true });
  await fs.writeFile(output, `${JSON.stringify(record, null, 2)}\n`);
  console.log(JSON.stringify({ output, passed: record.passed, assertions: record.assertions.length }, null, 2));
  return record.passed ? 0 : 1;
}

process.exit(await main());
