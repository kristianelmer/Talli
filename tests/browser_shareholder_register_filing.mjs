import assert from "node:assert/strict";
import { createHash, createHmac, generateKeyPairSync, randomInt, randomUUID } from "node:crypto";
import { existsSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";

import { createClient } from "@supabase/supabase-js";
import { chromium } from "playwright";
import pg from "pg";

import { createTalliApiClient } from "../packages/talli-api-client/src/index.ts";
import { currentCustomerAgreements } from "../apps/web/app/lib/customer-agreements.ts";
import { SYSTEM_USER_COOKIE } from "../apps/web/app/lib/system-user-presentation.ts";
import { installBrowserEgressGuard } from "./fixtures/system-user-authority-mock.mjs";
import { allocateLoopbackPort, ownedProcessDiagnostics, startOwnedProcess, stopOwnedProcess, waitForOwnedReadiness } from "./support/owned-process-lifecycle.mjs";
import { isLoopbackPostgresUrl, isLoopbackSupabaseUrl } from "./support/supabase_fixture_safety.mjs";
import { fixtureTableTransaction, deleteRfFixtureCompanies } from "./support/rf1086-fixture-access.mjs";

import { startRf1086FilingAuthorityMock } from "./fixtures/rf1086-filing-authority-mock.mjs";

const nextCli = createRequire(new URL("../apps/web/package.json", import.meta.url)).resolve("next/dist/bin/next");
const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL || process.env.SUPABASE_URL;
const anonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY || process.env.SUPABASE_ANON_KEY;
const serviceRoleKey = process.env.SUPABASE_SERVICE_ROLE_KEY;
const databaseUrl = process.env.DATABASE_URL;

// This is a mandatory local lane: absent or non-loopback configuration fails;
// it never converts the full-stack authority journey into a skipped test.
test("owner completes fresh RF preview, review, approval, send and private feedback through the canonical backend", {
  timeout: 300_000,
}, async (t) => {
  assert.ok(supabaseUrl && anonKey && serviceRoleKey && databaseUrl, "authority browser requires isolated Supabase configuration");
  assert.ok(isLoopbackSupabaseUrl(supabaseUrl) && isLoopbackPostgresUrl(databaseUrl), "authority browser fixtures require loopback");
  assert.notEqual(process.env.TALLI_AUTHORITY_OPS_ENABLED, "true");
  assert.notEqual(process.env.TALLI_RF1086_PRODUCTION_ENABLED, "true");
  const admin = createClient(supabaseUrl, serviceRoleKey, { auth: { autoRefreshToken: false, persistSession: false } });
  const database = new pg.Client({ connectionString: databaseUrl });
  const resources = { connected: false, users: [], companies: [], roles: [], backend: null, web: null, browser: null, mock: null };
  const health = [];
  const egressViolations = [];
  const apiCalls = [];
  let primaryFailure;
  t.after(async () => {
    const cleanupErrors = [];
    const attempt = async (operation) => { try { await operation(); } catch (error) { cleanupErrors.push(error); } };
    await attempt(() => resources.browser?.close());
    await attempt(() => stopOwnedProcess(resources.web));
    await attempt(() => stopOwnedProcess(resources.backend));
    await attempt(() => resources.mock?.close());
    if (resources.connected) {
      for (const role of resources.roles) await attempt(() => database.query(`alter role ${role} nologin password null`));
      await attempt(async () => {
        const objects = await rfFixtureTransaction(database, () => database.query("select d.storage_key from public.documents d join shareholder_register_filing.production_feedback_artifacts a on a.document_id=d.id where a.company_id=any($1::uuid[])", [resources.companies]));
        if (objects.rows.length) assert.ifError((await admin.storage.from("company-documents").remove(objects.rows.map(({ storage_key }) => storage_key))).error);
      });
      await attempt(() => restoreLocalReleaseSignoffs(database, resources.signoffs));
      await attempt(() => cleanupFixture(database, resources.companies, resources.users));
      for (const userId of resources.users) await attempt(async () => {
        const { error } = await admin.auth.admin.deleteUser(userId);
        assert.ifError(error);
      });
      await attempt(async () => {
        const residue = await authorityFixtureTransaction(database, () => database.query(`select
          (select count(*)::int from authority_connections.system_user_requests where company_id=any($1::uuid[])) requests,
          (select count(*)::int from authority_connections.authority_operations where actor_id=any($2::uuid[])) operations`, [resources.companies, resources.users]));
        await rfFixtureTransaction(database, async () => {
          for (const table of RF_TABLES) {
            if (table === "production_filing_events") continue;
            const count = (await database.query(`select count(*)::int count from shareholder_register_filing.${table} where company_id=any($1::uuid[])`, [resources.companies])).rows[0];
            assert.equal(count.count, 0, `RF fixture residue in ${table}`);
          }
          assert.equal((await database.query("select count(*)::int count from ledger.opening_bank_inputs where company_id=any($1::uuid[])", [resources.companies])).rows[0].count, 0);
        });
        const identities = await database.query(`select
          (select count(*)::int from public.companies where id=any($1::uuid[])) companies,
          (select count(*)::int from auth.users where id=any($2::uuid[])) users`, [resources.companies, resources.users]);
        assert.deepEqual({ ...residue.rows[0], ...identities.rows[0] }, { companies: 0, requests: 0, operations: 0, users: 0 });
      });
      await attempt(() => database.end());
    }
    if (cleanupErrors.length) throw new AggregateError([...(primaryFailure ? [primaryFailure] : []), ...cleanupErrors], "authority_browser_teardown_failed");
  });

  try {
    await database.connect();
    resources.connected = true;
    const owner = await createUser(admin, "authority-owner", resources.users);
    const other = await createUser(admin, "authority-other", resources.users);

    const primary = await seedCompany(admin, database, owner.id, "Synthetic Authority Holding", resources.companies);
    const otherCompany = await seedCompany(admin, database, other.id, "Synthetic Other Owner", resources.companies);
    await seedFreshBasis(database, primary.id, owner.id);
    await seedFreshBasis(database, otherCompany.id, other.id);
    assert.ifError((await admin.from("support_operators").insert([{ user_id: owner.id, role: "admin", active: true }, { user_id: other.id, role: "admin", active: true }])).error);
    resources.signoffs = await seedLocalReleaseSignoffs(database, owner.id);
    await seedCallbackAudit(database, owner.id);
    const databases = {};
    for (const role of ["talli_company_access_backend", "talli_ledger_backend"]) {
      const previous = await database.query("select rolcanlogin,rolinherit,rolbypassrls from pg_roles where rolname=$1", [role]);
      assert.deepEqual(previous.rows, [{ rolcanlogin: false, rolinherit: false, rolbypassrls: false }]);
      const password = randomUUID().replaceAll("-", "");
      await database.query(`alter role ${role} login password '${password}'`);
      resources.roles.push(role);
      const connection = new URL(databaseUrl);
      connection.username = role;
      connection.password = password;
      databases[role] = connection.href;
    }
    const webPort = await allocateLoopbackPort();
    const backendPort = await allocateLoopbackPort();
    const siteOrigin = `http://localhost:${webPort}`;
    const backendOrigin = `http://127.0.0.1:${backendPort}`;
    resources.mock = await startRf1086FilingAuthorityMock({ callbackOrigin: siteOrigin });
    const callbackKey = `local-authority-browser-${randomUUID()}`;
    const { privateKey } = generateKeyPairSync("rsa", { modulusLength: 2048,
      privateKeyEncoding: { type: "pkcs8", format: "pem" }, publicKeyEncoding: { type: "spki", format: "pem" } });
    const nonce = randomUUID();
    const python = process.env.TALLI_BACKEND_PYTHON_BIN || "apps/backend/.venv/bin/python";
    assert.ok(existsSync(python), "backend Python runtime is absent");
    resources.backend = startOwnedProcess({ command: python, args: ["tests/fixtures/start_shareholder_register_filing_backend.py"],
      cwd: process.cwd(), readinessProof: `TALLI_BACKEND_BOUND:${nonce}`, env: {
        ...runtimeEnvironment(), DATABASE_URL: databaseUrl, TALLI_LOCAL_RF1086_FRESH_SEND_FIXTURE: "true",
        SUPABASE_URL: supabaseUrl, SUPABASE_ANON_KEY: anonKey, SUPABASE_SERVICE_ROLE_KEY: serviceRoleKey,
        TALLI_LEDGER_DATABASE_URL: databases.talli_ledger_backend,
        TALLI_COMPANY_ACCESS_DATABASE_URL: databases.talli_company_access_backend,
        TALLI_AUTHORITY_CALLBACK_INTERNAL_KEY: callbackKey,
        TALLI_LOCAL_AUTHORITY_MOCK_BASE_URL: resources.mock.baseUrl,
        TALLI_PROD_MASKINPORTEN_CLIENT_ID: randomUUID(), TALLI_PROD_MASKINPORTEN_KEY_ID: randomUUID(),
        TALLI_PROD_MASKINPORTEN_PRIVATE_KEY_PEM: privateKey,
        TALLI_BACKEND_PORT: String(backendPort), TALLI_READINESS_NONCE: nonce,
      } });
    let httpOutput = "";
    resources.backend.stdout.on("data", (chunk) => {
      httpOutput += chunk.toString();
      let newline;
      while ((newline = httpOutput.indexOf("\n")) >= 0) {
        const line = httpOutput.slice(0, newline);
        httpOutput = httpOutput.slice(newline + 1);
        if (line.startsWith("TALLI_AUTHORITY_HTTP:")) apiCalls.push(line);
      }
    });
    await waitForOwnedReadiness({ process: resources.backend, url: `${backendOrigin}/health/ready` });
    resources.web = startOwnedProcess({ command: process.execPath,
      args: [nextCli, "dev", "apps/web", "--hostname", "127.0.0.1", "--port", String(webPort)],
      cwd: process.cwd(), readinessProof: "Ready in", env: {
        ...runtimeEnvironment(), NEXT_PUBLIC_SUPABASE_URL: supabaseUrl, NEXT_PUBLIC_SUPABASE_ANON_KEY: anonKey,
        SUPABASE_URL: supabaseUrl, SUPABASE_ANON_KEY: anonKey,
        TALLI_BACKEND_URL: backendOrigin, SITE_URL: siteOrigin,
        TALLI_AUTHORITY_CALLBACK_INTERNAL_KEY: callbackKey,
        TALLI_LOCAL_AUTHORITY_MOCK_BASE_URL: resources.mock.baseUrl,
        NODE_OPTIONS: `--import=${new URL("./fixtures/system-user-authority-mock.mjs", import.meta.url).href}`,
      } });
    await waitForOwnedReadiness({ process: resources.web, url: siteOrigin });
    resources.browser = await chromium.launch({ headless: true });
    const context = await resources.browser.newContext({ viewport: { width: 1440, height: 900 } });
    captureBrowserHealth(context, health);
    await installBrowserEgressGuard(context, { approvalEnabled: true, blockedRequests: egressViolations, mockBaseUrl: resources.mock.baseUrl });
    const page = await context.newPage();
    await login(page, siteOrigin, owner);
    await establishOwnerAal2(page, siteOrigin);
    const session = await browserSession(context);
    const api = createTalliApiClient({ baseUrl: backendOrigin });
    const authorization = { Authorization: `Bearer ${session.access_token}` };
    await page.goto(`${siteOrigin}/connections?company=${primary.id}`);
    await page.getByRole("heading", { name: "Altinn-tilkobling", exact: true }).waitFor();
    await page.getByRole("button", { name: "Opprett tilkobling", exact: true }).click();
    await page.getByRole("heading", { name: "Lokal Altinn-godkjenning", exact: true }).waitFor();
    const cookie = (await context.cookies(siteOrigin + SYSTEM_USER_COOKIE.options.path)).find(({ name }) => name === SYSTEM_USER_COOKIE.name);
    assert.ok(cookie?.httpOnly && cookie.secure && cookie.sameSite === "Lax");
    assert.equal(cookie.path, SYSTEM_USER_COOKIE.options.path);
    await page.getByRole("button", { name: "Godkjenn lokal forespørsel", exact: true }).click();
    await page.getByText("Tilkoblingen er godkjent og verifisert", { exact: true }).waitFor();
    assert.equal(new URL(page.url()).searchParams.get("company"), primary.id);
    assert.equal(new URL(page.url()).searchParams.has("requestId"), false);
    assert.equal((await context.cookies()).some(({ name }) => name === SYSTEM_USER_COOKIE.name), false);
    const stored = await authorityFixtureTransaction(database, () => database.query(`select id,company_id,status,preflight_verified_at,external_ref,altinn_request_id
      from authority_connections.system_user_requests where company_id=any($1::uuid[])`, [[primary.id]]));
    const original = stored.rows.find(({ company_id }) => company_id === primary.id);
    assert.equal(original.id, cookie.value);
    assert.equal(original.status, "accepted");
    assert.ok(original.preflight_verified_at && original.altinn_request_id);
    await page.reload();
    await page.getByText("Tilkoblingen er godkjent og verifisert", { exact: true }).waitFor();
    for (const width of [320, 1440]) {
      await page.setViewportSize({ width, height: 900 });
      assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), `connections overflow at ${width}`);
    }
    const body = await page.locator("body").innerText();
    assert.ok(!body.includes(original.external_ref) && !body.includes(original.altinn_request_id));
    assert.ok(!body.includes(callbackKey) && !body.includes(privateKey));
    const grant = async (token, companyId, userId, requestId) => {
      const headers = { Authorization: `Bearer ${token}` };
      await api.rf1086ConfirmFilingPermission({ companyId, productionEnabled: true }, { headers });
      const result = await api.billingManagePilotEntitlement({ companyId, userId, incomeYear: 2025,
        status: "active", billingExempt: true, systemUserRequestId: requestId,
        startsAt: new Date(Date.now() - 60_000).toISOString(), expiresAt: new Date(Date.now() + 3_600_000).toISOString(),
        evidenceReference: `synthetic-rf-browser:${requestId}`,
      }, { headers, idempotencyKey: `synthetic-rf-browser-${requestId}` });
      assert.equal(result.billingExempt, true);
      assert.equal(result.caseProfile, "rf1086_no_activity_v1");
      return result.entitlementId;
    };
    const entitlementId = await grant(session.access_token, primary.id, owner.id, original.id);
    const annualHref = `${siteOrigin}/companies/${primary.id}/annual-reporting/2025/aksjonaerregisteroppgaven`;
    const before = await api.rf1086Workspace(primary.id, 2025, { headers: authorization });
    assert.deepEqual(before.previews, []);
    assert.deepEqual(before.approvals, []);
    await page.goto(annualHref);
    await page.getByRole("button", { name: "Lag ny forhåndsvisning", exact: true }).click();
    await page.getByRole("button", { name: "Lagre kommentar", exact: true }).waitFor();
    const preview = (await api.rf1086Workspace(primary.id, 2025, { headers: authorization })).previews[0];
    assert.equal(preview.filing, "aksjonærregisteroppgaven");
    assert.equal(preview.status, "ready");
    assert.ok(preview.hovedskjemaXml && Object.keys(preview.underskjemaXml).length === 1);
    const payloadHash = createHash("sha256").update(JSON.stringify({ filing: preview.filing,
      company_id: preview.companyId, income_year: preview.incomeYear, hovedskjema_xml: preview.hovedskjemaXml,
      underskjema_xml: preview.underskjemaXml })).digest("hex");
    await page.getByLabel("Kommentar", { exact: true }).fill("Synthetic owner reviewed the original shareholder basis.");
    await page.getByRole("button", { name: "Lagre kommentar", exact: true }).click();
    await page.waitForLoadState("networkidle");
    const reviewed = await api.rf1086Workspace(primary.id, 2025, { headers: authorization });
    assert.equal(reviewed.reviewComments.length, 1);
    assert.equal(reviewed.reviewComments[0].previewId, preview.id);
    assert.equal(reviewed.reviewComments[0].severity, "advisory");
    await page.goto(`${siteOrigin}/filing/aksjonaerregisteroppgaven`);
    const productionSection = page.locator("section").filter({
      has: page.getByRole("heading", { name: "Reell innsending av aksjonærregisteroppgaven", exact: true }),
    });
    await productionSection.locator('input[name="realFilingConfirmed"]').check();
    await productionSection.getByRole("button", { name: "Godkjenn innholdet", exact: true }).click();
    await productionSection.getByRole("button", { name: "Send aksjonærregisteroppgaven", exact: true }).waitFor();
    const approved = await api.rf1086Workspace(primary.id, 2025, { headers: authorization });
    assert.equal(approved.approvals.length, 1);
    assert.equal(approved.approvals[0].previewId, preview.id);
    assert.equal(approved.approvals[0].entitlementId, entitlementId);
    assert.equal(approved.approvals[0].payloadHash, payloadHash);
    assert.equal(approved.previews[0].filing, "aksjonærregisteroppgaven");
    assert.deepEqual(approved.previews[0].underskjemaXml, preview.underskjemaXml);
    const send = productionSection.getByRole("button", { name: "Send aksjonærregisteroppgaven", exact: true });
    await send.focus();
    assert.equal(await send.evaluate((element) => element === document.activeElement), true);
    await send.press("Enter");
    await productionSection.getByText("Godkjent", { exact: true }).waitFor();
    const accepted = await api.rf1086Workspace(primary.id, 2025, { headers: authorization });
    assert.equal(accepted.productionSubmissions.length, 1);
    assert.equal(accepted.productionSubmissions[0].feedbackState, "accepted");
    assert.equal(accepted.productionSubmissions[0].payloadHash, payloadHash);
    assert.equal(accepted.feedbackArtifacts.length, 1);
    const artifact = accepted.feedbackArtifacts[0];
    assert.equal(artifact.submissionId, accepted.productionSubmissions[0].id);
    assert.equal(artifact.classification, "accepted");
    for (const width of [320, 768, 1440]) {
      await page.setViewportSize({ width, height: 900 });
      assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), `fresh RF overflow at ${width}`);
      assert.ok(await productionSection.getByRole("link", { name: /Last ned .*tilbakemelding/u }).isVisible());
    }
    for (let reload = 0; reload < 2; reload += 1) {
      await page.reload();
      await productionSection.getByText("Godkjent", { exact: true }).waitFor();
    }
    const download = productionSection.getByRole("link", { name: /Last ned .*tilbakemelding/u });
    await download.focus();
    assert.equal(await download.evaluate((element) => element === document.activeElement), true);
    const receipt = await context.request.get(new URL(await download.getAttribute("href"), siteOrigin).href, { maxRedirects: 0 });
    assert.equal(receipt.status(), 307);
    const signed = new URL(receipt.headers().location, siteOrigin);
    assert.ok(isLoopbackSupabaseUrl(signed.origin) && signed.searchParams.has("token"));
    const bytes = await context.request.get(signed.href, { maxRedirects: 0 });
    assert.equal(bytes.status(), 200);
    assert.equal(createHash("sha256").update(await bytes.body()).digest("hex"), artifact.sha256);
    const successfulCalls = resources.mock.snapshot();
    assert.equal(successfulCalls.filter(({ operation }) => operation === "post_hovedskjema").length, 1);
    assert.equal(successfulCalls.filter(({ operation }) => operation === "post_underskjema").length, 1);
    assert.equal(successfulCalls.filter(({ operation }) => operation === "confirm").length, 1);
    assert.equal(successfulCalls.find(({ operation }) => operation === "post_hovedskjema").digest,
      createHash("sha256").update(preview.hovedskjemaXml).digest("hex"));
    assert.equal(successfulCalls.find(({ operation }) => operation === "post_underskjema").digest,
      createHash("sha256").update(Object.values(preview.underskjemaXml)[0]).digest("hex"));

    const otherContext = await resources.browser.newContext({ viewport: { width: 1440, height: 900 } });
    captureBrowserHealth(otherContext, health);
    await installBrowserEgressGuard(otherContext, { approvalEnabled: true, blockedRequests: egressViolations, mockBaseUrl: resources.mock.baseUrl });
    const otherPage = await otherContext.newPage();
    await login(otherPage, siteOrigin, other);
    await establishOwnerAal2(otherPage, siteOrigin);
    const otherSession = await browserSession(otherContext);
    const otherHeaders = { Authorization: `Bearer ${otherSession.access_token}` };
    const denied = await fetch(`${backendOrigin}/api/v1/shareholder-register-filings/workspace?companyId=${primary.id}`, { headers: otherHeaders });
    assert.equal(denied.status, 403);
    assert.equal(denied.headers.get("cache-control"), "no-store");
    assert.ok(!(await denied.text()).includes(preview.id));
    const deniedReceipt = await otherContext.request.get(`${siteOrigin}/documents/${artifact.documentId}/download`, { maxRedirects: 0 });
    assert.equal(deniedReceipt.status(), 403);
    assert.equal(deniedReceipt.headers().location, undefined);
    assert.ok(!(await deniedReceipt.text()).includes(artifact.documentId));
    const deniedRecovery = await api.legacyRf1086ReconcileFeedback({ submissionId: accepted.productionSubmissions[0].id }, { headers: otherHeaders });
    assert.deepEqual(deniedRecovery, { state: null, errorCode: "basis_unavailable", requiresManualRetry: true });

    // A second supported fixture records the provider's ambiguous response.
    // The application must keep the original journal and never resend that POST.
    await otherPage.goto(`${siteOrigin}/connections?company=${otherCompany.id}`);
    await otherPage.getByRole("button", { name: "Opprett tilkobling", exact: true }).click();
    await otherPage.getByRole("button", { name: "Godkjenn lokal forespørsel", exact: true }).click();
    await otherPage.getByText("Tilkoblingen er godkjent og verifisert", { exact: true }).waitFor();
    const otherRequest = (await authorityFixtureTransaction(database, () => database.query(
      "select id from authority_connections.system_user_requests where company_id=$1", [otherCompany.id]))).rows[0];
    const otherEntitlement = await grant(otherSession.access_token, otherCompany.id, other.id, otherRequest.id);
    const otherSetup = (await rfFixtureTransaction(database, () => database.query(
      "select id from shareholder_register_filing.opening_balance_setups where company_id=$1", [otherCompany.id]))).rows[0];
    const otherPreview = await api.rf1086GeneratePreview({ companyId: otherCompany.id, openingSnapshotId: otherSetup.id }, { headers: otherHeaders });
    const otherApproval = await api.rf1086ApproveProduction({ previewId: otherPreview.recordId,
      entitlementId: otherEntitlement, realFilingConfirmed: true }, { headers: otherHeaders });
    resources.mock.failNextMainResponse();
    const unknownSend = await fetch(`${backendOrigin}/api/v1/legacy-rf1086/production-filings`, {
      method: "POST", headers: { ...otherHeaders, "Content-Type": "application/json" },
      body: JSON.stringify({ approvalId: otherApproval.recordId }),
    });
    assert.equal(unknownSend.status, 503);
    assert.equal((await unknownSend.json()).code, "send_unavailable");
    const unknownState = await api.rf1086Workspace(otherCompany.id, 2025, { headers: otherHeaders });
    assert.equal(unknownState.productionSubmissions.length, 1);
    assert.equal(unknownState.productionSubmissions[0].status, "unknown");
    assert.deepEqual(unknownState.feedbackArtifacts, []);
    const mutationCount = resources.mock.snapshot().filter(({ operation }) => operation.startsWith("post_")).length;
    const repeated = await fetch(`${backendOrigin}/api/v1/legacy-rf1086/production-filings`, {
      method: "POST", headers: { ...otherHeaders, "Content-Type": "application/json" },
      body: JSON.stringify({ approvalId: otherApproval.recordId }),
    });
    assert.equal(repeated.status, 503);
    const recovery = await api.legacyRf1086ReconcileFeedback({ submissionId: unknownState.productionSubmissions[0].id }, { headers: otherHeaders });
    assert.equal(recovery.requiresManualRetry, true);
    assert.notEqual(recovery.state, "accepted");
    assert.equal(resources.mock.snapshot().filter(({ operation }) => operation.startsWith("post_")).length, mutationCount);
    assert.ok(!resources.mock.snapshot().some(({ operation }) => operation === "replayed_mutation" || operation === "request_rejected"));
    for (const event of ["POST:/api/v1/shareholder-register-filings/previews:200",
      "POST:/api/v1/shareholder-register-filings/review-comments:200",
      "POST:/api/v1/shareholder-register-filings/production-approvals:200",
      "POST:/api/v1/legacy-rf1086/production-filings:200", "POST:/api/v1/legacy-rf1086/production-filings:503"])
      assert.ok(apiCalls.some((call) => call.endsWith(event)), `missing actual canonical backend request ${event}`);
    assert.ok(!(await page.locator("body").innerText()).includes(original.external_ref));
    await otherContext.close();
    await context.close();
    assert.deepEqual(health, []);
    assert.deepEqual(egressViolations, []);
  } catch (error) {
    primaryFailure = error;
    // Only process health diagnostics are retained; no environment, bearer,
    // provider body or generated private key is included in fixture output.
    throw new Error(`${error.message}\nweb=${ownedProcessDiagnostics(resources.web)}\nbackend=${ownedProcessDiagnostics(resources.backend)}`, { cause: error });
  }
});

