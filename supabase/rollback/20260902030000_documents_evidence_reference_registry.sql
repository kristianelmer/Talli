-- Roll back the Documents evidence registry only after consumer workflows.
begin;

set local lock_timeout = '5s';
set local statement_timeout = '120s';

do $guard$
begin
  if pg_catalog.to_regprocedure(
    'backend_system.register_corporate_governance_evidence_v1(text,uuid,uuid,uuid,integer,text,text,text,bigint,uuid)'
  ) is not null then
    raise exception 'documents_evidence_registry_rollback_unsafe';
  end if;
  if exists (select 1 from documents.evidence_references) then
    raise exception 'documents_evidence_registry_rollback_unsafe';
  end if;
end
$guard$;

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

create or replace function documents.has_evidence_references_v1(p_document_id uuid)
returns boolean language plpgsql security definer set search_path = '' stable
as $function$
declare v_investment_linked boolean := false;
begin
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

drop function documents.register_evidence_reference_v1(
  text, text, uuid, uuid, uuid, integer, text, text, text, bigint, uuid
);
drop table documents.evidence_references;

reset role;

revoke execute on function public.company_access_is_accepted_owner_v1(uuid)
from documents_store_owner;

do $membership_revoke$
begin
  execute pg_catalog.format(
    'revoke documents_store_owner from %I',
    pg_catalog.current_setting('talli.documents_evidence_registry_principal')
  );
end
$membership_revoke$;

commit;
