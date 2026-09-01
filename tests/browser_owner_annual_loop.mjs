import assert from "node:assert/strict";
import { createHash, createHmac, randomUUID } from "node:crypto";
import { existsSync, readFileSync } from "node:fs";
import { createRequire } from "node:module";
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
  ownedProcessDiagnostics,
  startOwnedProcess,
  waitForOwnedReadiness,
} from "./support/owned-process-lifecycle.mjs";
import {
  isLoopbackPostgresUrl,
  isLoopbackSupabaseUrl,
} from "./support/supabase_fixture_safety.mjs";

loadDotEnv();

const nextCli = createRequire(
  new URL("../apps/web/package.json", import.meta.url),
).resolve("next/dist/bin/next");

const supabaseUrl =
  process.env.NEXT_PUBLIC_SUPABASE_URL || process.env.SUPABASE_URL;
const serviceRoleKey = process.env.SUPABASE_SERVICE_ROLE_KEY;
const anonKey =
  process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY || process.env.SUPABASE_ANON_KEY;
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
  if (!isLoopbackPostgresUrl(databaseUrl)) {
    t.skip("Browser fixtures require local database");
    return;
  }

  const port = await allocateLoopbackPort();
  const baseUrl = `http://127.0.0.1:${port}`;
  const backendPort = await allocateLoopbackPort();
  const backendBaseUrl = `http://127.0.0.1:${backendPort}`;
  const admin = createClient(supabaseUrl, serviceRoleKey, {
    auth: { persistSession: false },
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
    storageKeys: [],
  };
  t.after(async () => {
    const cleanupErrors = await cleanupBrowserOwnerResources(resources);
    const failure = cleanupFailure(resources.primaryFailure, cleanupErrors);
    if (cleanupErrors.length > 0 && resources.primaryFailure) {
      t.diagnostic(
        `Cleanup encountered ${cleanupErrors.length} error(s) after the primary setup failure.`,
      );
    }
    if (failure) throw failure;
  });

  try {
    resources.databaseStarted = true;
    await database.connect();
    const backendDatabasePassword = randomUUID().replaceAll("-", "");
    const ledgerDatabasePassword = randomUUID().replaceAll("-", "");
    const bankingDatabasePassword = randomUUID().replaceAll("-", "");
    await database.query(
      `alter role talli_company_access_backend login password '${backendDatabasePassword}'`,
    );
    await database.query(
      `alter role talli_ledger_backend login password '${ledgerDatabasePassword}'`,
    );
    await database.query(
      `alter role talli_banking_backend login password '${bankingDatabasePassword}'`,
    );
    resources.cleanupBackendDatabaseRole = async () => {
      await database.query(
        "alter role talli_company_access_backend nologin password null",
      );
      await database.query(
        "alter role talli_ledger_backend nologin password null",
      );
      await database.query(
        "alter role talli_banking_backend nologin password null",
      );
      resources.cleanupBackendDatabaseRole = undefined;
    };
    const backendDatabaseUrl = databaseUrlForRole(
      databaseUrl,
      "talli_company_access_backend",
      backendDatabasePassword,
    );
    const ledgerDatabaseUrl = databaseUrlForRole(
      databaseUrl,
      "talli_ledger_backend",
      ledgerDatabasePassword,
    );
    const bankingDatabaseUrl = databaseUrlForRole(
      databaseUrl,
      "talli_banking_backend",
      bankingDatabasePassword,
    );
    const ownerEmail = `owner-${randomUUID()}@example.test`;
    const password = `Pw-${randomUUID()}-talli`;
    const orgNumber = String(Math.floor(100000000 + Math.random() * 899999999));
    const companyId = randomUUID();
    const setupId = randomUUID();
    const shareholderId = randomUUID();
    const previewId = randomUUID();

    const { data: createdUser, error: createUserError } =
      await admin.auth.admin.createUser({
        email: ownerEmail,
        password,
        email_confirm: true,
      });
    assert.ifError(createUserError);
    const ownerId = createdUser.user.id;
    resources.ownerId = ownerId;

    await seedAnnualLoop(
      admin,
      database,
      {
        companyId,
        setupId,
        shareholderId,
        previewId,
        ownerId,
        orgNumber,
      },
      () => {
        resources.companyId = companyId;
      },
    );
    await assertLedgerDatabaseBoundaries({
      companyId,
      databaseUrl: ledgerDatabaseUrl,
      ownerEmail,
      ownerId,
    });

    resources.backend = startBackendServer({
      port: backendPort,
      supabaseUrl,
      anonKey,
      databaseUrl: backendDatabaseUrl,
      bankingDatabaseUrl,
      ledgerDatabaseUrl,
    });
    await waitForOwnedReadiness({
      process: resources.backend,
      url: `${backendBaseUrl}/health/ready`,
    });

    resources.server = startNextServer({ port, backendBaseUrl });

    await waitForOwnedReadiness({ process: resources.server, url: baseUrl });
    resources.browser = await chromium.launch({ headless: true });
    const page = await resources.browser.newPage();

    // The public landing page moved to `/` in #90; authentication is a distinct
    // route and the browser rehearsal must exercise the real login surface.
    await page.goto(`${baseUrl}/login`);
    const loginForm = page
      .locator("form")
      .filter({ hasText: "Logg inn" })
      .first();
    await loginForm.getByLabel("E-post").fill(ownerEmail);
    await loginForm.getByLabel("Passord").fill(password);
    await loginForm.getByRole("button", { name: "Logg inn" }).click();
    await page.waitForLoadState("networkidle");
    await establishOwnerAal2(page, baseUrl);
    const ownerSession = await browserSupabaseSession(page);
    await assertLedgerReadBoundaries({
      accessToken: ownerSession.access_token,
      backendBaseUrl,
      companyId,
    });
    await page.goto(`${baseUrl}/dashboard`);
    await page.waitForLoadState("networkidle");

    if (process.env.TALLI_ANNUAL_WORKSPACE_ONLY === "1") {
      await page.goto(
        `${baseUrl}/companies/${companyId}/annual-reporting/2025`,
      );
      await page.waitForLoadState("networkidle");
      await page
        .getByRole("heading", { name: "Årsrapportering" })
        .waitFor({ state: "visible", timeout: 15_000 });
      assert.equal(await page.locator("[data-obligation]").count(), 3);
      assert.deepEqual(
        await page
          .locator("[data-obligation]")
          .evaluateAll((items) =>
            items.map((item) => item.getAttribute("data-obligation")),
          ),
        ["aksjonaerregisteroppgaven", "aarsregnskap", "skattemelding"],
      );
      await page.setViewportSize({ width: 390, height: 844 });
      assert.equal(
        await page.evaluate(
          () => document.body.scrollWidth <= window.innerWidth,
        ),
        true,
      );
      const workspaceNav = page.getByRole("navigation", {
        name: "Arbeidsflate",
      });
      assert.equal(await workspaceNav.getByRole("link").count(), 6);
      assert.equal(
        await workspaceNav.evaluate(
          (node) => node.scrollWidth <= node.clientWidth,
        ),
        true,
      );
      return;
    }

    await expectText(page, "Talli Browser Holding AS");
    await page
      .getByRole("heading", { name: "Årsrapportering" })
      .waitFor({ state: "visible", timeout: 15_000 });
    assert.equal(await page.locator("[data-obligation]").count(), 3);

    // The owner workflow tools now live under the /workspace route group (#90).
    await page.goto(`${baseUrl}/workspace`);
    await page.waitForLoadState("networkidle");

    await page
      .getByRole("button", { name: "Marker filingpakke betalt" })
      .click();
    await page.waitForLoadState("networkidle");
    await expectText(
      page,
      "Filing readiness må være klar før filingpakke kan betales.",
    );

    await page.getByRole("button", { name: "Oppdater readiness" }).click();
    await page.waitForLoadState("networkidle");
    await page.reload();
    await page.waitForLoadState("networkidle");
    await expectText(page, "Klar for produksjonsinnsending");

    await page
      .getByRole("button", { name: "Marker filingpakke betalt" })
      .click();
    await page.waitForLoadState("networkidle");
    await page
      .getByLabel("Jeg bekrefter rett til å sende inn for selskapet.")
      .check();
    await page
      .getByLabel("Jeg har kontrollert endelig forhåndsvisning.")
      .check();
    await page
      .getByRole("button", { name: "Arkiver simulert kvittering" })
      .click();
    await page.waitForLoadState("networkidle");

    await expectText(page, "sim-rf1086-");
    await expectText(page, "Eksporter arkiv");

    await seedSupportedInvestmentYear(database, {
      companyId,
      ownerId,
      orgNumber,
    });
    const investmentEvidence = await seedInvestmentEvidence(
      admin,
      database,
      { companyId, ownerId, storageKeys: resources.storageKeys },
    );
    await exerciseMobileInvestmentCorrection({
      companyId,
      database,
      evidence: investmentEvidence,
      page,
      baseUrl,
    });

  } catch (error) {
    const diagnostics = new Error(
      `${error instanceof Error ? error.message : String(error)}\n`
        + `web=${ownedProcessDiagnostics(resources.server)}\n`
        + `backend=${ownedProcessDiagnostics(resources.backend)}`,
      { cause: error },
    );
    resources.primaryFailure = diagnostics;
    throw diagnostics;
  }
});

