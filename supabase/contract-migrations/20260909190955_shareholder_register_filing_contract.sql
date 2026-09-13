-- CONTRACT RELEASE ARTIFACT: #151 shareholder register filing owner cutover.
-- Run only after both application orders passed and the approved receiver reads are rebound.
begin;
set local lock_timeout='5s';
set local statement_timeout='120s';
select pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended('talli:rf1086:capability:v1',0));

do $guard$ begin if shareholder_register_filing.phase_v1()<>'canonical_overlap' then raise exception 'rf1086_contract_wrong_phase'; end if; end; $guard$;

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

create temporary table rf151_schema_grants on commit drop as select false as ledger_create,false as company_access_create,false as workflow_create,not pg_catalog.has_schema_privilege(current_user,'backend_system','CREATE') as backend_create; do $g$ begin execute pg_catalog.format('grant create on schema backend_system to %I',current_user); end; $g$;

lock table public.opening_balance_setups,public.opening_shareholders,public.filing_previews,public.filing_submissions,public.filing_overrides,public.filing_review_comments,public.authority_permissions,public.authority_test_runs,shareholder_register_filing.opening_balance_setups,shareholder_register_filing.opening_shareholders,shareholder_register_filing.filing_previews,shareholder_register_filing.filing_submissions,shareholder_register_filing.filing_overrides,shareholder_register_filing.filing_review_comments,shareholder_register_filing.authority_permissions,shareholder_register_filing.authority_test_runs,shareholder_register_filing.filing_approval_snapshots,shareholder_register_filing.production_filing_submissions,shareholder_register_filing.production_filing_events,shareholder_register_filing.production_feedback_artifacts in access exclusive mode;

create temporary table rf151_contract_read_access(relation text primary key,owner name,had_select boolean) on commit drop;
create temporary table rf151_contract_hashes(relation text primary key,digest text) on commit drop;
do $contract_read_snapshot$ declare relation text; owner_role name; migration_role name:=current_user; had_select boolean; digest text; begin
 foreach relation in array array['shareholder_register_filing.opening_balance_setups','shareholder_register_filing.opening_shareholders','shareholder_register_filing.filing_previews','shareholder_register_filing.filing_submissions','shareholder_register_filing.filing_overrides','shareholder_register_filing.filing_review_comments','shareholder_register_filing.authority_permissions','shareholder_register_filing.authority_test_runs','shareholder_register_filing.filing_approval_snapshots','shareholder_register_filing.production_filing_submissions','shareholder_register_filing.production_filing_events','shareholder_register_filing.production_feedback_artifacts','ledger.opening_bank_inputs','shareholder_register_filing.migration_inventory','shareholder_register_filing.migration_quarantine'] loop
  select pg_catalog.pg_get_userbyid(c.relowner),exists(select 1 from pg_catalog.aclexplode(c.relacl) a
   where a.grantee=(select oid from pg_catalog.pg_roles where rolname=migration_role) and a.privilege_type='SELECT')
  into owner_role,had_select from pg_catalog.pg_class c where c.oid=pg_catalog.to_regclass(relation);
  if owner_role is null then raise exception 'rf1086_reverse_relation_missing'; end if;
  insert into rf151_contract_read_access values(relation,owner_role,had_select);
  execute pg_catalog.format('set local role %I',owner_role);
  if owner_role<>migration_role then execute pg_catalog.format('grant select on %s to %I',relation,migration_role); end if;
  execute pg_catalog.format('create policy rf151_contract_read_snapshot on %s for select to %I using(true)',relation,migration_role);
  execute 'reset role';
  execute pg_catalog.format('select pg_catalog.encode(extensions.digest(coalesce(pg_catalog.string_agg(pg_catalog.to_jsonb(t)::text,E''\n'' order by pg_catalog.to_jsonb(t)::text),pg_catalog.left(''x'',0)),''sha256''),''hex'') from %s t',relation) into digest;
  insert into rf151_contract_hashes values(relation,digest);
 end loop;
end; $contract_read_snapshot$;

