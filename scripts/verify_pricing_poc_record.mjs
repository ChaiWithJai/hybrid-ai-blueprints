#!/usr/bin/env node

import assert from "node:assert/strict";
import {buildUnsignedPricingPoc, validateUnsignedPricingPoc} from "../web/pricing-poc-record.mjs";

const values = {
  poc_id: "poc-001", buyer_id: "buyer-001",
  workflow_owner_role: "private_equity_vice_president",
  economic_buyer_role: "private_equity_partner",
  buyer_pubkey: "a".repeat(64), budget_authority_confirmed: true,
  buyer_effort_committed: true, authorized_source_access: true,
  success_criteria_approved: true, poc_paid: true, paid_amount_usd: "5000",
  deployment: "customer_controlled_local", included_review_allowance: "2",
  collaboration_included: true, policy_controls_included: true,
  deployment_support_included: true, asked_after_use: true,
  acceptable_price: "1000", expensive_price: "2500",
  prohibitively_expensive_price: "5000", next_step_decision: "agreed_paid_next_step",
  next_step_paid_amount_usd: "10000", declined_reason: "",
  deals: [
    {deal_id:"setup",experiment_role:"setup_and_correction",closed_historical:true,private_folder:true,source_snapshot_sha256:"b".repeat(64),historical_review_minutes:"240",prism_review_minutes:"120",useful_starting_point:true,accepted_review:true,critical_corrections:"1"},
    {deal_id:"transfer",experiment_role:"transfer_without_case_specific_change",closed_historical:true,private_folder:true,source_snapshot_sha256:"c".repeat(64),historical_review_minutes:"200",prism_review_minutes:"100",useful_starting_point:true,accepted_review:true,critical_corrections:"0"},
  ],
};
const record = buildUnsignedPricingPoc(values, new Date("2026-08-15T18:00:00Z"));
assert.deepEqual(validateUnsignedPricingPoc(record), []);
assert.equal("buyer_attestation" in record, false);
assert.equal(record.deals[1].critical_corrections, 0);
assert.equal(record.price_research.value_unit, "accepted_first_pass_review_per_deal_room");

const unsignedBoundary = structuredClone(record);
unsignedBoundary.success_contract.authorized_source_access = false;
assert.deepEqual(validateUnsignedPricingPoc(unsignedBoundary), []);

const transferBoundary = structuredClone(record);
transferBoundary.deals[1].critical_corrections = 1;
assert.deepEqual(validateUnsignedPricingPoc(transferBoundary), []);

const sourceBoundary = structuredClone(record);
sourceBoundary.deals[1].source_snapshot_sha256 = sourceBoundary.deals[0].source_snapshot_sha256;
assert.match(validateUnsignedPricingPoc(sourceBoundary).join(" "), /source snapshots must be distinct/);

const pricingBoundary = structuredClone(record);
pricingBoundary.price_research.expensive_price = 500;
assert.deepEqual(validateUnsignedPricingPoc(pricingBoundary), []);

const missingIdentity = structuredClone(record);
missingIdentity.buyer.buyer_pubkey = "";
assert.match(validateUnsignedPricingPoc(missingIdentity).join(" "), /public key/);

console.log(JSON.stringify({passed:true, assertions:8}));
