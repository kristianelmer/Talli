-- Remove new technical transport, preserving original rows and old web overlap.
begin;
set local lock_timeout='5s';
set local statement_timeout='120s';
do $membership$ begin
  perform pg_catalog.set_config('talli.launch_signoff_schema_membership_added',
    (not pg_catalog.pg_has_role(current_user,'ledger_store_owner','USAGE'))::text,true);
  if pg_catalog.current_setting('talli.launch_signoff_schema_membership_added')='true' then
    execute pg_catalog.format('grant ledger_store_owner to %I',current_user);
  end if;
  execute pg_catalog.format('grant launch_signoff_store_owner, launch_signoff_executor to %I',current_user);
end $membership$;
drop policy backend_launch_signoff_read on public.launch_signoffs;
drop policy backend_launch_signoff_insert on public.launch_signoffs;
drop policy backend_launch_signoff_update on public.launch_signoffs;
drop function backend_system.record_launch_signoff_v1(text,text,text,timestamptz,text,text);
drop function backend_system.list_launch_signoffs_v1();
drop function backend_system.assert_launch_signoff_operator_v1(boolean);
revoke all on public.launch_signoffs from launch_signoff_store_owner;
revoke usage on schema backend_system,public from launch_signoff_store_owner,launch_signoff_executor;
do $membership$ begin
  if exists(select 1 from pg_catalog.pg_roles where rolname='talli_ledger_backend') then
    revoke launch_signoff_executor from talli_ledger_backend;
  end if;
  execute pg_catalog.format('revoke launch_signoff_store_owner, launch_signoff_executor from %I',current_user);
  if pg_catalog.current_setting('talli.launch_signoff_schema_membership_added')='true' then
    execute pg_catalog.format('revoke ledger_store_owner from %I',current_user);
  end if;
end $membership$;
commit;
