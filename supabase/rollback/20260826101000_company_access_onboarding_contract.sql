-- Phase-aware rollback for the staged #138 company-access contract artifact.
-- This restores the immediately preceding overlap authority without deleting
-- companies, memberships, agreements, audit rows, or durable command receipts.
-- It is replay-safe and may be followed by the contract artifact for recutover.

begin;

do $membership$
begin
  execute pg_catalog.format(
    'grant company_access_executor, company_access_recovery_executor, company_archive_projection_executor to %I',
    current_user
  );
end
$membership$;

do $archive_seam$
declare
  v_definition text;
begin
  if pg_catalog.to_regprocedure(
    'public.company_archive_begin_export(uuid,integer)'
  ) is not null then
    grant create on schema public to company_archive_projection_executor;
    select pg_catalog.pg_get_functiondef(
      'public.company_archive_begin_export(uuid,integer)'::regprocedure
    ) into v_definition;
    v_definition := pg_catalog.replace(
      v_definition,
      'public.company_archive_authenticated_uid_v1()',
      'public.company_access_auth_uid_v1()'
    );
    v_definition := pg_catalog.replace(
      v_definition,
      'public.company_archive_authenticated_has_fresh_mfa_v1()',
      'public.company_access_has_fresh_mfa_v1()'
    );
    v_definition := pg_catalog.replace(
      v_definition,
      'public.company_archive_authenticated_owner_v1(p_company_id)',
      'public.company_access_is_accepted_owner_v1(p_company_id)'
    );
    execute 'set local role company_archive_projection_executor';
    execute v_definition;
    execute 'reset role';
    revoke create on schema public from company_archive_projection_executor;
  end if;
end
$archive_seam$;

create or replace function public.company_access_auth_uid_v1()
returns uuid
language sql
stable
security definer
set search_path = ''
as $function$
  select coalesce(
    nullif(pg_catalog.current_setting('talli.verified_actor_id', true), '')::uuid,
    auth.uid()
  );
$function$;

create or replace function public.company_access_auth_jwt_v1()
returns jsonb
language sql
stable
security definer
set search_path = ''
as $function$
  select case
    when nullif(pg_catalog.current_setting('talli.verified_actor_id', true), '') is not null
      then public.company_access_verified_claims_v1()
    else auth.jwt()
  end;
$function$;

grant select, insert, update on public.companies to authenticated;
grant select, insert on public.company_memberships to authenticated;
revoke all on public.company_invitations from authenticated;
grant select (
  id, company_id, invited_email, invited_user_id, role, status, expires_at,
  invited_by, accepted_by, accepted_at, revoked_by, revoked_at, resent_at,
  delivery_events, created_at, updated_at
) on public.company_invitations to authenticated;
revoke all on public.company_cancellations from authenticated;
grant select on public.support_operators to authenticated;
grant select on public.customer_agreement_acceptances to authenticated, service_role;

drop policy if exists "company members can create audit events for themselves"
  on public.audit_events;
create policy "company members can create audit events for themselves"
on public.audit_events for insert
to authenticated
with check (
  actor_id = (select auth.uid())
  and (
    exists (
      select 1
      from public.companies c
      where c.id = audit_events.company_id
        and c.created_by = (select auth.uid())
    )
    or exists (
      select 1
      from public.company_memberships m
      where m.company_id = audit_events.company_id
        and m.user_id = (select auth.uid())
    )
  )
);

drop function if exists company_access_policy.authenticated_can_append_audit_v1(uuid, uuid);

drop policy if exists "owners can create companies" on public.companies;
create policy "owners can create companies"
on public.companies for insert
to authenticated
with check (created_by = (select auth.uid()));

drop policy if exists "owners can lock their new company identity" on public.companies;
create policy "owners can lock their new company identity"
on public.companies for update
to authenticated
using (created_by = (select auth.uid()))
with check (created_by = (select auth.uid()));

drop policy if exists "company creator can add owner membership"
  on public.company_memberships;
create policy "company creator can add owner membership"
on public.company_memberships for insert
to authenticated
with check (
  user_id = (select auth.uid())
  and role = 'owner'
  and public.is_company_creator(company_memberships.company_id)
);

