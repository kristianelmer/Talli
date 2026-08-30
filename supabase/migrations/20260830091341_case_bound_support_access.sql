-- #200 security-only amendment: replace standing operator access with one
-- generated, opened, company/scope/time/MFA-bound support case. All command
-- and read functions are backend-executor only; authenticated Data API users
-- receive no support-case table or RPC authority.
begin;

-- Recutover may encounter helpers already owned by the restricted executor.
-- Borrow that role before any CREATE OR REPLACE and retain it until the final
-- ACL normalization has completed.
do $borrow_support_function_owner$
begin
  execute pg_catalog.format('grant company_access_executor to %I', current_user);
end
$borrow_support_function_owner$;

create table if not exists public.support_access_grants (
  case_id uuid primary key default gen_random_uuid(),
  company_id uuid not null references public.companies(id) on delete restrict,
  operator_user_id uuid not null references public.support_operators(user_id) on delete restrict,
  reason text not null check (reason = any (array[
    'customer_request', 'security_incident', 'service_recovery', 'legal_obligation'
  ])),
  scopes text[] not null check (
    pg_catalog.cardinality(scopes) between 1 and 8
    and scopes <@ array[
      'profile', 'filing', 'billing', 'audit', 'cancellation',
      'authority', 'documents', 'production'
    ]::text[]
  ),
  starts_at timestamptz not null,
  expires_at timestamptz not null,
  granted_by uuid not null references auth.users(id) on delete restrict,
  granted_at timestamptz not null default pg_catalog.clock_timestamp(),
  revoked_at timestamptz,
  revoked_by uuid references auth.users(id) on delete restrict,
  revocation_reason text check (
    revocation_reason is null or revocation_reason = any (array[
      'case_closed', 'access_no_longer_needed', 'operator_removed',
      'security_response', 'grant_replaced'
    ])
  ),
  check (expires_at > starts_at),
  check (expires_at <= starts_at + interval '8 hours'),
  check (
    (revoked_at is null and revoked_by is null and revocation_reason is null)
    or (revoked_at is not null and revoked_by is not null and revocation_reason is not null)
  )
);

create index if not exists support_access_grants_active_lookup_idx
on public.support_access_grants(operator_user_id, case_id, company_id, starts_at, expires_at)
where revoked_at is null;

create table if not exists public.support_access_operation_receipts (
  actor_id uuid not null references auth.users(id) on delete restrict,
  operation_id uuid not null,
  command_name text not null check (command_name in (
    'grant_support_access', 'revoke_support_access', 'open_support_case'
  )),
  case_id uuid not null references public.support_access_grants(case_id) on delete restrict,
  request_fingerprint text not null,
  request_payload jsonb not null,
  result jsonb not null,
  created_at timestamptz not null default pg_catalog.clock_timestamp(),
  primary key (actor_id, operation_id)
);

alter table public.support_access_operation_receipts
  add column if not exists request_fingerprint text;
update public.support_access_operation_receipts
set request_fingerprint = pg_catalog.encode(
  extensions.digest(request_payload::text, 'sha256'), 'hex'
)
where request_fingerprint is null;
alter table public.support_access_operation_receipts
  alter column request_fingerprint set not null;
do $support_receipt_fingerprint_constraint$
begin
  if not exists (
    select 1 from pg_catalog.pg_constraint
    where conname = 'support_access_receipts_fingerprint_check'
      and conrelid = 'public.support_access_operation_receipts'::regclass
  ) then
    alter table public.support_access_operation_receipts
      add constraint support_access_receipts_fingerprint_check
      check (request_fingerprint ~ '^[0-9a-f]{64}$');
  end if;
end
$support_receipt_fingerprint_constraint$;

create table if not exists public.support_case_openings (
  actor_id uuid not null references auth.users(id) on delete restrict,
  operation_id uuid not null,
  case_id uuid not null references public.support_access_grants(case_id) on delete restrict,
  company_id uuid not null references public.companies(id) on delete restrict,
  opened_at timestamptz not null default pg_catalog.clock_timestamp(),
  primary key (actor_id, operation_id)
);

alter table public.support_access_grants enable row level security;
alter table public.support_access_grants force row level security;
alter table public.support_access_operation_receipts enable row level security;
alter table public.support_access_operation_receipts force row level security;
alter table public.support_case_openings enable row level security;
alter table public.support_case_openings force row level security;

revoke all on table public.support_access_grants,
  public.support_access_operation_receipts,
  public.support_case_openings
from public, anon, authenticated, service_role;
grant select, insert, update on table public.support_access_grants
  to company_access_executor;
grant select, insert on table public.support_access_operation_receipts,
  public.support_case_openings to company_access_executor;
grant usage on schema extensions to company_access_executor;
grant usage on schema storage to company_access_executor;
grant execute on function extensions.digest(text, text) to company_access_executor;

drop policy if exists support_access_grants_executor_select
on public.support_access_grants;
create policy support_access_grants_executor_select
on public.support_access_grants for select to company_access_executor
using (
  operator_user_id = public.company_access_auth_uid_v1()
  or public.company_access_is_active_admin_v1()
);
drop policy if exists support_access_grants_executor_insert
on public.support_access_grants;
create policy support_access_grants_executor_insert
on public.support_access_grants for insert to company_access_executor
with check (
  granted_by = public.company_access_auth_uid_v1()
  and public.company_access_is_active_admin_v1()
  and public.company_access_has_fresh_mfa_v1()
);
drop policy if exists support_access_grants_executor_update
on public.support_access_grants;
create policy support_access_grants_executor_update
on public.support_access_grants for update to company_access_executor
using (
  public.company_access_is_active_admin_v1()
  and public.company_access_has_fresh_mfa_v1()
)
with check (
  public.company_access_is_active_admin_v1()
  and public.company_access_has_fresh_mfa_v1()
);

drop policy if exists support_access_receipts_executor
on public.support_access_operation_receipts;
create policy support_access_receipts_executor
on public.support_access_operation_receipts for all to company_access_executor
using (actor_id = public.company_access_auth_uid_v1())
with check (actor_id = public.company_access_auth_uid_v1());

