-- #153 EXPAND ONLY. Legacy generic Accounts rows remain the sole active writer.
-- No API permission or business writer is enabled by this artifact.
begin;
set local lock_timeout='5s';
set local statement_timeout='120s';
set local timezone='UTC';
set local search_path='';
select pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended('talli:annual-accounts-filing:migration:v1',0));

-- Serial predecessor and first owner creation; no existing runtime is switched.
do $predecessor$ begin
 if not exists(select 1 from backend_system.company_tax_return_migration_state where phase='contracted') then
  raise exception 'annual_accounts_predecessor_required';
 end if;
 if pg_catalog.to_regnamespace('annual_accounts_filing') is not null then
  raise exception 'annual_accounts_expansion_already_exists';
 end if;
end; $predecessor$;
do $roles$ declare r text; begin
 foreach r in array array['annual_accounts_filing_store_owner','annual_accounts_filing_workflow_executor'] loop
  if not exists(select 1 from pg_catalog.pg_roles where rolname=r) then
   execute pg_catalog.format('create role %I nologin noinherit nosuperuser nocreatedb nocreaterole noreplication nobypassrls',r);
  end if;
  if exists(select 1 from pg_catalog.pg_roles where rolname=r and
   (rolcanlogin or rolinherit or rolsuper or rolcreatedb or rolcreaterole or rolreplication or rolbypassrls))
  then raise exception 'annual_accounts_role_attributes_invalid'; end if;
 end loop;
end; $roles$;
create temporary table accounts153_borrowed_roles(role_name name primary key,prior jsonb) on commit drop;
do $borrow$ declare r text; v_prior jsonb; begin
 foreach r in array array['annual_accounts_filing_store_owner','ledger_store_owner','shareholder_register_filing_store_owner'] loop
  if not pg_catalog.pg_has_role(current_user,r,'SET') then
   select pg_catalog.jsonb_build_object('admin',m.admin_option,'inherit',m.inherit_option,'set',m.set_option) into v_prior
   from pg_catalog.pg_auth_members m where m.roleid=(select oid from pg_catalog.pg_roles where rolname=r)
    and m.member=(select oid from pg_catalog.pg_roles where rolname=current_user)
    and m.grantor=(select oid from pg_catalog.pg_roles where rolname=current_user);
   insert into accounts153_borrowed_roles values(r,v_prior);
   execute pg_catalog.format('grant %I to %I with set true granted by %I',r,current_user,current_user);
  end if;
 end loop;
end; $borrow$;
create schema annual_accounts_filing authorization annual_accounts_filing_store_owner;
revoke all on schema annual_accounts_filing from public,anon,authenticated,service_role;
grant usage on schema annual_accounts_filing to annual_accounts_filing_workflow_executor;
grant usage on schema public,auth,extensions,backend_system to annual_accounts_filing_store_owner;
grant execute on function public.company_access_auth_uid_v1(),public.company_access_auth_jwt_v1(),
 public.company_access_is_accepted_member_v1(uuid),public.company_access_is_accepted_owner_v1(uuid)
 to annual_accounts_filing_store_owner;
create temporary table accounts153_schema_privileges on commit drop as
select pg_catalog.has_schema_privilege(current_user,'backend_system','CREATE') as backend_create,
 pg_catalog.has_schema_privilege('annual_accounts_filing_store_owner','backend_system','CREATE') as accounts_backend_create,
 pg_catalog.has_schema_privilege(current_user,'annual_accounts_filing','CREATE') as accounts_create,
 pg_catalog.has_table_privilege(current_user,'shareholder_register_filing.opening_balance_setups','REFERENCES') as opening_references;
grant select on accounts153_schema_privileges to ledger_store_owner,annual_accounts_filing_store_owner;
set local role ledger_store_owner;
do $grant$ begin
 if not (select accounts_backend_create from pg_temp.accounts153_schema_privileges) then grant create on schema backend_system to annual_accounts_filing_store_owner; end if;
 if not (select backend_create from pg_temp.accounts153_schema_privileges) then execute pg_catalog.format('grant create on schema backend_system to %I',session_user); end if;
end; $grant$;
reset role;
set local role annual_accounts_filing_store_owner;
do $grant$ begin
 if not (select accounts_create from pg_temp.accounts153_schema_privileges) then execute pg_catalog.format('grant create on schema annual_accounts_filing to %I',session_user); end if;
end; $grant$;
reset role;

grant select on accounts153_schema_privileges to shareholder_register_filing_store_owner;
set local role shareholder_register_filing_store_owner;
do $reference_grant$ begin
 if not (select opening_references from pg_temp.accounts153_schema_privileges) then execute pg_catalog.format('grant references on shareholder_register_filing.opening_balance_setups to %I',session_user); end if;
