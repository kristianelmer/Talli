import assert from "node:assert/strict";
import { existsSync } from "node:fs";
import { spawnSync } from "node:child_process";
import { randomUUID } from "node:crypto";
import { fileURLToPath } from "node:url";
import test from "node:test";

const repositoryRoot = fileURLToPath(new URL("..", import.meta.url));
const migration = "/repo/supabase/migrations/20260829074916_validation_observation_authority.sql";
const localMigration = new URL(
  "../supabase/migrations/20260829074916_validation_observation_authority.sql",
  import.meta.url,
);
const dockerHost = process.env.TALLI_DOCKER_HOST;
const runId = "V2P8-20260829-LOCAL";
const entitlementId = "10000000-0000-4000-8000-000000000001";
const observationId = "20000000-0000-4000-8000-000000000002";
const reviewerId = "30000000-0000-4000-8000-000000000003";
const releaseSha = "a".repeat(64);
const noticeSha = "b".repeat(64);
const subjectSha = "c".repeat(64);

const bootstrapSql = String.raw`
create role anon nologin;
create role authenticated nologin;
create role service_role nologin bypassrls;
create role ledger_store_owner nologin noinherit nobypassrls;
create schema backend_system authorization ledger_store_owner;
`;

function docker(args, options = {}) {
  return spawnSync("docker", [...(dockerHost ? ["--host", dockerHost] : []), ...args], {
    encoding: "utf8",
    maxBuffer: 20 * 1024 * 1024,
    ...options,
  });
}

