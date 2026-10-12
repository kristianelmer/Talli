-- Documents owns immutable copies of verified originals; no object-store I/O in SQL.
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
grant execute on function public.company_archive_lock_company_v1(uuid),
 public.company_access_is_accepted_owner_v1(uuid) to documents_store_owner;
set local role documents_store_owner;
create table if not exists documents.retained_originals(
 id uuid primary key default gen_random_uuid(),
 document_id uuid not null,
 company_id uuid not null,
 source_income_year integer not null check(source_income_year between 2000 and 2100),
 metadata_sha256 text not null check(metadata_sha256 ~ '^[a-f0-9]{64}$'),
 content_sha256 text not null check(content_sha256 ~ '^[a-f0-9]{64}$'),
 byte_length integer not null check(byte_length between 1 and 10485760),
 content bytea not null,
 document_snapshot jsonb not null check(pg_catalog.jsonb_typeof(document_snapshot)='object'),
 retained_by uuid not null,
 retained_at timestamptz not null default pg_catalog.clock_timestamp(),
 unique(document_id,metadata_sha256,content_sha256),
 check(pg_catalog.octet_length(content)=byte_length),
 check(pg_catalog.encode(pg_catalog.sha256(content),'hex')=content_sha256)
);
alter table documents.retained_originals enable row level security;
alter table documents.retained_originals force row level security;
revoke all on documents.retained_originals from public,anon,authenticated,service_role,documents_executor,shareholder_register_filing_executor;
drop policy if exists retained_original_owner_read on documents.retained_originals;
create policy retained_original_owner_read on documents.retained_originals for select to documents_store_owner
 using(public.company_access_is_accepted_owner_v1(company_id));
drop policy if exists retained_original_owner_insert on documents.retained_originals;
create policy retained_original_owner_insert on documents.retained_originals for insert to documents_store_owner
 with check(public.company_access_is_accepted_owner_v1(company_id)
  and retained_by=nullif(pg_catalog.current_setting('talli.verified_actor_id',true),'')::uuid);
create or replace function documents.prevent_retained_original_mutation_v1() returns trigger
language plpgsql set search_path='' as $fn$
begin raise exception 'documents_retained_original_immutable'; end; $fn$;
drop trigger if exists retained_original_immutable on documents.retained_originals;
create trigger retained_original_immutable before update or delete on documents.retained_originals
 for each row execute function documents.prevent_retained_original_mutation_v1();
drop trigger if exists retained_original_no_truncate on documents.retained_originals;
create trigger retained_original_no_truncate before truncate on documents.retained_originals
 for each statement execute function documents.prevent_retained_original_mutation_v1();

create or replace function documents.retained_original_receipt_v1(p_id uuid) returns jsonb
language sql stable security invoker set search_path='' as $fn$
 select pg_catalog.jsonb_build_object('originalId',r.id,'documentId',r.document_id,'companyId',r.company_id,
  'sourceIncomeYear',r.source_income_year,'metadataSha256',r.metadata_sha256,'contentSha256',r.content_sha256,
  'byteLength',r.byte_length,'retainedAt',r.retained_at)
 from documents.retained_originals r where r.id=p_id;
$fn$;

create or replace function documents.retain_original_v1(p_document uuid,p_company uuid,p_metadata text,p_sha text,p_length integer,p_content bytea,p_subject text)
returns jsonb language plpgsql security definer set search_path='' as $fn$
declare d public.documents%rowtype; r documents.retained_originals%rowtype; a uuid:=nullif(pg_catalog.current_setting('talli.verified_actor_id',true),'')::uuid;
begin
 if a is null or p_subject is null or p_subject<>a::text or not public.company_access_is_accepted_owner_v1(p_company)
 then raise exception 'documents_forbidden'; end if;
 if p_document is null or p_company is null or p_metadata is null or p_metadata !~ '^[a-f0-9]{64}$'
  or p_sha is null or p_sha !~ '^[a-f0-9]{64}$' or p_length is null or p_length not between 1 and 10485760
  or p_content is null or pg_catalog.octet_length(p_content)<>p_length
  or pg_catalog.encode(pg_catalog.sha256(p_content),'hex')<>p_sha
 then raise exception 'documents_invalid_input'; end if;
 perform public.company_archive_lock_company_v1(p_company);
 -- Refresh permission after any wait; cached role maps cannot authorize retention.
 if not public.company_access_is_accepted_owner_v1(p_company) then raise exception 'documents_forbidden'; end if;
 perform pg_catalog.set_config('talli.authorized_company_roles',pg_catalog.jsonb_build_object(p_company::text,'owner')::text,true);
 select * into d from public.documents where id=p_document and company_id=p_company
  and status in ('attached','stored','generated_unsigned','signed_owner_attested')
  and content_sha256=p_sha and byte_length=p_length for update;
 if not found then raise exception 'documents_evidence_mismatch'; end if;
 insert into documents.retained_originals(document_id,company_id,source_income_year,metadata_sha256,content_sha256,byte_length,content,document_snapshot,retained_by)
 values(d.id,d.company_id,d.income_year,p_metadata,p_sha,p_length,p_content,pg_catalog.to_jsonb(d),a)
 on conflict(document_id,metadata_sha256,content_sha256) do nothing;
 select * into r from documents.retained_originals where document_id=d.id and metadata_sha256=p_metadata and content_sha256=p_sha;
 if r.id is null or r.company_id<>d.company_id or r.source_income_year<>d.income_year or r.content<>p_content
  or r.document_snapshot<>pg_catalog.to_jsonb(d) then raise exception 'documents_evidence_mismatch'; end if;
 -- Caller verifies complete metadata while this row lock remains held and raises
 -- a SQL assertion error on mismatch, rolling back this insertion as well.
 return pg_catalog.jsonb_build_object('receipt',documents.retained_original_receipt_v1(r.id),'document',pg_catalog.to_jsonb(d));
