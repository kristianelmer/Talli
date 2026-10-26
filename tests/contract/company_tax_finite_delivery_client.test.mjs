import assert from "node:assert/strict";
import test from "node:test";
import {createTalliApiClient,TalliApiError} from "../../packages/talli-api-client/src/generated/client.ts";

const companyId="10000000-0000-4000-8000-000000000001";
const filingId="10000000-0000-4000-8000-000000000002";
const approvalId="10000000-0000-4000-8000-000000000003";
const scope={companyId,incomeYear:2025,filingId};
const review={...scope,draftSha256:"a".repeat(64),reviewSha256:"b".repeat(64)};
const advance={...scope,approvalSha256:"c".repeat(64)};
const progress={...scope,approvalId,approvalSha256:advance.approvalSha256,
  draftSha256:review.draftSha256,reviewSha256:review.reviewSha256,authorityMode:"finite_loopback_rehearsal",
  status:"reviewed",mutationKind:null,latestEventSha256:"d".repeat(64),recordedAt:"2026-10-26T12:00:00Z"};
const operations=[
  ["companyTaxApproveDeliveryDraft","delivery-reviews",review],
  ["companyTaxAdvanceDelivery","delivery-advances",advance],
  ["companyTaxReconcileDelivery","delivery-reconciliations",advance],
  ["companyTaxAdvanceDeliveryUpload","delivery-upload-advances",advance],
  ["companyTaxReconcileDeliveryUpload","delivery-upload-reconciliations",advance],
  ["companyTaxAdvanceDeliveryValidation","delivery-validation-advances",advance],
  ["companyTaxReconcileDeliveryValidation","delivery-validation-reconciliations",advance],
  ["companyTaxAdvanceDeliveryConfirmation","delivery-confirmation-advances",advance],
  ["companyTaxReconcileDeliveryConfirmation","delivery-confirmation-reconciliations",advance],
];

for(const [method,path,command] of operations) {
  const expected=method.endsWith("Confirmation")?{...progress,status:"uncertain",mutationKind:"prepare_confirmation"}:method.endsWith("Upload")?{...progress,status:"uncertain",mutationKind:"upload_envelope"}:method.endsWith("Validation")?{...progress,status:"uncertain",mutationKind:"start_validation"}:progress;
  test(`${method} sends only bound scope and immutable review identity`,async()=>{
    let called;const api=createTalliApiClient({baseUrl:"https://backend.example",fetch:async(url,request)=>{
      called={url,request};return Response.json(expected);
    }});
    assert.deepEqual(await api[method](command,{idempotencyKey:"one-command-key-v1",headers:{Authorization:"Bearer fixture"}}),expected);
    assert.equal(called.url,"https://backend.example/api/v1/company-tax/"+path);
    assert.equal(called.request.method,"POST");assert.deepEqual(JSON.parse(called.request.body),command);
    assert.equal(new Headers(called.request.headers).get("Idempotency-Key"),"one-command-key-v1");
    assert.equal(new Headers(called.request.headers).get("Authorization"),"Bearer fixture");
  });
  for(const [name,change] of [
    ["foreign company",{companyId:filingId}],["foreign year",{incomeYear:2026}],["foreign filing",{filingId:companyId}],
    ["production authority",{authorityMode:"production"}],["invented submission",{status:"submitted"}],
    ["raw credentials",{credential:"must-not-be-returned"}],["original XML",{envelopeXml:"private"}],
  ])test(`${method} rejects ${name}`,async()=>{
    const api=createTalliApiClient({baseUrl:"https://backend.example",fetch:async()=>Response.json({...expected,...change})});
    await assert.rejects(api[method](command,{idempotencyKey:"one-command-key-v1"}),error=>error instanceof TalliApiError&&error.status===502);
  });
}

for(const field of ["draftSha256","reviewSha256"])test(`approval receipt must match ${field}`,async()=>{
  const api=createTalliApiClient({baseUrl:"https://backend.example",fetch:async()=>Response.json({...progress,[field]:"f".repeat(64)})});
  await assert.rejects(api.companyTaxApproveDeliveryDraft(review,{idempotencyKey:"one-command-key-v1"}),error=>error instanceof TalliApiError&&error.status===502);
});
for(const method of ["companyTaxAdvanceDelivery","companyTaxReconcileDelivery","companyTaxAdvanceDeliveryUpload","companyTaxReconcileDeliveryUpload","companyTaxAdvanceDeliveryValidation","companyTaxReconcileDeliveryValidation","companyTaxAdvanceDeliveryConfirmation","companyTaxReconcileDeliveryConfirmation"])test(`${method} binds the original approval`,async()=>{
  const api=createTalliApiClient({baseUrl:"https://backend.example",fetch:async()=>Response.json({...progress,approvalSha256:"f".repeat(64)})});
  await assert.rejects(api[method](advance,{idempotencyKey:"one-command-key-v1"}),error=>error instanceof TalliApiError&&error.status===502);
});

test("uncertainty is returned unchanged without automatic retry or invented outcome",async()=>{
  let calls=0;const unknown={...progress,status:"uncertain",mutationKind:"create_instance"};
  const api=createTalliApiClient({baseUrl:"https://backend.example",fetch:async()=>{calls++;return Response.json(unknown);}});
  assert.deepEqual(await api.companyTaxAdvanceDelivery(advance,{idempotencyKey:"one-command-key-v1"}),unknown);
  assert.equal(calls,1);
});

for(const method of ["companyTaxAdvanceDeliveryUpload","companyTaxReconcileDeliveryUpload","companyTaxAdvanceDeliveryValidation","companyTaxReconcileDeliveryValidation","companyTaxAdvanceDeliveryConfirmation","companyTaxReconcileDeliveryConfirmation"])test(`${method} cannot return a different mutation kind`,async()=>{
  const api=createTalliApiClient({baseUrl:"https://backend.example",fetch:async()=>Response.json({...progress,status:"mutation_completed",mutationKind:"create_instance"})});
  await assert.rejects(api[method](advance,{idempotencyKey:"upload-kind-bound-v1"}),error=>error instanceof TalliApiError&&error.status===502);
});