drop policy if exists "company members can read companies" on public.companies;
create policy "company members can read companies"
on public.companies for select to authenticated
using (
  created_by = (select auth.uid())
  or exists (
    select 1 from public.support_operators o
    where o.user_id = (select auth.uid()) and o.active
  )
  or exists (
    select 1 from public.company_memberships m
    where m.company_id = companies.id
      and m.user_id = (select auth.uid())
      and m.accepted_at is not null
  )
);

drop policy if exists "members and accepted owners can read company memberships"
  on public.company_memberships;
create policy "members and accepted owners can read company memberships"
on public.company_memberships for select to authenticated
using (
  user_id = (select public.company_access_auth_uid_v1())
  or public.company_access_is_accepted_owner_v1(company_id)
);

drop policy if exists "active operators can read own operator grant"
  on public.support_operators;
create policy "active operators can read own operator grant"
on public.support_operators for select to authenticated
using (user_id = (select auth.uid()) and active);

drop policy if exists "accepted owners can read company invitations"
  on public.company_invitations;
create policy "accepted owners can read company invitations"
on public.company_invitations for select to authenticated
using (public.company_access_is_accepted_owner_v1(company_id));

drop policy if exists "company members can read cancellation state"
  on public.company_cancellations;
drop policy if exists "support operators can read cancellation state"
  on public.company_cancellations;
drop policy if exists "legacy cancellation hides superseded rows"
  on public.company_cancellations;
create policy "legacy cancellation hides superseded rows"
on public.company_cancellations as restrictive for all to authenticated
using (status <> 'superseded')
with check (status <> 'superseded');

drop policy if exists "company members can read customer agreement acceptances"
  on public.customer_agreement_acceptances;
create policy "company members can read customer agreement acceptances"
on public.customer_agreement_acceptances for select to authenticated
using (
  exists (
    select 1 from public.company_memberships m
    where m.company_id = customer_agreement_acceptances.company_id
      and m.user_id = (select auth.uid())
      and m.accepted_at is not null
  )
);

grant execute on function public.company_access_auth_uid_v1(),
  public.company_access_auth_jwt_v1(),
  public.company_access_is_accepted_owner_v1(uuid)
to authenticated;

set role company_access_executor;
grant execute on function public.company_access_create_invitation(uuid,uuid,text,text,text,text),
  public.company_access_lookup_invitation(text,uuid,text),
  public.company_access_accept_invitation(uuid,text,uuid,text),
  public.company_access_revoke_invitation(uuid,uuid,uuid,timestamptz),
  public.company_access_resend_invitation(uuid,uuid,uuid,timestamptz,text,text),
  public.company_access_administer_membership(uuid,uuid,uuid,text,text,text),
  public.company_access_list_cancellations(uuid),
  public.company_access_request_cancellation(uuid,uuid,integer,text),
  public.company_access_resume_cancellation(uuid,uuid,uuid,integer,timestamptz),
  public.company_access_review_deletion(uuid,uuid,uuid,timestamptz,text,text),
  public.company_access_finalize_deletion(uuid,uuid,uuid,timestamptz),
  public.company_access_reconcile_cancellation_operation(uuid,text,uuid,uuid,integer,text,timestamptz,text,text)
to authenticated;
reset role;

set role company_access_recovery_executor;
grant execute on function public.company_access_pending_invitation_side_effects(),
  public.company_access_complete_invitation_side_effect(uuid)
to authenticated;
reset role;

-- Recreate the two frozen legacy facades byte-for-byte for an emergency return
-- to the pre-contract deployment. Recutover drops them again.
create or replace function public.create_company_workspace_with_acceptance(
  p_actor_id uuid,
  p_org_number text,
  p_name text,
  p_entity_type text,
  p_address text,
  p_postal_code text,
  p_city text,
  p_status_text text,
  p_source text,
  p_business_terms_version text,
  p_business_terms_effective_date date,
  p_business_terms_path text,
  p_business_terms_sha256 text,
  p_dpa_version text,
  p_dpa_effective_date date,
  p_dpa_path text,
  p_dpa_sha256 text,
  p_authority_statement_version text,
  p_acceptance_method text
)
returns uuid
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_actor_id uuid := p_actor_id;
  v_company_id uuid;
  v_now timestamptz := now();
