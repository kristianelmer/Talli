import assert from "node:assert/strict";
import { createHmac, randomUUID } from "node:crypto";
import { existsSync, readFileSync } from "node:fs";
import test from "node:test";

import { createClient } from "@supabase/supabase-js";
import { chromium } from "playwright";
import pg from "pg";

import {
  allocateLoopbackPort,
  startOwnedProcess,
  stopOwnedProcess,
  waitForOwnedReadiness,
} from "./support/owned-process-lifecycle.mjs";
import { isLoopbackSupabaseUrl } from "./support/supabase_fixture_safety.mjs";

loadDotEnv();

const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL || process.env.SUPABASE_URL;
const serviceRoleKey = process.env.SUPABASE_SERVICE_ROLE_KEY;
const anonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY || process.env.SUPABASE_ANON_KEY;
const databaseUrl = process.env.DATABASE_URL;

test("browser owner annual loop uses persisted state and survives reload", async (t) => {
  if (!supabaseUrl || !serviceRoleKey || !anonKey || !databaseUrl) {
    t.skip("Supabase env missing");
    return;
  }
  if (!isLoopbackSupabaseUrl(supabaseUrl)) {
    t.skip("Browser fixtures require local Supabase");
    return;
  }

  const port = await allocateLoopbackPort();
  const baseUrl = `http://127.0.0.1:${port}`;
  const backendPort = await allocateLoopbackPort();
  const backendBaseUrl = `http://127.0.0.1:${backendPort}`;
  const admin = createClient(supabaseUrl, serviceRoleKey, { auth: { persistSession: false } });
  const database = new pg.Client({ connectionString: databaseUrl });
  await database.connect();
  const ownerEmail = `owner-${randomUUID()}@example.test`;
  const password = `Pw-${randomUUID()}-talli`;
  const orgNumber = String(Math.floor(100000000 + Math.random() * 899999999));
  const companyId = randomUUID();
  const setupId = randomUUID();
  const shareholderId = randomUUID();
  const previewId = randomUUID();

  const { data: createdUser, error: createUserError } = await admin.auth.admin.createUser({
    email: ownerEmail,
    password,
    email_confirm: true,
  });
  assert.ifError(createUserError);
  const ownerId = createdUser.user.id;

  await seedAnnualLoop(admin, { companyId, setupId, shareholderId, previewId, ownerId, orgNumber });
  let backend;
  let server;
  let browser;
  t.after(async () => {
    await teardownAnnualLoop({ admin, database, companyId, ownerId, backend, server, browser });
  });

  backend = startBackendServer({
    port: backendPort,
    supabaseUrl,
    anonKey,
  });
  await waitForOwnedReadiness({
    process: backend,
    url: `${backendBaseUrl}/health/ready`,
  });

  server = startNextServer({ port, backendBaseUrl });

  await waitForOwnedReadiness({ process: server, url: baseUrl });
  browser = await chromium.launch({ headless: true });
  const page = await browser.newPage();

  // The public landing page moved to `/` in #90; authentication is a distinct
  // route and the browser rehearsal must exercise the real login surface.
  await page.goto(`${baseUrl}/login`);
  const loginForm = page.locator("form").filter({ hasText: "Logg inn" }).first();
  await loginForm.getByLabel("E-post").fill(ownerEmail);
  await loginForm.getByLabel("Passord").fill(password);
  await loginForm.getByRole("button", { name: "Logg inn" }).click();
  await page.waitForLoadState("networkidle");
  await establishSyntheticAal2(page, baseUrl);
  await page.goto(`${baseUrl}/dashboard`);
  await page.waitForLoadState("networkidle");

  if (process.env.TALLI_ANNUAL_WORKSPACE_ONLY === "1") {
    await page.goto(`${baseUrl}/companies/${companyId}/annual-reporting/2025`);
    await page.waitForLoadState("networkidle");
    await page.getByRole("heading", { name: "Årsrapportering" }).waitFor({ state: "visible", timeout: 15_000 });
    assert.equal(await page.locator("[data-obligation]").count(), 3);
    assert.deepEqual(
      await page.locator("[data-obligation]").evaluateAll((items) => items.map((item) => item.getAttribute("data-obligation"))),
      ["aksjonaerregisteroppgaven", "aarsregnskap", "skattemelding"],
    );
    await page.setViewportSize({ width: 390, height: 844 });
    assert.equal(await page.evaluate(() => document.body.scrollWidth <= window.innerWidth), true);
    const workspaceNav = page.getByRole("navigation", { name: "Arbeidsflate" });
    assert.equal(await workspaceNav.getByRole("link").count(), 6);
    assert.equal(
      await workspaceNav.evaluate((node) => node.scrollWidth <= node.clientWidth),
      true,
    );
    return;
  }

  await expectText(page, "Talli Browser Holding AS");
  await page.getByRole("heading", { name: "Årsrapportering" }).waitFor({ state: "visible", timeout: 15_000 });
  assert.equal(await page.locator("[data-obligation]").count(), 3);

  // The owner workflow tools now live under the /workspace route group (#90).
  await page.goto(`${baseUrl}/workspace`);
  await page.waitForLoadState("networkidle");

  await page.getByRole("button", { name: "Marker filingpakke betalt" }).click();
  await page.waitForLoadState("networkidle");
  await expectText(page, "Filing readiness må være klar før filingpakke kan betales.");

  await page.getByRole("button", { name: "Oppdater readiness" }).click();
  await page.waitForLoadState("networkidle");
  await page.reload();
  await page.waitForLoadState("networkidle");
  await expectText(page, "Klar for produksjonsinnsending");

  await page.getByRole("button", { name: "Marker filingpakke betalt" }).click();
  await page.waitForLoadState("networkidle");
  await page.getByLabel("Jeg bekrefter rett til å sende inn for selskapet.").check();
  await page.getByLabel("Jeg har kontrollert endelig forhåndsvisning.").check();
  await page.getByRole("button", { name: "Arkiver simulert kvittering" }).click();
  await page.waitForLoadState("networkidle");

  await expectText(page, "sim-rf1086-");
  await expectText(page, "Eksporter arkiv");
});

