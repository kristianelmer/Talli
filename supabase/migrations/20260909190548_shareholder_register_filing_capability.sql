-- #151 expand: one legacy-authoritative preparation writer during overlap.
-- RF production journal tables retain their physical OIDs and original records.
begin;
set local lock_timeout='5s';
set local statement_timeout='120s';
select pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended('talli:rf1086:capability:v1',0));
do $roles$ begin
  if not exists(select 1 from pg_catalog.pg_roles where rolname='shareholder_register_filing_store_owner') then
    create role shareholder_register_filing_store_owner nologin noinherit nobypassrls;
  end if;
  if not exists(select 1 from pg_catalog.pg_roles where rolname='shareholder_register_filing_executor') then
    create role shareholder_register_filing_executor nologin noinherit nobypassrls;
  end if;
end; $roles$;
create temporary table rf151_borrowed_roles(role_name name primary key,prior jsonb) on commit drop;
do $borrow$ declare r text; v_prior jsonb; begin
  foreach r in array array['shareholder_register_filing_store_owner','shareholder_register_filing_executor','ledger_store_owner','ledger_workflow_store_owner','company_access_executor','authority_connections_store_owner','billing_store_owner','documents_store_owner','company_archive_projection_executor'] loop
    if not pg_catalog.pg_has_role(current_user,r,'SET') then
      select pg_catalog.jsonb_build_object('admin',m.admin_option,'inherit',m.inherit_option,'set',m.set_option) into v_prior
      from pg_catalog.pg_auth_members m where m.roleid=(select oid from pg_catalog.pg_roles where rolname=r)
        and m.member=(select oid from pg_catalog.pg_roles where rolname=current_user)
        and m.grantor=(select oid from pg_catalog.pg_roles where rolname=current_user);
      insert into rf151_borrowed_roles values(r,v_prior);
      execute pg_catalog.format('grant %I to %I with set true granted by %I',r,current_user,current_user);
    end if;
  end loop;
end; $borrow$;
create schema shareholder_register_filing authorization shareholder_register_filing_store_owner;
revoke all on schema shareholder_register_filing from public,anon,authenticated,service_role;
grant usage on schema shareholder_register_filing to shareholder_register_filing_executor,ledger_workflow_executor,ledger_workflow_store_owner;
grant shareholder_register_filing_executor to talli_ledger_backend with inherit false,set true;

lock table public.opening_balance_setups,public.opening_shareholders,public.filing_previews,public.filing_submissions,public.filing_overrides,public.filing_review_comments,public.authority_permissions,public.authority_test_runs,public.filing_approval_snapshots,public.production_filing_submissions,public.production_filing_events,public.production_feedback_artifacts in share row exclusive mode;

create temporary table rf151_original_rows(family text,record_id uuid,original_row jsonb,primary key(family,record_id)) on commit drop;

insert into rf151_original_rows select 'opening_balance_setups',id,pg_catalog.to_jsonb(t) from public.opening_balance_setups t;

insert into rf151_original_rows select 'opening_shareholders',id,pg_catalog.to_jsonb(t) from public.opening_shareholders t;

insert into rf151_original_rows select 'filing_previews',id,pg_catalog.to_jsonb(t) from public.filing_previews t;

insert into rf151_original_rows select 'filing_submissions',id,pg_catalog.to_jsonb(t) from public.filing_submissions t;

insert into rf151_original_rows select 'filing_overrides',id,pg_catalog.to_jsonb(t) from public.filing_overrides t;

insert into rf151_original_rows select 'filing_review_comments',id,pg_catalog.to_jsonb(t) from public.filing_review_comments t;

insert into rf151_original_rows select 'authority_permissions',id,pg_catalog.to_jsonb(t) from public.authority_permissions t;

insert into rf151_original_rows select 'authority_test_runs',id,pg_catalog.to_jsonb(t) from public.authority_test_runs t;

insert into rf151_original_rows select 'filing_approval_snapshots',id,pg_catalog.to_jsonb(t) from public.filing_approval_snapshots t;

insert into rf151_original_rows select 'production_filing_submissions',id,pg_catalog.to_jsonb(t) from public.production_filing_submissions t;

insert into rf151_original_rows select 'production_filing_events',id,pg_catalog.to_jsonb(t) from public.production_filing_events t;

insert into rf151_original_rows select 'production_feedback_artifacts',id,pg_catalog.to_jsonb(t) from public.production_feedback_artifacts t;

create table shareholder_register_filing.migration_state(
 singleton boolean primary key default true check(singleton),
 phase text not null check(phase in ('legacy_overlap','canonical_overlap','contracted')),
 version text not null, source_revision text not null, expanded_at timestamptz not null default now(),
 original_objects jsonb not null default '{}'::jsonb, original_relations jsonb not null default '{}'::jsonb, original_foreign_policies jsonb not null default '{}'::jsonb, original_opening_schema jsonb not null default '{}'::jsonb, reconciliation jsonb not null default '{}'::jsonb
);
insert into shareholder_register_filing.migration_state(singleton,phase,version,source_revision)
values(true,'legacy_overlap','rf1086-storage-v1','7a49f010229baf13d4942364d352786d7cddc5c3');
create table shareholder_register_filing.migration_inventory(
 company_id uuid not null, income_year integer not null,
 family text not null, row_count bigint not null, row_digest text not null,
 quarantined_count bigint not null default 0, recorded_at timestamptz not null default now(),
 primary key(company_id,income_year,family)
);
create table shareholder_register_filing.migration_quarantine(
 family text not null, record_id uuid not null, company_id uuid, income_year integer,
 reason text not null, original_row jsonb not null, recorded_at timestamptz not null default now(),
 primary key(family,record_id)
);
update shareholder_register_filing.migration_state set original_objects=(
  select pg_catalog.jsonb_object_agg(n.nspname||'.'||p.proname||'('||pg_catalog.oidvectortypes(p.proargtypes)||')',
    pg_catalog.jsonb_build_object('definition',pg_catalog.pg_get_functiondef(p.oid),'owner',pg_catalog.pg_get_userbyid(p.proowner),'acl',p.proacl))
  from pg_catalog.pg_proc p join pg_catalog.pg_namespace n on n.oid=p.pronamespace
  where p.prokind='f' and (n.nspname='legacy_rf1086' or p.proname in (
    'approve_production_filing','begin_production_filing','append_production_filing_event',
    'claim_production_feedback_reconciliation','release_production_feedback_reconciliation',
    'append_production_feedback_reconciliation','record_production_feedback_artifact',
    'record_opening_snapshot_legacy_v1','list_opening_snapshots_legacy_v1','read_rf_pilot_v1','lock_rf_pilot_v1','company_access_read_support_case','has_evidence_references_v1','rf1086_confirmation_forsendelse_id'))
);

update shareholder_register_filing.migration_state set original_relations=(
 select pg_catalog.jsonb_object_agg(c.relname,pg_catalog.jsonb_build_object('owner',pg_catalog.pg_get_userbyid(c.relowner),'acl',c.relacl,'force_rls',c.relforcerowsecurity,'policies',(select coalesce(pg_catalog.jsonb_agg(pg_catalog.jsonb_build_object(
 'name',pol.polname,'roles',array(select case when roleid=0 then 'public' else pg_catalog.pg_get_userbyid(roleid) end from pg_catalog.unnest(pol.polroles) roleid),
 'command',case pol.polcmd when 'r' then 'SELECT' when 'a' then 'INSERT' when 'w' then 'UPDATE' when 'd' then 'DELETE' else 'ALL' end,
 'permissive',pol.polpermissive,'qual',pg_catalog.pg_get_expr(pol.polqual,pol.polrelid),'with_check',pg_catalog.pg_get_expr(pol.polwithcheck,pol.polrelid))), '[]'::jsonb) from pg_catalog.pg_policy pol where pol.polrelid=c.oid)))
 from pg_catalog.pg_class c join pg_catalog.pg_namespace n on n.oid=c.relnamespace
 where n.nspname='public' and c.relname in ('opening_balance_setups','opening_shareholders','filing_previews','filing_submissions','filing_overrides','filing_review_comments','authority_permissions','authority_test_runs','filing_approval_snapshots','production_filing_submissions','production_filing_events','production_feedback_artifacts'));

update shareholder_register_filing.migration_state set original_foreign_policies=(select pg_catalog.jsonb_object_agg(pol.polname,pg_catalog.jsonb_build_object('qual',pg_catalog.pg_get_expr(pol.polqual,pol.polrelid),'check',pg_catalog.pg_get_expr(pol.polwithcheck,pol.polrelid))) from pg_catalog.pg_policy pol where pol.polrelid='billing.production_pilot_entitlements'::regclass and pol.polname in ('billing_rf_pilot_owner_read','billing_rf_pilot_owner_lock'));

do $capture_opening_schema$ declare original_path text:=pg_catalog.current_setting('search_path'); begin
perform pg_catalog.set_config('search_path','',true);
update shareholder_register_filing.migration_state set original_opening_schema=(select pg_catalog.jsonb_object_agg(c.relname,pg_catalog.jsonb_build_object(
 'columns',(select pg_catalog.jsonb_agg(pg_catalog.jsonb_build_object('attnum',a.attnum,'name',a.attname,'format_type',pg_catalog.format_type(a.atttypid,a.atttypmod),'not_null',a.attnotnull,'default_sql',pg_catalog.pg_get_expr(d.adbin,d.adrelid),'identity',a.attidentity,'generated',a.attgenerated,'collation_schema',case when a.attcollation<>t.typcollation then cn.nspname end,'collation_name',case when a.attcollation<>t.typcollation then co.collname end) order by a.attnum) from pg_catalog.pg_attribute a join pg_catalog.pg_type t on t.oid=a.atttypid left join pg_catalog.pg_attrdef d on d.adrelid=a.attrelid and d.adnum=a.attnum left join pg_catalog.pg_collation co on co.oid=a.attcollation left join pg_catalog.pg_namespace cn on cn.oid=co.collnamespace where a.attrelid=c.oid and a.attnum>0 and not a.attisdropped),
 'constraints',(select coalesce(pg_catalog.jsonb_agg(pg_catalog.jsonb_build_object('name',x.conname,'type',x.contype,'definition',pg_catalog.pg_get_constraintdef(x.oid),'validated',x.convalidated) order by x.conname),'[]'::jsonb) from pg_catalog.pg_constraint x where x.conrelid=c.oid),
 'indexes',(select coalesce(pg_catalog.jsonb_agg(pg_catalog.jsonb_build_object('name',ic.relname,'definition',pg_catalog.pg_get_indexdef(i.indexrelid)) order by ic.relname),'[]'::jsonb) from pg_catalog.pg_index i join pg_catalog.pg_class ic on ic.oid=i.indexrelid where i.indrelid=c.oid and not exists(select 1 from pg_catalog.pg_constraint x where x.conindid=i.indexrelid)),
 'triggers',(select coalesce(pg_catalog.jsonb_agg(pg_catalog.jsonb_build_object('name',g.tgname,'definition',pg_catalog.pg_get_triggerdef(g.oid),'enabled',g.tgenabled) order by g.tgname),'[]'::jsonb) from pg_catalog.pg_trigger g where g.tgrelid=c.oid and not g.tgisinternal),
 'rls_enabled',c.relrowsecurity)) from pg_catalog.pg_class c where c.oid in ('public.opening_balance_setups'::regclass,'public.opening_shareholders'::regclass));
perform pg_catalog.set_config('search_path',original_path,true);
end; $capture_opening_schema$;

create table shareholder_register_filing.opening_balance_setups (like public.opening_balance_setups including all);

create table shareholder_register_filing.opening_shareholders (like public.opening_shareholders including all);

create table shareholder_register_filing.filing_previews (like public.filing_previews including all);

create table shareholder_register_filing.filing_submissions (like public.filing_submissions including all);

create table shareholder_register_filing.filing_overrides (like public.filing_overrides including all);

create table shareholder_register_filing.filing_review_comments (like public.filing_review_comments including all);

create table shareholder_register_filing.authority_permissions (like public.authority_permissions including all);

create table shareholder_register_filing.authority_test_runs (like public.authority_test_runs including all);

alter table shareholder_register_filing.opening_balance_setups drop column bank_balance;

alter table public.filing_approval_snapshots set schema shareholder_register_filing;
create view public.filing_approval_snapshots with (security_invoker=true) as select * from shareholder_register_filing.filing_approval_snapshots;
grant select on public.filing_approval_snapshots to authenticated,service_role,legacy_rf1086_executor;
grant usage on schema shareholder_register_filing to authenticated,service_role,legacy_rf1086_executor;

alter table public.production_filing_submissions set schema shareholder_register_filing;
create view public.production_filing_submissions with (security_invoker=true) as select * from shareholder_register_filing.production_filing_submissions;
grant select on public.production_filing_submissions to authenticated,service_role,legacy_rf1086_executor;
grant usage on schema shareholder_register_filing to authenticated,service_role,legacy_rf1086_executor;

alter table public.production_filing_events set schema shareholder_register_filing;
create view public.production_filing_events with (security_invoker=true) as select * from shareholder_register_filing.production_filing_events;
grant select on public.production_filing_events to authenticated,service_role,legacy_rf1086_executor;
grant usage on schema shareholder_register_filing to authenticated,service_role,legacy_rf1086_executor;

alter table public.production_feedback_artifacts set schema shareholder_register_filing;
create view public.production_feedback_artifacts with (security_invoker=true) as select * from shareholder_register_filing.production_feedback_artifacts;
grant select on public.production_feedback_artifacts to authenticated,service_role,legacy_rf1086_executor;
grant usage on schema shareholder_register_filing to authenticated,service_role,legacy_rf1086_executor;

-- Run at expand after physical production tables have moved and their four
-- security-invoker public views exist. No function is dropped, so existing
-- return-type OIDs, grants, ownership, attributes and dependencies remain.
-- Only four fixed physical relation references are rebound; no RF rule changes.
do $rf151_rebind_legacy_physical_journal$ declare item record; statement text; n text; restored integer:=0; begin
 for item in select * from pg_catalog.jsonb_each((select original_objects from shareholder_register_filing.migration_state where singleton))
 where pg_catalog.split_part(key,'(',1)=any(array['public.release_production_feedback_reconciliation','public.approve_production_filing','public.append_production_filing_event','public.begin_production_filing','public.claim_production_feedback_reconciliation','public.record_production_feedback_artifact','legacy_rf1086.assert_fresh_owner_v1','legacy_rf1086.actor_v1','legacy_rf1086.can_read_company_v1','legacy_rf1086.can_read_submission_v1','legacy_rf1086.assert_submission_v1','legacy_rf1086.prepare_operation_v1','public.append_production_feedback_reconciliation','public.rf1086_confirmation_forsendelse_id']) order by key loop
  if pg_catalog.to_regprocedure(item.key) is null then raise exception 'rf1086_original_function_missing'; end if;
  -- Read the current definition: ALTER TABLE SET SCHEMA already moved return
  -- composite types with their physical tables; saved pre-expand return names
  -- would resolve to the new compatibility view type instead.
  statement:=pg_catalog.pg_get_functiondef(pg_catalog.to_regprocedure(item.key));
  foreach n in array array['filing_approval_snapshots','production_filing_submissions','production_filing_events','production_feedback_artifacts'] loop
   statement:=pg_catalog.replace(statement,'public.'||n,'shareholder_register_filing.'||n);
  end loop;
  execute statement;
  restored:=restored+1;
 end loop;
 if restored<>14 then raise exception 'rf1086_original_function_inventory_incomplete'; end if;
end; $rf151_rebind_legacy_physical_journal$;

create function shareholder_register_filing.verified_actor_v1() returns uuid
language plpgsql stable security definer set search_path='' as $function$
declare a uuid:=nullif(pg_catalog.current_setting('talli.verified_actor_id',true),'')::uuid;
  claims jsonb:=nullif(pg_catalog.current_setting('talli.verified_actor_claims',true),'')::jsonb;
begin
  if a is null or claims->>'sub' is distinct from a::text
    or claims->>'role' is distinct from 'authenticated'
    or public.company_access_auth_uid_v1() is distinct from a
  then return null; end if;
  return a;
end; $function$;
create function shareholder_register_filing.phase_v1() returns text
language sql stable security definer set search_path='' as $function$
 select phase from shareholder_register_filing.migration_state where singleton;
$function$;
create function shareholder_register_filing.is_rf_label_v1(label text) returns boolean
language sql immutable security invoker set search_path='' as $function$
 select coalesce(label in ('aksjonærregisteroppgaven','aksjonaerregisteroppgaven'),false);
$function$;
create function shareholder_register_filing.classify_legacy_row_v1(family text,row_data jsonb) returns text
language plpgsql stable security definer set search_path='' as $function$
declare p jsonb; s jsonb; candidate boolean:=false;
begin
  if family in ('opening_balance_setups','opening_shareholders') then candidate:=true;
  elsif family in ('filing_previews','filing_submissions','filing_overrides') then
    candidate:=shareholder_register_filing.is_rf_label_v1(row_data->>'filing');
  elsif family in ('authority_permissions','authority_test_runs') then
    candidate:=row_data->>'obligation'='aksjonaerregisteroppgaven';
  elsif family='filing_review_comments' then candidate:=row_data->>'target'='rf1086_preview';
  else raise exception 'rf1086_unknown_migration_family'; end if;
  if family in ('filing_submissions','filing_overrides','filing_review_comments') and row_data->>'preview_id' is not null then
    select pg_catalog.to_jsonb(v) into p from public.filing_previews v where v.id=(row_data->>'preview_id')::uuid;
    if p is not null and shareholder_register_filing.is_rf_label_v1(p->>'filing') then
      if shareholder_register_filing.classify_legacy_row_v1('filing_previews',p)<>'rf' then return 'quarantine'; end if;
      if (not candidate) or p->>'company_id' is distinct from row_data->>'company_id'
        or (row_data ? 'income_year' and p->>'income_year' is distinct from row_data->>'income_year')
        or (row_data ? 'filing' and p->>'filing' is distinct from row_data->>'filing')
      then return 'quarantine'; end if;
      candidate:=true;
    elsif candidate then return 'quarantine'; end if;
  end if;
  if candidate and family in ('opening_shareholders','filing_previews','filing_submissions') and row_data->>'setup_id' is not null then
    if shareholder_register_filing.phase_v1()='contracted' then
      select pg_catalog.to_jsonb(v) into s from shareholder_register_filing.opening_balance_setups v where v.id=(row_data->>'setup_id')::uuid;
    else
      select pg_catalog.to_jsonb(v) into s from public.opening_balance_setups v where v.id=(row_data->>'setup_id')::uuid;
    end if;
    if s is null or s->>'company_id' is distinct from row_data->>'company_id'
      or (row_data ? 'income_year' and s->>'income_year' is distinct from row_data->>'income_year')
    then return 'quarantine'; end if;
  end if;
  if candidate and family='filing_submissions' and row_data->>'authority_test_run_id' is not null then
    select pg_catalog.to_jsonb(v) into p from public.authority_test_runs v where v.id=(row_data->>'authority_test_run_id')::uuid;
    if p is null or p->>'company_id' is distinct from row_data->>'company_id' or p->>'obligation'<>'aksjonaerregisteroppgaven'
    then return 'quarantine'; end if;
  end if;
  return case when candidate then 'rf' else 'sibling' end;
end; $function$;

-- Exact original bank input is Ledger-owned and never reconstructed from postings.
create temporary table rf151_schema_grants on commit drop as
select not pg_catalog.has_schema_privilege('ledger_store_owner','ledger','CREATE') as ledger_create,
 not pg_catalog.has_schema_privilege(current_user,'backend_system','CREATE') as backend_create,
 not pg_catalog.has_schema_privilege('company_access_executor','public','CREATE') as company_access_create,
 not pg_catalog.has_schema_privilege('ledger_workflow_store_owner','backend_system','CREATE') as workflow_create;
grant create on schema ledger to ledger_store_owner;
grant create on schema backend_system to ledger_workflow_store_owner;
do $grant_backend$ begin execute pg_catalog.format('grant create on schema backend_system to %I',current_user); end; $grant_backend$;
create table ledger.opening_bank_inputs(
 snapshot_id uuid primary key, company_id uuid not null references public.companies(id) on delete cascade,
 income_year integer not null check(income_year between 2000 and 2100),
 bank_balance_nok numeric not null check(bank_balance_nok>=0),
 recorded_by uuid not null references auth.users(id) on delete restrict,
 recorded_at timestamptz not null,
 unique(company_id,income_year), unique(snapshot_id,company_id,income_year)
);
alter table ledger.opening_bank_inputs owner to ledger_store_owner;
set local role ledger_store_owner;
alter table ledger.opening_bank_inputs enable row level security;
alter table ledger.opening_bank_inputs force row level security;
revoke all on ledger.opening_bank_inputs from public,anon,authenticated,service_role;
create policy opening_bank_input_owner_write on ledger.opening_bank_inputs for insert to ledger_store_owner
with check(recorded_by=public.company_access_auth_uid_v1() and public.company_access_is_accepted_owner_v1(company_id));
create policy opening_bank_input_member_read on ledger.opening_bank_inputs for select to ledger_store_owner
using(public.company_access_is_accepted_member_v1(company_id));
reset role;

do $bank_backfill$ begin
 execute pg_catalog.format('grant insert on ledger.opening_bank_inputs to %I',current_user);
 execute pg_catalog.format('create policy rf151_bank_backfill on ledger.opening_bank_inputs for insert to %I with check(true)',current_user);
 insert into ledger.opening_bank_inputs(snapshot_id,company_id,income_year,bank_balance_nok,recorded_by,recorded_at)
 select id,company_id,income_year,bank_balance,created_by,created_at from public.opening_balance_setups;
 drop policy rf151_bank_backfill on ledger.opening_bank_inputs;
 execute pg_catalog.format('revoke insert on ledger.opening_bank_inputs from %I',current_user);
end; $bank_backfill$;

insert into shareholder_register_filing.opening_balance_setups(id,company_id,income_year,share_capital,share_count,nominal_value,locked_at,created_by,created_at)
select s.id,s.company_id,s.income_year,s.share_capital,s.share_count,s.nominal_value,s.locked_at,s.created_by,s.created_at from public.opening_balance_setups s
where shareholder_register_filing.classify_legacy_row_v1('opening_balance_setups',pg_catalog.to_jsonb(s))='rf';
insert into shareholder_register_filing.migration_quarantine(family,record_id,company_id,income_year,reason,original_row)
select 'opening_balance_setups',s.id,(pg_catalog.to_jsonb(s)->>'company_id')::uuid,(pg_catalog.to_jsonb(s)->>'income_year')::integer,
 'conflicting_rf_provenance',pg_catalog.to_jsonb(s) from public.opening_balance_setups s
where shareholder_register_filing.classify_legacy_row_v1('opening_balance_setups',pg_catalog.to_jsonb(s))='quarantine';

insert into shareholder_register_filing.opening_shareholders(id,setup_id,company_id,name,shareholder_kind,national_id,org_number,share_count,created_by,created_at)
select s.id,s.setup_id,s.company_id,s.name,s.shareholder_kind,s.national_id,s.org_number,s.share_count,s.created_by,s.created_at from public.opening_shareholders s
where shareholder_register_filing.classify_legacy_row_v1('opening_shareholders',pg_catalog.to_jsonb(s))='rf';
insert into shareholder_register_filing.migration_quarantine(family,record_id,company_id,income_year,reason,original_row)
select 'opening_shareholders',s.id,(pg_catalog.to_jsonb(s)->>'company_id')::uuid,(pg_catalog.to_jsonb(s)->>'income_year')::integer,
 'conflicting_rf_provenance',pg_catalog.to_jsonb(s) from public.opening_shareholders s
where shareholder_register_filing.classify_legacy_row_v1('opening_shareholders',pg_catalog.to_jsonb(s))='quarantine';

insert into shareholder_register_filing.filing_previews(id,company_id,setup_id,income_year,filing,status,issues,preview,hovedskjema_xml,underskjema_xml,source,created_by,created_at)
select s.id,s.company_id,s.setup_id,s.income_year,s.filing,s.status,s.issues,s.preview,s.hovedskjema_xml,s.underskjema_xml,s.source,s.created_by,s.created_at from public.filing_previews s
where shareholder_register_filing.classify_legacy_row_v1('filing_previews',pg_catalog.to_jsonb(s))='rf';
insert into shareholder_register_filing.migration_quarantine(family,record_id,company_id,income_year,reason,original_row)
select 'filing_previews',s.id,(pg_catalog.to_jsonb(s)->>'company_id')::uuid,(pg_catalog.to_jsonb(s)->>'income_year')::integer,
 'conflicting_rf_provenance',pg_catalog.to_jsonb(s) from public.filing_previews s
