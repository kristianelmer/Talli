-- #153 CUTOVER: reconcile the final generic filing source and activate one owner.
-- Apply only after expansion and all Accounts contracts. No provider operation.
begin;
set local lock_timeout='5s';
set local statement_timeout='120s';
set local timezone='UTC';
set local search_path='';
select pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended('talli:annual-accounts-filing:migration:v1',0));
create temporary table accounts153_cutover_roles(role_name name primary key,prior jsonb) on commit drop;
do $borrow$ declare r text; previous jsonb; begin
 foreach r in array array['ledger_store_owner','annual_accounts_filing_store_owner','shareholder_register_filing_store_owner','company_access_executor','company_tax_filing_store_owner','company_archive_projection_executor','documents_store_owner'] loop
  if not pg_catalog.pg_has_role(current_user,r,'SET') or not pg_catalog.pg_has_role(current_user,r,'USAGE') then
   select pg_catalog.jsonb_build_object('admin',m.admin_option,'inherit',m.inherit_option,'set',m.set_option) into previous
   from pg_catalog.pg_auth_members m where m.roleid=(select oid from pg_catalog.pg_roles where rolname=r)
    and m.member=(select oid from pg_catalog.pg_roles where rolname=current_user)
    and m.grantor=(select oid from pg_catalog.pg_roles where rolname=current_user);
   insert into accounts153_cutover_roles values(r,previous);
   execute pg_catalog.format('grant %I to %I with set true, inherit true granted by %I',r,current_user,current_user);
  end if;
 end loop;
end; $borrow$;

create temporary table accounts153_cutover_schema_privileges on commit drop as
 select pg_catalog.has_schema_privilege(current_user,'backend_system','CREATE') as backend_create;
grant select on accounts153_cutover_schema_privileges to ledger_store_owner;
set local role ledger_store_owner;
do $schema_grant$ begin
 if not (select backend_create from pg_temp.accounts153_cutover_schema_privileges) then
  execute pg_catalog.format('grant create on schema backend_system to %I',session_user);
 end if;
end; $schema_grant$;
reset role;
select phase from backend_system.annual_accounts_migration_state where singleton for update;
do $phase$ begin
 if coalesce((select phase from backend_system.annual_accounts_migration_state where singleton) not in ('expanded','rolled_back'),true) then
  raise exception 'annual_accounts_cutover_requires_expanded'; end if;
 if (select phase from backend_system.company_tax_return_migration_state where singleton) is distinct from 'contracted' then
  raise exception 'annual_accounts_predecessor_required'; end if;
end; $phase$;
lock table public.filing_previews,public.authority_test_runs,public.authority_permissions,
 public.filing_submissions,public.filing_overrides,public.filing_review_comments,
 annual_accounts_filing.filing_previews,annual_accounts_filing.authority_test_runs,annual_accounts_filing.authority_permissions,
 annual_accounts_filing.filing_submissions,annual_accounts_filing.filing_overrides,annual_accounts_filing.filing_review_comments in access exclusive mode;
create temporary table accounts153_cutover_setup_ids(id uuid primary key) on commit drop;
insert into accounts153_cutover_setup_ids
select setup_id from public.filing_previews where setup_id is not null
union select setup_id from public.filing_submissions where setup_id is not null;
create temporary table accounts153_cutover_setup_scopes(id uuid primary key,company_id uuid,income_year integer) on commit drop;
grant select on accounts153_cutover_setup_ids to shareholder_register_filing_store_owner;
grant insert on accounts153_cutover_setup_scopes to shareholder_register_filing_store_owner;
set local role shareholder_register_filing_store_owner;
lock table shareholder_register_filing.opening_balance_setups in share row exclusive mode;
create policy accounts153_cutover_setup_scope on shareholder_register_filing.opening_balance_setups
 for select to shareholder_register_filing_store_owner using(true);
insert into pg_temp.accounts153_cutover_setup_scopes
select s.id,s.company_id,s.income_year from shareholder_register_filing.opening_balance_setups s
join pg_temp.accounts153_cutover_setup_ids wanted on wanted.id=s.id;
drop policy accounts153_cutover_setup_scope on shareholder_register_filing.opening_balance_setups;
reset role;

