-- #152 EXPAND ONLY. Legacy generic Tax rows remain the sole active writer.
-- No API permission or business writer is enabled by this artifact.
begin;
set local lock_timeout='5s';
set local statement_timeout='120s';
set local timezone='UTC';
set local search_path='';
select pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended('talli:company-tax-filing:migration:v1',0));

-- #146 owns these roles and the schema; expansion cannot silently create a
-- competing owner or proceed on an uncontracted settlement predecessor.
do $predecessor$ begin
 if not exists(select 1 from backend_system.tax_settlement_migration_state where phase='contracted')
 or pg_catalog.to_regnamespace('company_tax_filing') is null then
  raise exception 'company_tax_return_predecessor_required';
 end if;
end; $predecessor$;
create temporary table tax152_borrowed_roles(role_name name primary key,prior jsonb) on commit drop;
do $borrow$ declare r text; v_prior jsonb; begin
 foreach r in array array['company_tax_filing_store_owner','ledger_store_owner','shareholder_register_filing_store_owner'] loop
  if not pg_catalog.pg_has_role(current_user,r,'SET') then
   select pg_catalog.jsonb_build_object('admin',m.admin_option,'inherit',m.inherit_option,'set',m.set_option) into v_prior
   from pg_catalog.pg_auth_members m where m.roleid=(select oid from pg_catalog.pg_roles where rolname=r)
    and m.member=(select oid from pg_catalog.pg_roles where rolname=current_user)
    and m.grantor=(select oid from pg_catalog.pg_roles where rolname=current_user);
   insert into tax152_borrowed_roles values(r,v_prior);
   execute pg_catalog.format('grant %I to %I with set true granted by %I',r,current_user,current_user);
  end if;
 end loop;
end; $borrow$;
create temporary table tax152_schema_privileges on commit drop as
select pg_catalog.has_schema_privilege(current_user,'backend_system','CREATE') as backend_create,
 pg_catalog.has_schema_privilege('company_tax_filing_store_owner','backend_system','CREATE') as tax_backend_create,
 pg_catalog.has_schema_privilege(current_user,'company_tax_filing','CREATE') as tax_create,
 pg_catalog.has_table_privilege(current_user,'shareholder_register_filing.opening_balance_setups','REFERENCES') as opening_references;
grant select on tax152_schema_privileges to ledger_store_owner,company_tax_filing_store_owner;
set local role ledger_store_owner;
do $grant$ begin
 if not (select tax_backend_create from pg_temp.tax152_schema_privileges) then grant create on schema backend_system to company_tax_filing_store_owner; end if;
 if not (select backend_create from pg_temp.tax152_schema_privileges) then execute pg_catalog.format('grant create on schema backend_system to %I',session_user); end if;
end; $grant$;
reset role;
set local role company_tax_filing_store_owner;
do $grant$ begin
 if not (select tax_create from pg_temp.tax152_schema_privileges) then execute pg_catalog.format('grant create on schema company_tax_filing to %I',session_user); end if;
end; $grant$;
reset role;

grant select on tax152_schema_privileges to shareholder_register_filing_store_owner;
set local role shareholder_register_filing_store_owner;
do $reference_grant$ begin
 if not (select opening_references from pg_temp.tax152_schema_privileges) then execute pg_catalog.format('grant references on shareholder_register_filing.opening_balance_setups to %I',session_user); end if;
end; $reference_grant$;
reset role;

lock table public.filing_previews,public.filing_submissions,public.filing_overrides,
 public.filing_review_comments,public.authority_permissions,public.authority_test_runs in share row exclusive mode;

create table backend_system.company_tax_return_migration_state (
 singleton boolean primary key default true check(singleton),
 phase text not null check(phase in ('expanded','cutover','contracted','rolled_back')),
 source_revision text not null, changed_at timestamptz not null default now()
);
insert into backend_system.company_tax_return_migration_state(singleton,phase,source_revision)
values(true,'expanded','054740b81692e0e59b99a76fff085f322f1968b4');
create table backend_system.company_tax_return_migration_inventory (
 resource text primary key, definition jsonb not null,
 definition_sha256 text not null check(definition_sha256 ~ '^[0-9a-f]{64}$'),
 captured_at timestamptz not null default now()
);
create table backend_system.company_tax_return_source_rows (
 family text not null, source_id uuid not null, payload jsonb not null,
 source_sha256 text not null check(source_sha256 ~ '^[0-9a-f]{64}$'),
 classification text not null check(classification in ('tax','sibling','quarantine')),
 captured_at timestamptz not null default now(),
 primary key(family,source_id,source_sha256)
);
create table backend_system.company_tax_return_quarantine (
 family text not null, source_id uuid not null, payload jsonb not null,
 source_sha256 text not null check(source_sha256 ~ '^[0-9a-f]{64}$'),
 reason text not null, quarantined_at timestamptz not null default now(),
 primary key(family,source_id)
);
create table backend_system.company_tax_return_reconciliations (
 id uuid primary key default gen_random_uuid(), phase text not null, family text not null,
 source_count bigint not null, target_count bigint not null,
 source_digest text not null, target_digest text not null, recorded_at timestamptz not null default now(),
 check(source_count=target_count and source_digest=target_digest)
);

