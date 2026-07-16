import assert from "node:assert/strict";
import { createHmac, randomBytes, randomUUID } from "node:crypto";
import { readFile, readdir } from "node:fs/promises";
import test from "node:test";

import { createClient } from "@supabase/supabase-js";
import pg from "pg";

const requiredEnv = [
  "SUPABASE_URL",
  "SUPABASE_ANON_KEY",
  "SUPABASE_SERVICE_ROLE_KEY",
  "DATABASE_URL",
];

function isLocalRuntime() {
  if (!requiredEnv.every((key) => Boolean(process.env[key]))) return false;
  try {
    const api = new URL(process.env.SUPABASE_URL);
    const database = new URL(process.env.DATABASE_URL);
    return [api.hostname, database.hostname].every((host) =>
      host === "127.0.0.1" || host === "localhost"
    );
  } catch {
    return false;
  }
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

function confirmationUrl(altinnRequestId) {
  return `https://am.ui.altinn.no/accessmanagement/ui/systemuser/request?id=${altinnRequestId}`;
}

function entitlementInput({ companyId, ownerId, requestId, incomeYear = 2025, id = null }) {
  return {
    p_id: id,
    p_company_id: companyId,
    p_user_id: ownerId,
    p_income_year: incomeYear,
    p_status: "active",
    p_billing_exempt: true,
    p_system_user_request_id: requestId,
    p_starts_at: new Date(Date.now() - 60_000).toISOString(),
    p_expires_at: new Date(Date.now() + 3_600_000).toISOString(),
    p_evidence_reference: "local-system-user-authorization-test",
  };
}

async function createConfirmedUser(admin, label) {
  const email = `talli-system-user-${label}-${randomUUID()}@example.test`;
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
    friendlyName: `system-user-${randomUUID()}`,
  });
  assert.ifError(enrollmentError);
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
}

async function applyFocusedMigration(database) {
  const files = await readdir("supabase/migrations");
  const matches = files.filter((file) => file.endsWith("_rf1086_system_user_requests.sql"));
  assert.equal(matches.length, 1);
  const sql = await readFile(`supabase/migrations/${matches[0]}`, "utf8");
  await database.query(sql);
  await database.query("notify pgrst, 'reload schema'");
}

