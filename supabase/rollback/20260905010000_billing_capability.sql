-- Restore the predecessor public-table topology before the contract release.
begin;

do $membership$
begin
  execute pg_catalog.format(
    'grant billing_store_owner, billing_executor to %I', current_user
  );
end
$membership$;

drop table if exists billing.billing_command_receipts;

drop view if exists public.billing_payment_events;
drop view if exists public.billing_accounts;
drop view if exists public.production_pilot_entitlements;

drop policy if exists billing_accounts_backend_member_read
  on billing.billing_accounts;
drop policy if exists billing_accounts_backend_owner_write
  on billing.billing_accounts;
drop policy if exists billing_payment_events_backend_member_read
  on billing.billing_payment_events;
drop policy if exists billing_payment_events_backend_owner_write
  on billing.billing_payment_events;
drop policy if exists billing_payment_events_backend_owner_read
  on billing.billing_payment_events;
drop policy if exists billing_pilot_entitlements_backend_member_read
  on billing.production_pilot_entitlements;
drop policy if exists billing_pilot_entitlements_backend_admin_write
  on billing.production_pilot_entitlements;
drop policy if exists billing_store_reads_system_user_requests
  on public.system_user_requests;
drop policy if exists billing_store_reads_company_memberships
  on public.company_memberships;
drop policy if exists billing_store_reads_legacy_filing_readiness
  on public.filing_readiness_snapshots;

revoke select on public.filing_readiness_snapshots from billing_store_owner;

alter table billing.billing_accounts owner to current_user;
alter table billing.billing_payment_events owner to current_user;
alter table billing.production_pilot_entitlements owner to current_user;
alter table billing.billing_accounts set schema public;
alter table billing.billing_payment_events set schema public;
alter table billing.production_pilot_entitlements set schema public;

alter table public.billing_accounts no force row level security;
alter table public.billing_payment_events no force row level security;
alter table public.production_pilot_entitlements no force row level security;

grant select, insert, update on public.billing_accounts,
  public.billing_payment_events,
  public.production_pilot_entitlements
to authenticated, service_role;

drop function if exists billing.read_legacy_filing_readiness_v1(uuid, integer, text);
drop schema if exists billing;

do $backend_membership$
begin
  if exists (select 1 from pg_catalog.pg_roles where rolname = 'talli_ledger_backend') then
    revoke billing_executor, billing_store_owner from talli_ledger_backend;
  end if;
end
$backend_membership$;

do $cleanup$
begin
  execute pg_catalog.format(
    'revoke billing_store_owner, billing_executor from %I', current_user
  );
end
$cleanup$;

commit;
