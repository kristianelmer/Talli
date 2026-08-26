import assert from "node:assert/strict";
import { createHmac, randomUUID } from "node:crypto";
import { existsSync, readFileSync } from "node:fs";
import { createServer } from "node:http";
import test from "node:test";

import { createClient } from "@supabase/supabase-js";
import { chromium } from "playwright";
import pg from "pg";

import {
  cleanupBrowserOwnerResources,
  cleanupFailure,
} from "./support/browser-owner-cleanup.mjs";
import {
  allocateLoopbackPort,
  startOwnedProcess,
  waitForOwnedReadiness,
} from "./support/owned-process-lifecycle.mjs";
import {
  isLoopbackPostgresUrl,
  isLoopbackSupabaseUrl,
} from "./support/supabase_fixture_safety.mjs";

loadDotEnv();

const supabaseUrl =
  process.env.NEXT_PUBLIC_SUPABASE_URL || process.env.SUPABASE_URL;
const serviceRoleKey = process.env.SUPABASE_SERVICE_ROLE_KEY;
const anonKey =
  process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY || process.env.SUPABASE_ANON_KEY;
const databaseUrl = process.env.DATABASE_URL;

test("a verified AAL1 owner completes accessible, fail-closed company onboarding through FastAPI", { timeout: 120_000 }, async (t) => {
  if (!supabaseUrl || !serviceRoleKey || !anonKey || !databaseUrl) {
    t.skip("Supabase env missing");
    return;
  }
  if (!isLoopbackSupabaseUrl(supabaseUrl) || !isLoopbackPostgresUrl(databaseUrl)) {
    t.skip("Browser onboarding fixtures require local Supabase");
    return;
  }

  const webPort = await allocateLoopbackPort();
  const backendPort = await allocateLoopbackPort();
  const brregPort = await allocateLoopbackPort();
  const baseUrl = `http://127.0.0.1:${webPort}`;
  const backendBaseUrl = `http://127.0.0.1:${backendPort}`;
  const brregBaseUrl = `http://127.0.0.1:${brregPort}`;
  const orgNumbers = {
    unsupported: "987654321",
    missing: "987654323",
    malformed: "987654324",
    supported: "987654322",
  };
  const brregRequests = [];
  const browserRequests = [];
  const admin = createClient(supabaseUrl, serviceRoleKey, {
    auth: { persistSession: false, autoRefreshToken: false },
  });
  const database = new pg.Client({ connectionString: databaseUrl });
  const resources = {
    admin,
    backend: undefined,
    browser: undefined,
    cleanupBackendDatabaseRole: undefined,
    companyId: undefined,
    database,
    databaseStarted: false,
    ownerId: undefined,
    primaryFailure: undefined,
    server: undefined,
  };
  const brreg = createBrregServer({ orgNumbers, requests: brregRequests });
  t.after(async () => {
    await new Promise((resolve) => brreg.close(() => resolve()));
    if (!resources.companyId && resources.ownerId && resources.databaseStarted) {
      try {
        const created = await database.query(
          "select id from public.companies where created_by = $1 order by created_at desc limit 1",
          [resources.ownerId],
        );
        resources.companyId = created.rows[0]?.id;
      } catch {
        // The shared cleanup helper reports any substantive teardown failure.
      }
    }
    const cleanupErrors = await cleanupBrowserOwnerResources(resources);
    const failure = cleanupFailure(resources.primaryFailure, cleanupErrors);
    if (failure) throw failure;
  });

  try {
    await new Promise((resolve, reject) => {
      brreg.once("error", reject);
      brreg.listen(brregPort, "127.0.0.1", resolve);
    });
    await database.connect();
    resources.databaseStarted = true;
    const backendDatabasePassword = randomUUID().replaceAll("-", "");
    const roleBoundary = await database.query(
      `select rolcanlogin, rolinherit, rolbypassrls,
        pg_catalog.pg_has_role('talli_company_access_backend', 'company_access_executor', 'set') as can_set_executor,
        pg_catalog.pg_has_role('talli_company_access_backend', 'company_access_recovery_executor', 'set') as can_set_recovery
       from pg_catalog.pg_roles where rolname = 'talli_company_access_backend'`,
    );
    assert.deepEqual(roleBoundary.rows, [{
      rolcanlogin: false,
      rolinherit: false,
      rolbypassrls: false,
      can_set_executor: true,
      can_set_recovery: true,
    }]);
    await database.query(
      `alter role talli_company_access_backend login password '${backendDatabasePassword}'`,
    );
    resources.cleanupBackendDatabaseRole = async () => {
      await database.query(
        "alter role talli_company_access_backend nologin password null",
      );
      resources.cleanupBackendDatabaseRole = undefined;
    };
    const backendDatabaseUrl = databaseUrlForBackendRole(
      databaseUrl,
      backendDatabasePassword,
    );
    const ownerEmail = `onboarding-${randomUUID()}@example.test`;
    const password = `Pw-${randomUUID()}-talli`;
    const { data: createdUser, error: createUserError } =
      await admin.auth.admin.createUser({
        email: ownerEmail,
        password,
        email_confirm: true,
      });
    assert.ifError(createUserError);
    assert.ok(createdUser.user.email_confirmed_at, "fixture user is not verified");
    resources.ownerId = createdUser.user.id;
    assert.equal(await actorState(database, resources.ownerId), "0:0:0:0:0");

    // Password sign-in establishes the same verified AAL1 authentication class
    // used by the browser flow; onboarding intentionally must not require AAL2.
    const sessionProbe = createClient(supabaseUrl, anonKey, {
      auth: { persistSession: false, autoRefreshToken: false },
    });
    const { data: probe, error: probeError } = await sessionProbe.auth.signInWithPassword({
      email: ownerEmail,
      password,
    });
    assert.ifError(probeError);
    const aal1AccessToken = probe.session.access_token;
    assert.equal(jwtPayload(aal1AccessToken).aal, "aal1");

    resources.backend = startBackendServer({
      anonKey,
      brregBaseUrl,
      databaseUrl: backendDatabaseUrl,
      port: backendPort,
      supabaseUrl,
    });
    await waitForOwnedReadiness({
      process: resources.backend,
      url: `${backendBaseUrl}/health/ready`,
    });
    const emptyContextResponse = await fetch(
      `${backendBaseUrl}/api/v1/company-access/context`,
      { headers: { Authorization: `Bearer ${aal1AccessToken}` } },
    );
    const emptyContext = await emptyContextResponse.json();
    assert.deepEqual(
      { status: emptyContextResponse.status, code: emptyContext.code },
      { status: 404, code: "COMPANY_CONTEXT_NOT_FOUND" },
      `verified no-company context failed closed incorrectly: ${JSON.stringify(emptyContext)}`,
    );
    resources.server = startNextServer({ backendBaseUrl, port: webPort });
    await waitForOwnedReadiness({ process: resources.server, url: baseUrl });

    resources.browser = await chromium.launch({ headless: true });
    const page = await resources.browser.newPage();
    page.on("request", (request) => browserRequests.push(request.url()));
    await page.goto(`${baseUrl}/login`);
    const loginForm = page.locator("form").filter({ hasText: "Logg inn" }).first();
    await loginForm.getByLabel("E-post").fill(ownerEmail);
    await loginForm.getByLabel("Passord").fill(password);
    await loginForm.getByRole("button", { name: "Logg inn" }).click();
    await page.waitForURL((url) => ["/dashboard", "/onboarding"].includes(url.pathname), {
      timeout: 20_000,
    });
    if (new URL(page.url()).pathname !== "/onboarding") {
      await page.goto(`${baseUrl}/onboarding`);
    }
    assert.equal(new URL(page.url()).pathname, "/onboarding");

    const authority = page.getByLabel("Jeg bekrefter at jeg har fullmakt", { exact: false });
    const orgNumber = page.getByLabel("Organisasjonsnummer");
    const submit = page.getByRole("button", { name: "Hent fra Brønnøysund" });
    await assertAccessibleInitialForm({ authority, orgNumber, page, submit });

    // Unsupported company type is a business rejection, while registry 404 and
    // malformed payloads are provider failures. Every path must remain zero-state.
    await submitCompany({ authority, orgNumber, orgNumberValue: orgNumbers.unsupported, page, submit });
    await assertAlertAndZeroState({ database, ownerId: resources.ownerId, page });
    assert.match(await errorAlert(page).innerText(), /kun AS/u);

    await page.goto(`${baseUrl}/onboarding`);
    await submitCompany({
      authority: page.getByLabel("Jeg bekrefter at jeg har fullmakt", { exact: false }),
      orgNumber: page.getByLabel("Organisasjonsnummer"),
      orgNumberValue: orgNumbers.missing,
      page,
      submit: page.getByRole("button", { name: "Hent fra Brønnøysund" }),
    });
    await assertAlertAndZeroState({ database, ownerId: resources.ownerId, page });

    await page.goto(`${baseUrl}/onboarding`);
    await submitCompany({
      authority: page.getByLabel("Jeg bekrefter at jeg har fullmakt", { exact: false }),
      keyboardSubmit: true,
      orgNumber: page.getByLabel("Organisasjonsnummer"),
      orgNumberValue: orgNumbers.malformed,
      page,
      submit: page.getByRole("button", { name: "Hent fra Brønnøysund" }),
    });
    await assertAlertAndZeroState({ database, ownerId: resources.ownerId, page });
    assert.match(await errorAlert(page).innerText(), /Brønnøysundregistrene/u);

    await page.goto(`${baseUrl}/onboarding`);
    await submitCompany({
      authority: page.getByLabel("Jeg bekrefter at jeg har fullmakt", { exact: false }),
      keyboardSubmit: true,
      orgNumber: page.getByLabel("Organisasjonsnummer"),
      orgNumberValue: orgNumbers.supported,
      page,
      submit: page.getByRole("button", { name: "Hent fra Brønnøysund" }),
    });
    await page.waitForURL((url) => url.pathname === "/mfa", { timeout: 20_000 });
    await page.getByRole("heading", {
      name: "Beskytt kontoen før du fortsetter",
    }).waitFor({ state: "visible" });
    assert.equal(await actorState(database, resources.ownerId), "1:1:1:1:1");
    const startMfa = page.getByRole("button", {
      name: "Sett opp autentiseringsapp",
    });
    await startMfa.click();
    const secret = (await page.locator("code").innerText()).trim();
    assert.match(secret, /^[A-Z2-7]+=*$/u);
    const mfaCode = page.getByLabel("Sekssifret kode");
    assert.equal(await mfaCode.getAttribute("inputmode"), "numeric");
    await mfaCode.fill(currentTotp(secret));
    await page.getByRole("button", { name: "Bekreft og fortsett" }).click();
    await page.waitForURL((url) => url.pathname === "/onboarding", {
      timeout: 20_000,
    });
    const browserSession = await browserSupabaseSession(page);
    assert.equal(jwtPayload(browserSession.access_token).sub, resources.ownerId);
    assert.equal(jwtPayload(browserSession.access_token).aal, "aal2");
    const restrictedMemberships = await membershipsAsBackendActor({
      accessToken: browserSession.access_token,
      databaseUrl: backendDatabaseUrl,
    });
    assert.deepEqual(restrictedMemberships, [{
      accepted: true,
      userId: resources.ownerId,
    }]);
    const selectedContextResponse = await fetch(
      `${backendBaseUrl}/api/v1/company-access/context`,
      { headers: { Authorization: `Bearer ${browserSession.access_token}` } },
    );
    const selectedContext = await selectedContextResponse.json();
    assert.equal(
      selectedContextResponse.status,
      200,
      `AAL2 selected context failed: ${JSON.stringify({
        status: selectedContextResponse.status,
        code: selectedContext.code,
      })}`,
    );
    assert.deepEqual(
      selectedContext.companies?.map((company) => company.companyId),
      [selectedContext.selectedCompanyId],
    );
    try {
      await page.getByRole("heading", { name: "Åpningsbalanse" }).waitFor({
        state: "visible",
        timeout: 10_000,
      });
    } catch {
      const state = await actorState(database, resources.ownerId);
      const body = (await page.locator("body").innerText()).replace(/\s+/gu, " ").trim();
      throw new Error(`supported_company_did_not_advance:state=${state}:body=${body.slice(0, 800)}`);
    }

    const created = await database.query(
      "select id, name, entity_type from public.companies where org_number = $1",
      [orgNumbers.supported],
    );
    assert.deepEqual(created.rows.map(({ name, entity_type: entityType }) => ({ name, entityType })), [
      { name: "Talli Browser Holding AS", entityType: "AS" },
    ]);
    resources.companyId = created.rows[0].id;
    assert.equal(await companyAtomicState(database, resources.companyId, resources.ownerId), "1:1:1:1:1");

    assert.deepEqual(
      brregRequests,
      Object.values(orgNumbers).map((org) => `/enhetsregisteret/api/enheter/${org}`),
    );
    for (const url of browserRequests) {
      assert.ok(isLoopbackUrl(url), `browser contacted a non-loopback service: ${url}`);
    }
  } catch (error) {
    resources.primaryFailure = error;
    throw error;
  }
});

