-- EXPAND/MIGRATE: company-access invitation and membership administration.
--
-- The legacy authenticated table policies intentionally remain during this
-- expansion migration so the previously deployed web revision keeps working.
-- 20260801091000_company_access_invitations_contract.sql removes only the
-- invitation/membership-administration legacy surface after the new client is
-- deployed. Command functions run as a restricted NOLOGIN role that is subject
-- to RLS; no service role or table-owner mutation is involved.

do $role$
begin
  if not exists (select 1 from pg_catalog.pg_roles where rolname = 'company_access_executor') then
    create role company_access_executor nologin noinherit nobypassrls;
  end if;
end
$role$;

create table if not exists public.company_access_command_receipts (
  operation_id uuid primary key,
  command_name text not null check (command_name in (
    'create_invitation', 'accept_invitation', 'revoke_invitation',
    'resend_invitation', 'administer_membership'
  )),
  actor_id uuid not null references auth.users(id) on delete cascade,
  company_id uuid not null references public.companies(id) on delete cascade,
  invitation_id uuid references public.company_invitations(id) on delete cascade,
  request_fingerprint text not null,
  result jsonb not null,
  delivery_token text,
  expires_at timestamptz not null,
  created_at timestamptz not null default now()
);

alter table public.company_access_command_receipts enable row level security;
alter table public.company_access_command_receipts force row level security;

create or replace function public.company_access_is_accepted_owner(p_company_id uuid)
returns boolean
language sql
stable
security definer
set search_path = ''
as $function$
  select exists (
    select 1
    from public.company_memberships m
    where m.company_id = p_company_id
      and m.user_id = (select auth.uid())
      and m.role = 'owner'
      and m.accepted_at is not null
  );
$function$;

-- pgcrypto is installed in `extensions` on Supabase and commonly in `public`
-- in fresh PostgreSQL. Resolve its catalog-owned extension schema explicitly
-- while retaining an empty function search path.
create or replace function public.company_access_token_hash(p_token text)
returns text
language plpgsql
stable
security invoker
set search_path = ''
as $function$
declare
  v_extension_schema text;
  v_hash text;
begin
  select n.nspname into v_extension_schema
  from pg_catalog.pg_extension e
  join pg_catalog.pg_namespace n on n.oid = e.extnamespace
  where e.extname = 'pgcrypto';
  if v_extension_schema is null then
    raise exception 'company_access_unavailable' using errcode = 'P0001';
  end if;
  execute pg_catalog.format(
    'select pg_catalog.encode(%I.digest(pg_catalog.convert_to($1, ''UTF8''), ''sha256''), ''hex'')',
    v_extension_schema
  ) into v_hash using p_token;
  return v_hash;
end;
$function$;

drop policy if exists "users can read their memberships" on public.company_memberships;
drop policy if exists "members and accepted owners can read company memberships" on public.company_memberships;
create policy "members and accepted owners can read company memberships"
on public.company_memberships for select
to authenticated
using (
  user_id = (select auth.uid())
  or public.company_access_is_accepted_owner(company_id)
);

drop policy if exists "company access commands read companies" on public.companies;
create policy "company access commands read companies"
on public.companies for select
to company_access_executor
using (
  public.company_access_is_accepted_owner(id)
  or exists (
    select 1 from public.company_invitations i
    where i.company_id = companies.id
      and i.invited_email = lower(coalesce((select auth.jwt()) ->> 'email', ''))
  )
);

drop policy if exists "company access commands read invitations" on public.company_invitations;
create policy "company access commands read invitations"
on public.company_invitations for select
to company_access_executor
using (
  public.company_access_is_accepted_owner(company_id)
  or invited_email = lower(coalesce((select auth.jwt()) ->> 'email', ''))
);

drop policy if exists "company access commands create invitations" on public.company_invitations;
create policy "company access commands create invitations"
on public.company_invitations for insert
to company_access_executor
with check (
  invited_by = (select auth.uid())
  and role in ('reviewer', 'read_only')
  and status = 'pending'
  and coalesce((select auth.jwt()) ->> 'aal', '') = 'aal2'
  and public.company_access_is_accepted_owner(company_id)
);

