-- Billing commits a created event before provider I/O and settles it only after
-- execution or read-only reconciliation establishes an outcome for the same key.
begin;
do $authority$
begin
  execute pg_catalog.format('grant billing_store_owner to %I', current_user);
end
$authority$;
set local role billing_store_owner;

create policy billing_payment_events_backend_owner_reconcile
on billing.billing_payment_events for update to billing_store_owner
using (
  status in ('created', 'failed')
  and created_by = public.company_access_auth_uid_v1()
  and public.company_access_is_accepted_owner_v1(company_id)
  and public.company_access_has_fresh_mfa_v1()
)
with check (
  created_by = public.company_access_auth_uid_v1()
  and public.company_access_is_accepted_owner_v1(company_id)
  and public.company_access_has_fresh_mfa_v1()
);

reset role;
do $authority$
begin
  execute pg_catalog.format('revoke billing_store_owner from %I', current_user);
end
$authority$;
commit;