function psql(containerName, input, args = []) {
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

function scalar(containerName, sql) {
  return psql(containerName, sql, ["-Atq"]).trim().split("\n").at(-1);
}

function recordSql({
  id = observationId,
  entitlement = entitlementId,
  run = runId,
  release = releaseSha,
  notice = noticeSha,
  subject = subjectSha,
  task = "company_year_admission",
  state = "completed",
} = {}) {
  return String.raw`
begin;
set local role validation_observation_writer_executor;
select backend_system.record_validation_observation_v1(
  '${id}', '${entitlement}', '${run}', '${release}', '${notice}', '${subject}',
  '${task}', '${state}', 'onboarding', 'none', 1200,
  'none', 0, 0, 'none', 'not_required', 'not_applicable'
);
commit;
`;
}

test("pilot observation is database-authoritative, bounded, private, revocable, and launch-off provable", { timeout: 180_000 }, () => {
  assert.equal(existsSync(localMigration), true);
  assert.equal(docker(["info", "--format", "{{.ServerVersion}}"]).status, 0);
  const containerName = `talli-validation-${process.pid}-${randomUUID().slice(0, 8)}`;

  try {
    const started = docker([
      "run", "--rm", "--detach", "--name", containerName,
      "--env", "POSTGRES_PASSWORD=postgres", "--env", "POSTGRES_DB=talli_test",
      "--publish", "127.0.0.1::5432",
      "--volume", `${repositoryRoot}:/repo:ro`, "postgres:17-alpine",
    ]);
    assert.equal(started.status, 0, started.stderr);

    let ready = false;
    for (let attempt = 0; attempt < 80; attempt += 1) {
      ready = docker([
        "exec", containerName, "psql", "-U", "postgres", "-d", "talli_test",
        "-Atq", "-c", "select 1",
      ]).status === 0;
      if (ready) break;
      Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, 250);
    }
    assert.equal(ready, true, "PostgreSQL container did not become ready");
    psql(containerName, bootstrapSql);
    psql(containerName, undefined, ["--file", migration]);

    assert.equal(scalar(containerName, String.raw`
      select string_agg(
        rolname || ':' || rolcanlogin::text || ':' || rolinherit::text || ':' || rolbypassrls::text,
        ',' order by rolname
      ) from pg_catalog.pg_roles where rolname like 'validation_observation_%';
    `), [
      "validation_observation_gate_executor:false:false:false",
      "validation_observation_maintenance_executor:false:false:false",
      "validation_observation_provisioner_executor:false:false:false",
      "validation_observation_reviewer_executor:false:false:false",
      "validation_observation_store_owner:false:false:false",
      "validation_observation_writer_executor:false:false:false",
    ].join(","));

    assert.equal(scalar(containerName, String.raw`
      select string_agg(c.relname || ':' || c.relrowsecurity::text || ':' || c.relforcerowsecurity::text, ',' order by c.relname)
      from pg_catalog.pg_class c
      join pg_catalog.pg_namespace n on n.oid = c.relnamespace
      where n.nspname = 'backend_system' and c.relname in (
        'validation_observation_control', 'validation_runs',
        'validation_pilot_entitlements', 'validation_observations',
        'validation_reviewers'
      );
    `), [
      "validation_observation_control:true:true",
      "validation_observations:true:true",
      "validation_pilot_entitlements:true:true",
      "validation_reviewers:true:true",
      "validation_runs:true:true",
    ].join(","));

    for (const role of [
      "anon", "authenticated", "service_role",
      "validation_observation_writer_executor",
      "validation_observation_reviewer_executor",
    ]) {
      const denied = psqlFailure(containerName, String.raw`
        set role ${role}; select * from backend_system.validation_observations;
      `);
      assert.notEqual(denied.status, 0, `${role} unexpectedly read observations`);
      assert.match(denied.stderr, /permission denied/u);
    }

    assert.equal(scalar(containerName, String.raw`
      begin; set local role validation_observation_gate_executor;
      select backend_system.validation_observation_launch_status_v1()->>'ready_for_full_launch';
      commit;
    `), "true");

    const offFailure = psqlFailure(containerName, recordSql());
    assert.notEqual(offFailure.status, 0);
    assert.match(offFailure.stderr, /validation_observation_mode_off/u);

    psql(containerName, String.raw`
      begin;
      set local role validation_observation_provisioner_executor;
      select backend_system.provision_validation_run_v1(
        '${runId}', '${releaseSha}', 'pilot-information-v1', '${noticeSha}',
        pg_catalog.clock_timestamp() - interval '1 hour',
        pg_catalog.clock_timestamp() + interval '2 days',
        30, '${reviewerId}'
      );
      select backend_system.provision_validation_entitlement_v1(
        '${entitlementId}', '${runId}', 'V-01', '${subjectSha}',
        pg_catalog.clock_timestamp() - interval '30 minutes',
        pg_catalog.clock_timestamp() + interval '1 day'
      );
      select backend_system.provision_validation_reviewer_v1(
        '${runId}', '${reviewerId}',
        pg_catalog.clock_timestamp() - interval '30 minutes',
        pg_catalog.clock_timestamp() + interval '1 day'
      );
      select backend_system.set_validation_observation_mode_v1('invited-pilot');
      commit;
      create role validation_observation_test_login
        login password 'validation-test-password' noinherit nobypassrls;
      grant talli_validation_observation_backend to validation_observation_test_login;
    `);

    const publishedPort = docker(["port", containerName, "5432/tcp"]).stdout
      .trim().split(":").at(-1);
    assert.match(publishedPort, /^\d+$/u);
    const adapterTest = spawnSync(
      "uv",
      [
        "run", "--project", "apps/backend", "pytest",
        "apps/backend/tests/test_supabase_validation_observation.py", "-q",
      ],
      {
        cwd: repositoryRoot,
        encoding: "utf8",
        env: {
          ...process.env,
          TALLI_VALIDATION_OBSERVATION_TEST_DATABASE_URL:
            `postgresql://validation_observation_test_login:validation-test-password@127.0.0.1:${publishedPort}/talli_test`,
        },
      },
    );
    assert.equal(adapterTest.status, 0, `${adapterTest.stdout}\n${adapterTest.stderr}`);

    assert.equal(scalar(containerName, recordSql()), "t");
    assert.equal(scalar(containerName, recordSql()), "f", "exact replay must be idempotent");
    assert.equal(scalar(containerName, String.raw`
      select run_id || ':' || case_code || ':' || task_code || ':' || state_code
      from backend_system.validation_observations;
    `), `${runId}:V-01:company_year_admission:completed`);

    for (const [label, sql, expected] of [
      ["run", recordSql({ id: randomUUID(), run: "V2P8-20260829-FAIL" }), "authority_mismatch"],
      ["subject", recordSql({ id: randomUUID(), subject: "d".repeat(64) }), "subject_mismatch"],
      ["task", recordSql({ id: randomUUID(), task: "free_text" }), "invalid_task"],
    ]) {
      const failure = psqlFailure(containerName, sql);
      assert.notEqual(failure.status, 0, `${label} unexpectedly recorded`);
      assert.match(failure.stderr, new RegExp(`validation_observation_${expected}`, "u"));
    }

    assert.equal(scalar(containerName, String.raw`
      begin;
      set local role validation_observation_reviewer_executor;
      select pg_catalog.set_config('talli.verified_actor_id', '${reviewerId}', true);
      select pg_catalog.jsonb_array_length(
        backend_system.report_validation_observations_v1('${runId}')
      );
      commit;
    `), "2");

    psql(containerName, String.raw`
      begin;
      set local role validation_observation_provisioner_executor;
      select backend_system.withdraw_validation_entitlement_v1('${entitlementId}');
      select backend_system.set_validation_observation_mode_v1('off');
      commit;
    `);
    const withdrawnFailure = psqlFailure(
      containerName, recordSql({ id: randomUUID() }),
    );
    assert.notEqual(withdrawnFailure.status, 0);
    assert.match(withdrawnFailure.stderr, /validation_observation_mode_off/u);

    assert.equal(scalar(containerName, String.raw`
      begin; set local role validation_observation_gate_executor;
      select backend_system.validation_observation_launch_status_v1()->>'ready_for_full_launch';
      commit;
    `), "true");
    assert.equal(scalar(containerName, String.raw`
      begin; set local role validation_observation_gate_executor;
      select backend_system.validation_observation_launch_status_v1()->>'active_entitlements';
      commit;
    `), "0");
  } finally {
    docker(["rm", "--force", "--volumes", containerName]);
  }
});
