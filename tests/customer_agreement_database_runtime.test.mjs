import assert from "node:assert/strict";
import { randomUUID } from "node:crypto";
import { readFile } from "node:fs/promises";
import test from "node:test";

import { createClient } from "@supabase/supabase-js";
import pg from "pg";

const requiredEnv = [
  "SUPABASE_URL",
  "SUPABASE_ANON_KEY",
  "SUPABASE_SERVICE_ROLE_KEY",
  "DATABASE_URL",
];
const correctiveMigrationUrl = new URL(
  "../supabase/migrations/20260717113000_restrict_customer_agreement_creation.sql",
  import.meta.url,
);

function hasLocalEnvironment() {
  if (!requiredEnv.every((key) => Boolean(process.env[key]))) return false;
  try {
    return ["127.0.0.1", "localhost"].includes(new URL(process.env.DATABASE_URL).hostname);
  } catch {
    return false;
  }
}

function client(key) {
  return createClient(process.env.SUPABASE_URL, key, {
    auth: { persistSession: false, autoRefreshToken: false },
  });
}

function rpcArguments(actorId, orgNumber, overrides = {}) {
  return {
    p_actor_id: actorId,
    p_org_number: orgNumber,
    p_name: "Avtale Runtime AS",
    p_entity_type: "AS",
    p_address: "Testveien 1",
    p_postal_code: "0001",
    p_city: "Oslo",
    p_status_text: "Aktivt",
    p_source: "brreg",
    p_business_terms_version: "2026-07-17",
    p_business_terms_effective_date: "2026-07-17",
    p_business_terms_path: "/vilkar",
    p_business_terms_sha256: "a".repeat(64),
    p_dpa_version: "2026-07-17",
    p_dpa_effective_date: "2026-07-17",
    p_dpa_path: "/databehandleravtale",
    p_dpa_sha256: "b".repeat(64),
    p_authority_statement_version: "authority-v1",
    p_acceptance_method: "in_app_clickwrap",
    ...overrides,
  };
}

async function createConfirmedUser(admin) {
  const email = `agreement-runtime-${randomUUID()}@example.test`;
  const password = `Runtime-${randomUUID()}-Aa1!`;
  const { data, error } = await admin.auth.admin.createUser({
    email,
    password,
    email_confirm: true,
  });
  assert.ifError(error);
  return { ...data.user, password };
}

