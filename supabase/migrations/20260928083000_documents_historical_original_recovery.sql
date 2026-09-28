-- Exact retained evidence reads owned by Documents; no current-source authority.
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
create or replace function documents.read_retained_evidence_v1(
 p_document uuid,p_company uuid,p_year integer,p_metadata text,p_sha text,p_length integer,p_subject text)
returns table(receipt jsonb,document jsonb,content bytea)
language plpgsql stable security definer set search_path='' as $fn$
declare a uuid:=nullif(pg_catalog.current_setting('talli.verified_actor_id',true),'')::uuid;
begin
 if a is null or p_subject is null or p_subject<>a::text or not public.company_access_is_accepted_owner_v1(p_company)
 then raise exception 'documents_forbidden'; end if;
 if p_document is null or p_company is null or p_year is null or p_year not between 2000 and 2100
  or p_metadata is null or p_metadata !~ '^[a-f0-9]{64}$' or p_sha is null or p_sha !~ '^[a-f0-9]{64}$'
  or p_length is null or p_length not between 1 and 10485760
 then raise exception 'documents_invalid_input'; end if;
 -- The captured source year is authoritative. Never join mutable public.documents
 -- or substitute the filing year/current document metadata for this historical copy.
 return query select documents.retained_original_receipt_v1(r.id),r.document_snapshot,r.content
 from documents.retained_originals r
 where r.document_id=p_document and r.company_id=p_company and r.source_income_year=p_year
  and r.metadata_sha256=p_metadata and r.content_sha256=p_sha and r.byte_length=p_length;
 if not found then raise exception 'documents_not_found'; end if;
end; $fn$;
revoke all on function documents.read_retained_evidence_v1(uuid,uuid,integer,text,text,integer,text)
 from public,anon,authenticated,service_role,documents_executor,shareholder_register_filing_executor;
grant execute on function documents.read_retained_evidence_v1(uuid,uuid,integer,text,text,integer,text) to documents_executor;
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