function runtimeEnvironment() {
  const result = {};
  for (const key of ["PATH", "HOME", "TMPDIR", "LANG", "LC_ALL", "CI", "VIRTUAL_ENV"])
    if (process.env[key]) result[key] = process.env[key];
  return { ...result, TALLI_AUTHORITY_OPS_ENABLED: "false", TALLI_RF1086_PRODUCTION_ENABLED: "false", NEXT_TELEMETRY_DISABLED: "1" };
}

async function createUser(admin, prefix, users) {
  const email = `${prefix}-${randomUUID()}@example.test`;
  const password = `Pw-${randomUUID()}-local`;
  const result = await admin.auth.admin.createUser({ email, password, email_confirm: true });
  assert.ifError(result.error);
  users.push(result.data.user.id);
  return { id: result.data.user.id, email, password };
}

async function seedCompany(admin, database, ownerId, name, companies) {
  const id = randomUUID();
  const organizationNumber = String(randomInt(100000000, 999999999));
  const result = await admin.from("companies").insert({ id, org_number: organizationNumber, name, entity_type: "AS",
    address: "Synthetic local fixture", postal_code: "0155", city: "OSLO", status_text: "aktiv", source: "browser_test",
    created_by: ownerId, identity_confirmed_at: new Date().toISOString(), identity_locked_at: new Date().toISOString() });
  assert.ifError(result.error);
  companies.push(id);
  assert.ifError((await admin.from("company_memberships").insert({ company_id: id, user_id: ownerId, role: "owner",
    invited_by: ownerId, accepted_at: new Date().toISOString() })).error);
  const terms = currentCustomerAgreements.businessTerms;
  const dpa = currentCustomerAgreements.dpa;
  await database.query(`insert into public.customer_agreement_acceptances(company_id,accepted_by,customer_legal_name,
    customer_org_number,business_terms_version,business_terms_effective_date,business_terms_path,business_terms_sha256,
    dpa_version,dpa_effective_date,dpa_path,dpa_sha256,authority_statement_version,acceptance_method,accepted_at)
    values($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,'authority-v1','in_app_clickwrap',now())`,
    [id, ownerId, name, organizationNumber, terms.version, terms.effectiveDate, terms.path, terms.contentSha256,
      dpa.version, dpa.effectiveDate, dpa.path, dpa.contentSha256]);
  return { id, name };
}