async function seedSupportedInvestmentYear(
  database,
  { companyId, ownerId, orgNumber },
) {
  const eligibilityAssessmentId = randomUUID();
  const eligibilityOperationId = randomUUID();
  const companyYearAdmissionId = randomUUID();
  const companyYearAcceptanceId = randomUUID();
  const capabilityManifestSha256 =
    "9f91a66d0e2cb560d880b6b290c707bc45a8d117a4175780c75e2d1ccdb694de";
  await database.query(
    `insert into public.company_eligibility_assessments (
      id, company_id, accounting_year, operation_id, trigger, decision,
      capability_manifest, capability_manifest_version,
      capability_manifest_sha256, public_facts, public_facts_sha256,
      answers, answers_sha256, reason_codes, reason_explanations,
      next_step_code, next_step, consequential_operations_allowed,
      archive_export_available, evaluator_version, assessed_by, assessed_at
    ) values (
      $1, $2, 2026, $3, 'initial_admission', 'supported', '{}'::jsonb,
      '2026.1', $4, '{}'::jsonb, repeat('a', 64),
      '{"supported":true}'::jsonb, repeat('b', 64), '{}'::text[],
      '{}'::text[], 'CREATE_ACCOUNT_AND_ACCEPT', 'Browser fixture admission.',
      true, true, '2026.1', $5, now()
    )`,
    [
      eligibilityAssessmentId,
      companyId,
      eligibilityOperationId,
      capabilityManifestSha256,
      ownerId,
    ],
  );
  await database.query(
    `insert into public.company_year_admissions (
      id, company_id, accounting_year, eligibility_assessment_id,
      capability_manifest, capability_manifest_version,
      capability_manifest_sha256, company_year_promise,
      company_year_promise_sha256, reconstruct_from, admitted_by, admitted_at
    ) values (
      $1, $2, 2026, $3, '{}'::jsonb, '2026.1', $4, '{}'::jsonb,
      repeat('c', 64), date '2026-01-01', $5, now()
    )`,
    [
      companyYearAdmissionId,
      companyId,
      eligibilityAssessmentId,
      capabilityManifestSha256,
      ownerId,
    ],
  );
  await database.query(
    `insert into public.company_year_acceptances (
      id, company_year_admission_id, company_id, accounting_year, accepted_by,
      customer_legal_name, customer_org_number,
      business_terms_version, business_terms_effective_date,
      business_terms_path, business_terms_sha256,
      dpa_version, dpa_effective_date, dpa_path, dpa_sha256,
      privacy_notice_version, privacy_notice_effective_date,
      privacy_notice_path, privacy_notice_sha256,
      capability_manifest_version, capability_manifest_sha256,
      authority_statement_version, acceptance_method, accepted_at
    ) values (
      $1, $2, $3, 2026, $4, 'Talli Browser Holding AS', $5,
      '2026-08-30', date '2026-08-30', '/vilkar',
      'afc6fc3610f05056f3de8cc849a33accbf3bdff7d469aef8be57c5ccbe074c04',
      '2026-08-30', date '2026-08-30', '/databehandleravtale',
      '1f5c45a882db79fb248bdff92bd1a245e97b9a7a2f174b943b761f67bda4b94a',
      '2026-08-30', date '2026-08-30', '/personvern',
      '041a65be9f020c037bd65b7097e04afdbeb2c944ef45d7bef3dd380e92f907de',
      '2026.1', $6, 'authority-v1', 'in_app_clickwrap', now()
    )`,
    [
      companyYearAcceptanceId,
      companyYearAdmissionId,
      companyId,
      ownerId,
      orgNumber,
      capabilityManifestSha256,
    ],
  );
}

