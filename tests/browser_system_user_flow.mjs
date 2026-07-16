import assert from "node:assert/strict";
import {
  createHash,
  createHmac,
  generateKeyPairSync,
  randomInt,
  randomUUID,
} from "node:crypto";
import { spawn, spawnSync } from "node:child_process";
import { createServer } from "node:net";
import { fileURLToPath } from "node:url";
import test from "node:test";

import { createClient } from "@supabase/supabase-js";
import { chromium } from "playwright";
import pg from "pg";

import { SYSTEM_USER_SYSTEM_ID } from "../app/lib/system-user-requests.ts";
import {
  installBrowserEgressGuard,
  LOOPBACK_HOSTS,
  startSystemUserAuthorityMock,
} from "./fixtures/system-user-authority-mock.mjs";

const ROOT = fileURLToPath(new URL("..", import.meta.url));
const MOCK_PRELOAD = fileURLToPath(
  new URL("./fixtures/system-user-authority-mock.mjs", import.meta.url),
);
const INCOME_YEAR = 2025;
const CALLBACK_PATH = "/auth/systembruker/confirm";
const PRODUCTION_SCOPE = "skatteetaten:innrapporteringaksjonaerregisteroppgave";

test("local browser proves the isolated RF-1086 Systembruker release flow", {
  timeout: 240_000,
}, async () => {
  assert.notEqual(process.env.TALLI_AUTHORITY_OPS_ENABLED, "true");
  assert.notEqual(process.env.TALLI_RF1086_PRODUCTION_ENABLED, "true");

  let localSupabase;
  let admin;
  let database;
  let fixture;
  let mock;
  let nextServer;
  let browser;
  const browserProblems = [];
  const browserEgressViolations = [];

  try {
    localSupabase = ensureLocalSupabase();
    admin = createClient(localSupabase.apiUrl, localSupabase.serviceRoleKey, {
      auth: { autoRefreshToken: false, persistSession: false },
    });
    database = new pg.Client({ connectionString: localSupabase.databaseUrl });
    await database.connect();
    fixture = await seedIdentityAndCompanies(admin, database, (partialFixture) => {
      fixture = partialFixture;
    });

    const port = await availablePort();
    const siteOrigin = `http://localhost:${port}`;
    mock = await startSystemUserAuthorityMock({ callbackOrigin: siteOrigin });
    mock.setTamperedCallbackRequestId(fixture.tamperedRequestId);

    nextServer = startNextServer({
      port,
      siteOrigin,
      mockBaseUrl: mock.baseUrl,
      localSupabase,
    });
    await waitForServer(siteOrigin);

    browser = await chromium.launch({ headless: true });
    const ownerContext = await browser.newContext({
      viewport: { width: 1440, height: 900 },
    });
    captureBrowserHealth(ownerContext, browserProblems);
    await installBrowserEgressGuard(ownerContext, {
      approvalEnabled: true,
      blockedRequests: browserEgressViolations,
      mockBaseUrl: mock.baseUrl,
    });
    const ownerPage = await ownerContext.newPage();

    await login(ownerPage, siteOrigin, fixture.ownerEmail, fixture.ownerPassword);
    await establishSyntheticAal2(ownerPage, siteOrigin);
    await assertNoError(
      admin.from("support_operators").delete().eq("user_id", fixture.ownerId),
    );

    await ownerPage.goto(`${siteOrigin}/connections?company=${fixture.primaryCompanyId}`);
    await ownerPage.getByRole("heading", { name: "Altinn-tilkobling" }).waitFor();
    await assertKeyboardFocusOrder(ownerPage, [
      "Oversikt",
      "Handlinger",
      "Transaksjoner",
      "Årsavslutning",
      "Innsending",
      "Tilkoblinger",
    ]);

    await ownerPage.getByRole("button", { name: "Opprett tilkobling" }).click();
    await ownerPage.getByRole("heading", { name: "Lokal Altinn-godkjenning" }).waitFor();
    await ownerPage.getByRole("button", { name: "Godkjenn lokal forespørsel" }).click();
    await ownerPage.getByText("Tilkoblingen er godkjent og verifisert", { exact: true }).waitFor();
    assert.equal(new URL(ownerPage.url()).searchParams.has("requestId"), false);

    const requestsAfterCallback = await database.query(
      `select id, company_id, status, preflight_verified_at, external_ref
        from public.system_user_requests
        where company_id = any($1::uuid[])`,
      [[fixture.primaryCompanyId, fixture.tamperedCompanyId]],
    );
    const primaryRequest = requestsAfterCallback.rows.find(
      (request) => request.company_id === fixture.primaryCompanyId,
    );
    const tamperedRequest = requestsAfterCallback.rows.find(
      (request) => request.id === fixture.tamperedRequestId,
    );
    assert.equal(primaryRequest?.status, "accepted");
    assert.ok(primaryRequest?.preflight_verified_at);
    assert.equal(tamperedRequest?.status, "new");

    await ownerPage.reload();
    await ownerPage.getByText("Tilkoblingen er godkjent og verifisert", { exact: true }).waitFor();
    await verifyConnectionsResponsiveViewports(ownerPage);

    const production = await seedProcessingProductionFiling(admin, fixture, primaryRequest);
    mock.setForsendelseId(production.forsendelseId);

    await ownerPage.setViewportSize({ width: 1440, height: 900 });
    await ownerPage.goto(`${siteOrigin}/filing/aksjonaerregisteroppgaven`);
    await ownerPage.getByRole("heading", { name: "Aksjonærregisteroppgaven" }).waitFor();
    const productionSection = ownerPage.locator("section").filter({
      has: ownerPage.getByRole("heading", { name: "Reell RF-1086-produksjonspilot" }),
    });
    await productionSection.getByText("Til behandling", { exact: true }).waitFor();
    await productionSection.getByRole("button", { name: "Sjekk status på nytt" }).click();
    await productionSection.getByText("Godkjent", { exact: true }).waitFor();
    await waitForDatabaseState(admin, production.submissionId, "accepted");

    await ownerPage.reload();
    await productionSection.getByText("Godkjent", { exact: true }).waitFor();
    await ownerPage.reload();
    await productionSection.getByText("Godkjent", { exact: true }).waitFor();

    const artifactResult = await admin
      .from("production_feedback_artifacts")
      .select("document_id,sha256")
      .eq("submission_id", production.submissionId)
      .single();
    assert.ifError(artifactResult.error);
    assert.ok(artifactResult.data);
    await verifyRf1086ResponsiveViewports(ownerPage);

    const feedbackHref = await productionSection
      .getByRole("link", { name: /Last ned tilbakemelding/u })
      .getAttribute("href");
    assert.equal(typeof feedbackHref, "string");
    const appDownloadUrl = new URL(feedbackHref, siteOrigin);
    const appDownload = await ownerContext.request.get(appDownloadUrl.href, {
      failOnStatusCode: false,
      maxRedirects: 0,
    });
    assert.equal(appDownload.status(), 307);
    const signedLocation = appDownload.headers().location;
    assert.equal(typeof signedLocation, "string");
    const signedUrl = new URL(signedLocation, appDownloadUrl);
    assert.equal(LOOPBACK_HOSTS.has(signedUrl.hostname), true);
    assert.equal(signedUrl.searchParams.has("token"), true);
    const signedDownload = await ownerContext.request.get(signedUrl.href, {
      failOnStatusCode: false,
      maxRedirects: 0,
    });
    assert.equal(signedDownload.status(), 200);
    assert.equal(signedDownload.url(), signedUrl.href);
    assert.equal(sha256(await signedDownload.body()), artifactResult.data.sha256);

    const otherContext = await browser.newContext({ viewport: { width: 1440, height: 900 } });
    captureBrowserHealth(otherContext, browserProblems);
    await installBrowserEgressGuard(otherContext, {
      approvalEnabled: false,
      blockedRequests: browserEgressViolations,
      mockBaseUrl: mock.baseUrl,
    });
    const otherPage = await otherContext.newPage();
    await login(otherPage, siteOrigin, fixture.otherOwnerEmail, fixture.otherOwnerPassword);
    await otherPage.goto(`${siteOrigin}/connections?company=${fixture.primaryCompanyId}`);
    await otherPage.getByRole("heading", { name: "Altinn-tilkobling" }).waitFor();
    assert.equal(await otherPage.getByText(fixture.primaryCompanyName, { exact: true }).count(), 0);
    assert.equal(
      await otherPage.getByText("Tilkoblingen er godkjent og verifisert", { exact: true }).count(),
      0,
    );
    const forbiddenArtifact = await otherContext.request.get(
      `${siteOrigin}/documents/${artifactResult.data.document_id}/download`,
      { failOnStatusCode: false, maxRedirects: 0 },
    );
    assert.equal(forbiddenArtifact.status(), 404);
    await otherContext.close();
    await ownerContext.close();

    assert.deepEqual(browserProblems, []);
    assert.deepEqual(browserEgressViolations, []);
    const calls = mock.snapshot();
    assert.equal(calls.some((call) => call.operation === "request_rejected"), false);
    for (const expected of [
      ["altinn", "create_request"],
      ["altinn", "approval_page"],
      ["altinn", "approve_request"],
      ["altinn", "read_request"],
      ["altinn", "query_system_user"],
      ["skatteetaten", "list_documents"],
      ["skatteetaten", "read_feedback"],
    ]) {
      assert.equal(
        calls.some((call) => call.service === expected[0] && call.operation === expected[1]),
        true,
      );
    }
    assert.equal(
      calls.some((call) => call.service === "skatteetaten" && call.operation.startsWith("post_")),
      false,
    );
    assert.notEqual(process.env.TALLI_AUTHORITY_OPS_ENABLED, "true");
    assert.notEqual(process.env.TALLI_RF1086_PRODUCTION_ENABLED, "true");

    process.stdout.write(
      "browser-system-user PASS: 320x900 + 1440x900; keyboard order verified; console warnings/errors 0; parent switches off; child filing adapter local-mock-only\n",
    );
  } finally {
    const cleanupErrors = [];
    if (browser) await teardownStep(() => browser.close(), cleanupErrors);
    if (nextServer) await teardownStep(() => stopServer(nextServer), cleanupErrors);
    if (mock) await teardownStep(() => mock.close(), cleanupErrors);
    if (admin && database && fixture) {
      await teardownStep(() => cleanupFixture(admin, database, fixture), cleanupErrors);
    }
    if (database) await teardownStep(() => database.end(), cleanupErrors);
    if (localSupabase?.startedHere) {
      await teardownStep(() => stopLocalSupabase(), cleanupErrors);
    }
    assert.notEqual(process.env.TALLI_AUTHORITY_OPS_ENABLED, "true");
    assert.notEqual(process.env.TALLI_RF1086_PRODUCTION_ENABLED, "true");
    if (cleanupErrors.length) throw cleanupErrors[0];
  }
});