-- Freeze provenance before deleting parents; all six sibling families remain exact.
create temporary table rf151_contract_rows(family text,id uuid,category text,item jsonb,primary key(family,id)) on commit drop;
create temporary table rf151_contract_triggers(relation text,name name,enabled "char") on commit drop;
do $retire_generic_rows$
declare n text; t record; before_rows jsonb; retained_rows jsonb;
begin
 foreach n in array array['filing_previews','filing_submissions','filing_overrides','filing_review_comments','authority_permissions','authority_test_runs'] loop
  execute pg_catalog.format('insert into rf151_contract_rows select %L,id,shareholder_register_filing.classify_legacy_row_v1(%L,to_jsonb(p)),to_jsonb(p) from public.%I p',n,n,n);
  select jsonb_agg(item order by id) into before_rows from rf151_contract_rows where family=n and category<>'sibling';
  execute pg_catalog.format('select jsonb_agg(item order by item->>''id'') from (select to_jsonb(c) item from shareholder_register_filing.%I c union all select original_row from shareholder_register_filing.migration_quarantine where family=$1) r',n) into retained_rows using n;
  if before_rows is distinct from retained_rows then raise exception 'rf1086_generic_projection_reconciliation_failed'; end if;
 end loop;
 -- Only USER triggers are suspended; FK constraints and FORCE RLS stay active.
 for t in select n.nspname||'.'||c.relname relation,g.tgname,g.tgenabled
   from pg_catalog.pg_trigger g join pg_catalog.pg_class c on c.oid=g.tgrelid
   join pg_catalog.pg_namespace n on n.oid=c.relnamespace
   where n.nspname='public' and c.relname=any(array['filing_previews','filing_submissions','filing_overrides','filing_review_comments','authority_permissions','authority_test_runs']) and not g.tgisinternal loop
  insert into rf151_contract_triggers values(t.relation,t.tgname,t.tgenabled);
  execute pg_catalog.format('alter table %s disable trigger %I',t.relation,t.tgname);
 end loop;
 foreach n in array array['filing_review_comments','filing_overrides','filing_submissions','filing_previews','authority_permissions','authority_test_runs'] loop
  execute pg_catalog.format('delete from public.%I p using rf151_contract_rows r where r.family=$1 and r.id=p.id and r.category<>''sibling''',n) using n;
 end loop;
 foreach n in array array['filing_previews','filing_submissions','filing_overrides','filing_review_comments','authority_permissions','authority_test_runs'] loop
  select jsonb_agg(item order by id) into before_rows from rf151_contract_rows where family=n and category='sibling';
  execute pg_catalog.format('select jsonb_agg(to_jsonb(p) order by id) from public.%I p',n) into retained_rows;
  if before_rows is distinct from retained_rows then raise exception 'rf1086_sibling_projection_changed'; end if;
  select jsonb_agg(item order by id) into before_rows from rf151_contract_rows where family=n and category<>'sibling';
  execute pg_catalog.format('select jsonb_agg(item order by item->>''id'') from (select to_jsonb(c) item from shareholder_register_filing.%I c union all select original_row from shareholder_register_filing.migration_quarantine where family=$1) r',n) into retained_rows using n;
  if before_rows is distinct from retained_rows then raise exception 'rf1086_canonical_projection_changed'; end if;
 end loop;
 for t in select * from rf151_contract_triggers loop
  execute pg_catalog.format('alter table %s %s trigger %I',t.relation,
   case t.enabled when 'D' then 'disable' when 'A' then 'enable always' when 'R' then 'enable replica' else 'enable' end,t.name);
 end loop;
