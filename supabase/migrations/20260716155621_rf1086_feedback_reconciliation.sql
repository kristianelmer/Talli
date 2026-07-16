-- Durable RF-1086 feedback reconciliation and private authority artifacts.

alter table public.production_filing_submissions
  add column if not exists feedback_state text not null default 'sent'
  check (feedback_state in ('sent', 'processing', 'accepted', 'rejected', 'action_required', 'unknown')),
  add column if not exists feedback_forsendelse_id uuid,
  add column if not exists feedback_artifact_count integer not null default 0 check (feedback_artifact_count >= 0),
  add column if not exists feedback_last_checked_at timestamptz,
  add column if not exists feedback_last_changed_at timestamptz,
  add column if not exists feedback_safe_error_code text
    check (feedback_safe_error_code is null or feedback_safe_error_code ~ '^[A-Z0-9_]{1,100}$'),
  add column if not exists feedback_correlation_id text
    check (feedback_correlation_id is null or feedback_correlation_id ~ '^[A-Za-z0-9._:-]{1,200}$'),
  add column if not exists feedback_reconciliation_lease_id uuid,
  add column if not exists feedback_reconciliation_started_at timestamptz;

update public.production_filing_submissions
set feedback_state = case
  when status in ('accepted', 'rejected', 'action_required', 'unknown', 'processing') then status
  else 'sent'
end;

create or replace function public.rf1086_confirmation_forsendelse_id(p_reference text)
returns uuid
language plpgsql
immutable
set search_path = ''
as $$
declare
  v_confirmation jsonb;
begin
  if p_reference is null then
    return null;
  end if;
  begin
    v_confirmation := p_reference::jsonb;
  exception when invalid_text_representation then
    return null;
  end;
  if pg_catalog.jsonb_typeof(v_confirmation) is distinct from 'object' then
    return null;
  end if;
  if (select pg_catalog.count(*) from pg_catalog.jsonb_object_keys(v_confirmation)) <> 2
    or not (v_confirmation ?& array['dialogId', 'forsendelseId'])
    or pg_catalog.jsonb_typeof(v_confirmation -> 'dialogId') is distinct from 'string'
    or pg_catalog.jsonb_typeof(v_confirmation -> 'forsendelseId') is distinct from 'string'
    or v_confirmation ->> 'dialogId'
      !~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
    or v_confirmation ->> 'forsendelseId'
      !~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
  then
    return null;
  end if;
  return (v_confirmation ->> 'forsendelseId')::uuid;
end;
$$;

revoke all on function public.rf1086_confirmation_forsendelse_id(text)
  from public, anon, authenticated, service_role;

-- Recover submissions confirmed before this migration. Only the latest immutable,
-- succeeded confirmation event and the exact journal JSON shape may become authoritative.
with latest_succeeded_confirm as (
  select distinct on (e.submission_id)
    e.submission_id,
    e.authority_reference
  from public.production_filing_events e
  where e.operation_name = 'confirm'
    and e.operation_state = 'succeeded'
  order by e.submission_id, e.created_at desc, e.id desc
), validated_confirmation as (
  select
    c.submission_id,
    public.rf1086_confirmation_forsendelse_id(c.authority_reference) as forsendelse_id
  from latest_succeeded_confirm c
)
update public.production_filing_submissions s
set feedback_forsendelse_id = v.forsendelse_id
from validated_confirmation v
where s.id = v.submission_id
  and s.feedback_forsendelse_id is null
  and v.forsendelse_id is not null;

create index if not exists production_filing_submissions_feedback_pending_idx
on public.production_filing_submissions (feedback_state, updated_at)
where feedback_state in ('sent', 'processing', 'unknown');

alter table public.production_filing_events
  add column if not exists artifact_hashes text[] not null default '{}'::text[],
  add column if not exists safe_error_code text
    check (safe_error_code is null or safe_error_code ~ '^[A-Z0-9_]{1,100}$'),
  add column if not exists correlation_id text
    check (correlation_id is null or correlation_id ~ '^[A-Za-z0-9._:-]{1,200}$');

