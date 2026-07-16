-- Roll back only durable RF-1086 feedback reconciliation objects.

revoke all on function public.append_production_feedback_reconciliation(uuid, uuid, uuid, text, text[], text, text)
  from public, anon, authenticated, service_role;
revoke all on function public.release_production_feedback_reconciliation(uuid, uuid)
  from public, anon, authenticated, service_role;
revoke all on function public.claim_production_feedback_reconciliation(uuid, uuid)
  from public, anon, authenticated, service_role;
revoke all on function public.record_production_feedback_artifact(uuid, uuid, uuid, text, text, bigint, text, text)
  from public, anon, authenticated, service_role;

drop function if exists public.append_production_feedback_reconciliation(uuid, uuid, uuid, text, text[], text, text);
drop function if exists public.release_production_feedback_reconciliation(uuid, uuid);
drop function if exists public.claim_production_feedback_reconciliation(uuid, uuid);
drop function if exists public.record_production_feedback_artifact(uuid, uuid, uuid, text, text, bigint, text, text);

revoke all on table public.production_feedback_artifacts from public, anon, authenticated, service_role;
drop policy if exists production_feedback_artifacts_operator_read on public.production_feedback_artifacts;
drop policy if exists production_feedback_artifacts_owner_read on public.production_feedback_artifacts;
drop table if exists public.production_feedback_artifacts;

drop policy if exists "company members can read company document objects" on storage.objects;
create policy "company members can read company document objects"
on storage.objects for select
to authenticated
using (
  bucket_id = 'company-documents'
  and exists (
    select 1
    from public.company_memberships m
    where m.company_id = ((storage.foldername(name))[1])::uuid
      and m.user_id = (select auth.uid())
  )
  and not exists (
    select 1
    from public.documents d
    where d.storage_key = storage.objects.name
      and d.status = 'removed'
  )
);

update storage.buckets
set public = false,
    file_size_limit = 10485760,
    allowed_mime_types = array['application/pdf', 'image/png', 'image/jpeg', 'text/csv']
where id = 'company-documents';

alter table public.production_filing_events
  drop column if exists correlation_id,
  drop column if exists safe_error_code,
  drop column if exists artifact_hashes;

drop index if exists public.production_filing_submissions_feedback_pending_idx;
alter table public.production_filing_submissions
  drop column if exists feedback_reconciliation_started_at,
  drop column if exists feedback_reconciliation_lease_id,
  drop column if exists feedback_correlation_id,
  drop column if exists feedback_safe_error_code,
  drop column if exists feedback_last_changed_at,
  drop column if exists feedback_last_checked_at,
  drop column if exists feedback_artifact_count,
  drop column if exists feedback_forsendelse_id,
  drop column if exists feedback_state;
