const ZERO_EVENT_ID="0".repeat(64);

function unique(values){return [...new Set(values.filter(Boolean))]}
function clean(value){return String(value??"").trim()}

export function validateDraftInput(values){
  const errors=[];
  if(!values.reviewer_id)errors.push("Choose a domain-owner-approved reviewer.");
  if(!values.source_context_checked)errors.push("Confirm that you inspected the filing context.");
  if(!["approve","revise","reject"].includes(values.decision))errors.push("Choose a draft decision.");
  if(!["supported","refuse_absent","unresolved"].includes(values.answer_policy))errors.push("Choose an answer policy.");
  if(!clean(values.rationale))errors.push("Explain the source-review rationale.");
  if(["approve","revise"].includes(values.decision)&&!clean(values.final_question))errors.push("Approved or revised drafts need a final question.");
  const supporting=unique(values.supporting_citations||[]);
  const confusable=unique(values.confusable_citations||[]);
  if(supporting.some(item=>confusable.includes(item)))errors.push("One citation cannot be both supporting and confusable.");
  const claims=(values.expected_claim_lines||[]).map(clean).filter(Boolean);
  if(values.answer_policy==="supported"&&(!supporting.length||!claims.length))errors.push("Supported answers need at least one supporting citation and expected claim.");
  if(values.answer_policy==="refuse_absent"&&!clean(values.absence_basis))errors.push("Source absence needs a review basis.");
  if(values.decision==="reject"&&(values.answer_policy!=="unresolved"||supporting.length||claims.length))errors.push("Rejected drafts must use Unresolved with no supporting claims.");
  return errors;
}

export function buildUnsignedReview({packet,draft,reviewer,values,reviewedAt}){
  const errors=validateDraftInput({...values,reviewer_id:reviewer?.reviewer_id});
  if(errors.length)throw new Error(errors.join(" "));
  const supporting=unique(values.supporting_citations||[]);
  const sources=draft.sources?.length?draft.sources:[draft.source];
  const supportingHashes=new Set(draft.evidence_options.filter(item=>supporting.includes(item.citation)).map(item=>item.source_sha256));
  if(values.answer_policy==="supported"&&sources.length>1&&sources.some(item=>!supportingHashes.has(item.sha256)))throw new Error("Supported cross-document drafts need at least one citation from every admitted document.");
  const timestamp=reviewedAt||new Date().toISOString();
  const suffix=timestamp.replace(/[^0-9]/g,"");
  return {
    review_id:`source-review-${reviewer.reviewer_id}-${draft.draft_id}-${suffix}`,
    reviewer_id:reviewer.reviewer_id,
    reviewer_role:"qualified_deal_source_reviewer",
    qualification:reviewer.qualification,
    blinded_to_model:true,
    packet_sha256:packet.packet_sha256,
    reviewer_pubkey:reviewer.buzz_pubkey,
    buzz_event_id:ZERO_EVENT_ID,
    reviewed_at:timestamp,
    drafts:[{
      draft_id:draft.draft_id,
      source_sha256s:sources.map(item=>item.sha256).sort(),
      source_context_checked:true,
      decision:values.decision,
      final_question:clean(values.final_question),
      answer_policy:values.answer_policy,
      supporting_citations:supporting,
      confusable_citations:unique(values.confusable_citations||[]),
      expected_claims:(values.expected_claim_lines||[]).map(clean).filter(Boolean).map(text=>({text,citations:[...supporting]})),
      absence_basis:clean(values.absence_basis),
      rationale:clean(values.rationale),
    }],
  };
}