async function assertAccessibleInitialForm({ authority, orgNumber, page, submit }) {
  try {
    await authority.waitFor({ state: "visible", timeout: 10_000 });
  } catch {
    const body = (await page.locator("body").innerText()).replace(/\s+/gu, " ").trim();
    throw new Error(`onboarding_form_unavailable:${body.slice(0, 800)}`);
  }
  assert.equal(await authority.isChecked(), false, "authority checkbox started checked");
  assert.equal(await authority.getAttribute("required"), "");
  const describedBy = await authority.getAttribute("aria-describedby");
  assert.ok(describedBy, "authority checkbox has no accessible description");
  assert.match(await page.locator(`#${describedBy}`).innerText(), /vilkår|avtale/iu);
  await orgNumber.waitFor({ state: "visible" });
  await submit.waitFor({ state: "visible" });
  await authority.focus();
  assert.equal(await authority.evaluate((element) => element === document.activeElement), true);
  await page.keyboard.press("Space");
  assert.equal(await authority.isChecked(), true, "Space did not check authority confirmation");
  await page.keyboard.press("Space");
  assert.equal(await authority.isChecked(), false, "Space did not restore unchecked state");
}

async function submitCompany({ authority, keyboardSubmit = false, orgNumber, orgNumberValue, page, submit }) {
  assert.equal(await authority.isChecked(), false, "fresh onboarding form retained consent");
  await authority.check();
  await orgNumber.fill(orgNumberValue);
  if (keyboardSubmit) {
    await orgNumber.press("Enter");
  } else {
    await submit.click();
  }
}

