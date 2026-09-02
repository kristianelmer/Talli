import assert from "node:assert/strict";
import { createHash, createHmac, randomUUID } from "node:crypto";
import { readFile, readdir } from "node:fs/promises";
import { existsSync, readFileSync } from "node:fs";
import test from "node:test";

import { createClient } from "@supabase/supabase-js";
import pg from "pg";

import { buildPersistedCompanyArchive } from "../apps/web/app/lib/archive.ts";
import { annualConfirmations, buildYearEndInterviewAnswers, noActivityConfirmed } from "../apps/web/app/lib/annual-data.ts";
import { evaluateAnnualReadinessGates } from "../apps/web/app/lib/annual-readiness.ts";
import { productionAuthorityGate } from "../apps/web/app/lib/authority-permission.ts";
import { buildBillingAccount, productionBillingGate } from "../apps/web/app/lib/billing.ts";
import { buildCompanyTaxReturnEvidencePersistence } from "../apps/web/app/lib/company-tax-return-submission.ts";
import { assertNoBlockingFilingOverrides, validateFilingOverride } from "../apps/web/app/lib/filing-overrides.ts";
import { buildNoActivityRf1086Case, renderRf1086PreviewWithPython } from "../apps/web/app/lib/rf1086.ts";
import {
  Rf1086ProductionAdapterDisabledError,
  rf1086PayloadHash,
  rf1086ReceiptMetadata,
  rf1086SubmissionFeedbackItems,
  rf1086SubmissionIdempotencyKey,
  rf1086SubmittedPayloadReference,
  rf1086SubmittedPayloadSnapshot,
  runRf1086SubmissionAdapter,
} from "../apps/web/app/lib/rf1086-submission.ts";
import { assertAdvisoryCanBeAcknowledged, assertNoHardReviewBlocks } from "../apps/web/app/lib/review.ts";
import { shareholderLoanLedgerLines, validateShareholderLoan } from "../apps/web/app/lib/shareholder-loan.ts";
import {
  estimateAnnualTax,
  taxSettlementLedgerLines,
  validateTaxSettlement,
} from "../apps/web/app/lib/tax-settlement.ts";

const requiredEnv = ["SUPABASE_URL", "SUPABASE_ANON_KEY", "SUPABASE_SERVICE_ROLE_KEY"];

const invitationTokenHash = async (token) => createHash("sha256").update(token).digest("hex");
const bankSourceHash = (value) => createHash("sha256").update(value).digest("hex");
const invitationExpiry = () => new Date(Date.now() + 14 * 24 * 60 * 60 * 1000).toISOString();
const invitationDeliveryEvent = ({ recipientEmail, queuedAt = new Date().toISOString() }) => ({
  channel: "email",
  status: "queued",
  template: "workspace_invitation",
  recipientEmail: recipientEmail.trim().toLowerCase(),
  queuedAt,
});