async function seedIdentityAndCompanies(admin, database, retainFixtureForCleanup) {
  const ownerEmail = syntheticEmail("owner");
  const otherOwnerEmail = syntheticEmail("other-owner");
  const ownerPassword = syntheticPassword();
  const otherOwnerPassword = syntheticPassword();
  const owner = await admin.auth.admin.createUser({
    email: ownerEmail,
    password: ownerPassword,
    email_confirm: true,
  });
  assert.ifError(owner.error);
  const otherOwner = await admin.auth.admin.createUser({
    email: otherOwnerEmail,
    password: otherOwnerPassword,
    email_confirm: true,
  });
  if (otherOwner.error) {
    const ownerCleanup = await admin.auth.admin.deleteUser(owner.data.user.id);
    assert.ifError(ownerCleanup.error);
    assert.ifError(otherOwner.error);
  }

  const ids = {
    ownerId: owner.data.user.id,
    otherOwnerId: otherOwner.data.user.id,
    ownerEmail,
    otherOwnerEmail,
    ownerPassword,
    otherOwnerPassword,
    tamperedCompanyId: randomUUID(),
    primaryCompanyId: randomUUID(),
    otherCompanyId: randomUUID(),
    setupId: randomUUID(),
    shareholderId: randomUUID(),
    previewId: randomUUID(),
    tamperedRequestId: randomUUID(),
    primaryCompanyName: "Synthetic Browser Holding",
  };
  retainFixtureForCleanup(ids);
  const now = Date.now();

  await assertNoError(admin.from("companies").insert([
    companyRow({
      id: ids.tamperedCompanyId,
      ownerId: ids.ownerId,
      name: "Synthetic Callback Decoy",
      createdAt: new Date(now - 20_000).toISOString(),
    }),
    companyRow({
      id: ids.primaryCompanyId,
      ownerId: ids.ownerId,
      name: ids.primaryCompanyName,
      createdAt: new Date(now - 10_000).toISOString(),
    }),
    companyRow({
      id: ids.otherCompanyId,
      ownerId: ids.otherOwnerId,
      name: "Synthetic Isolated Holding",
      createdAt: new Date(now).toISOString(),
    }),
  ]));
  await assertNoError(admin.from("company_memberships").insert([
    membershipRow(ids.tamperedCompanyId, ids.ownerId),
    membershipRow(ids.primaryCompanyId, ids.ownerId),
    membershipRow(ids.otherCompanyId, ids.otherOwnerId),
  ]));
  await assertNoError(admin.from("support_operators").insert({
    user_id: ids.ownerId,
    role: "admin",
    active: true,
  }));

  const mainXml = syntheticXml("rf1086", syntheticXml("year", String(INCOME_YEAR)));
  const subXml = syntheticXml("rf1086u", syntheticXml("shares", "100"));
  await assertNoError(admin.from("opening_balance_setups").insert({
    id: ids.setupId,
    company_id: ids.primaryCompanyId,
    income_year: INCOME_YEAR,
    bank_balance: 30_000,
    share_capital: 30_000,
    share_count: 100,
    nominal_value: 300,
    created_by: ids.ownerId,
  }));
  await assertNoError(admin.from("opening_shareholders").insert({
    id: ids.shareholderId,
    setup_id: ids.setupId,
    company_id: ids.primaryCompanyId,
    name: "Synthetic owner",
    shareholder_kind: "norwegian_person",
    national_id: syntheticPersonalIdentifier(),
    share_count: 100,
    created_by: ids.ownerId,
  }));
  await assertNoError(admin.from("ledger_entries").insert({
    company_id: ids.primaryCompanyId,
    setup_id: ids.setupId,
    income_year: INCOME_YEAR,
    entry_type: "opening_balance",
    memo: "Synthetic opening balance",
    lines: [
      { account: "1920", debit: 30_000, credit: 0 },
      { account: "2000", debit: 0, credit: 30_000 },
    ],
    created_by: ids.ownerId,
  }));
  await assertNoError(admin.from("annual_data").insert({
    company_id: ids.primaryCompanyId,
    income_year: INCOME_YEAR,
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
    confirmations: [
      "bank_balance_confirmed",
      "general_meeting_approved",
      "authority_to_submit_confirmed",
      "no_activity_confirmed",
    ],
    no_activity_confirmed: true,
    completed_by: ids.ownerId,
    updated_by: ids.ownerId,
  }));
  await assertNoError(admin.from("billing_accounts").insert({
    company_id: ids.primaryCompanyId,
    pricing_plan: "founder",
    monthly_nok: 29,
    filing_package_nok: 299,
    founder_cohort_number: 1,
    subscription_active: true,
    filing_package_paid: true,
    supported_case: true,
    refund_eligible: false,
    refund_completed: false,
    no_charge_reason: null,
    updated_by: ids.ownerId,
  }));
  await assertNoError(admin.from("authority_permissions").insert({
    company_id: ids.primaryCompanyId,
    obligation: "aksjonaerregisteroppgaven",
    submitter_user_id: ids.ownerId,
    confirmed_by: ids.ownerId,
    production_enabled: true,
  }));
  await assertNoError(admin.from("filing_readiness_snapshots").insert({
    company_id: ids.primaryCompanyId,
    income_year: INCOME_YEAR,
    obligation: "aksjonaerregisteroppgaven",
    status: "ready",
    ready: true,
    hard_blocks: [],
    warnings: [],
    accepted_warnings: [],
    created_by: ids.ownerId,
  }));
  await assertNoError(admin.from("filing_previews").insert({
    id: ids.previewId,
    company_id: ids.primaryCompanyId,
    setup_id: ids.setupId,
    income_year: INCOME_YEAR,
    filing: "aksjonærregisteroppgaven",
    status: "ready",
    issues: [],
    preview: "Synthetic no-activity RF-1086 preview",
    hovedskjema_xml: mainXml,
    underskjema_xml: { [ids.shareholderId]: subXml },
    source: "browser_local_mock",
    created_by: ids.ownerId,
  }));
  await assertNoError(admin.from("authority_operations").insert({
    operation: "set_rf1086_systembruker_callback",
    actor_id: ids.ownerId,
    status: "succeeded",
    request_hash: sha256(Buffer.from(randomUUID())),
    result_code: "callback_already_verified",
    authority_http_status: 200,
    metadata: { systemId: SYSTEM_USER_SYSTEM_ID, callbackPath: CALLBACK_PATH },
    completed_at: new Date().toISOString(),
  }));

  const tamperedAltinnRequestId = randomUUID();
  await database.query(
    `insert into public.system_user_requests (
      id, company_id, initiating_owner_user_id, obligation, external_ref,
      altinn_request_id, status, confirm_url
    ) values ($1, $2, $3, $4, $5, $6, $7, $8)`,
    [
      ids.tamperedRequestId,
      ids.tamperedCompanyId,
      ids.ownerId,
      "aksjonaerregisteroppgaven",
      syntheticExternalRef(),
      tamperedAltinnRequestId,
      "new",
      `https://am.ui.altinn.no/accessmanagement/ui/systemuser/request?id=${tamperedAltinnRequestId}`,
    ],
  );
  return ids;
}