test(
  "customer agreement creation is service-only, atomic, and immutable",
  { skip: hasLocalEnvironment() ? false : "local Supabase environment is required", timeout: 30_000 },
  async () => {
    const admin = client(process.env.SUPABASE_SERVICE_ROLE_KEY);
    const anonymous = client(process.env.SUPABASE_ANON_KEY);
    const database = new pg.Client({ connectionString: process.env.DATABASE_URL });
    const authenticated = client(process.env.SUPABASE_ANON_KEY);
    const createdCompanyIds = [];
    const successfulOrgNumber = String(700_000_000 + Math.floor(Math.random() * 99_000_000));
    const failedOrgNumber = String(Number(successfulOrgNumber) + 1);
    let user;

    await database.connect();
    try {
      await database.query(`
        create or replace function public.create_company_workspace_with_acceptance(
          p_org_number text,
          p_name text,
          p_entity_type text,
          p_address text,
          p_postal_code text,
          p_city text,
          p_status_text text,
          p_source text,
          p_business_terms_version text,
          p_business_terms_effective_date date,
          p_business_terms_path text,
          p_business_terms_sha256 text,
          p_dpa_version text,
          p_dpa_effective_date date,
          p_dpa_path text,
          p_dpa_sha256 text,
          p_authority_statement_version text,
          p_acceptance_method text
        )
        returns uuid
        language sql
        security definer
        set search_path = ''
        as $$ select null::uuid $$;

        grant execute on function public.create_company_workspace_with_acceptance(
          text, text, text, text, text, text, text, text, text, date, text, text, text, date, text, text, text, text
        ) to authenticated;

        alter table public.customer_agreement_acceptances
          drop constraint if exists customer_agreement_acceptances_company_id_fkey;
        alter table public.customer_agreement_acceptances
          add constraint customer_agreement_acceptances_company_id_fkey
          foreign key (company_id) references public.companies(id) on delete cascade;

        grant all privileges on table public.customer_agreement_acceptances to service_role;
      `);
      await database.query(await readFile(correctiveMigrationUrl, "utf8"));

      const overloads = await database.query(`
        select
          oidvectortypes(p.proargtypes) as signature,
          has_function_privilege('anon', p.oid, 'execute') as anon_execute,
          has_function_privilege('authenticated', p.oid, 'execute') as authenticated_execute,
          has_function_privilege('service_role', p.oid, 'execute') as service_role_execute
        from pg_proc p
        join pg_namespace n on n.oid = p.pronamespace
        where n.nspname = 'public'
          and p.proname = 'create_company_workspace_with_acceptance'
        order by signature
      `);
      assert.deepEqual(overloads.rows, [{
        signature: "uuid, text, text, text, text, text, text, text, text, text, date, text, text, text, date, text, text, text, text",
        anon_execute: false,
        authenticated_execute: false,
        service_role_execute: true,
      }]);

      const foreignKey = await database.query(`
        select c.confdeltype
        from pg_constraint c
        where c.conrelid = 'public.customer_agreement_acceptances'::regclass
          and c.conname = 'customer_agreement_acceptances_company_id_fkey'
      `);
      assert.equal(foreignKey.rowCount, 1);
      assert.ok(["a", "r"].includes(foreignKey.rows[0].confdeltype));

      const tablePrivileges = await database.query(`
        select
          has_table_privilege('service_role', 'public.customer_agreement_acceptances', 'select') as can_select,
          has_table_privilege('service_role', 'public.customer_agreement_acceptances', 'insert') as can_insert,
          has_table_privilege('service_role', 'public.customer_agreement_acceptances', 'update') as can_update,
          has_table_privilege('service_role', 'public.customer_agreement_acceptances', 'delete') as can_delete,
          has_table_privilege('service_role', 'public.customer_agreement_acceptances', 'truncate') as can_truncate
      `);
      assert.deepEqual(tablePrivileges.rows[0], {
        can_select: true,
        can_insert: false,
        can_update: false,
        can_delete: false,
        can_truncate: false,
      });

      user = await createConfirmedUser(admin);
      const { error: signInError } = await authenticated.auth.signInWithPassword({
        email: user.email,
        password: user.password,
      });
      assert.ifError(signInError);

      const { error: anonymousError } = await anonymous.rpc(
        "create_company_workspace_with_acceptance",
        rpcArguments(user.id, failedOrgNumber),
      );
      assert.ok(anonymousError, "anonymous RPC execution must be denied");

      const { error: authenticatedError } = await authenticated.rpc(
        "create_company_workspace_with_acceptance",
        rpcArguments(user.id, failedOrgNumber),
      );
      assert.ok(authenticatedError, "authenticated RPC execution must be denied");

      const { error: nullMethodError } = await admin.rpc(
        "create_company_workspace_with_acceptance",
        rpcArguments(user.id, failedOrgNumber, { p_acceptance_method: null }),
      );
      assert.equal(nullMethodError?.message, "invalid_acceptance_method");

      const { data: companyId, error: createError } = await admin.rpc(
        "create_company_workspace_with_acceptance",
        rpcArguments(user.id, successfulOrgNumber),
      );
      assert.ifError(createError);
      assert.match(companyId, /^[a-f0-9-]{36}$/u);
      createdCompanyIds.push(companyId);

      const evidence = await database.query(
        `select
           (select count(*)::int from public.companies where id = $1) as companies,
           (select count(*)::int from public.company_memberships where company_id = $1 and user_id = $2 and role = 'owner' and accepted_at is not null) as owners,
           (select count(*)::int from public.customer_agreement_acceptances where company_id = $1 and accepted_by = $2) as acceptances,
           (select count(*)::int from public.audit_events where company_id = $1 and actor_id = $2 and action = 'workspace_created') as audits,
           (select count(*)::int from public.production_pilot_entitlements where company_id = $1) as entitlements`,
        [companyId, user.id],
      );
      assert.deepEqual(evidence.rows[0], {
        companies: 1,
        owners: 1,
        acceptances: 1,
        audits: 1,
        entitlements: 0,
      });

      const { data: ownerEvidence, error: ownerReadError } = await authenticated
        .from("customer_agreement_acceptances")
        .select("company_id")
        .eq("company_id", companyId);
      assert.ifError(ownerReadError);
      assert.deepEqual(ownerEvidence, [{ company_id: companyId }]);

      const { error: directInsertError } = await admin.from("customer_agreement_acceptances").insert({
        company_id: companyId,
        accepted_by: user.id,
        customer_legal_name: "Direct Insert AS",
        customer_org_number: successfulOrgNumber,
        business_terms_version: "2026-07-17",
        business_terms_effective_date: "2026-07-17",
        business_terms_path: "/vilkar",
        business_terms_sha256: "a".repeat(64),
        dpa_version: "2026-07-17",
        dpa_effective_date: "2026-07-17",
        dpa_path: "/databehandleravtale",
        dpa_sha256: "b".repeat(64),
        authority_statement_version: "authority-v1",
        acceptance_method: "in_app_clickwrap",
        accepted_at: new Date().toISOString(),
      });
      assert.ok(directInsertError, "service role direct insertion must be denied");

      const { error: updateError } = await admin
        .from("customer_agreement_acceptances")
        .update({ customer_legal_name: "Mutated AS" })
        .eq("company_id", companyId);
      assert.ok(updateError, "service role evidence update must be denied");

      const { error: deleteError } = await admin
        .from("customer_agreement_acceptances")
        .delete()
        .eq("company_id", companyId);
      assert.ok(deleteError, "service role evidence deletion must be denied");

      await assert.rejects(
        database.query("begin; set local role service_role; truncate table public.customer_agreement_acceptances"),
        /permission denied/iu,
      );
      await database.query("rollback");

      const failedEvidence = await database.query(
        `select
           (select count(*)::int from public.companies where org_number = $1) as companies,
           (select count(*)::int from public.customer_agreement_acceptances where customer_org_number = $1) as acceptances`,
        [failedOrgNumber],
      );
      assert.deepEqual(failedEvidence.rows[0], { companies: 0, acceptances: 0 });
    } finally {
      await database.query("begin");
      await database.query("set local session_replication_role = replica");
      if (user) {
        const fixtureCompanies = await database.query(
          "select id from public.companies where created_by = $1 and org_number = any($2::text[])",
          [user.id, [successfulOrgNumber, failedOrgNumber]],
        );
        createdCompanyIds.push(...fixtureCompanies.rows.map(({ id }) => id));
      }
      const uniqueCompanyIds = [...new Set(createdCompanyIds)];
      if (uniqueCompanyIds.length > 0) {
        await database.query("delete from public.customer_agreement_acceptances where company_id = any($1::uuid[])", [
          uniqueCompanyIds,
        ]);
        await database.query("delete from public.audit_events where company_id = any($1::uuid[])", [uniqueCompanyIds]);
        await database.query("delete from public.company_memberships where company_id = any($1::uuid[])", [uniqueCompanyIds]);
        await database.query("delete from public.companies where id = any($1::uuid[])", [uniqueCompanyIds]);
      }
      await database.query("commit");
      await authenticated.auth.signOut();
      if (user) await admin.auth.admin.deleteUser(user.id);
      await database.end();
    }
  },
);
