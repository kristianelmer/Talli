import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import pg from "pg";

const { Client } = pg;
const databaseUrl = process.env.DATABASE_URL;
const ownerId = "73000000-0000-0000-0000-000000000001";
const outsiderId = "73000000-0000-0000-0000-000000000002";
const companyId = "73000000-0000-0000-0000-000000000003";
const systemUserRequestId = "73000000-0000-0000-0000-000000000004";

async function topology(client) {
  const result = await client.query(String.raw`
    select
      pg_catalog.to_regnamespace('billing') is not null as billing_schema,
      pg_catalog.to_regclass('billing.billing_accounts') is not null as canonical_accounts,
      pg_catalog.to_regclass('billing.billing_payment_events') is not null as canonical_events,
      pg_catalog.to_regclass('billing.production_pilot_entitlements') is not null as canonical_pilots,
      pg_catalog.to_regclass('public.billing_accounts') is not null as public_accounts,
      pg_catalog.to_regclass('public.billing_payment_events') is not null as public_events,
      pg_catalog.to_regclass('public.production_pilot_entitlements') is not null as public_pilots,
      coalesce((select relation.relkind::text from pg_catalog.pg_class relation
        where relation.oid=pg_catalog.to_regclass('public.billing_accounts')), '') as public_accounts_kind,
      coalesce((select relation.relkind::text from pg_catalog.pg_class relation
        where relation.oid=pg_catalog.to_regclass('billing.billing_accounts')), '') as canonical_accounts_kind,
      coalesce((select relation.relforcerowsecurity from pg_catalog.pg_class relation
        where relation.oid=pg_catalog.to_regclass('billing.billing_accounts')), false) as accounts_force_rls,
      coalesce((select owner.rolname from pg_catalog.pg_class relation
        join pg_catalog.pg_roles owner on owner.oid=relation.relowner
        where relation.oid=pg_catalog.to_regclass('billing.billing_accounts')), '') as accounts_owner
  `);
  return result.rows[0];
}

async function canonicalEvidence(client) {
  const result = await client.query(String.raw`
    select pg_catalog.jsonb_build_object(
      'accounts', (select coalesce(pg_catalog.jsonb_agg(pg_catalog.to_jsonb(item) order by item.company_id), '[]'::jsonb) from billing.billing_accounts item),
      'events', (select coalesce(pg_catalog.jsonb_agg(pg_catalog.to_jsonb(item) order by item.id), '[]'::jsonb) from billing.billing_payment_events item),
      'pilots', (select coalesce(pg_catalog.jsonb_agg(pg_catalog.to_jsonb(item) order by item.id), '[]'::jsonb) from billing.production_pilot_entitlements item)
    ) as value
  `);
  return result.rows[0].value;
}

async function grantBillingStoreRole(client) {
  await client.query(String.raw`
    do $grant_billing_store_role$
    begin
      execute pg_catalog.format('grant billing_store_owner to %I', current_user);
    end
    $grant_billing_store_role$;
  `);
}

async function revokeBillingStoreRole(client) {
  await client.query(String.raw`
    do $revoke_billing_store_role$
    begin
      execute pg_catalog.format('revoke billing_store_owner from %I', current_user);
    end
    $revoke_billing_store_role$;
  `);
}

async function commandReceiptEvidence(client) {
  await grantBillingStoreRole(client);
  try {
    await client.query("begin");
    try {
      await client.query("set local role billing_store_owner");
      await client.query(
        "select pg_catalog.set_config('talli.verified_actor_id', $1, true), pg_catalog.set_config('talli.verified_actor_claims', $2, true)",
        [ownerId, JSON.stringify({
          sub: ownerId,
          aal: "aal2",
          amr: [{ method: "totp", timestamp: Date.now() / 1000 }],
        })],
      );
      const result = await client.query(String.raw`
        select idempotency_key, company_id::text, operation, request_fingerprint,
          result, created_by::text
        from billing.billing_command_receipts
        where idempotency_key = 'billing-rollback-receipt-00000001'
      `);
      await client.query("commit");
      assert.equal(result.rows.length, 1);
      return result.rows[0];
    } catch (error) {
      await client.query("rollback");
      throw error;
    }
  } finally {
    await revokeBillingStoreRole(client);
  }
}

