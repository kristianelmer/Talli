-- A step-up record must be derived from Supabase Auth's signed AAL2 JWT, not
-- from user-supplied timestamps or privilege flags.
create schema if not exists private;
revoke all on schema private from public, anon;
grant usage on schema private to authenticated;

update public.step_up_events
set security_review_approved = false,
    production_credentials_enabled = false
where security_review_approved or production_credentials_enabled;

create or replace function private.current_totp_verified_at()
returns timestamptz
language sql
stable
security invoker
set search_path = ''
as $$
  select max(to_timestamp((entry ->> 'timestamp')::double precision))
  from jsonb_array_elements(coalesce((select auth.jwt()) -> 'amr', '[]'::jsonb)) as entry
  where entry ->> 'method' = 'totp';
$$;

revoke all on function private.current_totp_verified_at() from public, anon;
grant execute on function private.current_totp_verified_at() to authenticated;

drop policy if exists "users can create their own step up events" on public.step_up_events;
create policy "users can record signed recent totp step up"
on public.step_up_events for insert
to authenticated
with check (
  actor_id = (select auth.uid())
  and method = 'totp'
  and not security_review_approved
  and not production_credentials_enabled
  and (select auth.jwt() ->> 'aal') = 'aal2'
  and mfa_verified_at = (select private.current_totp_verified_at())
  and mfa_verified_at >= now() - interval '15 minutes'
  and mfa_verified_at <= now() + interval '1 minute'
);

create or replace function public.record_mfa_step_up()
returns setof public.step_up_events
language plpgsql
volatile
security invoker
set search_path = ''
as $$
declare
  verified_at timestamptz := private.current_totp_verified_at();
begin
  if (select auth.uid()) is null
    or (select auth.jwt() ->> 'aal') <> 'aal2'
    or verified_at is null
    or verified_at < now() - interval '15 minutes'
    or verified_at > now() + interval '1 minute'
  then
    raise exception 'A recent signed TOTP verification is required.' using errcode = '42501';
  end if;

  return query
  insert into public.step_up_events (
    actor_id,
    method,
    mfa_verified_at,
    security_review_approved,
    production_credentials_enabled
  )
  values (
    (select auth.uid()),
    'totp',
    verified_at,
    false,
    false
  )
  returning *;
end;
$$;

revoke all on function public.record_mfa_step_up() from public, anon;
grant execute on function public.record_mfa_step_up() to authenticated;

create table if not exists public.production_security_grants (
  actor_id uuid primary key references auth.users(id) on delete cascade,
  security_review_approved boolean not null default false,
  production_credentials_enabled boolean not null default false,
  approved_by uuid not null references auth.users(id) on delete restrict,
  approved_at timestamptz not null default now(),
  expires_at timestamptz not null,
  revoked_at timestamptz,
  updated_at timestamptz not null default now(),
  check (expires_at > approved_at),
  check (actor_id <> approved_by)
);

alter table public.production_security_grants enable row level security;

grant select, insert, update on public.production_security_grants to authenticated;

drop policy if exists "users and admins can read production security grants" on public.production_security_grants;
create policy "users and admins can read production security grants"
on public.production_security_grants for select
to authenticated
using (
  actor_id = (select auth.uid())
  or exists (
    select 1
    from public.support_operators operator
    where operator.user_id = (select auth.uid())
      and operator.role = 'admin'
      and operator.active
  )
);

drop policy if exists "admins can create production security grants" on public.production_security_grants;
create policy "admins can create production security grants"
on public.production_security_grants for insert
to authenticated
with check (
  approved_by = (select auth.uid())
  and actor_id <> (select auth.uid())
  and exists (
    select 1
    from public.support_operators operator
    where operator.user_id = (select auth.uid())
      and operator.role = 'admin'
      and operator.active
  )
);

drop policy if exists "admins can update production security grants" on public.production_security_grants;
create policy "admins can update production security grants"
on public.production_security_grants for update
to authenticated
using (
  exists (
    select 1
    from public.support_operators operator
    where operator.user_id = (select auth.uid())
      and operator.role = 'admin'
      and operator.active
  )
)
with check (
  approved_by = (select auth.uid())
  and actor_id <> (select auth.uid())
  and exists (
    select 1
    from public.support_operators operator
    where operator.user_id = (select auth.uid())
      and operator.role = 'admin'
      and operator.active
  )
);

create index if not exists production_security_grants_active_idx
on public.production_security_grants(actor_id, expires_at)
where revoked_at is null;

-- Move the two legacy RLS helpers out of the exposed public schema and remove
-- their default PUBLIC execute privilege.
create or replace function private.is_company_creator(target_company_id uuid)
returns boolean
language sql
security definer
set search_path = ''
as $$
  select exists (
    select 1
    from public.companies company
    where company.id = target_company_id
      and company.created_by = (select auth.uid())
  );
$$;

create or replace function private.can_accept_company_invitation(target_company_id uuid, target_role text)
returns boolean
language sql
security definer
set search_path = ''
as $$
  select exists (
    select 1
    from public.company_invitations invitation
    where invitation.company_id = target_company_id
      and invitation.role = target_role
      and invitation.status = 'pending'
      and invitation.expires_at > now()
      and invitation.invited_email = lower(coalesce((select auth.jwt()) ->> 'email', ''))
  );
$$;

revoke all on function private.is_company_creator(uuid) from public, anon;
revoke all on function private.can_accept_company_invitation(uuid, text) from public, anon;
grant execute on function private.is_company_creator(uuid) to authenticated;
grant execute on function private.can_accept_company_invitation(uuid, text) to authenticated;

drop policy if exists "company creator can add owner membership" on public.company_memberships;
create policy "company creator can add owner membership"
on public.company_memberships for insert
to authenticated
with check (
  user_id = (select auth.uid())
  and role = 'owner'
  and (select private.is_company_creator(company_memberships.company_id))
);

drop policy if exists "owners can invite company members" on public.company_memberships;
create policy "owners can invite company members"
on public.company_memberships for insert
to authenticated
with check (
  role in ('reviewer', 'read_only')
  and invited_by = (select auth.uid())
  and (select private.is_company_creator(company_memberships.company_id))
);

drop policy if exists "invited users can accept company memberships" on public.company_memberships;
create policy "invited users can accept company memberships"
on public.company_memberships for insert
to authenticated
with check (
  user_id = (select auth.uid())
  and role in ('reviewer', 'read_only')
  and accepted_at is not null
  and (select private.can_accept_company_invitation(company_memberships.company_id, company_memberships.role))
);

drop function if exists public.is_company_creator(uuid);
drop function if exists public.can_accept_company_invitation(uuid, text);
