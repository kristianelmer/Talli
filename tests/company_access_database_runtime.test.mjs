import assert from "node:assert/strict";
import { spawn, spawnSync } from "node:child_process";
import { randomUUID } from "node:crypto";
import { fileURLToPath } from "node:url";
import test from "node:test";

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
    psql(containerName, ["--file", "/repo/supabase/migrations/20260801090000_company_access_invitations.sql"]);
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
        encode(extensions.digest(convert_to('create-token', 'UTF8'), 'sha256'), 'hex'),
        'create-token'
      );
      do $$ declare recovered text; begin
        if (select count(*) from public.company_invitations where invited_email = 'delivery@example.test') != 1 then
          raise exception 'create replay duplicated invitation';
        end if;
        select delivery_token into recovered from public.company_access_create_invitation(
          '40000000-0000-0000-0000-000000000001',
          '10000000-0000-0000-0000-000000000001',
          'delivery@example.test', 'reviewer',
          encode(extensions.digest(convert_to('create-token', 'UTF8'), 'sha256'), 'hex'), 'create-token'
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
  } finally {
    docker(["rm", "--force", containerName]);
  }
});