drop policy if exists support_case_openings_executor
on public.support_case_openings;
create policy support_case_openings_executor
on public.support_case_openings for all to company_access_executor
using (actor_id = public.company_access_auth_uid_v1())
with check (actor_id = public.company_access_auth_uid_v1());

create or replace function public.company_access_current_support_case_id_v1()
returns uuid
language sql
stable
set search_path = ''
as $function$
  select nullif(pg_catalog.current_setting('talli.support_case_id', true), '')::uuid;
$function$;

create or replace function public.company_access_is_active_support_operator_v1(
  p_user_id uuid
)
returns boolean
language sql
stable
security definer
set search_path = ''
as $function$
  select p_user_id is not null and exists (
    select 1 from public.support_operators o
    where o.user_id = p_user_id and o.active
  );
$function$;

revoke all on function
  public.company_access_is_active_support_operator_v1(uuid)
from public, anon, authenticated, service_role;
grant execute on function
  public.company_access_is_active_support_operator_v1(uuid)
to company_access_executor;

create or replace function public.company_access_has_open_support_case_v1(
  p_case_id uuid,
  p_company_id uuid,
  p_scope text
)
returns boolean
language sql
stable
security definer
set search_path = ''
as $function$
  select p_case_id is not null
    and p_case_id = public.company_access_current_support_case_id_v1()
    and p_company_id is not null
    and p_scope = any (array[
      'profile', 'filing', 'billing', 'audit', 'cancellation',
      'authority', 'documents', 'production'
    ])
    and public.company_access_is_active_operator_v1()
    and public.company_access_has_fresh_mfa_v1()
    and exists (
      select 1
      from public.support_access_grants g
      where g.case_id = p_case_id
        and g.operator_user_id = public.company_access_auth_uid_v1()
        and g.company_id = p_company_id
        and p_scope = any (g.scopes)
        and g.revoked_at is null
        and pg_catalog.statement_timestamp() >= g.starts_at
        and pg_catalog.statement_timestamp() < g.expires_at
    )
    and exists (
      select 1
      from public.support_case_openings o
      where o.actor_id = public.company_access_auth_uid_v1()
        and o.case_id = p_case_id
        and o.company_id = p_company_id
    );
$function$;

create or replace function public.company_access_grant_support_access(
  p_operation_id uuid,
  p_company_id uuid,
  p_operator_user_id uuid,
  p_reason text,
  p_scopes text[],
  p_starts_at timestamptz,
  p_expires_at timestamptz
)
returns table (
  case_id uuid, company_id uuid, operator_user_id uuid, reason text,
  scopes text[], starts_at timestamptz, expires_at timestamptz,
  granted_by uuid, granted_at timestamptz, revoked_at timestamptz,
  revoked_by uuid, revocation_reason text
)
language plpgsql
security definer
set search_path = ''
as $function$
declare
  v_actor_id uuid := public.company_access_auth_uid_v1();
  v_scopes text[];
  v_request jsonb;
  v_fingerprint text;
  v_receipt public.support_access_operation_receipts%rowtype;
  v_grant public.support_access_grants%rowtype;
begin
  if p_operation_id is null or p_company_id is null or p_operator_user_id is null
    or v_actor_id is null or not public.company_access_is_active_admin_v1()
    or not public.company_access_has_fresh_mfa_v1()
  then
    raise exception 'support_access_not_available' using errcode = 'P0001';
  end if;
  select pg_catalog.array_agg(distinct scope order by scope)
  into v_scopes from pg_catalog.unnest(p_scopes) scope;
  if p_reason is null or p_reason <> all (array[
      'customer_request', 'security_incident', 'service_recovery', 'legal_obligation'
    ]) or v_scopes is null or pg_catalog.cardinality(v_scopes) not between 1 and 8
    or not v_scopes <@ array[
      'profile', 'filing', 'billing', 'audit', 'cancellation',
      'authority', 'documents', 'production'
    ]::text[]
    or p_starts_at < pg_catalog.statement_timestamp() - interval '1 minute'
    or p_starts_at > pg_catalog.statement_timestamp() + interval '24 hours'
    or p_expires_at <= pg_catalog.statement_timestamp()
    or p_expires_at > p_starts_at + interval '8 hours'
  then
    raise exception 'support_access_invalid_request' using errcode = 'P0001';
  end if;
  if not public.company_access_is_active_support_operator_v1(
    p_operator_user_id
  ) then
    raise exception 'support_access_not_available' using errcode = 'P0001';
  end if;

  v_request := pg_catalog.jsonb_build_object(
    'companyId', p_company_id, 'operatorUserId', p_operator_user_id,
    'reason', p_reason, 'scopes', pg_catalog.to_jsonb(v_scopes),
    'startsAt', p_starts_at, 'expiresAt', p_expires_at
  );
  v_fingerprint := pg_catalog.encode(
    extensions.digest(v_request::text, 'sha256'), 'hex'
  );
  perform public.company_access_lock_operation_v1(v_actor_id, p_operation_id);
  select r.* into v_receipt
  from public.support_access_operation_receipts r
  where r.actor_id = v_actor_id and r.operation_id = p_operation_id;
  if found then
    if v_receipt.command_name <> 'grant_support_access'
      or v_receipt.request_fingerprint <> v_fingerprint
    then
      raise exception 'support_access_operation_conflict' using errcode = 'P0001';
    end if;
    return query select * from pg_catalog.jsonb_populate_record(
      null::public.support_access_grants, v_receipt.result
    );
    return;
  end if;

  begin
    insert into public.support_access_grants (
      company_id, operator_user_id, reason, scopes, starts_at, expires_at, granted_by
    ) values (
      p_company_id, p_operator_user_id, p_reason, v_scopes,
      p_starts_at, p_expires_at, v_actor_id
    ) returning * into v_grant;
  exception when foreign_key_violation then
    raise exception 'support_access_not_available' using errcode = 'P0001';
  end;
  insert into public.audit_events (company_id, actor_id, category, action, message)
  values (
    p_company_id, v_actor_id, 'support_access', 'support_access_granted',
    'A generated case-bound support grant was issued.'
  );
  insert into public.support_access_operation_receipts (
    actor_id, operation_id, command_name, case_id, request_fingerprint,
    request_payload, result
  ) values (
    v_actor_id, p_operation_id, 'grant_support_access', v_grant.case_id,
    v_fingerprint, v_request, pg_catalog.to_jsonb(v_grant)
  );
  return query select v_grant.*;
