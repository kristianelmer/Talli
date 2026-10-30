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
