-- Atomic transfer of the RF writer; generic sibling operations remain unchanged.
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

create temporary table rf151_schema_grants on commit drop as select false as ledger_create,false as company_access_create,false as workflow_create,not pg_catalog.has_schema_privilege(current_user,'backend_system','CREATE') as backend_create; do $g$ begin execute pg_catalog.format('grant create on schema backend_system to %I',current_user); end; $g$;

lock table public.opening_balance_setups,public.opening_shareholders,public.filing_previews,public.filing_submissions,public.filing_overrides,public.filing_review_comments,public.authority_permissions,public.authority_test_runs,shareholder_register_filing.opening_balance_setups,shareholder_register_filing.opening_shareholders,shareholder_register_filing.filing_previews,shareholder_register_filing.filing_submissions,shareholder_register_filing.filing_overrides,shareholder_register_filing.filing_review_comments,shareholder_register_filing.authority_permissions,shareholder_register_filing.authority_test_runs,shareholder_register_filing.filing_approval_snapshots,shareholder_register_filing.production_filing_submissions,shareholder_register_filing.production_filing_events,shareholder_register_filing.production_feedback_artifacts in access exclusive mode;

do $guard$ begin if shareholder_register_filing.phase_v1()<>'legacy_overlap' then raise exception 'rf1086_cutover_wrong_phase'; end if; end; $guard$;

do $verify$ declare a jsonb; b jsonb; begin
 select pg_catalog.jsonb_agg(pg_catalog.to_jsonb(t) - 'bank_balance' order by id) into a from public.opening_balance_setups t where shareholder_register_filing.classify_legacy_row_v1('opening_balance_setups',pg_catalog.to_jsonb(t))='rf';
 select pg_catalog.jsonb_agg(pg_catalog.to_jsonb(t) order by id) into b from shareholder_register_filing.opening_balance_setups t;
 if a is distinct from b then raise exception 'rf1086_cutover_reconciliation_failed'; end if;
end; $verify$;

do $verify$ declare a jsonb; b jsonb; begin
 select pg_catalog.jsonb_agg(pg_catalog.to_jsonb(t) order by id) into a from public.opening_shareholders t where shareholder_register_filing.classify_legacy_row_v1('opening_shareholders',pg_catalog.to_jsonb(t))='rf';
 select pg_catalog.jsonb_agg(pg_catalog.to_jsonb(t) order by id) into b from shareholder_register_filing.opening_shareholders t;
 if a is distinct from b then raise exception 'rf1086_cutover_reconciliation_failed'; end if;
end; $verify$;

do $verify$ declare a jsonb; b jsonb; begin
 select pg_catalog.jsonb_agg(pg_catalog.to_jsonb(t) order by id) into a from public.filing_previews t where shareholder_register_filing.classify_legacy_row_v1('filing_previews',pg_catalog.to_jsonb(t))='rf';
 select pg_catalog.jsonb_agg(pg_catalog.to_jsonb(t) order by id) into b from shareholder_register_filing.filing_previews t;
 if a is distinct from b then raise exception 'rf1086_cutover_reconciliation_failed'; end if;
end; $verify$;

do $verify$ declare a jsonb; b jsonb; begin
 select pg_catalog.jsonb_agg(pg_catalog.to_jsonb(t) order by id) into a from public.filing_submissions t where shareholder_register_filing.classify_legacy_row_v1('filing_submissions',pg_catalog.to_jsonb(t))='rf';
 select pg_catalog.jsonb_agg(pg_catalog.to_jsonb(t) order by id) into b from shareholder_register_filing.filing_submissions t;
 if a is distinct from b then raise exception 'rf1086_cutover_reconciliation_failed'; end if;
end; $verify$;

do $verify$ declare a jsonb; b jsonb; begin
 select pg_catalog.jsonb_agg(pg_catalog.to_jsonb(t) order by id) into a from public.filing_overrides t where shareholder_register_filing.classify_legacy_row_v1('filing_overrides',pg_catalog.to_jsonb(t))='rf';
 select pg_catalog.jsonb_agg(pg_catalog.to_jsonb(t) order by id) into b from shareholder_register_filing.filing_overrides t;
 if a is distinct from b then raise exception 'rf1086_cutover_reconciliation_failed'; end if;
end; $verify$;

do $verify$ declare a jsonb; b jsonb; begin
 select pg_catalog.jsonb_agg(pg_catalog.to_jsonb(t) order by id) into a from public.filing_review_comments t where shareholder_register_filing.classify_legacy_row_v1('filing_review_comments',pg_catalog.to_jsonb(t))='rf';
 select pg_catalog.jsonb_agg(pg_catalog.to_jsonb(t) order by id) into b from shareholder_register_filing.filing_review_comments t;
 if a is distinct from b then raise exception 'rf1086_cutover_reconciliation_failed'; end if;
end; $verify$;

