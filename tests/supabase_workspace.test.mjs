import assert from "node:assert/strict";
import { randomUUID } from "node:crypto";
import { readFile } from "node:fs/promises";
import { existsSync, readFileSync } from "node:fs";
import test from "node:test";

import { createClient } from "@supabase/supabase-js";
import pg from "pg";

import { buildPersistedCompanyArchive } from "../app/lib/archive.ts";
import { assertBankTransactionMatchesCost, buildAdminCostLedgerLines, parseBankCsv } from "../app/lib/bank.ts";
import { COMPANY_DOCUMENTS_BUCKET, documentStorageKey } from "../app/lib/documents.ts";
import { validateManualJournal } from "../app/lib/manual-journal.ts";
import { openingBalanceLedgerLines } from "../app/lib/opening-balance.ts";
import { buildNoActivityRf1086Case, renderRf1086PreviewWithPython } from "../app/lib/rf1086.ts";
import { simulateRf1086SubmissionWithPython } from "../app/lib/rf1086-submission.ts";
import { assertAdvisoryCanBeAcknowledged, assertNoHardReviewBlocks } from "../app/lib/review.ts";

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

    const { error: ledgerError } = await owner.from("ledger_entries").insert({
      company_id: companyId,
      setup_id: setup.id,
      income_year: 2025,
      entry_type: "opening_balance",
      memo: "Åpningsbalanse for Talli-start",
      lines: openingBalanceLedgerLines(openingInput),
      created_by: ownerUser.id,
    });
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
    assert.equal(filingPreview.source, "python_rf1086_engine");

    const simulatedSubmission = simulateRf1086SubmissionWithPython(filingPreview, ownerUser.id, {
      authorityConfirmed: true,
      previewConfirmed: true,
    });
    assert.equal(simulatedSubmission.status, "receipt_stored");
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
          status: simulatedSubmission.status,
          authority_confirmed_by: simulatedSubmission.authority_confirmed_by,
          authority_confirmed_at: simulatedSubmission.authority_confirmed_at,
          preview_confirmed_by: simulatedSubmission.preview_confirmed_by,
          preview_confirmed_at: simulatedSubmission.preview_confirmed_at,
          calls: simulatedSubmission.calls,
          receipt_id: simulatedSubmission.receipt_id,
          feedback_document_ids: simulatedSubmission.feedback_document_ids,
          failure_code: simulatedSubmission.failure_code,
          failure_message: simulatedSubmission.failure_message,
          created_by: ownerUser.id,
        },
        { onConflict: "preview_id" },
      )
      .select("id, preview_id, company_id, income_year, filing, mode, status, calls, receipt_id, feedback_document_ids, authority_confirmed_at, preview_confirmed_at, created_at, updated_at")
      .single();
    assert.ifError(filingSubmissionError);
    assert.equal(filingSubmission.status, "receipt_stored");
    assert.equal(filingSubmission.calls.length, 4);

    const retrySubmission = simulateRf1086SubmissionWithPython(filingPreview, ownerUser.id, {
      authorityConfirmed: true,
      previewConfirmed: true,
    });
    const { error: retryError } = await owner.from("filing_submissions").upsert(
      {
        preview_id: filingPreview.id,
        company_id: companyId,
        setup_id: setup.id,
        income_year: 2025,
        filing: filingPreview.filing,
        mode: "simulation",
        status: retrySubmission.status,
        authority_confirmed_by: retrySubmission.authority_confirmed_by,
        authority_confirmed_at: retrySubmission.authority_confirmed_at,
        preview_confirmed_by: retrySubmission.preview_confirmed_by,
        preview_confirmed_at: retrySubmission.preview_confirmed_at,
        calls: retrySubmission.calls,
        receipt_id: retrySubmission.receipt_id,
        feedback_document_ids: retrySubmission.feedback_document_ids,
        failure_code: retrySubmission.failure_code,
        failure_message: retrySubmission.failure_message,
        created_by: ownerUser.id,
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
      .select("id, receipt_id")
      .eq("preview_id", filingPreview.id);
    assert.ifError(reloadSubmissionError);
    assert.equal(reloadedSubmissions.length, 1);
    assert.equal(reloadedSubmissions[0].receipt_id, simulatedSubmission.receipt_id);

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
      .eq("id", documentId);
    assert.ifError(ownerDocumentError);
    assert.equal(ownerDocuments.length, 1);

    const { data: persistedLedgerEntries, error: persistedLedgerError } = await owner
      .from("ledger_entries")
      .select("id, company_id, setup_id, income_year, entry_type, memo, lines, risk_flags, warning_accepted_by, warning_accepted_at, created_by, created_at")
      .eq("company_id", companyId)
      .eq("income_year", 2025);
    assert.ifError(persistedLedgerError);
    const archive = buildPersistedCompanyArchive({
      company: persistedCompany,
      incomeYear: 2025,
      setups: [setup],
      shareholders: persistedShareholders,
      ledgerEntries: persistedLedgerEntries,
      documents: ownerDocuments,
      filingPreviews: [filingPreview],
      filingSubmissions: [filingSubmission],
    });
    assert.equal(archive.source, "supabase_persisted_workspace");
    assert.equal(archive.company.org_number, orgNumber);
    assert.equal(archive.openingBalanceSetups[0].share_count, 100);
    assert.equal(archive.documents[0].storageKey, storageKey);
    assert.equal(archive.readinessReports[0].status, "ready");
    assert.equal(archive.simulatedReceipts[0].receiptId, filingSubmission.receipt_id);

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

    const { data: outsiderSigned, error: outsiderSignedError } = await outsider.storage
      .from(COMPANY_DOCUMENTS_BUCKET)
      .createSignedUrl(storageKey, 60);
    assert.equal(outsiderSigned, null);
    assert.ok(outsiderSignedError);

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