async function seedAnnualLoop(admin, ids) {
  const { companyId, setupId, shareholderId, previewId, ownerId, orgNumber } = ids;
  await assertNoError(
    admin.from("companies").insert({
      id: companyId,
      org_number: orgNumber,
      name: "Talli Browser Holding AS",
      entity_type: "AS",
      address: "Storgata 1",
      postal_code: "0155",
      city: "OSLO",
      status_text: "aktiv",
      source: "browser_test",
      created_by: ownerId,
      identity_confirmed_at: new Date().toISOString(),
      identity_locked_at: new Date().toISOString(),
    }),
  );
  await assertNoError(
    admin.from("company_memberships").insert({
      company_id: companyId,
      user_id: ownerId,
      role: "owner",
      invited_by: ownerId,
      accepted_at: new Date().toISOString(),
    }),
  );
  await assertNoError(
    admin.from("support_operators").insert({
      user_id: ownerId,
      role: "admin",
      active: true,
    }),
  );
  await assertNoError(
    admin.rpc("append_company_agreement_acceptance", {
      p_actor_id: ownerId,
      p_company_id: companyId,
      p_business_terms_version: "2026-07-17",
      p_business_terms_effective_date: "2026-07-17",
      p_business_terms_path: "/vilkar",
      p_business_terms_sha256: "f64a7f6a9758389fca8985a883a945d84c849f5b3316944621507db336992543",
      p_dpa_version: "2026-07-17",
      p_dpa_effective_date: "2026-07-17",
      p_dpa_path: "/databehandleravtale",
      p_dpa_sha256: "083ee63c1917ef227068befd7706ba2d636c52070ed4d880a8efae720528191c",
      p_authority_statement_version: "authority-v1",
      p_acceptance_method: "in_app_clickwrap",
    }),
  );
  await assertNoError(
    admin.from("opening_balance_setups").insert({
      id: setupId,
      company_id: companyId,
      income_year: 2025,
      bank_balance: 30000,
      share_capital: 30000,
      share_count: 100,
      nominal_value: 300,
      created_by: ownerId,
    }),
  );
  await assertNoError(
    admin.from("opening_shareholders").insert({
      id: shareholderId,
      setup_id: setupId,
      company_id: companyId,
      name: "Ola Nordmann",
      shareholder_kind: "norwegian_person",
      national_id: "01017012345",
      share_count: 100,
      created_by: ownerId,
    }),
  );
  await assertNoError(
    admin.from("ledger_entries").insert({
      company_id: companyId,
      setup_id: setupId,
      income_year: 2025,
      entry_type: "opening_balance",
      memo: "Åpningsbalanse",
      lines: [
        { account: "1920", debit: 30000, credit: 0 },
        { account: "2000", debit: 0, credit: 30000 },
      ],
      created_by: ownerId,
    }),
  );
  await assertNoError(
    admin.from("annual_data").insert({
      company_id: companyId,
      income_year: 2025,
      answers: {
        shares_owned_at_year_end: false,
        bought_or_sold_shares: false,
        received_dividends: false,
        declared_owner_dividends: false,
        shareholder_loans: false,
        paid_costs: false,
        bank_balance_confirmed: true,
        has_unpaid_items: false,
        general_meeting_approved: true,
        authority_to_submit_confirmed: true,
      },
      confirmations: ["bank_balance_confirmed", "general_meeting_approved", "authority_to_submit_confirmed", "no_activity_confirmed"],
      no_activity_confirmed: true,
      completed_by: ownerId,
      updated_by: ownerId,
    }),
  );
  await assertNoError(
    admin.from("billing_accounts").insert({
      company_id: companyId,
      pricing_plan: "founder",
      monthly_nok: 29,
      filing_package_nok: 299,
      founder_cohort_number: 1,
      subscription_active: true,
      filing_package_paid: false,
      supported_case: true,
      refund_eligible: false,
      no_charge_reason: null,
      updated_by: ownerId,
    }),
  );
  await assertNoError(
    admin.from("authority_permissions").insert([
      { company_id: companyId, obligation: "aksjonaerregisteroppgaven", submitter_user_id: ownerId, confirmed_by: ownerId, production_enabled: true },
      { company_id: companyId, obligation: "skattemelding", submitter_user_id: ownerId, confirmed_by: ownerId, production_enabled: true },
      { company_id: companyId, obligation: "aarsregnskap", submitter_user_id: ownerId, confirmed_by: ownerId, production_enabled: true },
    ]),
  );
  await assertNoError(
    admin.from("filing_previews").insert({
      id: previewId,
      company_id: companyId,
      setup_id: setupId,
      income_year: 2025,
      filing: "aksjonærregisteroppgaven",
      status: "ready",
      issues: [],
      preview: "RF-1086 forhåndsvisning for Talli Browser Holding AS",
      hovedskjema_xml: "<RF-1086><org>test</org></RF-1086>",
      underskjema_xml: { [shareholderId]: "<RF-1086U><shareholder>test</shareholder></RF-1086U>" },
      source: "browser_test",
      created_by: ownerId,
    }),
  );
}

