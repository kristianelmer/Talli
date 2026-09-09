-- Full RF rollback follows receiver/backend rollback. Preserve every current RF row and bank input.
begin;
set local lock_timeout='5s';
set local statement_timeout='120s';
select pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended('talli:rf1086:capability:v1',0));

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

create temporary table rf151_schema_grants on commit drop as select false as ledger_create,false as company_access_create,false as workflow_create,false as backend_create;

create temporary table rf151_saved_objects on commit drop as select original_objects,original_relations from shareholder_register_filing.migration_state where singleton;

lock table public.opening_balance_setups,public.opening_shareholders,public.filing_previews,public.filing_submissions,public.filing_overrides,public.filing_review_comments,public.authority_permissions,public.authority_test_runs,shareholder_register_filing.opening_balance_setups,shareholder_register_filing.opening_shareholders,shareholder_register_filing.filing_previews,shareholder_register_filing.filing_submissions,shareholder_register_filing.filing_overrides,shareholder_register_filing.filing_review_comments,shareholder_register_filing.authority_permissions,shareholder_register_filing.authority_test_runs,shareholder_register_filing.filing_approval_snapshots,shareholder_register_filing.production_filing_submissions,shareholder_register_filing.production_filing_events,shareholder_register_filing.production_feedback_artifacts in access exclusive mode;

drop trigger if exists rf151_legacy_write_barrier on public.opening_balance_setups;

drop trigger if exists rf151_legacy_projection on public.opening_balance_setups;

drop trigger if exists rf151_preparation_projection on shareholder_register_filing.opening_balance_setups;

drop trigger if exists rf151_legacy_write_barrier on public.opening_shareholders;

drop trigger if exists rf151_legacy_projection on public.opening_shareholders;

drop trigger if exists rf151_preparation_projection on shareholder_register_filing.opening_shareholders;

drop trigger if exists rf151_legacy_write_barrier on public.filing_previews;

drop trigger if exists rf151_legacy_projection on public.filing_previews;

drop trigger if exists rf151_preparation_projection on shareholder_register_filing.filing_previews;

drop trigger if exists rf151_legacy_write_barrier on public.filing_submissions;

drop trigger if exists rf151_legacy_projection on public.filing_submissions;

drop trigger if exists rf151_preparation_projection on shareholder_register_filing.filing_submissions;

drop trigger if exists rf151_legacy_write_barrier on public.filing_overrides;

drop trigger if exists rf151_legacy_projection on public.filing_overrides;

drop trigger if exists rf151_preparation_projection on shareholder_register_filing.filing_overrides;

drop trigger if exists rf151_legacy_write_barrier on public.filing_review_comments;

drop trigger if exists rf151_legacy_projection on public.filing_review_comments;

drop trigger if exists rf151_preparation_projection on shareholder_register_filing.filing_review_comments;

drop trigger if exists rf151_legacy_write_barrier on public.authority_permissions;

drop trigger if exists rf151_legacy_projection on public.authority_permissions;

drop trigger if exists rf151_preparation_projection on shareholder_register_filing.authority_permissions;

drop trigger if exists rf151_legacy_write_barrier on public.authority_test_runs;

drop trigger if exists rf151_legacy_projection on public.authority_test_runs;

drop trigger if exists rf151_preparation_projection on shareholder_register_filing.authority_test_runs;

drop trigger if exists rf151_opening_projection on shareholder_register_filing.opening_balance_setups;

drop trigger if exists rf151_shareholder_projection on shareholder_register_filing.opening_shareholders;

drop trigger if exists rf151_scope_admission on shareholder_register_filing.opening_balance_setups;

drop trigger if exists rf151_capture_legacy_bank on public.opening_balance_setups;

alter table shareholder_register_filing.opening_balance_setups no force row level security;

grant select,insert,update,delete on shareholder_register_filing.opening_balance_setups to postgres;

alter table shareholder_register_filing.opening_shareholders no force row level security;

grant select,insert,update,delete on shareholder_register_filing.opening_shareholders to postgres;

alter table shareholder_register_filing.filing_previews no force row level security;

grant select,insert,update,delete on shareholder_register_filing.filing_previews to postgres;

alter table shareholder_register_filing.filing_submissions no force row level security;

grant select,insert,update,delete on shareholder_register_filing.filing_submissions to postgres;

alter table shareholder_register_filing.filing_overrides no force row level security;

grant select,insert,update,delete on shareholder_register_filing.filing_overrides to postgres;

