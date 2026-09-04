-- Documents-owned immutable evidence-reference registry for successor capabilities.
begin;

set local lock_timeout = '5s';
set local statement_timeout = '120s';

do $membership$
begin
  execute pg_catalog.format(
    'grant documents_store_owner to %I with set true', current_user
  );
end
$membership$;

select pg_catalog.set_config(
  'talli.documents_evidence_registry_principal', current_user, true
);

grant execute on function public.company_access_is_accepted_owner_v1(uuid)
to documents_store_owner;

set local role documents_store_owner;

create table documents.evidence_references (
  source_capability text not null check (
    source_capability ~ '^[a-z][a-z0-9_]{1,63}$'
  ),
  source_record_type text not null check (
    source_record_type ~ '^[a-z][a-z0-9_]{1,63}$'
  ),
  source_record_id uuid not null,
  document_id uuid not null references public.documents(id) on delete restrict,
  company_id uuid not null,
  income_year integer not null check (income_year between 2000 and 2100),
  linked_to text,
  document_status text check (
    document_status is null
    or document_status in ('generated_unsigned', 'signed_owner_attested')
  ),
  content_sha256 text check (
    content_sha256 is null or content_sha256 ~ '^[0-9a-f]{64}$'
  ),
  byte_length bigint check (
    byte_length is null or byte_length between 1 and 10485760
  ),
  created_by uuid not null,
  created_at timestamptz not null default pg_catalog.now(),
  primary key (source_capability, source_record_type, source_record_id)
);

create index documents_evidence_references_document_idx
on documents.evidence_references(document_id);

create or replace function documents.register_evidence_reference_v1(
  p_source_capability text,
  p_source_record_type text,
  p_source_record_id uuid,
  p_document_id uuid,
  p_company_id uuid,
  p_income_year integer,
  p_linked_to text,
  p_status text,
  p_content_sha256 text,
  p_byte_length bigint,
  p_actor_id uuid
) returns void language plpgsql security definer set search_path = ''
as $function$
declare
  v_actor_id uuid;
begin
  v_actor_id := nullif(
    pg_catalog.current_setting('talli.verified_actor_id', true), ''
  )::uuid;
  if v_actor_id is null
    or v_actor_id <> p_actor_id
    or not public.company_access_is_accepted_owner_v1(p_company_id)
  then
    raise exception 'documents_forbidden';
  end if;
  perform pg_catalog.set_config(
    'talli.authorized_company_roles',
    pg_catalog.jsonb_build_object(p_company_id::text, 'owner')::text,
    true
  );
  perform 1
  from public.documents document
  where document.id = p_document_id
    and document.company_id = p_company_id
    and document.income_year = p_income_year
    and document.status not in ('quarantined', 'removed')
    and (p_linked_to is null or (
      document.document_type = 'corporate_document'
      and document.linked_to = p_linked_to
    ))
    and (p_status is null or document.status = p_status)
    and (p_content_sha256 is null
      or document.content_sha256 = p_content_sha256)
    and (p_byte_length is null or document.byte_length = p_byte_length)
  for update;
  if not found then
    raise exception 'documents_evidence_mismatch';
  end if;

  insert into documents.evidence_references(
    source_capability, source_record_type, source_record_id,
    document_id, company_id, income_year, linked_to, document_status,
    content_sha256, byte_length, created_by
  ) values (
    p_source_capability, p_source_record_type, p_source_record_id,
    p_document_id, p_company_id, p_income_year, p_linked_to, p_status,
    p_content_sha256, p_byte_length, p_actor_id
  )
  on conflict (source_capability, source_record_type, source_record_id)
  do nothing;

  if not found and not exists (
    select 1 from documents.evidence_references reference
    where reference.source_capability = p_source_capability
      and reference.source_record_type = p_source_record_type
      and reference.source_record_id = p_source_record_id
      and reference.document_id = p_document_id
      and reference.company_id = p_company_id
      and reference.income_year = p_income_year
      and reference.linked_to is not distinct from p_linked_to
      and reference.document_status is not distinct from p_status
      and reference.content_sha256 is not distinct from p_content_sha256
      and reference.byte_length is not distinct from p_byte_length
      and reference.created_by = p_actor_id
  ) then
    raise exception 'documents_evidence_conflict';
  end if;
