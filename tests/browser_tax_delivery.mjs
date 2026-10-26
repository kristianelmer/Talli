import assert from "node:assert/strict";
import {createHash,randomUUID} from "node:crypto";
import {mkdir,readFile,writeFile} from "node:fs/promises";
import test from "node:test";
import {createClient} from "@supabase/supabase-js";
import {chromium} from "playwright";
import {startTaxBrowserFixture} from "./support/tax-browser-fixture.mjs";
import {establishOwnerAal2} from "./support/tax-browser-auth.mjs";
import {installBrowserEgressGuard} from "./fixtures/system-user-authority-mock.mjs";
import {connectedViewport,activateConnectedButton,assertConnectedLayout,assertConnectedReflow} from "./support/connected-viewport.mjs";

const viewport=connectedViewport();

test("owner completes finite Tax delivery, lost-response recovery and changed correction with exact originals",{timeout:240_000},async t=>{
  const fixture=await startTaxBrowserFixture({incomeYear:2025,delivery:true});
  let browser,page;
  const artifactPath=process.env.TALLI_TAX_BROWSER_ARTIFACT_DIR;
  t.after(async()=>{try{
    if(artifactPath){
      await writeFile(artifactPath+'/backend-private.log',fixture.diagnostics(),{mode:0o600});
      await writeFile(artifactPath+'/state-private.json',JSON.stringify(await fixture.deliveryState()),{mode:0o600});
      if(page){await writeFile(artifactPath+'/page-private.txt',await page.locator('body').innerText(),{mode:0o600});await page.screenshot({path:artifactPath+'/final.png',fullPage:true});}
    }
  }finally{try{await browser?.close();}finally{await fixture.close();}}});
  browser=await chromium.launch({headless:true});
  const context=await browser.newContext(viewport.contextOptions),blockedRequests=[];
  await installBrowserEgressGuard(context,{approvalEnabled:false,blockedRequests,mockBaseUrl:fixture.siteOrigin});
  page=await context.newPage();page.setDefaultTimeout(25_000);
  const scope=`companyId=${fixture.companyId}&incomeYear=2025`;
  const workspace=async()=>{const r=await fixture.taxRequest('/api/v1/company-tax/delivery-workspace?'+scope);assert.equal(r.status,200);return r.json();};
  if(artifactPath)await mkdir(artifactPath,{recursive:true,mode:0o700});
  async function capture(name){
    await assertConnectedLayout(page,viewport,name);await assertConnectedReflow(page,viewport);
    if(artifactPath)await page.screenshot({path:`${artifactPath}/${viewport.mobile?'touch':'desktop'}-${name}.png`,fullPage:true});
  }
  async function click(name,state){
    console.log('Owner step: '+name);
    await activateConnectedButton(page,page.getByRole('button',{name,exact:true}),viewport);
    if(state)await page.getByRole('heading',{name:state,exact:true}).waitFor();
  }
  await page.goto(fixture.siteOrigin+'/login');
  await page.getByRole('textbox',{name:'E-post',exact:true}).fill(fixture.owner.email);
  await page.locator('input[name="password"]').fill(fixture.owner.password);
  await click('Logg inn');await page.waitForURL(url=>url.pathname!=='/login');
  const auth=createClient(process.env.SUPABASE_URL,process.env.SUPABASE_ANON_KEY,{auth:{autoRefreshToken:false,persistSession:false}});
  const signed=await auth.auth.signInWithPassword({email:fixture.owner.email,password:fixture.owner.password});assert.ifError(signed.error);
  const aal1=signed.data.session.access_token;
  assert.equal((await fetch(fixture.backendOrigin+'/api/v1/company-tax/delivery-workspace?'+scope,{headers:{authorization:'Bearer '+aal1}})).status,403);
  await establishOwnerAal2(page,fixture.siteOrigin);
  await page.goto(fixture.siteOrigin+'/filing/skattemelding');
  await page.getByRole('button',{name:'Forbered skattemeldingen',exact:true}).waitFor();
  assert.equal((await workspace()).rows.length,0);
  await click('Forbered skattemeldingen','Utkast klart');
  const root=(await workspace()).rows[0];assert.equal(root.state,'prepared');assert.ok(root.fields.length>0);
  await capture('draft');
  async function throughReview(){
    for(const [name,state]of [['Bekreft utkastet','Utkast bekreftet'],['Opprett levering','Levering opprettet'],
      ['Overfør dokumentene','Dokumenter overført'],
      ['Valider dokumentene','Venter på validering'],['Hent valideringen','Validering klar'],
      ['Gjør klar eierkontroll','Kontrollsteget er uavklart'],['Kontroller bekreftelsessteget','Klar for eierkontroll']])await click(name,state);
    const review=page.getByRole('region',{name:'Eierkontroll av beregnede dokumenter'});
    await review.getByText('Kontroller alle feltene.',{exact:true}).waitFor();
    assert.equal(await review.locator('details').count(),5,'four calculated documents and all subject flags');
    const boxes=review.getByRole('checkbox');assert.equal(await boxes.count(),2);
    assert.equal(await boxes.nth(0).isChecked(),false);assert.equal(await boxes.nth(1).isChecked(),false);
    for(const details of await review.locator('details').all())await details.locator('summary').click();
    await capture('owner-review');
    assert.equal(await review.getByRole('link',{name:'Last ned dokumentets original',exact:true}).count(),4);
    await boxes.nth(0).check();await boxes.nth(1).check();
  }
  await throughReview();
  fixture.controls.dropNextTaxSubmission=true;
  await click('Bekreft og send','Innsendingsstatus er uavklart');
  assert.equal(await page.getByRole('button',{name:'Bekreft og send',exact:true}).count(),0);
  let current=await workspace();assert.deepEqual(current.rows[0].actions,['reconcile_submission']);
  await capture('lost-response');
  await click('Avklar innsendingsstatus','Sendt og kvittert');
  current=await workspace();
  const receipt=current.rows[0].originals.find(value=>value.purpose==='feedback');assert.ok(receipt);
  const keyScope=scope+`&filingId=${root.filingId}&key=${encodeURIComponent(receipt.key)}`;
  const exact=await fixture.taxRequest('/api/v1/company-tax/delivery-original?'+keyScope);assert.equal(exact.status,200);
  const wire=await exact.json(),raw=Buffer.from(wire.bodyBase64,'base64');
  // The binary trailer and UTF-8 BOM survive SDK/web download without XML parsing.
  assert.deepEqual(raw,Buffer.concat([Buffer.from('\ufeff <synthetic-technical-receipt/>\n'),Buffer.from([255])]));
  assert.equal(createHash('sha256').update(raw).digest('hex'),receipt.sha256);
  const originalLink=page.locator('a').filter({hasText:'Kvittering · '+receipt.sha256.slice(0,8)});
  await originalLink.locator('xpath=ancestor::details').evaluate(element=>element.open=true);
  const downloadPromise=page.waitForEvent('download');await originalLink.click();const download=await downloadPromise;
  assert.deepEqual(await readFile(await download.path()),raw);
  for(const [params,expected]of [[keyScope.replace(fixture.companyId,randomUUID()),404],[keyScope.replace('incomeYear=2025','incomeYear=2024'),422]]){
    assert.equal((await fixture.taxRequest('/api/v1/company-tax/delivery-original?'+params)).status,expected);
  }
  assert.ok([401,403].includes((await fetch(fixture.backendOrigin+'/api/v1/company-tax/delivery-original?'+keyScope,{headers:{authorization:'Bearer '+aal1}})).status),'unstepped token cannot download originals');
  await capture('receipted');
  fixture.seedCorrectionInterest();
  await page.reload();await click('Kontroller og forbered korrigering','Utkast klart');
  current=await workspace();assert.equal(current.rows.length,2);
  const child=current.rows.find(value=>value.parentFilingId===root.filingId);assert.ok(child);
  assert.ok(child.fields.some(field=>field.path.endsWith('beloepSomHeltall') && Number(field.value)===100));assert.notEqual(child.draftSha256,root.draftSha256);
  assert.deepEqual(current.rows.find(row=>row.filingId===root.filingId).actions,[]);
  await throughReview();await click('Bekreft og send','Innsendingsstatus er uavklart');
  await click('Avklar innsendingsstatus');
  await page.locator(`[data-tax-filing="${child.filingId}"]`).getByRole('heading',{name:'Sendt og kvittert',exact:true}).waitFor();
  await capture('correction-receipted');
  const state=await fixture.deliveryState();assert.deepEqual(state.errors,[]);
  assert.equal(Object.keys(state.filings).length,2);
  assert.equal(new Set(Object.values(state.filings).map(value=>value.instance)).size,2);
  for(const value of Object.values(state.filings))assert.deepEqual([value.confirmationPuts,value.submissionPuts,value.step],[1,1,3]);
  assert.equal(state.calls.filter(value=>value.family==='intake').length,2);
  assert.equal(state.calls.filter(value=>value.family==='parent').length,3);
  assert.deepEqual(blockedRequests,[]);
});

