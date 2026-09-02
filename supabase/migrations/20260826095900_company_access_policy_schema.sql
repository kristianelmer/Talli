-- Private execution schema for caller-bound RLS projections used during the
-- serialized capability migrations. Supabase exposes public/storage through
-- the Data API; this schema is deliberately not an exposed API schema.

create schema if not exists company_access_policy;

revoke all on schema company_access_policy from public, anon, service_role;
grant usage on schema company_access_policy to authenticated;

do $migration_owner_access$
begin
  if exists (
    select 1 from pg_catalog.pg_roles where rolname = 'talli_migration_owner'
  ) then
    grant usage, create on schema company_access_policy to talli_migration_owner;
  end if;
end
$migration_owner_access$;

create or replace function company_access_policy.authenticated_actor_memberships_v1()
returns table (
  company_id uuid,
  user_id uuid,
  role text,
  accepted_at timestamptz
)
language sql
stable
security definer
set search_path = ''
as $function$
  select m.company_id, m.user_id, m.role, m.accepted_at
  from public.company_memberships m
  where (select auth.uid()) is not null
    and m.user_id = (select auth.uid());
$function$;

create or replace function company_access_policy.authenticated_actor_operator_grants_v1()
returns table (
  user_id uuid,
  role text,
  active boolean
)
language sql
stable
security definer
set search_path = ''
as $function$
  select o.user_id, o.role, o.active
  from public.support_operators o
  where (select auth.uid()) is not null
    and o.user_id = (select auth.uid());
$function$;

revoke all on function
  company_access_policy.authenticated_actor_memberships_v1(),
  company_access_policy.authenticated_actor_operator_grants_v1()
from public, anon, authenticated, service_role;
grant execute on function
  company_access_policy.authenticated_actor_memberships_v1(),
  company_access_policy.authenticated_actor_operator_grants_v1()
to authenticated;

-- Preserve every non-company-access policy predicate byte-for-byte while
-- replacing only its caller-owned membership/operator relation. The private
-- projections expose no cross-tenant rows and are not in a Data API schema.
do $future_policy_seams$
declare
  v_policy record;
  v_using text;
  v_check text;
  v_statement text;
begin
  for v_policy in
    select schemaname, tablename, policyname, qual, with_check
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
      and not (
        schemaname = 'public'
        and tablename = 'audit_events'
        and policyname = 'company members can create audit events for themselves'
      )
  loop
    v_using := v_policy.qual;
    v_check := v_policy.with_check;
    if v_using is not null then
      v_using := pg_catalog.replace(
        pg_catalog.replace(
          v_using,
          'public.company_memberships',
          'company_access_policy.authenticated_actor_memberships_v1()'
        ),
        'company_memberships',
        'company_access_policy.authenticated_actor_memberships_v1()'
      );
      v_using := pg_catalog.replace(
        pg_catalog.replace(
          v_using,
          'public.support_operators',
          'company_access_policy.authenticated_actor_operator_grants_v1()'
        ),
        'support_operators',
        'company_access_policy.authenticated_actor_operator_grants_v1()'
      );
    end if;
    if v_check is not null then
      v_check := pg_catalog.replace(
        pg_catalog.replace(
          v_check,
          'public.company_memberships',
          'company_access_policy.authenticated_actor_memberships_v1()'
        ),
        'company_memberships',
        'company_access_policy.authenticated_actor_memberships_v1()'
      );
      v_check := pg_catalog.replace(
        pg_catalog.replace(
          v_check,
          'public.support_operators',
          'company_access_policy.authenticated_actor_operator_grants_v1()'
        ),
        'support_operators',
        'company_access_policy.authenticated_actor_operator_grants_v1()'
      );
    end if;
    v_statement := pg_catalog.format(
      'alter policy %I on %I.%I',
      v_policy.policyname, v_policy.schemaname, v_policy.tablename
    );
    if v_using is not null then
      v_statement := v_statement || pg_catalog.format(' using (%s)', v_using);
    end if;
    if v_check is not null then
      v_statement := v_statement || pg_catalog.format(' with check (%s)', v_check);
    end if;
    execute v_statement;
  end loop;

  if exists (
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
      and not (
        schemaname = 'public'
        and tablename = 'audit_events'
        and policyname = 'company members can create audit events for themselves'
      )
  ) then
    raise exception 'company_access_policy_dependency_remains';
  end if;
end
$future_policy_seams$;