drop policy if exists "company access commands update invitations" on public.company_invitations;
create policy "company access commands update invitations"
on public.company_invitations for update
to company_access_executor
using (
  (
    coalesce((select auth.jwt()) ->> 'aal', '') = 'aal2'
    and public.company_access_is_accepted_owner(company_id)
  )
  or invited_email = lower(coalesce((select auth.jwt()) ->> 'email', ''))
)
with check (
  role in ('reviewer', 'read_only')
  and (
    (
      coalesce((select auth.jwt()) ->> 'aal', '') = 'aal2'
      and public.company_access_is_accepted_owner(company_id)
    )
    or (
      invited_email = lower(coalesce((select auth.jwt()) ->> 'email', ''))
      and accepted_by = (select auth.uid())
      and status = 'accepted'
    )
  )
);

drop policy if exists "company access commands read memberships" on public.company_memberships;
create policy "company access commands read memberships"
on public.company_memberships for select
to company_access_executor
using (
  user_id = (select auth.uid())
  or public.company_access_is_accepted_owner(company_id)
);

drop policy if exists "company access commands accept memberships" on public.company_memberships;
create policy "company access commands accept memberships"
on public.company_memberships for insert
to company_access_executor
with check (
  user_id = (select auth.uid())
  and role in ('reviewer', 'read_only')
  and accepted_at is not null
  and exists (
    select 1 from public.company_invitations i
    where i.company_id = company_memberships.company_id
      and i.role = company_memberships.role
      and i.invited_email = lower(coalesce((select auth.jwt()) ->> 'email', ''))
      and i.status = 'pending'
      and i.expires_at > statement_timestamp()
  )
);

drop policy if exists "company access commands update memberships" on public.company_memberships;
create policy "company access commands update memberships"
on public.company_memberships for update
to company_access_executor
using (
  role in ('reviewer', 'read_only')
  and accepted_at is not null
  and coalesce((select auth.jwt()) ->> 'aal', '') = 'aal2'
  and public.company_access_is_accepted_owner(company_id)
)
with check (
  role in ('reviewer', 'read_only')
  and accepted_at is not null
  and coalesce((select auth.jwt()) ->> 'aal', '') = 'aal2'
  and public.company_access_is_accepted_owner(company_id)
);

drop policy if exists "company access commands remove memberships" on public.company_memberships;
create policy "company access commands remove memberships"
on public.company_memberships for delete
to company_access_executor
using (
  role in ('reviewer', 'read_only')
  and accepted_at is not null
  and coalesce((select auth.jwt()) ->> 'aal', '') = 'aal2'
  and public.company_access_is_accepted_owner(company_id)
);

drop policy if exists "company access commands read receipts" on public.company_access_command_receipts;
create policy "company access commands read receipts"
on public.company_access_command_receipts for select
to company_access_executor
using (
  actor_id = (select auth.uid())
  or public.company_access_is_accepted_owner(company_id)
);

drop policy if exists "company access commands create receipts" on public.company_access_command_receipts;
create policy "company access commands create receipts"
on public.company_access_command_receipts for insert
to company_access_executor
with check (actor_id = (select auth.uid()));

drop policy if exists "company access commands clear receipt tokens" on public.company_access_command_receipts;
create policy "company access commands clear receipt tokens"
on public.company_access_command_receipts for update
to company_access_executor
using (
  actor_id = (select auth.uid())
  or public.company_access_is_accepted_owner(company_id)
  or exists (
    select 1 from public.company_invitations i
    where i.id = company_access_command_receipts.invitation_id
      and i.invited_email = lower(coalesce((select auth.jwt()) ->> 'email', ''))
  )
)
with check (delivery_token is null);

create or replace function public.company_access_create_invitation(
  p_operation_id uuid,
  p_company_id uuid,
  p_invited_email text,
  p_role text,
  p_token_hash text,
  p_acceptance_token text
)
returns table (
  id uuid, company_id uuid, invited_email text, role text, status text,
  expires_at timestamptz, created_at timestamptz, updated_at timestamptz,
  delivery_token text
)
language plpgsql
security definer
set search_path = ''
as $function$
declare
  v_actor_id uuid := auth.uid();
  v_email text := lower(btrim(p_invited_email));
  v_fingerprint text := pg_catalog.concat_ws('|', p_company_id::text, v_email, p_role);
  v_invitation public.company_invitations%rowtype;
  v_receipt public.company_access_command_receipts%rowtype;
  v_now timestamptz := statement_timestamp();