async function seedProcessingProductionFiling(admin, fixture, systemUserRequest) {
  assert.ok(systemUserRequest?.id && systemUserRequest?.external_ref);
  const entitlementId = randomUUID();
  const approvalId = randomUUID();
  const submissionId = randomUUID();
  const forsendelseId = randomUUID();
  const dialogId = randomUUID();
  const payloadHash = sha256(Buffer.from(randomUUID()));
  const manifestHash = sha256(Buffer.from(randomUUID()));

  await assertNoError(admin.from("production_pilot_entitlements").insert({
    id: entitlementId,
    company_id: fixture.primaryCompanyId,
    user_id: fixture.ownerId,
    income_year: INCOME_YEAR,
    obligation: "aksjonaerregisteroppgaven",
    case_profile: "rf1086_no_activity_v1",
    status: "active",
    billing_exempt: true,
    system_user_request_id: systemUserRequest.id,
    system_user_external_reference: systemUserRequest.external_ref,
    starts_at: new Date(Date.now() - 60_000).toISOString(),
    expires_at: new Date(Date.now() + 3_600_000).toISOString(),
    evidence_reference: "synthetic-local-browser-proof",
    approved_by: fixture.ownerId,
  }));
  await assertNoError(admin.from("filing_approval_snapshots").insert({
    id: approvalId,
    entitlement_id: entitlementId,
    preview_id: fixture.previewId,
    company_id: fixture.primaryCompanyId,
    user_id: fixture.ownerId,
    income_year: INCOME_YEAR,
    obligation: "aksjonaerregisteroppgaven",
    case_profile: "rf1086_no_activity_v1",
    adapter_version: "rf1086-production-v1",
    payload_hash: payloadHash,
    manifest_hash: manifestHash,
    manifest: { proof: "synthetic-local-only" },
    approved_by: fixture.ownerId,
  }));
  await assertNoError(admin.from("production_filing_submissions").insert({
    id: submissionId,
    approval_id: approvalId,
    entitlement_id: entitlementId,
    company_id: fixture.primaryCompanyId,
    user_id: fixture.ownerId,
    income_year: INCOME_YEAR,
    obligation: "aksjonaerregisteroppgaven",
    case_profile: "rf1086_no_activity_v1",
    payload_hash: payloadHash,
    adapter_version: "rf1086-production-v1",
    environment: "production",
    status: "processing",
    authority_references: {},
    submitted_by: fixture.ownerId,
    feedback_state: "processing",
    feedback_forsendelse_id: forsendelseId,
  }));
  await assertNoError(admin.from("production_filing_events").insert({
    submission_id: submissionId,
    operation_name: "confirm",
    operation_state: "succeeded",
    attempt: 1,
    body_hash: sha256(Buffer.from(randomUUID())),
    idempotency_key: randomUUID(),
    authority_reference: JSON.stringify({ dialogId, forsendelseId }),
    resulting_status: "received",
  }));
  return { submissionId, forsendelseId };
}

