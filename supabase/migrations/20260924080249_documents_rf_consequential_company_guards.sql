-- Shared company-first evidence writes and narrow Governance admission assertions.
-- No provider I/O or cross-owner table grants. Full-year approval/send remains separate.
begin;
set local lock_timeout='5s';
set local statement_timeout='120s';
set local search_path='';
create temporary table rf193_consequential_borrowed_roles(role_name name, prior jsonb) on commit drop;
do $borrow$
declare r name; p jsonb;
begin
 foreach r in array array['documents_store_owner','shareholder_register_filing_store_owner','company_archive_projection_executor'] loop
  if not pg_catalog.pg_has_role(current_user,r,'SET') then
   select pg_catalog.jsonb_build_object('admin',m.admin_option,'inherit',m.inherit_option,'set',m.set_option) into p
   from pg_catalog.pg_auth_members m where m.roleid=(select oid from pg_catalog.pg_roles where rolname=r)
    and m.member=(select oid from pg_catalog.pg_roles where rolname=current_user) and m.grantor=m.member;
   insert into pg_temp.rf193_consequential_borrowed_roles values(r,p);
   execute pg_catalog.format('grant %I to %I with set true granted by %I',r,current_user,current_user);
  end if;
 end loop;
end; $borrow$;
grant execute on function public.company_archive_lock_company_v1(uuid),public.company_access_is_accepted_owner_v1(uuid)
 to documents_store_owner,shareholder_register_filing_store_owner;
set local role documents_store_owner;
create or replace function documents.lock_company_write_v1(p_company uuid,p_subject text) returns void
language plpgsql volatile security definer set search_path='' as $fn$
begin
 if p_company is null or p_subject is null or nullif(pg_catalog.current_setting('talli.verified_actor_id',true),'') is distinct from p_subject
  or not public.company_access_is_accepted_owner_v1(p_company) then raise exception 'documents_forbidden'; end if;
 if pg_catalog.current_setting('transaction_isolation')<>'read committed' then raise exception 'documents_guard_requires_read_committed'; end if;
 perform public.company_archive_lock_company_v1(p_company);
 if not public.company_access_is_accepted_owner_v1(p_company) then raise exception 'documents_forbidden'; end if;
end; $fn$;
create or replace function documents.lock_document_write_v1(p_document uuid,p_subject text) returns void
language plpgsql volatile security definer set search_path='' as $fn$
declare company uuid;
begin
 select company_id into company from public.documents where id=p_document;
 if not found then raise exception 'documents_not_found'; end if;
 perform documents.lock_company_write_v1(company,p_subject);
 if not exists(select 1 from public.documents where id=p_document and company_id=company)
 then raise exception 'documents_not_found'; end if;
end; $fn$;
revoke all on function documents.lock_company_write_v1(uuid,text),documents.lock_document_write_v1(uuid,text)
 from public,anon,authenticated,service_role,documents_executor,shareholder_register_filing_executor,corporate_governance_workflow_executor;
-- Backstops serialize retained evidence; archive/export inclusion is a separate contract.
create or replace function documents.lock_evidence_company_write_v1() returns trigger
language plpgsql security invoker set search_path='' as $fn$
declare company uuid;
begin
 for company in select distinct value from (
  select old.company_id as value where tg_op in ('UPDATE','DELETE')
  union all select new.company_id as value where tg_op in ('INSERT','UPDATE')
 ) changed where value is not null order by value loop
  perform public.company_archive_lock_company_v1(company);
 end loop;
 return coalesce(new,old);
end; $fn$;
revoke all on function documents.lock_evidence_company_write_v1() from public,anon,authenticated,service_role,documents_executor,
 shareholder_register_filing_executor,corporate_governance_workflow_executor;
drop trigger if exists consequential_company_guard on documents.evidence_references;
create trigger consequential_company_guard before insert or update or delete on documents.evidence_references
 for each row execute function documents.lock_evidence_company_write_v1();
drop trigger if exists consequential_company_guard on documents.retained_originals;
create trigger consequential_company_guard before insert or update or delete on documents.retained_originals
 for each row execute function documents.lock_evidence_company_write_v1();
-- Same-connection assertions consume already retained originals; they never download bytes.
grant usage on schema documents to corporate_governance_workflow_executor;
grant execute on function documents.assert_retained_original_v1(uuid,uuid,uuid,integer,text,text,integer,timestamptz,text),
 documents.assert_retained_metadata_v1(text,text) to corporate_governance_workflow_executor;