end; $reference_grant$;
reset role;

lock table public.filing_previews,public.filing_submissions,public.filing_overrides,
 public.filing_review_comments,public.authority_permissions,public.authority_test_runs in share row exclusive mode;

-- Migration-only scope evidence for retained RF-owned setup IDs. The owner
-- takes the snapshot under a write-blocking lock; its temporary SELECT policy
-- is removed in this transaction, so no runtime cross-owner access is added.
create temporary table accounts153_setup_ids(id uuid primary key) on commit drop;
insert into accounts153_setup_ids
select setup_id from public.filing_previews where setup_id is not null
union select setup_id from public.filing_submissions where setup_id is not null;
create temporary table accounts153_setup_scopes(id uuid primary key,company_id uuid,income_year integer) on commit drop;
grant select on accounts153_setup_ids to shareholder_register_filing_store_owner;
grant insert on accounts153_setup_scopes to shareholder_register_filing_store_owner;
set local role shareholder_register_filing_store_owner;
lock table shareholder_register_filing.opening_balance_setups in share row exclusive mode;
create policy accounts153_migration_setup_scope on shareholder_register_filing.opening_balance_setups
 for select to shareholder_register_filing_store_owner using(true);
insert into pg_temp.accounts153_setup_scopes
select s.id,s.company_id,s.income_year from shareholder_register_filing.opening_balance_setups s
join pg_temp.accounts153_setup_ids wanted on wanted.id=s.id;
drop policy accounts153_migration_setup_scope on shareholder_register_filing.opening_balance_setups;
reset role;

create table backend_system.annual_accounts_migration_state (
 singleton boolean primary key default true check(singleton),
 phase text not null check(phase in ('expanded','cutover','contracted','rolled_back')),
 source_revision text not null, changed_at timestamptz not null default now()
);
insert into backend_system.annual_accounts_migration_state(singleton,phase,source_revision)
values(true,'expanded','5b74340ca75f215b43d754c6bf0fc49ef5974b0b');
create table backend_system.annual_accounts_migration_inventory (
 resource text primary key, definition jsonb not null,
 definition_sha256 text not null check(definition_sha256 ~ '^[0-9a-f]{64}$'),
 captured_at timestamptz not null default now()
);
create table backend_system.annual_accounts_source_rows (
 family text not null, source_id uuid not null, payload jsonb not null,
 source_sha256 text not null check(source_sha256 ~ '^[0-9a-f]{64}$'),
 classification text not null check(classification in ('accounts','quarantine')),
 captured_at timestamptz not null default now(),
 primary key(family,source_id,source_sha256)
);
create table backend_system.annual_accounts_quarantine (
 family text not null, source_id uuid not null, payload jsonb not null,
 source_sha256 text not null check(source_sha256 ~ '^[0-9a-f]{64}$'),
 reason text not null, quarantined_at timestamptz not null default now(),
 primary key(family,source_id)
);
create table backend_system.annual_accounts_reconciliations (
 id uuid primary key default gen_random_uuid(), phase text not null, family text not null,
 source_count bigint not null, target_count bigint not null,
 source_digest text not null, target_digest text not null, recorded_at timestamptz not null default now(),
 check(source_count=target_count and source_digest=target_digest)
);

-- Accounts is the last generic-row owner. Every remaining row must positively
-- match Accounts and its references; unfamiliar or conflicting provenance is
-- retained in quarantine and prevents later cutover. Legacy review target text
-- remains rf1086_preview; referenced preview identity establishes ownership.
create function pg_temp.accounts153_classify(family text,row_data jsonb) returns text
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
  select pg_catalog.to_jsonb(s) into linked from pg_temp.accounts153_setup_scopes s where s.id=(row_data->>'setup_id')::uuid;
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
  if pg_temp.accounts153_classify('filing_previews',linked)<>'accounts' then return 'quarantine'; end if;
 end if;
 if family='filing_submissions' and row_data->>'authority_test_run_id' is not null then
  select pg_catalog.to_jsonb(r) into linked from public.authority_test_runs r where r.id=(row_data->>'authority_test_run_id')::uuid;
  if linked is null or linked->>'obligation' is distinct from 'aarsregnskap'
   or linked->>'company_id' is distinct from row_data->>'company_id'
  then return 'quarantine'; end if;
 end if;
 return 'accounts';
end; $function$;