end;
$function$;

create or replace function public.company_access_read_support_case(
  p_case_id uuid
)
returns table (
  case_id uuid,
  company_id uuid,
  scopes text[],
  resources jsonb
)
language plpgsql
security definer
set search_path = ''
as $function$
declare
  v_actor_id uuid := public.company_access_auth_uid_v1();
  v_grant public.support_access_grants%rowtype;
begin
  if p_case_id is null or v_actor_id is null
    or not public.company_access_is_active_operator_v1()
    or not public.company_access_has_fresh_mfa_v1()
  then
    raise exception 'support_access_not_available' using errcode = 'P0001';
  end if;
  select g.* into v_grant from public.support_access_grants g
  where g.case_id = p_case_id
    and g.operator_user_id = v_actor_id
    and g.revoked_at is null
    and pg_catalog.statement_timestamp() >= g.starts_at
    and pg_catalog.statement_timestamp() < g.expires_at;
  if not found or not exists (
    select 1 from public.support_case_openings o
    where o.actor_id = v_actor_id and o.case_id = p_case_id
      and o.company_id = v_grant.company_id
  ) then
    raise exception 'support_access_not_available' using errcode = 'P0001';
  end if;
  perform pg_catalog.set_config('talli.support_case_id', p_case_id::text, true);

  return query select v_grant.case_id, v_grant.company_id, v_grant.scopes,
    pg_catalog.jsonb_build_object(
      'companies', coalesce((
        select pg_catalog.jsonb_agg(pg_catalog.jsonb_build_object(
          'id', c.id, 'org_number', c.org_number, 'name', c.name,
          'entity_type', c.entity_type, 'address', c.address,
          'postal_code', c.postal_code, 'city', c.city,
          'status_text', c.status_text, 'source', c.source,
          'created_by', c.created_by,
          'identity_confirmed_at', c.identity_confirmed_at,
          'identity_locked_at', c.identity_locked_at, 'created_at', c.created_at
        )) from public.companies c where c.id = v_grant.company_id
      ), '[]'::jsonb),
      'audit_events', coalesce((
        select pg_catalog.jsonb_agg(item order by item.created_at desc) from (
          select a.id, a.company_id, a.actor_id, a.category, a.action,
            a.message, a.created_at
          from public.audit_events a where a.company_id = v_grant.company_id
          order by a.created_at desc limit 50
        ) item
      ), '[]'::jsonb),
      'company_cancellations', coalesce((
        select pg_catalog.jsonb_agg(pg_catalog.jsonb_build_object(
          'id', c.id, 'company_id', c.company_id, 'status', c.status,
          'reason', c.reason, 'evidence', c.evidence,
          'requested_by', c.requested_by, 'requested_at', c.requested_at,
          'reviewed_by', c.reviewed_by, 'reviewed_at', c.reviewed_at,
          'deleted_by', c.deleted_by, 'deleted_at', c.deleted_at,
          'updated_at', c.updated_at
        )) from public.company_cancellations c
        where c.company_id = v_grant.company_id
      ), '[]'::jsonb),
      'filing_submissions', coalesce((
        select pg_catalog.jsonb_agg(pg_catalog.jsonb_build_object(
          'id', f.id, 'company_id', f.company_id, 'income_year', f.income_year,
          'filing', f.filing, 'status', f.status, 'updated_at', f.updated_at
        ) order by f.updated_at desc)
        from public.filing_submissions f where f.company_id = v_grant.company_id
      ), '[]'::jsonb),
      'filing_readiness_snapshots', coalesce((
        select pg_catalog.jsonb_agg(pg_catalog.jsonb_build_object(
          'id', f.id, 'company_id', f.company_id, 'income_year', f.income_year,
          'obligation', f.obligation, 'status', f.status, 'ready', f.ready,
          'hard_blocks', f.hard_blocks, 'warnings', f.warnings,
          'updated_at', f.updated_at
        )) from public.filing_readiness_snapshots f
        where f.company_id = v_grant.company_id
      ), '[]'::jsonb),
      'billing_accounts', coalesce((
        select pg_catalog.jsonb_agg(pg_catalog.jsonb_build_object(
          'company_id', b.company_id, 'pricing_plan', b.pricing_plan,
          'subscription_active', b.subscription_active,
          'filing_package_paid', b.filing_package_paid,
          'refund_eligible', b.refund_eligible,
          'refund_completed', b.refund_completed,
          'refund_provider_ref', b.refund_provider_ref,
          'updated_at', b.updated_at
        )) from public.billing_accounts b where b.company_id = v_grant.company_id
      ), '[]'::jsonb),
      'billing_payment_events', coalesce((
        select pg_catalog.jsonb_agg(pg_catalog.jsonb_build_object(
          'id', b.id, 'company_id', b.company_id, 'provider', b.provider,
          'kind', b.kind, 'status', b.status, 'amount_nok', b.amount_nok,
          'created_at', b.created_at
        )) from public.billing_payment_events b
        where b.company_id = v_grant.company_id
      ), '[]'::jsonb),
      'authority_permissions', coalesce((
        select pg_catalog.jsonb_agg(pg_catalog.jsonb_build_object(
          'id', a.id, 'company_id', a.company_id, 'obligation', a.obligation,
          'production_enabled', a.production_enabled, 'updated_at', a.updated_at
        )) from public.authority_permissions a
        where a.company_id = v_grant.company_id
      ), '[]'::jsonb),
      'company_deletion_reviews', coalesce((
        select pg_catalog.jsonb_agg(pg_catalog.jsonb_build_object(
          'id', d.id, 'cancellation_id', d.cancellation_id,
          'company_id', d.company_id, 'decision', d.decision,
          'evidence_reference', d.evidence_reference,
          'reviewed_at', d.reviewed_at
        )) from public.company_deletion_reviews d
        where d.company_id = v_grant.company_id
      ), '[]'::jsonb)
    );
