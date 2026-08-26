-- CONTRACT RELEASE ARTIFACT: #138 company-access backend authority cutover.
-- Apply only after the generated client/web cutover and the backend database
-- adapter runtime rehearsal pass. This file is intentionally outside the
-- automatic Supabase migration runner.

begin;

-- Never silently delete historical step-up evidence. This preflight must run
-- before any grant, policy, function, or archive seam is changed so a failed
-- contract leaves the overlap phase untouched.
do $retired_step_up_preflight$
begin
  if pg_catalog.to_regclass('public.step_up_events') is not null
    and exists (select 1 from public.step_up_events)
  then
    raise exception 'company_access_contract_step_up_events_not_empty';
  end if;
end
$retired_step_up_preflight$;

do $membership$
begin
  execute pg_catalog.format(
    'grant company_access_executor, company_access_recovery_executor, company_archive_projection_executor to %I',
    current_user
  );
end
$membership$;

-- The archive capability is serialized after company-access. Preserve its
-- authenticated authority seam before company-access identity becomes
-- backend-only.
create or replace function public.company_archive_authenticated_uid_v1()
returns uuid
language sql
stable
security definer
set search_path = ''
as $function$
  select auth.uid();
$function$;

create or replace function public.company_archive_authenticated_has_fresh_mfa_v1()
returns boolean
language sql
stable
security definer
set search_path = ''
as $function$
  select coalesce(auth.jwt() ->> 'aal', '') = 'aal2'
    and exists (
      select 1
      from pg_catalog.jsonb_array_elements(
        case when pg_catalog.jsonb_typeof(auth.jwt() -> 'amr') = 'array'
          then auth.jwt() -> 'amr' else '[]'::jsonb end
      ) entry
      where entry ->> 'method' in ('totp', 'mfa/totp', 'mfa/phone', 'mfa/webauthn')
        and pg_catalog.jsonb_typeof(entry -> 'timestamp') = 'number'
        and pg_catalog.to_timestamp((entry ->> 'timestamp')::double precision)
          between pg_catalog.statement_timestamp() - interval '15 minutes'
              and pg_catalog.statement_timestamp()
    );
$function$;

create or replace function public.company_archive_authenticated_owner_v1(p_company_id uuid)
returns boolean
language sql
stable
security definer
set search_path = ''
as $function$
  select exists (
    select 1 from public.company_memberships m
    where m.company_id = p_company_id
      and m.user_id = public.company_archive_authenticated_uid_v1()
      and m.role = 'owner'
      and m.accepted_at is not null
  );
$function$;

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
      'public.company_access_auth_uid_v1()',
      'public.company_archive_authenticated_uid_v1()'
    );
    v_definition := pg_catalog.replace(
      v_definition,
      'public.company_access_has_fresh_mfa_v1()',
      'public.company_archive_authenticated_has_fresh_mfa_v1()'
    );
    v_definition := pg_catalog.replace(
      v_definition,
      'public.company_access_is_accepted_owner_v1(p_company_id)',
      'public.company_archive_authenticated_owner_v1(p_company_id)'
    );
    execute 'set local role company_archive_projection_executor';
    execute v_definition;
    execute 'reset role';
    revoke create on schema public from company_archive_projection_executor;
  end if;
end
$archive_seam$;

revoke all on function public.company_archive_authenticated_owner_v1(uuid)
  from public, anon, authenticated, service_role;
revoke all on function public.company_archive_authenticated_uid_v1(),
  public.company_archive_authenticated_has_fresh_mfa_v1()
  from public, anon, authenticated, service_role;
grant execute on function public.company_archive_authenticated_owner_v1(uuid),
  public.company_archive_authenticated_uid_v1(),
  public.company_archive_authenticated_has_fresh_mfa_v1()
  to company_archive_projection_executor;

-- From this point the company-access policy seam accepts only identity that the
-- backend installed transaction-locally after validating /auth/v1/user and the
-- bearer subject. Missing actor context fails closed.
create or replace function public.company_access_auth_uid_v1()
returns uuid
language sql
stable
security definer
set search_path = ''
as $function$
  select nullif(
    pg_catalog.current_setting('talli.verified_actor_id', true), ''
  )::uuid;
$function$;