create or replace function pg_temp.accounts153_cutover_classify(family text,row_data jsonb) returns text
language plpgsql set search_path='' as $function$
declare linked jsonb;
begin
 if family in ('filing_previews','filing_submissions','filing_overrides') then
  if row_data->>'filing' is distinct from 'årsregnskap' then return 'quarantine'; end if;
 elsif family in ('authority_permissions','authority_test_runs') then
  if row_data->>'obligation' is distinct from 'aarsregnskap' then return 'quarantine'; end if;
 elsif family<>'filing_review_comments' then raise exception 'annual_accounts_unknown_family';
 end if;
 if family='filing_overrides' and row_data->>'field_target' like 'skattemelding.%' then return 'quarantine'; end if;
 if family in ('filing_previews','filing_submissions') and row_data->>'setup_id' is not null then
  select pg_catalog.to_jsonb(s) into linked from pg_temp.accounts153_cutover_setup_scopes s where s.id=(row_data->>'setup_id')::uuid;
  if linked is null or linked->>'company_id' is distinct from row_data->>'company_id'
   or linked->>'income_year' is distinct from row_data->>'income_year'
  then return 'quarantine'; end if;
 end if;
 if family='filing_review_comments' and row_data->>'preview_id' is null then return 'quarantine'; end if;
 if family in ('filing_submissions','filing_overrides','filing_review_comments') and row_data->>'preview_id' is not null then
  select pg_catalog.to_jsonb(p) into linked from public.filing_previews p where p.id=(row_data->>'preview_id')::uuid;
  if linked is null or linked->>'filing' is distinct from 'årsregnskap'
   or linked->>'company_id' is distinct from row_data->>'company_id'
   or (row_data ? 'income_year' and linked->>'income_year' is distinct from row_data->>'income_year')
  then return 'quarantine'; end if;
  if pg_temp.accounts153_cutover_classify('filing_previews',linked)<>'accounts' then return 'quarantine'; end if;
 end if;
 if family='filing_submissions' and row_data->>'authority_test_run_id' is not null then
  select pg_catalog.to_jsonb(r) into linked from public.authority_test_runs r where r.id=(row_data->>'authority_test_run_id')::uuid;
  if linked is null or linked->>'obligation' is distinct from 'aarsregnskap'
   or linked->>'company_id' is distinct from row_data->>'company_id'
  then return 'quarantine'; end if;
 end if;
 return 'accounts';
end; $function$;


-- This transaction's temporary policy permits only physical migration. It is
-- never visible to another transaction and is removed before activation.
set local role annual_accounts_filing_store_owner;
do $migration_access$ declare f text; begin
 foreach f in array array['filing_previews','authority_test_runs','authority_permissions','filing_submissions','filing_overrides','filing_review_comments'] loop
  execute pg_catalog.format('create policy accounts153_physical_migration on annual_accounts_filing.%I for all to annual_accounts_filing_store_owner using(true) with check(true)',f);
 end loop;
end; $migration_access$;
reset role;

