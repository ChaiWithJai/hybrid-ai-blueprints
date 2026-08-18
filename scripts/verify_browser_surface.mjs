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
  const output = path.resolve(ROOT, argument("--output", "evidence/browser-first-pass-v7.json"));
  const screenshot = path.resolve(
    ROOT, argument("--screenshot", "evidence/browser-first-pass-v7.png"),
  );
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
    const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
    const page = await context.newPage();
    page.on("console", (message) => {
      if (message.type() === "error") consoleErrors.push(message.text());
    });
    page.on("requestfailed", (request) => {
      failedRequests.push({ url: request.url(), error: request.failure()?.errorText || "unknown" });
    });
    page.on("response", (response) => {
      if (response.status() >= 400) {
        httpErrors.push({ url: response.url(), status: response.status() });
      }
    });

    const apiResponse = await context.request.get(
      `${baseUrl}/api/workspace/first-pass?room=${encodeURIComponent(room)}`,
    );
    if (!apiResponse.ok()) throw new Error(`first-pass API returned ${apiResponse.status()}`);
    const apiBody = await apiResponse.json();
    const draft = apiBody.draft;
    if (!draft?.trace_id) throw new Error("first-pass API returned no trace identity");
    const workspaceResponse = await context.request.get(
      `${baseUrl}/api/workspace?room=${encodeURIComponent(room)}`,
    );
    if (!workspaceResponse.ok()) throw new Error(`workspace API returned ${workspaceResponse.status()}`);
    const workspace = await workspaceResponse.json();
    const statusResponse = await context.request.get(`${baseUrl}/api/status`);
    if (!statusResponse.ok()) throw new Error(`status API returned ${statusResponse.status()}`);
    const runtimeStatus = await statusResponse.json();
    const deploymentRecordPath = path.resolve(ROOT, "evidence/local-deployment-current.json");
    const deploymentRecordBytes = await fs.readFile(deploymentRecordPath);
    const deploymentRecordSha256 = crypto.createHash("sha256").update(
      deploymentRecordBytes,
    ).digest("hex");
    const concurrencyRecord = JSON.parse(await fs.readFile(
      path.resolve(ROOT, "evidence/live-inference-concurrency-v1.json"), "utf8",
    ));
    const reviewTraceId = concurrencyRecord.product_evidence?.trace_id;
    if (!reviewTraceId) throw new Error("live inference record returned no trace identity");
    const evalsResponse = await context.request.get(`${baseUrl}/api/evals`);
    if (!evalsResponse.ok()) throw new Error(`evals API returned ${evalsResponse.status()}`);
    const evalsBody = await evalsResponse.json();
    const reviewTrace = (evalsBody.traces || []).find((trace) => trace.trace_id === reviewTraceId);
    if (!reviewTrace) throw new Error("live inference trace is absent from the eval API");
    const excludedTrace = (evalsBody.traces || []).find(
      (trace) => trace.evaluation_state?.state === "excluded",
    );
    const digestResponse = await context.request.get(
      `${baseUrl}/api/workspace/digest?room=${encodeURIComponent(room)}`,
    );
    if (!digestResponse.ok()) throw new Error(`digest API returned ${digestResponse.status()}`);
    const digest = await digestResponse.json();

    await page.goto(`${baseUrl}/rooms/${encodeURIComponent(room)}/first-pass`, {
      waitUntil: "networkidle",
    });
    await page.waitForFunction(() => (
      document.getElementById("relay-label")?.textContent === "Activity available"
    ));
    await page.getByRole("heading", { name: "Not ready to advance", exact: true }).waitFor();

    assertions.push({
      name: "synthetic_source_provenance_visible",
      passed: workspace.source_provenance?.classification === "synthetic_engineering_fixture"
        && workspace.source_provenance?.synthetic_fixture === true
        && workspace.source_provenance?.customer_data_verified === false
        && workspace.source_provenance?.accuracy_release_evidence === false
        && workspace.source_provenance?.buyer_evidence === false
        && await page.locator("#truth-source-provenance").getByText(
          "Synthetic demonstration fixture", { exact: true },
        ).isVisible(),
      observed: workspace.source_provenance,
    });

    const publishLabel = "Save decision";
    const publish = page.getByRole("button", { name: publishLabel });
    assertions.push({ name: "review_control_visible", passed: await publish.isVisible() });
    assertions.push({ name: "review_control_enabled", passed: await publish.isEnabled() });
    assertions.push({
      name: "trace_visible",
      passed: /^trc_[a-f0-9]+$/.test(draft.trace_id)
        && await page.getByText(`trace ${draft.trace_id}`, { exact: true }).count() === 0,
    });
    assertions.push({
      name: "guard_visible",
      passed: typeof draft.guard_version === "string" && draft.guard_version.length > 0
        && await page.locator("#view-first-pass").getByText(
          draft.guard_version, { exact: true },
        ).count() === 0,
    });
    assertions.push({
      name: "draft_provenance_visible",
      passed: draft.restoration_verification?.state === "verified"
        && draft.restoration_verification?.event_id === draft.draft_event_id
        && draft.restoration_verification?.trace_id === draft.trace_id
        && draft.evidence_scope?.measurement_state
          === "current_parser_inventory_and_trace_bound_passage_selection"
        && draft.evidence_scope?.admitted_passage_count === draft.citations?.length
        && draft.evidence_scope?.semantic_coverage_measured === false
        && draft.evidence_scope?.full_document_review_claimed === false
        && await page.getByRole("heading", { name: "Why the review is paused", exact: true }).isVisible()
        && await page.getByRole("heading", { name: "Review next", exact: true }).isVisible(),
    });
    const invokedInProcess = runtimeStatus.local_inference_invoked_in_process === true;
    assertions.push({
      name: "runtime_state_boundary_visible",
      passed: await page.getByText("Bonsai 27B", { exact: true }).isVisible()
        && await page.getByText("Active", { exact: true }).isVisible()
        && runtimeStatus.local_inference_recorded_history === true
        && (invokedInProcess
          ? runtimeStatus.local_inference_invocation_evidence === "current_process_trace"
            && runtimeStatus.current_process_local_model === runtimeStatus.configured_local_model_name
          : runtimeStatus.local_inference_invocation_evidence === "recorded_trace_history"),
    });
    const citations = page.locator("button[data-source-citation]:visible");
    const citationCount = await citations.count();
    assertions.push({ name: "inline_citations_visible", passed: citationCount > 0, observed: citationCount });
    if (citationCount === 0) throw new Error("no visible citation controls");
    const firstCitation = citations.first();
    const source = await firstCitation.getAttribute("data-source");
    const anchor = await firstCitation.getAttribute("data-anchor");
    const overviewUrl = page.url();
    await firstCitation.click();
    const citationPanel = page.locator("#citation-preview-panel");
    const citationPreviewPassed = page.url() === overviewUrl
      && await citationPanel.isVisible()
      && (await page.locator("#citation-preview-content").innerText()).trim().length > 20;
    await page.getByRole("button", { name: "Open full source", exact: true }).click();
    await page.waitForURL((url) => (
      url.pathname.endsWith("/files")
      && url.searchParams.get("source") === source
      && url.searchParams.get("anchor") === anchor
    ));
    assertions.push({
      name: "canonical_citation_navigation",
      passed: citationPreviewPassed
        && new URL(page.url()).searchParams.get("anchor") === anchor,
      source,
      anchor,
      destination: page.url(),
    });
    assertions.push({
      name: "exact_anchor_preview",
      passed: await page.locator("#source-preview").evaluate((element) => document.activeElement === element)
        && (await page.locator("#source-preview").innerText()).includes(source),
    });

    await page.goto(`${baseUrl}/rooms/${encodeURIComponent(room)}/digest`, {
      waitUntil: "networkidle",
    });
    assertions.push({
      name: "canvas_signature_verified",
      passed: digest.signature_verification?.state === "verified"
        && digest.signature_verification?.scheme === "nip01_event_id_plus_bip340"
        && await page.getByText("Saved team decision", { exact: true }).isVisible()
        && await page.getByRole("heading", { name: "Decision notes", exact: true }).isVisible(),
      observed: digest.signature_verification,
    });

    await page.goto(`${baseUrl}/rooms/${encodeURIComponent(room)}/evidence`, {
      waitUntil: "networkidle",
    });
    const expectedRuntimeNote = invokedInProcess
      ? /A trace created by this server process identifies the returned local model/
      : /prior trace history exists, but this server process has not invoked it/;
    assertions.push({
      name: "trace_derived_runtime_state_card",
      passed: await page.getByText(expectedRuntimeNote).isVisible(),
    });
    const cloudConsent = runtimeStatus.cloud_consent || {};
    assertions.push({
      name: "hybrid_cloud_consent_boundary_visible",
      passed: cloudConsent.default === "deny_before_network"
        && cloudConsent.context_release_requires_distinct_signature === true
        && cloudConsent.relay_restoration_required === true
        && cloudConsent.maximum_consent_lifetime_seconds === 900
        && await page.getByText("Hybrid AI cloud boundary", { exact: true }).isVisible()
        && await page.getByText("Denied before network", { exact: true }).isVisible()
        && await page.getByText(/published to and restored from Buzz/, { exact: false }).isVisible()
        && await page.getByText(/browser cannot turn cloud access on with a checkbox/, { exact: false }).isVisible(),
      observed: cloudConsent,
    });
    const measuredDeployment = runtimeStatus.measured_local_deployment || {};
    assertions.push({
      name: "measured_deployment_identity_visible",
      passed: measuredDeployment.verified === true
        && measuredDeployment.record_sha256 === deploymentRecordSha256
        && measuredDeployment.model === "27b@q1_0"
        && measuredDeployment.artifact_count === 2
        && measuredDeployment.runtime?.effective_config?.fitted_context_length === "16384"
        && measuredDeployment.cache_basis === "record_bytes_plus_artifact_device_inode_size_mtime_ctime"
        && Boolean(measuredDeployment.verified_at)
        && measuredDeployment.artifact_files_verified === true
        && measuredDeployment.active_runtime?.verified === true
        && measuredDeployment.active_runtime?.runtime_version === "2.28.2"
        && measuredDeployment.active_runtime?.effective_config?.fitted_context_length === "16384"
        && measuredDeployment.active_runtime?.effective_config?.bind_host === "127.0.0.1"
        && /^\d{1,5}$/.test(measuredDeployment.active_runtime?.effective_config?.bind_port || "")
        && await page.getByText("Measured deployment identity", { exact: true }).isVisible()
        && await page.getByText(/artifacts and runtime verified/, { exact: false }).isVisible()
        && await page.getByText(/Artifacts are rechecked when file identity changes/, { exact: false }).isVisible()
        && await page.getByText(/process bind 127\.0\.0\.1:/, { exact: false }).isVisible()
        && await page.getByText(/Loopback binding is not a zero-egress, quality, or clean-machine claim/, { exact: false }).isVisible(),
      observed: measuredDeployment,
    });
    assertions.push({
      name: "deployment_and_invocation_states_separate",
      passed: measuredDeployment.verified === true
        && runtimeStatus.local_inference_invoked_in_process === invokedInProcess
        && await page.getByText(expectedRuntimeNote).isVisible(),
      observed: {
        deployment_verified: measuredDeployment.verified,
        invoked_in_process: runtimeStatus.local_inference_invoked_in_process,
      },
    });
    const traceStore = runtimeStatus.trace_store || {};
    assertions.push({
      name: "trace_store_integrity_boundary_visible",
      passed: traceStore.format === "hash_chained_local_jsonl_v1"
        && traceStore.integrity === "hash_chained_not_signed_not_externally_anchored"
        && traceStore.verified === true
        && traceStore.signed === false
        && traceStore.externally_anchored === false
        && /^[a-f0-9]{64}$/.test(traceStore.head_sha256 || "")
        && await page.getByText(/Hash-chained local JSONL/, { exact: false }).isVisible()
        && await page.getByText(/local administrator can rewrite or truncate/, { exact: false }).isVisible(),
      observed: traceStore,
    });
    const pdfOcr = runtimeStatus.document_ingestion?.pdf_ocr || {};
    assertions.push({
      name: "scanned_pdf_ocr_boundary_visible",
      passed: pdfOcr.available === true
        && pdfOcr.engine === "apple_vision_vnrecognizetextrequest"
        && pdfOcr.render_dpi === 300
        && Array.isArray(pdfOcr.limitations)
        && pdfOcr.limitations.some((item) => item.includes("not a measured accuracy score"))
        && await page.getByText("Scanned PDF support", { exact: true }).isVisible()
        && await page.getByText("Apple Vision OCR available", { exact: true }).isVisible()
        && await page.getByText(/accuracy has not been benchmarked/, { exact: false }).isVisible(),
      observed: pdfOcr,
    });
    assertions.push({
      name: "verification_fixture_exclusion_visible",
      passed: evalsBody.excluded_trace_count === 20
        && evalsBody.aggregate_eligible_traces === evalsBody.total_recorded_traces - 20
        && Boolean(excludedTrace)
        && await page.getByText("Ten most recent runs", { exact: true }).isVisible(),
      observed: {
        total_recorded_traces: evalsBody.total_recorded_traces,
        aggregate_eligible_traces: evalsBody.aggregate_eligible_traces,
        excluded_trace_count: evalsBody.excluded_trace_count,
        example_trace_id: excludedTrace?.trace_id || null,
      },
    });
    assertions.push({
      name: "evidence_trace_visible",
      passed: (evalsBody.traces || []).some((trace) => trace.trace_id === draft.trace_id)
        && await page.getByText("Ten most recent runs", { exact: true }).isVisible(),
    });
    const reviewRow = page.locator(`[data-trace-id="${reviewTraceId}"]`);
    assertions.push({
      name: "review_pending_not_rejected",
      passed: reviewTrace.evaluation_state?.state === "awaiting_review"
        && reviewTrace.evaluation_state?.label === "Review pending"
        && await reviewRow.getAttribute("data-evaluation-state") === "awaiting_review"
        && await reviewRow.getByText("Review pending", { exact: true }).isVisible()
        && !await reviewRow.getByText("Guard rejected", { exact: true }).isVisible(),
      observed: reviewTrace.evaluation_state,
      trace_id: reviewTraceId,
    });

    await fs.mkdir(path.dirname(screenshot), { recursive: true });
    await page.screenshot({ path: screenshot, fullPage: true });
    const screenshotBytes = await fs.readFile(screenshot);
    const passed = assertions.every((item) => item.passed)
      && !consoleErrors.length && !failedRequests.length && !httpErrors.length;
    record = {
      verification_kind: "replayable_browser_surface_check",
      recorded_at: new Date().toISOString(),
      passed,
      base_url: baseUrl,
      room,
      browser: { engine: "chromium", version: browser.version(), executable: CHROME },
      artifact: {
        trace_id: draft.trace_id,
        draft_event_id: draft.draft_event_id,
        guard_version: draft.guard_version,
        acceptance_state: draft.acceptance_state,
      },
      observed_runtime_status: {
        configured_model: runtimeStatus.configured_local_model_name,
        current_process_model: runtimeStatus.current_process_local_model,
        last_recorded_model: runtimeStatus.last_invoked_local_model,
        recorded_history: runtimeStatus.local_inference_recorded_history,
        invoked_in_process: runtimeStatus.local_inference_invoked_in_process,
        invocation_evidence: runtimeStatus.local_inference_invocation_evidence,
      },
      observed_measured_deployment: runtimeStatus.measured_local_deployment,
      observed_trace_store: runtimeStatus.trace_store,
      observed_document_ingestion: runtimeStatus.document_ingestion,
      observed_cloud_consent: runtimeStatus.cloud_consent,
      observed_trace_aggregate_boundary: {
        total_recorded_traces: evalsBody.total_recorded_traces,
        aggregate_eligible_traces: evalsBody.aggregate_eligible_traces,
        excluded_trace_count: evalsBody.excluded_trace_count,
      },
      deployment_record_sha256: deploymentRecordSha256,
      observed_canvas_verification: digest.signature_verification,
      observed_review_state: {
        trace_id: reviewTraceId,
        ...reviewTrace.evaluation_state,
      },
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
        "This replays the local Titan surface on one Chrome build, not cross-browser compatibility.",
        "It verifies rendering and navigation, not deal-domain accuracy or accessibility conformance.",
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
