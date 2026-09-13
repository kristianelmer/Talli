-- Reviewed draft: reverse only the indicated #151 phase, never application deployment.
-- Canonical journal OIDs/records, hashes, references, IDs and active leases remain in place.
begin;
set local lock_timeout='5s';
set local statement_timeout='120s';
select pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended('talli:rf1086:capability:v1',0));
do $guard$ begin
 if shareholder_register_filing.phase_v1() is distinct from 'canonical_overlap' then raise exception 'rf1086_phase_rollback_wrong_phase'; end if;
 if (select count(*) from pg_catalog.jsonb_object_keys((select original_relations from shareholder_register_filing.migration_state where singleton)))<>12
 then raise exception 'rf1086_original_metadata_incomplete'; end if;
end; $guard$;
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

create temporary table rf151_schema_grants on commit drop as select
 false as ledger_create,false as company_access_create,false as workflow_create,
 not pg_catalog.has_schema_privilege(current_user,'backend_system','CREATE') as backend_create;
do $schema_grant$ begin execute pg_catalog.format('grant create on schema backend_system to %I',current_user); end; $schema_grant$;
lock table public.opening_balance_setups,public.opening_shareholders,public.filing_previews,public.filing_submissions,public.filing_overrides,public.filing_review_comments,public.authority_permissions,public.authority_test_runs,shareholder_register_filing.opening_balance_setups,shareholder_register_filing.opening_shareholders,shareholder_register_filing.filing_previews,shareholder_register_filing.filing_submissions,shareholder_register_filing.filing_overrides,shareholder_register_filing.filing_review_comments,shareholder_register_filing.authority_permissions,shareholder_register_filing.authority_test_runs,shareholder_register_filing.filing_approval_snapshots,shareholder_register_filing.production_filing_submissions,shareholder_register_filing.production_filing_events,shareholder_register_filing.production_feedback_artifacts,ledger.opening_bank_inputs in access exclusive mode;
create temporary table rf151_saved_objects on commit drop as
 select original_objects,original_relations from shareholder_register_filing.migration_state where singleton;
-- These drafts preserve the original migration-owner path, not arbitrary DDL authority.
do $migration_owner$ declare n text; begin
 foreach n in array array['opening_balance_setups','opening_shareholders','filing_previews','filing_submissions','filing_overrides','filing_review_comments','authority_permissions','authority_test_runs'] loop
  if (select original_relations->n->>'owner' from rf151_saved_objects) is distinct from current_user
  then raise exception 'rf1086_original_migration_owner_required'; end if;
 end loop;
end; $migration_owner$;

-- A bounded migration-only SELECT policy is removed before COMMIT. Existing
-- force-RLS flags and grants are preserved; no application role receives it.
create temporary table rf151_reverse_read_access(relation text primary key,owner name,had_select boolean) on commit drop;
create temporary table rf151_reverse_hashes(relation text primary key,digest text) on commit drop;
create temporary table rf151_reverse_triggers(relation text,name name,enabled "char",primary key(relation,name)) on commit drop;
do $read_snapshot$ declare relation text; owner_role name; migration_role name:=current_user; had_select boolean; digest text; begin
 foreach relation in array array['shareholder_register_filing.opening_balance_setups','shareholder_register_filing.opening_shareholders','shareholder_register_filing.filing_previews','shareholder_register_filing.filing_submissions','shareholder_register_filing.filing_overrides','shareholder_register_filing.filing_review_comments','shareholder_register_filing.authority_permissions','shareholder_register_filing.authority_test_runs','shareholder_register_filing.filing_approval_snapshots','shareholder_register_filing.production_filing_submissions','shareholder_register_filing.production_filing_events','shareholder_register_filing.production_feedback_artifacts','ledger.opening_bank_inputs','shareholder_register_filing.migration_inventory','shareholder_register_filing.migration_quarantine'] loop
  select pg_catalog.pg_get_userbyid(c.relowner),exists(select 1 from pg_catalog.aclexplode(c.relacl) a
   where a.grantee=(select oid from pg_catalog.pg_roles where rolname=migration_role) and a.privilege_type='SELECT')
  into owner_role,had_select from pg_catalog.pg_class c where c.oid=pg_catalog.to_regclass(relation);
  if owner_role is null then raise exception 'rf1086_reverse_relation_missing'; end if;
  insert into rf151_reverse_read_access values(relation,owner_role,had_select);
  execute pg_catalog.format('set local role %I',owner_role);
  if owner_role<>migration_role then execute pg_catalog.format('grant select on %s to %I',relation,migration_role); end if;
  execute pg_catalog.format('create policy rf151_reverse_read_snapshot on %s for select to %I using(true)',relation,migration_role);
  execute 'reset role';
  execute pg_catalog.format('select pg_catalog.encode(extensions.digest(coalesce(pg_catalog.string_agg(pg_catalog.to_jsonb(t)::text,E''\n'' order by pg_catalog.to_jsonb(t)::text),pg_catalog.left(''x'',0)),''sha256''),''hex'') from %s t',relation) into digest;
  insert into rf151_reverse_hashes values(relation,digest);
 end loop;