do $source_schema$ declare f text; definition jsonb; begin
 foreach f in array array['filing_previews','authority_test_runs','authority_permissions','filing_submissions','filing_overrides','filing_review_comments'] loop
  select pg_catalog.jsonb_build_object('owner',pg_catalog.pg_get_userbyid(c.relowner),'acl',c.relacl,
   'rls',c.relrowsecurity,'forceRls',c.relforcerowsecurity,
   'columns',(select pg_catalog.jsonb_agg(pg_catalog.jsonb_build_object('name',a.attname,'type',pg_catalog.format_type(a.atttypid,a.atttypmod),'notNull',a.attnotnull,'default',pg_catalog.pg_get_expr(d.adbin,d.adrelid)) order by a.attnum)
    from pg_catalog.pg_attribute a left join pg_catalog.pg_attrdef d on d.adrelid=a.attrelid and d.adnum=a.attnum where a.attrelid=c.oid and a.attnum>0 and not a.attisdropped),
   'constraints',(select coalesce(pg_catalog.jsonb_agg(pg_catalog.jsonb_build_object('name',x.conname,'type',x.contype,'definition',pg_catalog.pg_get_constraintdef(x.oid)) order by x.conname),'[]'::jsonb) from pg_catalog.pg_constraint x where x.conrelid=c.oid),
   'policies',(select coalesce(pg_catalog.jsonb_agg(pg_catalog.jsonb_build_object('name',p.polname,'roles',p.polroles,'command',p.polcmd,'permissive',p.polpermissive,'using',pg_catalog.pg_get_expr(p.polqual,p.polrelid),'check',pg_catalog.pg_get_expr(p.polwithcheck,p.polrelid)) order by p.polname),'[]'::jsonb) from pg_catalog.pg_policy p where p.polrelid=c.oid),
   'triggers',(select coalesce(pg_catalog.jsonb_agg(pg_catalog.jsonb_build_object('name',t.tgname,'definition',pg_catalog.pg_get_triggerdef(t.oid),'enabled',t.tgenabled) order by t.tgname),'[]'::jsonb) from pg_catalog.pg_trigger t where t.tgrelid=c.oid and not t.tgisinternal)) into definition
  from pg_catalog.pg_class c where c.oid=pg_catalog.to_regclass('public.'||f) and c.relkind='r';
  if definition is distinct from (select i.definition from backend_system.annual_accounts_migration_inventory i where resource='table:public.'||f)
  then raise exception 'annual_accounts_source_schema_changed'; end if;
 end loop;
end; $source_schema$;

create temporary table accounts153_current_rows(family text,source_id uuid,payload jsonb,classification text,primary key(family,source_id)) on commit drop;
create temporary table accounts153_cutover_generations on commit drop as select * from public.company_archive_source_generations;
-- The captured original source remains immutable. Unknown provenance or target
-- rows without an exact preserved source identity stop the whole transaction.
do $capture$ declare f text; unproven boolean; item record; actual jsonb; begin
 if exists(select 1 from backend_system.annual_accounts_migration_inventory where definition_sha256<>pg_catalog.encode(extensions.digest(definition::text,'sha256'),'hex'))
  or exists(select 1 from backend_system.annual_accounts_source_rows where source_sha256<>pg_catalog.encode(extensions.digest(payload::text,'sha256'),'hex'))
  or exists(select 1 from backend_system.annual_accounts_quarantine)
 then raise exception 'annual_accounts_preserved_evidence_invalid'; end if;
 for item in select * from backend_system.annual_accounts_migration_inventory where resource like 'function:%' loop
  select pg_catalog.jsonb_build_object('identity',n.nspname||'.'||p.proname||'('||pg_catalog.pg_get_function_identity_arguments(p.oid)||')',
   'definition',pg_catalog.pg_get_functiondef(p.oid),'owner',pg_catalog.pg_get_userbyid(p.proowner),'acl',p.proacl) into actual
   from pg_catalog.pg_proc p join pg_catalog.pg_namespace n on n.oid=p.pronamespace
   where n.nspname||'.'||p.proname||'('||pg_catalog.pg_get_function_identity_arguments(p.oid)||')'=item.definition->>'identity';
  if actual is distinct from item.definition then raise exception 'annual_accounts_dependent_function_changed'; end if;
 end loop;
 foreach f in array array['filing_previews','authority_test_runs','authority_permissions','filing_submissions','filing_overrides','filing_review_comments'] loop
  execute pg_catalog.format('insert into pg_temp.accounts153_current_rows select $1,id,pg_catalog.to_jsonb(r),pg_temp.accounts153_cutover_classify($1,pg_catalog.to_jsonb(r)) from public.%I r',f) using f;
  execute pg_catalog.format('select exists(select 1 from annual_accounts_filing.%I t where not exists(select 1 from backend_system.annual_accounts_source_rows s where s.family=$1 and s.source_id=t.id and s.payload=pg_catalog.to_jsonb(t) and s.classification=''accounts''))',f) into unproven using f;
  if unproven then raise exception 'annual_accounts_unproven_target_rows'; end if;
 end loop;
 if exists(select 1 from pg_temp.accounts153_current_rows where classification<>'accounts') then raise exception 'annual_accounts_cutover_quarantine'; end if;
 insert into backend_system.annual_accounts_source_rows(family,source_id,payload,source_sha256,classification)
 select family,source_id,payload,pg_catalog.encode(extensions.digest(payload::text,'sha256'),'hex'),classification from pg_temp.accounts153_current_rows on conflict do nothing;
