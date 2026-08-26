-- EXPAND/MIGRATE: company-access onboarding and agreement acceptance.
--
-- The legacy service-role RPCs intentionally remain callable during the
-- generated-client deployment overlap. The reviewed contract artifact at
-- ../contract-migrations/20260826101000_company_access_onboarding_contract.sql
-- removes that old surface only after the backend/web cutover is proven.

alter role company_access_executor nologin noinherit nobypassrls;

-- The deployer enables LOGIN and installs the password out-of-band. Keeping
-- the checked-in role NOLOGIN by default avoids embedding a credential while
-- giving the backend one durable, auditable principal whose only authority is
-- to SET (never inherit) the two restricted company-access executors.
do $backend_login$
begin
  if not exists (
    select 1 from pg_catalog.pg_roles
    where rolname = 'talli_company_access_backend'
  ) then
    create role talli_company_access_backend nologin noinherit nobypassrls;
  end if;
end
$backend_login$;

alter role talli_company_access_backend noinherit nobypassrls;
grant company_access_executor, company_access_recovery_executor
  to talli_company_access_backend
  with inherit false, set true;

-- Normalize the predecessor overlap ACL to the intent of its reviewed
-- invitation/cancellation contracts. Those functions are owned by the
-- restricted executor roles, so the migration owner must SET ROLE to remove
-- any default PUBLIC execute privilege left by an older deployer and retain
-- only the authenticated overlap surface.
do $overlap_membership$
begin
  execute pg_catalog.format(
    'grant company_access_executor, company_access_recovery_executor to %I',
    current_user
  );
end
$overlap_membership$;

set role company_access_executor;
revoke all on function
  public.company_access_create_invitation(uuid,uuid,text,text,text,text),
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
  public.company_access_reconcile_cancellation_operation(
    uuid,text,uuid,uuid,integer,text,timestamptz,text,text
  )
from public, anon, authenticated, service_role;
grant execute on function
  public.company_access_create_invitation(uuid,uuid,text,text,text,text),
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
  public.company_access_reconcile_cancellation_operation(
    uuid,text,uuid,uuid,integer,text,timestamptz,text,text
  )
to authenticated;
reset role;

set role company_access_recovery_executor;
revoke all on function
  public.company_access_pending_invitation_side_effects(),
  public.company_access_complete_invitation_side_effect(uuid)
from public, anon, authenticated, service_role;
grant execute on function
  public.company_access_pending_invitation_side_effects(),
  public.company_access_complete_invitation_side_effect(uuid)
to authenticated;
reset role;

do $overlap_membership$
begin
  execute pg_catalog.format(
    'revoke company_access_executor, company_access_recovery_executor from %I',
    current_user
  );
end
$overlap_membership$;

create or replace function public.company_access_verified_claims_v1()
returns jsonb
language sql
stable
security definer
set search_path = ''
as $function$
  select coalesce(
    nullif(pg_catalog.current_setting('talli.verified_actor_claims', true), '')::jsonb,
    '{}'::jsonb
  );
$function$;

-- During the generated-client overlap the versioned policy seam accepts either
-- verified backend context or the legacy Data API Auth context. The staged
-- contract artifact removes the latter branch after browser cutover evidence.
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

revoke all on function public.company_access_verified_claims_v1()
  from public, anon, authenticated, service_role;
grant execute on function public.company_access_verified_claims_v1()
  to company_access_executor, company_access_recovery_executor;

alter table public.company_access_command_receipts
  drop constraint if exists company_access_command_receipts_command_name_check;
alter table public.company_access_command_receipts
  add constraint company_access_command_receipts_command_name_check check (command_name in (
    'create_invitation', 'accept_invitation', 'revoke_invitation',
    'resend_invitation', 'administer_membership', 'request_cancellation',
    'resume_cancellation', 'review_deletion', 'finalize_deletion',
    'onboard_company', 'reaccept_agreement'
  ));