reset role;
set local role shareholder_register_filing_store_owner;
create or replace function shareholder_register_filing.lock_company_write_v1(p_company uuid,p_review boolean default false) returns void
language plpgsql volatile security definer set search_path='' as $fn$
begin
 perform shareholder_register_filing.assert_preparation_access_v1(p_company,p_review);
 if pg_catalog.current_setting('transaction_isolation')<>'read committed' then raise exception 'rf1086_guard_requires_read_committed'; end if;
 perform public.company_archive_lock_company_v1(p_company);
 perform shareholder_register_filing.assert_preparation_access_v1(p_company,p_review);
end; $fn$;
create or replace function shareholder_register_filing.lock_preview_write_v1(p_preview uuid,p_review boolean default false) returns void
language plpgsql volatile security definer set search_path='' as $fn$
declare company uuid;
begin
 select company_id into company from shareholder_register_filing.filing_previews where id=p_preview;
 if not found then raise exception 'rf1086_not_found'; end if;
 perform shareholder_register_filing.lock_company_write_v1(company,p_review);
 if not exists(select 1 from shareholder_register_filing.filing_previews where id=p_preview and company_id=company)
 then raise exception 'rf1086_not_found'; end if;
end; $fn$;
create or replace function shareholder_register_filing.lock_comment_write_v1(p_comment uuid) returns void
language plpgsql volatile security definer set search_path='' as $fn$
declare company uuid;
begin
 select company_id into company from shareholder_register_filing.filing_review_comments where id=p_comment;
 if not found then raise exception 'rf1086_not_found'; end if;
 perform shareholder_register_filing.lock_company_write_v1(company,false);
 if not exists(select 1 from shareholder_register_filing.filing_review_comments where id=p_comment and company_id=company)
 then raise exception 'rf1086_not_found'; end if;
end; $fn$;
create or replace function shareholder_register_filing.lock_approval_write_v1(p_approval uuid) returns void
language plpgsql volatile security definer set search_path='' as $fn$
declare company uuid;
begin
 select company_id into company from shareholder_register_filing.filing_approval_snapshots where id=p_approval;
 if not found then raise exception 'production_approval_invalid'; end if;
 perform shareholder_register_filing.lock_company_write_v1(company,false);
 if not exists(select 1 from shareholder_register_filing.filing_approval_snapshots where id=p_approval and company_id=company)
 then raise exception 'production_approval_invalid'; end if;
end; $fn$;
create or replace function shareholder_register_filing.assert_current_register_observation_v1(
 p_id uuid,p_company uuid,p_year integer,p_revision integer,p_sha text,p_subject text) returns void
language plpgsql volatile security definer set search_path='' as $fn$
begin
 if p_subject is null or nullif(pg_catalog.current_setting('talli.verified_actor_id',true),'') is distinct from p_subject
 then raise exception 'rf1086_forbidden'; end if;
 perform shareholder_register_filing.lock_company_write_v1(p_company,false);
 if p_id is null or p_year is null or p_revision is null or p_revision<1 or p_sha is null
  or not exists(select 1 from shareholder_register_filing.register_observations r
   where r.id=p_id and r.company_id=p_company and r.income_year=p_year and r.version=p_revision and r.fact_sha256=p_sha
   and not exists(select 1 from shareholder_register_filing.register_observations successor where successor.predecessor_id=r.id))
 then raise exception 'rf1086_register_predecessor_mismatch'; end if;
end; $fn$;
revoke all on function shareholder_register_filing.lock_company_write_v1(uuid,boolean),shareholder_register_filing.lock_preview_write_v1(uuid,boolean),
 shareholder_register_filing.lock_comment_write_v1(uuid),shareholder_register_filing.lock_approval_write_v1(uuid),
 shareholder_register_filing.assert_current_register_observation_v1(uuid,uuid,integer,integer,text,text)
 from public,anon,authenticated,service_role,shareholder_register_filing_executor,corporate_governance_workflow_executor;
grant execute on function shareholder_register_filing.lock_company_write_v1(uuid,boolean),shareholder_register_filing.lock_preview_write_v1(uuid,boolean)
 to shareholder_register_filing_executor;
grant usage on schema shareholder_register_filing to corporate_governance_workflow_executor;
grant execute on function shareholder_register_filing.assert_current_register_observation_v1(uuid,uuid,integer,integer,text,text)
 to corporate_governance_workflow_executor;
reset role;

