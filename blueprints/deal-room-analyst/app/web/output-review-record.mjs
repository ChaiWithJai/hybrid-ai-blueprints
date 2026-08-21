const ZERO_EVENT_ID="0".repeat(64);

function clean(value){return String(value??"").trim()}
function nonnegativeNumber(value){const number=Number(value);return Number.isFinite(number)&&number>=0?number:null}
function nonnegativeInteger(value){const number=Number(value);return Number.isInteger(number)&&number>=0?number:null}

export function validateOutputCaseReview(reviewCase,values){
  const errors=[];
  if(!reviewCase)errors.push("Choose a review case.");
  const dimensions=values?.dimensions||{};
  for(const dimension of reviewCase?.dimensions_to_review||[]){
    const observed=dimensions[dimension]||{};
    if(!["pass","fail"].includes(observed.label))errors.push(`Choose pass or fail for ${dimension.replaceAll("_"," ")}.`);
    if(observed.label==="fail"&&!clean(observed.critique))errors.push(`Explain the failure for ${dimension.replaceAll("_"," ")}.`);
  }
  if(!["yes","no"].includes(values?.useful_starting_point))errors.push("Choose whether the brief is a useful starting point.");
  if(!["advance","pause","stop","unresolved"].includes(values?.decision))errors.push("Choose a deal decision.");
  if(nonnegativeNumber(values?.review_time_seconds)===null)errors.push("Enter review time in seconds.");
  if(nonnegativeInteger(values?.critical_corrections)===null)errors.push("Enter the critical correction count.");
  if(nonnegativeInteger(values?.major_corrections)===null)errors.push("Enter the major correction count.");
  return errors;
}

export function buildUnsignedOutputReview({packet,reviewer,caseReviews,reviewedAt}){
  const errors=[];
  if(!reviewer)errors.push("Choose a rostered output reviewer.");
  const expectedIds=new Set((packet?.cases||[]).map(item=>item.case_id));
  const observedIds=new Set(Object.keys(caseReviews||{}));
  if(expectedIds.size!==observedIds.size||[...expectedIds].some(item=>!observedIds.has(item)))errors.push("Complete every case in the packet exactly once.");
  const records=[];
  for(const reviewCase of packet?.cases||[]){
    const values=caseReviews?.[reviewCase.case_id];
    const caseErrors=validateOutputCaseReview(reviewCase,values);
    errors.push(...caseErrors.map(item=>`${reviewCase.case_id}: ${item}`));
    if(caseErrors.length)continue;
    records.push({
      case_id:reviewCase.case_id,
      case_version:reviewCase.case_version,
      response_sha256:reviewCase.response_sha256,
      dimensions:reviewCase.dimensions_to_review.map(dimension=>({
        dimension,
        label:values.dimensions[dimension].label,
        severity:reviewCase.severity,
        critique:clean(values.dimensions[dimension].critique),
      })),
      useful_starting_point:values.useful_starting_point==="yes",
      decision:values.decision,
      review_time_seconds:nonnegativeNumber(values.review_time_seconds),
      critical_corrections:nonnegativeInteger(values.critical_corrections),
      major_corrections:nonnegativeInteger(values.major_corrections),
      critique:clean(values.critique),
    });
  }
  if(errors.length)throw new Error(errors.join(" "));
  const timestamp=reviewedAt||new Date().toISOString();
  const suffix=timestamp.replace(/[^0-9]/g,"");
  return {
    review_id:`output-review-${reviewer.reviewer_id}-${suffix}`,
    reviewer_id:reviewer.reviewer_id,
    reviewer_role:"qualified_deal_output_reviewer",
    qualification:reviewer.qualification,
    blinded_to_model:true,
    packet_sha256:packet.packet_sha256,
    rubric_sha256:packet.rubric_sha256,
    reviewer_pubkey:reviewer.buzz_pubkey,
    buzz_event_id:ZERO_EVENT_ID,
    reviewed_at:timestamp,
    cases:records,
  };
}