end; $read_snapshot$;
-- Avoid turning projection refresh into business/archive writes. Restore every
-- original trigger enable mode; internal FK constraints are never disabled.
do $suspend_projection_triggers$ declare t record; begin
 for t in select n.nspname||'.'||c.relname relation,g.tgname,g.tgenabled
  from pg_catalog.pg_trigger g join pg_catalog.pg_class c on c.oid=g.tgrelid
  join pg_catalog.pg_namespace n on n.oid=c.relnamespace
  where n.nspname='public' and c.relname=any(array['opening_balance_setups','opening_shareholders','filing_previews','filing_submissions','filing_overrides','filing_review_comments','authority_permissions','authority_test_runs']) and not g.tgisinternal loop
  insert into rf151_reverse_triggers values(t.relation,t.tgname,t.tgenabled);
  execute pg_catalog.format('alter table %s disable trigger %I',t.relation,t.tgname);
 end loop;
end; $suspend_projection_triggers$;
-- Exact original bank-input relationship is necessary before restoring a source projection.
do $bank_binding$ begin
 if exists(select 1 from shareholder_register_filing.opening_balance_setups r
 left join ledger.opening_bank_inputs b on b.snapshot_id=r.id and b.company_id=r.company_id and b.income_year=r.income_year
 where b.snapshot_id is null or b.recorded_by is distinct from r.created_by or b.recorded_at is distinct from r.created_at)
 then raise exception 'rf1086_rollback_bank_input_missing'; end if;
end; $bank_binding$;

do $identity_collision$ begin
 if exists(select 1 from shareholder_register_filing.opening_balance_setups r join public.opening_balance_setups p using(id)
 where shareholder_register_filing.classify_legacy_row_v1('opening_balance_setups',pg_catalog.to_jsonb(p))<>'rf')
 then raise exception 'rf1086_rollback_conflicting_projection'; end if;
end; $identity_collision$;
insert into public.opening_balance_setups(id,company_id,income_year,bank_balance,share_capital,share_count,nominal_value,locked_at,created_by,created_at) select r.id,r.company_id,r.income_year,b.bank_balance_nok,r.share_capital,r.share_count,r.nominal_value,r.locked_at,r.created_by,r.created_at from shareholder_register_filing.opening_balance_setups r join ledger.opening_bank_inputs b on b.snapshot_id=r.id and b.company_id=r.company_id and b.income_year=r.income_year on conflict(id) do update set id=excluded.id,company_id=excluded.company_id,income_year=excluded.income_year,bank_balance=excluded.bank_balance,share_capital=excluded.share_capital,share_count=excluded.share_count,nominal_value=excluded.nominal_value,locked_at=excluded.locked_at,created_by=excluded.created_by,created_at=excluded.created_at;
do $identity_collision$ begin
 if exists(select 1 from shareholder_register_filing.opening_shareholders r join public.opening_shareholders p using(id)
 where shareholder_register_filing.classify_legacy_row_v1('opening_shareholders',pg_catalog.to_jsonb(p))<>'rf')
 then raise exception 'rf1086_rollback_conflicting_projection'; end if;
