import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import test from "node:test";
import vm from "node:vm";
import React from "react";
import * as jsx from "react/jsx-runtime";
import {renderToStaticMarkup} from "react-dom/server";
import ts from "typescript";

test('a later smaller document keeps every field visible even with a retained second-page cursor',()=>{
  const source=readFileSync(new URL('../app/(owner)/filing/_tax-delivery-fields.tsx',import.meta.url),'utf8');
  const code=ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022,jsx:ts.JsxEmit.ReactJSX}}).outputText;
  const exports={};
  vm.runInNewContext(code,{exports,Math,require:name=>{
    if(name==='react')return {...React,useState:()=>[1,()=>{}]};
    if(name==='react/jsx-runtime')return jsx;
    if(name.endsWith('.css'))return {default:{fields:'fields',pagination:'pagination'}};
    return {Button:({children,...props})=>React.createElement('button',props,children)};
  }});
  const large=Array.from({length:80},(_,index)=>({path:'/field['+index+']',value:String(index)}));
  const render=fields=>renderToStaticMarkup(React.createElement(exports.TaxDeliveryFields,{label:'Beregning',fields}));
  assert.match(render(large),/41–80 av 80 felt/u);
  const smaller=render([{path:'/latest',value:'latest-value'},{path:'/second',value:'second-value'}]);
  assert.match(smaller,/1–2 av 2 felt/u);assert.match(smaller,/latest-value/u);assert.match(smaller,/second-value/u);
  assert.doesNotMatch(smaller,/Neste felt/u);
});

test('retained Tax drafts expose the same scoped company archive after preparation expires',async()=>{
  const companyId='53454096-3fb6-45a6-a9c8-35fa83824614';
  for(const populated of [false,true])for(const mode of ['private_preview_preparation','unavailable']){
    const workspace={companyId,incomeYear:2025,technicalMode:mode,preparationAvailable:!populated&&mode!=='unavailable',rows:populated?[{
      filingId:'00000000-0000-4000-8000-000000000001',state:'prepared',sourceCurrent:true,fields:[],actions:[],originals:[],validation:null,
    }]:[]};
    const exports={};
    const code=ts.transpileModule(readFileSync(new URL('../app/(owner)/filing/_tax-delivery.tsx',import.meta.url),'utf8'),{
      compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022,jsx:ts.JsxEmit.ReactJSX},
    }).outputText;
    vm.runInNewContext(code,{exports,URLSearchParams,require:name=>{
      if(name==='react/jsx-runtime')return jsx;
      if(name==='node:crypto')return {randomUUID:()=> '00000000-0000-4000-8000-000000000002'};
      if(name.endsWith('.css'))return {default:{}};
      if(name.endsWith('/ui'))return {
        Banner:props=>React.createElement('aside',{},props.children),
        SubmitButton:props=>React.createElement('button',{},props.children),
        LinkButton:props=>React.createElement('a',{href:props.href},props.children),
      };
      if(name.endsWith('/auth-session'))return {getCurrentSessionAccessToken:async()=> 'synthetic-token'};
      if(name.endsWith('/company-tax-filing'))return {loadTaxDeliveryWorkspace:async(_token,company,year)=>{
        assert.equal(company,companyId);assert.equal(year,2025);return workspace;
      }};
      if(name==='./_tax-delivery-actions')return {taxDeliveryOwnerAction(){}};
      if(name==='./_tax-delivery-fields')return {TaxDeliveryFields:()=>null};
      throw new Error('Unexpected dependency: '+name);
    }});
    const html=renderToStaticMarkup(await exports.TaxDeliveryPanel({companyId,incomeYear:2025}));
    if(populated)assert.match(html,new RegExp(`href="/archive/${companyId}/2025/download"`, 'u'));
    else assert.doesNotMatch(html,/Eksporter selskapsarkiv/u);
    assert.doesNotMatch(html,/Bekreft og send|Opprett levering/u);
    if(mode==='private_preview_preparation')assert.match(html,/Referansen er syntetisk/u);
  }
});
