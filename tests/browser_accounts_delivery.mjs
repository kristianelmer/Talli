import {spawnSync} from "node:child_process";
import {copyCompanyYearArchive,assertRestoreIntegrity} from "../apps/web/app/lib/backup-restore.ts";
import {verifyAccountsCompanyArchive} from "../packages/talli-api-client/src/index.ts";
import assert from "node:assert/strict";
import {createHash,randomUUID} from "node:crypto";
import {mkdir,readFile,writeFile} from "node:fs/promises";
import test from "node:test";
import {chromium} from "playwright";
import {createClient} from "@supabase/supabase-js";
import {startTaxBrowserFixture} from "./support/tax-browser-fixture.mjs";
import {completeAccountsCorporateAnnualClose} from "./support/accounts-browser-governance.mjs";
import {establishOwnerAal2} from "./support/tax-browser-auth.mjs";
import {installBrowserEgressGuard} from "./fixtures/system-user-authority-mock.mjs";
import {connectedViewport,activateConnectedButton,assertConnectedLayout,assertConnectedReflow} from "./support/connected-viewport.mjs";

const viewport=connectedViewport();
const artifactDir=process.env.TALLI_ACCOUNTS_BROWSER_ARTIFACT_DIR;
const sha=bytes=>createHash('sha256').update(bytes).digest('hex');