alter table shareholder_register_filing.filing_review_comments no force row level security;

grant select,insert,update,delete on shareholder_register_filing.filing_review_comments to postgres;

alter table shareholder_register_filing.authority_permissions no force row level security;

grant select,insert,update,delete on shareholder_register_filing.authority_permissions to postgres;

alter table shareholder_register_filing.authority_test_runs no force row level security;

grant select,insert,update,delete on shareholder_register_filing.authority_test_runs to postgres;

alter table shareholder_register_filing.filing_approval_snapshots no force row level security;

grant select,insert,update,delete on shareholder_register_filing.filing_approval_snapshots to postgres;

alter table shareholder_register_filing.production_filing_submissions no force row level security;

grant select,insert,update,delete on shareholder_register_filing.production_filing_submissions to postgres;

alter table shareholder_register_filing.production_filing_events no force row level security;

grant select,insert,update,delete on shareholder_register_filing.production_filing_events to postgres;

alter table shareholder_register_filing.production_feedback_artifacts no force row level security;

grant select,insert,update,delete on shareholder_register_filing.production_feedback_artifacts to postgres;

alter table ledger.opening_bank_inputs no force row level security; grant select on ledger.opening_bank_inputs to postgres;

update shareholder_register_filing.migration_state set phase='legacy_overlap' where singleton;

do $bank$ begin if exists(select 1 from shareholder_register_filing.opening_balance_setups r left join ledger.opening_bank_inputs b on b.snapshot_id=r.id and b.company_id=r.company_id and b.income_year=r.income_year where b.snapshot_id is null or b.recorded_by<>r.created_by or b.recorded_at<>r.created_at) then raise exception 'rf1086_rollback_bank_input_missing'; end if; end; $bank$;

insert into public.opening_balance_setups(id,company_id,income_year,bank_balance,share_capital,share_count,nominal_value,locked_at,created_by,created_at) select r.id,r.company_id,r.income_year,b.bank_balance_nok,r.share_capital,r.share_count,r.nominal_value,r.locked_at,r.created_by,r.created_at from shareholder_register_filing.opening_balance_setups r join ledger.opening_bank_inputs b on b.snapshot_id=r.id and b.company_id=r.company_id and b.income_year=r.income_year on conflict(id) do update set id=excluded.id,company_id=excluded.company_id,income_year=excluded.income_year,bank_balance=excluded.bank_balance,share_capital=excluded.share_capital,share_count=excluded.share_count,nominal_value=excluded.nominal_value,locked_at=excluded.locked_at,created_by=excluded.created_by,created_at=excluded.created_at;

insert into public.opening_shareholders(id,setup_id,company_id,name,shareholder_kind,national_id,org_number,share_count,created_by,created_at) select r.id,r.setup_id,r.company_id,r.name,r.shareholder_kind,r.national_id,r.org_number,r.share_count,r.created_by,r.created_at from shareholder_register_filing.opening_shareholders r on conflict(id) do update set id=excluded.id,setup_id=excluded.setup_id,company_id=excluded.company_id,name=excluded.name,shareholder_kind=excluded.shareholder_kind,national_id=excluded.national_id,org_number=excluded.org_number,share_count=excluded.share_count,created_by=excluded.created_by,created_at=excluded.created_at;

insert into public.filing_previews(id,company_id,setup_id,income_year,filing,status,issues,preview,hovedskjema_xml,underskjema_xml,source,created_by,created_at) select r.id,r.company_id,r.setup_id,r.income_year,r.filing,r.status,r.issues,r.preview,r.hovedskjema_xml,r.underskjema_xml,r.source,r.created_by,r.created_at from shareholder_register_filing.filing_previews r on conflict(id) do update set id=excluded.id,company_id=excluded.company_id,setup_id=excluded.setup_id,income_year=excluded.income_year,filing=excluded.filing,status=excluded.status,issues=excluded.issues,preview=excluded.preview,hovedskjema_xml=excluded.hovedskjema_xml,underskjema_xml=excluded.underskjema_xml,source=excluded.source,created_by=excluded.created_by,created_at=excluded.created_at;