where shareholder_register_filing.classify_legacy_row_v1('filing_previews',pg_catalog.to_jsonb(s))='quarantine';

insert into shareholder_register_filing.filing_submissions(id,preview_id,company_id,setup_id,income_year,filing,mode,adapter_mode,payload_hash,idempotency_key,status,authority_confirmed_by,authority_confirmed_at,preview_confirmed_by,preview_confirmed_at,calls,receipt_id,feedback_document_ids,feedback_items,receipt_metadata,submitted_payload_ref,submitted_payload,failure_code,failure_message,created_by,submitted_by,created_at,updated_at,authority_test_run_id)
select s.id,s.preview_id,s.company_id,s.setup_id,s.income_year,s.filing,s.mode,s.adapter_mode,s.payload_hash,s.idempotency_key,s.status,s.authority_confirmed_by,s.authority_confirmed_at,s.preview_confirmed_by,s.preview_confirmed_at,s.calls,s.receipt_id,s.feedback_document_ids,s.feedback_items,s.receipt_metadata,s.submitted_payload_ref,s.submitted_payload,s.failure_code,s.failure_message,s.created_by,s.submitted_by,s.created_at,s.updated_at,s.authority_test_run_id from public.filing_submissions s
where shareholder_register_filing.classify_legacy_row_v1('filing_submissions',pg_catalog.to_jsonb(s))='rf';
insert into shareholder_register_filing.migration_quarantine(family,record_id,company_id,income_year,reason,original_row)
select 'filing_submissions',s.id,(pg_catalog.to_jsonb(s)->>'company_id')::uuid,(pg_catalog.to_jsonb(s)->>'income_year')::integer,
 'conflicting_rf_provenance',pg_catalog.to_jsonb(s) from public.filing_submissions s
where shareholder_register_filing.classify_legacy_row_v1('filing_submissions',pg_catalog.to_jsonb(s))='quarantine';

insert into shareholder_register_filing.filing_overrides(id,preview_id,company_id,income_year,filing,field_target,old_value,new_value,reason,risk_level,owner_confirmed_by,owner_confirmed_at,created_by,created_at)
select s.id,s.preview_id,s.company_id,s.income_year,s.filing,s.field_target,s.old_value,s.new_value,s.reason,s.risk_level,s.owner_confirmed_by,s.owner_confirmed_at,s.created_by,s.created_at from public.filing_overrides s
where shareholder_register_filing.classify_legacy_row_v1('filing_overrides',pg_catalog.to_jsonb(s))='rf';
insert into shareholder_register_filing.migration_quarantine(family,record_id,company_id,income_year,reason,original_row)
select 'filing_overrides',s.id,(pg_catalog.to_jsonb(s)->>'company_id')::uuid,(pg_catalog.to_jsonb(s)->>'income_year')::integer,
 'conflicting_rf_provenance',pg_catalog.to_jsonb(s) from public.filing_overrides s
where shareholder_register_filing.classify_legacy_row_v1('filing_overrides',pg_catalog.to_jsonb(s))='quarantine';

insert into shareholder_register_filing.filing_review_comments(id,preview_id,company_id,target,severity,body,created_by,acknowledged_by,acknowledged_at,created_at)
select s.id,s.preview_id,s.company_id,s.target,s.severity,s.body,s.created_by,s.acknowledged_by,s.acknowledged_at,s.created_at from public.filing_review_comments s
where shareholder_register_filing.classify_legacy_row_v1('filing_review_comments',pg_catalog.to_jsonb(s))='rf';
insert into shareholder_register_filing.migration_quarantine(family,record_id,company_id,income_year,reason,original_row)
select 'filing_review_comments',s.id,(pg_catalog.to_jsonb(s)->>'company_id')::uuid,(pg_catalog.to_jsonb(s)->>'income_year')::integer,
 'conflicting_rf_provenance',pg_catalog.to_jsonb(s) from public.filing_review_comments s
where shareholder_register_filing.classify_legacy_row_v1('filing_review_comments',pg_catalog.to_jsonb(s))='quarantine';

insert into shareholder_register_filing.authority_permissions(id,company_id,obligation,submitter_user_id,confirmed_by,confirmed_at,production_enabled,updated_at)
select s.id,s.company_id,s.obligation,s.submitter_user_id,s.confirmed_by,s.confirmed_at,s.production_enabled,s.updated_at from public.authority_permissions s
where shareholder_register_filing.classify_legacy_row_v1('authority_permissions',pg_catalog.to_jsonb(s))='rf';
insert into shareholder_register_filing.migration_quarantine(family,record_id,company_id,income_year,reason,original_row)
select 'authority_permissions',s.id,(pg_catalog.to_jsonb(s)->>'company_id')::uuid,(pg_catalog.to_jsonb(s)->>'income_year')::integer,
 'conflicting_rf_provenance',pg_catalog.to_jsonb(s) from public.authority_permissions s
where shareholder_register_filing.classify_legacy_row_v1('authority_permissions',pg_catalog.to_jsonb(s))='quarantine';

insert into shareholder_register_filing.authority_test_runs(id,company_id,obligation,environment,status,test_reference,feedback_summary,receipt_reference,archive_reference,evidence_url,payload_hash,recorded_by,recorded_at)
select s.id,s.company_id,s.obligation,s.environment,s.status,s.test_reference,s.feedback_summary,s.receipt_reference,s.archive_reference,s.evidence_url,s.payload_hash,s.recorded_by,s.recorded_at from public.authority_test_runs s
where shareholder_register_filing.classify_legacy_row_v1('authority_test_runs',pg_catalog.to_jsonb(s))='rf';
insert into shareholder_register_filing.migration_quarantine(family,record_id,company_id,income_year,reason,original_row)
select 'authority_test_runs',s.id,(pg_catalog.to_jsonb(s)->>'company_id')::uuid,(pg_catalog.to_jsonb(s)->>'income_year')::integer,
 'conflicting_rf_provenance',pg_catalog.to_jsonb(s) from public.authority_test_runs s
where shareholder_register_filing.classify_legacy_row_v1('authority_test_runs',pg_catalog.to_jsonb(s))='quarantine';

do $reconcile$ declare a jsonb; b jsonb; begin
 select pg_catalog.jsonb_build_object('count',count(*),'digest',pg_catalog.encode(extensions.digest(coalesce(pg_catalog.string_agg(item::text,E'\n' order by item->>'id'),''),'sha256'),'hex')) into a from (select original_row - 'bank_balance' item from rf151_original_rows r where family='opening_balance_setups' and shareholder_register_filing.classify_legacy_row_v1('opening_balance_setups',r.original_row)='rf') src;
 select pg_catalog.jsonb_build_object('count',count(*),'digest',pg_catalog.encode(extensions.digest(coalesce(pg_catalog.string_agg(pg_catalog.to_jsonb(t)::text,E'\n' order by id),''),'sha256'),'hex')) into b from shareholder_register_filing.opening_balance_setups t;
 if a is distinct from b then raise exception 'rf1086_migration_reconciliation_failed'; end if;
 update shareholder_register_filing.migration_state set reconciliation=reconciliation||pg_catalog.jsonb_build_object('opening_balance_setups',a);
end; $reconcile$;

do $reconcile$ declare a jsonb; b jsonb; begin
 select pg_catalog.jsonb_build_object('count',count(*),'digest',pg_catalog.encode(extensions.digest(coalesce(pg_catalog.string_agg(item::text,E'\n' order by item->>'id'),''),'sha256'),'hex')) into a from (select original_row item from rf151_original_rows r where family='opening_shareholders' and shareholder_register_filing.classify_legacy_row_v1('opening_shareholders',r.original_row)='rf') src;
 select pg_catalog.jsonb_build_object('count',count(*),'digest',pg_catalog.encode(extensions.digest(coalesce(pg_catalog.string_agg(pg_catalog.to_jsonb(t)::text,E'\n' order by id),''),'sha256'),'hex')) into b from shareholder_register_filing.opening_shareholders t;
 if a is distinct from b then raise exception 'rf1086_migration_reconciliation_failed'; end if;
 update shareholder_register_filing.migration_state set reconciliation=reconciliation||pg_catalog.jsonb_build_object('opening_shareholders',a);
end; $reconcile$;

do $reconcile$ declare a jsonb; b jsonb; begin
 select pg_catalog.jsonb_build_object('count',count(*),'digest',pg_catalog.encode(extensions.digest(coalesce(pg_catalog.string_agg(item::text,E'\n' order by item->>'id'),''),'sha256'),'hex')) into a from (select original_row item from rf151_original_rows r where family='filing_previews' and shareholder_register_filing.classify_legacy_row_v1('filing_previews',r.original_row)='rf') src;
 select pg_catalog.jsonb_build_object('count',count(*),'digest',pg_catalog.encode(extensions.digest(coalesce(pg_catalog.string_agg(pg_catalog.to_jsonb(t)::text,E'\n' order by id),''),'sha256'),'hex')) into b from shareholder_register_filing.filing_previews t;
 if a is distinct from b then raise exception 'rf1086_migration_reconciliation_failed'; end if;
 update shareholder_register_filing.migration_state set reconciliation=reconciliation||pg_catalog.jsonb_build_object('filing_previews',a);
end; $reconcile$;

do $reconcile$ declare a jsonb; b jsonb; begin
 select pg_catalog.jsonb_build_object('count',count(*),'digest',pg_catalog.encode(extensions.digest(coalesce(pg_catalog.string_agg(item::text,E'\n' order by item->>'id'),''),'sha256'),'hex')) into a from (select original_row item from rf151_original_rows r where family='filing_submissions' and shareholder_register_filing.classify_legacy_row_v1('filing_submissions',r.original_row)='rf') src;
 select pg_catalog.jsonb_build_object('count',count(*),'digest',pg_catalog.encode(extensions.digest(coalesce(pg_catalog.string_agg(pg_catalog.to_jsonb(t)::text,E'\n' order by id),''),'sha256'),'hex')) into b from shareholder_register_filing.filing_submissions t;
 if a is distinct from b then raise exception 'rf1086_migration_reconciliation_failed'; end if;
 update shareholder_register_filing.migration_state set reconciliation=reconciliation||pg_catalog.jsonb_build_object('filing_submissions',a);
end; $reconcile$;

do $reconcile$ declare a jsonb; b jsonb; begin
 select pg_catalog.jsonb_build_object('count',count(*),'digest',pg_catalog.encode(extensions.digest(coalesce(pg_catalog.string_agg(item::text,E'\n' order by item->>'id'),''),'sha256'),'hex')) into a from (select original_row item from rf151_original_rows r where family='filing_overrides' and shareholder_register_filing.classify_legacy_row_v1('filing_overrides',r.original_row)='rf') src;
 select pg_catalog.jsonb_build_object('count',count(*),'digest',pg_catalog.encode(extensions.digest(coalesce(pg_catalog.string_agg(pg_catalog.to_jsonb(t)::text,E'\n' order by id),''),'sha256'),'hex')) into b from shareholder_register_filing.filing_overrides t;
 if a is distinct from b then raise exception 'rf1086_migration_reconciliation_failed'; end if;
 update shareholder_register_filing.migration_state set reconciliation=reconciliation||pg_catalog.jsonb_build_object('filing_overrides',a);
end; $reconcile$;

do $reconcile$ declare a jsonb; b jsonb; begin
 select pg_catalog.jsonb_build_object('count',count(*),'digest',pg_catalog.encode(extensions.digest(coalesce(pg_catalog.string_agg(item::text,E'\n' order by item->>'id'),''),'sha256'),'hex')) into a from (select original_row item from rf151_original_rows r where family='filing_review_comments' and shareholder_register_filing.classify_legacy_row_v1('filing_review_comments',r.original_row)='rf') src;
 select pg_catalog.jsonb_build_object('count',count(*),'digest',pg_catalog.encode(extensions.digest(coalesce(pg_catalog.string_agg(pg_catalog.to_jsonb(t)::text,E'\n' order by id),''),'sha256'),'hex')) into b from shareholder_register_filing.filing_review_comments t;
 if a is distinct from b then raise exception 'rf1086_migration_reconciliation_failed'; end if;
 update shareholder_register_filing.migration_state set reconciliation=reconciliation||pg_catalog.jsonb_build_object('filing_review_comments',a);
end; $reconcile$;

do $reconcile$ declare a jsonb; b jsonb; begin
 select pg_catalog.jsonb_build_object('count',count(*),'digest',pg_catalog.encode(extensions.digest(coalesce(pg_catalog.string_agg(item::text,E'\n' order by item->>'id'),''),'sha256'),'hex')) into a from (select original_row item from rf151_original_rows r where family='authority_permissions' and shareholder_register_filing.classify_legacy_row_v1('authority_permissions',r.original_row)='rf') src;
 select pg_catalog.jsonb_build_object('count',count(*),'digest',pg_catalog.encode(extensions.digest(coalesce(pg_catalog.string_agg(pg_catalog.to_jsonb(t)::text,E'\n' order by id),''),'sha256'),'hex')) into b from shareholder_register_filing.authority_permissions t;
 if a is distinct from b then raise exception 'rf1086_migration_reconciliation_failed'; end if;
 update shareholder_register_filing.migration_state set reconciliation=reconciliation||pg_catalog.jsonb_build_object('authority_permissions',a);
end; $reconcile$;

do $reconcile$ declare a jsonb; b jsonb; begin
 select pg_catalog.jsonb_build_object('count',count(*),'digest',pg_catalog.encode(extensions.digest(coalesce(pg_catalog.string_agg(item::text,E'\n' order by item->>'id'),''),'sha256'),'hex')) into a from (select original_row item from rf151_original_rows r where family='authority_test_runs' and shareholder_register_filing.classify_legacy_row_v1('authority_test_runs',r.original_row)='rf') src;
 select pg_catalog.jsonb_build_object('count',count(*),'digest',pg_catalog.encode(extensions.digest(coalesce(pg_catalog.string_agg(pg_catalog.to_jsonb(t)::text,E'\n' order by id),''),'sha256'),'hex')) into b from shareholder_register_filing.authority_test_runs t;
 if a is distinct from b then raise exception 'rf1086_migration_reconciliation_failed'; end if;
 update shareholder_register_filing.migration_state set reconciliation=reconciliation||pg_catalog.jsonb_build_object('authority_test_runs',a);
end; $reconcile$;

do $reconcile$ declare a jsonb; b jsonb; begin
 select pg_catalog.jsonb_build_object('count',count(*),'digest',pg_catalog.encode(extensions.digest(coalesce(pg_catalog.string_agg(item::text,E'\n' order by item->>'id'),''),'sha256'),'hex')) into a from (select original_row item from rf151_original_rows r where family='filing_approval_snapshots') src;
 select pg_catalog.jsonb_build_object('count',count(*),'digest',pg_catalog.encode(extensions.digest(coalesce(pg_catalog.string_agg(pg_catalog.to_jsonb(t)::text,E'\n' order by id),''),'sha256'),'hex')) into b from shareholder_register_filing.filing_approval_snapshots t;
 if a is distinct from b then raise exception 'rf1086_migration_reconciliation_failed'; end if;
 update shareholder_register_filing.migration_state set reconciliation=reconciliation||pg_catalog.jsonb_build_object('filing_approval_snapshots',a);
end; $reconcile$;

do $reconcile$ declare a jsonb; b jsonb; begin
 select pg_catalog.jsonb_build_object('count',count(*),'digest',pg_catalog.encode(extensions.digest(coalesce(pg_catalog.string_agg(item::text,E'\n' order by item->>'id'),''),'sha256'),'hex')) into a from (select original_row item from rf151_original_rows r where family='production_filing_submissions') src;
 select pg_catalog.jsonb_build_object('count',count(*),'digest',pg_catalog.encode(extensions.digest(coalesce(pg_catalog.string_agg(pg_catalog.to_jsonb(t)::text,E'\n' order by id),''),'sha256'),'hex')) into b from shareholder_register_filing.production_filing_submissions t;
 if a is distinct from b then raise exception 'rf1086_migration_reconciliation_failed'; end if;
 update shareholder_register_filing.migration_state set reconciliation=reconciliation||pg_catalog.jsonb_build_object('production_filing_submissions',a);
end; $reconcile$;

do $reconcile$ declare a jsonb; b jsonb; begin
 select pg_catalog.jsonb_build_object('count',count(*),'digest',pg_catalog.encode(extensions.digest(coalesce(pg_catalog.string_agg(item::text,E'\n' order by item->>'id'),''),'sha256'),'hex')) into a from (select original_row item from rf151_original_rows r where family='production_filing_events') src;
 select pg_catalog.jsonb_build_object('count',count(*),'digest',pg_catalog.encode(extensions.digest(coalesce(pg_catalog.string_agg(pg_catalog.to_jsonb(t)::text,E'\n' order by id),''),'sha256'),'hex')) into b from shareholder_register_filing.production_filing_events t;
 if a is distinct from b then raise exception 'rf1086_migration_reconciliation_failed'; end if;
 update shareholder_register_filing.migration_state set reconciliation=reconciliation||pg_catalog.jsonb_build_object('production_filing_events',a);
end; $reconcile$;

do $reconcile$ declare a jsonb; b jsonb; begin
 select pg_catalog.jsonb_build_object('count',count(*),'digest',pg_catalog.encode(extensions.digest(coalesce(pg_catalog.string_agg(item::text,E'\n' order by item->>'id'),''),'sha256'),'hex')) into a from (select original_row item from rf151_original_rows r where family='production_feedback_artifacts') src;
 select pg_catalog.jsonb_build_object('count',count(*),'digest',pg_catalog.encode(extensions.digest(coalesce(pg_catalog.string_agg(pg_catalog.to_jsonb(t)::text,E'\n' order by id),''),'sha256'),'hex')) into b from shareholder_register_filing.production_feedback_artifacts t;
 if a is distinct from b then raise exception 'rf1086_migration_reconciliation_failed'; end if;
 update shareholder_register_filing.migration_state set reconciliation=reconciliation||pg_catalog.jsonb_build_object('production_feedback_artifacts',a);
end; $reconcile$;

alter table shareholder_register_filing.authority_permissions add constraint authority_permissions_company_id_fkey FOREIGN KEY (company_id) REFERENCES public.companies(id) ON DELETE CASCADE;

alter table shareholder_register_filing.authority_permissions add constraint authority_permissions_confirmed_by_fkey FOREIGN KEY (confirmed_by) REFERENCES auth.users(id) ON DELETE RESTRICT;

alter table shareholder_register_filing.authority_permissions add constraint authority_permissions_submitter_user_id_fkey FOREIGN KEY (submitter_user_id) REFERENCES auth.users(id) ON DELETE RESTRICT;

alter table shareholder_register_filing.authority_test_runs add constraint authority_test_runs_company_id_fkey FOREIGN KEY (company_id) REFERENCES public.companies(id) ON DELETE CASCADE;

alter table shareholder_register_filing.authority_test_runs add constraint authority_test_runs_recorded_by_fkey FOREIGN KEY (recorded_by) REFERENCES auth.users(id) ON DELETE RESTRICT;

alter table shareholder_register_filing.filing_overrides add constraint filing_overrides_company_id_fkey FOREIGN KEY (company_id) REFERENCES public.companies(id) ON DELETE CASCADE;

alter table shareholder_register_filing.filing_overrides add constraint filing_overrides_created_by_fkey FOREIGN KEY (created_by) REFERENCES auth.users(id) ON DELETE RESTRICT;

alter table shareholder_register_filing.filing_overrides add constraint filing_overrides_owner_confirmed_by_fkey FOREIGN KEY (owner_confirmed_by) REFERENCES auth.users(id) ON DELETE RESTRICT;

alter table shareholder_register_filing.filing_overrides add constraint filing_overrides_preview_id_fkey FOREIGN KEY (preview_id) REFERENCES shareholder_register_filing.filing_previews(id) ON DELETE CASCADE;

alter table shareholder_register_filing.filing_previews add constraint filing_previews_company_id_fkey FOREIGN KEY (company_id) REFERENCES public.companies(id) ON DELETE CASCADE;

alter table shareholder_register_filing.filing_previews add constraint filing_previews_created_by_fkey FOREIGN KEY (created_by) REFERENCES auth.users(id) ON DELETE RESTRICT;

alter table shareholder_register_filing.filing_previews add constraint filing_previews_setup_id_fkey FOREIGN KEY (setup_id) REFERENCES shareholder_register_filing.opening_balance_setups(id) ON DELETE RESTRICT;

alter table shareholder_register_filing.filing_review_comments add constraint filing_review_comments_acknowledged_by_fkey FOREIGN KEY (acknowledged_by) REFERENCES auth.users(id) ON DELETE RESTRICT;

alter table shareholder_register_filing.filing_review_comments add constraint filing_review_comments_company_id_fkey FOREIGN KEY (company_id) REFERENCES public.companies(id) ON DELETE CASCADE;

alter table shareholder_register_filing.filing_review_comments add constraint filing_review_comments_created_by_fkey FOREIGN KEY (created_by) REFERENCES auth.users(id) ON DELETE RESTRICT;

alter table shareholder_register_filing.filing_review_comments add constraint filing_review_comments_preview_id_fkey FOREIGN KEY (preview_id) REFERENCES shareholder_register_filing.filing_previews(id) ON DELETE CASCADE;

alter table shareholder_register_filing.filing_submissions add constraint filing_submissions_authority_confirmed_by_fkey FOREIGN KEY (authority_confirmed_by) REFERENCES auth.users(id) ON DELETE RESTRICT;

alter table shareholder_register_filing.filing_submissions add constraint filing_submissions_authority_test_run_id_fkey FOREIGN KEY (authority_test_run_id) REFERENCES shareholder_register_filing.authority_test_runs(id) ON DELETE RESTRICT;

alter table shareholder_register_filing.filing_submissions add constraint filing_submissions_company_id_fkey FOREIGN KEY (company_id) REFERENCES public.companies(id) ON DELETE CASCADE;

alter table shareholder_register_filing.filing_submissions add constraint filing_submissions_created_by_fkey FOREIGN KEY (created_by) REFERENCES auth.users(id) ON DELETE RESTRICT;

alter table shareholder_register_filing.filing_submissions add constraint filing_submissions_preview_confirmed_by_fkey FOREIGN KEY (preview_confirmed_by) REFERENCES auth.users(id) ON DELETE RESTRICT;

alter table shareholder_register_filing.filing_submissions add constraint filing_submissions_preview_id_fkey FOREIGN KEY (preview_id) REFERENCES shareholder_register_filing.filing_previews(id) ON DELETE CASCADE;

alter table shareholder_register_filing.filing_submissions add constraint filing_submissions_setup_id_fkey FOREIGN KEY (setup_id) REFERENCES shareholder_register_filing.opening_balance_setups(id) ON DELETE RESTRICT;

alter table shareholder_register_filing.filing_submissions add constraint filing_submissions_submitted_by_fkey FOREIGN KEY (submitted_by) REFERENCES auth.users(id) ON DELETE RESTRICT;

alter table shareholder_register_filing.opening_balance_setups add constraint opening_balance_setups_company_id_fkey FOREIGN KEY (company_id) REFERENCES public.companies(id) ON DELETE CASCADE;

alter table shareholder_register_filing.opening_balance_setups add constraint opening_balance_setups_created_by_fkey FOREIGN KEY (created_by) REFERENCES auth.users(id) ON DELETE RESTRICT;

alter table shareholder_register_filing.opening_shareholders add constraint opening_shareholders_company_id_fkey FOREIGN KEY (company_id) REFERENCES public.companies(id) ON DELETE CASCADE;

alter table shareholder_register_filing.opening_shareholders add constraint opening_shareholders_created_by_fkey FOREIGN KEY (created_by) REFERENCES auth.users(id) ON DELETE RESTRICT;

alter table shareholder_register_filing.opening_shareholders add constraint opening_shareholders_setup_id_fkey FOREIGN KEY (setup_id) REFERENCES shareholder_register_filing.opening_balance_setups(id) ON DELETE CASCADE;

alter table shareholder_register_filing.filing_previews add constraint rf151_owned_label check(filing in ('aksjonærregisteroppgaven','aksjonaerregisteroppgaven'));

alter table shareholder_register_filing.filing_submissions add constraint rf151_owned_label check(filing in ('aksjonærregisteroppgaven','aksjonaerregisteroppgaven'));

alter table shareholder_register_filing.filing_overrides add constraint rf151_owned_label check(filing in ('aksjonærregisteroppgaven','aksjonaerregisteroppgaven'));

