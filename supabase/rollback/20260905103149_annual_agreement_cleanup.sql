-- Remove the guard before cancellation/ledger rollback; retain all operations.
begin;
do $borrow$
begin
  execute pg_catalog.format('grant billing_store_owner to %I', current_user);
end;
$borrow$;
set local role billing_store_owner;
drop trigger if exists annual_cleanup_claim_guard on billing.annual_operations;
drop function if exists billing.guard_annual_agreement_cleanup_v1();
drop index if exists billing.annual_one_agreement_cleanup_per_purchase;
reset role;
do $return_authority$
begin
  execute pg_catalog.format('revoke billing_store_owner from %I', current_user);
end;
$return_authority$;
commit;