insert into public.filing_submissions(id,preview_id,company_id,setup_id,income_year,filing,mode,adapter_mode,payload_hash,idempotency_key,status,authority_confirmed_by,authority_confirmed_at,preview_confirmed_by,preview_confirmed_at,calls,receipt_id,feedback_document_ids,feedback_items,receipt_metadata,submitted_payload_ref,submitted_payload,failure_code,failure_message,created_by,submitted_by,created_at,updated_at,authority_test_run_id) select r.id,r.preview_id,r.company_id,r.setup_id,r.income_year,r.filing,r.mode,r.adapter_mode,r.payload_hash,r.idempotency_key,r.status,r.authority_confirmed_by,r.authority_confirmed_at,r.preview_confirmed_by,r.preview_confirmed_at,r.calls,r.receipt_id,r.feedback_document_ids,r.feedback_items,r.receipt_metadata,r.submitted_payload_ref,r.submitted_payload,r.failure_code,r.failure_message,r.created_by,r.submitted_by,r.created_at,r.updated_at,r.authority_test_run_id from shareholder_register_filing.filing_submissions r on conflict(id) do update set id=excluded.id,preview_id=excluded.preview_id,company_id=excluded.company_id,setup_id=excluded.setup_id,income_year=excluded.income_year,filing=excluded.filing,mode=excluded.mode,adapter_mode=excluded.adapter_mode,payload_hash=excluded.payload_hash,idempotency_key=excluded.idempotency_key,status=excluded.status,authority_confirmed_by=excluded.authority_confirmed_by,authority_confirmed_at=excluded.authority_confirmed_at,preview_confirmed_by=excluded.preview_confirmed_by,preview_confirmed_at=excluded.preview_confirmed_at,calls=excluded.calls,receipt_id=excluded.receipt_id,feedback_document_ids=excluded.feedback_document_ids,feedback_items=excluded.feedback_items,receipt_metadata=excluded.receipt_metadata,submitted_payload_ref=excluded.submitted_payload_ref,submitted_payload=excluded.submitted_payload,failure_code=excluded.failure_code,failure_message=excluded.failure_message,created_by=excluded.created_by,submitted_by=excluded.submitted_by,created_at=excluded.created_at,updated_at=excluded.updated_at,authority_test_run_id=excluded.authority_test_run_id;

insert into public.filing_overrides(id,preview_id,company_id,income_year,filing,field_target,old_value,new_value,reason,risk_level,owner_confirmed_by,owner_confirmed_at,created_by,created_at) select r.id,r.preview_id,r.company_id,r.income_year,r.filing,r.field_target,r.old_value,r.new_value,r.reason,r.risk_level,r.owner_confirmed_by,r.owner_confirmed_at,r.created_by,r.created_at from shareholder_register_filing.filing_overrides r on conflict(id) do update set id=excluded.id,preview_id=excluded.preview_id,company_id=excluded.company_id,income_year=excluded.income_year,filing=excluded.filing,field_target=excluded.field_target,old_value=excluded.old_value,new_value=excluded.new_value,reason=excluded.reason,risk_level=excluded.risk_level,owner_confirmed_by=excluded.owner_confirmed_by,owner_confirmed_at=excluded.owner_confirmed_at,created_by=excluded.created_by,created_at=excluded.created_at;

insert into public.filing_review_comments(id,preview_id,company_id,target,severity,body,created_by,acknowledged_by,acknowledged_at,created_at) select r.id,r.preview_id,r.company_id,r.target,r.severity,r.body,r.created_by,r.acknowledged_by,r.acknowledged_at,r.created_at from shareholder_register_filing.filing_review_comments r on conflict(id) do update set id=excluded.id,preview_id=excluded.preview_id,company_id=excluded.company_id,target=excluded.target,severity=excluded.severity,body=excluded.body,created_by=excluded.created_by,acknowledged_by=excluded.acknowledged_by,acknowledged_at=excluded.acknowledged_at,created_at=excluded.created_at;

insert into public.authority_permissions(id,company_id,obligation,submitter_user_id,confirmed_by,confirmed_at,production_enabled,updated_at) select r.id,r.company_id,r.obligation,r.submitter_user_id,r.confirmed_by,r.confirmed_at,r.production_enabled,r.updated_at from shareholder_register_filing.authority_permissions r on conflict(id) do update set id=excluded.id,company_id=excluded.company_id,obligation=excluded.obligation,submitter_user_id=excluded.submitter_user_id,confirmed_by=excluded.confirmed_by,confirmed_at=excluded.confirmed_at,production_enabled=excluded.production_enabled,updated_at=excluded.updated_at;

