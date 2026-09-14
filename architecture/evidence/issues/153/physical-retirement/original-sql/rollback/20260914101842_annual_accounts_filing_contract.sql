-- #153 contract-only rollback: restore the empty fenced shell; Accounts remains the writer.
begin;
set local lock_timeout='5s';
set local statement_timeout='120s';
set local search_path='';
select pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended('talli:annual-accounts-filing:migration:v1',0));
create temporary table accounts153_contract_rollback_roles(role_name name primary key,prior jsonb) on commit drop;
do $borrow$ declare r text; previous jsonb; begin
 foreach r in array array['ledger_store_owner','annual_accounts_filing_store_owner','shareholder_register_filing_store_owner','company_access_executor','company_tax_filing_store_owner','company_archive_projection_executor','documents_store_owner'] loop
  if not pg_catalog.pg_has_role(current_user,r,'SET') or not pg_catalog.pg_has_role(current_user,r,'USAGE') then
   select pg_catalog.jsonb_build_object('admin',m.admin_option,'inherit',m.inherit_option,'set',m.set_option) into previous
   from pg_catalog.pg_auth_members m where m.roleid=(select oid from pg_catalog.pg_roles where rolname=r)
    and m.member=(select oid from pg_catalog.pg_roles where rolname=current_user)
    and m.grantor=(select oid from pg_catalog.pg_roles where rolname=current_user);
   insert into accounts153_contract_rollback_roles values(r,previous);
   execute pg_catalog.format('grant %I to %I with set true, inherit true granted by %I',r,current_user,current_user);
  end if;
 end loop;
end; $borrow$;

create temporary table accounts153_contract_rollback_schema_privileges on commit drop as
 select pg_catalog.has_schema_privilege(current_user,'backend_system','CREATE') as backend_create;
grant select on accounts153_contract_rollback_schema_privileges to ledger_store_owner;
set local role ledger_store_owner;
do $schema_grant$ begin
 if not (select backend_create from pg_temp.accounts153_contract_rollback_schema_privileges) then
  execute pg_catalog.format('grant create on schema backend_system to %I',session_user);
 end if;
end; $schema_grant$;
reset role;
select phase from backend_system.annual_accounts_migration_state where singleton for update;
do $phase$ begin
 if (select phase from backend_system.annual_accounts_migration_state where singleton) is distinct from 'contracted' then
  raise exception 'annual_accounts_contract_rollback_requires_contracted'; end if;
 if exists(select 1 from backend_system.annual_accounts_migration_inventory where definition_sha256<>pg_catalog.encode(extensions.digest(definition::text,'sha256'),'hex'))
 then raise exception 'annual_accounts_preserved_evidence_invalid'; end if;
 if pg_catalog.to_regclass('public.filing_review_comments') is not null then raise exception 'annual_accounts_contract_rollback_relation_conflict'; end if;
 if pg_catalog.to_regclass('public.filing_overrides') is not null then raise exception 'annual_accounts_contract_rollback_relation_conflict'; end if;
 if pg_catalog.to_regclass('public.filing_submissions') is not null then raise exception 'annual_accounts_contract_rollback_relation_conflict'; end if;
 if pg_catalog.to_regclass('public.filing_previews') is not null then raise exception 'annual_accounts_contract_rollback_relation_conflict'; end if;
 if pg_catalog.to_regclass('public.authority_permissions') is not null then raise exception 'annual_accounts_contract_rollback_relation_conflict'; end if;
 if pg_catalog.to_regclass('public.authority_test_runs') is not null then raise exception 'annual_accounts_contract_rollback_relation_conflict'; end if;
end; $phase$;
create table if not exists public.filing_review_comments ();
create table if not exists public.filing_overrides ();
create table if not exists public.filing_submissions ();
create table if not exists public.filing_previews ();
create table if not exists public.authority_permissions ();
create table if not exists public.authority_test_runs ();
do $columns$ declare f text; c jsonb; original jsonb; begin
 foreach f in array array['filing_previews','authority_test_runs','authority_permissions','filing_submissions','filing_overrides','filing_review_comments'] loop
  select definition into original from backend_system.annual_accounts_migration_inventory where resource='table:public.'||f;
  if original is null then raise exception 'annual_accounts_rollback_original_schema_missing'; end if;
  for c in select * from pg_catalog.jsonb_array_elements(original->'columns') loop
   execute pg_catalog.format('alter table public.%I add column %I %s%s%s',f,c->>'name',c->>'type',
    case when c->>'default' is not null then ' default '||(c->>'default') else '' end,
    case when (c->>'notNull')::boolean then ' not null' else '' end);
  end loop;
  for c in select * from pg_catalog.jsonb_array_elements(original->'constraints') where value->>'type'<>'f' loop
   execute pg_catalog.format('alter table public.%I add constraint %I %s',f,c->>'name',c->>'definition');
  end loop;
  execute pg_catalog.format('alter table public.%I add constraint accounts153_legacy_writer_retired check(false)',f);
 end loop;