do $verify$ declare a jsonb; b jsonb; begin
 select pg_catalog.jsonb_agg(pg_catalog.to_jsonb(t) order by id) into a from public.authority_permissions t where shareholder_register_filing.classify_legacy_row_v1('authority_permissions',pg_catalog.to_jsonb(t))='rf';
 select pg_catalog.jsonb_agg(pg_catalog.to_jsonb(t) order by id) into b from shareholder_register_filing.authority_permissions t;
 if a is distinct from b then raise exception 'rf1086_cutover_reconciliation_failed'; end if;
end; $verify$;

do $verify$ declare a jsonb; b jsonb; begin
 select pg_catalog.jsonb_agg(pg_catalog.to_jsonb(t) order by id) into a from public.authority_test_runs t where shareholder_register_filing.classify_legacy_row_v1('authority_test_runs',pg_catalog.to_jsonb(t))='rf';
 select pg_catalog.jsonb_agg(pg_catalog.to_jsonb(t) order by id) into b from shareholder_register_filing.authority_test_runs t;
 if a is distinct from b then raise exception 'rf1086_cutover_reconciliation_failed'; end if;
end; $verify$;

-- Every retained production approval must retain its exact original RF preview.
do $refs$ begin if exists(select 1 from shareholder_register_filing.filing_approval_snapshots a left join shareholder_register_filing.filing_previews p on p.id=a.preview_id
 where p.id is null or p.company_id<>a.company_id or p.income_year<>a.income_year)
 then raise exception 'rf1086_quarantined_production_relationship'; end if; end; $refs$;
alter table shareholder_register_filing.filing_approval_snapshots drop constraint filing_approval_snapshots_preview_id_fkey;
alter table shareholder_register_filing.filing_approval_snapshots add constraint filing_approval_snapshots_preview_id_fkey foreign key(preview_id) references shareholder_register_filing.filing_previews(id) on delete restrict;
update shareholder_register_filing.migration_state set phase='canonical_overlap' where singleton;

create function backend_system.sync_rf_preparation_projection_v1() returns trigger
language plpgsql security definer set search_path='' as $function$
declare row_data jsonb; v_cols text; v_updates text;
begin
 if shareholder_register_filing.phase_v1()<>'canonical_overlap' or pg_catalog.pg_trigger_depth()>1 then return null; end if;
 if tg_table_name not in ('filing_previews','filing_submissions','filing_overrides','filing_review_comments','authority_permissions','authority_test_runs') then raise exception 'rf1086_overlap_trigger_invalid'; end if;
 row_data:=pg_catalog.to_jsonb(new);
 select pg_catalog.string_agg(pg_catalog.quote_ident(a.attname),',' order by a.attnum),
  pg_catalog.string_agg(pg_catalog.format('%I=excluded.%I',a.attname,a.attname),',' order by a.attnum)
 into v_cols,v_updates from pg_catalog.pg_attribute a where a.attrelid=pg_catalog.to_regclass('public.'||tg_table_name) and a.attnum>0 and not a.attisdropped;
 execute pg_catalog.format('insert into public.%I(%s) select %s from pg_catalog.jsonb_populate_record(null::public.%I,$1) on conflict(id) do update set %s',tg_table_name,v_cols,v_cols,tg_table_name,v_updates) using row_data;
 return null;
end; $function$;
revoke all on function backend_system.sync_rf_preparation_projection_v1() from public,anon,authenticated,service_role;

create trigger rf151_preparation_projection after insert or update on shareholder_register_filing.filing_previews for each row execute function backend_system.sync_rf_preparation_projection_v1();

create trigger rf151_preparation_projection after insert or update on shareholder_register_filing.filing_submissions for each row execute function backend_system.sync_rf_preparation_projection_v1();

create trigger rf151_preparation_projection after insert or update on shareholder_register_filing.filing_overrides for each row execute function backend_system.sync_rf_preparation_projection_v1();

create trigger rf151_preparation_projection after insert or update on shareholder_register_filing.filing_review_comments for each row execute function backend_system.sync_rf_preparation_projection_v1();

create trigger rf151_preparation_projection after insert or update on shareholder_register_filing.authority_permissions for each row execute function backend_system.sync_rf_preparation_projection_v1();

create trigger rf151_preparation_projection after insert or update on shareholder_register_filing.authority_test_runs for each row execute function backend_system.sync_rf_preparation_projection_v1();

create temporary table rf151_archive_grant on commit drop as select pg_catalog.has_function_privilege(current_user,'public.company_archive_track_source_write_v1()','EXECUTE') as had_execute;
do $grant_archive$ declare principal name:=current_user; begin
 execute 'set local role company_archive_projection_executor';
 execute pg_catalog.format('grant execute on function public.company_archive_track_source_write_v1() to %I',principal);
 execute 'reset role';
end; $grant_archive$;

drop trigger company_archive_track_filing_previews on public.filing_previews;