insert into public.authority_test_runs(id,company_id,obligation,environment,status,test_reference,feedback_summary,receipt_reference,archive_reference,evidence_url,payload_hash,recorded_by,recorded_at) select r.id,r.company_id,r.obligation,r.environment,r.status,r.test_reference,r.feedback_summary,r.receipt_reference,r.archive_reference,r.evidence_url,r.payload_hash,r.recorded_by,r.recorded_at from shareholder_register_filing.authority_test_runs r on conflict(id) do update set id=excluded.id,company_id=excluded.company_id,obligation=excluded.obligation,environment=excluded.environment,status=excluded.status,test_reference=excluded.test_reference,feedback_summary=excluded.feedback_summary,receipt_reference=excluded.receipt_reference,archive_reference=excluded.archive_reference,evidence_url=excluded.evidence_url,payload_hash=excluded.payload_hash,recorded_by=excluded.recorded_by,recorded_at=excluded.recorded_at;

drop policy if exists "legacy_rf1086_approval_read" on shareholder_register_filing.filing_approval_snapshots;

drop policy if exists "legacy_rf1086_preview_read" on public.filing_previews;

drop policy if exists "legacy_rf1086_artifact_read" on shareholder_register_filing.production_feedback_artifacts;

drop policy if exists "legacy_rf1086_event_read" on shareholder_register_filing.production_filing_events;

drop policy if exists "legacy_rf1086_submission_read" on shareholder_register_filing.production_filing_submissions;

drop function if exists public.release_production_feedback_reconciliation(uuid, uuid);

drop function if exists public.approve_production_filing(uuid, uuid, jsonb, text, text);

drop function if exists public.append_production_filing_event(uuid, text, text, integer, text, uuid, text, text, text, boolean);

drop function if exists public.begin_production_filing(uuid);

drop function if exists public.claim_production_feedback_reconciliation(uuid, uuid);

drop function if exists public.record_production_feedback_artifact(uuid, uuid, uuid, text, text, bigint, text, text);

drop function if exists legacy_rf1086.assert_fresh_owner_v1(uuid);

drop function if exists legacy_rf1086.actor_v1();

drop function if exists legacy_rf1086.can_read_company_v1(uuid);

drop function if exists legacy_rf1086.can_read_submission_v1(uuid);

drop function if exists legacy_rf1086.assert_submission_v1(uuid);

drop function if exists legacy_rf1086.prepare_operation_v1(uuid, text, text, uuid);

drop function if exists public.append_production_feedback_reconciliation(uuid, uuid, uuid, text, text[], text, text);

drop view if exists public.filing_approval_snapshots;

alter table shareholder_register_filing.filing_approval_snapshots set schema public;

alter table public.filing_approval_snapshots owner to postgres;

drop view if exists public.production_filing_submissions;

alter table shareholder_register_filing.production_filing_submissions set schema public;

alter table public.production_filing_submissions owner to postgres;

drop view if exists public.production_filing_events;

alter table shareholder_register_filing.production_filing_events set schema public;

alter table public.production_filing_events owner to postgres;

drop view if exists public.production_feedback_artifacts;

alter table shareholder_register_filing.production_feedback_artifacts set schema public;

alter table public.production_feedback_artifacts owner to postgres;

alter table public.filing_approval_snapshots drop constraint filing_approval_snapshots_preview_id_fkey; alter table public.filing_approval_snapshots add constraint filing_approval_snapshots_preview_id_fkey foreign key(preview_id) references public.filing_previews(id) on delete restrict;

create temporary table rf151_function_schema_grants(schema_name name,role_name name,had_create boolean,primary key(schema_name,role_name)) on commit drop;
do $original_functions$ declare item record; signature text; schema_name text; function_owner text; current_grantee oid; v_acl record; grantee text; begin
 for item in select * from pg_catalog.jsonb_each((select original_objects from rf151_saved_objects)) loop
  schema_name:=pg_catalog.split_part(item.key,'.',1); function_owner:=item.value->>'owner';
  insert into rf151_function_schema_grants values(schema_name,function_owner,pg_catalog.has_schema_privilege(function_owner,schema_name,'CREATE')) on conflict do nothing;
  execute pg_catalog.format('grant create on schema %I to %I',schema_name,function_owner);
  execute pg_catalog.format('set local role %I',function_owner);
  execute item.value->>'definition';
  execute 'reset role';
  signature:=item.key;
  for current_grantee in select distinct a.grantee from pg_catalog.pg_proc p cross join lateral pg_catalog.aclexplode(p.proacl) a where p.oid=signature::regprocedure loop
   grantee:=case when current_grantee=0 then 'public' else pg_catalog.quote_ident(pg_catalog.pg_get_userbyid(current_grantee)) end;
   execute 'revoke all on function '||signature||' from '||grantee;
  end loop;
  execute 'revoke all on function '||signature||' from public';
  if item.value->'acl'='null'::jsonb then
   execute 'grant execute on function '||signature||' to public,'||pg_catalog.quote_ident(function_owner);
  else
   for v_acl in select * from pg_catalog.aclexplode(array(select value::aclitem from pg_catalog.jsonb_array_elements_text(item.value->'acl'))) loop
    grantee:=case when v_acl.grantee=0 then 'public' else pg_catalog.quote_ident(pg_catalog.pg_get_userbyid(v_acl.grantee)) end;
    execute 'grant execute on function '||signature||' to '||grantee||case when v_acl.is_grantable then ' with grant option' else '' end;
   end loop;
  end if;
 end loop;
