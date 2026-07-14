import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { randomUUID } from "node:crypto";
import { fileURLToPath } from "node:url";
import test from "node:test";

const repositoryRoot = fileURLToPath(new URL("..", import.meta.url));
const migrationFiles = [
  "0001_authenticated_workspace.sql",
  "0002_fifo_investment_lots.sql",
  "0003_bank_rule_suggestions.sql",
  "0004_corporate_document_artifacts.sql",
];

const bootstrapSql = String.raw`
create role anon nologin;
create role authenticated nologin;
create role service_role nologin bypassrls;
create schema auth;
create table auth.users (id uuid primary key, email text);
create or replace function auth.uid() returns uuid language sql stable as $$
  select nullif(current_setting('request.jwt.claim.sub', true), '')::uuid;
$$;
create or replace function auth.jwt() returns jsonb language sql stable as $$
  select coalesce(nullif(current_setting('request.jwt.claims', true), '')::jsonb, '{}'::jsonb);
$$;
grant usage on schema auth to authenticated, anon, service_role;
grant execute on function auth.uid() to authenticated, anon, service_role;
grant execute on function auth.jwt() to authenticated, anon, service_role;
create schema storage;
create table storage.buckets (
  id text primary key,
  name text not null,
  public boolean not null default false,
  file_size_limit bigint,
  allowed_mime_types text[]
);
create table storage.objects (
  id uuid primary key default gen_random_uuid(),
  bucket_id text not null references storage.buckets(id),
  name text not null,
  owner uuid,
  created_at timestamptz not null default now(),
  unique (bucket_id, name)
);
create or replace function storage.foldername(name text) returns text[] language sql immutable as $$
  select string_to_array(name, '/');
$$;
grant usage on schema storage to authenticated, anon, service_role;
grant select, insert on storage.objects to authenticated;
`;

function docker(args, options = {}) {
  return spawnSync("docker", args, {
    encoding: "utf8",
    maxBuffer: 20 * 1024 * 1024,
    ...options,
  });
}

function psql(containerName, args = [], input) {
  const result = docker(
    [
      "exec",
      "-i",
      containerName,
      "psql",
      "-v",
      "ON_ERROR_STOP=1",
      "-U",
      "postgres",
      "-d",
      "talli_test",
      ...args,
    ],
    { input },
  );
  assert.equal(result.status, 0, `${result.stdout}\n${result.stderr}`);
  return result.stdout;
}

test("corporate lifecycle RPCs pass a fresh PostgreSQL rehearsal", { timeout: 120_000 }, (t) => {
  const dockerInfo = docker(["info", "--format", "{{.ServerVersion}}"]).status;
  if (dockerInfo !== 0) {
    t.skip("Docker daemon is required for the fresh PostgreSQL rehearsal");
    return;
  }

  const containerName = `talli-corporate-${process.pid}-${randomUUID().slice(0, 8)}`;
  try {
    const started = docker([
      "run",
      "--rm",
      "--detach",
      "--name",
      containerName,
      "--env",
      "POSTGRES_PASSWORD=postgres",
      "--env",
      "POSTGRES_DB=talli_test",
      "--volume",
      `${repositoryRoot}:/repo:ro`,
      "postgres:16-alpine",
    ]);
    assert.equal(started.status, 0, started.stderr);

    let readyChecks = 0;
    for (let attempt = 0; attempt < 40; attempt += 1) {
      if (docker(["exec", containerName, "pg_isready", "-U", "postgres", "-d", "talli_test"]).status === 0) {
        readyChecks += 1;
        if (readyChecks === 2) break;
      } else {
        readyChecks = 0;
      }
      Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, 250);
    }
    assert.equal(readyChecks, 2, "PostgreSQL container did not become ready");

    psql(containerName, [], bootstrapSql);
    for (const migration of migrationFiles) {
      psql(containerName, ["--file", `/repo/supabase/migrations/${migration}`]);
    }
    const output = psql(
      containerName,
      ["--file", "/repo/tests/fixtures/corporate_documents/database_rehearsal.sql"],
    );
    assert.match(output, /database_rehearsal_ok/);
  } finally {
    docker(["rm", "--force", containerName]);
  }
});