end; $retire_generic_rows$;
do $contract_unchanged_canonical$ declare r record; digest text; migration_role name:=current_user; begin
 for r in select a.*,h.digest expected from rf151_contract_read_access a join rf151_contract_hashes h using(relation) loop
  execute pg_catalog.format('select pg_catalog.encode(extensions.digest(coalesce(pg_catalog.string_agg(pg_catalog.to_jsonb(t)::text,E''\n'' order by pg_catalog.to_jsonb(t)::text),pg_catalog.left(''x'',0)),''sha256''),''hex'') from %s t',r.relation) into digest;
  if digest is distinct from r.expected then raise exception 'rf1086_contract_changed_canonical_evidence'; end if;
  execute pg_catalog.format('set local role %I',r.owner);
  execute pg_catalog.format('drop policy rf151_contract_read_snapshot on %s',r.relation);
  if not r.had_select and r.owner<>migration_role then execute pg_catalog.format('revoke select on %s from %I',r.relation,migration_role); end if;
  execute 'reset role';
 end loop;
end; $contract_unchanged_canonical$;

drop function public.release_production_feedback_reconciliation(uuid, uuid);

drop function public.approve_production_filing(uuid, uuid, jsonb, text, text);

drop function public.append_production_filing_event(uuid, text, text, integer, text, uuid, text, text, text, boolean);

drop function public.begin_production_filing(uuid);

drop function public.claim_production_feedback_reconciliation(uuid, uuid);

drop function public.record_production_feedback_artifact(uuid, uuid, uuid, text, text, bigint, text, text);

drop policy "legacy_rf1086_preview_read" on public.filing_previews;
drop policy "legacy_rf1086_approval_read" on shareholder_register_filing.filing_approval_snapshots;
drop policy "legacy_rf1086_submission_read" on shareholder_register_filing.production_filing_submissions;
drop policy "legacy_rf1086_event_read" on shareholder_register_filing.production_filing_events;
drop policy "legacy_rf1086_artifact_read" on shareholder_register_filing.production_feedback_artifacts;
drop function legacy_rf1086.assert_fresh_owner_v1(uuid);

drop function legacy_rf1086.actor_v1();

drop function legacy_rf1086.can_read_company_v1(uuid);

drop function legacy_rf1086.can_read_submission_v1(uuid);

drop function legacy_rf1086.assert_submission_v1(uuid);

drop function legacy_rf1086.prepare_operation_v1(uuid, text, text, uuid);

drop function public.append_production_feedback_reconciliation(uuid, uuid, uuid, text, text[], text, text);






drop trigger rf151_preparation_projection on shareholder_register_filing.filing_previews;

drop trigger rf151_preparation_projection on shareholder_register_filing.filing_submissions;

drop trigger rf151_preparation_projection on shareholder_register_filing.filing_overrides;

drop trigger rf151_preparation_projection on shareholder_register_filing.filing_review_comments;

drop trigger rf151_preparation_projection on shareholder_register_filing.authority_permissions;

drop trigger rf151_preparation_projection on shareholder_register_filing.authority_test_runs;

drop trigger rf151_opening_projection on shareholder_register_filing.opening_balance_setups;
drop trigger rf151_shareholder_projection on shareholder_register_filing.opening_shareholders;
drop trigger rf151_capture_legacy_bank on public.opening_balance_setups;
drop function backend_system.sync_rf_preparation_projection_v1();
drop function backend_system.sync_rf_opening_projection_v1();
drop function backend_system.capture_legacy_rf_opening_bank_v1();
drop function ledger.capture_legacy_opening_bank_input_v1(uuid,uuid,integer,numeric,uuid,timestamptz);
drop policy rf151_legacy_bank_capture on ledger.opening_bank_inputs;
drop policy rf151_legacy_bank_capture_read on ledger.opening_bank_inputs;

do $receivers$ declare refs text; begin
 select pg_catalog.string_agg(n.nspname||'.'||p.proname,',') into refs
 from pg_catalog.pg_proc p join pg_catalog.pg_namespace n on n.oid=p.pronamespace
 where p.prokind='f' and n.nspname not in ('shareholder_register_filing','pg_catalog','information_schema')
   and p.prosrc ~ 'public[.](filing_approval_snapshots|production_filing_submissions|production_filing_events|production_feedback_artifacts)';
 if refs is not null then raise exception 'rf1086_public_receiver_not_rebound'; end if;
end; $receivers$;

drop view public.filing_approval_snapshots;

drop view public.production_filing_submissions;

drop view public.production_filing_events;