create or replace function public.company_access_auth_jwt_v1()
returns jsonb
language sql
stable
security definer
set search_path = ''
as $function$
  select public.company_access_verified_claims_v1();
$function$;

-- Preserve the future audit writer's characterized browser behavior without
-- retaining a callable company-access RPC in the exposed public Data API
-- schema. The helper is deliberately caller-bound and exposes no company or
-- membership fields.
create or replace function company_access_policy.authenticated_can_append_audit_v1(
  p_company_id uuid,
  p_actor_id uuid
)
returns boolean
language sql
stable
security definer
set search_path = ''
as $function$
  select (select auth.uid()) is not null
    and p_actor_id = (select auth.uid())
    and (
      exists (
        select 1
        from public.companies c
        where c.id = p_company_id
          and c.created_by = (select auth.uid())
      )
      or exists (
        select 1
        from public.company_memberships m
        where m.company_id = p_company_id
          and m.user_id = (select auth.uid())
      )
    );
$function$;

revoke all on function company_access_policy.authenticated_can_append_audit_v1(uuid, uuid)
  from public, anon, authenticated, service_role;
grant execute on function company_access_policy.authenticated_can_append_audit_v1(uuid, uuid)
  to authenticated;

drop policy if exists "company members can create audit events for themselves"
  on public.audit_events;
create policy "company members can create audit events for themselves"
on public.audit_events for insert
to authenticated
with check (
  company_access_policy.authenticated_can_append_audit_v1(company_id, actor_id)
);

-- The expand migration must have moved every retained policy to its private,
-- caller-bound projection before direct table authority can be revoked.
do $policy_schema_preflight$
begin
  if pg_catalog.to_regnamespace('company_access_policy') is null
    or pg_catalog.to_regprocedure(
      'company_access_policy.authenticated_actor_memberships_v1()'
    ) is null
    or pg_catalog.to_regprocedure(
      'company_access_policy.authenticated_actor_operator_grants_v1()'
    ) is null
    or exists (
      select 1
      from pg_catalog.pg_policies
      where 'authenticated' = any(roles)
        and concat_ws(' ', qual, with_check)
          ~ '\m(company_memberships|support_operators)\M'
        and not (
          schemaname = 'public'
          and tablename = any(array[
            'companies', 'company_memberships', 'company_invitations',
            'company_cancellations', 'company_deletion_reviews',
            'company_access_command_receipts',
            'customer_agreement_acceptances', 'support_operators'
          ])
        )
    )
  then
    raise exception 'company_access_contract_policy_schema_unavailable';
  end if;
end
$policy_schema_preflight$;

-- Browser-facing roles lose all direct business-table privileges. Other
-- capability-owned security-definer functions may continue to consume these
-- records during their serialized migrations.
revoke all on table
  public.companies,
  public.company_memberships,
  public.company_invitations,
  public.company_cancellations,
  public.company_deletion_reviews,
  public.company_access_command_receipts,
  public.customer_agreement_acceptances,
  public.support_operators
from public, anon, authenticated, service_role;

-- Remove only policies whose role target still exposed a direct browser path;
-- restricted executor/recovery policies remain the canonical RLS boundary.
do $browser_policies$
declare
  v_policy record;
begin
  for v_policy in
    select schemaname, tablename, policyname
    from pg_catalog.pg_policies
    where schemaname = 'public'
      and tablename = any(array[
        'companies', 'company_memberships', 'company_invitations',
        'company_cancellations', 'company_deletion_reviews',
        'company_access_command_receipts',
        'customer_agreement_acceptances', 'support_operators'
      ])
      and (
        'authenticated' = any(roles)
        or 'anon' = any(roles)
        or 'public' = any(roles)
      )
  loop
    execute pg_catalog.format(
      'drop policy if exists %I on %I.%I',
      v_policy.policyname, v_policy.schemaname, v_policy.tablename
    );
  end loop;
end
$browser_policies$;

-- Every company-access RPC is backend-only after cutover.
set role company_access_executor;
revoke all on function public.company_access_onboard_company(
  uuid,uuid,text,text,text,text,text,text,text,text,text,boolean,text,date,text,text,text,date,text,text,text,text
) from public, anon, authenticated, service_role;
revoke all on function public.company_access_reaccept_agreement(
  uuid,uuid,uuid,text,boolean,text,date,text,text,text,date,text,text,text,text
) from public, anon, authenticated, service_role;
revoke all on function public.company_access_create_invitation(uuid,uuid,text,text,text,text)
  from public, anon, authenticated, service_role;
