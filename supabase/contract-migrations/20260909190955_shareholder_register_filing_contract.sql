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
