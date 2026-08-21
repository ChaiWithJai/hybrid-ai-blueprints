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
  const folder = path.resolve(process.env.PRISM_PREVIEW_FOLDER || path.join(ROOT, "deal_rooms/sample_ma_acquisition"));
  const output = path.resolve(ROOT, "evidence/browser-folder-preview-v1.json");
  const screenshot = path.resolve(ROOT, "evidence/browser-folder-preview-v1.png");
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

    const roomsBeforeResponse = await context.request.get(`${baseUrl}/api/deal-rooms`);
    if (!roomsBeforeResponse.ok()) throw new Error(`deal room API returned ${roomsBeforeResponse.status()}`);
    const roomsBefore = await roomsBeforeResponse.json();

    await page.goto(baseUrl, { waitUntil: "networkidle" });
    await page.getByRole("button", { name: "Open a deal room" }).click();
    const urlBeforePreview = page.url();
    assertions.push({
      name: "preview_is_first_action",
      passed: await page.getByRole("button", { name: "Preview folder" }).isVisible(),
    });
    await page.locator("#folder-path").fill(folder);
    const responsePromise = page.waitForResponse(response =>
      response.url() === `${baseUrl}/api/deal-room/preview` && response.request().method() === "POST"
    );
    await page.getByRole("button", { name: "Preview folder" }).click();
    const previewResponse = await responsePromise;
    const preview = await previewResponse.json();
    await page.getByRole("button", { name: "Create private room" }).waitFor();

    const roomsAfterResponse = await context.request.get(`${baseUrl}/api/deal-rooms`);
    const roomsAfter = await roomsAfterResponse.json();
    const beforeIds = roomsBefore.map(room => room.id).sort();
    const afterIds = roomsAfter.map(room => room.id).sort();
    assertions.push({
      name: "preview_api_is_read_only",
      passed: previewResponse.status() === 200
        && preview.verification_kind === "local_deal_room_preview"
        && preview.preview_state === "ready"
        && preview.buzz_write_performed === false
        && preview.room_registered === false
        && JSON.stringify(beforeIds) === JSON.stringify(afterIds),
    });
    assertions.push({
      name: "content_hash_is_bound",
      passed: /^[a-f0-9]{64}$/.test(preview.preview_sha256)
        && preview.files.every(file => /^[a-f0-9]{64}$/.test(file.source_sha256)),
    });
    assertions.push({
      name: "supported_inventory_visible",
      passed: await page.getByText(`${preview.document_count} supported files`, { exact: true }).isVisible()
        && await page.locator("#folder-preview-files li").count() === preview.document_count
        && preview.document_count > 0,
    });
    assertions.push({
      name: "no_publish_boundary_visible",
      passed: await page.getByText("Nothing has been published. Review the inventory, then create the room.", { exact: true }).isVisible()
        && await page.getByText("Source bytes stay in the selected folder.", { exact: false }).isVisible(),
    });
    assertions.push({
      name: "creation_requires_second_action",
      passed: await page.getByRole("button", { name: "Create private room" }).isVisible()
        && page.url() === urlBeforePreview,
    });

    await fs.mkdir(path.dirname(screenshot), { recursive: true });
    await page.locator("#folder-dialog").screenshot({ path: screenshot });
    const screenshotBytes = await fs.readFile(screenshot);
    const passed = assertions.every(item => item.passed)
      && !consoleErrors.length && !failedRequests.length && !httpErrors.length;
    record = {
      verification_kind: "replayable_folder_preview_browser_check",
      recorded_at: new Date().toISOString(),
      passed,
      base_url: baseUrl,
      folder_fixture: path.relative(ROOT, folder),
      preview: {
        preview_state: preview.preview_state,
        preview_sha256: preview.preview_sha256,
        room_id: preview.room_id,
        document_count: preview.document_count,
        warning_count: preview.warnings.length,
        buzz_write_performed: preview.buzz_write_performed,
        room_registered: preview.room_registered,
        source_inventory_sha256: crypto.createHash("sha256").update(
          JSON.stringify(preview.files.map(file => ({
            filename: file.filename,
            file_type: file.file_type,
            raw_size_bytes: file.raw_size_bytes,
            estimated_tokens: file.estimated_tokens,
            table_count: file.table_count,
            source_sha256: file.source_sha256,
          })))
        ).digest("hex"),
      },
      room_ids_before_sha256: crypto.createHash("sha256").update(JSON.stringify(beforeIds)).digest("hex"),
      room_ids_after_sha256: crypto.createHash("sha256").update(JSON.stringify(afterIds)).digest("hex"),
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
        "This uses a repository engineering fixture, not a customer deal room.",
        "It verifies preview and non-publication behavior. It does not measure model quality.",
        "The browser check intentionally stops before creating a Buzz room.",
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
