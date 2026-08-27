import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import pg from "pg";

const expand = readFileSync(
  new URL(
    "../supabase/migrations/20260827100000_ledger_capability.sql",
    import.meta.url,
  ),
  "utf8",
);
const coordinators = readFileSync(
  new URL(
    "../supabase/migrations/20260827100500_ledger_writer_coordinators.sql",
    import.meta.url,
  ),
  "utf8",
);
const recutoverMigrations = [
  "20260827102000_ledger_supported_patterns.sql",
  "20260827103000_ledger_corrections.sql",
  "20260827104000_ledger_company_year_close.sql",
  "20260827105000_ledger_received_dividend_lifecycle.sql",
  "20260827106000_ledger_bank_loan_lifecycle.sql",
  "20260827107000_ledger_cash_capital_increase_lifecycle.sql",
  "20260827108000_ledger_loss_coverage_capital_reduction_lifecycle.sql",
  "20260827109000_ledger_opening_position_rebuild.sql",
  "20260827109100_ledger_opening_position_acceptance.sql",
].map((name) =>
  readFileSync(new URL(`../supabase/migrations/${name}`, import.meta.url), "utf8"),
);
const contract = readFileSync(
  new URL(
    "../supabase/contract-migrations/20260827101000_ledger_capability_contract.sql",
    import.meta.url,
  ),
  "utf8",
);
const rollback = readFileSync(
  new URL(
    "../supabase/rollback/20260827101000_ledger_capability_contract.sql",
    import.meta.url,
  ),
  "utf8",
);

const ownerRoles = ["ledger_store_owner", "ledger_workflow_store_owner"];
const migrationAuthorityRoles = [
  ...ownerRoles,
  "company_access_executor",
  "company_archive_projection_executor",
];

function hasIsolatedLocalDatabase() {
  if (process.env.TALLI_LEDGER_HOSTED_AUTHORITY_REHEARSAL !== "1") return false;
  if (!process.env.DATABASE_URL) return false;
  try {
    const database = new URL(process.env.DATABASE_URL);
    return ["127.0.0.1", "localhost"].includes(database.hostname);
  } catch {
    return false;
  }
}

async function authoritySnapshot(database) {
  const memberships = await database.query(
    `
    select
      parent.rolname as owner_role,
      grantor.rolname as grantor,
      membership.admin_option,
      membership.inherit_option,
      membership.set_option
    from pg_catalog.pg_auth_members membership
    join pg_catalog.pg_roles parent on parent.oid = membership.roleid
    join pg_catalog.pg_roles member on member.oid = membership.member
    join pg_catalog.pg_roles grantor on grantor.oid = membership.grantor
    where member.rolname = current_user
      and parent.rolname = any($1::text[])
    order by parent.rolname, grantor.rolname;
  `,
    [migrationAuthorityRoles],
  );
  const schemas = await database.query(
    `
    select
      namespace.nspname as schema_name,
      pg_catalog.pg_get_userbyid(namespace.nspowner) as owner,
      pg_catalog.has_schema_privilege(
        current_user, namespace.nspname, 'CREATE'
      ) as effective_create,
      exists (
        select 1
        from pg_catalog.aclexplode(
          coalesce(namespace.nspacl, '{}'::pg_catalog.aclitem[])
        ) expanded
        join pg_catalog.pg_roles grantee on grantee.oid = expanded.grantee
        where grantee.rolname = current_user
          and expanded.privilege_type = 'CREATE'
      ) as direct_create
    from pg_catalog.pg_namespace namespace
    where namespace.nspname = any($1::text[])
    order by namespace.nspname;
  `,
    [["backend_system", "ledger"]],
  );
  return { memberships: memberships.rows, schemas: schemas.rows };
}