alter table shareholder_register_filing.authority_permissions add constraint rf151_owned_obligation check(obligation='aksjonaerregisteroppgaven');

alter table shareholder_register_filing.authority_test_runs add constraint rf151_owned_obligation check(obligation='aksjonaerregisteroppgaven');

alter table shareholder_register_filing.filing_review_comments add constraint rf151_owned_target check(target='rf1086_preview');

alter table shareholder_register_filing.opening_balance_setups add constraint rf151_opening_identity unique(id,company_id,income_year);

alter table shareholder_register_filing.opening_balance_setups add constraint rf151_opening_company unique(id,company_id);

alter table shareholder_register_filing.filing_previews add constraint rf151_preview_identity unique(id,company_id,income_year);

alter table shareholder_register_filing.filing_previews add constraint rf151_preview_company unique(id,company_id);

alter table shareholder_register_filing.filing_previews add constraint rf151_preview_opening_binding foreign key(setup_id,company_id,income_year) references shareholder_register_filing.opening_balance_setups(id,company_id,income_year);

alter table shareholder_register_filing.opening_shareholders add constraint rf151_shareholder_opening_binding foreign key(setup_id,company_id) references shareholder_register_filing.opening_balance_setups(id,company_id);

alter table shareholder_register_filing.filing_submissions add constraint rf151_preview_scope_binding foreign key(preview_id,company_id,income_year) references shareholder_register_filing.filing_previews(id,company_id,income_year);

alter table shareholder_register_filing.filing_overrides add constraint rf151_preview_scope_binding foreign key(preview_id,company_id,income_year) references shareholder_register_filing.filing_previews(id,company_id,income_year);

alter table shareholder_register_filing.filing_review_comments add constraint rf151_review_preview_binding foreign key(preview_id,company_id) references shareholder_register_filing.filing_previews(id,company_id);

alter table shareholder_register_filing.opening_balance_setups enable row level security;

alter table shareholder_register_filing.opening_shareholders enable row level security;

alter table shareholder_register_filing.filing_previews enable row level security;

alter table shareholder_register_filing.filing_submissions enable row level security;

alter table shareholder_register_filing.filing_overrides enable row level security;

alter table shareholder_register_filing.filing_review_comments enable row level security;

alter table shareholder_register_filing.authority_permissions enable row level security;

alter table shareholder_register_filing.authority_test_runs enable row level security;

alter table shareholder_register_filing.filing_approval_snapshots enable row level security;

alter table shareholder_register_filing.production_filing_submissions enable row level security;

alter table shareholder_register_filing.production_filing_events enable row level security;

alter table shareholder_register_filing.production_feedback_artifacts enable row level security;

create temporary table rf151_scopes on commit drop as
 select distinct company_id,income_year from public.opening_balance_setups
 union select company_id,income_year from shareholder_register_filing.filing_previews
 union select company_id,income_year from shareholder_register_filing.production_filing_submissions;

insert into shareholder_register_filing.migration_inventory(company_id,income_year,family,row_count,row_digest,quarantined_count)
select s.company_id,s.income_year,'opening_balance_setups',count(t.item),
 pg_catalog.encode(extensions.digest(coalesce(pg_catalog.string_agg(t.item::text,E'\n' order by t.item->>'id'),''),'sha256'),'hex'),
 (select count(*) from shareholder_register_filing.migration_quarantine q where q.company_id=s.company_id and (q.income_year=s.income_year or q.income_year is null))
from rf151_scopes s left join lateral (select pg_catalog.to_jsonb(t) item from shareholder_register_filing.opening_balance_setups t where t.company_id=s.company_id and t.income_year=s.income_year) t on true group by s.company_id,s.income_year;

insert into shareholder_register_filing.migration_inventory(company_id,income_year,family,row_count,row_digest,quarantined_count)
select s.company_id,s.income_year,'opening_shareholders',count(t.item),
 pg_catalog.encode(extensions.digest(coalesce(pg_catalog.string_agg(t.item::text,E'\n' order by t.item->>'id'),''),'sha256'),'hex'),
 (select count(*) from shareholder_register_filing.migration_quarantine q where q.company_id=s.company_id and (q.income_year=s.income_year or q.income_year is null))
from rf151_scopes s left join lateral (select pg_catalog.to_jsonb(t) item from shareholder_register_filing.opening_shareholders t join shareholder_register_filing.opening_balance_setups o on o.id=t.setup_id where t.company_id=s.company_id and o.income_year=s.income_year) t on true group by s.company_id,s.income_year;

insert into shareholder_register_filing.migration_inventory(company_id,income_year,family,row_count,row_digest,quarantined_count)
select s.company_id,s.income_year,'filing_previews',count(t.item),
 pg_catalog.encode(extensions.digest(coalesce(pg_catalog.string_agg(t.item::text,E'\n' order by t.item->>'id'),''),'sha256'),'hex'),
 (select count(*) from shareholder_register_filing.migration_quarantine q where q.company_id=s.company_id and (q.income_year=s.income_year or q.income_year is null))
from rf151_scopes s left join lateral (select pg_catalog.to_jsonb(t) item from shareholder_register_filing.filing_previews t where t.company_id=s.company_id and t.income_year=s.income_year) t on true group by s.company_id,s.income_year;

insert into shareholder_register_filing.migration_inventory(company_id,income_year,family,row_count,row_digest,quarantined_count)
select s.company_id,s.income_year,'filing_submissions',count(t.item),
 pg_catalog.encode(extensions.digest(coalesce(pg_catalog.string_agg(t.item::text,E'\n' order by t.item->>'id'),''),'sha256'),'hex'),
 (select count(*) from shareholder_register_filing.migration_quarantine q where q.company_id=s.company_id and (q.income_year=s.income_year or q.income_year is null))
from rf151_scopes s left join lateral (select pg_catalog.to_jsonb(t) item from shareholder_register_filing.filing_submissions t where t.company_id=s.company_id and t.income_year=s.income_year) t on true group by s.company_id,s.income_year;

insert into shareholder_register_filing.migration_inventory(company_id,income_year,family,row_count,row_digest,quarantined_count)
select s.company_id,s.income_year,'filing_overrides',count(t.item),
 pg_catalog.encode(extensions.digest(coalesce(pg_catalog.string_agg(t.item::text,E'\n' order by t.item->>'id'),''),'sha256'),'hex'),
 (select count(*) from shareholder_register_filing.migration_quarantine q where q.company_id=s.company_id and (q.income_year=s.income_year or q.income_year is null))
from rf151_scopes s left join lateral (select pg_catalog.to_jsonb(t) item from shareholder_register_filing.filing_overrides t where t.company_id=s.company_id and t.income_year=s.income_year) t on true group by s.company_id,s.income_year;

insert into shareholder_register_filing.migration_inventory(company_id,income_year,family,row_count,row_digest,quarantined_count)
select s.company_id,s.income_year,'filing_review_comments',count(t.item),
 pg_catalog.encode(extensions.digest(coalesce(pg_catalog.string_agg(t.item::text,E'\n' order by t.item->>'id'),''),'sha256'),'hex'),
 (select count(*) from shareholder_register_filing.migration_quarantine q where q.company_id=s.company_id and (q.income_year=s.income_year or q.income_year is null))
from rf151_scopes s left join lateral (select pg_catalog.to_jsonb(t) item from shareholder_register_filing.filing_review_comments t join shareholder_register_filing.filing_previews o on o.id=t.preview_id where t.company_id=s.company_id and o.income_year=s.income_year) t on true group by s.company_id,s.income_year;

insert into shareholder_register_filing.migration_inventory(company_id,income_year,family,row_count,row_digest,quarantined_count)
select s.company_id,s.income_year,'authority_permissions',count(t.item),
 pg_catalog.encode(extensions.digest(coalesce(pg_catalog.string_agg(t.item::text,E'\n' order by t.item->>'id'),''),'sha256'),'hex'),
 (select count(*) from shareholder_register_filing.migration_quarantine q where q.company_id=s.company_id and (q.income_year=s.income_year or q.income_year is null))
from rf151_scopes s left join lateral (select pg_catalog.to_jsonb(t) item from shareholder_register_filing.authority_permissions t where t.company_id=s.company_id) t on true group by s.company_id,s.income_year;

insert into shareholder_register_filing.migration_inventory(company_id,income_year,family,row_count,row_digest,quarantined_count)
select s.company_id,s.income_year,'authority_test_runs',count(t.item),
 pg_catalog.encode(extensions.digest(coalesce(pg_catalog.string_agg(t.item::text,E'\n' order by t.item->>'id'),''),'sha256'),'hex'),
 (select count(*) from shareholder_register_filing.migration_quarantine q where q.company_id=s.company_id and (q.income_year=s.income_year or q.income_year is null))
from rf151_scopes s left join lateral (select pg_catalog.to_jsonb(t) item from shareholder_register_filing.authority_test_runs t where t.company_id=s.company_id) t on true group by s.company_id,s.income_year;

insert into shareholder_register_filing.migration_inventory(company_id,income_year,family,row_count,row_digest,quarantined_count)
select s.company_id,s.income_year,'filing_approval_snapshots',count(t.item),
 pg_catalog.encode(extensions.digest(coalesce(pg_catalog.string_agg(t.item::text,E'\n' order by t.item->>'id'),''),'sha256'),'hex'),
 (select count(*) from shareholder_register_filing.migration_quarantine q where q.company_id=s.company_id and (q.income_year=s.income_year or q.income_year is null))
from rf151_scopes s left join lateral (select pg_catalog.to_jsonb(t) item from shareholder_register_filing.filing_approval_snapshots t where t.company_id=s.company_id and t.income_year=s.income_year) t on true group by s.company_id,s.income_year;

insert into shareholder_register_filing.migration_inventory(company_id,income_year,family,row_count,row_digest,quarantined_count)
select s.company_id,s.income_year,'production_filing_submissions',count(t.item),
 pg_catalog.encode(extensions.digest(coalesce(pg_catalog.string_agg(t.item::text,E'\n' order by t.item->>'id'),''),'sha256'),'hex'),
 (select count(*) from shareholder_register_filing.migration_quarantine q where q.company_id=s.company_id and (q.income_year=s.income_year or q.income_year is null))
from rf151_scopes s left join lateral (select pg_catalog.to_jsonb(t) item from shareholder_register_filing.production_filing_submissions t where t.company_id=s.company_id and t.income_year=s.income_year) t on true group by s.company_id,s.income_year;

insert into shareholder_register_filing.migration_inventory(company_id,income_year,family,row_count,row_digest,quarantined_count)
select s.company_id,s.income_year,'production_filing_events',count(t.item),
 pg_catalog.encode(extensions.digest(coalesce(pg_catalog.string_agg(t.item::text,E'\n' order by t.item->>'id'),''),'sha256'),'hex'),
 (select count(*) from shareholder_register_filing.migration_quarantine q where q.company_id=s.company_id and (q.income_year=s.income_year or q.income_year is null))
from rf151_scopes s left join lateral (select pg_catalog.to_jsonb(t) item from shareholder_register_filing.production_filing_events t join shareholder_register_filing.production_filing_submissions o on o.id=t.submission_id where o.company_id=s.company_id and o.income_year=s.income_year) t on true group by s.company_id,s.income_year;

insert into shareholder_register_filing.migration_inventory(company_id,income_year,family,row_count,row_digest,quarantined_count)
select s.company_id,s.income_year,'production_feedback_artifacts',count(t.item),
 pg_catalog.encode(extensions.digest(coalesce(pg_catalog.string_agg(t.item::text,E'\n' order by t.item->>'id'),''),'sha256'),'hex'),
 (select count(*) from shareholder_register_filing.migration_quarantine q where q.company_id=s.company_id and (q.income_year=s.income_year or q.income_year is null))
from rf151_scopes s left join lateral (select pg_catalog.to_jsonb(t) item from shareholder_register_filing.production_feedback_artifacts t join shareholder_register_filing.production_filing_submissions o on o.id=t.submission_id where t.company_id=s.company_id and o.income_year=s.income_year) t on true group by s.company_id,s.income_year;

alter table shareholder_register_filing.opening_balance_setups owner to shareholder_register_filing_store_owner;
alter table shareholder_register_filing.opening_balance_setups force row level security;
revoke all on shareholder_register_filing.opening_balance_setups from public,anon,authenticated,service_role;
grant select on shareholder_register_filing.opening_balance_setups to shareholder_register_filing_executor;
create policy rf151_member_read on shareholder_register_filing.opening_balance_setups for select to shareholder_register_filing_executor,shareholder_register_filing_store_owner
using(shareholder_register_filing.verified_actor_v1() is not null and public.company_access_is_accepted_member_v1(company_id));
create policy rf151_owner_write on shareholder_register_filing.opening_balance_setups for all to shareholder_register_filing_store_owner
using(shareholder_register_filing.verified_actor_v1() is not null and public.company_access_is_accepted_owner_v1(company_id))
with check(shareholder_register_filing.verified_actor_v1() is not null and public.company_access_is_accepted_owner_v1(company_id));

alter table shareholder_register_filing.opening_shareholders owner to shareholder_register_filing_store_owner;
alter table shareholder_register_filing.opening_shareholders force row level security;
revoke all on shareholder_register_filing.opening_shareholders from public,anon,authenticated,service_role;
grant select on shareholder_register_filing.opening_shareholders to shareholder_register_filing_executor;
create policy rf151_member_read on shareholder_register_filing.opening_shareholders for select to shareholder_register_filing_executor,shareholder_register_filing_store_owner
using(shareholder_register_filing.verified_actor_v1() is not null and public.company_access_is_accepted_member_v1(company_id));
create policy rf151_owner_write on shareholder_register_filing.opening_shareholders for all to shareholder_register_filing_store_owner
using(shareholder_register_filing.verified_actor_v1() is not null and public.company_access_is_accepted_owner_v1(company_id))
with check(shareholder_register_filing.verified_actor_v1() is not null and public.company_access_is_accepted_owner_v1(company_id));

alter table shareholder_register_filing.filing_previews owner to shareholder_register_filing_store_owner;
alter table shareholder_register_filing.filing_previews force row level security;
revoke all on shareholder_register_filing.filing_previews from public,anon,authenticated,service_role;
grant select on shareholder_register_filing.filing_previews to shareholder_register_filing_executor;
create policy rf151_member_read on shareholder_register_filing.filing_previews for select to shareholder_register_filing_executor,shareholder_register_filing_store_owner
using(shareholder_register_filing.verified_actor_v1() is not null and public.company_access_is_accepted_member_v1(company_id));
create policy rf151_owner_write on shareholder_register_filing.filing_previews for all to shareholder_register_filing_store_owner
using(shareholder_register_filing.verified_actor_v1() is not null and public.company_access_is_accepted_owner_v1(company_id))
with check(shareholder_register_filing.verified_actor_v1() is not null and public.company_access_is_accepted_owner_v1(company_id));

alter table shareholder_register_filing.filing_submissions owner to shareholder_register_filing_store_owner;
alter table shareholder_register_filing.filing_submissions force row level security;
revoke all on shareholder_register_filing.filing_submissions from public,anon,authenticated,service_role;
grant select on shareholder_register_filing.filing_submissions to shareholder_register_filing_executor;
create policy rf151_member_read on shareholder_register_filing.filing_submissions for select to shareholder_register_filing_executor,shareholder_register_filing_store_owner
using(shareholder_register_filing.verified_actor_v1() is not null and public.company_access_is_accepted_member_v1(company_id));
create policy rf151_owner_write on shareholder_register_filing.filing_submissions for all to shareholder_register_filing_store_owner
using(shareholder_register_filing.verified_actor_v1() is not null and public.company_access_is_accepted_owner_v1(company_id))
with check(shareholder_register_filing.verified_actor_v1() is not null and public.company_access_is_accepted_owner_v1(company_id));

alter table shareholder_register_filing.filing_overrides owner to shareholder_register_filing_store_owner;
alter table shareholder_register_filing.filing_overrides force row level security;
revoke all on shareholder_register_filing.filing_overrides from public,anon,authenticated,service_role;
grant select on shareholder_register_filing.filing_overrides to shareholder_register_filing_executor;
create policy rf151_member_read on shareholder_register_filing.filing_overrides for select to shareholder_register_filing_executor,shareholder_register_filing_store_owner
using(shareholder_register_filing.verified_actor_v1() is not null and public.company_access_is_accepted_member_v1(company_id));
create policy rf151_owner_write on shareholder_register_filing.filing_overrides for all to shareholder_register_filing_store_owner
using(shareholder_register_filing.verified_actor_v1() is not null and public.company_access_is_accepted_owner_v1(company_id))
with check(shareholder_register_filing.verified_actor_v1() is not null and public.company_access_is_accepted_owner_v1(company_id));

alter table shareholder_register_filing.filing_review_comments owner to shareholder_register_filing_store_owner;
alter table shareholder_register_filing.filing_review_comments force row level security;
revoke all on shareholder_register_filing.filing_review_comments from public,anon,authenticated,service_role;
grant select on shareholder_register_filing.filing_review_comments to shareholder_register_filing_executor;
create policy rf151_member_read on shareholder_register_filing.filing_review_comments for select to shareholder_register_filing_executor,shareholder_register_filing_store_owner
using(shareholder_register_filing.verified_actor_v1() is not null and public.company_access_is_accepted_member_v1(company_id));
create policy rf151_owner_write on shareholder_register_filing.filing_review_comments for all to shareholder_register_filing_store_owner
using(shareholder_register_filing.verified_actor_v1() is not null and public.company_access_is_accepted_owner_v1(company_id))
with check(shareholder_register_filing.verified_actor_v1() is not null and public.company_access_is_accepted_owner_v1(company_id));

alter table shareholder_register_filing.authority_permissions owner to shareholder_register_filing_store_owner;
alter table shareholder_register_filing.authority_permissions force row level security;
revoke all on shareholder_register_filing.authority_permissions from public,anon,authenticated,service_role;
grant select on shareholder_register_filing.authority_permissions to shareholder_register_filing_executor;
create policy rf151_member_read on shareholder_register_filing.authority_permissions for select to shareholder_register_filing_executor,shareholder_register_filing_store_owner
using(shareholder_register_filing.verified_actor_v1() is not null and public.company_access_is_accepted_member_v1(company_id));
create policy rf151_owner_write on shareholder_register_filing.authority_permissions for all to shareholder_register_filing_store_owner
using(shareholder_register_filing.verified_actor_v1() is not null and public.company_access_is_accepted_owner_v1(company_id))
with check(shareholder_register_filing.verified_actor_v1() is not null and public.company_access_is_accepted_owner_v1(company_id));

alter table shareholder_register_filing.authority_test_runs owner to shareholder_register_filing_store_owner;
alter table shareholder_register_filing.authority_test_runs force row level security;
revoke all on shareholder_register_filing.authority_test_runs from public,anon,authenticated,service_role;
grant select on shareholder_register_filing.authority_test_runs to shareholder_register_filing_executor;
create policy rf151_member_read on shareholder_register_filing.authority_test_runs for select to shareholder_register_filing_executor,shareholder_register_filing_store_owner
using(shareholder_register_filing.verified_actor_v1() is not null and public.company_access_is_accepted_member_v1(company_id));
create policy rf151_owner_write on shareholder_register_filing.authority_test_runs for all to shareholder_register_filing_store_owner
using(shareholder_register_filing.verified_actor_v1() is not null and public.company_access_is_accepted_owner_v1(company_id))
with check(shareholder_register_filing.verified_actor_v1() is not null and public.company_access_is_accepted_owner_v1(company_id));

-- No ordinary runtime can fabricate coverage or change migration phase.
alter table shareholder_register_filing.migration_state enable row level security;
alter table shareholder_register_filing.migration_inventory enable row level security;
alter table shareholder_register_filing.migration_quarantine enable row level security;
revoke all on shareholder_register_filing.migration_state,shareholder_register_filing.migration_inventory,shareholder_register_filing.migration_quarantine from public,anon,authenticated,service_role,shareholder_register_filing_executor;

-- Each original generic writer remains authoritative until the atomic cutover.
-- Projection synchronization is unidirectional according to the persisted phase.
create function shareholder_register_filing.sync_legacy_projection_v1() returns trigger
language plpgsql security definer set search_path='' as $function$
declare item jsonb; old_item jsonb; category text; v_cols text; v_update text; v_phase text;
begin
  if tg_table_name not in ('opening_balance_setups','opening_shareholders','filing_previews','filing_submissions',
    'filing_overrides','filing_review_comments','authority_permissions','authority_test_runs')
  then raise exception 'rf1086_unknown_migration_family'; end if;
  v_phase:=shareholder_register_filing.phase_v1();
  item:=case when tg_op='DELETE' then pg_catalog.to_jsonb(old) else pg_catalog.to_jsonb(new) end;
  if tg_op='UPDATE' then old_item:=pg_catalog.to_jsonb(old); end if;
  category:=shareholder_register_filing.classify_legacy_row_v1(tg_table_name,item);
  if tg_when='BEFORE' then
    if v_phase<>'legacy_overlap' and (category<>'sibling' or
      (old_item is not null and shareholder_register_filing.classify_legacy_row_v1(tg_table_name,old_item)<>'sibling'))
      and not(pg_catalog.pg_trigger_depth()>1 and pg_catalog.current_setting('role',true) in
        ('shareholder_register_filing_executor','ledger_workflow_executor'))
    then raise exception 'rf1086_legacy_writer_retired'; end if;
    return case when tg_op='DELETE' then old else new end;
  end if;
  if v_phase<>'legacy_overlap' then return null; end if;
  if category='quarantine' then
    insert into shareholder_register_filing.migration_quarantine(family,record_id,company_id,income_year,reason,original_row)
    values(tg_table_name,(item->>'id')::uuid,(item->>'company_id')::uuid,(item->>'income_year')::integer,'conflicting_rf_provenance',item)
    on conflict(family,record_id) do update set original_row=excluded.original_row;
    return null;
  end if;
  if tg_op='DELETE' or category='sibling' then
    execute pg_catalog.format('delete from shareholder_register_filing.%I where id=$1',tg_table_name)
      using (item->>'id')::uuid;
    return null;
  end if;
  select pg_catalog.string_agg(pg_catalog.quote_ident(a.attname),',' order by a.attnum),
    pg_catalog.string_agg(pg_catalog.format('%I=excluded.%I',a.attname,a.attname),',' order by a.attnum)
  into v_cols,v_update from pg_catalog.pg_attribute a
  where a.attrelid=pg_catalog.to_regclass('shareholder_register_filing.'||tg_table_name)
    and a.attnum>0 and not a.attisdropped;
  execute pg_catalog.format('insert into shareholder_register_filing.%I(%s) select %s from jsonb_populate_record(null::shareholder_register_filing.%I,$1) on conflict(id) do update set %s',tg_table_name,v_cols,v_cols,tg_table_name,v_update)
    using item;
  return null;
end; $function$;
do $triggers$ declare n text; begin
 foreach n in array array['opening_balance_setups','opening_shareholders','filing_previews','filing_submissions',
    'filing_overrides','filing_review_comments','authority_permissions','authority_test_runs'] loop
  execute pg_catalog.format('create trigger rf151_legacy_write_barrier before insert or update or delete on public.%I for each row execute function shareholder_register_filing.sync_legacy_projection_v1()',n);
  execute pg_catalog.format('create trigger rf151_legacy_projection after insert or update or delete on public.%I for each row execute function shareholder_register_filing.sync_legacy_projection_v1()',n);
  -- Temporary function-owner ACL, never inherited by the verified runtime login.
  execute pg_catalog.format('grant select,insert,update,delete on shareholder_register_filing.%I to %I',n,current_user);
  execute pg_catalog.format('create policy rf151_overlap_copy on shareholder_register_filing.%I for all to %I using(shareholder_register_filing.phase_v1()=''legacy_overlap'') with check(shareholder_register_filing.phase_v1()=''legacy_overlap'')',n,current_user);
 end loop;
end; $triggers$;

-- This is a Company Access decision, not a copied RF membership table policy.
grant create on schema public to company_access_executor;
set local role company_access_executor;
create function public.company_access_can_review_filing_v1(p_company_id uuid) returns boolean
language sql stable security definer set search_path='' as $function$
 select exists(select 1 from public.company_memberships m
   where m.company_id=p_company_id and m.user_id=public.company_access_auth_uid_v1()
     and m.role in ('owner','reviewer') and m.accepted_at is not null);
