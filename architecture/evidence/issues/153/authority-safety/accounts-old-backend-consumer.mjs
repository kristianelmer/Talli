import assert from 'node:assert/strict';
const t=await import("file:///Users/kristianelmer/.codex/worktrees/d060/Holding%20accounting/apps/web/features/annual-accounts-filing/transport.ts");const {loadPresentedAnnualAccountsSource}=await import("file:///Users/kristianelmer/.codex/worktrees/d060/Holding%20accounting/apps/web/app/lib/annual-accounts-workspace-source.ts");
const company='15300000-0000-4000-8000-000000000001';
const calls=[()=>t.loadAnnualAccountsFilingWorkspace('fixture',company,2025),
()=>t.loadAnnualAccountsSourceFacts('fixture',company,2025),
()=>t.importAnnualAccountsTt02Evidence('fixture',{companyId:company,evidenceJson:'{}',evidenceUrl:null}),
()=>t.findAnnualAccountsPreview('fixture',company),
()=>t.acknowledgeOwnedAnnualAccountsComment('fixture',company)];
for (const call of calls) {
 let failure;try {await call();} catch(error) {failure=error;}
 assert.ok(failure,'missing route cannot become a successful empty result');assert.equal(failure.status,404);
 assert.equal(t.annualAccountsEvidenceImportErrorMessage(failure),'TT02-evidensen kunne ikke lagres.');
 assert.equal(t.annualAccountsActionErrorMessage(failure),'Årsregnskapet kunne ikke oppdateres. Prøv igjen.');
}
const result=await loadPresentedAnnualAccountsSource('fixture',[company],2025);
assert.equal(result.error,'Årsregnskapsgrunnlaget kunne ikke leses. Prøv igjen.');
assert.deepEqual(result.submissions,[]);console.log('PASS five real predecessor HTTP 404 rejections and unavailable workspace composition');