async function assertAlertAndZeroState({ database, ownerId, page }) {
  const alert = errorAlert(page);
  await alert.waitFor({ state: "visible", timeout: 20_000 });
  assert.ok((await alert.innerText()).trim().length > 0, "failure alert has no accessible text");
  assert.equal(await actorState(database, ownerId), "0:0:0:0:0");
}

function errorAlert(page) {
  return page.getByRole("alert").filter({ hasText: /\S/u }).last();
}

async function actorState(database, ownerId) {
  const result = await database.query(
    `select concat_ws(':',
      (select count(*) from public.companies where created_by = $1),
      (select count(*) from public.company_memberships where user_id = $1),
      (select count(*) from public.customer_agreement_acceptances where accepted_by = $1),
      (select count(*) from public.audit_events where actor_id = $1),
      (select count(*) from public.company_access_command_receipts where actor_id = $1)) as state`,
    [ownerId],
  );
  return result.rows[0].state;
}

async function companyAtomicState(database, companyId, ownerId) {
  const result = await database.query(
    `select concat_ws(':',
      (select count(*) from public.companies where id = $1 and created_by = $2),
      (select count(*) from public.company_memberships where company_id = $1 and user_id = $2 and role = 'owner' and accepted_at is not null),
      (select count(*) from public.customer_agreement_acceptances where company_id = $1 and accepted_by = $2),
      (select count(*) from public.audit_events where company_id = $1 and actor_id = $2 and action = 'workspace_created'),
      (select count(*) from public.company_access_command_receipts where company_id = $1 and actor_id = $2 and command_name = 'onboard_company')) as state`,
    [companyId, ownerId],
  );
  return result.rows[0].state;
}

