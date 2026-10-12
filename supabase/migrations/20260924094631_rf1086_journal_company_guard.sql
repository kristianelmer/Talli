-- Company-first journal writes prevent correction/archive lock inversions.
begin;
set local lock_timeout='5s';
set local statement_timeout='120s';
set local search_path='';
create temporary table rf193_journal_guard_role(prior jsonb) on commit drop;
do $borrow$
declare v_prior jsonb;
begin
 if not pg_catalog.pg_has_role(current_user,'shareholder_register_filing_store_owner','SET') then
  select pg_catalog.jsonb_build_object('admin',m.admin_option,'inherit',m.inherit_option,'set',m.set_option)
  into v_prior from pg_catalog.pg_auth_members m where m.roleid=pg_catalog.to_regrole('shareholder_register_filing_store_owner')
   and m.member=pg_catalog.to_regrole(current_user) and m.grantor=m.member;
  insert into pg_temp.rf193_journal_guard_role values(v_prior);
  execute pg_catalog.format('grant shareholder_register_filing_store_owner to %I with set true granted by %I',current_user,current_user);
 end if;
end; $borrow$;
set local role shareholder_register_filing_store_owner;

-- Journal recovery keeps its historical relationship authority. In particular,
-- an expired pilot or stale MFA does not prevent recording/reconciling a claim.
create or replace function shareholder_register_filing.lock_submission_company_write_v1(p_submission_id uuid)
returns void language plpgsql volatile security definer set search_path='' as $fn$
declare company uuid;
begin
 perform shareholder_register_filing.assert_submission_v1(p_submission_id);
 if pg_catalog.current_setting('transaction_isolation')<>'read committed'
 then raise exception 'rf1086_guard_requires_read_committed'; end if;
 select s.company_id into company from shareholder_register_filing.production_filing_submissions s where s.id=p_submission_id;
 if not found then raise exception 'production_submission_not_found'; end if;
 perform public.company_archive_lock_company_v1(company);
 -- READ COMMITTED gives the post-wait check a fresh owner/relationship snapshot.
 perform shareholder_register_filing.assert_submission_v1(p_submission_id);
 if not exists(select 1 from shareholder_register_filing.production_filing_submissions s where s.id=p_submission_id and s.company_id=company)
 then raise exception 'production_submission_not_found'; end if;
end; $fn$;
revoke all on function shareholder_register_filing.lock_submission_company_write_v1(uuid)
 from public,anon,authenticated,service_role,shareholder_register_filing_executor;

-- The executor can read but cannot UPDATE owner tables or take FOR UPDATE itself.
-- This narrow port locks only the exact authorized predecessor, after the caller
-- has acquired company then RF-year guards on this same connection.
create or replace function shareholder_register_filing.lock_correction_predecessor_v1(
 p_submission_id uuid,p_company_id uuid,p_income_year integer,p_verified_subject text)
returns shareholder_register_filing.production_filing_submissions
language plpgsql volatile security definer set search_path='' as $fn$
declare result shareholder_register_filing.production_filing_submissions%rowtype; k bigint;
begin
 if p_verified_subject is null or shareholder_register_filing.actor_v1()::text is distinct from p_verified_subject
 then raise exception 'legacy_rf1086_submission_relationship_mismatch'; end if;
 if p_company_id is null or p_income_year is null or pg_catalog.current_setting('transaction_isolation')<>'read committed'
 then raise exception 'rf1086_source_approval_guard_required'; end if;
 foreach k in array array[pg_catalog.hashtextextended(p_company_id::text,157),
  pg_catalog.hashtextextended('rf1086:year-source:'||p_company_id::text||':'||p_income_year::text,0)] loop
  if not exists(select 1 from pg_catalog.pg_locks l where l.pid=pg_catalog.pg_backend_pid()
   and l.locktype='advisory' and l.granted and l.mode='ExclusiveLock' and l.objsubid=1
   and l.database=(select oid from pg_catalog.pg_database where datname=pg_catalog.current_database())
   and l.classid=((k >> 32) & 4294967295)::oid and l.objid=(k & 4294967295)::oid)
  then raise exception 'rf1086_source_approval_guard_required'; end if;
 end loop;
 perform public.company_archive_lock_company_v1(p_company_id);
 perform pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended('rf1086:year-source:'||p_company_id::text||':'||p_income_year::text,0));
 perform shareholder_register_filing.assert_submission_v1(p_submission_id);
 select s.* into result from shareholder_register_filing.production_filing_submissions s
 where s.id=p_submission_id and s.company_id=p_company_id and s.income_year=p_income_year for update;
 if result.id is null then raise exception 'rf1086_source_predecessor_mismatch'; end if;
 perform shareholder_register_filing.assert_submission_v1(p_submission_id);
 return result;