end; $original_functions$;

do $restore_relations$ declare item record; current_grantee oid; acl record; target text; grantee text; begin
 for item in select * from pg_catalog.jsonb_each((select original_relations from rf151_saved_objects)) loop
  target:='public.'||pg_catalog.quote_ident(item.key);
  for current_grantee in select distinct a.grantee from pg_catalog.pg_class c cross join lateral pg_catalog.aclexplode(c.relacl) a where c.oid=pg_catalog.to_regclass(target) loop
   grantee:=case when current_grantee=0 then 'public' else pg_catalog.quote_ident(pg_catalog.pg_get_userbyid(current_grantee)) end;
   execute 'revoke all on '||target||' from '||grantee;
  end loop;
  if item.value->'acl'='null'::jsonb then execute pg_catalog.format('grant all on %s to %I',target,item.value->>'owner');
  else
   for acl in select * from pg_catalog.aclexplode(array(select value::aclitem from pg_catalog.jsonb_array_elements_text(item.value->'acl'))) loop
    grantee:=case when acl.grantee=0 then 'public' else pg_catalog.quote_ident(pg_catalog.pg_get_userbyid(acl.grantee)) end;
    execute 'grant '||acl.privilege_type||' on '||target||' to '||grantee||case when acl.is_grantable then ' with grant option' else '' end;
   end loop;
  end if;
  if (item.value->>'force_rls')::boolean then execute 'alter table '||target||' force row level security';
  else execute 'alter table '||target||' no force row level security'; end if;
 end loop;
end; $restore_relations$;

do $policies$ declare item record; begin
 for item in select n.nspname,c.relname,p.polname from pg_catalog.pg_policy p join pg_catalog.pg_class c on c.oid=p.polrelid join pg_catalog.pg_namespace n on n.oid=c.relnamespace where n.nspname='public' and p.polname like 'rf151_%' loop
  execute pg_catalog.format('drop policy %I on %I.%I',item.polname,item.nspname,item.relname);
 end loop;
end; $policies$;

create policy "legacy_rf1086_approval_read" on public.filing_approval_snapshots for SELECT to "legacy_rf1086_executor" using (((user_id = legacy_rf1086.actor_v1()) AND legacy_rf1086.can_read_company_v1(company_id)));

create policy "legacy_rf1086_preview_read" on public.filing_previews for SELECT to "legacy_rf1086_executor" using (legacy_rf1086.can_read_company_v1(company_id));

create policy "legacy_rf1086_artifact_read" on public.production_feedback_artifacts for SELECT to "legacy_rf1086_executor" using (legacy_rf1086.can_read_submission_v1(submission_id));

create policy "legacy_rf1086_event_read" on public.production_filing_events for SELECT to "legacy_rf1086_executor" using (legacy_rf1086.can_read_submission_v1(submission_id));

create policy "legacy_rf1086_submission_read" on public.production_filing_submissions for SELECT to "legacy_rf1086_executor" using (((user_id = legacy_rf1086.actor_v1()) AND legacy_rf1086.can_read_company_v1(company_id)));

grant execute on function public.company_archive_track_source_write_v1() to postgres;

drop trigger company_archive_track_filing_previews on public.filing_previews;

CREATE TRIGGER company_archive_track_filing_previews BEFORE INSERT OR DELETE OR UPDATE ON public.filing_previews FOR EACH ROW EXECUTE FUNCTION public.company_archive_track_source_write_v1('year', 'company_id');