drop policy if exists "company access commands read companies" on public.companies;
create policy "company access commands read companies"
on public.companies for select
to company_access_executor
using (
  created_by = (select public.company_access_auth_uid_v1())
  or exists (
    select 1 from public.company_memberships m
    where m.company_id = companies.id
      and m.user_id = (select public.company_access_auth_uid_v1())
      and m.accepted_at is not null
  )
  or exists (
    select 1 from public.support_operators o
    where o.user_id = (select public.company_access_auth_uid_v1()) and o.active
  )
  or exists (
    select 1 from public.company_invitations i
    where i.company_id = companies.id
      and i.invited_email = pg_catalog.lower(coalesce(
        (select public.company_access_auth_jwt_v1()) ->> 'email', ''
      ))
  )
);

drop policy if exists "company access backend reads own operator grant"
  on public.support_operators;
create policy "company access backend reads own operator grant"
on public.support_operators for select
to company_access_executor
using (
  user_id = (select public.company_access_auth_uid_v1()) and active
);

create or replace function public.company_access_is_company_creator_v1(p_company_id uuid)
returns boolean
language sql
stable
security definer
set search_path = ''
as $function$
  select exists (
    select 1
    from public.companies c
    where c.id = p_company_id
      and c.created_by = (select public.company_access_auth_uid_v1())
  );
$function$;

create or replace function public.company_access_has_current_agreement_v1(p_company_id uuid)
returns boolean
language sql
stable
set search_path = ''
as $function$
  select exists (
    select 1
    from public.customer_agreement_acceptances a
    where a.company_id = p_company_id
      and a.business_terms_version = '2026-07-17'
      and a.business_terms_effective_date = date '2026-07-17'
      and a.business_terms_path = '/vilkar'
      and a.business_terms_sha256 = 'f64a7f6a9758389fca8985a883a945d84c849f5b3316944621507db336992543'
      and a.dpa_version = '2026-07-17'
      and a.dpa_effective_date = date '2026-07-17'
      and a.dpa_path = '/databehandleravtale'
      and a.dpa_sha256 = '083ee63c1917ef227068befd7706ba2d636c52070ed4d880a8efae720528191c'
      and a.authority_statement_version = 'authority-v1'
      and a.acceptance_method = 'in_app_clickwrap'
  );
$function$;

drop policy if exists "company access onboarding creates companies" on public.companies;
create policy "company access onboarding creates companies"
on public.companies for insert
to company_access_executor
with check (
  created_by = (select public.company_access_auth_uid_v1())
  and entity_type = 'AS'
  and source = 'brreg'
  and identity_confirmed_at is not null
  and identity_locked_at is not null
);

drop policy if exists "company access onboarding creates owner membership" on public.company_memberships;
create policy "company access onboarding creates owner membership"
on public.company_memberships for insert
to company_access_executor
with check (
  user_id = (select public.company_access_auth_uid_v1())
  and role = 'owner'
  and invited_by is null
  and accepted_at is not null
  and public.company_access_is_company_creator_v1(company_id)
);

drop policy if exists "company access reads agreement evidence" on public.customer_agreement_acceptances;
create policy "company access reads agreement evidence"
on public.customer_agreement_acceptances for select
to company_access_executor
using (public.company_access_is_accepted_owner_v1(company_id));

drop policy if exists "company access appends current agreement evidence" on public.customer_agreement_acceptances;
create policy "company access appends current agreement evidence"
on public.customer_agreement_acceptances for insert
to company_access_executor
with check (
  accepted_by = (select public.company_access_auth_uid_v1())
  and public.company_access_is_accepted_owner_v1(company_id)
  and business_terms_version = '2026-07-17'
  and business_terms_effective_date = date '2026-07-17'
  and business_terms_path = '/vilkar'
  and business_terms_sha256 = 'f64a7f6a9758389fca8985a883a945d84c849f5b3316944621507db336992543'
  and dpa_version = '2026-07-17'
  and dpa_effective_date = date '2026-07-17'
  and dpa_path = '/databehandleravtale'
  and dpa_sha256 = '083ee63c1917ef227068befd7706ba2d636c52070ed4d880a8efae720528191c'
  and authority_statement_version = 'authority-v1'
  and acceptance_method = 'in_app_clickwrap'
);