end; $identity_collision$;
insert into public.opening_shareholders(id,setup_id,company_id,name,shareholder_kind,national_id,org_number,share_count,created_by,created_at) select r.id,r.setup_id,r.company_id,r.name,r.shareholder_kind,r.national_id,r.org_number,r.share_count,r.created_by,r.created_at from shareholder_register_filing.opening_shareholders r on conflict(id) do update set id=excluded.id,setup_id=excluded.setup_id,company_id=excluded.company_id,name=excluded.name,shareholder_kind=excluded.shareholder_kind,national_id=excluded.national_id,org_number=excluded.org_number,share_count=excluded.share_count,created_by=excluded.created_by,created_at=excluded.created_at;
do $identity_collision$ begin
 if exists(select 1 from shareholder_register_filing.filing_previews r join public.filing_previews p using(id)
 where shareholder_register_filing.classify_legacy_row_v1('filing_previews',pg_catalog.to_jsonb(p))<>'rf')
 then raise exception 'rf1086_rollback_conflicting_projection'; end if;
end; $identity_collision$;
insert into public.filing_previews(id,company_id,setup_id,income_year,filing,status,issues,preview,hovedskjema_xml,underskjema_xml,source,created_by,created_at) select r.id,r.company_id,r.setup_id,r.income_year,r.filing,r.status,r.issues,r.preview,r.hovedskjema_xml,r.underskjema_xml,r.source,r.created_by,r.created_at from shareholder_register_filing.filing_previews r on conflict(id) do update set id=excluded.id,company_id=excluded.company_id,setup_id=excluded.setup_id,income_year=excluded.income_year,filing=excluded.filing,status=excluded.status,issues=excluded.issues,preview=excluded.preview,hovedskjema_xml=excluded.hovedskjema_xml,underskjema_xml=excluded.underskjema_xml,source=excluded.source,created_by=excluded.created_by,created_at=excluded.created_at;
do $identity_collision$ begin
 if exists(select 1 from shareholder_register_filing.authority_permissions r join public.authority_permissions p using(id)
 where shareholder_register_filing.classify_legacy_row_v1('authority_permissions',pg_catalog.to_jsonb(p))<>'rf')
 then raise exception 'rf1086_rollback_conflicting_projection'; end if;
end; $identity_collision$;
insert into public.authority_permissions(id,company_id,obligation,submitter_user_id,confirmed_by,confirmed_at,production_enabled,updated_at) select r.id,r.company_id,r.obligation,r.submitter_user_id,r.confirmed_by,r.confirmed_at,r.production_enabled,r.updated_at from shareholder_register_filing.authority_permissions r on conflict(id) do update set id=excluded.id,company_id=excluded.company_id,obligation=excluded.obligation,submitter_user_id=excluded.submitter_user_id,confirmed_by=excluded.confirmed_by,confirmed_at=excluded.confirmed_at,production_enabled=excluded.production_enabled,updated_at=excluded.updated_at;
do $identity_collision$ begin
 if exists(select 1 from shareholder_register_filing.authority_test_runs r join public.authority_test_runs p using(id)
 where shareholder_register_filing.classify_legacy_row_v1('authority_test_runs',pg_catalog.to_jsonb(p))<>'rf')
 then raise exception 'rf1086_rollback_conflicting_projection'; end if;
end; $identity_collision$;
insert into public.authority_test_runs(id,company_id,obligation,environment,status,test_reference,feedback_summary,receipt_reference,archive_reference,evidence_url,payload_hash,recorded_by,recorded_at) select r.id,r.company_id,r.obligation,r.environment,r.status,r.test_reference,r.feedback_summary,r.receipt_reference,r.archive_reference,r.evidence_url,r.payload_hash,r.recorded_by,r.recorded_at from shareholder_register_filing.authority_test_runs r on conflict(id) do update set id=excluded.id,company_id=excluded.company_id,obligation=excluded.obligation,environment=excluded.environment,status=excluded.status,test_reference=excluded.test_reference,feedback_summary=excluded.feedback_summary,receipt_reference=excluded.receipt_reference,archive_reference=excluded.archive_reference,evidence_url=excluded.evidence_url,payload_hash=excluded.payload_hash,recorded_by=excluded.recorded_by,recorded_at=excluded.recorded_at;
do $identity_collision$ begin
 if exists(select 1 from shareholder_register_filing.filing_submissions r join public.filing_submissions p using(id)
 where shareholder_register_filing.classify_legacy_row_v1('filing_submissions',pg_catalog.to_jsonb(p))<>'rf')
 then raise exception 'rf1086_rollback_conflicting_projection'; end if;