async function login(page, siteOrigin, email, password) {
  await page.goto(`${siteOrigin}/login`);
  const form = page.locator("form").filter({ hasText: "Logg inn" }).first();
  await form.getByLabel("E-post").fill(email);
  await form.getByLabel("Passord").fill(password);
  await form.getByRole("button", { name: "Logg inn" }).click();
  await page.waitForURL((url) => url.pathname === "/dashboard");
}

async function establishSyntheticAal2(page, siteOrigin) {
  await page.goto(`${siteOrigin}/operator`);
  const enrollmentResponsePromise = page.waitForResponse((response) =>
    response.request().method() === "POST"
      && new URL(response.url()).pathname.endsWith("/auth/v1/factors"));
  await page.getByRole("button", { name: "Sett opp autentiseringsapp" }).click();
  const enrollmentResponse = await enrollmentResponsePromise;
  const enrollment = await enrollmentResponse.json();
  const secret = enrollment?.totp?.secret;
  assert.equal(typeof secret, "string");
  assert.match(secret, /^[A-Z2-7]+$/iu);
  await page.getByLabel("Sekssifret kode").fill(totp(secret));
  await page.getByRole("button", { name: "Bekreft AAL2" }).click();
  await page.waitForURL((url) =>
    url.pathname === "/operator" && url.searchParams.get("authority") === "authority_mfa_ready");
  await page.getByText("Denne økten er bekreftet med AAL2.", { exact: true }).waitFor();
}

