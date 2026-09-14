-- CONTRACT RELEASE ARTIFACT: #153 final generic Accounts table retirement.
begin;
set local lock_timeout='5s';
set local statement_timeout='120s';
set local search_path='';
select pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended('talli:annual-accounts-filing:migration:v1',0));
create temporary table accounts153_contract_roles(role_name name primary key,prior jsonb) on commit drop;
do $borrow$ declare r text; previous jsonb; begin
 foreach r in array array['ledger_store_owner','annual_accounts_filing_store_owner','shareholder_register_filing_store_owner','company_access_executor','company_tax_filing_store_owner','company_archive_projection_executor','documents_store_owner'] loop
  if not pg_catalog.pg_has_role(current_user,r,'SET') or not pg_catalog.pg_has_role(current_user,r,'USAGE') then
   select pg_catalog.jsonb_build_object('admin',m.admin_option,'inherit',m.inherit_option,'set',m.set_option) into previous
   from pg_catalog.pg_auth_members m where m.roleid=(select oid from pg_catalog.pg_roles where rolname=r)
    and m.member=(select oid from pg_catalog.pg_roles where rolname=current_user)
    and m.grantor=(select oid from pg_catalog.pg_roles where rolname=current_user);
   insert into accounts153_contract_roles values(r,previous);
   execute pg_catalog.format('grant %I to %I with set true, inherit true granted by %I',r,current_user,current_user);
  end if;
 end loop;
end; $borrow$;

create temporary table accounts153_contract_schema_privileges on commit drop as
 select pg_catalog.has_schema_privilege(current_user,'backend_system','CREATE') as backend_create;
grant select on accounts153_contract_schema_privileges to ledger_store_owner;
set local role ledger_store_owner;
do $schema_grant$ begin
 if not (select backend_create from pg_temp.accounts153_contract_schema_privileges) then
  execute pg_catalog.format('grant create on schema backend_system to %I',session_user);
 end if;
end; $schema_grant$;
reset role;
select phase from backend_system.annual_accounts_migration_state where singleton for update;
do $phase$ begin
 if (select phase from backend_system.annual_accounts_migration_state where singleton) is distinct from 'cutover' then
  raise exception 'annual_accounts_contract_requires_cutover'; end if;
 if exists(select 1 from backend_system.annual_accounts_quarantine)
  or (select count(distinct family) from backend_system.annual_accounts_reconciliations where phase='cutover' and source_count=target_count and source_digest=target_digest)<>6
 then raise exception 'annual_accounts_contract_reconciliation_required'; end if;
end; $phase$;
lock table public.filing_review_comments,public.filing_overrides,public.filing_submissions,public.filing_previews,public.authority_permissions,public.authority_test_runs in access exclusive mode;
do $fences$ declare f text; index_definition jsonb; begin
 foreach f in array array['filing_previews','authority_test_runs','authority_permissions','filing_submissions','filing_overrides','filing_review_comments'] loop
  if not exists(select 1 from pg_catalog.pg_constraint where conrelid=pg_catalog.to_regclass('public.'||f)
   and conname='accounts153_legacy_writer_retired' and contype='c' and convalidated and pg_catalog.pg_get_constraintdef(oid)='CHECK (false)')
  then raise exception 'annual_accounts_contract_barrier_missing'; end if;
  select pg_catalog.jsonb_build_object('indexes',coalesce(pg_catalog.jsonb_agg(pg_catalog.jsonb_build_object(
   'name',idx.relname,'definition',pg_catalog.pg_get_indexdef(i.indexrelid)) order by idx.relname),'[]'::jsonb)) into index_definition
  from pg_catalog.pg_index i join pg_catalog.pg_class idx on idx.oid=i.indexrelid
  where i.indrelid=pg_catalog.to_regclass('public.'||f)
   and not exists(select 1 from pg_catalog.pg_constraint x where x.conindid=i.indexrelid);
  insert into backend_system.annual_accounts_migration_inventory(resource,definition,definition_sha256)
  values('contract-indexes:public.'||f,index_definition,pg_catalog.encode(extensions.digest(index_definition::text,'sha256'),'hex'))
  on conflict(resource) do nothing;
  if not exists(select 1 from backend_system.annual_accounts_migration_inventory saved
   where saved.resource='contract-indexes:public.'||f and saved.definition=index_definition
    and saved.definition_sha256=pg_catalog.encode(extensions.digest(index_definition::text,'sha256'),'hex'))
  then raise exception 'annual_accounts_contract_index_inventory_changed'; end if;
 end loop;
end; $fences$;
do $empty$ begin
 if pg_catalog.to_regclass('public.filing_review_comments') is not null and exists(select 1 from public.filing_review_comments) then raise exception 'annual_accounts_contract_source_not_empty'; end if;
 if pg_catalog.to_regclass('public.filing_overrides') is not null and exists(select 1 from public.filing_overrides) then raise exception 'annual_accounts_contract_source_not_empty'; end if;
 if pg_catalog.to_regclass('public.filing_submissions') is not null and exists(select 1 from public.filing_submissions) then raise exception 'annual_accounts_contract_source_not_empty'; end if;
 if pg_catalog.to_regclass('public.filing_previews') is not null and exists(select 1 from public.filing_previews) then raise exception 'annual_accounts_contract_source_not_empty'; end if;
 if pg_catalog.to_regclass('public.authority_permissions') is not null and exists(select 1 from public.authority_permissions) then raise exception 'annual_accounts_contract_source_not_empty'; end if;
 if pg_catalog.to_regclass('public.authority_test_runs') is not null and exists(select 1 from public.authority_test_runs) then raise exception 'annual_accounts_contract_source_not_empty'; end if;
end; $empty$;
drop table if exists public.filing_review_comments;
drop table if exists public.filing_overrides;
drop table if exists public.filing_submissions;
drop table if exists public.filing_previews;
drop table if exists public.authority_permissions;
drop table if exists public.authority_test_runs;
update backend_system.annual_accounts_migration_state set phase='contracted',changed_at=pg_catalog.now() where singleton;
set local role ledger_store_owner;
do $schema_restore$ begin
 if not (select backend_create from pg_temp.accounts153_contract_schema_privileges) then
  execute pg_catalog.format('revoke create on schema backend_system from %I',session_user);
 end if;
end; $schema_restore$;
reset role;
do $restore$ declare r record; begin
 for r in select * from pg_temp.accounts153_contract_roles loop
  if r.prior is null then execute pg_catalog.format('revoke %I from %I granted by %I',r.role_name,current_user,current_user);
  else execute pg_catalog.format('grant %I to %I with admin %s,inherit %s,set %s granted by %I',r.role_name,current_user,r.prior->>'admin',r.prior->>'inherit',r.prior->>'set',current_user); end if;
 end loop;
end; $restore$;
commit;