async function exerciseMobileInvestmentCorrection({
  companyId,
  database,
  evidence,
  page,
  baseUrl,
}) {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(`${baseUrl}/actions/share-purchase`);
  await page.waitForLoadState("networkidle");
  await page.getByLabel("Type investering").selectOption("norwegian_equity_fund");
  await page.getByLabel("Selskapet du kjøper i").fill("Talli Browser Fond");
  await page.getByLabel("ISIN").fill("NO0000000001");
  await page.getByLabel("Kjøpsdato").fill("2026-03-01");
  await page.getByLabel("Antall aksjer").fill("100");
  await page.getByLabel("Kjøpsbeløp (kr)").fill("10000.00");
  await page.getByLabel("Transaksjonskostnader (kr)").fill("25.00");
  await page.getByLabel("Aksjeandel ved kjøp (basispoeng)").fill("6500");
  await page
    .getByLabel("Referanse til fondets skatteoppgave")
    .fill("browser-fund-tax-2026");
  await page.locator('input[name="investmentBoundaryConfirmed"]').check();
  await page.locator('select[name="documentId"]')
    .selectOption(evidence.purchaseDocumentId);
  await page.locator('input[name="evidenceReference"]')
    .fill("browser-broker-purchase-1");
  await page.locator('input[name="ownerAttested"]').check();
  const originalActionId = await page
    .locator('input[name="operationId"]')
    .inputValue();
  assert.equal(await page.evaluate(() => document.body.scrollWidth <= innerWidth), true);
  await page.getByRole("button", { name: "Bekreft og bokfør" }).click();
  await page.waitForLoadState("networkidle");
  await expectText(page, "Handlingen er bokført");

  await page.goto(`${baseUrl}/actions/investment-correction`);
  await page.waitForLoadState("networkidle");
  await page.getByLabel("Hendelse som skal korrigeres").selectOption({
    label: "2026-03-01 · Talli Browser Fond",
  });
  const preservedName = page.getByLabel("Investeringsnavn");
  assert.equal(await preservedName.inputValue(), "Talli Browser Fond");
  assert.equal(await preservedName.getAttribute("readonly"), "");
  await page.getByLabel("Kjøpsbeløp (kr)").fill("12000.00");
  await page.locator('input[name="investmentBoundaryConfirmed"]').check();
  await page.getByLabel("Korrigeringsdato").fill("2026-12-30");
  await page.getByLabel("Begrunnelse").fill("Korrigert kjøpsbeløp mot meglernota");
  await page.locator('select[name="documentId"]')
    .selectOption(evidence.purchaseDocumentId);
  await page.locator('input[name="evidenceReference"]')
    .fill("browser-correction-note-1");
  await page.locator('input[name="ownerAttested"]').check();
  await page.locator('select[name="replacementDocumentId"]')
    .selectOption(evidence.replacementDocumentId);
  await page.locator('input[name="replacementEvidenceReference"]')
    .fill("browser-broker-purchase-2");
  await page.locator('input[name="replacementOwnerAttested"]').check();
  const replacementActionId = await page
    .locator('input[name="replacementActionId"]')
    .inputValue();
  assert.equal(await page.evaluate(() => document.body.scrollWidth <= innerWidth), true);
  await page.getByRole("button", { name: "Reverser og erstatt" }).click();
  await page.waitForLoadState("networkidle");
  await expectText(page, "Handlingen er bokført");

  await page.goto(`${baseUrl}/actions/investment-settlement`);
  await page.waitForLoadState("networkidle");
  await page
    .getByLabel("Hendelse som skal avstemmes")
    .selectOption(replacementActionId);
  await page.getByLabel("Oppgjørsdato").fill("2026-03-15");
  await page.locator('select[name="bankTransactionId"]')
    .selectOption(evidence.purchaseBankId);
  await page
    .getByLabel("Bank- eller oppgjørsreferanse")
    .fill("browser-purchase-payment-1");
  const purchaseSettlementId = await page
    .locator('input[name="operationId"]')
    .inputValue();
  await page.getByRole("button", { name: "Avstem kontantoppgjør" }).click();
  await page.waitForLoadState("networkidle");
  await expectText(page, "Handlingen er bokført");

  await page.goto(`${baseUrl}/actions/fund-distribution`);
  await page.waitForLoadState("networkidle");
  await page.locator('select[name="positionId"]').selectOption({
    label: "Talli Browser Fond",
  });
  await page.getByLabel("Rettighetsdato").fill("2026-06-01");
  await page.getByLabel("Brutto utdeling (kr)").fill("1000.00");
  await page
    .getByLabel("Aksjeandel ved årets start (basispoeng)")
    .fill("6500");
  await page
    .getByLabel("Referanse til fondets skatteoppgave")
    .fill("browser-fund-tax-2026");
  await page.locator('select[name="documentId"]')
    .selectOption(evidence.distributionDocumentId);
  await page.locator('input[name="evidenceReference"]')
    .fill("browser-fund-entitlement-1");
  await page.locator('input[name="ownerAttested"]').check();
  const distributionActionId = await page
    .locator('input[name="operationId"]')
    .inputValue();
  await page.getByRole("button", { name: "Poster fondsutdeling" }).click();
  await page.waitForLoadState("networkidle");
  await expectText(page, "Handlingen er bokført");

  await page.goto(`${baseUrl}/actions/investment-settlement`);
  await page.waitForLoadState("networkidle");
  await page
    .getByLabel("Hendelse som skal avstemmes")
    .selectOption(distributionActionId);
  await page.getByLabel("Oppgjørsdato").fill("2026-06-15");
  await page
    .locator('select[name="bankTransactionId"]')
    .selectOption(evidence.distributionBankId);
  await page
    .getByLabel("Bank- eller oppgjørsreferanse")
    .fill("browser-fund-payment-1");
  const distributionSettlementId = await page
    .locator('input[name="operationId"]')
    .inputValue();
  await page.getByRole("button", { name: "Avstem kontantoppgjør" }).click();
  await page.waitForLoadState("networkidle");
  await expectText(page, "Handlingen er bokført");
  await page.reload();
  await page.waitForLoadState("networkidle");
  assert.equal(await page.evaluate(() => document.body.scrollWidth <= innerWidth), true);

  const persisted = await database.query(
    `select
       (select count(*)::integer from investments.economic_events
        where company_id = $1) as economic_events,
       (select count(*)::integer from investments.cash_settlements
        where company_id = $1) as cash_settlements,
       (select count(*)::integer from investments.lifecycle_corrections
        where company_id = $1) as lifecycle_corrections,
       (select count(*)::integer from investments.share_purchases
        where company_id = $1) as legacy_purchases,
       (select count(*)::integer from investments.received_fund_distributions
        where company_id = $1) as legacy_distributions,
       (select count(*)::integer from investments.corrections
        where company_id = $1) as legacy_corrections,
       (select count(*)::integer from ledger.entries
        where company_id = $1 and source_capability = 'INVESTMENTS'
          and source_record_id in ($2, $3, $4, $5, $6)) as lifecycle_entries`,
    [
      companyId,
      originalActionId,
      replacementActionId,
      purchaseSettlementId,
      distributionActionId,
      distributionSettlementId,
    ],
  );
  assert.deepEqual(persisted.rows[0], {
    economic_events: 3,
    cash_settlements: 2,
    lifecycle_corrections: 1,
    legacy_purchases: 0,
    legacy_distributions: 0,
    legacy_corrections: 0,
    lifecycle_entries: 5,
  });
}