$function$;
create function public.company_access_read_rf_company_identity_v1(p_company_id uuid,p_verified_subject text) returns jsonb
language plpgsql stable security definer set search_path='' as $function$
declare a uuid:=public.company_access_auth_uid_v1(); result jsonb;
begin
 if a is null or p_verified_subject is distinct from a::text then raise exception 'company_access_forbidden'; end if;
 if not public.company_access_is_accepted_member_v1(p_company_id) then raise exception 'company_access_not_found'; end if;
 select pg_catalog.jsonb_build_object('id',c.id,'org_number',c.org_number,'name',c.name,
   'address',c.address,'postal_code',c.postal_code,'city',c.city) into result
 from public.companies c where c.id=p_company_id;
 if result is null then raise exception 'company_access_not_found'; end if;
 return result;
end; $function$;
revoke all on function public.company_access_can_review_filing_v1(uuid) from public,anon,authenticated,service_role;
revoke all on function public.company_access_read_rf_company_identity_v1(uuid,text) from public,anon,authenticated,service_role;
grant execute on function public.company_access_can_review_filing_v1(uuid)
to shareholder_register_filing_store_owner,shareholder_register_filing_executor;
grant execute on function public.company_access_read_rf_company_identity_v1(uuid,text)
to shareholder_register_filing_store_owner,shareholder_register_filing_executor;
reset role;
-- Original CREATE privilege restored by the migration grant ledger.

grant execute on function public.company_access_auth_uid_v1(),public.company_access_auth_jwt_v1(),
 public.company_access_is_accepted_owner_v1(uuid),public.company_access_is_accepted_member_v1(uuid),
 public.company_access_has_fresh_mfa_v1(),public.company_access_company_year_allows_consequential_v1(uuid,integer)
to shareholder_register_filing_store_owner,shareholder_register_filing_executor;
grant execute on function public.company_access_auth_uid_v1(),public.company_access_is_accepted_owner_v1(uuid),
 public.company_access_is_accepted_member_v1(uuid) to ledger_store_owner;
grant usage on schema shareholder_register_filing to ledger_store_owner;

set local role ledger_store_owner;
create function ledger.record_opening_bank_input_v1(
 p_snapshot_id uuid,p_company_id uuid,p_income_year integer,p_bank_balance_nok numeric,p_verified_subject text)
returns table(snapshot_id uuid,company_id uuid,income_year integer,bank_balance_nok numeric,recorded_by uuid,recorded_at timestamptz)
language plpgsql security definer set search_path='' as $function$
declare a uuid:=public.company_access_auth_uid_v1(); r ledger.opening_bank_inputs%rowtype;
begin
 if a is null or p_verified_subject is distinct from a::text
   or not public.company_access_is_accepted_owner_v1(p_company_id)
 then raise exception 'ledger_forbidden'; end if;
 if p_snapshot_id is null or p_company_id is null or p_income_year is null or p_income_year not between 2000 and 2100
   or p_bank_balance_nok is null or p_bank_balance_nok<0
   or p_bank_balance_nok<>pg_catalog.round(p_bank_balance_nok,2)
 then raise exception 'ledger_invalid_input'; end if;
 insert into ledger.opening_bank_inputs(snapshot_id,company_id,income_year,bank_balance_nok,recorded_by,recorded_at)
 values(p_snapshot_id,p_company_id,p_income_year,p_bank_balance_nok,a,pg_catalog.transaction_timestamp())
 on conflict do nothing;
 select * into r from ledger.opening_bank_inputs v where v.snapshot_id=p_snapshot_id;
 if r.snapshot_id is null or r.company_id<>p_company_id or r.income_year<>p_income_year
   or r.bank_balance_nok<>p_bank_balance_nok or r.recorded_by<>a
 then raise exception 'ledger_opening_already_exists'; end if;
 if not public.company_access_is_accepted_owner_v1(p_company_id) then raise exception 'ledger_forbidden'; end if;
 return query select r.snapshot_id,r.company_id,r.income_year,r.bank_balance_nok,r.recorded_by,r.recorded_at;
end; $function$;
create function ledger.read_opening_bank_inputs_v1(p_company_id uuid,p_income_year integer,p_verified_subject text)
returns table(snapshot_id uuid,company_id uuid,income_year integer,bank_balance_nok numeric,recorded_by uuid,recorded_at timestamptz)
language plpgsql stable security definer set search_path='' as $function$
declare a uuid:=public.company_access_auth_uid_v1();
begin
 if a is null or p_verified_subject is distinct from a::text then raise exception 'ledger_forbidden'; end if;
 if not public.company_access_is_accepted_member_v1(p_company_id) then raise exception 'ledger_not_found'; end if;
 return query select v.snapshot_id,v.company_id,v.income_year,v.bank_balance_nok,v.recorded_by,v.recorded_at
 from ledger.opening_bank_inputs v where v.company_id=p_company_id and (p_income_year is null or v.income_year=p_income_year)
 order by v.recorded_at desc,v.snapshot_id desc;
end; $function$;
revoke all on function ledger.record_opening_bank_input_v1(uuid,uuid,integer,numeric,text),
 ledger.read_opening_bank_inputs_v1(uuid,integer,text) from public,anon,authenticated,service_role;
grant execute on function ledger.record_opening_bank_input_v1(uuid,uuid,integer,numeric,text),
 ledger.read_opening_bank_inputs_v1(uuid,integer,text) to ledger_workflow_executor,ledger_workflow_store_owner;
reset role;

-- New backend can inspect the canonical mirrored records during either rollout order.
grant select on shareholder_register_filing.filing_approval_snapshots,shareholder_register_filing.production_filing_submissions,
 shareholder_register_filing.production_filing_events,shareholder_register_filing.production_feedback_artifacts
to shareholder_register_filing_executor;
create policy rf151_approval_read on shareholder_register_filing.filing_approval_snapshots for select to shareholder_register_filing_executor
using(shareholder_register_filing.verified_actor_v1() is not null and public.company_access_is_accepted_member_v1(company_id));
create policy rf151_submission_read on shareholder_register_filing.production_filing_submissions for select to shareholder_register_filing_executor
using(shareholder_register_filing.verified_actor_v1() is not null and public.company_access_is_accepted_member_v1(company_id));
create policy rf151_event_read on shareholder_register_filing.production_filing_events for select to shareholder_register_filing_executor
using(exists(select 1 from shareholder_register_filing.production_filing_submissions s where s.id=submission_id));
create policy rf151_artifact_read on shareholder_register_filing.production_feedback_artifacts for select to shareholder_register_filing_executor
using(shareholder_register_filing.verified_actor_v1() is not null and public.company_access_is_accepted_owner_v1(company_id));

-- Explicit function allowlist; default PUBLIC execute is not an API contract.
revoke all on all functions in schema shareholder_register_filing from public,anon,authenticated,service_role;
grant execute on function shareholder_register_filing.verified_actor_v1(),shareholder_register_filing.phase_v1(),
 shareholder_register_filing.is_rf_label_v1(text) to shareholder_register_filing_executor,shareholder_register_filing_store_owner;

create function shareholder_register_filing.has_blocking_override_v1(p_company_id uuid,p_income_year integer) returns boolean
language sql stable security definer set search_path='' as $function$
 select public.company_access_is_accepted_member_v1(p_company_id) and exists(select 1 from shareholder_register_filing.filing_overrides o
 where o.company_id=p_company_id and o.income_year=p_income_year and o.risk_level='block');
$function$;
alter function shareholder_register_filing.has_blocking_override_v1(uuid,integer) owner to shareholder_register_filing_store_owner;
revoke all on function shareholder_register_filing.has_blocking_override_v1(uuid,integer) from public,anon,authenticated,service_role;
grant execute on function shareholder_register_filing.has_blocking_override_v1(uuid,integer) to postgres;
-- Public receiver queries retain the pre-existing stored release predicates.
create function backend_system.rf1086_stored_release_inputs_v1(p_company_id uuid,p_income_year integer,p_obligation text)
returns boolean language sql stable security definer set search_path='' as $function$
 select public.company_access_is_accepted_member_v1(p_company_id)
   and coalesce((select r.ready and pg_catalog.jsonb_array_length(r.hard_blocks)=0
     from public.filing_readiness_snapshots r where r.company_id=p_company_id and r.income_year=p_income_year
       and r.obligation=p_obligation order by r.updated_at desc,r.id desc limit 1),false)
   and not shareholder_register_filing.has_blocking_override_v1(p_company_id,p_income_year)
   and not exists(select 1 from public.filing_overrides o
     where o.company_id=p_company_id and o.income_year=p_income_year and o.risk_level='block'
       and not shareholder_register_filing.is_rf_label_v1(o.filing));
$function$;
create function backend_system.rf1086_annual_readiness_ready_v1(p_company_id uuid,p_income_year integer,p_obligation text)
returns boolean language sql stable security definer set search_path='' as $function$
 select public.company_access_is_accepted_member_v1(p_company_id)
   and coalesce((select r.ready from public.filing_readiness_snapshots r where r.company_id=p_company_id
     and r.income_year=p_income_year and r.obligation=p_obligation order by r.updated_at desc,r.id desc limit 1),false);
$function$;
create function backend_system.rf1086_technical_release_ready_v1() returns boolean
language sql stable security definer set search_path='' as $function$
 select not exists(select 1 from pg_catalog.unnest(array['launch_legal_name_public_copy','legal_policy_pack','security_restore',
   'support_rollback','founder_production_go_live','rf1086_authority']) required_key where not exists(
   select 1 from public.launch_signoffs s where s.key=required_key and s.status='approved'
     and s.reviewed_at<=pg_catalog.now() and (s.key<>'security_restore' or s.reviewed_at>=pg_catalog.now()-interval '30 days')));
$function$;
revoke all on function backend_system.rf1086_stored_release_inputs_v1(uuid,integer,text),
 backend_system.rf1086_annual_readiness_ready_v1(uuid,integer,text),backend_system.rf1086_technical_release_ready_v1()
from public,anon,authenticated,service_role;
grant usage on schema backend_system to shareholder_register_filing_executor,shareholder_register_filing_store_owner;
grant execute on function backend_system.rf1086_stored_release_inputs_v1(uuid,integer,text),
 backend_system.rf1086_annual_readiness_ready_v1(uuid,integer,text),backend_system.rf1086_technical_release_ready_v1()
to shareholder_register_filing_executor,shareholder_register_filing_store_owner;

create function shareholder_register_filing.assert_member_v1(p_company_id uuid) returns uuid
language plpgsql stable security definer set search_path='' as $function$
declare a uuid:=shareholder_register_filing.verified_actor_v1(); begin
 if a is null then raise exception 'rf1086_forbidden'; end if;
 if not public.company_access_is_accepted_member_v1(p_company_id) then raise exception 'rf1086_not_found'; end if;
 return a;
end; $function$;
create function shareholder_register_filing.assert_preparation_access_v1(p_company_id uuid,p_review boolean default false) returns uuid
language plpgsql stable security definer set search_path='' as $function$
declare a uuid:=shareholder_register_filing.assert_member_v1(p_company_id); begin
 if not (case when p_review then public.company_access_can_review_filing_v1(p_company_id)
   else public.company_access_is_accepted_owner_v1(p_company_id) end)
 then raise exception 'rf1086_forbidden'; end if;
 return a;
end; $function$;

-- Fixed inventory, private insert primitive: table/column names never come from an HTTP command.
-- During expand the original table is still the authoritative writer.
create function shareholder_register_filing.insert_preparation_row_v1(p_family text,p_row jsonb) returns jsonb
language plpgsql security definer set search_path='' as $function$
declare v_schema text; v_columns text; result jsonb; begin
 if p_family not in ('filing_previews','filing_submissions','filing_overrides','filing_review_comments','authority_permissions','authority_test_runs')
 then raise exception 'rf1086_invalid_input'; end if;
 v_schema:=case when shareholder_register_filing.phase_v1()='legacy_overlap' then 'public' else 'shareholder_register_filing' end;
 select pg_catalog.string_agg(pg_catalog.quote_ident(a.attname),',' order by a.attnum) into v_columns
 from pg_catalog.pg_attribute a where a.attrelid=pg_catalog.to_regclass(v_schema||'.'||p_family)
   and a.attnum>0 and not a.attisdropped and p_row ? a.attname;
 execute pg_catalog.format('insert into %I.%I(%s) select %s from pg_catalog.jsonb_populate_record(null::%I.%I,$1) returning pg_catalog.to_jsonb(%I.*)',
   v_schema,p_family,v_columns,v_columns,v_schema,p_family,p_family) into result using p_row;
 return result;
end; $function$;
create function shareholder_register_filing.record_preview_v1(p_company_id uuid,p_setup_id uuid,p_status text,p_issues jsonb,p_preview text,p_main_xml text,p_sub_xml jsonb)
returns jsonb language plpgsql security definer set search_path='' as $function$
declare a uuid:=shareholder_register_filing.assert_preparation_access_v1(p_company_id); o shareholder_register_filing.opening_balance_setups%rowtype; begin
 select * into o from shareholder_register_filing.opening_balance_setups where id=p_setup_id and company_id=p_company_id for update;
 if o.id is null then raise exception 'rf1086_not_found'; end if;
 if p_status not in ('ready','blocked','warning') or pg_catalog.jsonb_typeof(p_issues)<>'array'
   or pg_catalog.jsonb_typeof(p_sub_xml)<>'object' or p_preview is null then raise exception 'rf1086_invalid_input'; end if;
 return shareholder_register_filing.insert_preparation_row_v1('filing_previews',pg_catalog.jsonb_build_object(
  'company_id',p_company_id,'setup_id',p_setup_id,'income_year',o.income_year,'filing','aksjonærregisteroppgaven',
  'status',p_status,'issues',p_issues,'preview',p_preview,'hovedskjema_xml',p_main_xml,'underskjema_xml',p_sub_xml,'source','deterministic_rf1086_engine','created_by',a));
end; $function$;
create function shareholder_register_filing.record_override_v1(p_preview_id uuid,p_target text,p_old text,p_new text,p_reason text,p_risk text,p_confirmed boolean)
returns jsonb language plpgsql security definer set search_path='' as $function$
declare a uuid; p shareholder_register_filing.filing_previews%rowtype; begin
 select * into p from shareholder_register_filing.filing_previews where id=p_preview_id for update;
 if p.id is null then raise exception 'rf1086_not_found'; end if;
 a:=shareholder_register_filing.assert_preparation_access_v1(p.company_id);
 if p_confirmed is distinct from true or p_target='' or p_reason='' or (p_old='' and p_new='') or p_risk not in ('advisory','warning','block') then raise exception 'rf1086_invalid_input'; end if;
 return shareholder_register_filing.insert_preparation_row_v1('filing_overrides',pg_catalog.jsonb_build_object('preview_id',p.id,
  'company_id',p.company_id,'income_year',p.income_year,'filing',p.filing,'field_target',p_target,'old_value',p_old,'new_value',p_new,
  'reason',p_reason,'risk_level',p_risk,'owner_confirmed_by',a,'owner_confirmed_at',pg_catalog.now(),'created_by',a));
end; $function$;
create function shareholder_register_filing.add_review_comment_v1(p_preview_id uuid,p_severity text,p_body text)
returns jsonb language plpgsql security definer set search_path='' as $function$
declare a uuid; p shareholder_register_filing.filing_previews%rowtype; begin
 select * into p from shareholder_register_filing.filing_previews where id=p_preview_id;
 if p.id is null then raise exception 'rf1086_not_found'; end if;
 a:=shareholder_register_filing.assert_preparation_access_v1(p.company_id,true);
 if p_severity not in ('advisory','hard_block') or p_body is null or p_body='' then raise exception 'rf1086_invalid_input'; end if;
 return shareholder_register_filing.insert_preparation_row_v1('filing_review_comments',pg_catalog.jsonb_build_object(
  'preview_id',p.id,'company_id',p.company_id,'target','rf1086_preview','severity',p_severity,'body',p_body,'created_by',a));
end; $function$;
create function shareholder_register_filing.acknowledge_review_comment_v1(p_comment_id uuid)
returns jsonb language plpgsql security definer set search_path='' as $function$
declare a uuid; c shareholder_register_filing.filing_review_comments%rowtype; result jsonb; begin
 select * into c from shareholder_register_filing.filing_review_comments where id=p_comment_id for update;
 if c.id is null then raise exception 'rf1086_not_found'; end if;
 a:=shareholder_register_filing.assert_preparation_access_v1(c.company_id);
 if c.severity='hard_block' then raise exception 'rf1086_forbidden'; end if;
 if shareholder_register_filing.phase_v1()='legacy_overlap' then
  update public.filing_review_comments set acknowledged_by=a,acknowledged_at=pg_catalog.now() where id=c.id returning pg_catalog.to_jsonb(filing_review_comments.*) into result;
 else
  update shareholder_register_filing.filing_review_comments set acknowledged_by=a,acknowledged_at=pg_catalog.now() where id=c.id returning pg_catalog.to_jsonb(filing_review_comments.*) into result;
 end if;
 return result;
end; $function$;
create function shareholder_register_filing.confirm_filing_permission_v1(p_company_id uuid,p_enabled boolean)
returns jsonb language plpgsql security definer set search_path='' as $function$
declare a uuid:=shareholder_register_filing.assert_preparation_access_v1(p_company_id); result jsonb; v_schema text; begin
 if not public.company_access_has_fresh_mfa_v1() then raise exception 'rf1086_company_year_not_admitted'; end if;
 if p_enabled is null then raise exception 'rf1086_invalid_input'; end if;
 v_schema:=case when shareholder_register_filing.phase_v1()='legacy_overlap' then 'public' else 'shareholder_register_filing' end;
 execute pg_catalog.format('insert into %I.authority_permissions(company_id,obligation,submitter_user_id,confirmed_by,confirmed_at,production_enabled) values($1,''aksjonaerregisteroppgaven'',$2,$2,pg_catalog.now(),$3) on conflict(company_id,obligation) do update set submitter_user_id=excluded.submitter_user_id,confirmed_by=excluded.confirmed_by,confirmed_at=excluded.confirmed_at,production_enabled=excluded.production_enabled,updated_at=pg_catalog.now() returning pg_catalog.to_jsonb(authority_permissions.*)',v_schema)
 into result using p_company_id,a,p_enabled;
 return result;
end; $function$;
create function shareholder_register_filing.record_test_evidence_v1(p_company_id uuid,p_data jsonb)
returns jsonb language plpgsql security definer set search_path='' as $function$
declare a uuid:=shareholder_register_filing.assert_preparation_access_v1(p_company_id); begin
 if not public.company_access_has_fresh_mfa_v1() then raise exception 'rf1086_company_year_not_admitted'; end if;
 if p_data->>'environment' not in ('test','manual_evidence') or p_data->>'status' not in ('accepted','rejected','blocked','pending')
   or coalesce(p_data->>'test_reference','')='' then raise exception 'rf1086_invalid_input'; end if;
 return shareholder_register_filing.insert_preparation_row_v1('authority_test_runs',pg_catalog.jsonb_build_object(
 'company_id',p_company_id,'obligation','aksjonaerregisteroppgaven','recorded_by',a,'environment',p_data->>'environment',
 'status',p_data->>'status','test_reference',p_data->>'test_reference','feedback_summary',p_data->>'feedback_summary',
 'receipt_reference',p_data->>'receipt_reference','archive_reference',p_data->>'archive_reference','evidence_url',p_data->>'evidence_url','payload_hash',p_data->>'payload_hash'));
end; $function$;
create function shareholder_register_filing.record_simulation_v1(p_preview_id uuid,p_data jsonb)
returns jsonb language plpgsql security definer set search_path='' as $function$
declare a uuid; p shareholder_register_filing.filing_previews%rowtype; result jsonb; v_schema text; begin
 select * into p from shareholder_register_filing.filing_previews where id=p_preview_id for update;
 if p.id is null then raise exception 'rf1086_not_found'; end if;
 a:=shareholder_register_filing.assert_preparation_access_v1(p.company_id);
 if p.status<>'ready' or not backend_system.rf1086_annual_readiness_ready_v1(p.company_id,p.income_year,'aksjonaerregisteroppgaven')
   or exists(select 1 from shareholder_register_filing.filing_review_comments c where c.preview_id=p.id and c.severity='hard_block')
   or exists(select 1 from shareholder_register_filing.filing_overrides o where o.company_id=p.company_id and o.income_year=p.income_year and o.risk_level='block' and o.filing=p.filing)
 then raise exception 'rf1086_company_year_not_admitted'; end if;
 -- Exact original upsert key preserves repeat simulation semantics.
 v_schema:=case when shareholder_register_filing.phase_v1()='legacy_overlap' then 'public' else 'shareholder_register_filing' end;
 execute pg_catalog.format('insert into %I.filing_submissions(preview_id,setup_id,company_id,income_year,filing,mode,adapter_mode,payload_hash,idempotency_key,status,calls,receipt_id,feedback_document_ids,feedback_items,receipt_metadata,submitted_payload_ref,submitted_payload,failure_code,failure_message,authority_confirmed_by,authority_confirmed_at,preview_confirmed_by,preview_confirmed_at,created_by,submitted_by) values($1,$2,$3,$4,$5,''simulation'',''simulation'',$6->>''payload_hash'',$6->>''idempotency_key'',$6->>''status'',$6->''calls'',$6->>''receipt_id'',$6->''feedback_document_ids'',$6->''feedback_items'',$6->''receipt_metadata'',$6->''submitted_payload_ref'',$6->''submitted_payload'',$6->>''failure_code'',$6->>''failure_message'',$7,($6->>''authority_confirmed_at'')::timestamptz,$7,($6->>''preview_confirmed_at'')::timestamptz,$7,$7) on conflict(preview_id) do update set mode=excluded.mode,adapter_mode=excluded.adapter_mode,payload_hash=excluded.payload_hash,idempotency_key=excluded.idempotency_key,status=excluded.status,calls=excluded.calls,receipt_id=excluded.receipt_id,feedback_document_ids=excluded.feedback_document_ids,feedback_items=excluded.feedback_items,receipt_metadata=excluded.receipt_metadata,submitted_payload_ref=excluded.submitted_payload_ref,submitted_payload=excluded.submitted_payload,failure_code=excluded.failure_code,failure_message=excluded.failure_message,authority_confirmed_by=excluded.authority_confirmed_by,authority_confirmed_at=excluded.authority_confirmed_at,preview_confirmed_by=excluded.preview_confirmed_by,preview_confirmed_at=excluded.preview_confirmed_at,created_by=excluded.created_by,submitted_by=excluded.submitted_by,updated_at=pg_catalog.now() returning pg_catalog.to_jsonb(filing_submissions.*)',v_schema)
 into result using p.id,p.setup_id,p.company_id,p.income_year,p.filing,p_data,a;
 return result;
end; $function$;

CREATE OR REPLACE FUNCTION shareholder_register_filing.rf1086_confirmation_forsendelse_id(p_reference text)
 RETURNS uuid
 LANGUAGE plpgsql
 IMMUTABLE
 SET search_path TO ''
AS $function$
declare
  v_confirmation jsonb;
begin
  if p_reference is null then
    return null;
  end if;
  begin
    v_confirmation := p_reference::jsonb;
  exception when invalid_text_representation then
    return null;
  end;
  if pg_catalog.jsonb_typeof(v_confirmation) is distinct from 'object' then
    return null;
  end if;
  if (select pg_catalog.count(*) from pg_catalog.jsonb_object_keys(v_confirmation)) <> 2
    or not (v_confirmation ?& array['dialogId', 'forsendelseId'])
    or pg_catalog.jsonb_typeof(v_confirmation -> 'dialogId') is distinct from 'string'
    or pg_catalog.jsonb_typeof(v_confirmation -> 'forsendelseId') is distinct from 'string'
    or v_confirmation ->> 'dialogId'
      !~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
    or v_confirmation ->> 'forsendelseId'
      !~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
  then
    return null;
  end if;
  return (v_confirmation ->> 'forsendelseId')::uuid;
end;
$function$
;

alter function shareholder_register_filing.rf1086_confirmation_forsendelse_id(text) owner to shareholder_register_filing_store_owner;

revoke all on function shareholder_register_filing.rf1086_confirmation_forsendelse_id(text) from public,anon,authenticated,service_role;

grant execute on function shareholder_register_filing.rf1086_confirmation_forsendelse_id(text) to shareholder_register_filing_executor;

grant usage on schema authority_connections, billing, documents to shareholder_register_filing_store_owner, shareholder_register_filing_executor;

grant execute on function authority_connections.read_rf_request_v1(uuid,uuid,uuid),authority_connections.lock_rf_request_v1(uuid,uuid,uuid),documents.get_document_v1(uuid,text) to shareholder_register_filing_executor,shareholder_register_filing_store_owner;

set local role billing_store_owner;