drop trigger company_archive_track_filing_submissions on public.filing_submissions;

CREATE TRIGGER company_archive_track_filing_submissions BEFORE INSERT OR DELETE OR UPDATE ON public.filing_submissions FOR EACH ROW EXECUTE FUNCTION public.company_archive_track_source_write_v1('year', 'company_id');

drop trigger company_archive_track_filing_review_comments on public.filing_review_comments;

CREATE TRIGGER company_archive_track_filing_review_comments BEFORE INSERT OR DELETE OR UPDATE ON public.filing_review_comments FOR EACH ROW EXECUTE FUNCTION public.company_archive_track_source_write_v1('company', 'company_id');

drop trigger company_archive_track_authority_permissions on public.authority_permissions;

CREATE TRIGGER company_archive_track_authority_permissions BEFORE INSERT OR DELETE OR UPDATE ON public.authority_permissions FOR EACH ROW EXECUTE FUNCTION public.company_archive_track_source_write_v1('company', 'company_id');

drop trigger company_archive_track_authority_test_runs on public.authority_test_runs;

CREATE TRIGGER company_archive_track_authority_test_runs BEFORE INSERT OR DELETE OR UPDATE ON public.authority_test_runs FOR EACH ROW EXECUTE FUNCTION public.company_archive_track_source_write_v1('company', 'company_id');

drop trigger company_archive_track_opening_balance_setups on public.opening_balance_setups;

CREATE TRIGGER company_archive_track_opening_balance_setups BEFORE INSERT OR DELETE OR UPDATE ON public.opening_balance_setups FOR EACH ROW EXECUTE FUNCTION public.company_archive_track_source_write_v1('year', 'company_id');

drop trigger company_archive_track_opening_shareholders on public.opening_shareholders;

CREATE TRIGGER company_archive_track_opening_shareholders BEFORE INSERT OR DELETE OR UPDATE ON public.opening_shareholders FOR EACH ROW EXECUTE FUNCTION public.company_archive_track_source_write_v1('company', 'company_id');

revoke execute on function public.company_archive_track_source_write_v1() from postgres;

drop function if exists backend_system.read_new_year_opening_snapshots_v1(uuid[],text,integer,text);

drop function if exists backend_system.sync_rf_preparation_projection_v1();

drop function if exists backend_system.sync_rf_opening_projection_v1();

drop function if exists backend_system.capture_legacy_rf_opening_bank_v1();

drop function if exists backend_system.admit_rf_opening_scope_v1();

drop function if exists backend_system.rf_opening_quarantine_count_v1(uuid,uuid[]);

drop function if exists backend_system.rf1086_stored_release_inputs_v1(uuid,integer,text);

drop function if exists backend_system.rf1086_annual_readiness_ready_v1(uuid,integer,text);

drop function if exists backend_system.rf1086_technical_release_ready_v1();

drop function ledger.record_opening_bank_input_v1(uuid,uuid,integer,numeric,text);
drop function ledger.read_opening_bank_inputs_v1(uuid,integer,text);
drop function if exists ledger.capture_legacy_opening_bank_input_v1(uuid,uuid,integer,numeric,uuid,timestamptz);
drop table ledger.opening_bank_inputs;

revoke select,insert,update on public.opening_balance_setups from shareholder_register_filing_store_owner;

revoke select,insert,update on public.opening_shareholders from shareholder_register_filing_store_owner;

revoke select,insert,update on public.filing_previews from shareholder_register_filing_store_owner;

revoke select,insert,update on public.filing_submissions from shareholder_register_filing_store_owner;

revoke select,insert,update on public.filing_overrides from shareholder_register_filing_store_owner;

revoke select,insert,update on public.filing_review_comments from shareholder_register_filing_store_owner;

revoke select,insert,update on public.authority_permissions from shareholder_register_filing_store_owner;

revoke select,insert,update on public.authority_test_runs from shareholder_register_filing_store_owner;

drop schema shareholder_register_filing cascade;

drop function public.company_access_can_review_filing_v1(uuid); drop function public.company_access_read_rf_company_identity_v1(uuid,text);

revoke shareholder_register_filing_executor from talli_ledger_backend;

do $function_schema_cleanup$ declare r record; begin
 for r in select * from rf151_function_schema_grants where not had_create loop
 execute pg_catalog.format('revoke create on schema %I from %I',r.schema_name,r.role_name);
 end loop;
end; $function_schema_cleanup$;

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
