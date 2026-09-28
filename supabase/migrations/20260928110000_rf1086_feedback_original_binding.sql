-- Commit a verified Documents original identity with new RF feedback metadata.
begin;
set local lock_timeout='5s';
set local statement_timeout='120s';
set local search_path='';
create temporary table rf193_feedback_original_roles(role_name text,prior jsonb) on commit drop;
do $borrow$
declare n text; p jsonb;
begin
 foreach n in array array['documents_store_owner','shareholder_register_filing_store_owner'] loop
  if not pg_catalog.pg_has_role(current_user,n,'SET') then
   select pg_catalog.jsonb_build_object('admin',m.admin_option,'inherit',m.inherit_option,'set',m.set_option)
   into p from pg_catalog.pg_auth_members m where m.roleid=pg_catalog.to_regrole(n)
    and m.member=pg_catalog.to_regrole(current_user) and m.grantor=m.member;
   insert into pg_temp.rf193_feedback_original_roles values(n,p);
   execute pg_catalog.format('grant %I to %I with set true granted by %I',n,current_user,current_user);
  end if;
 end loop;
end; $borrow$;
set local role documents_store_owner;
-- A receipt assertion exposes metadata only, never retained object bytes.
grant execute on function documents.assert_retained_original_v1(uuid,uuid,uuid,integer,text,text,integer,timestamptz,text)
 to shareholder_register_filing_store_owner;
reset role;
set local role shareholder_register_filing_store_owner;
alter table shareholder_register_filing.production_feedback_artifacts
 add column if not exists original_id uuid,
 add column if not exists original_metadata_sha256 text,
 add column if not exists original_source_income_year integer,
 add column if not exists original_retained_at timestamptz;
do $constraint$
begin
 if not exists(select 1 from pg_catalog.pg_constraint where conrelid='shareholder_register_filing.production_feedback_artifacts'::regclass
  and conname='feedback_original_complete') then
  alter table shareholder_register_filing.production_feedback_artifacts add constraint feedback_original_complete check(
   pg_catalog.num_nonnulls(original_id,original_metadata_sha256,original_source_income_year,original_retained_at)=0
   or (pg_catalog.num_nonnulls(original_id,original_metadata_sha256,original_source_income_year,original_retained_at)=4
    and original_metadata_sha256 ~ '^[a-f0-9]{64}$' and original_source_income_year between 2000 and 2100));
 end if;
end; $constraint$;
create or replace function shareholder_register_filing.protect_feedback_original_v1() returns trigger
language plpgsql set search_path='' as $fn$
begin
 if old.original_id is not null and pg_catalog.to_jsonb(new) is distinct from pg_catalog.to_jsonb(old)
 then raise exception 'rf1086_feedback_original_immutable'; end if;
 return new;
end; $fn$;
revoke all on function shareholder_register_filing.protect_feedback_original_v1() from public,anon,authenticated,service_role,shareholder_register_filing_executor;
drop trigger if exists feedback_original_immutable on shareholder_register_filing.production_feedback_artifacts;
create trigger feedback_original_immutable before update on shareholder_register_filing.production_feedback_artifacts
 for each row execute function shareholder_register_filing.protect_feedback_original_v1();

create or replace function shareholder_register_filing.record_retained_feedback_artifact_v1(
 p_company_id uuid,p_submission_id uuid,p_document_id uuid,p_authority_reference text,p_content_type text,
 p_byte_length bigint,p_sha256 text,p_classification text,p_original_id uuid,p_metadata_sha256 text,p_retained_at timestamptz)
returns shareholder_register_filing.production_feedback_artifacts
language plpgsql volatile security definer set search_path='' as $fn$
declare r shareholder_register_filing.production_feedback_artifacts%rowtype; y integer;
begin
 perform shareholder_register_filing.lock_submission_company_write_v1(p_submission_id);
 select s.income_year into y from shareholder_register_filing.production_filing_submissions s
 where s.id=p_submission_id and s.company_id=p_company_id;
 if not found then raise exception 'production_feedback_submission_relationship_mismatch'; end if;
 -- Existing canonical records keep their original attribution. Missing legacy
 -- bindings cannot be reconstructed from today's mutable document projection.
 select * into r from shareholder_register_filing.production_feedback_artifacts
 where submission_id=p_submission_id and sha256=p_sha256;
 if found then return r; end if;
 if p_original_id is null or p_metadata_sha256 is null or p_retained_at is null
  or p_byte_length is null or p_byte_length not between 1 and 10485760
 then raise exception 'production_feedback_metadata_invalid'; end if;
 perform documents.assert_retained_original_v1(p_original_id,p_document_id,p_company_id,y,
  p_metadata_sha256,p_sha256,p_byte_length::integer,p_retained_at,shareholder_register_filing.actor_v1()::text);
 r:=shareholder_register_filing.record_production_feedback_artifact(p_company_id,p_submission_id,p_document_id,
  p_authority_reference,p_content_type,p_byte_length,p_sha256,p_classification);
 if r.document_id is distinct from p_document_id then raise exception 'production_feedback_document_relationship_mismatch'; end if;
 update shareholder_register_filing.production_feedback_artifacts set original_id=p_original_id,
  original_metadata_sha256=p_metadata_sha256,original_source_income_year=y,original_retained_at=p_retained_at
 where id=r.id returning * into r;
 return r;
end; $fn$;
revoke all on function shareholder_register_filing.record_retained_feedback_artifact_v1(uuid,uuid,uuid,text,text,bigint,text,text,uuid,text,timestamptz) from public,anon,authenticated,service_role;
grant execute on function shareholder_register_filing.record_retained_feedback_artifact_v1(uuid,uuid,uuid,text,text,bigint,text,text,uuid,text,timestamptz) to shareholder_register_filing_executor;
reset role;
do $restore$
declare r record;
begin
 for r in select * from pg_temp.rf193_feedback_original_roles loop
  execute pg_catalog.format('revoke %I from %I granted by %I',r.role_name,current_user,current_user);
  if r.prior is not null then
   execute pg_catalog.format('grant %I to %I with admin %s,inherit %s,set %s granted by %I',r.role_name,current_user,r.prior->>'admin',r.prior->>'inherit',r.prior->>'set',current_user);
  end if;
 end loop;
end; $restore$;
commit;
