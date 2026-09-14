import assert from "node:assert/strict";
import { randomUUID } from "node:crypto";
import { readFile } from "node:fs/promises";
import test from "node:test";
import { createClient } from "@supabase/supabase-js";
import { chromium } from "playwright";
import { startTaxBrowserFixture } from "./support/tax-browser-fixture.mjs";
import { establishOwnerAal2 } from "./support/tax-browser-auth.mjs";
import { fixtureTableTransaction } from "./support/rf1086-fixture-access.mjs";
import { installBrowserEgressGuard } from "./fixtures/system-user-authority-mock.mjs";

// Exercise the real owner form/JWT/FastAPI/restricted SQL boundary using retained
// synthetic TT02 metadata. No signing or authority request is performed.
test("Accounts owner imports pending evidence, records controls and reads scoped source history", { timeout: 240_000 }, async t => {
  const fixture = await startTaxBrowserFixture({ incomeYear: 2025 });
  let browser;
  t.after(async () => { try { await browser?.close(); } finally { await fixture.close(); } });
  browser = await chromium.launch({ headless: true });
  const context = await browser.newContext(), blockedRequests = [];
  await installBrowserEgressGuard(context, { approvalEnabled: false, blockedRequests, mockBaseUrl: fixture.siteOrigin });
  const page = await context.newPage();
  page.setDefaultTimeout(25_000);
  await page.goto(fixture.siteOrigin + '/login');
  await page.getByRole('textbox', { name: 'E-post', exact: true }).fill(fixture.owner.email);
  await page.locator('input[name="password"]').fill(fixture.owner.password);
  await page.getByRole('button', { name: 'Logg inn', exact: true }).click();
  await page.waitForURL(url => url.pathname !== '/login');
  const archive = JSON.parse(await readFile(new URL('../architecture/evidence/issues/153/characterization/legacy-pure-characterization.json', import.meta.url), 'utf8'));
  const original = archive.evidenceCases.find(row => row.id === 'archived-tt02-pending').input.evidence;
  const evidence = JSON.parse(JSON.stringify(original).replaceAll(original.companyOrgNumber, fixture.orgNumber));
  const auth = createClient(process.env.SUPABASE_URL, process.env.SUPABASE_ANON_KEY, { auth: { autoRefreshToken: false, persistSession: false } });
  const signed = await auth.auth.signInWithPassword({ email: fixture.owner.email, password: fixture.owner.password });
  assert.ifError(signed.error);
  const unstepped = await fetch(fixture.backendOrigin + '/api/v1/annual-accounts/tt02-evidence-imports', {
    method: 'POST', headers: { authorization: `Bearer ${signed.data.session.access_token}`, 'content-type': 'application/json' },
    body: JSON.stringify({ companyId: fixture.companyId, evidenceJson: JSON.stringify(evidence), evidenceUrl: null }),
  });
  assert.equal(unstepped.status, 403, 'real AAL1 owner cannot import evidence');
  await establishOwnerAal2(page, fixture.siteOrigin);
  const imports = () => fixture.controls.filingCalls.filter(call => call.path === '/api/v1/annual-accounts/tt02-evidence-imports');
  async function importEvidence(value, invalid = false) {
    await page.goto(fixture.siteOrigin + '/workspace');
    const form = page.locator('form').filter({ has: page.getByRole('button', { name: 'Importer TT02-evidens', exact: true }) });
    await form.locator('input[type="file"]').setInputFiles({ name: 'synthetic-accounts-evidence.json', mimeType: 'application/json', buffer: Buffer.from(JSON.stringify(value)) });
    const before = imports().length;
    await form.getByRole('button', { name: 'Importer TT02-evidens', exact: true }).click();
    await poll(() => imports().length === before + 1);
    await page.waitForURL(url => url.pathname === '/workspace' && url.searchParams.has('error') === invalid);
  }
  await importEvidence({ ...evidence, companyOrgNumber: '000000153' }, true);
  assert.equal(imports().at(-1).status, 422);
  await importEvidence(evidence);
  assert.equal(imports().at(-1).status, 200);
  assert.ok(imports().at(-1).response.recordId);
  const accountsEvidence = page.locator('.readinessItem').filter({ has: page.getByText('Årsregnskap', { exact: true }) });
  await accountsEvidence.getByText('Test-evidens: Venter på klassifisering', { exact: true }).waitFor();
  await accountsEvidence.getByText(`Siste testref: tt02:${evidence.instance.id} (Venter på klassifisering)`, { exact: true }).waitFor();
  const permission = page.locator('form').filter({ has: page.getByRole('button', { name: 'Bekreft innsendingsrett', exact: true }) });
  await permission.locator('select[name="obligation"]').selectOption('aarsregnskap');
  await permission.getByRole('button', { name: 'Bekreft innsendingsrett', exact: true }).click();
  await poll(() => fixture.controls.filingCalls.some(call => call.path === '/api/v1/annual-accounts/permissions'));
  assert.equal(fixture.controls.filingCalls.find(call => call.path === '/api/v1/annual-accounts/permissions').status, 200);
  await page.goto(fixture.siteOrigin + '/workspace');
  const manual = page.locator('form').filter({ has: page.getByRole('button', { name: 'Lagre test-evidens', exact: true }) });
  await manual.locator('select[name="obligation"]').selectOption('aarsregnskap');
  await manual.locator('select[name="environment"]').selectOption('manual_evidence');
  await manual.locator('input[name="testReference"]').fill('synthetic-accounts-browser');
  await manual.locator('textarea[name="feedbackSummary"]').fill('Synthetic manual evidence remains pending.');
  await manual.getByRole('button', { name: 'Lagre test-evidens', exact: true }).click();
  await poll(() => fixture.controls.filingCalls.some(call => call.path === '/api/v1/annual-accounts/test-evidence'));
  assert.equal(fixture.controls.filingCalls.find(call => call.path === '/api/v1/annual-accounts/test-evidence').status, 200);
  const sourcePath = `/api/v1/annual-accounts/source-facts?companyId=${fixture.companyId}&incomeYear=2025`;
  const response = await fixture.accountsRequest(sourcePath);
  assert.equal(response.status, 200);
  const source = await response.json();
  assert.equal(source.historyCoverage.status, 'complete');
  assert.equal(source.historyCoverage.submissionCount, 0, 'Accounts evidence import retains its evidence-only behavior');
  assert.equal(source.readinessStatus, 'blocked');
  assert.deepEqual(source.hardBlocks, ['annual_accounts_production_disabled']);
  assert.deepEqual(source.productionAttempts, []);
  assert.equal((await fixture.accountsRequest(sourcePath.replace(fixture.companyId, randomUUID()))).status, 404);
  await fixtureTableTransaction(fixture.db, ['annual_accounts_filing.authority_test_runs', 'annual_accounts_filing.authority_permissions', 'annual_accounts_filing.filing_submissions', 'public.audit_events'], async () => {
    const count = async (table, extra = '') => (await fixture.db.query(`select count(*)::int count from ${table} where company_id=$1 ${extra}`, [fixture.companyId])).rows[0].count;
    assert.equal(await count('annual_accounts_filing.authority_test_runs'), 2);
    assert.equal(await count('annual_accounts_filing.authority_permissions'), 1);
    assert.equal(await count('annual_accounts_filing.filing_submissions'), 0);
    assert.equal(await count('public.audit_events', "and action='annual_accounts_tt02_evidence_imported'"), 1);
  });
  fixture.controls.failAccountsReads = true;
  await page.goto(fixture.siteOrigin + '/workspace');
  assert.ok(fixture.controls.accountsReadFailures.some(call => call.status === 503 && call.path.includes(fixture.companyId)));
  await page.getByRole('complementary', { name: 'Status', exact: true }).getByText('Feil', { exact: true }).waitFor();
  await accountsEvidence.getByText('Test-evidens: Test-evidens mangler', { exact: true }).waitFor();
  await accountsEvidence.getByText('Siste testref: Ingen', { exact: true }).waitFor();
  fixture.controls.failAccountsReads = false;
  await fixtureTableTransaction(fixture.db, ['public.company_memberships'], async () => {
    await fixture.db.query("update public.company_memberships set role='read_only' where company_id=$1 and user_id=$2", [fixture.companyId, fixture.owner.id]);
  });
  try {
    assert.equal((await fixture.accountsRequest(sourcePath)).status, 404, 'retained JWT cannot bypass current owner authorization');
  } finally {
    await fixtureTableTransaction(fixture.db, ['public.company_memberships'], async () => {
      await fixture.db.query("update public.company_memberships set role='owner' where company_id=$1 and user_id=$2", [fixture.companyId, fixture.owner.id]);
    });
  }
  assert.deepEqual(blockedRequests, []);
});

async function poll(condition) {
  const deadline = Date.now() + 25_000;
  while (!condition()) {
    assert.ok(Date.now() < deadline, 'fixture condition timed out');
    await new Promise(resolve => setTimeout(resolve, 25));
  }
}