-- Migration-only classification; no runtime policy or second filing engine.
-- The legacy comment target says rf1086_preview even for Tax/Accounts, so only
-- its referenced preview and matching company determine ownership.
create function pg_temp.tax152_classify(family text,row_data jsonb) returns text
language plpgsql set search_path='' as $function$
declare candidate boolean:=false; linked jsonb; linked_tax boolean;
begin
 if family in ('filing_previews','filing_submissions','filing_overrides') then
  if row_data->>'filing' not in ('skattemelding for AS','årsregnskap') then return 'quarantine'; end if;
  candidate:=row_data->>'filing'='skattemelding for AS';
 elsif family in ('authority_permissions','authority_test_runs') then
  candidate:=row_data->>'obligation'='skattemelding';
 elsif family<>'filing_review_comments' then raise exception 'company_tax_return_unknown_family';
 end if;
 if family='filing_overrides' and not candidate and row_data->>'field_target' like 'skattemelding.%' then return 'quarantine'; end if;
 if family in ('filing_submissions','filing_overrides','filing_review_comments') and row_data->>'preview_id' is not null then
  select pg_catalog.to_jsonb(p) into linked from public.filing_previews p where p.id=(row_data->>'preview_id')::uuid;
  if linked is not null and (linked->>'filing' not in ('skattemelding for AS','årsregnskap')
   or linked->>'company_id' is distinct from row_data->>'company_id') then return 'quarantine'; end if;
  linked_tax:=linked->>'filing'='skattemelding for AS';
  if family='filing_review_comments' then candidate:=coalesce(linked_tax,false); end if;
  if candidate or linked_tax then
   if linked is null or not coalesce(linked_tax,false) or not candidate
    or linked->>'company_id' is distinct from row_data->>'company_id'
    or (row_data ? 'income_year' and linked->>'income_year' is distinct from row_data->>'income_year')
   then return 'quarantine'; end if;
  elsif linked is null and family='filing_review_comments' then return 'quarantine';
  end if;
 end if;
 if family='filing_submissions' and row_data->>'authority_test_run_id' is not null then
  select pg_catalog.to_jsonb(r) into linked from public.authority_test_runs r where r.id=(row_data->>'authority_test_run_id')::uuid;
  linked_tax:=linked->>'obligation'='skattemelding';
  if candidate or linked_tax then
   if linked is null or not coalesce(linked_tax,false) or not candidate
    or linked->>'company_id' is distinct from row_data->>'company_id'
   then return 'quarantine'; end if;
  end if;
 end if;
 return case when candidate then 'tax' else 'sibling' end;
end; $function$;