async function teardownAnnualLoop({ admin, database, companyId, ownerId, backend, server, browser }) {
  const errors = [];
  for (const cleanup of [
    () => browser?.close(),
    () => stopOwnedProcess(server),
    () => stopOwnedProcess(backend),
    () => cleanupAnnualLoopFixture({ admin, database, companyId, ownerId }),
    () => database.end(),
  ]) {
    try {
      await cleanup();
    } catch (error) {
      errors.push(error);
    }
  }
  if (errors.length > 0) throw new AggregateError(errors, "annual_loop_teardown_failed");
}

async function cleanupAnnualLoopFixture({ admin, database, companyId, ownerId }) {
  const errors = [];
  try {
    await database.query("begin");
    await database.query("set local session_replication_role = replica");
    await database.query("delete from public.customer_agreement_acceptances where company_id = $1", [companyId]);
    await database.query("commit");
  } catch (error) {
    errors.push(error);
    try {
      await database.query("rollback");
    } catch (rollbackError) {
      errors.push(rollbackError);
    }
  }
  try {
    await assertNoError(admin.from("companies").delete().eq("id", companyId));
  } catch (error) {
    errors.push(error);
  }
  try {
    const { error } = await admin.auth.admin.deleteUser(ownerId);
    assert.ifError(error);
  } catch (error) {
    errors.push(error);
  }
  if (errors.length > 0) throw new AggregateError(errors, "annual_loop_fixture_cleanup_failed");
}