async function authorityFixtureTransaction(database, operation) {
  return fixtureTableTransaction(database, [
    "authority_connections.authority_operations", "authority_connections.system_user_requests",
  ], operation);
}

async function seedCallbackAudit(database, actorId) {
  await authorityFixtureTransaction(database, () => database.query(`insert into authority_connections.authority_operations
    (operation,actor_id,status,request_hash,result_code,authority_http_status,metadata,completed_at)
    values('set_rf1086_systembruker_callback',$1,'succeeded',$2,'callback_already_verified',200,
      '{"systemId":"930835978_talli","callbackPath":"/auth/systembruker/confirm"}',now())`,
    [actorId, createHash("sha256").update("synthetic-local-callback-prerequisite").digest("hex")]));
}

async function cleanupFixture(database, companyIds, userIds) {
  await fixtureTableTransaction(database, [
    ...RF_FIXTURE_RELATIONS,
    "authority_connections.system_user_requests", "authority_connections.authority_operations",
    "public.audit_events", "public.support_operators", "public.customer_agreement_acceptances",
    "public.company_memberships", "public.companies",
  ], async () => {
    await database.query("delete from shareholder_register_filing.production_feedback_artifacts where company_id=any($1::uuid[])", [companyIds]);
    await database.query("delete from documents.evidence_references where document_id in (select id from public.documents where company_id=any($1::uuid[]))", [companyIds]);
    await database.query("delete from shareholder_register_filing.production_filing_events where submission_id in (select id from shareholder_register_filing.production_filing_submissions where company_id=any($1::uuid[]))", [companyIds]);
    await database.query("delete from shareholder_register_filing.production_filing_submissions where company_id=any($1::uuid[])", [companyIds]);
    await database.query("delete from shareholder_register_filing.filing_approval_snapshots where company_id=any($1::uuid[])", [companyIds]);
    // Normal RF writes keep these public projections. Their setup FKs still
    // reference the canonical opening after contract, so remove children first.
    for (const table of RF_PUBLIC_PROJECTION_TABLES)
      await database.query(`delete from public.${table} where company_id=any($1::uuid[])`, [companyIds]);
    await database.query("delete from ledger.opening_bank_inputs where company_id=any($1::uuid[])", [companyIds]);
    for (const table of ["filing_review_comments", "filing_overrides", "filing_submissions", "authority_test_runs", "authority_permissions", "filing_previews", "opening_shareholders", "opening_balance_setups", "migration_inventory", "migration_quarantine"])
      await database.query(`delete from shareholder_register_filing.${table} where company_id=any($1::uuid[])`, [companyIds]);
    await database.query("delete from public.filing_readiness_snapshots where company_id=any($1::uuid[])", [companyIds]);
    await database.query("delete from public.documents where company_id=any($1::uuid[])", [companyIds]);
    await database.query("delete from billing.production_pilot_entitlements where company_id=any($1::uuid[])", [companyIds]);
    await database.query("delete from public.company_archive_source_generations where company_id=any($1::uuid[])", [companyIds]);
    await database.query("delete from authority_connections.system_user_requests where company_id=any($1::uuid[])", [companyIds]);
    await database.query("delete from authority_connections.authority_operations where actor_id=any($1::uuid[])", [userIds]);
    await database.query("delete from public.audit_events where actor_id=any($1::uuid[])", [userIds]);
    await database.query("delete from public.support_operators where user_id=any($1::uuid[])", [userIds]);
    await database.query("delete from public.customer_agreement_acceptances where company_id=any($1::uuid[])", [companyIds]);
    await database.query("delete from public.company_memberships where company_id=any($1::uuid[])", [companyIds]);
    await deleteRfFixtureCompanies(database, companyIds);
  });
}