end; $identity_collision$;
insert into public.filing_submissions(id,preview_id,company_id,setup_id,income_year,filing,mode,adapter_mode,payload_hash,idempotency_key,status,authority_confirmed_by,authority_confirmed_at,preview_confirmed_by,preview_confirmed_at,calls,receipt_id,feedback_document_ids,feedback_items,receipt_metadata,submitted_payload_ref,submitted_payload,failure_code,failure_message,created_by,submitted_by,created_at,updated_at,authority_test_run_id) select r.id,r.preview_id,r.company_id,r.setup_id,r.income_year,r.filing,r.mode,r.adapter_mode,r.payload_hash,r.idempotency_key,r.status,r.authority_confirmed_by,r.authority_confirmed_at,r.preview_confirmed_by,r.preview_confirmed_at,r.calls,r.receipt_id,r.feedback_document_ids,r.feedback_items,r.receipt_metadata,r.submitted_payload_ref,r.submitted_payload,r.failure_code,r.failure_message,r.created_by,r.submitted_by,r.created_at,r.updated_at,r.authority_test_run_id from shareholder_register_filing.filing_submissions r on conflict(id) do update set id=excluded.id,preview_id=excluded.preview_id,company_id=excluded.company_id,setup_id=excluded.setup_id,income_year=excluded.income_year,filing=excluded.filing,mode=excluded.mode,adapter_mode=excluded.adapter_mode,payload_hash=excluded.payload_hash,idempotency_key=excluded.idempotency_key,status=excluded.status,authority_confirmed_by=excluded.authority_confirmed_by,authority_confirmed_at=excluded.authority_confirmed_at,preview_confirmed_by=excluded.preview_confirmed_by,preview_confirmed_at=excluded.preview_confirmed_at,calls=excluded.calls,receipt_id=excluded.receipt_id,feedback_document_ids=excluded.feedback_document_ids,feedback_items=excluded.feedback_items,receipt_metadata=excluded.receipt_metadata,submitted_payload_ref=excluded.submitted_payload_ref,submitted_payload=excluded.submitted_payload,failure_code=excluded.failure_code,failure_message=excluded.failure_message,created_by=excluded.created_by,submitted_by=excluded.submitted_by,created_at=excluded.created_at,updated_at=excluded.updated_at,authority_test_run_id=excluded.authority_test_run_id;
do $identity_collision$ begin
 if exists(select 1 from shareholder_register_filing.filing_overrides r join public.filing_overrides p using(id)
 where shareholder_register_filing.classify_legacy_row_v1('filing_overrides',pg_catalog.to_jsonb(p))<>'rf')
 then raise exception 'rf1086_rollback_conflicting_projection'; end if;
end; $identity_collision$;
insert into public.filing_overrides(id,preview_id,company_id,income_year,filing,field_target,old_value,new_value,reason,risk_level,owner_confirmed_by,owner_confirmed_at,created_by,created_at) select r.id,r.preview_id,r.company_id,r.income_year,r.filing,r.field_target,r.old_value,r.new_value,r.reason,r.risk_level,r.owner_confirmed_by,r.owner_confirmed_at,r.created_by,r.created_at from shareholder_register_filing.filing_overrides r on conflict(id) do update set id=excluded.id,preview_id=excluded.preview_id,company_id=excluded.company_id,income_year=excluded.income_year,filing=excluded.filing,field_target=excluded.field_target,old_value=excluded.old_value,new_value=excluded.new_value,reason=excluded.reason,risk_level=excluded.risk_level,owner_confirmed_by=excluded.owner_confirmed_by,owner_confirmed_at=excluded.owner_confirmed_at,created_by=excluded.created_by,created_at=excluded.created_at;
do $identity_collision$ begin
 if exists(select 1 from shareholder_register_filing.filing_review_comments r join public.filing_review_comments p using(id)
 where shareholder_register_filing.classify_legacy_row_v1('filing_review_comments',pg_catalog.to_jsonb(p))<>'rf')
 then raise exception 'rf1086_rollback_conflicting_projection'; end if;