drop view public.production_feedback_artifacts;

drop function public.rf1086_confirmation_forsendelse_id(text);

drop trigger rf151_legacy_projection on public.opening_balance_setups;

drop policy rf151_backend_overlap on public.opening_balance_setups;

revoke select,insert,update on public.opening_balance_setups from shareholder_register_filing_store_owner;

drop policy rf151_overlap_copy on shareholder_register_filing.opening_balance_setups;

revoke select,insert,update,delete on shareholder_register_filing.opening_balance_setups from postgres;

drop trigger rf151_legacy_projection on public.opening_shareholders;

drop policy rf151_backend_overlap on public.opening_shareholders;

revoke select,insert,update on public.opening_shareholders from shareholder_register_filing_store_owner;

drop policy rf151_overlap_copy on shareholder_register_filing.opening_shareholders;

revoke select,insert,update,delete on shareholder_register_filing.opening_shareholders from postgres;

drop trigger rf151_legacy_projection on public.filing_previews;

drop policy rf151_backend_overlap on public.filing_previews;

revoke select,insert,update on public.filing_previews from shareholder_register_filing_store_owner;

drop policy rf151_overlap_copy on shareholder_register_filing.filing_previews;

revoke select,insert,update,delete on shareholder_register_filing.filing_previews from postgres;

drop trigger rf151_legacy_projection on public.filing_submissions;

drop policy rf151_backend_overlap on public.filing_submissions;

revoke select,insert,update on public.filing_submissions from shareholder_register_filing_store_owner;

drop policy rf151_overlap_copy on shareholder_register_filing.filing_submissions;

revoke select,insert,update,delete on shareholder_register_filing.filing_submissions from postgres;

drop trigger rf151_legacy_projection on public.filing_overrides;

drop policy rf151_backend_overlap on public.filing_overrides;

revoke select,insert,update on public.filing_overrides from shareholder_register_filing_store_owner;

drop policy rf151_overlap_copy on shareholder_register_filing.filing_overrides;

revoke select,insert,update,delete on shareholder_register_filing.filing_overrides from postgres;

drop trigger rf151_legacy_projection on public.filing_review_comments;

drop policy rf151_backend_overlap on public.filing_review_comments;

revoke select,insert,update on public.filing_review_comments from shareholder_register_filing_store_owner;

drop policy rf151_overlap_copy on shareholder_register_filing.filing_review_comments;

revoke select,insert,update,delete on shareholder_register_filing.filing_review_comments from postgres;

drop trigger rf151_legacy_projection on public.authority_permissions;

drop policy rf151_backend_overlap on public.authority_permissions;

revoke select,insert,update on public.authority_permissions from shareholder_register_filing_store_owner;

drop policy rf151_overlap_copy on shareholder_register_filing.authority_permissions;

revoke select,insert,update,delete on shareholder_register_filing.authority_permissions from postgres;

drop trigger rf151_legacy_projection on public.authority_test_runs;

drop policy rf151_backend_overlap on public.authority_test_runs;

revoke select,insert,update on public.authority_test_runs from shareholder_register_filing_store_owner;

drop policy rf151_overlap_copy on shareholder_register_filing.authority_test_runs;

revoke select,insert,update,delete on shareholder_register_filing.authority_test_runs from postgres;

drop policy rf151_old_function_owner on shareholder_register_filing.filing_approval_snapshots;

revoke all on shareholder_register_filing.filing_approval_snapshots from postgres,legacy_rf1086_executor,authenticated,service_role;

drop policy rf151_old_function_owner on shareholder_register_filing.production_filing_submissions;

revoke all on shareholder_register_filing.production_filing_submissions from postgres,legacy_rf1086_executor,authenticated,service_role;

drop policy rf151_old_function_owner on shareholder_register_filing.production_filing_events;

revoke all on shareholder_register_filing.production_filing_events from postgres,legacy_rf1086_executor,authenticated,service_role;

drop policy rf151_old_function_owner on shareholder_register_filing.production_feedback_artifacts;