begin
  perform pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended(p_operation_id::text, 160));
  select r.* into v_receipt from public.company_access_command_receipts r
  where r.operation_id = p_operation_id;
  if found then
    if v_receipt.command_name <> 'create_invitation'
       or v_receipt.actor_id <> v_actor_id
       or v_receipt.company_id <> p_company_id
       or v_receipt.request_fingerprint <> v_fingerprint then
      raise exception 'company_access_invalid_request' using errcode = 'P0001';
    end if;
    return query select
      (v_receipt.result ->> 'id')::uuid,
      (v_receipt.result ->> 'company_id')::uuid,
      v_receipt.result ->> 'invited_email', v_receipt.result ->> 'role',
      v_receipt.result ->> 'status', (v_receipt.result ->> 'expires_at')::timestamptz,
      (v_receipt.result ->> 'created_at')::timestamptz,
      (v_receipt.result ->> 'updated_at')::timestamptz, v_receipt.delivery_token;
    return;
  end if;
  if v_actor_id is null
     or coalesce(auth.jwt() ->> 'aal', '') <> 'aal2'
     or not public.company_access_is_accepted_owner(p_company_id) then
    raise exception 'company_access_not_found' using errcode = 'P0001';
  end if;
  if p_role not in ('reviewer', 'read_only')
     or v_email !~ '^[^@[:space:]]+@[^@[:space:]]+\.[^@[:space:]]+$'
     or p_token_hash !~ '^[0-9a-f]{64}$'
     or public.company_access_token_hash(p_acceptance_token) <> p_token_hash then
    raise exception 'company_access_invalid_request' using errcode = 'P0001';
  end if;
  perform pg_catalog.pg_advisory_xact_lock(
    pg_catalog.hashtextextended(p_company_id::text || '|' || v_email, 160)
  );
  if exists (
    select 1 from public.company_invitations i
    where i.company_id = p_company_id and i.invited_email = v_email
      and i.status = 'pending' and i.expires_at > v_now
  ) then
    raise exception 'company_access_conflict' using errcode = 'P0001';
  end if;
  update public.company_invitations i
  set status = 'expired', updated_at = v_now
  where i.company_id = p_company_id and i.invited_email = v_email
    and i.status = 'pending' and i.expires_at <= v_now;

  insert into public.company_invitations (
    company_id, invited_email, role, token_hash, status, expires_at,
    invited_by, delivery_events, updated_at
  ) values (
    p_company_id, v_email, p_role, p_token_hash, 'pending', v_now + interval '14 days',
    v_actor_id,
    jsonb_build_array(jsonb_build_object(
      'channel', 'email', 'status', 'queued', 'template', 'workspace_invitation',
      'recipientEmail', v_email, 'queuedAt', v_now
    )),
    v_now
  ) returning * into v_invitation;

  insert into public.company_access_command_receipts (
    operation_id, command_name, actor_id, company_id, invitation_id,
    request_fingerprint, result, delivery_token, expires_at
  ) values (
    p_operation_id, 'create_invitation', v_actor_id, p_company_id, v_invitation.id,
    v_fingerprint,
    pg_catalog.jsonb_build_object(
      'id', v_invitation.id, 'company_id', v_invitation.company_id,
      'invited_email', v_invitation.invited_email, 'role', v_invitation.role,
      'status', v_invitation.status, 'expires_at', v_invitation.expires_at,
      'created_at', v_invitation.created_at, 'updated_at', v_invitation.updated_at
    ),
    p_acceptance_token, v_invitation.expires_at
  );

  return query select
    v_invitation.id, v_invitation.company_id, v_invitation.invited_email,
    v_invitation.role, v_invitation.status, v_invitation.expires_at,
    v_invitation.created_at, v_invitation.updated_at, p_acceptance_token;
end;
$function$;

create or replace function public.company_access_lookup_invitation(
  p_token_hash text,
  p_verified_subject uuid,
  p_verified_email text
)
returns table (
  id uuid, company_id uuid, company_name text, invited_email text, role text,
  status text, expires_at timestamptz, created_at timestamptz, updated_at timestamptz
)
language sql
stable
security definer
set search_path = ''
as $function$
  select
    i.id, i.company_id, c.name, i.invited_email, i.role, i.status,
    i.expires_at, i.created_at, i.updated_at
  from public.company_invitations i
  join public.companies c on c.id = i.company_id
  where p_verified_subject = auth.uid()
    and lower(btrim(p_verified_email)) = lower(coalesce(auth.jwt() ->> 'email', ''))
    and i.token_hash = p_token_hash
    and i.invited_email = lower(btrim(p_verified_email))
    and i.status = 'pending'
    and i.expires_at > statement_timestamp();
