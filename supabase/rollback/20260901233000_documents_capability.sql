-- Bounded #147 rollback before staged/canonical document state is written.
begin;

do $migration_authority$
begin
  execute pg_catalog.format('grant documents_store_owner to %I', current_user);
end
$migration_authority$;

do $guard$
begin
  if exists (
    select 1 from public.documents
    where status in ('staged','quarantined') or content_sha256 is not null
  ) then raise exception 'documents_capability_rollback_unsafe'; end if;
end
$guard$;

do $restore_corporate_draft$
declare v_definition text; v_restored text;
begin
  v_definition := pg_catalog.pg_get_functiondef('public.create_corporate_document_draft(jsonb)'::regprocedure);
  v_restored := pg_catalog.replace(v_definition, $new$
    perform documents.assert_registered_artifact_v1(
      (v_artifact ->> 'document_id')::uuid, v_company_id, v_income_year,
      'corporate_document', 'corporate_decision:' || v_decision_id::text,
      'generated_unsigned', v_artifact ->> 'name', v_artifact ->> 'storage_key',
      v_artifact ->> 'mime_type', (v_artifact ->> 'byte_length')::bigint,
      v_artifact ->> 'content_sha256', v_actor_id
    );$new$, $old$
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
    );$old$);
  if v_restored = v_definition then raise exception 'documents_corporate_draft_rollback_drift'; end if;
  execute v_restored;
end
$restore_corporate_draft$;

do $restore_corporate_signed$
declare v_definition text; v_restored text;
begin
  v_definition := pg_catalog.pg_get_functiondef('public.attest_corporate_signed_artifact(jsonb)'::regprocedure);
  v_restored := pg_catalog.replace(v_definition, $new$
  perform documents.assert_registered_artifact_v1(
    (v_signed ->> 'document_id')::uuid, v_decision.company_id, v_decision.income_year,
    'corporate_document', 'corporate_decision:' || v_decision.id::text,
    'signed_owner_attested', v_signed ->> 'name', v_signed ->> 'storage_key',
    v_signed ->> 'mime_type', (v_signed ->> 'byte_length')::bigint,
    v_signed ->> 'content_sha256', v_actor_id
  );$new$, $old$
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
  );$old$);
  if v_restored = v_definition then raise exception 'documents_corporate_signed_rollback_drift'; end if;
  execute v_restored;
end
$restore_corporate_signed$;

drop policy if exists documents_store_appends_document_audit on public.audit_events;
drop policy if exists documents_store_updates_owner_documents on public.documents;
drop policy if exists documents_store_creates_owner_documents on public.documents;
drop policy if exists documents_store_reads_visible_documents on public.documents;

alter table public.documents no force row level security;
alter table public.documents owner to postgres;

drop function if exists documents.restore_after_storage_failure_v1(uuid,text);
drop function if exists documents.mark_removed_v1(uuid,text,text);
drop function if exists documents.has_evidence_references_v1(uuid);
drop function if exists documents.register_evidence_reference_v1(
  text, text, uuid, uuid, uuid, integer, text, text, text, bigint, uuid
);
drop function if exists documents.assert_registered_artifact_v1(uuid,uuid,integer,text,text,text,text,text,text,bigint,text,uuid);
drop function if exists documents.finalize_upload_v1(uuid,bigint,text,text);
drop function if exists documents.quarantine_upload_v1(uuid,text,text);
drop function if exists documents.list_documents_v1(uuid[],text);
drop function if exists documents.get_document_v1(uuid,text);
drop function if exists documents.stage_upload_v1(jsonb,text);
drop function if exists documents.actor_company_role_v1(uuid);
drop table if exists documents.evidence_references;
drop schema if exists documents;

grant select, insert on public.documents to authenticated;
grant execute on function public.remove_unlinked_document(uuid),
  public.restore_unlinked_document_after_storage_failure(uuid)
to authenticated, service_role;

drop policy if exists "company members can read document metadata" on public.documents;
drop policy if exists "company members can read documents" on public.documents;
create policy "company members can read document metadata" on public.documents for select
to authenticated using (
  case when documents.document_type = 'authority_feedback' then exists (
    select 1 from public.company_memberships membership
    where membership.company_id=documents.company_id
      and membership.user_id=(select auth.uid())
      and membership.role='owner' and membership.accepted_at is not null
  ) else exists (
    select 1 from public.company_memberships membership
    where membership.company_id=documents.company_id
      and membership.user_id=(select auth.uid())
  ) end
);
create policy "owners can create document metadata" on public.documents for insert
to authenticated with check (created_by=(select auth.uid()) and exists (
  select 1 from public.company_memberships membership
  where membership.company_id=documents.company_id and membership.user_id=(select auth.uid())
    and membership.role='owner'
));

create policy "company members can read company document objects" on storage.objects
for select to authenticated using (
  bucket_id='company-documents' and exists (
    select 1 from public.company_memberships membership
    where membership.company_id=((storage.foldername(name))[1])::uuid
      and membership.user_id=(select auth.uid())
  )
);
create policy "owners can upload company document objects" on storage.objects
for insert to authenticated with check (
  bucket_id='company-documents' and exists (
    select 1 from public.company_memberships membership
    where membership.company_id=((storage.foldername(name))[1])::uuid
      and membership.user_id=(select auth.uid()) and membership.role='owner'
  )
);
create policy "owners can delete removed unlinked document objects" on storage.objects
for delete to authenticated using (
  bucket_id='company-documents' and exists (
    select 1 from public.documents document
    join public.company_memberships membership on membership.company_id=document.company_id
    where document.storage_key=storage.objects.name and document.status='removed'
      and document.removed_by=(select auth.uid()) and membership.user_id=(select auth.uid())
      and membership.role='owner' and membership.accepted_at is not null
  )
);

revoke documents_executor from talli_ledger_backend;

do $migration_authority_cleanup$
begin
  execute pg_catalog.format('revoke documents_store_owner from %I', current_user);
end
$migration_authority_cleanup$;

commit;
