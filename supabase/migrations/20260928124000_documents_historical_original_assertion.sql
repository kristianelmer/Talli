-- Guarded exact historical receipt assertion; no byte reads or current-source authority.
begin;
set local lock_timeout='5s';
set local statement_timeout='120s';
set local search_path='';
create temporary table documents_original_borrowed_role(prior jsonb, borrowed boolean) on commit drop;
do $borrow$
declare p jsonb; b boolean:=not pg_catalog.pg_has_role(current_user,'documents_store_owner','SET');
begin
 if b then
  select pg_catalog.jsonb_build_object('admin',m.admin_option,'inherit',m.inherit_option,'set',m.set_option) into p
  from pg_catalog.pg_auth_members m where m.roleid=(select oid from pg_catalog.pg_roles where rolname='documents_store_owner')
   and m.member=(select oid from pg_catalog.pg_roles where rolname=current_user) and m.grantor=m.member;
  execute pg_catalog.format('grant documents_store_owner to %I with set true granted by %I',current_user,current_user);
 end if;
 insert into pg_temp.documents_original_borrowed_role values(p,b);
end; $borrow$;
set local role documents_store_owner;
create or replace function documents.assert_historical_original_v1(
 p_original uuid,p_document uuid,p_company uuid,p_year integer,p_metadata text,p_sha text,p_length integer,p_retained_at timestamptz,p_subject text)
returns jsonb language plpgsql security definer set search_path='' as $fn$
declare r documents.retained_originals%rowtype; a uuid:=nullif(pg_catalog.current_setting('talli.verified_actor_id',true),'')::uuid;
begin
 if a is null or p_subject is null or p_subject<>a::text or not public.company_access_is_accepted_owner_v1(p_company)
 then raise exception 'documents_forbidden'; end if;
 if pg_catalog.current_setting('transaction_isolation')<>'read committed' then raise exception 'documents_guard_requires_read_committed'; end if;
 perform public.company_archive_lock_company_v1(p_company);
 if not public.company_access_is_accepted_owner_v1(p_company) then raise exception 'documents_forbidden'; end if;
 perform pg_catalog.set_config('talli.authorized_company_roles',pg_catalog.jsonb_build_object(p_company::text,'owner')::text,true);
 select * into r from documents.retained_originals where id=p_original and document_id=p_document and company_id=p_company
  and source_income_year=p_year and metadata_sha256=p_metadata and content_sha256=p_sha and byte_length=p_length and retained_at=p_retained_at;
 if not found then raise exception 'documents_evidence_mismatch'; end if;
 -- Immutable captured metadata only. Current-source assertions remain separate.
 return r.document_snapshot;
end; $fn$;
revoke all on function documents.assert_historical_original_v1(uuid,uuid,uuid,integer,text,text,integer,timestamptz,text)
 from public,anon,authenticated,service_role,documents_executor,shareholder_register_filing_executor;
grant execute on function documents.assert_historical_original_v1(uuid,uuid,uuid,integer,text,text,integer,timestamptz,text)
 to documents_executor,shareholder_register_filing_executor;
reset role;
do $restore$
declare r record;
begin
 select * into r from pg_temp.documents_original_borrowed_role;
 if r.borrowed then
  execute pg_catalog.format('revoke documents_store_owner from %I granted by %I',current_user,current_user);
  if r.prior is not null then
   execute pg_catalog.format('grant documents_store_owner to %I with admin %s,inherit %s,set %s granted by %I',current_user,r.prior->>'admin',r.prior->>'inherit',r.prior->>'set',current_user);
  end if;
 end if;
end; $restore$;
commit;