async function listRlsVisibleCompanies(client, userId) {
  const { data: memberships, error: membershipError } = await client
    .from("company_memberships")
    .select("company_id")
    .eq("user_id", userId)
    .not("accepted_at", "is", null);
  if (membershipError || !memberships?.length) {
    return { companies: [], error: membershipError?.message ?? null };
  }
  const { data, error } = await client
    .from("companies")
    .select("id")
    .in("id", memberships.map(({ company_id }) => company_id))
    .order("created_at", { ascending: false });
  return { companies: data ?? [], error: error?.message ?? null };
}

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
  const migrationFiles = (await readdir("supabase/migrations"))
    .filter((file) => file.endsWith(".sql"))
    .sort();
  const client = new pg.Client({
    ...getDatabaseConfig(),
  });
  await client.connect();
  try {
    const latestMigrationState = await client.query(String.raw`
      select pg_catalog.to_regprocedure(
        'public.company_access_complete_invitation_side_effect(uuid)'
      ) is not null
      and pg_catalog.to_regprocedure(
        'public.company_access_auth_uid_v1()'
      ) is not null
      and pg_catalog.to_regprocedure(
        'public.company_access_auth_jwt_v1()'
      ) is not null as company_access_expand_applied
    `);
    if (!latestMigrationState.rows[0]?.company_access_expand_applied) {
      for (const migrationFile of migrationFiles) {
        const sql = await readFile(`supabase/migrations/${migrationFile}`, "utf8");
        await client.query(sql);
      }
    }
    // This current-application security rehearsal runs after Release C. The
    // automatic migration directory intentionally stops at the mixed-revision
    // overlap, so apply the staged immutable contract artifact explicitly.
    const companyAccessContract = await readFile(
      "supabase/contract-migrations/20260801091000_company_access_invitations_contract.sql",
      "utf8",
    );
    await client.query(companyAccessContract);
    const contractState = await client.query(String.raw`
      select not pg_catalog.has_table_privilege(
        'authenticated', 'public.company_invitations', 'INSERT'
      ) as invitation_insert_contracted
    `);
    assert.equal(
      contractState.rows[0]?.invitation_insert_contracted,
      true,
      "current-app rehearsal must explicitly reach the company-access contract state",
    );
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
  const [databaseName, rawParams = ""] = databaseAndParams.split("?", 2);
  const database = databaseName || "postgres";
  const portColon = hostPort.lastIndexOf(":");
  const host = portColon === -1 ? hostPort : hostPort.slice(0, portColon);
  const port = portColon === -1 ? 5432 : Number(hostPort.slice(portColon + 1));
  if (!host || !Number.isFinite(port)) {
    return null;
  }
  const sslMode = new URLSearchParams(rawParams).get("sslmode");
  const ssl = sslMode === "disable" || host === "127.0.0.1" || host === "localhost"
    ? false
    : { rejectUnauthorized: false };
  return { host, port, database, user, password, ssl };
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

async function insertDocumentFixture(document) {
  const database = new pg.Client({ ...getDatabaseConfig() });
  try {
    await database.connect();
    await database.query("begin");
    await database.query(String.raw`
      do $authority$ begin
        execute pg_catalog.format('grant documents_store_owner to %I', current_user);
      end $authority$
    `);
    await database.query(
      `insert into public.documents (
        id, company_id, income_year, document_type, name, linked_to, status,
        retention_years, storage_key, created_by, content_type, byte_length,
        content_sha256, final_status
      ) values ($1,$2,$3,$4,$5,$6,$7,5,$8,$9,'application/pdf',10,$10,$7)`,
      [
        document.id, document.company_id, document.income_year,
        document.document_type, document.name, document.linked_to,
        document.status, document.storage_key, document.created_by,
        "a".repeat(64),
      ],
    );
    await database.query(String.raw`
      do $authority$ begin
        execute pg_catalog.format('revoke documents_store_owner from %I', current_user);
      end $authority$
    `);
    await database.query("commit");
  } catch (error) {
    await database.query("rollback").catch(() => undefined);
    throw error;
  } finally {
    await database.end().catch(() => undefined);
  }
}

async function listDocumentFixtures(companyId, incomeYear) {
  const database = new pg.Client({ ...getDatabaseConfig() });
  try {
    await database.connect();
    await database.query("begin");
    await database.query(String.raw`
      do $authority$ begin
        execute pg_catalog.format('grant documents_store_owner to %I', current_user);
      end $authority$
    `);
    const result = await database.query(
      `select id, company_id, income_year, document_type, name, linked_to, status,
        retention_years, storage_key, created_by, created_at, removed_at,
        removed_by, removal_reason
      from public.documents where company_id=$1 and income_year=$2
      order by created_at, id`,
      [companyId, incomeYear],
    );
    await database.query(String.raw`
      do $authority$ begin
        execute pg_catalog.format('revoke documents_store_owner from %I', current_user);
      end $authority$
    `);
    await database.query("commit");
    return result.rows;
  } catch (error) {
    await database.query("rollback").catch(() => undefined);
    throw error;
  } finally {
    await database.end().catch(() => undefined);
  }
}

async function assertNoError(resultPromise) {
  const { error } = await resultPromise;
  assert.ifError(error);
}

async function collectCleanupError(step, errors) {
  try {
    await step();
  } catch (error) {
    errors.push(error);
  }
}

function throwWithCleanupErrors(primaryError, cleanupErrors) {
  if (primaryError && cleanupErrors.length) {
    throw new AggregateError(
      [primaryError, ...cleanupErrors],
      "Supabase workspace test and fixture cleanup both failed",
    );
  }
  if (primaryError) throw primaryError;
  if (cleanupErrors.length) {
    throw new AggregateError(cleanupErrors, "Supabase workspace fixture cleanup failed");
  }
}

async function deleteWorkspaceCompanyFixture(companyId) {
  const database = new pg.Client({ ...getDatabaseConfig() });
  let connected = false;
  let operationError;
  const cleanupErrors = [];
  try {
    await database.connect();
    connected = true;
    await database.query("begin");
    await database.query(String.raw`
      do $authority$ begin
        execute pg_catalog.format('grant documents_store_owner to %I', current_user);
      end $authority$
    `);
    await database.query(
      `select pg_catalog.set_config(
        'talli.verified_actor_id',
        (select company.created_by::text from public.companies company where company.id = $1),
        true
      )`,
      [companyId],
    );
    for (const table of [
      "production_feedback_artifacts",
      "filing_approval_snapshots",
      "company_archive_export_receipts",
      "company_archive_export_attempts",
      "company_deletion_reviews",
      "customer_agreement_acceptances",
      "corporate_document_events",
      "corporate_decision_finalizations",
      "corporate_document_artifacts",
      "corporate_document_sets",
      "corporate_decisions",
      "bank_suggestion_acceptances",
      "bank_transactions",
      "investment_lot_allocations",
      "investment_lots",
      "investment_positions",
      "filing_review_comments",
      "filing_submissions",
      "holding_actions",
      "documents",
      "authority_test_runs",
      "authority_permissions",
      "filing_previews",
      "ledger_entries",
      "opening_shareholders",
      "opening_balance_setups",
      "billing_accounts",
      "audit_events",
    ]) {
      await database.query(`delete from public.${table} where company_id = $1`, [companyId]);
    }
    await database.query("delete from public.company_archive_source_generations where company_id = $1", [companyId]);
    await database.query("delete from public.companies where id = $1", [companyId]);
    await database.query(String.raw`
      do $authority$ begin
        execute pg_catalog.format('revoke documents_store_owner from %I', current_user);
      end $authority$
    `);
    await database.query("commit");
  } catch (error) {
    operationError = error;
    if (connected) {
      await collectCleanupError(() => database.query("rollback"), cleanupErrors);
    }
  } finally {
    if (connected) {
      await collectCleanupError(() => database.end(), cleanupErrors);
    }
  }
  throwWithCleanupErrors(operationError, cleanupErrors);
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

function totpCode(secret, now = Date.now()) {
  const alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567";
  const normalized = secret.toUpperCase().replace(/=+$/u, "").replace(/\s+/gu, "");
  let bits = "";
  for (const character of normalized) {
    const value = alphabet.indexOf(character);
    assert.notEqual(value, -1, "Supabase returned an invalid base32 TOTP secret");
    bits += value.toString(2).padStart(5, "0");
  }
  const bytes = Buffer.alloc(Math.floor(bits.length / 8));
  for (let index = 0; index < bytes.length; index += 1) {
    bytes[index] = Number.parseInt(bits.slice(index * 8, index * 8 + 8), 2);
  }
  const counter = Buffer.alloc(8);
  counter.writeBigUInt64BE(BigInt(Math.floor(now / 30_000)));
  const digest = createHmac("sha1", bytes).update(counter).digest();
  const offset = digest.at(-1) & 0x0f;
  const binary = (digest.readUInt32BE(offset) & 0x7fffffff) % 1_000_000;
  return String(binary).padStart(6, "0");
}

async function elevateToAal2(client) {
  const { data: enrollment, error: enrollmentError } = await client.auth.mfa.enroll({
    factorType: "totp",
    friendlyName: `company-tax-${randomUUID()}`,
  });
  assert.ifError(enrollmentError);
  assert.ok(enrollment?.id);
  assert.ok(enrollment?.totp?.secret);
  const { data: challenge, error: challengeError } = await client.auth.mfa.challenge({
    factorId: enrollment.id,
  });
  assert.ifError(challengeError);
  const { error: verificationError } = await client.auth.mfa.verify({
    factorId: enrollment.id,
    challengeId: challenge.id,
    code: totpCode(enrollment.totp.secret),
  });
  assert.ifError(verificationError);
  const { data: assurance, error: assuranceError } = await client.auth.mfa.getAuthenticatorAssuranceLevel();
  assert.ifError(assuranceError);
  assert.equal(assurance.currentLevel, "aal2");
}

function companyTaxTt02Persistence({ companyId, orgNumber, ownerId }) {
  const instanceId = `51549454/${randomUUID()}`;
  const envelopeDataId = randomUUID();
  const receiptDataId = randomUUID();
  const archiveReference = `https://platform.tt02.altinn.no/storage/api/v1/instances/${instanceId}`;
  return buildCompanyTaxReturnEvidencePersistence({
    companyId,
    expectedCompanyOrgNumber: orgNumber,
    expectedIncomeYear: 2025,
    evidenceUrl: "https://evidence.example/company-tax-tt02.json",
    recordedBy: ownerId,
    evidence: {
      schemaVersion: 2,
      status: "submitted_and_receipted",
      environment: "test",
      productionEnabled: false,
      companyOrgNumber: orgNumber,
      incomeYear: 2025,
      scope: "skatteetaten:formueinntekt/skattemelding altinn:instances.read altinn:instances.write",
      systemUserResource: "app_skd_formueinntekt-skattemelding-v2",
      payloadHashes: {
        skattemelding: "a".repeat(64),
        naeringsspesifikasjon: "b".repeat(64),
        validationEnvelope: "c".repeat(64),
        submissionEnvelope: "d".repeat(64),
      },
      localSchemaValidation: {
        status: "passed",
        schemas: [
          "skattemeldingUpersonlig_v5_ekstern.xsd",
          "naeringsspesifikasjon_v6_ekstern.xsd",
          "skattemeldingognaeringsspesifikasjonrequest_v2_kompakt.xsd",
        ],
      },
      authorityValidation: { result: "validertOK", failureReasons: [] },
      currentDocumentReferenceHash: "e".repeat(64),
      currentDocumentReference: "DATABASE_TEST_REFERENCE",
      sourceXml: "<skattemelding>DATABASE_TEST_XML</skattemelding>",
      partyNumber: "DATABASE_TEST_PARTY",
      accessToken: "DATABASE_TEST_TOKEN",
      privateKeyPem: "DATABASE_TEST_KEY",
      personalIdentifier: "DATABASE_TEST_PERSON",
      instance: {
        id: instanceId,
        envelopeUploaded: true,
        envelopeDataId,
        fileScanResult: "Clean",
        confirmationPrepared: true,
        processTask: "confirmation",
      },
      confirmationUrl: `https://skatt-test.sits.no/web/skattemelding-visning/altinn?appId=skd/formueinntekt-skattemelding-v2&instansId=${instanceId}`,
      validatedAt: "2026-07-14T12:20:00.000Z",
      confirmationPreparedAt: "2026-07-14T12:21:00.000Z",
      receipt: {
        dataId: receiptDataId,
        dataType: "tilbakemelding",
        contentType: "application/xml",
        byteLength: 527,
        contentSha256: "f".repeat(64),
        reference: `${archiveReference}/data/${receiptDataId}`,
      },
      submission: {
        submitted: true,
        processTask: null,
        processEndedAt: "2026-07-14T12:30:00.000Z",
        archived: true,
        archivedAt: "2026-07-14T12:31:00.000Z",
        archiveReference,
      },
      receiptRetrievedAt: "2026-07-14T12:32:00.000Z",
      secretsStored: false,
    },
  });
}

test(
  "Supabase authenticated workspace persists owner data and denies outsider",
  { skip: hasRequiredEnv() ? false : "Supabase URL/keys or usable DATABASE_URL missing" },
  async () => {
  await applyMigration();
  const admin = serviceClient();
  const orgNumber = `${Math.floor(100000000 + Math.random() * 899999999)}`;
  const createdUsers = [];
  let ownerUser;
  let secondOwnerUser;
  let outsiderUser;
  let reviewerUser;
  let readOnlyUser;
  let inviteeUser;
  let owner;
  let secondOwner;
  let outsider;
  let reviewer;
  let readOnly;
  let invitee;
  let companyId;
  let foreignCompanyId;
  let primaryError;
  const cleanupErrors = [];

  try {
    ownerUser = await createConfirmedUser("owner");
    createdUsers.push(ownerUser);
    secondOwnerUser = await createConfirmedUser("second-owner");
    createdUsers.push(secondOwnerUser);
    outsiderUser = await createConfirmedUser("outsider");
    createdUsers.push(outsiderUser);
    reviewerUser = await createConfirmedUser("reviewer");
    createdUsers.push(reviewerUser);
    readOnlyUser = await createConfirmedUser("readonly");
    createdUsers.push(readOnlyUser);
    inviteeUser = await createConfirmedUser("invitee");
    createdUsers.push(inviteeUser);
    owner = await signIn(ownerUser);
    secondOwner = await signIn(secondOwnerUser);
    outsider = await signIn(outsiderUser);
    reviewer = await signIn(reviewerUser);
    readOnly = await signIn(readOnlyUser);
    invitee = await signIn(inviteeUser);

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

    const { error: membershipError } = await admin.from("company_memberships").insert({
      company_id: companyId,
      user_id: ownerUser.id,
      role: "owner",
      accepted_at: new Date().toISOString(),
    });
    assert.ifError(membershipError);

    const { error: secondOwnerMembershipError } = await admin.from("company_memberships").insert({
      company_id: companyId,
      user_id: secondOwnerUser.id,
      role: "owner",
      invited_by: ownerUser.id,
      accepted_at: new Date().toISOString(),
    });
    assert.ifError(secondOwnerMembershipError);

    const { error: reviewerInviteError } = await admin.from("company_memberships").insert({
      company_id: companyId,
      user_id: reviewerUser.id,
      role: "reviewer",
      invited_by: ownerUser.id,
      accepted_at: new Date().toISOString(),
    });
    assert.ifError(reviewerInviteError);
    const { error: readOnlyInviteError } = await admin.from("company_memberships").insert({
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
        [secondOwnerUser.id, "owner"],
      ].sort((a, b) => String(a[0]).localeCompare(String(b[0]))),
    );

    foreignCompanyId = randomUUID();
    await assertNoError(admin.from("companies").insert({
      id: foreignCompanyId,
      org_number: `${Math.floor(100000000 + Math.random() * 899999999)}`,
      name: "Foreign Operator-visible Holding AS",
      entity_type: "AS",
      address: "Storgata 2",
      postal_code: "0155",
      city: "OSLO",
      status_text: "aktiv",
      source: "test",
      created_by: outsiderUser.id,
      identity_confirmed_at: new Date().toISOString(),
      identity_locked_at: new Date().toISOString(),
    }));
    await assertNoError(admin.from("company_memberships").insert({
      company_id: foreignCompanyId,
      user_id: outsiderUser.id,
      role: "owner",
      accepted_at: new Date().toISOString(),
    }));
    await assertNoError(admin.from("company_memberships").insert({
      company_id: companyId,
      user_id: inviteeUser.id,
      role: "reviewer",
      invited_by: ownerUser.id,
      accepted_at: null,
    }));
    await assertNoError(admin.from("support_operators").insert({
      user_id: ownerUser.id,
      role: "admin",
      active: true,
    }));

    for (const [client, userId] of [
      [owner, ownerUser.id],
      [reviewer, reviewerUser.id],
      [readOnly, readOnlyUser.id],
    ]) {
      const scoped = await listRlsVisibleCompanies(client, userId);
      assert.ifError(scoped.error);
      assert.deepEqual(scoped.companies.map(({ id }) => id), [companyId]);
    }
    const pending = await listRlsVisibleCompanies(invitee, inviteeUser.id);
    assert.ifError(pending.error);
    assert.deepEqual(pending.companies, []);

    await assertNoError(admin.from("support_operators").delete().eq("user_id", ownerUser.id));
    await assertNoError(
      admin.from("company_memberships").delete().eq("company_id", companyId).eq("user_id", inviteeUser.id),
    );
    await assertNoError(admin.from("companies").delete().eq("id", foreignCompanyId));
    foreignCompanyId = undefined;

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

    const invitationToken = randomUUID();
    const invitationHash = await invitationTokenHash(invitationToken);
    const invitationEvent = invitationDeliveryEvent({
      recipientEmail: inviteeUser.email,
      queuedAt: new Date().toISOString(),
    });
    const { error: directInvitationError } = await owner
      .from("company_invitations")
      .insert({
        company_id: companyId,
        invited_email: inviteeUser.email,
        role: "reviewer",
        token_hash: invitationHash,
        status: "pending",
        expires_at: invitationExpiry(),
        invited_by: ownerUser.id,
        delivery_events: [invitationEvent],
      });
    assert.ok(directInvitationError);

    const { data: invitation, error: invitationError } = await admin
      .from("company_invitations")
      .insert({
        company_id: companyId,
        invited_email: inviteeUser.email,
        role: "reviewer",
        token_hash: invitationHash,
        status: "pending",
        expires_at: invitationExpiry(),
        invited_by: ownerUser.id,
        delivery_events: [invitationEvent],
      })
      .select("id, company_id, invited_email, role, status, expires_at")
      .single();
    assert.ifError(invitationError);
    assert.equal(invitation.invited_email, inviteeUser.email);

    const { error: outboxError } = await owner.from("notification_outbox").insert({
      company_id: companyId,
      recipient_email: inviteeUser.email,
      template: "workspace_invitation",
      payload: { invitationId: invitation.id },
      status: "queued",
      created_by: ownerUser.id,
    });
    assert.ifError(outboxError);

    const { data: inviteeInvitations, error: inviteeInvitationReadError } = await invitee
      .from("company_invitations")
      .select("id, role, status")
      .eq("id", invitation.id);
    assert.ifError(inviteeInvitationReadError);
    assert.deepEqual(inviteeInvitations, []);

    const { data: lookedUpInvitations, error: invitationLookupError } = await invitee.rpc(
      "company_access_lookup_invitation",
      {
        p_token_hash: invitationHash,
        p_verified_subject: inviteeUser.id,
        p_verified_email: inviteeUser.email,
      },
    );
    assert.ifError(invitationLookupError);
    assert.deepEqual(
      lookedUpInvitations.map(({ id, role, status }) => ({ id, role, status })),
      [{ id: invitation.id, role: "reviewer", status: "pending" }],
    );

    const { error: acceptedInvitationError } = await invitee.rpc(
      "company_access_accept_invitation",
      {
        p_operation_id: randomUUID(),
        p_token_hash: invitationHash,
        p_verified_subject: inviteeUser.id,
        p_verified_email: inviteeUser.email,
      },
    );
    assert.ifError(acceptedInvitationError);

    const { data: acceptedInvitation, error: acceptedInvitationReadError } = await owner
      .from("company_invitations")
      .select("status, accepted_by")
      .eq("id", invitation.id)
      .single();
    assert.ifError(acceptedInvitationReadError);
    assert.deepEqual(acceptedInvitation, { status: "accepted", accepted_by: inviteeUser.id });

    const revokeTokenHash = await invitationTokenHash(randomUUID());
    const { data: revokedCandidate, error: revokedCandidateError } = await admin
      .from("company_invitations")
      .insert({
        company_id: companyId,
        invited_email: `revoke-${inviteeUser.email}`,
        role: "read_only",
        token_hash: revokeTokenHash,
        status: "pending",
        expires_at: invitationExpiry(),
        invited_by: ownerUser.id,
        delivery_events: [invitationDeliveryEvent({ recipientEmail: `revoke-${inviteeUser.email}` })],
      })
      .select("id")
      .single();
    assert.ifError(revokedCandidateError);
    const revokedAt = new Date().toISOString();
    const { error: revokeError } = await admin
      .from("company_invitations")
      .update({ status: "revoked", revoked_by: ownerUser.id, revoked_at: revokedAt })
      .eq("id", revokedCandidate.id);
    assert.ifError(revokeError);

    const { data: ownerOutboxRows, error: ownerOutboxReadError } = await owner
      .from("notification_outbox")
      .select("recipient_email, template, status")
      .eq("company_id", companyId);
    assert.ifError(ownerOutboxReadError);
    assert.deepEqual(ownerOutboxRows, [
      { recipient_email: inviteeUser.email, template: "workspace_invitation", status: "queued" },
    ]);

    const { data: inviteeOutboxRows, error: inviteeOutboxReadError } = await invitee
      .from("notification_outbox")
      .select("id")
      .eq("company_id", companyId);
    assert.ifError(inviteeOutboxReadError);
    assert.deepEqual(inviteeOutboxRows, []);

    const { error: ownerStepUpWriteError } = await owner.from("step_up_events").insert({
      actor_id: ownerUser.id,
      method: "totp",
      mfa_verified_at: new Date().toISOString(),
      security_review_approved: true,
      production_credentials_enabled: true,
    });
    assert.ok(ownerStepUpWriteError);

    const { error: ownerStepUpReadError } = await owner
      .from("step_up_events")
      .select("id")
      .eq("actor_id", ownerUser.id);
    assert.ok(ownerStepUpReadError);

    const { error: outsiderStepUpWriteError } = await outsider.from("step_up_events").insert({
      actor_id: ownerUser.id,
      method: "totp",
      mfa_verified_at: new Date().toISOString(),
    });
    assert.ok(outsiderStepUpWriteError);

    const { error: outsiderStepUpReadError } = await outsider
      .from("step_up_events")
      .select("id")
      .eq("actor_id", ownerUser.id);
    assert.ok(outsiderStepUpReadError);

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
        lines: [
          { account: "1920", description: "Bankinnskudd", debit: openingInput.bankBalance, credit: 0 },
          { account: "2000", description: "Aksjekapital", debit: 0, credit: openingInput.shareCapital },
          { account: "2050", description: "Annen egenkapital", debit: 0, credit: 0 },
        ],
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

    const companyTaxPersistence = companyTaxTt02Persistence({
      companyId,
      orgNumber,
      ownerId: ownerUser.id,
    });
    const { data: authorityPermissionsBeforeImport, error: authorityPermissionsBeforeImportError } = await admin
      .from("authority_permissions")
      .select("id, company_id, obligation, submitter_user_id, confirmed_by, confirmed_at, production_enabled, updated_at")
      .eq("company_id", companyId)
      .order("obligation");
    assert.ifError(authorityPermissionsBeforeImportError);
    const { data: launchSignoffsBeforeImport, error: launchSignoffsBeforeImportError } = await admin
      .from("launch_signoffs")
      .select("key, status, reviewer, reviewed_at, evidence_link, decision, recorded_by, updated_at")
      .order("key");
    assert.ifError(launchSignoffsBeforeImportError);

    const { error: noMfaImportError } = await owner.rpc("import_company_tax_tt02_evidence", {
      p_payload: companyTaxPersistence,
    });
    assert.match(noMfaImportError?.message ?? "", /company_tax_evidence_mfa_required/u);

    await elevateToAal2(owner);
    for (const [label, evidenceUrl] of [
      ["missing host", "https:///missing-host"],
      ["non-canonical host-only URL", "https://evidence.example"],
      ["credentials", "https://user:password@evidence.example/company-tax.json"],
      ["port", "https://evidence.example:443/company-tax.json"],
      ["query", "https://evidence.example/company-tax.json?token=secret"],
      ["fragment", "https://evidence.example/company-tax.json#secret"],
      ["unsupported scheme", "http://evidence.example/company-tax.json"],
      ["path traversal", "https://evidence.example/archive/../company-tax.json"],
      ["encoded path traversal", "https://evidence.example/archive/%2e%2e/company-tax.json"],
      ["control character", "https://evidence.example/company-tax.json\nignored"],
    ]) {
      const invalidUrlPayload = structuredClone(companyTaxPersistence);
      invalidUrlPayload.authorityRun.evidence_url = evidenceUrl;
      const { error: invalidUrlError } = await owner.rpc(
        "import_company_tax_tt02_evidence",
        { p_payload: invalidUrlPayload },
      );
      assert.match(
        invalidUrlError?.message ?? "",
        /company_tax_evidence_invalid_payload/u,
        `${label} must fail at the direct RPC boundary`,
      );
    }
    const { data: importedCompanyTax, error: companyTaxImportError } = await owner.rpc(
      "import_company_tax_tt02_evidence",
      { p_payload: companyTaxPersistence },
    );
    assert.ifError(companyTaxImportError);
    assert.equal(importedCompanyTax.created, true);
    assert.match(importedCompanyTax.authority_test_run_id, /^[0-9a-f-]{36}$/u);
    assert.match(importedCompanyTax.filing_submission_id, /^[0-9a-f-]{36}$/u);

    const { data: importedAuthorityRuns, error: importedAuthorityRunsError } = await owner
      .from("authority_test_runs")
      .select("id, company_id, obligation, environment, status, test_reference, payload_hash")
      .eq("company_id", companyId)
      .eq("obligation", "skattemelding")
      .eq("test_reference", companyTaxPersistence.authorityRun.test_reference);
    assert.ifError(importedAuthorityRunsError);
    assert.deepEqual(importedAuthorityRuns, [{
      id: importedCompanyTax.authority_test_run_id,
      company_id: companyId,
      obligation: "skattemelding",
      environment: "test",
      status: "pending",
      test_reference: companyTaxPersistence.authorityRun.test_reference,
      payload_hash: companyTaxPersistence.authorityRun.payload_hash,
    }]);
    const { data: importedSubmissions, error: importedSubmissionsError } = await owner
      .from("filing_submissions")
      .select("id, authority_test_run_id, company_id, income_year, filing, mode, adapter_mode, status, receipt_id, submitted_payload")
      .eq("authority_test_run_id", importedCompanyTax.authority_test_run_id);
    assert.ifError(importedSubmissionsError);
    assert.deepEqual(importedSubmissions, [{
      id: importedCompanyTax.filing_submission_id,
      authority_test_run_id: importedCompanyTax.authority_test_run_id,
      company_id: companyId,
      income_year: 2025,
      filing: "skattemelding for AS",
      mode: "test_authority",
      adapter_mode: "test_authority",
      status: "feedback_ready",
      receipt_id: companyTaxPersistence.submission.receipt_id,
      submitted_payload: null,
    }]);

    const { data: companyTaxAuditBeforeRetry, error: companyTaxAuditBeforeRetryError } = await owner
      .from("audit_events")
      .select("id, actor_id")
      .eq("company_id", companyId)
      .eq("action", "company_tax_tt02_evidence_imported");
    assert.ifError(companyTaxAuditBeforeRetryError);
    assert.equal(companyTaxAuditBeforeRetry.length, 1);
    assert.equal(companyTaxAuditBeforeRetry[0].actor_id, ownerUser.id);
    const { data: retriedCompanyTax, error: companyTaxRetryError } = await owner.rpc(
      "import_company_tax_tt02_evidence",
      { p_payload: structuredClone(companyTaxPersistence) },
    );
    assert.ifError(companyTaxRetryError);
    assert.deepEqual(retriedCompanyTax, {
      authority_test_run_id: importedCompanyTax.authority_test_run_id,
      filing_submission_id: importedCompanyTax.filing_submission_id,
      created: false,
    });
    await elevateToAal2(secondOwner);
    const secondOwnerRetryPayload = structuredClone(companyTaxPersistence);
    secondOwnerRetryPayload.authorityRun.recorded_by = secondOwnerUser.id;
    secondOwnerRetryPayload.submission.created_by = secondOwnerUser.id;
    const { data: secondOwnerRetry, error: secondOwnerRetryError } = await secondOwner.rpc(
      "import_company_tax_tt02_evidence",
      { p_payload: secondOwnerRetryPayload },
    );
    assert.ifError(secondOwnerRetryError);
    assert.deepEqual(secondOwnerRetry, {
      authority_test_run_id: importedCompanyTax.authority_test_run_id,
      filing_submission_id: importedCompanyTax.filing_submission_id,
      created: false,
    });
    const { data: originalEvidenceActors, error: originalEvidenceActorsError } = await admin
      .from("authority_test_runs")
      .select("recorded_by")
      .eq("id", importedCompanyTax.authority_test_run_id)
      .single();
    assert.ifError(originalEvidenceActorsError);
    assert.equal(originalEvidenceActors.recorded_by, ownerUser.id);
    const { data: originalSubmissionActors, error: originalSubmissionActorsError } = await admin
      .from("filing_submissions")
      .select("created_by")
      .eq("id", importedCompanyTax.filing_submission_id)
      .single();
    assert.ifError(originalSubmissionActorsError);
    assert.equal(originalSubmissionActors.created_by, ownerUser.id);
    const { data: companyTaxAuditAfterRetry, error: companyTaxAuditAfterRetryError } = await owner
      .from("audit_events")
      .select("id, actor_id")
      .eq("company_id", companyId)
      .eq("action", "company_tax_tt02_evidence_imported");
    assert.ifError(companyTaxAuditAfterRetryError);
    assert.deepEqual(companyTaxAuditAfterRetry, companyTaxAuditBeforeRetry);

    const legacyDuplicateReference = `legacy-duplicate-${randomUUID()}`;
    const { error: legacyDuplicateError } = await owner.from("authority_test_runs").insert([
      {
        ...companyTaxPersistence.authorityRun,
        environment: "manual_evidence",
        status: "accepted",
        test_reference: legacyDuplicateReference,
      },
      {
        ...companyTaxPersistence.authorityRun,
        environment: "manual_evidence",
        status: "accepted",
        test_reference: legacyDuplicateReference,
      },
    ]);
    assert.ifError(legacyDuplicateError);
    const { error: duplicateCompanyTaxIdentityError } = await owner
      .from("authority_test_runs")
      .insert(structuredClone(companyTaxPersistence.authorityRun));
    assert.ok(duplicateCompanyTaxIdentityError);

    const conflictingCompanyTax = structuredClone(companyTaxPersistence);
    const conflictingReceiptId = randomUUID();
    conflictingCompanyTax.authorityRun.receipt_reference = `${conflictingCompanyTax.authorityRun.archive_reference}/data/${conflictingReceiptId}`;
    conflictingCompanyTax.submission.receipt_id = conflictingReceiptId;
    conflictingCompanyTax.submission.feedback_document_ids = [conflictingReceiptId];
    conflictingCompanyTax.submission.feedback_items[0].documentId = conflictingReceiptId;
    conflictingCompanyTax.submission.receipt_metadata.receiptId = conflictingReceiptId;
    conflictingCompanyTax.submission.receipt_metadata.feedbackDocumentIds = [conflictingReceiptId];
    conflictingCompanyTax.submission.receipt_metadata.reference = conflictingCompanyTax.authorityRun.receipt_reference;
    const { error: conflictingCompanyTaxError } = await owner.rpc(
      "import_company_tax_tt02_evidence",
      { p_payload: conflictingCompanyTax },
    );
    assert.match(conflictingCompanyTaxError?.message ?? "", /company_tax_evidence_conflict/u);

    const rawNestedCompanyTax = structuredClone(companyTaxPersistence);
    rawNestedCompanyTax.submission.receipt_metadata.rawXml = "<skattemelding>forbidden</skattemelding>";
    const { error: rawNestedCompanyTaxError } = await owner.rpc(
      "import_company_tax_tt02_evidence",
      { p_payload: rawNestedCompanyTax },
    );
    assert.match(rawNestedCompanyTaxError?.message ?? "", /company_tax_evidence_forbidden_content/u);

    const missingCanonicalKeys = [
      ["receipt metadata", (payload) => delete payload.submission.receipt_metadata.contentSha256],
      ["payload reference", (payload) => delete payload.submission.submitted_payload_ref.validationEnvelopeHash],
      ["feedback item", (payload) => delete payload.submission.feedback_items[0].severity],
      ["validation call", (payload) => delete payload.submission.calls[0].status],
      ["confirmation call", (payload) => delete payload.submission.calls[1].status],
      ["receipt call", (payload) => delete payload.submission.calls[2].status],
    ];
    for (const [label, removeKey] of missingCanonicalKeys) {
      const missingKeyPayload = structuredClone(companyTaxPersistence);
      removeKey(missingKeyPayload);
      const { error: missingKeyError } = await owner.rpc("import_company_tax_tt02_evidence", {
        p_payload: missingKeyPayload,
      });
      assert.match(
        missingKeyError?.message ?? "",
        /company_tax_evidence_invalid_payload/u,
        `${label} key removal must fail closed`,
      );
    }

    const identityAndDigestAttacks = [
      ["organization number", (payload) => {
        payload.submission.submitted_payload_ref.companyOrgNumber = "999999999";
      }],
      ["income year", (payload) => {
        payload.submission.submitted_payload_ref.incomeYear = 2024;
      }],
      ["self-consistent non-2025 income year", (payload) => {
        payload.submission.income_year = 2024;
        payload.submission.submitted_payload_ref.incomeYear = 2024;
        payload.submission.idempotency_key = payload.submission.idempotency_key.replace(
          ":2025:",
          ":2024:",
        );
      }],
      ["component digest", (payload) => {
        payload.submission.submitted_payload_ref.validationEnvelopeHash = "0".repeat(64);
        payload.submission.calls[0].body_hash = "0".repeat(64);
      }],
      ["receipt UUID", (payload) => {
        payload.submission.receipt_id = "not-a-uuid";
      }],
      ["uppercase semantic UUID duplicate", (payload) => {
        const instanceUuid = payload.authorityRun.test_reference.split("/").at(-1);
        const uppercaseInstanceUuid = instanceUuid.toUpperCase();
        const uppercaseReceiptId = payload.submission.receipt_id.toUpperCase();
        const envelopeDataId = payload.submission.submitted_payload_ref.envelopeDataId;
        const uppercaseArchiveReference = payload.authorityRun.archive_reference.replace(
          instanceUuid,
          uppercaseInstanceUuid,
        );
        const uppercaseReceiptReference =
          `${uppercaseArchiveReference}/data/${uppercaseReceiptId}`;
        payload.authorityRun.test_reference = payload.authorityRun.test_reference.replace(
          instanceUuid,
          uppercaseInstanceUuid,
        );
        payload.authorityRun.archive_reference = uppercaseArchiveReference;
        payload.authorityRun.receipt_reference = uppercaseReceiptReference;
        payload.submission.receipt_id = uppercaseReceiptId;
        payload.submission.feedback_document_ids = [uppercaseReceiptId];
        payload.submission.feedback_items[0].documentId = uppercaseReceiptId;
        payload.submission.receipt_metadata.receiptId = uppercaseReceiptId;
        payload.submission.receipt_metadata.feedbackDocumentIds = [uppercaseReceiptId];
        payload.submission.receipt_metadata.reference = uppercaseReceiptReference;
        payload.submission.receipt_metadata.archiveReference = uppercaseArchiveReference;
        payload.submission.submitted_payload_ref.envelopeDataId = envelopeDataId.toUpperCase();
        payload.submission.submitted_payload_ref.archiveReference = uppercaseArchiveReference;
      }],
    ];
    for (const [label, mutate] of identityAndDigestAttacks) {
      const attackedPayload = structuredClone(companyTaxPersistence);
      mutate(attackedPayload);
      const { error: attackedPayloadError } = await owner.rpc("import_company_tax_tt02_evidence", {
        p_payload: attackedPayload,
      });
      assert.match(
        attackedPayloadError?.message ?? "",
        /company_tax_evidence_invalid_payload/u,
        `${label} tampering must fail closed`,
      );
    }
    const { data: canonicalRetryRows, error: canonicalRetryRowsError } = await owner
      .from("filing_submissions")
      .select("id, idempotency_key")
      .eq("mode", "test_authority")
      .eq("idempotency_key", companyTaxPersistence.submission.idempotency_key);
    assert.ifError(canonicalRetryRowsError);
    assert.deepEqual(canonicalRetryRows, [{
      id: importedCompanyTax.filing_submission_id,
      idempotency_key: companyTaxPersistence.submission.idempotency_key,
    }]);

    for (const [label, mutate] of [
      ["PostgreSQL infinity timestamp", (payload) => {
        payload.submission.calls[0].created_at = "infinity";
      }],
      ["non-RFC3339 timestamp", (payload) => {
        payload.submission.calls[1].created_at = "2026-07-14 12:21:00+00";
      }],
      ["confirmation after process end", (payload) => {
        payload.submission.calls[1].created_at = "2026-07-14T12:30:30.000Z";
      }],
      ["out-of-range RFC3339 components", (payload) => {
        const invalidTimestamp = "2026-07-14T24:00:00Z";
        payload.authorityRun.recorded_at = invalidTimestamp;
        payload.submission.updated_at = invalidTimestamp;
        for (const call of payload.submission.calls) {
          call.created_at = invalidTimestamp;
        }
        payload.submission.receipt_metadata.receivedAt = invalidTimestamp;
        payload.submission.receipt_metadata.processEndedAt = invalidTimestamp;
        payload.submission.receipt_metadata.archivedAt = invalidTimestamp;
        payload.submission.submitted_payload_ref.storedAt = invalidTimestamp;
      }],
      ["sub-microsecond reversed chronology", (payload) => {
        payload.submission.calls[0].created_at = "2026-07-14T12:20:00.0000002Z";
        payload.submission.calls[1].created_at = "2026-07-14T12:20:00.0000001Z";
      }],
    ]) {
      const timestampAttack = structuredClone(companyTaxPersistence);
      mutate(timestampAttack);
      const { error: timestampAttackError } = await owner.rpc(
        "import_company_tax_tt02_evidence",
        { p_payload: timestampAttack },
      );
      assert.match(
        timestampAttackError?.message ?? "",
        /company_tax_evidence_invalid_payload/u,
        `${label} must fail closed`,
      );
    }

    for (const forbiddenContent of [
      "<skattemelding>RAW_XML_SENTINEL</skattemelding>",
      "ACCESS_TOKEN_SENTINEL",
      "PRIVATE_KEY_SENTINEL",
      "PERSONAL_IDENTIFIER_SENTINEL",
    ]) {
      const forbiddenPayload = structuredClone(companyTaxPersistence);
      forbiddenPayload.submission.feedback_items[0].message = forbiddenContent;
      const { error: forbiddenPayloadError } = await owner.rpc("import_company_tax_tt02_evidence", {
        p_payload: forbiddenPayload,
      });
      assert.match(
        forbiddenPayloadError?.message ?? "",
        /company_tax_evidence_forbidden_content/u,
      );
    }
    const currentReferenceSentinelPayload = structuredClone(companyTaxPersistence);
    currentReferenceSentinelPayload.authorityRun.evidence_url =
      "https://evidence.example/CuRrEnT_DoCuMeNt_ReFeReNcE_SeNtInEl.json";
    const { error: currentReferenceSentinelError } = await owner.rpc(
      "import_company_tax_tt02_evidence",
      { p_payload: currentReferenceSentinelPayload },
    );
    assert.match(
      currentReferenceSentinelError?.message ?? "",
      /company_tax_evidence_forbidden_content/u,
    );

    const directAuthority = {
      ...companyTaxPersistence.authorityRun,
      test_reference: `tt02:51549454/${randomUUID()}`,
    };
    const { data: directAuthorityRow, error: directAuthorityError } = await owner
      .from("authority_test_runs")
      .insert(directAuthority)
      .select("id")
      .single();
    assert.ifError(directAuthorityError);
    const { error: directTestAuthoritySubmissionError } = await owner
      .from("filing_submissions")
      .insert({
        ...companyTaxPersistence.submission,
        authority_test_run_id: directAuthorityRow.id,
      });
    assert.ok(directTestAuthoritySubmissionError);

    const { data: directSimulationSubmission, error: directSimulationSubmissionError } = await owner
      .from("filing_submissions")
      .insert({
        preview_id: filingPreview.id,
        company_id: companyId,
        setup_id: setup.id,
        income_year: 2025,
        filing: filingPreview.filing,
        mode: "simulation",
        adapter_mode: "simulation",
        status: "ready",
        created_by: ownerUser.id,
      })
      .select("id")
      .single();
    assert.ifError(directSimulationSubmissionError);
    const { error: simulationToTestAuthorityError } = await owner
      .from("filing_submissions")
      .update({
        mode: "test_authority",
        adapter_mode: "test_authority",
        preview_id: null,
        authority_test_run_id: directAuthorityRow.id,
      })
      .eq("id", directSimulationSubmission.id);
    assert.ok(simulationToTestAuthorityError);
    const { data: unchangedSimulationSubmission, error: unchangedSimulationSubmissionError } = await owner
      .from("filing_submissions")
      .select("mode, adapter_mode, preview_id, authority_test_run_id")
      .eq("id", directSimulationSubmission.id)
      .single();
    assert.ifError(unchangedSimulationSubmissionError);
    assert.deepEqual(unchangedSimulationSubmission, {
      mode: "simulation",
      adapter_mode: "simulation",
      preview_id: filingPreview.id,
      authority_test_run_id: null,
    });

    const { data: directTestAuthorityUpdates, error: directTestAuthorityUpdateError } = await owner
      .from("filing_submissions")
      .update({
        mode: "simulation",
        adapter_mode: "simulation",
        preview_id: filingPreview.id,
        authority_test_run_id: null,
      })
      .eq("id", importedCompanyTax.filing_submission_id)
      .select("id");
    assert.ifError(directTestAuthorityUpdateError);
    assert.deepEqual(directTestAuthorityUpdates, []);
    const { data: unchangedTestAuthoritySubmission, error: unchangedTestAuthoritySubmissionError } = await owner
      .from("filing_submissions")
      .select("mode, adapter_mode, preview_id, authority_test_run_id")
      .eq("id", importedCompanyTax.filing_submission_id)
      .single();
    assert.ifError(unchangedTestAuthoritySubmissionError);
    assert.deepEqual(unchangedTestAuthoritySubmission, {
      mode: "test_authority",
      adapter_mode: "test_authority",
      preview_id: null,
      authority_test_run_id: importedCompanyTax.authority_test_run_id,
    });

    await elevateToAal2(reviewer);
    const { error: reviewerCompanyTaxError } = await reviewer.rpc(
      "import_company_tax_tt02_evidence",
      { p_payload: companyTaxPersistence },
    );
    assert.match(reviewerCompanyTaxError?.message ?? "", /company_tax_evidence_owner_required/u);
    await elevateToAal2(outsider);
    const { error: outsiderCompanyTaxError } = await outsider.rpc(
      "import_company_tax_tt02_evidence",
      { p_payload: companyTaxPersistence },
    );
    assert.match(outsiderCompanyTaxError?.message ?? "", /company_tax_evidence_owner_required/u);

    const { data: reviewerCompanyTaxRuns, error: reviewerCompanyTaxRunsError } = await reviewer
      .from("authority_test_runs")
      .select("id")
      .eq("id", importedCompanyTax.authority_test_run_id);
    assert.ifError(reviewerCompanyTaxRunsError);
    assert.deepEqual(reviewerCompanyTaxRuns, [{ id: importedCompanyTax.authority_test_run_id }]);
    const { data: reviewerCompanyTaxSubmissions, error: reviewerCompanyTaxSubmissionsError } = await reviewer
      .from("filing_submissions")
      .select("id, authority_test_run_id")
      .eq("id", importedCompanyTax.filing_submission_id);
    assert.ifError(reviewerCompanyTaxSubmissionsError);
    assert.deepEqual(reviewerCompanyTaxSubmissions, [{
      id: importedCompanyTax.filing_submission_id,
      authority_test_run_id: importedCompanyTax.authority_test_run_id,
    }]);

    const { data: authorityPermissionsAfterImport, error: authorityPermissionsAfterImportError } = await admin
      .from("authority_permissions")
      .select("id, company_id, obligation, submitter_user_id, confirmed_by, confirmed_at, production_enabled, updated_at")
      .eq("company_id", companyId)
      .order("obligation");
    assert.ifError(authorityPermissionsAfterImportError);
    assert.deepEqual(authorityPermissionsAfterImport, authorityPermissionsBeforeImport);
    const { data: launchSignoffsAfterImport, error: launchSignoffsAfterImportError } = await admin
      .from("launch_signoffs")
      .select("key, status, reviewer, reviewed_at, evidence_link, decision, recorded_by, updated_at")
      .order("key");
    assert.ifError(launchSignoffsAfterImportError);
    assert.deepEqual(launchSignoffsAfterImport, launchSignoffsBeforeImport);

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

    const parsedBank = [
      {
        transactionDate: "2025-01-02",
        text: "Opening",
        amount: 30000,
        balance: 30000,
        sourceHash: "1b22d1e46d2e15f7b51c68f74d280e669fea9bc692e862a3a5eaed1ec6b80778",
      },
      {
        transactionDate: "2025-01-03",
        text: "Bank fee",
        amount: -50,
        balance: 29950,
        sourceHash: "ab40e8421185f6eba0502af6427d3e38c3d76ad0849ce23ce4055ebb9732577f",
      },
    ];
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
    assert.equal(Number(feeTransaction.amount), -50);
    const adminCostLines = [
      { account: "7770", description: "Admin cost: Bank", debit: 50, credit: 0 },
      { account: "1920", description: "Paid from bank", debit: 0, credit: 50 },
    ];
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

    const { data: suggestedBankTransaction, error: suggestedBankTransactionError } = await owner
      .from("bank_transactions")
      .insert({
        company_id: companyId,
        income_year: 2025,
        transaction_date: "2025-02-01",
        text: "Årsgebyr bedriftskonto",
        amount: -50,
        source_hash: bankSourceHash(`bank-suggestion-${randomUUID()}`),
        created_by: ownerUser.id,
      })
      .select("id")
      .single();
    assert.ifError(suggestedBankTransactionError);

    const outsiderSuggestionResult = await outsider.rpc("accept_bank_transaction_suggestion", {
      p_bank_transaction_id: suggestedBankTransaction.id,
      p_rule_id: "bank_fee",
      p_rule_version: "2026-07-13.1",
    });
    assert.ok(outsiderSuggestionResult.error);
    const reviewerSuggestionResult = await reviewer.rpc("accept_bank_transaction_suggestion", {
      p_bank_transaction_id: suggestedBankTransaction.id,
      p_rule_id: "bank_fee",
      p_rule_version: "2026-07-13.1",
    });
    assert.ok(reviewerSuggestionResult.error);

    const { data: acceptedSuggestion, error: acceptedSuggestionError } = await owner.rpc(
      "accept_bank_transaction_suggestion",
      {
        p_bank_transaction_id: suggestedBankTransaction.id,
        p_rule_id: "bank_fee",
        p_rule_version: "2026-07-13.1",
      },
    );
    assert.ifError(acceptedSuggestionError);
    assert.equal(acceptedSuggestion.rule_id, "bank_fee");
    assert.equal(acceptedSuggestion.idempotent, false);
    const { data: repeatedSuggestion, error: repeatedSuggestionError } = await owner.rpc(
      "accept_bank_transaction_suggestion",
      {
        p_bank_transaction_id: suggestedBankTransaction.id,
        p_rule_id: "bank_fee",
        p_rule_version: "2026-07-13.1",
      },
    );
    assert.ifError(repeatedSuggestionError);
    assert.equal(repeatedSuggestion.idempotent, true);

    const { data: suggestionAcceptances, error: suggestionAcceptanceError } = await owner
      .from("bank_suggestion_acceptances")
      .select("id, bank_transaction_id, ledger_entry_id, rule_id, rule_version, lines, accepted_by")
      .eq("bank_transaction_id", suggestedBankTransaction.id);
    assert.ifError(suggestionAcceptanceError);
    assert.equal(suggestionAcceptances.length, 1);
    assert.equal(suggestionAcceptances[0].accepted_by, ownerUser.id);
    assert.deepEqual(suggestionAcceptances[0].lines, [
      { account: "7770", credit: 0, debit: 50, description: "Bankomkostninger" },
      { account: "1920", credit: 50, debit: 0, description: "Bank" },
    ]);
    const directSuggestionAcceptance = await owner.from("bank_suggestion_acceptances").insert({
      company_id: companyId,
      bank_transaction_id: suggestedBankTransaction.id,
      ledger_entry_id: suggestionAcceptances[0].ledger_entry_id,
      rule_id: "bank_fee",
      rule_version: "forged",
      reason: "forged",
      lines: [],
      accepted_by: ownerUser.id,
    });
    assert.ok(directSuggestionAcceptance.error);
    const { data: outsiderSuggestionAcceptances, error: outsiderSuggestionAcceptanceError } = await outsider
      .from("bank_suggestion_acceptances")
      .select("id")
      .eq("company_id", companyId);
    assert.ifError(outsiderSuggestionAcceptanceError);
    assert.deepEqual(outsiderSuggestionAcceptances, []);

    const { data: ambiguousBankTransaction, error: ambiguousBankTransactionError } = await owner
      .from("bank_transactions")
      .insert({
        company_id: companyId,
        income_year: 2025,
        transaction_date: "2025-02-02",
        text: "Bankgebyr og renter",
        amount: 100,
        source_hash: bankSourceHash(`bank-ambiguous-${randomUUID()}`),
        created_by: ownerUser.id,
      })
      .select("id")
      .single();
    assert.ifError(ambiguousBankTransactionError);
    const ambiguousSuggestionResult = await owner.rpc("accept_bank_transaction_suggestion", {
      p_bank_transaction_id: ambiguousBankTransaction.id,
      p_rule_id: "deposit_interest",
      p_rule_version: "2026-07-13.1",
    });
    assert.match(ambiguousSuggestionResult.error?.message ?? "", /bank_suggestion_ambiguous/);

    const purchaseDocumentId = randomUUID();
    await insertDocumentFixture({
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
    const { data: purchaseBankTransaction, error: purchaseBankTransactionError } = await owner
      .from("bank_transactions")
      .insert({
        company_id: companyId,
        income_year: 2025,
        transaction_date: "2025-05-01",
        text: "Purchase Portfolio AS",
        amount: -50000,
        balance: -19050,
        source_hash: bankSourceHash(`purchase-bank-${randomUUID()}`),
        created_by: ownerUser.id,
      })
      .select("id, amount")
      .single();
    assert.ifError(purchaseBankTransactionError);
    // This fixture exercises the still-frozen sale compatibility path. New
    // purchase policy is owned and tested by the backend investments capability.
    const purchasePayload = {
      acquisition_date: "2025-05-01",
      bank_transaction_id: purchaseBankTransaction.id,
      document_id: purchaseDocumentId,
      document_status: "attached",
      investment_key: "portfolio-as",
      investment_kind: "norwegian_private_company",
      investment_name: "Portfolio AS",
      org_number: "999888777",
      purchase_amount: 50000,
      share_count: 100,
      tax_treatment: "fritaksmetoden",
    };
    const purchaseActionId = randomUUID();
    const { data: purchaseWrite, error: purchaseWriteError } = await owner.rpc("record_share_purchase_fifo", {
      p_action_id: purchaseActionId,
      p_company_id: companyId,
      p_income_year: 2025,
      p_investment_key: purchasePayload.investment_key,
      p_investment_name: purchasePayload.investment_name,
      p_investment_kind: purchasePayload.investment_kind,
      p_tax_treatment: purchasePayload.tax_treatment,
      p_acquisition_date: purchasePayload.acquisition_date,
      p_share_count: purchasePayload.share_count,
      p_purchase_amount: purchasePayload.purchase_amount,
      p_org_number: purchasePayload.org_number,
      p_bank_transaction_id: purchaseBankTransaction.id,
      p_document_id: purchaseDocumentId,
      p_document_status: purchasePayload.document_status,
    });
    assert.ifError(purchaseWriteError);
    assert.equal(purchaseWrite.action_id, purchaseActionId);
    assert.equal(purchaseWrite.idempotent, false);
    const { data: purchasePosition, error: purchasePositionError } = await owner
      .from("investment_positions")
      .select("id, investment_key, share_count, cost_basis, lot_history_status")
      .eq("id", purchaseWrite.position_id)
      .single();
    assert.ifError(purchasePositionError);
    assert.equal(purchasePosition.investment_key, "portfolio-as");
    assert.equal(Number(purchasePosition.share_count), 100);
    assert.equal(Number(purchasePosition.cost_basis), 50000);
    assert.equal(purchasePosition.lot_history_status, "complete");
    const { data: purchaseLots, error: purchaseLotsError } = await owner
      .from("investment_lots")
      .select("id, acquisition_date, remaining_share_count, remaining_cost_basis")
      .eq("position_id", purchasePosition.id);
    assert.ifError(purchaseLotsError);
    assert.equal(purchaseLots.length, 1);
    assert.equal(Number(purchaseLots[0].remaining_share_count), 100);
    assert.equal(Number(purchaseLots[0].remaining_cost_basis), 50000);
    const { data: purchaseRetry, error: purchaseRetryError } = await owner.rpc("record_share_purchase_fifo", {
      p_action_id: purchaseActionId,
      p_company_id: companyId,
      p_income_year: 2025,
      p_investment_key: purchasePayload.investment_key,
      p_investment_name: purchasePayload.investment_name,
      p_investment_kind: purchasePayload.investment_kind,
      p_tax_treatment: purchasePayload.tax_treatment,
      p_acquisition_date: purchasePayload.acquisition_date,
      p_share_count: purchasePayload.share_count,
      p_purchase_amount: purchasePayload.purchase_amount,
      p_org_number: purchasePayload.org_number,
      p_bank_transaction_id: purchaseBankTransaction.id,
      p_document_id: purchaseDocumentId,
      p_document_status: purchasePayload.document_status,
    });
    assert.ifError(purchaseRetryError);
    assert.equal(purchaseRetry.idempotent, true);
    const { data: outsiderPositions, error: outsiderPositionError } = await outsider
      .from("investment_positions")
      .select("id")
      .eq("id", purchasePosition.id);
    assert.ifError(outsiderPositionError);
    assert.deepEqual(outsiderPositions, []);
    const { error: outsiderPurchaseActionInsertError } = await outsider.rpc("record_share_purchase_fifo", {
      p_action_id: randomUUID(),
      p_company_id: companyId,
      p_income_year: 2025,
      p_investment_key: "forbidden",
      p_investment_name: "Forbidden AS",
      p_investment_kind: "norwegian_private_company",
      p_tax_treatment: "fritaksmetoden",
      p_acquisition_date: "2025-05-01",
      p_share_count: 1,
      p_purchase_amount: 1,
      p_org_number: null,
      p_bank_transaction_id: null,
      p_document_id: null,
      p_document_status: "not_required",
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
    await insertDocumentFixture({
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
    const { data: loanBankTransaction, error: loanBankTransactionError } = await owner
      .from("bank_transactions")
      .insert({
        company_id: companyId,
        income_year: 2025,
        transaction_date: "2025-07-01",
        text: "Loan from shareholder",
        amount: 20000,
        balance: 30950,
        source_hash: bankSourceHash(`loan-bank-${randomUUID()}`),
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
      ledgerEntries: [
        { entry_type: "admin_cost", lines: adminCostEntry.lines },
        {
          entry_type: "interest_income",
          lines: [
            { account: "1920", description: "Bankrente", debit: 100, credit: 0 },
            { account: "8050", description: "Renteinntekt", debit: 0, credit: 100 },
          ],
        },
      ],
      holdingActions: [{
        action_type: "dividend_received",
        payload: { gross_amount: 1000, taxable_add_back: 30 },
      }],
    });
    assert.equal(taxEstimate.status, "payable");
    assert.equal(taxEstimate.estimatedTax, 17.6);
    const taxDocumentId = randomUUID();
    await insertDocumentFixture({
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
    const { data: taxBankTransaction, error: taxBankTransactionError } = await owner
      .from("bank_transactions")
      .insert({
        company_id: companyId,
        income_year: 2025,
        transaction_date: "2025-12-31",
        text: "Tax payment",
        amount: -17.6,
        balance: 30932.4,
        source_hash: bankSourceHash(`tax-bank-${randomUUID()}`),
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

    const manualJournal = {
      lines: [
        { account: "1800", description: "Manual investment correction", debit: 100, credit: 0 },
        { account: "1920", description: "Bank", debit: 0, credit: 100 },
      ],
      riskFlags: [{
        account: "1800",
        code: "manual_journal_sensitive_account",
        message: "Manuell journal berører filing-sensitiv konto 1800.",
      }],
    };
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
      source_hash: bankSourceHash(`locked-bank-${randomUUID()}`),
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
    const storageKey = `${companyId}/2025/${documentId}/bank.pdf`;
    const { error: uploadError } = await owner.storage
      .from("company-documents")
      .upload(storageKey, new Blob(["test"], { type: "application/pdf" }), {
        contentType: "application/pdf",
      });
    assert.ok(uploadError, "authenticated browsers cannot create document objects directly");

    await insertDocumentFixture({
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

    const { data: directOwnerDocuments, error: ownerDocumentError } = await owner
      .from("documents")
      .select("id, company_id, income_year, document_type, name, linked_to, status, retention_years, storage_key, created_by, created_at")
      .eq("company_id", companyId)
      .eq("income_year", 2025);
    assert.ok(ownerDocumentError);
    assert.equal(directOwnerDocuments, null);
    const ownerDocuments = await listDocumentFixtures(companyId, 2025);
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
    const { data: persistedBankSuggestionAcceptances, error: persistedBankSuggestionAcceptanceError } = await owner
      .from("bank_suggestion_acceptances")
      .select("id, company_id, bank_transaction_id, ledger_entry_id, rule_id, rule_version, reason, lines, accepted_by, accepted_at")
      .eq("company_id", companyId);
    assert.ifError(persistedBankSuggestionAcceptanceError);
    const archive = buildPersistedCompanyArchive({
      company: persistedCompany,
      incomeYear: 2025,
      setups: [setup],
      shareholders: persistedShareholders,
      ledgerEntries: persistedLedgerEntries,
      documents: ownerDocuments,
      holdingActions: persistedHoldingActions,
      bankSuggestionAcceptances: persistedBankSuggestionAcceptances,
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
    assert.ok(
      archive.authorityPermissions.some(
        (permission) => permission.obligation === "aksjonaerregisteroppgaven",
      ),
    );
    assert.equal(archive.bankSuggestionAcceptances[0].rule_id, "bank_fee");

    const { data: outsiderArchiveCompany, error: outsiderArchiveCompanyError } = await outsider
      .from("companies")
      .select("id")
      .eq("id", companyId);
    assert.ifError(outsiderArchiveCompanyError);
    assert.deepEqual(outsiderArchiveCompany, []);

    const { data: signed, error: signedError } = await owner.storage
      .from("company-documents")
      .createSignedUrl(storageKey, 60);
    assert.equal(signed, null);
    assert.ok(signedError);

    const { data: outsiderDocuments, error: outsiderDocumentError } = await outsider
      .from("documents")
      .select("id")
      .eq("id", documentId);
    assert.ok(outsiderDocumentError);
    assert.equal(outsiderDocuments, null);

    const { data: reviewerDocuments, error: reviewerDocumentError } = await reviewer
      .from("documents")
      .select("id")
      .eq("id", documentId);
    assert.ok(reviewerDocumentError);
    assert.equal(reviewerDocuments, null);

    const { data: readOnlyDocuments, error: readOnlyDocumentError } = await readOnly
      .from("documents")
      .select("id")
      .eq("id", documentId);
    assert.ok(readOnlyDocumentError);
    assert.equal(readOnlyDocuments, null);

    const linkedRemoval = await owner.rpc("remove_unlinked_document", {
      p_document_id: purchaseDocumentId,
    });
    assert.ok(linkedRemoval.error, "legacy browser removal RPC execution is revoked");

    const { data: outsiderSigned, error: outsiderSignedError } = await outsider.storage
      .from("company-documents")
      .createSignedUrl(storageKey, 60);
    assert.equal(outsiderSigned, null);
    assert.ok(outsiderSignedError);

    const reviewerStorageKey = `${companyId}/2025/${randomUUID()}/reviewer.pdf`;
    const { error: reviewerUploadError } = await reviewer.storage
      .from("company-documents")
      .upload(reviewerStorageKey, new Blob(["reviewer"], { type: "application/pdf" }), {
        contentType: "application/pdf",
      });
    assert.ok(reviewerUploadError);

    const readOnlyStorageKey = `${companyId}/2025/${randomUUID()}/readonly.pdf`;
    const { error: readOnlyUploadError } = await readOnly.storage
      .from("company-documents")
      .upload(readOnlyStorageKey, new Blob(["readonly"], { type: "application/pdf" }), {
        contentType: "application/pdf",
      });
    assert.ok(readOnlyUploadError);

  } catch (error) {
    primaryError = error;
  } finally {
    if (foreignCompanyId) {
      await collectCleanupError(
        () => deleteWorkspaceCompanyFixture(foreignCompanyId),
        cleanupErrors,
      );
    }
    if (companyId) {
      await collectCleanupError(
        () => deleteWorkspaceCompanyFixture(companyId),
        cleanupErrors,
      );
    }
    for (const user of createdUsers) {
      await collectCleanupError(
        () => assertNoError(admin.auth.admin.deleteUser(user.id)),
        cleanupErrors,
      );
    }
  }
  throwWithCleanupErrors(primaryError, cleanupErrors);
  },
);