end;
$function$;

create or replace function public.company_access_support_storage_company_id_v1(
  p_name text
)
returns uuid
language plpgsql
immutable
set search_path = ''
as $function$
declare
  v_parts text[] := pg_catalog.string_to_array(p_name, '/');
  v_candidate text;
begin
  v_candidate := case when v_parts[1] = 'authority-feedback'
    then v_parts[2] else v_parts[1] end;
  if v_candidate is null or v_candidate !~* '^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$' then
    return null;
  end if;
  return v_candidate::uuid;
exception when others then
  return null;
end;
$function$;

-- Remove every direct-browser standing operator policy. Customer/member
-- predicates remain, and separate executor-only case policies follow.
drop policy if exists "support operators can read audit events" on public.audit_events;
drop policy if exists "support operators can read cancellation state" on public.company_cancellations;
drop policy if exists "support operators can read filing submissions" on public.filing_submissions;
drop policy if exists "support operators can read filing readiness snapshots" on public.filing_readiness_snapshots;
drop policy if exists "support operators can read billing accounts" on public.billing_accounts;
drop policy if exists "support operators can read billing payment events" on public.billing_payment_events;
drop policy if exists "support operators can read authority permissions" on public.authority_permissions;
drop policy if exists "support operators can read authority test runs" on public.authority_test_runs;
drop policy if exists system_user_requests_operator_read on public.system_user_requests;
drop policy if exists "active operators read production pilot entitlements" on public.production_pilot_entitlements;
drop policy if exists "active operators read filing approval snapshots" on public.filing_approval_snapshots;
drop policy if exists "active operators read production filing submissions" on public.production_filing_submissions;
drop policy if exists "active operators read production filing events" on public.production_filing_events;
drop policy if exists production_feedback_artifacts_operator_read on public.production_feedback_artifacts;

drop policy if exists "company members can read companies" on public.companies;
create policy "company members can read companies"
on public.companies for select to authenticated
using (
  created_by = (select auth.uid())
  or exists (
    select 1 from public.company_memberships m
    where m.company_id = companies.id and m.user_id = (select auth.uid())
      and m.accepted_at is not null
  )
);

drop policy if exists "company members can read document metadata" on public.documents;
create policy "company members can read document metadata"
on public.documents for select to authenticated
using (
  case when documents.document_type = 'authority_feedback' then exists (
    select 1 from public.company_memberships m
    where m.company_id = documents.company_id and m.user_id = (select auth.uid())
      and m.role = 'owner' and m.accepted_at is not null
  ) else exists (
    select 1 from public.company_memberships m
    where m.company_id = documents.company_id and m.user_id = (select auth.uid())
  ) end
);

drop policy if exists "company members can read company document objects" on storage.objects;
create policy "company members can read company document objects"
on storage.objects for select to authenticated
using (
  bucket_id = 'company-documents' and (
    ((storage.foldername(name))[1] = 'authority-feedback' and exists (
      select 1 from public.company_memberships m
      where m.company_id::text = (storage.foldername(name))[2]
        and m.user_id = (select auth.uid()) and m.role = 'owner'
        and m.accepted_at is not null
    )) or ((storage.foldername(name))[1] <> 'authority-feedback' and exists (
      select 1 from public.company_memberships m
      where m.company_id::text = (storage.foldername(name))[1]
        and m.user_id = (select auth.uid())
    ))
  )
  and not exists (
    select 1 from public.documents d
    where d.storage_key = storage.objects.name and d.status = 'removed'
  )
);

grant select on public.companies, public.audit_events, public.company_cancellations,
  public.filing_submissions, public.filing_readiness_snapshots,
  public.billing_accounts, public.billing_payment_events,
  public.authority_permissions, public.authority_test_runs,
  public.system_user_requests, public.production_pilot_entitlements,
  public.filing_approval_snapshots, public.production_filing_submissions,
  public.production_filing_events, public.production_feedback_artifacts,
  public.documents, public.company_deletion_reviews to company_access_executor;
grant select on storage.objects to company_access_executor;

drop policy if exists "company access commands read companies" on public.companies;
create policy "company access commands read companies"
on public.companies for select to company_access_executor
using (
  created_by = public.company_access_auth_uid_v1()
  or exists (
    select 1 from public.company_memberships m
    where m.company_id = companies.id
      and m.user_id = public.company_access_auth_uid_v1()
      and m.accepted_at is not null
  )
  or exists (
    select 1 from public.company_invitations i
    where i.company_id = companies.id
      and i.invited_email = pg_catalog.lower(coalesce(
        public.company_access_auth_jwt_v1() ->> 'email', ''
      ))
  )
  or public.company_access_has_open_support_case_v1(
    public.company_access_current_support_case_id_v1(), id, 'profile'
  )
);

drop policy if exists support_case_read_audit_events on public.audit_events;
drop policy if exists support_case_read_filing_submissions on public.filing_submissions;
drop policy if exists support_case_read_filing_readiness on public.filing_readiness_snapshots;
drop policy if exists support_case_read_billing_accounts on public.billing_accounts;
drop policy if exists support_case_read_billing_events on public.billing_payment_events;
drop policy if exists support_case_read_authority_permissions on public.authority_permissions;
drop policy if exists support_case_read_authority_runs on public.authority_test_runs;
drop policy if exists support_case_read_system_user_requests on public.system_user_requests;
drop policy if exists support_case_read_pilot_entitlements on public.production_pilot_entitlements;
drop policy if exists support_case_read_approval_snapshots on public.filing_approval_snapshots;
drop policy if exists support_case_read_production_submissions on public.production_filing_submissions;
drop policy if exists support_case_read_production_events on public.production_filing_events;
drop policy if exists support_case_read_feedback_artifacts on public.production_feedback_artifacts;
drop policy if exists support_case_read_documents on public.documents;
drop policy if exists support_case_read_storage_objects on storage.objects;

