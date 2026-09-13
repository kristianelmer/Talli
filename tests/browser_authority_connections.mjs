import assert from "node:assert/strict";
import { fixtureTableTransaction, deleteRfFixtureCompanies } from "./support/rf1086-fixture-access.mjs";
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
import { installBrowserEgressGuard, startSystemUserAuthorityMock } from "./fixtures/system-user-authority-mock.mjs";
import { allocateLoopbackPort, ownedProcessDiagnostics, startOwnedProcess, stopOwnedProcess, waitForOwnedReadiness } from "./support/owned-process-lifecycle.mjs";
import { isLoopbackPostgresUrl, isLoopbackSupabaseUrl } from "./support/supabase_fixture_safety.mjs";

const nextCli = createRequire(new URL("../apps/web/package.json", import.meta.url)).resolve("next/dist/bin/next");
const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL || process.env.SUPABASE_URL;
const anonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY || process.env.SUPABASE_ANON_KEY;
const serviceRoleKey = process.env.SUPABASE_SERVICE_ROLE_KEY;
const databaseUrl = process.env.DATABASE_URL;

// This is a mandatory local lane: absent or non-loopback configuration fails;
// it never converts the full-stack authority journey into a skipped test.
test("owner connects through hydrated Next, generated FastAPI transport, real RLS and a local authority mock", {
  timeout: 240_000,
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
      await attempt(() => cleanupFixture(database, resources.companies, resources.users));
      for (const userId of resources.users) await attempt(async () => {
        const { error } = await admin.auth.admin.deleteUser(userId);
        assert.ifError(error);
      });
      await attempt(async () => {
        const residue = await authorityFixtureTransaction(database, () => database.query(`select
          (select count(*)::int from authority_connections.system_user_requests where company_id=any($1::uuid[])) requests,
          (select count(*)::int from authority_connections.authority_operations where actor_id=any($2::uuid[])) operations`, [resources.companies, resources.users]));
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
    const decoy = await seedCompany(admin, database, owner.id, "Synthetic Callback Decoy", resources.companies);
    const primary = await seedCompany(admin, database, owner.id, "Synthetic Authority Holding", resources.companies);
    await seedCompany(admin, database, other.id, "Synthetic Other Owner", resources.companies);
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
    resources.mock = await startSystemUserAuthorityMock({ callbackOrigin: siteOrigin });
    const callbackKey = `local-authority-browser-${randomUUID()}`;
    const { privateKey } = generateKeyPairSync("rsa", { modulusLength: 2048,
      privateKeyEncoding: { type: "pkcs8", format: "pem" }, publicKeyEncoding: { type: "spki", format: "pem" } });
    const nonce = randomUUID();
    const python = process.env.TALLI_BACKEND_PYTHON_BIN || "apps/backend/.venv/bin/python";
    assert.ok(existsSync(python), "backend Python runtime is absent");
    resources.backend = startOwnedProcess({ command: python, args: ["tests/fixtures/start_authority_connections_backend.py"],
      cwd: process.cwd(), readinessProof: `TALLI_BACKEND_BOUND:${nonce}`, env: {
        ...runtimeEnvironment(), DATABASE_URL: databaseUrl,
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
    const decoyId = randomUUID();
    const decoyResult = await api.authorityConnectionsStartSystemUserRequest(
      { companyId: decoy.id, requestId: decoyId }, { headers: authorization },
    );
    assert.equal(decoyResult.status, "new");
    resources.mock.setTamperedCallbackRequestId(decoyId);

    await page.goto(`${siteOrigin}/connections?company=${primary.id}`);
    await page.getByRole("heading", { name: "Altinn-tilkobling", exact: true }).waitFor();
    await page.getByRole("button", { name: "Opprett tilkobling", exact: true }).click();
    await page.getByRole("heading", { name: "Lokal Altinn-godkjenning", exact: true }).waitFor();
    const cookie = (await context.cookies(siteOrigin + SYSTEM_USER_COOKIE.options.path)).find(({ name }) => name === SYSTEM_USER_COOKIE.name);
    assert.ok(cookie?.httpOnly && cookie.secure && cookie.sameSite === "Lax");
    assert.equal(cookie.path, SYSTEM_USER_COOKIE.options.path);
    assert.notEqual(cookie.value, decoyId);
    await page.getByRole("button", { name: "Godkjenn lokal forespørsel", exact: true }).click();
    await page.getByText("Tilkoblingen er godkjent og verifisert", { exact: true }).waitFor();
    assert.equal(new URL(page.url()).searchParams.get("company"), primary.id);
    assert.equal(new URL(page.url()).searchParams.has("requestId"), false);
    assert.equal((await context.cookies()).some(({ name }) => name === SYSTEM_USER_COOKIE.name), false);
    const stored = await authorityFixtureTransaction(database, () => database.query(`select id,company_id,status,preflight_verified_at,external_ref,altinn_request_id
      from authority_connections.system_user_requests where company_id=any($1::uuid[])`, [[primary.id, decoy.id]]));
    const original = stored.rows.find(({ company_id }) => company_id === primary.id);
    const untouched = stored.rows.find(({ company_id }) => company_id === decoy.id);
    assert.equal(original.id, cookie.value);
    assert.equal(original.status, "accepted");
    assert.ok(original.preflight_verified_at && original.altinn_request_id);
    assert.equal(untouched.id, decoyId);
    assert.equal(untouched.status, "new");
    assert.equal(untouched.preflight_verified_at, null);
    await page.reload();
    await page.getByText("Tilkoblingen er godkjent og verifisert", { exact: true }).waitFor();
    for (const width of [320, 1440]) {
      await page.setViewportSize({ width, height: 900 });
      assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), `connections overflow at ${width}`);
    }
    const body = await page.locator("body").innerText();
    assert.ok(!body.includes(original.external_ref) && !body.includes(original.altinn_request_id));
    assert.ok(!body.includes(callbackKey) && !body.includes(privateKey));
    const production = await seedHistoricalRf(database, primary.id, owner.id, original);
    resources.mock.setForsendelseId(production.forsendelseId);
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto(`${siteOrigin}/filing/aksjonaerregisteroppgaven`);
    const productionSection = page.locator("section").filter({
      has: page.getByRole("heading", { name: "Reell innsending av aksjonærregisteroppgaven", exact: true }),
    });
    await productionSection.getByText("Til behandling", { exact: true }).waitFor();
    const retry = productionSection.getByRole("button", { name: "Sjekk status på nytt", exact: true });
    await retry.focus();
    assert.equal(await retry.evaluate((element) => element === document.activeElement), true);
    await retry.press("Enter");
    await productionSection.getByText("Godkjent", { exact: true }).waitFor();
    const storedFiling = await rfFixtureTransaction(database, () => database.query("select feedback_state from shareholder_register_filing.production_filing_submissions where id=$1", [production.submissionId]));
    assert.equal(storedFiling.rows[0].feedback_state, "accepted");
    for (let reload = 0; reload < 2; reload += 1) {
      await page.reload();
      await productionSection.getByText("Godkjent", { exact: true }).waitFor();
    }
    const artifact = (await rfFixtureTransaction(database, () => database.query("select document_id,sha256 from shareholder_register_filing.production_feedback_artifacts where submission_id=$1", [production.submissionId]))).rows;
    assert.equal(artifact.length, 1);
    for (const width of [320, 768, 1440]) {
      await page.setViewportSize({ width, height: 900 });
      assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), `RF overflow at ${width}`);
      assert.ok(await productionSection.getByRole("link", { name: /Last ned .*tilbakemelding/u }).isVisible());
    }
    const download = productionSection.getByRole("link", { name: /Last ned .*tilbakemelding/u });
    await download.focus();
    assert.equal(await download.evaluate((element) => element === document.activeElement), true);
    const downloadHref = await download.getAttribute("href");
    const receipt = await context.request.get(new URL(downloadHref, siteOrigin).href, { maxRedirects: 0 });
    assert.equal(receipt.status(), 307);
    const signed = new URL(receipt.headers().location, siteOrigin);
    assert.ok(isLoopbackSupabaseUrl(signed.origin) && signed.searchParams.has("token"));
    const bytes = await context.request.get(signed.href, { maxRedirects: 0 });
    assert.equal(bytes.status(), 200);
    assert.equal(createHash("sha256").update(await bytes.body()).digest("hex"), artifact[0].sha256);
    assert.ok(!(await page.locator("body").innerText()).includes(original.external_ref));
    // A callback URL alone has no cookie authority, even with the legitimate
    // session and a query selecting an existing request.
    await page.goto(`${siteOrigin}/auth/systembruker/confirm?requestId=${decoyId}`);
    await page.waitForURL((url) => url.pathname === "/connections" && url.searchParams.get("systembruker") === "manual");
    const directCallback = await fetch(`${backendOrigin}/api/v1/authority-connections/system-user-callbacks`, {
      method: "POST", headers: { ...authorization, "Content-Type": "application/json" }, body: JSON.stringify({ requestId: decoyId }),
    });
    assert.equal(directCallback.status, 401);

    const otherContext = await resources.browser.newContext({ viewport: { width: 1440, height: 900 } });
    captureBrowserHealth(otherContext, health);
    await installBrowserEgressGuard(otherContext, { approvalEnabled: false, blockedRequests: egressViolations, mockBaseUrl: resources.mock.baseUrl });
    const otherPage = await otherContext.newPage();
    await login(otherPage, siteOrigin, other);
    await establishOwnerAal2(otherPage, siteOrigin);
    await otherPage.goto(`${siteOrigin}/connections?company=${primary.id}`);
    await otherPage.getByRole("heading", { name: "Altinn-tilkobling", exact: true }).waitFor();
    const otherBody = await otherPage.locator("body").innerText();
    assert.ok(!otherBody.includes(primary.name) && !otherBody.includes("Tilkoblingen er godkjent og verifisert"));
    assert.ok(!otherBody.includes(original.external_ref) && !otherBody.includes(original.altinn_request_id));
    const otherSession = await browserSession(otherContext);
    const forbidden = await fetch(`${backendOrigin}/api/v1/authority-connections/system-user-requests/reconciliations`, {
      method: "POST", headers: { Authorization: `Bearer ${otherSession.access_token}`, "Content-Type": "application/json" },
      body: JSON.stringify({ companyId: primary.id, requestId: original.id }),
    });
    assert.equal(forbidden.status, 403);
    assert.equal(forbidden.headers.get("cache-control"), "no-store");
    assert.ok(!(await forbidden.text()).includes(original.external_ref));
    const forbiddenReceipt = await otherContext.request.get(`${siteOrigin}/documents/${artifact[0].document_id}/download`, { maxRedirects: 0 });
    assert.equal(forbiddenReceipt.status(), 403);
    assert.equal(forbiddenReceipt.headers().location, undefined);
    assert.ok(!(await forbiddenReceipt.text()).includes(artifact[0].document_id));
    const forbiddenRecovery = await fetch(`${backendOrigin}/api/v1/legacy-rf1086/feedback-reconciliations`, {
      method: "POST", headers: { Authorization: `Bearer ${otherSession.access_token}`, "Content-Type": "application/json" },
      body: JSON.stringify({ submissionId: production.submissionId }),
    });
    assert.equal(forbiddenRecovery.status, 200);
    assert.deepEqual(await forbiddenRecovery.json(), { state: null, errorCode: "basis_unavailable", requiresManualRetry: true });
    const calls = resources.mock.snapshot();
    assert.equal(calls.filter(({ operation }) => operation === "list_documents").length, 1);
    assert.equal(calls.filter(({ operation }) => operation === "read_feedback").length, 1);
    assert.ok(!calls.some(({ service, operation }) => service === "skatteetaten" && operation.startsWith("post_")));
    assert.equal(calls.filter(({ operation }) => operation === "create_request").length, 2);
    for (const operation of ["approval_page", "approve_request", "read_request", "query_system_user"])
      assert.ok(calls.some((call) => call.operation === operation), `missing local provider operation ${operation}`);
    assert.ok(!calls.some(({ operation }) => operation === "request_rejected"));
    for (const event of [
      "POST:/api/v1/authority-connections/system-user-requests:200",
      "POST:/api/v1/authority-connections/system-user-callbacks:200",
      "GET:/api/v1/authority-connections/system-user-requests:200",
      "POST:/api/v1/legacy-rf1086/feedback-reconciliations:200",
    ]) assert.ok(apiCalls.some((call) => call.endsWith(event)), `missing actual backend request ${event}`);
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
  return fixtureTableTransaction(database, ["authority_connections.authority_operations", "authority_connections.system_user_requests"], operation);
}

async function seedCallbackAudit(database, actorId) {
  await authorityFixtureTransaction(database, () => database.query(`insert into authority_connections.authority_operations
    (operation,actor_id,status,request_hash,result_code,authority_http_status,metadata,completed_at)
    values('set_rf1086_systembruker_callback',$1,'succeeded',$2,'callback_already_verified',200,
      '{"systemId":"930835978_talli","callbackPath":"/auth/systembruker/confirm"}',now())`,
    [actorId, createHash("sha256").update("synthetic-local-callback-prerequisite").digest("hex")]));
}

async function cleanupFixture(database, companyIds, userIds) {
  await rfFixtureTransaction(database, async () => {
    await database.query("delete from shareholder_register_filing.production_feedback_artifacts where company_id=any($1::uuid[])", [companyIds]);
    await database.query("delete from documents.evidence_references where document_id in (select id from public.documents where company_id=any($1::uuid[]))", [companyIds]);
    await database.query("delete from shareholder_register_filing.production_filing_events where submission_id in (select id from shareholder_register_filing.production_filing_submissions where company_id=any($1::uuid[]))", [companyIds]);
    await database.query("delete from shareholder_register_filing.production_filing_submissions where company_id=any($1::uuid[])", [companyIds]);
    await database.query("delete from shareholder_register_filing.filing_approval_snapshots where company_id=any($1::uuid[])", [companyIds]);
    await database.query("delete from shareholder_register_filing.filing_previews where company_id=any($1::uuid[])", [companyIds]);
    await database.query("delete from public.documents where company_id=any($1::uuid[])", [companyIds]);
    await database.query("delete from billing.production_pilot_entitlements where company_id=any($1::uuid[])", [companyIds]);
    await database.query("delete from public.company_archive_source_generations where company_id=any($1::uuid[])", [companyIds]);
  });
  await authorityFixtureTransaction(database, async () => {
    await database.query("delete from authority_connections.system_user_requests where company_id=any($1::uuid[])", [companyIds]);
    await database.query("delete from authority_connections.authority_operations where actor_id=any($1::uuid[])", [userIds]);
  });
  await fixtureTableTransaction(database, ["public.audit_events", "public.customer_agreement_acceptances",
    "public.company_memberships", "public.companies", "public.company_archive_source_generations"], async () => {
    await database.query("delete from public.audit_events where actor_id=any($1::uuid[])", [userIds]);
    await database.query("delete from public.customer_agreement_acceptances where company_id=any($1::uuid[])", [companyIds]);
    await database.query("delete from public.company_memberships where company_id=any($1::uuid[])", [companyIds]);
    await database.query("delete from public.company_archive_source_generations where company_id=any($1::uuid[])", [companyIds]);
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


async function rfFixtureTransaction(database, operation) {
  return fixtureTableTransaction(database, ["shareholder_register_filing.filing_previews", "shareholder_register_filing.filing_approval_snapshots",
    "shareholder_register_filing.production_filing_submissions", "shareholder_register_filing.production_filing_events",
    "shareholder_register_filing.production_feedback_artifacts", "billing.production_pilot_entitlements",
    "public.documents", "documents.evidence_references"], operation);
}

async function seedHistoricalRf(database, companyId, ownerId, request) {
  const [previewId, entitlementId, approvalId, submissionId, forsendelseId, dialogId, shareholderId] = Array.from({ length: 7 }, randomUUID);
  const hash = createHash("sha256").update("local historical RF fixture").digest("hex");
  await rfFixtureTransaction(database, async () => {
    await database.query(`insert into shareholder_register_filing.filing_previews(id,company_id,income_year,filing,status,issues,preview,hovedskjema_xml,underskjema_xml,created_by)
      values($1,$2,2025,'aksjonærregisteroppgaven','ready','[]','Local historical RF fixture','<H>original</H>',$3::jsonb,$4)`,
      [previewId, companyId, JSON.stringify({ [shareholderId]: "<U>original</U>" }), ownerId]);
    // Historical recovery retains its original basis even after the pilot ends
    // and its old approval has been invalidated; it acquires no new entitlement.
    await database.query(`insert into billing.production_pilot_entitlements(id,company_id,user_id,income_year,obligation,case_profile,status,billing_exempt,
      system_user_request_id,system_user_external_reference,starts_at,expires_at,evidence_reference,approved_by)
      values($1,$2,$3,2025,'aksjonaerregisteroppgaven','rf1086_no_activity_v1','suspended',true,$4,$5,now()-interval '2 days',now()-interval '1 day','local-browser-historical',$3)`,
      [entitlementId, companyId, ownerId, request.id, request.external_ref]);
    await database.query(`insert into shareholder_register_filing.filing_approval_snapshots(id,entitlement_id,preview_id,company_id,user_id,income_year,obligation,case_profile,
      adapter_version,payload_hash,manifest_hash,manifest,approved_by,invalidated_at,invalidation_reason)
      values($1,$2,$3,$4,$5,2025,'aksjonaerregisteroppgaven','rf1086_no_activity_v1','rf1086-production-v1',$6,$6,'{"proof":"historical-local"}',$5,now(),'local historical proof')`,
      [approvalId, entitlementId, previewId, companyId, ownerId, hash]);
    await database.query(`insert into shareholder_register_filing.production_filing_submissions(id,approval_id,entitlement_id,company_id,user_id,income_year,obligation,case_profile,
      payload_hash,adapter_version,environment,status,authority_references,submitted_by,feedback_state,feedback_forsendelse_id)
      values($1,$2,$3,$4,$5,2025,'aksjonaerregisteroppgaven','rf1086_no_activity_v1',$6,'rf1086-production-v1','production','processing','{}',$5,'processing',$7)`,
      [submissionId, approvalId, entitlementId, companyId, ownerId, hash, forsendelseId]);
    await database.query(`insert into shareholder_register_filing.production_filing_events(submission_id,operation_name,operation_state,attempt,body_hash,idempotency_key,authority_reference,resulting_status)
      values($1,'confirm','succeeded',1,$2,$3,$4,'received')`, [submissionId, hash, randomUUID(), JSON.stringify({ dialogId, forsendelseId })]);
  });
  return { submissionId, forsendelseId };
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
