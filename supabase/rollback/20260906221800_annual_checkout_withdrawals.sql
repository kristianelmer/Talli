-- Preserve permanent withdrawals and deny new checkout claims until recutover.
-- The operation trigger keeps this function's OID through predecessor rollback.
begin;
set local lock_timeout = '5s';
set local statement_timeout = '120s';
select pg_catalog.pg_advisory_xact_lock(
  pg_catalog.hashtextextended('talli:billing:capability-cutover:v1', 0)
);
select pg_catalog.set_config('talli.annual_checkout_withdrawals_borrowed_role',
  (not pg_catalog.pg_has_role(current_user, 'billing_store_owner', 'SET'))::text, true);
-- Supabase can retain an admin-only membership from another grantor after REVOKE.
-- Preserve a pre-existing grant by this principal, including its non-SET authority.
select pg_catalog.set_config('talli.annual_checkout_withdrawals_existing_grant',
  exists (select 1 from pg_catalog.pg_auth_members membership
    join pg_catalog.pg_roles granted on granted.oid = membership.roleid
    join pg_catalog.pg_roles principal on principal.oid = membership.member
    join pg_catalog.pg_roles grantor on grantor.oid = membership.grantor
    where granted.rolname = 'billing_store_owner'
      and principal.rolname = current_user and grantor.rolname = current_user)::text, true);
do $borrow$
begin
  if pg_catalog.current_setting('talli.annual_checkout_withdrawals_borrowed_role')::boolean then
    execute pg_catalog.format('grant billing_store_owner to %I with set true', current_user);
  end if;
end;
$borrow$;
set local role billing_store_owner;
create or replace function billing.guard_annual_checkout_request_v1()
returns trigger language plpgsql security invoker set search_path = '' as $function$
begin
  if tg_op = 'INSERT' and tg_table_name = 'annual_operations' then
    if new.operation <> 'checkout' then return new; end if;
  end if;
  raise exception 'annual_checkout_withdrawal_unavailable';
end;
$function$;
revoke all on billing.annual_checkout_withdrawals from public, anon, authenticated, service_role, billing_executor, billing_store_owner;
revoke update (id) on billing.annual_checkout_withdrawals from billing_store_owner;
revoke insert (company_id,income_year,requested_by,idempotency_key,request_fingerprint,
  offer_version,terms_digest,purchase_accepted,recurring_consent,consent_version)
  on billing.annual_checkout_withdrawals from billing_store_owner;
drop policy if exists annual_checkout_withdrawal_read on billing.annual_checkout_withdrawals;
drop policy if exists annual_checkout_withdrawal_insert on billing.annual_checkout_withdrawals;
alter table billing.annual_checkout_withdrawals set schema billing_annual_retired;
alter function billing.guard_annual_checkout_request_v1() set schema billing_annual_retired;
reset role;
do $return_authority$
begin
  if pg_catalog.current_setting('talli.annual_checkout_withdrawals_borrowed_role')::boolean then
    if pg_catalog.current_setting('talli.annual_checkout_withdrawals_existing_grant')::boolean then
      execute pg_catalog.format('grant billing_store_owner to %I with set false', current_user);
    else
      execute pg_catalog.format('revoke billing_store_owner from %I', current_user);
    end if;
  end if;
end;
$return_authority$;
commit;