async function seedCommandReceipt(client) {
  await grantBillingStoreRole(client);
  try {
    await client.query("begin");
    try {
      await client.query("set local role billing_store_owner");
      await client.query(
        "select pg_catalog.set_config('talli.verified_actor_id', $1, true), pg_catalog.set_config('talli.verified_actor_claims', $2, true)",
        [ownerId, JSON.stringify({
          sub: ownerId,
          aal: "aal2",
          amr: [{ method: "totp", timestamp: Date.now() / 1000 }],
        })],
      );
      await client.query(
        String.raw`insert into billing.billing_command_receipts (
          idempotency_key, company_id, operation, request_fingerprint, result, created_by
        ) values (
          'billing-rollback-receipt-00000001', $1::uuid, 'configure_account',
          repeat('a', 64), '{"pricingPlan":"founder"}'::jsonb, $2::uuid
        ) on conflict (idempotency_key) do nothing`,
        [companyId, ownerId],
      );
      await client.query("commit");
    } catch (error) {
      await client.query("rollback");
      throw error;
    }
  } finally {
    await revokeBillingStoreRole(client);
  }
}

async function assertTenantBoundaryAndReadiness(client) {
  await client.query(String.raw`
    do $grant_test_role$
    begin
      execute pg_catalog.format('grant billing_executor to %I', current_user);
    end
    $grant_test_role$;
  `);
  await client.query("begin");
  try {
    await client.query("set local role billing_executor");
    await client.query(
      "select pg_catalog.set_config('talli.verified_actor_id', $1, true), pg_catalog.set_config('talli.verified_actor_claims', $2, true)",
      [ownerId, JSON.stringify({ sub: ownerId, aal: "aal2" })],
    );
    const owner = await client.query(
      "select count(*)::int as count, billing.read_legacy_filing_readiness_v1($1::uuid, 2025, 'aksjonaerregisteroppgaven') as ready from billing.billing_accounts where company_id=$1::uuid",
      [companyId],
    );
    assert.deepEqual(owner.rows, [{ count: 1, ready: true }]);
  } finally {
    await client.query("rollback");
  }

  await client.query("begin");
  try {
    await client.query("set local role billing_executor");
    await client.query(
      "select pg_catalog.set_config('talli.verified_actor_id', $1, true), pg_catalog.set_config('talli.verified_actor_claims', $2, true)",
      [outsiderId, JSON.stringify({ sub: outsiderId, aal: "aal2" })],
    );
    const outsider = await client.query(
      "select count(*)::int as count from billing.billing_accounts where company_id=$1::uuid",
      [companyId],
    );
    assert.deepEqual(outsider.rows, [{ count: 0 }]);
  } finally {
    await client.query("rollback");
  }
  await client.query(String.raw`
    do $revoke_test_role$
    begin
      execute pg_catalog.format('revoke billing_executor from %I', current_user);
    end
    $revoke_test_role$;
  `);
}

async function assertPredecessorPilotWriter(client) {
  const boundary = await client.query(String.raw`
    select
      pg_catalog.to_regprocedure(
        'public.manage_production_pilot_entitlement(uuid,uuid,uuid,integer,text,boolean,uuid,timestamptz,timestamptz,text)'
      ) is not null as writer_exists,
      pg_catalog.has_function_privilege(
        'authenticated',
        'public.manage_production_pilot_entitlement(uuid,uuid,uuid,integer,text,boolean,uuid,timestamptz,timestamptz,text)',
        'execute'
      ) as authenticated_can_execute
  `);
  assert.deepEqual(boundary.rows, [{
    writer_exists: true,
    authenticated_can_execute: true,
  }]);
  await client.query("begin");
  try {
    await client.query("set local role authenticated");
    await client.query(
      "select pg_catalog.set_config('request.jwt.claims', $1, true)",
      [JSON.stringify({ sub: ownerId, role: "authenticated", aal: "aal2" })],
    );
    const result = await client.query(
      String.raw`select (public.manage_production_pilot_entitlement(
        $1::uuid, $2::uuid, $3::uuid, 2025, 'pending', false, $4::uuid,
        '2026-09-01T00:00:00Z'::timestamptz,
        '2026-10-01T00:00:00Z'::timestamptz,
        'rollback-writer-rehearsal'
      )).*`,
      [null, companyId, ownerId, systemUserRequestId],
    );
    assert.equal(result.rows.length, 1);
  } finally {
    await client.query("rollback");
  }
}

