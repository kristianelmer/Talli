-- Preserve cancellation intent before rolling back any predecessor billing table.
begin;
do $borrow$
begin
  execute pg_catalog.format('grant billing_store_owner to %I', current_user);
end;
$borrow$;
set local role billing_store_owner;
revoke all on billing.annual_cancellation_requests from public, anon, authenticated, service_role, billing_executor, billing_store_owner;
drop policy if exists annual_cancellation_owner_read on billing.annual_cancellation_requests;
drop policy if exists annual_cancellation_owner_request on billing.annual_cancellation_requests;
drop trigger if exists annual_cancellation_prepare on billing.annual_cancellation_requests;
drop trigger if exists annual_cancellation_apply on billing.annual_cancellation_requests;
drop trigger if exists annual_cancellation_immutable on billing.annual_cancellation_requests;
alter table billing.annual_cancellation_requests set schema billing_annual_retired;
drop function billing.apply_annual_cancellation_request_v1();
reset role;
do $return_authority$
begin
  execute pg_catalog.format('revoke billing_store_owner from %I', current_user);
end;
$return_authority$;
commit;