$function$;

create or replace function public.company_access_accept_invitation(
  p_operation_id uuid,
  p_token_hash text,
  p_verified_subject uuid,
  p_verified_email text
)
returns table (company_id uuid, user_id uuid, role text, state text, accepted_at timestamptz)
language plpgsql
security definer
set search_path = ''
as $function$
declare
  v_actor_id uuid := auth.uid();
  v_email text := lower(btrim(p_verified_email));
  v_fingerprint text := pg_catalog.concat_ws('|', p_token_hash, p_verified_subject::text, v_email);
  v_invitation public.company_invitations%rowtype;
  v_receipt public.company_access_command_receipts%rowtype;
  v_now timestamptz := statement_timestamp();
begin
  perform pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended(p_operation_id::text, 160));
  select r.* into v_receipt from public.company_access_command_receipts r
  where r.operation_id = p_operation_id;
  if found then
    if v_receipt.command_name <> 'accept_invitation'
       or v_receipt.actor_id <> v_actor_id
       or v_receipt.request_fingerprint <> v_fingerprint then
      raise exception 'invitation_not_found' using errcode = 'P0001';
    end if;
    return query select
      (v_receipt.result ->> 'company_id')::uuid,
      (v_receipt.result ->> 'user_id')::uuid,
      v_receipt.result ->> 'role', v_receipt.result ->> 'state',
      (v_receipt.result ->> 'accepted_at')::timestamptz;
    return;
  end if;
  if v_actor_id is null
     or p_verified_subject <> auth.uid()
     or v_email = ''
     or v_email <> lower(coalesce(auth.jwt() ->> 'email', '')) then
    raise exception 'invitation_not_found' using errcode = 'P0001';
  end if;
  select i.* into v_invitation
  from public.company_invitations i
  where i.token_hash = p_token_hash and i.invited_email = v_email
    and i.status = 'pending' and i.expires_at > v_now
  for update;
  if not found or v_invitation.role not in ('reviewer', 'read_only')
     or exists (
       select 1 from public.company_memberships m
       where m.company_id = v_invitation.company_id and m.user_id = v_actor_id
     ) then
    raise exception 'invitation_not_found' using errcode = 'P0001';
  end if;
  insert into public.company_memberships (company_id, user_id, role, invited_by, accepted_at)
  values (v_invitation.company_id, v_actor_id, v_invitation.role, v_invitation.invited_by, v_now);
  update public.company_invitations i
  set invited_user_id = v_actor_id, status = 'accepted', accepted_by = v_actor_id,
      accepted_at = v_now, updated_at = v_now
  where i.id = v_invitation.id;
  update public.company_access_command_receipts r
  set delivery_token = null where r.invitation_id = v_invitation.id;
  insert into public.company_access_command_receipts (
    operation_id, command_name, actor_id, company_id, invitation_id,
    request_fingerprint, result, expires_at
  ) values (
    p_operation_id, 'accept_invitation', v_actor_id, v_invitation.company_id,
    v_invitation.id, v_fingerprint,
    pg_catalog.jsonb_build_object(
      'company_id', v_invitation.company_id, 'user_id', v_actor_id,
      'role', v_invitation.role, 'state', 'active', 'accepted_at', v_now
    ),
    v_now + interval '14 days'
  );
  return query select v_invitation.company_id, v_actor_id, v_invitation.role, 'active'::text, v_now;
end;
$function$;

create or replace function public.company_access_revoke_invitation(
  p_operation_id uuid,
  p_company_id uuid,
  p_invitation_id uuid,
  p_expected_updated_at timestamptz
)
returns table (
  id uuid, company_id uuid, invited_email text, role text, status text,
  expires_at timestamptz, created_at timestamptz, updated_at timestamptz
)
language plpgsql
security definer
set search_path = ''
as $function$
declare
  v_actor_id uuid := auth.uid();
  v_fingerprint text := pg_catalog.concat_ws('|', p_company_id::text, p_invitation_id::text, p_expected_updated_at::text);
  v_invitation public.company_invitations%rowtype;
  v_receipt public.company_access_command_receipts%rowtype;
  v_now timestamptz := statement_timestamp();