async function seedInvestmentEvidence(
  admin,
  database,
  { companyId, ownerId, storageKeys },
) {
  const documents = [
    ["purchaseDocumentId", "browser-purchase-contract.pdf"],
    ["replacementDocumentId", "browser-purchase-correction.pdf"],
    ["distributionDocumentId", "browser-fund-entitlement.pdf"],
  ];
  const result = {};
  for (const [key, name] of documents) {
    const documentId = randomUUID();
    const storageKey = `${companyId}/2026/${documentId}/${name}`;
    const pdf = Buffer.from(
      `%PDF-1.4\n% Talli browser evidence ${documentId}\n1 0 obj<<>>endobj\n%%EOF\n`,
      "utf8",
    );
    const { error: uploadError } = await admin.storage
      .from("company-documents")
      .upload(storageKey, pdf, {
        contentType: "application/pdf",
        upsert: false,
      });
    assert.ifError(uploadError);
    storageKeys.push(storageKey);
    await assertNoError(admin.from("documents").insert({
      id: documentId,
      company_id: companyId,
      income_year: 2026,
      document_type: "investment_evidence",
      name,
      linked_to: "investments",
      status: "attached",
      retention_years: 5,
      storage_key: storageKey,
      created_by: ownerId,
    }));
    result[key] = documentId;
  }

  const purchaseBankId = randomUUID();
  const distributionBankId = randomUUID();
  await database.query("begin");
  try {
    await database.query(`do $browser_owner_banking_authority$
      begin
        execute pg_catalog.format(
          'grant banking_store_owner to %I', current_user
        );
      end
      $browser_owner_banking_authority$`);
    await database.query("set local role banking_store_owner");
    await database.query(
      `select
         pg_catalog.set_config('request.jwt.claim.sub', $1, true),
         pg_catalog.set_config('request.jwt.claims', $2, true)`,
      [ownerId, JSON.stringify({ sub: ownerId, aal: "aal2" })],
    );
    await database.query(
      `insert into banking.transactions (
         id, company_id, income_year, transaction_date, text, amount, balance,
         source_hash, created_by
       ) values
         ($1, $2, 2026, date '2026-03-15', 'Purchase settlement', -12025.00,
          25000.00, $3, $4),
         ($5, $2, 2026, date '2026-06-15', 'Fund distribution', 1000.00,
          26000.00, $6, $4)`,
      [
        purchaseBankId,
        companyId,
        createHash("sha256").update("browser-purchase-bank-v1").digest("hex"),
        ownerId,
        distributionBankId,
        createHash("sha256").update("browser-distribution-bank-v1").digest("hex"),
      ],
    );
    await database.query("reset role");
    await database.query(`do $browser_owner_banking_authority$
      begin
        execute pg_catalog.format(
          'revoke banking_store_owner from %I', current_user
        );
      end
      $browser_owner_banking_authority$`);
    await database.query("commit");
  } catch (error) {
    await database.query("rollback");
    throw error;
  }
  return {
    ...result,
    purchaseBankId,
    distributionBankId,
  };
}