create table if not exists public.production_feedback_artifacts (
  id uuid primary key default gen_random_uuid(),
  company_id uuid not null references public.companies(id) on delete cascade,
  submission_id uuid not null references public.production_filing_submissions(id) on delete cascade,
  document_id uuid not null references public.documents(id) on delete restrict,
  authority_reference text not null check (length(trim(authority_reference)) between 1 and 500),
  content_type text not null check (content_type in ('application/xml','text/xml','application/pdf','text/plain','application/octet-stream')),
  byte_length bigint not null check (byte_length between 1 and 10485760),
  sha256 text not null check (sha256 ~ '^[a-f0-9]{64}$'),
  retrieved_at timestamptz not null default now(),
  classification text not null check (classification in ('accepted','rejected','action_required')),
  unique (submission_id, sha256),
  unique (document_id)
);

create index if not exists production_feedback_artifacts_company_idx
on public.production_feedback_artifacts (company_id, retrieved_at desc, id);
create index if not exists production_feedback_artifacts_submission_idx
on public.production_feedback_artifacts (submission_id, retrieved_at, id);

alter table public.production_feedback_artifacts enable row level security;

revoke all on table public.production_feedback_artifacts from public, anon, authenticated, service_role;
grant select on table public.production_feedback_artifacts to authenticated, service_role;

-- Authority feedback is private to accepted owners and active operators. Keep the
-- pre-existing membership behavior unchanged for every other document type.
drop policy if exists "company members can read document metadata" on public.documents;
create policy "company members can read document metadata"
on public.documents for select
to authenticated
using (
  case
    when documents.document_type = 'authority_feedback' then
      exists (
        select 1
        from public.company_memberships m
        where m.company_id = documents.company_id
          and m.user_id = (select auth.uid())
          and m.role = 'owner'
          and m.accepted_at is not null
      )
      or exists (
        select 1
        from public.support_operators o
        where o.user_id = (select auth.uid())
          and o.active
      )
    else
      exists (
        select 1
        from public.company_memberships m
        where m.company_id = documents.company_id
          and m.user_id = (select auth.uid())
      )
  end
);

drop policy if exists production_feedback_artifacts_owner_read on public.production_feedback_artifacts;
create policy production_feedback_artifacts_owner_read
on public.production_feedback_artifacts for select to authenticated
using (exists (
  select 1
  from public.company_memberships m
  where m.company_id = production_feedback_artifacts.company_id
    and m.user_id = (select auth.uid())
    and m.role = 'owner'
    and m.accepted_at is not null
));

drop policy if exists production_feedback_artifacts_operator_read on public.production_feedback_artifacts;
create policy production_feedback_artifacts_operator_read
on public.production_feedback_artifacts for select to authenticated
using (exists (
  select 1
  from public.support_operators o
  where o.user_id = (select auth.uid())
    and o.active
));

-- Keep the existing bucket private while allowing the feedback content types.
update storage.buckets
set public = false,
    file_size_limit = 10485760,
    allowed_mime_types = array[
      'application/pdf', 'image/png', 'image/jpeg', 'text/csv',
      'application/xml', 'text/xml', 'text/plain', 'application/octet-stream'
    ]
where id = 'company-documents';

drop policy if exists "company members can read company document objects" on storage.objects;
create policy "company members can read company document objects"
on storage.objects for select
to authenticated
using (
  bucket_id = 'company-documents'
  and (
    (
      (storage.foldername(name))[1] = 'authority-feedback'
      and (
        exists (
          select 1
          from public.company_memberships m
          where m.company_id::text = (storage.foldername(name))[2]
            and m.user_id = (select auth.uid())
            and m.role = 'owner'
            and m.accepted_at is not null
        )
        or exists (
          select 1
          from public.support_operators o
          where o.user_id = (select auth.uid())
            and o.active
        )
      )
    )
    or (
      (storage.foldername(name))[1] <> 'authority-feedback'
      and exists (
        select 1
        from public.company_memberships m
        where m.company_id::text = (storage.foldername(name))[1]
          and m.user_id = (select auth.uid())
      )
    )
  )
  and not exists (
    select 1
    from public.documents d
    where d.storage_key = storage.objects.name
      and d.status = 'removed'
  )
);