test('Accounts actual owner reviews, reconciles lost uploads and retains a technical archive',{timeout:480_000},async t=>{
  const fixture=await startTaxBrowserFixture({incomeYear:2025,accountsDelivery:true});let browser,page;
  t.after(async()=>{try{
    if(artifactDir){
      await mkdir(artifactDir,{recursive:true,mode:0o700});await writeFile(artifactDir+'/backend-private.log',fixture.diagnostics(),{mode:0o600});
      await writeFile(artifactDir+'/web-private.log',fixture.webDiagnostics(),{mode:0o600});
      await writeFile(artifactDir+'/filing-calls-private.json',JSON.stringify(fixture.controls.filingCalls,null,2),{mode:0o600});
      if(page&&!['/mfa','/login'].includes(new URL(page.url()).pathname))await writeFile(artifactDir+'/page-private.txt',await page.locator('body').innerText(),{mode:0o600});
    }
  }finally{try{await browser?.close();}finally{await fixture.close();}}});
  browser=await chromium.launch({headless:true});const context=await browser.newContext(viewport.contextOptions);const blockedRequests=[];
  await installBrowserEgressGuard(context,{approvalEnabled:false,blockedRequests,mockBaseUrl:fixture.siteOrigin});
  page=await context.newPage();page.setDefaultTimeout(60_000);
  async function checkpoint(name){
    await assertConnectedLayout(page,viewport,name);await assertConnectedReflow(page,viewport);
    if(artifactDir){await mkdir(artifactDir,{recursive:true,mode:0o700});await page.screenshot({path:artifactDir+'/'+name+'.png',fullPage:true});}
    if(artifactDir&&viewport.mobile&&name==='accounts-correction-technical-archive'){
      try{await page.setViewportSize({width:320,height:844});await assertConnectedLayout(page,viewport,'final correction at 320px');
        await page.screenshot({path:artifactDir+'/'+name+'-320.png',fullPage:true});
      }finally{await page.setViewportSize(viewport.contextOptions.viewport);}
    }
  }
  await page.goto(fixture.siteOrigin+'/login');
  await page.getByRole('textbox',{name:'E-post',exact:true}).fill(fixture.owner.email);
  await page.locator('input[name="password"]').fill(fixture.owner.password);
  await activateConnectedButton(page,page.getByRole('button',{name:'Logg inn',exact:true}),viewport);
  await page.waitForURL(url=>url.pathname!=='/login');await page.goto(fixture.siteOrigin+'/filing/aarsregnskap');
  const body={companyId:fixture.companyId,incomeYear:2025,filingId:randomUUID(),contactEmail:'owner@example.test',confirmingRepresentative:'Synthetic Chair'};
  const auth=createClient(process.env.SUPABASE_URL,process.env.SUPABASE_ANON_KEY,{auth:{autoRefreshToken:false,persistSession:false}});
  const signed=await auth.auth.signInWithPassword({email:fixture.owner.email,password:fixture.owner.password});assert.ifError(signed.error);
  const unstepped=await fetch(fixture.backendOrigin+'/api/v1/annual-accounts/delivery-drafts',{method:'POST',
    headers:{authorization:'Bearer '+signed.data.session.access_token,'Content-Type':'application/json','Idempotency-Key':randomUUID()},body:JSON.stringify(body)});
  assert.equal(unstepped.status,403,'actual AAL1 owner cannot prepare');
  await establishOwnerAal2(page,fixture.siteOrigin);
  for(let attempt=0;attempt<3;attempt++){
    await page.goto(fixture.siteOrigin+'/filing/aarsregnskap',{waitUntil:'commit',timeout:90_000});
    if(await page.locator('[data-accounts-delivery="workspace"]').count())break;
    await new Promise(resolve=>setTimeout(resolve,1000));
  }
  await page.locator('[data-accounts-delivery="workspace"]').waitFor();
  const corporate=await completeAccountsCorporateAnnualClose(fixture);
  assert.equal(corporate.readiness.finalized,true,'actual owning read must derive readiness from the supported2025 owner workflow');
  await page.reload({waitUntil:'commit',timeout:90_000});
  let panel=page.locator('[data-accounts-delivery="workspace"]');
  await panel.getByRole('button',{name:'Forbered årsregnskapet',exact:true}).waitFor();
  assert.equal((await fixture.accountsDeliveryState()).calls.length,0);
  await panel.getByLabel('Kontaktadresse',{exact:true}).fill('owner@example.test');
  await panel.getByLabel('Bekreftende representant',{exact:true}).fill('Synthetic Chair');
  await activateConnectedButton(page,panel.getByRole('button',{name:'Forbered årsregnskapet',exact:true}),viewport);
  for(let wait=0;wait<100&&!fixture.controls.filingCalls.some(call=>call.path==='/api/v1/annual-accounts/delivery-drafts');wait++)await new Promise(resolve=>setTimeout(resolve,100));
  const preparationCall=fixture.controls.filingCalls.find(call=>call.path==='/api/v1/annual-accounts/delivery-drafts');
  assert.equal(preparationCall?.status,200,JSON.stringify(preparationCall?.response));
  await panel.getByRole('heading',{name:'Utkast klart',exact:true}).waitFor();await checkpoint('accounts-prepared');
  const workspacePath='/api/v1/annual-accounts/delivery-workspace?'+new URLSearchParams({companyId:fixture.companyId,incomeYear:'2025'});
  async function workspace(){const response=await fixture.accountsRequest(workspacePath);assert.equal(response.status,200);return response.json();}
  let current=await workspace();assert.equal(current.rows.length,1);const filingId=current.rows[0].filingId;
  assert.ok(current.rows[0].fields.length>40);assert.equal(current.rows[0].sourceCurrent,true);
  assert.equal((await fixture.accountsDeliveryState()).calls.length,0,'prepare/view emits no authority request');
  const source=current.rows[0].originals.find(item=>item.purpose==='prepared_source');
  async function original(ref){
    const response=await fixture.accountsRequest('/api/v1/annual-accounts/delivery-original?'+new URLSearchParams({companyId:fixture.companyId,incomeYear:'2025',filingId:ref.sourceFilingId,key:ref.key}));
    assert.equal(response.status,200);const value=await response.json();const bytes=Buffer.from(value.bodyBase64,'base64');
    assert.equal(value.sourceFilingId,ref.sourceFilingId);assert.equal(value.sha256,ref.sha256);assert.equal(sha(bytes),ref.sha256);return bytes;
  }
  assert.equal(sha(await original(source)),current.rows[0].sourceSha256);
  const more=panel.getByRole('button',{name:'Neste felt',exact:true});await activateConnectedButton(page,more,viewport);
  await panel.getByText(/^41–/u).waitFor();await checkpoint('accounts-all-fields');
  async function review(label){
    const form=panel.locator('form').filter({has:page.getByRole('button',{name:label,exact:true})});
    assert.equal(await form.locator('input[type="checkbox"]').count(),2);
    assert.equal(await form.locator('input[type="checkbox"]:checked').count(),0);
    assert.equal(await form.evaluate(node=>node.checkValidity()),false);
    for(const box of await form.locator('input[type="checkbox"]').all()){
      if(viewport.mobile)await activateConnectedButton(page,box.locator('..'),viewport);else await box.check();
      assert.equal(await box.isChecked(),true);
    }
    await activateConnectedButton(page,form.getByRole('button',{name:label,exact:true}),viewport);
    const next={'Bekreft utkastet':'Opprett levering','Bekreft dokumentkontrollen':'Gå videre til signering','Bekreft signeringskontrollen':'Utfør personens signeringssteg'}[label];
    await panel.getByRole('button',{name:next,exact:true}).waitFor();
  }
  async function step(label,expected){
    await activateConnectedButton(page,panel.getByRole('button',{name:label,exact:true}),viewport);
    await panel.getByRole('heading',{name:expected,exact:true}).waitFor();await checkpoint('accounts-'+expected.replace(/[^a-zA-Z]/gu,'_'));
  }
  await review('Bekreft utkastet');await step('Opprett levering','Levering opprettet');
  await step('Hent og kontroller status','Levering opprettet');
  await step('Overfør hovedskjema','Hovedskjemaets overføring er uavklart');
  assert.equal(await panel.getByRole('button',{name:'Overfør hovedskjema',exact:true}).count(),0);
  await step('Hent og kontroller status','Hovedskjema kontrollert');
  await step('Overfør regnskapsdokumentet','Regnskapsdokumentets overføring er uavklart');
  await step('Hent og kontroller status','Klar for dokumentkontroll');
  await review('Bekreft dokumentkontrollen');await step('Gå videre til signering','Bekreftelsessteget er uavklart');
  await step('Hent og kontroller status','Klar for personens signeringskontroll');
  current=await workspace();assert.equal(current.rows[0].originals.filter(item=>item.purpose==='pdf').length,4);
  await checkpoint('accounts-person-review');await review('Bekreft signeringskontrollen');
  await step('Utfør personens signeringssteg','Signeringssteget er uavklart');
  await step('Hent og kontroller status','Teknisk arkivering bekreftet');
  current=await workspace();const row=current.rows[0];assert.equal(row.state,'technical_archive');
  assert.equal(row.filingId,filingId);assert.ok(row.knownInstance);
  const signature=row.originals.find(item=>item.purpose==='signature');const signatureBytes=await original(signature);
  assert.deepEqual(signatureBytes,Buffer.concat([Buffer.from([0xef,0xbb,0xbf]),Buffer.from('opaque synthetic signature'),Buffer.from([0x00,0xff])]));
  await panel.getByText(/^Originale dokumenter og svar /u).click();
  const link=panel.locator('a').filter({hasText:/^Signaturoriginal ·/u});
  const [download]=await Promise.all([page.waitForEvent('download'),link.click()]);
  const bytes=await readFile(await download.path());assert.equal(sha(bytes),signature.sha256);
  const rootState=await fixture.accountsDeliveryState();assert.deepEqual(rootState.errors,[]);
  assert.equal(rootState.calls.filter(call=>call.method!=='GET').length,5);
  await checkpoint('accounts-root-technical-archive');
  const changed=await fixture.db.query('update public.annual_data set annual_full_time_equivalents=1,updated_at=clock_timestamp() where company_id=$1 and income_year=2025 returning id',[fixture.companyId]);
  assert.equal(changed.rowCount,1,'change only the owned synthetic interview');
  const correctedCorporate=await completeAccountsCorporateAnnualClose(fixture);
  assert.notEqual(correctedCorporate.decisionId,corporate.decisionId);assert.notEqual(correctedCorporate.decisionHash,corporate.decisionHash);
  await page.reload({waitUntil:'commit',timeout:90_000});panel=page.locator('[data-accounts-filing="'+filingId+'"]');
  const correction=panel.locator('form').filter({has:page.getByRole('button',{name:'Forbered retting',exact:true})});
  await correction.getByLabel('Kontaktadresse',{exact:true}).fill('owner@example.test');
  await correction.getByLabel('Bekreftende representant',{exact:true}).fill('Synthetic Chair');
  await activateConnectedButton(page,correction.getByRole('button',{name:'Forbered retting',exact:true}),viewport);
  await page.getByRole('heading',{name:'Utkast klart',exact:true}).waitFor();
  current=await workspace();assert.equal(current.rows.length,2);
  const child=current.rows.find(item=>item.parentFilingId===filingId);assert.ok(child);
  assert.notEqual(child.sourceSha256,row.sourceSha256);assert.equal(child.sourceCurrent,true);
  assert.equal(current.rows.find(item=>item.filingId===filingId).state,'technical_archive');
  assert.equal((await fixture.accountsDeliveryState()).calls.filter(call=>call.method!=='GET').length,5,'parent recheck has no mutation');
  panel=page.locator('[data-accounts-filing="'+child.filingId+'"]');await checkpoint('accounts-correction-prepared');
  await review('Bekreft utkastet');
  await fixture.failNextAccountsParentRead();
  const childScope={companyId:fixture.companyId,incomeYear:2025,filingId:child.filingId,draftSha256:child.draftSha256};
  const uncertain=await fixture.accountsRequest('/api/v1/annual-accounts/delivery-reconciliations',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(childScope)});
  assert.equal(uncertain.status,200);assert.equal((await uncertain.json()).state,'correction_parent_unknown');
  const blockedCreate=await fixture.accountsRequest('/api/v1/annual-accounts/delivery-advances',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({...childScope,action:'create_instance'})});
  assert.equal(blockedCreate.status,409,'an earlier fresh proof must not authorize creation after a failed refresh');
  assert.equal((await fixture.accountsDeliveryState()).calls.filter(call=>call.method!=='GET').length,5);
  await page.reload({waitUntil:'commit',timeout:90_000});await panel.getByRole('heading',{name:'Tidligere levering må avklares',exact:true}).waitFor();
  assert.equal(await panel.getByRole('button',{name:'Opprett levering',exact:true}).count(),0);await checkpoint('accounts-failed-parent-refresh');
  await step('Kontroller tidligere levering på nytt','Utkast kontrollert');
  await step('Opprett levering','Levering opprettet');
  await step('Hent og kontroller status','Levering opprettet');
  await step('Overfør hovedskjema','Hovedskjemaets overføring er uavklart');
  await step('Hent og kontroller status','Hovedskjema kontrollert');
  await step('Overfør regnskapsdokumentet','Regnskapsdokumentets overføring er uavklart');
  await step('Hent og kontroller status','Klar for dokumentkontroll');
  await review('Bekreft dokumentkontrollen');await step('Gå videre til signering','Bekreftelsessteget er uavklart');
  await step('Hent og kontroller status','Klar for personens signeringskontroll');
  await review('Bekreft signeringskontrollen');await step('Utfør personens signeringssteg','Signeringssteget er uavklart');
  await step('Hent og kontroller status','Teknisk arkivering bekreftet');
  current=await workspace();const finalChild=current.rows.find(item=>item.filingId===child.filingId);
  assert.equal(finalChild.state,'technical_archive');assert.notEqual(finalChild.knownInstance,row.knownInstance);
  const childSignature=finalChild.originals.find(item=>item.purpose==='signature');assert.deepEqual(await original(childSignature),signatureBytes);
  assert.ok(finalChild.originals.some(item=>item.purpose==='parent_signature'));
  // Re-reading the parent after child creation must preserve both histories.
  const parentRecheck=await fixture.accountsRequest('/api/v1/annual-accounts/delivery-reconciliations',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({companyId:fixture.companyId,incomeYear:2025,filingId,draftSha256:row.draftSha256})});
  assert.equal(parentRecheck.status,200);assert.ok((await workspace()).rows.every(item=>item.state==='technical_archive'));
  // The shared company export must contain the actual Corporate-backed root
  // and correction, not only the separately downloadable workspace originals.
  const download=await page.request.get(fixture.siteOrigin+`/archive/${fixture.companyId}/2025/download`);
  assert.equal(download.status(),200,await download.text());
  const companyArchiveText=await download.text(),companyArchive=JSON.parse(companyArchiveText),accountsArchive=companyArchive.annualAccountsCompanyArchive;
  const exportReceipts=(await fixture.db.query('select archive_sha256 from public.company_archive_export_receipts where company_id=$1 and income_year=2025',[fixture.companyId])).rows;
  assert.equal(exportReceipts.filter(receipt=>receipt.archive_sha256===sha(Buffer.from(companyArchiveText))).length,1);
  await verifyAccountsCompanyArchive(accountsArchive,fixture.companyId,2025);
  assert.equal(accountsArchive.draftCount,2);
  const restored=copyCompanyYearArchive(companyArchiveText,{targetCompanyId:fixture.companyId,expectedArchiveSha256:sha(Buffer.from(companyArchiveText))});
  const integrity=assertRestoreIntegrity(restored);
  assert.deepEqual(integrity.failures.filter(code=>code.startsWith('annual_accounts_')),[]);
  assert.deepEqual(restored.restored.annualAccountsCompanyArchive,accountsArchive);
  const python=process.env.TALLI_BACKEND_PYTHON_BIN||'apps/backend/.venv/bin/python';
  const check=spawnSync(python,['scripts/check_accounts_company_archive.py','--company-id',fixture.companyId,'--income-year','2025',
    '--actor-id',fixture.owner.id,'--expected-sha256',accountsArchive.sha256],{cwd:process.cwd(),input:JSON.stringify(restored.restored.annualAccountsCompanyArchive),
    encoding:'utf8',timeout:60_000,maxBuffer:2*1024*1024});
  assert.equal(check.status,0,check.stderr);const isolatedCopy=JSON.parse(check.stdout);
  const currentHistory=await workspace();
  assert.equal(isolatedCopy.draftCount,2);assert.equal(isolatedCopy.originalCount,accountsArchive.originalCount);
  for(const filing of currentHistory.rows)for(const original of filing.originals){
    const matches=isolatedCopy.originals.filter(value=>value.filingId===filing.filingId&&value.key===original.key);
    assert.equal(matches.length,1);assert.equal(matches[0].sha256,original.sha256);assert.equal(matches[0].purpose,original.purpose);
  }
  assert.ok(isolatedCopy.originals.some(value=>value.purpose==='pdf'));
  assert.ok(isolatedCopy.originals.some(value=>value.purpose==='signature'));
  assert.ok(isolatedCopy.originals.some(value=>value.purpose==='parent_signature'));
  const missing=structuredClone(restored);missing.restored.annualAccountsCompanyArchive=null;
  assert.ok(assertRestoreIntegrity(missing).failures.includes('annual_accounts_archive_missing'));
  if(artifactDir)await writeFile(artifactDir+'/accounts-company-archive-copy-private.json',JSON.stringify({companyArchive,isolatedCopy,integrity},null,2)+'\n',{mode:0o600});
  const state=await fixture.accountsDeliveryState();assert.deepEqual(state.errors,[]);
  assert.equal(state.parentReadFailures,1);
  const mutations=state.calls.filter(call=>call.method!=='GET');assert.equal(mutations.length,10);
  const stages=[['system_user','prepare'],['system_user','prepare'],['system_user','prepare'],['system_user','confirm'],['person','sign']];
  assert.deepEqual(mutations.map(call=>[call.port,call.stage]),[...stages,...stages]);
  assert.deepEqual(blockedRequests,[]);await checkpoint('accounts-correction-technical-archive');
  if(artifactDir)await writeFile(artifactDir+'/result.json',JSON.stringify({status:'pass',scope:'actual signed JWT+AAL2+restricted SQL, finite loopback only',
    viewport:viewport.mobile?'390 touch +320 reflow':'desktop',filingId,corporateDecisionId:corporate.decisionId,corporateSourceMode:"actual 2025 owner approval, signing attestation and finalized annual-close workflow",
    mutations:mutations.length,latestParentAttemptFaultBlocked:true,correctionFilingId:child.filingId,correctionInstance:finalChild.knownInstance,exactSignatureSha256:signature.sha256,sourceSha256:row.sourceSha256,fields:row.fields.length,
    originalCount:row.originals.length,providerActivated:false,signatureAuthenticityProved:false,registryAcceptanceProved:false},null,2)+'\n',{mode:0o600});
});