begin
  perform pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended(p_operation_id::text, 160));
  select r.* into v_receipt from public.company_access_command_receipts r where r.operation_id = p_operation_id;
  if found then
    if v_receipt.command_name <> 'revoke_invitation' or v_receipt.actor_id <> v_actor_id
       or v_receipt.company_id <> p_company_id or v_receipt.request_fingerprint <> v_fingerprint then
      raise exception 'company_access_invalid_request' using errcode = 'P0001';
    end if;
    return query select
      (v_receipt.result ->> 'id')::uuid, (v_receipt.result ->> 'company_id')::uuid,
      v_receipt.result ->> 'invited_email', v_receipt.result ->> 'role',
      v_receipt.result ->> 'status', (v_receipt.result ->> 'expires_at')::timestamptz,
      (v_receipt.result ->> 'created_at')::timestamptz,
      (v_receipt.result ->> 'updated_at')::timestamptz;
    return;
  end if;
  if v_actor_id is null or coalesce(auth.jwt() ->> 'aal', '') <> 'aal2'
     or not public.company_access_is_accepted_owner(p_company_id) then
    raise exception 'company_access_not_found' using errcode = 'P0001';
  end if;
  select i.* into v_invitation from public.company_invitations i
  where i.id = p_invitation_id and i.company_id = p_company_id and i.status = 'pending'
  for update;
  if not found then raise exception 'company_access_not_found' using errcode = 'P0001'; end if;
  if v_invitation.updated_at <> p_expected_updated_at then
    raise exception 'company_access_conflict' using errcode = 'P0001';
  end if;
  update public.company_invitations i
  set status = 'revoked', revoked_by = v_actor_id, revoked_at = v_now, updated_at = v_now
  where i.id = v_invitation.id returning * into v_invitation;
  update public.company_access_command_receipts r set delivery_token = null
  where r.invitation_id = v_invitation.id;
  insert into public.company_access_command_receipts (
    operation_id, command_name, actor_id, company_id, invitation_id,
    request_fingerprint, result, expires_at
  ) values (
    p_operation_id, 'revoke_invitation', v_actor_id, p_company_id, v_invitation.id,
    v_fingerprint,
    pg_catalog.jsonb_build_object(
      'id', v_invitation.id, 'company_id', v_invitation.company_id,
      'invited_email', v_invitation.invited_email, 'role', v_invitation.role,
      'status', v_invitation.status, 'expires_at', v_invitation.expires_at,
      'created_at', v_invitation.created_at, 'updated_at', v_invitation.updated_at
    ),
    v_now + interval '14 days'
  );
  return query select v_invitation.id, v_invitation.company_id, v_invitation.invited_email,
    v_invitation.role, v_invitation.status, v_invitation.expires_at,
    v_invitation.created_at, v_invitation.updated_at;
end;
$function$;

create or replace function public.company_access_resend_invitation(
  p_operation_id uuid,
  p_company_id uuid,
  p_invitation_id uuid,
  p_expected_updated_at timestamptz,
  p_token_hash text,
  p_acceptance_token text
)
returns table (
  id uuid, company_id uuid, invited_email text, role text, status text,
  expires_at timestamptz, created_at timestamptz, updated_at timestamptz,
  delivery_token text
)
language plpgsql
security definer
set search_path = ''
as $function$
declare
  v_actor_id uuid := auth.uid();
  v_fingerprint text := pg_catalog.concat_ws('|', p_company_id::text, p_invitation_id::text, p_expected_updated_at::text);
  v_invitation public.company_invitations%rowtype;
  v_receipt public.company_access_command_receipts%rowtype;
  v_now timestamptz := statement_timestamp();