create policy support_case_read_audit_events on public.audit_events
for select to company_access_executor using (
  public.company_access_has_open_support_case_v1(
    public.company_access_current_support_case_id_v1(), company_id, 'audit'
  )
);
create policy support_case_read_filing_submissions on public.filing_submissions
for select to company_access_executor using (
  public.company_access_has_open_support_case_v1(
    public.company_access_current_support_case_id_v1(), company_id, 'filing'
  )
);
create policy support_case_read_filing_readiness on public.filing_readiness_snapshots
for select to company_access_executor using (
  public.company_access_has_open_support_case_v1(
    public.company_access_current_support_case_id_v1(), company_id, 'filing'
  )
);
create policy support_case_read_billing_accounts on public.billing_accounts
for select to company_access_executor using (
  public.company_access_has_open_support_case_v1(
    public.company_access_current_support_case_id_v1(), company_id, 'billing'
  )
);
create policy support_case_read_billing_events on public.billing_payment_events
for select to company_access_executor using (
  public.company_access_has_open_support_case_v1(
    public.company_access_current_support_case_id_v1(), company_id, 'billing'
  )
);
create policy support_case_read_authority_permissions on public.authority_permissions
for select to company_access_executor using (
  public.company_access_has_open_support_case_v1(
    public.company_access_current_support_case_id_v1(), company_id, 'authority'
  )
);
create policy support_case_read_authority_runs on public.authority_test_runs
for select to company_access_executor using (
  public.company_access_has_open_support_case_v1(
    public.company_access_current_support_case_id_v1(), company_id, 'authority'
  )
);
create policy support_case_read_system_user_requests on public.system_user_requests
for select to company_access_executor using (
  public.company_access_has_open_support_case_v1(
    public.company_access_current_support_case_id_v1(), company_id, 'authority'
  )
);
create policy support_case_read_pilot_entitlements on public.production_pilot_entitlements
for select to company_access_executor using (
  public.company_access_has_open_support_case_v1(
    public.company_access_current_support_case_id_v1(), company_id, 'production'
  )
);
create policy support_case_read_approval_snapshots on public.filing_approval_snapshots
for select to company_access_executor using (
  public.company_access_has_open_support_case_v1(
    public.company_access_current_support_case_id_v1(), company_id, 'production'
  )
);
create policy support_case_read_production_submissions on public.production_filing_submissions
for select to company_access_executor using (
  public.company_access_has_open_support_case_v1(
    public.company_access_current_support_case_id_v1(), company_id, 'production'
  )
);
create policy support_case_read_production_events on public.production_filing_events
for select to company_access_executor using (exists (
  select 1 from public.production_filing_submissions s
  where s.id = production_filing_events.submission_id
    and public.company_access_has_open_support_case_v1(
      public.company_access_current_support_case_id_v1(), s.company_id, 'production'
    )
));
create policy support_case_read_feedback_artifacts on public.production_feedback_artifacts
for select to company_access_executor using (
  public.company_access_has_open_support_case_v1(
    public.company_access_current_support_case_id_v1(), company_id, 'documents'
  )
);
create policy support_case_read_documents on public.documents
for select to company_access_executor using (
  public.company_access_has_open_support_case_v1(
    public.company_access_current_support_case_id_v1(), company_id, 'documents'
  )
);
create policy support_case_read_storage_objects on storage.objects
for select to company_access_executor using (
  bucket_id = 'company-documents'
  and public.company_access_has_open_support_case_v1(
    public.company_access_current_support_case_id_v1(),
    public.company_access_support_storage_company_id_v1(name), 'documents'
  )
  and not exists (
    select 1 from public.documents d
    where d.storage_key = storage.objects.name and d.status = 'removed'
  )
);

drop policy if exists "company access commands read cancellations" on public.company_cancellations;
create policy "company access commands read cancellations"
on public.company_cancellations for select to company_access_executor
using (
  exists (
    select 1 from public.company_memberships m
    where m.company_id = company_cancellations.company_id
      and m.user_id = public.company_access_auth_uid_v1()
      and m.accepted_at is not null
  ) or public.company_access_has_open_support_case_v1(
    public.company_access_current_support_case_id_v1(), company_id, 'cancellation'
  )
);

drop policy if exists "company access members read deletion reviews" on public.company_deletion_reviews;
create policy "company access members read deletion reviews"
on public.company_deletion_reviews for select to company_access_executor
using (
  exists (
    select 1 from public.company_memberships m
    where m.company_id = company_deletion_reviews.company_id
      and m.user_id = public.company_access_auth_uid_v1()
      and m.accepted_at is not null
  ) or public.company_access_has_open_support_case_v1(
    public.company_access_current_support_case_id_v1(), company_id, 'cancellation'
  )
);

alter table public.company_access_command_receipts
  add column if not exists support_case_id uuid
  references public.support_access_grants(case_id) on delete restrict;
alter table public.company_deletion_reviews
  add column if not exists support_case_id uuid
  references public.support_access_grants(case_id) on delete restrict;

create or replace function public.company_access_bind_deletion_review_case_v1()
returns trigger
language plpgsql
security invoker
set search_path = ''
as $function$
declare
  v_case_id uuid;
begin
  if new.command_name = 'review_deletion' then
    v_case_id := public.company_access_current_support_case_id_v1();
    if not public.company_access_has_open_support_case_v1(
      v_case_id, new.company_id, 'cancellation'
    ) then
      raise exception 'support_access_not_available' using errcode = 'P0001';
    end if;
    new.support_case_id := v_case_id;
  end if;
  return new;
end;
$function$;

drop trigger if exists company_access_bind_deletion_review_case
  on public.company_access_command_receipts;
create trigger company_access_bind_deletion_review_case
before insert on public.company_access_command_receipts
for each row execute function public.company_access_bind_deletion_review_case_v1();

create or replace function public.company_access_copy_review_case_v1()
returns trigger
language plpgsql
security invoker
set search_path = ''
as $function$
begin
  if new.support_case_id is null then
    new.support_case_id := public.company_access_current_support_case_id_v1();
  end if;
  if not public.company_access_has_open_support_case_v1(
    new.support_case_id, new.company_id, 'cancellation'
  ) then
    raise exception 'support_access_not_available' using errcode = 'P0001';
  end if;
  return new;
end;
$function$;

drop trigger if exists company_access_copy_review_case
  on public.company_deletion_reviews;
create trigger company_access_copy_review_case
before insert on public.company_deletion_reviews
for each row execute function public.company_access_copy_review_case_v1();

