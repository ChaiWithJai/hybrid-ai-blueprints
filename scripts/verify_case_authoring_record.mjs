import assert from "node:assert/strict";
import {buildUnsignedCaseApproval,validateCaseAuthoringInput} from "../web/case-authoring-record.mjs";

const material={
  draft_id:"deal-one__price",candidate_id:"deal-one",company:"Deal One",
  source_review_packet_sha256:"a".repeat(64),
  source_review_ids:["review-a","review-b"],
  source_review_event_ids:["1".repeat(64),"2".repeat(64)],
  source_adjudication_id:null,source_adjudication_event_id:null,
  question:"What is the final consideration?",answer_policy:"answer",
  reviewed_absence_basis:"",task_family:"purchase_price_and_valuation",
  required_claims:[{id:"claim_1",text:"The final consideration is $42.00.",citation_ids:["citation_1"]}],
  required_citations:[{id:"citation_1",filename:"filing.htm",anchor:"html:block:00100",source_sha256:"b".repeat(64),evidence_excerpt_sha256:"c".repeat(64)}],
  confusable_citations:[],source_snapshot_sha256:"d".repeat(64),
  allowed_splits:["development","calibration"],sealed_test_repository_storage_allowed:false,
};
const owner={reviewer_id:"owner.one",qualification:"M&A benchmark owner.",buzz_pubkey:"e".repeat(64)};
const values={domain_owner_id:owner.reviewer_id,case_id:"deal_one_price",version:"1.0.0",near_duplicate_family_id:"",split:"development",investment_screen:"initial pricing",severity:"critical",requested_components:["final consideration"],calculations:[],acceptable_absence_terms:[],forbidden_claims:[],slices:["single_document"]};
assert.deepEqual(validateCaseAuthoringInput(material,values),[]);
const record=buildUnsignedCaseApproval({material,owner,values,approvedAt:"2026-08-15T10:00:00.000Z"});
assert.equal(record.buzz_event_id,"0".repeat(64));
assert.equal(record.case.question,material.question);
assert.deepEqual(record.case.required_claims[0].citation_ids,["citation_1"]);
assert.equal(record.case.domain_review.status,"approved");
assert.ok(validateCaseAuthoringInput(material,{...values,split:"sealed_test"}).some(item=>item.includes("Sealed test")));
assert.ok(validateCaseAuthoringInput(material,{...values,requested_components:[]}).some(item=>item.includes("requested component")));
const calculation={id:"double_consideration",formula:"consideration * 2",expected_value:84,unit:"USD per share",tolerance:0.01,input_claim_ids:["claim_1"],inputs:[{name:"consideration",claim_id:"claim_1",value:42,unit:"USD per share"}]};
assert.deepEqual(validateCaseAuthoringInput(material,{...values,calculations:[calculation]}),[]);
assert.ok(validateCaseAuthoringInput(material,{...values,calculations:[{...calculation,inputs:[{...calculation.inputs[0],value:41}]}]}).some(item=>item.includes("not present in its reviewed claim")));
process.stdout.write(JSON.stringify({passed:true,record}));
