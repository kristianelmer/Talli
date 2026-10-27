/** Initial synthetic facts only; Corporate lifecycle must use actual owner APIs. */
import assert from "node:assert/strict";
import {randomUUID} from "node:crypto";
import {fixtureTableTransaction} from "./rf1086-fixture-access.mjs";
import {createClient} from "@supabase/supabase-js";

export async function seedAccountsOpening(database,companyId,ownerId) {
  assert.ok((await database.query('select 1 from public.company_memberships where company_id=$1 and user_id=$2 and role=$3 and accepted_at is not null',
    [companyId,ownerId,'owner'])).rowCount===1);
  const setup=randomUUID(),shareholder=randomUUID(),entry=randomUUID();
  await fixtureTableTransaction(database,['shareholder_register_filing.opening_balance_setups','shareholder_register_filing.opening_shareholders','ledger.opening_bank_inputs','ledger.entries'],async()=>{
    await database.query('insert into shareholder_register_filing.opening_balance_setups(id,company_id,income_year,share_capital,share_count,nominal_value,created_by) values($1,$2,2025,30000,30,1000,$3)',[setup,companyId,ownerId]);
    await database.query('insert into ledger.opening_bank_inputs(snapshot_id,company_id,income_year,bank_balance_nok,recorded_by,recorded_at) select id,company_id,income_year,30000,created_by,created_at from shareholder_register_filing.opening_balance_setups where id=$1',[setup]);
    await database.query('insert into shareholder_register_filing.opening_shareholders(id,setup_id,company_id,name,shareholder_kind,org_number,share_count,created_by) values($1,$2,$3,$4,$5,$6,30,$7)',
      [shareholder,setup,companyId,'Synthetic Holder AS','norwegian_company','930835978',ownerId]);
    const lines=[{account:'1920',description:'Synthetic bank',debit:'30000.00',credit:'0.00',currency:'NOK'},
      {account:'2000',description:'Synthetic share capital',debit:'0.00',credit:'30000.00',currency:'NOK'}];
    await database.query('insert into ledger.entries(id,company_id,income_year,entry_kind,memo,lines,created_by,source_capability,source_record_id,correlation_id) values($1,$2,2025,$3,$4,$5::jsonb,$6,$7,$8,$9)',
      [entry,companyId,'OPENING_BALANCE','Synthetic historical opening',JSON.stringify(lines),ownerId,'LEDGER',setup,'accounts-owned-initial-opening']);
  });
  return {setup,shareholder,entry};
}

