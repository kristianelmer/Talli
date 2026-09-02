import assert from "node:assert/strict";
import { existsSync } from "node:fs";
import { spawn, spawnSync } from "node:child_process";
import { randomUUID } from "node:crypto";
import { fileURLToPath } from "node:url";
import test from "node:test";

const repositoryRoot = fileURLToPath(new URL("..", import.meta.url));
const migration = "/repo/supabase/migrations/20260828103000_marketing_funnel_measurement.sql";
const thresholdMigration = "/repo/supabase/migrations/20260829070411_marketing_measurement_small_cell_threshold.sql";
const localMigration = new URL(
  "../supabase/migrations/20260828103000_marketing_funnel_measurement.sql",
  import.meta.url,
);
const dockerHost = process.env.TALLI_DOCKER_HOST;

const operatorId = "00000000-0000-0000-0000-000000000011";
const outsiderId = "00000000-0000-0000-0000-000000000022";
const firstSessionHash = "a".repeat(64);
const withdrawnSessionHash = "b".repeat(64);
const purchaseOnlySessionHash = "c".repeat(64);

const bootstrapSql = String.raw`
create role anon nologin;
create role authenticated nologin;
create role service_role nologin bypassrls;
create role ledger_store_owner nologin noinherit nobypassrls;
create schema backend_system authorization ledger_store_owner;
create schema extensions;
create extension pgcrypto with schema extensions;
create schema auth;
create or replace function auth.uid() returns uuid language sql stable as $$
  select nullif(current_setting('request.jwt.claim.sub', true), '')::uuid;
$$;
create table public.support_operators (
  user_id uuid primary key,
  role text not null check (role in ('support', 'admin')),
  active boolean not null default true
);
alter table public.support_operators enable row level security;
insert into public.support_operators (user_id, role, active) values
  ('${operatorId}', 'admin', true),
  ('${outsiderId}', 'support', false);
create or replace function public.company_access_is_active_operator_v1()
returns boolean
language sql
stable
security definer
set search_path = ''
as $function$
  select exists (
    select 1 from public.support_operators o
    where o.user_id = nullif(
      pg_catalog.current_setting('talli.verified_actor_id', true), ''
    )::uuid
      and o.active
  );
$function$;
revoke all on function public.company_access_is_active_operator_v1() from public;
`;

function docker(args, options = {}) {
  const host = dockerHost ? ["--host", dockerHost] : [];
  return spawnSync("docker", [...host, ...args], {
    encoding: "utf8",
    maxBuffer: 20 * 1024 * 1024,
    ...options,
  });
}

function psql(containerName, args = [], input) {
  const result = docker([
    "exec", "-i", containerName, "psql", "-v", "ON_ERROR_STOP=1",
    "-U", "postgres", "-d", "talli_test", ...args,
  ], { input });
  assert.equal(result.status, 0, `${result.stdout}\n${result.stderr}`);
  return result.stdout;
}

function psqlFailure(containerName, input) {
  return docker([
    "exec", "-i", containerName, "psql", "-v", "ON_ERROR_STOP=1",
    "-U", "postgres", "-d", "talli_test",
  ], { input });
}

function psqlAsync(containerName, input) {
  return new Promise((resolve) => {
    const child = spawn("docker", [
      ...(dockerHost ? ["--host", dockerHost] : []),
      "exec", "-i", containerName, "psql", "-v", "ON_ERROR_STOP=1",
      "-U", "postgres", "-d", "talli_test", "-Atq",
    ]);
    const stdout = [];
    const stderr = [];
    child.stdout.on("data", (chunk) => stdout.push(chunk));
    child.stderr.on("data", (chunk) => stderr.push(chunk));
    child.on("close", (status) => resolve({
      status,
      stdout: Buffer.concat(stdout).toString("utf8"),
      stderr: Buffer.concat(stderr).toString("utf8"),
    }));
    child.stdin.end(input);
  });
}

function scalar(containerName, sql) {
  return psql(containerName, ["-Atq"], sql).trim().split("\n").at(-1);
}

