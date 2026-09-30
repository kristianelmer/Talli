-- Documents-owned atomic retention for verified RF originals. No provider operations.
begin;
set local lock_timeout='5s';
set local statement_timeout='120s';
set local search_path='';
create temporary table documents_rf_retention_borrowed_role(prior jsonb) on commit drop;
do $borrow$
declare v_prior jsonb;
begin
 if not pg_catalog.pg_has_role(current_user,'documents_store_owner','SET') then
  select pg_catalog.jsonb_build_object('admin',m.admin_option,'inherit',m.inherit_option,'set',m.set_option)
  into v_prior from pg_catalog.pg_auth_members m where m.roleid=(select oid from pg_catalog.pg_roles where rolname='documents_store_owner')
   and m.member=(select oid from pg_catalog.pg_roles where rolname=current_user) and m.grantor=m.member;
  insert into pg_temp.documents_rf_retention_borrowed_role values(v_prior);
  execute pg_catalog.format('grant documents_store_owner to %I with set true granted by %I',current_user,current_user);
 end if;
end; $borrow$;
set local role documents_store_owner;

alter table documents.evidence_references
 add column if not exists capture_source_id uuid,
 add column if not exists metadata_sha256 text;
alter table documents.evidence_references drop constraint if exists evidence_references_document_status_check;
alter table documents.evidence_references add constraint evidence_references_document_status_check
 check(document_status is null or document_status in ('generated_unsigned','signed_owner_attested')
   or (document_status in ('attached','stored') and source_capability='shareholder_register_filing'
       and source_record_type in ('rf1086_year_source','rf1086_register_observation')
       and capture_source_id is not null and metadata_sha256 is not null));
alter table documents.evidence_references drop constraint if exists evidence_references_metadata_sha256_check;
alter table documents.evidence_references add constraint evidence_references_metadata_sha256_check
 check((capture_source_id is null and metadata_sha256 is null)
   or (capture_source_id is not null and metadata_sha256 ~ '^[a-f0-9]{64}$'));

create or replace function documents.retain_verified_rf_evidence_v1(
 p_source_type text,p_source_id uuid,p_document_id uuid,p_company_id uuid,
 p_document_year integer,p_status text,p_content_sha256 text,p_byte_length bigint,
 p_metadata_sha256 text,p_actor_id uuid
) returns setof public.documents language plpgsql security definer set search_path='' as $fn$
declare
 v_actor uuid;
 v_reference uuid;
 v_document public.documents%rowtype;
begin
 v_actor:=nullif(pg_catalog.current_setting('talli.verified_actor_id',true),'')::uuid;
 if v_actor is null or p_actor_id is null or v_actor<>p_actor_id
   or not public.company_access_is_accepted_owner_v1(p_company_id)
 then raise exception 'documents_forbidden'; end if;
 if p_source_type is null or p_source_type not in ('rf1086_year_source','rf1086_register_observation')
   or p_source_id is null or p_document_id is null or p_company_id is null
   or p_document_year is null or p_document_year not between 2000 and 2100
   or p_status is null or p_status not in ('attached','stored','generated_unsigned','signed_owner_attested')
   or p_content_sha256 is null or p_content_sha256 !~ '^[a-f0-9]{64}$'
   or p_metadata_sha256 is null or p_metadata_sha256 !~ '^[a-f0-9]{64}$'
   or p_byte_length is null or p_byte_length not between 1 and 10485760
 then raise exception 'documents_invalid_input'; end if;
 perform pg_catalog.set_config('talli.authorized_company_roles',
   pg_catalog.jsonb_build_object(p_company_id::text,'owner')::text,true);
 select * into v_document from public.documents d
 where d.id=p_document_id and d.company_id=p_company_id and d.income_year=p_document_year
   and d.status=p_status and d.content_sha256=p_content_sha256 and d.byte_length=p_byte_length
 for update;
 if not found then raise exception 'documents_evidence_mismatch'; end if;
 -- A stable per-source/document identity allows multiple originals for one source.
 -- Include the source type to keep independent RF record namespaces distinct.
 v_reference:=pg_catalog.substr(pg_catalog.encode(pg_catalog.sha256(pg_catalog.convert_to(
   'documents-rf-retention-v1:'||p_source_type||':'||p_source_id::text||':'||p_document_id::text,
   'UTF8')),'hex'),1,32)::uuid;
 insert into documents.evidence_references(
   source_capability,source_record_type,source_record_id,document_id,company_id,income_year,
   linked_to,document_status,content_sha256,byte_length,created_by,capture_source_id,metadata_sha256
 ) values (
   'shareholder_register_filing',p_source_type,v_reference,p_document_id,p_company_id,p_document_year,
   v_document.linked_to,p_status,p_content_sha256,p_byte_length,p_actor_id,p_source_id,p_metadata_sha256
 ) on conflict(source_capability,source_record_type,source_record_id) do nothing;
 if not found and not exists(select 1 from documents.evidence_references r
   where r.source_capability='shareholder_register_filing' and r.source_record_type=p_source_type
   and r.source_record_id=v_reference and r.document_id=p_document_id and r.company_id=p_company_id
   and r.income_year=p_document_year and r.linked_to is not distinct from v_document.linked_to
   and r.document_status=p_status and r.content_sha256=p_content_sha256 and r.byte_length=p_byte_length
   and r.created_by=p_actor_id and r.capture_source_id=p_source_id and r.metadata_sha256=p_metadata_sha256)
 then raise exception 'documents_evidence_conflict'; end if;
 return next v_document;
end; $fn$;

-- The adapter hashes the complete returned DocumentRecord while its row lock is
-- held. A mismatch is a SQL error, so catching it cannot commit partial capture.
create or replace function documents.assert_retained_metadata_v1(p_actual text,p_expected text)
returns void language plpgsql security invoker set search_path='' as $fn$
begin
 if p_actual is null or p_expected is null or p_actual !~ '^[a-f0-9]{64}$'
   or p_expected !~ '^[a-f0-9]{64}$' or p_actual<>p_expected
 then raise exception 'documents_evidence_mismatch'; end if;
end; $fn$;

revoke all on function documents.retain_verified_rf_evidence_v1(text,uuid,uuid,uuid,integer,text,text,bigint,text,uuid),
 documents.assert_retained_metadata_v1(text,text) from public,anon,authenticated,service_role,documents_executor;
grant usage on schema documents to shareholder_register_filing_executor;
grant execute on function documents.retain_verified_rf_evidence_v1(text,uuid,uuid,uuid,integer,text,text,bigint,text,uuid),
 documents.assert_retained_metadata_v1(text,text) to shareholder_register_filing_executor;

reset role;
do $restore$
declare r record;
begin
 for r in select * from pg_temp.documents_rf_retention_borrowed_role loop
  execute pg_catalog.format('revoke documents_store_owner from %I granted by %I',current_user,current_user);
  if r.prior is not null then
   execute pg_catalog.format('grant documents_store_owner to %I with admin %s, inherit %s, set %s granted by %I',current_user,r.prior->>'admin',r.prior->>'inherit',r.prior->>'set',current_user);
  end if;
 end loop;
end; $restore$;
commit;