end; $columns$;
do $references_and_indexes$ declare f text; c jsonb; original jsonb; begin
 foreach f in array array['filing_previews','authority_test_runs','authority_permissions','filing_submissions','filing_overrides','filing_review_comments'] loop
  select definition into original from backend_system.annual_accounts_migration_inventory where resource='table:public.'||f;
  for c in select * from pg_catalog.jsonb_array_elements(original->'constraints') where value->>'type'='f' loop
   execute pg_catalog.format('alter table public.%I add constraint %I %s',f,c->>'name',c->>'definition');
  end loop;
  for c in select * from pg_catalog.jsonb_array_elements((select definition->'indexes' from backend_system.annual_accounts_migration_inventory where resource='contract-indexes:public.'||f)) loop
   execute c->>'definition';
  end loop;
 end loop;
end; $references_and_indexes$;
do $policies_and_grants$ declare f text; item jsonb; original jsonb; principals text; acl_record record; begin
 foreach f in array array['filing_previews','authority_test_runs','authority_permissions','filing_submissions','filing_overrides','filing_review_comments'] loop
  select definition into original from backend_system.annual_accounts_migration_inventory where resource='table:public.'||f;
  execute pg_catalog.format('alter table public.%I %s row level security',f,case when (original->>'rls')::boolean then 'enable' else 'disable' end);
  execute pg_catalog.format('alter table public.%I %s force row level security',f,case when (original->>'forceRls')::boolean then '' else 'no' end);
  for item in select * from pg_catalog.jsonb_array_elements(original->'policies') loop
   select pg_catalog.string_agg(case when r::oid=0 then 'public' else pg_catalog.quote_ident(pg_catalog.pg_get_userbyid(r::oid)) end,',' order by r::oid) into principals
   from pg_catalog.jsonb_array_elements_text(item->'roles') r;
   execute pg_catalog.format('create policy %I on public.%I as %s for %s to %s%s%s',item->>'name',f,
    case when (item->>'permissive')::boolean then 'permissive' else 'restrictive' end,
    case item->>'command' when 'r' then 'select' when 'a' then 'insert' when 'w' then 'update' when 'd' then 'delete' else 'all' end,principals,
    case when item->>'using' is not null then ' using ('||(item->>'using')||')' else '' end,
    case when item->>'check' is not null then ' with check ('||(item->>'check')||')' else '' end);
  end loop;
  for item in select * from pg_catalog.jsonb_array_elements(original->'triggers') loop
   execute item->>'definition';
   execute pg_catalog.format('alter table public.%I %s trigger %I',f,
    case item->>'enabled' when 'O' then 'enable' when 'D' then 'disable' when 'R' then 'enable replica' when 'A' then 'enable always' end,item->>'name');
  end loop;
  -- Remove default ACL entries before restoring original privileges.
  for acl_record in select distinct a.grantee from pg_catalog.pg_class c cross join lateral pg_catalog.aclexplode(c.relacl) a where c.oid=pg_catalog.to_regclass('public.'||f) loop
   execute pg_catalog.format('revoke all on public.%I from %s',f,case when acl_record.grantee=0 then 'public' else pg_catalog.quote_ident(pg_catalog.pg_get_userbyid(acl_record.grantee)) end);
  end loop;
  for acl_record in select * from pg_catalog.aclexplode(array(select value::aclitem from pg_catalog.jsonb_array_elements_text(original->'acl'))) loop
   execute pg_catalog.format('grant %s on public.%I to %s%s',acl_record.privilege_type,f,
    case when acl_record.grantee=0 then 'public' else pg_catalog.quote_ident(pg_catalog.pg_get_userbyid(acl_record.grantee)) end,
    case when acl_record.is_grantable then ' with grant option' else '' end);
  end loop;
  execute pg_catalog.format('alter table public.%I owner to %I',f,original->>'owner');
 end loop;
end; $policies_and_grants$;
update backend_system.annual_accounts_migration_state set phase='cutover',changed_at=pg_catalog.now() where singleton;
set local role ledger_store_owner;
do $schema_restore$ begin
 if not (select backend_create from pg_temp.accounts153_contract_rollback_schema_privileges) then
  execute pg_catalog.format('revoke create on schema backend_system from %I',session_user);
 end if;
end; $schema_restore$;
reset role;
do $restore$ declare r record; begin
 for r in select * from pg_temp.accounts153_contract_rollback_roles loop
  if r.prior is null then execute pg_catalog.format('revoke %I from %I granted by %I',r.role_name,current_user,current_user);
  else execute pg_catalog.format('grant %I to %I with admin %s,inherit %s,set %s granted by %I',r.role_name,current_user,r.prior->>'admin',r.prior->>'inherit',r.prior->>'set',current_user); end if;
 end loop;
end; $restore$;
commit;