async function assertAuthorityClosed(database, baseline, phase) {
  const current = await authoritySnapshot(database);
  assert.deepEqual(
    current.memberships,
    baseline.memberships,
    `${phase}: migration-owner memberships must return to their exact Supabase baseline`,
  );
  assert.deepEqual(
    current.schemas,
    baseline.schemas,
    `${phase}: schema ACLs must return to their exact Supabase baseline`,
  );
  for (const schema of current.schemas) {
    assert.equal(schema.owner, "ledger_store_owner", `${phase}: ${schema.schema_name} owner`);
    assert.equal(schema.effective_create, false, `${phase}: effective migrator CREATE leaked`);
    assert.equal(schema.direct_create, false, `${phase}: direct migrator CREATE leaked`);
  }
  const legacyOwnerCreate = await database.query(`
    select pg_catalog.has_schema_privilege(
      'ledger_store_owner', 'public', 'CREATE'
    ) as can_create;
  `);
  assert.equal(
    legacyOwnerCreate.rows[0].can_create,
    false,
    `${phase}: legacy storage-owner CREATE leaked on public`,
  );

  const boundary = await database.query(
    `
    select
      role.rolname,
      role.rolsuper,
      role.rolcanlogin,
      role.rolinherit,
      role.rolbypassrls,
      case when role.rolname = any($1::text[]) then
        pg_catalog.pg_has_role(current_user, role.oid, 'USAGE')
      else false end as migrator_usage,
      case when role.rolname = any($1::text[]) then
        pg_catalog.pg_has_role(current_user, role.oid, 'SET')
      else false end as migrator_set
    from pg_catalog.pg_roles role
    where role.rolname = any($2::text[])
    order by role.rolname;
  `,
    [
      migrationAuthorityRoles,
      [
        "company_archive_projection_executor",
        "company_access_executor",
        "ledger_executor",
        "ledger_store_owner",
        "ledger_workflow_executor",
        "ledger_workflow_store_owner",
        "talli_ledger_backend",
      ],
    ],
  );
  assert.equal(boundary.rows.length, 7, `${phase}: complete role boundary`);
  for (const role of boundary.rows) {
    assert.equal(role.rolsuper, false, `${phase}: ${role.rolname} must not be superuser`);
    assert.equal(role.rolcanlogin, false, `${phase}: ${role.rolname} must remain NOLOGIN`);
    assert.equal(role.rolinherit, false, `${phase}: ${role.rolname} must remain NOINHERIT`);
    assert.equal(role.rolbypassrls, false, `${phase}: ${role.rolname} must remain NOBYPASSRLS`);
    if (migrationAuthorityRoles.includes(role.rolname)) {
      assert.equal(role.migrator_usage, false, `${phase}: usable migration membership leaked`);
      assert.equal(role.migrator_set, false, `${phase}: SET ROLE authority leaked`);
    }
  }

  const persistence = await database.query(`
    select
      namespace.nspname || '.' || class.relname as relation,
      pg_catalog.pg_get_userbyid(class.relowner) as owner,
      class.relrowsecurity,
      class.relforcerowsecurity
    from pg_catalog.pg_class class
    join pg_catalog.pg_namespace namespace on namespace.oid = class.relnamespace
    where (namespace.nspname, class.relname) in (
      ('backend_system', 'ledger_workflow_receipts'),
      ('ledger', 'cash_capital_increase_phases'),
      ('ledger', 'entries'),
      ('ledger', 'opening_position_component_sources'),
      ('ledger', 'opening_position_components'),
      ('ledger', 'opening_position_rebuilds'),
      ('ledger', 'opening_received_dividend_settlements'),
      ('ledger', 'reconstruction_evidence'),
      ('public', 'ledger_entries')
    )
      and (namespace.nspname <> 'public' or class.relkind in ('r', 'p'))
    order by relation;
  `);
  const expectedPersistence = [
    {
      relation: "backend_system.ledger_workflow_receipts",
      owner: "ledger_workflow_store_owner",
      relrowsecurity: true,
      relforcerowsecurity: true,
    },
    {
      relation: "ledger.cash_capital_increase_phases",
      owner: "ledger_store_owner",
      relrowsecurity: true,
      relforcerowsecurity: true,
    },
    {
      relation: phase === "rollback" ? "public.ledger_entries" : "ledger.entries",
      owner: "ledger_store_owner",
      relrowsecurity: true,
      relforcerowsecurity: true,
    },
    {
      relation: "ledger.reconstruction_evidence",
      owner: "ledger_store_owner",
      relrowsecurity: true,
      relforcerowsecurity: true,
    },
    {
      relation: "ledger.opening_position_component_sources",
      owner: "ledger_store_owner",
      relrowsecurity: true,
      relforcerowsecurity: true,
    },
    {
      relation: "ledger.opening_position_components",
      owner: "ledger_store_owner",
      relrowsecurity: true,
      relforcerowsecurity: true,
    },
    {
      relation: "ledger.opening_position_rebuilds",
      owner: "ledger_store_owner",
      relrowsecurity: true,
      relforcerowsecurity: true,
    },
    {
      relation: "ledger.opening_received_dividend_settlements",
      owner: "ledger_store_owner",
      relrowsecurity: true,
      relforcerowsecurity: true,
    },
  ];
  expectedPersistence.sort((left, right) => left.relation.localeCompare(right.relation));
  assert.deepEqual(
    persistence.rows,
    expectedPersistence,
    `${phase}: ownership and forced-RLS boundary`,
  );
}