begin
  perform pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended(p_operation_id::text, 160));
  select r.* into v_receipt from public.company_access_command_receipts r where r.operation_id = p_operation_id;
  if found then
    if v_receipt.command_name <> 'resend_invitation' or v_receipt.actor_id <> v_actor_id
       or v_receipt.company_id <> p_company_id or v_receipt.request_fingerprint <> v_fingerprint then
      raise exception 'company_access_invalid_request' using errcode = 'P0001';
    end if;
    return query select
      (v_receipt.result ->> 'id')::uuid, (v_receipt.result ->> 'company_id')::uuid,
      v_receipt.result ->> 'invited_email', v_receipt.result ->> 'role',
      v_receipt.result ->> 'status', (v_receipt.result ->> 'expires_at')::timestamptz,
      (v_receipt.result ->> 'created_at')::timestamptz,
      (v_receipt.result ->> 'updated_at')::timestamptz, v_receipt.delivery_token;
    return;
  end if;
  if v_actor_id is null or coalesce(auth.jwt() ->> 'aal', '') <> 'aal2'
     or not public.company_access_is_accepted_owner(p_company_id) then
    raise exception 'company_access_not_found' using errcode = 'P0001';
  end if;
  if p_token_hash !~ '^[0-9a-f]{64}$'
     or public.company_access_token_hash(p_acceptance_token) <> p_token_hash then
    raise exception 'company_access_invalid_request' using errcode = 'P0001';
  end if;
  select i.* into v_invitation from public.company_invitations i
  where i.id = p_invitation_id and i.company_id = p_company_id
    and i.status in ('pending', 'revoked', 'expired')
  for update;
  if not found then raise exception 'company_access_not_found' using errcode = 'P0001'; end if;
  if v_invitation.updated_at <> p_expected_updated_at then
    raise exception 'company_access_conflict' using errcode = 'P0001';
  end if;
  update public.company_access_command_receipts r set delivery_token = null
  where r.invitation_id = v_invitation.id;
  update public.company_invitations i
  set token_hash = p_token_hash, status = 'pending', expires_at = v_now + interval '14 days',
      resent_at = v_now, revoked_by = null, revoked_at = null,
      delivery_events = i.delivery_events || pg_catalog.jsonb_build_array(pg_catalog.jsonb_build_object(
        'channel', 'email', 'status', 'queued', 'template', 'workspace_invitation',
        'recipientEmail', i.invited_email, 'queuedAt', v_now
      )), updated_at = v_now
  where i.id = v_invitation.id returning * into v_invitation;
  insert into public.company_access_command_receipts (
    operation_id, command_name, actor_id, company_id, invitation_id,
    request_fingerprint, result, delivery_token, expires_at
  ) values (
    p_operation_id, 'resend_invitation', v_actor_id, p_company_id, v_invitation.id,
    v_fingerprint,
    pg_catalog.jsonb_build_object(
      'id', v_invitation.id, 'company_id', v_invitation.company_id,
      'invited_email', v_invitation.invited_email, 'role', v_invitation.role,
      'status', v_invitation.status, 'expires_at', v_invitation.expires_at,
      'created_at', v_invitation.created_at, 'updated_at', v_invitation.updated_at
    ),
    p_acceptance_token, v_invitation.expires_at
  );
  return query select v_invitation.id, v_invitation.company_id, v_invitation.invited_email,
    v_invitation.role, v_invitation.status, v_invitation.expires_at,
    v_invitation.created_at, v_invitation.updated_at, p_acceptance_token;
end;
$function$;

create or replace function public.company_access_administer_membership(
  p_operation_id uuid,
  p_company_id uuid,
  p_user_id uuid,
  p_expected_role text,
  p_role text,
  p_state text
)
returns table (company_id uuid, user_id uuid, role text, state text, accepted_at timestamptz)
language plpgsql
security definer
set search_path = ''
as $function$
declare
  v_actor_id uuid := auth.uid();
  v_fingerprint text := pg_catalog.concat_ws('|', p_company_id::text, p_user_id::text, p_expected_role, p_role, p_state);
  v_membership public.company_memberships%rowtype;
  v_receipt public.company_access_command_receipts%rowtype;
  v_result_role text;