create or replace function public.record_production_feedback_artifact(
  p_company_id uuid,
  p_submission_id uuid,
  p_document_id uuid,
  p_authority_reference text,
  p_content_type text,
  p_byte_length bigint,
  p_sha256 text,
  p_classification text
)
returns public.production_feedback_artifacts
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_submission public.production_filing_submissions%rowtype;
  v_document public.documents%rowtype;
  v_artifact public.production_feedback_artifacts%rowtype;
  v_expected_storage_key text;
begin
  if coalesce((select auth.jwt()) ->> 'role', '') <> 'service_role' then
    raise exception 'production_feedback_service_role_required';
  end if;
  if p_sha256 !~ '^[a-f0-9]{64}$'
    or p_byte_length not between 1 and 10485760
    or p_content_type not in ('application/xml','text/xml','application/pdf','text/plain','application/octet-stream')
    or p_classification not in ('accepted','rejected','action_required')
    or length(trim(coalesce(p_authority_reference, ''))) not between 1 and 500
  then
    raise exception 'production_feedback_metadata_invalid';
  end if;

  select s.*
  into v_submission
  from public.production_filing_submissions s
  where s.id = p_submission_id
    and s.company_id = p_company_id
    and s.obligation = 'aksjonaerregisteroppgaven'
    and s.environment = 'production'
  for update;
  if v_submission.id is null then
    raise exception 'production_feedback_submission_relationship_mismatch';
  end if;

  v_expected_storage_key := format(
    'authority-feedback/%s/%s/%s',
    p_company_id,
    p_submission_id,
    p_sha256
  );
  select d.*
  into v_document
  from public.documents d
  where d.id = p_document_id
    and d.company_id = p_company_id
    and d.income_year = v_submission.income_year
    and d.document_type = 'authority_feedback'
    and d.linked_to = 'production_filing_submission:' || p_submission_id::text
    and d.status = 'attached'
    and d.storage_key = v_expected_storage_key
    and d.created_by = v_submission.user_id
    and d.name ~ '^authority-feedback-[a-f0-9]{12}\.(xml|pdf|txt|bin)$';
  if v_document.id is null then
    raise exception 'production_feedback_document_relationship_mismatch';
  end if;

  insert into public.production_feedback_artifacts (
    company_id, submission_id, document_id, authority_reference,
    content_type, byte_length, sha256, classification
  ) values (
    p_company_id, p_submission_id, p_document_id, trim(p_authority_reference),
    p_content_type, p_byte_length, p_sha256, p_classification
  )
  on conflict (submission_id, sha256) do nothing
  returning * into v_artifact;

  if v_artifact.id is null then
    select a.*
    into v_artifact
    from public.production_feedback_artifacts a
    where a.submission_id = p_submission_id
      and a.sha256 = p_sha256;
  end if;
  return v_artifact;
end;
$$;

create or replace function public.claim_production_feedback_reconciliation(
  p_submission_id uuid,
  p_lease_id uuid
)
returns boolean
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_submission public.production_filing_submissions%rowtype;
  v_authority_reference text;
  v_forsendelse_id uuid;
