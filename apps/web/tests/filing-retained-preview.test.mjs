import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import {createRequire} from "node:module";
import vm from "node:vm";
import test from "node:test";
import ts from "typescript";

const require=createRequire(import.meta.url),React=require("react"),{renderToStaticMarkup}=require("react-dom/server");
function compile(path,dependencies={}) {
  const exports={};
  vm.runInNewContext(ts.transpileModule(readFileSync(new URL(`../app/${path}`,import.meta.url),"utf8"),{
    compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.ReactJSX},
  }).outputText,{exports,URLSearchParams,process:{env:{}},require(name){
    if(name in dependencies)return dependencies[name];
    if(name==="react/jsx-runtime")return require(name);
    throw new Error(`Unexpected dependency: ${name}`);
  }});
  return exports;
}
const {ownerCopy}=compile("lib/copy.ts",{"./launch-copy.ts":compile("lib/launch-copy.ts")});
const f=ownerCopy.filing;
async function render({blocked,retained=true}) {
  const preview={id:"retained",income_year:2025,filing:"aksjonærregisteroppgaven",status:"ready",preview:"RETAINED_RF_PREVIEW",issues:[]};
  const input={company:{id:"fixture-company",name:"Fixture"},incomeYear:2025,setups:[],overrides:[],filingSubmissions:[],filingPreviews:retained?[preview]:[]};
  const data={corporateDecisions:[],corporateDocumentSets:[],primaryBillingEntitlements:{},filingApprovalSnapshots:[],productionFilingSubmissions:[],primaryReadinessSnapshots:[],comments:[],user:{id:"owner"}};
  const ui={Banner:props=>React.createElement("aside",{},props.children),EmptyState:()=>null,
    LinkButton:props=>React.createElement("a",{href:props.href},props.children),StatusBadge:props=>React.createElement("span",{},props.label),
    Stepper:()=>null,SubmitButton:props=>React.createElement("button",{},props.children)};
  const page=compile("(owner)/filing/[obligation]/page.tsx",{
    "next/link":props=>React.createElement("a",{href:props.href},props.children),
    "next/navigation":{notFound(){throw new Error("Not found");}},"../../../actions":{},"../../../components/ui":ui,
    "../../../lib/annual-readiness":{evaluateObligationReadiness:()=>({ready:!blocked,status:blocked?"blocked":"ready",warnings:[],hard_blocks:blocked?[{level:"block",code:"year_not_locked",message:"Inntektsåret er ikke låst ennå."}]:[]})},
    "../../../lib/copy":{ownerCopy},"../../../lib/rf1086-production-presentation":{selectLatestRf1086ProductionSubmission:()=>null,buildRf1086OwnerProductionPresentation:()=>({})},
    "../../../lib/supabase/server":{createSupabaseServerClient:async()=>({})},"../../../lib/workspace-data":{loadWorkspaceData:async()=>data},
    "../../connections/_presentation":{loadSystemUserRequestPresentations:async()=>{throw new Error("Unavailable");}},
    "../_readiness":{isFilingObligation:()=>true,buildReadinessInput:()=>input},
    "../_presentation":{buildOwnerFilingPresentation:()=>({filing:preview.filing,primarySubmission:null,submitted:false})},
    "../_submission-presentation":{},"../_tax-delivery":{},"../_accounts-delivery":{},
  }).default;
  return renderToStaticMarkup(await page({params:Promise.resolve({obligation:"aksjonaerregisteroppgaven"}),searchParams:Promise.resolve({})}));
}

test("a retained RF preview stays readable while the year-lock blocker keeps commands closed",async()=>{
  const html=await render({blocked:true});
  assert.match(html,/RETAINED_RF_PREVIEW/u);
  assert.match(html,/Inntektsåret er ikke låst ennå/u);
  assert.doesNotMatch(html,/Klar til innsending/u);
  assert.ok(!html.includes(f.preview.regenerateCta));
  assert.ok(!html.includes(f.confirm.cta));
});
test("a blocked RF case without a preview cannot generate one",async()=>{
  const html=await render({blocked:true,retained:false});
  assert.ok(!html.includes(f.preview.generateCta));
});
test("the existing regeneration control still requires clear prerequisites",async()=>{
  const html=await render({blocked:false});
  assert.match(html,/RETAINED_RF_PREVIEW/u);
  assert.ok(html.includes(f.preview.regenerateCta));
});
