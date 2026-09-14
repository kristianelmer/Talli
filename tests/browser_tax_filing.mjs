import assert from "node:assert/strict";
import { randomUUID } from "node:crypto";
import { readFile } from "node:fs/promises";
import test from "node:test";
import { createClient } from "@supabase/supabase-js";
import { chromium } from "playwright";
import { startTaxBrowserFixture } from "./support/tax-browser-fixture.mjs";
import { establishOwnerAal2 } from "./support/tax-browser-auth.mjs";
import { fixtureTableTransaction } from "./support/rf1086-fixture-access.mjs";
import { installBrowserEgressGuard } from "./fixtures/system-user-authority-mock.mjs";

// Synthetic TT02 metadata only. No authority request, acceptance or production
// claim: the real owner form/JWT/FastAPI/SQL write the pending imported evidence.
test("Tax owner imports pending TT02 feedback, recovers a lost response and reads complete scoped history", {timeout:240_000}, async t => {
  const fixture=await startTaxBrowserFixture({incomeYear:2025});
  let browser;
  t.after(async()=>{try{await browser?.close();}finally{await fixture.close();}});
  browser=await chromium.launch({headless:true});
  const context=await browser.newContext(),blockedRequests=[];
  await installBrowserEgressGuard(context,{approvalEnabled:false,blockedRequests,mockBaseUrl:fixture.siteOrigin});
  const page=await context.newPage();page.setDefaultTimeout(25_000);
  await page.goto(fixture.siteOrigin+'/login');
  await page.getByRole('textbox',{name:'E-post',exact:true}).fill(fixture.owner.email);
  await page.locator('input[name="password"]').fill(fixture.owner.password);
  await page.getByRole('button',{name:'Logg inn',exact:true}).click();
  await page.waitForURL(url=>url.pathname!=='/login');
  const archive=JSON.parse(await readFile(new URL('../architecture/evidence/issues/152/legacy-characterization.json',import.meta.url),'utf8'));
  const original=archive.evidenceCases.find(c=>c.id==='synthetic-completed-pending-feedback').input.evidence;
  const evidence=JSON.parse(JSON.stringify(original).replaceAll(original.companyOrgNumber,fixture.orgNumber)
    .replaceAll('60d6fdca-9e11-49d4-b55d-73b8bb5a2108',randomUUID()).replaceAll('70beee03-d8c2-4584-b366-8231c6de6584',randomUUID()));
  const imports=()=>fixture.controls.filingCalls.filter(call=>call.path==='/api/v1/company-tax/tt02-evidence-imports');
  async function submit(value) {
    await page.goto(fixture.siteOrigin+'/workspace');
    const form=page.locator('form').filter({has:page.getByRole('button',{name:'Importer skattemelding-evidens',exact:true})});
    assert.equal(await form.locator('input[name="incomeYear"]').inputValue(),'2025');
    await form.locator('input[type="file"]').setInputFiles({name:'synthetic-tax-evidence.json',mimeType:'application/json',buffer:Buffer.from(JSON.stringify(value))});
    await Promise.all([page.waitForURL(url=>url.pathname==='/workspace'&&url.searchParams.has('error')),
      form.getByRole('button',{name:'Importer skattemelding-evidens',exact:true}).click()]);
  }
  const auth=createClient(process.env.SUPABASE_URL,process.env.SUPABASE_ANON_KEY,{auth:{autoRefreshToken:false,persistSession:false}});
  const signed=await auth.auth.signInWithPassword({email:fixture.owner.email,password:fixture.owner.password});
  assert.ifError(signed.error);
  const unstepped=await fetch(fixture.backendOrigin+'/api/v1/company-tax/tt02-evidence-imports',{
    method:'POST',headers:{authorization:`Bearer ${signed.data.session.access_token}`,'content-type':'application/json'},
    body:JSON.stringify({companyId:fixture.companyId,incomeYear:2025,evidenceJson:JSON.stringify(evidence),evidenceUrl:null})});
  assert.equal(unstepped.status,403,'real AAL1 owner cannot import evidence');
  await establishOwnerAal2(page,fixture.siteOrigin);
  await submit({...evidence,incomeYear:2024});
  assert.equal(imports().at(-1).status,422,'wrong year fails closed');
  fixture.controls.dropNextTaxImport=true;
  await submit(evidence);
  const committed=imports().at(-1);
  assert.equal(committed.status,200);assert.equal(committed.response.created,true);
  // Replay through the same owner form after the first response was lost.
  await page.goto(fixture.siteOrigin+'/workspace');
  const form=page.locator('form').filter({has:page.getByRole('button',{name:'Importer skattemelding-evidens',exact:true})});
  await form.locator('input[type="file"]').setInputFiles({name:'synthetic-tax-evidence.json',mimeType:'application/json',buffer:Buffer.from(JSON.stringify(evidence))});
  await form.getByRole('button',{name:'Importer skattemelding-evidens',exact:true}).click();
  await poll(()=>imports().length===3);
  await page.getByRole('heading',{name:'Mottatt testtilbakemelding venter på klassifisering.'}).waitFor();
  assert.deepEqual(imports().at(-1).response,{...committed.response,created:false});
  assert.equal(new URL(page.url()).searchParams.has('error'),false);
  await page.getByText('Venter på klassifisering',{exact:true}).waitFor();
  const sourceResponse=await fixture.taxRequest(`/api/v1/company-tax/source-facts?companyId=${fixture.companyId}&incomeYear=2025`);
  assert.equal(sourceResponse.status,200);
  const source=await sourceResponse.json();
  assert.equal(source.evidence.companyId,fixture.companyId);assert.equal(source.evidence.incomeYear,2025);
  assert.equal(source.historyCoverage.status,'complete');assert.equal(source.historyCoverage.submissionCount,1);
  assert.equal(source.readinessStatus,'blocked');assert.deepEqual(source.hardBlocks,['company_tax_production_disabled']);
  assert.deepEqual(source.productionAttempts,[]);
  assert.equal(source.recordedSubmissions[0].sourceId,committed.response.filingSubmissionId);
  assert.equal(source.recordedSubmissions[0].state,'feedback_ready');
  assert.equal(source.recordedSubmissions[0].effectStatus,'not_production');
  assert.equal(source.recordedSubmissions[0].receiptReference,evidence.receipt.dataId);
  const other=await fixture.taxRequest(`/api/v1/company-tax/source-facts?companyId=${randomUUID()}&incomeYear=2025`);
  assert.equal(other.status,404,'an absent or inaccessible company is not an empty successful history');
  // The generic permission form must route the Tax branch through FastAPI.
  const permission=page.locator('form').filter({has:page.getByRole('button',{name:'Bekreft innsendingsrett',exact:true})});
  await permission.locator('select[name="obligation"]').selectOption('skattemelding');
  await permission.getByRole('button',{name:'Bekreft innsendingsrett',exact:true}).click();
  await poll(()=>fixture.controls.filingCalls.some(c=>c.path==='/api/v1/company-tax/permissions'));
  const permissionCall=fixture.controls.filingCalls.find(c=>c.path==='/api/v1/company-tax/permissions');
  assert.equal(permissionCall.status,200);assert.equal(permissionCall.body.productionEnabled,false);
  await page.goto(fixture.siteOrigin+'/workspace');
  const manual=page.locator('form').filter({has:page.getByRole('button',{name:'Lagre test-evidens',exact:true})});
  await manual.locator('select[name="obligation"]').selectOption('skattemelding');
  await manual.locator('select[name="environment"]').selectOption('manual_evidence');
  await manual.locator('input[name="testReference"]').fill('synthetic-browser-manual-evidence');
  await manual.locator('textarea[name="feedbackSummary"]').fill('Synthetic manual evidence remains pending.');
  await manual.getByRole('button',{name:'Lagre test-evidens',exact:true}).click();
  await poll(()=>fixture.controls.filingCalls.some(c=>c.path==='/api/v1/company-tax/test-evidence'));
  assert.equal(fixture.controls.filingCalls.find(c=>c.path==='/api/v1/company-tax/test-evidence').status,200);
  const relations=['company_tax_filing.filing_submissions','company_tax_filing.authority_test_runs','company_tax_filing.authority_permissions','public.audit_events'];
  await fixtureTableTransaction(fixture.db,relations,async()=>{
    const count=async(table,extra='')=>(await fixture.db.query(`select count(*)::int count from ${table} where company_id=$1 ${extra}`,[fixture.companyId])).rows[0].count;
    assert.equal(await count('company_tax_filing.filing_submissions'),1);
    assert.equal(await count('company_tax_filing.authority_test_runs'),2);
    assert.equal(await count('company_tax_filing.authority_permissions'),1);
    assert.equal(await count('public.audit_events',"and action='company_tax_tt02_evidence_imported'"),1);
    for (const family of ['filing_submissions','authority_test_runs'])
      assert.equal((await fixture.db.query('select to_regclass($1) is null absent',[`public.${family}`])).rows[0].absent,true);
    const row=(await fixture.db.query('select submitted_payload::text payload,receipt_metadata::text receipt from company_tax_filing.filing_submissions where company_id=$1',[fixture.companyId])).rows[0];
    assert.doesNotMatch(row.payload+row.receipt,/SENTINEL|accessToken|privateKeyPem|personalIdentifier/u);
  });
  await fixtureTableTransaction(fixture.db,['public.company_memberships'],async()=>{
    await fixture.db.query("update public.company_memberships set role='read_only' where company_id=$1 and user_id=$2",[fixture.companyId,fixture.owner.id]);
  });
  try {
    const revoked=await fixture.taxRequest(`/api/v1/company-tax/source-facts?companyId=${fixture.companyId}&incomeYear=2025`);
    assert.equal(revoked.status,404,'a retained real AAL2 JWT cannot bypass current owner authorization or reveal concealed history');
  } finally {
    await fixtureTableTransaction(fixture.db,['public.company_memberships'],async()=>{
      await fixture.db.query("update public.company_memberships set role='owner' where company_id=$1 and user_id=$2",[fixture.companyId,fixture.owner.id]);
    });
  }
  assert.deepEqual(blockedRequests,[]);
});
async function poll(condition) {
  const deadline=Date.now()+25_000;
  while(!condition()){assert.ok(Date.now()<deadline,'fixture condition timed out');await new Promise(resolve=>setTimeout(resolve,25));}
}