revoke all on function public.company_access_lookup_invitation(text,uuid,text)
  from public, anon, authenticated, service_role;
revoke all on function public.company_access_accept_invitation(uuid,text,uuid,text)
  from public, anon, authenticated, service_role;
revoke all on function public.company_access_revoke_invitation(uuid,uuid,uuid,timestamptz)
  from public, anon, authenticated, service_role;
revoke all on function public.company_access_resend_invitation(uuid,uuid,uuid,timestamptz,text,text)
  from public, anon, authenticated, service_role;
revoke all on function public.company_access_administer_membership(uuid,uuid,uuid,text,text,text)
  from public, anon, authenticated, service_role;
revoke all on function public.company_access_list_cancellations(uuid)
  from public, anon, authenticated, service_role;
revoke all on function public.company_access_request_cancellation(uuid,uuid,integer,text)
  from public, anon, authenticated, service_role;
revoke all on function public.company_access_resume_cancellation(uuid,uuid,uuid,integer,timestamptz)
  from public, anon, authenticated, service_role;
revoke all on function public.company_access_review_deletion(uuid,uuid,uuid,timestamptz,text,text)
  from public, anon, authenticated, service_role;
revoke all on function public.company_access_finalize_deletion(uuid,uuid,uuid,timestamptz)
  from public, anon, authenticated, service_role;
revoke all on function public.company_access_reconcile_cancellation_operation(uuid,text,uuid,uuid,integer,text,timestamptz,text,text)
  from public, anon, authenticated, service_role;

grant execute on function public.company_access_onboard_company(
  uuid,uuid,text,text,text,text,text,text,text,text,text,boolean,text,date,text,text,text,date,text,text,text,text
) to company_access_executor;
grant execute on function public.company_access_reaccept_agreement(
  uuid,uuid,uuid,text,boolean,text,date,text,text,text,date,text,text,text,text
) to company_access_executor;
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
to company_access_executor;
reset role;

set role company_access_recovery_executor;
revoke all on function public.company_access_pending_invitation_side_effects(),
  public.company_access_complete_invitation_side_effect(uuid)
  from public, anon, authenticated, service_role;
grant execute on function public.company_access_pending_invitation_side_effects(),
  public.company_access_complete_invitation_side_effect(uuid)
  to company_access_recovery_executor;
reset role;

-- The authenticated overlap helpers are no longer needed once their policies
-- have been removed. Revoke them explicitly so the exposed public schema has
-- no authenticated-callable company-access RPC after Stage 1 exit.
revoke all on function public.company_access_auth_uid_v1(),
  public.company_access_auth_jwt_v1(),
  public.company_access_is_accepted_owner_v1(uuid)
from public, anon, authenticated, service_role;

-- Remove frozen legacy service-role facades only after their replacement has
-- passed runtime evidence. Durable company, membership, acceptance, audit and
-- receipt data is intentionally untouched.
revoke all on function public.create_company_workspace_with_acceptance(
  uuid,text,text,text,text,text,text,text,text,text,date,text,text,text,date,text,text,text,text
) from public, anon, authenticated, service_role;
drop function if exists public.create_company_workspace_with_acceptance(
  uuid,text,text,text,text,text,text,text,text,text,date,text,text,text,date,text,text,text,text
);
revoke all on function public.append_company_agreement_acceptance(
  uuid,uuid,text,date,text,text,text,date,text,text,text,text
) from public, anon, authenticated, service_role;
drop function if exists public.append_company_agreement_acceptance(
  uuid,uuid,text,date,text,text,text,date,text,text,text,text
);

-- Superseded by the canonical JWT AAL2 helper in 20260715084507. Repository
-- dependency and runtime catalog probes must pass before this staged artifact
-- is applied.
drop table if exists public.step_up_events;

do $membership$
begin
  execute pg_catalog.format(
    'revoke company_access_executor, company_access_recovery_executor, company_archive_projection_executor from %I',
    current_user
  );
end
$membership$;

commit;