drop policy if exists "company access commands update cancellations"
  on public.company_cancellations;
create policy "company access commands update cancellations"
on public.company_cancellations for update to company_access_executor
using (
  public.company_access_is_accepted_owner_v1(company_id)
  or public.company_access_has_open_support_case_v1(
    public.company_access_current_support_case_id_v1(), company_id, 'cancellation'
  )
)
with check (
  public.company_access_has_fresh_mfa_v1() and (
    (status = 'retention_hold' and (
      public.company_access_is_accepted_owner_v1(company_id)
      or public.company_access_has_open_support_case_v1(
        public.company_access_current_support_case_id_v1(), company_id, 'cancellation'
      )
    ))
    or (status = 'deletion_approved' and
      public.company_access_has_open_support_case_v1(
        public.company_access_current_support_case_id_v1(), company_id, 'cancellation'
      )
    )
    or (status = 'deleted' and public.company_access_is_accepted_owner_v1(company_id))
  )
);

drop policy if exists "company access commands append deletion reviews"
  on public.company_deletion_reviews;
create policy "company access commands append deletion reviews"
on public.company_deletion_reviews for insert to company_access_executor
with check (
  reviewed_by = public.company_access_auth_uid_v1()
  and reviewed_by <> requester_id
  and support_case_id = public.company_access_current_support_case_id_v1()
  and public.company_access_has_open_support_case_v1(
    support_case_id, company_id, 'cancellation'
  )
  and exists (
    select 1 from public.company_cancellations c
    where c.id = company_deletion_reviews.cancellation_id
      and c.company_id = company_deletion_reviews.company_id
      and c.requested_by = company_deletion_reviews.requester_id
  )
);

drop policy if exists "company access lifecycle appends audit evidence"
  on public.audit_events;
create policy "company access lifecycle appends audit evidence"
on public.audit_events for insert to company_access_executor
with check (
  actor_id = public.company_access_auth_uid_v1() and (
    public.company_access_is_accepted_owner_v1(company_id)
    or public.company_access_has_open_support_case_v1(
      public.company_access_current_support_case_id_v1(), company_id, 'cancellation'
    )
    or (
      category = 'support_access'
      and action = 'support_case_opened'
      and (
        public.company_access_has_open_support_case_v1(
          public.company_access_current_support_case_id_v1(), company_id, 'profile'
        )
        or public.company_access_has_open_support_case_v1(
          public.company_access_current_support_case_id_v1(), company_id, 'filing'
        )
        or public.company_access_has_open_support_case_v1(
          public.company_access_current_support_case_id_v1(), company_id, 'billing'
        )
        or public.company_access_has_open_support_case_v1(
          public.company_access_current_support_case_id_v1(), company_id, 'audit'
        )
        or public.company_access_has_open_support_case_v1(
          public.company_access_current_support_case_id_v1(), company_id, 'cancellation'
        )
        or public.company_access_has_open_support_case_v1(
          public.company_access_current_support_case_id_v1(), company_id, 'authority'
        )
        or public.company_access_has_open_support_case_v1(
          public.company_access_current_support_case_id_v1(), company_id, 'documents'
        )
        or public.company_access_has_open_support_case_v1(
          public.company_access_current_support_case_id_v1(), company_id, 'production'
        )
      )
    )
    or public.company_access_is_active_admin_v1()
  )
);

drop policy if exists "company access commands read receipts"
  on public.company_access_command_receipts;
create policy "company access commands read receipts"
on public.company_access_command_receipts for select to company_access_executor
using (
  actor_id = public.company_access_auth_uid_v1() and (
    command_name = 'accept_invitation'
    or (
      command_name in (
        'create_invitation', 'revoke_invitation', 'resend_invitation',
        'administer_membership', 'request_cancellation',
        'resume_cancellation', 'finalize_deletion',
        'onboard_company', 'reaccept_agreement'
      )
      and expires_at > pg_catalog.statement_timestamp()
    )
    or (
      command_name = 'review_deletion'
      and expires_at > pg_catalog.statement_timestamp()
      and support_case_id = public.company_access_current_support_case_id_v1()
      and public.company_access_has_open_support_case_v1(
        support_case_id, company_id, 'cancellation'
      )
    )
  )
);

create or replace function public.company_access_support_review_operation_available_v1(
  p_operation_id uuid,
  p_support_case_id uuid
)
returns boolean
language sql
stable
security definer
set search_path = ''
as $function$
  select p_operation_id is not null
    and p_support_case_id is not null
    and public.company_access_auth_uid_v1() is not null
    and (
      not exists (
        select 1 from public.company_access_command_receipts r
        where r.actor_id = public.company_access_auth_uid_v1()
          and r.operation_id = p_operation_id
      )
      or exists (
        select 1 from public.company_access_command_receipts r
        where r.actor_id = public.company_access_auth_uid_v1()
          and r.operation_id = p_operation_id
          and r.command_name = 'review_deletion'
          and r.support_case_id = p_support_case_id
      )
    );
$function$;

create or replace function public.company_access_review_deletion(
  p_operation_id uuid,
  p_support_case_id uuid,
  p_cancellation_id uuid,
  p_company_id uuid,
  p_expected_updated_at timestamptz,
  p_decision text,
  p_evidence_reference text
)
returns table (
  id uuid, company_id uuid, status text, reason text, evidence jsonb,
  requested_by uuid, requested_at timestamptz, reviewed_by uuid,
  reviewed_at timestamptz, deleted_by uuid, deleted_at timestamptz,
  updated_at timestamptz, review jsonb
)
language plpgsql
security definer
set search_path = ''
as $function$
begin
  perform pg_catalog.set_config('talli.support_case_id', p_support_case_id::text, true);
  if not public.company_access_has_open_support_case_v1(
    p_support_case_id, p_company_id, 'cancellation'
  ) then
    raise exception 'support_access_not_available' using errcode = 'P0001';
  end if;
  if not public.company_access_support_review_operation_available_v1(
    p_operation_id, p_support_case_id
  ) then
    raise exception 'support_access_operation_conflict' using errcode = 'P0001';
  end if;
  return query
  select * from public.company_access_review_deletion(
    p_operation_id, p_cancellation_id, p_company_id, p_expected_updated_at,
    p_decision, p_evidence_reference
  );
