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
    let entitlementId = null;
    const requestId = randomUUID();
    const altinnRequestId = randomUUID();
    const externalRef = randomBytes(32).toString("base64url");

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
        p_id: randomUUID(),
        p_company_id: companyBId,
        p_external_ref: randomBytes(32).toString("base64url"),
      });
      assert.match(aal1Attempt.error?.message ?? "", /fresh_owner_step_up_required/iu);

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
        p_confirm_url: `https://am.ui.altinn.no/accessmanagement/ui/systemuser/request?id=${altinnRequestId}`,
        p_failure_code: null,
        p_operator_evidence_id: evidenceId,
      });
      assert.match(
        ownerTransition.error?.message ?? "",
        /permission denied for function record_system_user_authority_state|service_role_required/iu,
      );

      const { data: recordedNew, error: recordNewError } = await admin.rpc(
        "record_system_user_authority_state",
        {
          p_request_id: requestId,
          p_company_id: companyAId,
          p_altinn_request_id: altinnRequestId,
          p_external_ref: externalRef,
          p_status: "new",
          p_confirm_url: `https://am.ui.altinn.no/accessmanagement/ui/systemuser/request?id=${altinnRequestId}`,
          p_failure_code: null,
          p_operator_evidence_id: evidenceId,
        },
      );
      assert.ifError(recordNewError);
      assert.equal(recordedNew.status, "new");
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
        {
          p_id: null,
          p_company_id: companyAId,
          p_user_id: ownerAUser.id,
          p_income_year: 2025,
          p_status: "active",
          p_billing_exempt: true,
          p_system_user_request_id: requestId,
          p_starts_at: new Date(Date.now() - 60_000).toISOString(),
          p_expires_at: new Date(Date.now() + 3_600_000).toISOString(),
          p_evidence_reference: "local-role-abuse-test",
        },
      );
      assert.ifError(entitlementError);
      entitlementId = entitlement.id;
      assert.equal(entitlement.system_user_request_id, requestId);
      assert.equal(entitlement.system_user_external_reference, externalRef);

      const { data: operatorRows, error: operatorReadError } = await operator
        .from("system_user_requests")
        .select("id,status")
        .eq("id", requestId);
      assert.ifError(operatorReadError);
      assert.deepEqual(operatorRows, [{ id: requestId, status: "accepted" }]);
    } finally {
      for (const client of signedInClients) {
        client.auth.stopAutoRefresh();
        await client.auth.signOut({ scope: "local" }).catch(() => undefined);
      }
      admin.auth.stopAutoRefresh();
      try {
        await database.query(
          "delete from public.production_pilot_entitlements where id = $1",
          [entitlementId],
        );
        if ((await database.query("select to_regclass('public.system_user_requests') as relation")).rows[0].relation) {
          await database.query(
            "delete from public.system_user_requests where id = $1",
            [requestId],
          );
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
