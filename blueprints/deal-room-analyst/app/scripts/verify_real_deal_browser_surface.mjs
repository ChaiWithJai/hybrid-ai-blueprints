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


async function main() {
  const baseUrl = argument("--base-url", "http://127.0.0.1:8787").replace(/\/$/, "");
  const room = argument("--room");
  const eventId = argument("--event");
  const sourceFileArgument = argument("--source-file");
  const expectedValue = argument("--expected-value");
  const expectedAnchor = argument("--expected-anchor");
  const expectedAnchors = argument("--expected-anchors", expectedAnchor)?.split(",").filter(Boolean);
  const previewAnchor = argument("--preview-anchor", expectedAnchor);
  const previewValue = argument("--preview-value", expectedValue);
  const traceId = argument("--trace");
  const output = path.resolve(ROOT, argument("--output", "evidence/browser-real-deal-v1.json"));
  const screenshot = path.resolve(ROOT, argument("--screenshot", "evidence/browser-real-deal-v1.png"));
  if (!room || !eventId || !sourceFileArgument || !expectedValue || !expectedAnchor || !traceId) {
    throw new Error("--room, --event, --source-file, --expected-value, and --expected-anchor are required");
  }
  const sourceFile = path.resolve(sourceFileArgument);
  const roomRegistryPath = path.resolve(ROOT, ".runtime/deal_rooms/registrations.v1.json");

  const sourceBytes = await fs.readFile(sourceFile);
  const sourceSha256 = crypto.createHash("sha256").update(sourceBytes).digest("hex");
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
      if (response.status() >= 400) httpErrors.push({ url: response.url(), status: response.status() });
    });

    const workspaceResponse = await context.request.get(
      `${baseUrl}/api/workspace?room=${encodeURIComponent(room)}`,
    );
    const messagesResponse = await context.request.get(
      `${baseUrl}/api/workspace/messages?room=${encodeURIComponent(room)}`,
    );
    const digestResponse = await context.request.get(
      `${baseUrl}/api/workspace/digest?room=${encodeURIComponent(room)}`,
    );
    const evalsResponse = await context.request.get(`${baseUrl}/api/evals`);
    if (!workspaceResponse.ok() || !messagesResponse.ok() || !digestResponse.ok() || !evalsResponse.ok()) {
      throw new Error("real deal workspace API is unavailable");
    }
    const workspace = await workspaceResponse.json();
    const messages = await messagesResponse.json();
    const digest = await digestResponse.json();
    const evals = await evalsResponse.json();
    const answerEvent = messages.messages.find((message) => message.id === eventId);
    const trace = evals.traces.find((item) => item.trace_id === traceId);
    const statusResponse = await context.request.get(`${baseUrl}/api/status`);
    if (!statusResponse.ok()) throw new Error(`status API returned ${statusResponse.status()}`);
    const runtimeStatus = await statusResponse.json();
    const roomRegistryBytes = await fs.readFile(roomRegistryPath);
    const roomRegistry = JSON.parse(roomRegistryBytes.toString("utf8"));
    const roomRegistryStat = await fs.stat(roomRegistryPath);
    const registeredRoom = roomRegistry.rooms.find((item) => item.id === room);
    assertions.push({
      name: "source_folder_bound",
      passed: path.resolve(workspace.folder_path) === path.dirname(sourceFile),
      observed: workspace.folder_path,
    });
    assertions.push({
      name: "custom_room_restored_from_persisted_registry",
      passed: Boolean(registeredRoom)
        && path.resolve(registeredRoom.path) === path.dirname(sourceFile)
        && roomRegistryStat.mtimeMs / 1000 < runtimeStatus.server_process_started_at,
      observed: {
        registry_path: path.relative(ROOT, roomRegistryPath),
        registry_mtime: roomRegistryStat.mtimeMs / 1000,
        server_process_started_at: runtimeStatus.server_process_started_at,
      },
    });
    assertions.push({
      name: "hash_bound_public_source_set",
      passed: workspace.total_documents === workspace.source_provenance?.public_integrity?.source_count
        && workspace.total_documents === 2
        && workspace.parse_warnings.length === 0
        && workspace.source_provenance?.classification === "public_filing_corpus"
        && workspace.source_provenance?.manifest_bound === true
        && workspace.source_provenance?.public_integrity?.passed === true
        && workspace.source_provenance?.public_integrity?.errors?.length === 0,
      observed: {
        total_documents: workspace.total_documents,
        parse_warnings: workspace.parse_warnings,
        source_provenance: workspace.source_provenance,
      },
    });
    assertions.push({ name: "signed_answer_event_present", passed: Boolean(answerEvent) });
    assertions.push({
      name: "answer_currently_trace_and_source_bound",
      passed: answerEvent?.prism_acceptance_state === "accepted"
        && answerEvent?.prism_guard_version === "deal_room_chat_guard_v1"
        && answerEvent?.prism_evidence_scope?.measurement_state
          === "current_parser_inventory_and_trace_bound_passage_selection"
        && !answerEvent?.display_content,
      observed: {
        acceptance_state: answerEvent?.prism_acceptance_state || null,
        guard_version: answerEvent?.prism_guard_version || null,
      },
    });
    assertions.push({
      name: "answer_event_signature_verified",
      passed: answerEvent?.signature_verified === true
        && answerEvent?.signature_scheme === "nip01_event_id_plus_bip340"
        && messages.signature_verification?.state === "verified"
        && messages.signature_verification?.scheme === "nip01_event_id_plus_bip340",
      observed: messages.signature_verification,
    });
    assertions.push({
      name: "guarded_answer_trace_restored",
      passed: Boolean(trace)
        && trace.timestamp < runtimeStatus.server_process_started_at,
      observed: {
        trace_id: trace?.trace_id,
        trace_timestamp: trace?.timestamp,
        server_process_started_at: runtimeStatus.server_process_started_at,
      },
    });
    assertions.push({
      name: "guarded_answer_event_trace_binding",
      passed: trace?.metadata?.answer_event_id === eventId
        && answerEvent?.content?.includes(`trace=${traceId}`)
        && answerEvent?.content?.includes("guard=deal_room_chat_guard_v1"),
      observed: {
        answer_event_id: trace?.metadata?.answer_event_id,
        question_event_id: trace?.metadata?.question_event_id,
        guard_version: trace?.metadata?.guard_version,
      },
    });
    assertions.push({
      name: "guarded_answer_requested_part_contract",
      passed: JSON.stringify(trace?.metadata?.requested_parts) === JSON.stringify([
        "consideration", "stockholder_approval", "regulatory_approval", "financing_condition",
      ])
        && expectedAnchors.every((anchor) => trace?.metadata?.retrieved_anchors?.some(
          (item) => item.citation.endsWith(`#${anchor}]`) && item.source_sha256 === sourceSha256,
        )),
      observed: {
        requested_parts: trace?.metadata?.requested_parts,
        part_citations: trace?.metadata?.part_citations,
      },
    });
    assertions.push({
      name: "observed_value_matches_source_bounded_answer",
      passed: Boolean(answerEvent?.content?.includes(expectedValue)),
      observed: answerEvent?.content,
    });

    const discussionUrl = (
      `${baseUrl}/rooms/${encodeURIComponent(room)}/discussion?event=${encodeURIComponent(eventId)}`
    );
    await page.goto(discussionUrl, { waitUntil: "networkidle" });
    await page.locator("#relay-label").getByText("Buzz workspace ready", { exact: true }).waitFor();
    const focused = page.locator(`#event-${eventId}`);
    await focused.waitFor();
    assertions.push({
      name: "hash_verified_public_provenance_visible",
      passed: await page.locator("#room-provenance").getByText(
        "Hash-verified public filing corpus", { exact: true },
      ).isVisible(),
    });
    assertions.push({
      name: "canonical_url_opens_discussion",
      passed: new URL(page.url()).pathname.endsWith("/discussion"),
      destination: page.url(),
    });
    assertions.push({
      name: "answer_event_focused",
      passed: await focused.evaluate((element) => element.classList.contains("message-focus")),
    });
    assertions.push({
      name: "verified_signature_visible",
      passed: await focused.getByText(
        "Verified signature · current source guard", { exact: true },
      ).isVisible(),
    });
    assertions.push({
      name: "bonsai_answer_visible",
      passed: await focused.getByText(expectedValue, { exact: false }).isVisible(),
    });
    const focusedText = await focused.innerText();
    assertions.push({
      name: "machine_trace_marker_hidden_from_human_view",
      passed: !focusedText.includes("prism:deal-room-answer") && !focusedText.includes(traceId),
    });
    assertions.push({
      name: "human_requested_part_labels_visible",
      passed: [
        "Per-share consideration:", "Stockholder approval:",
        "Regulatory approval:", "Financing condition:",
      ].every((label) => focusedText.includes(label)),
    });
    const evidenceScope = answerEvent?.prism_evidence_scope || {};
    const scopeSummary = `Evidence scope: ${Number(evidenceScope.admitted_passage_count).toLocaleString()} passages selected from ${Number(evidenceScope.corpus_searchable_node_count).toLocaleString()} searchable nodes`;
    const scopeControl = focused.getByText(scopeSummary, { exact: true });
    await scopeControl.click();
    assertions.push({
      name: "bounded_evidence_scope_visible",
      passed: evidenceScope.corpus_document_count === 2
        && evidenceScope.corpus_parsed_node_count >= evidenceScope.corpus_searchable_node_count
        && evidenceScope.corpus_searchable_node_count >= evidenceScope.admitted_passage_count
        && evidenceScope.admitted_passage_count === trace?.metadata?.retrieved_anchors?.length
        && evidenceScope.semantic_coverage_measured === false
        && evidenceScope.full_document_review_claimed === false
        && /^[0-9a-f]{64}$/.test(evidenceScope.inventory_sha256 || "")
        && await focused.getByText(
          "These counts do not measure semantic coverage or prove full-document review.",
          { exact: false },
        ).isVisible(),
      observed: evidenceScope,
    });
    const invokedInProcess = runtimeStatus.local_inference_invoked_in_process === true;
    const localProvider = runtimeStatus.providers?.find(
      (provider) => provider.provider_id === "local_bonsai",
    );
    const expectedRuntimeLabel = invokedInProcess
      ? "Invoked this process" : "Configured · prior trace recorded";
    await page.locator("#toggle-context").click();
    await page.getByRole("button", { name: "Technical details", exact: true }).click();
    const contextAdmissionVisible = await page.getByText(
      "Active context admission", { exact: true },
    ).isVisible() && await page.getByText("16,384 fitted tokens", { exact: true }).isVisible();
    await page.getByRole("tab", { name: "Activity", exact: true }).click();
    assertions.push({
      name: "runtime_state_boundary_visible",
      passed: await page.getByText(expectedRuntimeLabel, { exact: true }).isVisible()
        && runtimeStatus.local_inference_recorded_history === true
        && localProvider?.context_admission === "loaded_model_tokenizer_with_runtime_margin"
        && localProvider?.context_window_tokens === 16384
        && contextAdmissionVisible
        && (invokedInProcess
          ? runtimeStatus.local_inference_invocation_evidence === "current_process_trace"
            && runtimeStatus.current_process_local_model === runtimeStatus.configured_local_model_name
          : runtimeStatus.local_inference_invocation_evidence === "recorded_trace_history"),
      observed: {
        invocation_evidence: runtimeStatus.local_inference_invocation_evidence,
        context_admission: localProvider?.context_admission || null,
        context_window_tokens: localProvider?.context_window_tokens || null,
      },
    });
    await fs.mkdir(path.dirname(screenshot), { recursive: true });
    await page.screenshot({ path: screenshot, fullPage: true });

    const citations = focused.locator("button[data-source-citation]");
    const observedAnchors = await citations.evaluateAll((elements) => (
      elements.map((element) => element.getAttribute("data-anchor"))
    ));
    const citation = focused.locator(
      `button[data-source-citation][data-anchor="${previewAnchor}"]`,
    );
    assertions.push({ name: "answer_citation_visible", passed: await citation.isVisible() });
    assertions.push({
      name: "all_requested_part_citations_exact",
      passed: JSON.stringify(observedAnchors) === JSON.stringify(expectedAnchors),
      observed: observedAnchors,
    });
    await citation.click();
    await page.waitForURL((url) => (
      url.pathname.endsWith("/files") && url.searchParams.get("anchor") === previewAnchor
    ));
    assertions.push({ name: "citation_navigates_to_exact_anchor", passed: true, destination: page.url() });
    assertions.push({
      name: "source_preview_contains_exact_cited_passage",
      passed: await page.locator("#source-preview").getByText(previewValue, { exact: false }).isVisible()
        && await page.locator("#source-preview").getByText(`Cited passage · ${previewAnchor}`, { exact: true }).isVisible(),
    });
    await page.goto(`${baseUrl}/rooms/${encodeURIComponent(room)}/digest`, {
      waitUntil: "networkidle",
    });
    assertions.push({
      name: "canvas_signature_verified",
      passed: digest.signature_verification?.state === "verified"
        && digest.signature_verification?.scheme === "nip01_event_id_plus_bip340"
        && await page.getByText(/verified signature/, { exact: false }).first().isVisible(),
      observed: digest.signature_verification,
    });

    const screenshotBytes = await fs.readFile(screenshot);
    const passed = assertions.every((item) => item.passed)
      && !consoleErrors.length && !failedRequests.length && !httpErrors.length;
    record = {
      verification_kind: "replayable_real_deal_browser_check",
      recorded_at: new Date().toISOString(),
      passed,
      semantic_claim_state: "multi_part_structural_pass_not_accuracy_release",
      accuracy_release_passed: false,
      base_url: baseUrl,
      room,
      browser: { engine: "chromium", version: browser.version(), executable: CHROME },
      source: {
        path: path.relative(ROOT, sourceFile),
        bytes: sourceBytes.length,
        sha256: sourceSha256,
      },
      buzz: {
        channel_id: workspace.workspace.channel_id,
        answer_event_id: eventId,
        canonical_path: `/rooms/${room}/discussion?event=${eventId}`,
      },
      observed_runtime_status: {
        configured_model: runtimeStatus.configured_local_model_name,
        current_process_model: runtimeStatus.current_process_local_model,
        last_recorded_model: runtimeStatus.last_invoked_local_model,
        recorded_history: runtimeStatus.local_inference_recorded_history,
        invoked_in_process: runtimeStatus.local_inference_invoked_in_process,
        invocation_evidence: runtimeStatus.local_inference_invocation_evidence,
      },
      observed_signature_verification: messages.signature_verification,
      observed_canvas_verification: digest.signature_verification,
      observed_source_provenance: workspace.source_provenance,
      workspace_document_count: workspace.total_documents,
      observed_trace: trace,
      observed_room_registration: {
        registry_path: path.relative(ROOT, roomRegistryPath),
        registry_sha256: crypto.createHash("sha256").update(roomRegistryBytes).digest("hex"),
        registry_mtime: roomRegistryStat.mtimeMs / 1000,
        server_process_started_at: runtimeStatus.server_process_started_at,
        restored_before_process: roomRegistryStat.mtimeMs / 1000 < runtimeStatus.server_process_started_at,
        room_id: registeredRoom?.id || null,
        folder_path: registeredRoom?.path || null,
      },
      expected_observation: {
        value: expectedValue,
        source_anchors: expectedAnchors,
        preview_anchor: previewAnchor,
        preview_value: previewValue,
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
        "This is one public SEC transaction folder with its proxy and financial companion, plus one named extraction task. It is not a domain accuracy release.",
        "It verifies one Chromium build, not cross-browser or accessibility conformance.",
        "The four-part answer passed a structural publication guard. It has not received domain review and is not an accuracy release.",
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