-- Preserve each existing OID, owner, ACL, security/configuration and complete body.
-- Nest the original block so even DECLARE initializers run after the guard.
-- This avoids parsing an apparent first BEGIN inside a comment/string/initializer.
do $wrap$
declare spec record; before_row record; after_row record; body text; definition text; prefix text; wrapped text;
begin
 for spec in select * from (values
  ('documents.stage_upload_v1(jsonb,text)','documents.lock_company_write_v1((p_request->>''companyId'')::uuid,p_verified_subject)','documents_store_owner'),
  ('documents.quarantine_upload_v1(uuid,text,text)','documents.lock_document_write_v1(p_document_id,p_verified_subject)','documents_store_owner'),
  ('documents.finalize_upload_v1(uuid,bigint,text,text)','documents.lock_document_write_v1(p_document_id,p_verified_subject)','documents_store_owner'),
  ('documents.mark_removed_v1(uuid,text,text)','documents.lock_document_write_v1(p_document_id,p_verified_subject)','documents_store_owner'),
  ('documents.restore_after_storage_failure_v1(uuid,text)','documents.lock_document_write_v1(p_document_id,p_verified_subject)','documents_store_owner'),
  ('documents.register_evidence_reference_v1(text,text,uuid,uuid,uuid,integer,text,text,text,bigint,uuid)','documents.lock_company_write_v1(p_company_id,p_actor_id::text)','documents_store_owner'),
  ('documents.retain_verified_rf_evidence_v1(text,uuid,uuid,uuid,integer,text,text,bigint,text,uuid)','documents.lock_company_write_v1(p_company_id,p_actor_id::text)','documents_store_owner'),
  ('documents.retain_original_v1(uuid,uuid,text,text,integer,bytea,text)','documents.lock_company_write_v1(p_company,p_subject)','documents_store_owner'),
  ('documents.assert_retained_original_v1(uuid,uuid,uuid,integer,text,text,integer,timestamptz,text)','documents.lock_company_write_v1(p_company,p_subject)','documents_store_owner'),
  ('shareholder_register_filing.record_preview_v1(uuid,uuid,text,jsonb,text,text,jsonb)','shareholder_register_filing.lock_company_write_v1(p_company_id,false)','shareholder_register_filing_store_owner'),
  ('shareholder_register_filing.record_override_v1(uuid,text,text,text,text,text,boolean)','shareholder_register_filing.lock_preview_write_v1(p_preview_id,false)','shareholder_register_filing_store_owner'),
  ('shareholder_register_filing.add_review_comment_v1(uuid,text,text)','shareholder_register_filing.lock_preview_write_v1(p_preview_id,true)','shareholder_register_filing_store_owner'),
  ('shareholder_register_filing.acknowledge_review_comment_v1(uuid)','shareholder_register_filing.lock_comment_write_v1(p_comment_id)','shareholder_register_filing_store_owner'),
  ('shareholder_register_filing.confirm_filing_permission_v1(uuid,boolean)','shareholder_register_filing.lock_company_write_v1(p_company_id,false)','shareholder_register_filing_store_owner'),
  ('shareholder_register_filing.record_test_evidence_v1(uuid,jsonb)','shareholder_register_filing.lock_company_write_v1(p_company_id,false)','shareholder_register_filing_store_owner'),
  ('shareholder_register_filing.record_simulation_v1(uuid,jsonb)','shareholder_register_filing.lock_preview_write_v1(p_preview_id,false)','shareholder_register_filing_store_owner'),
  ('shareholder_register_filing.approve_production_filing(uuid,uuid,jsonb,text,text)','shareholder_register_filing.lock_preview_write_v1(p_preview_id,false)','shareholder_register_filing_store_owner'),
  ('shareholder_register_filing.begin_production_filing(uuid)','shareholder_register_filing.lock_approval_write_v1(p_approval_id)','shareholder_register_filing_store_owner')
 ) s(signature,call,owner_name) loop
  select p.oid,p.proowner,p.proacl,p.proconfig,p.prosecdef,p.provolatile,p.proparallel,p.prosrc,l.lanname into before_row
  from pg_catalog.pg_proc p join pg_catalog.pg_language l on l.oid=p.prolang where p.oid=pg_catalog.to_regprocedure(spec.signature);
  if not found or before_row.proowner<>(select oid from pg_catalog.pg_roles where rolname=spec.owner_name)
   or before_row.lanname<>'plpgsql' or not before_row.prosecdef or before_row.provolatile<>'v'
   or before_row.prosrc ~ '^[[:space:]]*#' then raise exception 'rf193_company_guard_definition_drift: %',spec.signature; end if;
  prefix:=E'begin\n -- rf193-company-guard-v1\n perform '||spec.call||E';\n';
  if pg_catalog.strpos(before_row.prosrc,'-- rf193-company-guard-v1')>0 then
   if pg_catalog.left(before_row.prosrc,pg_catalog.length(prefix))<>prefix then raise exception 'rf193_company_guard_definition_drift: %',spec.signature; end if;
   continue;
  end if;
  body:=pg_catalog.rtrim(before_row.prosrc);
  if pg_catalog.right(body,1)<>';' then body:=body||';'; end if;
  wrapped:=prefix||body||E'\nend;\n';
  definition:=pg_catalog.pg_get_functiondef(before_row.oid);
  if (pg_catalog.length(definition)-pg_catalog.length(pg_catalog.replace(definition,before_row.prosrc,'')))<>pg_catalog.length(before_row.prosrc)
   then raise exception 'rf193_company_guard_body_ambiguous: %',spec.signature; end if;
  execute pg_catalog.format('set local role %I',spec.owner_name);
  execute pg_catalog.replace(definition,before_row.prosrc,wrapped);
  reset role;
  select proowner,proacl,proconfig,prosecdef,provolatile,proparallel into after_row from pg_catalog.pg_proc where oid=before_row.oid;
  if (after_row.proowner,after_row.proacl,after_row.proconfig,after_row.prosecdef,after_row.provolatile,after_row.proparallel)
   is distinct from (before_row.proowner,before_row.proacl,before_row.proconfig,before_row.prosecdef,before_row.provolatile,before_row.proparallel)
  then raise exception 'rf193_company_guard_authority_drift: %',spec.signature; end if;
 end loop;