async function login(page, origin, user) {
  await page.goto(`${origin}/login`);
  const form = page.locator("form").filter({ hasText: "Logg inn" }).first();
  await form.getByLabel("E-post").fill(user.email);
  await form.getByLabel("Passord").fill(user.password);
  await form.getByRole("button", { name: "Logg inn", exact: true }).click();
  await page.waitForLoadState("networkidle");
}

async function establishOwnerAal2(page, origin) {
  await page.goto(`${origin}/mfa?next=%2Fconnections`);
  await page.getByRole("heading", { name: "Beskytt kontoen før du fortsetter" }).waitFor();
  await page.getByRole("button", { name: "Sett opp autentiseringsapp", exact: true }).click();
  const secret = (await page.locator("code").innerText()).trim();
  const alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567";
  const bits = [...secret.toUpperCase().replace(/=+$/u, "")].map((character) => {
    const index = alphabet.indexOf(character);
    assert.notEqual(index, -1);
    return index.toString(2).padStart(5, "0");
  }).join("");
  const key = Buffer.from((bits.match(/.{8}/gu) ?? []).map((byte) => Number.parseInt(byte, 2)));
  const counter = Buffer.alloc(8);
  counter.writeBigUInt64BE(BigInt(Math.floor(Date.now() / 30000)));
  const digest = createHmac("sha1", key).update(counter).digest();
  const code = String((digest.readUInt32BE(digest.at(-1) & 0x0f) & 0x7fffffff) % 1000000).padStart(6, "0");
  await page.getByLabel("Sekssifret kode").fill(code);
  await page.getByRole("button", { name: "Bekreft og fortsett", exact: true }).click();
  await page.waitForURL((url) => url.pathname !== "/mfa");
}