end; $identity_collision$;
insert into public.filing_review_comments(id,preview_id,company_id,target,severity,body,created_by,acknowledged_by,acknowledged_at,created_at) select r.id,r.preview_id,r.company_id,r.target,r.severity,r.body,r.created_by,r.acknowledged_by,r.acknowledged_at,r.created_at from shareholder_register_filing.filing_review_comments r on conflict(id) do update set id=excluded.id,preview_id=excluded.preview_id,company_id=excluded.company_id,target=excluded.target,severity=excluded.severity,body=excluded.body,created_by=excluded.created_by,acknowledged_by=excluded.acknowledged_by,acknowledged_at=excluded.acknowledged_at,created_at=excluded.created_at;
do $projection_equal$ declare a jsonb; b jsonb; begin
 select pg_catalog.jsonb_agg(pg_catalog.to_jsonb(t) - 'bank_balance' order by id) into a from public.opening_balance_setups t
 where shareholder_register_filing.classify_legacy_row_v1('opening_balance_setups',pg_catalog.to_jsonb(t))='rf';
 select pg_catalog.jsonb_agg(pg_catalog.to_jsonb(t) order by id) into b from shareholder_register_filing.opening_balance_setups t;
 if a is distinct from b then raise exception 'rf1086_rollback_projection_reconciliation_failed'; end if;
end; $projection_equal$;
do $projection_equal$ declare a jsonb; b jsonb; begin
 select pg_catalog.jsonb_agg(pg_catalog.to_jsonb(t) order by id) into a from public.opening_shareholders t
 where shareholder_register_filing.classify_legacy_row_v1('opening_shareholders',pg_catalog.to_jsonb(t))='rf';
 select pg_catalog.jsonb_agg(pg_catalog.to_jsonb(t) order by id) into b from shareholder_register_filing.opening_shareholders t;
 if a is distinct from b then raise exception 'rf1086_rollback_projection_reconciliation_failed'; end if;
end; $projection_equal$;
do $projection_equal$ declare a jsonb; b jsonb; begin
 select pg_catalog.jsonb_agg(pg_catalog.to_jsonb(t) order by id) into a from public.filing_previews t
 where shareholder_register_filing.classify_legacy_row_v1('filing_previews',pg_catalog.to_jsonb(t))='rf';
 select pg_catalog.jsonb_agg(pg_catalog.to_jsonb(t) order by id) into b from shareholder_register_filing.filing_previews t;
 if a is distinct from b then raise exception 'rf1086_rollback_projection_reconciliation_failed'; end if;
end; $projection_equal$;
do $projection_equal$ declare a jsonb; b jsonb; begin
 select pg_catalog.jsonb_agg(pg_catalog.to_jsonb(t) order by id) into a from public.filing_submissions t
 where shareholder_register_filing.classify_legacy_row_v1('filing_submissions',pg_catalog.to_jsonb(t))='rf';
 select pg_catalog.jsonb_agg(pg_catalog.to_jsonb(t) order by id) into b from shareholder_register_filing.filing_submissions t;
 if a is distinct from b then raise exception 'rf1086_rollback_projection_reconciliation_failed'; end if;
end; $projection_equal$;
do $projection_equal$ declare a jsonb; b jsonb; begin
 select pg_catalog.jsonb_agg(pg_catalog.to_jsonb(t) order by id) into a from public.filing_overrides t
 where shareholder_register_filing.classify_legacy_row_v1('filing_overrides',pg_catalog.to_jsonb(t))='rf';
 select pg_catalog.jsonb_agg(pg_catalog.to_jsonb(t) order by id) into b from shareholder_register_filing.filing_overrides t;
 if a is distinct from b then raise exception 'rf1086_rollback_projection_reconciliation_failed'; end if;