create or replace function billing.read_rf_pilot_v1(p_entitlement_id uuid,p_company_id uuid,p_actor_id uuid)
returns table(id uuid,company_id uuid,user_id uuid,income_year integer,obligation text,case_profile text,status text,starts_at timestamptz,expires_at timestamptz,system_user_request_id uuid,system_user_external_reference text)
language plpgsql security definer set search_path='' as $function$
begin
  if pg_catalog.current_setting('role',true) not in ('legacy_rf1086_executor','shareholder_register_filing_executor')
    or p_actor_id is distinct from public.company_access_auth_uid_v1()
    or not public.company_access_is_accepted_owner_v1(p_company_id)
  then raise exception 'legacy_rf1086_verified_owner_required'; end if;
  return query select e.id,e.company_id,e.user_id,e.income_year,e.obligation,e.case_profile,e.status,
    e.starts_at,e.expires_at,e.system_user_request_id,e.system_user_external_reference
  from billing.production_pilot_entitlements e where e.id=p_entitlement_id
    and e.company_id=p_company_id and e.user_id=p_actor_id;
  if not public.company_access_is_accepted_owner_v1(p_company_id)
  then raise exception 'legacy_rf1086_verified_owner_required'; end if;
end; $function$;

reset role;

grant execute on function billing.read_rf_pilot_v1(uuid,uuid,uuid) to shareholder_register_filing_executor,shareholder_register_filing_store_owner;

set local role billing_store_owner;

create or replace function billing.lock_rf_pilot_v1(p_entitlement_id uuid,p_company_id uuid,p_actor_id uuid)
returns table(id uuid,company_id uuid,user_id uuid,income_year integer,obligation text,case_profile text,status text,starts_at timestamptz,expires_at timestamptz,system_user_request_id uuid,system_user_external_reference text)
language plpgsql security definer set search_path='' as $function$
begin
  if pg_catalog.current_setting('role',true) not in ('legacy_rf1086_executor','shareholder_register_filing_executor')
    or p_actor_id is distinct from public.company_access_auth_uid_v1()
    or not public.company_access_is_accepted_owner_v1(p_company_id)
  then raise exception 'legacy_rf1086_verified_owner_required'; end if;
  return query select e.id,e.company_id,e.user_id,e.income_year,e.obligation,e.case_profile,e.status,
    e.starts_at,e.expires_at,e.system_user_request_id,e.system_user_external_reference
  from billing.production_pilot_entitlements e where e.id=p_entitlement_id
    and e.company_id=p_company_id and e.user_id=p_actor_id for update;
  if not public.company_access_is_accepted_owner_v1(p_company_id)
  then raise exception 'legacy_rf1086_verified_owner_required'; end if;
end; $function$;

reset role;

grant execute on function billing.lock_rf_pilot_v1(uuid,uuid,uuid) to shareholder_register_filing_executor,shareholder_register_filing_store_owner;

set local role billing_store_owner;
alter policy billing_rf_pilot_owner_read on billing.production_pilot_entitlements using(
 pg_catalog.current_setting('role',true) in ('legacy_rf1086_executor','shareholder_register_filing_executor')
 and user_id=public.company_access_auth_uid_v1() and public.company_access_is_accepted_owner_v1(company_id));
alter policy billing_rf_pilot_owner_lock on billing.production_pilot_entitlements using(
 pg_catalog.current_setting('role',true) in ('legacy_rf1086_executor','shareholder_register_filing_executor')
 and user_id=public.company_access_auth_uid_v1() and public.company_access_is_accepted_owner_v1(company_id)) with check(false);
reset role;

alter table shareholder_register_filing.filing_approval_snapshots owner to shareholder_register_filing_store_owner;
alter table shareholder_register_filing.filing_approval_snapshots force row level security;
grant select,insert,update,delete on shareholder_register_filing.filing_approval_snapshots to postgres;
create policy rf151_function_owner on shareholder_register_filing.filing_approval_snapshots for all to shareholder_register_filing_store_owner using (
 public.company_access_is_accepted_owner_v1(company_id)) with check (
 public.company_access_is_accepted_owner_v1(company_id));
create policy rf151_old_function_owner on shareholder_register_filing.filing_approval_snapshots for all to postgres using (shareholder_register_filing.phase_v1()<>'contracted') with check (shareholder_register_filing.phase_v1()<>'contracted');

alter table shareholder_register_filing.production_filing_submissions owner to shareholder_register_filing_store_owner;
alter table shareholder_register_filing.production_filing_submissions force row level security;
grant select,insert,update,delete on shareholder_register_filing.production_filing_submissions to postgres;
create policy rf151_function_owner on shareholder_register_filing.production_filing_submissions for all to shareholder_register_filing_store_owner using (
 public.company_access_is_accepted_owner_v1(company_id)) with check (
 public.company_access_is_accepted_owner_v1(company_id));
create policy rf151_old_function_owner on shareholder_register_filing.production_filing_submissions for all to postgres using (shareholder_register_filing.phase_v1()<>'contracted') with check (shareholder_register_filing.phase_v1()<>'contracted');

alter table shareholder_register_filing.production_filing_events owner to shareholder_register_filing_store_owner;
alter table shareholder_register_filing.production_filing_events force row level security;
grant select,insert,update,delete on shareholder_register_filing.production_filing_events to postgres;
create policy rf151_function_owner on shareholder_register_filing.production_filing_events for all to shareholder_register_filing_store_owner using (
 exists(select 1 from shareholder_register_filing.production_filing_submissions s where s.id=submission_id and public.company_access_is_accepted_owner_v1(s.company_id))) with check (
 exists(select 1 from shareholder_register_filing.production_filing_submissions s where s.id=submission_id and public.company_access_is_accepted_owner_v1(s.company_id)));
create policy rf151_old_function_owner on shareholder_register_filing.production_filing_events for all to postgres using (shareholder_register_filing.phase_v1()<>'contracted') with check (shareholder_register_filing.phase_v1()<>'contracted');

alter table shareholder_register_filing.production_feedback_artifacts owner to shareholder_register_filing_store_owner;
alter table shareholder_register_filing.production_feedback_artifacts force row level security;
grant select,insert,update,delete on shareholder_register_filing.production_feedback_artifacts to postgres;
create policy rf151_function_owner on shareholder_register_filing.production_feedback_artifacts for all to shareholder_register_filing_store_owner using (
 public.company_access_is_accepted_owner_v1(company_id)) with check (
 public.company_access_is_accepted_owner_v1(company_id));
create policy rf151_old_function_owner on shareholder_register_filing.production_feedback_artifacts for all to postgres using (shareholder_register_filing.phase_v1()<>'contracted') with check (shareholder_register_filing.phase_v1()<>'contracted');

CREATE OR REPLACE FUNCTION shareholder_register_filing.assert_fresh_owner_v1(p_company_id uuid)
 RETURNS uuid
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO ''
AS $function$
declare v_actor uuid:=shareholder_register_filing.actor_v1();
begin
  if shareholder_register_filing.assert_fresh_production_owner_v1(p_company_id) is distinct from v_actor
  then raise exception 'production_filing_fresh_owner_step_up_required'; end if;
  return v_actor;
end;
$function$
;

alter function shareholder_register_filing.assert_fresh_owner_v1(uuid) owner to shareholder_register_filing_store_owner;

revoke all on function shareholder_register_filing.assert_fresh_owner_v1(uuid) from public,anon,authenticated,service_role;

grant execute on function shareholder_register_filing.assert_fresh_owner_v1(uuid) to shareholder_register_filing_executor;

CREATE OR REPLACE FUNCTION shareholder_register_filing.actor_v1()
 RETURNS uuid
 LANGUAGE plpgsql
 STABLE SECURITY DEFINER
 SET search_path TO ''
AS $function$
declare
  v_actor uuid:=nullif(pg_catalog.current_setting('talli.verified_actor_id',true),'')::uuid;
  v_claims jsonb:=nullif(pg_catalog.current_setting('talli.verified_actor_claims',true),'')::jsonb;
begin
  if pg_catalog.current_setting('role',true) is distinct from 'shareholder_register_filing_executor'
    or v_actor is null or v_claims->>'sub' is distinct from v_actor::text
    or v_claims->>'role' is distinct from 'authenticated'
    or public.company_access_auth_uid_v1() is distinct from v_actor
    or (select public.company_access_auth_uid_v1()) is distinct from v_actor
    or (select public.company_access_auth_jwt_v1()) is distinct from v_claims
  then raise exception 'legacy_rf1086_verified_owner_required'; end if;
  return v_actor;
end;
$function$
;

alter function shareholder_register_filing.actor_v1() owner to shareholder_register_filing_store_owner;

revoke all on function shareholder_register_filing.actor_v1() from public,anon,authenticated,service_role;

grant execute on function shareholder_register_filing.actor_v1() to shareholder_register_filing_executor;

CREATE OR REPLACE FUNCTION shareholder_register_filing.can_read_company_v1(p_company_id uuid)
 RETURNS boolean
 LANGUAGE sql
 STABLE SECURITY DEFINER
 SET search_path TO ''
AS $function$
  select shareholder_register_filing.actor_v1() is not null
    and public.company_access_is_accepted_owner_v1(p_company_id);
$function$
;

alter function shareholder_register_filing.can_read_company_v1(uuid) owner to shareholder_register_filing_store_owner;

revoke all on function shareholder_register_filing.can_read_company_v1(uuid) from public,anon,authenticated,service_role;

grant execute on function shareholder_register_filing.can_read_company_v1(uuid) to shareholder_register_filing_executor;

CREATE OR REPLACE FUNCTION shareholder_register_filing.can_read_submission_v1(p_submission_id uuid)
 RETURNS boolean
 LANGUAGE sql
 STABLE SECURITY DEFINER
 SET search_path TO ''
AS $function$
  select exists(select 1 from shareholder_register_filing.production_filing_submissions s
    where s.id=p_submission_id and s.user_id=shareholder_register_filing.actor_v1()
      and shareholder_register_filing.can_read_company_v1(s.company_id)
      and s.obligation='aksjonaerregisteroppgaven' and s.case_profile='rf1086_no_activity_v1'
      and s.environment='production');
$function$
;

alter function shareholder_register_filing.can_read_submission_v1(uuid) owner to shareholder_register_filing_store_owner;

revoke all on function shareholder_register_filing.can_read_submission_v1(uuid) from public,anon,authenticated,service_role;

grant execute on function shareholder_register_filing.can_read_submission_v1(uuid) to shareholder_register_filing_executor;

CREATE OR REPLACE FUNCTION shareholder_register_filing.assert_submission_v1(p_submission_id uuid)
 RETURNS void
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO ''
AS $function$
begin
  if not shareholder_register_filing.can_read_submission_v1(p_submission_id)
  then raise exception 'legacy_rf1086_submission_relationship_mismatch'; end if;
end;
$function$
;

alter function shareholder_register_filing.assert_submission_v1(uuid) owner to shareholder_register_filing_store_owner;

revoke all on function shareholder_register_filing.assert_submission_v1(uuid) from public,anon,authenticated,service_role;

grant execute on function shareholder_register_filing.assert_submission_v1(uuid) to shareholder_register_filing_executor;

CREATE OR REPLACE FUNCTION shareholder_register_filing.prepare_operation_v1(p_submission_id uuid, p_operation_name text, p_body_hash text, p_idempotency_key uuid)
 RETURNS TABLE(id uuid, operation_name text, operation_state text, attempt integer, body_hash text, idempotency_key uuid, authority_reference text, failure_class text, newly_prepared boolean)
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO ''
AS $function$
declare v_event shareholder_register_filing.production_filing_events%rowtype; v_new boolean:=false;
begin
  perform shareholder_register_filing.assert_submission_v1(p_submission_id);
  if not (p_operation_name in ('post_hovedskjema','confirm','list_documents')
    or p_operation_name like 'post_underskjema:%')
    or (p_operation_name='list_documents' and (p_body_hash is not null or p_idempotency_key is not null))
    or (p_operation_name<>'list_documents' and (p_body_hash is null or p_idempotency_key is null))
  then raise exception 'legacy_rf1086_operation_invalid'; end if;
  -- The existing submission row serializes only preparation. No transaction or
  -- lock spans provider I/O. An existing prepared mutation returns as unknown.
  perform 1 from shareholder_register_filing.production_filing_submissions s where s.id=p_submission_id for update;
  perform shareholder_register_filing.assert_submission_v1(p_submission_id);
  select e.* into v_event from shareholder_register_filing.production_filing_events e
  where e.submission_id=p_submission_id and e.operation_name=p_operation_name
  order by e.created_at desc limit 1;
  if v_event.id is null then
    insert into shareholder_register_filing.production_filing_events(submission_id,operation_name,operation_state,
      attempt,body_hash,idempotency_key,resulting_status)
    values(p_submission_id,p_operation_name,'prepared',1,p_body_hash,p_idempotency_key,'sending')
    returning * into v_event;
    v_new:=true;
  end if;
  return query select v_event.id,v_event.operation_name,v_event.operation_state,v_event.attempt,
    v_event.body_hash,v_event.idempotency_key,v_event.authority_reference,v_event.failure_class,v_new;
end;
$function$
;

alter function shareholder_register_filing.prepare_operation_v1(uuid, text, text, uuid) owner to shareholder_register_filing_store_owner;

revoke all on function shareholder_register_filing.prepare_operation_v1(uuid, text, text, uuid) from public,anon,authenticated,service_role;

grant execute on function shareholder_register_filing.prepare_operation_v1(uuid, text, text, uuid) to shareholder_register_filing_executor;

CREATE OR REPLACE FUNCTION shareholder_register_filing.approve_production_filing(p_preview_id uuid, p_entitlement_id uuid, p_manifest jsonb, p_manifest_hash text, p_adapter_version text)
 RETURNS shareholder_register_filing.filing_approval_snapshots
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO ''
AS $function$
declare
  v_preview shareholder_register_filing.filing_previews%rowtype;
  v_entitlement record;
  v_actor_id uuid;
  v_row shareholder_register_filing.filing_approval_snapshots%rowtype;
  v_payload_hash text;
begin
  select * into v_preview from shareholder_register_filing.filing_previews where id = p_preview_id for update;
  if v_preview.id is null then raise exception 'production_preview_not_found'; end if;
  v_actor_id := shareholder_register_filing.assert_fresh_owner_v1(v_preview.company_id);
  select * into v_entitlement
  from billing.read_rf_pilot_v1(p_entitlement_id,v_preview.company_id,v_actor_id)
  where id = p_entitlement_id
    and company_id = v_preview.company_id
    and user_id = v_actor_id
    and income_year = v_preview.income_year
    and obligation = 'aksjonaerregisteroppgaven'
    and case_profile = 'rf1086_no_activity_v1'
    and status = 'active'
    and starts_at <= now()
    and expires_at > now();
  if v_entitlement.id is null then raise exception 'production_pilot_entitlement_required'; end if;
  if v_preview.status <> 'ready'
    or not shareholder_register_filing.is_rf_label_v1(v_preview.filing)
    or v_preview.hovedskjema_xml is null
    or jsonb_typeof(v_preview.underskjema_xml) is distinct from 'object'
    or v_preview.underskjema_xml = '{}'::jsonb
    or jsonb_typeof(p_manifest) <> 'object'
    or p_manifest_hash !~ '^[0-9a-f]{64}$'
    or length(trim(coalesce(p_adapter_version, ''))) not between 1 and 100
    or coalesce(p_manifest ->> 'companyId', '') <> v_preview.company_id::text
    or coalesce(p_manifest ->> 'userId', '') <> v_actor_id::text
    or coalesce((p_manifest ->> 'incomeYear')::integer, -1) <> v_preview.income_year
    or coalesce(p_manifest ->> 'obligation', '') <> 'aksjonaerregisteroppgaven'
    or coalesce(p_manifest ->> 'caseProfile', '') <> 'rf1086_no_activity_v1'
    or coalesce(p_manifest ->> 'adapterVersion', '') <> p_adapter_version
    or coalesce(p_manifest ->> 'previewId', '') <> v_preview.id::text
    or jsonb_array_length(coalesce(p_manifest -> 'blockers', '[]'::jsonb)) <> 0
  then
    raise exception 'production_approval_manifest_invalid';
  end if;
  v_payload_hash := p_manifest ->> 'payloadHash';
  if v_payload_hash !~ '^[0-9a-f]{64}$' then raise exception 'production_approval_payload_hash_invalid'; end if;

  update shareholder_register_filing.filing_approval_snapshots
  set invalidated_at = now(), invalidation_reason = 'superseded_by_new_approval'
  where preview_id = p_preview_id and invalidated_at is null;

  insert into shareholder_register_filing.filing_approval_snapshots (
    entitlement_id, preview_id, company_id, user_id, income_year, obligation,
    case_profile, adapter_version, payload_hash, manifest_hash, manifest,
    approved_by
  ) values (
    v_entitlement.id, v_preview.id, v_preview.company_id, v_actor_id,
    v_preview.income_year, 'aksjonaerregisteroppgaven', 'rf1086_no_activity_v1',
    p_adapter_version, v_payload_hash, p_manifest_hash, p_manifest, v_actor_id
  ) returning * into v_row;
  return v_row;
end;
$function$
;

alter function shareholder_register_filing.approve_production_filing(uuid, uuid, jsonb, text, text) owner to shareholder_register_filing_store_owner;

revoke all on function shareholder_register_filing.approve_production_filing(uuid, uuid, jsonb, text, text) from public,anon,authenticated,service_role;

grant execute on function shareholder_register_filing.approve_production_filing(uuid, uuid, jsonb, text, text) to shareholder_register_filing_executor;

CREATE OR REPLACE FUNCTION shareholder_register_filing.begin_production_filing(p_approval_id uuid)
 RETURNS shareholder_register_filing.production_filing_submissions
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO ''
AS $function$
declare
  v_approval shareholder_register_filing.filing_approval_snapshots%rowtype;
  v_actor_id uuid;
  v_system_user_request_id uuid;
  v_request record;
  v_entitlement record;
  v_row shareholder_register_filing.production_filing_submissions%rowtype;
begin
  select *
  into v_approval
  from shareholder_register_filing.filing_approval_snapshots
  where id = p_approval_id;

  if v_approval.id is null or v_approval.invalidated_at is not null then
    raise exception 'production_approval_invalid';
  end if;

  v_actor_id := shareholder_register_filing.assert_fresh_owner_v1(v_approval.company_id);
  if v_actor_id <> v_approval.user_id then
    raise exception 'production_filing_release_gate_blocked';
  end if;

  -- Discover the foreign key without locking, then acquire authorization locks
  -- in one order everywhere: exact request first, linked entitlement second.
  select e.system_user_request_id
  into v_system_user_request_id
  from billing.read_rf_pilot_v1(v_approval.entitlement_id,v_approval.company_id,v_actor_id) e;

  if v_system_user_request_id is null then
    raise exception 'production_filing_release_gate_blocked';
  end if;

  select r.* into v_request
  from authority_connections.lock_rf_request_v1(
    v_system_user_request_id,v_approval.company_id,v_actor_id) r;

  if v_request.id is null then
    raise exception 'production_filing_release_gate_blocked';
  end if;

  select e.* into v_entitlement
  from billing.lock_rf_pilot_v1(v_approval.entitlement_id,v_approval.company_id,v_actor_id) e;

  if v_entitlement.id is null
    or v_entitlement.system_user_request_id is distinct from v_request.id
    or v_entitlement.company_id <> v_approval.company_id
    or v_entitlement.user_id <> v_actor_id
    or v_entitlement.income_year <> v_approval.income_year
    or v_entitlement.obligation <> v_approval.obligation
    or v_entitlement.case_profile <> v_approval.case_profile
    or v_entitlement.status <> 'active'
    or v_entitlement.starts_at > pg_catalog.now()
    or v_entitlement.expires_at <= pg_catalog.now()
    or v_request.company_id <> v_approval.company_id
    or v_request.initiating_owner_user_id <> v_actor_id
    or v_request.obligation <> v_approval.obligation
    or v_request.status <> 'accepted'
    or v_request.preflight_verified_at is null
    or v_request.external_ref <> v_entitlement.system_user_external_reference
    or not exists (
      select 1
      from shareholder_register_filing.authority_permissions p
      where p.company_id = v_approval.company_id
        and p.obligation = v_approval.obligation
        and p.submitter_user_id = v_actor_id
        and p.confirmed_by = v_actor_id
        and p.production_enabled
    )
    or not backend_system.rf1086_stored_release_inputs_v1(v_approval.company_id,v_approval.income_year,v_approval.obligation)
    or exists (
      select 1
      from shareholder_register_filing.filing_review_comments c
      where c.preview_id = v_approval.preview_id
        and c.severity = 'hard_block'
        and c.acknowledged_at is null
    )
    or not backend_system.rf1086_technical_release_ready_v1()
  then
    raise exception 'production_filing_release_gate_blocked';
  end if;

  insert into shareholder_register_filing.production_filing_submissions (
    approval_id,
    entitlement_id,
    company_id,
    user_id,
    income_year,
    obligation,
    case_profile,
    payload_hash,
    adapter_version,
    environment,
    status,
    submitted_by
  ) values (
    v_approval.id,
    v_approval.entitlement_id,
    v_approval.company_id,
    v_actor_id,
    v_approval.income_year,
    v_approval.obligation,
    v_approval.case_profile,
    v_approval.payload_hash,
    v_approval.adapter_version,
    'production',
    'sending',
    v_actor_id
  )
  on conflict (approval_id) do update
  set updated_at = shareholder_register_filing.production_filing_submissions.updated_at
  returning * into v_row;

  return v_row;
end;
$function$
;

alter function shareholder_register_filing.begin_production_filing(uuid) owner to shareholder_register_filing_store_owner;

revoke all on function shareholder_register_filing.begin_production_filing(uuid) from public,anon,authenticated,service_role;

grant execute on function shareholder_register_filing.begin_production_filing(uuid) to shareholder_register_filing_executor;

CREATE OR REPLACE FUNCTION shareholder_register_filing.append_production_filing_event(p_submission_id uuid, p_operation_name text, p_operation_state text, p_attempt integer, p_body_hash text, p_idempotency_key uuid, p_authority_reference text, p_failure_class text, p_status text, p_final_authority_decision boolean DEFAULT false)
 RETURNS shareholder_register_filing.production_filing_events
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO ''
AS $function$
declare
  v_submission shareholder_register_filing.production_filing_submissions%rowtype;
  v_event shareholder_register_filing.production_filing_events%rowtype;
  v_allowed boolean := false;
begin
  perform shareholder_register_filing.assert_submission_v1(p_submission_id);
  select * into v_submission from shareholder_register_filing.production_filing_submissions where id = p_submission_id for update;
  if v_submission.id is null then raise exception 'production_submission_not_found'; end if;
  if p_status = v_submission.status then
    v_allowed := true;
  elsif v_submission.status = 'sending' and p_status in ('received', 'unknown', 'rejected') then
    v_allowed := true;
  elsif v_submission.status = 'received' and p_status in ('processing', 'rejected', 'action_required') then
    v_allowed := true;
  elsif v_submission.status = 'processing' and p_status in ('accepted', 'rejected', 'action_required') then
    v_allowed := true;
  end if;
  if not v_allowed then raise exception 'production_submission_transition_invalid'; end if;
  if p_status = 'accepted' and p_final_authority_decision is not true then
    raise exception 'production_final_authority_decision_required';
  end if;

  insert into shareholder_register_filing.production_filing_events (
    submission_id, operation_name, operation_state, attempt, body_hash,
    idempotency_key, authority_reference, failure_class, resulting_status
  ) values (
    p_submission_id, trim(p_operation_name), p_operation_state, p_attempt,
    p_body_hash, p_idempotency_key, left(p_authority_reference, 500),
    p_failure_class, p_status
  ) returning * into v_event;

  update shareholder_register_filing.production_filing_submissions
  set status = p_status,
      authority_references = case
        when p_authority_reference is null then authority_references
        else authority_references || jsonb_build_object(p_operation_name, left(p_authority_reference, 500))
      end,
      failure_class = p_failure_class,
      updated_at = now()
  where id = p_submission_id;
  return v_event;
end;
$function$
;

alter function shareholder_register_filing.append_production_filing_event(uuid, text, text, integer, text, uuid, text, text, text, boolean) owner to shareholder_register_filing_store_owner;

revoke all on function shareholder_register_filing.append_production_filing_event(uuid, text, text, integer, text, uuid, text, text, text, boolean) from public,anon,authenticated,service_role;

grant execute on function shareholder_register_filing.append_production_filing_event(uuid, text, text, integer, text, uuid, text, text, text, boolean) to shareholder_register_filing_executor;