begin
  if coalesce((select auth.jwt()) ->> 'role', '') <> 'service_role'
    or p_lease_id is null
  then
    raise exception 'production_feedback_service_role_required';
  end if;

  select s.*
  into v_submission
  from public.production_filing_submissions s
  where s.id = p_submission_id
  for update;
  if v_submission.id is null
    or v_submission.obligation <> 'aksjonaerregisteroppgaven'
    or v_submission.environment <> 'production'
  then
    raise exception 'production_feedback_submission_relationship_mismatch';
  end if;
  if v_submission.feedback_state not in ('sent', 'processing', 'unknown') then
    return false;
  end if;

  select e.authority_reference
  into v_authority_reference
  from public.production_filing_events e
  where e.submission_id = p_submission_id
    and e.operation_name = 'confirm'
    and e.operation_state = 'succeeded'
  order by e.created_at desc, e.id desc
  limit 1;
  v_forsendelse_id := public.rf1086_confirmation_forsendelse_id(v_authority_reference);
  if v_forsendelse_id is null then
    raise exception 'production_feedback_confirmation_reference_invalid';
  end if;

  if v_submission.feedback_forsendelse_id is not null
    and v_submission.feedback_forsendelse_id is distinct from v_forsendelse_id
  then
    raise exception 'production_feedback_confirmation_relationship_mismatch';
  end if;
  if v_submission.feedback_reconciliation_lease_id is not null
    and (
      v_submission.feedback_reconciliation_started_at is null
      or v_submission.feedback_reconciliation_started_at >= pg_catalog.now() - interval '5 minutes'
    )
  then
    return false;
  end if;

  update public.production_filing_submissions
  set feedback_forsendelse_id = v_forsendelse_id,
      feedback_reconciliation_lease_id = p_lease_id,
      feedback_reconciliation_started_at = pg_catalog.now()
  where id = p_submission_id;
  return true;
end;
$$;

create or replace function public.release_production_feedback_reconciliation(
  p_submission_id uuid,
  p_lease_id uuid
)
returns boolean
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_released boolean := false;
begin
  if coalesce((select auth.jwt()) ->> 'role', '') <> 'service_role'
    or p_lease_id is null
  then
    raise exception 'production_feedback_service_role_required';
  end if;
  update public.production_filing_submissions s
  set feedback_reconciliation_lease_id = null,
      feedback_reconciliation_started_at = null
  where s.id = p_submission_id
    and s.feedback_reconciliation_lease_id = p_lease_id
  returning true into v_released;
  return coalesce(v_released, false);
end;
$$;

create or replace function public.append_production_feedback_reconciliation(
  p_submission_id uuid,
  p_lease_id uuid,
  p_forsendelse_id uuid,
  p_state text,
  p_artifact_hashes text[],
  p_safe_error_code text,
  p_correlation_id text
)
returns boolean
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_submission public.production_filing_submissions%rowtype;
  v_previous public.production_filing_events%rowtype;
  v_hashes text[];
  v_persisted_hashes text[];
  v_resulting_status text;
