import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import test from "node:test";
import vm from "node:vm";
import ts from "typescript";

const companyId='10000000-0000-4000-8000-000000000001',filingId='10000000-0000-4000-8000-000000000002';
const source=readFileSync(new URL('../app/(owner)/filing/_tax-delivery-actions.ts',import.meta.url),'utf8');
const code=ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText;
class Redirect extends Error {}
function harness({token='actual-session',actions=['submit'],review='a'.repeat(64)}={}){
  const effects=[],exports={};
  const dependencies={getCurrentSessionAccessToken:async()=>token,redirect:url=>{throw new Redirect(url);},revalidatePath:path=>effects.push(['revalidate',path]),
    loadTaxDeliveryWorkspace:async()=>({companyId,incomeYear:2025,preparationAvailable:false,rows:[{filingId,actions,approvalSha256:'b'.repeat(64)}]}),
    loadTaxDeliveryOwnerReview:async()=>({artifactSha256:review}),
    confirmTaxDeliverySubmission:async(...args)=>effects.push(['submit',...args]),
    advanceTaxDeliveryAction:async(...args)=>effects.push(['advance',...args]),companyTaxActionErrorMessage:()=> 'safe error'};
  vm.runInNewContext(code,{exports,require:()=>dependencies,FormData,Number,String,Error});
  const form=new FormData();for(const[key,value]of Object.entries({companyId,incomeYear:'2025',filingId,deliveryAction:'submit',
    ownerReviewSha256:'a'.repeat(64),documentsConfirmed:'on',warningsAcknowledged:'on'}))form.set(key,value);
  return {effects,form,action:exports.taxDeliveryOwnerAction};
}
const redirect=promise=>assert.rejects(promise,Redirect);

for(const name of ['documentsConfirmed','warningsAcknowledged'])test(`owner form cannot send without explicit ${name}`,async()=>{
  const h=harness();h.form.delete(name);await redirect(h.action(h.form));assert.deepEqual(h.effects,[]);
});
test('owner form rereads advertised actions and complete review commitment before sending',async()=>{
  for(const options of [{token:null},{actions:['reconcile_submission']},{review:'c'.repeat(64)}]){
    const h=harness(options);await redirect(h.action(h.form));assert.deepEqual(h.effects,[]);
  }
  const h=harness();await redirect(h.action(h.form));assert.equal(h.effects[0][0],'submit');
  const [kind,token,command,key]=h.effects[0];assert.equal(token,'actual-session');
  assert.deepEqual(JSON.parse(JSON.stringify(command)),{companyId,incomeYear:2025,filingId,approvalSha256:'b'.repeat(64),
    ownerReviewSha256:'a'.repeat(64),documentsConfirmed:true,warningsAcknowledged:true});
  assert.equal(key,'tax-delivery-'+filingId+'-submit');
});
test('unknown submission offers only the advertised read recovery even if hidden action is changed',async()=>{
  const h=harness({actions:['reconcile_submission']});h.form.set('deliveryAction','create');
  await redirect(h.action(h.form));assert.deepEqual(h.effects,[]);
  h.form.set('deliveryAction','reconcile_submission');await redirect(h.action(h.form));
  assert.equal(h.effects[0][0],'advance');assert.equal(h.effects[0][2],'reconcile_submission');
});
