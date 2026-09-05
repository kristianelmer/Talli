-- Durable annual refund requests and single-assignment execution binding.
-- Existing owner/support-case authorization is preserved; no worker is activated.
begin;
set local lock_timeout = '5s';
set local statement_timeout = '120s';
select pg_catalog.pg_advisory_xact_lock(
  pg_catalog.hashtextextended('talli:billing:capability-cutover:v1', 0)
);
select pg_catalog.set_config('talli.annual_refund_requests_borrowed_role',
  (not pg_catalog.pg_has_role(current_user, 'billing_store_owner', 'SET'))::text, true);
-- Supabase can retain an admin-only membership from another grantor after REVOKE.
-- Preserve a pre-existing grant by this principal, including its non-SET authority.
select pg_catalog.set_config('talli.annual_refund_requests_existing_grant',
  exists (select 1 from pg_catalog.pg_auth_members membership
    join pg_catalog.pg_roles granted on granted.oid = membership.roleid
    join pg_catalog.pg_roles principal on principal.oid = membership.member
    join pg_catalog.pg_roles grantor on grantor.oid = membership.grantor
    where granted.rolname = 'billing_store_owner'
      and principal.rolname = current_user and grantor.rolname = current_user)::text, true);
do $borrow$
begin
  if pg_catalog.current_setting('talli.annual_refund_requests_borrowed_role')::boolean then
    execute pg_catalog.format('grant billing_store_owner to %I with set true', current_user);
  end if;
end;
$borrow$;
set local role billing_store_owner;
revoke all on billing.annual_refund_requests from public, anon, authenticated, service_role, billing_executor, billing_store_owner;
drop policy if exists annual_refund_request_read on billing.annual_refund_requests;
drop policy if exists annual_refund_request_insert on billing.annual_refund_requests;
drop policy if exists annual_refund_request_bind on billing.annual_refund_requests;
drop trigger if exists annual_refund_request_guard on billing.annual_refund_requests;
drop trigger if exists annual_refund_request_apply on billing.annual_refund_requests;
alter table billing.annual_refund_requests set schema billing_annual_retired;
drop function billing.guard_annual_refund_request_v1();
drop function billing.apply_annual_refund_request_v1();
reset role;
do $return_authority$
begin
  if pg_catalog.current_setting('talli.annual_refund_requests_borrowed_role')::boolean then
    if pg_catalog.current_setting('talli.annual_refund_requests_existing_grant')::boolean then
      execute pg_catalog.format('grant billing_store_owner to %I with set false', current_user);
    else
      execute pg_catalog.format('revoke billing_store_owner from %I', current_user);
    end if;
  end if;
end;
$return_authority$;
commit;
