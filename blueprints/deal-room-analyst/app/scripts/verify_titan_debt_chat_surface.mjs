#!/usr/bin/env node

import crypto from "node:crypto";
import fs from "node:fs/promises";
import path from "node:path";
import process from "node:process";
import { chromium } from "playwright-core";


const ROOT = path.resolve(path.dirname(new URL(import.meta.url).pathname), "..");
const CHROME = process.env.PRISM_BROWSER_EXECUTABLE || chromium.executablePath();
const ROOM = "project_titan_lbo";
const QUERY = "What are the disclosed debt tranches and amounts for Project Titan? Cite the source for every amount.";
const SOURCE_PATH = path.resolve(ROOT, "deal_rooms/project_titan_lbo/01_Confidential_Information_Memorandum.md");
const SOURCE_NAME = "01_Confidential_Information_Memorandum.md";
const SOURCE_ANCHOR = "node:node_tbl_1";
const CITATION = `[${SOURCE_NAME}#${SOURCE_ANCHOR}]`;
const EXPECTED_PARTS = ["capital_structure"];
const EXPECTED_INSTRUMENTS = [
  "Revolving Credit Facility", "First Lien Term Loan B",
  "Second Lien Senior Notes", "Subordinated Mezzanine Debt",
];
const EXPECTED_VALUES = ["$150M", "$0.0", "$900.0", "$300.0", "$240.0"];


function argument(name, fallback = null) {
  const index = process.argv.indexOf(name);
  return index >= 0 && process.argv[index + 1] ? process.argv[index + 1] : fallback;
}


