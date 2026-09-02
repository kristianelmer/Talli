-- Remove historical browser metadata access left by an earlier policy-name
-- variant and make the request-local RLS settings init-plan constants (#147).
begin;

do $owner_authority$
begin
  execute pg_catalog.format(
    'grant documents_store_owner to %I with set true', current_user
  );
end
$owner_authority$;

set local role documents_store_owner;

drop policy if exists "company members can read document metadata" on public.documents;

drop policy if exists documents_store_reads_visible_documents on public.documents;
create policy documents_store_reads_visible_documents on public.documents
for select to documents_store_owner
using (
  coalesce(
    nullif((select pg_catalog.current_setting('talli.authorized_company_roles', true)), ''),
    '{}'
  )::jsonb ? company_id::text
);

drop policy if exists documents_store_creates_owner_documents on public.documents;
create policy documents_store_creates_owner_documents on public.documents
for insert to documents_store_owner
with check (
  created_by = nullif(
    (select pg_catalog.current_setting('talli.verified_actor_id', true)), ''
  )::uuid
  and coalesce(
    nullif((select pg_catalog.current_setting('talli.authorized_company_roles', true)), ''),
    '{}'
  )::jsonb ->> company_id::text = 'owner'
);

drop policy if exists documents_store_updates_owner_documents on public.documents;
create policy documents_store_updates_owner_documents on public.documents
for update to documents_store_owner
using (
  coalesce(
    nullif((select pg_catalog.current_setting('talli.authorized_company_roles', true)), ''),
    '{}'
  )::jsonb ->> company_id::text = 'owner'
)
with check (
  coalesce(
    nullif((select pg_catalog.current_setting('talli.authorized_company_roles', true)), ''),
    '{}'
  )::jsonb ->> company_id::text = 'owner'
);

reset role;

drop policy if exists documents_store_appends_document_audit on public.audit_events;
create policy documents_store_appends_document_audit on public.audit_events
for insert to documents_store_owner
with check (
  actor_id = nullif(
    (select pg_catalog.current_setting('talli.verified_actor_id', true)), ''
  )::uuid
  and coalesce(
    nullif((select pg_catalog.current_setting('talli.authorized_company_roles', true)), ''),
    '{}'
  )::jsonb ->> company_id::text = 'owner'
);

do $restore_owner_authority$
begin
  execute pg_catalog.format(
    'grant documents_store_owner to %I with set false', current_user
  );
end
$restore_owner_authority$;

commit;