async function seedAnnualLoop(admin, database, ids, onCompanyCreated) {
  const { companyId, setupId, shareholderId, previewId, ownerId, orgNumber } =
    ids;
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
  onCompanyCreated();
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
  await database.query(
    `insert into public.customer_agreement_acceptances(
      company_id, accepted_by, customer_legal_name, customer_org_number,
      business_terms_version, business_terms_effective_date,
      business_terms_path, business_terms_sha256,
      dpa_version, dpa_effective_date, dpa_path, dpa_sha256,
      authority_statement_version, acceptance_method, accepted_at
    ) values (
      $1, $2, 'Talli Browser Holding AS', $3,
      '2026-08-30', date '2026-08-30', '/vilkar',
      'afc6fc3610f05056f3de8cc849a33accbf3bdff7d469aef8be57c5ccbe074c04',
      '2026-08-30', date '2026-08-30', '/databehandleravtale',
      '1f5c45a882db79fb248bdff92bd1a245e97b9a7a2f174b943b761f67bda4b94a',
      'authority-v1', 'in_app_clickwrap', now()
    )`,
    [companyId, ownerId, orgNumber],
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
  await database.query(
    String.raw`
      insert into ledger.entries (
        company_id, setup_id, income_year, entry_kind, memo, lines, created_by,
        source_capability, source_record_id, correlation_id
      ) values ($1, $2, 2025, 'OPENING_BALANCE', 'Åpningsbalanse', $3::jsonb, $4,
        'SHAREHOLDER_REGISTER_FILING', $5, $6)
    `,
    [
      companyId,
      setupId,
      JSON.stringify([
        {
          account: "1920",
          description: "Bankinnskudd",
          debit: "30000.00",
          credit: "0.00",
          currency: "NOK",
        },
        {
          account: "2000",
          description: "Aksjekapital",
          debit: "0.00",
          credit: "30000.00",
          currency: "NOK",
        },
      ]),
      ownerId,
      `opening-setup:${setupId}`,
      `browser-fixture:${setupId}`,
    ],
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
      confirmations: [
        "bank_balance_confirmed",
        "general_meeting_approved",
        "authority_to_submit_confirmed",
        "no_activity_confirmed",
      ],
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
      {
        company_id: companyId,
        obligation: "aksjonaerregisteroppgaven",
        submitter_user_id: ownerId,
        confirmed_by: ownerId,
        production_enabled: true,
      },
      {
        company_id: companyId,
        obligation: "skattemelding",
        submitter_user_id: ownerId,
        confirmed_by: ownerId,
        production_enabled: true,
      },
      {
        company_id: companyId,
        obligation: "aarsregnskap",
        submitter_user_id: ownerId,
        confirmed_by: ownerId,
        production_enabled: true,
      },
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
      underskjema_xml: {
        [shareholderId]: "<RF-1086U><shareholder>test</shareholder></RF-1086U>",
      },
      source: "browser_test",
      created_by: ownerId,
    }),
  );
}