test(
  "hosted non-super migrator rehearses contract, rollback, recutover, and failed authority cleanup",
  {
    skip: hasIsolatedLocalDatabase()
      ? false
      : "explicit isolated local Supabase authority rehearsal is required",
    timeout: 120_000,
  },
  async () => {
    const database = new pg.Client({ connectionString: process.env.DATABASE_URL });
    await database.connect();
    try {
      const identity = await database.query(`
        select current_user as current_user, session_user as session_user,
          current_setting('is_superuser') = 'on' as is_superuser;
      `);
      assert.equal(identity.rows[0].current_user, identity.rows[0].session_user);
      assert.equal(identity.rows[0].is_superuser, false, "rehearsal must not use a superuser");

      const baseline = await authoritySnapshot(database);
      await assertAuthorityClosed(database, baseline, "initial expand");

      await database.query("begin");
      try {
        await database.query(`
          do $failed_authority$
          begin
            execute pg_catalog.format(
              'grant ledger_store_owner, ledger_workflow_store_owner to %I', current_user
            );
            execute pg_catalog.format(
              'grant create on schema ledger, backend_system to %I', current_user
            );
          end
          $failed_authority$;
        `);
        const acquired = await database.query(`
          select pg_catalog.bool_and(
            pg_catalog.has_schema_privilege(current_user, schema_name, 'CREATE')
          ) as acquired
          from unnest(array['ledger', 'backend_system']) schema_name;
        `);
        assert.equal(acquired.rows[0].acquired, true, "failure probe must acquire direct CREATE");
        await assert.rejects(database.query("select 1 / 0"), /division by zero/iu);
      } finally {
        await database.query("rollback");
      }
      await assertAuthorityClosed(database, baseline, "injected failure");

      await database.query(contract);
      assert.equal(
        (
          await database.query(
            "select pg_catalog.to_regclass('public.ledger_entries') is null as contracted",
          )
        ).rows[0].contracted,
        true,
      );
      await assertAuthorityClosed(database, baseline, "contract");

      await database.query(rollback);
      assert.equal(
        (
          await database.query(
            "select pg_catalog.to_regclass('public.ledger_entries') is not null as rolled_back",
          )
        ).rows[0].rolled_back,
        true,
      );
      await assertAuthorityClosed(database, baseline, "rollback");

      await database.query(expand);
      await database.query(coordinators);
      await assertAuthorityClosed(database, baseline, "recutover overlap");
      for (const migration of recutoverMigrations) {
        await database.query(migration);
      }
      await assertAuthorityClosed(database, baseline, "recutover additive migrations");
      await database.query(contract);
      assert.equal(
        (
          await database.query(
            "select pg_catalog.to_regclass('public.ledger_entries') is null as recutover",
          )
        ).rows[0].recutover,
        true,
      );
      await assertAuthorityClosed(database, baseline, "recutover");
      const archiveTrigger = await database.query(`
        select pg_catalog.count(*)::integer as trigger_count,
          pg_catalog.bool_and(trigger.tgenabled in ('O', 'A')) as enabled
        from pg_catalog.pg_trigger trigger
        where trigger.tgrelid = 'ledger.entries'::pg_catalog.regclass
          and trigger.tgfoid = pg_catalog.to_regprocedure(
            'public.company_archive_track_source_write_v1()'
          )
          and not trigger.tgisinternal;
      `);
      assert.deepEqual(archiveTrigger.rows[0], { trigger_count: 1, enabled: true });
    } finally {
      await database.end();
    }
  },
);