end; $capture$;
create temporary table accounts153_trigger_modes on commit drop as
select c.relname as family,t.tgname,t.tgenabled,pg_catalog.pg_get_triggerdef(t.oid) as definition from pg_catalog.pg_trigger t
join pg_catalog.pg_class c on c.oid=t.tgrelid join pg_catalog.pg_namespace n on n.oid=c.relnamespace
where n.nspname='public' and c.relname in ('filing_previews','authority_test_runs','authority_permissions','filing_submissions','filing_overrides','filing_review_comments') and not t.tgisinternal;
do $disable$ declare t record; begin
 if (select count(*) from pg_temp.accounts153_trigger_modes)<>(select count(*) from backend_system.annual_accounts_migration_inventory i,
  lateral pg_catalog.jsonb_array_elements(i.definition->'triggers') original where i.resource like 'table:public.%')
 then raise exception 'annual_accounts_source_trigger_changed'; end if;
 for t in select * from pg_temp.accounts153_trigger_modes loop
  if not exists(select 1 from backend_system.annual_accounts_migration_inventory i,
   lateral pg_catalog.jsonb_array_elements(i.definition->'triggers') original
   where i.resource='table:public.'||t.family and original->>'name'=t.tgname
    and original->>'enabled'=t.tgenabled::text and original->>'definition'=t.definition)
  then raise exception 'annual_accounts_source_trigger_changed'; end if;
  execute pg_catalog.format('alter table public.%I disable trigger %I',t.family,t.tgname);
 end loop;
end; $disable$;
-- No target business trigger is permitted before first activation. Rollback
-- removes the exact owned archive triggers before a later re-cutover.
do $target_triggers$ begin
 if exists(select 1 from pg_catalog.pg_trigger t join pg_catalog.pg_class c on c.oid=t.tgrelid
  join pg_catalog.pg_namespace n on n.oid=c.relnamespace where n.nspname='annual_accounts_filing'
  and c.relname in ('filing_previews','authority_test_runs','authority_permissions','filing_submissions','filing_overrides','filing_review_comments') and not t.tgisinternal)
 then raise exception 'annual_accounts_target_trigger_changed'; end if;
end; $target_triggers$;

do $unfence$ declare f text; begin
 if (select phase from backend_system.annual_accounts_migration_state where singleton)='rolled_back' then
  foreach f in array array['filing_previews','authority_test_runs','authority_permissions','filing_submissions','filing_overrides','filing_review_comments'] loop
   execute pg_catalog.format('alter table annual_accounts_filing.%I drop constraint accounts153_owned_writer_inactive',f);
  end loop;
 end if;