async function establishSyntheticAal2(page, baseUrl) {
  await page.goto(`${baseUrl}/operator`);
  const enrollmentResponsePromise = page.waitForResponse((response) => (
    response.request().method() === "POST"
    && new URL(response.url()).pathname.endsWith("/auth/v1/factors")
  ));
  await page.getByRole("button", { name: "Sett opp autentiseringsapp" }).click();
  const enrollment = await (await enrollmentResponsePromise).json();
  const secret = enrollment?.totp?.secret;
  assert.equal(typeof secret, "string");
  assert.match(secret, /^[A-Z2-7]+$/iu);
  await page.getByLabel("Sekssifret kode").fill(totp(secret));
  await page.getByRole("button", { name: "Bekreft AAL2" }).click();
  await page.waitForURL((url) => (
    url.pathname === "/operator" && url.searchParams.get("authority") === "authority_mfa_ready"
  ));
  await page.getByText("Denne økten er bekreftet med AAL2.", { exact: true }).waitFor();
}

function totp(secret) {
  const key = base32Decode(secret);
  const counter = BigInt(Math.floor(Date.now() / 30_000));
  const message = Buffer.alloc(8);
  message.writeBigUInt64BE(counter);
  const digest = createHmac("sha1", key).update(message).digest();
  const offset = digest.at(-1) & 0x0f;
  const number = (digest.readUInt32BE(offset) & 0x7fffffff) % 1_000_000;
  return String(number).padStart(6, "0");
}

function base32Decode(value) {
  const alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567";
  let bits = "";
  for (const character of value.toUpperCase().replace(/=+$/u, "")) {
    const index = alphabet.indexOf(character);
    assert.notEqual(index, -1);
    bits += index.toString(2).padStart(5, "0");
  }
  const bytes = [];
  for (let index = 0; index + 8 <= bits.length; index += 8) {
    bytes.push(Number.parseInt(bits.slice(index, index + 8), 2));
  }
  return Buffer.from(bytes);
}

function startBackendServer({ port, supabaseUrl: localSupabaseUrl, anonKey: localAnonKey }) {
  const backendPython = process.env.TALLI_BACKEND_PYTHON_BIN || "apps/backend/.venv/bin/python";
  if (!existsSync(backendPython)) {
    throw new Error("backend_python_missing");
  }
  return startOwnedProcess({
    command: backendPython,
    args: [
      "-m",
      "uvicorn",
      "talli_backend.main:app",
      "--app-dir",
      "apps/backend/src",
      "--host",
      "127.0.0.1",
      "--port",
      String(port),
    ],
    cwd: process.cwd(),
    env: {
      ...process.env,
      SUPABASE_URL: localSupabaseUrl,
      SUPABASE_ANON_KEY: localAnonKey,
    },
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
    env: { ...process.env, TALLI_BACKEND_URL: backendBaseUrl },
  });
}

async function expectText(page, text) {
  await page.getByText(text, { exact: false }).first().waitFor({ timeout: 15000 });
}

async function assertNoError(query) {
  const { error } = await query;
  assert.ifError(error);
}

function loadDotEnv() {
  if (!existsSync(".env")) return;
  for (const line of readFileSync(".env", "utf8").split(/\r?\n/)) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith("#") || !trimmed.includes("=")) continue;
    const [key, ...valueParts] = trimmed.split("=");
    if (!process.env[key]) {
      process.env[key] = valueParts.join("=").replace(/^["']|["']$/g, "");
    }
  }
}
