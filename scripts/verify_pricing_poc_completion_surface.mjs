#!/usr/bin/env node

import crypto from "node:crypto";
import fs from "node:fs/promises";
import path from "node:path";
import process from "node:process";
import { chromium } from "playwright-core";
import {validateUnsignedPricingPoc} from "../web/pricing-poc-record.mjs";

const ROOT = path.resolve(path.dirname(new URL(import.meta.url).pathname), "..");
const CHROME = process.env.PRISM_BROWSER_EXECUTABLE || chromium.executablePath();

async function main() {
  const baseUrl = (process.env.PRISM_BASE_URL || "http://127.0.0.1:8787").replace(/\/$/, "");
  const output = path.resolve(ROOT, "evidence/browser-pricing-poc-completion-fixture-v1.json");
  const screenshot = path.resolve(ROOT, "evidence/browser-pricing-poc-completion-fixture-v1.png");
  const browser = await chromium.launch({executablePath: CHROME, headless: true, args:["--disable-background-networking"]});
  const assertions=[]; const consoleErrors=[]; const failedRequests=[]; const httpErrors=[];
  let record;
  try {
    const context=await browser.newContext({viewport:{width:1500,height:1200},acceptDownloads:true});
    const page=await context.newPage();
    page.on("console",m=>{if(m.type()==="error")consoleErrors.push(m.text())});
    page.on("requestfailed",r=>failedRequests.push({url:r.url(),error:r.failure()?.errorText||"unknown"}));
    page.on("response",r=>{if(r.status()>=400)httpErrors.push({url:r.url(),status:r.status()})});
    await page.goto(`${baseUrl}/benchmark/pricing-poc`,{waitUntil:"networkidle"});
    await page.locator("#poc-id").fill("fixture-pricing-poc-001");
    await page.locator("#buyer-id").fill("fixture-buyer-001");
    await page.locator("#workflow-owner-role").fill("fixture workflow owner");
    await page.locator("#economic-buyer-role").fill("fixture economic buyer");
    await page.locator("#buyer-pubkey").fill("a".repeat(64));
    await page.locator("#paid-amount").fill("5000");
    await page.locator("#deployment").selectOption("customer_controlled_local");
    await page.locator("#review-allowance").fill("2");
    for(const id of ["budget-authority","buyer-effort","authorized-access","success-approved","poc-paid","collaboration-included","policy-included","support-included","asked-after-use"])await page.locator(`#${id}`).check();
    const fillDeal=async(selector,id,hash,historical,prism,corrections)=>{const node=page.locator(selector);await node.locator('[data-field="deal-id"]').fill(id);await node.locator('[data-field="source-hash"]').fill(hash);await node.locator('[data-field="historical-minutes"]').fill(historical);await node.locator('[data-field="prism-minutes"]').fill(prism);await node.locator('[data-field="critical-corrections"]').fill(corrections);for(const field of ["closed","private","useful","accepted"])await node.locator(`[data-field="${field}"]`).check()};
    await fillDeal('[data-deal="setup"]',"fixture-setup","b".repeat(64),"240","120","1");
    await fillDeal('[data-deal="transfer"]',"fixture-transfer","c".repeat(64),"200","100","0");
    await page.locator("#acceptable-price").fill("1000");await page.locator("#expensive-price").fill("2500");await page.locator("#prohibitive-price").fill("5000");
    await page.locator("#next-step").selectOption("agreed_paid_next_step");await page.locator("#next-step-amount").fill("10000");
    await page.evaluate(()=>{const banner=document.createElement("div");banner.id="synthetic-fixture-banner";banner.textContent="Synthetic browser fixture — not customer evidence";banner.style.cssText="position:sticky;top:0;z-index:99;background:#7f1d1d;color:white;padding:12px 24px;font-weight:800;text-align:center";document.body.prepend(banner)});
    const downloadPromise=page.waitForEvent("download");
    await page.getByRole("button",{name:"Download unsigned POC record"}).click();
    const download=await downloadPromise; const downloadPath=await download.path();
    const unsigned=JSON.parse(await fs.readFile(downloadPath,"utf8"));
    assertions.push({name:"fixture_banner_visible",passed:await page.getByText("Synthetic browser fixture — not customer evidence",{exact:true}).isVisible()});
    assertions.push({name:"unsigned_record_downloaded",passed:download.suggestedFilename()==="fixture-pricing-poc-001.unsigned.json"});
    assertions.push({name:"unsigned_record_has_no_buyer_attestation",passed:!("buyer_attestation" in unsigned)});
    assertions.push({name:"unsigned_record_has_no_buyer_authorization",passed:!("buyer_authorization" in unsigned)});
    assertions.push({name:"unsigned_record_passes_browser_contract",passed:validateUnsignedPricingPoc(unsigned).length===0});
    assertions.push({name:"two_distinct_source_hashes",passed:unsigned.deals.length===2&&new Set(unsigned.deals.map(item=>item.source_snapshot_sha256)).size===2});
    assertions.push({name:"setup_and_transfer_roles_preserved",passed:unsigned.deals[0].experiment_role==="setup_and_correction"&&unsigned.deals[1].experiment_role==="transfer_without_case_specific_change"});
    assertions.push({name:"post_use_prices_ordered",passed:unsigned.price_research.asked_after_use&&unsigned.price_research.acceptable_price<unsigned.price_research.expensive_price&&unsigned.price_research.expensive_price<unsigned.price_research.prohibitively_expensive_price});
    assertions.push({name:"fixture_key_is_public_only",passed:unsigned.buyer.buyer_pubkey==="a".repeat(64)&&!JSON.stringify(unsigned).includes("private_key")});
    assertions.push({name:"download_does_not_submit",passed:await page.getByText("Unsigned POC downloaded. No evidence was submitted.",{exact:false}).isVisible()});
    const api=await (await context.request.get(`${baseUrl}/api/benchmark/pricing-poc`)).json();
    assertions.push({name:"fixture_does_not_change_server_evidence",passed:api.evidence_state==="not_recorded"&&api.pricing_poc_passed===false});
    await page.screenshot({path:screenshot,fullPage:true});const bytes=await fs.readFile(screenshot);
    const passed=assertions.every(item=>item.passed)&&!consoleErrors.length&&!failedRequests.length&&!httpErrors.length;
    record={verification_kind:"synthetic_pricing_poc_completion_browser_fixture",recorded_at:new Date().toISOString(),passed,synthetic_buyer_fixture:true,buyer_evidence_recorded:false,pricing_poc_passed:false,base_url:baseUrl,assertions,fixture_unsigned_record:unsigned,fixture_unsigned_record_sha256:crypto.createHash("sha256").update(`${JSON.stringify(unsigned,null,2)}\n`).digest("hex"),console_errors:consoleErrors,failed_requests:failedRequests,http_errors:httpErrors,screenshot:{path:path.relative(ROOT,screenshot),bytes:bytes.length,sha256:crypto.createHash("sha256").update(bytes).digest("hex")},limitations:["The buyer identity, authority, keys, deal hashes, timings, and prices are synthetic browser fixture data.","This proves unsigned record construction only. It does not publish an authority or buyer event, record customer evidence, establish willingness to pay, or prove revenue."]};
    await context.close();
  }finally{await browser.close()}
  await fs.writeFile(output,`${JSON.stringify(record,null,2)}\n`);console.log(JSON.stringify({output,passed:record.passed,assertions:record.assertions.length},null,2));return record.passed?0:1;
}
process.exit(await main());