-- Pin original columns, physical references, policy/grant and trigger state;
-- all six families, including siblings, contribute positive enumeration evidence.
do $capture$ declare family text; row_info jsonb; definition jsonb; begin
 foreach family in array array['filing_previews','authority_test_runs','authority_permissions','filing_submissions','filing_overrides','filing_review_comments'] loop
  select pg_catalog.jsonb_build_object('owner',pg_catalog.pg_get_userbyid(c.relowner),'acl',c.relacl,
   'rls',c.relrowsecurity,'forceRls',c.relforcerowsecurity,
   'columns',(select pg_catalog.jsonb_agg(pg_catalog.jsonb_build_object('name',a.attname,'type',pg_catalog.format_type(a.atttypid,a.atttypmod),'notNull',a.attnotnull,'default',pg_catalog.pg_get_expr(d.adbin,d.adrelid)) order by a.attnum)
    from pg_catalog.pg_attribute a left join pg_catalog.pg_attrdef d on d.adrelid=a.attrelid and d.adnum=a.attnum where a.attrelid=c.oid and a.attnum>0 and not a.attisdropped),
   'constraints',(select coalesce(pg_catalog.jsonb_agg(pg_catalog.jsonb_build_object('name',x.conname,'type',x.contype,'definition',pg_catalog.pg_get_constraintdef(x.oid)) order by x.conname),'[]'::jsonb) from pg_catalog.pg_constraint x where x.conrelid=c.oid),
   'policies',(select coalesce(pg_catalog.jsonb_agg(pg_catalog.jsonb_build_object('name',p.polname,'roles',p.polroles,'command',p.polcmd,'permissive',p.polpermissive,'using',pg_catalog.pg_get_expr(p.polqual,p.polrelid),'check',pg_catalog.pg_get_expr(p.polwithcheck,p.polrelid)) order by p.polname),'[]'::jsonb) from pg_catalog.pg_policy p where p.polrelid=c.oid),
   'triggers',(select coalesce(pg_catalog.jsonb_agg(pg_catalog.jsonb_build_object('name',t.tgname,'definition',pg_catalog.pg_get_triggerdef(t.oid),'enabled',t.tgenabled) order by t.tgname),'[]'::jsonb) from pg_catalog.pg_trigger t where t.tgrelid=c.oid and not t.tgisinternal)) into definition
  from pg_catalog.pg_class c where c.oid=pg_catalog.to_regclass('public.'||family) and c.relkind='r';
  if definition is null then raise exception 'company_tax_return_source_relation_required'; end if;
  insert into backend_system.company_tax_return_migration_inventory(resource,definition,definition_sha256)
  values('table:public.'||family,definition,pg_catalog.encode(extensions.digest(definition::text,'sha256'),'hex'));
  for row_info in execute pg_catalog.format('select pg_catalog.to_jsonb(r) from public.%I r',family) loop
   insert into backend_system.company_tax_return_source_rows(family,source_id,payload,source_sha256,classification)
   values(family,(row_info->>'id')::uuid,row_info,pg_catalog.encode(extensions.digest(row_info::text,'sha256'),'hex'),pg_temp.tax152_classify(family,row_info));
  end loop;
 end loop;
 definition:=(select pg_catalog.jsonb_build_object('definition',pg_catalog.pg_get_functiondef(p.oid),'owner',pg_catalog.pg_get_userbyid(p.proowner),'acl',p.proacl)
  from pg_catalog.pg_proc p where p.oid=pg_catalog.to_regprocedure('public.import_company_tax_tt02_evidence(jsonb)'));
 if definition is null then raise exception 'company_tax_return_legacy_writer_required'; end if;
 insert into backend_system.company_tax_return_migration_inventory(resource,definition,definition_sha256)
 values('function:public.import_company_tax_tt02_evidence(jsonb)',definition,pg_catalog.encode(extensions.digest(definition::text,'sha256'),'hex'));
end; $capture$;
insert into backend_system.company_tax_return_quarantine(family,source_id,payload,source_sha256,reason)
select family,source_id,payload,source_sha256,'conflicting_filing_provenance'
from backend_system.company_tax_return_source_rows where classification='quarantine';

create table company_tax_filing.filing_previews (like public.filing_previews including all);
create table company_tax_filing.authority_test_runs (like public.authority_test_runs including all);
create table company_tax_filing.authority_permissions (like public.authority_permissions including all);
create table company_tax_filing.filing_submissions (like public.filing_submissions including all);
create table company_tax_filing.filing_overrides (like public.filing_overrides including all);
create table company_tax_filing.filing_review_comments (like public.filing_review_comments including all);