function jwtPayload(token) {
  return JSON.parse(Buffer.from(token.split(".")[1], "base64url").toString("utf8"));
}

async function browserSupabaseSession(page) {
  const storageKey = `sb-${new URL(supabaseUrl).hostname.split(".")[0]}-auth-token`;
  const cookies = await page.context().cookies();
  const exact = cookies.find((cookie) => cookie.name === storageKey);
  const encoded = exact?.value ?? cookies
    .filter((cookie) => cookie.name.startsWith(`${storageKey}.`))
    .sort((left, right) =>
      Number(left.name.slice(storageKey.length + 1))
      - Number(right.name.slice(storageKey.length + 1)))
    .map((cookie) => cookie.value)
    .join("");
  assert.ok(encoded, "browser Supabase session cookie is absent after MFA");
  const serialized = encoded.startsWith("base64-")
    ? Buffer.from(encoded.slice("base64-".length), "base64url").toString("utf8")
    : encoded;
  const session = JSON.parse(serialized);
  assert.ok(session.access_token, "browser Supabase session cookie has no access token");
  return session;
}

async function membershipsAsBackendActor({ accessToken, databaseUrl: restrictedDatabaseUrl }) {
  const claims = jwtPayload(accessToken);
  const database = new pg.Client({ connectionString: restrictedDatabaseUrl });
  await database.connect();
  try {
    await database.query("begin");
    await database.query("set local role company_access_executor");
    await database.query(
      "select pg_catalog.set_config('talli.verified_actor_id', $1, true)",
      [claims.sub],
    );
    await database.query(
      "select pg_catalog.set_config('talli.verified_actor_claims', $1, true)",
      [JSON.stringify({
        aal: claims.aal,
        amr: claims.amr,
        email: claims.email,
        role: "authenticated",
        sub: claims.sub,
      })],
    );
    const result = await database.query(
      `select user_id as "userId", accepted_at is not null as accepted
       from public.company_memberships
       where user_id = public.company_access_auth_uid_v1()`,
    );
    await database.query("rollback");
    return result.rows;
  } finally {
    await database.end();
  }
}

