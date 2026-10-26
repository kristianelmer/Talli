import assert from "node:assert/strict";
import { EventEmitter,getEventListeners } from "node:events";
import test from "node:test";
import { waitForRfMutationCheckpoint as wait } from "./support/rf1086-crash-checkpoint.mjs";
const deferred=()=>{let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b;});return{promise,resolve,reject};};
const flush=()=>new Promise(resolve=>setImmediate(resolve));
const expectedURL="http://127.0.0.1:3201/api/v1/shareholder-register-filings/source-production-filings";
const request=(extra={})=>({url:()=>expectedURL,method:()=>"POST",postDataJSON:()=>({approvalId:"owned-approval",manifestSha256:"a".repeat(64)}),...extra});
const matcher=r=>r.url()===expectedURL&&r.method()==="POST"&&r.postDataJSON().approvalId==="owned-approval"&&r.postDataJSON().manifestSha256==="a".repeat(64);
function clean(page,signal,baseline=0){
 assert.equal(page.listenerCount("request"),baseline);
 assert.equal(page.listenerCount("requestfinished"),0);assert.equal(page.listenerCount("requestfailed"),0);
 assert.equal(getEventListeners(signal,"abort").length,0);
}

test("late checkpoint defeats the old 10s guess; matched start clears 30s and success awaits trigger too",async t=>{
 t.mock.timers.enable({apis:["setTimeout"]});
 const old=deferred();let oldTimer;
 const oldRace=Promise.race([old.promise,new Promise((_,reject)=>{oldTimer=setTimeout(()=>reject(new Error("mock_mutation_hold_deadline_exceeded")),10000);})]);
 const oldRed=assert.rejects(oldRace,{message:"mock_mutation_hold_deadline_exceeded"});
 const page=new EventEmitter(),parent=new AbortController(),checkpoint=deferred(),click=deferred(),owned=request();
 const foreign=request({postDataJSON:()=>({approvalId:"foreign",manifestSha256:"a".repeat(64)})});
 const background=()=>{};page.on("request",background);
 let done=false,triggerCount=0;
 const pending=wait({page,checkpoint:checkpoint.promise,signal:parent.signal,matchesRequest:matcher,
  trigger:()=>{triggerCount++;assert.equal(page.listenerCount("request"),2);assert.equal(page.listenerCount("requestfinished"),1);assert.equal(page.listenerCount("requestfailed"),1);
   page.emit("request",foreign);page.emit("requestfinished",foreign);page.emit("request",owned);return click.promise;}});
 void pending.then(()=>{done=true;},()=>{});
 await flush();t.mock.timers.tick(10000);await oldRed;assert.equal(done,false);
 t.mock.timers.tick(21000);await flush();assert.equal(done,false,"no renewed fixed hold timer after matched request");
 old.resolve();checkpoint.resolve();await flush();assert.equal(done,false,"checkpoint alone must not bypass click completion");
 page.emit("requestfinished",owned);click.resolve();const result=await pending;
 assert.equal(result.request,owned);assert.equal(result.checkpointReached,true);assert.equal(triggerCount,1);
 clean(page,parent.signal,1);page.off("request",background);clearTimeout(oldTimer);
});

test("exact tracked terminal rejects early; foreign terminals ignored; early checkpoint refuses before trigger",async t=>{
 t.mock.timers.enable({apis:["setTimeout"]});
 for(const event of ["requestfinished","requestfailed"]){
  const page=new EventEmitter(),parent=new AbortController(),checkpoint=deferred(),click=deferred(),owned=request();
  const pending=wait({page,checkpoint:checkpoint.promise,signal:parent.signal,matchesRequest:matcher,
   trigger:()=>{page.emit("request",owned);return click.promise;}});
  const rejection=assert.rejects(pending,{code:event==="requestfinished"?"rf_checkpoint_request_finished_before_checkpoint":"rf_checkpoint_request_failed_before_checkpoint"});
  await flush();page.emit(event,request());await flush();page.emit(event,owned);checkpoint.resolve();await rejection;
  clean(page,parent.signal);click.reject(new Error("late click failure is observed"));await flush();
 }
 const page=new EventEmitter(),parent=new AbortController();let clicked=false;
 await assert.rejects(wait({page,signal:parent.signal,checkpoint:Promise.resolve(),matchesRequest:matcher,trigger:()=>{clicked=true;}}),{code:"rf_checkpoint_before_matching_request"});
 assert.equal(clicked,false);clean(page,parent.signal);
});

test("never-started exact request is bounded by the existing 30s UI start timer",async t=>{
 t.mock.timers.enable({apis:["setTimeout"]});
 const page=new EventEmitter(),parent=new AbortController(),checkpoint=deferred();let settled=false;
 const pending=wait({page,checkpoint:checkpoint.promise,signal:parent.signal,matchesRequest:matcher,trigger:()=>{
  page.emit("request",request({method:()=>"GET"}));
  page.emit("request",request({postDataJSON:()=>({approvalId:"foreign",manifestSha256:"a".repeat(64)})}));
  page.emit("request",request({postDataJSON:()=>({approvalId:"owned-approval",manifestSha256:"b".repeat(64)})}));
 }});
 const rejection=assert.rejects(pending,{code:"rf_checkpoint_request_start_timeout"}).then(()=>{settled=true;});
 await flush();t.mock.timers.tick(29999);await flush();assert.equal(settled,false);
 t.mock.timers.tick(1);await rejection;clean(page,parent.signal);
 checkpoint.reject(new Error("late checkpoint rejection is consumed"));await flush();
});

test("parent abort cleans every listener/timer before start, after start and while trigger remains pending",async t=>{
 t.mock.timers.enable({apis:["setTimeout"]});
 for(const phase of ["preaborted","started","checkpoint"]){
  const page=new EventEmitter(),parent=new AbortController(),checkpoint=deferred(),click=deferred();let clicked=false;
  if(phase==="preaborted")parent.abort(new Error("private parent reason is not exposed"));
  const pending=wait({page,checkpoint:checkpoint.promise,signal:parent.signal,matchesRequest:matcher,trigger:()=>{
   clicked=true;page.emit("request",request());return click.promise;}});
  const rejection=assert.rejects(pending,error=>error.name==="AbortError"&&error.code==="rf_checkpoint_parent_aborted"&&error.message==="rf_checkpoint_parent_aborted");
  await flush();if(phase==="checkpoint"){checkpoint.resolve();await flush();}
  parent.abort();await rejection;clean(page,parent.signal);assert.equal(clicked,phase!=="preaborted");
  click.reject(new Error("late trigger rejection is consumed"));
  // No trigger is called for preaborted, so this test owns that unused promise.
  if(phase==="preaborted")void click.promise.catch(()=>{});
  checkpoint.reject(new Error("late checkpoint rejection is consumed"));
  t.mock.timers.tick(360000);await flush();clean(page,parent.signal);
 }
});
