import assert from "node:assert/strict";
import {buildUnsignedReview,validateDraftInput} from "../web/source-review-record.mjs";

const packet={packet_sha256:"a".repeat(64)};
const draft={
  draft_id:"deal-one__price",
  source:{filename:"filing.htm",sha256:"b".repeat(64)},
  sources:[{filename:"filing.htm",sha256:"b".repeat(64)}],
  evidence_options:[
    {citation:"[filing.htm#html:block:00100]",source_sha256:"b".repeat(64)},
    {citation:"[filing.htm#html:block:00020]",source_sha256:"b".repeat(64)},
  ],
};
const reviewer={
  reviewer_id:"reviewer.one",
  qualification:"M&A source review experience.",
  buzz_pubkey:"c".repeat(64),
};
const values={
  reviewer_id:reviewer.reviewer_id,
  source_context_checked:true,
  decision:"approve",
  final_question:"What is the final per-share consideration?",
  answer_policy:"supported",
  supporting_citations:["[filing.htm#html:block:00100]"],
  confusable_citations:["[filing.htm#html:block:00020]"],
  expected_claim_lines:["The final consideration is $42.00 per share."],
  absence_basis:"",
  rationale:"The final merger agreement states the operative term.",
};
assert.deepEqual(validateDraftInput(values),[]);
const record=buildUnsignedReview({
  packet,draft,reviewer,values,reviewedAt:"2026-08-15T08:30:00.000Z",
});
assert.equal(record.buzz_event_id,"0".repeat(64));
assert.equal(record.blinded_to_model,true);
assert.equal(record.drafts.length,1);
assert.deepEqual(record.drafts[0].source_sha256s,["b".repeat(64)]);
assert.deepEqual(record.drafts[0].expected_claims[0].citations,values.supporting_citations);
assert.ok(validateDraftInput({...values,supporting_citations:[]}).some(item=>item.includes("supporting citation")));
assert.ok(validateDraftInput({...values,decision:"reject"}).some(item=>item.includes("Rejected drafts")));
assert.ok(validateDraftInput({...values,confusable_citations:values.supporting_citations}).some(item=>item.includes("both supporting and confusable")));
assert.equal("provider" in record,false);
assert.equal("model" in record,false);
const crossDraft={
  ...draft,
  sources:[
    {filename:"filing.htm",sha256:"b".repeat(64)},
    {filename:"financial.htm",sha256:"d".repeat(64)},
  ],
  evidence_options:[
    ...draft.evidence_options,
    {citation:"[financial.htm#html:block:00010]",source_sha256:"d".repeat(64)},
  ],
};
assert.throws(()=>buildUnsignedReview({packet,draft:crossDraft,reviewer,values,reviewedAt:"2026-08-15T08:30:00.000Z"}),/every admitted document/);
const crossValues={...values,supporting_citations:[values.supporting_citations[0],"[financial.htm#html:block:00010]"]};
const crossRecord=buildUnsignedReview({packet,draft:crossDraft,reviewer,values:crossValues,reviewedAt:"2026-08-15T08:30:00.000Z"});
assert.deepEqual(crossRecord.drafts[0].source_sha256s,["b".repeat(64),"d".repeat(64)]);
process.stdout.write(JSON.stringify({passed:true,record}));
