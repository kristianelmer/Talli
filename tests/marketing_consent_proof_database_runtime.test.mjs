import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { randomUUID } from "node:crypto";
import { fileURLToPath } from "node:url";
import test from "node:test";

const root = fileURLToPath(new URL("..", import.meta.url));
const dockerHost = process.env.TALLI_DOCKER_HOST;
const operatorId = "00000000-0000-4000-8000-000000000011";
const approverId = "00000000-0000-4000-8000-000000000012";
const firstLayerSha = "a".repeat(64);
const privacySha = "b".repeat(64);
const releaseSha = "c".repeat(64);

function docker(args, options = {}) {
  return spawnSync("docker", [...(dockerHost ? ["--host", dockerHost] : []), ...args], {
    encoding: "utf8", maxBuffer: 20 * 1024 * 1024, ...options,
  });
}

function psql(container, input, args = []) {
  const result = docker([
    "exec", "-i", container, "psql", "-v", "ON_ERROR_STOP=1",
    "-U", "postgres", "-d", "talli_test", ...args,
  ], { input });
  assert.equal(result.status, 0, `${result.stdout}\n${result.stderr}`);
  return result.stdout;
}

function failure(container, input) {
  return docker([
    "exec", "-i", container, "psql", "-v", "ON_ERROR_STOP=1",
    "-U", "postgres", "-d", "talli_test",
  ], { input });
}

function scalar(container, input) {
  return psql(container, input, ["-Atq"]).trim().split("\n").at(-1);
}

function record({
  session = "1".repeat(64),
  event = "provisional_clarify",
  reason = "'missing_required_facts'",
  id = randomUUID(),
  first = firstLayerSha,
  privacy = privacySha,
  release = releaseSha,
} = {}) {
  return String.raw`
begin; set local role marketing_measurement_ingest_executor;
select backend_system.record_marketing_funnel_event_v2(
  '${id}', '${session}', 'marketing-analytics-v1',
  'candidate-2026-08-29', '${first}',
  '2026-08-29-candidate', '${privacy}', '${release}',
  '${event}', ${reason}, 'eligibility', 'direct'
);
commit;
`;
}

