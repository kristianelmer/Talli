import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { randomUUID } from "node:crypto";
import { fileURLToPath } from "node:url";
import test from "node:test";

const repositoryRoot = fileURLToPath(new URL("..", import.meta.url));

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
create table storage.buckets (id text primary key, name text not null, public boolean not null default false, file_size_limit bigint, allowed_mime_types text[]);
create table storage.objects (id uuid primary key default gen_random_uuid(), bucket_id text not null references storage.buckets(id), name text not null, owner uuid, created_at timestamptz not null default now(), unique (bucket_id, name));
create or replace function storage.foldername(name text) returns text[] language sql immutable as $$ select string_to_array(name, '/'); $$;
grant usage on schema storage to authenticated, anon, service_role;
grant select, insert on storage.objects to authenticated;
`;

function docker(args, options = {}) {
  return spawnSync("docker", args, { encoding: "utf8", maxBuffer: 20 * 1024 * 1024, ...options });
}

function psql(containerName, args = [], input) {
  const result = docker([
    "exec", "-i", containerName, "psql", "-v", "ON_ERROR_STOP=1", "-U", "postgres", "-d", "talli_test", ...args,
  ], { input });
  assert.equal(result.status, 0, `${result.stdout}\n${result.stderr}`);
  return result.stdout;
}

test("company access RLS isolates tenants and exposes exact membership roles to owner policy", { timeout: 120_000 }, () => {
  const dockerInfo = docker(["info", "--format", "{{.ServerVersion}}"]).status;
  assert.equal(dockerInfo, 0, "Docker is required for the mandatory company-access PostgreSQL rehearsal");

  const containerName = `talli-company-access-${process.pid}-${randomUUID().slice(0, 8)}`;
  try {
    const started = docker([
      "run", "--rm", "--detach", "--name", containerName,
      "--env", "POSTGRES_PASSWORD=postgres", "--env", "POSTGRES_DB=talli_test",
      "--volume", `${repositoryRoot}:/repo:ro`, "postgres:16-alpine",
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
    psql(containerName, ["--file", "/repo/supabase/migrations/0001_authenticated_workspace.sql"]);
    const output = psql(containerName, [], String.raw`
      insert into auth.users (id, email) values
        ('00000000-0000-0000-0000-000000000001', 'creator@example.test'),
        ('00000000-0000-0000-0000-000000000011', 'member@example.test'),
        ('00000000-0000-0000-0000-000000000022', 'other@example.test'),
        ('00000000-0000-0000-0000-000000000033', 'outsider@example.test'),
        ('00000000-0000-0000-0000-000000000044', 'reviewer@example.test'),
        ('00000000-0000-0000-0000-000000000055', 'read-only@example.test');
      insert into public.companies (id, org_number, name, entity_type, address, postal_code, city, status_text, source, created_by) values
        ('10000000-0000-0000-0000-000000000001', '314159265', 'Member AS', 'AS', 'One', '0150', 'Oslo', 'Active', 'test', '00000000-0000-0000-0000-000000000001'),
        ('20000000-0000-0000-0000-000000000002', '271828182', 'Other AS', 'AS', 'Two', '5003', 'Bergen', 'Active', 'test', '00000000-0000-0000-0000-000000000001');
      insert into public.company_memberships (company_id, user_id, role, accepted_at) values
        ('10000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000011', 'owner', now()),
        ('20000000-0000-0000-0000-000000000002', '00000000-0000-0000-0000-000000000022', 'owner', now()),
        ('10000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000044', 'reviewer', now()),
        ('10000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000055', 'read_only', now());
      set role authenticated;
      select set_config('request.jwt.claim.sub', '00000000-0000-0000-0000-000000000011', false);
      do $$ begin
        if (select array_agg(id order by id) from public.companies) != array['10000000-0000-0000-0000-000000000001'::uuid] then raise exception 'member received a cross-company row'; end if;
        if (select array_agg(company_id order by company_id) from public.company_memberships) != array['10000000-0000-0000-0000-000000000001'::uuid] then raise exception 'member received another membership'; end if;
      end $$;
      select set_config('request.jwt.claim.sub', '00000000-0000-0000-0000-000000000044', false);
      do $$ begin
        if (select role from public.company_memberships) != 'reviewer' then raise exception 'reviewer role was not preserved through RLS'; end if;
      end $$;
      select set_config('request.jwt.claim.sub', '00000000-0000-0000-0000-000000000055', false);
      do $$ begin
        if (select role from public.company_memberships) != 'read_only' then raise exception 'read-only role was not preserved through RLS'; end if;
      end $$;
      select set_config('request.jwt.claim.sub', '00000000-0000-0000-0000-000000000033', false);
      do $$ begin
        if exists (select 1 from public.companies) then raise exception 'outsider received company rows'; end if;
        if exists (select 1 from public.company_memberships) then raise exception 'outsider received membership rows'; end if;
      end $$;
      reset role;
      select 'company_access_rls_ok';
    `);
    assert.match(output, /company_access_rls_ok/);
  } finally {
    docker(["rm", "--force", containerName]);
  }
});
