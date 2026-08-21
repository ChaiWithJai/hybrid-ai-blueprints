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
  const output = path.resolve(ROOT, "evidence/browser-source-review-v1.json");
  const screenshot = path.resolve(ROOT, "evidence/browser-source-review-v1.png");
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

    const pipelineResponse = await context.request.get(`${baseUrl}/api/benchmark/pipeline`);
    if (!pipelineResponse.ok()) throw new Error(`pipeline API returned ${pipelineResponse.status()}`);
    const pipeline = await pipelineResponse.json();
    const diagnosticResponse = await context.request.get(`${baseUrl}/api/benchmark/oracle-diagnostic`);
    if (!diagnosticResponse.ok()) throw new Error(`oracle diagnostic API returned ${diagnosticResponse.status()}`);
    const diagnostic = await diagnosticResponse.json();
    const queueResponse = await context.request.get(`${baseUrl}/api/benchmark/source-review`);
    if (!queueResponse.ok()) throw new Error(`source review API returned ${queueResponse.status()}`);
    const queue = await queueResponse.json();
    await page.goto(`${baseUrl}/benchmark/source-review`, { waitUntil: "networkidle" });
    await page.getByText("Accuracy release blocked", { exact: true }).waitFor();
    await page.getByText("Accuracy unverified", { exact: true }).waitFor();

    const assertVisible = async (name, text) => {
      assertions.push({ name, passed: await page.getByText(text, { exact: true }).first().isVisible() });
    };
    await assertVisible("source_gate_truth", "0 eligible · 319 pending · 0 rejected");
    await assertVisible(
      "approval_gate_truth",
      `${pipeline.case_approval.recorded_approval_count} recorded · ${pipeline.case_approval.unregistered_approval_count} awaiting · ${pipeline.case_approval.active_domain_case_owner_count} owners`,
    );
    await assertVisible("registration_gate_truth", "0 candidate · 5 total cases");
    await assertVisible(
      "calibration_gate_truth",
      `${pipeline.calibration.registered_case_count}/${pipeline.calibration.required_case_count} cases · ${pipeline.calibration.registered_deal_count}/${pipeline.calibration.required_deal_count} deals · ${pipeline.calibration.evidence_state}`,
    );
    await assertVisible(
      "release_gate_truth",
      `${pipeline.release.domain_approved_cases}/${pipeline.release.target_cases} approved cases · ${pipeline.release.blocker_count} blockers`,
    );
    await assertVisible(
      "ten_decision_count_visible",
      `${pipeline.benchmark_decisions.release_satisfied_count} of ${pipeline.benchmark_decisions.decision_count} release decisions satisfied`,
    );
    assertions.push({
      name: "ten_decision_cards_visible",
      passed: await page.locator("[data-benchmark-decision]").count() === 10,
    });
    assertions.push({
      name: "ten_decision_api_matches_surface",
      passed: pipeline.benchmark_decisions.decision_count === 10
        && pipeline.benchmark_decisions.release_satisfied_count === 0
        && pipeline.benchmark_decisions.all_release_satisfied === false
        && pipeline.benchmark_decisions.decisions.map((item) => item.number).join(",") === "1,2,3,4,5,6,7,8,9,10"
        && pipeline.benchmark_decisions.decisions.every((item) => item.release_satisfied === false),
    });
    await assertVisible(
      "governance_receipt_count_visible",
      `${pipeline.governance.receipt_count} of ${pipeline.governance.required_receipt_count} verified receipts`,
    );
    await assertVisible(
      "governance_unconfigured_truth",
      "Governance is unconfigured. No name, checkbox, or unsigned browser action can approve a scope.",
    );
    assertions.push({
      name: "governance_matrix_geometry",
      passed: await page.locator("[data-governance-scope]").count() === 3
        && await page.locator("[data-governance-receipt]").count() === 12
        && await page.locator('[data-governance-receipt]:has-text("Open")').count() === 12,
    });
    await page.getByText("Inspect exact material hashes", { exact: true }).click();
    assertions.push({
      name: "governance_material_hashes_visible",
      passed: pipeline.governance.scopes.length === 3
        && pipeline.governance.scopes.every((scope) => /^[a-f0-9]{64}$/.test(scope.material_sha256))
        && (await Promise.all(pipeline.governance.scopes.map(
          (scope) => page.getByText(scope.material_sha256, { exact: true }).isVisible(),
        ))).every(Boolean),
    });
    assertions.push({
      name: "governance_private_key_not_requested",
      passed: await page.locator('input[id*="private"], input[name*="private"], textarea[id*="private"], textarea[name*="private"]').count() === 0
        && await page.getByText("Prism never asks for a governance private key in this browser.", { exact: false }).isVisible(),
    });
    await assertVisible("attestation_boundary", "Buzz attestations: private channel configured · signatures: NIP-01 event identity + BIP-340 · calibration receipt: not_recorded · no stage promotes itself.");
    await assertVisible(
      "oracle_summary_truth",
      `${diagnostic.completed_case_count} oracle runs · ${diagnostic.oracle_probe_pass_count} narrow passes · accuracy unverified`,
    );
    await assertVisible("oracle_citrix_regression", "Oracle Context Regressed Deterministic Contract");
    await assertVisible("oracle_cma_persistent_failure", "Deterministic Failure Persists With Registered Oracle Context");
    await assertVisible(
      "whole_corpus_absence_audit_visible",
      "Complete folder audit: 2 files, 2401 nodes, 3 registered patterns, 0 direct hits. Absence phrases: present. Missing citation: [02_citrix_financing_supplement.htm#html:block:00058]",
    );
    assertions.push({
      name: "no_preselected_decision",
      passed: await page.locator('input[name="source-decision"]:checked').count() === 0,
    });
    assertions.push({
      name: "no_preselected_answer_policy",
      passed: await page.locator('input[name="answer-policy"]:checked').count() === 0,
    });
    assertions.push({
      name: "unsigned_export_closed_without_roster",
      passed: await page.getByRole("button", { name: "Download unsigned review" }).isDisabled(),
    });
    await assertVisible(
      "unconfigured_authority_visible",
      "Export is closed because the reviewer authority key has not been provisioned. Free-text identity and approval flags are not accepted.",
    );
    assertions.push({
      name: "pipeline_api_matches_surface",
      passed: pipeline.source_review.pending_count === 319
        && pipeline.registration.candidate_cases_registered === 0
        && pipeline.calibration.calibration_passed === false
        && pipeline.release.accuracy_release_ready === false,
    });
    assertions.push({
      name: "packet_binding_matches_api",
      passed: queue.draft_count === 319
        && typeof queue.packet_sha256 === "string"
        && queue.packet_sha256.length === 64,
    });
    const visibleFamilies = new Set(queue.drafts.map((item) => item.task_family));
    assertions.push({
      name: "all_release_task_families_have_review_leads",
      passed: [
        "transaction_identity_structure_chronology",
        "purchase_price_and_valuation",
        "financing_and_capital_structure",
        "financial_quality_and_earnings_adjustments",
        "contract_terms_covenants_and_approvals",
        "market_and_regulatory_findings",
        "risks_conflicts_and_missing_information",
        "cross_document_synthesis_and_recommendation",
      ].every((family) => visibleFamilies.has(family)),
    });
    assertions.push({
      name: "two_cross_document_question_families_are_visible",
      passed: [
        "cross_document_underwriting_synthesis",
        "cross_document_financing_capacity",
      ].every((family) => queue.drafts.some((item) => item.question_family === family)),
    });
    const crossSummary = queue.drafts.find(
      (item) => item.question_family === "cross_document_underwriting_synthesis",
    );
    if (!crossSummary) throw new Error("cross-document draft is absent from source review API");
    const crossResponse = await context.request.get(
      `${baseUrl}/api/benchmark/source-review?draft=${encodeURIComponent(crossSummary.draft_id)}`,
    );
    if (!crossResponse.ok()) throw new Error(`cross-document detail returned ${crossResponse.status()}`);
    const crossDetail = await crossResponse.json();
    const crossDraft = crossDetail.draft;
    const crossHashes = new Set(crossDraft.sources.map((item) => item.sha256));
    assertions.push({
      name: "multi_document_draft_has_two_hash_bound_sources",
      passed: crossDraft.sources.length === 2
        && new Set(crossDraft.evidence_options.map((item) => item.source_sha256)).size === 2
        && crossDraft.evidence_options.every((item) => crossHashes.has(item.source_sha256)),
    });
    await page.goto(
      `${baseUrl}/benchmark/source-review?draft=${encodeURIComponent(crossDraft.draft_id)}`,
      { waitUntil: "networkidle" },
    );
    const sourceLabel = crossDraft.sources.map((item) => item.filename).join(" + ");
    assertions.push({
      name: "multi_document_sources_visible",
      passed: await page.getByText(sourceLabel, { exact: true }).isVisible(),
    });
    assertions.push({
      name: "multi_document_evidence_from_both_sources_visible",
      passed: await Promise.all(crossDraft.sources.map(async (source) => {
        const option = crossDraft.evidence_options.find(
          (item) => item.source_sha256 === source.sha256,
        );
        return option
          ? page.getByText(option.citation, { exact: true }).isVisible()
          : false;
      })).then((values) => values.every(Boolean)),
    });

    await fs.mkdir(path.dirname(screenshot), { recursive: true });
    await page.screenshot({ path: screenshot, fullPage: true });
    const screenshotBytes = await fs.readFile(screenshot);
    const passed = assertions.every((item) => item.passed)
      && !consoleErrors.length && !failedRequests.length && !httpErrors.length;
    record = {
      verification_kind: "replayable_source_review_browser_check",
      recorded_at: new Date().toISOString(),
      passed,
      base_url: baseUrl,
      assertions,
      observed_pipeline: pipeline,
      observed_oracle_diagnostic: diagnostic,
      source_review_packet_sha256: queue.packet_sha256,
      source_review_draft_count: queue.draft_count,
      console_errors: consoleErrors,
      failed_requests: failedRequests,
      http_errors: httpErrors,
      screenshot: {
        path: path.relative(ROOT, screenshot),
        bytes: screenshotBytes.length,
        sha256: crypto.createHash("sha256").update(screenshotBytes).digest("hex"),
      },
      limitations: [
        "This verifies the rendered promotion gates, ten decision states, governance receipt matrix, and closed controls, not domain accuracy.",
        "The empty reviewer roster is intentional; no human approval is inferred.",
        "The oracle panel reports literal development-contract probes, not semantic accuracy.",
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
