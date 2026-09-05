-- Preserve every pending intent/outcome while withdrawing settlement authority.
begin;
do $authority$
begin
  execute pg_catalog.format('grant billing_store_owner to %I', current_user);
end
$authority$;
set local role billing_store_owner;
drop policy if exists billing_payment_events_backend_owner_reconcile
on billing.billing_payment_events;
reset role;
do $authority$
begin
  execute pg_catalog.format('revoke billing_store_owner from %I', current_user);
end
$authority$;
commit;