async function browserSession(context) {
  const key = `sb-${new URL(supabaseUrl).hostname.split(".")[0]}-auth-token`;
  const cookies = await context.cookies();
  const value = cookies.find(({ name }) => name === key)?.value ?? cookies.filter(({ name }) => name.startsWith(key + "."))
    .sort((a, b) => Number(a.name.slice(key.length + 1)) - Number(b.name.slice(key.length + 1))).map(({ value }) => value).join("");
  assert.ok(value, "authenticated browser session is absent");
  const session = JSON.parse(value.startsWith("base64-") ? Buffer.from(value.slice(7), "base64url").toString() : value);
  assert.ok(session.access_token, "authenticated browser bearer is absent");
  return session;
}


const RF_TABLES = ["opening_balance_setups", "opening_shareholders", "filing_previews", "filing_submissions",
  "filing_overrides", "filing_review_comments", "authority_permissions", "authority_test_runs", "filing_approval_snapshots",
  "production_filing_submissions", "production_filing_events", "production_feedback_artifacts", "migration_inventory", "migration_quarantine"];
const SIGNOFF_KEYS = ["launch_legal_name_public_copy", "legal_policy_pack", "security_restore", "support_rollback", "founder_production_go_live", "rf1086_authority"];
const RF_PUBLIC_PROJECTION_TABLES = Object.freeze([
  "filing_review_comments", "filing_overrides", "filing_submissions",
  "authority_test_runs", "authority_permissions", "filing_previews",
]);