CREATE OR REPLACE FUNCTION shareholder_register_filing.claim_production_feedback_reconciliation(p_submission_id uuid, p_lease_id uuid)
 RETURNS boolean
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO ''
AS $function$
declare
  v_submission shareholder_register_filing.production_filing_submissions%rowtype;
  v_authority_reference text;
  v_forsendelse_id uuid;
begin
  perform shareholder_register_filing.assert_submission_v1(p_submission_id);
  if p_lease_id is null then raise exception 'production_feedback_reconciliation_invalid'; end if;

  select s.*
  into v_submission
  from shareholder_register_filing.production_filing_submissions s
  where s.id = p_submission_id
  for update;
  if v_submission.id is null
    or v_submission.obligation <> 'aksjonaerregisteroppgaven'
    or v_submission.environment <> 'production'
  then
    raise exception 'production_feedback_submission_relationship_mismatch';
  end if;
  if v_submission.feedback_state not in ('sent', 'processing', 'unknown') then
    return false;
  end if;

  select e.authority_reference
  into v_authority_reference
  from shareholder_register_filing.production_filing_events e
  where e.submission_id = p_submission_id
    and e.operation_name = 'confirm'
    and e.operation_state = 'succeeded'
  order by e.created_at desc, e.id desc
  limit 1;
  v_forsendelse_id := shareholder_register_filing.rf1086_confirmation_forsendelse_id(v_authority_reference);
  if v_forsendelse_id is null then
    raise exception 'production_feedback_confirmation_reference_invalid';
  end if;

  if v_submission.feedback_forsendelse_id is not null
    and v_submission.feedback_forsendelse_id is distinct from v_forsendelse_id
  then
    raise exception 'production_feedback_confirmation_relationship_mismatch';
  end if;
  if v_submission.feedback_reconciliation_lease_id is not null
    and (
      v_submission.feedback_reconciliation_started_at is null
      or v_submission.feedback_reconciliation_started_at >= pg_catalog.now() - interval '5 minutes'
    )
  then
    return false;
  end if;

  update shareholder_register_filing.production_filing_submissions
  set feedback_forsendelse_id = v_forsendelse_id,
      feedback_reconciliation_lease_id = p_lease_id,
      feedback_reconciliation_started_at = pg_catalog.now()
  where id = p_submission_id;
  return true;
end;
$function$
;

alter function shareholder_register_filing.claim_production_feedback_reconciliation(uuid, uuid) owner to shareholder_register_filing_store_owner;

revoke all on function shareholder_register_filing.claim_production_feedback_reconciliation(uuid, uuid) from public,anon,authenticated,service_role;

grant execute on function shareholder_register_filing.claim_production_feedback_reconciliation(uuid, uuid) to shareholder_register_filing_executor;

CREATE OR REPLACE FUNCTION shareholder_register_filing.release_production_feedback_reconciliation(p_submission_id uuid, p_lease_id uuid)
 RETURNS boolean
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO ''
AS $function$
declare
  v_released boolean := false;
begin
  perform shareholder_register_filing.assert_submission_v1(p_submission_id);
  if p_lease_id is null then raise exception 'production_feedback_reconciliation_invalid'; end if;
  update shareholder_register_filing.production_filing_submissions s
  set feedback_reconciliation_lease_id = null,
      feedback_reconciliation_started_at = null
  where s.id = p_submission_id
    and s.feedback_reconciliation_lease_id = p_lease_id
  returning true into v_released;
  return coalesce(v_released, false);
end;
$function$
;

alter function shareholder_register_filing.release_production_feedback_reconciliation(uuid, uuid) owner to shareholder_register_filing_store_owner;

revoke all on function shareholder_register_filing.release_production_feedback_reconciliation(uuid, uuid) from public,anon,authenticated,service_role;

grant execute on function shareholder_register_filing.release_production_feedback_reconciliation(uuid, uuid) to shareholder_register_filing_executor;

CREATE OR REPLACE FUNCTION shareholder_register_filing.append_production_feedback_reconciliation(p_submission_id uuid, p_lease_id uuid, p_forsendelse_id uuid, p_state text, p_artifact_hashes text[], p_safe_error_code text, p_correlation_id text)
 RETURNS boolean
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO ''
AS $function$
declare
  v_submission shareholder_register_filing.production_filing_submissions%rowtype;
  v_previous shareholder_register_filing.production_filing_events%rowtype;
  v_hashes text[];
  v_persisted_hashes text[];
  v_resulting_status text;
begin
  perform shareholder_register_filing.assert_submission_v1(p_submission_id);
  if p_state not in ('sent', 'processing', 'accepted', 'rejected', 'action_required', 'unknown')
    or p_lease_id is null
    or p_forsendelse_id is null
    or (p_safe_error_code is not null and p_safe_error_code !~ '^[A-Z0-9_]{1,100}$')
    or (p_correlation_id is not null and p_correlation_id !~ '^[A-Za-z0-9._:-]{1,200}$')
    or exists (
      select 1 from unnest(coalesce(p_artifact_hashes, '{}'::text[])) h
      where h !~ '^[a-f0-9]{64}$'
    )
  then
    raise exception 'production_feedback_reconciliation_invalid';
  end if;

  select s.*
  into v_submission
  from shareholder_register_filing.production_filing_submissions s
  where s.id = p_submission_id
  for update;
  if v_submission.id is null
    or v_submission.feedback_reconciliation_lease_id is distinct from p_lease_id
    or (
      v_submission.feedback_forsendelse_id is not null
      and v_submission.feedback_forsendelse_id <> p_forsendelse_id
    )
  then
    raise exception 'production_feedback_reconciliation_relationship_mismatch';
  end if;
  if v_submission.feedback_state in ('accepted', 'rejected', 'action_required')
    and p_state <> v_submission.feedback_state
  then
    raise exception 'production_feedback_reconciliation_terminal';
  end if;

  select coalesce(array_agg(distinct h order by h), '{}'::text[])
  into v_hashes
  from unnest(coalesce(p_artifact_hashes, '{}'::text[])) h;
  select coalesce(array_agg(a.sha256 order by a.sha256), '{}'::text[])
  into v_persisted_hashes
  from shareholder_register_filing.production_feedback_artifacts a
  where a.submission_id = p_submission_id;
  if v_hashes <> v_persisted_hashes then
    raise exception 'production_feedback_artifact_set_mismatch';
  end if;
  if p_state = 'accepted' and (
    cardinality(v_hashes) = 0
    or exists (
      select 1 from shareholder_register_filing.production_feedback_artifacts a
      where a.submission_id = p_submission_id and a.classification <> 'accepted'
    )
  ) then
    raise exception 'production_feedback_acceptance_evidence_required';
  end if;
  if p_state = 'rejected' and (
    cardinality(v_hashes) = 0
    or exists (
      select 1 from shareholder_register_filing.production_feedback_artifacts a
      where a.submission_id = p_submission_id and a.classification <> 'rejected'
    )
  ) then
    raise exception 'production_feedback_rejection_evidence_required';
  end if;

  select e.*
  into v_previous
  from shareholder_register_filing.production_filing_events e
  where e.submission_id = p_submission_id
    and e.operation_name like 'reconciliation:%'
  order by e.created_at desc, e.id desc
  limit 1;

  v_resulting_status := case when p_state = 'sent' then 'received' else p_state end;
  if v_previous.id is not null
    and v_previous.resulting_status = v_resulting_status
    and v_previous.artifact_hashes = v_hashes
  then
    update shareholder_register_filing.production_filing_submissions
    set feedback_last_checked_at = pg_catalog.now(),
        feedback_safe_error_code = p_safe_error_code,
        feedback_correlation_id = p_correlation_id,
        updated_at = pg_catalog.now()
    where id = p_submission_id;
    return false;
  end if;

  insert into shareholder_register_filing.production_filing_events (
    submission_id, operation_name, operation_state, attempt, body_hash,
    idempotency_key, authority_reference, failure_class, resulting_status,
    artifact_hashes, safe_error_code, correlation_id
  ) values (
    p_submission_id,
    'reconciliation:' || pg_catalog.gen_random_uuid()::text,
    case when p_state = 'unknown' then 'unknown' else 'succeeded' end,
    1, null, null, null,
    case when p_state = 'unknown' then 'unknown' else null end,
    v_resulting_status,
    v_hashes, p_safe_error_code, p_correlation_id
  );

  update shareholder_register_filing.production_filing_submissions
  set status = v_resulting_status,
      feedback_state = p_state,
      feedback_forsendelse_id = coalesce(feedback_forsendelse_id, p_forsendelse_id),
      feedback_artifact_count = cardinality(v_hashes),
      feedback_last_checked_at = pg_catalog.now(),
      feedback_last_changed_at = pg_catalog.now(),
      feedback_safe_error_code = p_safe_error_code,
      feedback_correlation_id = p_correlation_id,
      updated_at = pg_catalog.now()
  where id = p_submission_id;
  return true;
end;
$function$
;

alter function shareholder_register_filing.append_production_feedback_reconciliation(uuid, uuid, uuid, text, text[], text, text) owner to shareholder_register_filing_store_owner;

revoke all on function shareholder_register_filing.append_production_feedback_reconciliation(uuid, uuid, uuid, text, text[], text, text) from public,anon,authenticated,service_role;

grant execute on function shareholder_register_filing.append_production_feedback_reconciliation(uuid, uuid, uuid, text, text[], text, text) to shareholder_register_filing_executor;

CREATE OR REPLACE FUNCTION shareholder_register_filing.record_production_feedback_artifact(p_company_id uuid, p_submission_id uuid, p_document_id uuid, p_authority_reference text, p_content_type text, p_byte_length bigint, p_sha256 text, p_classification text)
 RETURNS shareholder_register_filing.production_feedback_artifacts
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO ''
AS $function$
declare
  v_submission shareholder_register_filing.production_filing_submissions%rowtype;
  v_document public.documents%rowtype;
  v_artifact shareholder_register_filing.production_feedback_artifacts%rowtype;
begin
  perform shareholder_register_filing.assert_submission_v1(p_submission_id);
  if p_sha256 !~ '^[a-f0-9]{64}$'
    or p_byte_length not between 1 and 10485760
    or p_content_type not in ('application/xml','text/xml','application/pdf','text/plain','application/octet-stream')
    or p_classification not in ('accepted','rejected','action_required')
    or length(trim(coalesce(p_authority_reference, ''))) not between 1 and 500
  then
    raise exception 'production_feedback_metadata_invalid';
  end if;

  select s.*
  into v_submission
  from shareholder_register_filing.production_filing_submissions s
  where s.id = p_submission_id
    and s.company_id = p_company_id
    and s.obligation = 'aksjonaerregisteroppgaven'
    and s.environment = 'production'
  for update;
  if v_submission.id is null then
    raise exception 'production_feedback_submission_relationship_mismatch';
  end if;

  -- Documents owns its current stored status, immutable byte proof and path.
  -- The former attached/authority-feedback/... path predated its public port.
  select d.*
  into v_document
  from documents.get_document_v1(p_document_id,shareholder_register_filing.actor_v1()::text) d
  where d.id = p_document_id
    and d.company_id = p_company_id
    and d.income_year = v_submission.income_year
    and d.document_type = 'authority_feedback'
    and d.linked_to = 'production_filing_submission:' || p_submission_id::text
    and d.status = 'stored'
    and d.content_type = p_content_type
    and d.byte_length = p_byte_length
    and d.content_sha256 = p_sha256
    and d.created_by = v_submission.user_id
    and d.name ~ '^authority-feedback-[a-f0-9]{12}\.(xml|pdf|txt|bin)$';
  if v_document.id is null then
    raise exception 'production_feedback_document_relationship_mismatch';
  end if;

  insert into shareholder_register_filing.production_feedback_artifacts (
    company_id, submission_id, document_id, authority_reference,
    content_type, byte_length, sha256, classification
  ) values (
    p_company_id, p_submission_id, p_document_id, trim(p_authority_reference),
    p_content_type, p_byte_length, p_sha256, p_classification
  )
  on conflict (submission_id, sha256) do nothing
  returning * into v_artifact;

  if v_artifact.id is null then
    select a.*
    into v_artifact
    from shareholder_register_filing.production_feedback_artifacts a
    where a.submission_id = p_submission_id
      and a.sha256 = p_sha256;
  end if;
  return v_artifact;
end;
$function$
;

alter function shareholder_register_filing.record_production_feedback_artifact(uuid, uuid, uuid, text, text, bigint, text, text) owner to shareholder_register_filing_store_owner;

revoke all on function shareholder_register_filing.record_production_feedback_artifact(uuid, uuid, uuid, text, text, bigint, text, text) from public,anon,authenticated,service_role;

grant execute on function shareholder_register_filing.record_production_feedback_artifact(uuid, uuid, uuid, text, text, bigint, text, text) to shareholder_register_filing_executor;

CREATE OR REPLACE FUNCTION shareholder_register_filing.assert_fresh_production_owner_v1(target_company_id uuid)
 RETURNS uuid
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO ''
AS $function$
declare
  v_actor_id uuid := public.company_access_auth_uid_v1();
  v_claims jsonb := coalesce((select public.company_access_auth_jwt_v1()), '{}'::jsonb);
  v_mfa_verified_at timestamptz;
begin
  if v_actor_id is null
    or coalesce(v_claims ->> 'sub', '') <> v_actor_id::text
    or coalesce(v_claims ->> 'aal', '') <> 'aal2'
    or not public.company_access_is_accepted_owner_v1(target_company_id)
  then
    raise exception 'production_filing_fresh_owner_step_up_required';
  end if;

  if jsonb_typeof(v_claims -> 'amr') <> 'array' then
    raise exception 'production_filing_fresh_owner_step_up_required';
  end if;

  select to_timestamp((entry ->> 'timestamp')::double precision)
  into v_mfa_verified_at
  from jsonb_array_elements(v_claims -> 'amr') as entry
  where entry ->> 'method' in ('totp', 'mfa/totp', 'mfa/phone', 'mfa/webauthn')
    and entry ->> 'timestamp' ~ '^[0-9]{1,12}$'
  order by (entry ->> 'timestamp')::bigint desc
  limit 1;

  if v_mfa_verified_at is null
    or v_mfa_verified_at > now()
    or v_mfa_verified_at < now() - interval '15 minutes'
  then
    raise exception 'production_filing_fresh_owner_step_up_required';
  end if;
  return v_actor_id;
end;
$function$
;

alter function shareholder_register_filing.assert_fresh_production_owner_v1(uuid) owner to shareholder_register_filing_store_owner;

revoke all on function shareholder_register_filing.assert_fresh_production_owner_v1(uuid) from public,anon,authenticated,service_role;

alter policy rf151_approval_read on shareholder_register_filing.filing_approval_snapshots using(shareholder_register_filing.actor_v1() is not null and public.company_access_is_accepted_member_v1(company_id));
alter policy rf151_submission_read on shareholder_register_filing.production_filing_submissions using(shareholder_register_filing.actor_v1() is not null and public.company_access_is_accepted_member_v1(company_id));
alter policy rf151_artifact_read on shareholder_register_filing.production_feedback_artifacts using(shareholder_register_filing.actor_v1() is not null and public.company_access_is_accepted_owner_v1(company_id));

create function backend_system.rf_opening_quarantine_count_v1(p_company_id uuid,p_opening_ids uuid[]) returns bigint
language sql stable security definer set search_path='' as $function$
 select count(*) from shareholder_register_filing.migration_quarantine q
 where (q.family='opening_balance_setups' and q.record_id=any(p_opening_ids))
   or (q.family='opening_shareholders' and (q.original_row->>'setup_id')::uuid=any(p_opening_ids));
$function$;
revoke all on function backend_system.rf_opening_quarantine_count_v1(uuid,uuid[]) from public,anon,authenticated,service_role;
grant execute on function backend_system.rf_opening_quarantine_count_v1(uuid,uuid[]) to shareholder_register_filing_store_owner;
create function shareholder_register_filing.assert_opening_read_integrity_v1(p_company_id uuid,p_income_year integer) returns void
language plpgsql stable security definer set search_path='' as $function$
declare ids uuid[]; begin
 select array_agg(id) into ids from shareholder_register_filing.opening_balance_setups o
 where o.company_id=p_company_id and (p_income_year is null or o.income_year=p_income_year);
 if backend_system.rf_opening_quarantine_count_v1(p_company_id,coalesce(ids,'{}'::uuid[]))>0 then raise exception 'ledger_dependency_unavailable'; end if;
end; $function$;
alter function shareholder_register_filing.assert_opening_read_integrity_v1(uuid,integer) owner to shareholder_register_filing_store_owner;
revoke all on function shareholder_register_filing.assert_opening_read_integrity_v1(uuid,integer) from public,anon,authenticated,service_role;

CREATE OR REPLACE FUNCTION shareholder_register_filing.record_opening_snapshot_v1(p_company_id uuid, p_income_year integer, p_share_capital numeric, p_share_count integer, p_nominal_value numeric, p_shareholders jsonb, p_verified_subject text)
 RETURNS uuid
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO ''
AS $function$
declare
  v_actor_id uuid := public.company_access_auth_uid_v1();
  v_setup_id uuid := pg_catalog.gen_random_uuid();
  v_shareholder jsonb;
  v_name text;
  v_kind text;
  v_national_id text;
  v_org_number text;
  v_shares integer;
  v_total_shares bigint := 0;
begin
  if v_actor_id is null
    or p_verified_subject is null
    or p_verified_subject !~ '^[0-9a-fA-F-]{36}$'
    or v_actor_id is distinct from p_verified_subject::uuid
  then
    raise exception 'ledger_forbidden';
  end if;
  if p_company_id is null
    or p_income_year not between 2000 and 2100
    or p_share_capital is null or p_share_capital < 0
    or p_share_capital <> pg_catalog.round(p_share_capital, 2)
    or p_share_count is null or p_share_count <= 0
    or p_nominal_value is null or p_nominal_value <= 0
    or p_nominal_value <> pg_catalog.round(p_nominal_value, 2)
    or p_share_capital <> pg_catalog.round(p_share_count * p_nominal_value, 2)
    or pg_catalog.jsonb_typeof(p_shareholders) is distinct from 'array'
    or pg_catalog.jsonb_array_length(p_shareholders) not between 1 and 100
  then
    raise exception 'ledger_invalid_input';
  end if;
  if not public.company_access_is_accepted_member_v1(p_company_id) then
    raise exception 'ledger_not_found';
  end if;
  if not public.company_access_is_accepted_owner_v1(p_company_id) then
    raise exception 'ledger_forbidden';
  end if;
  -- Every ledger writer takes the company-year lock before the eligibility
  -- recheck lock. Keeping this order identical to ledger.post_entry prevents
  -- a new-year workflow and another posting from deadlocking each other.
  perform ledger.lock_company_year_v1(p_company_id, p_income_year);
  if coalesce(public.company_access_auth_jwt_v1() ->> 'aal', '') <> 'aal2'
    or not public.company_access_company_year_allows_consequential_v1(
      p_company_id, p_income_year
    )
  then
    raise exception 'ledger_company_year_not_admitted';
  end if;

  if exists (
    select 1 from shareholder_register_filing.opening_balance_setups setup
    where setup.company_id = p_company_id
      and setup.income_year = p_income_year
  ) then
    raise exception 'ledger_opening_already_exists';
  end if;

  for v_shareholder in
    select value from pg_catalog.jsonb_array_elements(p_shareholders)
  loop
    if pg_catalog.jsonb_typeof(v_shareholder) is distinct from 'object'
      or pg_catalog.jsonb_typeof(v_shareholder -> 'name') is distinct from 'string'
      or pg_catalog.jsonb_typeof(v_shareholder -> 'shareholderKind')
        is distinct from 'string'
      or pg_catalog.jsonb_typeof(v_shareholder -> 'shareCount')
        is distinct from 'number'
      or (v_shareholder ->> 'shareCount') !~ '^[0-9]+$'
    then
      raise exception 'ledger_invalid_input';
    end if;
    v_name := pg_catalog.btrim(v_shareholder ->> 'name');
    v_kind := v_shareholder ->> 'shareholderKind';
    v_national_id := nullif(pg_catalog.btrim(
      coalesce(v_shareholder ->> 'nationalId', '')
    ), '');
    v_org_number := nullif(pg_catalog.btrim(
      coalesce(v_shareholder ->> 'orgNumber', '')
    ), '');
    v_shares := (v_shareholder ->> 'shareCount')::integer;
    if v_name = '' or pg_catalog.char_length(v_name) > 255
      or v_kind not in ('norwegian_person', 'norwegian_company')
      or v_shares < 0
      or (v_kind = 'norwegian_person' and coalesce(v_national_id, '') !~ '^[0-9]{11}$')
      or (v_kind = 'norwegian_company' and coalesce(v_org_number, '') !~ '^[0-9]{9}$')
    then
      raise exception 'ledger_invalid_input';
    end if;
    v_total_shares := v_total_shares + v_shares;
  end loop;
  if v_total_shares <> p_share_count then
    raise exception 'ledger_invalid_input';
  end if;

  insert into shareholder_register_filing.opening_balance_setups (
    id, company_id, income_year, share_capital,
    share_count, nominal_value, created_by
  ) values (
    v_setup_id, p_company_id, p_income_year, p_share_capital,
    p_share_count, p_nominal_value, v_actor_id
  );
  insert into shareholder_register_filing.opening_shareholders (
    setup_id, company_id, name, shareholder_kind, national_id,
    org_number, share_count, created_by
  )
  select
    v_setup_id,
    p_company_id,
    pg_catalog.btrim(value ->> 'name'),
    value ->> 'shareholderKind',
    nullif(pg_catalog.btrim(coalesce(value ->> 'nationalId', '')), ''),
    nullif(pg_catalog.btrim(coalesce(value ->> 'orgNumber', '')), ''),
    (value ->> 'shareCount')::integer,
    v_actor_id
  from pg_catalog.jsonb_array_elements(p_shareholders);
  return v_setup_id;
end;
$function$
;

alter function shareholder_register_filing.record_opening_snapshot_v1(uuid,integer,numeric,integer,numeric,jsonb,text) owner to shareholder_register_filing_store_owner;

revoke all on function shareholder_register_filing.record_opening_snapshot_v1(uuid,integer,numeric,integer,numeric,jsonb,text) from public,anon,authenticated,service_role;
grant execute on function shareholder_register_filing.record_opening_snapshot_v1(uuid,integer,numeric,integer,numeric,jsonb,text) to ledger_workflow_executor,ledger_workflow_store_owner;
grant usage on schema ledger to shareholder_register_filing_store_owner;
grant execute on function ledger.lock_company_year_v1(uuid,integer) to shareholder_register_filing_store_owner;
create function shareholder_register_filing.read_opening_snapshots_v1(p_company_id uuid,p_income_year integer,p_verified_subject text)
returns setof shareholder_register_filing.opening_balance_setups language plpgsql stable security definer set search_path='' as $function$
begin
 if p_verified_subject is distinct from shareholder_register_filing.assert_member_v1(p_company_id)::text then raise exception 'ledger_forbidden'; end if;
 perform shareholder_register_filing.assert_opening_read_integrity_v1(p_company_id,p_income_year);
 return query select o.* from shareholder_register_filing.opening_balance_setups o where o.company_id=p_company_id
   and (p_income_year is null or o.income_year=p_income_year) order by o.created_at desc,o.id desc;
end; $function$;
create function shareholder_register_filing.read_opening_shareholders_v1(p_company_id uuid,p_income_year integer,p_verified_subject text)
returns setof shareholder_register_filing.opening_shareholders language plpgsql stable security definer set search_path='' as $function$
begin
 if p_verified_subject is distinct from shareholder_register_filing.assert_member_v1(p_company_id)::text then raise exception 'ledger_forbidden'; end if;
 perform shareholder_register_filing.assert_opening_read_integrity_v1(p_company_id,p_income_year);
 return query select h.* from shareholder_register_filing.opening_shareholders h join shareholder_register_filing.opening_balance_setups o on o.id=h.setup_id
 where o.company_id=p_company_id and (p_income_year is null or o.income_year=p_income_year) order by h.id;
end; $function$;
alter function shareholder_register_filing.read_opening_snapshots_v1(uuid,integer,text) owner to shareholder_register_filing_store_owner;
alter function shareholder_register_filing.read_opening_shareholders_v1(uuid,integer,text) owner to shareholder_register_filing_store_owner;
revoke all on function shareholder_register_filing.read_opening_snapshots_v1(uuid,integer,text),shareholder_register_filing.read_opening_shareholders_v1(uuid,integer,text) from public,anon,authenticated,service_role;
grant execute on function shareholder_register_filing.read_opening_snapshots_v1(uuid,integer,text),shareholder_register_filing.read_opening_shareholders_v1(uuid,integer,text) to shareholder_register_filing_executor,ledger_workflow_store_owner,ledger_workflow_executor;