begin
  perform pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended(p_operation_id::text, 160));
  select r.* into v_receipt from public.company_access_command_receipts r where r.operation_id = p_operation_id;
  if found then
    if v_receipt.command_name <> 'administer_membership' or v_receipt.actor_id <> v_actor_id
       or v_receipt.company_id <> p_company_id or v_receipt.request_fingerprint <> v_fingerprint then
      raise exception 'company_access_invalid_request' using errcode = 'P0001';
    end if;
    return query select
      (v_receipt.result ->> 'company_id')::uuid, (v_receipt.result ->> 'user_id')::uuid,
      v_receipt.result ->> 'role', v_receipt.result ->> 'state',
      (v_receipt.result ->> 'accepted_at')::timestamptz;
    return;
  end if;
  if v_actor_id is null or coalesce(auth.jwt() ->> 'aal', '') <> 'aal2'
     or not public.company_access_is_accepted_owner(p_company_id)
     or p_user_id = v_actor_id or p_expected_role not in ('reviewer', 'read_only')
     or (p_role is not null and p_role not in ('reviewer', 'read_only'))
     or (p_state is not null and p_state not in ('active', 'removed'))
     or (p_role is null and p_state is null) then
    raise exception 'company_access_not_found' using errcode = 'P0001';
  end if;
  select m.* into v_membership from public.company_memberships m
  where m.company_id = p_company_id and m.user_id = p_user_id
    and m.role in ('reviewer', 'read_only') and m.accepted_at is not null
  for update;
  if not found then raise exception 'company_access_not_found' using errcode = 'P0001'; end if;
  if v_membership.role <> p_expected_role then
    raise exception 'company_access_conflict' using errcode = 'P0001';
  end if;
  v_result_role := coalesce(p_role, v_membership.role);
  if p_state = 'removed' then
    delete from public.company_memberships m where m.company_id = p_company_id and m.user_id = p_user_id;
  else
    update public.company_memberships m set role = v_result_role
    where m.company_id = p_company_id and m.user_id = p_user_id;
  end if;
  insert into public.company_access_command_receipts (
    operation_id, command_name, actor_id, company_id, request_fingerprint, result, expires_at
  ) values (
    p_operation_id, 'administer_membership', v_actor_id, p_company_id, v_fingerprint,
    pg_catalog.jsonb_build_object(
      'company_id', p_company_id, 'user_id', p_user_id, 'role', v_result_role,
      'state', case when p_state = 'removed' then 'removed' else 'active' end,
      'accepted_at', v_membership.accepted_at
    ),
    statement_timestamp() + interval '14 days'
  );
  return query select p_company_id, p_user_id, v_result_role,
    case when p_state = 'removed' then 'removed'::text else 'active'::text end,
    v_membership.accepted_at;
end;
$function$;

grant usage on schema public, auth to company_access_executor;
grant select on public.companies to company_access_executor;
grant select, insert, update on public.company_invitations to company_access_executor;
grant select, insert, update, delete on public.company_memberships to company_access_executor;
grant select, insert, update on public.company_access_command_receipts to company_access_executor;
grant execute on function auth.uid(), auth.jwt() to company_access_executor;
grant execute on function public.company_access_is_accepted_owner(uuid) to company_access_executor;
grant execute on function public.company_access_token_hash(text) to company_access_executor;

alter function public.company_access_create_invitation(uuid, uuid, text, text, text, text)
  owner to company_access_executor;
alter function public.company_access_lookup_invitation(text, uuid, text)
  owner to company_access_executor;
alter function public.company_access_accept_invitation(uuid, text, uuid, text)
  owner to company_access_executor;
alter function public.company_access_revoke_invitation(uuid, uuid, uuid, timestamptz)
  owner to company_access_executor;
alter function public.company_access_resend_invitation(uuid, uuid, uuid, timestamptz, text, text)
  owner to company_access_executor;
alter function public.company_access_administer_membership(uuid, uuid, uuid, text, text, text)
  owner to company_access_executor;

revoke all on table public.company_access_command_receipts from public, anon, authenticated;
revoke all on function public.company_access_is_accepted_owner(uuid) from public, anon;
revoke all on function public.company_access_token_hash(text) from public, anon, authenticated;
revoke all on function public.company_access_create_invitation(uuid, uuid, text, text, text, text) from public, anon;
revoke all on function public.company_access_lookup_invitation(text, uuid, text) from public, anon;
revoke all on function public.company_access_accept_invitation(uuid, text, uuid, text) from public, anon;
revoke all on function public.company_access_revoke_invitation(uuid, uuid, uuid, timestamptz) from public, anon;
revoke all on function public.company_access_resend_invitation(uuid, uuid, uuid, timestamptz, text, text) from public, anon;
revoke all on function public.company_access_administer_membership(uuid, uuid, uuid, text, text, text) from public, anon;

grant execute on function public.company_access_is_accepted_owner(uuid) to authenticated;
grant execute on function public.company_access_create_invitation(uuid, uuid, text, text, text, text) to authenticated;
grant execute on function public.company_access_lookup_invitation(text, uuid, text) to authenticated;
grant execute on function public.company_access_accept_invitation(uuid, text, uuid, text) to authenticated;
grant execute on function public.company_access_revoke_invitation(uuid, uuid, uuid, timestamptz) to authenticated;
grant execute on function public.company_access_resend_invitation(uuid, uuid, uuid, timestamptz, text, text) to authenticated;
grant execute on function public.company_access_administer_membership(uuid, uuid, uuid, text, text, text) to authenticated;
