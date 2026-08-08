import assert from "node:assert/strict";
import { spawn, spawnSync } from "node:child_process";
import { randomUUID } from "node:crypto";
import { fileURLToPath } from "node:url";
import test from "node:test";

import { deriveInvitationSideEffectId } from "../apps/web/app/lib/invitation-side-effects.ts";

const repositoryRoot = fileURLToPath(new URL("..", import.meta.url));

const bootstrapSql = String.raw`
create role anon nologin;
create role authenticated nologin;
create role service_role nologin bypassrls;
create schema extensions;
create extension pgcrypto with schema extensions;
grant usage on schema extensions to anon, authenticated, service_role;
create schema auth;
create table auth.users (id uuid primary key, email text);
create or replace function auth.uid() returns uuid language sql stable as $$
  select nullif(current_setting('request.jwt.claim.sub', true), '')::uuid;
$$;
create or replace function auth.jwt() returns jsonb language sql stable as $$
  select coalesce(nullif(current_setting('request.jwt.claims', true), '')::jsonb, '{}'::jsonb);
$$;
grant usage on schema auth to authenticated, anon, service_role;
revoke all on function auth.uid(), auth.jwt() from public;
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

function interactivePsql(containerName) {
  const child = spawn("docker", [
    "exec", "-i", containerName, "psql", "-v", "ON_ERROR_STOP=1", "-U", "postgres", "-d", "talli_test",
  ], { stdio: ["pipe", "pipe", "pipe"] });
  let stdout = "";
  let stderr = "";
  child.stdout.setEncoding("utf8");
  child.stderr.setEncoding("utf8");
  child.stdout.on("data", (chunk) => { stdout += chunk; });
  child.stderr.on("data", (chunk) => { stderr += chunk; });
  const exited = new Promise((resolve, reject) => {
    child.once("error", reject);
    child.once("exit", (code) => resolve({
      code,
      stdout: () => stdout,
      stderr: () => stderr,
    }));
  });
  return { child, exited, stdout: () => stdout, stderr: () => stderr };
}

function waitForOutput(process, pattern, timeoutMs = 10_000) {
  return new Promise((resolve, reject) => {
    const timeout = setTimeout(() => reject(new Error(
      `Timed out waiting for ${pattern}; stdout=${process.stdout()} stderr=${process.stderr()}`,
    )), timeoutMs);
    const inspect = () => {
      if (pattern.test(`${process.stdout()}\n${process.stderr()}`)) {
        clearTimeout(timeout);
        resolve();
      }
    };
    process.child.stdout.on("data", inspect);
    process.child.stderr.on("data", inspect);
    inspect();
  });
}

function waitForExit(process) {
  return process.exited.then(({ code, stdout, stderr }) => ({
    code,
    stdout: stdout(),
    stderr: stderr(),
  }));
}

test("company access RLS isolates tenants and exposes exact membership roles to owner policy", { timeout: 120_000 }, async () => {
  const dockerInfo = docker(["info", "--format", "{{.ServerVersion}}"]).status;
  assert.equal(dockerInfo, 0, "Docker is required for the mandatory company-access PostgreSQL rehearsal");

  const containerName = `talli-company-access-${process.pid}-${randomUUID().slice(0, 8)}`;
  try {
    const started = docker([
      "run", "--rm", "--detach", "--name", containerName,
      "--env", "POSTGRES_PASSWORD=postgres", "--env", "POSTGRES_DB=talli_test",
      "--volume", `${repositoryRoot}:/repo:ro`, "postgres:17",
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
    psql(containerName, [], String.raw`
      create role talli_migration_owner login noinherit createrole bypassrls;
      alter schema public owner to talli_migration_owner;
      grant usage on schema auth to talli_migration_owner with grant option;
      grant usage on schema extensions to talli_migration_owner;
      grant select, references on auth.users to talli_migration_owner;
      grant execute on function auth.uid(), auth.jwt()
        to talli_migration_owner with grant option;
      alter table public.companies owner to talli_migration_owner;
      alter table public.company_memberships owner to talli_migration_owner;
      alter table public.company_invitations owner to talli_migration_owner;
      alter table public.notification_outbox owner to talli_migration_owner;
      alter table public.audit_events owner to talli_migration_owner;
    `);
    psql(containerName, [
      "-U", "talli_migration_owner",
      "--file", "/repo/supabase/migrations/20260801090000_company_access_invitations.sql",
    ]);
    psql(containerName, [], String.raw`
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
      insert into public.company_invitations (
        id, company_id, invited_email, role, token_hash, status, expires_at, invited_by
      ) values (
        '30000000-0000-0000-0000-000000000001',
        '10000000-0000-0000-0000-000000000001',
        'outsider@example.test',
        'reviewer',
        encode(extensions.digest(convert_to('accept-token', 'UTF8'), 'sha256'), 'hex'),
        'pending',
        now() + interval '1 day',
        '00000000-0000-0000-0000-000000000011'
      );
    `);

    const overlapOutput = psql(containerName, [], String.raw`
      set role authenticated;
      select set_config('request.jwt.claim.sub', '00000000-0000-0000-0000-000000000011', false);
      select set_config('request.jwt.claims', '{"email":"member@example.test","aal":"aal2"}', false);
      insert into public.company_invitations (
        id, company_id, invited_email, role, token_hash, status, expires_at, invited_by
      ) values (
        '30000000-0000-0000-0000-000000000099',
        '10000000-0000-0000-0000-000000000001',
        'legacy@example.test', 'reviewer', repeat('a', 64), 'pending',
        now() + interval '1 day', '00000000-0000-0000-0000-000000000011'
      );
      reset role;
      select 'company_access_expand_overlap_ok';
    `);
    assert.match(overlapOutput, /company_access_expand_overlap_ok/);

    psql(containerName, [], String.raw`
      delete from public.company_invitations where id = '30000000-0000-0000-0000-000000000099';
    `);
    psql(containerName, ["--file", "/repo/supabase/contract-migrations/20260801091000_company_access_invitations_contract.sql"]);

    const output = psql(containerName, [], String.raw`
      set role authenticated;
      select set_config('request.jwt.claim.sub', '00000000-0000-0000-0000-000000000011', false);
      select set_config('request.jwt.claims', '{"email":"member@example.test","aal":"aal2"}', false);
      do $$ begin
        if (select array_agg(id order by id) from public.companies) != array['10000000-0000-0000-0000-000000000001'::uuid] then raise exception 'member received a cross-company row'; end if;
        if (select array_agg(distinct company_id order by company_id) from public.company_memberships) != array['10000000-0000-0000-0000-000000000001'::uuid] then raise exception 'owner received another company membership'; end if;
        if (select count(*) from public.company_memberships) != 3 then raise exception 'owner could not administer company memberships'; end if;
        if has_table_privilege('authenticated', 'public.company_invitations', 'INSERT') then raise exception 'contract left invitation insert grant'; end if;
        if has_column_privilege('authenticated', 'public.company_invitations', 'token_hash', 'SELECT') then raise exception 'token hash remains readable'; end if;
      end $$;

      select * from public.company_access_create_invitation(
        '40000000-0000-0000-0000-000000000001',
        '10000000-0000-0000-0000-000000000001',
        'delivery@example.test', 'reviewer',
        encode(extensions.digest(convert_to('create-token', 'UTF8'), 'sha256'), 'hex'),
        'create-token'
      );
      select * from public.company_access_create_invitation(
        '40000000-0000-0000-0000-000000000001',
        '10000000-0000-0000-0000-000000000001',
        'delivery@example.test', 'reviewer',
        encode(extensions.digest(convert_to('discarded-create-candidate', 'UTF8'), 'sha256'), 'hex'),
        'discarded-create-candidate'
      );
      do $$ declare recovered text; begin
        if (select count(*) from public.company_invitations where invited_email = 'delivery@example.test') != 1 then
          raise exception 'create replay duplicated invitation';
        end if;
        select delivery_token into recovered from public.company_access_create_invitation(
          '40000000-0000-0000-0000-000000000001',
          '10000000-0000-0000-0000-000000000001',
          'delivery@example.test', 'reviewer',
          encode(extensions.digest(convert_to('another-discarded-candidate', 'UTF8'), 'sha256'), 'hex'),
          'another-discarded-candidate'
        );
        if recovered <> 'create-token' then
          raise exception 'create receipt cannot recover delivery token';
        end if;
      end $$;

      do $$ declare invitation_id uuid; expected timestamptz; recovered text; superseded text; begin
        select id, updated_at into invitation_id, expected
        from public.company_invitations where invited_email = 'delivery@example.test';
        perform set_config('test.resend_invitation_id', invitation_id::text, false);
        perform set_config('test.resend_expected', expected::text, false);
        select delivery_token into recovered from public.company_access_resend_invitation(
          '40000000-0000-0000-0000-000000000002',
          '10000000-0000-0000-0000-000000000001', invitation_id, expected,
          encode(extensions.digest(convert_to('resend-token', 'UTF8'), 'sha256'), 'hex'), 'resend-token'
        );
        if recovered <> 'resend-token' then raise exception 'resend did not return delivery token'; end if;
        select delivery_token into recovered from public.company_access_resend_invitation(
          '40000000-0000-0000-0000-000000000002',
          '10000000-0000-0000-0000-000000000001', invitation_id, expected,
          encode(extensions.digest(convert_to('resend-token', 'UTF8'), 'sha256'), 'hex'), 'resend-token'
        );
        if recovered <> 'resend-token' then raise exception 'resend receipt cannot recover delivery token'; end if;
        select delivery_token into superseded from public.company_access_create_invitation(
          '40000000-0000-0000-0000-000000000001',
          '10000000-0000-0000-0000-000000000001', 'delivery@example.test', 'reviewer',
          encode(extensions.digest(convert_to('create-token', 'UTF8'), 'sha256'), 'hex'), 'create-token'
        );
        if superseded is not null then
          raise exception 'resend retained superseded raw token';
        end if;
      end $$;

      select * from public.company_access_create_invitation(
        '40000000-0000-0000-0000-000000000007',
        '10000000-0000-0000-0000-000000000001',
        'retained-secret@example.test', 'reviewer',
        encode(extensions.digest(convert_to('retained-token', 'UTF8'), 'sha256'), 'hex'),
        'retained-token'
      );
      select * from public.company_access_create_invitation(
        '40000000-0000-0000-0000-000000000008',
        '10000000-0000-0000-0000-000000000001',
        'revoke-replay@example.test', 'reviewer',
        encode(extensions.digest(convert_to('revoke-token', 'UTF8'), 'sha256'), 'hex'),
        'revoke-token'
      );
      do $$ declare invitation_id uuid; expected timestamptz; begin
        select id, updated_at into invitation_id, expected
        from public.company_invitations where invited_email = 'revoke-replay@example.test';
        perform set_config('test.revoke_invitation_id', invitation_id::text, false);
        perform set_config('test.revoke_expected', expected::text, false);
        perform * from public.company_access_revoke_invitation(
          '40000000-0000-0000-0000-000000000009',
          '10000000-0000-0000-0000-000000000001', invitation_id, expected
        );
      end $$;

      select set_config('request.jwt.claim.sub', '00000000-0000-0000-0000-000000000044', false);
      do $$ declare changed integer; v_membership_role text; v_membership_accepted timestamptz; begin
        begin
          update public.company_memberships set role = 'owner', accepted_at = null
          where company_id = '10000000-0000-0000-0000-000000000001'
            and user_id = '00000000-0000-0000-0000-000000000044';
          get diagnostics changed = row_count;
        exception when insufficient_privilege then
          changed := 0;
        end;
        select role, accepted_at into v_membership_role, v_membership_accepted
        from public.company_memberships
        where company_id = '10000000-0000-0000-0000-000000000001'
          and user_id = '00000000-0000-0000-0000-000000000044';
        if changed <> 0 or v_membership_role <> 'reviewer' or v_membership_accepted is null then
          raise exception 'reviewer directly promoted or cleared accepted_at: changed=%, role=%, accepted=%',
            changed, v_membership_role, v_membership_accepted;
        end if;
      end $$;
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
        if has_function_privilege('authenticated', 'public.company_access_current_identity_v1()', 'EXECUTE') then
          raise exception 'authenticated can directly execute current identity helper';
        end if;
        if has_function_privilege('authenticated', 'public.company_access_token_hash_v1(text)', 'EXECUTE') then
          raise exception 'authenticated can directly execute token hash helper';
        end if;
        if pg_catalog.to_regprocedure('public.company_access_receipt_exists_v1(uuid, uuid, text, text)') is not null
           and has_function_privilege('authenticated', 'public.company_access_receipt_exists_v1(uuid, uuid, text, text)', 'EXECUTE') then
          raise exception 'authenticated can directly execute receipt existence helper';
        end if;
      end $$;
      select set_config('request.jwt.claims', '{"email":"outsider@example.test","aal":"aal1"}', false);
      do $$ begin
        if exists (select 1 from public.company_invitations) then
          raise exception 'invitee enumerated an invitation without the token RPC';
        end if;
      end $$;
      reset role;
      update auth.users set email = 'current-outsider@example.test'
      where id = '00000000-0000-0000-0000-000000000033';
      set role authenticated;
      select set_config('request.jwt.claim.sub', '00000000-0000-0000-0000-000000000033', false);
      select set_config('request.jwt.claims', '{"email":"outsider@example.test","aal":"aal1"}', false);
      do $$ begin
        if (select count(*) from public.company_access_lookup_invitation(
          encode(extensions.digest(convert_to('accept-token', 'UTF8'), 'sha256'), 'hex'),
          '00000000-0000-0000-0000-000000000033', 'outsider@example.test'
        )) <> 0 then
          raise exception 'direct stale-JWT lookup forged current Auth identity';
        end if;
        begin
          perform * from public.company_access_accept_invitation(
            '40000000-0000-0000-0000-000000000099',
            encode(extensions.digest(convert_to('accept-token', 'UTF8'), 'sha256'), 'hex'),
            '00000000-0000-0000-0000-000000000033', 'outsider@example.test'
          );
          raise exception 'direct stale-JWT acceptance forged current Auth identity';
        exception when sqlstate 'P0001' then
          if sqlerrm <> 'invitation_not_found' then raise; end if;
        end;
      end $$;
      reset role;
      update auth.users set email = 'outsider@example.test'
      where id = '00000000-0000-0000-0000-000000000033';
      set role authenticated;
      select set_config('request.jwt.claim.sub', '00000000-0000-0000-0000-000000000033', false);
      select set_config('request.jwt.claims', '{"email":"outsider@example.test","aal":"aal1"}', false);
      do $$ begin
        if (select count(*) from public.company_access_lookup_invitation(
          encode(extensions.digest(convert_to('accept-token', 'UTF8'), 'sha256'), 'hex'),
          '00000000-0000-0000-0000-000000000033', 'outsider@example.test'
        )) != 1 then
          raise exception 'recipient could not look up pending invitation';
        end if;
      end $$;
      do $$ begin
        perform * from public.company_access_accept_invitation(
          '40000000-0000-0000-0000-000000000003',
          encode(extensions.digest(convert_to('accept-token', 'UTF8'), 'sha256'), 'hex'),
          '00000000-0000-0000-0000-000000000033', 'stale@example.test'
        );
        raise exception 'stale JWT disagreement was accepted';
      exception when sqlstate 'P0001' then
        if sqlerrm <> 'invitation_not_found' then raise; end if;
      end $$;
      select * from public.company_access_accept_invitation(
        '40000000-0000-0000-0000-000000000004',
        encode(extensions.digest(convert_to('accept-token', 'UTF8'), 'sha256'), 'hex'),
        '00000000-0000-0000-0000-000000000033', 'outsider@example.test'
      );
      select * from public.company_access_accept_invitation(
        '40000000-0000-0000-0000-000000000004',
        encode(extensions.digest(convert_to('accept-token', 'UTF8'), 'sha256'), 'hex'),
        '00000000-0000-0000-0000-000000000033', 'outsider@example.test'
      );
      do $$ begin
        if not exists (
          select 1 from public.company_memberships
          where company_id = '10000000-0000-0000-0000-000000000001'
            and user_id = '00000000-0000-0000-0000-000000000033'
            and role = 'reviewer' and accepted_at is not null
        ) then raise exception 'atomic acceptance did not create membership'; end if;
      end $$;
      select set_config('request.jwt.claim.sub', '00000000-0000-0000-0000-000000000011', false);
      select set_config('request.jwt.claims', '{"email":"member@example.test","aal":"aal2"}', false);
      select * from public.company_access_administer_membership(
        '40000000-0000-0000-0000-000000000005',
        '10000000-0000-0000-0000-000000000001',
        '00000000-0000-0000-0000-000000000033',
        'reviewer',
        'read_only',
        'active'
      );
      select * from public.company_access_administer_membership(
        '40000000-0000-0000-0000-000000000005',
        '10000000-0000-0000-0000-000000000001',
        '00000000-0000-0000-0000-000000000033',
        'reviewer', 'read_only', 'active'
      );
      do $$ begin
        if (select role from public.company_memberships where user_id = '00000000-0000-0000-0000-000000000033') != 'read_only' then
          raise exception 'membership role transition did not commit';
        end if;
      end $$;
      select * from public.company_access_administer_membership(
        '40000000-0000-0000-0000-000000000006',
        '10000000-0000-0000-0000-000000000001',
        '00000000-0000-0000-0000-000000000033',
        'read_only',
        null,
        'removed'
      );
      do $$ begin
        if exists (select 1 from public.company_memberships where user_id = '00000000-0000-0000-0000-000000000033') then
          raise exception 'membership removal did not commit';
        end if;
        if (select rolbypassrls from pg_catalog.pg_roles where rolname = 'company_access_executor') then raise exception 'executor bypasses RLS'; end if;
        if has_schema_privilege('company_access_executor', 'extensions', 'USAGE') then raise exception 'executor received broad pgcrypto schema usage'; end if;
        if exists (
          select 1 from pg_catalog.pg_class
          where oid in ('public.company_invitations'::regclass, 'public.company_memberships'::regclass)
            and relforcerowsecurity
        ) then raise exception 'business tables unexpectedly force RLS'; end if;
      end $$;
      do $$ declare changed integer; begin
        begin
          update public.company_memberships set role = 'reviewer'
          where company_id = '10000000-0000-0000-0000-000000000001'
            and user_id = '00000000-0000-0000-0000-000000000055';
          get diagnostics changed = row_count;
        exception when insufficient_privilege then
          changed := 0;
        end;
        if changed <> 0 then raise exception 'authenticated owner bypassed command RLS'; end if;
      end $$;
      select set_config('request.jwt.claim.sub', '', false);
      select set_config('request.jwt.claims', '', false);
      do $$ begin
        if public.company_access_is_accepted_owner_v1('10000000-0000-0000-0000-000000000001') then
          raise exception 'connection context leaked after claims were cleared';
        end if;
      end $$;

      select set_config('request.jwt.claim.sub', '00000000-0000-0000-0000-000000000011', false);
      select set_config('request.jwt.claims', '{"email":"member@example.test","aal":"aal1"}', false);
      do $$ declare leaked text; begin
        begin
          select delivery_token into leaked from public.company_access_create_invitation(
            '40000000-0000-0000-0000-000000000007',
            '10000000-0000-0000-0000-000000000001',
            'retained-secret@example.test', 'reviewer',
            encode(extensions.digest(convert_to('retained-token', 'UTF8'), 'sha256'), 'hex'),
            'retained-token'
          );
          raise exception 'aal1 create replay returned token %', leaked;
        exception when sqlstate 'P0001' then
          if sqlerrm <> 'company_access_not_found' then raise; end if;
        end;
        begin
          select delivery_token into leaked from public.company_access_resend_invitation(
            '40000000-0000-0000-0000-000000000002',
            '10000000-0000-0000-0000-000000000001',
            current_setting('test.resend_invitation_id')::uuid,
            current_setting('test.resend_expected')::timestamptz,
            encode(extensions.digest(convert_to('resend-token', 'UTF8'), 'sha256'), 'hex'),
            'resend-token'
          );
          raise exception 'aal1 resend replay returned token %', leaked;
        exception when sqlstate 'P0001' then
          if sqlerrm <> 'company_access_not_found' then raise; end if;
        end;
        begin
          perform * from public.company_access_revoke_invitation(
            '40000000-0000-0000-0000-000000000009',
            '10000000-0000-0000-0000-000000000001',
            current_setting('test.revoke_invitation_id')::uuid,
            current_setting('test.revoke_expected')::timestamptz
          );
          raise exception 'aal1 revoke replay returned a receipt';
        exception when sqlstate 'P0001' then
          if sqlerrm <> 'company_access_not_found' then raise; end if;
        end;
        begin
          perform * from public.company_access_administer_membership(
            '40000000-0000-0000-0000-000000000006',
            '10000000-0000-0000-0000-000000000001',
            '00000000-0000-0000-0000-000000000033',
            'read_only', null, 'removed'
          );
          raise exception 'aal1 membership replay returned a receipt';
        exception when sqlstate 'P0001' then
          if sqlerrm <> 'company_access_not_found' then raise; end if;
        end;
      end $$;

      reset role;
      delete from public.company_memberships
      where company_id = '10000000-0000-0000-0000-000000000001'
        and user_id = '00000000-0000-0000-0000-000000000011';
      set role authenticated;
      select set_config('request.jwt.claim.sub', '00000000-0000-0000-0000-000000000011', false);
      select set_config('request.jwt.claims', '{"email":"member@example.test","aal":"aal2"}', false);
      do $$ declare leaked text; begin
        begin
          select delivery_token into leaked from public.company_access_create_invitation(
            '40000000-0000-0000-0000-000000000007',
            '10000000-0000-0000-0000-000000000001',
            'retained-secret@example.test', 'reviewer',
            encode(extensions.digest(convert_to('retained-token', 'UTF8'), 'sha256'), 'hex'),
            'retained-token'
          );
          raise exception 'demoted create replay returned token %', leaked;
        exception when sqlstate 'P0001' then
          if sqlerrm <> 'company_access_not_found' then raise; end if;
        end;
        begin
          select delivery_token into leaked from public.company_access_resend_invitation(
            '40000000-0000-0000-0000-000000000002',
            '10000000-0000-0000-0000-000000000001',
            current_setting('test.resend_invitation_id')::uuid,
            current_setting('test.resend_expected')::timestamptz,
            encode(extensions.digest(convert_to('resend-token', 'UTF8'), 'sha256'), 'hex'),
            'resend-token'
          );
          raise exception 'demoted resend replay returned token %', leaked;
        exception when sqlstate 'P0001' then
          if sqlerrm <> 'company_access_not_found' then raise; end if;
        end;
      end $$;

      reset role;
      insert into public.company_memberships (company_id, user_id, role, accepted_at)
      values (
        '10000000-0000-0000-0000-000000000001',
        '00000000-0000-0000-0000-000000000011', 'owner', statement_timestamp()
      );
      set role authenticated;
      select set_config('request.jwt.claim.sub', '00000000-0000-0000-0000-000000000011', false);
      select set_config('request.jwt.claims', '{"email":"member@example.test","aal":"aal2"}', false);
      do $$ declare recovered text; begin
        select delivery_token into recovered from public.company_access_create_invitation(
          '40000000-0000-0000-0000-000000000007',
          '10000000-0000-0000-0000-000000000001',
          'retained-secret@example.test', 'reviewer',
          encode(extensions.digest(convert_to('retained-token', 'UTF8'), 'sha256'), 'hex'),
          'retained-token'
        );
        if recovered <> 'retained-token' then raise exception 'authorized create reconciliation failed'; end if;
        select delivery_token into recovered from public.company_access_resend_invitation(
          '40000000-0000-0000-0000-000000000002',
          '10000000-0000-0000-0000-000000000001',
          current_setting('test.resend_invitation_id')::uuid,
          current_setting('test.resend_expected')::timestamptz,
          encode(extensions.digest(convert_to('resend-token', 'UTF8'), 'sha256'), 'hex'),
          'resend-token'
        );
        if recovered <> 'resend-token' then raise exception 'authorized resend reconciliation failed'; end if;
      end $$;

      reset role;
      update public.company_access_command_receipts
      set expires_at = statement_timestamp() - interval '1 second'
      where operation_id = '40000000-0000-0000-0000-000000000007';
      set role authenticated;
      select set_config('request.jwt.claim.sub', '00000000-0000-0000-0000-000000000011', false);
      select set_config('request.jwt.claims', '{"email":"member@example.test","aal":"aal2"}', false);
      do $$ declare leaked text; begin
        begin
          select delivery_token into leaked from public.company_access_create_invitation(
            '40000000-0000-0000-0000-000000000007',
            '10000000-0000-0000-0000-000000000001',
            'retained-secret@example.test', 'reviewer',
            encode(extensions.digest(convert_to('retained-token', 'UTF8'), 'sha256'), 'hex'),
            'retained-token'
          );
          raise exception 'expired create receipt returned token %', leaked;
        exception when sqlstate 'P0001' then
          if sqlerrm <> 'company_access_not_found' then raise; end if;
        end;
      end $$;
      reset role;
      set role company_access_executor;
      select set_config('request.jwt.claim.sub', '00000000-0000-0000-0000-000000000033', false);
      select set_config('request.jwt.claims', '{"email":"outsider@example.test","aal":"aal2"}', false);
      do $$ declare changed integer; begin
        update public.company_invitations set status = 'revoked'
        where invited_email = 'delivery@example.test';
        get diagnostics changed = row_count;
        if changed <> 0 then raise exception 'restricted executor bypassed invitation RLS'; end if;
      end $$;
      reset role;
      select 'company_access_rls_ok';
    `);
    assert.match(output, /company_access_rls_ok/);

    psql(containerName, [], String.raw`
      set role authenticated;
      select set_config('request.jwt.claim.sub', '00000000-0000-0000-0000-000000000022', false);
      select set_config('request.jwt.claims', '{"email":"other@example.test","aal":"aal2"}', false);
      select * from public.company_access_create_invitation(
        '50000000-0000-0000-0000-000000000001',
        '20000000-0000-0000-0000-000000000002',
        'foreign-receipt@example.test', 'reviewer',
        encode(extensions.digest(convert_to('foreign-token', 'UTF8'), 'sha256'), 'hex'),
        'foreign-token'
      );
    `);
    const oracleOutput = psql(containerName, [], String.raw`
      set role authenticated;
      select set_config('request.jwt.claim.sub', '00000000-0000-0000-0000-000000000011', false);
      select set_config('request.jwt.claims', '{"email":"member@example.test","aal":"aal2"}', false);
      do $$
      declare
        v_foreign_error text;
        v_unknown_error text;
        v_invitation_count bigint;
      begin
        select count(*) into v_invitation_count from public.company_invitations
        where company_id = '10000000-0000-0000-0000-000000000001';
        begin
          perform * from public.company_access_create_invitation(
            '50000000-0000-0000-0000-000000000001',
            '10000000-0000-0000-0000-000000000001',
            'oracle-probe@example.test', 'reviewer', repeat('0', 64), 'invalid-token'
          );
        exception when sqlstate 'P0001' then
          v_foreign_error := sqlerrm;
        end;
        begin
          perform * from public.company_access_create_invitation(
            '50000000-0000-0000-0000-000000000099',
            '10000000-0000-0000-0000-000000000001',
            'oracle-probe@example.test', 'reviewer', repeat('0', 64), 'invalid-token'
          );
        exception when sqlstate 'P0001' then
          v_unknown_error := sqlerrm;
        end;
        if v_foreign_error is distinct from v_unknown_error then
          raise exception 'foreign receipt oracle: foreign=%, unknown=%', v_foreign_error, v_unknown_error;
        end if;
        if v_foreign_error <> 'company_access_invalid_request' then
          raise exception 'invalid probes were not handled identically: %', v_foreign_error;
        end if;
        if (select count(*) from public.company_invitations
            where company_id = '10000000-0000-0000-0000-000000000001') <> v_invitation_count then
          raise exception 'oracle probes mutated invitations';
        end if;
      end $$;
      select 'company_access_receipt_oracle_concealed';
    `);
    assert.match(oracleOutput, /company_access_receipt_oracle_concealed/u);
    const unknownProbeReceipts = psql(containerName, ["-Atc", String.raw`
      select count(*) from public.company_access_command_receipts
      where operation_id = '50000000-0000-0000-0000-000000000099'
    `]).trim();
    assert.equal(unknownProbeReceipts, "0", "unknown probe created a receipt");

    const validProbe = (operationId) => docker([
      "exec", "-i", containerName, "psql", "-v", "ON_ERROR_STOP=1", "-U", "postgres", "-d", "talli_test",
    ], { input: String.raw`
      begin;
      set role authenticated;
      select set_config('request.jwt.claim.sub', '00000000-0000-0000-0000-000000000011', false);
      select set_config('request.jwt.claims', '{"email":"member@example.test","aal":"aal2"}', false);
      select invited_email, role, status, delivery_token
      from public.company_access_create_invitation(
        '${operationId}',
        '10000000-0000-0000-0000-000000000001',
        'valid-oracle-probe@example.test', 'reviewer',
        encode(extensions.digest(convert_to('valid-oracle-token', 'UTF8'), 'sha256'), 'hex'),
        'valid-oracle-token'
      );
      rollback;
    ` });
    const validForeign = validProbe("50000000-0000-0000-0000-000000000001");
    const validUnknown = validProbe("50000000-0000-0000-0000-000000000098");
    assert.equal(
      validForeign.status,
      validUnknown.status,
      `valid receipt probes diverged: foreign=${validForeign.stderr} unknown=${validUnknown.stderr}`,
    );
    assert.equal(validForeign.status, 0, validForeign.stderr);
    for (const result of [validForeign, validUnknown]) {
      assert.match(result.stdout, /valid-oracle-probe@example\.test[\s\S]+reviewer[\s\S]+pending[\s\S]+valid-oracle-token/u);
    }
    const validProbeState = psql(containerName, ["-Atc", String.raw`
      select
        (select count(*) from public.company_invitations
          where company_id = '10000000-0000-0000-0000-000000000001'
            and invited_email = 'valid-oracle-probe@example.test')::text
        || ':' ||
        (select count(*) from public.company_access_command_receipts
          where actor_id = '00000000-0000-0000-0000-000000000011'
            and operation_id in (
              '50000000-0000-0000-0000-000000000001',
              '50000000-0000-0000-0000-000000000098'
            ))::text
        || ':' ||
        (select count(*) from public.company_access_command_receipts
          where actor_id = '00000000-0000-0000-0000-000000000022'
            and operation_id = '50000000-0000-0000-0000-000000000001')::text
    `]).trim();
    assert.equal(validProbeState, "0:0:1", "valid probes leaked mutation across rollback or tenant");
    const foreignCompletionOutput = psql(containerName, [], String.raw`
      set role authenticated;
      select set_config('request.jwt.claim.sub', '00000000-0000-0000-0000-000000000011', false);
      select set_config('request.jwt.claims', '{"email":"member@example.test","aal":"aal2"}', false);
      do $$ begin
        begin
          perform public.company_access_complete_invitation_side_effect(
            '50000000-0000-0000-0000-000000000001'
          );
          raise exception 'foreign receipt completion unexpectedly succeeded';
        exception when sqlstate 'P0001' then
          if sqlerrm <> 'company_access_not_found' then raise; end if;
        end;
      end $$;
      select 'foreign_completion_concealed';
    `);
    assert.match(foreignCompletionOutput, /foreign_completion_concealed/u);
    psql(containerName, [], String.raw`
      do $$ begin
        if pg_catalog.hashtextextended(
          '00000000-0000-0000-0000-000000000011|50000000-0000-0000-0000-000000000001', 160
        ) = pg_catalog.hashtextextended(
          '00000000-0000-0000-0000-000000000022|50000000-0000-0000-0000-000000000001', 160
        ) then raise exception 'test actors unexpectedly share an advisory namespace'; end if;
      end $$;
    `);

    const sharedCreateOperationId = "60000000-0000-4000-8000-000000000001";
    const sharedResendOperationId = "60000000-0000-4000-8000-000000000002";
    const actorWorkflows = [
      {
        actorId: "00000000-0000-0000-0000-000000000011",
        actorEmail: "member@example.test",
        companyId: "10000000-0000-0000-0000-000000000001",
        recipientEmail: "actor-a-side-effect@example.test",
        token: "actor-a-side-effect-token",
      },
      {
        actorId: "00000000-0000-0000-0000-000000000022",
        actorEmail: "other@example.test",
        companyId: "20000000-0000-0000-0000-000000000002",
        recipientEmail: "actor-b-side-effect@example.test",
        token: "actor-b-side-effect-token",
      },
    ];
    for (const workflow of actorWorkflows) {
      const createAuditId = deriveInvitationSideEffectId({
        actorId: workflow.actorId,
        operationId: sharedCreateOperationId,
        purpose: "create_invitation:audit",
      });
      const resendAuditId = deriveInvitationSideEffectId({
        actorId: workflow.actorId,
        operationId: sharedResendOperationId,
        purpose: "resend_invitation:audit",
      });
      const workflowOutput = psql(containerName, [], String.raw`
        set role authenticated;
        select set_config('request.jwt.claim.sub', '${workflow.actorId}', false);
        select set_config('request.jwt.claims', '{"email":"${workflow.actorEmail}","aal":"aal2"}', false);
        select * from public.company_access_create_invitation(
          '${sharedCreateOperationId}', '${workflow.companyId}', '${workflow.recipientEmail}', 'reviewer',
          encode(extensions.digest(convert_to('${workflow.token}', 'UTF8'), 'sha256'), 'hex'), '${workflow.token}'
        );
        do $$ begin
          begin
            perform public.company_access_complete_invitation_side_effect('${sharedCreateOperationId}');
            raise exception 'completion accepted missing side-effect proof';
          exception when sqlstate 'P0001' then
            if sqlerrm <> 'company_access_side_effect_pending' then raise; end if;
          end;
        end $$;
        insert into public.audit_events (id, company_id, actor_id, category, action, message)
        values (
          '${createAuditId}', '${workflow.companyId}', '${workflow.actorId}', 'review',
          'reviewer_invitation_created',
          'Reviewer/read-only invitasjon køet for reviewer. Forespørsels-ID: ${sharedCreateOperationId}.'
        );
        do $$ begin
          if not public.company_access_complete_invitation_side_effect('${sharedCreateOperationId}')
             or not public.company_access_complete_invitation_side_effect('${sharedCreateOperationId}') then
            raise exception 'create side-effect completion was not idempotent';
          end if;
        end $$;
        select * from public.company_access_resend_invitation(
          '${sharedResendOperationId}', '${workflow.companyId}',
          (select id from public.company_invitations where company_id = '${workflow.companyId}' and invited_email = '${workflow.recipientEmail}'),
          (select updated_at from public.company_invitations where company_id = '${workflow.companyId}' and invited_email = '${workflow.recipientEmail}'),
          encode(extensions.digest(convert_to('${workflow.token}-resent', 'UTF8'), 'sha256'), 'hex'),
          '${workflow.token}-resent'
        );
        insert into public.audit_events (id, company_id, actor_id, category, action, message)
        values (
          '${resendAuditId}', '${workflow.companyId}', '${workflow.actorId}', 'review',
          'reviewer_invitation_resent',
          'Reviewer/read-only invitasjon sendt på nytt. Forespørsels-ID: ${sharedResendOperationId}.'
        );
        do $$ begin
          if (select count(*) from public.company_access_pending_invitation_side_effects()
              where operation_id in ('${sharedCreateOperationId}', '${sharedResendOperationId}')) <> 1 then
            raise exception 'actor could not list the pending resend continuation';
          end if;
          if not public.company_access_complete_invitation_side_effect('${sharedResendOperationId}') then
            raise exception 'side-effect completion was not idempotent';
          end if;
          if exists (select 1 from public.company_access_pending_invitation_side_effects()
              where operation_id in ('${sharedCreateOperationId}', '${sharedResendOperationId}')) then
            raise exception 'completed continuation remained pending';
          end if;
        end $$;
        do $$ begin
          if (select count(*) from public.notification_outbox where created_by = '${workflow.actorId}') <> 2 then
            raise exception 'actor could not see both own delivery continuations';
          end if;
          if (select count(*) from public.audit_events where actor_id = '${workflow.actorId}') <> 2 then
            raise exception 'actor could not see both own audit continuations';
          end if;
          if exists (select 1 from public.notification_outbox where created_by <> '${workflow.actorId}') then
            raise exception 'actor could see a foreign delivery continuation';
          end if;
          if exists (select 1 from public.audit_events where actor_id <> '${workflow.actorId}') then
            raise exception 'actor could see foreign audit evidence';
          end if;
        end $$;
        reset role;
        select 'actor_scoped_invitation_side_effects_ok';
      `);
      assert.match(workflowOutput, /actor_scoped_invitation_side_effects_ok/u);
    }
    const persistedSideEffects = psql(containerName, ["-Atc", String.raw`
      select
        (select count(*) from public.notification_outbox
          where payload ->> 'operationId' in ('${sharedCreateOperationId}', '${sharedResendOperationId}'))::text
        || ':' ||
        (select count(*) from public.audit_events
          where message like '%${sharedCreateOperationId}%' or message like '%${sharedResendOperationId}%')::text
        || ':' ||
        (select count(distinct created_by) from public.notification_outbox
          where payload ->> 'operationId' in ('${sharedCreateOperationId}', '${sharedResendOperationId}'))::text
        || ':' ||
        (select count(distinct actor_id) from public.audit_events
          where message like '%${sharedCreateOperationId}%' or message like '%${sharedResendOperationId}%')::text
    `]).trim();
    assert.equal(persistedSideEffects, "4:4:2:2", "shared operation ids lost or merged side effects");
    const completedContinuations = psql(containerName, ["-Atc", String.raw`
      select count(*)::text || ':' ||
        count(*) filter (where delivery_token is null)::text || ':' ||
        count(*) filter (where result ? 'delivery_body' or result ? 'delivery_subject')::text || ':' ||
        count(*) filter (where result::text like '%side-effect-token%')::text
      from public.company_access_command_receipts
      where operation_id in ('${sharedCreateOperationId}', '${sharedResendOperationId}')
        and side_effects_completed_at is not null
    `]).trim();
    assert.equal(completedContinuations, "4:4:0:0", "completion did not scrub every receipt secret copy");

    const recoveryRoleBoundary = psql(containerName, ["-Atc", String.raw`
      select
        (select rolname from pg_catalog.pg_roles where oid =
          (select proowner from pg_catalog.pg_proc where oid =
            'public.company_access_pending_invitation_side_effects()'::regprocedure)) || ':' ||
        (select rolname from pg_catalog.pg_roles where oid =
          (select proowner from pg_catalog.pg_proc where oid =
            'public.company_access_complete_invitation_side_effect(uuid)'::regprocedure)) || ':' ||
        (select rolinherit::text || ':' || rolbypassrls::text || ':' || rolcanlogin::text
          from pg_catalog.pg_roles where rolname = 'company_access_recovery_executor') || ':' ||
        pg_catalog.pg_has_role('company_access_recovery_executor', 'company_access_executor', 'member')::text || ':' ||
        pg_catalog.pg_has_role('company_access_executor', 'company_access_recovery_executor', 'member')::text
    `]).trim();
    assert.equal(
      recoveryRoleBoundary,
      "company_access_recovery_executor:company_access_recovery_executor:false:false:false:false:false",
      "recovery functions escaped the restricted non-inheriting executor",
    );
    const migrationRoleBoundary = psql(containerName, ["-Atc", String.raw`
      select
        (select rolname from pg_catalog.pg_roles where oid =
          (select proowner from pg_catalog.pg_proc where oid =
            'public.company_access_create_invitation(uuid,uuid,text,text,text,text)'::regprocedure)) || ':' ||
        (select count(*) from pg_catalog.pg_auth_members am
          join pg_catalog.pg_roles granted on granted.oid = am.roleid
          join pg_catalog.pg_roles member on member.oid = am.member
          where granted.rolname in ('company_access_executor', 'company_access_recovery_executor')
            and member.rolname = 'talli_migration_owner'
            and (am.inherit_option or am.set_option))::text || ':' ||
        pg_catalog.has_schema_privilege('company_access_executor', 'public', 'CREATE')::text || ':' ||
        pg_catalog.has_schema_privilege('company_access_recovery_executor', 'public', 'CREATE')::text
    `]).trim();
    assert.equal(
      migrationRoleBoundary,
      "company_access_executor:0:false:false",
      "migration ownership transfer left SET, INHERIT, or schema creation behind",
    );
    const wrapperRoleBoundary = psql(containerName, ["-Atc", String.raw`
      select
        (select rolname from pg_catalog.pg_roles where oid =
          (select proowner from pg_catalog.pg_proc where oid =
            'public.company_access_auth_uid_v1()'::regprocedure)) || ':' ||
        (select rolname from pg_catalog.pg_roles where oid =
          (select proowner from pg_catalog.pg_proc where oid =
            'public.company_access_auth_jwt_v1()'::regprocedure)) || ':' ||
        pg_catalog.has_function_privilege(
          'authenticated', 'public.company_access_auth_uid_v1()', 'EXECUTE'
        )::text || ':' ||
        pg_catalog.has_function_privilege(
          'anon', 'public.company_access_auth_uid_v1()', 'EXECUTE'
        )::text || ':' ||
        pg_catalog.has_function_privilege(
          'company_access_executor', 'public.company_access_auth_jwt_v1()', 'EXECUTE'
        )::text || ':' ||
        pg_catalog.has_function_privilege(
          'company_access_recovery_executor', 'public.company_access_auth_jwt_v1()', 'EXECUTE'
        )::text || ':' ||
        pg_catalog.has_schema_privilege('company_access_executor', 'auth', 'USAGE')::text || ':' ||
        pg_catalog.has_schema_privilege('company_access_recovery_executor', 'auth', 'USAGE')::text || ':' ||
        pg_catalog.has_function_privilege(
          'company_access_executor', 'auth.uid()', 'EXECUTE'
        )::text
    `]).trim();
    assert.equal(
      wrapperRoleBoundary,
      "talli_migration_owner:talli_migration_owner:true:false:true:true:false:false:false",
      "claim wrappers escaped their migration-owned, least-privilege boundary",
    );
    const wrapperClaims = psql(containerName, ["-Atc", String.raw`
      set role authenticated;
      select set_config(
        'request.jwt.claim.sub', '00000000-0000-0000-0000-000000000011', false
      );
      select set_config(
        'request.jwt.claims', '{"email":"member@example.test","aal":"aal2"}', false
      );
      select public.company_access_auth_uid_v1()::text || ':' ||
        (public.company_access_auth_jwt_v1() ->> 'email') || ':' ||
        (public.company_access_auth_jwt_v1() ->> 'aal');
    `]).trim().split("\n").at(-1);
    assert.equal(
      wrapperClaims,
      "00000000-0000-0000-0000-000000000011:member@example.test:aal2",
      "claim wrappers did not preserve the authenticated request identity",
    );
    const anonWrapperBoundary = psql(containerName, [], String.raw`
      set role anon;
      do $$ begin
        begin
          perform public.company_access_auth_uid_v1();
          raise exception 'anon invoked company access auth wrapper';
        exception when insufficient_privilege then null;
        end;
      end $$;
      select 'anon_wrapper_concealed';
    `);
    assert.match(anonWrapperBoundary, /anon_wrapper_concealed/u);

    const expiryOperationId = "70000000-0000-4000-8000-000000000001";
    const expiryAuditId = deriveInvitationSideEffectId({
      actorId: "00000000-0000-0000-0000-000000000011",
      operationId: expiryOperationId,
      purpose: "create_invitation:audit",
    });
    const expiryOutput = psql(containerName, [], String.raw`
      set role authenticated;
      select set_config('request.jwt.claim.sub', '00000000-0000-0000-0000-000000000011', false);
      select set_config('request.jwt.claims', '{"email":"member@example.test","aal":"aal2"}', false);
      select * from public.company_access_create_invitation(
        '${expiryOperationId}', '10000000-0000-0000-0000-000000000001',
        'expiry-race@example.test', 'reviewer',
        encode(extensions.digest(convert_to('expiry-race-token', 'UTF8'), 'sha256'), 'hex'),
        'expiry-race-token'
      );
      insert into public.audit_events (id, company_id, actor_id, category, action, message)
      values (
        '${expiryAuditId}', '10000000-0000-0000-0000-000000000001',
        '00000000-0000-0000-0000-000000000011', 'review', 'reviewer_invitation_created',
        'Reviewer/read-only invitasjon køet for reviewer. Forespørsels-ID: ${expiryOperationId}.'
      );
      select delivery_token from public.company_access_pending_invitation_side_effects()
      where operation_id = '${expiryOperationId}';
    `);
    assert.match(expiryOutput, /expiry-race-token/u, "pre-expiry recovery did not expose its committed token");
    psql(containerName, [], String.raw`
      update public.company_access_command_receipts
      set expires_at = clock_timestamp() + interval '5 seconds'
      where actor_id = '00000000-0000-0000-0000-000000000011'
        and operation_id = '${expiryOperationId}';
    `);
    const expiryLocker = interactivePsql(containerName);
    expiryLocker.child.stdin.write(String.raw`
      begin;
      select operation_id from public.company_access_command_receipts
      where actor_id = '00000000-0000-0000-0000-000000000011'
        and operation_id = '${expiryOperationId}'
      for update;
      select 'expiry_receipt_lock_ready';
    `);
    await waitForOutput(expiryLocker, /expiry_receipt_lock_ready/u);
    const blockedCompletion = interactivePsql(containerName);
    blockedCompletion.child.stdin.end(String.raw`
      set application_name = 'company_access_expiry_completion';
      set role authenticated;
      select set_config('request.jwt.claim.sub', '00000000-0000-0000-0000-000000000011', false);
      select set_config('request.jwt.claims', '{"email":"member@example.test","aal":"aal2"}', false);
      select public.company_access_complete_invitation_side_effect('${expiryOperationId}');
    `);
    let completionBlocked = false;
    for (let attempt = 0; attempt < 50; attempt += 1) {
      const waiting = psql(containerName, ["-Atc", String.raw`
        select count(*) from pg_catalog.pg_stat_activity
        where application_name = 'company_access_expiry_completion'
          and wait_event_type = 'Lock'
          and query like '%company_access_complete_invitation_side_effect%'
      `]).trim();
      if (waiting === "1") { completionBlocked = true; break; }
      await new Promise((resolve) => setTimeout(resolve, 100));
    }
    assert.equal(completionBlocked, true, "completion did not block behind the receipt lock");
    let receiptExpired = false;
    for (let attempt = 0; attempt < 80; attempt += 1) {
      receiptExpired = psql(containerName, ["-Atc", String.raw`
        select clock_timestamp() > expires_at
        from public.company_access_command_receipts
        where actor_id = '00000000-0000-0000-0000-000000000011'
          and operation_id = '${expiryOperationId}'
      `]).trim() === "t";
      if (receiptExpired) break;
      await new Promise((resolve) => setTimeout(resolve, 100));
    }
    assert.equal(receiptExpired, true, "test clock did not advance beyond receipt expiry");
    expiryLocker.child.stdin.end("commit;\n");
    const blockedResult = await waitForExit(blockedCompletion);
    await waitForExit(expiryLocker);
    assert.equal(blockedResult.code, 0, blockedResult.stderr);
    assert.match(blockedResult.stdout, /t/u);
    const expiryState = psql(containerName, ["-Atc", String.raw`
      select
        (select count(*) from public.notification_outbox
          where payload ->> 'operationId' = '${expiryOperationId}')::text || ':' ||
        (select count(*) from public.company_access_command_receipts
          where operation_id = '${expiryOperationId}' and delivery_token is null
            and side_effects_completed_at is not null
            and not (result ? 'delivery_body') and result::text not like '%expiry-race-token%')::text
    `]).trim();
    assert.equal(expiryState, "0:1", "expiry crossing queued obsolete mail or retained its receipt secret");

    const [raceInvitationId, raceExpectedRevision] = psql(containerName, ["-Atc", String.raw`
      select invitation_id::text || E'\t' || split_part(request_fingerprint, '|', 3)
      from public.company_access_command_receipts
      where operation_id = '40000000-0000-0000-0000-000000000002'
    `]).trim().split("\t");

    psql(containerName, [], String.raw`
      create or replace function public.company_access_is_accepted_owner_v1(p_company_id uuid)
      returns boolean
      language plpgsql
      stable
      security definer
      set search_path = ''
      as $function$
      declare
        v_authorized boolean;
      begin
        select exists (
          select 1 from public.company_memberships m
          where m.company_id = p_company_id
            and m.user_id = (select auth.uid())
            and m.role = 'owner'
            and m.accepted_at is not null
        ) into v_authorized;
        if current_setting('test.receipt_race_hook', true) = 'on' then
          perform pg_catalog.pg_advisory_lock(160, 4);
        end if;
        return v_authorized;
      end;
      $function$;
    `);

    const authorizationLocker = interactivePsql(containerName);
    authorizationLocker.child.stdin.write(String.raw`
      select pg_catalog.pg_advisory_lock(160, 4);
      select 'authorization_race_lock_ready';
    `);
    await waitForOutput(authorizationLocker, /authorization_race_lock_ready/u);

    const racingReplay = interactivePsql(containerName);
    racingReplay.child.stdin.end(String.raw`
      set application_name = 'company_access_receipt_race';
      set role authenticated;
      select set_config('request.jwt.claim.sub', '00000000-0000-0000-0000-000000000011', false);
      select set_config('request.jwt.claims', '{"email":"member@example.test","aal":"aal2"}', false);
      select set_config('test.receipt_race_hook', 'on', false);
      select delivery_token from public.company_access_resend_invitation(
        '40000000-0000-0000-0000-000000000002',
        '10000000-0000-0000-0000-000000000001',
        '${raceInvitationId}'::uuid,
        '${raceExpectedRevision}'::timestamptz,
        encode(extensions.digest(convert_to('resend-token', 'UTF8'), 'sha256'), 'hex'),
        'resend-token'
      );
    `);

    let replayBlockedAfterAuthorization = false;
    for (let attempt = 0; attempt < 50; attempt += 1) {
      const waiting = psql(containerName, ["-Atc", String.raw`
        select count(*) from pg_catalog.pg_stat_activity
        where application_name = 'company_access_receipt_race'
          and wait_event_type = 'Lock'
          and wait_event = 'advisory'
          and query like '%company_access_resend_invitation%'
      `]).trim();
      if (waiting === "1") {
        replayBlockedAfterAuthorization = true;
        break;
      }
      await new Promise((resolve) => setTimeout(resolve, 100));
    }
    assert.equal(replayBlockedAfterAuthorization, true, "replay did not pause after computing owner authorization");

    psql(containerName, [], String.raw`
      delete from public.company_memberships
      where company_id = '10000000-0000-0000-0000-000000000001'
        and user_id = '00000000-0000-0000-0000-000000000011';
    `);
    authorizationLocker.child.stdin.end("select pg_catalog.pg_advisory_unlock(160, 4);\n");
    const raced = await waitForExit(racingReplay);
    await waitForExit(authorizationLocker);
    assert.notEqual(raced.code, 0, `concurrent demotion disclosed receipt: ${raced.stdout}`);
    assert.match(raced.stderr, /company_access_not_found/u);
    assert.doesNotMatch(raced.stdout, /resend-token/u);

    psql(containerName, [], String.raw`
      insert into public.company_memberships (company_id, user_id, role, accepted_at)
      values (
        '10000000-0000-0000-0000-000000000001',
        '00000000-0000-0000-0000-000000000011', 'owner', statement_timestamp()
      );
    `);
    const reconciled = psql(containerName, [], String.raw`
      set role authenticated;
      select set_config('request.jwt.claim.sub', '00000000-0000-0000-0000-000000000011', false);
      select set_config('request.jwt.claims', '{"email":"member@example.test","aal":"aal2"}', false);
      select delivery_token from public.company_access_resend_invitation(
        '40000000-0000-0000-0000-000000000002',
        '10000000-0000-0000-0000-000000000001',
        '${raceInvitationId}'::uuid,
        '${raceExpectedRevision}'::timestamptz,
        encode(extensions.digest(convert_to('resend-token', 'UTF8'), 'sha256'), 'hex'),
        'resend-token'
      );
    `);
    assert.match(reconciled, /resend-token/u);
    const persisted = psql(containerName, [], String.raw`
      select status, accepted_by from public.company_invitations
      where id = '30000000-0000-0000-0000-000000000001';
    `);
    assert.match(persisted, /accepted[\s\S]+00000000-0000-0000-0000-000000000033/);

    const acceptanceOperationId = "40000000-0000-0000-0000-000000000004";
    const acceptanceAuditId = deriveInvitationSideEffectId({
      actorId: "00000000-0000-0000-0000-000000000033",
      operationId: acceptanceOperationId,
      purpose: "accept_invitation:audit",
    });
    psql(containerName, [], String.raw`
      insert into public.company_memberships (company_id, user_id, role, accepted_at)
      values (
        '10000000-0000-0000-0000-000000000001',
        '00000000-0000-0000-0000-000000000033', 'reviewer', clock_timestamp()
      );
      insert into public.audit_events (id, company_id, actor_id, category, action, message)
      values (
        '${acceptanceAuditId}', '10000000-0000-0000-0000-000000000001',
        '00000000-0000-0000-0000-000000000033', 'review', 'reviewer_invitation_accepted',
        'Invitasjon akseptert som reviewer. Forespørsels-ID: ${acceptanceOperationId}.'
      );
    `);
    psql(containerName, [], String.raw`
      set role authenticated;
      select set_config('request.jwt.claim.sub', '00000000-0000-0000-0000-000000000033', false);
      select set_config('request.jwt.claims', '{"email":"outsider@example.test","aal":"aal1"}', false);
      select public.company_access_complete_invitation_side_effect('${acceptanceOperationId}');
    `);
    const concealCompleted = (actorId, email, aal, operationId, unknownId) => psql(containerName, [], String.raw`
      set role authenticated;
      select set_config('request.jwt.claim.sub', '${actorId}', false);
      select set_config('request.jwt.claims', '{"email":"${email}","aal":"${aal}"}', false);
      do $$ declare v_completed text := 'success'; v_unknown text := 'success'; begin
        begin perform public.company_access_complete_invitation_side_effect('${operationId}');
        exception when sqlstate 'P0001' then v_completed := sqlerrm; end;
        begin perform public.company_access_complete_invitation_side_effect('${unknownId}');
        exception when sqlstate 'P0001' then v_unknown := sqlerrm; end;
        if v_completed is distinct from v_unknown or v_unknown <> 'company_access_not_found' then
          raise exception 'completed receipt oracle: completed=%, unknown=%', v_completed, v_unknown;
        end if;
      end $$;
      select 'completed_receipt_concealed';
    `);
    assert.match(concealCompleted(
      "00000000-0000-0000-0000-000000000011", "member@example.test", "aal1",
      sharedCreateOperationId, "80000000-0000-4000-8000-000000000001",
    ), /completed_receipt_concealed/u);
    psql(containerName, [], String.raw`
      delete from public.company_memberships
      where company_id = '10000000-0000-0000-0000-000000000001'
        and user_id = '00000000-0000-0000-0000-000000000011';
    `);
    assert.match(concealCompleted(
      "00000000-0000-0000-0000-000000000011", "member@example.test", "aal2",
      sharedCreateOperationId, "80000000-0000-4000-8000-000000000002",
    ), /completed_receipt_concealed/u);
    psql(containerName, [], String.raw`
      insert into public.company_memberships (company_id, user_id, role, accepted_at)
      values (
        '10000000-0000-0000-0000-000000000001',
        '00000000-0000-0000-0000-000000000011', 'owner', clock_timestamp()
      );
      delete from public.company_memberships
      where company_id = '10000000-0000-0000-0000-000000000001'
        and user_id = '00000000-0000-0000-0000-000000000033';
    `);
    assert.match(concealCompleted(
      "00000000-0000-0000-0000-000000000033", "outsider@example.test", "aal1",
      acceptanceOperationId, "80000000-0000-4000-8000-000000000003",
    ), /completed_receipt_concealed/u);
  } finally {
    docker(["rm", "--force", containerName]);
  }
});

test("cancellation lifecycle is atomic, review-bound, replay-safe, and tenant concealed", { timeout: 120_000 }, async () => {
  assert.equal(
    docker(["info", "--format", "{{.ServerVersion}}"]).status,
    0,
    "Docker is required for the mandatory cancellation PostgreSQL rehearsal",
  );
  const containerName = `talli-cancellation-${process.pid}-${randomUUID().slice(0, 8)}`;
  try {
    const started = docker([
      "run", "--rm", "--detach", "--name", containerName,
      "--env", "POSTGRES_PASSWORD=postgres", "--env", "POSTGRES_DB=talli_test",
      "--volume", `${repositoryRoot}:/repo:ro`, "postgres:17",
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
    psql(containerName, ["--file", "/repo/supabase/migrations/0002_fifo_investment_lots.sql"]);
    psql(containerName, ["--file", "/repo/supabase/migrations/0003_bank_rule_suggestions.sql"]);
    psql(containerName, ["--file", "/repo/supabase/migrations/0004_corporate_document_artifacts.sql"]);
    psql(containerName, [], String.raw`
      create role talli_migration_owner login noinherit createrole bypassrls;
      alter schema public owner to talli_migration_owner;
      grant usage on schema auth to talli_migration_owner with grant option;
      grant usage on schema extensions to talli_migration_owner;
      grant select, references on auth.users to talli_migration_owner;
      grant execute on function auth.uid(), auth.jwt() to talli_migration_owner with grant option;
      alter table public.companies owner to talli_migration_owner;
      alter table public.company_memberships owner to talli_migration_owner;
      alter table public.company_invitations owner to talli_migration_owner;
      alter table public.notification_outbox owner to talli_migration_owner;
      alter table public.audit_events owner to talli_migration_owner;
      alter table public.company_cancellations owner to talli_migration_owner;
      alter table public.documents owner to talli_migration_owner;
      alter table public.opening_balance_setups owner to talli_migration_owner;
      alter table public.opening_shareholders owner to talli_migration_owner;
      alter table public.ledger_entries owner to talli_migration_owner;
      alter table public.filing_previews owner to talli_migration_owner;
      alter table public.filing_submissions owner to talli_migration_owner;
      alter table public.holding_actions owner to talli_migration_owner;
      alter table public.billing_accounts owner to talli_migration_owner;
      alter table public.authority_permissions owner to talli_migration_owner;
      alter table public.authority_test_runs owner to talli_migration_owner;
      alter table public.filing_review_comments owner to talli_migration_owner;
      alter table public.investment_positions owner to talli_migration_owner;
      alter table public.investment_lots owner to talli_migration_owner;
      alter table public.investment_lot_allocations owner to talli_migration_owner;
      alter table public.bank_suggestion_acceptances owner to talli_migration_owner;
      alter table public.support_operators owner to talli_migration_owner;
      alter table public.corporate_decisions owner to talli_migration_owner;
      alter table public.corporate_document_sets owner to talli_migration_owner;
      alter table public.corporate_document_artifacts owner to talli_migration_owner;
      alter table public.corporate_document_events owner to talli_migration_owner;
      alter table public.corporate_decision_finalizations owner to talli_migration_owner;
    `);
    psql(containerName, [
      "-U", "talli_migration_owner",
      "--file", "/repo/supabase/migrations/20260801090000_company_access_invitations.sql",
    ]);
    psql(containerName, [
      "-U", "talli_migration_owner",
      "--file", "/repo/supabase/migrations/20260808120000_company_access_cancellation_lifecycle.sql",
    ]);
    psql(containerName, [], String.raw`
      insert into auth.users (id, email) values
        ('00000000-0000-0000-0000-000000000011', 'owner@example.test'),
        ('00000000-0000-0000-0000-000000000022', 'reviewer@example.test'),
        ('00000000-0000-0000-0000-000000000033', 'outsider@example.test'),
        ('00000000-0000-0000-0000-000000000044', 'admin@example.test'),
        ('00000000-0000-0000-0000-000000000055', 'support@example.test');
      insert into public.companies (id, org_number, name, entity_type, status_text, created_by) values
        ('10000000-0000-0000-0000-000000000001', '314159265', 'Lifecycle AS', 'AS', 'Active', '00000000-0000-0000-0000-000000000011'),
        ('20000000-0000-0000-0000-000000000002', '271828182', 'Incomplete AS', 'AS', 'Active', '00000000-0000-0000-0000-000000000011'),
        ('30000000-0000-0000-0000-000000000003', '161803398', 'Race AS', 'AS', 'Active', '00000000-0000-0000-0000-000000000011');
      insert into public.company_memberships (company_id, user_id, role, accepted_at) values
        ('10000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000011', 'owner', now()),
        ('10000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000022', 'reviewer', now()),
        ('20000000-0000-0000-0000-000000000002', '00000000-0000-0000-0000-000000000011', 'owner', now()),
        ('30000000-0000-0000-0000-000000000003', '00000000-0000-0000-0000-000000000011', 'owner', now());
      insert into public.support_operators (user_id, role, active) values
        ('00000000-0000-0000-0000-000000000044', 'admin', true),
        ('00000000-0000-0000-0000-000000000055', 'support', true);
      insert into public.audit_events (company_id, actor_id, category, action, message, created_at)
      values ('10000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000011', 'archive', 'company_year_archive_exported:2025', 'archive ready', now() - interval '1 minute');
      insert into public.documents (id, company_id, income_year, document_type, name, linked_to, status, storage_key, created_by)
      values
        ('70000000-0000-0000-0000-000000000001', '10000000-0000-0000-0000-000000000001', 2025, 'bank', 'bank.pdf', 'year', 'attached', '10000000-0000-0000-0000-000000000001/2025/bank.pdf', '00000000-0000-0000-0000-000000000011'),
        ('70000000-0000-0000-0000-000000000003', '30000000-0000-0000-0000-000000000003', 2025, 'bank', 'race.pdf', 'year', 'attached', '30000000-0000-0000-0000-000000000003/2025/race.pdf', '00000000-0000-0000-0000-000000000011');
    `);

    const prepareRaceArchive = (sha) => psql(containerName, [], String.raw`
      set role authenticated;
      select set_config('request.jwt.claim.sub', '00000000-0000-0000-0000-000000000011', false);
      select set_config('request.jwt.claims', jsonb_build_object('aal','aal2','amr',jsonb_build_array(jsonb_build_object('method','totp','timestamp',extract(epoch from now()))))::text, false);
      select public.company_archive_begin_export('30000000-0000-0000-0000-000000000003', 2025) as attempt_id \gset
      reset role;
      set role service_role;
      select public.company_archive_complete_export(:'attempt_id', '${sha}');
    `);

    psql(containerName, [], String.raw`
      set role authenticated;
      select set_config('request.jwt.claim.sub', '00000000-0000-0000-0000-000000000011', false);
      select set_config('request.jwt.claims', jsonb_build_object('aal','aal2','amr',jsonb_build_array(jsonb_build_object('method','totp','timestamp',extract(epoch from now()))))::text, false);
      select public.company_archive_begin_export('30000000-0000-0000-0000-000000000003', 2025) as stale_attempt_id \gset
      reset role;
      update public.documents set name = 'generation-mismatch.pdf' where id = '70000000-0000-0000-0000-000000000003';
      set role service_role;
      select set_config('test.stale_attempt_id', :'stale_attempt_id', false);
      do $$ begin
        begin
          perform public.company_archive_complete_export(current_setting('test.stale_attempt_id')::uuid, repeat('e', 64));
          raise exception 'generation-mismatched attempt completed';
        exception when sqlstate 'P0001' then
          if sqlerrm <> 'archive_export_stale' then raise; end if;
        end;
      end $$;
      reset role;
      set role authenticated;
      select set_config('request.jwt.claim.sub', '00000000-0000-0000-0000-000000000011', false);
      select set_config('request.jwt.claims', jsonb_build_object('aal','aal2','amr',jsonb_build_array(jsonb_build_object('method','totp','timestamp',extract(epoch from now()))))::text, false);
      select public.company_archive_begin_export('30000000-0000-0000-0000-000000000003', 2025) as company_stale_attempt_id \gset
      reset role;
      update public.companies set name = 'Race AS updated'
      where id = '30000000-0000-0000-0000-000000000003';
      set role service_role;
      select set_config('test.company_stale_attempt_id', :'company_stale_attempt_id', false);
      do $$ begin
        begin
          perform public.company_archive_complete_export(current_setting('test.company_stale_attempt_id')::uuid, repeat('d', 64));
          raise exception 'company-wide generation-mismatched attempt completed';
        exception when sqlstate 'P0001' then
          if sqlerrm <> 'archive_export_stale' then raise; end if;
        end;
      end $$;
      reset role;
      insert into public.company_archive_export_attempts(
        id, company_id, income_year, actor_id, source_generation, started_at, expires_at
      ) select
        '90000000-0000-0000-0000-000000000099', '30000000-0000-0000-0000-000000000003', 2025,
        '00000000-0000-0000-0000-000000000011', generation,
        statement_timestamp() - interval '20 minutes', statement_timestamp() - interval '10 minutes'
      from public.company_archive_source_generations
      where company_id = '30000000-0000-0000-0000-000000000003' and income_year = 2025;
      set role service_role;
      do $$ begin
        begin
          perform public.company_archive_complete_export('90000000-0000-0000-0000-000000000099', repeat('f', 64));
          raise exception 'expired attempt completed';
        exception when sqlstate 'P0001' then
          if sqlerrm <> 'archive_export_invalid' then raise; end if;
        end;
      end $$;
    `);

    prepareRaceArchive("c".repeat(64));
    const lifecycleFirst = interactivePsql(containerName);
    lifecycleFirst.child.stdin.write(String.raw`
      set role authenticated;
      select set_config('request.jwt.claim.sub', '00000000-0000-0000-0000-000000000011', false);
      select set_config('request.jwt.claims', jsonb_build_object('aal','aal2','amr',jsonb_build_array(jsonb_build_object('method','totp','timestamp',extract(epoch from now()))))::text, false);
      begin;
      select * from public.company_access_request_cancellation(
        '40000000-0000-0000-0000-000000000020', '30000000-0000-0000-0000-000000000003', 2025, 'Race lifecycle first'
      );
      select 'lifecycle_holds_scope_lock';
    `);
    await waitForOutput(lifecycleFirst, /lifecycle_holds_scope_lock/u);
    const writerSecond = interactivePsql(containerName);
    writerSecond.child.stdin.write(String.raw`
      begin;
      update public.documents set name = 'race-after-lifecycle.pdf'
      where id = '70000000-0000-0000-0000-000000000003';
      select 'writer_after_lifecycle_completed';
      commit;
      \q
    `);
    const blockedWriter = psql(containerName, [], String.raw`
      select count(*) as blocked_writer_count from pg_catalog.pg_stat_activity
      where wait_event_type = 'Lock' and query like 'update public.documents%';
    `);
    assert.match(blockedWriter, /blocked_writer_count[\s\S]*1/u);
    lifecycleFirst.child.stdin.write("commit;\n\\q\n");
    assert.equal((await waitForExit(lifecycleFirst)).code, 0);
    assert.equal((await waitForExit(writerSecond)).code, 0);

    psql(containerName, [], String.raw`
      delete from public.company_cancellations where company_id = '30000000-0000-0000-0000-000000000003';
    `);
    prepareRaceArchive("d".repeat(64));
    const writerFirst = interactivePsql(containerName);
    writerFirst.child.stdin.write(String.raw`
      begin;
      update public.documents set name = 'race-before-lifecycle.pdf'
      where id = '70000000-0000-0000-0000-000000000003';
      select 'writer_holds_scope_lock';
    `);
    await waitForOutput(writerFirst, /writer_holds_scope_lock/u);
    const lifecycleSecond = interactivePsql(containerName);
    lifecycleSecond.child.stdin.write(String.raw`
      set role authenticated;
      select set_config('request.jwt.claim.sub', '00000000-0000-0000-0000-000000000011', false);
      select set_config('request.jwt.claims', jsonb_build_object('aal','aal2','amr',jsonb_build_array(jsonb_build_object('method','totp','timestamp',extract(epoch from now()))))::text, false);
      select * from public.company_access_request_cancellation(
        '40000000-0000-0000-0000-000000000021', '30000000-0000-0000-0000-000000000003', 2025, 'Writer race first'
      );
      \q
    `);
    const blockedLifecycle = psql(containerName, [], String.raw`
      select count(*) as blocked_lifecycle_count from pg_catalog.pg_stat_activity
      where wait_event_type = 'Lock' and query like 'select * from public.company_access_request_cancellation%';
    `);
    assert.match(blockedLifecycle, /blocked_lifecycle_count[\s\S]*1/u);
    writerFirst.child.stdin.write("commit;\n\\q\n");
    assert.equal((await waitForExit(writerFirst)).code, 0);
    const staleLifecycle = await waitForExit(lifecycleSecond);
    assert.notEqual(staleLifecycle.code, 0);
    assert.match(staleLifecycle.stderr, /cancellation_prerequisite_failed/u);

    const output = psql(containerName, [], String.raw`
      set role authenticated;
      select set_config('request.jwt.claim.sub', '00000000-0000-0000-0000-000000000011', false);
      select set_config('request.jwt.claims', jsonb_build_object('aal','aal2','amr',jsonb_build_array(jsonb_build_object('method','totp','timestamp',extract(epoch from now()))))::text, false);

      insert into public.company_cancellations (company_id, status, reason, requested_by)
      values ('10000000-0000-0000-0000-000000000001', 'retention_hold', 'legacy overlap', '00000000-0000-0000-0000-000000000011');
      reset role;
      delete from public.company_cancellations where reason = 'legacy overlap';
      set role authenticated;

      do $$ begin
        begin
          perform public.company_archive_begin_export('10000000-0000-0000-0000-000000000001', null);
          raise exception 'null archive year succeeded';
        exception when sqlstate 'P0001' then
          if sqlerrm <> 'company_access_invalid_request' then raise; end if;
        end;
        begin
          perform * from public.company_access_request_cancellation(
            '40000000-0000-0000-0000-000000000031', '10000000-0000-0000-0000-000000000001', null, 'Null year'
          );
          raise exception 'null cancellation year succeeded';
        exception when sqlstate 'P0001' then
          if sqlerrm <> 'company_access_invalid_request' then raise; end if;
        end;
        begin
          perform * from public.company_access_reconcile_cancellation_operation(
            '40000000-0000-0000-0000-000000000032', 'request_cancellation',
            '10000000-0000-0000-0000-000000000001', p_income_year => null, p_reason => 'Null year'
          );
          raise exception 'null reconciliation year succeeded';
        exception when sqlstate 'P0001' then
          if sqlerrm <> 'company_access_invalid_request' then raise; end if;
        end;
      end $$;

      select public.company_archive_begin_export('10000000-0000-0000-0000-000000000001', 2025) as archive_attempt_id \gset
      do $$ begin
        begin
          perform public.company_archive_complete_export('90000000-0000-0000-0000-000000000001', repeat('a', 64));
          raise exception 'authenticated completed archive receipt';
        exception when insufficient_privilege then null;
        end;
      end $$;
      reset role;
      set role service_role;
      select public.company_archive_complete_export(:'archive_attempt_id', repeat('a', 64));
      select set_config('test.archive_attempt_id', :'archive_attempt_id', false);
      do $$ begin
        begin
          perform public.company_archive_complete_export(current_setting('test.archive_attempt_id')::uuid, repeat('a', 64));
          raise exception 'archive attempt replay succeeded';
        exception when sqlstate 'P0001' then
          if sqlerrm <> 'archive_export_invalid' then raise; end if;
        end;
      end $$;
      reset role;
      set role authenticated;
      select set_config('request.jwt.claim.sub', '00000000-0000-0000-0000-000000000011', false);
      select set_config('request.jwt.claims', jsonb_build_object('aal','aal2','amr',jsonb_build_array(jsonb_build_object('method','totp','timestamp',extract(epoch from now()))))::text, false);

      select * from public.company_access_request_cancellation(
        '40000000-0000-0000-0000-000000000001', '10000000-0000-0000-0000-000000000001', 2025, 'Customer requested cancellation'
      );
      select * from public.company_access_request_cancellation(
        '40000000-0000-0000-0000-000000000001', '10000000-0000-0000-0000-000000000001', 2025, 'Customer requested cancellation'
      );
      do $$ begin
        if (select count(*) from public.company_access_list_cancellations('10000000-0000-0000-0000-000000000001')) <> 1 then raise exception 'request replay duplicated cancellation'; end if;
        if (select count(*) from public.audit_events where company_id = '10000000-0000-0000-0000-000000000001' and action in ('cancellation_archive_verified','company_cancellation_requested')) <> 2 then raise exception 'request replay duplicated audit'; end if;
        begin
          insert into public.company_cancellations (company_id, status, reason, requested_by)
          values ('10000000-0000-0000-0000-000000000001', 'retention_hold', 'second active', '00000000-0000-0000-0000-000000000011');
          raise exception 'second active cancellation succeeded';
        exception when unique_violation then null;
        end;
        begin
          perform * from public.company_access_request_cancellation(
            '40000000-0000-0000-0000-000000000002', '20000000-0000-0000-0000-000000000002', 2025, 'Incomplete archive'
          );
          raise exception 'missing archive request succeeded';
        exception when sqlstate 'P0001' then
          if sqlerrm <> 'cancellation_prerequisite_failed' then raise; end if;
        end;
        if exists (select 1 from public.company_cancellations where company_id = '20000000-0000-0000-0000-000000000002') then raise exception 'failed request left partial cancellation'; end if;
      end $$;

      select set_config('request.jwt.claim.sub', '00000000-0000-0000-0000-000000000033', false);
      do $$ begin
        if exists (select 1 from public.company_access_list_cancellations('10000000-0000-0000-0000-000000000001')) then raise exception 'outsider saw cancellation'; end if;
      end $$;
      select set_config('request.jwt.claim.sub', '00000000-0000-0000-0000-000000000022', false);
      do $$ begin
        if (select count(*) from public.company_access_list_cancellations('10000000-0000-0000-0000-000000000001')) <> 1 then raise exception 'accepted reviewer lost read'; end if;
      end $$;
      select set_config('request.jwt.claim.sub', '00000000-0000-0000-0000-000000000055', false);
      do $$ begin
        if (select count(*) from public.company_access_list_cancellations('10000000-0000-0000-0000-000000000001')) <> 1 then raise exception 'support operator lost narrow read'; end if;
      end $$;

      select set_config('request.jwt.claim.sub', '00000000-0000-0000-0000-000000000011', false);
      reset role;
      insert into public.support_operators (user_id, role, active)
      values ('00000000-0000-0000-0000-000000000011', 'admin', true);
      set role authenticated;
      select set_config('request.jwt.claim.sub', '00000000-0000-0000-0000-000000000011', false);
      select set_config('request.jwt.claims', jsonb_build_object('aal','aal2','amr',jsonb_build_array(jsonb_build_object('method','totp','timestamp',extract(epoch from now()))))::text, false);
      do $$ declare c record; begin
        select * into c from public.company_access_list_cancellations('10000000-0000-0000-0000-000000000001') limit 1;
        begin
          perform * from public.company_access_review_deletion(
            '40000000-0000-0000-0000-000000000003', c.id, c.company_id, c.updated_at, 'approved', 'owner-self-review'
          );
          raise exception 'owner self-review succeeded';
        exception when sqlstate 'P0001' then
          if sqlerrm <> 'company_access_not_found' then raise; end if;
        end;
      end $$;

      do $$ begin
        begin
          perform * from public.company_access_request_cancellation(
            '40000000-0000-0000-0000-000000000008', '10000000-0000-0000-0000-000000000001', 2025, repeat('x', 1001)
          );
          raise exception 'oversized reason succeeded';
        exception when sqlstate 'P0001' then
          if sqlerrm <> 'company_access_invalid_request' then raise; end if;
        end;
      end $$;
      reset role;
      do $$ begin
        if exists (select 1 from public.company_access_command_receipts where operation_id = '40000000-0000-0000-0000-000000000008') then
          raise exception 'invalid request wrote receipt';
        end if;
      end $$;
      set role authenticated;

      select set_config('request.jwt.claim.sub', '00000000-0000-0000-0000-000000000044', false);
      do $$ declare c record; begin
        select * into c from public.company_access_list_cancellations('10000000-0000-0000-0000-000000000001') limit 1;
        begin
          perform * from public.company_access_review_deletion(
            '40000000-0000-0000-0000-000000000009', c.id, c.company_id, null, 'approved', 'null revision'
          );
          raise exception 'null review revision succeeded';
        exception when sqlstate 'P0001' then
          if sqlerrm <> 'company_access_invalid_request' then raise; end if;
        end;
        begin
          perform * from public.company_access_review_deletion(
            '40000000-0000-0000-0000-000000000010', c.id, c.company_id, c.updated_at, 'approved', repeat('x', 501)
          );
          raise exception 'oversized evidence reference succeeded';
        exception when sqlstate 'P0001' then
          if sqlerrm <> 'company_access_invalid_request' then raise; end if;
        end;
        perform * from public.company_access_review_deletion(
          '40000000-0000-0000-0000-000000000004', c.id, c.company_id, c.updated_at, 'rejected', 'legal/case-161-rejected'
        );
      end $$;

      select set_config('request.jwt.claim.sub', '00000000-0000-0000-0000-000000000011', false);
      do $$ declare c record; begin
        select * into c from public.company_access_list_cancellations('10000000-0000-0000-0000-000000000001') limit 1;
        begin
          perform * from public.company_access_finalize_deletion(
            '40000000-0000-0000-0000-000000000011', c.id, c.company_id, null
          );
          raise exception 'null finalize revision succeeded';
        exception when sqlstate 'P0001' then
          if sqlerrm <> 'company_access_invalid_request' then raise; end if;
        end;
        begin
          perform * from public.company_access_finalize_deletion(
            '40000000-0000-0000-0000-000000000005', c.id, c.company_id, c.updated_at
          );
          raise exception 'rejected review authorized finalize';
        exception when sqlstate 'P0001' then
          if sqlerrm <> 'company_access_conflict' then raise; end if;
        end;
      end $$;

      select set_config('request.jwt.claim.sub', '00000000-0000-0000-0000-000000000044', false);
      do $$ declare c record; review_json jsonb; begin
        select * into c from public.company_access_list_cancellations('10000000-0000-0000-0000-000000000001') limit 1;
        select review into review_json from public.company_access_review_deletion(
          '40000000-0000-0000-0000-000000000006', c.id, c.company_id, c.updated_at, 'approved', 'legal/case-161-approved'
        );
        if review_json ? 'requester_id' or not review_json ?& array[
          'id','cancellation_id','company_id','decision','evidence_reference',
          'reviewed_by','reviewed_at','operation_id','cancellation_revision'
        ] then raise exception 'review response projection mismatch: %', review_json; end if;
      end $$;

      reset role;
      update public.documents set status = 'missing_object' where id = '70000000-0000-0000-0000-000000000001';
      set role authenticated;
      select set_config('request.jwt.claim.sub', '00000000-0000-0000-0000-000000000011', false);
      do $$ declare c record; begin
        select * into c from public.company_access_list_cancellations('10000000-0000-0000-0000-000000000001') limit 1;
        begin
          perform * from public.company_access_finalize_deletion(
            '40000000-0000-0000-0000-000000000007', c.id, c.company_id, c.updated_at
          );
          raise exception 'stale archive finalize succeeded';
        exception when sqlstate 'P0001' then
          if sqlerrm <> 'cancellation_prerequisite_failed' then raise; end if;
        end;
        if c.status <> 'deletion_approved' then raise exception 'failed finalize changed cancellation'; end if;
      end $$;
      reset role;
      update public.documents set status = 'attached' where id = '70000000-0000-0000-0000-000000000001';
      set role authenticated;
      select set_config('request.jwt.claim.sub', '00000000-0000-0000-0000-000000000011', false);
      select set_config('request.jwt.claims', jsonb_build_object('aal','aal2','amr',jsonb_build_array(jsonb_build_object('method','totp','timestamp',extract(epoch from now()))))::text, false);
      select public.company_archive_begin_export('10000000-0000-0000-0000-000000000001', 2025) as replacement_archive_attempt_id \gset
      reset role;
      set role service_role;
      select public.company_archive_complete_export(:'replacement_archive_attempt_id', repeat('b', 64));
      reset role;
      set role authenticated;
      select set_config('request.jwt.claim.sub', '00000000-0000-0000-0000-000000000011', false);
      select set_config('request.jwt.claims', jsonb_build_object('aal','aal2','amr',jsonb_build_array(jsonb_build_object('method','totp','timestamp',extract(epoch from now()))))::text, false);
      do $$ declare c record; begin
        select * into c from public.company_access_list_cancellations('10000000-0000-0000-0000-000000000001') limit 1;
        perform * from public.company_access_finalize_deletion(
          '40000000-0000-0000-0000-000000000007', c.id, c.company_id, c.updated_at
        );
        perform * from public.company_access_finalize_deletion(
          '40000000-0000-0000-0000-000000000007', c.id, c.company_id, c.updated_at
        );
      end $$;
      reset role;
      do $$ begin
        if (select status from public.company_cancellations where company_id = '10000000-0000-0000-0000-000000000001') <> 'deleted' then raise exception 'final status missing'; end if;
        if (select status_text from public.companies where id = '10000000-0000-0000-0000-000000000001') <> 'deleted_retention_record' then raise exception 'company marker missing'; end if;
        if (select count(*) from public.audit_events where action = 'company_deletion_completed') <> 1 then raise exception 'finalize replay duplicated audit'; end if;
        if not exists (select 1 from public.documents where id = '70000000-0000-0000-0000-000000000001') then raise exception 'physical business data was deleted'; end if;
        if (select count(*) from public.company_deletion_reviews) <> 2 then raise exception 'append-only reviews missing'; end if;
      end $$;
      select 'company_access_cancellation_runtime_ok';
    `);
    assert.match(output, /company_access_cancellation_runtime_ok/);

    psql(containerName, ["--file", "/repo/supabase/contract-migrations/20260808121000_company_access_cancellation_contract.sql"]);
    const contracted = psql(containerName, [], String.raw`
      do $$ begin
        if has_table_privilege('authenticated', 'public.company_cancellations', 'SELECT') then raise exception 'direct cancellation select remains'; end if;
        if has_table_privilege('authenticated', 'public.company_cancellations', 'UPDATE') then raise exception 'direct cancellation update remains'; end if;
      end $$;
      set role authenticated;
      select set_config('request.jwt.claim.sub', '00000000-0000-0000-0000-000000000011', false);
      select set_config('request.jwt.claims', jsonb_build_object('aal','aal2','amr',jsonb_build_array(jsonb_build_object('method','totp','timestamp',extract(epoch from now()))))::text, false);
      do $$ begin
        if (select count(*) from public.company_access_list_cancellations('10000000-0000-0000-0000-000000000001')) <> 1 then raise exception 'generated query RPC failed after contract'; end if;
      end $$;
      select 'company_access_cancellation_contract_ok';
    `);
    assert.match(contracted, /company_access_cancellation_contract_ok/);
  } finally {
    docker(["rm", "--force", containerName]);
  }
});
