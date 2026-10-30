import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import {createRequire} from "node:module";
import vm from "node:vm";
import test from "node:test";
import ts from "typescript";
import * as annual from "../app/lib/annual-data.ts";

const require=createRequire(import.meta.url);
function compile(path, dependencies) {
  const exports={};
  vm.runInNewContext(ts.transpileModule(readFileSync(new URL(`../app/${path}`,import.meta.url),"utf8"),{
    compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.ReactJSX},
  }).outputText,{exports,URL,URLSearchParams,Date,process:{env:{NODE_ENV:"production"}},require(name){
    if(name in dependencies)return dependencies[name];
    if(name==="node:crypto"||name==="react/jsx-runtime")return require(name);
    if(dependencies["*"])return dependencies["*"];
    throw new Error(`Unexpected dependency: ${name}`);
  }});
  return exports;
}

test("actual year-end action saves explicit attachment answers under the selected owner year",async()=>{
  for(const answer of [undefined,"none","required","forged"]){
    const writes=[];
    const table={select(){return this;},eq(){return this;},async maybeSingle(){return {data:null};},
      async upsert(value){writes.push(value);return {error:null};},async insert(){return {error:null};}};
    const dependencies={hasSupabaseEnv:()=>true,createSupabaseServerClient:async()=>({
      auth:{getUser:async()=>({data:{user:{id:"synthetic-owner"}}})},from:()=>table}),
      revalidatePath(){},redirect(url){throw new Error(`REDIRECT:${url}`);}};
    const actions=compile("actions.ts",{"./lib/annual-data":annual,
      "./lib/action-return":compile("lib/action-return.ts",{}),"*":dependencies});
    const form=new FormData();form.set("companyId","synthetic-company");form.set("incomeYear","2025");
    form.set("annualFullTimeEquivalents","0");form.set("bank_balance_confirmed","on");
    if(answer!==undefined)form.set("companyTaxAdditionalAttachments",answer);
    await assert.rejects(actions.saveYearEndInterview(form),/REDIRECT:/u);
    assert.equal(writes.length,1);
    assert.equal(writes[0].company_id,"synthetic-company");assert.equal(writes[0].income_year,2025);
    assert.equal(writes[0].answers.company_tax_additional_attachments,annual.taxAttachmentAnswer(answer));
    assert.equal(writes[0].answers.bank_balance_confirmed,true);
    assert.equal(writes[0].answers.authority_to_submit_confirmed,false);
  }
});

test("the real form defaults to unknown and preserves the chosen answer through each step",()=>{
  const React=require("react"),{renderToStaticMarkup}=require("react-dom/server");
  for(const saved of [undefined,"none","required"])for(const step of [0,1,2,3]){
    let stateIndex=0;
    const ui=compile("(owner)/year-end/YearEndInterview.tsx",{
      react:{...React,useMemo:fn=>fn(),useState(initial){
        const index=stateIndex++;return [index===3?step:typeof initial==="function"?initial():initial,()=>{}];}},
      "../../lib/annual-data":annual,"../../lib/copy":compile("lib/copy.ts",{"./launch-copy.ts":compile("lib/launch-copy.ts",{})}),
      "../../actions":{saveYearEndInterview(){}},"../../components/ui":{
        Banner:props=>React.createElement("aside",{},props.children),Stepper:()=>null,
        SubmitButton:props=>React.createElement("button",{},props.children)},
    });
    const html=renderToStaticMarkup(React.createElement(ui.YearEndInterview,{
      companyId:"synthetic-company",incomeYear:2025,initialFte:0,
      initialAnswers:saved?{company_tax_additional_attachments:saved}:null,registered:{},
    }));
    assert.match(html,new RegExp(`name="companyTaxAdditionalAttachments" value="${saved??"unknown"}"`,"u"));
    if(step===2){assert.match(html,/Krever skattemeldingen ekstra vedlegg/u);assert.match(html,/Ingen ekstra vedlegg/u);}
  }
});