end; $wrap$;

set local role shareholder_register_filing_store_owner;
drop trigger if exists consequential_company_guard on shareholder_register_filing.filing_overrides;
create trigger consequential_company_guard before insert or update or delete on shareholder_register_filing.filing_overrides
 for each row execute function shareholder_register_filing.lock_source_company_write_v1();
reset role;

-- Reuse the archive owner's existing company-wide guard for missing backstops.
-- It also invalidates archive generations when these evidence facts change.
create temporary table rf193_guard_archive_grant(had boolean,principal name) on commit drop;
insert into rf193_guard_archive_grant select pg_catalog.has_function_privilege(current_user,'public.company_archive_track_source_write_v1()','EXECUTE'),current_user;
do $archive_grant$ declare principal name:=(select g.principal from pg_temp.rf193_guard_archive_grant g); begin
 if not (select had from pg_temp.rf193_guard_archive_grant) then
  execute 'set local role company_archive_projection_executor';
  execute pg_catalog.format('grant execute on function public.company_archive_track_source_write_v1() to %I',principal);
  reset role;
 end if;
end; $archive_grant$;
do $backstops$
declare relation text;
begin
 foreach relation in array array['public.filing_overrides','public.filing_readiness_snapshots'] loop
  if pg_catalog.to_regclass(relation) is null then raise exception 'rf193_company_guard_table_missing: %',relation; end if;
  execute pg_catalog.format('drop trigger if exists consequential_company_guard on %s',relation);
  execute pg_catalog.format('create trigger consequential_company_guard before insert or update or delete on %s for each row execute function public.company_archive_track_source_write_v1(''company'',''company_id'')',relation);
 end loop;
end; $backstops$;
do $restore_archive_grant$ declare principal name:=(select g.principal from pg_temp.rf193_guard_archive_grant g); begin
 if not (select had from pg_temp.rf193_guard_archive_grant) then
  execute 'set local role company_archive_projection_executor';
  execute pg_catalog.format('revoke execute on function public.company_archive_track_source_write_v1() from %I',principal);
  reset role;
 end if;
end; $restore_archive_grant$;
do $restore$
declare r record;
begin
 for r in select * from pg_temp.rf193_consequential_borrowed_roles loop
  execute pg_catalog.format('revoke %I from %I granted by %I',r.role_name,current_user,current_user);
  if r.prior is not null then execute pg_catalog.format('grant %I to %I with admin %s,inherit %s,set %s granted by %I',
   r.role_name,current_user,r.prior->>'admin',r.prior->>'inherit',r.prior->>'set',current_user); end if;
 end loop;
end; $restore$;
commit;