test(
  "local Supabase denies request forgery and binds only a verified exact entitlement",
  { skip: isLocalRuntime() ? false : "local Supabase runtime variables are required", timeout: 120_000 },
  async () => {
    const database = new pg.Client({ connectionString: process.env.DATABASE_URL });
    await database.connect();
    const admin = serviceClient();
    const users = [];
    const signedInClients = [];
    const companyIds = [];
    let evidenceId = null;
    const entitlementIds = [];
    const requestId = randomUUID();
    const altinnRequestId = randomUUID();
    const externalRef = randomBytes(32).toString("base64url");
    const rejectedRequestId = randomUUID();
    const rejectedAltinnRequestId = randomUUID();
    const rejectedExternalRef = randomBytes(32).toString("base64url");
    const previewId = randomUUID();
    const approvalId = randomUUID();
    let previousLaunchSignoffs = [];
    let launchSignoffsReplaced = false;

    try {
      await applyFocusedMigration(database);
      const ownerAUser = await createConfirmedUser(admin, "owner-a");
      const ownerBUser = await createConfirmedUser(admin, "owner-b");
      const operatorUser = await createConfirmedUser(admin, "operator");
      users.push(ownerAUser, ownerBUser, operatorUser);

      const ownerA = await signIn(ownerAUser);
      const ownerB = await signIn(ownerBUser);
      const operator = await signIn(operatorUser);
      signedInClients.push(ownerA, ownerB, operator);
      await elevateToAal2(ownerA);

      const companyAId = randomUUID();
      const companyBId = randomUUID();
      companyIds.push(companyAId, companyBId);
      const { error: companyError } = await admin.from("companies").insert([
        {
          id: companyAId,
          org_number: String(100_000_000 + Math.floor(Math.random() * 899_999_999)),
          name: "System User Company A",
          entity_type: "AS",
          created_by: ownerAUser.id,
          identity_confirmed_at: new Date().toISOString(),
          identity_locked_at: new Date().toISOString(),
        },
        {
          id: companyBId,
          org_number: String(100_000_000 + Math.floor(Math.random() * 899_999_999)),
          name: "System User Company B",
          entity_type: "AS",
          created_by: ownerBUser.id,
          identity_confirmed_at: new Date().toISOString(),
          identity_locked_at: new Date().toISOString(),
        },
      ]);
      assert.ifError(companyError);
      const { error: membershipError } = await admin.from("company_memberships").insert([
        {
          company_id: companyAId,
          user_id: ownerAUser.id,
          role: "owner",
          accepted_at: new Date().toISOString(),
        },
        {
          company_id: companyBId,
          user_id: ownerBUser.id,
          role: "owner",
          accepted_at: new Date().toISOString(),
        },
      ]);
      assert.ifError(membershipError);
      const { error: operatorError } = await admin.from("support_operators").insert({
        user_id: operatorUser.id,
        role: "admin",
        active: true,
      });
      assert.ifError(operatorError);

      const { data: evidence, error: evidenceError } = await admin
        .from("authority_operations")
        .insert({
          operation: "register_rf1086_system",
          actor_id: operatorUser.id,
          status: "succeeded",
          request_hash: "a".repeat(64),
          result_code: "created_and_verified",
          completed_at: new Date().toISOString(),
        })
        .select("id")
        .single();
      assert.ifError(evidenceError);
      evidenceId = evidence.id;

      const aal1Attempt = await ownerB.rpc("begin_system_user_request", {
        p_id: rejectedRequestId,
        p_company_id: companyBId,
        p_external_ref: rejectedExternalRef,
      });
      assert.match(aal1Attempt.error?.message ?? "", /fresh_owner_step_up_required/iu);
      await elevateToAal2(ownerB);

      const { data: rejectedBegun, error: rejectedBeginError } = await ownerB.rpc(
        "begin_system_user_request",
        {
          p_id: rejectedRequestId,
          p_company_id: companyBId,
          p_external_ref: rejectedExternalRef,
        },
      );
      assert.ifError(rejectedBeginError);
      assert.equal(rejectedBegun.status, "creating");

      const unverifiedActivation = await operator.rpc(
        "manage_production_pilot_entitlement",
        entitlementInput({
          companyId: companyBId,
          ownerId: ownerBUser.id,
          requestId: rejectedRequestId,
        }),
      );
      assert.match(unverifiedActivation.error?.message ?? "", /verified_system_user_required/iu);

      const { data: rejected, error: rejectedError } = await admin.rpc(
        "record_system_user_authority_state",
        {
          p_request_id: rejectedRequestId,
          p_company_id: companyBId,
          p_altinn_request_id: rejectedAltinnRequestId,
          p_external_ref: rejectedExternalRef,
          p_status: "rejected",
          p_confirm_url: null,
          p_failure_code: null,
          p_operator_evidence_id: evidenceId,
        },
      );
      assert.ifError(rejectedError);
      assert.equal(rejected.status, "rejected");

      const rejectedActivation = await operator.rpc(
        "manage_production_pilot_entitlement",
        entitlementInput({
          companyId: companyBId,
          ownerId: ownerBUser.id,
          requestId: rejectedRequestId,
        }),
      );
      assert.match(rejectedActivation.error?.message ?? "", /verified_system_user_required/iu);

      const exactTerminalRetry = await admin.rpc("record_system_user_authority_state", {
        p_request_id: rejectedRequestId,
        p_company_id: companyBId,
        p_altinn_request_id: rejectedAltinnRequestId,
        p_external_ref: rejectedExternalRef,
        p_status: "rejected",
        p_confirm_url: null,
        p_failure_code: null,
        p_operator_evidence_id: evidenceId,
      });
      assert.ifError(exactTerminalRetry.error);
      assert.equal(exactTerminalRetry.data.status, "rejected");

      for (const evidenceRewrite of [
        { p_altinn_request_id: randomUUID() },
        { p_confirm_url: confirmationUrl(rejectedAltinnRequestId) },
        { p_failure_code: "network_error" },
        { p_operator_evidence_id: randomUUID() },
      ]) {
        const terminalRewrite = await admin.rpc("record_system_user_authority_state", {
          p_request_id: rejectedRequestId,
          p_company_id: companyBId,
          p_altinn_request_id: rejectedAltinnRequestId,
          p_external_ref: rejectedExternalRef,
          p_status: "rejected",
          p_confirm_url: null,
          p_failure_code: null,
          p_operator_evidence_id: evidenceId,
          ...evidenceRewrite,
        });
        assert.match(
          terminalRewrite.error?.message ?? "",
          /terminal_evidence_immutable/iu,
        );
      }

      const { data: begun, error: beginError } = await ownerA.rpc(
        "begin_system_user_request",
        { p_id: requestId, p_company_id: companyAId, p_external_ref: externalRef },
      );
      assert.ifError(beginError);
      assert.equal(begun.id, requestId);
      assert.equal(begun.initiating_owner_user_id, ownerAUser.id);
      assert.equal(begun.status, "creating");

      const ownerBRead = await ownerB
        .from("system_user_requests")
        .select("id")
        .eq("id", requestId);
      assert.deepEqual(ownerBRead.data, []);
      assert.equal(ownerBRead.error, null);

      const forged = await ownerA
        .from("system_user_requests")
        .update({ status: "accepted" })
        .eq("id", requestId);
      assert.ok(forged.error);

      const serviceDirectMutation = await admin
        .from("system_user_requests")
        .update({ status: "accepted" })
        .eq("id", requestId);
      assert.ok(serviceDirectMutation.error);
      const serviceDirectRead = await admin
        .from("system_user_requests")
        .select("id")
        .eq("id", requestId);
      assert.ok(serviceDirectRead.error);

      const ownerTransition = await ownerA.rpc("record_system_user_authority_state", {
        p_request_id: requestId,
        p_company_id: companyAId,
        p_altinn_request_id: altinnRequestId,
        p_external_ref: externalRef,
        p_status: "new",
        p_confirm_url: confirmationUrl(altinnRequestId),
        p_failure_code: null,
        p_operator_evidence_id: evidenceId,
      });
      assert.match(
        ownerTransition.error?.message ?? "",
        /permission denied for function record_system_user_authority_state|service_role_required/iu,
      );

      for (const unsafeConfirmUrl of [
        `${confirmationUrl(altinnRequestId)}&token=secret-pii`,
        `${confirmationUrl(altinnRequestId)}#secret-pii`,
        `${confirmationUrl(altinnRequestId)}%26token%3Dsecret-pii`,
      ]) {
        const unsafeConfirmation = await admin.rpc("record_system_user_authority_state", {
          p_request_id: requestId,
          p_company_id: companyAId,
          p_altinn_request_id: altinnRequestId,
          p_external_ref: externalRef,
          p_status: "new",
          p_confirm_url: unsafeConfirmUrl,
          p_failure_code: null,
          p_operator_evidence_id: evidenceId,
        });
        assert.match(
          unsafeConfirmation.error?.message ?? "",
          /invalid_confirmation_url/iu,
        );
      }

      const { data: recordedNew, error: recordNewError } = await admin.rpc(
        "record_system_user_authority_state",
        {
          p_request_id: requestId,
          p_company_id: companyAId,
          p_altinn_request_id: altinnRequestId,
          p_external_ref: externalRef,
          p_status: "new",
          p_confirm_url: confirmationUrl(altinnRequestId),
          p_failure_code: null,
          p_operator_evidence_id: evidenceId,
        },
      );
      assert.ifError(recordNewError);
      assert.equal(recordedNew.status, "new");
      assert.equal(recordedNew.confirm_url, confirmationUrl(altinnRequestId));
      assert.ok(recordedNew.requested_at);
      assert.ok(recordedNew.last_status_checked_at);

      const wrongRelationship = await admin.rpc("record_system_user_authority_state", {
        p_request_id: requestId,
        p_company_id: companyAId,
        p_altinn_request_id: altinnRequestId,
        p_external_ref: randomBytes(32).toString("base64url"),
        p_status: "accepted",
        p_confirm_url: null,
        p_failure_code: null,
        p_operator_evidence_id: evidenceId,
      });
      assert.match(wrongRelationship.error?.message ?? "", /relationship_mismatch/iu);

      const { data: accepted, error: acceptedError } = await admin.rpc(
        "record_system_user_authority_state",
        {
          p_request_id: requestId,
          p_company_id: companyAId,
          p_altinn_request_id: altinnRequestId,
          p_external_ref: externalRef,
          p_status: "accepted",
          p_confirm_url: null,
          p_failure_code: null,
          p_operator_evidence_id: evidenceId,
        },
      );
      assert.ifError(acceptedError);
      assert.equal(accepted.status, "accepted");
      assert.ok(accepted.accepted_at);
      assert.ok(accepted.resolved_at);

      const invalidFailureCode = await admin.rpc("record_system_user_authority_state", {
        p_request_id: requestId,
        p_company_id: companyAId,
        p_altinn_request_id: altinnRequestId,
        p_external_ref: externalRef,
        p_status: "verification_failed",
        p_confirm_url: null,
        p_failure_code: "raw_authority_detail_must_not_persist",
        p_operator_evidence_id: evidenceId,
      });
      assert.match(invalidFailureCode.error?.message ?? "", /failure_code_invalid/iu);

      const unsafeEvidence = await admin.rpc("record_system_user_authority_state", {
        p_request_id: requestId,
        p_company_id: companyAId,
        p_altinn_request_id: altinnRequestId,
        p_external_ref: externalRef,
        p_status: "accepted",
        p_confirm_url: null,
        p_failure_code: null,
        p_operator_evidence_id: randomUUID(),
      });
      assert.match(unsafeEvidence.error?.message ?? "", /operator_evidence_invalid/iu);

      const invalidTransition = await admin.rpc("record_system_user_authority_state", {
        p_request_id: requestId,
        p_company_id: companyAId,
        p_altinn_request_id: altinnRequestId,
        p_external_ref: externalRef,
        p_status: "new",
        p_confirm_url: null,
        p_failure_code: null,
        p_operator_evidence_id: evidenceId,
      });
      assert.match(invalidTransition.error?.message ?? "", /invalid_system_user_transition/iu);

      const wrongPreflight = await admin.rpc("verify_system_user_preflight", {
        p_request_id: requestId,
        p_expected_external_ref: randomBytes(32).toString("base64url"),
      });
      assert.match(wrongPreflight.error?.message ?? "", /relationship_mismatch/iu);

      const { data: verified, error: verifyError } = await admin.rpc(
        "verify_system_user_preflight",
        { p_request_id: requestId, p_expected_external_ref: externalRef },
      );
      assert.ifError(verifyError);
      assert.equal(verified.status, "accepted");
      assert.ok(verified.preflight_verified_at);

      const { data: entitlement, error: entitlementError } = await operator.rpc(
        "manage_production_pilot_entitlement",
        entitlementInput({
          companyId: companyAId,
          ownerId: ownerAUser.id,
          requestId,
        }),
      );
      assert.ifError(entitlementError);
      entitlementIds.push(entitlement.id);
      assert.equal(entitlement.system_user_request_id, requestId);
      assert.equal(entitlement.system_user_external_reference, externalRef);

      const { data: secondEntitlement, error: secondEntitlementError } = await operator.rpc(
        "manage_production_pilot_entitlement",
        entitlementInput({
          companyId: companyAId,
          ownerId: ownerAUser.id,
          requestId,
          incomeYear: 2024,
        }),
      );
      assert.ifError(secondEntitlementError);
      entitlementIds.push(secondEntitlement.id);

      await database.query(
        `insert into public.filing_previews (
           id, company_id, income_year, filing, status, issues, preview,
           hovedskjema_xml, underskjema_xml, created_by
         ) values ($1, $2, 2025, 'aksjonaerregisteroppgaven', 'ready', '[]'::jsonb,
           'local production preview', '<melding/>', '{"RF-1086":"<underskjema/>"}'::jsonb, $3)`,
        [previewId, companyAId, ownerAUser.id],
      );
      await database.query(
        `insert into public.filing_approval_snapshots (
           id, entitlement_id, preview_id, company_id, user_id, income_year,
           obligation, case_profile, adapter_version, payload_hash, manifest_hash,
           manifest, approved_by
         ) values ($1, $2, $3, $4, $5, 2025, 'aksjonaerregisteroppgaven',
           'rf1086_no_activity_v1', 'local-adapter-v1', $6, $7, '{}'::jsonb, $5)`,
        [approvalId, entitlement.id, previewId, companyAId, ownerAUser.id, "b".repeat(64), "c".repeat(64)],
      );
      await database.query(
        `insert into public.authority_permissions (
           company_id, obligation, submitter_user_id, confirmed_by, production_enabled
         ) values ($1, 'aksjonaerregisteroppgaven', $2, $2, true)`,
        [companyAId, ownerAUser.id],
      );
      await database.query(
        `insert into public.filing_readiness_snapshots (
           company_id, income_year, obligation, status, ready, hard_blocks,
           warnings, accepted_warnings, created_by
         ) values ($1, 2025, 'aksjonaerregisteroppgaven', 'ready', true,
           '[]'::jsonb, '[]'::jsonb, '[]'::jsonb, $2)`,
        [companyAId, ownerAUser.id],
      );

      const launchKeys = [
        "launch_legal_name_public_copy",
        "legal_policy_pack",
        "security_restore",
        "support_rollback",
        "founder_production_go_live",
        "rf1086_authority",
      ];
      previousLaunchSignoffs = (
        await database.query("select * from public.launch_signoffs where key = any($1::text[])", [launchKeys])
      ).rows;
      launchSignoffsReplaced = true;
      await database.query(
        `insert into public.launch_signoffs (
           key, status, reviewer, reviewed_at, evidence_link, decision, recorded_by
         )
         select key, 'approved', 'local-runtime', pg_catalog.now(),
           'https://example.test/local-evidence', 'local test approval', $2
         from unnest($1::text[]) key
         on conflict (key) do update set
           status = excluded.status,
           reviewer = excluded.reviewer,
           reviewed_at = excluded.reviewed_at,
           evidence_link = excluded.evidence_link,
           decision = excluded.decision,
           recorded_by = excluded.recorded_by,
           updated_at = pg_catalog.now()`,
        [launchKeys, operatorUser.id],
      );

      const { data: submission, error: submissionError } = await ownerA.rpc(
        "begin_production_filing",
        { p_approval_id: approvalId },
      );
      assert.ifError(submissionError);
      assert.equal(submission.approval_id, approvalId);
      assert.equal(submission.entitlement_id, entitlement.id);

      let concurrentBeginPromise;
      let concurrentActivationPromise;
      await database.query("begin");
      try {
        await database.query(
          "select pg_catalog.set_config('request.jwt.claims', $1, true)",
          [JSON.stringify({ role: "service_role" })],
        );
        const invalidation = await database.query(
          `select (
             public.record_system_user_authority_state(
               $1, $2, $3, $4, 'verification_failed', null, 'network_error', $5
             )
           ).status as status`,
          [requestId, companyAId, altinnRequestId, externalRef, evidenceId],
        );
        assert.equal(invalidation.rows[0].status, "verification_failed");

        let beginSettled = false;
        let activationSettled = false;
        concurrentBeginPromise = ownerA
          .rpc("begin_production_filing", { p_approval_id: approvalId })
          .then((result) => {
            beginSettled = true;
            return result;
          });
        concurrentActivationPromise = operator
          .rpc(
            "manage_production_pilot_entitlement",
            entitlementInput({
              companyId: companyAId,
              ownerId: ownerAUser.id,
              requestId,
              id: entitlement.id,
            }),
          )
          .then((result) => {
            activationSettled = true;
            return result;
          });

        await new Promise((resolve) => setTimeout(resolve, 100));
        assert.equal(beginSettled, false, "begin waits for the invalidation request lock");
        assert.equal(
          activationSettled,
          false,
          "entitlement activation waits for the invalidation request lock",
        );
        await database.query("commit");
      } catch (error) {
        await database.query("rollback").catch(() => undefined);
        await Promise.allSettled(
          [concurrentBeginPromise, concurrentActivationPromise].filter(Boolean),
        );
        throw error;
      }

      const [invalidBegin, failedReactivation] = await Promise.all([
        concurrentBeginPromise,
        concurrentActivationPromise,
      ]);
      assert.match(invalidBegin.error?.message ?? "", /release_gate_blocked/iu);
      assert.match(failedReactivation.error?.message ?? "", /verified_system_user_required/iu);

      const invalidated = (
        await database.query(
          "select status, preflight_verified_at from public.system_user_requests where id = $1",
          [requestId],
        )
      ).rows[0];
      assert.equal(invalidated.status, "verification_failed");
      assert.equal(invalidated.preflight_verified_at, null);

      const suspendedRows = (
        await database.query(
          "select id, status from public.production_pilot_entitlements where id = any($1::uuid[]) order by id",
          [entitlementIds],
        )
      ).rows;
      assert.equal(suspendedRows.length, 2);
      assert.ok(suspendedRows.every((row) => row.status === "suspended"));

      const { data: operatorRows, error: operatorReadError } = await operator
        .from("system_user_requests")
        .select("id,status")
        .eq("id", requestId);
      assert.ifError(operatorReadError);
      assert.deepEqual(operatorRows, [{ id: requestId, status: "verification_failed" }]);
    } finally {
      for (const client of signedInClients) {
        client.auth.stopAutoRefresh();
        await client.auth.signOut({ scope: "local" }).catch(() => undefined);
      }
      admin.auth.stopAutoRefresh();
      try {
        await database.query(
          "delete from public.production_filing_submissions where approval_id = $1",
          [approvalId],
        );
        await database.query("delete from public.filing_approval_snapshots where id = $1", [approvalId]);
        await database.query("delete from public.filing_readiness_snapshots where company_id = any($1::uuid[])", [companyIds]);
        await database.query("delete from public.authority_permissions where company_id = any($1::uuid[])", [companyIds]);
        await database.query("delete from public.filing_previews where id = $1", [previewId]);
        await database.query(
          "delete from public.production_pilot_entitlements where id = any($1::uuid[])",
          [entitlementIds],
        );
        if ((await database.query("select to_regclass('public.system_user_requests') as relation")).rows[0].relation) {
          await database.query(
            "delete from public.system_user_requests where id = any($1::uuid[])",
            [[requestId, rejectedRequestId]],
          );
        }
        if (launchSignoffsReplaced) {
          const launchKeys = [
            "launch_legal_name_public_copy",
            "legal_policy_pack",
            "security_restore",
            "support_rollback",
            "founder_production_go_live",
            "rf1086_authority",
          ];
          await database.query("delete from public.launch_signoffs where key = any($1::text[])", [launchKeys]);
          for (const signoff of previousLaunchSignoffs) {
            await database.query(
              `insert into public.launch_signoffs (
                 key, status, reviewer, reviewed_at, evidence_link, decision,
                 recorded_by, updated_at
               ) values ($1, $2, $3, $4, $5, $6, $7, $8)`,
              [
                signoff.key,
                signoff.status,
                signoff.reviewer,
                signoff.reviewed_at,
                signoff.evidence_link,
                signoff.decision,
                signoff.recorded_by,
                signoff.updated_at,
              ],
            );
          }
        }
        await database.query(
          "delete from public.authority_operations where id = $1",
          [evidenceId],
        );
        if (companyIds.length) {
          await database.query("delete from public.companies where id = any($1::uuid[])", [companyIds]);
        }
        for (const user of users) {
          await admin.auth.admin.deleteUser(user.id);
        }
      } finally {
        await database.end();
      }
    }
  },
);
