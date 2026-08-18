const ZERO_EVENT_ID="0".repeat(64);

function clean(value){return String(value??"").trim()}
function unique(values){return [...new Set((values||[]).map(clean).filter(Boolean))]}
function numericValues(value){return [...String(value??"").matchAll(/(?<![A-Za-z0-9_])[-+]?\d[\d,]*(?:\.\d+)?/g)].map(item=>Number(item[0].replaceAll(",",""))).filter(Number.isFinite)}
function calculationErrors(material,calculations){
  const errors=[];
  const claims=new Map((material?.required_claims||[]).map(item=>[item.id,item]));
  const calculationIds=new Set();
  for(const [index,calculation] of calculations.entries()){
    const label=`Calculation ${index+1}`;
    if(!calculation||typeof calculation!=="object"||Array.isArray(calculation)){errors.push(`${label} must be an object.`);continue}
    if(!clean(calculation.id)||calculationIds.has(calculation.id))errors.push(`${label} needs a unique ID.`);else calculationIds.add(calculation.id);
    if(!clean(calculation.formula)||calculation.formula.length>500)errors.push(`${label} needs a formula of at most 500 characters.`);
    if(!Number.isFinite(calculation.expected_value))errors.push(`${label} needs a numeric expected value.`);
    if(!Number.isFinite(calculation.tolerance)||calculation.tolerance<0)errors.push(`${label} needs a nonnegative numeric tolerance.`);
    if(!clean(calculation.unit))errors.push(`${label} needs a result unit.`);
    const inputs=calculation.inputs;
    if(!Array.isArray(inputs)||!inputs.length){errors.push(`${label} needs source-bound inputs.`);continue}
    const names=inputs.map(item=>clean(item?.name));
    if(names.some(name=>!/^[A-Za-z_][A-Za-z0-9_]*$/.test(name))||new Set(names).size!==names.length)errors.push(`${label} input names must be unique identifiers.`);
    const claimIds=inputs.map(item=>clean(item?.claim_id));
    if(!Array.isArray(calculation.input_claim_ids)||!calculation.input_claim_ids.length||new Set(claimIds).size!==new Set(calculation.input_claim_ids.map(clean)).size||claimIds.some(id=>!calculation.input_claim_ids.map(clean).includes(id)))errors.push(`${label} input claim IDs must match its inputs.`);
    for(const input of inputs){
      const claim=claims.get(clean(input?.claim_id));
      if(!claim)errors.push(`${label} input ${clean(input?.name)||"unknown"} references an unknown reviewed claim.`);
      if(!Number.isFinite(input?.value))errors.push(`${label} input ${clean(input?.name)||"unknown"} needs a finite numeric value.`);
      else if(claim&&!numericValues(claim.text).some(value=>value===input.value))errors.push(`${label} input ${clean(input?.name)} is not present in its reviewed claim.`);
      if(!clean(input?.unit))errors.push(`${label} input ${clean(input?.name)||"unknown"} needs a unit.`);
    }
  }
  return errors;
}

export function validateCaseAuthoringInput(material,values){
  const errors=[];
  if(!material)errors.push("An eligible reviewed draft is required.");
  if(!values.domain_owner_id)errors.push("Choose a rostered domain case owner.");
  if(!clean(values.case_id))errors.push("Enter a case ID.");
  if(!clean(values.version))errors.push("Enter a case version.");
  if(!material?.allowed_splits?.includes(values.split))errors.push("Choose an allowed repository split.");
  if(values.split==="sealed_test")errors.push("Sealed test cases cannot be stored in this repository.");
  if(!["critical","major","minor"].includes(values.severity))errors.push("Choose a case severity.");
  if(!unique(values.requested_components).length)errors.push("Add at least one requested component.");
  if(!Array.isArray(values.calculations))errors.push("Calculations must be a JSON array.");
  else errors.push(...calculationErrors(material,values.calculations));
  if(material?.answer_policy==="refuse_absent"&&!unique(values.acceptable_absence_terms).length)errors.push("An absence case needs at least one acceptable refusal term.");
  return errors;
}

export function buildUnsignedCaseApproval({material,owner,values,approvedAt}){
  const errors=validateCaseAuthoringInput(material,{...values,domain_owner_id:owner?.reviewer_id});
  if(errors.length)throw new Error(errors.join(" "));
  const timestamp=approvedAt||new Date().toISOString();
  const suffix=timestamp.replace(/[^0-9]/g,"");
  return {
    approval_id:`case-approval-${clean(values.case_id)}-${suffix}`,
    draft_id:material.draft_id,
    source_review_packet_sha256:material.source_review_packet_sha256,
    source_review_ids:[...material.source_review_ids],
    source_review_event_ids:[...material.source_review_event_ids],
    source_adjudication_id:material.source_adjudication_id,
    source_adjudication_event_id:material.source_adjudication_event_id,
    domain_owner_id:owner.reviewer_id,
    qualification:owner.qualification,
    reviewer_pubkey:owner.buzz_pubkey,
    buzz_event_id:ZERO_EVENT_ID,
    approved_at:timestamp,
    confusable_citations:[...material.confusable_citations],
    case:{
      id:clean(values.case_id),
      version:clean(values.version),
      deal_id:material.candidate_id,
      near_duplicate_family_id:clean(values.near_duplicate_family_id)||null,
      split:values.split,
      task_family:material.task_family,
      question:material.question,
      investment_screen:clean(values.investment_screen)||null,
      answer_policy:material.answer_policy,
      severity:values.severity,
      requested_components:unique(values.requested_components),
      required_claims:material.required_claims.map(item=>({...item,severity:values.severity})),
      required_citations:material.required_citations.map(item=>({...item})),
      calculations:values.calculations.map(item=>({...item})),
      acceptable_absence_terms:unique(values.acceptable_absence_terms),
      forbidden_claims:unique(values.forbidden_claims),
      slices:unique(values.slices),
      source_snapshot_sha256:material.source_snapshot_sha256,
      domain_review:{status:"approved",owner:owner.reviewer_id,reviewed_at:timestamp},
    },
  };
}