test("owner can read blocking validation findings and documents without a submission action",{timeout:150_000},async t=>{
  const fixture=await startTaxBrowserFixture({incomeYear:2025,delivery:true,validationBlocked:true,partialCalculated:true});
  let browser,page;
  t.after(async()=>{try{await browser?.close();}finally{await fixture.close();}});
  browser=await chromium.launch({headless:true});const context=await browser.newContext(viewport.contextOptions),blockedRequests=[];
  await installBrowserEgressGuard(context,{approvalEnabled:false,blockedRequests,mockBaseUrl:fixture.siteOrigin});
  page=await context.newPage();page.setDefaultTimeout(25_000);
  await page.goto(fixture.siteOrigin+'/login');
  await page.getByRole('textbox',{name:'E-post',exact:true}).fill(fixture.owner.email);
  await page.locator('input[name="password"]').fill(fixture.owner.password);
  await activateConnectedButton(page,page.getByRole('button',{name:'Logg inn',exact:true}),viewport);
  await page.waitForURL(url=>url.pathname!=='/login');await establishOwnerAal2(page,fixture.siteOrigin);
  await page.goto(fixture.siteOrigin+'/filing/skattemelding');
  for(const [name,heading]of [['Forbered skattemeldingen','Utkast klart'],['Bekreft utkastet','Utkast bekreftet'],
    ['Opprett levering','Levering opprettet'],['Overfør dokumentene','Dokumenter overført'],['Valider dokumentene','Venter på validering'],
    ['Hent valideringen','Validering krever kontroll']]){
    await activateConnectedButton(page,page.getByRole('button',{name,exact:true}),viewport);
    await page.getByRole('heading',{name:heading,exact:true}).waitFor();
  }
  await activateConnectedButton(page,page.getByRole('button',{name:'Hent valideringen',exact:true}),viewport);
  await page.getByText('Kontroller alle feltene. Versjon 2.',{exact:true}).waitFor();
  const result=page.getByRole('region',{name:'Valideringsresultat',exact:true});
  await result.getByText('Kontroller dette feltet.',{exact:true}).waitFor();
  await result.getByText('123',{exact:true}).waitFor();await result.getByText('test.felt',{exact:true}).waitFor();
  assert.equal(await result.locator('details').count(),2,'one supported statutory document and all flags remain readable');
  assert.equal(await page.getByRole('button',{name:'Bekreft og send',exact:true}).count(),0);
  assert.equal(await page.getByRole('button',{name:'Gjør klar eierkontroll',exact:true}).count(),0);
  for(const details of await result.locator('details').all())await details.locator('summary').click();
  const response=await fixture.taxRequest(`/api/v1/company-tax/delivery-workspace?companyId=${fixture.companyId}&incomeYear=2025`);
  assert.equal(response.status,200);const row=(await response.json()).rows[0];
  assert.equal(row.validation.documentsAvailable,false);assert.equal(row.validation.documents.length,1);
  assert.ok(row.validation.documents[0].fields.some(field=>field.path.endsWith('/beloepSomHeltall[1]') && field.value==='2'));
  const originalHref=await result.getByRole('link',{name:'Last ned valideringsoriginalen',exact:true}).getAttribute('href');
  assert.equal(new URL(originalHref,fixture.siteOrigin).searchParams.get('key'),'validation_result:'+row.validation.originalSha256,'displayed fields link to their latest exact enclosing original');
  assert.equal(row.originals.filter(value=>value.purpose==='validation_result').length,2);
  await assertConnectedLayout(page,viewport,'blocked validation');await assertConnectedReflow(page,viewport);
  if(process.env.TALLI_TAX_BROWSER_ARTIFACT_DIR)await page.screenshot({path:process.env.TALLI_TAX_BROWSER_ARTIFACT_DIR+'/'+(viewport.mobile?'touch':'desktop')+'-validation-blocked.png',fullPage:true});
  const state=await fixture.deliveryState();assert.deepEqual(state.errors,[]);
  assert.ok(state.calls.every(call=>call.method!=='PUT'));assert.deepEqual(blockedRequests,[]);
});
