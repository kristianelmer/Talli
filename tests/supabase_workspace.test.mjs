import assert from "node:assert/strict";
import { randomUUID } from "node:crypto";
import { readFile } from "node:fs/promises";
import { existsSync, readFileSync } from "node:fs";
import test from "node:test";

import { createClient } from "@supabase/supabase-js";
import pg from "pg";

import { buildPersistedCompanyArchive } from "../app/lib/archive.ts";
import { annualConfirmations, buildYearEndInterviewAnswers, noActivityConfirmed } from "../app/lib/annual-data.ts";
import { evaluateAnnualReadinessGates } from "../app/lib/annual-readiness.ts";
import { productionAuthorityGate } from "../app/lib/authority-permission.ts";
import { assertBankTransactionMatchesCost, buildAdminCostLedgerLines, parseBankCsv } from "../app/lib/bank.ts";
import { buildBillingAccount, productionBillingGate } from "../app/lib/billing.ts";
import {
  dividendReceivedLedgerLines,
  summarizeDividendReceivedAnnualImpact,
  validateDividendReceived,
} from "../app/lib/dividend-received.ts";
import { COMPANY_DOCUMENTS_BUCKET, documentStorageKey } from "../app/lib/documents.ts";
import { assertNoBlockingFilingOverrides, validateFilingOverride } from "../app/lib/filing-overrides.ts";
import { validateManualJournal } from "../app/lib/manual-journal.ts";
import { openingBalanceLedgerLines } from "../app/lib/opening-balance.ts";
import {
  ownerDividendCorporateDocumentRecords,
  ownerDividendLedgerLines,
  validateOwnerDividend,
} from "../app/lib/owner-dividend.ts";
import { buildNoActivityRf1086Case, renderRf1086PreviewWithPython } from "../app/lib/rf1086.ts";
import {
  Rf1086ProductionAdapterDisabledError,
  rf1086PayloadHash,
  rf1086ReceiptMetadata,
  rf1086SubmissionFeedbackItems,
  rf1086SubmissionIdempotencyKey,
  rf1086SubmittedPayloadReference,
  rf1086SubmittedPayloadSnapshot,
  runRf1086SubmissionAdapter,
} from "../app/lib/rf1086-submission.ts";
import { assertAdvisoryCanBeAcknowledged, assertNoHardReviewBlocks } from "../app/lib/review.ts";
import { assertStepUpAllowed, stepUpContextFromEvent } from "../app/lib/security.ts";
import { sharePurchaseLedgerLines, validateSharePurchase } from "../app/lib/share-purchase.ts";
import { shareSaleLedgerLines, validateShareSale } from "../app/lib/share-sale.ts";
import { shareholderLoanLedgerLines, validateShareholderLoan } from "../app/lib/shareholder-loan.ts";
import {
  estimateAnnualTax,
  taxSettlementLedgerLines,
  validateTaxSettlement,
} from "../app/lib/tax-settlement.ts";

const requiredEnv = ["SUPABASE_URL", "SUPABASE_ANON_KEY", "SUPABASE_SERVICE_ROLE_KEY"];

function loadDotenv() {
  if (!existsSync(".env")) {
    return;
  }
  for (const line of readFileSync(".env", "utf8").split(/\r?\n/)) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith("#") || !trimmed.includes("=")) {
      continue;
    }
    const [key, ...rest] = trimmed.split("=");
    if (!process.env[key]) {
      process.env[key] = rest.join("=").replace(/^"|"$/g, "");
    }
  }
}

loadDotenv();

function hasRequiredEnv() {
  return requiredEnv.every((key) => Boolean(process.env[key])) && Boolean(getDatabaseConfig());
}

async function applyMigration() {
  const sql = await readFile("supabase/migrations/0001_authenticated_workspace.sql", "utf8");
  const client = new pg.Client({
    ...getDatabaseConfig(),
    ssl: { rejectUnauthorized: false },
  });
  await client.connect();
  try {
    await client.query(sql);
  } finally {
    await client.end();
  }
}

function getDatabaseConfig() {
  for (const candidate of [process.env.DIRECT_DATABASE_URL, process.env.DATABASE_URL]) {
    if (!candidate) {
      continue;
    }
    if (candidate.includes("<") || candidate.includes("your-project-ref") || candidate.includes("your-password")) {
      continue;
    }
    const parsed = parsePostgresUrl(candidate);
    if (parsed) {
      return parsed;
    }
  }
  return null;
}

function parsePostgresUrl(raw) {
  raw = raw.trim();
  const schemeEnd = raw.indexOf("://");
  const at = raw.lastIndexOf("@");
  const credentialColon = raw.indexOf(":", schemeEnd + 3);
  if (schemeEnd === -1 || at === -1 || credentialColon === -1 || credentialColon > at) {
    return null;
  }
  const user = raw.slice(schemeEnd + 3, credentialColon);
  const password = raw.slice(credentialColon + 1, at);
  const rest = raw.slice(at + 1);
  const slash = rest.indexOf("/");
  if (slash === -1) {
    return null;
  }
  const hostPort = rest.slice(0, slash);
  const databaseAndParams = rest.slice(slash + 1);
  const database = databaseAndParams.split("?", 1)[0] || "postgres";
  const portColon = hostPort.lastIndexOf(":");
  const host = portColon === -1 ? hostPort : hostPort.slice(0, portColon);
  const port = portColon === -1 ? 5432 : Number(hostPort.slice(portColon + 1));
  if (!host || !Number.isFinite(port)) {
    return null;
  }
  return { host, port, database, user, password };
}

function serviceClient() {
  return createClient(process.env.SUPABASE_URL, process.env.SUPABASE_SERVICE_ROLE_KEY, {
    auth: { persistSession: false, autoRefreshToken: false },
  });
}

function anonClient() {
  return createClient(process.env.SUPABASE_URL, process.env.SUPABASE_ANON_KEY, {
    auth: { persistSession: false, autoRefreshToken: false },
  });
}

async function createConfirmedUser(label) {
  const admin = serviceClient();
  const email = `talli-${label}-${randomUUID()}@example.test`;
  const password = `Talli-${randomUUID()}!`;
  const { data, error } = await admin.auth.admin.createUser({
    email,
    password,
    email_confirm: true,
  });
  assert.ifError(error);
  assert.ok(data.user?.id);
  return { id: data.user.id, email, password };
}

async function signIn(user) {
  const client = anonClient();
  const { error } = await client.auth.signInWithPassword({
    email: user.email,
    password: user.password,
  });
  assert.ifError(error);
  return client;
}

