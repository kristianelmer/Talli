-- Extend the existing archive-generation protocol to retained RF evidence.
-- No source content, submission, receipt or cancellation policy is rewritten.
begin;
set local lock_timeout='5s';
set local statement_timeout='120s';
set local search_path='';
create temporary table rf193_generation_roles(role_name text,prior jsonb) on commit drop;
do $borrow$
declare r text; prior jsonb;
begin
 foreach r in array array['company_archive_projection_executor','documents_store_owner','shareholder_register_filing_store_owner'] loop
  if not pg_catalog.pg_has_role(current_user,r,'SET') then
   select pg_catalog.jsonb_build_object('admin',m.admin_option,'inherit',m.inherit_option,'set',m.set_option)
   into prior from pg_catalog.pg_auth_members m where m.roleid=(select oid from pg_catalog.pg_roles where rolname=r)
    and m.member=(select oid from pg_catalog.pg_roles where rolname=current_user) and m.grantor=m.member;
   insert into pg_temp.rf193_generation_roles values(r,prior);
   execute pg_catalog.format('grant %I to %I with set true granted by %I',r,current_user,current_user);
  end if;
 end loop;
end; $borrow$;
create temporary table rf193_generation_sources(relation text,scope text,owner_name text) on commit drop;
insert into rf193_generation_sources values
 ('shareholder_register_filing.year_source_versions','year','shareholder_register_filing_store_owner'),
 ('shareholder_register_filing.year_source_heads','year','shareholder_register_filing_store_owner'),
 ('shareholder_register_filing.register_observations','year','shareholder_register_filing_store_owner'),
 ('shareholder_register_filing.source_previews','year','shareholder_register_filing_store_owner'),
 ('shareholder_register_filing.source_review_bridges','year','shareholder_register_filing_store_owner'),
 ('shareholder_register_filing.source_approval_bindings','year','shareholder_register_filing_store_owner'),
 ('shareholder_register_filing.source_submission_bindings','year','shareholder_register_filing_store_owner'),
 ('shareholder_register_filing.submission_heads','year','shareholder_register_filing_store_owner'),
 ('documents.evidence_references','company','documents_store_owner'),
 ('documents.retained_originals','company','documents_store_owner');
create temporary table rf193_generation_companies(company_id uuid primary key) on commit drop;
create temporary table rf193_generation_grants on commit drop as
 select role_name,pg_catalog.has_function_privilege(role_name,'public.company_archive_track_source_write_v1()','EXECUTE') had
 from (values ('documents_store_owner'),('shareholder_register_filing_store_owner')) roles(role_name);
grant select on pg_temp.rf193_generation_sources to documents_store_owner,shareholder_register_filing_store_owner;
grant select,insert on pg_temp.rf193_generation_companies to documents_store_owner,shareholder_register_filing_store_owner;
grant select on pg_temp.rf193_generation_companies,pg_temp.rf193_generation_grants to company_archive_projection_executor;
set local role company_archive_projection_executor;
do $grant$
declare r record;
begin
 for r in select * from pg_temp.rf193_generation_grants where not had loop
  execute pg_catalog.format('grant execute on function public.company_archive_track_source_write_v1() to %I',r.role_name);
 end loop;
end; $grant$;
reset role;

do $sources$
declare r record; forced boolean; protected boolean; installed boolean;
begin
 for r in select * from pg_temp.rf193_generation_sources order by relation loop
  execute pg_catalog.format('set local role %I',r.owner_name);
  select relforcerowsecurity,relkind='r' and relowner=current_user::regrole
   into forced,protected from pg_catalog.pg_class where oid=pg_catalog.to_regclass(r.relation);
  if protected is distinct from true then raise exception 'rf1086_archive_generation_owner_precondition: %',r.relation; end if;
  select exists(select 1 from pg_catalog.pg_trigger where tgrelid=pg_catalog.to_regclass(r.relation)
   and tgname='company_archive_track_retained_rf') into installed;
  if not installed then
   -- First activation invalidates existing receipts for every affected company,
   -- including exports for a later year that use an earlier retained original.
   -- Owner-only RLS suspension and restoration share this transaction.
   if forced then execute pg_catalog.format('alter table %s no force row level security',r.relation); end if;
   execute pg_catalog.format('insert into pg_temp.rf193_generation_companies select distinct company_id from %s on conflict do nothing',r.relation);
   if forced then execute pg_catalog.format('alter table %s force row level security',r.relation); end if;
  end if;
  execute pg_catalog.format('drop trigger if exists company_archive_track_retained_rf on %s',r.relation);
  if r.owner_name='documents_store_owner' then
   -- Documents already locks the company before any row write. Track only an
   -- actual change: INSERT ... ON CONFLICT DO NOTHING is an ordinary read replay.
   if not exists(select 1 from pg_catalog.pg_trigger where tgrelid=pg_catalog.to_regclass(r.relation)
    and tgfoid='documents.lock_evidence_company_write_v1()'::regprocedure and tgtype=31 and tgenabled='O')
   then raise exception 'documents_archive_generation_guard_required'; end if;
   execute pg_catalog.format('create trigger company_archive_track_retained_rf after insert or update or delete on %s for each row execute function public.company_archive_track_source_write_v1(%L,''company_id'')',r.relation,r.scope);
  else
   execute pg_catalog.format('create trigger company_archive_track_retained_rf before insert or update or delete on %s for each row execute function public.company_archive_track_source_write_v1(%L,''company_id'')',r.relation,r.scope);
  end if;
  reset role;
 end loop;
end; $sources$;
set local role company_archive_projection_executor;
do $invalidate$
declare r record;
begin
 for r in select company_id from pg_temp.rf193_generation_companies order by company_id loop
  perform public.company_archive_lock_company_v1(r.company_id);
  update public.company_archive_source_generations set generation=generation+1,updated_at=pg_catalog.statement_timestamp()
   where company_id=r.company_id;
 end loop;
end; $invalidate$;
do $revoke$
declare r record;
begin
 for r in select * from pg_temp.rf193_generation_grants where not had loop
  execute pg_catalog.format('revoke execute on function public.company_archive_track_source_write_v1() from %I',r.role_name);
 end loop;
end; $revoke$;
reset role;
do $restore$
declare r record;
begin
 for r in select * from pg_temp.rf193_generation_roles order by role_name loop
  execute pg_catalog.format('revoke %I from %I granted by %I',r.role_name,current_user,current_user);
  if r.prior is not null then execute pg_catalog.format('grant %I to %I with admin %s,inherit %s,set %s granted by %I',
   r.role_name,current_user,r.prior->>'admin',r.prior->>'inherit',r.prior->>'set',current_user); end if;
 end loop;
end; $restore$;
commit;
