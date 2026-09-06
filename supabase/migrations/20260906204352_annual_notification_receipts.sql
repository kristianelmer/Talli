-- Technical delivery receipts only. No runtime login is granted the executor.
begin;
set local lock_timeout = '5s';
set local statement_timeout = '120s';
select pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended('talli:annual-notification-inbox:v1', 0));

do $roles$
begin
  if not exists (select 1 from pg_catalog.pg_roles where rolname='annual_notification_store_owner') then
    create role annual_notification_store_owner nologin noinherit nobypassrls;
  end if;
  if not exists (select 1 from pg_catalog.pg_roles where rolname='annual_notification_executor') then
    create role annual_notification_executor nologin noinherit nobypassrls;
  end if;
  if exists (select 1 from pg_catalog.pg_roles
    where rolname in ('annual_notification_store_owner', 'annual_notification_executor')
      and (rolcanlogin or rolinherit or rolbypassrls or rolsuper or rolcreaterole or rolcreatedb or rolreplication))
  then raise exception 'annual_notification_role_is_not_restricted'; end if;
end;
$roles$;

-- Borrow only missing SET authority and preserve an existing self-granted
-- admin-only membership, as required by Supabase's grantor semantics.
do $borrow$
declare v_role text; v_state jsonb := '{}'::jsonb; v_existing boolean;
begin
  foreach v_role in array array['ledger_store_owner', 'annual_notification_store_owner'] loop
    if not pg_catalog.pg_has_role(current_user, v_role, 'SET') then
      select exists (select 1 from pg_catalog.pg_auth_members m
        join pg_catalog.pg_roles r on r.oid=m.roleid
        join pg_catalog.pg_roles p on p.oid=m.member
        join pg_catalog.pg_roles g on g.oid=m.grantor
        where r.rolname=v_role and p.rolname=current_user and g.rolname=current_user) into v_existing;
      v_state := v_state || pg_catalog.jsonb_build_object(v_role, v_existing);
      execute pg_catalog.format('grant %I to %I with set true', v_role, current_user);
    end if;
  end loop;
  perform pg_catalog.set_config('talli.notification_borrowed_roles', v_state::text, true);
end;
$borrow$;
set local role ledger_store_owner;
grant usage, create on schema backend_system to annual_notification_store_owner;
grant usage on schema backend_system to annual_notification_executor;
reset role;
set local role annual_notification_store_owner;

create table if not exists backend_system.annual_notification_receipts (
  id uuid primary key default pg_catalog.gen_random_uuid(),
  received_at timestamptz not null default pg_catalog.statement_timestamp() check (pg_catalog.isfinite(received_at)),
  provider text not null check (provider ~ '^[A-Za-z0-9._:-]{1,100}$'),
  provider_account text not null check (provider_account ~ '^[A-Za-z0-9._:-]{1,100}$'),
  receipt_digest text not null check (receipt_digest ~ '^[a-f0-9]{64}$'),
  agreement_reference text not null check (agreement_reference ~ '^[A-Za-z0-9_-]{1,100}$'),
  charge_reference text check (charge_reference ~ '^[A-Za-z0-9_-]{1,100}$'),
  event_type text not null check (event_type ~ '^[A-Za-z0-9._-]{1,100}$'),
  occurred_at timestamptz not null check (pg_catalog.isfinite(occurred_at)),
  unique(provider, provider_account, receipt_digest)
);
alter table backend_system.annual_notification_receipts enable row level security;
alter table backend_system.annual_notification_receipts force row level security;
revoke all on backend_system.annual_notification_receipts
  from public, anon, authenticated, service_role, billing_executor, billing_store_owner,
       annual_notification_executor, annual_notification_store_owner;
revoke insert (provider, provider_account, receipt_digest, agreement_reference,
               charge_reference, event_type, occurred_at)
  on backend_system.annual_notification_receipts from annual_notification_executor;
grant trigger on backend_system.annual_notification_receipts to annual_notification_store_owner;
grant select on backend_system.annual_notification_receipts to annual_notification_executor;
grant insert (provider, provider_account, receipt_digest, agreement_reference,
              charge_reference, event_type, occurred_at)
  on backend_system.annual_notification_receipts to annual_notification_executor;

create or replace function backend_system.guard_annual_notification_receipt_v1()
returns trigger language plpgsql set search_path='' as $function$
begin
  raise exception 'annual_notification_receipt_is_immutable';
end;
$function$;
revoke all on function backend_system.guard_annual_notification_receipt_v1() from public, anon, authenticated, service_role;
drop trigger if exists annual_notification_receipt_guard on backend_system.annual_notification_receipts;
create trigger annual_notification_receipt_guard before update or delete
  on backend_system.annual_notification_receipts for each row
  execute function backend_system.guard_annual_notification_receipt_v1();
drop policy if exists annual_notification_read on backend_system.annual_notification_receipts;
create policy annual_notification_read on backend_system.annual_notification_receipts
  for select to annual_notification_executor using (
    provider = (select pg_catalog.current_setting('talli.notification_provider', true))
    and provider_account = (select pg_catalog.current_setting('talli.notification_account', true))
  );
drop policy if exists annual_notification_insert on backend_system.annual_notification_receipts;
create policy annual_notification_insert on backend_system.annual_notification_receipts
  for insert to annual_notification_executor with check (
    provider = (select pg_catalog.current_setting('talli.notification_provider', true))
    and provider_account = (select pg_catalog.current_setting('talli.notification_account', true))
  );
-- Settings scope an already-authorized technical executor. They are not proof
-- of a customer identity or merchant authentication for any other role.
reset role;
do $return_authority$
declare v_role text; v_existing jsonb;
begin
  for v_role, v_existing in select key, value from pg_catalog.jsonb_each(
      pg_catalog.current_setting('talli.notification_borrowed_roles')::jsonb) loop
    if v_existing::boolean then
      execute pg_catalog.format('grant %I to %I with set false', v_role, current_user);
    else
      execute pg_catalog.format('revoke %I from %I', v_role, current_user);
    end if;
  end loop;
end;
$return_authority$;
commit;