begin
  if auth.role() is distinct from 'service_role' then raise exception 'service_role_required'; end if;
  if p_actor_id is null then raise exception 'authenticated_actor_required'; end if;
  if p_org_number is null or p_org_number !~ '^[0-9]{9}$' then raise exception 'invalid_org_number'; end if;
  if p_name is null or p_name = '' then raise exception 'invalid_company_name'; end if;
  if p_entity_type is distinct from 'AS' then raise exception 'unsupported_entity_type'; end if;
  if p_acceptance_method is distinct from 'in_app_clickwrap' then raise exception 'invalid_acceptance_method'; end if;
  if p_authority_statement_version is distinct from 'authority-v1' then raise exception 'invalid_authority_statement'; end if;
  if p_business_terms_version is null or p_business_terms_version = ''
    or p_dpa_version is null or p_dpa_version = '' then
    raise exception 'invalid_contract_version';
  end if;
  if p_business_terms_effective_date is null or p_dpa_effective_date is null then
    raise exception 'invalid_contract_effective_date';
  end if;
  if p_business_terms_path is null or p_business_terms_path = ''
    or p_dpa_path is null or p_dpa_path = '' then
    raise exception 'invalid_contract_path';
  end if;
  if p_business_terms_sha256 is null or p_business_terms_sha256 !~ '^[a-f0-9]{64}$'
    or p_dpa_sha256 is null or p_dpa_sha256 !~ '^[a-f0-9]{64}$' then
    raise exception 'invalid_contract_digest';
  end if;

  insert into public.companies (
    org_number,
    name,
    entity_type,
    address,
    postal_code,
    city,
    status_text,
    source,
    created_by,
    identity_confirmed_at,
    identity_locked_at
  )
  values (
    p_org_number,
    p_name,
    p_entity_type,
    p_address,
    p_postal_code,
    p_city,
    p_status_text,
    p_source,
    v_actor_id,
    v_now,
    v_now
  )
  returning id into v_company_id;

  insert into public.company_memberships (company_id, user_id, role, accepted_at)
  values (v_company_id, v_actor_id, 'owner', v_now);

  insert into public.customer_agreement_acceptances (
    company_id,
    accepted_by,
    customer_legal_name,
    customer_org_number,
    business_terms_version,
    business_terms_effective_date,
    business_terms_path,
    business_terms_sha256,
    dpa_version,
    dpa_effective_date,
    dpa_path,
    dpa_sha256,
    authority_statement_version,
    acceptance_method,
    accepted_at
  )
  values (
    v_company_id,
    v_actor_id,
    p_name,
    p_org_number,
    p_business_terms_version,
    p_business_terms_effective_date,
    p_business_terms_path,
    p_business_terms_sha256,
    p_dpa_version,
    p_dpa_effective_date,
    p_dpa_path,
    p_dpa_sha256,
    p_authority_statement_version,
    'in_app_clickwrap',
    v_now
  );

  insert into public.audit_events (company_id, actor_id, category, action, message)
  values (
    v_company_id,
    v_actor_id,
    'company',
    'workspace_created',
    'Selskapsarbeidsflate opprettet med dokumentert avtaleaksept.'
  );

  return v_company_id;
end;
$$;

revoke all on function public.create_company_workspace_with_acceptance(
  uuid,text,text,text,text,text,text,text,text,text,date,text,text,text,date,text,text,text,text
) from public, anon, authenticated, service_role;
grant execute on function public.create_company_workspace_with_acceptance(
  uuid,text,text,text,text,text,text,text,text,text,date,text,text,text,date,text,text,text,text
) to service_role;

create or replace function public.append_company_agreement_acceptance(
  p_actor_id uuid,
  p_company_id uuid,
  p_business_terms_version text,
  p_business_terms_effective_date date,
  p_business_terms_path text,
  p_business_terms_sha256 text,
  p_dpa_version text,
  p_dpa_effective_date date,
  p_dpa_path text,
  p_dpa_sha256 text,
  p_authority_statement_version text,
  p_acceptance_method text
)
returns uuid
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_acceptance_id uuid;
  v_company_name text;
  v_org_number text;
  v_now timestamptz := now();
