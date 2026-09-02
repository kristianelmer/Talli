-- Canonical accounting-document metadata and private transfer boundary (#147).
begin;

do $roles$
begin
  if not exists (select 1 from pg_catalog.pg_roles where rolname = 'documents_store_owner') then
    create role documents_store_owner nologin noinherit nobypassrls;
  end if;
  if not exists (select 1 from pg_catalog.pg_roles where rolname = 'documents_executor') then
    create role documents_executor nologin noinherit nobypassrls;
  end if;
end
$roles$;

do $membership$
begin
  execute pg_catalog.format(
    'grant documents_store_owner, documents_executor to %I', current_user
  );
end
$membership$;

create schema if not exists documents authorization documents_store_owner;
revoke all on schema documents from public, anon, authenticated, service_role;
grant usage on schema documents to documents_executor;
grant usage, create on schema public to documents_store_owner;

alter table public.documents
  add column if not exists content_type text not null default 'application/pdf',
  add column if not exists declared_byte_length bigint,
  add column if not exists byte_length bigint,
  add column if not exists content_sha256 text,
  add column if not exists staged_at timestamptz,
  add column if not exists quarantined_at timestamptz,
  add column if not exists quarantine_reason text,
  add column if not exists final_status text,
  add column if not exists removed_from_status text;

alter table public.documents drop constraint if exists documents_content_sha256_check;
alter table public.documents add constraint documents_content_sha256_check
  check (content_sha256 is null or content_sha256 ~ '^[0-9a-f]{64}$');
alter table public.documents drop constraint if exists documents_byte_length_check;
alter table public.documents add constraint documents_byte_length_check
  check (byte_length is null or byte_length between 1 and 10485760);
alter table public.documents drop constraint if exists documents_declared_byte_length_check;
alter table public.documents add constraint documents_declared_byte_length_check
  check (declared_byte_length is null or declared_byte_length between 1 and 10485760);

alter table public.documents owner to documents_store_owner;
revoke create on schema public from documents_store_owner;
alter table public.documents enable row level security;
alter table public.documents force row level security;
revoke all on public.documents from public, anon, authenticated, service_role, documents_executor;

drop policy if exists "company members can read documents" on public.documents;
drop policy if exists "company members can read document metadata" on public.documents;
drop policy if exists "owners can create document metadata" on public.documents;
drop policy if exists documents_store_reads_visible_documents on public.documents;
create policy documents_store_reads_visible_documents on public.documents
for select to documents_store_owner
using (
  coalesce(
    nullif(pg_catalog.current_setting('talli.authorized_company_roles', true), ''),
    '{}'
  )::jsonb ? company_id::text
);
drop policy if exists documents_store_creates_owner_documents on public.documents;
create policy documents_store_creates_owner_documents on public.documents
for insert to documents_store_owner
with check (
  created_by = nullif(pg_catalog.current_setting('talli.verified_actor_id', true), '')::uuid
  and coalesce(
    nullif(pg_catalog.current_setting('talli.authorized_company_roles', true), ''),
    '{}'
  )::jsonb ->> company_id::text = 'owner'
);
drop policy if exists documents_store_updates_owner_documents on public.documents;
create policy documents_store_updates_owner_documents on public.documents
for update to documents_store_owner
using (
  coalesce(
    nullif(pg_catalog.current_setting('talli.authorized_company_roles', true), ''),
    '{}'
  )::jsonb ->> company_id::text = 'owner'
)
with check (
  coalesce(
    nullif(pg_catalog.current_setting('talli.authorized_company_roles', true), ''),
    '{}'
  )::jsonb ->> company_id::text = 'owner'
);

grant insert on public.audit_events to documents_store_owner;
drop policy if exists documents_store_appends_document_audit on public.audit_events;
create policy documents_store_appends_document_audit on public.audit_events
for insert to documents_store_owner
with check (
  actor_id = nullif(pg_catalog.current_setting('talli.verified_actor_id', true), '')::uuid
  and coalesce(
    nullif(pg_catalog.current_setting('talli.authorized_company_roles', true), ''),
    '{}'
  )::jsonb ->> company_id::text = 'owner'
);

set local role documents_store_owner;

create or replace function documents.actor_company_role_v1(p_company_id uuid)
returns text language sql security definer set search_path = '' stable
as $function$
  select coalesce(
    nullif(pg_catalog.current_setting('talli.authorized_company_roles', true), ''),
    '{}'
  )::jsonb ->> p_company_id::text
$function$;

create or replace function documents.stage_upload_v1(p_request jsonb, p_verified_subject text)
returns setof public.documents language plpgsql security definer set search_path = ''
as $function$
declare v_actor uuid;
begin
  v_actor := nullif(pg_catalog.current_setting('talli.verified_actor_id', true), '')::uuid;
  if v_actor is null or v_actor::text <> p_verified_subject then raise exception 'documents_forbidden'; end if;
  if (coalesce(
      nullif(pg_catalog.current_setting('talli.authorized_company_roles', true), ''),
      '{}'
    )::jsonb ->> (p_request ->> 'companyId')) is distinct from 'owner'
    or p_request ->> 'contentType' not in ('application/pdf','application/octet-stream','application/xml','text/xml','text/plain')
    or (p_request ->> 'declaredByteLength')::bigint not between 1 and 10485760
    or p_request ->> 'documentType' not in ('bank_statement','accounting_document','corporate_document','authority_feedback')
    or p_request ->> 'finalStatus' not in ('attached','generated_unsigned','signed_owner_attested','stored')
    or not (
      (
        p_request ->> 'documentType' in ('bank_statement','accounting_document')
        and p_request ->> 'linkedTo' in ('workspace','aksjonaerregisteroppgaven','skattemelding','aarsregnskap')
        and p_request ->> 'finalStatus' = 'attached'
      )
      or (
        p_request ->> 'documentType' = 'corporate_document'
        and (
          (p_request ->> 'linkedTo' in ('workspace','aksjonaerregisteroppgaven','skattemelding','aarsregnskap') and p_request ->> 'finalStatus'='attached')
          or (p_request ->> 'linkedTo' ~ '^corporate_decision:[0-9a-fA-F-]{36}$' and p_request ->> 'finalStatus' in ('generated_unsigned','signed_owner_attested'))
        )
      )
      or (
        p_request ->> 'documentType' = 'authority_feedback'
        and p_request ->> 'linkedTo' ~ '^production_filing_submission:[0-9a-fA-F-]{36}$'
        and p_request ->> 'finalStatus' = 'stored'
      )
    )
  then raise exception 'documents_invalid_input'; end if;
  return query
  insert into public.documents (
    id, company_id, income_year, document_type, name, linked_to, status,
    retention_years, storage_key, created_by, content_type,
    declared_byte_length, staged_at, final_status
  ) values (
    (p_request ->> 'documentId')::uuid, (p_request ->> 'companyId')::uuid,
    (p_request ->> 'incomeYear')::integer, p_request ->> 'documentType',
    p_request ->> 'name', p_request ->> 'linkedTo', 'staged', 5,
    p_request ->> 'storageKey', v_actor, p_request ->> 'contentType',
    (p_request ->> 'declaredByteLength')::bigint, pg_catalog.now(), p_request ->> 'finalStatus'
  )
  on conflict (id) do nothing
  returning *;
  if found then return; end if;
  return query
  select document.* from public.documents document
  where document.id=(p_request ->> 'documentId')::uuid
    and document.company_id=(p_request ->> 'companyId')::uuid
    and document.income_year=(p_request ->> 'incomeYear')::integer
    and document.document_type=p_request ->> 'documentType'
    and document.name=p_request ->> 'name'
    and document.linked_to=p_request ->> 'linkedTo'
    and document.status='staged'
    and document.retention_years=5
    and document.storage_key=p_request ->> 'storageKey'
    and document.created_by=v_actor
    and document.content_type=p_request ->> 'contentType'
    and document.declared_byte_length=(p_request ->> 'declaredByteLength')::bigint
    and document.final_status=p_request ->> 'finalStatus';
  if not found then raise exception 'documents_conflict'; end if;
end
$function$;

create or replace function documents.get_document_v1(p_document_id uuid, p_verified_subject text)
returns setof public.documents language sql security definer set search_path = '' stable
as $function$
  select document.* from public.documents document
  where document.id = p_document_id
    and nullif(pg_catalog.current_setting('talli.verified_actor_id', true), '') = p_verified_subject
$function$;

create or replace function documents.list_documents_v1(p_company_ids uuid[], p_verified_subject text)
returns setof public.documents language sql security definer set search_path = '' stable
as $function$
  select document.* from public.documents document
  where document.company_id = any(p_company_ids)
    and document.status <> 'removed'
    and nullif(pg_catalog.current_setting('talli.verified_actor_id', true), '') = p_verified_subject
  order by document.created_at desc, document.id desc
$function$;

create or replace function documents.quarantine_upload_v1(
  p_document_id uuid, p_reason text, p_verified_subject text
) returns void language plpgsql security definer set search_path = ''
as $function$
begin
  if nullif(pg_catalog.current_setting('talli.verified_actor_id', true), '') <> p_verified_subject
  then raise exception 'documents_forbidden'; end if;
  update public.documents set status='quarantined', quarantined_at=pg_catalog.now(),
    quarantine_reason=left(p_reason, 200)
  where id=p_document_id and status='staged';
end
$function$;

create or replace function documents.finalize_upload_v1(
  p_document_id uuid, p_byte_length bigint, p_content_sha256 text,
  p_verified_subject text
) returns setof public.documents language plpgsql security definer set search_path = ''
as $function$
begin
  if nullif(pg_catalog.current_setting('talli.verified_actor_id', true), '') <> p_verified_subject
  then raise exception 'documents_forbidden'; end if;
  if p_byte_length not between 1 and 10485760
    or p_content_sha256 !~ '^[0-9a-f]{64}$'
  then raise exception 'documents_invalid_input'; end if;
  return query update public.documents set status=coalesce(final_status,'attached'), byte_length=p_byte_length,
    content_sha256=p_content_sha256, quarantined_at=null, quarantine_reason=null
  where id=p_document_id and status='staged' and declared_byte_length=p_byte_length
  returning *;
  if found then return; end if;
  return query select document.* from public.documents document
  where document.id=p_document_id
    and document.status in ('attached','generated_unsigned','signed_owner_attested','stored')
    and document.byte_length=p_byte_length
    and document.content_sha256=p_content_sha256;
  if not found then raise exception 'documents_conflict'; end if;
end
$function$;

reset role;

-- A single boolean projection is the only evidence access granted to the
-- document store. Its migration owner can see every evidence table, while the
-- document role cannot enumerate or join any of them directly.
create or replace function documents.has_evidence_references_v1(p_document_id uuid)
returns boolean language plpgsql security definer set search_path = '' stable
as $function$
declare v_investment_linked boolean := false;
begin
  -- Older investment characterization rehearsals intentionally apply this
  -- successor migration before the lifecycle registry exists. Resolve that
  -- predecessor-safe dependency only when the canonical registry is present.
  if pg_catalog.to_regclass('investments.source_fact_registry') is not null then
    execute $query$
      select exists (
        select 1 from investments.source_fact_registry item
        where item.source_capability='DOCUMENTS'
          and item.source_record_id=$1
      )
    $query$ into v_investment_linked using p_document_id;
  end if;
  return exists (select 1 from public.holding_actions item where item.document_id=p_document_id)
    or exists (select 1 from public.corporate_document_artifacts item where item.document_id=p_document_id)
    or exists (
      select 1 from public.filing_submissions item
      where coalesce(item.feedback_document_ids,'[]'::jsonb) @> pg_catalog.jsonb_build_array(p_document_id::text)
         or item.receipt_id=p_document_id::text
    )
    or exists (select 1 from public.production_feedback_artifacts item where item.document_id=p_document_id)
    or v_investment_linked
    or exists (
      select 1 from public.ledger_entries item join public.documents document on document.id=p_document_id
      where item.company_id=document.company_id and pg_catalog.strpos(item.memo, p_document_id::text)>0
    );
end;
$function$;

revoke all on function documents.has_evidence_references_v1(uuid)
from public, anon, authenticated, service_role;
grant execute on function documents.has_evidence_references_v1(uuid) to documents_store_owner;

set local role documents_store_owner;

create or replace function documents.assert_registered_artifact_v1(
  p_document_id uuid, p_company_id uuid, p_income_year integer,
  p_document_type text, p_linked_to text, p_status text, p_name text,
  p_storage_key text, p_content_type text, p_byte_length bigint,
  p_content_sha256 text, p_actor_id uuid
) returns void language plpgsql security definer set search_path = ''
as $function$
begin
  perform pg_catalog.set_config('talli.verified_actor_id', p_actor_id::text, true);
  perform pg_catalog.set_config(
    'talli.authorized_company_roles',
    pg_catalog.jsonb_build_object(p_company_id::text, 'owner')::text,
    true
  );
  if not exists (
    select 1 from public.documents document
    where document.id=p_document_id and document.company_id=p_company_id
      and document.income_year=p_income_year and document.document_type=p_document_type
      and document.linked_to=p_linked_to and document.status=p_status
      and document.name=p_name and document.storage_key=p_storage_key
      and document.content_type=p_content_type and document.byte_length=p_byte_length
      and document.content_sha256=p_content_sha256 and document.created_by=p_actor_id
  ) then raise exception 'documents_artifact_not_registered'; end if;
end
$function$;

create or replace function documents.mark_removed_v1(
  p_document_id uuid, p_reason text, p_verified_subject text
) returns setof public.documents language plpgsql security definer set search_path = ''
as $function$
declare v_actor uuid; v_company uuid;
begin
  v_actor := nullif(pg_catalog.current_setting('talli.verified_actor_id', true), '')::uuid;
  if v_actor is null or v_actor::text <> p_verified_subject then raise exception 'documents_forbidden'; end if;
  if documents.has_evidence_references_v1(p_document_id) then raise exception 'documents_evidence_linked'; end if;
  select company_id into v_company from public.documents
  where id=p_document_id and status in ('attached','generated_unsigned','signed_owner_attested','stored') for update;
  if not found then raise exception 'documents_not_found'; end if;
  return query update public.documents set removed_from_status=status, status='removed', removed_at=pg_catalog.now(),
    removed_by=v_actor, removal_reason=left(p_reason,200)
  where id=p_document_id returning *;
  insert into public.audit_events(company_id,actor_id,category,action,message)
  values(v_company,v_actor,'document','document_removal_requested','Unlinked document marked for removal.');
end
$function$;

create or replace function documents.restore_after_storage_failure_v1(
  p_document_id uuid, p_verified_subject text
) returns void language plpgsql security definer set search_path = ''
as $function$
declare v_actor uuid; v_company uuid;
begin
  v_actor := nullif(pg_catalog.current_setting('talli.verified_actor_id', true), '')::uuid;
  if v_actor is null or v_actor::text <> p_verified_subject then raise exception 'documents_forbidden'; end if;
  update public.documents set status=coalesce(removed_from_status,'attached'),removed_at=null,
    removed_by=null,removal_reason=null,removed_from_status=null
  where id=p_document_id and status='removed' and removed_by=v_actor
    and removed_at >= pg_catalog.now()-interval '5 minutes'
  returning company_id into v_company;
  if not found then raise exception 'documents_conflict'; end if;
  insert into public.audit_events(company_id,actor_id,category,action,message)
  values(v_company,v_actor,'document','document_removal_storage_failed','Document removal restored after storage failure.');
end
$function$;

reset role;

-- The next-stage governance implementation remains legacy, but its two producer
-- functions are cut to the documents public contract. The exact guarded rewrite
-- fails if their characterized definitions drift and leaves no active document
-- metadata writer in governance.
do $rewrite_corporate_draft$
declare v_definition text; v_rewritten text;
begin
  v_definition := pg_catalog.pg_get_functiondef('public.create_corporate_document_draft(jsonb)'::regprocedure);
  v_rewritten := pg_catalog.replace(v_definition, $old$
    insert into public.documents (
      id,
      company_id,
      income_year,
      document_type,
      name,
      linked_to,
      status,
      storage_key,
      created_by
    ) values (
      (v_artifact ->> 'document_id')::uuid,
      v_company_id,
      v_income_year,
      'corporate_document',
      v_artifact ->> 'name',
      v_decision_id::text,
      'generated_unsigned',
      v_artifact ->> 'storage_key',
      v_actor_id
    );$old$, $new$
    perform documents.assert_registered_artifact_v1(
      (v_artifact ->> 'document_id')::uuid, v_company_id, v_income_year,
      'corporate_document', 'corporate_decision:' || v_decision_id::text,
      'generated_unsigned', v_artifact ->> 'name', v_artifact ->> 'storage_key',
      v_artifact ->> 'mime_type', (v_artifact ->> 'byte_length')::bigint,
      v_artifact ->> 'content_sha256', v_actor_id
    );$new$);
  if v_rewritten = v_definition then raise exception 'documents_corporate_draft_definition_drift'; end if;
  execute v_rewritten;
end
$rewrite_corporate_draft$;

do $rewrite_corporate_signed$
declare v_definition text; v_rewritten text;
begin
  v_definition := pg_catalog.pg_get_functiondef('public.attest_corporate_signed_artifact(jsonb)'::regprocedure);
  v_rewritten := pg_catalog.replace(v_definition, $old$
  insert into public.documents (
    id,
    company_id,
    income_year,
    document_type,
    name,
    linked_to,
    status,
    storage_key,
    created_by
  ) values (
    (v_signed ->> 'document_id')::uuid,
    v_decision.company_id,
    v_decision.income_year,
    'corporate_document',
    v_signed ->> 'name',
    v_decision.id::text,
    'signed_owner_attested',
    v_signed ->> 'storage_key',
    v_actor_id
  );$old$, $new$
  perform documents.assert_registered_artifact_v1(
    (v_signed ->> 'document_id')::uuid, v_decision.company_id, v_decision.income_year,
    'corporate_document', 'corporate_decision:' || v_decision.id::text,
    'signed_owner_attested', v_signed ->> 'name', v_signed ->> 'storage_key',
    v_signed ->> 'mime_type', (v_signed ->> 'byte_length')::bigint,
    v_signed ->> 'content_sha256', v_actor_id
  );$new$);
  if v_rewritten = v_definition then raise exception 'documents_corporate_signed_definition_drift'; end if;
  execute v_rewritten;
end
$rewrite_corporate_signed$;

do $producer_grants$
declare v_owner text;
begin
  for v_owner in
    select distinct owner.rolname from pg_catalog.pg_proc procedure
    join pg_catalog.pg_roles owner on owner.oid=procedure.proowner
    where procedure.oid in (
      'public.create_corporate_document_draft(jsonb)'::regprocedure,
      'public.attest_corporate_signed_artifact(jsonb)'::regprocedure
    )
  loop
    execute pg_catalog.format(
      'grant execute on function documents.assert_registered_artifact_v1(uuid,uuid,integer,text,text,text,text,text,text,bigint,text,uuid) to %I',
      v_owner
    );
  end loop;
end
$producer_grants$;

revoke all on function documents.actor_company_role_v1(uuid),
  documents.stage_upload_v1(jsonb,text), documents.get_document_v1(uuid,text),
  documents.list_documents_v1(uuid[],text), documents.quarantine_upload_v1(uuid,text,text),
  documents.finalize_upload_v1(uuid,bigint,text,text),
  documents.has_evidence_references_v1(uuid),
  documents.assert_registered_artifact_v1(uuid,uuid,integer,text,text,text,text,text,text,bigint,text,uuid),
  documents.mark_removed_v1(uuid,text,text),
  documents.restore_after_storage_failure_v1(uuid,text)
from public, anon, authenticated, service_role;
grant execute on function documents.actor_company_role_v1(uuid),
  documents.stage_upload_v1(jsonb,text), documents.get_document_v1(uuid,text),
  documents.list_documents_v1(uuid[],text), documents.quarantine_upload_v1(uuid,text,text),
  documents.finalize_upload_v1(uuid,bigint,text,text),
  documents.has_evidence_references_v1(uuid), documents.mark_removed_v1(uuid,text,text),
  documents.restore_after_storage_failure_v1(uuid,text)
to documents_executor;

revoke all on function public.remove_unlinked_document(uuid),
  public.restore_unlinked_document_after_storage_failure(uuid)
from public, anon, authenticated, service_role;

drop policy if exists "company members can read company document objects" on storage.objects;
drop policy if exists "owners can upload company document objects" on storage.objects;
drop policy if exists "owners can delete removed unlinked document objects" on storage.objects;

grant documents_executor to talli_ledger_backend;

do $membership_revoke$
begin
  execute pg_catalog.format(
    'revoke documents_store_owner, documents_executor from %I', current_user
  );
end
$membership_revoke$;

commit;