function captureBrowserHealth(context, browserProblems) {
  context.on("page", (page) => {
    page.on("console", (message) => {
      if (message.type() === "warning" || message.type() === "error") {
        browserProblems.push(
          `console_${message.type()}:${sanitizeBrowserDiagnostic(message.text())}`,
        );
      }
    });
    page.on("pageerror", () => browserProblems.push("page_error"));
  });
}

function sanitizeBrowserDiagnostic(value) {
  return value
    .replace(/https?:\/\/\S+/gu, "<url>")
    .replace(/[0-9a-f]{8}-[0-9a-f-]{27,}/giu, "<opaque-id>")
    .replace(/\b\d{9,11}\b/gu, "<synthetic-number>")
    .slice(0, 240);
}

async function assertKeyboardFocusOrder(page, accessibleNames) {
  for (const name of accessibleNames) {
    await page.keyboard.press("Tab");
    const focused = await page.getByRole("link", { name, exact: true }).evaluate(
      (element) => element === document.activeElement,
    );
    assert.equal(focused, true, `Keyboard focus did not reach ${name} in DOM order.`);
  }
}

async function verifyConnectionsResponsiveViewports(page) {
  await page.setViewportSize({ width: 320, height: 900 });
  await page.reload();
  await page.getByRole("heading", { name: "Altinn-tilkobling" }).waitFor();
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), true);
  await page.keyboard.press("Tab");
  assert.equal(
    await page.getByRole("button", { name: "Meny" }).evaluate(
      (element) => element === document.activeElement,
    ),
    true,
  );
  await page.keyboard.press("Enter");
  await page.getByRole("link", { name: "Tilkoblinger", exact: true }).waitFor();

  await page.setViewportSize({ width: 1440, height: 900 });
  await page.reload();
  await page.getByRole("heading", { name: "Altinn-tilkobling" }).waitFor();
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), true);
}

