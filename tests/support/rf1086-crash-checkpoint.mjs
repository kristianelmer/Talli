/** Test-only correlated crash checkpoint. No browser/process/provider dependencies. */
export class RfMutationCheckpointError extends Error {
  constructor(code) { super(code); this.name = code === "rf_checkpoint_parent_aborted" ? "AbortError" : "RfMutationCheckpointError"; this.code = code; }
}
export async function waitForRfMutationCheckpoint({page,checkpoint,trigger,matchesRequest,signal,startTimeoutMs=30000}) {
  if (!page || typeof page.on !== "function" || typeof page.off !== "function"
      || typeof trigger !== "function" || typeof matchesRequest !== "function"
      || !(signal instanceof AbortSignal) || !Number.isInteger(startTimeoutMs)
      || startTimeoutMs < 1 || startTimeoutMs > 30000) {
    throw new RfMutationCheckpointError("rf_checkpoint_invalid_arguments");
  }
  let tracked, requestStartObserved=false, checkpointSeen=false, closed=false, failure, timer;
  let resolveGate,rejectFailure;
  const gate=new Promise(resolve=>{resolveGate=resolve;});
  const failed=new Promise((_,reject)=>{rejectFailure=reject;});
  const fail=code=>{if(!closed&&!failure){failure=new RfMutationCheckpointError(code);rejectFailure(failure);}};
  const onRequest=request=>{
    if(closed||failure||tracked)return;
    let matches;
    try { matches=matchesRequest(request); }
    catch { fail("rf_checkpoint_request_matcher_failed"); return; }
    if(matches!==true)return; // matcher must be synchronous and fail closed.
    tracked=request;
    clearTimeout(timer); timer=undefined;
    // Preserve observable ordering even when fake transports emit both in one
    // stack. A checkpoint already queued BEFORE this request cannot qualify it.
    queueMicrotask(()=>{if(!closed&&!failure)requestStartObserved=true;});
  };
  const terminal=(request,code)=>{
    if(closed||failure||request!==tracked)return;
    // An already-arrived checkpoint's observer runs first; a genuinely earlier
    // terminal rejects even if checkpoint resolves later in this same stack.
    queueMicrotask(()=>{if(!checkpointSeen)fail(code);});
  };
  const onFinished=request=>terminal(request,"rf_checkpoint_request_finished_before_checkpoint");
  const onFailed=request=>terminal(request,"rf_checkpoint_request_failed_before_checkpoint");
  const onAbort=()=>fail("rf_checkpoint_parent_aborted");
  // Attach rejection handling immediately; late checkpoint rejection remains
  // consumed after another path has rejected/cleaned up. No request/body logging.
  void Promise.resolve(checkpoint).then(()=>{
    if(closed||failure)return;
    if(!tracked||!requestStartObserved){fail("rf_checkpoint_before_matching_request");return;}
    checkpointSeen=true;resolveGate();
  },()=>fail("rf_checkpoint_rejected"));
  try {
    page.on("request",onRequest);
    page.on("requestfinished",onFinished);
    page.on("requestfailed",onFailed);
    signal.addEventListener("abort",onAbort,{once:true});
    if(signal.aborted)onAbort();
    else timer=setTimeout(()=>fail("rf_checkpoint_request_start_timeout"),startTimeoutMs);
    // The microtask lets an already-settled checkpoint refuse BEFORE trigger.
    // Promise.all observes both; the separate failure channel can still abort
    // after checkpoint while the trigger is pending, without losing late errors.
    const triggerWork=Promise.resolve().then(()=>{
      if(failure||closed)return;
      return trigger();
    });
    await Promise.race([Promise.all([triggerWork,gate]),failed]);
    return {request:tracked,checkpointReached:true};
  } finally {
    closed=true;
    clearTimeout(timer);
    page.off("request",onRequest);
    page.off("requestfinished",onFinished);
    page.off("requestfailed",onFailed);
    signal.removeEventListener("abort",onAbort);
  }
}