test(
  "billing expansion, RLS, rollback, contract, and recutover are repeatable twice",
  { skip: !databaseUrl && "DATABASE_URL is required", timeout: 180_000 },
  async () => {
    const [expand, expandRollback, contract, contractRollback, reconcile, reconcileRollback] = await Promise.all([
      readFile(new URL("../supabase/migrations/20260905010000_billing_capability.sql", import.meta.url), "utf8"),
      readFile(new URL("../supabase/rollback/20260905010000_billing_capability.sql", import.meta.url), "utf8"),
      readFile(new URL("../supabase/contract-migrations/20260905013000_billing_contract.sql", import.meta.url), "utf8"),
      readFile(new URL("../supabase/rollback/20260905013000_billing_contract.sql", import.meta.url), "utf8"),
      readFile(new URL("../supabase/migrations/20260905061339_billing_provider_reconciliation.sql", import.meta.url), "utf8"),
      readFile(new URL("../supabase/rollback/20260905061339_billing_provider_reconciliation.sql", import.meta.url), "utf8"),
    ]);
    const [cancellation, cancellationRollback, annual, annualRollback, basis, basisRollback] = await Promise.all([
      readFile(new URL("../supabase/migrations/20260905100130_annual_renewal_cancellation.sql", import.meta.url), "utf8"),
      readFile(new URL("../supabase/rollback/20260905100130_annual_renewal_cancellation.sql", import.meta.url), "utf8"),
      readFile(new URL("../supabase/migrations/20260905083150_annual_billing_purchase_ledger.sql", import.meta.url), "utf8"),
      readFile(new URL("../supabase/rollback/20260905083150_annual_billing_purchase_ledger.sql", import.meta.url), "utf8"),
      readFile(new URL("../supabase/migrations/20260905080550_annual_billing_purchase_basis.sql", import.meta.url), "utf8"),
      readFile(new URL("../supabase/rollback/20260905080550_annual_billing_purchase_basis.sql", import.meta.url), "utf8"),
    ]);
    const client = new Client({ connectionString: databaseUrl });
    await client.connect();
    try {
      assert.deepEqual(await topology(client), {
        billing_schema: true,
        canonical_accounts: true,
        canonical_events: true,
        canonical_pilots: true,
        public_accounts: true,
        public_events: true,
        public_pilots: true,
        public_accounts_kind: "v",
        canonical_accounts_kind: "r",
        accounts_force_rls: true,
        accounts_owner: "billing_store_owner",
      });

      await client.query(String.raw`
        insert into auth.users (id, email) values
          ('${ownerId}', 'billing-owner@example.test'),
          ('${outsiderId}', 'billing-outsider@example.test')
        on conflict (id) do nothing;
        insert into public.companies (
          id, org_number, name, entity_type, address, postal_code, city,
          status_text, source, created_by, identity_confirmed_at, identity_locked_at
        ) values (
          '${companyId}', '730000003', 'Billing Rehearsal AS', 'AS', 'Testveien 1',
          '0150', 'Oslo', 'Active', 'test', '${ownerId}', now(), now()
        ) on conflict (id) do nothing;
        insert into public.company_memberships (company_id, user_id, role, accepted_at)
        values ('${companyId}', '${ownerId}', 'owner', now())
        on conflict (company_id, user_id) do nothing;
        insert into public.support_operators (user_id, role, active)
        values ('${ownerId}', 'admin', true)
        on conflict (user_id) do update set role='admin', active=true;
        insert into public.system_user_requests (
          id, company_id, initiating_owner_user_id, obligation, external_ref,
          status, preflight_verified_at, accepted_at
        ) values (
          '${systemUserRequestId}', '${companyId}', '${ownerId}',
          'aksjonaerregisteroppgaven',
          'AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA',
          'accepted', now(), now()
        ) on conflict (id) do update set status='accepted',
          preflight_verified_at=now(), accepted_at=now();
        insert into billing.billing_accounts (
          company_id, pricing_plan, monthly_nok, filing_package_nok,
          founder_cohort_number, subscription_active, filing_package_paid,
          supported_case, refund_eligible, refund_completed, updated_by
        ) values (
          '${companyId}', 'founder', 29, 299, 1, true, false, true, false, false,
          '${ownerId}'
        ) on conflict (company_id) do nothing;
        insert into public.filing_readiness_snapshots (
          company_id, income_year, obligation, status, ready, hard_blocks,
          warnings, accepted_warnings, created_by
        ) values (
          '${companyId}', 2025, 'aksjonaerregisteroppgaven', 'ready', true,
          '[]'::jsonb, '[]'::jsonb, '[]'::jsonb, '${ownerId}'
        ) on conflict (company_id, income_year, obligation) do update set ready=true,
          status='ready', hard_blocks='[]'::jsonb;
      `);
      await client.query(`
        insert into billing.billing_payment_events (
          company_id, provider, provider_reference, idempotency_key, kind,
          status, amount_nok, income_year, payload, created_by
        ) values (
          '${companyId}', 'simulation', 'intent_billing-rollback-pending-00000001',
          'billing-rollback-pending-00000001', 'filing_package', 'created', 299,
          2025, '{"obligation":"aksjonaerregisteroppgaven"}'::jsonb, '${ownerId}'
        )
      `);
      await seedCommandReceipt(client);
      const evidence = await canonicalEvidence(client);
      const commandReceipt = await commandReceiptEvidence(client);
      await assertTenantBoundaryAndReadiness(client);

      for (let rehearsal = 0; rehearsal < 2; rehearsal += 1) {
        await client.query(cancellationRollback);
        await client.query(annualRollback);
        await client.query(basisRollback);
        await client.query(reconcileRollback);
        await client.query(expandRollback);
        const predecessor = await topology(client);
        assert.equal(predecessor.billing_schema, false);
        assert.equal(predecessor.public_accounts, true);
        assert.equal(predecessor.public_accounts_kind, "r");
        const quarantinedReceipt = await client.query(String.raw`
          select pg_catalog.to_regclass(
            'backend_system.billing_command_receipts'
          ) is not null as exists
        `);
        assert.deepEqual(quarantinedReceipt.rows, [{ exists: true }]);

        await client.query(expand);
        await client.query(reconcile);
        await client.query(basis);
        await client.query(annual);
        await client.query(cancellation);
        const successor = await topology(client);
        assert.equal(successor.billing_schema, true);
        assert.equal(successor.canonical_accounts, true);
        assert.equal(successor.public_accounts_kind, "v");
        assert.equal(successor.accounts_force_rls, true);
        assert.deepEqual(await canonicalEvidence(client), evidence);
        assert.deepEqual(await commandReceiptEvidence(client), commandReceipt);
        await assertTenantBoundaryAndReadiness(client);
      }

      for (let rehearsal = 0; rehearsal < 2; rehearsal += 1) {
        await client.query(contract);
        const cutover = await topology(client);
        assert.equal(cutover.public_accounts, false);
        assert.equal(cutover.public_events, false);
        assert.equal(cutover.public_pilots, false);
        assert.deepEqual(await canonicalEvidence(client), evidence);

        await client.query(contractRollback);
        const rollback = await topology(client);
        assert.equal(rollback.public_accounts_kind, "v");
        assert.deepEqual(await canonicalEvidence(client), evidence);
        await assertPredecessorPilotWriter(client);
      }

      await client.query(contract);
      const finalState = await topology(client);
      assert.equal(finalState.public_accounts, false);
      assert.equal(finalState.canonical_accounts, true);
      assert.deepEqual(await canonicalEvidence(client), evidence);
    } finally {
      await client.end();
    }
  },
);
