/** Validate an actual signed-topology archive through generated + web readers. */
import assert from "node:assert/strict";
import {webcrypto} from "node:crypto";
import {readFileSync} from "node:fs";
import vm from "node:vm";
import ts from "typescript";
import {createTalliApiClient,TalliApiError} from "../../packages/talli-api-client/src/generated/client.ts";

const input=JSON.parse(readFileSync(0,"utf8"));
const value=input.archive;
const api=createTalliApiClient({baseUrl:"https://finite-client.invalid",fetch:async url=>{
  const parsed=new URL(url);
  if(parsed.pathname.endsWith("/delivery-journal-v1")) {
    assert.equal(parsed.searchParams.get("readEvidence"),"true");
    assert.equal(parsed.searchParams.get("readEvidenceVersion"),"2");
    assert.equal(parsed.searchParams.get("validationEvidence"),"true");
    return Response.json(value);
  }
  assert.ok(parsed.pathname.endsWith("/source-facts"));
  return Response.json(input.source);
}});
const exports={};
const dependencies={backendBaseUrl:()=>"https://finite-client.invalid",TalliApiError,createTalliApiClient:()=>api};
const source=readFileSync(new URL("../../apps/web/features/company-tax-filing/transport.ts",import.meta.url),"utf8");
vm.runInNewContext(ts.transpileModule(source,{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.CommonJS}}).outputText,
  {exports,require:()=>dependencies,AbortSignal,TextEncoder,TextDecoder,atob,btoa,crypto:webcrypto});
const result=await exports.loadTaxDeliveryDraftArchiveSource("synthetic-local-check",value.companyId,value.incomeYear);
assert.equal(result.error,null,"actual retained archive must survive the browser reader");
assert.equal(JSON.stringify(result.data.journal),JSON.stringify(value));
process.stdout.write("Actual Tax archive accepted with every original unchanged.\n");