function currentTotp(secret, now = Date.now()) {
  const alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567";
  let bits = "";
  for (const character of secret.toUpperCase().replaceAll("=", "")) {
    const value = alphabet.indexOf(character);
    assert.notEqual(value, -1, "MFA secret is not canonical base32");
    bits += value.toString(2).padStart(5, "0");
  }
  const key = Buffer.from(
    Array.from({ length: Math.floor(bits.length / 8) }, (_, index) =>
      Number.parseInt(bits.slice(index * 8, index * 8 + 8), 2),
    ),
  );
  const counter = Buffer.alloc(8);
  counter.writeBigUInt64BE(BigInt(Math.floor(now / 30_000)));
  const digest = createHmac("sha1", key).update(counter).digest();
  const offset = digest.at(-1) & 0x0f;
  const code = (digest.readUInt32BE(offset) & 0x7fffffff) % 1_000_000;
  return String(code).padStart(6, "0");
}

function databaseUrlForBackendRole(value, password) {
  const url = new URL(value);
  assert.ok(isLoopbackPostgresUrl(value), "backend database fixture escaped loopback");
  url.username = "talli_company_access_backend";
  url.password = password;
  return url.toString();
}

function isLoopbackUrl(value) {
  const hostname = new URL(value).hostname;
  return hostname === "127.0.0.1" || hostname === "localhost" || hostname === "[::1]";
}

