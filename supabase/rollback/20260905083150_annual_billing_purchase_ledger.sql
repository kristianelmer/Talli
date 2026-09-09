-- Withdraw the annual runtime surface without erasing accepted or paid evidence.
begin;
do $borrow$
begin
  execute pg_catalog.format('grant billing_store_owner to %I', current_user);
end;
$borrow$;
set local role billing_store_owner;
do $retire$
declare v_name text; v_policy text;
begin
  foreach v_name in array array['annual_operations','annual_refund_cases','annual_purchases'] loop
    execute pg_catalog.format('revoke all on billing.%I from public, anon, authenticated, service_role, billing_executor, billing_store_owner', v_name);
    for v_policy in select policy.polname from pg_catalog.pg_policy policy
      where policy.polrelid = pg_catalog.to_regclass('billing.' || v_name)
    loop
      execute pg_catalog.format('drop policy %I on billing.%I', v_policy, v_name);
    end loop;
    execute pg_catalog.format('drop trigger if exists annual_evidence_immutable on billing.%I', v_name);
    execute pg_catalog.format('drop trigger if exists annual_operation_reservation on billing.%I', v_name);
    execute pg_catalog.format('alter table billing.%I set schema billing_annual_retired', v_name);
  end loop;
end;
$retire$;
drop function billing.guard_annual_evidence_v1(), billing.reserve_annual_operation_v1();
reset role;
do $return_authority$
begin
  execute pg_catalog.format('revoke billing_store_owner from %I', current_user);
end;
$return_authority$;
commit;