-- Pin original columns, physical references, policy/grant and trigger state;
-- all six families, including quarantined rows, contribute positive enumeration evidence.
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
  if definition is null then raise exception 'annual_accounts_source_relation_required'; end if;
  insert into backend_system.annual_accounts_migration_inventory(resource,definition,definition_sha256)
  values('table:public.'||family,definition,pg_catalog.encode(extensions.digest(definition::text,'sha256'),'hex'));
  for row_info in execute pg_catalog.format('select pg_catalog.to_jsonb(r) from public.%I r',family) loop
   insert into backend_system.annual_accounts_source_rows(family,source_id,payload,source_sha256,classification)
   values(family,(row_info->>'id')::uuid,row_info,pg_catalog.encode(extensions.digest(row_info::text,'sha256'),'hex'),pg_temp.accounts153_classify(family,row_info));
  end loop;
 end loop;
 -- Snapshot every existing dependent business routine as rollback evidence;
 -- expansion does not rewrite any routine body, owner or grants.
 for row_info in select pg_catalog.jsonb_build_object(
  'identity',n.nspname||'.'||p.proname||'('||pg_catalog.pg_get_function_identity_arguments(p.oid)||')',
  'definition',pg_catalog.pg_get_functiondef(p.oid),'owner',pg_catalog.pg_get_userbyid(p.proowner),'acl',p.proacl)
  from pg_catalog.pg_proc p join pg_catalog.pg_namespace n on n.oid=p.pronamespace
  where p.prokind='f' and n.nspname in ('public','documents','backend_system','company_tax_filing','shareholder_register_filing')
   and p.prosrc ~ '(filing_previews|filing_submissions|filing_overrides|filing_review_comments|authority_permissions|authority_test_runs)'
 loop
  insert into backend_system.annual_accounts_migration_inventory(resource,definition,definition_sha256)
  values('function:'||(row_info->>'identity'),row_info,pg_catalog.encode(extensions.digest(row_info::text,'sha256'),'hex'));
 end loop;
end; $capture$;
insert into backend_system.annual_accounts_quarantine(family,source_id,payload,source_sha256,reason)
select family,source_id,payload,source_sha256,'conflicting_filing_provenance'
from backend_system.annual_accounts_source_rows where classification='quarantine';

create table annual_accounts_filing.filing_previews (like public.filing_previews including all);
create table annual_accounts_filing.authority_test_runs (like public.authority_test_runs including all);
create table annual_accounts_filing.authority_permissions (like public.authority_permissions including all);
create table annual_accounts_filing.filing_submissions (like public.filing_submissions including all);
create table annual_accounts_filing.filing_overrides (like public.filing_overrides including all);
create table annual_accounts_filing.filing_review_comments (like public.filing_review_comments including all);

