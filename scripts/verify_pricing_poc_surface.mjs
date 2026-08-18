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
  const output = path.resolve(ROOT, "evidence/browser-pricing-poc-v1.json");
  const screenshot = path.resolve(ROOT, "evidence/browser-pricing-poc-v1.png");
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
    const context = await browser.newContext({ viewport: { width: 1500, height: 1100 } });
    const page = await context.newPage();
    page.on("console", message => { if (message.type() === "error") consoleErrors.push(message.text()); });
    page.on("requestfailed", request => failedRequests.push({ url: request.url(), error: request.failure()?.errorText || "unknown" }));
    page.on("response", response => { if (response.status() >= 400) httpErrors.push({ url: response.url(), status: response.status() }); });
    const apiResponse = await context.request.get(`${baseUrl}/api/benchmark/pricing-poc`);
    if (!apiResponse.ok()) throw new Error(`pricing POC API returned ${apiResponse.status()}`);
    const status = await apiResponse.json();
    await page.goto(`${baseUrl}/benchmark/pricing-poc`, { waitUntil: "networkidle" });
    await page.getByText("No qualifying buyer proof recorded", { exact: true }).waitFor();
    const visible = async (name, text) => assertions.push({ name, passed: await page.getByText(text, { exact: true }).isVisible() });
    await visible("honest_empty_state", "No qualifying buyer proof recorded");
    await visible("buyer_authority_blocker_visible", "Set a commercial authority key and Buzz channel after an out-of-band buyer identity check. A self-issued buyer key cannot qualify.");
    await visible("zero_of_ten_gates", "0/10");
    await visible("value_unit_visible", "One accepted first pass review");
    await visible("paid_poc_gate_visible", "Paid proof of concept");
    await visible("two_private_deals_gate_visible", "Two private historical deals");
    await visible("transfer_gate_visible", "Setup and transfer");
    await visible("post_use_price_gate_visible", "Post-use price range");
    await visible("buyer_attestation_gate_visible", "Buyer attestation");
    const buyerRequirement = status.requirements.find(item => item.id === "buyer_signature");
    await visible("buyer_relay_restoration_visible", buyerRequirement.requirement);
    await visible("public_demo_boundary_visible", status.public_demo_boundary);
    await visible("unsigned_builder_visible", "Build the buyer's unsigned POC record");
    assertions.push({
      name: "buyer_private_key_not_requested",
      passed: await page.getByText("It never asks for source text or a private key.", { exact: false }).isVisible()
        && await page.locator('input[id*="private"], input[name*="private"]').count() === 0,
    });
    assertions.push({
      name: "unsigned_builder_starts_blank",
      passed: await page.locator("#pricing-record-form input:checked").count() === 0
        && await page.locator('#pricing-record-form input:not([type="checkbox"])').evaluateAll(nodes => nodes.every(node => !node.value)),
    });
    assertions.push({
      name: "api_preserves_unmeasured_state",
      passed: status.evidence_state === "not_recorded"
        && status.pricing_poc_passed === false
        && status.relay_restored === false
        && status.buyer_authority_configured === false
        && status.buyer_authority_verified === false
        && status.deal_count === 0
        && status.requirements.length === 10,
    });
    await fs.mkdir(path.dirname(screenshot), { recursive: true });
    await page.screenshot({ path: screenshot, fullPage: true });
    const screenshotBytes = await fs.readFile(screenshot);
    const passed = assertions.every(item => item.passed)
      && !consoleErrors.length && !failedRequests.length && !httpErrors.length;
    record = {
      verification_kind: "replayable_pricing_poc_browser_check",
      recorded_at: new Date().toISOString(),
      passed,
      base_url: baseUrl,
      assertions,
      observed_state: {
        evidence_state: status.evidence_state,
        pricing_poc_passed: status.pricing_poc_passed,
        relay_restored: status.relay_restored,
        buyer_authority_configured: status.buyer_authority_configured,
        buyer_authority_verified: status.buyer_authority_verified,
        deal_count: status.deal_count,
        requirement_count: status.requirements.length,
        record_expected_at: status.record_expected_at,
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
        "This verifies the pricing contract and honest empty state. It does not create buyer evidence.",
        "Synthetic evaluator tests do not establish willingness to pay or revenue.",
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