function recordSql({
  clientEventId,
  sessionHash = firstSessionHash,
  event = "home_view",
  reason = "null",
  surface = "homepage",
  campaignSource = "direct",
}) {
  return String.raw`
    begin;
    set local role marketing_measurement_ingest_executor;
    select backend_system.record_marketing_funnel_event_v1(
      '${clientEventId}', '${sessionHash}', 'marketing-analytics-v1',
      '${event}', ${reason}, '${surface}', '${campaignSource}'
    );
    commit;
  `;
}

test("marketing measurement is consent-bounded, private, aggregate-only, and retained briefly", { timeout: 180_000 }, async () => {
  assert.equal(existsSync(localMigration), true, "the exact reserved #196 migration must exist");
  assert.equal(
    docker(["info", "--format", "{{.ServerVersion}}"]).status,
    0,
    "Docker is required for the mandatory marketing-measurement PostgreSQL rehearsal",
  );
  const containerName = `talli-marketing-${process.pid}-${randomUUID().slice(0, 8)}`;

  try {
    const started = docker([
      "run", "--rm", "--detach", "--name", containerName,
      "--env", "POSTGRES_PASSWORD=postgres", "--env", "POSTGRES_DB=talli_test",
      "--publish", "127.0.0.1::5432",
      "--volume", `${repositoryRoot}:/repo:ro`, "postgres:17-alpine",
    ]);
    assert.equal(started.status, 0, started.stderr);

    let readyChecks = 0;
    for (let attempt = 0; attempt < 80; attempt += 1) {
      const ready = docker([
        "exec", containerName, "psql", "-U", "postgres", "-d", "talli_test",
        "-Atq", "-c", "select 1",
      ]).status === 0;
      readyChecks = ready ? readyChecks + 1 : 0;
      if (readyChecks === 2) break;
      Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, 250);
    }
    assert.equal(readyChecks, 2, "PostgreSQL container did not become ready");

    psql(containerName, [], bootstrapSql);
    psql(containerName, ["--file", migration]);
    psql(containerName, ["--file", thresholdMigration]);
    psql(containerName, [], String.raw`
      create role marketing_measurement_test_login
        login password 'measurement-test-password' noinherit nobypassrls;
      grant talli_marketing_measurement_backend to marketing_measurement_test_login;
    `);

    assert.equal(scalar(containerName, String.raw`
      select string_agg(
        rolname || ':' || rolcanlogin::text || ':' || rolinherit::text || ':' || rolbypassrls::text,
        ',' order by rolname
      )
      from pg_catalog.pg_roles
      where rolname in (
        'marketing_measurement_store_owner',
        'marketing_measurement_ingest_executor',
        'marketing_measurement_report_executor',
        'talli_marketing_measurement_backend'
      );
    `), [
      "marketing_measurement_ingest_executor:false:false:false",
      "marketing_measurement_report_executor:false:false:false",
      "marketing_measurement_store_owner:false:false:false",
      "talli_marketing_measurement_backend:false:false:false",
    ].join(","));

    assert.equal(scalar(containerName, String.raw`
      select not exists (
        select 1
        from pg_catalog.pg_auth_members membership
        join pg_catalog.pg_roles granted_role on granted_role.oid = membership.roleid
        join pg_catalog.pg_roles member_role on member_role.oid = membership.member
        where member_role.rolname = 'postgres'
          and granted_role.rolname in (
            'ledger_store_owner', 'marketing_measurement_store_owner'
          )
      );
    `), "t");

    assert.equal(scalar(containerName, String.raw`
      select c.relrowsecurity::text || ':' || c.relforcerowsecurity::text || ':' || r.rolname
      from pg_catalog.pg_class c
      join pg_catalog.pg_roles r on r.oid = c.relowner
      where c.oid = 'backend_system.marketing_funnel_events'::regclass;
    `), "true:true:marketing_measurement_store_owner");

    for (const role of ["anon", "authenticated", "service_role", "marketing_measurement_ingest_executor", "marketing_measurement_report_executor"]) {
      for (const table of ["marketing_funnel_events", "marketing_funnel_withdrawals"]) {
        const forbidden = psqlFailure(containerName, String.raw`
          set role ${role};
          select * from backend_system.${table};
        `);
        assert.notEqual(forbidden.status, 0, `${role} unexpectedly read raw ${table} rows`);
        assert.match(forbidden.stderr, /permission denied/u);
      }
    }

    const concurrentEventId = "10000000-0000-4000-8000-000000000009";
    const concurrentResults = await Promise.all([
      psqlAsync(containerName, recordSql({
        clientEventId: concurrentEventId,
        sessionHash: "d".repeat(64),
        event: "signup_start",
        surface: "signup",
      })),
      psqlAsync(containerName, recordSql({
        clientEventId: concurrentEventId,
        sessionHash: "d".repeat(64),
        event: "signup_start",
        surface: "signup",
      })),
    ]);
    assert.deepEqual(concurrentResults.map((result) => result.status), [0, 0]);
    assert.deepEqual(
      concurrentResults.map((result) => result.stdout.trim()).sort(),
      ["f", "t"],
    );

    const homeEventId = "10000000-0000-4000-8000-000000000001";
    const purchaseEventId = "10000000-0000-4000-8000-000000000002";
    const repeatedPurchaseEventId = "10000000-0000-4000-8000-000000000005";
    assert.equal(scalar(containerName, recordSql({ clientEventId: homeEventId })), "t");
    assert.equal(scalar(containerName, recordSql({ clientEventId: homeEventId })), "f");
    assert.equal(scalar(containerName, recordSql({
      clientEventId: purchaseEventId,
      event: "purchase_complete",
      surface: "checkout",
    })), "t");
    assert.equal(scalar(containerName, recordSql({
      clientEventId: repeatedPurchaseEventId,
      event: "purchase_complete",
      surface: "checkout",
    })), "t");
    assert.equal(scalar(containerName, recordSql({
      clientEventId: "10000000-0000-4000-8000-000000000006",
      sessionHash: purchaseOnlySessionHash,
      event: "purchase_complete",
      surface: "checkout",
    })), "t");

    const mismatchedReplay = psqlFailure(containerName, recordSql({
      clientEventId: homeEventId,
      event: "signup_start",
      surface: "signup",
    }));
    assert.notEqual(mismatchedReplay.status, 0);
    assert.match(mismatchedReplay.stderr, /marketing_measurement_event_id_conflict/u);

    const invalidEvent = psqlFailure(containerName, recordSql({
      clientEventId: "10000000-0000-4000-8000-000000000003",
      event: "free_text_event",
    }));
    assert.notEqual(invalidEvent.status, 0);
    assert.match(invalidEvent.stderr, /marketing_measurement_invalid_event/u);

    const invalidReason = psqlFailure(containerName, recordSql({
      clientEventId: "10000000-0000-4000-8000-000000000004",
      event: "support_contact",
      reason: "'unbounded explanation'",
      surface: "support",
    }));
    assert.notEqual(invalidReason.status, 0);
    assert.match(invalidReason.stderr, /marketing_measurement_invalid_reason/u);

    psql(containerName, [], String.raw`
      update backend_system.marketing_funnel_events
      set received_at = now() - interval '10 minutes',
        retained_until = now() - interval '10 minutes' + interval '90 days'
      where client_event_id = '${homeEventId}';
      update backend_system.marketing_funnel_events
      set received_at = now(), retained_until = now() + interval '90 days'
      where client_event_id in ('${purchaseEventId}', '${repeatedPurchaseEventId}');
    `);

    const report = JSON.parse(scalar(containerName, String.raw`
      begin;
      set local role marketing_measurement_report_executor;
      select pg_catalog.set_config('talli.verified_actor_id', '${operatorId}', true);
      select backend_system.report_marketing_funnel_v1(30);
      commit;
    `));
    assert.equal(report.counts.home_view, 1);
    assert.equal(report.counts.purchase_complete, 3);
    assert.equal(report.rates.home_to_purchase, 1);
    assert.equal(report.rates.company_year_completion, null);
    assert.equal(report.rates.refund, null);
    assert.equal(report.median_seconds.home_to_purchase, 600);
    assert.equal(report.median_seconds.company_year_completion, null);
    assert.equal(report.rates.acquisition_cost_minor, null);
    assert.deepEqual(report.repeated_signals, []);
    assert.equal(JSON.stringify(report).includes(firstSessionHash), false);
    assert.equal(JSON.stringify(report).includes(homeEventId), false);

    for (let index = 0; index < 5; index += 1) {
      assert.equal(scalar(containerName, recordSql({
        clientEventId: `40000000-0000-4000-8000-00000000000${index}`,
        sessionHash: String(index + 1).repeat(64),
        event: "support_contact",
        reason: "'eligibility_help'",
        surface: "eligibility",
      })), "t");
      const thresholdReport = JSON.parse(scalar(containerName, String.raw`
        begin;
        set local role marketing_measurement_report_executor;
        select pg_catalog.set_config('talli.verified_actor_id', '${operatorId}', true);
        select backend_system.report_marketing_funnel_v1(30);
        commit;
      `));
      assert.equal(
        thresholdReport.repeated_signals.length,
        index < 4 ? 0 : 1,
        "repeated signals must remain suppressed until five observations",
      );
    }

    const outsiderReport = psqlFailure(containerName, String.raw`
      begin;
      set local role marketing_measurement_report_executor;
      select pg_catalog.set_config('talli.verified_actor_id', '${outsiderId}', true);
      select backend_system.report_marketing_funnel_v1(30);
      commit;
    `);
    assert.notEqual(outsiderReport.status, 0);
    assert.match(outsiderReport.stderr, /marketing_measurement_operator_required/u);

    const oldSessionId = "20000000-0000-4000-8000-000000000001";
    assert.equal(scalar(containerName, recordSql({
      clientEventId: oldSessionId,
      sessionHash: withdrawnSessionHash,
    })), "t");
    psql(containerName, [], String.raw`
      update backend_system.marketing_funnel_events
      set received_at = now() - interval '31 minutes',
        retained_until = now() - interval '31 minutes' + interval '90 days'
      where client_event_id = '${oldSessionId}';
    `);
    const expiredSession = psqlFailure(containerName, recordSql({
      clientEventId: "20000000-0000-4000-8000-000000000002",
      sessionHash: withdrawnSessionHash,
      event: "eligibility_start",
      surface: "eligibility",
    }));
    assert.notEqual(expiredSession.status, 0);
    assert.match(expiredSession.stderr, /marketing_measurement_session_expired/u);

    assert.equal(scalar(containerName, String.raw`
      begin;
      set local role marketing_measurement_ingest_executor;
      select backend_system.withdraw_marketing_funnel_session_v1('${withdrawnSessionHash}');
      commit;
    `), "1");
    assert.equal(scalar(containerName, String.raw`
      begin;
      set local role marketing_measurement_ingest_executor;
      select backend_system.withdraw_marketing_funnel_session_v1('${withdrawnSessionHash}');
      commit;
    `), "0");
    assert.equal(scalar(containerName, String.raw`
      select withdrawn_until - withdrawn_at = interval '30 minutes'
      from backend_system.marketing_funnel_withdrawals
      where anonymous_session_hash = '${withdrawnSessionHash}';
    `), "t");
    assert.equal(scalar(containerName, String.raw`
      select count(*) from backend_system.marketing_funnel_events
      where anonymous_session_hash = '${withdrawnSessionHash}';
    `), "0");
    const withdrawnReplay = psqlFailure(containerName, recordSql({
      clientEventId: "20000000-0000-4000-8000-000000000003",
      sessionHash: withdrawnSessionHash,
    }));
    assert.notEqual(withdrawnReplay.status, 0);
    assert.match(withdrawnReplay.stderr, /marketing_measurement_consent_withdrawn/u);

    psql(containerName, [], String.raw`
      update backend_system.marketing_funnel_events
      set retained_until = now() - interval '1 second'
      where client_event_id = '${homeEventId}';
      begin;
      set local role marketing_measurement_ingest_executor;
      select backend_system.purge_expired_marketing_funnel_events_v1();
      commit;
    `);
    assert.equal(scalar(containerName, String.raw`
      select count(*) from backend_system.marketing_funnel_events
      where client_event_id = '${homeEventId}';
    `), "0");
  } finally {
    docker(["rm", "--force", containerName]);
  }
});