end
$function$;

reset role;

revoke all on function documents.register_evidence_reference_v1(
  text, text, uuid, uuid, uuid, integer, text, text, text, bigint, uuid
) from public, anon, authenticated, service_role, documents_executor;

-- The migration owner retains the predecessor compatibility reads. Dynamic
-- lookup avoids coupling this Documents contract to a table retired later.
create or replace function documents.has_evidence_references_v1(p_document_id uuid)
returns boolean language plpgsql security definer set search_path = '' stable
as $function$
declare
  v_corporate_linked boolean := false;
  v_investment_linked boolean := false;
begin
  if pg_catalog.to_regclass('public.corporate_document_artifacts') is not null then
    execute $query$
      select exists (
        select 1 from public.corporate_document_artifacts item
        where item.document_id=$1
      )
    $query$ into v_corporate_linked using p_document_id;
  end if;
  if pg_catalog.to_regclass('investments.source_fact_registry') is not null then
    execute $query$
      select exists (
        select 1 from investments.source_fact_registry item
        where item.source_capability='DOCUMENTS'
          and item.source_record_id=$1
      )
    $query$ into v_investment_linked using p_document_id;
  end if;
  return exists (
      select 1 from documents.evidence_references item
      where item.document_id=p_document_id
    )
    or exists (
      select 1 from public.holding_actions item
      where item.document_id=p_document_id
    )
    or v_corporate_linked
    or exists (
      select 1 from public.filing_submissions item
      where coalesce(item.feedback_document_ids,'[]'::jsonb)
              @> pg_catalog.jsonb_build_array(p_document_id::text)
         or item.receipt_id=p_document_id::text
    )
    or exists (
      select 1 from public.production_feedback_artifacts item
      where item.document_id=p_document_id
    )
    or v_investment_linked
    or exists (
      select 1 from public.ledger_entries item
      join public.documents document on document.id=p_document_id
      where item.company_id=document.company_id
        and pg_catalog.strpos(item.memo, p_document_id::text)>0
    );
end;
$function$;

revoke all on function documents.has_evidence_references_v1(uuid)
from public, anon, authenticated, service_role;
grant execute on function documents.has_evidence_references_v1(uuid)
to documents_store_owner;

set local role documents_store_owner;

create or replace function documents.mark_removed_v1(
  p_document_id uuid, p_reason text, p_verified_subject text
) returns setof public.documents language plpgsql security definer set search_path = ''
as $function$
declare v_actor uuid; v_company uuid;
begin
  v_actor := nullif(pg_catalog.current_setting('talli.verified_actor_id', true), '')::uuid;
  if v_actor is null or v_actor::text <> p_verified_subject then raise exception 'documents_forbidden'; end if;
  select company_id into v_company from public.documents
  where id=p_document_id and status in ('attached','generated_unsigned','signed_owner_attested','stored') for update;
  if not found then raise exception 'documents_not_found'; end if;
  if documents.has_evidence_references_v1(p_document_id) then raise exception 'documents_evidence_linked'; end if;
  return query update public.documents set removed_from_status=status, status='removed', removed_at=pg_catalog.now(),
    removed_by=v_actor, removal_reason=left(p_reason,200)
  where id=p_document_id returning *;
  insert into public.audit_events(company_id,actor_id,category,action,message)
  values(v_company,v_actor,'document','document_removal_requested','Unlinked document marked for removal.');
end
$function$;

reset role;

do $existing_workflow_grant$
begin
  if exists (
    select 1 from pg_catalog.pg_roles
    where rolname = 'corporate_governance_workflow_executor'
  ) then
    grant usage on schema documents
    to corporate_governance_workflow_executor;
    grant execute on function documents.register_evidence_reference_v1(
      text, text, uuid, uuid, uuid, integer, text, text, text, bigint, uuid
    ) to corporate_governance_workflow_executor;
  end if;
end
$existing_workflow_grant$;

do $membership_revoke$
begin
  execute pg_catalog.format(
    'revoke documents_store_owner from %I',
    pg_catalog.current_setting('talli.documents_evidence_registry_principal')
  );
end
$membership_revoke$;

commit;