-- Runtime can lock visible source rows but cannot update them directly.
do $permissions$ declare n text; r record; review_access text; begin
 foreach n in array array['opening_balance_setups','opening_shareholders','filing_previews','filing_submissions','filing_overrides','filing_review_comments','authority_permissions','authority_test_runs'] loop
  execute pg_catalog.format('grant select,update on shareholder_register_filing.%I to shareholder_register_filing_executor',n);
  execute pg_catalog.format('create policy rf151_executor_lock on shareholder_register_filing.%I for update to shareholder_register_filing_executor using(public.company_access_is_accepted_member_v1(company_id)) with check(false)',n);
  execute pg_catalog.format('grant select,insert,update on public.%I to shareholder_register_filing_store_owner',n);
  review_access:=case when n='filing_review_comments' then 'public.company_access_can_review_filing_v1(company_id)' else 'public.company_access_is_accepted_owner_v1(company_id)' end;
  execute pg_catalog.format('create policy rf151_backend_overlap on public.%I for all to shareholder_register_filing_store_owner using(shareholder_register_filing.phase_v1()=''legacy_overlap'' and %s) with check(shareholder_register_filing.phase_v1()=''legacy_overlap'' and %s)',n,review_access,review_access);
 end loop;
 -- A reviewer may create RF comments, but the acknowledge routine still requires owner.
 create policy rf151_review_write on shareholder_register_filing.filing_review_comments for all to shareholder_register_filing_store_owner
 using(public.company_access_can_review_filing_v1(company_id)) with check(public.company_access_can_review_filing_v1(company_id));
 for r in select p.oid::regprocedure signature from pg_catalog.pg_proc p join pg_catalog.pg_namespace n on n.oid=p.pronamespace
   where n.nspname='shareholder_register_filing' and p.proname in ('assert_member_v1','assert_preparation_access_v1','insert_preparation_row_v1','record_preview_v1','record_override_v1','add_review_comment_v1','acknowledge_review_comment_v1','confirm_filing_permission_v1','record_test_evidence_v1','record_simulation_v1') loop
  execute pg_catalog.format('alter function %s owner to shareholder_register_filing_store_owner',r.signature);
  execute pg_catalog.format('revoke all on function %s from public,anon,authenticated,service_role',r.signature);
  if r.signature::text not like '%insert_preparation_row_v1%' then
   execute pg_catalog.format('grant execute on function %s to shareholder_register_filing_executor',r.signature);
  end if;
 end loop;
end; $permissions$;

create function shareholder_register_filing.opening_ids_v1(p_company_id uuid,p_income_year integer) returns uuid[]
language plpgsql stable security definer set search_path='' as $function$
begin
 perform shareholder_register_filing.assert_member_v1(p_company_id);
 return coalesce((select pg_catalog.array_agg(id) from shareholder_register_filing.opening_balance_setups where company_id=p_company_id and income_year=p_income_year),'{}'::uuid[]);
end; $function$;
alter function shareholder_register_filing.opening_ids_v1(uuid,integer) owner to shareholder_register_filing_store_owner;
revoke all on function shareholder_register_filing.opening_ids_v1(uuid,integer) from public,anon,authenticated,service_role;
grant execute on function shareholder_register_filing.opening_ids_v1(uuid,integer) to postgres;
-- Runtime receives only the immutable scoped attestation; it cannot fabricate it.
create function shareholder_register_filing.read_migration_inventory_v1(p_company_id uuid,p_income_year integer)
returns jsonb language plpgsql stable security definer set search_path='' as $function$
declare result jsonb; begin
 perform shareholder_register_filing.assert_member_v1(p_company_id);
 select pg_catalog.jsonb_build_object('version',s.version,'reference',s.version||':'||p_company_id||':'||p_income_year,
   'source_revision',s.source_revision,'reconciled',(select count(*) from pg_catalog.jsonb_object_keys(s.reconciliation))=12,
   'family_counts',pg_catalog.jsonb_object_agg(i.family,i.row_count),'family_digests',pg_catalog.jsonb_object_agg(i.family,i.row_digest),
   'quarantined_count',(select count(*) from shareholder_register_filing.migration_quarantine q where (q.company_id=p_company_id and (q.income_year=p_income_year or q.income_year is null)) or (q.original_row->>'setup_id')::uuid=any(shareholder_register_filing.opening_ids_v1(p_company_id,p_income_year))))
 into result from shareholder_register_filing.migration_state s cross join shareholder_register_filing.migration_inventory i
 where s.singleton and i.company_id=p_company_id and i.income_year=p_income_year group by s.version,s.source_revision,s.reconciliation;
 return result;
end; $function$;
revoke all on function shareholder_register_filing.read_migration_inventory_v1(uuid,integer) from public,anon,authenticated,service_role;
grant execute on function shareholder_register_filing.read_migration_inventory_v1(uuid,integer) to shareholder_register_filing_executor;

-- Temporary backend-system coordination; removed by the final RF contract.
-- The canonical Ledger function receives exact old input, never a posting-derived balance.
set local role ledger_store_owner;
create policy rf151_legacy_bank_capture on ledger.opening_bank_inputs for insert to ledger_store_owner
with check(pg_catalog.pg_trigger_depth()>0);
create policy rf151_legacy_bank_capture_read on ledger.opening_bank_inputs for select to ledger_store_owner
using(pg_catalog.pg_trigger_depth()>0);
create function ledger.capture_legacy_opening_bank_input_v1(p_snapshot_id uuid,p_company_id uuid,p_income_year integer,p_bank numeric,p_recorded_by uuid,p_recorded_at timestamptz)
returns void language plpgsql security definer set search_path='' as $function$
declare r ledger.opening_bank_inputs%rowtype; begin
 if pg_catalog.pg_trigger_depth()=0 then raise exception 'ledger_forbidden'; end if;
 insert into ledger.opening_bank_inputs values(p_snapshot_id,p_company_id,p_income_year,p_bank,p_recorded_by,p_recorded_at) on conflict do nothing;
 select * into r from ledger.opening_bank_inputs where snapshot_id=p_snapshot_id;
 if r.snapshot_id is null or (r.company_id,r.income_year,r.bank_balance_nok,r.recorded_by,r.recorded_at)
    is distinct from (p_company_id,p_income_year,p_bank,p_recorded_by,p_recorded_at)
 then raise exception 'rf1086_legacy_bank_projection_conflict'; end if;
end; $function$;
revoke all on function ledger.capture_legacy_opening_bank_input_v1(uuid,uuid,integer,numeric,uuid,timestamptz) from public,anon,authenticated,service_role;
grant execute on function ledger.capture_legacy_opening_bank_input_v1(uuid,uuid,integer,numeric,uuid,timestamptz),ledger.read_opening_bank_inputs_v1(uuid,integer,text) to postgres;
reset role;
create function backend_system.capture_legacy_rf_opening_bank_v1() returns trigger
language plpgsql security definer set search_path='' as $function$
begin
 if shareholder_register_filing.phase_v1()='legacy_overlap' then
  perform ledger.capture_legacy_opening_bank_input_v1(new.id,new.company_id,new.income_year,new.bank_balance,new.created_by,new.created_at);
 end if;
 return null;
end; $function$;
create trigger rf151_capture_legacy_bank after insert on public.opening_balance_setups
for each row execute function backend_system.capture_legacy_rf_opening_bank_v1();

create function backend_system.sync_rf_opening_projection_v1() returns trigger
language plpgsql security definer set search_path='' as $function$
declare company uuid; setup uuid; o record; bank record; h record; current_row jsonb; expected_row jsonb; actor text;
begin
 if shareholder_register_filing.phase_v1()='contracted' then return null; end if;
 if tg_table_name='opening_balance_setups' then company:=new.company_id; setup:=new.id;
 elsif tg_table_name='opening_shareholders' then company:=new.company_id; setup:=new.setup_id;
 else raise exception 'rf1086_overlap_trigger_invalid'; end if;
 -- Old-row copying already retains its own authoritative projection and original bank input.
 if shareholder_register_filing.phase_v1()='legacy_overlap' and exists(select 1 from public.opening_balance_setups p where p.id=setup)
 then return null; end if;
 actor:=shareholder_register_filing.verified_actor_v1()::text;
 select * into o from shareholder_register_filing.read_opening_snapshots_v1(company,null,actor) x where x.id=setup;
 if o.id is null then raise exception 'rf1086_opening_projection_missing'; end if;
 select * into bank from ledger.read_opening_bank_inputs_v1(company,o.income_year,actor) b where b.snapshot_id=setup;
 if bank.snapshot_id is null or bank.recorded_by<>o.created_by or bank.recorded_at<>o.created_at
 then raise exception 'rf1086_opening_bank_projection_missing'; end if;
 expected_row:=pg_catalog.to_jsonb(o)||pg_catalog.jsonb_build_object('bank_balance',bank.bank_balance_nok);
 select pg_catalog.to_jsonb(p) into current_row from public.opening_balance_setups p where p.id=setup;
 if current_row is not null and current_row is distinct from expected_row then raise exception 'rf1086_opening_projection_conflict'; end if;
 if current_row is null then
  insert into public.opening_balance_setups select * from pg_catalog.jsonb_populate_record(null::public.opening_balance_setups,expected_row);
 end if;
 for h in select * from shareholder_register_filing.read_opening_shareholders_v1(company,o.income_year,actor) x where x.setup_id=setup loop
  select pg_catalog.to_jsonb(p) into current_row from public.opening_shareholders p where p.id=h.id;
  if current_row is not null and current_row is distinct from pg_catalog.to_jsonb(h) then raise exception 'rf1086_opening_projection_conflict'; end if;
  if current_row is null then insert into public.opening_shareholders select * from pg_catalog.jsonb_populate_record(null::public.opening_shareholders,pg_catalog.to_jsonb(h)); end if;
 end loop;
 return null;
end; $function$;
revoke all on function backend_system.sync_rf_opening_projection_v1(),backend_system.capture_legacy_rf_opening_bank_v1() from public,anon,authenticated,service_role;
grant execute on function shareholder_register_filing.read_opening_snapshots_v1(uuid,integer,text),shareholder_register_filing.read_opening_shareholders_v1(uuid,integer,text) to postgres;
create constraint trigger rf151_opening_projection after insert or update on shareholder_register_filing.opening_balance_setups
 deferrable initially deferred for each row execute function backend_system.sync_rf_opening_projection_v1();
create constraint trigger rf151_shareholder_projection after insert or update on shareholder_register_filing.opening_shareholders
 deferrable initially deferred for each row execute function backend_system.sync_rf_opening_projection_v1();

grant execute on function public.company_access_has_open_support_case_v1(uuid,uuid,text),public.company_access_current_support_case_id_v1() to shareholder_register_filing_store_owner;
create function shareholder_register_filing.read_support_filing_history_v1(p_company_id uuid,p_case_id uuid)
returns jsonb language plpgsql stable security definer set search_path='' as $function$
begin
 if p_case_id is distinct from public.company_access_current_support_case_id_v1() then return '{"filing_approval_snapshots":[],"production_filing_submissions":[],"production_filing_events":[],"production_feedback_artifacts":[],"authority_permissions":[],"authority_test_runs":[]}'::jsonb; end if;
 return pg_catalog.jsonb_build_object('filing_approval_snapshots',case when public.company_access_has_open_support_case_v1(p_case_id,p_company_id,'production') then coalesce((
        select pg_catalog.jsonb_agg(pg_catalog.jsonb_build_object(
          'id', f.id, 'company_id', f.company_id, 'income_year', f.income_year,
          'obligation', f.obligation, 'case_profile', f.case_profile,
          'adapter_version', f.adapter_version, 'payload_hash', f.payload_hash,
          'manifest_hash', f.manifest_hash, 'approved_at', f.approved_at,
          'invalidated_at', f.invalidated_at
        ) order by f.approved_at desc)
        from shareholder_register_filing.filing_approval_snapshots f
        where f.company_id = p_company_id
      ), '[]'::jsonb) else '[]'::jsonb end,
'production_filing_submissions',case when public.company_access_has_open_support_case_v1(p_case_id,p_company_id,'production') then coalesce((
        select pg_catalog.jsonb_agg(pg_catalog.jsonb_build_object(
          'id', p.id, 'company_id', p.company_id, 'income_year', p.income_year,
          'obligation', p.obligation, 'case_profile', p.case_profile,
          'adapter_version', p.adapter_version, 'status', p.status,
          'failure_class', p.failure_class, 'created_at', p.created_at,
          'updated_at', p.updated_at
        ) order by p.updated_at desc)
        from shareholder_register_filing.production_filing_submissions p
        where p.company_id = p_company_id
      ), '[]'::jsonb) else '[]'::jsonb end,
'production_filing_events',case when public.company_access_has_open_support_case_v1(p_case_id,p_company_id,'production') then coalesce((
        select pg_catalog.jsonb_agg(pg_catalog.jsonb_build_object(
          'id', e.id, 'submission_id', e.submission_id,
          'operation_name', e.operation_name, 'operation_state', e.operation_state,
          'attempt', e.attempt, 'failure_class', e.failure_class,
          'resulting_status', e.resulting_status, 'created_at', e.created_at
        ) order by e.created_at desc)
        from shareholder_register_filing.production_filing_events e
        join shareholder_register_filing.production_filing_submissions p on p.id = e.submission_id
        where p.company_id = p_company_id
      ), '[]'::jsonb) else '[]'::jsonb end,
'production_feedback_artifacts',case when public.company_access_has_open_support_case_v1(p_case_id,p_company_id,'documents') then coalesce((
        select pg_catalog.jsonb_agg(pg_catalog.jsonb_build_object(
          'id', p.id, 'company_id', p.company_id, 'submission_id', p.submission_id,
          'document_id', p.document_id, 'content_type', p.content_type,
          'byte_length', p.byte_length, 'sha256', p.sha256,
          'retrieved_at', p.retrieved_at, 'classification', p.classification
        ) order by p.retrieved_at desc)
        from shareholder_register_filing.production_feedback_artifacts p
        where p.company_id = p_company_id
      ), '[]'::jsonb) else '[]'::jsonb end,
'authority_permissions',case when public.company_access_has_open_support_case_v1(p_case_id,p_company_id,'authority') then coalesce((
        select pg_catalog.jsonb_agg(pg_catalog.jsonb_build_object(
          'id', a.id, 'company_id', a.company_id, 'obligation', a.obligation,
          'production_enabled', a.production_enabled, 'updated_at', a.updated_at
        )) from shareholder_register_filing.authority_permissions a
        where a.company_id = p_company_id
      ), '[]'::jsonb) else '[]'::jsonb end,
'authority_test_runs',case when public.company_access_has_open_support_case_v1(p_case_id,p_company_id,'authority') then coalesce((
        select pg_catalog.jsonb_agg(pg_catalog.jsonb_build_object(
          'id', a.id, 'company_id', a.company_id, 'obligation', a.obligation,
          'environment', a.environment, 'status', a.status,
          'test_reference', a.test_reference, 'recorded_at', a.recorded_at
        ) order by a.recorded_at desc)
        from shareholder_register_filing.authority_test_runs a where a.company_id = p_company_id
      ), '[]'::jsonb) else '[]'::jsonb end);
end; $function$;
alter function shareholder_register_filing.read_support_filing_history_v1(uuid,uuid) owner to shareholder_register_filing_store_owner;
revoke all on function shareholder_register_filing.read_support_filing_history_v1(uuid,uuid) from public,anon,authenticated,service_role;
grant usage on schema shareholder_register_filing to company_access_executor;
grant execute on function shareholder_register_filing.read_support_filing_history_v1(uuid,uuid) to company_access_executor;

create policy rf151_support_read on shareholder_register_filing.filing_approval_snapshots for select to shareholder_register_filing_store_owner using(public.company_access_has_open_support_case_v1(public.company_access_current_support_case_id_v1(),company_id,'production'));

create policy rf151_support_read on shareholder_register_filing.production_filing_submissions for select to shareholder_register_filing_store_owner using(public.company_access_has_open_support_case_v1(public.company_access_current_support_case_id_v1(),company_id,'production'));

create policy rf151_support_read on shareholder_register_filing.production_filing_events for select to shareholder_register_filing_store_owner using(exists(select 1 from shareholder_register_filing.production_filing_submissions s where s.id=submission_id and public.company_access_has_open_support_case_v1(public.company_access_current_support_case_id_v1(),s.company_id,'production')));

create policy rf151_support_read on shareholder_register_filing.production_feedback_artifacts for select to shareholder_register_filing_store_owner using(public.company_access_has_open_support_case_v1(public.company_access_current_support_case_id_v1(),company_id,'documents'));

create policy rf151_support_read on shareholder_register_filing.authority_permissions for select to shareholder_register_filing_store_owner using(public.company_access_has_open_support_case_v1(public.company_access_current_support_case_id_v1(),company_id,'authority'));

create policy rf151_support_read on shareholder_register_filing.authority_test_runs for select to shareholder_register_filing_store_owner using(public.company_access_has_open_support_case_v1(public.company_access_current_support_case_id_v1(),company_id,'authority'));

CREATE OR REPLACE FUNCTION public.company_access_read_support_case(p_case_id uuid)
 RETURNS TABLE(case_id uuid, company_id uuid, scopes text[], resources jsonb)
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO ''
AS $function$
declare
  v_actor_id uuid := public.company_access_auth_uid_v1();
  v_grant public.support_access_grants%rowtype;
begin
  if p_case_id is null or v_actor_id is null
    or not public.company_access_is_active_operator_v1()
    or not public.company_access_has_fresh_mfa_v1()
  then
    raise exception 'support_access_not_available' using errcode = 'P0001';
  end if;
  select g.* into v_grant from public.support_access_grants g
  where g.case_id = p_case_id
    and g.operator_user_id = v_actor_id
    and g.revoked_at is null
    and pg_catalog.statement_timestamp() >= g.starts_at
    and pg_catalog.statement_timestamp() < g.expires_at;
  if not found or not exists (
    select 1 from public.support_case_openings o
    where o.actor_id = v_actor_id and o.case_id = p_case_id
      and o.company_id = v_grant.company_id
  ) then
    raise exception 'support_access_not_available' using errcode = 'P0001';
  end if;
  perform pg_catalog.set_config('talli.support_case_id', p_case_id::text, true);

  return query select v_grant.case_id, v_grant.company_id, v_grant.scopes,
    pg_catalog.jsonb_build_object(
      'companies', coalesce((
        select pg_catalog.jsonb_agg(pg_catalog.jsonb_build_object(
          'id', c.id, 'org_number', c.org_number, 'name', c.name,
          'entity_type', c.entity_type, 'address', c.address,
          'postal_code', c.postal_code, 'city', c.city,
          'status_text', c.status_text, 'source', c.source,
          'created_by', c.created_by,
          'identity_confirmed_at', c.identity_confirmed_at,
          'identity_locked_at', c.identity_locked_at, 'created_at', c.created_at
        )) from public.companies c where c.id = v_grant.company_id
      ), '[]'::jsonb),
      'audit_events', coalesce((
        select pg_catalog.jsonb_agg(item order by item.created_at desc) from (
          select a.id, a.company_id, a.actor_id, a.category, a.action,
            a.message, a.created_at
          from public.audit_events a where a.company_id = v_grant.company_id
          order by a.created_at desc limit 50
        ) item
      ), '[]'::jsonb),
      'company_cancellations', coalesce((
        select pg_catalog.jsonb_agg(pg_catalog.jsonb_build_object(
          'id', c.id, 'company_id', c.company_id, 'status', c.status,
          'reason', c.reason, 'evidence', c.evidence,
          'requested_by', c.requested_by, 'requested_at', c.requested_at,
          'reviewed_by', c.reviewed_by, 'reviewed_at', c.reviewed_at,
          'deleted_by', c.deleted_by, 'deleted_at', c.deleted_at,
          'updated_at', c.updated_at
        )) from public.company_cancellations c
        where c.company_id = v_grant.company_id
      ), '[]'::jsonb),
      'filing_submissions', coalesce((
        select pg_catalog.jsonb_agg(pg_catalog.jsonb_build_object(
          'id', f.id, 'company_id', f.company_id, 'income_year', f.income_year,
          'filing', f.filing, 'status', f.status, 'updated_at', f.updated_at
        ) order by f.updated_at desc)
        from public.filing_submissions f where f.company_id = v_grant.company_id
      ), '[]'::jsonb),
      'filing_readiness_snapshots', coalesce((
        select pg_catalog.jsonb_agg(pg_catalog.jsonb_build_object(
          'id', f.id, 'company_id', f.company_id, 'income_year', f.income_year,
          'obligation', f.obligation, 'status', f.status, 'ready', f.ready,
          'hard_blocks', f.hard_blocks, 'warnings', f.warnings,
          'updated_at', f.updated_at
        )) from public.filing_readiness_snapshots f
        where f.company_id = v_grant.company_id
      ), '[]'::jsonb),
      'billing_accounts', coalesce((
        select pg_catalog.jsonb_agg(pg_catalog.jsonb_build_object(
          'company_id', b.company_id, 'pricing_plan', b.pricing_plan,
          'subscription_active', b.subscription_active,
          'filing_package_paid', b.filing_package_paid,
          'refund_eligible', b.refund_eligible,
          'refund_completed', b.refund_completed,
          'refund_provider_ref', b.refund_provider_ref,
          'updated_at', b.updated_at
        )) from billing.billing_accounts b where b.company_id = v_grant.company_id
      ), '[]'::jsonb),
      'billing_payment_events', coalesce((
        select pg_catalog.jsonb_agg(pg_catalog.jsonb_build_object(
          'id', b.id, 'company_id', b.company_id, 'provider', b.provider,
          'kind', b.kind, 'status', b.status, 'amount_nok', b.amount_nok,
          'created_at', b.created_at
        )) from billing.billing_payment_events b
        where b.company_id = v_grant.company_id
      ), '[]'::jsonb),
      'authority_permissions', (
        with legacy as (
          select item, ordinal::bigint as position
          from pg_catalog.jsonb_array_elements(coalesce((
        select pg_catalog.jsonb_agg(pg_catalog.jsonb_build_object(
          'id', a.id, 'company_id', a.company_id, 'obligation', a.obligation,
          'production_enabled', a.production_enabled, 'updated_at', a.updated_at
        )) from public.authority_permissions a
        where a.company_id = v_grant.company_id
      ), '[]'::jsonb)) with ordinality as entries(item,ordinal)
        ), current_rf as (
          select item, ordinal::bigint as position
          from pg_catalog.jsonb_array_elements(
            shareholder_register_filing.read_support_filing_history_v1(v_grant.company_id,p_case_id)->'authority_permissions'
          ) with ordinality as entries(item,ordinal)
        ), combined as (
          select coalesce(c.item,l.item) as item,l.position
          from legacy l left join current_rf c on c.item->>'id'=l.item->>'id'
          union all
          select c.item,(select count(*) from legacy)+c.position
          from current_rf c where not exists(select 1 from legacy l where l.item->>'id'=c.item->>'id')
        )
        select coalesce(pg_catalog.jsonb_agg(item order by position),'[]'::jsonb) from combined
      ),
      'authority_test_runs', (
        with legacy as (
          select item, ordinal::bigint as position
          from pg_catalog.jsonb_array_elements(coalesce((
        select pg_catalog.jsonb_agg(pg_catalog.jsonb_build_object(
          'id', a.id, 'company_id', a.company_id, 'obligation', a.obligation,
          'environment', a.environment, 'status', a.status,
          'test_reference', a.test_reference, 'recorded_at', a.recorded_at
        ) order by a.recorded_at desc)
        from public.authority_test_runs a where a.company_id = v_grant.company_id
      ), '[]'::jsonb)) with ordinality as entries(item,ordinal)
        ), current_rf as (
          select item, ordinal::bigint as position
          from pg_catalog.jsonb_array_elements(
            shareholder_register_filing.read_support_filing_history_v1(v_grant.company_id,p_case_id)->'authority_test_runs'
          ) with ordinality as entries(item,ordinal)
        ), combined as (
          select coalesce(c.item,l.item) as item,l.position
          from legacy l left join current_rf c on c.item->>'id'=l.item->>'id'
          union all
          select c.item,(select count(*) from legacy)+c.position
          from current_rf c where not exists(select 1 from legacy l where l.item->>'id'=c.item->>'id')
        )
        select coalesce(pg_catalog.jsonb_agg(item order by (item->>'recorded_at')::timestamptz desc, position),'[]'::jsonb) from combined
      ),
      'system_user_requests', authority_connections.read_support_requests_v1(v_grant.company_id,p_case_id),
      'production_pilot_entitlements', coalesce((
        select pg_catalog.jsonb_agg(pg_catalog.jsonb_build_object(
          'id', p.id, 'company_id', p.company_id, 'user_id', p.user_id,
          'income_year', p.income_year, 'obligation', p.obligation,
          'case_profile', p.case_profile, 'status', p.status,
          'starts_at', p.starts_at, 'expires_at', p.expires_at,
          'updated_at', p.updated_at
        ) order by p.updated_at desc)
        from billing.production_pilot_entitlements p
        where p.company_id = v_grant.company_id
      ), '[]'::jsonb),
      'filing_approval_snapshots', shareholder_register_filing.read_support_filing_history_v1(v_grant.company_id,p_case_id)->'filing_approval_snapshots',
      'production_filing_submissions', shareholder_register_filing.read_support_filing_history_v1(v_grant.company_id,p_case_id)->'production_filing_submissions',
      'production_filing_events', shareholder_register_filing.read_support_filing_history_v1(v_grant.company_id,p_case_id)->'production_filing_events',
      'production_feedback_artifacts', shareholder_register_filing.read_support_filing_history_v1(v_grant.company_id,p_case_id)->'production_feedback_artifacts',
      'documents', coalesce((
        select pg_catalog.jsonb_agg(pg_catalog.jsonb_build_object(
          'id', d.id, 'company_id', d.company_id, 'income_year', d.income_year,
          'document_type', d.document_type, 'name', d.name,
          'linked_to', d.linked_to, 'status', d.status,
          'retention_years', d.retention_years, 'storage_key', d.storage_key,
          'created_at', d.created_at
        ) order by d.created_at desc)
        from public.documents d where d.company_id = v_grant.company_id
      ), '[]'::jsonb),
      'storage_objects', coalesce((
        select pg_catalog.jsonb_agg(pg_catalog.jsonb_build_object(
          'id', s.id, 'bucket_id', s.bucket_id, 'name', s.name,
          'created_at', s.created_at
        ) order by s.created_at desc)
        from storage.objects s
        where public.company_access_support_storage_company_id_v1(s.name)
          = v_grant.company_id
      ), '[]'::jsonb),
      'company_deletion_reviews', coalesce((
        select pg_catalog.jsonb_agg(pg_catalog.jsonb_build_object(
          'id', d.id, 'cancellation_id', d.cancellation_id,
          'company_id', d.company_id, 'decision', d.decision,
          'evidence_reference', d.evidence_reference,
          'reviewed_at', d.reviewed_at, 'support_case_id', d.support_case_id
        )) from public.company_deletion_reviews d
        where d.company_id = v_grant.company_id
      ), '[]'::jsonb)
    );
