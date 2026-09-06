-- Withdraw intake while retaining immutable delivery evidence and deduplication.
-- The technical relation is independent of billing's business-table rollback.
begin;
set local lock_timeout = '5s';
set local statement_timeout = '120s';
select pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended('talli:annual-notification-inbox:v1', 0));
select pg_catalog.set_config('talli.notification_borrowed_owner',
  (not pg_catalog.pg_has_role(current_user, 'annual_notification_store_owner', 'SET'))::text, true);
select pg_catalog.set_config('talli.notification_existing_owner_grant',
  exists (select 1 from pg_catalog.pg_auth_members m
    join pg_catalog.pg_roles r on r.oid=m.roleid
    join pg_catalog.pg_roles p on p.oid=m.member
    join pg_catalog.pg_roles g on g.oid=m.grantor
    where r.rolname='annual_notification_store_owner'
      and p.rolname=current_user and g.rolname=current_user)::text, true);
do $borrow$
begin
  if pg_catalog.current_setting('talli.notification_borrowed_owner')::boolean then
    execute pg_catalog.format('grant annual_notification_store_owner to %I with set true', current_user);
  end if;
end;
$borrow$;
set local role annual_notification_store_owner;
revoke all on backend_system.annual_notification_receipts from annual_notification_executor;
revoke insert (provider, provider_account, receipt_digest, agreement_reference,
               charge_reference, event_type, occurred_at)
  on backend_system.annual_notification_receipts from annual_notification_executor;
drop policy if exists annual_notification_read on backend_system.annual_notification_receipts;
drop policy if exists annual_notification_insert on backend_system.annual_notification_receipts;
reset role;
do $return_authority$
begin
  if pg_catalog.current_setting('talli.notification_borrowed_owner')::boolean then
    if pg_catalog.current_setting('talli.notification_existing_owner_grant')::boolean then
      execute pg_catalog.format('grant annual_notification_store_owner to %I with set false', current_user);
    else
      execute pg_catalog.format('revoke annual_notification_store_owner from %I', current_user);
    end if;
  end if;
end;
$return_authority$;
commit;
