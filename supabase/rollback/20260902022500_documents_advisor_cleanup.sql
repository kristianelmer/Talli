-- Restore the exact policy shapes observed immediately after the original
-- Documents cutover. The parent rollback then restores the full predecessor.
begin;

drop policy if exists documents_store_appends_document_audit on public.audit_events;
create policy documents_store_appends_document_audit on public.audit_events
for insert to documents_store_owner
with check (
  actor_id = nullif(pg_catalog.current_setting('talli.verified_actor_id', true), '')::uuid
  and coalesce(
    nullif(pg_catalog.current_setting('talli.authorized_company_roles', true), ''), '{}'
  )::jsonb ->> company_id::text = 'owner'
);

do $owner_authority$
begin
  execute pg_catalog.format(
    'grant documents_store_owner to %I with set true', current_user
  );
end
$owner_authority$;

set local role documents_store_owner;

drop policy if exists documents_store_updates_owner_documents on public.documents;
create policy documents_store_updates_owner_documents on public.documents
for update to documents_store_owner
using (
  coalesce(
    nullif(pg_catalog.current_setting('talli.authorized_company_roles', true), ''), '{}'
  )::jsonb ->> company_id::text = 'owner'
)
with check (
  coalesce(
    nullif(pg_catalog.current_setting('talli.authorized_company_roles', true), ''), '{}'
  )::jsonb ->> company_id::text = 'owner'
);

drop policy if exists documents_store_creates_owner_documents on public.documents;
create policy documents_store_creates_owner_documents on public.documents
for insert to documents_store_owner
with check (
  created_by = nullif(pg_catalog.current_setting('talli.verified_actor_id', true), '')::uuid
  and coalesce(
    nullif(pg_catalog.current_setting('talli.authorized_company_roles', true), ''), '{}'
  )::jsonb ->> company_id::text = 'owner'
);

drop policy if exists documents_store_reads_visible_documents on public.documents;
create policy documents_store_reads_visible_documents on public.documents
for select to documents_store_owner
using (
  coalesce(
    nullif(pg_catalog.current_setting('talli.authorized_company_roles', true), ''), '{}'
  )::jsonb ? company_id::text
);

drop policy if exists "company members can read document metadata" on public.documents;
create policy "company members can read document metadata" on public.documents
for select to authenticated
using (
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

reset role;

do $restore_owner_authority$
begin
  execute pg_catalog.format(
    'grant documents_store_owner to %I with set false', current_user
  );
end
$restore_owner_authority$;

commit;