async function main() {
  const baseUrl = argument("--base-url", "http://127.0.0.1:8787").replace(/\/$/, "");
  const acceptedEventId = argument("--accepted-event");
  const acceptedTraceId = argument("--accepted-trace");
  const rejectedEventId = argument("--prior-rejection-event");
  const rejectedTraceId = argument("--prior-rejection-trace");
  const output = path.resolve(ROOT, argument("--output", "evidence/browser-titan-debt-chat-v1.json"));
  const screenshot = path.resolve(ROOT, argument("--screenshot", "evidence/browser-titan-debt-chat-v1.png"));
  if (!acceptedEventId || !acceptedTraceId || !rejectedEventId || !rejectedTraceId) {
    throw new Error(
      "--accepted-event, --accepted-trace, --prior-rejection-event, and --prior-rejection-trace are required",
    );
  }

  const sourceBytes = await fs.readFile(SOURCE_PATH);
  const sourceSha256 = crypto.createHash("sha256").update(sourceBytes).digest("hex");
  const assertions = [];
  const consoleErrors = [];
  const failedRequests = [];
  const httpErrors = [];
  const add = (name, passed, observed = undefined) => assertions.push({ name, passed, observed });
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

    const [workspaceResponse, messagesResponse, evalsResponse, statusResponse] = await Promise.all([
      context.request.get(`${baseUrl}/api/workspace?room=${ROOM}`),
      context.request.get(`${baseUrl}/api/workspace/messages?room=${ROOM}`),
      context.request.get(`${baseUrl}/api/evals`),
      context.request.get(`${baseUrl}/api/status`),
    ]);
    if (![workspaceResponse, messagesResponse, evalsResponse, statusResponse].every((item) => item.ok())) {
      throw new Error("Titan chat evidence APIs are unavailable");
    }
    const workspace = await workspaceResponse.json();
    const messages = await messagesResponse.json();
    const evals = await evalsResponse.json();
    const status = await statusResponse.json();
    const acceptedEvent = messages.messages.find((item) => item.id === acceptedEventId);
    const rejectedEvent = messages.messages.find((item) => item.id === rejectedEventId);
    const acceptedTrace = evals.traces.find((item) => item.trace_id === acceptedTraceId);
    const rejectedTrace = evals.traces.find((item) => item.trace_id === rejectedTraceId);
    const questionEvent = messages.messages.find(
      (item) => item.id === acceptedTrace?.metadata?.question_event_id,
    );
    const acceptedText = acceptedEvent?.content || "";

    add("buzz_workspace_ready", status.buzz?.relay_live === true && status.buzz?.workspace_ready === true);
    add("trace_ledger_verified", status.trace_store?.verified === true, status.trace_store);
    add(
      "runtime_history_separate_from_current_process",
      status.local_inference_recorded_history === true
        && status.local_inference_invoked_in_process === false
        && status.local_inference_invocation_evidence === "recorded_trace_history",
      {
        recorded_history: status.local_inference_recorded_history,
        invoked_in_process: status.local_inference_invoked_in_process,
        invocation_evidence: status.local_inference_invocation_evidence,
      },
    );
    const sourceDocument = workspace.documents.find((item) => item.filename === SOURCE_NAME);
    add(
      "source_hash_and_anchor_bound",
      sourceDocument?.parser_facts?.source_sha256 === sourceSha256
        && Boolean(sourceDocument?.anchors?.[SOURCE_ANCHOR])
        && workspace.parse_warnings.length === 0,
      { source_sha256: sourceDocument?.parser_facts?.source_sha256, anchor: SOURCE_ANCHOR },
    );
    add(
      "accepted_question_signature_verified",
      questionEvent?.signature_verified === true && questionEvent?.content === QUERY,
      { event_id: questionEvent?.id },
    );
    add(
      "accepted_answer_signature_verified",
      acceptedEvent?.signature_verified === true
        && acceptedEvent?.signature_scheme === "nip01_event_id_plus_bip340"
        && acceptedEvent?.prism_acceptance_state === "accepted"
        && acceptedEvent?.prism_evidence_scope?.measurement_state
          === "current_parser_inventory_and_trace_bound_passage_selection"
        && acceptedEvent?.prism_evidence_scope?.semantic_coverage_measured === false
        && acceptedEvent?.prism_evidence_scope?.full_document_review_claimed === false
        && !acceptedEvent?.display_content,
      { event_id: acceptedEvent?.id },
    );
    add(
      "accepted_trace_event_binding",
      acceptedTrace?.metadata?.answer_event_id === acceptedEventId
        && acceptedTrace?.metadata?.question_event_id === questionEvent?.id
        && acceptedTrace?.metadata?.result_state === "guard_passed_and_signed_to_buzz"
        && acceptedText.includes(`trace=${acceptedTraceId}`),
      acceptedTrace?.metadata,
    );
    add(
      "capital_structure_contract_bound",
      JSON.stringify(acceptedTrace?.metadata?.requested_parts) === JSON.stringify(EXPECTED_PARTS)
        && JSON.stringify(acceptedTrace?.metadata?.part_citations?.capital_structure) === JSON.stringify([CITATION])
        && acceptedTrace?.metadata?.retrieved_anchors?.some(
          (item) => item.citation === CITATION
            && item.source_sha256 === sourceSha256
            && JSON.stringify(item.requested_parts) === JSON.stringify(EXPECTED_PARTS),
        ),
      acceptedTrace?.metadata?.part_citations,
    );
    add(
      "every_debt_instrument_visible_in_signed_answer",
      EXPECTED_INSTRUMENTS.every((value) => acceptedText.includes(value))
        && EXPECTED_VALUES.every((value) => acceptedText.includes(value)),
      acceptedText,
    );
    add(
      "equity_rows_excluded_from_debt_answer",
      !acceptedText.includes("Sponsor Preferred Equity")
        && !acceptedText.includes("Management Rollover Equity"),
    );
    const acceptedEvaluations = Object.fromEntries(
      (acceptedTrace?.evaluations || []).map((item) => [item.name, item]),
    );
    add(
      "structural_pass_is_not_accuracy_release",
      acceptedTrace?.evaluation_state?.state === "awaiting_review"
        && acceptedEvaluations.deal_room_chat_publication_guard?.passed === true
        && acceptedEvaluations.human_accuracy_review?.passed === false
        && acceptedEvaluations.human_accuracy_review?.metadata?.measurement_state === "awaiting_domain_review",
      acceptedTrace?.evaluation_state,
    );
    add(
      "prior_rejection_retained",
      rejectedEvent?.signature_verified === true
        && rejectedTrace?.metadata?.rejection_event_id === rejectedEventId
        && rejectedTrace?.metadata?.result_state === "rejected_before_buzz_answer"
        && rejectedTrace?.query === QUERY
        && rejectedTrace?.evaluation_state?.state === "rejected",
      { event_id: rejectedEvent?.id, trace_id: rejectedTrace?.trace_id },
    );
    add(
      "accepted_trace_restored_after_restart",
      acceptedTrace?.timestamp < status.server_process_started_at,
      { trace_timestamp: acceptedTrace?.timestamp, server_process_started_at: status.server_process_started_at },
    );

    const discussionUrl = `${baseUrl}/rooms/${ROOM}/discussion?event=${acceptedEventId}`;
    await page.goto(discussionUrl, { waitUntil: "networkidle" });
    const focused = page.locator(`#event-${acceptedEventId}`);
    await focused.waitFor();
    add("canonical_discussion_event_focused", await focused.evaluate((element) => (
      element.classList.contains("message-focus")
    )), page.url());
    add(
      "verified_signature_visible",
      await focused.getByText(
        "Verified signature · current source guard", { exact: true },
      ).isVisible(),
    );
    const focusedText = await focused.innerText();
    add(
      "human_debt_label_and_values_visible",
      focusedText.includes("Debt tranches and amounts:")
        && EXPECTED_INSTRUMENTS.every((value) => focusedText.includes(value))
        && EXPECTED_VALUES.every((value) => focusedText.includes(value)),
      focusedText,
    );
    add(
      "machine_marker_hidden",
      !focusedText.includes("prism:deal-room-answer") && !focusedText.includes(acceptedTraceId),
    );
    const citation = focused.locator(
      `button[data-source-citation][data-source="${SOURCE_NAME}"][data-anchor="${SOURCE_ANCHOR}"]`,
    );
    add("exact_citation_visible", await citation.isVisible(), CITATION);
    await fs.mkdir(path.dirname(screenshot), { recursive: true });
    await page.screenshot({ path: screenshot, fullPage: true });
    await citation.click();
    await page.waitForURL((url) => (
      url.pathname.endsWith("/files") && url.searchParams.get("anchor") === SOURCE_ANCHOR
    ));
    add("citation_opens_exact_source_anchor", true, page.url());
    add(
      "source_preview_contains_debt_table",
      await page.locator("#source-preview").getByText("Revolving Credit Facility", { exact: false }).isVisible()
        && await page.locator("#source-preview").getByText("Subordinated Mezzanine Debt", { exact: false }).isVisible()
        && await page.locator("#source-preview").getByText(
          `Cited passage · ${SOURCE_ANCHOR}`, { exact: true },
        ).isVisible(),
    );

    const screenshotBytes = await fs.readFile(screenshot);
    const passed = assertions.every((item) => item.passed)
      && !consoleErrors.length && !failedRequests.length && !httpErrors.length;
    record = {
      verification_kind: "replayable_titan_debt_chat_browser_check_v1",
      recorded_at: new Date().toISOString(),
      passed,
      measurement_state: "structural_guard_passed_awaiting_domain_review",
      accuracy_release_passed: false,
      base_url: baseUrl,
      room: ROOM,
      query: QUERY,
      source: {
        path: path.relative(ROOT, SOURCE_PATH),
        bytes: sourceBytes.length,
        sha256: sourceSha256,
        citation: CITATION,
      },
      buzz: {
        question_event_id: questionEvent?.id || null,
        accepted_answer_event_id: acceptedEventId,
        prior_rejection_event_id: rejectedEventId,
        canonical_path: `/rooms/${ROOM}/discussion?event=${acceptedEventId}`,
        signature_verification: messages.signature_verification,
      },
      accepted_trace: acceptedTrace,
      prior_rejected_trace: rejectedTrace,
      observed_runtime_status: {
        configured_model: status.configured_local_model_name,
        last_recorded_model: status.last_invoked_local_model,
        recorded_history: status.local_inference_recorded_history,
        invoked_in_process: status.local_inference_invoked_in_process,
        invocation_evidence: status.local_inference_invocation_evidence,
        provider_network_scope: status.configured_local_provider_network_scope,
        server_process_started_at: status.server_process_started_at,
      },
      browser: { engine: "chromium", version: browser.version(), executable: CHROME },
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
        "This is one synthetic Titan source set and one debt-structure question, not a deal-domain accuracy release.",
        "The deterministic checks prove source admission, completeness against named debt rows, citation support, signed delivery, and restart restoration. They do not prove economic interpretation.",
        "The browser replay covers one Chromium build, not accessibility conformance or every browser.",
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