end; $unfence$;
do $copy$ declare f text; source_count bigint; target_count bigint; source_digest text; target_digest text; begin
 foreach f in array array['filing_review_comments','filing_overrides','filing_submissions','filing_previews','authority_permissions','authority_test_runs'] loop
  execute pg_catalog.format('delete from annual_accounts_filing.%I',f);
 end loop;
 foreach f in array array['filing_previews','authority_test_runs','authority_permissions','filing_submissions','filing_overrides','filing_review_comments'] loop
  execute pg_catalog.format('insert into annual_accounts_filing.%I select (pg_catalog.jsonb_populate_record(null::annual_accounts_filing.%I,payload)).* from pg_temp.accounts153_current_rows where family=$1',f,f) using f;
  select count(*),pg_catalog.encode(extensions.digest(coalesce(pg_catalog.string_agg(payload::text,E'\n' order by source_id),''),'sha256'),'hex') into source_count,source_digest from pg_temp.accounts153_current_rows where family=f;
  execute pg_catalog.format('select count(*),pg_catalog.encode(extensions.digest(coalesce(pg_catalog.string_agg(pg_catalog.to_jsonb(t)::text,E''\n'' order by id),''''),''sha256''),''hex'') from annual_accounts_filing.%I t',f) into target_count,target_digest;
  insert into backend_system.annual_accounts_reconciliations(phase,family,source_count,target_count,source_digest,target_digest) values('cutover',f,source_count,target_count,source_digest,target_digest);
 end loop;
 foreach f in array array['filing_review_comments','filing_overrides','filing_submissions','filing_previews','authority_permissions','authority_test_runs'] loop
  execute pg_catalog.format('delete from public.%I',f);
  execute pg_catalog.format('alter table public.%I add constraint accounts153_legacy_writer_retired check(false)',f);
 end loop;
end; $copy$;
set local role annual_accounts_filing_store_owner;
create or replace function annual_accounts_filing.filing_phase_v1() returns text
language plpgsql volatile security definer set search_path='' as $function$
declare result text; begin
 select phase into result from backend_system.annual_accounts_migration_state where singleton for share;
 return result;
end; $function$;
alter function annual_accounts_filing.read_workspace_v1(uuid,integer,text) volatile;
alter function annual_accounts_filing.assert_filing_available_v1(text) volatile;
alter function annual_accounts_filing.assert_preparation_access_v1(uuid,text,boolean) volatile;
alter function annual_accounts_filing.read_preview_v1(uuid,text) volatile;
do $migration_access_end$ declare f text; begin
 foreach f in array array['filing_previews','authority_test_runs','authority_permissions','filing_submissions','filing_overrides','filing_review_comments'] loop
  execute pg_catalog.format('drop policy accounts153_physical_migration on annual_accounts_filing.%I',f);
 end loop;
end; $migration_access_end$;
reset role;

do $rebind_0$ declare definition text; anchor text:=$old$not exists(select 1 from public.filing_overrides o
     where o.company_id=p_company_id and o.income_year=p_income_year and o.risk_level='block'
       and not shareholder_register_filing.is_rf_label_v1(o.filing))$old$; begin
 select pg_catalog.pg_get_functiondef(p.oid) into definition from pg_catalog.pg_proc p join pg_catalog.pg_namespace n on n.oid=p.pronamespace
 where n.nspname||'.'||p.proname||'('||pg_catalog.pg_get_function_identity_arguments(p.oid)||')'='backend_system.rf1086_stored_release_inputs_v1(p_company_id uuid, p_income_year integer, p_obligation text)';
 if definition is null or pg_catalog.strpos(definition,anchor)=0 then raise exception 'annual_accounts_dependency_changed'; end if;
 execute pg_catalog.replace(definition,anchor,$new$not annual_accounts_filing.has_blocking_override_v1(p_company_id,p_income_year)$new$);
end; $rebind_0$;

do $rebind_1$ declare definition text; anchor text:=$old$'legacyFencesValid',coalesce(fences_valid,false)$old$; begin
 select pg_catalog.pg_get_functiondef(p.oid) into definition from pg_catalog.pg_proc p join pg_catalog.pg_namespace n on n.oid=p.pronamespace
 where n.nspname||'.'||p.proname||'('||pg_catalog.pg_get_function_identity_arguments(p.oid)||')'='company_tax_filing.read_source_snapshot_v1(p_company uuid, p_year integer, p_subject text)';
 if definition is null or pg_catalog.strpos(definition,anchor)=0 then raise exception 'annual_accounts_dependency_changed'; end if;
 execute pg_catalog.replace(definition,anchor,$new$'legacyFencesValid',(coalesce(fences_valid,false) or coalesce(annual_accounts_filing.generic_store_retired_v1(),false))$new$);
end; $rebind_1$;

do $rebind_2$ declare definition text; anchor text:=$old$exists (
      select 1 from public.filing_submissions item
      where coalesce(item.feedback_document_ids,'[]'::jsonb)
              @> pg_catalog.jsonb_build_array(p_document_id::text)
         or item.receipt_id=p_document_id::text
    )$old$; begin
 select pg_catalog.pg_get_functiondef(p.oid) into definition from pg_catalog.pg_proc p join pg_catalog.pg_namespace n on n.oid=p.pronamespace
 where n.nspname||'.'||p.proname||'('||pg_catalog.pg_get_function_identity_arguments(p.oid)||')'='documents.has_evidence_references_v1(p_document_id uuid)';
 if definition is null or pg_catalog.strpos(definition,anchor)=0 then raise exception 'annual_accounts_dependency_changed'; end if;
 execute pg_catalog.replace(definition,anchor,$new$annual_accounts_filing.has_document_reference_v1(p_document_id)$new$);
end; $rebind_2$;

do $rebind_3$ declare definition text; anchor text:=$old$coalesce((
        select pg_catalog.jsonb_agg(pg_catalog.jsonb_build_object(
          'id', f.id, 'company_id', f.company_id, 'income_year', f.income_year,
          'filing', f.filing, 'status', f.status, 'updated_at', f.updated_at
        ) order by f.updated_at desc)
        from public.filing_submissions f where f.company_id = v_grant.company_id
      ), '[]'::jsonb)$old$; begin
 select pg_catalog.pg_get_functiondef(p.oid) into definition from pg_catalog.pg_proc p join pg_catalog.pg_namespace n on n.oid=p.pronamespace
 where n.nspname||'.'||p.proname||'('||pg_catalog.pg_get_function_identity_arguments(p.oid)||')'='public.company_access_read_support_case(p_case_id uuid)';
 if definition is null or pg_catalog.strpos(definition,anchor)=0 then raise exception 'annual_accounts_dependency_changed'; end if;
 execute pg_catalog.replace(definition,anchor,$new$(annual_accounts_filing.read_support_filing_history_v1(v_grant.company_id,p_case_id)->'filing_submissions')$new$);
end; $rebind_3$;

do $rebind_4$ declare definition text; anchor text:=$old$coalesce((
        select pg_catalog.jsonb_agg(pg_catalog.jsonb_build_object(
          'id', a.id, 'company_id', a.company_id, 'obligation', a.obligation,
          'production_enabled', a.production_enabled, 'updated_at', a.updated_at
        )) from public.authority_permissions a
        where a.company_id = v_grant.company_id
      ), '[]'::jsonb)$old$; begin
 select pg_catalog.pg_get_functiondef(p.oid) into definition from pg_catalog.pg_proc p join pg_catalog.pg_namespace n on n.oid=p.pronamespace
 where n.nspname||'.'||p.proname||'('||pg_catalog.pg_get_function_identity_arguments(p.oid)||')'='public.company_access_read_support_case(p_case_id uuid)';
 if definition is null or pg_catalog.strpos(definition,anchor)=0 then raise exception 'annual_accounts_dependency_changed'; end if;
 execute pg_catalog.replace(definition,anchor,$new$(annual_accounts_filing.read_support_filing_history_v1(v_grant.company_id,p_case_id)->'authority_permissions')$new$);
end; $rebind_4$;

do $rebind_5$ declare definition text; anchor text:=$old$coalesce((
        select pg_catalog.jsonb_agg(pg_catalog.jsonb_build_object(
          'id', a.id, 'company_id', a.company_id, 'obligation', a.obligation,
          'environment', a.environment, 'status', a.status,
          'test_reference', a.test_reference, 'recorded_at', a.recorded_at
        ) order by a.recorded_at desc)
        from public.authority_test_runs a where a.company_id = v_grant.company_id
      ), '[]'::jsonb)$old$; begin
 select pg_catalog.pg_get_functiondef(p.oid) into definition from pg_catalog.pg_proc p join pg_catalog.pg_namespace n on n.oid=p.pronamespace
 where n.nspname||'.'||p.proname||'('||pg_catalog.pg_get_function_identity_arguments(p.oid)||')'='public.company_access_read_support_case(p_case_id uuid)';
 if definition is null or pg_catalog.strpos(definition,anchor)=0 then raise exception 'annual_accounts_dependency_changed'; end if;
 execute pg_catalog.replace(definition,anchor,$new$(annual_accounts_filing.read_support_filing_history_v1(v_grant.company_id,p_case_id)->'authority_test_runs')$new$);
end; $rebind_5$;

do $bind_dependents$ declare item jsonb; begin
 for item in select pg_catalog.jsonb_build_object('identity',n.nspname||'.'||p.proname||'('||pg_catalog.pg_get_function_identity_arguments(p.oid)||')',
  'definition',pg_catalog.pg_get_functiondef(p.oid)) from pg_catalog.pg_proc p join pg_catalog.pg_namespace n on n.oid=p.pronamespace
  where (n.nspname,p.proname) in (('backend_system','rf1086_stored_release_inputs_v1'),('company_tax_filing','read_source_snapshot_v1'),
   ('documents','has_evidence_references_v1'),('public','company_access_read_support_case')) loop
  if exists(select 1 from backend_system.annual_accounts_migration_inventory where resource='cutover-function:'||(item->>'identity') and definition<>item)
  then raise exception 'annual_accounts_cutover_dependency_binding_changed'; end if;
  insert into backend_system.annual_accounts_migration_inventory(resource,definition,definition_sha256)
  values('cutover-function:'||(item->>'identity'),item,pg_catalog.encode(extensions.digest(item::text,'sha256'),'hex')) on conflict do nothing;
 end loop;
end; $bind_dependents$;

-- Preserve the exact Archive WHEN guard and source scope; do not copy RF's
-- already-retired legacy writer barrier into the new owner.
do $archive$ declare t record; definition text; begin
 for t in select * from pg_temp.accounts153_trigger_modes where tgname like 'company_archive_track_%' loop
  definition:=pg_catalog.replace(t.definition,' ON public.'||t.family||' ',' ON annual_accounts_filing.'||t.family||' ');
  if definition=t.definition then raise exception 'annual_accounts_archive_trigger_definition_changed'; end if;
  execute definition;
  execute pg_catalog.format('alter table annual_accounts_filing.%I %s trigger %I',t.family,
   case t.tgenabled when 'O' then 'enable' when 'D' then 'disable' when 'R' then 'enable replica' when 'A' then 'enable always' end,t.tgname);
 end loop;
end; $archive$;
do $restore_triggers$ declare t record; begin
 for t in select * from pg_temp.accounts153_trigger_modes loop
  execute pg_catalog.format('alter table public.%I %s trigger %I',t.family,
   case t.tgenabled when 'O' then 'enable' when 'D' then 'disable' when 'R' then 'enable replica' when 'A' then 'enable always' end,t.tgname);
 end loop;
end; $restore_triggers$;
do $verify$ declare f text; remaining bigint; begin
 foreach f in array array['filing_previews','authority_test_runs','authority_permissions','filing_submissions','filing_overrides','filing_review_comments'] loop
  execute pg_catalog.format('select count(*) from public.%I',f) into remaining;
  if remaining<>0 then raise exception 'annual_accounts_generic_source_not_empty'; end if;
 end loop;
 if exists((select * from pg_temp.accounts153_cutover_generations except select * from public.company_archive_source_generations)
 union all (select * from public.company_archive_source_generations except select * from pg_temp.accounts153_cutover_generations))
 then raise exception 'annual_accounts_archive_generation_changed'; end if;
 update backend_system.annual_accounts_migration_state set phase='cutover',changed_at=pg_catalog.now() where singleton;
end; $verify$;
set local role ledger_store_owner;
do $schema_restore$ begin
 if not (select backend_create from pg_temp.accounts153_cutover_schema_privileges) then
  execute pg_catalog.format('revoke create on schema backend_system from %I',session_user);
 end if;
end; $schema_restore$;
reset role;
do $restore$ declare r record; begin
 for r in select * from pg_temp.accounts153_cutover_roles loop
  if r.prior is null then execute pg_catalog.format('revoke %I from %I granted by %I',r.role_name,current_user,current_user);
  else execute pg_catalog.format('grant %I to %I with admin %s,inherit %s,set %s granted by %I',r.role_name,current_user,r.prior->>'admin',r.prior->>'inherit',r.prior->>'set',current_user); end if;
 end loop;
end; $restore$;
commit;
