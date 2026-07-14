alter table public.filing_submissions
  add column if not exists authority_test_run_id uuid;

do $$
begin
  if not exists (
    select 1
    from pg_constraint
    where conrelid = 'public.filing_submissions'::regclass
      and conname = 'filing_submissions_authority_test_run_id_fkey'
  ) then
    alter table public.filing_submissions
      add constraint filing_submissions_authority_test_run_id_fkey
      foreign key (authority_test_run_id)
      references public.authority_test_runs(id)
      on delete restrict;
  end if;
end;
$$;

alter table public.filing_submissions
  alter column preview_id drop not null;

alter table public.filing_submissions
  drop constraint if exists filing_submissions_mode_check,
  drop constraint if exists filing_submissions_adapter_mode_check,
  drop constraint if exists filing_submissions_authority_mode_shape_check;

alter table public.filing_submissions
  add constraint filing_submissions_mode_check
    check (mode in ('simulation', 'test_authority')),
  add constraint filing_submissions_adapter_mode_check
    check (adapter_mode in ('simulation', 'test_authority', 'production')),
  add constraint filing_submissions_authority_mode_shape_check
    check (
      (
        mode = 'simulation'
        and preview_id is not null
        and authority_test_run_id is null
      )
      or (
        mode = 'test_authority'
        and preview_id is null
        and authority_test_run_id is not null
      )
    );

create unique index if not exists filing_submissions_authority_test_run_id_key
on public.filing_submissions (authority_test_run_id);

create unique index if not exists authority_test_runs_evidence_identity_key
on public.authority_test_runs (company_id, obligation, environment, test_reference);

drop policy if exists "owners can create filing submissions" on public.filing_submissions;
create policy "owners can create filing submissions"
on public.filing_submissions for insert
to authenticated
with check (
  created_by = (select auth.uid())
  and mode = 'simulation'
  and exists (
    select 1
    from public.company_memberships m
    where m.company_id = filing_submissions.company_id
      and m.user_id = (select auth.uid())
      and m.role = 'owner'
  )
);

drop policy if exists "owners can update filing submissions" on public.filing_submissions;
create policy "owners can update filing submissions"
on public.filing_submissions for update
to authenticated
using (
  created_by = (select auth.uid())
  and mode = 'simulation'
  and exists (
    select 1
    from public.company_memberships m
    where m.company_id = filing_submissions.company_id
      and m.user_id = (select auth.uid())
      and m.role = 'owner'
  )
)
with check (
  created_by = (select auth.uid())
  and mode = 'simulation'
  and exists (
    select 1
    from public.company_memberships m
    where m.company_id = filing_submissions.company_id
      and m.user_id = (select auth.uid())
      and m.role = 'owner'
  )
);

create or replace function public.import_company_tax_tt02_evidence(p_payload jsonb)
returns jsonb
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
  v_actor_id uuid := auth.uid();
  v_authority_payload jsonb;
  v_submission_payload jsonb;
  v_authority public.authority_test_runs%rowtype;
  v_submission public.filing_submissions%rowtype;
  v_persisted_authority public.authority_test_runs%rowtype;
  v_persisted_submission public.filing_submissions%rowtype;
  v_expected_archive_reference text;
  v_company_org_number text;
  v_reference_income_year integer;
  v_recomputed_payload_hash text;
  v_call jsonb;
  v_call_index integer;
  v_created boolean := false;