const RF_FIXTURE_RELATIONS = Object.freeze([
  ...RF_TABLES.map((name) => `shareholder_register_filing.${name}`),
  ...RF_PUBLIC_PROJECTION_TABLES.map((name) => `public.${name}`),
  "ledger.opening_bank_inputs", "billing.production_pilot_entitlements", "documents.evidence_references",
  "public.documents", "public.filing_readiness_snapshots", "public.company_archive_source_generations",
]);

async function rfFixtureTransaction(database, operation) {
  return fixtureTableTransaction(database, RF_FIXTURE_RELATIONS, operation);
}

async function seedFreshBasis(database, companyId, ownerId) {
  const setupId = randomUUID();
  await rfFixtureTransaction(database, async () => {
    await database.query(`insert into shareholder_register_filing.opening_balance_setups
      (id,company_id,income_year,share_capital,share_count,nominal_value,created_by)
      values($1,$2,2025,30000,100,300,$3)`, [setupId, companyId, ownerId]);
    await database.query(`insert into ledger.opening_bank_inputs(snapshot_id,company_id,income_year,bank_balance_nok,recorded_by,recorded_at)
      values($1,$2,2025,30000,$3,now())`, [setupId, companyId, ownerId]);
    await database.query(`insert into shareholder_register_filing.opening_shareholders
      (id,setup_id,company_id,name,shareholder_kind,org_number,share_count,created_by)
      values($1,$2,$3,'Synthetic Fixture Owner AS','norwegian_company','999999999',100,$4)`, [randomUUID(), setupId, companyId, ownerId]);
    // This local prerequisite records the exact supported no-activity case;
    // no paid account, preview, approval, journal or provider receipt is seeded.
    await database.query(`insert into public.filing_readiness_snapshots
      (company_id,income_year,obligation,status,ready,created_by)
      values($1,2025,'aksjonaerregisteroppgaven','ready',true,$2)`, [companyId, ownerId]);
  });
}