drop policy if exists "company access commands read receipts" on public.company_access_command_receipts;
create policy "company access commands read receipts"
on public.company_access_command_receipts for select
to company_access_executor
using (
  actor_id = (select public.company_access_auth_uid_v1())
  and (
    command_name in ('accept_invitation', 'onboard_company')
    or (
      command_name = 'reaccept_agreement'
      and public.company_access_is_accepted_owner_v1(company_id)
    )
    or (
      command_name in ('create_invitation', 'revoke_invitation', 'resend_invitation', 'administer_membership', 'request_cancellation', 'resume_cancellation', 'finalize_deletion')
      and expires_at > statement_timestamp()
      and coalesce((select public.company_access_auth_jwt_v1()) ->> 'aal', '') = 'aal2'
      and public.company_access_is_accepted_owner_v1(company_id)
    )
    or (
      command_name = 'review_deletion'
      and expires_at > statement_timestamp()
      and public.company_access_has_fresh_mfa_v1()
      and public.company_access_is_active_admin_v1()
    )
  )
);

create or replace function public.company_access_onboard_company(
  p_operation_id uuid,
  p_verified_subject uuid,
  p_verified_email text,
  p_org_number text,
  p_name text,
  p_entity_type text,
  p_address text,
  p_postal_code text,
  p_city text,
  p_status_text text,
  p_source text,
  p_agreement_accepted boolean,
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
returns table (company_id uuid, current_agreement_accepted boolean, replayed boolean)
language plpgsql
security definer
set search_path = ''
as $function$
declare
  v_actor_id uuid := public.company_access_auth_uid_v1();
  v_current_subject uuid;
  v_current_email text;
  v_email text := pg_catalog.lower(pg_catalog.btrim(p_verified_email));
  v_company_id uuid;
  v_receipt public.company_access_command_receipts%rowtype;
  v_now timestamptz := statement_timestamp();
  v_fingerprint text := pg_catalog.concat_ws(
    '|', p_org_number, p_name, p_entity_type, p_address, p_postal_code, p_city,
    p_status_text, p_source, p_agreement_accepted::text,
    p_business_terms_version, p_business_terms_effective_date::text,
    p_business_terms_path, p_business_terms_sha256,
    p_dpa_version, p_dpa_effective_date::text, p_dpa_path, p_dpa_sha256,
    p_authority_statement_version, p_acceptance_method
  );
begin
  select identity.user_id, identity.email
  into v_current_subject, v_current_email
  from public.company_access_current_identity_v1() identity;
  if p_operation_id is null
     or v_actor_id is null
     or v_current_subject is null
     or p_verified_subject is distinct from v_actor_id
     or p_verified_subject is distinct from v_current_subject
     or v_email is distinct from v_current_email
     or v_current_email is distinct from pg_catalog.lower(coalesce(public.company_access_auth_jwt_v1() ->> 'email', '')) then
    raise exception 'company_access_not_found' using errcode = 'P0001';
  end if;
  if p_org_number is null or p_org_number !~ '^[0-9]{9}$'
     or p_name is null or pg_catalog.btrim(p_name) = ''
     or p_agreement_accepted is distinct from true
     or p_source is distinct from 'brreg'
     or p_business_terms_version is distinct from '2026-07-17'
     or p_business_terms_effective_date is distinct from date '2026-07-17'
     or p_business_terms_path is distinct from '/vilkar'
     or p_business_terms_sha256 is distinct from 'f64a7f6a9758389fca8985a883a945d84c849f5b3316944621507db336992543'
     or p_dpa_version is distinct from '2026-07-17'
     or p_dpa_effective_date is distinct from date '2026-07-17'
     or p_dpa_path is distinct from '/databehandleravtale'
     or p_dpa_sha256 is distinct from '083ee63c1917ef227068befd7706ba2d636c52070ed4d880a8efae720528191c'
     or p_authority_statement_version is distinct from 'authority-v1'
     or p_acceptance_method is distinct from 'in_app_clickwrap' then
    raise exception 'company_access_invalid_request' using errcode = 'P0001';
  end if;
  if p_entity_type is distinct from 'AS' then
    raise exception 'unsupported_entity_type' using errcode = 'P0001';
  end if;

  perform pg_catalog.pg_advisory_xact_lock(
    pg_catalog.hashtextextended(v_actor_id::text || '|onboard|' || p_org_number, 138)
  );
  select r.* into v_receipt
  from public.company_access_command_receipts r
  where r.actor_id = v_actor_id
    and r.command_name = 'onboard_company'
    and r.result ->> 'org_number' = p_org_number
  order by r.created_at desc
  limit 1;
  if found then
    if v_receipt.request_fingerprint is distinct from v_fingerprint then
      raise exception 'company_access_conflict' using errcode = 'P0001';
    end if;
    return query select v_receipt.company_id, true, true;
    return;
  end if;

  select c.id into v_company_id
  from public.companies c
  where c.org_number = p_org_number
  limit 1;
  if v_company_id is not null then
    if not public.company_access_is_accepted_owner_v1(v_company_id)
       or not public.company_access_has_current_agreement_v1(v_company_id) then
      raise exception 'company_access_conflict' using errcode = 'P0001';
    end if;
    insert into public.company_access_command_receipts (
      operation_id, command_name, actor_id, company_id,
      request_fingerprint, result, expires_at
    ) values (
      p_operation_id, 'onboard_company', v_actor_id, v_company_id,
      v_fingerprint,
      pg_catalog.jsonb_build_object(
        'company_id', v_company_id,
        'org_number', p_org_number,
        'current_agreement_accepted', true
      ),
      'infinity'::timestamptz
    );
    return query select v_company_id, true, true;
    return;
  end if;

  insert into public.companies (
    org_number, name, entity_type, address, postal_code, city, status_text,
    source, created_by, identity_confirmed_at, identity_locked_at
  ) values (
    p_org_number, p_name, p_entity_type, coalesce(p_address, ''),
    coalesce(p_postal_code, ''), coalesce(p_city, ''), coalesce(p_status_text, ''),
    p_source, v_actor_id, v_now, v_now
  ) returning id into v_company_id;

  insert into public.company_memberships (
    company_id, user_id, role, invited_by, accepted_at
  ) values (v_company_id, v_actor_id, 'owner', null, v_now);

  insert into public.customer_agreement_acceptances (
    company_id, accepted_by, customer_legal_name, customer_org_number,
    business_terms_version, business_terms_effective_date,
    business_terms_path, business_terms_sha256,
    dpa_version, dpa_effective_date, dpa_path, dpa_sha256,
    authority_statement_version, acceptance_method, accepted_at
  ) values (
    v_company_id, v_actor_id, p_name, p_org_number,
    p_business_terms_version, p_business_terms_effective_date,
    p_business_terms_path, p_business_terms_sha256,
    p_dpa_version, p_dpa_effective_date, p_dpa_path, p_dpa_sha256,
    p_authority_statement_version, p_acceptance_method, v_now
  );

  insert into public.audit_events (company_id, actor_id, category, action, message)
  values (
    v_company_id, v_actor_id, 'company', 'workspace_created',
    'Selskapsarbeidsflate opprettet med dokumentert avtaleaksept.'
  );

  insert into public.company_access_command_receipts (
    operation_id, command_name, actor_id, company_id,
    request_fingerprint, result, expires_at
  ) values (
    p_operation_id, 'onboard_company', v_actor_id, v_company_id,
    v_fingerprint,
    pg_catalog.jsonb_build_object(
      'company_id', v_company_id,
      'org_number', p_org_number,
      'current_agreement_accepted', true
    ),
    'infinity'::timestamptz
  );
  return query select v_company_id, true, false;
exception
  when unique_violation then
    raise exception 'company_access_conflict' using errcode = 'P0001';
end;
$function$;

create or replace function public.company_access_reaccept_agreement(
  p_operation_id uuid,
  p_company_id uuid,
  p_verified_subject uuid,
  p_verified_email text,
  p_agreement_accepted boolean,
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
returns table (company_id uuid, current_agreement_accepted boolean, replayed boolean)
language plpgsql
security definer
set search_path = ''
as $function$
declare
  v_actor_id uuid := public.company_access_auth_uid_v1();
  v_current_subject uuid;
  v_current_email text;
  v_email text := pg_catalog.lower(pg_catalog.btrim(p_verified_email));
  v_company_name text;
  v_org_number text;
  v_receipt public.company_access_command_receipts%rowtype;
  v_now timestamptz := statement_timestamp();
  v_fingerprint text := pg_catalog.concat_ws(
    '|', p_company_id::text, p_agreement_accepted::text,
    p_business_terms_version, p_business_terms_effective_date::text,
    p_business_terms_path, p_business_terms_sha256,
    p_dpa_version, p_dpa_effective_date::text, p_dpa_path, p_dpa_sha256,
    p_authority_statement_version, p_acceptance_method
  );
begin
  select identity.user_id, identity.email
  into v_current_subject, v_current_email
  from public.company_access_current_identity_v1() identity;
  if p_operation_id is null
     or p_company_id is null
     or v_actor_id is null
     or v_current_subject is null
     or p_verified_subject is distinct from v_actor_id
     or p_verified_subject is distinct from v_current_subject
     or v_email is distinct from v_current_email
     or v_current_email is distinct from pg_catalog.lower(coalesce(public.company_access_auth_jwt_v1() ->> 'email', '')) then
    raise exception 'company_access_not_found' using errcode = 'P0001';
  end if;
  if p_agreement_accepted is distinct from true
     or p_business_terms_version is distinct from '2026-07-17'
     or p_business_terms_effective_date is distinct from date '2026-07-17'
     or p_business_terms_path is distinct from '/vilkar'
     or p_business_terms_sha256 is distinct from 'f64a7f6a9758389fca8985a883a945d84c849f5b3316944621507db336992543'
     or p_dpa_version is distinct from '2026-07-17'
     or p_dpa_effective_date is distinct from date '2026-07-17'
     or p_dpa_path is distinct from '/databehandleravtale'
     or p_dpa_sha256 is distinct from '083ee63c1917ef227068befd7706ba2d636c52070ed4d880a8efae720528191c'
     or p_authority_statement_version is distinct from 'authority-v1'
     or p_acceptance_method is distinct from 'in_app_clickwrap' then
    raise exception 'company_access_invalid_request' using errcode = 'P0001';
  end if;
  if not public.company_access_is_accepted_owner_v1(p_company_id) then
    raise exception 'accepted_owner_membership_required' using errcode = 'P0001';
  end if;

  perform pg_catalog.pg_advisory_xact_lock(
    pg_catalog.hashtextextended(
      v_actor_id::text || '|reaccept|' || p_company_id::text || '|' ||
      p_business_terms_sha256 || '|' || p_dpa_sha256,
      138
    )
  );
  select r.* into v_receipt
  from public.company_access_command_receipts r
  where r.actor_id = v_actor_id
    and r.company_id = p_company_id
    and r.command_name = 'reaccept_agreement'
    and r.request_fingerprint = v_fingerprint
  order by r.created_at desc
  limit 1;
  if found then
    return query select p_company_id, true, true;
    return;
  end if;

  select c.name, c.org_number
  into v_company_name, v_org_number
  from public.companies c
  where c.id = p_company_id;
  if not found then
    raise exception 'company_access_not_found' using errcode = 'P0001';
  end if;

  if public.company_access_has_current_agreement_v1(p_company_id) then
    insert into public.company_access_command_receipts (
      operation_id, command_name, actor_id, company_id,
      request_fingerprint, result, expires_at
    ) values (
      p_operation_id, 'reaccept_agreement', v_actor_id, p_company_id,
      v_fingerprint,
      pg_catalog.jsonb_build_object(
        'company_id', p_company_id,
        'current_agreement_accepted', true
      ),
      'infinity'::timestamptz
    );
    return query select p_company_id, true, true;
    return;
  end if;

  insert into public.customer_agreement_acceptances (
    company_id, accepted_by, customer_legal_name, customer_org_number,
    business_terms_version, business_terms_effective_date,
    business_terms_path, business_terms_sha256,
    dpa_version, dpa_effective_date, dpa_path, dpa_sha256,
    authority_statement_version, acceptance_method, accepted_at
  ) values (
    p_company_id, v_actor_id, v_company_name, v_org_number,
    p_business_terms_version, p_business_terms_effective_date,
    p_business_terms_path, p_business_terms_sha256,
    p_dpa_version, p_dpa_effective_date, p_dpa_path, p_dpa_sha256,
    p_authority_statement_version, p_acceptance_method, v_now
  );

  insert into public.audit_events (company_id, actor_id, category, action, message)
  values (
    p_company_id, v_actor_id, 'company', 'customer_agreement_reaccepted',
    'Oppdatert kundeavtale og databehandleravtale uttrykkelig akseptert.'
  );

  insert into public.company_access_command_receipts (
    operation_id, command_name, actor_id, company_id,
    request_fingerprint, result, expires_at
  ) values (
    p_operation_id, 'reaccept_agreement', v_actor_id, p_company_id,
    v_fingerprint,
    pg_catalog.jsonb_build_object(
      'company_id', p_company_id,
      'current_agreement_accepted', true
    ),
    'infinity'::timestamptz
  );
  return query select p_company_id, true, false;
exception
  when unique_violation then
    raise exception 'company_access_conflict' using errcode = 'P0001';
end;
$function$;

grant select, insert on public.customer_agreement_acceptances to company_access_executor;
grant insert on public.companies to company_access_executor;
grant execute on function public.company_access_is_company_creator_v1(uuid) to company_access_executor;
grant execute on function public.company_access_has_current_agreement_v1(uuid) to company_access_executor;

do $ownership$
begin
  execute pg_catalog.format('grant company_access_executor to %I', current_user);
  grant create on schema public to company_access_executor;
  alter function public.company_access_onboard_company(
    uuid, uuid, text, text, text, text, text, text, text, text, text,
    boolean, text, date, text, text, text, date, text, text, text, text
  ) owner to company_access_executor;
  alter function public.company_access_reaccept_agreement(
    uuid, uuid, uuid, text, boolean, text, date, text, text,
    text, date, text, text, text, text
  ) owner to company_access_executor;
  revoke create on schema public from company_access_executor;
end
$ownership$;

revoke all on function public.company_access_is_company_creator_v1(uuid)
  from public, anon, authenticated, service_role;
revoke all on function public.company_access_has_current_agreement_v1(uuid)
  from public, anon, authenticated, service_role;
set role company_access_executor;
revoke all on function public.company_access_onboard_company(
  uuid, uuid, text, text, text, text, text, text, text, text, text,
  boolean, text, date, text, text, text, date, text, text, text, text
) from public, anon, authenticated, service_role;
revoke all on function public.company_access_reaccept_agreement(
  uuid, uuid, uuid, text, boolean, text, date, text, text,
  text, date, text, text, text, text
) from public, anon, authenticated, service_role;

grant execute on function public.company_access_onboard_company(
  uuid, uuid, text, text, text, text, text, text, text, text, text,
  boolean, text, date, text, text, text, date, text, text, text, text
) to company_access_executor;
grant execute on function public.company_access_reaccept_agreement(
  uuid, uuid, uuid, text, boolean, text, date, text, text,
  text, date, text, text, text, text
) to company_access_executor;
reset role;

do $ownership$
begin
  execute pg_catalog.format('revoke company_access_executor from %I', current_user);
end
$ownership$;