end;
$function$;

create or replace function public.company_access_reconcile_cancellation_operation(
  p_operation_id uuid,
  p_command_name text,
  p_company_id uuid,
  p_support_case_id uuid default null,
  p_cancellation_id uuid default null,
  p_income_year integer default null,
  p_reason text default null,
  p_expected_updated_at timestamptz default null,
  p_decision text default null,
  p_evidence_reference text default null
)
returns table(found boolean, result jsonb)
language plpgsql
security definer
set search_path = ''
as $function$
begin
  if p_command_name = 'review_deletion' then
    perform pg_catalog.set_config('talli.support_case_id', p_support_case_id::text, true);
    if not public.company_access_has_open_support_case_v1(
      p_support_case_id, p_company_id, 'cancellation'
    ) then
      raise exception 'support_access_not_available' using errcode = 'P0001';
    end if;
    if not public.company_access_support_review_operation_available_v1(
      p_operation_id, p_support_case_id
    ) then
      raise exception 'support_access_operation_conflict' using errcode = 'P0001';
    end if;
  end if;
  return query
  select * from public.company_access_reconcile_cancellation_operation(
    p_operation_id, p_command_name, p_company_id, p_cancellation_id,
    p_income_year, p_reason, p_expected_updated_at, p_decision,
    p_evidence_reference
  );
end;
$function$;

-- The old overloads remain only as internal implementation details. Their
-- table policies and receipt trigger fail closed without an exact opened case.

create or replace function public.company_access_revoke_support_access(
  p_operation_id uuid,
  p_case_id uuid,
  p_revocation_reason text
)
returns table (
  case_id uuid, company_id uuid, operator_user_id uuid, reason text,
  scopes text[], starts_at timestamptz, expires_at timestamptz,
  granted_by uuid, granted_at timestamptz, revoked_at timestamptz,
  revoked_by uuid, revocation_reason text
)
language plpgsql
security definer
set search_path = ''
as $function$
declare
  v_actor_id uuid := public.company_access_auth_uid_v1();
  v_request jsonb;
  v_fingerprint text;
  v_receipt public.support_access_operation_receipts%rowtype;
  v_grant public.support_access_grants%rowtype;
begin
  if p_operation_id is null or p_case_id is null or v_actor_id is null
    or not public.company_access_is_active_admin_v1()
    or not public.company_access_has_fresh_mfa_v1()
  then
    raise exception 'support_access_not_available' using errcode = 'P0001';
  end if;
  if p_revocation_reason is null or p_revocation_reason <> all (array[
    'case_closed', 'access_no_longer_needed', 'operator_removed',
    'security_response', 'grant_replaced'
  ]) then
    raise exception 'support_access_invalid_request' using errcode = 'P0001';
  end if;
  v_request := pg_catalog.jsonb_build_object(
    'caseId', p_case_id, 'reason', p_revocation_reason
  );
  v_fingerprint := pg_catalog.encode(
    extensions.digest(v_request::text, 'sha256'), 'hex'
  );
  perform public.company_access_lock_operation_v1(v_actor_id, p_operation_id);
  select r.* into v_receipt
  from public.support_access_operation_receipts r
  where r.actor_id = v_actor_id and r.operation_id = p_operation_id;
  if found then
    if v_receipt.command_name <> 'revoke_support_access'
      or v_receipt.request_fingerprint <> v_fingerprint
    then
      raise exception 'support_access_operation_conflict' using errcode = 'P0001';
    end if;
    return query select * from pg_catalog.jsonb_populate_record(
      null::public.support_access_grants, v_receipt.result
    );
    return;
  end if;
  select g.* into v_grant from public.support_access_grants g
  where g.case_id = p_case_id for update;
  if not found or v_grant.revoked_at is not null then
    raise exception 'support_access_not_available' using errcode = 'P0001';
  end if;
  update public.support_access_grants g
  set revoked_at = pg_catalog.clock_timestamp(), revoked_by = v_actor_id,
      revocation_reason = p_revocation_reason
  where g.case_id = p_case_id returning * into v_grant;
  insert into public.audit_events (company_id, actor_id, category, action, message)
  values (
    v_grant.company_id, v_actor_id, 'support_access', 'support_access_revoked',
    'The case-bound support grant was revoked.'
  );
  insert into public.support_access_operation_receipts (
    actor_id, operation_id, command_name, case_id, request_fingerprint,
    request_payload, result
  ) values (
    v_actor_id, p_operation_id, 'revoke_support_access', p_case_id,
    v_fingerprint, v_request, pg_catalog.to_jsonb(v_grant)
  );
  return query select v_grant.*;
end;
$function$;

create or replace function public.company_access_open_support_case(
  p_operation_id uuid,
  p_case_id uuid
)
returns table (
  operation_id uuid, case_id uuid, company_id uuid,
  opened_by uuid, opened_at timestamptz
)
language plpgsql
security definer
set search_path = ''
as $function$
declare
  v_actor_id uuid := public.company_access_auth_uid_v1();
  v_request jsonb;
  v_fingerprint text;
  v_receipt public.support_access_operation_receipts%rowtype;
  v_grant public.support_access_grants%rowtype;
  v_opening public.support_case_openings%rowtype;