end; $projection_equal$;
do $projection_equal$ declare a jsonb; b jsonb; begin
 select pg_catalog.jsonb_agg(pg_catalog.to_jsonb(t) order by id) into a from public.filing_review_comments t
 where shareholder_register_filing.classify_legacy_row_v1('filing_review_comments',pg_catalog.to_jsonb(t))='rf';
 select pg_catalog.jsonb_agg(pg_catalog.to_jsonb(t) order by id) into b from shareholder_register_filing.filing_review_comments t;
 if a is distinct from b then raise exception 'rf1086_rollback_projection_reconciliation_failed'; end if;
end; $projection_equal$;
do $projection_equal$ declare a jsonb; b jsonb; begin
 select pg_catalog.jsonb_agg(pg_catalog.to_jsonb(t) order by id) into a from public.authority_permissions t
 where shareholder_register_filing.classify_legacy_row_v1('authority_permissions',pg_catalog.to_jsonb(t))='rf';
 select pg_catalog.jsonb_agg(pg_catalog.to_jsonb(t) order by id) into b from shareholder_register_filing.authority_permissions t;
 if a is distinct from b then raise exception 'rf1086_rollback_projection_reconciliation_failed'; end if;
end; $projection_equal$;
do $projection_equal$ declare a jsonb; b jsonb; begin
 select pg_catalog.jsonb_agg(pg_catalog.to_jsonb(t) order by id) into a from public.authority_test_runs t
 where shareholder_register_filing.classify_legacy_row_v1('authority_test_runs',pg_catalog.to_jsonb(t))='rf';
 select pg_catalog.jsonb_agg(pg_catalog.to_jsonb(t) order by id) into b from shareholder_register_filing.authority_test_runs t;
 if a is distinct from b then raise exception 'rf1086_rollback_projection_reconciliation_failed'; end if;
end; $projection_equal$;
do $restore_projection_triggers$ declare t record; begin
 for t in select * from rf151_reverse_triggers loop
  execute pg_catalog.format('alter table %s %s trigger %I',t.relation,
   case t.enabled when 'D' then 'disable' when 'A' then 'enable always' when 'R' then 'enable replica' else 'enable' end,t.name);
 end loop;
end; $restore_projection_triggers$;
drop trigger rf151_preparation_projection on shareholder_register_filing.filing_previews;
drop trigger rf151_preparation_projection on shareholder_register_filing.filing_submissions;
drop trigger rf151_preparation_projection on shareholder_register_filing.filing_overrides;
drop trigger rf151_preparation_projection on shareholder_register_filing.filing_review_comments;
drop trigger rf151_preparation_projection on shareholder_register_filing.authority_permissions;
drop trigger rf151_preparation_projection on shareholder_register_filing.authority_test_runs;
drop function backend_system.sync_rf_preparation_projection_v1();
alter table shareholder_register_filing.filing_approval_snapshots drop constraint filing_approval_snapshots_preview_id_fkey;
alter table shareholder_register_filing.filing_approval_snapshots add constraint filing_approval_snapshots_preview_id_fkey
 foreign key(preview_id) references public.filing_previews(id) on delete restrict;

create temporary table rf151_archive_grant on commit drop as select pg_catalog.has_function_privilege(current_user,'public.company_archive_track_source_write_v1()','EXECUTE') as had_execute;
do $grant_archive$ declare principal name:=current_user; begin
 execute 'set local role company_archive_projection_executor';
 execute pg_catalog.format('grant execute on function public.company_archive_track_source_write_v1() to %I',principal);
 execute 'reset role';
end; $grant_archive$;


