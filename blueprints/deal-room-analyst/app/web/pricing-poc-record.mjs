export const VALUE_UNIT = "accepted_first_pass_review_per_deal_room";
const numberOrNull = value => String(value ?? "").trim() === "" ? null : Number(value);

export function buildUnsignedPricingPoc(values, now = new Date()) {
  return {
    schema_version: 1,
    poc_id: values.poc_id.trim(),
    status: "completed",
    recorded_at: now.toISOString(),
    buyer: {
      buyer_id: values.buyer_id.trim(),
      workflow_owner_role: values.workflow_owner_role.trim(),
      economic_buyer_role: values.economic_buyer_role.trim(),
      budget_authority_confirmed: values.budget_authority_confirmed,
      buyer_pubkey: values.buyer_pubkey.trim().toLowerCase(),
    },
    success_contract: {
      buyer_effort_committed: values.buyer_effort_committed,
      authorized_source_access: values.authorized_source_access,
      success_criteria_approved: values.success_criteria_approved,
      poc_paid: values.poc_paid,
      paid_amount_usd: numberOrNull(values.paid_amount_usd),
    },
    package_hypothesis: {
      value_unit: VALUE_UNIT,
      deployment: values.deployment,
      included_review_allowance: Number(values.included_review_allowance),
      collaboration_included: values.collaboration_included,
      policy_controls_included: values.policy_controls_included,
      deployment_support_included: values.deployment_support_included,
    },
    deals: values.deals.map(item => ({
      deal_id: item.deal_id.trim(),
      experiment_role: item.experiment_role,
      closed_historical: item.closed_historical,
      private_folder: item.private_folder,
      source_snapshot_sha256: item.source_snapshot_sha256.trim().toLowerCase(),
      historical_review_minutes: Number(item.historical_review_minutes),
      prism_review_minutes: Number(item.prism_review_minutes),
      useful_starting_point: item.useful_starting_point,
      accepted_review: item.accepted_review,
      critical_corrections: Number(item.critical_corrections),
    })),
    price_research: {
      asked_after_use: values.asked_after_use,
      currency: "USD",
      value_unit: VALUE_UNIT,
      acceptable_price: numberOrNull(values.acceptable_price),
      expensive_price: numberOrNull(values.expensive_price),
      prohibitively_expensive_price: numberOrNull(values.prohibitively_expensive_price),
    },
    next_step: {
      decision: values.next_step_decision,
      paid_amount_usd: values.next_step_decision === "agreed_paid_next_step"
        ? numberOrNull(values.next_step_paid_amount_usd) : null,
      declined_reason: values.next_step_decision === "declined"
        ? values.declined_reason.trim() : null,
    },
  };
}

export function validateUnsignedPricingPoc(record) {
  const errors = [];
  const requiredText = [
    [record.poc_id, "POC ID"], [record.buyer.buyer_id, "Buyer ID"],
    [record.buyer.workflow_owner_role, "Workflow owner role"],
    [record.buyer.economic_buyer_role, "Economic buyer role"],
  ];
  for (const [value, label] of requiredText) if (!value) errors.push(`${label} is required.`);
  if (!/^[a-f0-9]{64}$/.test(record.buyer.buyer_pubkey)) errors.push("Buyer Buzz public key must be 64 lowercase hexadecimal characters.");
  if (record.success_contract.paid_amount_usd !== null && !(record.success_contract.paid_amount_usd >= 0)) errors.push("Paid POC amount is invalid.");
  if (!record.package_hypothesis.deployment) errors.push("Deployment package is required.");
  if (!(record.package_hypothesis.included_review_allowance >= 1)) errors.push("Included review allowance must be at least one.");
  if (record.deals.length !== 2) errors.push("Exactly two pilot deals are required in this first POC record.");
  for (const [index, deal] of record.deals.entries()) {
    const label = index === 0 ? "Setup deal" : "Transfer deal";
    if (!deal.deal_id) errors.push(`${label} ID is required.`);
    if (!/^[a-f0-9]{64}$/.test(deal.source_snapshot_sha256)) errors.push(`${label} source snapshot must be a SHA-256 hash.`);
    if (!(deal.historical_review_minutes > 0) || !(deal.prism_review_minutes >= 0)) errors.push(`${label} review times are invalid.`);
    if (!(deal.critical_corrections >= 0)) errors.push(`${label} critical corrections are invalid.`);
  }
  if (new Set(record.deals.map(item => item.deal_id)).size !== 2) errors.push("Pilot deal IDs must be distinct.");
  if (new Set(record.deals.map(item => item.source_snapshot_sha256)).size !== 2) errors.push("Pilot source snapshots must be distinct.");
  if (record.next_step.decision === "agreed_paid_next_step" && !(record.next_step.paid_amount_usd > 0)) errors.push("Paid next-step amount is required.");
  if (record.next_step.decision === "declined" && !record.next_step.declined_reason) errors.push("A concrete decline reason is required.");
  if (!record.next_step.decision) errors.push("Commercial next-step decision is required.");
  return errors;
}
