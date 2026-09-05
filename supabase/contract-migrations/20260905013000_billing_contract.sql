-- CONTRACT RELEASE ARTIFACT: billing stage exit #137.
-- Remove the public Data API compatibility surface after the web cutover.
begin;

set local lock_timeout = '5s';
set local statement_timeout = '120s';

do $membership$
begin
  execute pg_catalog.format(
    'grant billing_store_owner, billing_executor, company_access_executor to %I',
    current_user
  );
end
$membership$;

-- PL/pgSQL stores relation references in function bodies as source text. Move
-- every downstream legacy filing/support reader to the canonical billing
-- relation before removing the temporary public views. The obsolete billing
-- writer RPC is deliberately excluded and removed below.
do $rewrite_downstream_readers$
declare
  routine record;
  definition text;
begin
  for routine in
    select procedure.oid,
      namespace.nspname,
      procedure.proname,
      pg_catalog.pg_get_function_identity_arguments(procedure.oid) as arguments
    from pg_catalog.pg_proc procedure
    join pg_catalog.pg_namespace namespace on namespace.oid = procedure.pronamespace
    where procedure.prokind = 'f'
      and procedure.proname <> 'manage_production_pilot_entitlement'
      and (
        procedure.prosrc like '%public.production_pilot_entitlements%'
        or procedure.prosrc like '%public.billing_accounts%'
        or procedure.prosrc like '%public.billing_payment_events%'
      )
  loop
    definition := pg_catalog.pg_get_functiondef(routine.oid);
    definition := pg_catalog.replace(
      definition,
      'public.production_pilot_entitlements',
      'billing.production_pilot_entitlements'
    );
    definition := pg_catalog.replace(
      definition, 'public.billing_accounts', 'billing.billing_accounts'
    );
    definition := pg_catalog.replace(
      definition, 'public.billing_payment_events', 'billing.billing_payment_events'
    );
    execute definition;
  end loop;
end
$rewrite_downstream_readers$;

drop function if exists public.manage_production_pilot_entitlement(
  uuid, uuid, uuid, integer, text, boolean, uuid,
  timestamptz, timestamptz, text
);

drop policy if exists "company members can read billing accounts"
  on billing.billing_accounts;
drop policy if exists "support operators can read billing accounts"
  on billing.billing_accounts;
drop policy if exists "owners can create billing accounts"
  on billing.billing_accounts;
drop policy if exists "owners can update billing accounts"
  on billing.billing_accounts;
drop policy if exists "company members can read billing payment events"
  on billing.billing_payment_events;
drop policy if exists "support operators can read billing payment events"
  on billing.billing_payment_events;
drop policy if exists "owners can create billing payment events"
  on billing.billing_payment_events;
drop policy if exists "company members read production pilot entitlements"
  on billing.production_pilot_entitlements;
drop policy if exists "active operators read production pilot entitlements"
  on billing.production_pilot_entitlements;

revoke all on public.billing_accounts,
  public.billing_payment_events,
  public.production_pilot_entitlements
from public, anon, authenticated, service_role;

drop view public.billing_payment_events;
drop view public.billing_accounts;
drop view public.production_pilot_entitlements;

-- Direct roles remain denied even if a future schema exposure changes.
revoke all on billing.billing_accounts,
  billing.billing_payment_events,
  billing.production_pilot_entitlements
from public, anon, authenticated, service_role;
revoke usage on schema billing from authenticated, service_role;

do $assertions$
begin
  if pg_catalog.to_regclass('public.billing_accounts') is not null
    or pg_catalog.to_regclass('public.billing_payment_events') is not null
    or pg_catalog.to_regclass('public.production_pilot_entitlements') is not null
    or pg_catalog.to_regclass('billing.billing_accounts') is null
    or pg_catalog.to_regclass('billing.billing_payment_events') is null
    or pg_catalog.to_regclass('billing.production_pilot_entitlements') is null
  then
    raise exception 'billing_contract_boundary_failed';
  end if;
end
$assertions$;

do $cleanup$
begin
  execute pg_catalog.format(
    'revoke billing_store_owner, billing_executor, company_access_executor from %I',
    current_user
  );
end
$cleanup$;

commit;
