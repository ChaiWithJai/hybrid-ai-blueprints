import {buildUnsignedPricingPoc, validateUnsignedPricingPoc} from "/pricing-poc-record.mjs?v=1";

document.addEventListener("DOMContentLoaded", init);

async function init() {
  document.getElementById("pricing-record-form").addEventListener("submit", downloadUnsignedRecord);
  try {
    const response = await fetch("/api/benchmark/pricing-poc");
    const result = await response.json();
    if (!response.ok) throw new Error(result.detail || result.error || `Request failed (${response.status})`);
    render(result);
  } catch (error) {
    document.getElementById("state-heading").textContent = "Pricing evidence unavailable";
    document.getElementById("state-detail").textContent = error.message;
    document.getElementById("truth-state").textContent = "Evidence check failed";
    document.getElementById("truth-state").classList.add("invalid");
  }
}

function checked(id) { return document.getElementById(id).checked; }
function value(id) { return document.getElementById(id).value; }
function dealValues(selector, role) {
  const node = document.querySelector(selector);
  const field = name => node.querySelector(`[data-field="${name}"]`);
  return {
    deal_id: field("deal-id").value,
    experiment_role: role,
    closed_historical: field("closed").checked,
    private_folder: field("private").checked,
    source_snapshot_sha256: field("source-hash").value,
    historical_review_minutes: field("historical-minutes").value,
    prism_review_minutes: field("prism-minutes").value,
    useful_starting_point: field("useful").checked,
    accepted_review: field("accepted").checked,
    critical_corrections: field("critical-corrections").value,
  };
}
function formValues() {
  return {
    poc_id: value("poc-id"), buyer_id: value("buyer-id"),
    workflow_owner_role: value("workflow-owner-role"), economic_buyer_role: value("economic-buyer-role"),
    buyer_pubkey: value("buyer-pubkey"), budget_authority_confirmed: checked("budget-authority"),
    buyer_effort_committed: checked("buyer-effort"), authorized_source_access: checked("authorized-access"),
    success_criteria_approved: checked("success-approved"), poc_paid: checked("poc-paid"),
    paid_amount_usd: value("paid-amount"), deployment: value("deployment"),
    included_review_allowance: value("review-allowance"), collaboration_included: checked("collaboration-included"),
    policy_controls_included: checked("policy-included"), deployment_support_included: checked("support-included"),
    deals: [
      dealValues('[data-deal="setup"]', "setup_and_correction"),
      dealValues('[data-deal="transfer"]', "transfer_without_case_specific_change"),
    ],
    asked_after_use: checked("asked-after-use"), acceptable_price: value("acceptable-price"),
    expensive_price: value("expensive-price"), prohibitively_expensive_price: value("prohibitive-price"),
    next_step_decision: value("next-step"), next_step_paid_amount_usd: value("next-step-amount"),
    declined_reason: value("declined-reason"),
  };
}
function downloadUnsignedRecord(event) {
  event.preventDefault();
  const status = document.getElementById("builder-status");
  const record = buildUnsignedPricingPoc(formValues());
  const errors = validateUnsignedPricingPoc(record);
  if (errors.length) { status.textContent = errors.join(" "); return; }
  const blob = new Blob([`${JSON.stringify(record, null, 2)}\n`], {type: "application/json"});
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = `${record.poc_id}.unsigned.json`;
  anchor.click();
  URL.revokeObjectURL(url);
  status.textContent = "Unsigned POC downloaded. No evidence was submitted. The buyer must sign the exact payload through Buzz, and Prism must restore and verify the raw event before the canonical record is written.";
}

function render(result) {
  const gates = result.gates || {};
  const passed = Object.values(gates).filter(item => item.passed).length;
  const total = result.requirements.length;
  const complete = result.pricing_poc_passed === true;
  const truth = document.getElementById("truth-state");
  truth.textContent = complete
    ? "Authority-approved buyer pricing proof passed"
    : result.buyer_authority_configured
      ? `${humanize(result.evidence_state)} · pricing proof blocked`
      : "Buyer authority not configured · pricing proof blocked";
  truth.classList.toggle("ready", complete);
  document.getElementById("state-heading").textContent = complete ? "Paid proof of concept verified" : "No qualifying buyer proof recorded";
  document.getElementById("state-detail").textContent = complete
    ? `${result.deal_count} private historical deals are bound to distinct authority and buyer events restored from Buzz.`
    : result.buyer_authority_configured
      ? "No authority-approved customer record satisfies the commercial gates."
      : "Set a commercial authority key and Buzz channel after an out-of-band buyer identity check. A self-issued buyer key cannot qualify.";
  document.getElementById("gate-count").textContent = `${passed}/${total}`;
  document.getElementById("public-boundary").textContent = result.public_demo_boundary;
  document.getElementById("record-path").textContent = result.record_expected_at;
  document.getElementById("gate-list").innerHTML = result.requirements.map((requirement, index) => {
    const gate = gates[requirement.id];
    const state = gate?.passed ? "passed" : "pending";
    const observed = gate ? formatObserved(gate.observed) : "Not recorded";
    return `<li class="${state}"><span class="gate-number">${index + 1}</span><div><strong>${escapeHtml(requirement.label)}</strong><p>${escapeHtml(requirement.requirement)}</p><small>${escapeHtml(observed)}</small></div><span class="gate-state">${gate?.passed ? "Passed" : "Open"}</span></li>`;
  }).join("");
}

function formatObserved(value) {
  if (value === null || value === undefined) return "Not recorded";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}
function humanize(value) { return String(value || "not recorded").replaceAll("_", " ").replace(/\b\w/g, char => char.toUpperCase()); }
function escapeHtml(value) { return String(value ?? "").replace(/[&<>"']/g, char => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"})[char]); }
