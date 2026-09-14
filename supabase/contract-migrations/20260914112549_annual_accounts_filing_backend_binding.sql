-- #153 explicit restricted backend binding after the owned store is canonical.
begin;
set local lock_timeout='5s';
set local statement_timeout='30s';
set local search_path='';
do $guard$
begin
 if not exists(select 1 from backend_system.annual_accounts_migration_state where singleton and phase in ('cutover','contracted')) then
  raise exception 'annual_accounts_unavailable';
 end if;
 if not exists(select 1 from pg_catalog.pg_roles where rolname='talli_ledger_backend'
  and not rolsuper and not rolinherit and not rolcreaterole and not rolcreatedb and not rolreplication and not rolbypassrls) then
  raise exception 'annual_accounts_backend_role_changed';
 end if;
end;
$guard$;
grant annual_accounts_filing_workflow_executor to talli_ledger_backend with inherit false,set true;
commit;