test(
  "Supabase authenticated workspace persists owner data and denies outsider",
  { skip: hasRequiredEnv() ? false : "Supabase URL/keys or usable DATABASE_URL missing" },
  async () => {
  await applyMigration();
  const admin = serviceClient();
  const ownerUser = await createConfirmedUser("owner");
  const outsiderUser = await createConfirmedUser("outsider");
  const reviewerUser = await createConfirmedUser("reviewer");
  const readOnlyUser = await createConfirmedUser("readonly");
  const owner = await signIn(ownerUser);
  const outsider = await signIn(outsiderUser);
  const reviewer = await signIn(reviewerUser);
  const readOnly = await signIn(readOnlyUser);
  const orgNumber = `${Math.floor(100000000 + Math.random() * 899999999)}`;
  let companyId;

  try {
    const { data: company, error: companyError } = await owner
      .from("companies")
      .insert({
        org_number: orgNumber,
        name: "Talli Test Holding AS",
        entity_type: "AS",
        address: "Storgata 1",
        postal_code: "0155",
        city: "OSLO",
        status_text: "aktiv",
        source: "test",
        created_by: ownerUser.id,
        identity_confirmed_at: new Date().toISOString(),
        identity_locked_at: new Date().toISOString(),
      })
      .select("id, org_number, name, created_by")
      .single();
    assert.ifError(companyError);
    assert.equal(company.org_number, orgNumber);
    assert.equal(company.created_by, ownerUser.id);
    companyId = company.id;

    const { error: membershipError } = await owner.from("company_memberships").insert({
      company_id: companyId,
      user_id: ownerUser.id,
      role: "owner",
      accepted_at: new Date().toISOString(),
    });
    assert.ifError(membershipError);

    const { error: reviewerInviteError } = await owner.from("company_memberships").insert({
      company_id: companyId,
      user_id: reviewerUser.id,
      role: "reviewer",
      invited_by: ownerUser.id,
      accepted_at: new Date().toISOString(),
    });
    assert.ifError(reviewerInviteError);
    const { error: readOnlyInviteError } = await owner.from("company_memberships").insert({
      company_id: companyId,
      user_id: readOnlyUser.id,
      role: "read_only",
      invited_by: ownerUser.id,
      accepted_at: new Date().toISOString(),
    });
    assert.ifError(readOnlyInviteError);
    const { data: persistedRoles, error: persistedRolesError } = await admin
      .from("company_memberships")
      .select("user_id, role")
      .eq("company_id", companyId);
    assert.ifError(persistedRolesError);
    assert.deepEqual(
      persistedRoles
        .map((membership) => [membership.user_id, membership.role])
        .sort((a, b) => String(a[0]).localeCompare(String(b[0]))),
      [
        [ownerUser.id, "owner"],
        [readOnlyUser.id, "read_only"],
        [reviewerUser.id, "reviewer"],
      ].sort((a, b) => String(a[0]).localeCompare(String(b[0]))),
    );

    const { error: auditError } = await owner.from("audit_events").insert({
      company_id: companyId,
      actor_id: ownerUser.id,
      category: "company",
      action: "workspace_created",
      message: "Selskapsarbeidsflate opprettet.",
    });
    assert.ifError(auditError);

    const { data: reloaded, error: reloadError } = await owner
      .from("companies")
      .select("id, org_number, name")
      .eq("id", companyId)
      .single();
    assert.ifError(reloadError);
    assert.equal(reloaded.name, "Talli Test Holding AS");

    const { data: auditRows, error: auditReadError } = await owner
      .from("audit_events")
      .select("action")
      .eq("company_id", companyId);
    assert.ifError(auditReadError);
    assert.deepEqual(
      auditRows.map((row) => row.action),
      ["workspace_created"],
    );

    const { data: stepUpEvent, error: stepUpError } = await owner
      .from("step_up_events")
      .insert({
        actor_id: ownerUser.id,
        method: "totp",
        mfa_verified_at: new Date().toISOString(),
      })
      .select("actor_id, mfa_verified_at, security_review_approved, production_credentials_enabled")
      .single();
    assert.ifError(stepUpError);
    assert.doesNotThrow(() =>
      assertStepUpAllowed("billing_admin", stepUpContextFromEvent(ownerUser.id, stepUpEvent), new Date()),
    );

    const { data: outsiderStepUps, error: outsiderStepUpReadError } = await outsider
      .from("step_up_events")
      .select("id")
      .eq("actor_id", ownerUser.id);
    assert.ifError(outsiderStepUpReadError);
    assert.deepEqual(outsiderStepUps, []);

    const { error: outsiderStepUpWriteError } = await outsider.from("step_up_events").insert({
      actor_id: ownerUser.id,
      method: "totp",
      mfa_verified_at: new Date().toISOString(),
    });
    assert.ok(outsiderStepUpWriteError);

    const { data: outsiderCompanies, error: outsiderCompanyError } = await outsider
      .from("companies")
      .select("id")
      .eq("id", companyId);
    assert.ifError(outsiderCompanyError);
    assert.deepEqual(outsiderCompanies, []);

    const { data: outsiderMemberships, error: outsiderMembershipError } = await outsider
      .from("company_memberships")
      .select("company_id, role")
      .eq("company_id", companyId);
    assert.ifError(outsiderMembershipError);
    assert.deepEqual(outsiderMemberships, []);

    const openingInput = {
      bankBalance: 30000,
      shareCapital: 30000,
      shareCount: 100,
      nominalValue: 300,
      shareholders: [
        {
          name: "Ola Nordmann",
          shareholderKind: "norwegian_person",
          nationalId: "01017012345",
          shareCount: 100,
        },
      ],
    };
    const { data: setup, error: setupError } = await owner
      .from("opening_balance_setups")
      .insert({
        company_id: companyId,
        income_year: 2025,
        bank_balance: openingInput.bankBalance,
        share_capital: openingInput.shareCapital,
        share_count: openingInput.shareCount,
        nominal_value: openingInput.nominalValue,
        created_by: ownerUser.id,
      })
      .select("id, company_id, income_year, bank_balance, share_capital, share_count, nominal_value, locked_at, created_by")
      .single();
    assert.ifError(setupError);
    assert.equal(setup.share_count, 100);

    const { error: openingShareholderError } = await owner.from("opening_shareholders").insert({
      setup_id: setup.id,
      company_id: companyId,
      name: "Ola Nordmann",
      shareholder_kind: "norwegian_person",
      national_id: "01017012345",
      share_count: 100,
      created_by: ownerUser.id,
    });
    assert.ifError(openingShareholderError);

    const { data: openingLedgerEntry, error: ledgerError } = await owner
      .from("ledger_entries")
      .insert({
        company_id: companyId,
        setup_id: setup.id,
        income_year: 2025,
        entry_type: "opening_balance",
        memo: "Åpningsbalanse for Talli-start",
        lines: openingBalanceLedgerLines(openingInput),
        created_by: ownerUser.id,
      })
      .select("id, lines")
      .single();
    assert.ifError(ledgerError);

    const { error: openingAuditError } = await owner.from("audit_events").insert({
      company_id: companyId,
      actor_id: ownerUser.id,
      category: "ledger",
      action: "opening_balance_locked",
      message: "Åpningsbalanse låst for 2025.",
    });
    assert.ifError(openingAuditError);

    const { data: openingReload, error: openingReloadError } = await owner
      .from("opening_balance_setups")
      .select("id, share_count")
      .eq("id", setup.id)
      .single();
    assert.ifError(openingReloadError);
    assert.equal(openingReload.share_count, 100);

    const { data: outsiderSetups, error: outsiderSetupError } = await outsider
      .from("opening_balance_setups")
      .select("id")
      .eq("id", setup.id);
    assert.ifError(outsiderSetupError);
    assert.deepEqual(outsiderSetups, []);

    const { data: persistedCompany, error: persistedCompanyError } = await owner
      .from("companies")
      .select("id, org_number, name, entity_type, address, postal_code, city, status_text, source, created_by, identity_confirmed_at, identity_locked_at, created_at")
      .eq("id", companyId)
      .single();
    assert.ifError(persistedCompanyError);
    const annualAnswers = buildYearEndInterviewAnswers({
      shares_owned_at_year_end: true,
      bank_balance_confirmed: true,
      general_meeting_approved: true,
      authority_to_submit_confirmed: true,
    });
    const { data: annualData, error: annualDataError } = await owner
      .from("annual_data")
      .insert({
        company_id: companyId,
        income_year: 2025,
        answers: annualAnswers,
        confirmations: annualConfirmations(annualAnswers),
        no_activity_confirmed: noActivityConfirmed(annualAnswers),
        completed_by: ownerUser.id,
        updated_by: ownerUser.id,
      })
      .select("id, company_id, income_year, answers, confirmations, no_activity_confirmed, completed_by, completed_at, updated_by, updated_at")
      .single();
    assert.ifError(annualDataError);
    assert.equal(annualData.answers.bank_balance_confirmed, true);
    assert.equal(annualData.no_activity_confirmed, false);
    const noActivityAnswers = buildYearEndInterviewAnswers({
      bank_balance_confirmed: true,
      general_meeting_approved: true,
      authority_to_submit_confirmed: true,
    });
    const { data: updatedAnnualData, error: updatedAnnualDataError } = await owner
      .from("annual_data")
      .update({
        answers: noActivityAnswers,
        confirmations: annualConfirmations(noActivityAnswers),
        no_activity_confirmed: noActivityConfirmed(noActivityAnswers),
        updated_by: ownerUser.id,
      })
      .eq("id", annualData.id)
      .select("id, answers, confirmations, no_activity_confirmed")
      .single();
    assert.ifError(updatedAnnualDataError);
    assert.equal(updatedAnnualData.no_activity_confirmed, true);
    const { error: annualDataAuditError } = await owner.from("audit_events").insert({
      company_id: companyId,
      actor_id: ownerUser.id,
      category: "filing",
      action: "year_end_interview_updated",
      message: "Year-end interview oppdatert for 2025.",
    });
    assert.ifError(annualDataAuditError);
    const { data: reloadedAnnualData, error: reloadedAnnualDataError } = await owner
      .from("annual_data")
      .select("id, company_id, income_year, answers, confirmations, no_activity_confirmed, completed_by, completed_at, updated_by, updated_at")
      .eq("company_id", companyId)
      .eq("income_year", 2025)
      .single();
    assert.ifError(reloadedAnnualDataError);
    assert.equal(reloadedAnnualData.confirmations.includes("no_activity_confirmed"), true);
    const { error: outsiderAnnualDataError } = await outsider.from("annual_data").insert({
      company_id: companyId,
      income_year: 2025,
      answers: noActivityAnswers,
      confirmations: annualConfirmations(noActivityAnswers),
      no_activity_confirmed: true,
      completed_by: outsiderUser.id,
      updated_by: outsiderUser.id,
    });
    assert.ok(outsiderAnnualDataError);
    const { data: outsiderAnnualDataRows, error: outsiderAnnualDataRowsError } = await outsider
      .from("annual_data")
      .select("id")
      .eq("company_id", companyId);
    assert.ifError(outsiderAnnualDataRowsError);
    assert.equal(outsiderAnnualDataRows.length, 0);
    const { data: persistedShareholders, error: persistedShareholdersError } = await owner
      .from("opening_shareholders")
      .select("id, setup_id, company_id, name, shareholder_kind, national_id, org_number, share_count")
      .eq("setup_id", setup.id);
    assert.ifError(persistedShareholdersError);
    const rendered = renderRf1086PreviewWithPython(
      buildNoActivityRf1086Case(persistedCompany, setup, persistedShareholders),
    );
    assert.equal(rendered.status, "ready");
    assert.match(rendered.preview, /Talli Test Holding AS/);

    const { data: filingPreview, error: filingPreviewError } = await owner
      .from("filing_previews")
      .insert({
        company_id: companyId,
        setup_id: setup.id,
        income_year: 2025,
        filing: rendered.filing,
        status: rendered.status,
        issues: rendered.issues,
        preview: rendered.preview,
        hovedskjema_xml: rendered.hovedskjemaXml,
        underskjema_xml: rendered.underskjemaXml,
        source: "python_rf1086_engine",
        created_by: ownerUser.id,
      })
      .select("id, company_id, setup_id, income_year, filing, status, issues, preview, hovedskjema_xml, underskjema_xml, source, created_at")
      .single();
    assert.ifError(filingPreviewError);
    assert.equal(filingPreview.status, "ready");

    assert.equal(productionAuthorityGate([], "aksjonaerregisteroppgaven").status, "missing_authority_confirmation");
    const { data: authorityPermission, error: authorityPermissionError } = await owner
      .from("authority_permissions")
      .insert({
        company_id: companyId,
        obligation: "aksjonaerregisteroppgaven",
        submitter_user_id: ownerUser.id,
        confirmed_by: ownerUser.id,
        production_enabled: true,
      })
      .select("id, company_id, obligation, submitter_user_id, confirmed_by, confirmed_at, production_enabled, updated_at")
      .single();
    assert.ifError(authorityPermissionError);
    assert.equal(authorityPermission.obligation, "aksjonaerregisteroppgaven");
    assert.equal(authorityPermission.submitter_user_id, ownerUser.id);
    assert.equal(productionAuthorityGate([authorityPermission], "aksjonaerregisteroppgaven").allowed, true);
    const { error: authorityAuditError } = await owner.from("audit_events").insert({
      company_id: companyId,
      actor_id: ownerUser.id,
      category: "submission",
      action: "authority_permission_confirmed",
      message: "Innsendingsrett bekreftet for aksjonaerregisteroppgaven.",
    });
    assert.ifError(authorityAuditError);
    const { error: annualAuthorityPermissionError } = await owner.from("authority_permissions").insert([
      {
        company_id: companyId,
        obligation: "skattemelding",
        submitter_user_id: ownerUser.id,
        confirmed_by: ownerUser.id,
        production_enabled: true,
      },
      {
        company_id: companyId,
        obligation: "aarsregnskap",
        submitter_user_id: ownerUser.id,
        confirmed_by: ownerUser.id,
        production_enabled: true,
      },
    ]);
    assert.ifError(annualAuthorityPermissionError);
    const { error: reviewerAuthorityError } = await reviewer.from("authority_permissions").insert({
      company_id: companyId,
      obligation: "skattemelding",
      submitter_user_id: reviewerUser.id,
      confirmed_by: reviewerUser.id,
      production_enabled: false,
    });
    assert.ok(reviewerAuthorityError);
    const { error: outsiderAuthorityError } = await outsider.from("authority_permissions").insert({
      company_id: companyId,
      obligation: "aarsregnskap",
      submitter_user_id: outsiderUser.id,
      confirmed_by: outsiderUser.id,
      production_enabled: false,
    });
    assert.ok(outsiderAuthorityError);
    const { data: outsiderAuthorityRows, error: outsiderAuthorityRowsError } = await outsider
      .from("authority_permissions")
      .select("id")
      .eq("company_id", companyId);
    assert.ifError(outsiderAuthorityRowsError);
    assert.equal(outsiderAuthorityRows.length, 0);

    assert.throws(() => buildBillingAccount({ companyId, pricingPlan: "founder", founderCohortNumber: 101 }), /Founder-kull/);
    const billingAccount = buildBillingAccount({
      companyId,
      pricingPlan: "founder",
      founderCohortNumber: 1,
      subscriptionActive: true,
    });
    const { error: billingInsertError } = await owner.from("billing_accounts").insert({
      ...billingAccount,
      updated_by: ownerUser.id,
    });
    assert.ifError(billingInsertError);
    const { data: reloadedBilling, error: reloadedBillingError } = await owner
      .from("billing_accounts")
      .select("company_id, pricing_plan, monthly_nok, filing_package_nok, founder_cohort_number, subscription_active, filing_package_paid, supported_case, refund_eligible, no_charge_reason")
      .eq("company_id", companyId)
      .single();
    assert.ifError(reloadedBillingError);
    assert.equal(reloadedBilling.pricing_plan, "founder");
    assert.equal(reloadedBilling.monthly_nok, 29);
    assert.equal(productionBillingGate(reloadedBilling, false).chargeAllowed, false);
    assert.equal(productionBillingGate(reloadedBilling, true).chargeAllowed, true);

    const { error: billingUnsupportedError } = await owner
      .from("billing_accounts")
      .update({
        supported_case: false,
        filing_package_paid: false,
        no_charge_reason: "Utenfor enkel holding-AS-løype",
        updated_by: ownerUser.id,
      })
      .eq("company_id", companyId);
    assert.ifError(billingUnsupportedError);
    const { data: unsupportedBilling, error: unsupportedBillingError } = await owner
      .from("billing_accounts")
      .select("company_id, pricing_plan, monthly_nok, filing_package_nok, founder_cohort_number, subscription_active, filing_package_paid, supported_case, refund_eligible, no_charge_reason")
      .eq("company_id", companyId)
      .single();
    assert.ifError(unsupportedBillingError);
    assert.equal(productionBillingGate(unsupportedBilling, true).status, "unsupported_case");
    assert.equal(productionBillingGate(unsupportedBilling, true).chargeAllowed, false);

    const { error: billingPaidError } = await owner
      .from("billing_accounts")
      .update({
        supported_case: true,
        no_charge_reason: null,
        filing_package_paid: true,
        refund_eligible: false,
        updated_by: ownerUser.id,
      })
      .eq("company_id", companyId);
    assert.ifError(billingPaidError);
    const { data: paidBilling, error: paidBillingError } = await owner
      .from("billing_accounts")
      .select("company_id, pricing_plan, monthly_nok, filing_package_nok, founder_cohort_number, subscription_active, filing_package_paid, supported_case, refund_eligible, no_charge_reason")
      .eq("company_id", companyId)
      .single();
    assert.ifError(paidBillingError);
    assert.equal(productionBillingGate(paidBilling, true).allowed, true);
    const { data: annualAuthorityPermissions, error: annualAuthorityPermissionsError } = await owner
      .from("authority_permissions")
      .select("company_id, obligation, submitter_user_id, confirmed_by, confirmed_at, production_enabled")
      .eq("company_id", companyId);
    assert.ifError(annualAuthorityPermissionsError);
    const annualReadinessSnapshots = evaluateAnnualReadinessGates({
      company: persistedCompany,
      incomeYear: 2025,
      setups: [setup],
      ledgerEntries: [
        {
          id: openingLedgerEntry.id,
          company_id: companyId,
          setup_id: setup.id,
          income_year: 2025,
          entry_type: "opening_balance",
          memo: "Opening balance",
          lines: openingLedgerEntry.lines,
          risk_flags: [],
          warning_accepted_by: null,
          warning_accepted_at: null,
          created_by: ownerUser.id,
          created_at: "2026-01-01T00:00:00Z",
        },
      ],
      holdingActions: [],
      bankTransactions: [],
      documents: [],
      overrides: [],
      locks: [],
      annualData: reloadedAnnualData,
      billingAccount: paidBilling,
      authorityPermissions: annualAuthorityPermissions,
      filingPreviews: [filingPreview],
      filingSubmissions: [],
    });
    const { data: persistedReadinessSnapshots, error: readinessSnapshotError } = await owner
      .from("filing_readiness_snapshots")
      .upsert(
        annualReadinessSnapshots.map((snapshot) => ({
          company_id: snapshot.company_id,
          income_year: snapshot.income_year,
          obligation: snapshot.obligation,
          status: snapshot.status,
          ready: snapshot.ready,
          hard_blocks: snapshot.hard_blocks,
          warnings: snapshot.warnings,
          accepted_warnings: snapshot.accepted_warnings,
          evaluated_at: snapshot.evaluated_at,
          created_by: ownerUser.id,
        })),
        { onConflict: "company_id,income_year,obligation" },
      )
      .select("id, company_id, income_year, obligation, status, ready, hard_blocks, warnings, accepted_warnings, evaluated_at, created_by, updated_at");
    assert.ifError(readinessSnapshotError);
    assert.equal(persistedReadinessSnapshots.length, 3);
    assert.equal(persistedReadinessSnapshots.find((snapshot) => snapshot.obligation === "aksjonaerregisteroppgaven").ready, true);
    assert.ok(persistedReadinessSnapshots.find((snapshot) => snapshot.obligation === "aarsregnskap").warnings.length);
    assert.equal(productionBillingGate(paidBilling, persistedReadinessSnapshots.find((snapshot) => snapshot.obligation === "aksjonaerregisteroppgaven").ready).allowed, true);
    const { data: reloadedReadinessSnapshots, error: reloadedReadinessError } = await owner
      .from("filing_readiness_snapshots")
      .select("id, obligation, status, ready, hard_blocks, warnings, accepted_warnings")
      .eq("company_id", companyId)
      .eq("income_year", 2025);
    assert.ifError(reloadedReadinessError);
    assert.equal(reloadedReadinessSnapshots.length, 3);
    const { error: outsiderReadinessError } = await outsider.from("filing_readiness_snapshots").insert({
      company_id: companyId,
      income_year: 2025,
      obligation: "aarsregnskap",
      status: "ready",
      ready: true,
      hard_blocks: [],
      warnings: [],
      accepted_warnings: [],
      created_by: outsiderUser.id,
    });
    assert.ok(outsiderReadinessError);
    const { data: outsiderReadinessRows, error: outsiderReadinessRowsError } = await outsider
      .from("filing_readiness_snapshots")
      .select("id")
      .eq("company_id", companyId);
    assert.ifError(outsiderReadinessRowsError);
    assert.equal(outsiderReadinessRows.length, 0);
    const { error: billingRefundError } = await owner
      .from("billing_accounts")
      .update({ refund_eligible: true, updated_by: ownerUser.id })
      .eq("company_id", companyId);
    assert.ifError(billingRefundError);
    const { data: refundBilling, error: refundBillingError } = await owner
      .from("billing_accounts")
      .select("company_id, pricing_plan, monthly_nok, filing_package_nok, founder_cohort_number, subscription_active, filing_package_paid, supported_case, refund_eligible, no_charge_reason")
      .eq("company_id", companyId)
      .single();
    assert.ifError(refundBillingError);
    assert.equal(productionBillingGate(refundBilling, true).status, "refund_eligible");
    const { error: outsiderBillingError } = await outsider.from("billing_accounts").update({ filing_package_paid: false }).eq("company_id", companyId);
    assert.ifError(outsiderBillingError);
    const { data: outsiderBillingRows, error: outsiderBillingRowsError } = await outsider
      .from("billing_accounts")
      .select("company_id")
      .eq("company_id", companyId);
    assert.ifError(outsiderBillingRowsError);
    assert.equal(outsiderBillingRows.length, 0);
    const { data: billingAfterOutsiderUpdate, error: billingAfterOutsiderUpdateError } = await owner
      .from("billing_accounts")
      .select("filing_package_paid, refund_eligible")
      .eq("company_id", companyId)
      .single();
    assert.ifError(billingAfterOutsiderUpdateError);
    assert.equal(billingAfterOutsiderUpdate.filing_package_paid, true);
    assert.equal(billingAfterOutsiderUpdate.refund_eligible, true);
    assert.equal(filingPreview.source, "python_rf1086_engine");

    const advisoryOverride = validateFilingOverride({
      fieldTarget: "rf1086.note",
      oldValue: "",
      newValue: "Manuell note for myndighetsfelt",
      reason: "Authority field not modelled yet",
      riskLevel: "advisory",
    });
    const { data: persistedAdvisoryOverride, error: advisoryOverrideError } = await owner
      .from("filing_overrides")
      .insert({
        preview_id: filingPreview.id,
        company_id: companyId,
        income_year: 2025,
        filing: filingPreview.filing,
        field_target: advisoryOverride.fieldTarget,
        old_value: advisoryOverride.oldValue,
        new_value: advisoryOverride.newValue,
        reason: advisoryOverride.reason,
        risk_level: advisoryOverride.riskLevel,
        owner_confirmed_by: ownerUser.id,
        owner_confirmed_at: new Date().toISOString(),
        created_by: ownerUser.id,
      })
      .select("id, preview_id, company_id, income_year, filing, field_target, old_value, new_value, reason, risk_level, owner_confirmed_by")
      .single();
    assert.ifError(advisoryOverrideError);
    assert.equal(persistedAdvisoryOverride.field_target, "rf1086.note");
    assert.equal(persistedAdvisoryOverride.risk_level, "advisory");
    assert.equal(persistedAdvisoryOverride.owner_confirmed_by, ownerUser.id);

    const { error: advisoryOverrideAuditError } = await owner.from("audit_events").insert({
      company_id: companyId,
      actor_id: ownerUser.id,
      category: "filing",
      action: "filing_override_added",
      message: "Filing-overstyring lagt til for rf1086.note: advisory.",
    });
    assert.ifError(advisoryOverrideAuditError);

    const { data: reloadedOverrides, error: reloadedOverrideError } = await owner
      .from("filing_overrides")
      .select("id, field_target, risk_level")
      .eq("preview_id", filingPreview.id);
    assert.ifError(reloadedOverrideError);
    assert.deepEqual(reloadedOverrides, [
      {
        id: persistedAdvisoryOverride.id,
        field_target: "rf1086.note",
        risk_level: "advisory",
      },
    ]);

    const { data: outsiderOverrides, error: outsiderOverrideError } = await outsider
      .from("filing_overrides")
      .select("id")
      .eq("preview_id", filingPreview.id);
    assert.ifError(outsiderOverrideError);
    assert.deepEqual(outsiderOverrides, []);

    const { error: readOnlyOverrideError } = await readOnly.from("filing_overrides").insert({
      preview_id: filingPreview.id,
      company_id: companyId,
      income_year: 2025,
      filing: filingPreview.filing,
      field_target: "rf1086.note",
      old_value: "",
      new_value: "Read-only should not write.",
      reason: "Forbidden role.",
      risk_level: "advisory",
      owner_confirmed_by: readOnlyUser.id,
      owner_confirmed_at: new Date().toISOString(),
      created_by: readOnlyUser.id,
    });
    assert.ok(readOnlyOverrideError);
    assertNoBlockingFilingOverrides([persistedAdvisoryOverride]);

    assert.throws(
      () =>
        runRf1086SubmissionAdapter({
          mode: "production",
          preview: filingPreview,
          userId: ownerUser.id,
          confirmations: { authorityConfirmed: true, previewConfirmed: true },
        }),
      (error) => error instanceof Rf1086ProductionAdapterDisabledError,
    );
    const simulatedSubmission = runRf1086SubmissionAdapter({
      mode: "simulation",
      preview: filingPreview,
      userId: ownerUser.id,
      confirmations: {
        authorityConfirmed: true,
        previewConfirmed: true,
      },
    });
    assert.equal(simulatedSubmission.status, "receipt_stored");
    const submissionPayloadHash = rf1086PayloadHash(filingPreview);
    const submissionIdempotencyKey = rf1086SubmissionIdempotencyKey(filingPreview);
    const submissionFeedbackItems = rf1086SubmissionFeedbackItems(simulatedSubmission);
    const submissionReceiptMetadata = rf1086ReceiptMetadata(simulatedSubmission);
    const submittedPayloadRef = rf1086SubmittedPayloadReference(filingPreview, simulatedSubmission);
    const submittedPayload = rf1086SubmittedPayloadSnapshot(filingPreview);
    const { data: filingSubmission, error: filingSubmissionError } = await owner
      .from("filing_submissions")
      .upsert(
        {
          preview_id: filingPreview.id,
          company_id: companyId,
          setup_id: setup.id,
          income_year: 2025,
          filing: filingPreview.filing,
          mode: "simulation",
          adapter_mode: "simulation",
          payload_hash: submissionPayloadHash,
          idempotency_key: submissionIdempotencyKey,
          status: simulatedSubmission.status,
          authority_confirmed_by: simulatedSubmission.authority_confirmed_by,
          authority_confirmed_at: simulatedSubmission.authority_confirmed_at,
          preview_confirmed_by: simulatedSubmission.preview_confirmed_by,
          preview_confirmed_at: simulatedSubmission.preview_confirmed_at,
          calls: simulatedSubmission.calls,
          receipt_id: simulatedSubmission.receipt_id,
          feedback_document_ids: simulatedSubmission.feedback_document_ids,
          feedback_items: submissionFeedbackItems,
          receipt_metadata: submissionReceiptMetadata,
          submitted_payload_ref: submittedPayloadRef,
          submitted_payload: submittedPayload,
          failure_code: simulatedSubmission.failure_code,
          failure_message: simulatedSubmission.failure_message,
          created_by: ownerUser.id,
          submitted_by: ownerUser.id,
        },
        { onConflict: "preview_id" },
      )
      .select("id, preview_id, company_id, income_year, filing, mode, adapter_mode, payload_hash, idempotency_key, status, calls, receipt_id, feedback_document_ids, feedback_items, receipt_metadata, submitted_payload_ref, submitted_payload, authority_confirmed_at, preview_confirmed_at, created_at, updated_at, submitted_by")
      .single();
    assert.ifError(filingSubmissionError);
    assert.equal(filingSubmission.status, "receipt_stored");
    assert.equal(filingSubmission.calls.length, 4);
    assert.equal(filingSubmission.payload_hash, submissionPayloadHash);
    assert.equal(filingSubmission.idempotency_key, submissionIdempotencyKey);
    assert.equal(filingSubmission.submitted_by, ownerUser.id);
    assert.equal(filingSubmission.feedback_items[0].severity, "accepted");
    assert.equal(filingSubmission.receipt_metadata.receiptId, simulatedSubmission.receipt_id);
    assert.equal(filingSubmission.submitted_payload_ref.payloadHash, submissionPayloadHash);
    assert.equal(filingSubmission.submitted_payload.hovedskjemaXml, filingPreview.hovedskjema_xml);

    const retrySubmission = runRf1086SubmissionAdapter({
      mode: "simulation",
      preview: filingPreview,
      userId: ownerUser.id,
      confirmations: {
        authorityConfirmed: true,
        previewConfirmed: true,
      },
    });
    const { error: retryError } = await owner.from("filing_submissions").upsert(
      {
        preview_id: filingPreview.id,
        company_id: companyId,
        setup_id: setup.id,
        income_year: 2025,
        filing: filingPreview.filing,
        mode: "simulation",
        adapter_mode: "simulation",
        payload_hash: submissionPayloadHash,
        idempotency_key: submissionIdempotencyKey,
        status: retrySubmission.status,
        authority_confirmed_by: retrySubmission.authority_confirmed_by,
        authority_confirmed_at: retrySubmission.authority_confirmed_at,
        preview_confirmed_by: retrySubmission.preview_confirmed_by,
        preview_confirmed_at: retrySubmission.preview_confirmed_at,
        calls: retrySubmission.calls,
        receipt_id: retrySubmission.receipt_id,
        feedback_document_ids: retrySubmission.feedback_document_ids,
        feedback_items: rf1086SubmissionFeedbackItems(retrySubmission),
        receipt_metadata: rf1086ReceiptMetadata(retrySubmission),
        submitted_payload_ref: rf1086SubmittedPayloadReference(filingPreview, retrySubmission),
        submitted_payload: submittedPayload,
        failure_code: retrySubmission.failure_code,
        failure_message: retrySubmission.failure_message,
        created_by: ownerUser.id,
        submitted_by: ownerUser.id,
      },
      { onConflict: "preview_id" },
    );
    assert.ifError(retryError);
    assert.deepEqual(
      retrySubmission.calls.map((call) => call.idempotency_key),
      simulatedSubmission.calls.map((call) => call.idempotency_key),
    );

    const { data: reloadedSubmissions, error: reloadSubmissionError } = await owner
      .from("filing_submissions")
      .select("id, receipt_id, idempotency_key, feedback_items, receipt_metadata, submitted_payload_ref")
      .eq("preview_id", filingPreview.id);
    assert.ifError(reloadSubmissionError);
    assert.equal(reloadedSubmissions.length, 1);
    assert.equal(reloadedSubmissions[0].receipt_id, simulatedSubmission.receipt_id);
    assert.equal(reloadedSubmissions[0].idempotency_key, submissionIdempotencyKey);
    assert.equal(reloadedSubmissions[0].feedback_items[0].code, "RF1086_ACCEPTED");
    assert.equal(reloadedSubmissions[0].receipt_metadata.receiptId, simulatedSubmission.receipt_id);
    assert.equal(reloadedSubmissions[0].submitted_payload_ref.payloadHash, submissionPayloadHash);

    const blockingOverride = validateFilingOverride({
      fieldTarget: "rf1086.transaction_code",
      oldValue: "U",
      newValue: "K",
      reason: "Production value not verified by authority evidence.",
      riskLevel: "block",
    });
    const { data: persistedBlockingOverride, error: blockingOverrideError } = await owner
      .from("filing_overrides")
      .insert({
        preview_id: filingPreview.id,
        company_id: companyId,
        income_year: 2025,
        filing: filingPreview.filing,
        field_target: blockingOverride.fieldTarget,
        old_value: blockingOverride.oldValue,
        new_value: blockingOverride.newValue,
        reason: blockingOverride.reason,
        risk_level: blockingOverride.riskLevel,
        owner_confirmed_by: ownerUser.id,
        owner_confirmed_at: new Date().toISOString(),
        created_by: ownerUser.id,
      })
      .select("risk_level, field_target")
      .single();
    assert.ifError(blockingOverrideError);
    assert.throws(() => assertNoBlockingFilingOverrides([persistedBlockingOverride]), /Blokkerende filing-overstyring/);

    const { data: outsiderSubmissions, error: outsiderSubmissionError } = await outsider
      .from("filing_submissions")
      .select("id")
      .eq("id", filingSubmission.id);
    assert.ifError(outsiderSubmissionError);
    assert.deepEqual(outsiderSubmissions, []);

    const { data: outsiderPreviews, error: outsiderPreviewError } = await outsider
      .from("filing_previews")
      .select("id")
      .eq("id", filingPreview.id);
    assert.ifError(outsiderPreviewError);
    assert.deepEqual(outsiderPreviews, []);

    const { data: reviewerPreviews, error: reviewerPreviewError } = await reviewer
      .from("filing_previews")
      .select("id")
      .eq("id", filingPreview.id);
    assert.ifError(reviewerPreviewError);
    assert.deepEqual(reviewerPreviews, [{ id: filingPreview.id }]);

    const { data: advisoryComment, error: advisoryCommentError } = await reviewer
      .from("filing_review_comments")
      .insert({
        preview_id: filingPreview.id,
        company_id: companyId,
        target: "rf1086_preview",
        severity: "advisory",
        body: "Kontroller aksjonærnavn før innsending.",
        created_by: reviewerUser.id,
      })
      .select("id, severity, acknowledged_by")
      .single();
    assert.ifError(advisoryCommentError);
    assert.equal(advisoryComment.severity, "advisory");
    assertAdvisoryCanBeAcknowledged({ severity: advisoryComment.severity });

    const { error: readOnlyCommentError } = await readOnly.from("filing_review_comments").insert({
      preview_id: filingPreview.id,
      company_id: companyId,
      target: "rf1086_preview",
      severity: "advisory",
      body: "Read-only should not write.",
      created_by: readOnlyUser.id,
    });
    assert.ok(readOnlyCommentError);

    const acknowledgedAt = new Date().toISOString();
    const { data: acknowledgedComment, error: acknowledgeError } = await owner
      .from("filing_review_comments")
      .update({ acknowledged_by: ownerUser.id, acknowledged_at: acknowledgedAt })
      .eq("id", advisoryComment.id)
      .select("id, acknowledged_by")
      .single();
    assert.ifError(acknowledgeError);
    assert.equal(acknowledgedComment.acknowledged_by, ownerUser.id);

    const { data: hardBlockComment, error: hardBlockError } = await reviewer
      .from("filing_review_comments")
      .insert({
        preview_id: filingPreview.id,
        company_id: companyId,
        target: "rf1086_preview",
        severity: "hard_block",
        body: "Mangler gyldig avklaring.",
        created_by: reviewerUser.id,
      })
      .select("id, severity")
      .single();
    assert.ifError(hardBlockError);
    assert.throws(() => assertAdvisoryCanBeAcknowledged({ severity: hardBlockComment.severity }), /Hard review-blokk/);
    assert.throws(
      () => assertNoHardReviewBlocks([{ severity: "advisory" }, { severity: hardBlockComment.severity }]),
      /simulert innsending/,
    );

    const bankCsv = "date,text,amount,balance\n2025-01-02,Opening,30000,30000\n2025-01-03,Bank fee,-50,29950\n";
    const parsedBank = parseBankCsv(bankCsv);
    for (let attempt = 0; attempt < 2; attempt += 1) {
      const { error: bankImportError } = await owner.from("bank_transactions").upsert(
        parsedBank.map((transaction) => ({
          company_id: companyId,
          income_year: 2025,
          transaction_date: transaction.transactionDate,
          text: transaction.text,
          amount: transaction.amount,
          balance: transaction.balance,
          source_hash: transaction.sourceHash,
          created_by: ownerUser.id,
        })),
        { onConflict: "company_id,income_year,source_hash", ignoreDuplicates: true },
      );
      assert.ifError(bankImportError);
    }
    const { data: importedBankTransactions, error: importedBankError } = await owner
      .from("bank_transactions")
      .select("id, amount, matched_entry_id, matched_action_id, accepted_warning")
      .eq("company_id", companyId)
      .eq("income_year", 2025)
      .order("transaction_date", { ascending: true });
    assert.ifError(importedBankError);
    assert.equal(importedBankTransactions.length, 2);

    const feeTransaction = importedBankTransactions.find((transaction) => Number(transaction.amount) === -50);
    assert.ok(feeTransaction);
    assertBankTransactionMatchesCost(Number(feeTransaction.amount), 50);
    const adminCostLines = buildAdminCostLedgerLines({ category: "bank_fee", payee: "Bank", amount: 50 });
    const { data: adminCostEntry, error: adminCostEntryError } = await owner
      .from("ledger_entries")
      .insert({
        company_id: companyId,
        income_year: 2025,
        entry_type: "admin_cost",
        memo: "Admin cost paid to Bank on 2025-01-03",
        lines: adminCostLines,
        created_by: ownerUser.id,
      })
      .select("id, entry_type, lines")
      .single();
    assert.ifError(adminCostEntryError);
    assert.equal(adminCostEntry.entry_type, "admin_cost");
    assert.deepEqual(adminCostEntry.lines, adminCostLines);

    const { error: bankMatchError } = await owner
      .from("bank_transactions")
      .update({ matched_entry_id: adminCostEntry.id })
      .eq("id", feeTransaction.id);
    assert.ifError(bankMatchError);
    const { data: reloadedBankTransactions, error: reloadedBankError } = await owner
      .from("bank_transactions")
      .select("id, matched_entry_id, matched_action_id, accepted_warning")
      .eq("company_id", companyId)
      .eq("income_year", 2025);
    assert.ifError(reloadedBankError);
    assert.equal(
      reloadedBankTransactions.filter(
        (transaction) => !transaction.matched_entry_id && !transaction.matched_action_id && !transaction.accepted_warning,
      ).length,
      1,
    );

    const { data: outsiderBankTransactions, error: outsiderBankError } = await outsider
      .from("bank_transactions")
      .select("id")
      .eq("company_id", companyId);
    assert.ifError(outsiderBankError);
    assert.deepEqual(outsiderBankTransactions, []);

    assert.throws(
      () =>
        validateDividendReceived({
          payingCompanyName: "Unclear Fund",
          declaredDate: "2025-04-01",
          paidDate: "2025-04-15",
          grossAmount: 1000,
          linkedInvestmentId: "unclear-fund",
          taxTreatment: "needs_accountant",
          documentStatus: "attached",
        }),
      (error) => error?.code === "unsupported_tax_treatment",
    );
    const dividendDocumentId = randomUUID();
    const { error: dividendDocumentError } = await owner.from("documents").insert({
      id: dividendDocumentId,
      company_id: companyId,
      income_year: 2025,
      document_type: "dividend_resolution",
      name: "dividend.pdf",
      linked_to: "dividend_received",
      status: "attached",
      storage_key: `companies/${companyId}/2025/${dividendDocumentId}/dividend.pdf`,
      created_by: ownerUser.id,
    });
    assert.ifError(dividendDocumentError);
    const dividendSourceHash = `dividend-bank-${randomUUID()}`;
    const { data: dividendBankTransaction, error: dividendBankTransactionError } = await owner
      .from("bank_transactions")
      .insert({
        company_id: companyId,
        income_year: 2025,
        transaction_date: "2025-04-15",
        text: "Dividend Portfolio AS",
        amount: 1000,
        balance: 30950,
        source_hash: dividendSourceHash,
        created_by: ownerUser.id,
      })
      .select("id, amount")
      .single();
    assert.ifError(dividendBankTransactionError);
    const dividendPayload = validateDividendReceived({
      payingCompanyName: "Portfolio AS",
      declaredDate: "2025-04-01",
      paidDate: "2025-04-15",
      grossAmount: 1000,
      linkedInvestmentId: "portfolio-as",
      taxTreatment: "fritaksmetoden",
      bankTransactionId: dividendBankTransaction.id,
      documentId: dividendDocumentId,
      documentStatus: "attached",
    });
    assert.equal(dividendPayload.taxable_add_back, 30);
    const dividendLines = dividendReceivedLedgerLines(dividendPayload);
    const { data: dividendEntry, error: dividendEntryError } = await owner
      .from("ledger_entries")
      .insert({
        company_id: companyId,
        income_year: 2025,
        entry_type: "dividend_received",
        memo: "Dividend received from Portfolio AS",
        lines: dividendLines,
        created_by: ownerUser.id,
      })
      .select("id, entry_type, lines")
      .single();
    assert.ifError(dividendEntryError);
    assert.equal(dividendEntry.entry_type, "dividend_received");
    assert.deepEqual(dividendEntry.lines, dividendLines);
    const dividendActionId = randomUUID();
    const { data: dividendAction, error: dividendActionError } = await owner
      .from("holding_actions")
      .insert({
        id: dividendActionId,
        company_id: companyId,
        income_year: 2025,
        action_type: "dividend_received",
        action_date: dividendPayload.paid_date,
        payload: dividendPayload,
        ledger_entry_id: dividendEntry.id,
        bank_transaction_id: dividendBankTransaction.id,
        document_id: dividendDocumentId,
        risk_level: "ready",
        created_by: ownerUser.id,
      })
      .select("id, action_type, payload, ledger_entry_id, bank_transaction_id, document_id")
      .single();
    assert.ifError(dividendActionError);
    assert.equal(dividendAction.action_type, "dividend_received");
    assert.equal(dividendAction.ledger_entry_id, dividendEntry.id);
    assert.equal(dividendAction.bank_transaction_id, dividendBankTransaction.id);
    assert.equal(dividendAction.document_id, dividendDocumentId);
    assert.deepEqual(
      summarizeDividendReceivedAnnualImpact([{ action_type: dividendAction.action_type, payload: dividendAction.payload }]),
      { dividendIncome: 1000, fritaksmetodenAddBack: 30 },
    );
    const { error: dividendBankMatchError } = await owner
      .from("bank_transactions")
      .update({ matched_action_id: dividendAction.id })
      .eq("id", dividendBankTransaction.id);
    assert.ifError(dividendBankMatchError);
    const { data: reloadedDividendEntry, error: reloadedDividendEntryError } = await owner
      .from("ledger_entries")
      .select("id, entry_type")
      .eq("id", dividendEntry.id)
      .single();
    assert.ifError(reloadedDividendEntryError);
    assert.equal(reloadedDividendEntry.entry_type, "dividend_received");
    const { data: outsiderDividendActions, error: outsiderDividendActionError } = await outsider
      .from("holding_actions")
      .select("id")
      .eq("id", dividendAction.id);
    assert.ifError(outsiderDividendActionError);
    assert.deepEqual(outsiderDividendActions, []);
    const { error: outsiderDividendActionInsertError } = await outsider.from("holding_actions").insert({
      company_id: companyId,
      income_year: 2025,
      action_type: "dividend_received",
      action_date: dividendPayload.paid_date,
      payload: dividendPayload,
      ledger_entry_id: dividendEntry.id,
      bank_transaction_id: dividendBankTransaction.id,
      document_id: dividendDocumentId,
      risk_level: "ready",
      created_by: outsiderUser.id,
    });
    assert.ok(outsiderDividendActionInsertError);

    assert.throws(
      () =>
        validateSharePurchase({
          investmentKey: "listed",
          investmentName: "Listed ASA",
          investmentKind: "simple_listed_security",
          taxTreatment: "fritaksmetoden",
          acquisitionDate: "2025-05-01",
          shareCount: 100,
          purchaseAmount: 50000,
          documentStatus: "attached",
        }),
      (error) => error?.code === "unsupported_investment_kind",
    );
    const purchaseDocumentId = randomUUID();
    const { error: purchaseDocumentError } = await owner.from("documents").insert({
      id: purchaseDocumentId,
      company_id: companyId,
      income_year: 2025,
      document_type: "share_purchase_agreement",
      name: "purchase.pdf",
      linked_to: "share_purchase",
      status: "attached",
      storage_key: `companies/${companyId}/2025/${purchaseDocumentId}/purchase.pdf`,
      created_by: ownerUser.id,
    });
    assert.ifError(purchaseDocumentError);
    const { data: purchaseBankTransaction, error: purchaseBankTransactionError } = await owner
      .from("bank_transactions")
      .insert({
        company_id: companyId,
        income_year: 2025,
        transaction_date: "2025-05-01",
        text: "Purchase Portfolio AS",
        amount: -50000,
        balance: -19050,
        source_hash: `purchase-bank-${randomUUID()}`,
        created_by: ownerUser.id,
      })
      .select("id, amount")
      .single();
    assert.ifError(purchaseBankTransactionError);
    const purchasePayload = validateSharePurchase({
      investmentKey: "portfolio-as",
      investmentName: "Portfolio AS",
      investmentKind: "norwegian_private_company",
      taxTreatment: "fritaksmetoden",
      acquisitionDate: "2025-05-01",
      shareCount: 100,
      purchaseAmount: 50000,
      orgNumber: "999888777",
      bankTransactionId: purchaseBankTransaction.id,
      documentId: purchaseDocumentId,
      documentStatus: "attached",
    });
    const purchaseLines = sharePurchaseLedgerLines(purchasePayload);
    const { data: purchaseEntry, error: purchaseEntryError } = await owner
      .from("ledger_entries")
      .insert({
        company_id: companyId,
        income_year: 2025,
        entry_type: "share_purchase",
        memo: "Share purchase: Portfolio AS",
        lines: purchaseLines,
        created_by: ownerUser.id,
      })
      .select("id, entry_type, lines")
      .single();
    assert.ifError(purchaseEntryError);
    assert.equal(purchaseEntry.entry_type, "share_purchase");
    assert.deepEqual(purchaseEntry.lines, purchaseLines);
    const purchaseActionId = randomUUID();
    const { data: purchaseAction, error: purchaseActionError } = await owner
      .from("holding_actions")
      .insert({
        id: purchaseActionId,
        company_id: companyId,
        income_year: 2025,
        action_type: "share_purchase",
        action_date: purchasePayload.acquisition_date,
        payload: purchasePayload,
        ledger_entry_id: purchaseEntry.id,
        bank_transaction_id: purchaseBankTransaction.id,
        document_id: purchaseDocumentId,
        risk_level: "ready",
        created_by: ownerUser.id,
      })
      .select("id, action_type, ledger_entry_id, bank_transaction_id, document_id")
      .single();
    assert.ifError(purchaseActionError);
    assert.equal(purchaseAction.action_type, "share_purchase");
    assert.equal(purchaseAction.ledger_entry_id, purchaseEntry.id);
    assert.equal(purchaseAction.bank_transaction_id, purchaseBankTransaction.id);
    assert.equal(purchaseAction.document_id, purchaseDocumentId);
    const { data: purchasePosition, error: purchasePositionError } = await owner
      .from("investment_positions")
      .insert({
        company_id: companyId,
        investment_key: purchasePayload.investment_key,
        name: purchasePayload.investment_name,
        kind: purchasePayload.investment_kind,
        tax_treatment: purchasePayload.tax_treatment,
        org_number: purchasePayload.org_number,
        share_count: purchasePayload.share_count,
        cost_basis: purchasePayload.purchase_amount,
        created_by: ownerUser.id,
      })
      .select("id, investment_key, share_count, cost_basis")
      .single();
    assert.ifError(purchasePositionError);
    assert.equal(purchasePosition.investment_key, "portfolio-as");
    assert.equal(Number(purchasePosition.share_count), 100);
    assert.equal(Number(purchasePosition.cost_basis), 50000);
    const { error: purchaseBankMatchError } = await owner
      .from("bank_transactions")
      .update({ matched_action_id: purchaseAction.id })
      .eq("id", purchaseBankTransaction.id);
    assert.ifError(purchaseBankMatchError);
    const { data: reloadedPurchasePosition, error: reloadedPurchasePositionError } = await owner
      .from("investment_positions")
      .select("id, share_count, cost_basis")
      .eq("id", purchasePosition.id)
      .single();
    assert.ifError(reloadedPurchasePositionError);
    assert.equal(Number(reloadedPurchasePosition.share_count), 100);
    assert.equal(Number(reloadedPurchasePosition.cost_basis), 50000);
    const { data: outsiderPositions, error: outsiderPositionError } = await outsider
      .from("investment_positions")
      .select("id")
      .eq("id", purchasePosition.id);
    assert.ifError(outsiderPositionError);
    assert.deepEqual(outsiderPositions, []);
    const { error: outsiderPurchaseActionInsertError } = await outsider.from("holding_actions").insert({
      company_id: companyId,
      income_year: 2025,
      action_type: "share_purchase",
      action_date: purchasePayload.acquisition_date,
      payload: purchasePayload,
      ledger_entry_id: purchaseEntry.id,
      bank_transaction_id: purchaseBankTransaction.id,
      document_id: purchaseDocumentId,
      risk_level: "ready",
      created_by: outsiderUser.id,
    });
    assert.ok(outsiderPurchaseActionInsertError);
    const { error: outsiderPurchasePositionInsertError } = await outsider.from("investment_positions").insert({
      company_id: companyId,
      investment_key: "forbidden",
      name: "Forbidden AS",
      kind: "norwegian_private_company",
      tax_treatment: "fritaksmetoden",
      share_count: 1,
      cost_basis: 1,
      created_by: outsiderUser.id,
    });
    assert.ok(outsiderPurchasePositionInsertError);

    assert.throws(
      () =>
        validateShareSale({
          positionId: purchasePosition.id,
          investmentKey: "portfolio-as",
          investmentName: "Portfolio AS",
          currentShareCount: 100,
          currentCostBasis: 50000,
          saleDate: "2025-08-01",
          soldShareCount: 101,
          proceeds: 30000,
          documentStatus: "attached",
        }),
      (error) => error?.code === "sale_exceeds_position",
    );
    const saleDocumentId = randomUUID();
    const { error: saleDocumentError } = await owner.from("documents").insert({
      id: saleDocumentId,
      company_id: companyId,
      income_year: 2025,
      document_type: "share_sale_agreement",
      name: "sale.pdf",
      linked_to: "share_sale",
      status: "attached",
      storage_key: `companies/${companyId}/2025/${saleDocumentId}/sale.pdf`,
      created_by: ownerUser.id,
    });
    assert.ifError(saleDocumentError);
    const { data: saleBankTransaction, error: saleBankTransactionError } = await owner
      .from("bank_transactions")
      .insert({
        company_id: companyId,
        income_year: 2025,
        transaction_date: "2025-08-01",
        text: "Sale Portfolio AS",
        amount: 30000,
        balance: 10950,
        source_hash: `sale-bank-${randomUUID()}`,
        created_by: ownerUser.id,
      })
      .select("id, amount")
      .single();
    assert.ifError(saleBankTransactionError);
    const salePayload = validateShareSale({
      positionId: purchasePosition.id,
      investmentKey: "portfolio-as",
      investmentName: "Portfolio AS",
      currentShareCount: 100,
      currentCostBasis: 50000,
      saleDate: "2025-08-01",
      soldShareCount: 40,
      proceeds: 30000,
      bankTransactionId: saleBankTransaction.id,
      documentId: saleDocumentId,
      documentStatus: "attached",
    });
    assert.equal(salePayload.cost_basis_reduction, 20000);
    assert.equal(salePayload.gain_or_loss, 10000);
    const saleLines = shareSaleLedgerLines(salePayload);
    const { data: saleEntry, error: saleEntryError } = await owner
      .from("ledger_entries")
      .insert({
        company_id: companyId,
        income_year: 2025,
        entry_type: "share_sale",
        memo: "Share sale: Portfolio AS",
        lines: saleLines,
        created_by: ownerUser.id,
      })
      .select("id, entry_type, lines")
      .single();
    assert.ifError(saleEntryError);
    assert.deepEqual(saleEntry.lines, saleLines);
    const saleActionId = randomUUID();
    const { data: saleAction, error: saleActionError } = await owner
      .from("holding_actions")
      .insert({
        id: saleActionId,
        company_id: companyId,
        income_year: 2025,
        action_type: "share_sale",
        action_date: salePayload.sale_date,
        payload: salePayload,
        ledger_entry_id: saleEntry.id,
        bank_transaction_id: saleBankTransaction.id,
        document_id: saleDocumentId,
        risk_level: "ready",
        created_by: ownerUser.id,
      })
      .select("id, action_type, ledger_entry_id, bank_transaction_id, document_id")
      .single();
    assert.ifError(saleActionError);
    assert.equal(saleAction.action_type, "share_sale");
    const saleMovement = {
      action_id: saleAction.id,
      movement_type: "sale",
      movement_date: salePayload.sale_date,
      share_delta: -salePayload.sold_share_count,
      cost_basis_delta: -salePayload.cost_basis_reduction,
      amount: salePayload.proceeds,
      gain_or_loss: salePayload.gain_or_loss,
    };
    const { error: salePositionUpdateError } = await owner
      .from("investment_positions")
      .update({
        share_count: salePayload.remaining_share_count,
        cost_basis: salePayload.remaining_cost_basis,
        movements: [saleMovement],
        updated_at: new Date().toISOString(),
      })
      .eq("id", purchasePosition.id);
    assert.ifError(salePositionUpdateError);
    const { error: saleBankMatchError } = await owner
      .from("bank_transactions")
      .update({ matched_action_id: saleAction.id })
      .eq("id", saleBankTransaction.id);
    assert.ifError(saleBankMatchError);
    const { data: positionAfterPartialSale, error: partialSaleReloadError } = await owner
      .from("investment_positions")
      .select("id, share_count, cost_basis, movements")
      .eq("id", purchasePosition.id)
      .single();
    assert.ifError(partialSaleReloadError);
    assert.equal(Number(positionAfterPartialSale.share_count), 60);
    assert.equal(Number(positionAfterPartialSale.cost_basis), 30000);
    assert.equal(positionAfterPartialSale.movements[0].gain_or_loss, 10000);

    const fullSalePayload = validateShareSale({
      positionId: purchasePosition.id,
      investmentKey: "portfolio-as",
      investmentName: "Portfolio AS",
      currentShareCount: 60,
      currentCostBasis: 30000,
      saleDate: "2025-09-01",
      soldShareCount: 60,
      proceeds: 30000,
      documentStatus: "not_required",
    });
    assert.equal(fullSalePayload.remaining_share_count, 0);
    assert.equal(fullSalePayload.remaining_cost_basis, 0);
    const { error: fullSalePositionUpdateError } = await owner
      .from("investment_positions")
      .update({
        share_count: fullSalePayload.remaining_share_count,
        cost_basis: fullSalePayload.remaining_cost_basis,
        movements: [
          ...positionAfterPartialSale.movements,
          {
            action_id: "full-sale-test",
            movement_type: "sale",
            movement_date: fullSalePayload.sale_date,
            share_delta: -fullSalePayload.sold_share_count,
            cost_basis_delta: -fullSalePayload.cost_basis_reduction,
            amount: fullSalePayload.proceeds,
            gain_or_loss: fullSalePayload.gain_or_loss,
          },
        ],
        updated_at: new Date().toISOString(),
      })
      .eq("id", purchasePosition.id);
    assert.ifError(fullSalePositionUpdateError);
    const { data: positionAfterFullSale, error: fullSaleReloadError } = await owner
      .from("investment_positions")
      .select("share_count, cost_basis, movements")
      .eq("id", purchasePosition.id)
      .single();
    assert.ifError(fullSaleReloadError);
    assert.equal(Number(positionAfterFullSale.share_count), 0);
    assert.equal(Number(positionAfterFullSale.cost_basis), 0);
    assert.equal(positionAfterFullSale.movements.length, 2);

    const { error: outsiderSaleActionInsertError } = await outsider.from("holding_actions").insert({
      company_id: companyId,
      income_year: 2025,
      action_type: "share_sale",
      action_date: salePayload.sale_date,
      payload: salePayload,
      ledger_entry_id: saleEntry.id,
      bank_transaction_id: saleBankTransaction.id,
      document_id: saleDocumentId,
      risk_level: "ready",
      created_by: outsiderUser.id,
    });
    assert.ok(outsiderSaleActionInsertError);

    assert.throws(
      () =>
        validateOwnerDividend({
          decisionDate: "2025-06-01",
          paymentDate: "2025-06-15",
          totalAmount: 1000,
          distributableEquity: 5000,
          liquidityAfterPayment: 1000,
          documentStatus: "attached",
          allocations: [{ shareholderId: persistedShareholders[0].id, shareholderName: persistedShareholders[0].name, shareCount: 100, amount: 900 }],
        }),
      (error) => error?.code === "allocation_mismatch",
    );
    const ownerDividendPayload = validateOwnerDividend({
      decisionDate: "2025-06-01",
      paymentDate: "2025-06-15",
      totalAmount: 1000,
      distributableEquity: 5000,
      liquidityAfterPayment: 1000,
      documentStatus: "missing_accepted_warning",
      allocations: [{ shareholderId: persistedShareholders[0].id, shareholderName: persistedShareholders[0].name, shareCount: 100, amount: 1000 }],
    });
    const ownerDividendLines = ownerDividendLedgerLines(ownerDividendPayload);
    const { data: ownerDividendEntry, error: ownerDividendEntryError } = await owner
      .from("ledger_entries")
      .insert({
        company_id: companyId,
        income_year: 2025,
        entry_type: "dividend_to_owner",
        memo: "Cash dividend paid to shareholders",
        lines: ownerDividendLines,
        created_by: ownerUser.id,
      })
      .select("id, entry_type, lines")
      .single();
    assert.ifError(ownerDividendEntryError);
    assert.equal(ownerDividendEntry.entry_type, "dividend_to_owner");
    assert.deepEqual(ownerDividendEntry.lines, ownerDividendLines);
    const ownerDividendActionId = randomUUID();
    const { data: ownerDividendAction, error: ownerDividendActionError } = await owner
      .from("holding_actions")
      .insert({
        id: ownerDividendActionId,
        company_id: companyId,
        income_year: 2025,
        action_type: "dividend_to_owner",
        action_date: ownerDividendPayload.payment_date,
        payload: ownerDividendPayload,
        ledger_entry_id: ownerDividendEntry.id,
        risk_level: "ready",
        created_by: ownerUser.id,
      })
      .select("id, action_type, ledger_entry_id, payload")
      .single();
    assert.ifError(ownerDividendActionError);
    assert.equal(ownerDividendAction.action_type, "dividend_to_owner");
    assert.equal(ownerDividendAction.ledger_entry_id, ownerDividendEntry.id);
    const { error: ownerDividendDocumentError } = await owner
      .from("documents")
      .insert(ownerDividendCorporateDocumentRecords(companyId, 2025, ownerDividendAction.id, ownerUser.id));
    assert.ifError(ownerDividendDocumentError);
    const { data: corporateDocuments, error: corporateDocumentReloadError } = await owner
      .from("documents")
      .select("id, company_id, income_year, document_type, name, linked_to, status, retention_years, storage_key, created_by, created_at")
      .eq("linked_to", ownerDividendAction.id)
      .order("name", { ascending: true });
    assert.ifError(corporateDocumentReloadError);
    assert.equal(corporateDocuments.length, 2);
    assert.deepEqual(
      corporateDocuments.map((document) => document.document_type),
      ["corporate_document", "corporate_document"],
    );
    assert.ok(corporateDocuments.every((document) => document.status === "missing_placeholder"));
    const dividendArchive = buildPersistedCompanyArchive({
      company: persistedCompany,
      incomeYear: 2025,
      setups: [setup],
      shareholders: persistedShareholders,
      ledgerEntries: [ownerDividendEntry],
      documents: corporateDocuments,
      filingPreviews: [filingPreview],
      filingSubmissions: [filingSubmission],
    });
    assert.equal(dividendArchive.documents.length, 2);
    assert.deepEqual(
      dividendArchive.documents.map((document) => document.documentType),
      ["corporate_document", "corporate_document"],
    );
    const { error: outsiderOwnerDividendActionInsertError } = await outsider.from("holding_actions").insert({
      company_id: companyId,
      income_year: 2025,
      action_type: "dividend_to_owner",
      action_date: ownerDividendPayload.payment_date,
      payload: ownerDividendPayload,
      ledger_entry_id: ownerDividendEntry.id,
      risk_level: "ready",
      created_by: outsiderUser.id,
    });
    assert.ok(outsiderOwnerDividendActionInsertError);

    assert.throws(
      () =>
        validateShareholderLoan({
          loanDate: "2025-07-01",
          amount: 20000,
          direction: "company_to_personal_shareholder",
          counterpartyName: "Ola Nordmann",
          documentStatus: "attached",
          interestModelled: false,
          relatedPartySecurity: false,
        }),
      (error) => error?.code === "personal_shareholder_loan_blocked",
    );
    const loanDocumentId = randomUUID();
    const { error: loanDocumentError } = await owner.from("documents").insert({
      id: loanDocumentId,
      company_id: companyId,
      income_year: 2025,
      document_type: "shareholder_loan_agreement",
      name: "loan.pdf",
      linked_to: "shareholder_loan",
      status: "attached",
      storage_key: `companies/${companyId}/2025/${loanDocumentId}/loan.pdf`,
      created_by: ownerUser.id,
    });
    assert.ifError(loanDocumentError);
    const { data: loanBankTransaction, error: loanBankTransactionError } = await owner
      .from("bank_transactions")
      .insert({
        company_id: companyId,
        income_year: 2025,
        transaction_date: "2025-07-01",
        text: "Loan from shareholder",
        amount: 20000,
        balance: 30950,
        source_hash: `loan-bank-${randomUUID()}`,
        created_by: ownerUser.id,
      })
      .select("id, amount")
      .single();
    assert.ifError(loanBankTransactionError);
    const loanPayload = validateShareholderLoan({
      loanDate: "2025-07-01",
      amount: 20000,
      direction: "shareholder_to_company",
      counterpartyName: "Ola Nordmann",
      documentStatus: "attached",
      interestModelled: true,
      relatedPartySecurity: false,
      bankTransactionId: loanBankTransaction.id,
      documentId: loanDocumentId,
    });
    const loanLines = shareholderLoanLedgerLines(loanPayload);
    const { data: loanEntry, error: loanEntryError } = await owner
      .from("ledger_entries")
      .insert({
        company_id: companyId,
        income_year: 2025,
        entry_type: "shareholder_loan",
        memo: "Shareholder loan: Ola Nordmann",
        lines: loanLines,
        created_by: ownerUser.id,
      })
      .select("id, entry_type, lines")
      .single();
    assert.ifError(loanEntryError);
    assert.equal(loanEntry.entry_type, "shareholder_loan");
    assert.deepEqual(loanEntry.lines, loanLines);
    const loanActionId = randomUUID();
    const { data: loanAction, error: loanActionError } = await owner
      .from("holding_actions")
      .insert({
        id: loanActionId,
        company_id: companyId,
        income_year: 2025,
        action_type: "shareholder_loan",
        action_date: loanPayload.loan_date,
        payload: loanPayload,
        ledger_entry_id: loanEntry.id,
        bank_transaction_id: loanBankTransaction.id,
        document_id: loanDocumentId,
        risk_level: "ready",
        created_by: ownerUser.id,
      })
      .select("id, action_type, ledger_entry_id, bank_transaction_id, document_id")
      .single();
    assert.ifError(loanActionError);
    assert.equal(loanAction.action_type, "shareholder_loan");
    assert.equal(loanAction.ledger_entry_id, loanEntry.id);
    assert.equal(loanAction.bank_transaction_id, loanBankTransaction.id);
    assert.equal(loanAction.document_id, loanDocumentId);
    const { error: loanBankMatchError } = await owner
      .from("bank_transactions")
      .update({ matched_action_id: loanAction.id })
      .eq("id", loanBankTransaction.id);
    assert.ifError(loanBankMatchError);
    const { data: reloadedLoanEntry, error: reloadedLoanEntryError } = await owner
      .from("ledger_entries")
      .select("id, entry_type")
      .eq("id", loanEntry.id)
      .single();
    assert.ifError(reloadedLoanEntryError);
    assert.equal(reloadedLoanEntry.entry_type, "shareholder_loan");
    const { error: outsiderLoanActionInsertError } = await outsider.from("holding_actions").insert({
      company_id: companyId,
      income_year: 2025,
      action_type: "shareholder_loan",
      action_date: loanPayload.loan_date,
      payload: loanPayload,
      ledger_entry_id: loanEntry.id,
      bank_transaction_id: loanBankTransaction.id,
      document_id: loanDocumentId,
      risk_level: "ready",
      created_by: outsiderUser.id,
    });
    assert.ok(outsiderLoanActionInsertError);

    const taxEstimate = estimateAnnualTax({
      ledgerEntries: [{ entry_type: "admin_cost", lines: adminCostEntry.lines }],
      holdingActions: [{ action_type: "dividend_received", payload: dividendPayload }],
    });
    assert.equal(taxEstimate.status, "payable");
    assert.equal(taxEstimate.estimatedTax, 17.6);
    const taxDocumentId = randomUUID();
    const { error: taxDocumentError } = await owner.from("documents").insert({
      id: taxDocumentId,
      company_id: companyId,
      income_year: 2025,
      document_type: "tax_settlement",
      name: "tax-settlement.pdf",
      linked_to: "tax_settlement",
      status: "attached",
      storage_key: `companies/${companyId}/2025/${taxDocumentId}/tax-settlement.pdf`,
      created_by: ownerUser.id,
    });
    assert.ifError(taxDocumentError);
    const { data: taxBankTransaction, error: taxBankTransactionError } = await owner
      .from("bank_transactions")
      .insert({
        company_id: companyId,
        income_year: 2025,
        transaction_date: "2025-12-31",
        text: "Tax payment",
        amount: -17.6,
        balance: 30932.4,
        source_hash: `tax-bank-${randomUUID()}`,
        created_by: ownerUser.id,
      })
      .select("id, amount")
      .single();
    assert.ifError(taxBankTransactionError);
    const taxPayload = validateTaxSettlement({
      settlementDate: "2025-12-31",
      amount: taxEstimate.estimatedTax,
      settlementType: "payment",
      documentStatus: "attached",
      bankTransactionId: taxBankTransaction.id,
      documentId: taxDocumentId,
    });
    const taxLines = taxSettlementLedgerLines(taxPayload);
    const { data: taxEntry, error: taxEntryError } = await owner
      .from("ledger_entries")
      .insert({
        company_id: companyId,
        income_year: 2025,
        entry_type: "tax_settlement",
        memo: "Skatteoppgjør: payment",
        lines: taxLines,
        created_by: ownerUser.id,
      })
      .select("id, entry_type, lines")
      .single();
    assert.ifError(taxEntryError);
    assert.equal(taxEntry.entry_type, "tax_settlement");
    assert.deepEqual(taxEntry.lines, taxLines);
    const taxActionId = randomUUID();
    const { data: taxAction, error: taxActionError } = await owner
      .from("holding_actions")
      .insert({
        id: taxActionId,
        company_id: companyId,
        income_year: 2025,
        action_type: "tax_settlement",
        action_date: taxPayload.settlement_date,
        payload: taxPayload,
        ledger_entry_id: taxEntry.id,
        bank_transaction_id: taxBankTransaction.id,
        document_id: taxDocumentId,
        risk_level: "ready",
        created_by: ownerUser.id,
      })
      .select("id, action_type, ledger_entry_id, bank_transaction_id, document_id, payload, action_date, risk_level, blocker_code, created_by, created_at")
      .single();
    assert.ifError(taxActionError);
    assert.equal(taxAction.action_type, "tax_settlement");
    assert.equal(taxAction.ledger_entry_id, taxEntry.id);
    assert.equal(taxAction.document_id, taxDocumentId);
    const { error: taxBankMatchError } = await owner
      .from("bank_transactions")
      .update({ matched_action_id: taxAction.id })
      .eq("id", taxBankTransaction.id);
    assert.ifError(taxBankMatchError);
    const { data: reloadedTaxEntry, error: reloadedTaxEntryError } = await owner
      .from("ledger_entries")
      .select("id, entry_type")
      .eq("id", taxEntry.id)
      .single();
    assert.ifError(reloadedTaxEntryError);
    assert.equal(reloadedTaxEntry.entry_type, "tax_settlement");
    const { error: outsiderTaxActionInsertError } = await outsider.from("holding_actions").insert({
      company_id: companyId,
      income_year: 2025,
      action_type: "tax_settlement",
      action_date: taxPayload.settlement_date,
      payload: taxPayload,
      ledger_entry_id: taxEntry.id,
      bank_transaction_id: taxBankTransaction.id,
      document_id: taxDocumentId,
      risk_level: "ready",
      created_by: outsiderUser.id,
    });
    assert.ok(outsiderTaxActionInsertError);

    const manualJournal = validateManualJournal({
      warningAccepted: true,
      lines: [
        { account: "1800", description: "Manual investment correction", debit: 100, credit: 0 },
        { account: "1920", description: "Bank", debit: 0, credit: 100 },
      ],
    });
    const { data: manualEntry, error: manualEntryError } = await owner
      .from("ledger_entries")
      .insert({
        company_id: companyId,
        income_year: 2025,
        entry_type: "manual_journal",
        memo: "Manual sensitive correction",
        lines: manualJournal.lines,
        risk_flags: manualJournal.riskFlags,
        warning_accepted_by: ownerUser.id,
        warning_accepted_at: new Date().toISOString(),
        created_by: ownerUser.id,
      })
      .select("id, entry_type, risk_flags, warning_accepted_by")
      .single();
    assert.ifError(manualEntryError);
    assert.equal(manualEntry.entry_type, "manual_journal");
    assert.equal(manualEntry.risk_flags[0].account, "1800");
    assert.equal(manualEntry.warning_accepted_by, ownerUser.id);

    const { error: outsiderManualEntryError } = await outsider.from("ledger_entries").insert({
      company_id: companyId,
      income_year: 2025,
      entry_type: "manual_journal",
      memo: "Forbidden manual entry",
      lines: manualJournal.lines,
      risk_flags: manualJournal.riskFlags,
      warning_accepted_by: outsiderUser.id,
      warning_accepted_at: new Date().toISOString(),
      created_by: outsiderUser.id,
    });
    assert.ok(outsiderManualEntryError);

    const { data: periodLock, error: periodLockError } = await owner
      .from("period_locks")
      .insert({
        company_id: companyId,
        income_year: 2025,
        reason: "Filing fullført og arkivert.",
        locked_by: ownerUser.id,
      })
      .select("id, company_id, income_year, reason, locked_by, locked_at")
      .single();
    assert.ifError(periodLockError);
    assert.equal(periodLock.company_id, companyId);
    assert.equal(periodLock.income_year, 2025);
    assert.equal(periodLock.locked_by, ownerUser.id);

    const { error: periodLockAuditError } = await owner.from("audit_events").insert({
      company_id: companyId,
      actor_id: ownerUser.id,
      category: "filing",
      action: "period_locked",
      message: "Inntektsår 2025 låst: Filing fullført og arkivert.",
    });
    assert.ifError(periodLockAuditError);

    const { data: reloadedPeriodLocks, error: reloadedPeriodLockError } = await owner
      .from("period_locks")
      .select("id, income_year, reason")
      .eq("company_id", companyId);
    assert.ifError(reloadedPeriodLockError);
    assert.deepEqual(reloadedPeriodLocks, [
      {
        id: periodLock.id,
        income_year: 2025,
        reason: "Filing fullført og arkivert.",
      },
    ]);

    const { data: outsiderPeriodLocks, error: outsiderPeriodLockError } = await outsider
      .from("period_locks")
      .select("id")
      .eq("company_id", companyId);
    assert.ifError(outsiderPeriodLockError);
    assert.deepEqual(outsiderPeriodLocks, []);

    const { error: readOnlyPeriodLockError } = await readOnly.from("period_locks").insert({
      company_id: companyId,
      income_year: 2027,
      reason: "Read-only should not lock.",
      locked_by: readOnlyUser.id,
    });
    assert.ok(readOnlyPeriodLockError);

    const { error: lockedBankImportError } = await owner.from("bank_transactions").insert({
      company_id: companyId,
      income_year: 2025,
      transaction_date: "2025-12-31",
      text: "Late locked import",
      amount: -10,
      balance: 29940,
      source_hash: `locked-bank-${randomUUID()}`,
      created_by: ownerUser.id,
    });
    assert.ok(lockedBankImportError);

    const openTransaction = importedBankTransactions.find((transaction) => Number(transaction.amount) === 30000);
    assert.ok(openTransaction);
    const { data: lockedBankMatchRows, error: lockedBankMatchError } = await owner
      .from("bank_transactions")
      .update({ accepted_warning: true })
      .eq("id", openTransaction.id)
      .select("id");
    assert.ok(lockedBankMatchError || lockedBankMatchRows.length === 0);

    const { error: lockedAdminCostError } = await owner.from("ledger_entries").insert({
      company_id: companyId,
      income_year: 2025,
      entry_type: "admin_cost",
      memo: "Locked admin cost",
      lines: adminCostLines,
      created_by: ownerUser.id,
    });
    assert.ok(lockedAdminCostError);

    const { error: lockedManualJournalError } = await owner.from("ledger_entries").insert({
      company_id: companyId,
      income_year: 2025,
      entry_type: "manual_journal",
      memo: "Locked manual journal",
      lines: manualJournal.lines,
      risk_flags: manualJournal.riskFlags,
      warning_accepted_by: ownerUser.id,
      warning_accepted_at: new Date().toISOString(),
      created_by: ownerUser.id,
    });
    assert.ok(lockedManualJournalError);

    const { error: periodLock2026Error } = await owner.from("period_locks").insert({
      company_id: companyId,
      income_year: 2026,
      reason: "Approved prior-year migration boundary.",
      locked_by: ownerUser.id,
    });
    assert.ifError(periodLock2026Error);
    const { error: lockedOpeningSetupError } = await owner.from("opening_balance_setups").insert({
      company_id: companyId,
      income_year: 2026,
      bank_balance: 30000,
      share_capital: 30000,
      share_count: 100,
      nominal_value: 300,
      created_by: ownerUser.id,
    });
    assert.ok(lockedOpeningSetupError);

    const documentId = randomUUID();
    const storageKey = documentStorageKey(companyId, 2025, documentId, "bank.pdf");
    const { error: uploadError } = await owner.storage
      .from(COMPANY_DOCUMENTS_BUCKET)
      .upload(storageKey, new Blob(["test"], { type: "application/pdf" }), {
        contentType: "application/pdf",
      });
    assert.ifError(uploadError);

    const { error: documentInsertError } = await owner.from("documents").insert({
      id: documentId,
      company_id: companyId,
      income_year: 2025,
      document_type: "bank_statement",
      name: "bank.pdf",
      linked_to: "aksjonærregisteroppgaven",
      status: "attached",
      storage_key: storageKey,
      created_by: ownerUser.id,
    });
    assert.ifError(documentInsertError);

    const { data: ownerDocuments, error: ownerDocumentError } = await owner
      .from("documents")
      .select("id, company_id, income_year, document_type, name, linked_to, status, retention_years, storage_key, created_by, created_at")
      .eq("company_id", companyId)
      .eq("income_year", 2025);
    assert.ifError(ownerDocumentError);
    assert.ok(ownerDocuments.length >= 2);

    const { data: persistedLedgerEntries, error: persistedLedgerError } = await owner
      .from("ledger_entries")
      .select("id, company_id, setup_id, income_year, entry_type, memo, lines, risk_flags, warning_accepted_by, warning_accepted_at, created_by, created_at")
      .eq("company_id", companyId)
      .eq("income_year", 2025);
    assert.ifError(persistedLedgerError);
    const { data: persistedHoldingActions, error: persistedHoldingActionsError } = await owner
      .from("holding_actions")
      .select("id, company_id, income_year, action_type, action_date, payload, ledger_entry_id, bank_transaction_id, document_id, risk_level, blocker_code, created_by, created_at")
      .eq("company_id", companyId)
      .eq("income_year", 2025);
    assert.ifError(persistedHoldingActionsError);
    const { data: persistedBillingAccounts, error: persistedBillingError } = await owner
      .from("billing_accounts")
      .select("company_id, pricing_plan, monthly_nok, filing_package_nok, founder_cohort_number, subscription_active, filing_package_paid, supported_case, refund_eligible, no_charge_reason, updated_by, created_at, updated_at")
      .eq("company_id", companyId);
    assert.ifError(persistedBillingError);
    const { data: persistedAuthorityPermissions, error: persistedAuthorityError } = await owner
      .from("authority_permissions")
      .select("id, company_id, obligation, submitter_user_id, confirmed_by, confirmed_at, production_enabled, updated_at")
      .eq("company_id", companyId);
    assert.ifError(persistedAuthorityError);
    const archive = buildPersistedCompanyArchive({
      company: persistedCompany,
      incomeYear: 2025,
      setups: [setup],
      shareholders: persistedShareholders,
      ledgerEntries: persistedLedgerEntries,
      documents: ownerDocuments,
      holdingActions: persistedHoldingActions,
      billingAccounts: persistedBillingAccounts,
      authorityPermissions: persistedAuthorityPermissions,
      filingPreviews: [filingPreview],
      filingSubmissions: [filingSubmission],
    });
    assert.equal(archive.source, "supabase_persisted_workspace");
    assert.equal(archive.company.org_number, orgNumber);
    assert.equal(archive.openingBalanceSetups[0].share_count, 100);
    assert.equal(archive.documents.find((document) => document.id === documentId).storageKey, storageKey);
    assert.equal(archive.readinessReports[0].status, "ready");
    assert.equal(archive.simulatedReceipts[0].receiptId, filingSubmission.receipt_id);
    assert.equal(archive.simulatedReceipts[0].receiptMetadata.receiptId, filingSubmission.receipt_id);
    assert.equal(archive.rf1086Submissions[0].feedbackItems[0].code, "RF1086_ACCEPTED");
    assert.equal(archive.rf1086Submissions[0].submittedPayloadReference.payloadHash, filingSubmission.payload_hash);
    assert.equal(archive.rf1086Submissions[0].submittedPayload.hovedskjemaXml, filingPreview.hovedskjema_xml);
    assert.equal(archive.taxSettlements[0].ledgerEntryId, taxEntry.id);
    assert.equal(archive.taxSettlements[0].documentId, taxDocumentId);
    assert.equal(archive.taxSettlements[0].document.id, taxDocumentId);
    assert.equal(archive.billingAccounts[0].refund_eligible, true);
    assert.equal(archive.authorityPermissions[0].obligation, "aksjonaerregisteroppgaven");

    const { data: outsiderArchiveCompany, error: outsiderArchiveCompanyError } = await outsider
      .from("companies")
      .select("id")
      .eq("id", companyId);
    assert.ifError(outsiderArchiveCompanyError);
    assert.deepEqual(outsiderArchiveCompany, []);

    const { data: signed, error: signedError } = await owner.storage
      .from(COMPANY_DOCUMENTS_BUCKET)
      .createSignedUrl(storageKey, 60);
    assert.ifError(signedError);
    assert.ok(signed.signedUrl.includes("/storage/v1/"));

    const { data: outsiderDocuments, error: outsiderDocumentError } = await outsider
      .from("documents")
      .select("id")
      .eq("id", documentId);
    assert.ifError(outsiderDocumentError);
    assert.deepEqual(outsiderDocuments, []);

    const { data: reviewerDocuments, error: reviewerDocumentError } = await reviewer
      .from("documents")
      .select("id")
      .eq("id", documentId);
    assert.ifError(reviewerDocumentError);
    assert.deepEqual(reviewerDocuments, [{ id: documentId }]);

    const { data: readOnlyDocuments, error: readOnlyDocumentError } = await readOnly
      .from("documents")
      .select("id")
      .eq("id", documentId);
    assert.ifError(readOnlyDocumentError);
    assert.deepEqual(readOnlyDocuments, [{ id: documentId }]);

    const { data: outsiderSigned, error: outsiderSignedError } = await outsider.storage
      .from(COMPANY_DOCUMENTS_BUCKET)
      .createSignedUrl(storageKey, 60);
    assert.equal(outsiderSigned, null);
    assert.ok(outsiderSignedError);

    const reviewerStorageKey = documentStorageKey(companyId, 2025, randomUUID(), "reviewer.pdf");
    const { error: reviewerUploadError } = await reviewer.storage
      .from(COMPANY_DOCUMENTS_BUCKET)
      .upload(reviewerStorageKey, new Blob(["reviewer"], { type: "application/pdf" }), {
        contentType: "application/pdf",
      });
    assert.ok(reviewerUploadError);

    const readOnlyStorageKey = documentStorageKey(companyId, 2025, randomUUID(), "readonly.pdf");
    const { error: readOnlyUploadError } = await readOnly.storage
      .from(COMPANY_DOCUMENTS_BUCKET)
      .upload(readOnlyStorageKey, new Blob(["readonly"], { type: "application/pdf" }), {
        contentType: "application/pdf",
      });
    assert.ok(readOnlyUploadError);

    await owner.storage.from(COMPANY_DOCUMENTS_BUCKET).remove([storageKey]);
  } finally {
    if (companyId) {
      await admin.from("companies").delete().eq("id", companyId);
    }
    await admin.auth.admin.deleteUser(ownerUser.id);
    await admin.auth.admin.deleteUser(outsiderUser.id);
    await admin.auth.admin.deleteUser(reviewerUser.id);
    await admin.auth.admin.deleteUser(readOnlyUser.id);
  }
  },
);