-- No business triggers are copied: physical backfill must not fabricate events
-- or advance archive source generations. Cutover attaches the owned sources.
do $copy$ declare v_family text; source_count bigint; target_count bigint; source_digest text; target_digest text; begin
 foreach v_family in array array['filing_previews','authority_test_runs','authority_permissions','filing_submissions','filing_overrides','filing_review_comments'] loop
  execute pg_catalog.format('insert into company_tax_filing.%I select (pg_catalog.jsonb_populate_record(null::company_tax_filing.%I,payload)).* from backend_system.company_tax_return_source_rows where family=$1 and classification=''tax''',v_family,v_family) using v_family;
  select count(*),pg_catalog.encode(extensions.digest(coalesce(pg_catalog.string_agg(payload::text,E'\n' order by source_id),''),'sha256'),'hex') into source_count,source_digest
  from backend_system.company_tax_return_source_rows r where r.family=v_family and classification='tax';
  execute pg_catalog.format('select count(*),pg_catalog.encode(extensions.digest(coalesce(pg_catalog.string_agg(pg_catalog.to_jsonb(t)::text,E''\n'' order by id),''''),''sha256''),''hex'') from company_tax_filing.%I t',v_family) into target_count,target_digest;
  insert into backend_system.company_tax_return_reconciliations(phase,family,source_count,target_count,source_digest,target_digest)
  values('expanded',v_family,source_count,target_count,source_digest,target_digest);
 end loop;
end; $copy$;

-- LIKE retains checks, indexes and defaults. Restore the existing FK behavior,
-- rebinding only Tax's intra-capability references. External IDs keep their
-- original physical retention semantics; no new cross-owner reads are granted.
do $foreign_keys$ declare family text; constraint_info record; definition text; target text; begin
 foreach family in array array['filing_previews','authority_test_runs','authority_permissions','filing_submissions','filing_overrides','filing_review_comments'] loop
  for constraint_info in select conname,pg_catalog.pg_get_constraintdef(oid) as definition from pg_catalog.pg_constraint
   where conrelid=pg_catalog.to_regclass('public.'||family) and contype='f' loop
   definition:=constraint_info.definition;
   foreach target in array array['filing_previews','authority_test_runs','authority_permissions','filing_submissions','filing_overrides','filing_review_comments'] loop
    definition:=pg_catalog.replace(definition,'REFERENCES public.'||target||'(','REFERENCES company_tax_filing.'||target||'(');
   end loop;
   execute pg_catalog.format('alter table company_tax_filing.%I add constraint %I %s',family,constraint_info.conname,definition);
  end loop;
 end loop;
end; $foreign_keys$;

-- Explicit single-obligation fences supplement the inherited shape checks.
alter table company_tax_filing.filing_previews add constraint company_tax_preview_obligation check(filing='skattemelding for AS');
alter table company_tax_filing.filing_submissions add constraint company_tax_submission_obligation check(filing='skattemelding for AS');
alter table company_tax_filing.filing_overrides add constraint company_tax_override_obligation check(filing='skattemelding for AS');
alter table company_tax_filing.authority_permissions add constraint company_tax_permission_obligation check(obligation='skattemelding');
alter table company_tax_filing.authority_test_runs add constraint company_tax_test_obligation check(obligation='skattemelding');

-- Locked expansion targets have FORCE RLS with no business policy or grants.
-- Technical evidence is private to the restricted store owner/migration runner.
do $seal$ declare family text; begin
 foreach family in array array['filing_previews','authority_test_runs','authority_permissions','filing_submissions','filing_overrides','filing_review_comments'] loop
  execute pg_catalog.format('alter table company_tax_filing.%I enable row level security',family);
  execute pg_catalog.format('alter table company_tax_filing.%I force row level security',family);
  execute pg_catalog.format('revoke all on company_tax_filing.%I from public,anon,authenticated,service_role,company_tax_filing_workflow_executor',family);
  execute pg_catalog.format('alter table company_tax_filing.%I owner to company_tax_filing_store_owner',family);
 end loop;
 foreach family in array array['company_tax_return_migration_state','company_tax_return_migration_inventory','company_tax_return_source_rows','company_tax_return_quarantine','company_tax_return_reconciliations'] loop
  execute pg_catalog.format('alter table backend_system.%I enable row level security',family);
  execute pg_catalog.format('alter table backend_system.%I force row level security',family);
  execute pg_catalog.format('revoke all on backend_system.%I from public,anon,authenticated,service_role,company_tax_filing_workflow_executor',family);
  execute pg_catalog.format('create policy tax_return_migration_private on backend_system.%I for all to company_tax_filing_store_owner using(true) with check(true)',family);
  execute pg_catalog.format('alter table backend_system.%I owner to company_tax_filing_store_owner',family);
 end loop;
end; $seal$;

-- Return borrowed schema privileges and role memberships to their exact state.
set local role shareholder_register_filing_store_owner;
do $reference_restore$ begin
 if not (select opening_references from pg_temp.tax152_schema_privileges) then
  execute pg_catalog.format('revoke references on shareholder_register_filing.opening_balance_setups from %I',session_user);
 end if;
end; $reference_restore$;
reset role;
set local role ledger_store_owner;
do $schema_restore$ begin
 if not (select backend_create from pg_temp.tax152_schema_privileges) then execute pg_catalog.format('revoke create on schema backend_system from %I',session_user); end if;
 if not (select tax_backend_create from pg_temp.tax152_schema_privileges) then revoke create on schema backend_system from company_tax_filing_store_owner; end if;
end; $schema_restore$;
reset role;
set local role company_tax_filing_store_owner;
do $schema_restore$ begin
 if not (select tax_create from pg_temp.tax152_schema_privileges) then execute pg_catalog.format('revoke create on schema company_tax_filing from %I',session_user); end if;
end; $schema_restore$;
reset role;
do $restore$ declare r record; begin
 for r in select * from tax152_borrowed_roles loop
  execute pg_catalog.format('revoke %I from %I granted by %I',r.role_name,current_user,current_user);
  if r.prior is not null then
   execute pg_catalog.format('grant %I to %I with admin %s,inherit %s,set %s granted by %I',r.role_name,current_user,(r.prior->>'admin')::boolean,(r.prior->>'inherit')::boolean,(r.prior->>'set')::boolean,current_user);
  end if;
 end loop;
end; $restore$;
commit;