begin
  if auth.role() is distinct from 'service_role' then raise exception 'service_role_required'; end if;
  if p_actor_id is null then raise exception 'authenticated_actor_required'; end if;
  if p_company_id is null then raise exception 'invalid_company_id'; end if;
  if p_business_terms_version is distinct from '2026-07-17'
    or p_business_terms_effective_date is distinct from date '2026-07-17'
    or p_business_terms_path is distinct from '/vilkar'
    or p_business_terms_sha256 is distinct from 'f64a7f6a9758389fca8985a883a945d84c849f5b3316944621507db336992543'
    or p_dpa_version is distinct from '2026-07-17'
    or p_dpa_effective_date is distinct from date '2026-07-17'
    or p_dpa_path is distinct from '/databehandleravtale'
    or p_dpa_sha256 is distinct from '083ee63c1917ef227068befd7706ba2d636c52070ed4d880a8efae720528191c'
    or p_authority_statement_version is distinct from 'authority-v1'
    or p_acceptance_method is distinct from 'in_app_clickwrap' then
    raise exception 'stale_or_invalid_agreement_evidence';
  end if;

  if not exists (
    select 1
    from public.company_memberships m
    where m.company_id = p_company_id
      and m.user_id = p_actor_id
      and m.role = 'owner'
      and m.accepted_at is not null
  ) then
    raise exception 'accepted_owner_membership_required';
  end if;

  select c.name, c.org_number
  into v_company_name, v_org_number
  from public.companies c
  where c.id = p_company_id;
  if not found then raise exception 'company_not_found'; end if;

  perform pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended(p_company_id::text, 0));

  select a.id
  into v_acceptance_id
  from public.customer_agreement_acceptances a
  where a.company_id = p_company_id
    and a.business_terms_version = p_business_terms_version
    and a.business_terms_effective_date = p_business_terms_effective_date
    and a.business_terms_path = p_business_terms_path
    and a.business_terms_sha256 = p_business_terms_sha256
    and a.dpa_version = p_dpa_version
    and a.dpa_effective_date = p_dpa_effective_date
    and a.dpa_path = p_dpa_path
    and a.dpa_sha256 = p_dpa_sha256
    and a.authority_statement_version = p_authority_statement_version
    and a.acceptance_method = p_acceptance_method
  order by a.accepted_at desc
  limit 1;
  if v_acceptance_id is not null then return v_acceptance_id; end if;

  insert into public.customer_agreement_acceptances (
    company_id, accepted_by, customer_legal_name, customer_org_number,
    business_terms_version, business_terms_effective_date, business_terms_path, business_terms_sha256,
    dpa_version, dpa_effective_date, dpa_path, dpa_sha256,
    authority_statement_version, acceptance_method, accepted_at
  ) values (
    p_company_id, p_actor_id, v_company_name, v_org_number,
    p_business_terms_version, p_business_terms_effective_date, p_business_terms_path, p_business_terms_sha256,
    p_dpa_version, p_dpa_effective_date, p_dpa_path, p_dpa_sha256,
    p_authority_statement_version, p_acceptance_method, v_now
  ) returning id into v_acceptance_id;

  insert into public.audit_events (company_id, actor_id, category, action, message)
  values (
    p_company_id, p_actor_id, 'company', 'customer_agreement_reaccepted',
    'Oppdatert kundeavtale og databehandleravtale uttrykkelig akseptert.'
  );

  return v_acceptance_id;
end;
$$;

revoke all on function public.append_company_agreement_acceptance(
  uuid,uuid,text,date,text,text,text,date,text,text,text,text
) from public, anon, authenticated, service_role;
grant execute on function public.append_company_agreement_acceptance(
  uuid,uuid,text,date,text,text,text,date,text,text,text,text
) to service_role;

-- The retired table must be empty before contract application. Recreate only
-- its schema for an idempotent rollback; no production path may write it.
create table if not exists public.step_up_events (
  id uuid primary key default gen_random_uuid(),
  actor_id uuid not null references auth.users(id) on delete cascade,
  method text not null default 'mfa'
    check (method in ('mfa', 'webauthn', 'totp', 'recovery')),
  mfa_verified_at timestamptz not null default now(),
  security_review_approved boolean not null default false,
  production_credentials_enabled boolean not null default false,
  created_at timestamptz not null default now()
);
alter table public.step_up_events enable row level security;
revoke all on table public.step_up_events from public, anon, authenticated, service_role;

drop function if exists public.company_archive_authenticated_owner_v1(uuid);
drop function if exists public.company_archive_authenticated_uid_v1();
drop function if exists public.company_archive_authenticated_has_fresh_mfa_v1();

do $membership$
begin
  execute pg_catalog.format(
    'revoke company_access_executor, company_access_recovery_executor, company_archive_projection_executor from %I',
    current_user
  );
end
$membership$;

commit;
