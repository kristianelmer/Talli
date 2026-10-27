import assert from "node:assert/strict";
import { randomUUID } from "node:crypto";
import { spawnSync } from "node:child_process";
import { createServer } from "node:http";
import { createRequire } from "node:module";
import { mkdir,writeFile } from "node:fs/promises";
import { pathToFileURL } from "node:url";
import { createClient } from "@supabase/supabase-js";
import pg from "pg";
import { allocateLoopbackPort,ownedProcessDiagnostics,startOwnedProcess,stopOwnedProcess,waitForOwnedReadiness } from "./owned-process-lifecycle.mjs";
import { isLoopbackPostgresUrl,isLoopbackSupabaseUrl } from "./supabase_fixture_safety.mjs";
import { connectedWebMode } from "./connected-viewport.mjs";
import {seedAccountsOpening} from "./accounts-browser-governance.mjs";

export async function startTaxBrowserFixture({incomeYear=2026,delivery=false,accountsDelivery=false,validationBlocked=false,partialCalculated=false}={}) {
  const webMode=connectedWebMode();
  assert.ok([2025,2026].includes(incomeYear));
  assert.ok(!delivery || incomeYear===2025);
  assert.ok(!accountsDelivery || incomeYear===2025 && !delivery);
  assert.ok(!validationBlocked || delivery);
  assert.ok(!partialCalculated || validationBlocked);
  const deliveryControlKey=delivery||accountsDelivery?randomUUID().replaceAll("-","")+randomUUID().replaceAll("-",""):null;
  const databaseUrl=process.env.DATABASE_URL;
  const supabaseUrl=process.env.SUPABASE_URL;
  const anonKey=process.env.SUPABASE_ANON_KEY;
  const serviceKey=process.env.SUPABASE_SERVICE_ROLE_KEY;
  assert.ok(databaseUrl&&supabaseUrl&&anonKey&&serviceKey);
  assert.ok(isLoopbackPostgresUrl(databaseUrl)&&isLoopbackSupabaseUrl(supabaseUrl));
  const db=new pg.Client({connectionString:databaseUrl});await db.connect();
  const admin=createClient(supabaseUrl,serviceKey,{auth:{autoRefreshToken:false,persistSession:false}});
  const roles=[];let owner,companyId,orgNumber,backend,web,proxy;
  const filingAuthorization=new Map();
  const controls={dropNextCapture:false,failNextPreview:false,delayPreviewAmount:null,captures:[],previews:[],filingCalls:[],dropNextTaxImport:false,dropNextTaxSubmission:false,failAccountsReads:false,accountsReadFailures:[]};
  const baseEnv=Object.fromEntries(['PATH','HOME','TMPDIR','LANG','LC_ALL'].filter(key=>process.env[key]).map(key=>[key,process.env[key]]));
  const close=async()=>{
    const errors=[];const attempt=async(fn)=>{try{await fn();}catch(e){errors.push(e);}};
    await attempt(()=>stopOwnedProcess(web));await attempt(()=>stopOwnedProcess(backend));
    if(proxy)await attempt(()=>new Promise(resolve=>proxy.close(resolve)));
    if(companyId&&accountsDelivery)await attempt(async()=>{
      const {rows}=await db.query('select storage_key from public.documents where company_id=$1',[companyId]);
      const keys=rows.map(row=>row.storage_key).filter(Boolean);
      if(keys.length)assert.ifError((await admin.storage.from('company-documents').remove(keys)).error);
    });
    for(const role of roles)await attempt(()=>db.query(`alter role ${role} nologin password null`));
    if(companyId&&(delivery||accountsDelivery))await attempt(()=>db.query("delete from public.annual_data where company_id=$1",[companyId]));
    if(companyId)await attempt(()=>{
      const result=spawnSync(process.execPath,['tests/support/tax-fixture-cleanup.mjs'],{cwd:process.cwd(),env:{...baseEnv,DATABASE_URL:databaseUrl},input:JSON.stringify([companyId]),encoding:'utf8'});
      assert.equal(result.status,0,result.stderr);
    });
    if(owner)await attempt(async()=>assert.ifError((await admin.auth.admin.deleteUser(owner.id)).error));
    await attempt(()=>db.end());
    if(errors.length)throw new AggregateError(errors,'tax_browser_fixture_cleanup_failed');
  };
  try {
    assert.equal((await db.query('select phase from backend_system.tax_settlement_migration_state')).rows[0].phase,'contracted');
    if(incomeYear===2025)assert.equal((await db.query('select phase from backend_system.company_tax_return_migration_state')).rows[0].phase,'contracted');
    const email=`tax-browser-${randomUUID()}@example.test`,password=`Fixture-${randomUUID()}-1a!`;
    const created=await admin.auth.admin.createUser({email,password,email_confirm:true});assert.ifError(created.error);
    owner={id:created.data.user.id,email,password};
    const python=process.env.TALLI_BACKEND_PYTHON_BIN||'apps/backend/.venv/bin/python';
    const seed=spawnSync(python,['tests/fixtures/seed_tax_browser_company.py'],{cwd:process.cwd(),env:{...baseEnv,DATABASE_URL:databaseUrl},input:JSON.stringify({owner:owner.id,incomeYear,delivery:delivery||accountsDelivery,accountsDelivery}),encoding:'utf8'});
    assert.equal(seed.status,0,seed.stderr);({companyId,orgNumber}=JSON.parse(seed.stdout));
    if(accountsDelivery)await seedAccountsOpening(db,companyId,owner.id);
    const urls={};
    for(const role of ['talli_company_access_backend','talli_ledger_backend','talli_banking_backend','talli_marketing_measurement_backend']){
      const prior=(await db.query('select rolcanlogin,rolinherit,rolbypassrls from pg_roles where rolname=$1',[role])).rows;
      assert.deepEqual(prior,[{rolcanlogin:false,rolinherit:false,rolbypassrls:false}]);
      const password=randomUUID().replaceAll('-','');await db.query(`alter role ${role} login password '${password}'`);roles.push(role);
      const url=new URL(databaseUrl);url.username=role;url.password=password;urls[role]=url.href;
    }
    const backendPort=await allocateLoopbackPort(),webPort=await allocateLoopbackPort(),proxyPort=await allocateLoopbackPort();
    const backendOrigin=`http://127.0.0.1:${backendPort}`,siteOrigin=`http://127.0.0.1:${webPort}`;
    const nonce=randomUUID();
    backend=startOwnedProcess({command:python,args:[accountsDelivery?'tests/fixtures/start_accounts_delivery_workspace_backend.py':delivery?'tests/fixtures/start_tax_delivery_workspace_backend.py':'tests/fixtures/start_rf1086_workspace_backend.py'],cwd:process.cwd(),readinessProof:`TALLI_BACKEND_BOUND:${nonce}`,env:{...baseEnv,
      SUPABASE_URL:supabaseUrl,SUPABASE_ANON_KEY:anonKey,SUPABASE_SERVICE_ROLE_KEY:serviceKey,DATABASE_URL:databaseUrl,
      TALLI_LEDGER_DATABASE_URL:urls.talli_ledger_backend,TALLI_COMPANY_ACCESS_DATABASE_URL:urls.talli_company_access_backend,
      TALLI_BANKING_DATABASE_URL:urls.talli_banking_backend,TALLI_MARKETING_MEASUREMENT_DATABASE_URL:urls.talli_marketing_measurement_backend,TALLI_BACKEND_PORT:String(backendPort),TALLI_READINESS_NONCE:nonce,
      TALLI_RF1086_PRODUCTION_ENABLED:'false',TALLI_AUTHORITY_OPS_ENABLED:'false',...(delivery?{TALLI_TAX_BROWSER_COMPANY_ID:companyId,TALLI_TAX_BROWSER_OWNER_ID:owner.id,TALLI_TAX_BROWSER_ORG:orgNumber,TALLI_TAX_BROWSER_CONTROL_KEY:deliveryControlKey,TALLI_TAX_BROWSER_VALIDATION_BLOCKED:String(validationBlocked),TALLI_TAX_BROWSER_PARTIAL_CALCULATED:String(partialCalculated)}:{}),
      ...(accountsDelivery?{TALLI_ACCOUNTS_BROWSER_COMPANY_ID:companyId,TALLI_ACCOUNTS_BROWSER_OWNER_ID:owner.id,TALLI_ACCOUNTS_BROWSER_ORG:orgNumber,TALLI_ACCOUNTS_BROWSER_CONTROL_KEY:deliveryControlKey}:{})}});
    await waitForOwnedReadiness({process:backend,url:backendOrigin+'/health/ready'});
    proxy=createServer(async(req,res)=>{
      try{
        let body='';for await(const chunk of req)body+=chunk;
        const headers=new Headers();for(const [key,value]of Object.entries(req.headers))if(!['host','connection','content-length'].includes(key)&&value!==undefined)headers.set(key,Array.isArray(value)?value.join(','):value);
        if(controls.failAccountsReads && req.method==='GET' && req.url.startsWith('/api/v1/annual-accounts/')) {
          controls.accountsReadFailures.push({path:req.url,status:503});
          res.writeHead(503);res.end();return;
        }
        const response=await fetch(backendOrigin+req.url,{method:req.method,headers,...(body?{body}:{})});
        const bytes=Buffer.from(await response.arrayBuffer());
        if(req.url.startsWith('/api/v1/company-tax/') || req.url.startsWith('/api/v1/annual-accounts/')){
          filingAuthorization.set(req.url.split('/')[3],headers.get('authorization'));
          if(req.method==='POST'&&!req.url.endsWith('-previews')){
            controls.filingCalls.push({path:req.url,body:JSON.parse(body),status:response.status,response:JSON.parse(bytes.toString())});
            if(req.url==='/api/v1/company-tax/delivery-submission-advances'&&controls.dropNextTaxSubmission&&response.ok){controls.dropNextTaxSubmission=false;res.destroy();return;}
            if(req.url==='/api/v1/company-tax/tt02-evidence-imports'&&controls.dropNextTaxImport&&response.ok){controls.dropNextTaxImport=false;res.destroy();return;}
          }
        }
        if(req.url==='/api/v1/ledger/tax-settlements'&&req.method==='POST'){
          controls.captures.push({body:JSON.parse(body),status:response.status,response:JSON.parse(bytes.toString())});
          if(controls.dropNextCapture&&response.status===201){controls.dropNextCapture=false;res.destroy();return;}
        }
        if(req.url==='/api/v1/company-tax/settlement-previews'){
          const input=JSON.parse(body);controls.previews.push(input);
          if(controls.failNextPreview){controls.failNextPreview=false;res.writeHead(503);res.end();return;}
          if(input.amount===controls.delayPreviewAmount)await new Promise(resolve=>setTimeout(resolve,1200));
        }
        res.writeHead(response.status,Object.fromEntries([...response.headers].filter(([key])=>!['content-length','content-encoding','transfer-encoding','connection'].includes(key))));res.end(bytes);
      }catch{res.writeHead(503);res.end();}
    });
    await new Promise(resolve=>proxy.listen(proxyPort,'127.0.0.1',resolve));
    const nextCli=createRequire(new URL('../../apps/web/package.json',import.meta.url)).resolve('next/dist/bin/next');
    web=startOwnedProcess({command:process.execPath,args:[nextCli,webMode.command,'apps/web','--hostname','127.0.0.1','--port',String(webPort)],cwd:process.cwd(),readinessProof:webMode.readinessProof,env:{...baseEnv,...webMode.env,NEXT_TELEMETRY_DISABLED:'1',NEXT_PUBLIC_SUPABASE_URL:supabaseUrl,NEXT_PUBLIC_SUPABASE_ANON_KEY:anonKey,SUPABASE_URL:supabaseUrl,SUPABASE_ANON_KEY:anonKey,...(accountsDelivery?{SUPABASE_SERVICE_ROLE_KEY:serviceKey}:{}),TALLI_BACKEND_URL:`http://127.0.0.1:${proxyPort}`,SITE_URL:siteOrigin}});
    await waitForOwnedReadiness({process:web,url:siteOrigin});
    const filingRequest=(capability,path,options={})=>{
      assert.ok(path.startsWith(`/api/v1/${capability}/`));
      const authorization=filingAuthorization.get(capability);
      assert.ok(authorization,'a real browser session must establish authorization');
      return fetch(backendOrigin+path,{...options,headers:{...options.headers,authorization}});
    };
    const taxRequest=(path,options)=>filingRequest('company-tax',path,options);
    const accountsRequest=(path,options)=>filingRequest('annual-accounts',path,options);
    const governanceRequest=(path,options={})=>{
      assert.ok(accountsDelivery && /^\/api\/v1\/(?:corporate-governance|documents)\//u.test(path));
      const authorization=filingAuthorization.get('annual-accounts');assert.ok(authorization,'an actual owner browser request must establish authorization');
      return fetch(backendOrigin+path,{...options,headers:{...options.headers,authorization}});
    };
    const deliveryState=async()=>{assert.ok(delivery);const response=await fetch(backendOrigin+'/__fixture__/tax-delivery-state',{headers:{'X-Talli-Fixture-Key':deliveryControlKey}});assert.equal(response.status,200);return response.json();};
    const accountsDeliveryState=async()=>{assert.ok(accountsDelivery);const response=await fetch(backendOrigin+'/__fixture__/accounts-delivery-state',{headers:{'X-Talli-Fixture-Key':deliveryControlKey}});assert.equal(response.status,200);return response.json();};
    const failNextAccountsParentRead=async()=>{assert.ok(accountsDelivery);const response=await fetch(backendOrigin+'/__fixture__/accounts-delivery-control',{method:'POST',headers:{'X-Talli-Fixture-Key':deliveryControlKey}});assert.equal(response.status,200);};
    const seedCorrectionInterest=()=>{assert.ok(delivery);const seeded=spawnSync(python,['tests/fixtures/seed_tax_delivery_interest.py'],{cwd:process.cwd(),env:{...baseEnv,DATABASE_URL:databaseUrl},input:JSON.stringify({companyId,owner:owner.id}),encoding:'utf8'});assert.equal(seeded.status,0,seeded.stderr);};
    return {siteOrigin,backendOrigin,owner,companyId,orgNumber,controls,db,diagnostics:()=>ownedProcessDiagnostics(backend),webDiagnostics:()=>ownedProcessDiagnostics(web),close,taxRequest,accountsRequest,governanceRequest,deliveryState,accountsDeliveryState,failNextAccountsParentRead,seedCorrectionInterest};
  }catch(error){if((delivery||accountsDelivery)&&process.env.TALLI_TAX_BROWSER_ARTIFACT_DIR){try{await mkdir(process.env.TALLI_TAX_BROWSER_ARTIFACT_DIR,{recursive:true,mode:0o700});await writeFile(process.env.TALLI_TAX_BROWSER_ARTIFACT_DIR+'/startup-private.log',ownedProcessDiagnostics(backend)+'\n'+ownedProcessDiagnostics(web),{mode:0o600});}catch{ /* Diagnostics must never prevent owned cleanup. */ }}try{await close();}catch(cleanup){throw new AggregateError([error,cleanup],'tax_browser_fixture_setup_failed');}throw error;}
}

if(process.argv[1] && import.meta.url===pathToFileURL(process.argv[1]).href){
 const fixture=await startTaxBrowserFixture();
 await writeFile(process.env.TALLI_TAX_BROWSER_MANIFEST,JSON.stringify({siteOrigin:fixture.siteOrigin,owner:fixture.owner,companyId:fixture.companyId}));
 console.log(`Owned Tax browser ready: ${fixture.siteOrigin}`);
 await new Promise(resolve=>{process.once('SIGTERM',resolve);process.once('SIGINT',resolve);});await fixture.close();
}