begin
  if coalesce((select auth.jwt()) ->> 'role', '') <> 'service_role' then
    raise exception 'production_feedback_service_role_required';
  end if;
  if p_state not in ('sent', 'processing', 'accepted', 'rejected', 'action_required', 'unknown')
    or p_lease_id is null
    or p_forsendelse_id is null
    or (p_safe_error_code is not null and p_safe_error_code !~ '^[A-Z0-9_]{1,100}$')
    or (p_correlation_id is not null and p_correlation_id !~ '^[A-Za-z0-9._:-]{1,200}$')
    or exists (
      select 1 from unnest(coalesce(p_artifact_hashes, '{}'::text[])) h
      where h !~ '^[a-f0-9]{64}$'
    )
  then
    raise exception 'production_feedback_reconciliation_invalid';
  end if;

  select s.*
  into v_submission
  from public.production_filing_submissions s
  where s.id = p_submission_id
  for update;
  if v_submission.id is null
    or v_submission.feedback_reconciliation_lease_id is distinct from p_lease_id
    or (
      v_submission.feedback_forsendelse_id is not null
      and v_submission.feedback_forsendelse_id <> p_forsendelse_id
    )
  then
    raise exception 'production_feedback_reconciliation_relationship_mismatch';
  end if;
  if v_submission.feedback_state in ('accepted', 'rejected', 'action_required')
    and p_state <> v_submission.feedback_state
  then
    raise exception 'production_feedback_reconciliation_terminal';
  end if;

  select coalesce(array_agg(distinct h order by h), '{}'::text[])
  into v_hashes
  from unnest(coalesce(p_artifact_hashes, '{}'::text[])) h;
  select coalesce(array_agg(a.sha256 order by a.sha256), '{}'::text[])
  into v_persisted_hashes
  from public.production_feedback_artifacts a
  where a.submission_id = p_submission_id;
  if v_hashes <> v_persisted_hashes then
    raise exception 'production_feedback_artifact_set_mismatch';
  end if;
  if p_state = 'accepted' and (
    cardinality(v_hashes) = 0
    or exists (
      select 1 from public.production_feedback_artifacts a
      where a.submission_id = p_submission_id and a.classification <> 'accepted'
    )
  ) then
    raise exception 'production_feedback_acceptance_evidence_required';
  end if;
  if p_state = 'rejected' and (
    cardinality(v_hashes) = 0
    or exists (
      select 1 from public.production_feedback_artifacts a
      where a.submission_id = p_submission_id and a.classification <> 'rejected'
    )
  ) then
    raise exception 'production_feedback_rejection_evidence_required';
  end if;

  select e.*
  into v_previous
  from public.production_filing_events e
  where e.submission_id = p_submission_id
    and e.operation_name like 'reconciliation:%'
  order by e.created_at desc, e.id desc
  limit 1;

  v_resulting_status := case when p_state = 'sent' then 'received' else p_state end;
  if v_previous.id is not null
    and v_previous.resulting_status = v_resulting_status
    and v_previous.artifact_hashes = v_hashes
  then
    update public.production_filing_submissions
    set feedback_last_checked_at = pg_catalog.now(),
        feedback_safe_error_code = p_safe_error_code,
        feedback_correlation_id = p_correlation_id,
        updated_at = pg_catalog.now()
    where id = p_submission_id;
    return false;
  end if;

  insert into public.production_filing_events (
    submission_id, operation_name, operation_state, attempt, body_hash,
    idempotency_key, authority_reference, failure_class, resulting_status,
    artifact_hashes, safe_error_code, correlation_id
  ) values (
    p_submission_id,
    'reconciliation:' || pg_catalog.gen_random_uuid()::text,
    case when p_state = 'unknown' then 'unknown' else 'succeeded' end,
    1, null, null, null,
    case when p_state = 'unknown' then 'unknown' else null end,
    v_resulting_status,
    v_hashes, p_safe_error_code, p_correlation_id
  );

  update public.production_filing_submissions
  set status = v_resulting_status,
      feedback_state = p_state,
      feedback_forsendelse_id = coalesce(feedback_forsendelse_id, p_forsendelse_id),
      feedback_artifact_count = cardinality(v_hashes),
      feedback_last_checked_at = pg_catalog.now(),
      feedback_last_changed_at = pg_catalog.now(),
      feedback_safe_error_code = p_safe_error_code,
      feedback_correlation_id = p_correlation_id,
      updated_at = pg_catalog.now()
  where id = p_submission_id;
  return true;
end;
$$;

revoke all on function public.record_production_feedback_artifact(uuid, uuid, uuid, text, text, bigint, text, text)
  from public, anon, authenticated, service_role;
revoke all on function public.claim_production_feedback_reconciliation(uuid, uuid)
  from public, anon, authenticated, service_role;
revoke all on function public.release_production_feedback_reconciliation(uuid, uuid)
  from public, anon, authenticated, service_role;
revoke all on function public.append_production_feedback_reconciliation(uuid, uuid, uuid, text, text[], text, text)
  from public, anon, authenticated, service_role;

grant execute on function public.record_production_feedback_artifact(uuid, uuid, uuid, text, text, bigint, text, text)
  to service_role;
grant execute on function public.claim_production_feedback_reconciliation(uuid, uuid)
  to service_role;
grant execute on function public.release_production_feedback_reconciliation(uuid, uuid)
  to service_role;
grant execute on function public.append_production_feedback_reconciliation(uuid, uuid, uuid, text, text[], text, text)
  to service_role;