drop trigger company_archive_track_opening_bank_inputs on ledger.opening_bank_inputs;
drop trigger company_archive_track_filing_previews on shareholder_register_filing.filing_previews;
drop trigger company_archive_track_filing_previews on public.filing_previews;
CREATE TRIGGER company_archive_track_filing_previews BEFORE INSERT OR DELETE OR UPDATE ON public.filing_previews FOR EACH ROW EXECUTE FUNCTION public.company_archive_track_source_write_v1('year', 'company_id');
drop trigger company_archive_track_filing_submissions on shareholder_register_filing.filing_submissions;
drop trigger company_archive_track_filing_submissions on public.filing_submissions;
CREATE TRIGGER company_archive_track_filing_submissions BEFORE INSERT OR DELETE OR UPDATE ON public.filing_submissions FOR EACH ROW EXECUTE FUNCTION public.company_archive_track_source_write_v1('year', 'company_id');
drop trigger company_archive_track_filing_review_comments on shareholder_register_filing.filing_review_comments;
drop trigger company_archive_track_filing_review_comments on public.filing_review_comments;
CREATE TRIGGER company_archive_track_filing_review_comments BEFORE INSERT OR DELETE OR UPDATE ON public.filing_review_comments FOR EACH ROW EXECUTE FUNCTION public.company_archive_track_source_write_v1('company', 'company_id');
drop trigger company_archive_track_authority_permissions on shareholder_register_filing.authority_permissions;
drop trigger company_archive_track_authority_permissions on public.authority_permissions;
CREATE TRIGGER company_archive_track_authority_permissions BEFORE INSERT OR DELETE OR UPDATE ON public.authority_permissions FOR EACH ROW EXECUTE FUNCTION public.company_archive_track_source_write_v1('company', 'company_id');
drop trigger company_archive_track_authority_test_runs on shareholder_register_filing.authority_test_runs;
drop trigger company_archive_track_authority_test_runs on public.authority_test_runs;
CREATE TRIGGER company_archive_track_authority_test_runs BEFORE INSERT OR DELETE OR UPDATE ON public.authority_test_runs FOR EACH ROW EXECUTE FUNCTION public.company_archive_track_source_write_v1('company', 'company_id');
drop trigger company_archive_track_opening_balance_setups on shareholder_register_filing.opening_balance_setups;
drop trigger company_archive_track_opening_balance_setups on public.opening_balance_setups;
CREATE TRIGGER company_archive_track_opening_balance_setups BEFORE INSERT OR DELETE OR UPDATE ON public.opening_balance_setups FOR EACH ROW EXECUTE FUNCTION public.company_archive_track_source_write_v1('year', 'company_id');
drop trigger company_archive_track_opening_shareholders on shareholder_register_filing.opening_shareholders;
drop trigger company_archive_track_opening_shareholders on public.opening_shareholders;
CREATE TRIGGER company_archive_track_opening_shareholders BEFORE INSERT OR DELETE OR UPDATE ON public.opening_shareholders FOR EACH ROW EXECUTE FUNCTION public.company_archive_track_source_write_v1('company', 'company_id');
do $restore_archive_grant$ declare principal name:=current_user; begin
 if not (select had_execute from rf151_archive_grant) then
  execute 'set local role company_archive_projection_executor';
  execute pg_catalog.format('revoke execute on function public.company_archive_track_source_write_v1() from %I',principal);
  execute 'reset role';
 end if;
end; $restore_archive_grant$;


-- Every preparation command now writes public; its existing after-trigger
-- mirrors canonical storage. Direct retired RF writes stay blocked in other phases.
update shareholder_register_filing.migration_state set phase='legacy_overlap' where singleton;

-- Refuse any accidental canonical mutation, including timestamps/leases and
-- retained migration evidence. Only migration_state.phase may change.
do $unchanged_canonical$ declare r record; digest text; migration_role name:=current_user; begin
 for r in select a.*,h.digest expected from rf151_reverse_read_access a join rf151_reverse_hashes h using(relation) loop
  execute pg_catalog.format('select pg_catalog.encode(extensions.digest(coalesce(pg_catalog.string_agg(pg_catalog.to_jsonb(t)::text,E''\n'' order by pg_catalog.to_jsonb(t)::text),pg_catalog.left(''x'',0)),''sha256''),''hex'') from %s t',r.relation) into digest;
  if digest is distinct from r.expected then raise exception 'rf1086_reverse_changed_canonical_evidence'; end if;
  execute pg_catalog.format('set local role %I',r.owner);
  execute pg_catalog.format('drop policy rf151_reverse_read_snapshot on %s',r.relation);
  if not r.had_select and r.owner<>migration_role then execute pg_catalog.format('revoke select on %s from %I',r.relation,migration_role); end if;
  execute 'reset role';
 end loop;
end; $unchanged_canonical$;

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
