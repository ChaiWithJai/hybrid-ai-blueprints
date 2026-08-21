import assert from "node:assert/strict";
import {buildUnsignedOutputReview,validateOutputCaseReview} from "../web/output-review-record.mjs";

const dimensions=["primary_decision_intent","evidence_support","component_completeness","calibrated_uncertainty","human_usefulness"];
const cases=["case-one","case-two"].map((caseId,index)=>({
  case_id:caseId,case_version:"1.0.0",response_sha256:String(index+1).repeat(64),
  severity:index?"major":"critical",dimensions_to_review:dimensions,
}));
const packet={packet_sha256:"a".repeat(64),rubric_sha256:"b".repeat(64),cases};
const reviewer={reviewer_id:"reviewer.one",qualification:"Experienced M&A output reviewer.",buzz_pubkey:"c".repeat(64)};
const valuesFor=(failed=false)=>({
  dimensions:Object.fromEntries(dimensions.map(dimension=>[dimension,{label:failed&&dimension==="evidence_support"?"fail":"pass",critique:failed&&dimension==="evidence_support"?"The cited passage does not support the stated relation.":""}])),
  useful_starting_point:failed?"no":"yes",decision:failed?"pause":"advance",
  review_time_seconds:"90",critical_corrections:failed?"1":"0",major_corrections:"0",critique:failed?"Correct the evidence relation.":"",
});
assert.deepEqual(validateOutputCaseReview(cases[0],valuesFor()),[]);
assert.ok(validateOutputCaseReview(cases[0],{...valuesFor(),dimensions:{}}).some(item=>item.includes("Choose pass or fail")));
const missingCritique=valuesFor(true);missingCritique.dimensions.evidence_support.critique="";
assert.ok(validateOutputCaseReview(cases[0],missingCritique).some(item=>item.includes("Explain the failure")));
const record=buildUnsignedOutputReview({packet,reviewer,caseReviews:{"case-one":valuesFor(),"case-two":valuesFor(true)},reviewedAt:"2026-08-15T13:00:00.000Z"});
assert.equal(record.buzz_event_id,"0".repeat(64));
assert.equal(record.blinded_to_model,true);
assert.equal(record.cases.length,2);
assert.equal(record.cases[1].dimensions.find(item=>item.dimension==="evidence_support").label,"fail");
assert.throws(()=>buildUnsignedOutputReview({packet,reviewer,caseReviews:{"case-one":valuesFor()}}),/Complete every case/);
assert.equal("provider" in record,false);
assert.equal("model" in record,false);
process.stdout.write(JSON.stringify({passed:true,record}));
