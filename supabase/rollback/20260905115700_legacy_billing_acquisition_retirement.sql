-- Controlled rollback restores the predecessor writer surface without deleting evidence.
begin;
set local lock_timeout = '5s';
set local statement_timeout = '120s';
select pg_catalog.pg_advisory_xact_lock(
  pg_catalog.hashtextextended('talli:billing:capability-cutover:v1', 0)
);
select pg_catalog.set_config('talli.legacy_retirement_borrowed_role',
  (not pg_catalog.pg_has_role(current_user, 'billing_store_owner', 'SET'))::text, true);
-- Supabase can retain an admin-only membership from another grantor after REVOKE.
-- Preserve a pre-existing grant by this principal, including its non-SET authority.
select pg_catalog.set_config('talli.legacy_retirement_existing_grant',
  exists (select 1 from pg_catalog.pg_auth_members membership
    join pg_catalog.pg_roles granted on granted.oid = membership.roleid
    join pg_catalog.pg_roles principal on principal.oid = membership.member
    join pg_catalog.pg_roles grantor on grantor.oid = membership.grantor
    where granted.rolname = 'billing_store_owner'
      and principal.rolname = current_user and grantor.rolname = current_user)::text, true);
do $borrow$
begin
  if pg_catalog.current_setting('talli.legacy_retirement_borrowed_role')::boolean then
    execute pg_catalog.format('grant billing_store_owner to %I with set true', current_user);
  end if;
end;
$borrow$;
set local role billing_store_owner;
lock table billing.billing_accounts, billing.billing_payment_events in share row exclusive mode;
drop trigger if exists legacy_account_retirement on billing.billing_accounts;
drop trigger if exists legacy_event_retirement on billing.billing_payment_events;
drop function if exists billing.guard_legacy_account_retirement_v1();
drop function if exists billing.guard_legacy_event_retirement_v1();
reset role;
do $return_authority$
begin
  if pg_catalog.current_setting('talli.legacy_retirement_borrowed_role')::boolean then
    if pg_catalog.current_setting('talli.legacy_retirement_existing_grant')::boolean then
      execute pg_catalog.format('grant billing_store_owner to %I with set false', current_user);
    else
      execute pg_catalog.format('revoke billing_store_owner from %I', current_user);
    end if;
  end if;
end;
$return_authority$;
commit;