begin
  if v_actor_id is null then
    raise exception 'company_tax_evidence_authentication_required';
  end if;

  if (select auth.jwt() ->> 'aal') is distinct from 'aal2' then
    raise exception 'company_tax_evidence_mfa_required';
  end if;

  if p_payload is null
    or jsonb_typeof(p_payload) is distinct from 'object'
    or not (p_payload ?& array['authorityRun', 'submission'])
    or p_payload - array['authorityRun', 'submission'] is distinct from '{}'::jsonb
    or jsonb_typeof(p_payload -> 'authorityRun') is distinct from 'object'
    or jsonb_typeof(p_payload -> 'submission') is distinct from 'object' then
    raise exception 'company_tax_evidence_invalid_payload';
  end if;

  v_authority_payload := p_payload -> 'authorityRun';
  v_submission_payload := p_payload -> 'submission';
  if not (v_authority_payload ?& array[
      'company_id', 'obligation', 'environment', 'status', 'test_reference',
      'feedback_summary', 'receipt_reference', 'archive_reference', 'evidence_url',
      'payload_hash', 'recorded_by', 'recorded_at'
    ])
    or v_authority_payload - array[
      'company_id', 'obligation', 'environment', 'status', 'test_reference',
      'feedback_summary', 'receipt_reference', 'archive_reference', 'evidence_url',
      'payload_hash', 'recorded_by', 'recorded_at'
    ] is distinct from '{}'::jsonb
    or not (v_submission_payload ?& array[
      'company_id', 'income_year', 'filing', 'mode', 'adapter_mode', 'payload_hash',
      'idempotency_key', 'status', 'calls', 'receipt_id', 'feedback_document_ids',
      'feedback_items', 'receipt_metadata', 'submitted_payload_ref', 'submitted_payload',
      'failure_code', 'failure_message', 'created_by', 'submitted_by', 'updated_at'
    ])
    or v_submission_payload - array[
      'company_id', 'income_year', 'filing', 'mode', 'adapter_mode', 'payload_hash',
      'idempotency_key', 'status', 'calls', 'receipt_id', 'feedback_document_ids',
      'feedback_items', 'receipt_metadata', 'submitted_payload_ref', 'submitted_payload',
      'failure_code', 'failure_message', 'created_by', 'submitted_by', 'updated_at'
    ] is distinct from '{}'::jsonb then
    raise exception 'company_tax_evidence_invalid_payload';
  end if;

  if octet_length(p_payload::text) > 32768
    or p_payload::text ~* '<[^>]+>'
    or p_payload::text ~* '(raw_xml_sentinel|party_number_sentinel|access_token_sentinel|private_key_sentinel|personal_identifier_sentinel)' then
    raise exception 'company_tax_evidence_forbidden_content';
  end if;

  if jsonb_typeof(v_authority_payload -> 'company_id') is distinct from 'string'
    or jsonb_typeof(v_authority_payload -> 'obligation') is distinct from 'string'
    or jsonb_typeof(v_authority_payload -> 'environment') is distinct from 'string'
    or jsonb_typeof(v_authority_payload -> 'status') is distinct from 'string'
    or jsonb_typeof(v_authority_payload -> 'test_reference') is distinct from 'string'
    or jsonb_typeof(v_authority_payload -> 'feedback_summary') is distinct from 'string'
    or jsonb_typeof(v_authority_payload -> 'receipt_reference') is distinct from 'string'
    or jsonb_typeof(v_authority_payload -> 'archive_reference') is distinct from 'string'
    or jsonb_typeof(v_authority_payload -> 'evidence_url') not in ('string', 'null')
    or jsonb_typeof(v_authority_payload -> 'payload_hash') is distinct from 'string'
    or jsonb_typeof(v_authority_payload -> 'recorded_by') is distinct from 'string'
    or jsonb_typeof(v_authority_payload -> 'recorded_at') is distinct from 'string'
    or jsonb_typeof(v_submission_payload -> 'company_id') is distinct from 'string'
    or jsonb_typeof(v_submission_payload -> 'income_year') is distinct from 'number'
    or jsonb_typeof(v_submission_payload -> 'filing') is distinct from 'string'
    or jsonb_typeof(v_submission_payload -> 'mode') is distinct from 'string'
    or jsonb_typeof(v_submission_payload -> 'adapter_mode') is distinct from 'string'
    or jsonb_typeof(v_submission_payload -> 'payload_hash') is distinct from 'string'
    or jsonb_typeof(v_submission_payload -> 'idempotency_key') is distinct from 'string'
    or jsonb_typeof(v_submission_payload -> 'status') is distinct from 'string'
    or jsonb_typeof(v_submission_payload -> 'calls') is distinct from 'array'
    or jsonb_typeof(v_submission_payload -> 'receipt_id') is distinct from 'string'
    or jsonb_typeof(v_submission_payload -> 'feedback_document_ids') is distinct from 'array'
    or jsonb_typeof(v_submission_payload -> 'feedback_items') is distinct from 'array'
    or jsonb_typeof(v_submission_payload -> 'receipt_metadata') is distinct from 'object'
    or jsonb_typeof(v_submission_payload -> 'submitted_payload_ref') is distinct from 'object'
    or jsonb_typeof(v_submission_payload -> 'submitted_payload') is distinct from 'null'
    or jsonb_typeof(v_submission_payload -> 'failure_code') is distinct from 'null'
    or jsonb_typeof(v_submission_payload -> 'failure_message') is distinct from 'null'
    or jsonb_typeof(v_submission_payload -> 'created_by') is distinct from 'string'
    or jsonb_typeof(v_submission_payload -> 'submitted_by') is distinct from 'null'
    or jsonb_typeof(v_submission_payload -> 'updated_at') is distinct from 'string' then
    raise exception 'company_tax_evidence_invalid_payload';
  end if;

  if jsonb_array_length(v_submission_payload -> 'calls') <> 3
    or jsonb_array_length(v_submission_payload -> 'feedback_document_ids') <> 1
    or jsonb_array_length(v_submission_payload -> 'feedback_items') <> 1
    or (v_submission_payload -> 'income_year')::text !~ '^[0-9]+$'
    or (v_submission_payload -> 'receipt_metadata' -> 'byteLength')::text !~ '^[0-9]+$'
    or (v_submission_payload -> 'submitted_payload_ref' -> 'incomeYear')::text !~ '^[0-9]+$'
    or jsonb_typeof(v_submission_payload -> 'feedback_items' -> 0) is distinct from 'object'
    or not ((v_submission_payload -> 'feedback_items' -> 0) ?& array[
      'severity', 'code', 'message', 'documentId'
    ])
    or (v_submission_payload -> 'feedback_items' -> 0) - array[
      'severity', 'code', 'message', 'documentId'
    ] is distinct from '{}'::jsonb
    or jsonb_typeof(v_submission_payload -> 'feedback_items' -> 0 -> 'severity') is distinct from 'string'
    or jsonb_typeof(v_submission_payload -> 'feedback_items' -> 0 -> 'code') is distinct from 'string'
    or jsonb_typeof(v_submission_payload -> 'feedback_items' -> 0 -> 'message') is distinct from 'string'
    or jsonb_typeof(v_submission_payload -> 'feedback_items' -> 0 -> 'documentId') is distinct from 'string'
    or not (v_submission_payload -> 'receipt_metadata' ?& array[
      'authority', 'receiptId', 'status', 'receivedAt', 'feedbackDocumentIds',
      'dataType', 'contentType', 'byteLength', 'contentSha256', 'reference',
      'archiveReference', 'processEndedAt', 'archivedAt'
    ])
    or (v_submission_payload -> 'receipt_metadata') - array[
      'authority', 'receiptId', 'status', 'receivedAt', 'feedbackDocumentIds',
      'dataType', 'contentType', 'byteLength', 'contentSha256', 'reference',
      'archiveReference', 'processEndedAt', 'archivedAt'
    ] is distinct from '{}'::jsonb
    or jsonb_typeof(v_submission_payload -> 'receipt_metadata' -> 'authority') is distinct from 'string'
    or jsonb_typeof(v_submission_payload -> 'receipt_metadata' -> 'receiptId') is distinct from 'string'
    or jsonb_typeof(v_submission_payload -> 'receipt_metadata' -> 'status') is distinct from 'string'
    or jsonb_typeof(v_submission_payload -> 'receipt_metadata' -> 'receivedAt') is distinct from 'string'
    or jsonb_typeof(v_submission_payload -> 'receipt_metadata' -> 'feedbackDocumentIds') is distinct from 'array'
    or jsonb_typeof(v_submission_payload -> 'receipt_metadata' -> 'dataType') is distinct from 'string'
    or jsonb_typeof(v_submission_payload -> 'receipt_metadata' -> 'contentType') is distinct from 'string'
    or jsonb_typeof(v_submission_payload -> 'receipt_metadata' -> 'byteLength') is distinct from 'number'
    or jsonb_typeof(v_submission_payload -> 'receipt_metadata' -> 'contentSha256') is distinct from 'string'
    or jsonb_typeof(v_submission_payload -> 'receipt_metadata' -> 'reference') is distinct from 'string'
    or jsonb_typeof(v_submission_payload -> 'receipt_metadata' -> 'archiveReference') is distinct from 'string'
    or jsonb_typeof(v_submission_payload -> 'receipt_metadata' -> 'processEndedAt') is distinct from 'string'
    or jsonb_typeof(v_submission_payload -> 'receipt_metadata' -> 'archivedAt') is distinct from 'string'
    or not (v_submission_payload -> 'submitted_payload_ref' ?& array[
      'companyOrgNumber', 'incomeYear', 'envelopeDataId', 'archiveReference',
      'payloadHash', 'skattemeldingHash', 'naeringsspesifikasjonHash',
      'validationEnvelopeHash', 'submissionEnvelopeHash',
      'currentDocumentReferenceHash', 'storedAt'
    ])
    or (v_submission_payload -> 'submitted_payload_ref') - array[
      'companyOrgNumber', 'incomeYear', 'envelopeDataId', 'archiveReference',
      'payloadHash', 'skattemeldingHash', 'naeringsspesifikasjonHash',
      'validationEnvelopeHash', 'submissionEnvelopeHash',
      'currentDocumentReferenceHash', 'storedAt'
    ] is distinct from '{}'::jsonb
    or jsonb_typeof(v_submission_payload -> 'submitted_payload_ref' -> 'companyOrgNumber') is distinct from 'string'
    or jsonb_typeof(v_submission_payload -> 'submitted_payload_ref' -> 'incomeYear') is distinct from 'number'
    or jsonb_typeof(v_submission_payload -> 'submitted_payload_ref' -> 'envelopeDataId') is distinct from 'string'
    or jsonb_typeof(v_submission_payload -> 'submitted_payload_ref' -> 'archiveReference') is distinct from 'string'
    or jsonb_typeof(v_submission_payload -> 'submitted_payload_ref' -> 'payloadHash') is distinct from 'string'
    or jsonb_typeof(v_submission_payload -> 'submitted_payload_ref' -> 'skattemeldingHash') is distinct from 'string'
    or jsonb_typeof(v_submission_payload -> 'submitted_payload_ref' -> 'naeringsspesifikasjonHash') is distinct from 'string'
    or jsonb_typeof(v_submission_payload -> 'submitted_payload_ref' -> 'validationEnvelopeHash') is distinct from 'string'
    or jsonb_typeof(v_submission_payload -> 'submitted_payload_ref' -> 'submissionEnvelopeHash') is distinct from 'string'
    or jsonb_typeof(v_submission_payload -> 'submitted_payload_ref' -> 'currentDocumentReferenceHash') is distinct from 'string'
    or jsonb_typeof(v_submission_payload -> 'submitted_payload_ref' -> 'storedAt') is distinct from 'string' then
    raise exception 'company_tax_evidence_invalid_payload';
  end if;

  for v_call_index in 0..2 loop
    v_call := v_submission_payload -> 'calls' -> v_call_index;
    if jsonb_typeof(v_call) is distinct from 'object'
      or not (v_call ?& array['endpoint', 'body_hash', 'idempotency_key', 'status', 'created_at'])
      or v_call - array['endpoint', 'body_hash', 'idempotency_key', 'status', 'created_at']
        is distinct from '{}'::jsonb
      or jsonb_typeof(v_call -> 'endpoint') is distinct from 'string'
      or jsonb_typeof(v_call -> 'body_hash') is distinct from 'string'
      or jsonb_typeof(v_call -> 'idempotency_key') is distinct from 'null'
      or jsonb_typeof(v_call -> 'status') is distinct from 'string'
      or jsonb_typeof(v_call -> 'created_at') is distinct from 'string' then
      raise exception 'company_tax_evidence_invalid_payload';
    end if;
  end loop;

  begin
    select * into v_authority
    from jsonb_populate_record(null::public.authority_test_runs, v_authority_payload);
    select * into v_submission
    from jsonb_populate_record(null::public.filing_submissions, v_submission_payload);
  exception
    when others then
      raise exception 'company_tax_evidence_invalid_payload';
  end;

  if v_authority.company_id is null
    or v_submission.company_id is null
    or v_authority.company_id is distinct from v_submission.company_id
    or v_submission.income_year is null
    or v_submission.income_year not between 2000 and 2100
    or v_authority.obligation is distinct from 'skattemelding'
    or v_authority.environment is distinct from 'test'
    or v_authority.status is distinct from 'pending'
    or v_authority.feedback_summary is distinct from
      'validertOK; personbekreftelse fullført; offisiell tilbakemelding mottatt; myndighetsutfall venter på klassifisering.'
    or (
      v_authority.evidence_url is not null
      and (
        v_authority.evidence_url !~ '^https://'
        or v_authority.evidence_url like '%?%'
        or v_authority.evidence_url like '%#%'
        or v_authority.evidence_url like '%@%'
        or octet_length(v_authority.evidence_url) > 2048
      )
    )
    or v_submission.filing is distinct from 'skattemelding for AS'
    or v_submission.mode is distinct from 'test_authority'
    or v_submission.adapter_mode is distinct from 'test_authority'
    or v_submission.status is distinct from 'feedback_ready'
    or v_submission.preview_id is not null
    or v_submission.setup_id is not null
    or v_submission.authority_confirmed_by is not null
    or v_submission.authority_confirmed_at is not null
    or v_submission.preview_confirmed_by is not null
    or v_submission.preview_confirmed_at is not null
    or v_submission.failure_code is not null
    or v_submission.failure_message is not null
    or v_submission.submitted_payload is not null then
    raise exception 'company_tax_evidence_invalid_payload';
  end if;

  if not exists (
    select 1
    from public.company_memberships m
    where m.company_id = v_authority.company_id
      and m.user_id = v_actor_id
      and m.role = 'owner'
      and m.accepted_at is not null
  ) then
    raise exception 'company_tax_evidence_owner_required';
  end if;

  if v_authority.recorded_by is distinct from v_actor_id
    or v_submission.created_by is distinct from v_actor_id
    or v_submission.submitted_by is not null then
    raise exception 'company_tax_evidence_invalid_payload';
  end if;

  begin
    v_expected_archive_reference :=
      'https://platform.tt02.altinn.no/storage/api/v1/instances/'
      || substring(v_authority.test_reference from 6);
    select c.org_number into v_company_org_number
    from public.companies c
    where c.id = v_authority.company_id;
    v_reference_income_year :=
      (v_submission.submitted_payload_ref ->> 'incomeYear')::integer;
    v_recomputed_payload_hash := encode(digest(
      'skattemelding:' || (v_submission.submitted_payload_ref ->> 'skattemeldingHash') || E'\n'
      || 'naeringsspesifikasjon:' || (v_submission.submitted_payload_ref ->> 'naeringsspesifikasjonHash') || E'\n'
      || 'validationEnvelope:' || (v_submission.submitted_payload_ref ->> 'validationEnvelopeHash') || E'\n'
      || 'submissionEnvelope:' || (v_submission.submitted_payload_ref ->> 'submissionEnvelopeHash'),
      'sha256'
    ), 'hex');

  if v_authority.test_reference is null
    or v_authority.test_reference !~ '^tt02:[0-9]+/[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$'
    or octet_length(v_authority.test_reference) > 64
    or v_submission.receipt_id !~ '^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$'
    or v_submission.submitted_payload_ref ->> 'companyOrgNumber' !~ '^[0-9]{9}$'
    or v_submission.submitted_payload_ref ->> 'companyOrgNumber' is distinct from v_company_org_number
    or v_reference_income_year is distinct from v_submission.income_year
    or v_submission.payload_hash is distinct from v_recomputed_payload_hash
    or v_submission.submitted_payload_ref ->> 'payloadHash' is distinct from v_recomputed_payload_hash
    or v_authority.payload_hash is distinct from 'sha256:' || v_recomputed_payload_hash
    or v_submission.idempotency_key is distinct from
      'company-tax:' || v_submission.company_id::text || ':'
      || v_submission.income_year::text || ':' || v_recomputed_payload_hash
    or octet_length(v_submission.idempotency_key) > 180
    or v_authority.archive_reference is distinct from v_expected_archive_reference
    or octet_length(v_authority.archive_reference) > 2048
    or v_authority.receipt_reference is distinct from
      v_expected_archive_reference || '/data/' || v_submission.receipt_id
    or octet_length(v_authority.receipt_reference) > 2048
    or jsonb_typeof(v_submission.calls) is distinct from 'array'
    or jsonb_array_length(v_submission.calls) is distinct from 3
    or jsonb_typeof(v_submission.feedback_document_ids) is distinct from 'array'
    or v_submission.feedback_document_ids is distinct from jsonb_build_array(v_submission.receipt_id)
    or jsonb_typeof(v_submission.feedback_items) is distinct from 'array'
    or jsonb_array_length(v_submission.feedback_items) is distinct from 1
    or (v_submission.feedback_items -> 0) - array[
      'severity', 'code', 'message', 'documentId'
    ] is distinct from '{}'::jsonb
    or v_submission.feedback_items -> 0 ->> 'documentId' is distinct from v_submission.receipt_id
    or v_submission.feedback_items -> 0 ->> 'code' is distinct from 'COMPANY_TAX_AUTHORITY_OUTCOME_PENDING'
    or v_submission.feedback_items -> 0 ->> 'severity' is distinct from 'warning'
    or v_submission.feedback_items -> 0 ->> 'message' is distinct from
      'Offisiell tilbakemelding er mottatt, men myndighetsutfallet venter på klassifisering.'
    or v_submission.receipt_metadata - array[
      'authority', 'receiptId', 'status', 'receivedAt', 'feedbackDocumentIds',
      'dataType', 'contentType', 'byteLength', 'contentSha256', 'reference',
      'archiveReference', 'processEndedAt', 'archivedAt'
    ] is distinct from '{}'::jsonb
    or v_submission.receipt_metadata ->> 'authority' is distinct from 'skatteetaten'
    or v_submission.receipt_metadata ->> 'receiptId' is distinct from v_submission.receipt_id
    or v_submission.receipt_metadata ->> 'status' is distinct from 'feedback_ready'
    or v_submission.receipt_metadata ->> 'dataType' is distinct from 'tilbakemelding'
    or v_submission.receipt_metadata ->> 'contentType' not in ('application/xml', 'text/xml')
    or (v_submission.receipt_metadata ->> 'byteLength')::integer < 1
    or v_submission.receipt_metadata ->> 'contentSha256' !~ '^[0-9a-f]{64}$'
    or v_submission.receipt_metadata -> 'feedbackDocumentIds' is distinct from v_submission.feedback_document_ids
    or v_submission.receipt_metadata ->> 'reference' is distinct from v_authority.receipt_reference
    or v_submission.receipt_metadata ->> 'archiveReference' is distinct from v_authority.archive_reference
    or v_submission.submitted_payload_ref - array[
      'companyOrgNumber', 'incomeYear', 'envelopeDataId', 'archiveReference',
      'payloadHash', 'skattemeldingHash', 'naeringsspesifikasjonHash',
      'validationEnvelopeHash', 'submissionEnvelopeHash',
      'currentDocumentReferenceHash', 'storedAt'
    ] is distinct from '{}'::jsonb
    or v_submission.submitted_payload_ref ->> 'envelopeDataId'
      !~ '^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$'
    or v_submission.submitted_payload_ref ->> 'archiveReference' is distinct from v_authority.archive_reference
    or v_submission.submitted_payload_ref ->> 'skattemeldingHash' !~ '^[0-9a-f]{64}$'
    or v_submission.submitted_payload_ref ->> 'naeringsspesifikasjonHash' !~ '^[0-9a-f]{64}$'
    or v_submission.submitted_payload_ref ->> 'validationEnvelopeHash' !~ '^[0-9a-f]{64}$'
    or v_submission.submitted_payload_ref ->> 'submissionEnvelopeHash' !~ '^[0-9a-f]{64}$'
    or v_submission.submitted_payload_ref ->> 'currentDocumentReferenceHash' !~ '^[0-9a-f]{64}$'
    or (v_submission.calls -> 0) - array[
      'endpoint', 'body_hash', 'idempotency_key', 'status', 'created_at'
    ] is distinct from '{}'::jsonb
    or (v_submission.calls -> 1) - array[
      'endpoint', 'body_hash', 'idempotency_key', 'status', 'created_at'
    ] is distinct from '{}'::jsonb
    or (v_submission.calls -> 2) - array[
      'endpoint', 'body_hash', 'idempotency_key', 'status', 'created_at'
    ] is distinct from '{}'::jsonb
    or v_submission.calls -> 0 ->> 'endpoint' is distinct from 'skatteetaten:company-tax-validation'
    or v_submission.calls -> 0 -> 'idempotency_key' is distinct from 'null'::jsonb
    or v_submission.calls -> 0 ->> 'status' is distinct from 'validertOK'
    or v_submission.calls -> 0 ->> 'body_hash' is distinct from
      v_submission.submitted_payload_ref ->> 'validationEnvelopeHash'
    or v_submission.calls -> 1 ->> 'endpoint' is distinct from 'altinn:owner-confirmation-handoff'
    or v_submission.calls -> 1 -> 'idempotency_key' is distinct from 'null'::jsonb
    or v_submission.calls -> 1 ->> 'status' is distinct from 'confirmation_prepared'
    or v_submission.calls -> 1 ->> 'body_hash' is distinct from
      v_submission.submitted_payload_ref ->> 'submissionEnvelopeHash'
    or v_submission.calls -> 2 ->> 'endpoint' is distinct from 'altinn:official-feedback-receipt'
    or v_submission.calls -> 2 -> 'idempotency_key' is distinct from 'null'::jsonb
    or v_submission.calls -> 2 ->> 'status' is distinct from 'received'
    or v_submission.calls -> 2 ->> 'body_hash' is distinct from
      v_submission.receipt_metadata ->> 'contentSha256'
    or v_authority.recorded_at is null
    or v_submission.updated_at is null
    or v_authority.recorded_at is distinct from v_submission.updated_at
    or v_submission.updated_at is distinct from
      (v_submission.receipt_metadata ->> 'receivedAt')::timestamptz
    or v_submission.updated_at is distinct from
      (v_submission.submitted_payload_ref ->> 'storedAt')::timestamptz
    or (v_submission.calls -> 0 ->> 'created_at')::timestamptz >=
      (v_submission.calls -> 1 ->> 'created_at')::timestamptz
    or (v_submission.calls -> 1 ->> 'created_at')::timestamptz >= v_submission.updated_at
    or (v_submission.calls -> 2 ->> 'created_at')::timestamptz is distinct from v_submission.updated_at
    or (v_submission.receipt_metadata ->> 'processEndedAt')::timestamptz >=
      (v_submission.receipt_metadata ->> 'archivedAt')::timestamptz
    or (v_submission.receipt_metadata ->> 'archivedAt')::timestamptz >= v_submission.updated_at then
    raise exception 'company_tax_evidence_invalid_payload';
  end if;
  exception
    when others then
      raise exception 'company_tax_evidence_invalid_payload';
  end;

  select r.* into v_persisted_authority
  from public.authority_test_runs r
  where r.company_id = v_authority.company_id
    and r.obligation = v_authority.obligation
    and r.environment = v_authority.environment
    and r.test_reference = v_authority.test_reference
  for update;

  if not found then
    insert into public.authority_test_runs (
      company_id,
      obligation,
      environment,
      status,
      test_reference,
      feedback_summary,
      receipt_reference,
      archive_reference,
      evidence_url,
      payload_hash,
      recorded_by,
      recorded_at
    ) values (
      v_authority.company_id,
      v_authority.obligation,
      v_authority.environment,
      v_authority.status,
      v_authority.test_reference,
      v_authority.feedback_summary,
      v_authority.receipt_reference,
      v_authority.archive_reference,
      v_authority.evidence_url,
      v_authority.payload_hash,
      v_authority.recorded_by,
      v_authority.recorded_at
    )
    on conflict (company_id, obligation, environment, test_reference) do nothing
    returning * into v_persisted_authority;

    if not found then
      select r.* into v_persisted_authority
      from public.authority_test_runs r
      where r.company_id = v_authority.company_id
        and r.obligation = v_authority.obligation
        and r.environment = v_authority.environment
        and r.test_reference = v_authority.test_reference
      for update;
    end if;
  end if;

  if v_persisted_authority.status is distinct from v_authority.status
    or v_persisted_authority.feedback_summary is distinct from v_authority.feedback_summary
    or v_persisted_authority.receipt_reference is distinct from v_authority.receipt_reference
    or v_persisted_authority.archive_reference is distinct from v_authority.archive_reference
    or v_persisted_authority.evidence_url is distinct from v_authority.evidence_url
    or v_persisted_authority.payload_hash is distinct from v_authority.payload_hash
    or v_persisted_authority.recorded_by is distinct from v_authority.recorded_by
    or v_persisted_authority.recorded_at is distinct from v_authority.recorded_at then
    raise exception 'company_tax_evidence_conflict';
  end if;

  select s.* into v_persisted_submission
  from public.filing_submissions s
  where s.authority_test_run_id = v_persisted_authority.id
  for update;

  if not found then
    insert into public.filing_submissions (
      preview_id,
      authority_test_run_id,
      company_id,
      setup_id,
      income_year,
      filing,
      mode,
      adapter_mode,
      payload_hash,
      idempotency_key,
      status,
      authority_confirmed_by,
      authority_confirmed_at,
      preview_confirmed_by,
      preview_confirmed_at,
      calls,
      receipt_id,
      feedback_document_ids,
      feedback_items,
      receipt_metadata,
      submitted_payload_ref,
      submitted_payload,
      failure_code,
      failure_message,
      created_by,
      submitted_by,
      updated_at
    ) values (
      null,
      v_persisted_authority.id,
      v_submission.company_id,
      null,
      v_submission.income_year,
      v_submission.filing,
      v_submission.mode,
      v_submission.adapter_mode,
      v_submission.payload_hash,
      v_submission.idempotency_key,
      v_submission.status,
      null,
      null,
      null,
      null,
      v_submission.calls,
      v_submission.receipt_id,
      v_submission.feedback_document_ids,
      v_submission.feedback_items,
      v_submission.receipt_metadata,
      v_submission.submitted_payload_ref,
      null,
      null,
      null,
      v_submission.created_by,
      null,
      v_submission.updated_at
    )
    on conflict (authority_test_run_id) do nothing
    returning * into v_persisted_submission;

    if found then
      v_created := true;
    else
      select s.* into v_persisted_submission
      from public.filing_submissions s
      where s.authority_test_run_id = v_persisted_authority.id
      for update;
    end if;
  end if;

  if v_persisted_submission.preview_id is not null
    or v_persisted_submission.authority_test_run_id is distinct from v_persisted_authority.id
    or v_persisted_submission.company_id is distinct from v_submission.company_id
    or v_persisted_submission.setup_id is not null
    or v_persisted_submission.income_year is distinct from v_submission.income_year
    or v_persisted_submission.filing is distinct from v_submission.filing
    or v_persisted_submission.mode is distinct from v_submission.mode
    or v_persisted_submission.adapter_mode is distinct from v_submission.adapter_mode
    or v_persisted_submission.payload_hash is distinct from v_submission.payload_hash
    or v_persisted_submission.idempotency_key is distinct from v_submission.idempotency_key
    or v_persisted_submission.status is distinct from v_submission.status
    or v_persisted_submission.authority_confirmed_by is not null
    or v_persisted_submission.authority_confirmed_at is not null
    or v_persisted_submission.preview_confirmed_by is not null
    or v_persisted_submission.preview_confirmed_at is not null
    or v_persisted_submission.calls is distinct from v_submission.calls
    or v_persisted_submission.receipt_id is distinct from v_submission.receipt_id
    or v_persisted_submission.feedback_document_ids is distinct from v_submission.feedback_document_ids
    or v_persisted_submission.feedback_items is distinct from v_submission.feedback_items
    or v_persisted_submission.receipt_metadata is distinct from v_submission.receipt_metadata
    or v_persisted_submission.submitted_payload_ref is distinct from v_submission.submitted_payload_ref
    or v_persisted_submission.submitted_payload is not null
    or v_persisted_submission.failure_code is not null
    or v_persisted_submission.failure_message is not null
    or v_persisted_submission.created_by is distinct from v_submission.created_by
    or v_persisted_submission.submitted_by is not null
    or v_persisted_submission.updated_at is distinct from v_submission.updated_at then
    raise exception 'company_tax_evidence_conflict';
  end if;

  if v_created then
    insert into public.audit_events (company_id, actor_id, category, action, message)
    values (
      v_authority.company_id,
      v_actor_id,
      'submission',
      'company_tax_tt02_evidence_imported',
      'Skattemelding TT02-evidens importert som pending med ref '
        || v_authority.test_reference || '.'
    );
  end if;

  return jsonb_build_object(
    'authority_test_run_id', v_persisted_authority.id,
    'filing_submission_id', v_persisted_submission.id,
    'created', v_created
  );
end;
$$;

revoke all on function public.import_company_tax_tt02_evidence(jsonb) from public, anon;
grant execute on function public.import_company_tax_tt02_evidence(jsonb) to authenticated;