async function seedLocalReleaseSignoffs(database, actorId) {
  // Technical signoff storage remains this physical table after authenticated
  // access is contracted; the finite fixture restores its exact previous rows.
  return fixtureTableTransaction(database, ["public.launch_signoffs"], async () => {
    const previous = (await database.query("select to_jsonb(s) value from public.launch_signoffs s where key=any($1::text[])", [SIGNOFF_KEYS])).rows.map(({ value }) => value);
    for (const key of SIGNOFF_KEYS) await database.query(`insert into public.launch_signoffs
      (key,status,reviewer,reviewed_at,evidence_link,decision,recorded_by)
      values($1,'approved','Synthetic local browser',now()-interval '1 minute','local-synthetic-rf-browser','Local fixture only',$2)
      on conflict(key) do update set status=excluded.status,reviewer=excluded.reviewer,reviewed_at=excluded.reviewed_at,
        evidence_link=excluded.evidence_link,decision=excluded.decision,recorded_by=excluded.recorded_by`, [key, actorId]);
    return previous;
  });
}

async function restoreLocalReleaseSignoffs(database, previous) {
  if (previous === undefined) return;
  await fixtureTableTransaction(database, ["public.launch_signoffs"], async () => {
    await database.query("delete from public.launch_signoffs where key=any($1::text[])", [SIGNOFF_KEYS]);
    for (const row of previous) await database.query("insert into public.launch_signoffs select * from jsonb_populate_record(null::public.launch_signoffs,$1::jsonb)", [JSON.stringify(row)]);
  });
}

function captureBrowserHealth(context, health) {
  context.on("page", (page) => {
    page.on("console", (message) => {
      if (message.type() === "warning" || message.type() === "error") {
        // Closed diagnostics record every warning/error without persisting any
        // console text that could contain a bearer, identifier or response.
        health.push(`console_${message.type()}`);
      }
    });
    page.on("pageerror", () => health.push("page_error"));
  });
}
