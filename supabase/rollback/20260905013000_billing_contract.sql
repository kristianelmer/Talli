-- Restore the deployment-overlap views for a billing contract rollback.
begin;

do $membership$
begin
  execute pg_catalog.format(
    'grant billing_store_owner, billing_executor to %I', current_user
  );
end
$membership$;

grant usage on schema billing to authenticated, service_role;

create view public.billing_accounts
with (security_invoker = true)
as select * from billing.billing_accounts;
create view public.billing_payment_events
with (security_invoker = true)
as select * from billing.billing_payment_events;
create view public.production_pilot_entitlements
with (security_invoker = true)
as select * from billing.production_pilot_entitlements;

grant select, insert, update on public.billing_accounts,
  public.billing_payment_events,
  public.production_pilot_entitlements
to authenticated, service_role;

do $cleanup$
begin
  execute pg_catalog.format(
    'revoke billing_store_owner, billing_executor from %I', current_user
  );
end
$cleanup$;

commit;