begin
  if p_operation_id is null or p_case_id is null or v_actor_id is null
    or not public.company_access_is_active_operator_v1()
    or not public.company_access_has_fresh_mfa_v1()
  then
    raise exception 'support_access_not_available' using errcode = 'P0001';
  end if;
  v_request := pg_catalog.jsonb_build_object('caseId', p_case_id);
  v_fingerprint := pg_catalog.encode(
    extensions.digest(v_request::text, 'sha256'), 'hex'
  );
  perform public.company_access_lock_operation_v1(v_actor_id, p_operation_id);
  select r.* into v_receipt
  from public.support_access_operation_receipts r
  where r.actor_id = v_actor_id and r.operation_id = p_operation_id;
  if found then
    if v_receipt.command_name <> 'open_support_case'
      or v_receipt.request_fingerprint <> v_fingerprint
    then
      raise exception 'support_access_operation_conflict' using errcode = 'P0001';
    end if;
    return query select
      (v_receipt.result ->> 'operation_id')::uuid,
      (v_receipt.result ->> 'case_id')::uuid,
      (v_receipt.result ->> 'company_id')::uuid,
      (v_receipt.result ->> 'opened_by')::uuid,
      (v_receipt.result ->> 'opened_at')::timestamptz;
    return;
  end if;
  select g.* into v_grant from public.support_access_grants g
  where g.case_id = p_case_id
    and g.operator_user_id = v_actor_id
    and g.revoked_at is null
    and pg_catalog.statement_timestamp() >= g.starts_at
    and pg_catalog.statement_timestamp() < g.expires_at;
  if not found then
    raise exception 'support_access_not_available' using errcode = 'P0001';
  end if;
  insert into public.support_case_openings (
    actor_id, operation_id, case_id, company_id
  ) values (
    v_actor_id, p_operation_id, p_case_id, v_grant.company_id
  )
  returning * into v_opening;
  perform pg_catalog.set_config('talli.support_case_id', p_case_id::text, true);
  insert into public.audit_events (company_id, actor_id, category, action, message)
  values (
    v_grant.company_id, v_actor_id, 'support_access', 'support_case_opened',
    'The operator explicitly opened the authorized support case.'
  );
  insert into public.support_access_operation_receipts (
    actor_id, operation_id, command_name, case_id, request_fingerprint,
    request_payload, result
  ) values (
    v_actor_id, p_operation_id, 'open_support_case', p_case_id, v_fingerprint,
    v_request,
    pg_catalog.jsonb_build_object(
      'operation_id', v_opening.operation_id, 'case_id', v_opening.case_id,
      'company_id', v_opening.company_id, 'opened_by', v_opening.actor_id,
      'opened_at', v_opening.opened_at
    )
  );
  return query select v_opening.operation_id, v_opening.case_id,
    v_opening.company_id, v_opening.actor_id, v_opening.opened_at;
end;
$function$;

revoke all on function public.company_access_bind_deletion_review_case_v1(),
  public.company_access_copy_review_case_v1(),
  public.company_access_support_review_operation_available_v1(uuid, uuid)
from public, anon, authenticated, service_role;
grant execute on function
  public.company_access_support_review_operation_available_v1(uuid, uuid)
to company_access_executor;

do $function_ownership$
begin
  grant create on schema public to company_access_executor;
  alter function public.company_access_current_support_case_id_v1()
    owner to company_access_executor;
  alter function public.company_access_has_open_support_case_v1(uuid, uuid, text)
    owner to company_access_executor;
  alter function public.company_access_support_storage_company_id_v1(text)
    owner to company_access_executor;
  alter function public.company_access_grant_support_access(
    uuid, uuid, uuid, text, text[], timestamptz, timestamptz
  ) owner to company_access_executor;
  alter function public.company_access_revoke_support_access(uuid, uuid, text)
    owner to company_access_executor;
  alter function public.company_access_open_support_case(uuid, uuid)
    owner to company_access_executor;
  alter function public.company_access_read_support_case(uuid)
    owner to company_access_executor;
  alter function public.company_access_review_deletion(
    uuid, uuid, uuid, uuid, timestamptz, text, text
  ) owner to company_access_executor;
  alter function public.company_access_reconcile_cancellation_operation(
    uuid, text, uuid, uuid, uuid, integer, text, timestamptz, text, text
  ) owner to company_access_executor;
  revoke create on schema public from company_access_executor;
end
$function_ownership$;

set role company_access_executor;
revoke all on function public.company_access_current_support_case_id_v1(),
  public.company_access_has_open_support_case_v1(uuid, uuid, text),
  public.company_access_support_storage_company_id_v1(text),
  public.company_access_grant_support_access(
    uuid, uuid, uuid, text, text[], timestamptz, timestamptz
  ),
  public.company_access_revoke_support_access(uuid, uuid, text),
  public.company_access_open_support_case(uuid, uuid),
  public.company_access_read_support_case(uuid),
  public.company_access_review_deletion(
    uuid, uuid, uuid, uuid, timestamptz, text, text
  ),
  public.company_access_reconcile_cancellation_operation(
    uuid, text, uuid, uuid, uuid, integer, text, timestamptz, text, text
  ),
  public.company_access_review_deletion(
    uuid, uuid, uuid, timestamptz, text, text
  ),
  public.company_access_reconcile_cancellation_operation(
    uuid, text, uuid, uuid, integer, text, timestamptz, text, text
  )
from public, anon, authenticated, service_role;

grant execute on function public.company_access_current_support_case_id_v1(),
  public.company_access_has_open_support_case_v1(uuid, uuid, text),
  public.company_access_support_storage_company_id_v1(text),
  public.company_access_grant_support_access(
    uuid, uuid, uuid, text, text[], timestamptz, timestamptz
  ),
  public.company_access_revoke_support_access(uuid, uuid, text),
  public.company_access_open_support_case(uuid, uuid),
  public.company_access_read_support_case(uuid),
  public.company_access_review_deletion(
    uuid, uuid, uuid, uuid, timestamptz, text, text
  ),
  public.company_access_reconcile_cancellation_operation(
    uuid, text, uuid, uuid, uuid, integer, text, timestamptz, text, text
  ),
  public.company_access_review_deletion(
    uuid, uuid, uuid, timestamptz, text, text
  ),
  public.company_access_reconcile_cancellation_operation(
    uuid, text, uuid, uuid, integer, text, timestamptz, text, text
  )
to company_access_executor;
reset role;

do $function_ownership_cleanup$
begin
  execute pg_catalog.format('revoke company_access_executor from %I', current_user);
end
$function_ownership_cleanup$;

comment on table public.support_access_grants is
  'Generated, company/scope/time/operator-bound support cases. No customer text.';
comment on table public.support_access_operation_receipts is
  'Immutable idempotency evidence for support grant, revoke, and explicit open commands.';
comment on table public.support_case_openings is
  'Durable explicit support-case opening evidence; read operations never write it.';

commit;