revoke all on shareholder_register_filing.production_feedback_artifacts from postgres,legacy_rf1086_executor,authenticated,service_role;

-- The old bank-bearing opening projection is retired only after its readers are rebound.
-- Surviving generic filing rows retain only the RF-owned opening identity relation.
do $opening_contract$ declare n text; c record; begin
 if exists(select 1 from pg_catalog.pg_attribute where attrelid='ledger.entries'::regclass and attname='setup_id' and not attisdropped)
 then raise exception 'rf1086_opening_contract_requires_ledger_contract'; end if;
 if (select count(*) from pg_catalog.jsonb_object_keys((select original_opening_schema from shareholder_register_filing.migration_state where singleton)))<>2
 then raise exception 'rf1086_original_opening_schema_missing'; end if;
 foreach n in array array['filing_previews','filing_submissions'] loop
  select * into c from pg_catalog.pg_constraint where conrelid=pg_catalog.to_regclass('public.'||n) and conname=n||'_setup_id_fkey';
  if not found or c.contype<>'f' or c.confrelid<>'public.opening_balance_setups'::regclass
    or c.confdeltype<>'r' or c.confupdtype<>'a' or c.condeferrable or not c.convalidated
  then raise exception 'rf1086_original_incoming_opening_constraint_changed'; end if;
  execute pg_catalog.format('alter table public.%I drop constraint %I',n,n||'_setup_id_fkey');
  execute pg_catalog.format('alter table public.%I add constraint %I foreign key(setup_id) references shareholder_register_filing.opening_balance_setups(id) on delete restrict',n,n||'_setup_id_fkey');
 end loop;
end; $opening_contract$;
drop function backend_system.record_opening_snapshot_legacy_v1(uuid,integer,numeric,numeric,integer,numeric,jsonb,text);
drop function backend_system.list_opening_snapshots_legacy_v1(uuid[],text,integer,text);
-- Reconcile every original projection row, including quarantined holders, before disposal.
do $opening_projection_reconciliation$ declare original jsonb; retained jsonb; begin
 select jsonb_agg(to_jsonb(o) order by id) into original from public.opening_balance_setups o;
 select jsonb_agg(item order by item->>'id') into retained from (
  select to_jsonb(o)||jsonb_build_object('bank_balance',b.bank_balance_nok) item
  from shareholder_register_filing.opening_balance_setups o join ledger.opening_bank_inputs b on b.snapshot_id=o.id
   and b.company_id=o.company_id and b.income_year=o.income_year and b.recorded_by=o.created_by and b.recorded_at=o.created_at
  union all select original_row from shareholder_register_filing.migration_quarantine where family='opening_balance_setups') r;
 if original is distinct from retained then raise exception 'rf1086_opening_projection_reconciliation_failed'; end if;
 select jsonb_agg(to_jsonb(o) order by id) into original from public.opening_shareholders o;
 select jsonb_agg(item order by item->>'id') into retained from (
  select to_jsonb(o) item from shareholder_register_filing.opening_shareholders o
  union all select original_row from shareholder_register_filing.migration_quarantine where family='opening_shareholders') r;
 if original is distinct from retained then raise exception 'rf1086_opening_projection_reconciliation_failed'; end if;
 if exists(select 1 from pg_catalog.pg_trigger where tgrelid in ('public.opening_balance_setups'::regclass,'public.opening_shareholders'::regclass) and not tgisinternal and tgtype & 32 <> 0)
 then raise exception 'rf1086_unexpected_opening_truncate_trigger'; end if;
end; $opening_projection_reconciliation$;
-- TRUNCATE names both original relations and never CASCADEs. Row-level archive triggers do not fire.
truncate public.opening_shareholders,public.opening_balance_setups;
do $opening_empty_preflight$ begin
 if pg_catalog.to_regclass('public.opening_shareholders') is not null
 and exists(select 1 from public.opening_shareholders)
 then raise exception 'rf1086_opening_projection_not_empty'; end if;
 if pg_catalog.to_regclass('public.opening_balance_setups') is not null
 and exists(select 1 from public.opening_balance_setups)
 then raise exception 'rf1086_opening_projection_not_empty'; end if;