function createBrregServer({ orgNumbers, requests }) {
  return createServer((request, response) => {
    requests.push(request.url ?? "");
    const orgNumber = request.url?.split("/").at(-1);
    if (orgNumber === orgNumbers.missing) {
      response.writeHead(404, { "Content-Type": "application/json" });
      response.end(JSON.stringify({ message: "not found" }));
      return;
    }
    if (orgNumber === orgNumbers.malformed) {
      response.writeHead(200, { "Content-Type": "application/json" });
      response.end(JSON.stringify({ organisasjonsnummer: orgNumber, navn: "" }));
      return;
    }
    if (![orgNumbers.supported, orgNumbers.unsupported].includes(orgNumber)) {
      response.writeHead(404, { "Content-Type": "application/json" }).end();
      return;
    }
    response.writeHead(200, { "Content-Type": "application/json" });
    response.end(JSON.stringify({
      organisasjonsnummer: orgNumber,
      navn: orgNumber === orgNumbers.supported
        ? "Talli Browser Holding AS"
        : "Talli Browser Enkeltpersonforetak",
      organisasjonsform: {
        kode: orgNumber === orgNumbers.supported ? "AS" : "ENK",
      },
      forretningsadresse: {
        adresse: ["Storgata 1"],
        postnummer: "0155",
        poststed: "OSLO",
      },
    }));
  });
}

function startBackendServer({ port, supabaseUrl: localSupabaseUrl, anonKey: localAnonKey, brregBaseUrl, databaseUrl: localDatabaseUrl }) {
  const backendPython =
    process.env.TALLI_BACKEND_PYTHON_BIN || "apps/backend/.venv/bin/python";
  if (!existsSync(backendPython)) throw new Error("backend_python_missing");
  const readinessNonce = randomUUID();
  return startOwnedProcess({
    command: backendPython,
    args: ["tests/fixtures/start_talli_backend.py"],
    cwd: process.cwd(),
    env: {
      PATH: process.env.PATH,
      BRREG_BASE_URL: brregBaseUrl,
      BRREG_TIMEOUT_SECONDS: "2",
      SUPABASE_URL: localSupabaseUrl,
      SUPABASE_ANON_KEY: localAnonKey,
      TALLI_COMPANY_ACCESS_DATABASE_URL: localDatabaseUrl,
      TALLI_BACKEND_PORT: String(port),
      TALLI_READINESS_NONCE: readinessNonce,
    },
    readinessProof: `TALLI_BACKEND_BOUND:${readinessNonce}`,
  });
}

function startNextServer({ port, backendBaseUrl }) {
  return startOwnedProcess({
    command: process.execPath,
    args: [
      "node_modules/next/dist/bin/next",
      "dev",
      "apps/web",
      "--hostname",
      "127.0.0.1",
      "--port",
      String(port),
    ],
    cwd: process.cwd(),
    env: {
      PATH: process.env.PATH,
      NODE_ENV: "test",
      NEXT_PUBLIC_SUPABASE_URL: supabaseUrl,
      NEXT_PUBLIC_SUPABASE_ANON_KEY: anonKey,
      SUPABASE_URL: supabaseUrl,
      SUPABASE_ANON_KEY: anonKey,
      TALLI_BACKEND_URL: backendBaseUrl,
    },
    readinessProof: "Ready in",
  });
}

function loadDotEnv() {
  if (!existsSync(".env")) return;
  for (const line of readFileSync(".env", "utf8").split(/\r?\n/u)) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith("#") || !trimmed.includes("=")) continue;
    const [key, ...valueParts] = trimmed.split("=");
    if (!process.env[key]) {
      process.env[key] = valueParts.join("=").replace(/^["']|["']$/gu, "");
    }
  }
}