end; $fn$;
revoke all on function shareholder_register_filing.lock_correction_predecessor_v1(uuid,uuid,integer,text)
 from public,anon,authenticated,service_role;
grant execute on function shareholder_register_filing.lock_correction_predecessor_v1(uuid,uuid,integer,text)
 to shareholder_register_filing_executor;
reset role;

-- Preserve the existing complete body, including DECLARE initializers, beneath
-- one exact outer guard. No ambient GUC authorizes a journal mutation.
do $wrap$
declare signature text; before_row record; after_row record; body text; definition text; wrapped text;
 prefix constant text:=E'begin\n -- rf193-journal-company-guard-v1\n perform shareholder_register_filing.lock_submission_company_write_v1(p_submission_id);\n';
begin
 foreach signature in array array[
  'shareholder_register_filing.prepare_operation_v1(uuid,text,text,uuid)',
  'shareholder_register_filing.append_production_filing_event(uuid,text,text,integer,text,uuid,text,text,text,boolean)',
  'shareholder_register_filing.claim_production_feedback_reconciliation(uuid,uuid)',
  'shareholder_register_filing.release_production_feedback_reconciliation(uuid,uuid)',
  'shareholder_register_filing.append_production_feedback_reconciliation(uuid,uuid,uuid,text,text[],text,text)',
  'shareholder_register_filing.record_production_feedback_artifact(uuid,uuid,uuid,text,text,bigint,text,text)'
 ] loop
  select p.oid,p.proowner,p.proacl,p.proconfig,p.prosecdef,p.provolatile,p.proparallel,p.prosrc,p.proargnames,l.lanname into before_row
  from pg_catalog.pg_proc p join pg_catalog.pg_language l on l.oid=p.prolang where p.oid=pg_catalog.to_regprocedure(signature);
  if not found or before_row.proowner<>pg_catalog.to_regrole('shareholder_register_filing_store_owner')
   or before_row.lanname<>'plpgsql' or not before_row.prosecdef or before_row.provolatile<>'v'
   or before_row.proconfig is distinct from array['search_path=""']::text[]
   or before_row.proargnames[case when signature like 'shareholder_register_filing.record_production_feedback_artifact(%' then 2 else 1 end] is distinct from 'p_submission_id' or before_row.prosrc ~ '^[[:space:]]*#'
  then raise exception 'rf193_journal_guard_definition_drift: %',signature; end if;
  if pg_catalog.strpos(before_row.prosrc,'-- rf193-journal-company-guard-v1')>0 then
   if pg_catalog.left(before_row.prosrc,pg_catalog.length(prefix))<>prefix
   then raise exception 'rf193_journal_guard_definition_drift: %',signature; end if;
   continue;
  end if;
  body:=pg_catalog.rtrim(before_row.prosrc,E' \t\n\r');
  if pg_catalog.right(body,1)<>';' then body:=body||';'; end if;
  wrapped:=prefix||body||E'\nend;\n';
  definition:=pg_catalog.pg_get_functiondef(before_row.oid);
  if (pg_catalog.length(definition)-pg_catalog.length(pg_catalog.replace(definition,before_row.prosrc,'')))<>pg_catalog.length(before_row.prosrc)
  then raise exception 'rf193_journal_guard_body_ambiguous: %',signature; end if;
  set local role shareholder_register_filing_store_owner;
  execute pg_catalog.replace(definition,before_row.prosrc,wrapped);
  reset role;
  select proowner,proacl,proconfig,prosecdef,provolatile,proparallel,proargnames into after_row from pg_catalog.pg_proc where oid=before_row.oid;
  if (after_row.proowner,after_row.proacl,after_row.proconfig,after_row.prosecdef,after_row.provolatile,after_row.proparallel,after_row.proargnames)
   is distinct from (before_row.proowner,before_row.proacl,before_row.proconfig,before_row.prosecdef,before_row.provolatile,before_row.proparallel,before_row.proargnames)
  then raise exception 'rf193_journal_guard_authority_drift: %',signature; end if;
 end loop;
end; $wrap$;
reset role;
do $restore$
declare r record;
begin
 for r in select * from pg_temp.rf193_journal_guard_role loop
  execute pg_catalog.format('revoke shareholder_register_filing_store_owner from %I granted by %I',current_user,current_user);
  if r.prior is not null then
   execute pg_catalog.format('grant shareholder_register_filing_store_owner to %I with admin %s,inherit %s,set %s granted by %I',current_user,r.prior->>'admin',r.prior->>'inherit',r.prior->>'set',current_user);
  end if;
 end loop;
end; $restore$;
commit;