-- No business triggers are copied: physical backfill must not fabricate events
-- or advance archive source generations. Cutover attaches the owned sources.
do $copy$ declare v_family text; source_count bigint; target_count bigint; source_digest text; target_digest text; begin
 foreach v_family in array array['filing_previews','authority_test_runs','authority_permissions','filing_submissions','filing_overrides','filing_review_comments'] loop
  execute pg_catalog.format('insert into annual_accounts_filing.%I select (pg_catalog.jsonb_populate_record(null::annual_accounts_filing.%I,payload)).* from backend_system.annual_accounts_source_rows where family=$1 and classification=''accounts''',v_family,v_family) using v_family;
  select count(*),pg_catalog.encode(extensions.digest(coalesce(pg_catalog.string_agg(payload::text,E'\n' order by source_id),''),'sha256'),'hex') into source_count,source_digest
  from backend_system.annual_accounts_source_rows r where r.family=v_family and classification='accounts';
  execute pg_catalog.format('select count(*),pg_catalog.encode(extensions.digest(coalesce(pg_catalog.string_agg(pg_catalog.to_jsonb(t)::text,E''\n'' order by id),''''),''sha256''),''hex'') from annual_accounts_filing.%I t',v_family) into target_count,target_digest;
  insert into backend_system.annual_accounts_reconciliations(phase,family,source_count,target_count,source_digest,target_digest)
  values('expanded',v_family,source_count,target_count,source_digest,target_digest);
 end loop;
end; $copy$;

-- LIKE retains checks, indexes and defaults. Restore the existing FK behavior,
-- rebinding only Accounts' intra-capability references. External IDs keep their
-- original physical retention semantics; no new cross-owner reads are granted.
do $foreign_keys$ declare family text; constraint_info record; definition text; target text; begin
 foreach family in array array['filing_previews','authority_test_runs','authority_permissions','filing_submissions','filing_overrides','filing_review_comments'] loop
  for constraint_info in select conname,pg_catalog.pg_get_constraintdef(oid) as definition from pg_catalog.pg_constraint
   where conrelid=pg_catalog.to_regclass('public.'||family) and contype='f' loop
   definition:=constraint_info.definition;
   foreach target in array array['filing_previews','authority_test_runs','authority_permissions','filing_submissions','filing_overrides','filing_review_comments'] loop
    definition:=pg_catalog.replace(definition,'REFERENCES public.'||target||'(','REFERENCES annual_accounts_filing.'||target||'(');
   end loop;
   execute pg_catalog.format('alter table annual_accounts_filing.%I add constraint %I %s',family,constraint_info.conname,definition);
  end loop;
 end loop;
end; $foreign_keys$;

-- Explicit single-obligation fences supplement the inherited shape checks.
alter table annual_accounts_filing.filing_previews add constraint annual_accounts_preview_obligation check(filing='årsregnskap');
alter table annual_accounts_filing.filing_submissions add constraint annual_accounts_submission_obligation check(filing='årsregnskap');
alter table annual_accounts_filing.filing_overrides add constraint annual_accounts_override_obligation check(filing='årsregnskap');
alter table annual_accounts_filing.authority_permissions add constraint annual_accounts_permission_obligation check(obligation='aarsregnskap');
alter table annual_accounts_filing.authority_test_runs add constraint annual_accounts_test_obligation check(obligation='aarsregnskap');

-- Locked expansion targets have FORCE RLS with no business policy or grants.
-- Technical evidence is private to the restricted store owner/migration runner.
do $seal$ declare family text; begin
 foreach family in array array['filing_previews','authority_test_runs','authority_permissions','filing_submissions','filing_overrides','filing_review_comments'] loop
  execute pg_catalog.format('alter table annual_accounts_filing.%I enable row level security',family);
  execute pg_catalog.format('alter table annual_accounts_filing.%I force row level security',family);
  execute pg_catalog.format('revoke all on annual_accounts_filing.%I from public,anon,authenticated,service_role,annual_accounts_filing_workflow_executor',family);
  execute pg_catalog.format('alter table annual_accounts_filing.%I owner to annual_accounts_filing_store_owner',family);
 end loop;
 foreach family in array array['annual_accounts_migration_state','annual_accounts_migration_inventory','annual_accounts_source_rows','annual_accounts_quarantine','annual_accounts_reconciliations'] loop
  execute pg_catalog.format('alter table backend_system.%I enable row level security',family);
  execute pg_catalog.format('alter table backend_system.%I force row level security',family);
  execute pg_catalog.format('revoke all on backend_system.%I from public,anon,authenticated,service_role,annual_accounts_filing_workflow_executor',family);
  execute pg_catalog.format('create policy accounts_filing_migration_private on backend_system.%I for all to annual_accounts_filing_store_owner using(true) with check(true)',family);
  execute pg_catalog.format('alter table backend_system.%I owner to annual_accounts_filing_store_owner',family);
 end loop;
end; $seal$;

-- Return borrowed schema privileges and role memberships to their exact state.
set local role shareholder_register_filing_store_owner;
do $reference_restore$ begin
 if not (select opening_references from pg_temp.accounts153_schema_privileges) then
  execute pg_catalog.format('revoke references on shareholder_register_filing.opening_balance_setups from %I',session_user);
 end if;
end; $reference_restore$;
reset role;
set local role ledger_store_owner;
do $schema_restore$ begin
 if not (select backend_create from pg_temp.accounts153_schema_privileges) then execute pg_catalog.format('revoke create on schema backend_system from %I',session_user); end if;
 if not (select accounts_backend_create from pg_temp.accounts153_schema_privileges) then revoke create on schema backend_system from annual_accounts_filing_store_owner; end if;
end; $schema_restore$;
reset role;
set local role annual_accounts_filing_store_owner;
do $schema_restore$ begin
 if not (select accounts_create from pg_temp.accounts153_schema_privileges) then execute pg_catalog.format('revoke create on schema annual_accounts_filing from %I',session_user); end if;
end; $schema_restore$;
reset role;
do $restore$ declare r record; begin
 for r in select * from accounts153_borrowed_roles loop
  execute pg_catalog.format('revoke %I from %I granted by %I',r.role_name,current_user,current_user);
  if r.prior is not null then
   execute pg_catalog.format('grant %I to %I with admin %s,inherit %s,set %s granted by %I',r.role_name,current_user,(r.prior->>'admin')::boolean,(r.prior->>'inherit')::boolean,(r.prior->>'set')::boolean,current_user);
  end if;
 end loop;
end; $restore$;
commit;