test("marketing collection requires durable server-stamped approved notice proof and five distinct sessions", { timeout: 180_000 }, () => {
  assert.equal(docker(["info", "--format", "{{.ServerVersion}}"]).status, 0);
  const container = `talli-consent-${process.pid}-${randomUUID().slice(0, 8)}`;
  try {
    const started = docker([
      "run", "--rm", "--detach", "--name", container,
      "--env", "POSTGRES_PASSWORD=postgres", "--env", "POSTGRES_DB=talli_test",
      "--publish", "127.0.0.1::5432",
      "--volume", `${root}:/repo:ro`, "postgres:17-alpine",
    ]);
    assert.equal(started.status, 0, started.stderr);
    let ready = false;
    for (let i = 0; i < 80; i += 1) {
      ready = docker([
        "exec", container, "psql", "-U", "postgres", "-d", "talli_test",
        "-Atq", "-c", "select 1",
      ]).status === 0;
      if (ready) break;
      Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, 250);
    }
    assert.equal(ready, true);
    psql(container, String.raw`
      create role anon nologin;
      create role authenticated nologin;
      create role service_role nologin bypassrls;
      create role ledger_store_owner nologin noinherit nobypassrls;
      create schema backend_system authorization ledger_store_owner;
      create schema extensions;
      create extension pgcrypto with schema extensions;
      create schema auth;
      create or replace function auth.uid() returns uuid language sql stable as $$ select null::uuid $$;
      create table public.support_operators (user_id uuid primary key, role text, active boolean);
      insert into public.support_operators values ('${operatorId}', 'admin', true);
      create or replace function public.company_access_is_active_operator_v1()
      returns boolean language sql stable security definer set search_path = '' as $$
        select true;
      $$;
      revoke all on function public.company_access_is_active_operator_v1() from public;
    `);
    for (const migration of [
      "/repo/supabase/migrations/20260828103000_marketing_funnel_measurement.sql",
      "/repo/supabase/migrations/20260829070411_marketing_measurement_small_cell_threshold.sql",
      "/repo/supabase/migrations/20260829080345_marketing_measurement_consent_proof.sql",
    ]) psql(container, undefined, ["--file", migration]);

    const noRelease = failure(container, record());
    assert.notEqual(noRelease.status, 0);
    assert.match(noRelease.stderr, /marketing_measurement_release_required/u);

    psql(container, String.raw`
      begin; set local role marketing_measurement_provisioner_executor;
      select backend_system.provision_marketing_measurement_release_v1(
        'marketing-analytics-v1',
        'candidate-2026-08-29', '${firstLayerSha}',
        '2026-08-29-candidate', '${privacySha}', '${releaseSha}',
        pg_catalog.clock_timestamp() - interval '1 hour',
        pg_catalog.clock_timestamp() + interval '1 day',
        90, 365, '${approverId}'
      );
      commit;
      create role marketing_measurement_consent_test_login
        login password 'consent-test-password' noinherit nobypassrls;
      grant talli_marketing_measurement_backend to marketing_measurement_consent_test_login;
    `);

    const publishedPort = docker(["port", container, "5432/tcp"]).stdout
      .trim().split(":").at(-1);
    assert.match(publishedPort, /^\d+$/u);
    const adapterTest = spawnSync(
      "uv",
      [
        "run", "--project", "apps/backend", "pytest",
        "apps/backend/tests/test_supabase_marketing_measurement.py", "-q",
      ],
      {
        cwd: root,
        encoding: "utf8",
        env: {
          ...process.env,
          TALLI_MARKETING_MEASUREMENT_TEST_DATABASE_URL:
            `postgresql://marketing_measurement_consent_test_login:consent-test-password@127.0.0.1:${publishedPort}/talli_test`,
          TALLI_MARKETING_MEASUREMENT_TEST_OPERATOR_ID: operatorId,
        },
      },
    );
    assert.equal(adapterTest.status, 0, `${adapterTest.stdout}\n${adapterTest.stderr}`);

    assert.equal(scalar(container, record()), "t");
    assert.equal(scalar(container, String.raw`
      select action || ':' || consent_version || ':'
        || first_layer_notice_sha256 || ':' || privacy_notice_sha256 || ':'
        || release_sha256 || ':'
        || (expires_at = received_at + interval '30 minutes')::text
      from backend_system.marketing_consent_actions
      where anonymous_session_hash = '${"1".repeat(64)}';
    `), `grant:marketing-analytics-v1:${firstLayerSha}:${privacySha}:${releaseSha}:true`);

    const wrongNotice = failure(container, record({
      session: "2".repeat(64), first: "d".repeat(64),
    }));
    assert.notEqual(wrongNotice.status, 0);
    assert.match(wrongNotice.stderr, /marketing_measurement_release_required/u);

    for (let index = 0; index < 5; index += 1) {
      assert.equal(scalar(container, record({ id: randomUUID() })), "t");
    }
    assert.equal(scalar(container, String.raw`
      begin; set local role marketing_measurement_report_executor;
      select pg_catalog.set_config('talli.verified_actor_id', '${operatorId}', true);
      select pg_catalog.jsonb_array_length(
        backend_system.report_marketing_funnel_v2(30)->'repeated_signals'
      ); commit;
    `), "0", "five events from one session must remain suppressed");

    for (let index = 2; index <= 5; index += 1) {
      assert.equal(scalar(container, record({ session: String(index).repeat(64) })), "t");
    }
    assert.equal(scalar(container, String.raw`
      begin; set local role marketing_measurement_report_executor;
      select pg_catalog.set_config('talli.verified_actor_id', '${operatorId}', true);
      select pg_catalog.jsonb_array_length(
        backend_system.report_marketing_funnel_v2(30)->'repeated_signals'
      ); commit;
    `), "1");

    assert.equal(scalar(container, String.raw`
      begin; set local role marketing_measurement_ingest_executor;
      select backend_system.withdraw_marketing_funnel_session_v2('${"1".repeat(64)}');
      commit;
    `), "6");
    const withdrawn = failure(container, record({ id: randomUUID() }));
    assert.notEqual(withdrawn.status, 0);
    assert.match(withdrawn.stderr, /marketing_measurement_consent_withdrawn/u);

    for (const role of ["anon", "authenticated", "service_role", "marketing_measurement_ingest_executor", "marketing_measurement_report_executor"]) {
      const denied = failure(container, String.raw`
        set role ${role}; select * from backend_system.marketing_consent_actions;
      `);
      assert.notEqual(denied.status, 0);
      assert.match(denied.stderr, /permission denied/u);
    }
  } finally {
    docker(["rm", "--force", container]);
  }
});