end; $fn$;

create or replace function documents.read_retained_original_v1(p_original uuid,p_company uuid,p_subject text)
returns table(receipt jsonb,content bytea) language plpgsql stable security definer set search_path='' as $fn$
declare a uuid:=nullif(pg_catalog.current_setting('talli.verified_actor_id',true),'')::uuid;
begin
 if a is null or p_subject is null or p_subject<>a::text or not public.company_access_is_accepted_owner_v1(p_company)
 then raise exception 'documents_forbidden'; end if;
 return query select documents.retained_original_receipt_v1(r.id),r.content from documents.retained_originals r
 where r.id=p_original and r.company_id=p_company;
 if not found then raise exception 'documents_not_found'; end if;
end; $fn$;

create or replace function documents.assert_retained_original_v1(p_original uuid,p_document uuid,p_company uuid,p_year integer,p_metadata text,p_sha text,p_length integer,p_retained_at timestamptz,p_subject text)
returns jsonb language plpgsql security definer set search_path='' as $fn$
declare d public.documents%rowtype; r documents.retained_originals%rowtype; a uuid:=nullif(pg_catalog.current_setting('talli.verified_actor_id',true),'')::uuid;
begin
 if a is null or p_subject is null or p_subject<>a::text or not public.company_access_is_accepted_owner_v1(p_company)
 then raise exception 'documents_forbidden'; end if;
 perform public.company_archive_lock_company_v1(p_company);
 if not public.company_access_is_accepted_owner_v1(p_company) then raise exception 'documents_forbidden'; end if;
 perform pg_catalog.set_config('talli.authorized_company_roles',pg_catalog.jsonb_build_object(p_company::text,'owner')::text,true);
 select * into r from documents.retained_originals where id=p_original and document_id=p_document and company_id=p_company
  and source_income_year=p_year and metadata_sha256=p_metadata and content_sha256=p_sha and byte_length=p_length and retained_at=p_retained_at;
 if not found then raise exception 'documents_evidence_mismatch'; end if;
 select * into d from public.documents where id=p_document and company_id=p_company for update;
 if not found or pg_catalog.to_jsonb(d)<>r.document_snapshot then raise exception 'documents_evidence_mismatch'; end if;
 return pg_catalog.to_jsonb(d);
end; $fn$;

revoke all on function documents.prevent_retained_original_mutation_v1(),documents.retained_original_receipt_v1(uuid),
 documents.retain_original_v1(uuid,uuid,text,text,integer,bytea,text),documents.read_retained_original_v1(uuid,uuid,text),
 documents.assert_retained_original_v1(uuid,uuid,uuid,integer,text,text,integer,timestamptz,text)
 from public,anon,authenticated,service_role,documents_executor,shareholder_register_filing_executor;
grant execute on function documents.retain_original_v1(uuid,uuid,text,text,integer,bytea,text),
 documents.read_retained_original_v1(uuid,uuid,text),documents.assert_retained_original_v1(uuid,uuid,uuid,integer,text,text,integer,timestamptz,text),
 documents.assert_retained_metadata_v1(text,text) to documents_executor;
grant execute on function documents.assert_retained_original_v1(uuid,uuid,uuid,integer,text,text,integer,timestamptz,text)
 to shareholder_register_filing_executor;
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