async function verifyRf1086ResponsiveViewports(page) {
  const focusControl = async (control, name) => {
    for (let attempt = 0; attempt < 80; attempt += 1) {
      await page.keyboard.press("Tab");
      if (await control.evaluate((element) => element === document.activeElement)) return;
    }
    assert.fail(`Keyboard focus did not reach ${name}.`);
  };

  for (const width of [320, 1440]) {
    await page.setViewportSize({ width, height: 900 });
    await page.reload();
    await page.getByRole("heading", { name: "Aksjonærregisteroppgaven" }).waitFor();
    const productionSection = page.locator("section").filter({
      has: page.getByRole("heading", { name: "Reell RF-1086-produksjonspilot" }),
    });
    await productionSection.getByText("Godkjent", { exact: true }).waitFor();
    const overflow = await page.evaluate(() => {
      if (document.documentElement.scrollWidth <= window.innerWidth) return [];
      return Array.from(document.body.querySelectorAll("*"))
        .filter((element) => {
          const rect = element.getBoundingClientRect();
          return rect.left < -0.5 || rect.right > window.innerWidth + 0.5;
        })
        .map((element) => ({
          className: String(element.className).slice(0, 80),
          tag: element.tagName.toLowerCase(),
        }))
        .slice(0, 12);
    });
    assert.deepEqual(overflow, []);
    assert.equal(
      await productionSection.evaluate((element) => element.scrollWidth <= element.clientWidth),
      true,
    );
    if (width === 320) {
      await page.keyboard.press("Tab");
      assert.equal(
        await page.getByRole("button", { name: "Meny" }).evaluate(
          (element) => element === document.activeElement,
        ),
        true,
      );
      await page.keyboard.press("Enter");
    }
    await focusControl(
      productionSection.getByRole("button", { name: "Sjekk status på nytt" }),
      "Sjekk status på nytt",
    );
    await focusControl(
      productionSection.getByRole("link", { name: /Last ned tilbakemelding/u }),
      "Last ned tilbakemelding",
    );
  }
}

async function waitForDatabaseState(admin, submissionId, expected) {
  const deadline = Date.now() + 20_000;
  while (Date.now() < deadline) {
    const result = await admin
      .from("production_filing_submissions")
      .select("feedback_state")
      .eq("id", submissionId)
      .single();
    if (!result.error && result.data?.feedback_state === expected) return;
    await protocolDelay(100);
  }
  throw new Error("database_state_deadline_exceeded");
}

function ensureLocalSupabase() {
  let status = supabaseCommand(["status", "--output", "env"]);
  let startedHere = false;
  if (status.status !== 0) {
    const started = supabaseCommand([
      "start",
      "--exclude",
      "studio,imgproxy,mailpit,logflare,vector,supavisor,postgres-meta,edge-runtime,realtime",
    ]);
    if (started.status !== 0) throw new Error("local_supabase_start_failed");
    startedHere = true;
    status = supabaseCommand(["status", "--output", "env"]);
  }
  if (status.status !== 0) throw new Error("local_supabase_status_failed");
  const environment = parseEnvironment(status.stdout);
  for (const name of ["API_URL", "ANON_KEY", "SERVICE_ROLE_KEY", "DB_URL"]) {
    if (!environment[name]) throw new Error("local_supabase_credentials_missing");
  }
  const api = new URL(environment.API_URL);
  assert.equal(api.hostname, "127.0.0.1");
  return {
    apiUrl: environment.API_URL,
    anonKey: environment.ANON_KEY,
    serviceRoleKey: environment.SERVICE_ROLE_KEY,
    databaseUrl: environment.DB_URL,
    startedHere,
  };
}

