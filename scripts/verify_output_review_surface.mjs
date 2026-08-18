#!/usr/bin/env node

import crypto from "node:crypto";
import fs from "node:fs/promises";
import path from "node:path";
import process from "node:process";
import { chromium } from "playwright-core";

const ROOT=path.resolve(path.dirname(new URL(import.meta.url).pathname),"..");
const CHROME=process.env.PRISM_BROWSER_EXECUTABLE||chromium.executablePath();

async function main(){
  const baseUrl=(process.env.PRISM_BASE_URL||"http://127.0.0.1:8787").replace(/\/$/,"");
  const output=path.resolve(ROOT,"evidence/browser-output-review-v1.json");
  const screenshot=path.resolve(ROOT,"evidence/browser-output-review-v1.png");
  const consoleErrors=[];const failedRequests=[];const httpErrors=[];const assertions=[];
  const browser=await chromium.launch({executablePath:CHROME,headless:true,args:["--disable-background-networking"]});
  let record;
  try{
    const context=await browser.newContext({viewport:{width:1600,height:1100}});
    const page=await context.newPage();
    page.on("console",message=>{if(message.type()==="error")consoleErrors.push(message.text())});
    page.on("requestfailed",request=>failedRequests.push({url:request.url(),error:request.failure()?.errorText||"unknown"}));
    page.on("response",response=>{if(response.status()>=400)httpErrors.push({url:response.url(),status:response.status()})});
    const packetResponse=await context.request.get(`${baseUrl}/api/benchmark/output-review`);
    if(!packetResponse.ok())throw new Error(`output review API returned ${packetResponse.status()}`);
    const packet=await packetResponse.json();
    await page.goto(`${baseUrl}/benchmark/output-review`,{waitUntil:"networkidle"});
    await page.getByText("Model identity withheld",{exact:true}).waitFor();
    const visible=async(name,text)=>assertions.push({name,passed:await page.getByText(text,{exact:true}).isVisible()});
    await visible("blinded_identity_state","Model identity withheld");
    await visible("packet_case_count",`${packet.case_count} blinded cases`);
    await visible("development_boundary","Development review supports error analysis. It does not count as calibration or an accuracy release.");
    await visible("closed_roster_guard","Export is closed because the reviewer authority key has not been provisioned. Free-text identity and approval flags are not accepted.");
    assertions.push({name:"five_cases_rendered",passed:await page.locator("[data-case-id]").count()===5});
    assertions.push({name:"no_dimension_label_preselected",passed:await page.locator("[data-dimension] input:checked").count()===0});
    assertions.push({name:"no_usefulness_preselected",passed:await page.locator('input[name="useful"]:checked').count()===0});
    assertions.push({name:"no_deal_decision_preselected",passed:await page.locator("#deal-decision").inputValue()===""});
    assertions.push({name:"unsigned_export_closed",passed:await page.getByRole("button",{name:"Download unsigned submission"}).isDisabled()});
    assertions.push({name:"api_is_blinded_and_calibration_blocked",passed:packet.blinded_to_model===true&&packet.model_identity_included===false&&packet.pipeline.calibration.calibration_passed===false&&packet.pipeline.calibration.evidence_state==="not_recorded"});
    assertions.push({name:"model_identifier_absent_from_page",passed:!(await page.locator("body").innerText()).includes("27b@q1_0")});
    assertions.push({name:"loading_state_cleared",passed:await page.locator("#review-loading").isHidden()&&await page.locator("#review-content").isVisible()});
    const screenshotBytes=await page.screenshot({path:screenshot,fullPage:true});
    const passed=assertions.every(item=>item.passed)&&!consoleErrors.length&&!failedRequests.length&&!httpErrors.length;
    record={verification_kind:"replayable_output_review_browser_check",recorded_at:new Date().toISOString(),passed,base_url:baseUrl,packet:{packet_sha256:packet.packet_sha256,rubric_sha256:packet.rubric_sha256,case_count:packet.case_count,blinded_to_model:packet.blinded_to_model,model_identity_included:packet.model_identity_included,reviewer_roster_ready:packet.reviewer_roster_ready,unsigned_export_ready:packet.unsigned_export_ready},observed_calibration:packet.pipeline.calibration,assertions,console_errors:consoleErrors,failed_requests:failedRequests,http_errors:httpErrors,screenshot:{path:path.relative(ROOT,screenshot),bytes:screenshotBytes.length,sha256:crypto.createHash("sha256").update(screenshotBytes).digest("hex")},limitations:["This verifies a model blind unsigned review workspace, not reviewer identity or a signed submission.","The five cases are development data and do not satisfy the calibration sample requirement."]};
    await context.close();
  }finally{await browser.close()}
  await fs.writeFile(output,`${JSON.stringify(record,null,2)}\n`);
  console.log(JSON.stringify({output,passed:record.passed,assertions:record.assertions.length},null,2));
  return record.passed?0:1;
}

process.exit(await main());