export async function completeAccountsCorporateAnnualClose(fixture) {
  const call=async(path,body)=>{
    const response=await fixture.governanceRequest(path,body===undefined?{}:{method:'POST',
      headers:{'Content-Type':'application/json','Idempotency-Key':randomUUID()},body:JSON.stringify(body)});
    assert.ok(response.ok,`Corporate owning step ${path}: ${response.status} ${await response.clone().text()}`);
    return response.json();
  };
  const facts=await call('/api/v1/corporate-governance/decision-facts?'+new URLSearchParams({companyId:fixture.companyId,incomeYear:'2025',decisionKind:'annual_close'}));
  const decisionId=randomUUID(),documentSetId=randomUUID();
  const proposal=await call('/api/v1/corporate-governance/annual-closes/proposals',{companyId:fixture.companyId,incomeYear:2025,
    decisionId,documentSetId,...facts,
    boardMeeting:{meetingDate:'2026-05-10',meetingTime:'09:00:00',place:'Synthetic Oslo',treatmentMethod:'physical'},
    boardParticipants:[{participantId:'synthetic-board-chair',name:'Synthetic Chair',role:'chair',order:0}],
    generalMeeting:{meetingDate:'2026-05-10',meetingTime:'10:00:00',place:'Synthetic Oslo',meetingForm:'physical',chairName:'Synthetic Chair',coSignerName:'Synthetic Co-signer'},
    shareholderBallots:facts.shareholders.map(holder=>({shareholderId:holder.shareholderId,representedShareCount:holder.shareCount,vote:'for'})),
    oneShareClassConfirmed:true,fullBoardParticipationConfirmed:true,unanimousBoardConfirmed:true,supportedDividendBasisConfirmed:true,
    prudentEquityAndLiquidityConfirmed:true,annualResultAllocationOre:facts.annualBasis.resultAfterTaxOre});
  const decisionHash=proposal.decision.decisionHash;const scope={companyId:fixture.companyId,documentSetId,decisionHash};
  const storage=createClient(process.env.SUPABASE_URL,process.env.SUPABASE_ANON_KEY,{auth:{autoRefreshToken:false,persistSession:false}});
  async function document(artifact,status) {
    const documentId=randomUUID(),bytes=Buffer.from(artifact.contentBase64,'base64');
    const transfer=await call('/api/v1/documents/uploads',{companyId:fixture.companyId,incomeYear:2025,documentId,
      documentType:'corporate_document',linkedTo:'corporate_decision:'+decisionId,fileName:artifact.filename,
      contentType:'application/pdf',byteLength:bytes.length,headerBase64:bytes.subarray(0,5).toString('base64'),finalStatus:status});
    assert.ifError((await storage.storage.from(transfer.bucket).uploadToSignedUrl(transfer.storageKey,transfer.token,bytes,{contentType:'application/pdf'})).error);
    const result=await call('/api/v1/documents/'+documentId+'/finalize',{});
    assert.equal(result.contentSha256,artifact.contentSha256);assert.equal(result.byteLength,bytes.length);
    return {artifactId:randomUUID(),documentId,artifactKind:artifact.artifactKind,contentSha256:result.contentSha256,byteLength:bytes.length};
  }
  const artifacts=[];
  for(const artifact of proposal.artifacts)artifacts.push(await document(artifact,'generated_unsigned'));
  await call('/api/v1/corporate-governance/annual-closes/'+decisionId+'/documents',{...scope,artifacts});
  const approved=await call('/api/v1/corporate-governance/annual-closes/'+decisionId+'/approvals',{...scope,approvalEventId:randomUUID()});
  assert.equal(approved.state,'facts_approved');
  const requested=await call('/api/v1/corporate-governance/annual-closes/'+decisionId+'/events',{...scope,eventId:randomUUID(),eventKind:'signing_requested',metadata:{source:'synthetic_actual_corporate_2025_owner_workflow'}});
  assert.equal(requested.state,'signing_requested');
  for(const [index,artifact] of proposal.artifacts.entries()) {
    const signed=await document(artifact,'signed_owner_attested');
    const unsigned=artifacts.find(item=>item.artifactKind===artifact.artifactKind);
    const result=await call('/api/v1/corporate-governance/annual-closes/'+decisionId+'/signed-artifacts',{...scope,
      unsignedArtifactId:unsigned.artifactId,signedArtifactId:signed.artifactId,signedDocumentId:signed.documentId,
      artifactKind:artifact.artifactKind,filename:artifact.filename,contentSha256:signed.contentSha256,byteLength:signed.byteLength});
    assert.equal(result.signedArtifactHashes[artifact.artifactKind],signed.contentSha256);
    assert.equal(Object.keys(result.signedArtifactHashes).length,index+1);
    assert.equal(result.state,index===proposal.artifacts.length-1?'signed_owner_attested':'signing_requested');
  }
  const finalizationId=randomUUID();
  const final=await call('/api/v1/corporate-governance/annual-closes/'+decisionId+'/finalizations',{...scope,finalizationId});
  assert.equal(final.state,'finalized');assert.equal(final.finalizationId,finalizationId);
  const readiness=await call('/api/v1/corporate-governance/readiness?'+new URLSearchParams({companyId:fixture.companyId,incomeYear:'2025',decisionKind:'annual_close'}));
  assert.equal(readiness.finalizationId,finalizationId);assert.equal(readiness.finalized,true);assert.equal(readiness.currentSourceMatches,true);
  const retained=await call('/api/v1/corporate-governance/decisions/'+decisionId);
  assert.equal(retained.decisions[0].companyId,fixture.companyId);
  assert.equal(retained.decisions[0].canonicalInput.generalMeeting.meetingDate,'2026-05-10');
  return {decisionId,decisionHash,documentSetId,finalizationId,readiness};
}