end; $opening_empty_preflight$;
drop table if exists public.opening_shareholders;
drop table if exists public.opening_balance_setups;

create or replace function backend_system.admit_rf_opening_scope_v1() returns trigger
language plpgsql security definer set search_path='' as $function$
declare facts jsonb; actor text; family record; begin
 if exists(select 1 from shareholder_register_filing.migration_inventory where company_id=new.company_id and income_year=new.income_year) then return null; end if;
 actor:=shareholder_register_filing.verified_actor_v1()::text;
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

-- Only canonical commands and the sibling-only write barrier remain installed.
create or replace function shareholder_register_filing.classify_legacy_row_v1(family text,row_data jsonb) returns text
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
  -- The shared predecessor UI used this target for every obligation. The
  -- referenced preview, with matching company, determines a comment's owner.
  if family='filing_review_comments' then
    select pg_catalog.to_jsonb(v) into p from public.filing_previews v where v.id=(row_data->>'preview_id')::uuid;
    if p is not null and not shareholder_register_filing.is_rf_label_v1(p->>'filing') then
      return case when p->>'company_id'=row_data->>'company_id' then 'sibling' else 'quarantine' end;
    end if;
  end if;
  -- Conflicting labels/field targets cannot attest complete RF readiness.
  if family='filing_overrides' and not candidate and row_data->>'field_target' like 'rf1086.%'
  then return 'quarantine'; end if;
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
      select pg_catalog.to_jsonb(v) into s from shareholder_register_filing.opening_balance_setups v where v.id=(row_data->>'setup_id')::uuid;

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

create or replace function shareholder_register_filing.sync_legacy_projection_v1() returns trigger
language plpgsql security definer set search_path='' as $function$
begin
 if tg_when<>'BEFORE' or tg_table_name not in ('filing_previews','filing_submissions','filing_overrides','filing_review_comments','authority_permissions','authority_test_runs')
 then raise exception 'rf1086_overlap_trigger_invalid'; end if;
 if (tg_op<>'DELETE' and shareholder_register_filing.classify_legacy_row_v1(tg_table_name,to_jsonb(new))<>'sibling')
 or (tg_op<>'INSERT' and shareholder_register_filing.classify_legacy_row_v1(tg_table_name,to_jsonb(old))<>'sibling')
 then raise exception 'rf1086_legacy_writer_retired'; end if;
 return case when tg_op='DELETE' then old else new end;
end; $function$;

create or replace function shareholder_register_filing.insert_preparation_row_v1(p_family text,p_row jsonb) returns jsonb
language plpgsql security definer set search_path='' as $function$
declare v_schema text; v_columns text; result jsonb; begin
 if p_family not in ('filing_previews','filing_submissions','filing_overrides','filing_review_comments','authority_permissions','authority_test_runs')
 then raise exception 'rf1086_invalid_input'; end if;
 v_schema:='shareholder_register_filing';
 select pg_catalog.string_agg(pg_catalog.quote_ident(a.attname),',' order by a.attnum) into v_columns
 from pg_catalog.pg_attribute a where a.attrelid=pg_catalog.to_regclass(v_schema||'.'||p_family)
   and a.attnum>0 and not a.attisdropped and p_row ? a.attname;
 execute pg_catalog.format('insert into %I.%I(%s) select %s from pg_catalog.jsonb_populate_record(null::%I.%I,$1) returning pg_catalog.to_jsonb(%I.*)',
   v_schema,p_family,v_columns,v_columns,v_schema,p_family,p_family) into result using p_row;
 return result;
end; $function$;

create or replace function shareholder_register_filing.acknowledge_review_comment_v1(p_comment_id uuid)
returns jsonb language plpgsql security definer set search_path='' as $function$
declare a uuid; c shareholder_register_filing.filing_review_comments%rowtype; result jsonb; begin
 select * into c from shareholder_register_filing.filing_review_comments where id=p_comment_id for update;
 if c.id is null then raise exception 'rf1086_not_found'; end if;
 a:=shareholder_register_filing.assert_preparation_access_v1(c.company_id);
 if c.severity='hard_block' then raise exception 'rf1086_forbidden'; end if;
  update shareholder_register_filing.filing_review_comments set acknowledged_by=a,acknowledged_at=pg_catalog.now() where id=c.id returning pg_catalog.to_jsonb(filing_review_comments.*) into result;

 return result;