end;
$function$
;

create function shareholder_register_filing.has_document_reference_v1(p_document_id uuid) returns boolean
language sql stable security definer set search_path='' as $function$
 select exists(select 1 from shareholder_register_filing.filing_submissions item
   where coalesce(item.feedback_document_ids,'[]'::jsonb) @> pg_catalog.jsonb_build_array(p_document_id::text)
     or item.receipt_id=p_document_id::text)
 or exists(select 1 from shareholder_register_filing.production_feedback_artifacts item where item.document_id=p_document_id);
$function$;
alter function shareholder_register_filing.has_document_reference_v1(uuid) owner to shareholder_register_filing_store_owner;
revoke all on function shareholder_register_filing.has_document_reference_v1(uuid) from public,anon,authenticated,service_role;
grant execute on function shareholder_register_filing.has_document_reference_v1(uuid) to documents_store_owner,postgres;
grant usage on schema shareholder_register_filing to documents_store_owner;
create policy rf151_documents_reference_read on shareholder_register_filing.filing_submissions for select to shareholder_register_filing_store_owner
using(pg_catalog.current_setting('role',true)='documents_executor');
create policy rf151_documents_reference_read on shareholder_register_filing.production_feedback_artifacts for select to shareholder_register_filing_store_owner
using(pg_catalog.current_setting('role',true)='documents_executor');

CREATE OR REPLACE FUNCTION documents.has_evidence_references_v1(p_document_id uuid)
 RETURNS boolean
 LANGUAGE plpgsql
 STABLE SECURITY DEFINER
 SET search_path TO ''
AS $function$
declare
  v_corporate_linked boolean := false;
  v_investment_linked boolean := false;
begin
  if pg_catalog.to_regclass('public.corporate_document_artifacts') is not null then
    execute $query$
      select exists (
        select 1 from public.corporate_document_artifacts item
        where item.document_id=$1
      )
    $query$ into v_corporate_linked using p_document_id;
  end if;
  if pg_catalog.to_regclass('investments.source_fact_registry') is not null then
    execute $query$
      select exists (
        select 1 from investments.source_fact_registry item
        where item.source_capability='DOCUMENTS'
          and item.source_record_id=$1
      )
    $query$ into v_investment_linked using p_document_id;
  end if;
  return exists (
      select 1 from documents.evidence_references item
      where item.document_id=p_document_id
    )
    or exists (
      select 1 from public.holding_actions item
      where item.document_id=p_document_id
    )
    or v_corporate_linked
    or exists (
      select 1 from public.filing_submissions item
      where coalesce(item.feedback_document_ids,'[]'::jsonb)
              @> pg_catalog.jsonb_build_array(p_document_id::text)
         or item.receipt_id=p_document_id::text
    )
    or shareholder_register_filing.has_document_reference_v1(p_document_id)
    or v_investment_linked
    or exists (
      select 1 from public.ledger_entries item
      join public.documents document on document.id=p_document_id
      where item.company_id=document.company_id
        and pg_catalog.strpos(item.memo, p_document_id::text)>0
    );
end;
$function$
;

create function shareholder_register_filing.read_scope_inventory_v1(p_company_id uuid,p_income_year integer,p_verified_subject text)
returns jsonb language plpgsql stable security definer set search_path='' as $function$
declare result jsonb:='{}'::jsonb; family_value jsonb; begin
 if p_verified_subject is distinct from shareholder_register_filing.assert_preparation_access_v1(p_company_id)::text then raise exception 'rf1086_forbidden'; end if;

select pg_catalog.jsonb_build_object('count',count(*),'digest',pg_catalog.encode(extensions.digest(coalesce(pg_catalog.string_agg(item::text,E'\n' order by item->>'id'),''),'sha256'),'hex')) into family_value from (select pg_catalog.to_jsonb(t) item from shareholder_register_filing.opening_balance_setups t where t.company_id=p_company_id and t.income_year=p_income_year) source;
 result:=result||pg_catalog.jsonb_build_object('opening_balance_setups',family_value);

select pg_catalog.jsonb_build_object('count',count(*),'digest',pg_catalog.encode(extensions.digest(coalesce(pg_catalog.string_agg(item::text,E'\n' order by item->>'id'),''),'sha256'),'hex')) into family_value from (select pg_catalog.to_jsonb(t) item from shareholder_register_filing.opening_shareholders t join shareholder_register_filing.opening_balance_setups p on p.id=t.setup_id where p.company_id=p_company_id and p.income_year=p_income_year) source;
 result:=result||pg_catalog.jsonb_build_object('opening_shareholders',family_value);

select pg_catalog.jsonb_build_object('count',count(*),'digest',pg_catalog.encode(extensions.digest(coalesce(pg_catalog.string_agg(item::text,E'\n' order by item->>'id'),''),'sha256'),'hex')) into family_value from (select pg_catalog.to_jsonb(t) item from shareholder_register_filing.filing_previews t where t.company_id=p_company_id and t.income_year=p_income_year) source;
 result:=result||pg_catalog.jsonb_build_object('filing_previews',family_value);

select pg_catalog.jsonb_build_object('count',count(*),'digest',pg_catalog.encode(extensions.digest(coalesce(pg_catalog.string_agg(item::text,E'\n' order by item->>'id'),''),'sha256'),'hex')) into family_value from (select pg_catalog.to_jsonb(t) item from shareholder_register_filing.filing_submissions t where t.company_id=p_company_id and t.income_year=p_income_year) source;
 result:=result||pg_catalog.jsonb_build_object('filing_submissions',family_value);

select pg_catalog.jsonb_build_object('count',count(*),'digest',pg_catalog.encode(extensions.digest(coalesce(pg_catalog.string_agg(item::text,E'\n' order by item->>'id'),''),'sha256'),'hex')) into family_value from (select pg_catalog.to_jsonb(t) item from shareholder_register_filing.filing_overrides t where t.company_id=p_company_id and t.income_year=p_income_year) source;
 result:=result||pg_catalog.jsonb_build_object('filing_overrides',family_value);

select pg_catalog.jsonb_build_object('count',count(*),'digest',pg_catalog.encode(extensions.digest(coalesce(pg_catalog.string_agg(item::text,E'\n' order by item->>'id'),''),'sha256'),'hex')) into family_value from (select pg_catalog.to_jsonb(t) item from shareholder_register_filing.filing_review_comments t join shareholder_register_filing.filing_previews p on p.id=t.preview_id where p.company_id=p_company_id and p.income_year=p_income_year) source;
 result:=result||pg_catalog.jsonb_build_object('filing_review_comments',family_value);

select pg_catalog.jsonb_build_object('count',count(*),'digest',pg_catalog.encode(extensions.digest(coalesce(pg_catalog.string_agg(item::text,E'\n' order by item->>'id'),''),'sha256'),'hex')) into family_value from (select pg_catalog.to_jsonb(t) item from shareholder_register_filing.authority_permissions t where t.company_id=p_company_id) source;
 result:=result||pg_catalog.jsonb_build_object('authority_permissions',family_value);

select pg_catalog.jsonb_build_object('count',count(*),'digest',pg_catalog.encode(extensions.digest(coalesce(pg_catalog.string_agg(item::text,E'\n' order by item->>'id'),''),'sha256'),'hex')) into family_value from (select pg_catalog.to_jsonb(t) item from shareholder_register_filing.authority_test_runs t where t.company_id=p_company_id) source;
 result:=result||pg_catalog.jsonb_build_object('authority_test_runs',family_value);

select pg_catalog.jsonb_build_object('count',count(*),'digest',pg_catalog.encode(extensions.digest(coalesce(pg_catalog.string_agg(item::text,E'\n' order by item->>'id'),''),'sha256'),'hex')) into family_value from (select pg_catalog.to_jsonb(t) item from shareholder_register_filing.filing_approval_snapshots t where t.company_id=p_company_id and t.income_year=p_income_year) source;
 result:=result||pg_catalog.jsonb_build_object('filing_approval_snapshots',family_value);

select pg_catalog.jsonb_build_object('count',count(*),'digest',pg_catalog.encode(extensions.digest(coalesce(pg_catalog.string_agg(item::text,E'\n' order by item->>'id'),''),'sha256'),'hex')) into family_value from (select pg_catalog.to_jsonb(t) item from shareholder_register_filing.production_filing_submissions t where t.company_id=p_company_id and t.income_year=p_income_year) source;
 result:=result||pg_catalog.jsonb_build_object('production_filing_submissions',family_value);

select pg_catalog.jsonb_build_object('count',count(*),'digest',pg_catalog.encode(extensions.digest(coalesce(pg_catalog.string_agg(item::text,E'\n' order by item->>'id'),''),'sha256'),'hex')) into family_value from (select pg_catalog.to_jsonb(t) item from shareholder_register_filing.production_filing_events t join shareholder_register_filing.production_filing_submissions p on p.id=t.submission_id where p.company_id=p_company_id and p.income_year=p_income_year) source;
 result:=result||pg_catalog.jsonb_build_object('production_filing_events',family_value);

select pg_catalog.jsonb_build_object('count',count(*),'digest',pg_catalog.encode(extensions.digest(coalesce(pg_catalog.string_agg(item::text,E'\n' order by item->>'id'),''),'sha256'),'hex')) into family_value from (select pg_catalog.to_jsonb(t) item from shareholder_register_filing.production_feedback_artifacts t join shareholder_register_filing.production_filing_submissions p on p.id=t.submission_id where p.company_id=p_company_id and p.income_year=p_income_year) source;
 result:=result||pg_catalog.jsonb_build_object('production_feedback_artifacts',family_value);

return result;
end; $function$;
alter function shareholder_register_filing.read_scope_inventory_v1(uuid,integer,text) owner to shareholder_register_filing_store_owner;
revoke all on function shareholder_register_filing.read_scope_inventory_v1(uuid,integer,text) from public,anon,authenticated,service_role;
grant execute on function shareholder_register_filing.read_scope_inventory_v1(uuid,integer,text) to postgres;
grant usage on schema extensions to shareholder_register_filing_store_owner;
grant execute on function extensions.digest(text,text) to shareholder_register_filing_store_owner;
create function backend_system.admit_rf_opening_scope_v1() returns trigger
language plpgsql security definer set search_path='' as $function$
declare facts jsonb; actor text; family record; begin
 if exists(select 1 from shareholder_register_filing.migration_inventory where company_id=new.company_id and income_year=new.income_year) then return null; end if;
 actor:=shareholder_register_filing.verified_actor_v1()::text;
 if actor is null and shareholder_register_filing.phase_v1()='legacy_overlap' then return null; end if;
 facts:=shareholder_register_filing.read_scope_inventory_v1(new.company_id,new.income_year,actor);
 if (select count(*) from pg_catalog.jsonb_object_keys(facts))<>12 or (facts->'opening_balance_setups'->>'count')::integer<1
 then raise exception 'rf1086_scope_inventory_incomplete'; end if;
 for family in select * from pg_catalog.jsonb_each(facts) loop
  insert into shareholder_register_filing.migration_inventory(company_id,income_year,family,row_count,row_digest,quarantined_count)
  values(new.company_id,new.income_year,family.key,(family.value->>'count')::bigint,family.value->>'digest',
   (select count(*) from shareholder_register_filing.migration_quarantine q where q.company_id=new.company_id and (q.income_year=new.income_year or q.income_year is null)))
  on conflict do nothing;
 end loop;
 return null;
end; $function$;
revoke all on function backend_system.admit_rf_opening_scope_v1() from public,anon,authenticated,service_role;
create constraint trigger rf151_scope_admission after insert on shareholder_register_filing.opening_balance_setups
 deferrable initially deferred for each row execute function backend_system.admit_rf_opening_scope_v1();

-- Backend-system composition of published RF opening and Ledger bank read contracts.
-- Original cursor/authentication/argument validation is retained byte-for-byte.
create or replace function backend_system.read_new_year_opening_snapshots_v1(
  p_company_ids uuid[],
  p_cursor text,
  p_limit integer,
  p_verified_subject text,
  p_income_year integer default null
)
returns table (items jsonb, next_cursor text, has_more boolean)
language plpgsql
stable
security definer
set search_path = ''
as $function$
declare
  v_actor_id uuid := public.company_access_auth_uid_v1();
  v_company_count integer;
  v_distinct_company_count integer;
  v_cursor_created_at timestamptz;
  v_cursor_id uuid;
  v_encoded text;
  v_signature text;
  v_payload jsonb;
  v_key_id uuid;
  v_issued_at timestamptz;
  v_companies text;
  v_company_hash text;
  v_count integer;
  v_last_created_at timestamptz;
  v_last_id uuid;
  v_page jsonb;
  v_setup jsonb;
  v_shareholders jsonb;
  v_resource text := case when p_income_year is null then 'opening_snapshots' else 'opening_snapshots:'||p_income_year::text end;
begin
  if v_actor_id is null
    or p_verified_subject is null
    or p_verified_subject !~ '^[0-9a-fA-F-]{36}$'
    or v_actor_id is distinct from p_verified_subject::uuid
  then
    raise exception 'ledger_forbidden';
  end if;
  if p_company_ids is null
    or pg_catalog.cardinality(p_company_ids) = 0
    or pg_catalog.cardinality(p_company_ids) > 100
    or p_limit is null
    or p_limit < 1 or p_limit > 100
    or (p_cursor is not null and pg_catalog.length(p_cursor) > 4096)
  then
    raise exception 'ledger_invalid_input';
  end if;
  if p_income_year is not null and (p_income_year < 2000 or p_income_year > 2100) then raise exception 'ledger_invalid_input'; end if;
  select pg_catalog.count(company_id), pg_catalog.count(distinct company_id)
  into v_company_count, v_distinct_company_count
  from pg_catalog.unnest(p_company_ids) company_id;
  if v_company_count <> pg_catalog.cardinality(p_company_ids)
    or v_distinct_company_count <> v_company_count
  then
    raise exception 'ledger_invalid_input';
  end if;

  select coalesce(
    pg_catalog.string_agg(company_id::text, ',' order by company_id), ''
  ) into v_companies
  from pg_catalog.unnest(p_company_ids) company_id;
  v_company_hash := pg_catalog.encode(
    extensions.digest(v_companies, 'sha256'), 'hex'
  );

  if p_cursor is not null then
    begin
      v_encoded := pg_catalog.split_part(p_cursor, '.', 1);
      v_signature := pg_catalog.split_part(p_cursor, '.', 2);
      if v_encoded = '' or v_signature !~ '^[0-9a-f]{64}$'
        or pg_catalog.split_part(p_cursor, '.', 3) <> ''
      then
        raise exception 'ledger_invalid_cursor';
      end if;
      v_payload := pg_catalog.convert_from(pg_catalog.decode(
        pg_catalog.translate(v_encoded, '-_', '+/') ||
          pg_catalog.repeat(
            '=', (4 - pg_catalog.length(v_encoded) % 4) % 4
          ),
        'base64'
      ), 'UTF8')::jsonb;
      v_key_id := (v_payload ->> 'kid')::uuid;
      v_issued_at := (v_payload ->> 'issuedAt')::timestamptz;
      if ledger.cursor_secret_v1(v_key_id) is null
        or v_signature <> pg_catalog.encode(extensions.hmac(
          v_encoded, ledger.cursor_secret_v1(v_key_id), 'sha256'
        ), 'hex')
        or v_issued_at < pg_catalog.statement_timestamp() - interval '7 days'
        or v_issued_at > pg_catalog.statement_timestamp() + interval '5 minutes'
        or v_payload ->> 'resource' <> v_resource
        or v_payload ->> 'companies' <> v_company_hash
      then
        raise exception 'ledger_invalid_cursor';
      end if;
      v_cursor_created_at := (v_payload ->> 'createdAt')::timestamptz;
      v_cursor_id := (v_payload ->> 'id')::uuid;
    exception
      when others then
        raise exception 'ledger_invalid_cursor';
    end;
  end if;

  -- A mixed authorized/unauthorized company selection retains the original
  -- accepted-member filtering. Do not invoke a source port for a hidden company.
  with visible_companies as materialized (
    select company_id
    from pg_catalog.unnest(p_company_ids) company_id
    where public.company_access_is_accepted_member_v1(company_id)
  ), source_openings as materialized (
    select opening.*
    from visible_companies company
    cross join lateral shareholder_register_filing.read_opening_snapshots_v1(
      company.company_id, p_income_year, v_actor_id::text
    ) opening
  ), source_banks as materialized (
    select bank.*
    from visible_companies company
    cross join lateral ledger.read_opening_bank_inputs_v1(
      company.company_id, p_income_year, v_actor_id::text
    ) bank
  ), page as (
    select opening.*, bank.snapshot_id as bank_snapshot_id,
      bank.bank_balance_nok as bank_balance, bank.recorded_by as bank_recorded_by,
      bank.recorded_at as bank_recorded_at
    from source_openings opening
    left join source_banks bank on bank.snapshot_id = opening.id
      and bank.company_id = opening.company_id and bank.income_year = opening.income_year
    where p_cursor is null or (opening.created_at, opening.id)
      < (v_cursor_created_at, v_cursor_id)
    order by opening.created_at desc, opening.id desc
    limit p_limit + 1
  )
  select coalesce(pg_catalog.jsonb_agg(pg_catalog.to_jsonb(page)
    order by page.created_at desc, page.id desc), '[]'::jsonb)
  into v_page from page;

  has_more := pg_catalog.jsonb_array_length(v_page) > p_limit;
  items := '[]'::jsonb;
  for v_setup in select value from pg_catalog.jsonb_array_elements(v_page) limit p_limit loop
    -- A missing or conflicting owner fact is unavailable, never an omitted
    -- snapshot or a reconstructed current-bank value.
    if v_setup ->> 'bank_snapshot_id' is null
      or (v_setup ->> 'bank_recorded_by')::uuid is distinct from (v_setup ->> 'created_by')::uuid
      or (v_setup ->> 'bank_recorded_at')::timestamptz is distinct from (v_setup ->> 'created_at')::timestamptz
      or (v_setup ->> 'bank_balance')::numeric <> pg_catalog.round((v_setup ->> 'bank_balance')::numeric, 2)
      or (v_setup ->> 'share_capital')::numeric <> pg_catalog.round((v_setup ->> 'share_capital')::numeric, 2)
      or (v_setup ->> 'nominal_value')::numeric <> pg_catalog.round((v_setup ->> 'nominal_value')::numeric, 2)
    then
      raise exception 'ledger_dependency_unavailable';
    end if;

    select coalesce(pg_catalog.jsonb_agg(pg_catalog.jsonb_build_object(
      'shareholderId', shareholder.id,
      'setupId', shareholder.setup_id,
      'companyId', shareholder.company_id,
      'name', shareholder.name,
      'shareholderKind', shareholder.shareholder_kind,
      'nationalId', shareholder.national_id,
      'orgNumber', shareholder.org_number,
      'shareCount', shareholder.share_count
    ) order by shareholder.id), '[]'::jsonb)
    into v_shareholders
    from (
      select shareholder.*
      from shareholder_register_filing.read_opening_shareholders_v1(
        (v_setup ->> 'company_id')::uuid,
        (v_setup ->> 'income_year')::integer,
        v_actor_id::text
      ) shareholder
      where shareholder.setup_id = (v_setup ->> 'id')::uuid
      order by shareholder.id
      limit 101
    ) shareholder;
    if pg_catalog.jsonb_array_length(v_shareholders) > 100 then
      raise exception 'ledger_dependency_unavailable';
    end if;

    items := items || pg_catalog.jsonb_build_array(pg_catalog.jsonb_build_object(
      'setupId', v_setup -> 'id',
      'companyId', v_setup -> 'company_id',
      'incomeYear', v_setup -> 'income_year',
      'bankBalance', v_setup ->> 'bank_balance',
      'shareCapital', v_setup ->> 'share_capital',
      'shareCount', v_setup -> 'share_count',
      'nominalValue', v_setup ->> 'nominal_value',
      'lockedAt', v_setup -> 'locked_at',
      'createdAt', v_setup -> 'created_at',
      'createdBy', v_setup -> 'created_by',
      'shareholders', v_shareholders
    ));
    v_last_created_at := (v_setup ->> 'created_at')::timestamptz;
    v_last_id := (v_setup ->> 'id')::uuid;
  end loop;

  if has_more and pg_catalog.jsonb_array_length(items) > 0 then
    next_cursor := ledger.cursor_encode_v1(
      v_resource, p_company_ids, v_last_created_at, v_last_id
    );
  else
    next_cursor := null;
  end if;
  return next;
end;
$function$;

alter function backend_system.read_new_year_opening_snapshots_v1(uuid[],text,integer,text,integer)
  owner to ledger_workflow_store_owner;
revoke all on function backend_system.read_new_year_opening_snapshots_v1(uuid[],text,integer,text,integer)
  from public,anon,authenticated,service_role;
grant execute on function backend_system.read_new_year_opening_snapshots_v1(uuid[],text,integer,text,integer)
  to ledger_workflow_executor;

do $restore_roles$ declare r record; begin
 if (select workflow_create from rf151_schema_grants) then revoke create on schema backend_system from ledger_workflow_store_owner; end if;
 if (select backend_create from rf151_schema_grants) then execute pg_catalog.format('revoke create on schema backend_system from %I',current_user); end if;
 if (select company_access_create from rf151_schema_grants) then revoke create on schema public from company_access_executor; end if;
 if (select ledger_create from rf151_schema_grants) then revoke create on schema ledger from ledger_store_owner; end if;
 for r in select * from rf151_borrowed_roles loop
  if r.prior is null then execute pg_catalog.format('revoke %I from %I granted by %I',r.role_name,current_user,current_user);
  else execute pg_catalog.format('grant %I to %I with admin %s, inherit %s, set %s granted by %I',r.role_name,current_user,
    r.prior->>'admin',r.prior->>'inherit',r.prior->>'set',current_user); end if;
 end loop;
end; $restore_roles$;
commit;