async function establishOwnerAal2(page, baseUrl) {
  await page.goto(`${baseUrl}/mfa?next=%2Fdashboard`);
  await page.getByRole("heading", {
    name: "Beskytt kontoen før du fortsetter",
  }).waitFor({ state: "visible" });
  await page
    .getByRole("button", { name: "Sett opp autentiseringsapp" })
    .click();
  const secret = (await page.locator("code").innerText()).trim();
  assert.match(secret, /^[A-Z2-7]+=*$/iu);
  await page.getByLabel("Sekssifret kode").fill(totp(secret));
  await page.getByRole("button", { name: "Bekreft og fortsett" }).click();
  await page.waitForURL((url) => url.pathname !== "/mfa");
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

function startBackendServer({
  port,
  supabaseUrl: localSupabaseUrl,
  anonKey: localAnonKey,
  databaseUrl: localDatabaseUrl,
  bankingDatabaseUrl,
  ledgerDatabaseUrl,
}) {
  const backendPython =
    process.env.TALLI_BACKEND_PYTHON_BIN || "apps/backend/.venv/bin/python";
  if (!existsSync(backendPython)) {
    throw new Error("backend_python_missing");
  }
  const readinessNonce = randomUUID();
  return startOwnedProcess({
    command: backendPython,
    args: ["tests/fixtures/start_talli_backend.py"],
    cwd: process.cwd(),
    env: {
      ...process.env,
      SUPABASE_URL: localSupabaseUrl,
      SUPABASE_ANON_KEY: localAnonKey,
      TALLI_COMPANY_ACCESS_DATABASE_URL: localDatabaseUrl,
      TALLI_BANKING_DATABASE_URL: bankingDatabaseUrl,
      TALLI_BANKING_ENCRYPTION_KEY:
        "browser-fixture-only-banking-encryption-key",
      TALLI_LEDGER_DATABASE_URL: ledgerDatabaseUrl,
      TALLI_BACKEND_PORT: String(port),
      TALLI_READINESS_NONCE: readinessNonce,
    },
    readinessProof: `TALLI_BACKEND_BOUND:${readinessNonce}`,
  });
}

function databaseUrlForRole(value, role, password) {
  const url = new URL(value);
  assert.ok(isLoopbackPostgresUrl(value), "backend database fixture escaped loopback");
  url.username = role;
  url.password = password;
  return url.toString();
}

function startNextServer({ port, backendBaseUrl }) {
  return startOwnedProcess({
    command: process.execPath,
    args: [
      nextCli,
      "dev",
      "apps/web",
      "--hostname",
      "127.0.0.1",
      "--port",
      String(port),
    ],
    cwd: process.cwd(),
    env: { ...process.env, TALLI_BACKEND_URL: backendBaseUrl },
    readinessProof: "Ready in",
  });
}

async function expectText(page, text) {
  try {
    await page
      .getByText(text, { exact: false })
      .first()
      .waitFor({ timeout: 15000 });
  } catch (error) {
    const body = (await page.locator("body").innerText()).slice(0, 2000);
    throw new Error(
      `Expected ${JSON.stringify(text)} at ${page.url()}; body=${JSON.stringify(body)}`,
      { cause: error },
    );
  }
}

async function assertLedgerReadBoundaries({ accessToken, backendBaseUrl, companyId }) {
  for (const path of ["opening-snapshots", "period-locks", "entries"]) {
    const url = new URL(`/api/v1/ledger/${path}`, backendBaseUrl);
    url.searchParams.append("companyId", companyId);
    url.searchParams.set("limit", "100");
    const response = await fetch(url, {
      headers: { Authorization: `Bearer ${accessToken}` },
    });
    if (!response.ok) {
      throw new Error(
        `ledger browser boundary ${path} returned ${response.status}: ${await response.text()}`,
      );
    }
  }
}

async function assertLedgerDatabaseBoundaries({ companyId, databaseUrl, ownerEmail, ownerId }) {
  const ledgerDatabase = new pg.Client({ connectionString: databaseUrl });
  await ledgerDatabase.connect();
  try {
    await ledgerDatabase.query("begin");
    await ledgerDatabase.query("set local role ledger_executor");
    await ledgerDatabase.query(
      "select pg_catalog.set_config('talli.verified_actor_id', $1, true)",
      [ownerId],
    );
    await ledgerDatabase.query(
      "select pg_catalog.set_config('talli.verified_actor_claims', $1, true)",
      [JSON.stringify({
        aal: "aal2",
        email: ownerEmail,
        role: "authenticated",
        sub: ownerId,
      })],
    );
    await ledgerDatabase.query(
      "select * from backend_system.list_opening_snapshots_legacy_v1(array[$1]::uuid[], null, 100, $2)",
      [companyId, ownerId],
    );
    await ledgerDatabase.query(
      "select * from ledger.list_period_locks(array[$1]::uuid[], null, 100, $2)",
      [companyId, ownerId],
    );
    await ledgerDatabase.query(
      "select * from ledger.list_entries(array[$1]::uuid[], null, 100, $2)",
      [companyId, ownerId],
    );
    await ledgerDatabase.query("rollback");
  } finally {
    await ledgerDatabase.end();
  }
}

async function browserSupabaseSession(page) {
  const storageKey = `sb-${new URL(supabaseUrl).hostname.split(".")[0]}-auth-token`;
  const cookies = await page.context().cookies();
  const exact = cookies.find((cookie) => cookie.name === storageKey);
  const encoded = exact?.value ?? cookies
    .filter((cookie) => cookie.name.startsWith(`${storageKey}.`))
    .sort((left, right) => (
      Number(left.name.slice(storageKey.length + 1))
      - Number(right.name.slice(storageKey.length + 1))
    ))
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
