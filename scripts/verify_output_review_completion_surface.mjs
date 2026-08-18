#!/usr/bin/env node

import crypto from "node:crypto";
import fs from "node:fs/promises";
import path from "node:path";
import process from "node:process";
import {chromium} from "playwright-core";

const ROOT=path.resolve(path.dirname(new URL(import.meta.url).pathname),"..");
const CHROME=process.env.PRISM_BROWSER_EXECUTABLE||chromium.executablePath();
const FIXTURE_REVIEWERS=[
  {reviewer_id:"fixture.output.one",display_name:"Fixture Output Reviewer One",qualification:"Synthetic browser completion fixture.",buzz_pubkey:"c".repeat(64)},
  {reviewer_id:"fixture.output.two",display_name:"Fixture Output Reviewer Two",qualification:"Synthetic browser completion fixture.",buzz_pubkey:"d".repeat(64)},
];

async function main(){
  const baseUrl=(process.env.PRISM_BASE_URL||"http://127.0.0.1:8787").replace(/\/$/,"");
  const output=path.resolve(ROOT,"evidence/browser-output-review-completion-fixture-v1.json");
  const screenshot=path.resolve(ROOT,"evidence/browser-output-review-completion-fixture-v1.png");
  const browser=await chromium.launch({executablePath:CHROME,headless:true,args:["--disable-background-networking"]});
  let record;
  try{
    const context=await browser.newContext({viewport:{width:1600,height:1100},acceptDownloads:true});
    const actualResponse=await context.request.get(`${baseUrl}/api/benchmark/output-review`);
    if(!actualResponse.ok())throw new Error(`output review API returned ${actualResponse.status()}`);
    const actualSummary=await actualResponse.json();
    const actualDetails=new Map();
    for(const item of actualSummary.cases){
      const response=await context.request.get(`${baseUrl}/api/benchmark/output-review?case=${encodeURIComponent(item.case_id)}`);
      if(!response.ok())throw new Error(`output review case API returned ${response.status()}`);
      const detail=await response.json();
      actualDetails.set(item.case_id,detail.case);
    }
    const fixtureSummary={...actualSummary,qualified_reviewers:FIXTURE_REVIEWERS,reviewer_roster_ready:true,unsigned_export_ready:true};
    const page=await context.newPage();
    const consoleErrors=[];const failedRequests=[];const httpErrors=[];const assertions=[];
    page.on("console",message=>{if(message.type()==="error")consoleErrors.push(message.text())});
    page.on("requestfailed",request=>failedRequests.push({url:request.url(),error:request.failure()?.errorText||"unknown"}));
    page.on("response",response=>{if(response.status()>=400)httpErrors.push({url:response.url(),status:response.status()})});
    await page.route("**/api/benchmark/output-review**",async route=>{
      const url=new URL(route.request().url());
      const caseId=url.searchParams.get("case");
      const payload={...fixtureSummary,case:caseId?actualDetails.get(caseId):null};
      await route.fulfill({status:caseId&&!payload.case?404:200,contentType:"application/json",body:JSON.stringify(payload)});
    });
    await page.goto(`${baseUrl}/benchmark/output-review`,{waitUntil:"networkidle"});
    await page.getByText("5 blinded cases",{exact:true}).waitFor();
    assertions.push({name:"fixture_roster_visible",passed:await page.locator("#reviewer-id option").count()===3});
    await page.locator("#reviewer-id").selectOption("fixture.output.one");
    assertions.push({name:"fixture_reviewer_selected",passed:await page.locator("#reviewer-id").inputValue()==="fixture.output.one"});
    let explicitDimensionLabels=0;
    for(const reviewCase of actualSummary.cases){
      await page.locator(`[data-case-id="${reviewCase.case_id}"]`).click();
      const passControls=await page.locator('[data-dimension] input[value="pass"]').all();
      for(const control of passControls){await control.check();explicitDimensionLabels+=1}
      await page.locator('input[name="useful"][value="yes"]').check();
      await page.locator("#deal-decision").selectOption("advance");
      await page.locator("#review-time").fill("60");
      await page.locator("#critical-corrections").fill("0");
      await page.locator("#major-corrections").fill("0");
      await page.getByRole("button",{name:"Save this case"}).click();
    }
    assertions.push({name:"five_cases_completed",passed:await page.getByText("5 of 5 cases saved",{exact:true}).isVisible()});
    assertions.push({name:"all_dimension_labels_explicit",passed:explicitDimensionLabels===25});
    const exportButton=page.getByRole("button",{name:"Download unsigned submission"});
    assertions.push({name:"unsigned_export_enabled_after_completion",passed:await exportButton.isEnabled()});
    const screenshotBytes=await page.screenshot({path:screenshot,fullPage:true});
    const downloadPromise=page.waitForEvent("download");
    await exportButton.click();
    const download=await downloadPromise;
    const downloadPath=await download.path();
    if(!downloadPath)throw new Error("browser did not retain the downloaded review record");
    const downloadedBytes=await fs.readFile(downloadPath);
    const unsignedRecord=JSON.parse(downloadedBytes.toString("utf-8"));
    assertions.push({name:"unsigned_record_downloaded",passed:true});
    assertions.push({name:"unsigned_record_case_count",passed:unsignedRecord.cases?.length===5});
    assertions.push({name:"unsigned_record_packet_bound",passed:unsignedRecord.packet_sha256===actualSummary.packet_sha256&&unsignedRecord.rubric_sha256===actualSummary.rubric_sha256});
    assertions.push({name:"unsigned_record_not_attested",passed:unsignedRecord.buzz_event_id==="0".repeat(64)});
    assertions.push({name:"unsigned_record_has_no_model_identity",passed:!("model" in unsignedRecord)&&!("provider" in unsignedRecord)&&unsignedRecord.blinded_to_model===true});
    assertions.push({name:"fixture_cannot_promote_review_gate",passed:actualSummary.pipeline.calibration.calibration_passed===false&&actualSummary.pipeline.release.accuracy_release_ready===false});
    const passed=assertions.every(item=>item.passed)&&!consoleErrors.length&&!failedRequests.length&&!httpErrors.length;
    record={verification_kind:"synthetic_output_review_completion_browser_fixture",recorded_at:new Date().toISOString(),passed,base_url:baseUrl,synthetic_reviewer_fixture:true,human_review_performed:false,review_gate_complete:false,accuracy_release_passed:false,packet:{packet_sha256:actualSummary.packet_sha256,rubric_sha256:actualSummary.rubric_sha256,case_count:actualSummary.case_count,blinded_to_model:actualSummary.blinded_to_model,model_identity_included:actualSummary.model_identity_included},fixture_reviewers:FIXTURE_REVIEWERS,fixture_unsigned_record:unsignedRecord,fixture_unsigned_record_sha256:crypto.createHash("sha256").update(downloadedBytes).digest("hex"),assertions,console_errors:consoleErrors,failed_requests:failedRequests,http_errors:httpErrors,screenshot:{path:path.relative(ROOT,screenshot),bytes:screenshotBytes.length,sha256:crypto.createHash("sha256").update(screenshotBytes).digest("hex")},limitations:["The reviewer names and keys are synthetic browser fixtures. They are not on the approved roster and do not count as human review.","The replay proves form completion and unsigned download behavior. It does not prove Buzz signing, reviewer identity, calibration, or accuracy."]};
    await context.close();
  }finally{await browser.close()}
  await fs.writeFile(output,`${JSON.stringify(record,null,2)}\n`);
  console.log(JSON.stringify({output,passed:record.passed,assertions:record.assertions.length},null,2));
  return record.passed?0:1;
}

process.exit(await main());