CREATE TRIGGER company_archive_track_filing_previews BEFORE INSERT OR DELETE OR UPDATE ON public.filing_previews FOR EACH ROW WHEN (pg_catalog.pg_trigger_depth()=0) EXECUTE FUNCTION public.company_archive_track_source_write_v1('year', 'company_id');

CREATE TRIGGER company_archive_track_filing_previews BEFORE INSERT OR DELETE OR UPDATE ON shareholder_register_filing.filing_previews FOR EACH ROW EXECUTE FUNCTION public.company_archive_track_source_write_v1('year', 'company_id');

drop trigger company_archive_track_filing_submissions on public.filing_submissions;

CREATE TRIGGER company_archive_track_filing_submissions BEFORE INSERT OR DELETE OR UPDATE ON public.filing_submissions FOR EACH ROW WHEN (pg_catalog.pg_trigger_depth()=0) EXECUTE FUNCTION public.company_archive_track_source_write_v1('year', 'company_id');

CREATE TRIGGER company_archive_track_filing_submissions BEFORE INSERT OR DELETE OR UPDATE ON shareholder_register_filing.filing_submissions FOR EACH ROW EXECUTE FUNCTION public.company_archive_track_source_write_v1('year', 'company_id');

drop trigger company_archive_track_filing_review_comments on public.filing_review_comments;

CREATE TRIGGER company_archive_track_filing_review_comments BEFORE INSERT OR DELETE OR UPDATE ON public.filing_review_comments FOR EACH ROW WHEN (pg_catalog.pg_trigger_depth()=0) EXECUTE FUNCTION public.company_archive_track_source_write_v1('company', 'company_id');

CREATE TRIGGER company_archive_track_filing_review_comments BEFORE INSERT OR DELETE OR UPDATE ON shareholder_register_filing.filing_review_comments FOR EACH ROW EXECUTE FUNCTION public.company_archive_track_source_write_v1('company', 'company_id');

drop trigger company_archive_track_authority_permissions on public.authority_permissions;

CREATE TRIGGER company_archive_track_authority_permissions BEFORE INSERT OR DELETE OR UPDATE ON public.authority_permissions FOR EACH ROW WHEN (pg_catalog.pg_trigger_depth()=0) EXECUTE FUNCTION public.company_archive_track_source_write_v1('company', 'company_id');

CREATE TRIGGER company_archive_track_authority_permissions BEFORE INSERT OR DELETE OR UPDATE ON shareholder_register_filing.authority_permissions FOR EACH ROW EXECUTE FUNCTION public.company_archive_track_source_write_v1('company', 'company_id');

drop trigger company_archive_track_authority_test_runs on public.authority_test_runs;

CREATE TRIGGER company_archive_track_authority_test_runs BEFORE INSERT OR DELETE OR UPDATE ON public.authority_test_runs FOR EACH ROW WHEN (pg_catalog.pg_trigger_depth()=0) EXECUTE FUNCTION public.company_archive_track_source_write_v1('company', 'company_id');

CREATE TRIGGER company_archive_track_authority_test_runs BEFORE INSERT OR DELETE OR UPDATE ON shareholder_register_filing.authority_test_runs FOR EACH ROW EXECUTE FUNCTION public.company_archive_track_source_write_v1('company', 'company_id');

drop trigger company_archive_track_opening_balance_setups on public.opening_balance_setups;

CREATE TRIGGER company_archive_track_opening_balance_setups BEFORE INSERT OR DELETE OR UPDATE ON public.opening_balance_setups FOR EACH ROW WHEN (pg_catalog.pg_trigger_depth()=0) EXECUTE FUNCTION public.company_archive_track_source_write_v1('year', 'company_id');

CREATE TRIGGER company_archive_track_opening_balance_setups BEFORE INSERT OR DELETE OR UPDATE ON shareholder_register_filing.opening_balance_setups FOR EACH ROW EXECUTE FUNCTION public.company_archive_track_source_write_v1('year', 'company_id');

drop trigger company_archive_track_opening_shareholders on public.opening_shareholders;

CREATE TRIGGER company_archive_track_opening_shareholders BEFORE INSERT OR DELETE OR UPDATE ON public.opening_shareholders FOR EACH ROW WHEN (pg_catalog.pg_trigger_depth()=0) EXECUTE FUNCTION public.company_archive_track_source_write_v1('company', 'company_id');

CREATE TRIGGER company_archive_track_opening_shareholders BEFORE INSERT OR DELETE OR UPDATE ON shareholder_register_filing.opening_shareholders FOR EACH ROW EXECUTE FUNCTION public.company_archive_track_source_write_v1('company', 'company_id');

do $restore_archive_grant$ declare principal name:=current_user; begin
 if not (select had_execute from rf151_archive_grant) then
  execute 'set local role company_archive_projection_executor';
  execute pg_catalog.format('revoke execute on function public.company_archive_track_source_write_v1() from %I',principal);
  execute 'reset role';
 end if;
end; $restore_archive_grant$;

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
