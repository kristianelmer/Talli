import assert from "node:assert/strict";
import { randomUUID } from "node:crypto";
import { spawnSync } from "node:child_process";
import { createServer } from "node:http";
import { createRequire } from "node:module";
import { writeFile } from "node:fs/promises";
import { pathToFileURL } from "node:url";
import { createClient } from "@supabase/supabase-js";
import pg from "pg";
import { allocateLoopbackPort,startOwnedProcess,stopOwnedProcess,waitForOwnedReadiness } from "./owned-process-lifecycle.mjs";
import { isLoopbackPostgresUrl,isLoopbackSupabaseUrl } from "./supabase_fixture_safety.mjs";

export async function startTaxBrowserFixture({incomeYear=2026}={}) {
  assert.ok([2025,2026].includes(incomeYear));
  const databaseUrl=process.env.DATABASE_URL;
  const supabaseUrl=process.env.SUPABASE_URL;
  const anonKey=process.env.SUPABASE_ANON_KEY;
  const serviceKey=process.env.SUPABASE_SERVICE_ROLE_KEY;
  assert.ok(databaseUrl&&supabaseUrl&&anonKey&&serviceKey);
  assert.ok(isLoopbackPostgresUrl(databaseUrl)&&isLoopbackSupabaseUrl(supabaseUrl));
  const db=new pg.Client({connectionString:databaseUrl});await db.connect();
  const admin=createClient(supabaseUrl,serviceKey,{auth:{autoRefreshToken:false,persistSession:false}});
  const roles=[];let owner,companyId,orgNumber,backend,web,proxy,taxAuthorization;
  const controls={dropNextCapture:false,failNextPreview:false,delayPreviewAmount:null,captures:[],previews:[],filingCalls:[],dropNextTaxImport:false};
  const baseEnv=Object.fromEntries(['PATH','HOME','TMPDIR','LANG','LC_ALL'].filter(key=>process.env[key]).map(key=>[key,process.env[key]]));
  const close=async()=>{
    const errors=[];const attempt=async(fn)=>{try{await fn();}catch(e){errors.push(e);}};
    await attempt(()=>stopOwnedProcess(web));await attempt(()=>stopOwnedProcess(backend));
    if(proxy)await attempt(()=>new Promise(resolve=>proxy.close(resolve)));
    for(const role of roles)await attempt(()=>db.query(`alter role ${role} nologin password null`));
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
    const seed=spawnSync(python,['tests/fixtures/seed_tax_browser_company.py'],{cwd:process.cwd(),env:{...baseEnv,DATABASE_URL:databaseUrl},input:JSON.stringify({owner:owner.id,incomeYear}),encoding:'utf8'});
    assert.equal(seed.status,0,seed.stderr);({companyId,orgNumber}=JSON.parse(seed.stdout));
    const urls={};
    for(const role of ['talli_company_access_backend','talli_ledger_backend','talli_banking_backend']){
      const prior=(await db.query('select rolcanlogin,rolinherit,rolbypassrls from pg_roles where rolname=$1',[role])).rows;
      assert.deepEqual(prior,[{rolcanlogin:false,rolinherit:false,rolbypassrls:false}]);
      const password=randomUUID().replaceAll('-','');await db.query(`alter role ${role} login password '${password}'`);roles.push(role);
      const url=new URL(databaseUrl);url.username=role;url.password=password;urls[role]=url.href;
    }
    const backendPort=await allocateLoopbackPort(),webPort=await allocateLoopbackPort(),proxyPort=await allocateLoopbackPort();
    const backendOrigin=`http://127.0.0.1:${backendPort}`,siteOrigin=`http://127.0.0.1:${webPort}`;
    const nonce=randomUUID();
    backend=startOwnedProcess({command:python,args:['tests/fixtures/start_rf1086_workspace_backend.py'],cwd:process.cwd(),readinessProof:`TALLI_BACKEND_BOUND:${nonce}`,env:{...baseEnv,
      SUPABASE_URL:supabaseUrl,SUPABASE_ANON_KEY:anonKey,SUPABASE_SERVICE_ROLE_KEY:serviceKey,DATABASE_URL:databaseUrl,
      TALLI_LEDGER_DATABASE_URL:urls.talli_ledger_backend,TALLI_COMPANY_ACCESS_DATABASE_URL:urls.talli_company_access_backend,
      TALLI_BANKING_DATABASE_URL:urls.talli_banking_backend,TALLI_BACKEND_PORT:String(backendPort),TALLI_READINESS_NONCE:nonce,
      TALLI_RF1086_PRODUCTION_ENABLED:'false',TALLI_AUTHORITY_OPS_ENABLED:'false'}});
    await waitForOwnedReadiness({process:backend,url:backendOrigin+'/health/ready'});
    proxy=createServer(async(req,res)=>{
      try{
        let body='';for await(const chunk of req)body+=chunk;
        const headers=new Headers();for(const [key,value]of Object.entries(req.headers))if(!['host','connection','content-length'].includes(key)&&value!==undefined)headers.set(key,Array.isArray(value)?value.join(','):value);
        const response=await fetch(backendOrigin+req.url,{method:req.method,headers,...(body?{body}:{})});
        const bytes=Buffer.from(await response.arrayBuffer());
        if(req.url.startsWith('/api/v1/company-tax/')){
          taxAuthorization=headers.get('authorization');
          if(req.method==='POST'&&!req.url.endsWith('-previews')){
            controls.filingCalls.push({path:req.url,body:JSON.parse(body),status:response.status,response:JSON.parse(bytes.toString())});
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
    web=startOwnedProcess({command:process.execPath,args:[nextCli,'dev','apps/web','--hostname','127.0.0.1','--port',String(webPort)],cwd:process.cwd(),readinessProof:'Ready in',env:{...baseEnv,NEXT_TELEMETRY_DISABLED:'1',NEXT_PUBLIC_SUPABASE_URL:supabaseUrl,NEXT_PUBLIC_SUPABASE_ANON_KEY:anonKey,SUPABASE_URL:supabaseUrl,SUPABASE_ANON_KEY:anonKey,TALLI_BACKEND_URL:`http://127.0.0.1:${proxyPort}`,SITE_URL:siteOrigin}});
    await waitForOwnedReadiness({process:web,url:siteOrigin});
    const taxRequest=(path,options={})=>{
      assert.ok(path.startsWith('/api/v1/company-tax/'));
      assert.ok(taxAuthorization,'a real browser session must establish authorization');
      return fetch(backendOrigin+path,{...options,headers:{...options.headers,authorization:taxAuthorization}});
    };
    return {siteOrigin,backendOrigin,owner,companyId,orgNumber,controls,db,close,taxRequest};
  }catch(error){try{await close();}catch(cleanup){throw new AggregateError([error,cleanup],'tax_browser_fixture_setup_failed');}throw error;}
}

if(process.argv[1] && import.meta.url===pathToFileURL(process.argv[1]).href){
 const fixture=await startTaxBrowserFixture();
 await writeFile(process.env.TALLI_TAX_BROWSER_MANIFEST,JSON.stringify({siteOrigin:fixture.siteOrigin,owner:fixture.owner,companyId:fixture.companyId}));
 console.log(`Owned Tax browser ready: ${fixture.siteOrigin}`);
 await new Promise(resolve=>{process.once('SIGTERM',resolve);process.once('SIGINT',resolve);});await fixture.close();
}
