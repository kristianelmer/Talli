-- Retire the observation worker without deleting authority or lease evidence.
begin;
set local lock_timeout = '5s';
set local statement_timeout = '120s';
select pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended('talli:billing:capability-cutover:v1', 0));
do $roles$
declare r text; saved jsonb := '{}'::jsonb;
begin
  foreach r in array array['annual_checkout_observer_executor','annual_checkout_observer_store_owner'] loop
    if not exists (select 1 from pg_catalog.pg_roles where rolname=r) then
      execute pg_catalog.format('create role %I nologin noinherit nosuperuser nocreatedb nocreaterole noreplication nobypassrls', r);
    end if;
    if exists(select 1 from pg_catalog.pg_roles where rolname=r and (rolcanlogin or rolinherit or rolsuper or rolbypassrls or rolcreaterole or rolcreatedb or rolreplication))
      or exists(select 1 from pg_catalog.pg_auth_members m join pg_catalog.pg_roles x on x.oid=m.member where x.rolname=r) then
      raise exception 'annual_observer_unsafe_role';
    end if;
  end loop;
  foreach r in array array['billing_store_owner','ledger_store_owner','annual_checkout_observer_store_owner'] loop
    saved := saved || pg_catalog.jsonb_build_object(r, pg_catalog.jsonb_build_object(
      'borrowed', not pg_catalog.pg_has_role(current_user,r,'SET'),
      'existing', exists(select 1 from pg_catalog.pg_auth_members m join pg_catalog.pg_roles a on a.oid=m.roleid
        join pg_catalog.pg_roles b on b.oid=m.member join pg_catalog.pg_roles g on g.oid=m.grantor
        where a.rolname=r and b.rolname=current_user and g.rolname=current_user)));
    if not pg_catalog.pg_has_role(current_user,r,'SET') then
      execute pg_catalog.format('grant %I to %I with set true', r, current_user);
    end if;
  end loop;
  perform pg_catalog.set_config('talli.annual_observer_borrowed_roles',saved::text,true);
end;
$roles$;
set local role billing_store_owner;
grant usage,create on schema billing_annual_retired to annual_checkout_observer_store_owner;
drop policy if exists annual_observer_read on billing.annual_purchases;
drop policy if exists annual_observer_update on billing.annual_purchases;
drop policy if exists annual_observer_read on billing.annual_operations;
drop policy if exists annual_observer_update on billing.annual_operations;
revoke select,references on billing.annual_purchases,billing.annual_operations from annual_checkout_observer_store_owner;
revoke update(status,agreement_reference,captured_minor,refunded_minor,captured_at,updated_at) on billing.annual_purchases from annual_checkout_observer_store_owner;
revoke update(status,observation,updated_at) on billing.annual_operations from annual_checkout_observer_store_owner;
reset role;
set local role annual_checkout_observer_store_owner;
-- Retain all immutable authority and technical evidence; disable every principal
-- and advance its epoch so rollback/recutover cannot resurrect in-flight leases.
alter table billing.annual_checkout_observation_principals no force row level security;
update billing.annual_checkout_observation_principals set enabled=false;
alter table billing.annual_checkout_observation_principals force row level security;
do $retire$
declare signature text;
begin
 for signature in select p.oid::regprocedure::text from pg_catalog.pg_proc p join pg_catalog.pg_namespace n on n.oid=p.pronamespace
   where n.nspname='billing' and p.proname like 'annual_observer_%' loop
  execute 'revoke all on function '||signature||' from annual_checkout_observer_executor';
  execute 'alter function '||signature||' set schema billing_annual_retired';
 end loop;
end;
$retire$;
alter table billing.annual_checkout_observation_principals set schema billing_annual_retired;
alter table billing.annual_checkout_observation_authorities set schema billing_annual_retired;
reset role;
set local role billing_store_owner;
revoke create on schema billing_annual_retired from annual_checkout_observer_store_owner;
reset role;
do $return_roles$
declare r text; saved jsonb:=pg_catalog.current_setting('talli.annual_observer_borrowed_roles')::jsonb;
begin
 foreach r in array array['billing_store_owner','ledger_store_owner','annual_checkout_observer_store_owner'] loop
  if (saved->r->>'borrowed')::boolean then
   if (saved->r->>'existing')::boolean then execute pg_catalog.format('grant %I to %I with set false',r,current_user);
   else execute pg_catalog.format('revoke %I from %I',r,current_user); end if;
  end if;
 end loop;
end;
$return_roles$;
commit;