function stopLocalSupabase() {
  const stopped = supabaseCommand(["stop", "--no-backup"]);
  if (stopped.status !== 0) throw new Error("local_supabase_stop_failed");
}

function supabaseCommand(args) {
  return spawnSync("npm", ["exec", "--", "supabase", ...args], {
    cwd: ROOT,
    encoding: "utf8",
    maxBuffer: 10 * 1024 * 1024,
  });
}

function parseEnvironment(value) {
  return Object.fromEntries(value.split(/\r?\n/u).flatMap((line) => {
    const match = line.match(/^([A-Z0-9_]+)=(.*)$/u);
    if (!match) return [];
    const raw = match[2].trim();
    return [[match[1], raw.replace(/^['"]|['"]$/gu, "")]];
  }));
}

function startNextServer({ port, siteOrigin, mockBaseUrl, localSupabase }) {
  const privateKey = syntheticPrivateKey();
  const childEnvironment = Object.fromEntries(Object.entries({
    PATH: process.env.PATH,
    HOME: process.env.HOME,
    TMPDIR: process.env.TMPDIR,
    NODE_ENV: "development",
    NODE_OPTIONS: `--import=${MOCK_PRELOAD}`,
    NEXT_TELEMETRY_DISABLED: "1",
    SITE_URL: siteOrigin,
    NEXT_PUBLIC_SITE_URL: siteOrigin,
    NEXT_PUBLIC_SUPABASE_URL: localSupabase.apiUrl,
    NEXT_PUBLIC_SUPABASE_ANON_KEY: localSupabase.anonKey,
    SUPABASE_URL: localSupabase.apiUrl,
    SUPABASE_ANON_KEY: localSupabase.anonKey,
    SUPABASE_SERVICE_ROLE_KEY: localSupabase.serviceRoleKey,
    DATABASE_URL: localSupabase.databaseUrl,
    TALLI_LOCAL_AUTHORITY_MOCK_BASE_URL: mockBaseUrl,
    TALLI_AUTHORITY_OPS_ENABLED: "false",
    TALLI_RF1086_PRODUCTION_ENABLED: "true",
    TALLI_PROD_MASKINPORTEN_CLIENT_ID: randomUUID(),
    TALLI_PROD_MASKINPORTEN_KEY_ID: randomUUID(),
    TALLI_PROD_MASKINPORTEN_PRIVATE_KEY_PEM: privateKey,
    TALLI_PROD_RF1086_SCOPE: PRODUCTION_SCOPE,
  }).filter(([, value]) => value !== undefined));
  const server = spawn(
    process.execPath,
    ["node_modules/next/dist/bin/next", "dev", "--hostname", "127.0.0.1", "--port", String(port)],
    {
      cwd: ROOT,
      env: childEnvironment,
      detached: true,
      stdio: ["ignore", "pipe", "pipe"],
    },
  );
  server.stdout.resume();
  server.stderr.resume();
  return server;
}

async function waitForServer(origin) {
  const deadline = Date.now() + 45_000;
  while (Date.now() < deadline) {
    try {
      const response = await fetch(origin);
      if (response.ok) return;
    } catch {
      // Bounded local process startup polling.
    }
    await protocolDelay(250);
  }
  throw new Error("next_server_start_deadline_exceeded");
}

async function stopServer(server) {
  if (server.exitCode !== null || server.signalCode !== null) return;
  const exited = new Promise((resolve) => server.once("exit", resolve));
  try {
    process.kill(-server.pid, "SIGTERM");
  } catch {
    server.kill("SIGTERM");
  }
  const stopped = await Promise.race([
    exited.then(() => true),
    new Promise((resolve) => {
      const timer = setTimeout(() => resolve(false), 5_000);
      timer.unref?.();
    }),
  ]);
  if (!stopped && server.exitCode === null && server.signalCode === null) {
    try {
      process.kill(-server.pid, "SIGKILL");
    } catch {
      server.kill("SIGKILL");
    }
    await exited;
  }
}

async function cleanupFixture(admin, database, fixture) {
  const documents = await database.query(
    `select d.storage_key
      from public.documents d
      join public.production_feedback_artifacts a on a.document_id = d.id
      where a.company_id = $1`,
    [fixture.primaryCompanyId],
  );
  const storageKeys = documents.rows.map((document) => document.storage_key);
  if (storageKeys.length) {
    const removal = await admin.storage.from("company-documents").remove(storageKeys);
    assert.ifError(removal.error);
  }
  await database.query(
    `delete from public.production_filing_events
      where submission_id in (
        select id from public.production_filing_submissions where company_id = $1
      )`,
    [fixture.primaryCompanyId],
  );
  await database.query("delete from public.production_feedback_artifacts where company_id = $1", [
    fixture.primaryCompanyId,
  ]);
  await database.query("delete from public.production_filing_submissions where company_id = $1", [
    fixture.primaryCompanyId,
  ]);
  await database.query("delete from public.filing_approval_snapshots where company_id = $1", [
    fixture.primaryCompanyId,
  ]);
  await database.query("delete from public.production_pilot_entitlements where company_id = $1", [
    fixture.primaryCompanyId,
  ]);
  await database.query("delete from public.documents where company_id = $1", [
    fixture.primaryCompanyId,
  ]);
  await database.query("delete from public.system_user_requests where company_id = any($1::uuid[])", [[
    fixture.primaryCompanyId,
    fixture.tamperedCompanyId,
  ]]);
  await database.query("delete from public.authority_operations where actor_id = $1", [
    fixture.ownerId,
  ]);
  await database.query("delete from public.support_operators where user_id = $1", [
    fixture.ownerId,
  ]);
  const companyIds = [
    fixture.primaryCompanyId,
    fixture.tamperedCompanyId,
    fixture.otherCompanyId,
  ];
  await database.query("delete from public.companies where id = any($1::uuid[])", [companyIds]);
  const ownerDeletion = await admin.auth.admin.deleteUser(fixture.ownerId);
  assert.ifError(ownerDeletion.error);
  const otherOwnerDeletion = await admin.auth.admin.deleteUser(fixture.otherOwnerId);
  assert.ifError(otherOwnerDeletion.error);

  const residue = await database.query(
    `select
      (select count(*)::int from public.companies where id = any($1::uuid[])) as companies,
      (select count(*)::int from public.system_user_requests where company_id = any($1::uuid[])) as requests,
      (select count(*)::int from auth.users where id = any($2::uuid[])) as users,
      (select count(*)::int from storage.objects
        where bucket_id = 'company-documents' and name = any($3::text[])) as objects`,
    [companyIds, [fixture.ownerId, fixture.otherOwnerId], storageKeys],
  );
  assert.deepEqual(residue.rows[0], {
    companies: 0,
    requests: 0,
    users: 0,
    objects: 0,
  });
}

async function teardownStep(step, errors) {
  try {
    await step();
  } catch (error) {
    errors.push(error);
  }
}

function companyRow({ id, ownerId, name, createdAt }) {
  return {
    id,
    org_number: syntheticOrgNumber(),
    name,
    entity_type: "AS",
    address: "Synthetic local address",
    postal_code: "0001",
    city: "LOCAL",
    status_text: "active",
    source: "browser_local_mock",
    created_by: ownerId,
    identity_confirmed_at: createdAt,
    identity_locked_at: createdAt,
    created_at: createdAt,
  };
}

function membershipRow(companyId, userId) {
  return {
    company_id: companyId,
    user_id: userId,
    role: "owner",
    invited_by: userId,
    accepted_at: new Date().toISOString(),
  };
}

function syntheticEmail(prefix) {
  return `${prefix}-${randomUUID()}${String.fromCodePoint(64)}invalid.test`;
}

function syntheticPassword() {
  return `Local-${randomUUID()}-Aa1!`;
}

function syntheticOrgNumber() {
  return String((10 ** 8) + randomInt(9 * (10 ** 8)));
}

function syntheticPersonalIdentifier() {
  return String((10 ** 10) + randomInt(9 * (10 ** 10)));
}

function syntheticExternalRef() {
  return createHash("sha256").update(randomUUID()).digest("base64url").slice(0, 43);
}

function syntheticXml(name, content) {
  const left = String.fromCodePoint(60);
  const right = String.fromCodePoint(62);
  return `${left}${name}${right}${content}${left}/${name}${right}`;
}

function syntheticPrivateKey() {
  while (true) {
    const { privateKey } = generateKeyPairSync("rsa", {
      modulusLength: 2048,
      publicKeyEncoding: { type: "spki", format: "pem" },
      privateKeyEncoding: { type: "pkcs8", format: "pem" },
    });
    if (!/(?:test|tt02)/iu.test(privateKey)) return privateKey;
  }
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

function sha256(value) {
  return createHash("sha256").update(value).digest("hex");
}

async function assertNoError(query) {
  const { error } = await query;
  assert.ifError(error);
}

async function availablePort() {
  const server = createServer();
  await new Promise((resolve, reject) => {
    server.once("error", reject);
    server.listen(0, "127.0.0.1", resolve);
  });
  const address = server.address();
  assert.ok(address && typeof address === "object");
  await new Promise((resolve) => server.close(resolve));
  return address.port;
}

function protocolDelay(milliseconds) {
  return new Promise((resolve) => setTimeout(resolve, milliseconds));
}