end; $function$;

create or replace function shareholder_register_filing.confirm_filing_permission_v1(p_company_id uuid,p_enabled boolean)
returns jsonb language plpgsql security definer set search_path='' as $function$
declare a uuid:=shareholder_register_filing.assert_preparation_access_v1(p_company_id); result jsonb; v_schema text; begin
 if not public.company_access_has_fresh_mfa_v1() then raise exception 'rf1086_company_year_not_admitted'; end if;
 if p_enabled is null then raise exception 'rf1086_invalid_input'; end if;
 v_schema:='shareholder_register_filing';
 execute pg_catalog.format('insert into %I.authority_permissions(company_id,obligation,submitter_user_id,confirmed_by,confirmed_at,production_enabled) values($1,''aksjonaerregisteroppgaven'',$2,$2,pg_catalog.now(),$3) on conflict(company_id,obligation) do update set submitter_user_id=excluded.submitter_user_id,confirmed_by=excluded.confirmed_by,confirmed_at=excluded.confirmed_at,production_enabled=excluded.production_enabled,updated_at=pg_catalog.now() returning pg_catalog.to_jsonb(authority_permissions.*)',v_schema)
 into result using p_company_id,a,p_enabled;
 return result;
end; $function$;

create or replace function shareholder_register_filing.record_simulation_v1(p_preview_id uuid,p_data jsonb)
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
 v_schema:='shareholder_register_filing';
 execute pg_catalog.format('insert into %I.filing_submissions(preview_id,setup_id,company_id,income_year,filing,mode,adapter_mode,payload_hash,idempotency_key,status,calls,receipt_id,feedback_document_ids,feedback_items,receipt_metadata,submitted_payload_ref,submitted_payload,failure_code,failure_message,authority_confirmed_by,authority_confirmed_at,preview_confirmed_by,preview_confirmed_at,created_by,submitted_by) values($1,$2,$3,$4,$5,''simulation'',''simulation'',$6->>''payload_hash'',$6->>''idempotency_key'',$6->>''status'',$6->''calls'',$6->>''receipt_id'',$6->''feedback_document_ids'',$6->''feedback_items'',$6->''receipt_metadata'',$6->''submitted_payload_ref'',$6->''submitted_payload'',$6->>''failure_code'',$6->>''failure_message'',$7,($6->>''authority_confirmed_at'')::timestamptz,$7,($6->>''preview_confirmed_at'')::timestamptz,$7,$7) on conflict(preview_id) do update set mode=excluded.mode,adapter_mode=excluded.adapter_mode,payload_hash=excluded.payload_hash,idempotency_key=excluded.idempotency_key,status=excluded.status,calls=excluded.calls,receipt_id=excluded.receipt_id,feedback_document_ids=excluded.feedback_document_ids,feedback_items=excluded.feedback_items,receipt_metadata=excluded.receipt_metadata,submitted_payload_ref=excluded.submitted_payload_ref,submitted_payload=excluded.submitted_payload,failure_code=excluded.failure_code,failure_message=excluded.failure_message,authority_confirmed_by=excluded.authority_confirmed_by,authority_confirmed_at=excluded.authority_confirmed_at,preview_confirmed_by=excluded.preview_confirmed_by,preview_confirmed_at=excluded.preview_confirmed_at,created_by=excluded.created_by,submitted_by=excluded.submitted_by,updated_at=pg_catalog.now() returning pg_catalog.to_jsonb(filing_submissions.*)',v_schema)
 into result using p.id,p.setup_id,p.company_id,p.income_year,p.filing,p_data,a;
 return result;
end; $function$;

update shareholder_register_filing.migration_state set phase='contracted' where singleton;

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
