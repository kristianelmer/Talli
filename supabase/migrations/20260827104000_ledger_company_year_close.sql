-- Issue #188: immutable evidence-gated company-year close assessments.
-- Source capabilities approve facts. This coordinator validates their structural
-- contract against the current immutable ledger and records the resulting state.

begin;

do $ledger_company_year_close_migration_authority$
begin
  execute pg_catalog.format('grant ledger_store_owner to %I', current_user);
  execute pg_catalog.format('grant create on schema ledger to %I', current_user);
  grant create on schema ledger to ledger_store_owner;
end
$ledger_company_year_close_migration_authority$;

alter table backend_system.ledger_command_receipts
  drop constraint if exists ledger_command_receipts_operation_name_check;
alter table backend_system.ledger_command_receipts
  add constraint ledger_command_receipts_operation_name_check check (
    operation_name in (
      'post_entry', 'lock_period', 'record_reconstruction', 'correct_entry',
      'close_company_year'
    )
  );

create or replace function ledger.company_year_ledger_state_digest_v1(
  p_company_id uuid,
  p_income_year integer
)
returns text
language sql
stable
security definer
set search_path = ''
as $function$
  select pg_catalog.encode(extensions.digest(
    pg_catalog.jsonb_build_object(
      'entries', coalesce((
        select pg_catalog.jsonb_agg(pg_catalog.to_jsonb(entry) order by entry.id)
        from ledger.entries entry
        where entry.company_id = p_company_id
          and entry.income_year = p_income_year
      ), '[]'::jsonb),
      'contexts', coalesce((
        select pg_catalog.jsonb_agg(
          pg_catalog.to_jsonb(context) order by context.entry_id
        )
        from ledger.entry_contexts context
        where context.company_id = p_company_id
          and context.income_year = p_income_year
      ), '[]'::jsonb),
      'sources', coalesce((
        select pg_catalog.jsonb_agg(
          pg_catalog.to_jsonb(source) order by source.entry_id, source.ordinal
        )
        from ledger.entry_sources source
        where source.company_id = p_company_id
          and source.income_year = p_income_year
      ), '[]'::jsonb),
      'corrections', coalesce((
        select pg_catalog.jsonb_agg(
          pg_catalog.to_jsonb(correction)
          order by correction.original_entry_id
        )
        from ledger.entry_corrections correction
        where correction.company_id = p_company_id
          and correction.income_year = p_income_year
      ), '[]'::jsonb)
    )::text,
    'sha256'
  ), 'hex');
$function$;

do $ledger_reconstruction_digest_interface$
begin
  if pg_catalog.to_regprocedure(
    'ledger.record_reconstruction_assessment_without_state_digest_v1(text,uuid,integer,date,jsonb,text,text[],text,text)'
  ) is null then
    alter function ledger.record_reconstruction_assessment(
      text, uuid, integer, date, jsonb, text, text[], text, text
    ) rename to record_reconstruction_assessment_without_state_digest_v1;
  end if;
  if pg_catalog.to_regprocedure(
    'ledger.get_reconstruction_assessment_without_state_digest_v1(uuid,integer,text)'
  ) is null then
    alter function ledger.get_reconstruction_assessment(uuid, integer, text)
      rename to get_reconstruction_assessment_without_state_digest_v1;
  end if;
end
$ledger_reconstruction_digest_interface$;

create or replace function ledger.record_reconstruction_assessment(
  p_idempotency_key text,
  p_company_id uuid,
  p_income_year integer,
  p_as_of date,
  p_evidence jsonb,
  p_state text,
  p_gap_codes text[],
  p_correlation_id text,
  p_verified_subject text
)
returns table (
  assessment_id uuid,
  company_id uuid,
  income_year integer,
  as_of date,
  state text,
  gap_codes text[],
  evidence_digest text,
  ledger_state_digest text,
  recorded_at timestamptz,
  replayed boolean
)
language plpgsql
security definer
set search_path = ''
as $function$
declare
  v_legacy record;
begin
  if pg_catalog.to_regclass('ledger.entries') is null then
    raise exception 'ledger_cutover_inactive';
  end if;
  select legacy.* into strict v_legacy
  from ledger.record_reconstruction_assessment_without_state_digest_v1(
    p_idempotency_key, p_company_id, p_income_year, p_as_of, p_evidence,
    p_state, p_gap_codes, p_correlation_id, p_verified_subject
  ) legacy;
  return query select v_legacy.assessment_id, v_legacy.company_id,
    v_legacy.income_year, v_legacy.as_of, v_legacy.state, v_legacy.gap_codes,
    v_legacy.evidence_digest, assessment.ledger_state_digest,
    v_legacy.recorded_at, v_legacy.replayed
  from ledger.reconstruction_assessments assessment
  where assessment.id = v_legacy.assessment_id;
end;
$function$;

create or replace function ledger.get_reconstruction_assessment(
  p_company_id uuid,
  p_income_year integer,
  p_verified_subject text
)
returns table (
  assessment_id uuid,
  company_id uuid,
  income_year integer,
  as_of date,
  state text,
  gap_codes text[],
  evidence_digest text,
  ledger_state_digest text,
  recorded_at timestamptz,
  replayed boolean
)
language plpgsql
security definer
set search_path = ''
as $function$
begin
  return query select legacy.assessment_id, legacy.company_id, legacy.income_year,
    legacy.as_of, legacy.state, legacy.gap_codes, legacy.evidence_digest,
    assessment.ledger_state_digest, legacy.recorded_at, legacy.replayed
  from ledger.get_reconstruction_assessment_without_state_digest_v1(
    p_company_id, p_income_year, p_verified_subject
  ) legacy
  join ledger.reconstruction_assessments assessment
    on assessment.id = legacy.assessment_id;
end;
$function$;

create or replace function ledger.close_company_year_v1(
  p_idempotency_key text,
  p_company_id uuid,
  p_income_year integer,
  p_period_end date,
  p_reason text,
  p_reconstruction_assessment_id uuid,
  p_reconstruction_digest text,
  p_evidence jsonb,
  p_derived_state text,
  p_gap_codes text[],
  p_correlation_id text,
  p_verified_subject text
)
returns table (
  assessment_id uuid,
  reconstruction_assessment_id uuid,
  close_lock_id uuid,
  company_id uuid,
  income_year integer,
  period_end date,
  state text,
  gap_codes text[],
  evidence_digest text,
  ledger_state_digest text,
  recorded_at timestamptz,
  is_current boolean,
  replayed boolean
)
language plpgsql
security definer
set search_path = ''
as $function$
declare
  v_actor_id uuid := public.company_access_auth_uid_v1();
  v_receipt backend_system.ledger_command_receipts%rowtype;
  v_reconstruction ledger.reconstruction_assessments%rowtype;
  v_assessment_id uuid;
  v_close_lock_id uuid;
  v_recorded_at timestamptz;
  v_evidence_digest text;
  v_ledger_state_digest text;
  v_fingerprint text;
  v_derived_state text;
  v_derived_gaps text[] := '{}'::text[];
  v_requested_gaps text[];
  v_result jsonb;
begin
  if pg_catalog.to_regclass('ledger.entries') is null then
    raise exception 'ledger_cutover_inactive';
  end if;
  if v_actor_id is null
    or p_verified_subject is null
    or p_verified_subject !~ '^[0-9a-fA-F-]{36}$'
    or v_actor_id is distinct from p_verified_subject::uuid
  then
    raise exception 'ledger_forbidden';
  end if;
  if p_company_id is null
    or p_reconstruction_assessment_id is null
    or p_income_year not between 2000 and 2100
    or p_period_end is null
    or extract(year from p_period_end)::integer <> p_income_year
    or coalesce(p_idempotency_key, '') !~ '^[A-Za-z0-9._:-]{16,255}$'
    or pg_catalog.btrim(coalesce(p_reason, '')) = ''
    or pg_catalog.length(p_reason) > 500
    or coalesce(p_reconstruction_digest, '') !~ '^[0-9a-f]{64}$'
    or pg_catalog.jsonb_typeof(p_evidence) is distinct from 'array'
    or pg_catalog.jsonb_array_length(p_evidence) > 3
    or p_derived_state not in ('CLOSED', 'BLOCKED')
    or p_gap_codes is null
    or coalesce(p_correlation_id, '') !~ '^[A-Za-z0-9._:-]{1,80}$'
  then
    raise exception 'ledger_invalid_input';
  end if;
  select coalesce(pg_catalog.array_agg(gap order by gap), '{}'::text[])
  into v_requested_gaps
  from (select distinct gap from pg_catalog.unnest(p_gap_codes) gap) requested;
  if pg_catalog.cardinality(v_requested_gaps)
      <> pg_catalog.cardinality(p_gap_codes)
    or exists (
      select 1 from pg_catalog.unnest(v_requested_gaps) gap
      where gap not in (
        'BANK_NOT_RECONCILED', 'CHECK_EVIDENCE_INCOMPLETE',
        'DUPLICATE_POSTING_FOUND', 'JOURNAL_UNBALANCED',
        'MATERIAL_BALANCE_UNDOCUMENTED', 'PERIOD_END_UNSUPPORTED',
        'REPORTING_NOT_RECONCILED', 'SOURCE_INCOMPLETE',
        'UNRESOLVED_BANK_ROW', 'UNSUPPORTED_TRANSACTION'
      )
    )
  then
    raise exception 'ledger_company_year_close_evidence_invalid';
  end if;
  if not public.company_access_is_accepted_member_v1(p_company_id) then
    raise exception 'ledger_not_found';
  end if;
  if not public.company_access_is_accepted_owner_v1(p_company_id) then
    raise exception 'ledger_forbidden';
  end if;

  if exists (
    select 1
    from pg_catalog.jsonb_array_elements(p_evidence) item
    where pg_catalog.jsonb_typeof(item) is distinct from 'object'
      or item ->> 'status' not in ('CONFIRMED', 'GAP', 'UNKNOWN')
      or pg_catalog.btrim(coalesce(item ->> 'sourceRecordId', '')) = ''
      or pg_catalog.length(item ->> 'sourceRecordId') > 255
      or coalesce(item ->> 'revision', '') !~ '^[1-9][0-9]*$'
      or coalesce(item ->> 'factSha256', '') !~ '^[0-9a-f]{64}$'
      or coalesce(item ->> 'ledgerStateDigest', '') !~ '^[0-9a-f]{64}$'
      or not pg_catalog.pg_input_is_valid(
        coalesce(item ->> 'coverageThrough', ''), 'date'
      )
      or pg_catalog.jsonb_typeof(item -> 'outputs') is distinct from 'array'
      or (item ->> 'kind', item ->> 'issuer') not in (
        ('BANK_ROWS_RESOLVED', 'BANKING'),
        ('MATERIAL_BALANCES_DOCUMENTED', 'DOCUMENTS'),
        ('REPORTING_RECONCILED', 'LEDGER')
      )
      or item ->> 'gapCode' is distinct from case
        when item ->> 'status' = 'CONFIRMED' then null
        when item ->> 'kind' = 'BANK_ROWS_RESOLVED' then 'UNRESOLVED_BANK_ROW'
        when item ->> 'kind' = 'MATERIAL_BALANCES_DOCUMENTED'
          then 'MATERIAL_BALANCE_UNDOCUMENTED'
        when item ->> 'kind' = 'REPORTING_RECONCILED'
          then 'REPORTING_NOT_RECONCILED'
      end
      or (
        (item ->> 'kind' = 'REPORTING_RECONCILED'
          and item ->> 'status' = 'CONFIRMED')
        is distinct from (pg_catalog.jsonb_array_length(item -> 'outputs') = 7)
      )
      or (
        item ->> 'kind' <> 'REPORTING_RECONCILED'
        and pg_catalog.jsonb_array_length(item -> 'outputs') <> 0
      )
      or (
        item ->> 'kind' = 'REPORTING_RECONCILED'
        and item ->> 'status' <> 'CONFIRMED'
        and pg_catalog.jsonb_array_length(item -> 'outputs') <> 0
      )
  ) or exists (
    select 1
    from pg_catalog.jsonb_array_elements(p_evidence) item
    group by item ->> 'kind', item ->> 'issuer'
    having pg_catalog.count(*) > 1
  ) or exists (
    select 1
    from pg_catalog.jsonb_array_elements(p_evidence) item
    cross join lateral pg_catalog.jsonb_array_elements(item -> 'outputs') output
    where pg_catalog.jsonb_typeof(output) is distinct from 'object'
      or output ->> 'kind' not in (
        'INVESTMENTS', 'CORPORATE_GOVERNANCE',
        'SHAREHOLDER_REGISTER_FILING', 'COMPANY_TAX_FILING',
        'ANNUAL_ACCOUNTS_FILING', 'SAF_T', 'COMPANY_ARCHIVE'
      )
      or pg_catalog.btrim(coalesce(output ->> 'sourceRecordId', '')) = ''
      or pg_catalog.length(output ->> 'sourceRecordId') > 255
      or coalesce(output ->> 'revision', '') !~ '^[1-9][0-9]*$'
      or coalesce(output ->> 'factSha256', '') !~ '^[0-9a-f]{64}$'
  ) or exists (
    select 1
    from pg_catalog.jsonb_array_elements(p_evidence) item
    cross join lateral pg_catalog.jsonb_array_elements(item -> 'outputs') output
    group by item ->> 'kind', output ->> 'kind'
    having pg_catalog.count(*) > 1
  ) or (
    exists (
      select 1 from pg_catalog.jsonb_array_elements(p_evidence) item
      where item ->> 'kind' = 'REPORTING_RECONCILED'
        and item ->> 'status' = 'CONFIRMED'
    ) and exists (
      with expected(kind) as (values
      ('INVESTMENTS'), ('CORPORATE_GOVERNANCE'),
      ('SHAREHOLDER_REGISTER_FILING'), ('COMPANY_TAX_FILING'),
      ('ANNUAL_ACCOUNTS_FILING'), ('SAF_T'), ('COMPANY_ARCHIVE')
    ), supplied(kind) as (
      select output ->> 'kind'
      from pg_catalog.jsonb_array_elements(p_evidence) item
      cross join lateral pg_catalog.jsonb_array_elements(item -> 'outputs') output
      where item ->> 'kind' = 'REPORTING_RECONCILED'
        and item ->> 'status' = 'CONFIRMED'
    )
      (select * from expected except all select * from supplied)
      union all
      (select * from supplied except all select * from expected)
    )
  ) then
    raise exception 'ledger_company_year_close_evidence_invalid';
  end if;

  v_evidence_digest := pg_catalog.encode(
    extensions.digest(p_evidence::text, 'sha256'), 'hex'
  );
  v_fingerprint := ledger.company_year_close_request_fingerprint_v1(
    p_company_id, p_income_year, p_period_end, p_reason,
    p_reconstruction_assessment_id, p_reconstruction_digest, p_evidence,
    p_correlation_id
  );
  if not pg_catalog.pg_try_advisory_xact_lock(pg_catalog.hashtextextended(
    'ledger:v1:' || v_actor_id::text || ':' || p_company_id::text
      || ':close_company_year:' || p_idempotency_key,
    0
  )) then
    raise exception 'ledger_idempotency_in_progress';
  end if;
  select receipt.* into v_receipt
  from backend_system.ledger_command_receipts receipt
  where receipt.api_major = 'v1'
    and receipt.actor_id = v_actor_id
    and receipt.company_id = p_company_id
    and receipt.operation_name = 'close_company_year'
    and receipt.idempotency_key = p_idempotency_key;
  if found then
    if v_receipt.request_fingerprint <> v_fingerprint then
      raise exception 'ledger_idempotency_key_reused';
    end if;
    return query select
      (v_receipt.result ->> 'assessment_id')::uuid,
      (v_receipt.result ->> 'reconstruction_assessment_id')::uuid,
      (v_receipt.result ->> 'close_lock_id')::uuid,
      (v_receipt.result ->> 'company_id')::uuid,
      (v_receipt.result ->> 'income_year')::integer,
      (v_receipt.result ->> 'period_end')::date,
      v_receipt.result ->> 'state',
      array(select pg_catalog.jsonb_array_elements_text(
        v_receipt.result -> 'gap_codes'
      )),
      v_receipt.result ->> 'evidence_digest',
      v_receipt.result ->> 'ledger_state_digest',
      (v_receipt.result ->> 'recorded_at')::timestamptz,
      ledger.company_year_close_is_current_v1(
        (v_receipt.result ->> 'assessment_id')::uuid,
        p_company_id, p_income_year
      ),
      true;
    return;
  end if;

  perform ledger.lock_company_year_v1(p_company_id, p_income_year);
  if not public.company_access_company_year_allows_consequential_v1(
    p_company_id, p_income_year
  ) then
    raise exception 'ledger_company_year_not_admitted';
  end if;
  v_ledger_state_digest := ledger.company_year_ledger_state_digest_v1(
    p_company_id, p_income_year
  );
  select assessment.* into v_reconstruction
  from ledger.reconstruction_assessments assessment
  where assessment.company_id = p_company_id
    and assessment.income_year = p_income_year
  order by assessment.recorded_at desc, assessment.id desc
  limit 1;
  if not found
    or v_reconstruction.id is distinct from p_reconstruction_assessment_id
    or v_reconstruction.evidence_digest is distinct from p_reconstruction_digest
    or v_reconstruction.as_of is distinct from p_period_end
    or v_reconstruction.ledger_state_digest is distinct from v_ledger_state_digest
  then
    raise exception 'ledger_company_year_close_reconstruction_stale';
  end if;
  if exists (
    select 1 from pg_catalog.jsonb_array_elements(p_evidence) item
    where item ->> 'ledgerStateDigest' is distinct from v_ledger_state_digest
  ) then
    raise exception 'ledger_company_year_close_evidence_invalid';
  end if;

  if p_period_end is distinct from pg_catalog.make_date(p_income_year, 12, 31) then
    v_derived_gaps := pg_catalog.array_append(
      v_derived_gaps, 'PERIOD_END_UNSUPPORTED'
    );
  end if;
  if v_reconstruction.state <> 'READY' then
    v_derived_gaps := pg_catalog.array_append(v_derived_gaps, 'SOURCE_INCOMPLETE');
    if 'BANK_NOT_RECONCILED' = any(v_reconstruction.gap_codes) then
      v_derived_gaps := pg_catalog.array_append(
        v_derived_gaps, 'BANK_NOT_RECONCILED'
      );
    end if;
    if 'UNSUPPORTED_ACTIVITY_FOUND' = any(v_reconstruction.gap_codes) then
      v_derived_gaps := pg_catalog.array_append(
        v_derived_gaps, 'UNSUPPORTED_TRANSACTION'
      );
    end if;
  end if;
  if pg_catalog.jsonb_array_length(p_evidence) < 3 then
    v_derived_gaps := pg_catalog.array_append(
      v_derived_gaps, 'CHECK_EVIDENCE_INCOMPLETE'
    );
  end if;
  if exists (
    select 1 from pg_catalog.jsonb_array_elements(p_evidence) item
    where (item ->> 'coverageThrough')::date is distinct from p_period_end
  ) then
    v_derived_gaps := pg_catalog.array_append(
      v_derived_gaps, 'CHECK_EVIDENCE_INCOMPLETE'
    );
  end if;
  select v_derived_gaps || coalesce(
    pg_catalog.array_agg(item ->> 'gapCode' order by ordinal)
      filter (where item ->> 'status' <> 'CONFIRMED'),
    '{}'::text[]
  ) into v_derived_gaps
  from pg_catalog.jsonb_array_elements(p_evidence)
    with ordinality source(item, ordinal);
  select coalesce(pg_catalog.array_agg(gap order by gap), '{}'::text[])
  into v_derived_gaps
  from (select distinct gap from pg_catalog.unnest(v_derived_gaps) gap) derived;
  v_derived_state := case
    when pg_catalog.cardinality(v_derived_gaps) = 0 then 'CLOSED'
    else 'BLOCKED'
  end;
  if p_derived_state is distinct from v_derived_state
    or v_requested_gaps is distinct from v_derived_gaps
  then
    raise exception 'ledger_company_year_close_evidence_invalid';
  end if;
  if v_derived_state = 'CLOSED' and (
    v_reconstruction.state <> 'READY'
    or pg_catalog.jsonb_array_length(p_evidence) <> 3
    or exists (
      select 1 from pg_catalog.jsonb_array_elements(p_evidence) item
      where item ->> 'status' <> 'CONFIRMED'
        or (item ->> 'coverageThrough')::date <> p_period_end
    )
  ) then
    raise exception 'ledger_company_year_close_evidence_invalid';
  end if;

  if exists (
    select 1 from ledger.entries entry
    where entry.company_id = p_company_id
      and entry.income_year = p_income_year
      and not ledger.entry_lines_are_valid_v1(entry.lines, true)
  ) then
    v_derived_gaps := pg_catalog.array_append(v_derived_gaps, 'JOURNAL_UNBALANCED');
  end if;
  if exists (
    select 1 from ledger.entries entry
    where entry.company_id = p_company_id
      and entry.income_year = p_income_year
    group by entry.source_capability, entry.source_record_id
    having pg_catalog.count(*) > 1
  ) then
    v_derived_gaps := pg_catalog.array_append(
      v_derived_gaps, 'DUPLICATE_POSTING_FOUND'
    );
  end if;
  select coalesce(pg_catalog.array_agg(gap order by gap), '{}'::text[])
  into v_derived_gaps
  from (select distinct gap from pg_catalog.unnest(v_derived_gaps) gap) derived;
  v_derived_state := case
    when pg_catalog.cardinality(v_derived_gaps) = 0 then 'CLOSED'
    else 'BLOCKED'
  end;

  v_close_lock_id := null;
  if v_derived_state = 'CLOSED' then
    select close_lock.id into v_close_lock_id
    from ledger.company_year_close_locks close_lock
    where close_lock.company_id = p_company_id
      and close_lock.income_year = p_income_year;
    if not found then
      v_close_lock_id := pg_catalog.gen_random_uuid();
      insert into ledger.company_year_close_locks (
        id, company_id, income_year, reason, locked_by, locked_at
      ) values (
        v_close_lock_id, p_company_id, p_income_year,
        pg_catalog.btrim(p_reason), v_actor_id,
        pg_catalog.statement_timestamp()
      );
    end if;
  end if;

  v_assessment_id := pg_catalog.gen_random_uuid();
  v_recorded_at := pg_catalog.statement_timestamp();
  insert into ledger.company_year_close_assessments (
    id, reconstruction_assessment_id, close_lock_id, company_id, income_year,
    period_end, reason, reconstruction_digest, state, gap_codes,
    evidence_digest, ledger_state_digest, correlation_id, recorded_by,
    recorded_at
  ) values (
    v_assessment_id, p_reconstruction_assessment_id, v_close_lock_id,
    p_company_id, p_income_year, p_period_end, pg_catalog.btrim(p_reason),
    p_reconstruction_digest, v_derived_state, v_derived_gaps,
    v_evidence_digest, v_ledger_state_digest, p_correlation_id, v_actor_id,
    v_recorded_at
  );
  insert into ledger.company_year_close_evidence (
    assessment_id, company_id, income_year, ordinal, kind, issuer, status,
    source_record_id, source_revision, fact_sha256, coverage_through, gap_code,
    ledger_state_digest
  )
  select v_assessment_id, p_company_id, p_income_year, ordinal::integer,
    item ->> 'kind', item ->> 'issuer', item ->> 'status',
    item ->> 'sourceRecordId', (item ->> 'revision')::integer,
    item ->> 'factSha256', (item ->> 'coverageThrough')::date,
    item ->> 'gapCode', item ->> 'ledgerStateDigest'
  from pg_catalog.jsonb_array_elements(p_evidence)
    with ordinality source(item, ordinal);
  insert into ledger.company_year_close_reporting_outputs (
    assessment_id, company_id, income_year, ordinal, kind, source_record_id,
    source_revision, fact_sha256, ledger_state_digest
  )
  select v_assessment_id, p_company_id, p_income_year, ordinal::integer,
    output ->> 'kind', output ->> 'sourceRecordId',
    (output ->> 'revision')::integer, output ->> 'factSha256',
    item ->> 'ledgerStateDigest'
  from pg_catalog.jsonb_array_elements(p_evidence) item
  cross join lateral pg_catalog.jsonb_array_elements(item -> 'outputs')
    with ordinality supplied(output, ordinal);

  v_result := pg_catalog.jsonb_build_object(
    'assessment_id', v_assessment_id,
    'reconstruction_assessment_id', p_reconstruction_assessment_id,
    'close_lock_id', v_close_lock_id,
    'company_id', p_company_id,
    'income_year', p_income_year,
    'period_end', p_period_end,
    'state', v_derived_state,
    'gap_codes', pg_catalog.to_jsonb(v_derived_gaps),
    'evidence_digest', v_evidence_digest,
    'ledger_state_digest', v_ledger_state_digest,
    'recorded_at', v_recorded_at
  );
  insert into backend_system.ledger_command_receipts (
    api_major, actor_id, company_id, operation_name, idempotency_key,
    request_fingerprint, result, completed_at
  ) values (
    'v1', v_actor_id, p_company_id, 'close_company_year', p_idempotency_key,
    v_fingerprint, v_result, v_recorded_at
  );

  return query select v_assessment_id, p_reconstruction_assessment_id,
    v_close_lock_id, p_company_id, p_income_year, p_period_end,
    v_derived_state, v_derived_gaps, v_evidence_digest, v_ledger_state_digest,
    v_recorded_at, true, false;
end;
$function$;

alter table ledger.reconstruction_assessments
  add column if not exists ledger_state_digest text;
alter table ledger.reconstruction_assessments
  drop constraint if exists reconstruction_assessments_ledger_state_digest_check;
alter table ledger.reconstruction_assessments
  add constraint reconstruction_assessments_ledger_state_digest_check check (
    ledger_state_digest is null
    or ledger_state_digest ~ '^[0-9a-f]{64}$'
  );

create table if not exists ledger.company_year_close_locks (
  id uuid primary key default pg_catalog.gen_random_uuid(),
  company_id uuid not null references public.companies(id) on delete restrict,
  income_year integer not null check (income_year between 2000 and 2100),
  reason text not null check (
    pg_catalog.btrim(reason) <> '' and pg_catalog.length(reason) <= 500
  ),
  locked_by uuid not null references auth.users(id) on delete restrict,
  locked_at timestamptz not null default pg_catalog.statement_timestamp(),
  unique (company_id, income_year),
  unique (id, company_id, income_year)
);

create table if not exists ledger.company_year_close_assessments (
  id uuid primary key default pg_catalog.gen_random_uuid(),
  reconstruction_assessment_id uuid not null,
  close_lock_id uuid,
  company_id uuid not null references public.companies(id) on delete restrict,
  income_year integer not null check (income_year between 2000 and 2100),
  period_end date not null,
  reason text not null check (
    pg_catalog.btrim(reason) <> '' and pg_catalog.length(reason) <= 500
  ),
  reconstruction_digest text not null check (
    reconstruction_digest ~ '^[0-9a-f]{64}$'
  ),
  state text not null check (state in ('CLOSED', 'BLOCKED')),
  gap_codes text[] not null,
  evidence_digest text not null check (evidence_digest ~ '^[0-9a-f]{64}$'),
  ledger_state_digest text not null check (
    ledger_state_digest ~ '^[0-9a-f]{64}$'
  ),
  correlation_id text not null check (
    correlation_id ~ '^[A-Za-z0-9._:-]{1,80}$'
  ),
  recorded_by uuid not null references auth.users(id) on delete restrict,
  recorded_at timestamptz not null default pg_catalog.statement_timestamp(),
  unique (id, company_id, income_year),
  foreign key (reconstruction_assessment_id, company_id, income_year)
    references ledger.reconstruction_assessments(id, company_id, income_year)
    on delete restrict,
  foreign key (close_lock_id, company_id, income_year)
    references ledger.company_year_close_locks(id, company_id, income_year)
    on delete restrict,
  check (
    (state = 'CLOSED' and close_lock_id is not null
      and pg_catalog.cardinality(gap_codes) = 0)
    or (state = 'BLOCKED' and close_lock_id is null
      and pg_catalog.cardinality(gap_codes) > 0)
  ),
  check (
    gap_codes <@ array[
      'BANK_NOT_RECONCILED', 'CHECK_EVIDENCE_INCOMPLETE',
      'DUPLICATE_POSTING_FOUND', 'JOURNAL_UNBALANCED',
      'MATERIAL_BALANCE_UNDOCUMENTED', 'PERIOD_END_UNSUPPORTED',
      'REPORTING_NOT_RECONCILED', 'SOURCE_INCOMPLETE',
      'UNRESOLVED_BANK_ROW', 'UNSUPPORTED_TRANSACTION'
    ]::text[]
  )
);

create table if not exists ledger.company_year_close_evidence (
  assessment_id uuid not null,
  company_id uuid not null,
  income_year integer not null,
  ordinal integer not null check (ordinal between 1 and 3),
  kind text not null,
  issuer text not null,
  status text not null check (status in ('CONFIRMED', 'GAP', 'UNKNOWN')),
  source_record_id text not null check (
    pg_catalog.btrim(source_record_id) <> ''
    and pg_catalog.length(source_record_id) <= 255
  ),
  source_revision integer not null check (source_revision >= 1),
  fact_sha256 text not null check (fact_sha256 ~ '^[0-9a-f]{64}$'),
  coverage_through date not null,
  gap_code text,
  ledger_state_digest text not null check (
    ledger_state_digest ~ '^[0-9a-f]{64}$'
  ),
  primary key (assessment_id, ordinal),
  unique (assessment_id, kind, issuer),
  foreign key (assessment_id, company_id, income_year)
    references ledger.company_year_close_assessments(id, company_id, income_year)
    on delete restrict,
  check (
    (kind = 'BANK_ROWS_RESOLVED' and issuer = 'BANKING')
    or (kind = 'MATERIAL_BALANCES_DOCUMENTED' and issuer = 'DOCUMENTS')
    or (kind = 'REPORTING_RECONCILED' and issuer = 'LEDGER')
  ),
  check (
    (status = 'CONFIRMED' and gap_code is null)
    or (
      status in ('GAP', 'UNKNOWN')
      and gap_code = case kind
        when 'BANK_ROWS_RESOLVED' then 'UNRESOLVED_BANK_ROW'
        when 'MATERIAL_BALANCES_DOCUMENTED' then 'MATERIAL_BALANCE_UNDOCUMENTED'
        when 'REPORTING_RECONCILED' then 'REPORTING_NOT_RECONCILED'
      end
    )
  )
);

create table if not exists ledger.company_year_close_reporting_outputs (
  assessment_id uuid not null,
  company_id uuid not null,
  income_year integer not null,
  ordinal integer not null check (ordinal between 1 and 7),
  kind text not null check (kind in (
    'INVESTMENTS', 'CORPORATE_GOVERNANCE',
    'SHAREHOLDER_REGISTER_FILING', 'COMPANY_TAX_FILING',
    'ANNUAL_ACCOUNTS_FILING', 'SAF_T', 'COMPANY_ARCHIVE'
  )),
  source_record_id text not null check (
    pg_catalog.btrim(source_record_id) <> ''
    and pg_catalog.length(source_record_id) <= 255
  ),
  source_revision integer not null check (source_revision >= 1),
  fact_sha256 text not null check (fact_sha256 ~ '^[0-9a-f]{64}$'),
  ledger_state_digest text not null check (
    ledger_state_digest ~ '^[0-9a-f]{64}$'
  ),
  primary key (assessment_id, ordinal),
  unique (assessment_id, kind),
  foreign key (assessment_id, company_id, income_year)
    references ledger.company_year_close_assessments(id, company_id, income_year)
    on delete restrict
);

alter table ledger.company_year_close_locks enable row level security;
alter table ledger.company_year_close_locks force row level security;
alter table ledger.company_year_close_assessments enable row level security;
alter table ledger.company_year_close_assessments force row level security;
alter table ledger.company_year_close_evidence enable row level security;
alter table ledger.company_year_close_evidence force row level security;
alter table ledger.company_year_close_reporting_outputs enable row level security;
alter table ledger.company_year_close_reporting_outputs force row level security;

drop policy if exists "ledger store reads company year close locks"
  on ledger.company_year_close_locks;
create policy "ledger store reads company year close locks"
on ledger.company_year_close_locks for select to ledger_store_owner
using (public.company_access_is_accepted_member_v1(company_id));
drop policy if exists "ledger store records company year close locks"
  on ledger.company_year_close_locks;
create policy "ledger store records company year close locks"
on ledger.company_year_close_locks for insert to ledger_store_owner
with check (
  locked_by = public.company_access_auth_uid_v1()
  and public.company_access_is_accepted_owner_v1(company_id)
  and public.company_access_company_year_allows_consequential_v1(
    company_id, income_year
  )
);

drop policy if exists "ledger store reads company year close assessments"
  on ledger.company_year_close_assessments;
create policy "ledger store reads company year close assessments"
on ledger.company_year_close_assessments for select to ledger_store_owner
using (public.company_access_is_accepted_member_v1(company_id));
drop policy if exists "ledger store records company year close assessments"
  on ledger.company_year_close_assessments;
create policy "ledger store records company year close assessments"
on ledger.company_year_close_assessments for insert to ledger_store_owner
with check (
  recorded_by = public.company_access_auth_uid_v1()
  and public.company_access_is_accepted_owner_v1(company_id)
  and public.company_access_company_year_allows_consequential_v1(
    company_id, income_year
  )
);

drop policy if exists "ledger store reads company year close evidence"
  on ledger.company_year_close_evidence;
create policy "ledger store reads company year close evidence"
on ledger.company_year_close_evidence for select to ledger_store_owner
using (public.company_access_is_accepted_member_v1(company_id));
drop policy if exists "ledger store records company year close evidence"
  on ledger.company_year_close_evidence;
create policy "ledger store records company year close evidence"
on ledger.company_year_close_evidence for insert to ledger_store_owner
with check (
  public.company_access_is_accepted_owner_v1(company_id)
  and public.company_access_company_year_allows_consequential_v1(
    company_id, income_year
  )
);

drop policy if exists "ledger store reads company year close reporting outputs"
  on ledger.company_year_close_reporting_outputs;
create policy "ledger store reads company year close reporting outputs"
on ledger.company_year_close_reporting_outputs for select to ledger_store_owner
using (public.company_access_is_accepted_member_v1(company_id));
drop policy if exists "ledger store records company year close reporting outputs"
  on ledger.company_year_close_reporting_outputs;
create policy "ledger store records company year close reporting outputs"
on ledger.company_year_close_reporting_outputs for insert to ledger_store_owner
with check (
  public.company_access_is_accepted_owner_v1(company_id)
  and public.company_access_company_year_allows_consequential_v1(
    company_id, income_year
  )
);

create or replace function ledger.company_year_close_is_current_v1(
  p_assessment_id uuid,
  p_company_id uuid,
  p_income_year integer
)
returns boolean
language sql
stable
security definer
set search_path = ''
as $function$
  select exists (
    select 1
    from ledger.company_year_close_assessments assessment
    where assessment.id = p_assessment_id
      and assessment.company_id = p_company_id
      and assessment.income_year = p_income_year
      and assessment.id = (
        select latest.id
        from ledger.company_year_close_assessments latest
        where latest.company_id = p_company_id
          and latest.income_year = p_income_year
        order by latest.recorded_at desc, latest.id desc
        limit 1
      )
      and assessment.reconstruction_assessment_id = (
        select reconstruction.id
        from ledger.reconstruction_assessments reconstruction
        where reconstruction.company_id = p_company_id
          and reconstruction.income_year = p_income_year
        order by reconstruction.recorded_at desc, reconstruction.id desc
        limit 1
      )
      and assessment.ledger_state_digest =
        ledger.company_year_ledger_state_digest_v1(p_company_id, p_income_year)
      and exists (
        select 1
        from ledger.reconstruction_assessments reconstruction
        where reconstruction.id = assessment.reconstruction_assessment_id
          and reconstruction.ledger_state_digest = assessment.ledger_state_digest
      )
      and not exists (
        select 1 from ledger.company_year_close_evidence evidence
        where evidence.assessment_id = assessment.id
          and evidence.ledger_state_digest <> assessment.ledger_state_digest
      )
      and not exists (
        select 1 from ledger.company_year_close_reporting_outputs output
        where output.assessment_id = assessment.id
          and output.ledger_state_digest <> assessment.ledger_state_digest
      )
  );
$function$;

create or replace function ledger.get_company_year_close_replay_v1(
  p_idempotency_key text,
  p_company_id uuid,
  p_income_year integer,
  p_period_end date,
  p_reason text,
  p_reconstruction_assessment_id uuid,
  p_reconstruction_digest text,
  p_evidence jsonb,
  p_correlation_id text,
  p_verified_subject text
)
returns table (
  assessment_id uuid,
  reconstruction_assessment_id uuid,
  close_lock_id uuid,
  company_id uuid,
  income_year integer,
  period_end date,
  state text,
  gap_codes text[],
  evidence_digest text,
  ledger_state_digest text,
  recorded_at timestamptz,
  is_current boolean,
  replayed boolean
)
language plpgsql
security definer
set search_path = ''
as $function$
declare
  v_actor_id uuid := public.company_access_auth_uid_v1();
  v_receipt backend_system.ledger_command_receipts%rowtype;
  v_fingerprint text;
begin
  if pg_catalog.to_regclass('ledger.entries') is null then
    raise exception 'ledger_cutover_inactive';
  end if;
  if v_actor_id is null
    or p_verified_subject is null
    or p_verified_subject !~ '^[0-9a-fA-F-]{36}$'
    or v_actor_id is distinct from p_verified_subject::uuid
  then
    raise exception 'ledger_forbidden';
  end if;
  if p_company_id is null
    or p_income_year not between 2000 and 2100
    or p_period_end is null
    or extract(year from p_period_end)::integer <> p_income_year
    or coalesce(p_idempotency_key, '') !~ '^[A-Za-z0-9._:-]{16,255}$'
    or pg_catalog.btrim(coalesce(p_reason, '')) = ''
    or pg_catalog.length(p_reason) > 500
    or p_reconstruction_assessment_id is null
    or coalesce(p_reconstruction_digest, '') !~ '^[0-9a-f]{64}$'
    or pg_catalog.jsonb_typeof(p_evidence) is distinct from 'array'
    or coalesce(p_correlation_id, '') !~ '^[A-Za-z0-9._:-]{1,80}$'
  then
    raise exception 'ledger_invalid_input';
  end if;
  if not public.company_access_is_accepted_member_v1(p_company_id) then
    raise exception 'ledger_not_found';
  end if;
  if not public.company_access_is_accepted_owner_v1(p_company_id) then
    raise exception 'ledger_forbidden';
  end if;
  v_fingerprint := ledger.company_year_close_request_fingerprint_v1(
    p_company_id, p_income_year, p_period_end, p_reason,
    p_reconstruction_assessment_id, p_reconstruction_digest, p_evidence,
    p_correlation_id
  );
  if not pg_catalog.pg_try_advisory_xact_lock(pg_catalog.hashtextextended(
    'ledger:v1:' || v_actor_id::text || ':' || p_company_id::text
      || ':close_company_year:' || p_idempotency_key,
    0
  )) then
    raise exception 'ledger_idempotency_in_progress';
  end if;
  select receipt.* into v_receipt
  from backend_system.ledger_command_receipts receipt
  where receipt.api_major = 'v1'
    and receipt.actor_id = v_actor_id
    and receipt.company_id = p_company_id
    and receipt.operation_name = 'close_company_year'
    and receipt.idempotency_key = p_idempotency_key;
  if not found then
    return;
  end if;
  if v_receipt.request_fingerprint <> v_fingerprint then
    raise exception 'ledger_idempotency_key_reused';
  end if;
  return query select
    (v_receipt.result ->> 'assessment_id')::uuid,
    (v_receipt.result ->> 'reconstruction_assessment_id')::uuid,
    (v_receipt.result ->> 'close_lock_id')::uuid,
    (v_receipt.result ->> 'company_id')::uuid,
    (v_receipt.result ->> 'income_year')::integer,
    (v_receipt.result ->> 'period_end')::date,
    v_receipt.result ->> 'state',
    array(select pg_catalog.jsonb_array_elements_text(
      v_receipt.result -> 'gap_codes'
    )),
    v_receipt.result ->> 'evidence_digest',
    v_receipt.result ->> 'ledger_state_digest',
    (v_receipt.result ->> 'recorded_at')::timestamptz,
    ledger.company_year_close_is_current_v1(
      (v_receipt.result ->> 'assessment_id')::uuid,
      p_company_id, p_income_year
    ),
    true;
end;
$function$;

create or replace function ledger.get_company_year_close_assessment_v1(
  p_company_id uuid,
  p_income_year integer,
  p_verified_subject text
)
returns table (
  assessment_id uuid,
  reconstruction_assessment_id uuid,
  close_lock_id uuid,
  company_id uuid,
  income_year integer,
  period_end date,
  state text,
  gap_codes text[],
  evidence_digest text,
  ledger_state_digest text,
  recorded_at timestamptz,
  is_current boolean,
  replayed boolean
)
language plpgsql
security definer
set search_path = ''
as $function$
begin
  if pg_catalog.to_regclass('ledger.entries') is null then
    raise exception 'ledger_cutover_inactive';
  end if;
  if public.company_access_auth_uid_v1() is null
    or p_verified_subject is null
    or p_verified_subject !~ '^[0-9a-fA-F-]{36}$'
    or public.company_access_auth_uid_v1() is distinct from p_verified_subject::uuid
  then
    raise exception 'ledger_forbidden';
  end if;
  if not public.company_access_is_accepted_member_v1(p_company_id) then
    raise exception 'ledger_not_found';
  end if;
  return query
  select assessment.id, assessment.reconstruction_assessment_id,
    assessment.close_lock_id, assessment.company_id, assessment.income_year,
    assessment.period_end, assessment.state, assessment.gap_codes,
    assessment.evidence_digest, assessment.ledger_state_digest,
    assessment.recorded_at,
    ledger.company_year_close_is_current_v1(
      assessment.id, assessment.company_id, assessment.income_year
    ),
    false
  from ledger.company_year_close_assessments assessment
  where assessment.company_id = p_company_id
    and assessment.income_year = p_income_year
  order by assessment.recorded_at desc, assessment.id desc
  limit 1;
end;
$function$;

create or replace function ledger.bind_reconstruction_ledger_state_v1()
returns trigger
language plpgsql
security definer
set search_path = ''
as $function$
begin
  new.ledger_state_digest := ledger.company_year_ledger_state_digest_v1(
    new.company_id, new.income_year
  );
  return new;
end;
$function$;

drop trigger if exists reconstruction_assessments_bind_ledger_state
  on ledger.reconstruction_assessments;
create trigger reconstruction_assessments_bind_ledger_state
before insert on ledger.reconstruction_assessments
for each row execute function ledger.bind_reconstruction_ledger_state_v1();

create index if not exists ledger_company_year_close_assessments_lookup_idx
  on ledger.company_year_close_assessments(
    company_id, income_year, recorded_at desc, id desc
  );
create index if not exists ledger_company_year_close_assessments_reconstruction_idx
  on ledger.company_year_close_assessments(reconstruction_assessment_id);
create index if not exists ledger_company_year_close_evidence_company_year_idx
  on ledger.company_year_close_evidence(company_id, income_year, assessment_id);
create index if not exists ledger_company_year_close_outputs_company_year_idx
  on ledger.company_year_close_reporting_outputs(
    company_id, income_year, assessment_id
  );

create or replace function ledger.company_year_close_request_fingerprint_v1(
  p_company_id uuid,
  p_income_year integer,
  p_period_end date,
  p_reason text,
  p_reconstruction_assessment_id uuid,
  p_reconstruction_digest text,
  p_evidence jsonb,
  p_correlation_id text
)
returns text
language sql
immutable
set search_path = ''
as $function$
  select pg_catalog.encode(extensions.digest(
    pg_catalog.jsonb_build_object(
      'companyId', p_company_id,
      'incomeYear', p_income_year,
      'periodEnd', p_period_end,
      'reason', pg_catalog.btrim(p_reason),
      'reconstructionAssessmentId', p_reconstruction_assessment_id,
      'reconstructionDigest', p_reconstruction_digest,
      'evidence', p_evidence,
      'correlationId', p_correlation_id
    )::text,
    'sha256'
  ), 'hex');
$function$;

revoke all on ledger.company_year_close_locks,
  ledger.company_year_close_assessments,
  ledger.company_year_close_evidence,
  ledger.company_year_close_reporting_outputs
from public, anon, authenticated, service_role, ledger_executor,
  ledger_workflow_executor, talli_ledger_backend;
grant select, insert on ledger.company_year_close_locks,
  ledger.company_year_close_assessments,
  ledger.company_year_close_evidence,
  ledger.company_year_close_reporting_outputs
to ledger_store_owner;

revoke all on function
  ledger.company_year_ledger_state_digest_v1(uuid, integer),
  ledger.bind_reconstruction_ledger_state_v1(),
  ledger.company_year_close_request_fingerprint_v1(
    uuid, integer, date, text, uuid, text, jsonb, text
  ),
  ledger.company_year_close_is_current_v1(uuid, uuid, integer),
  ledger.record_reconstruction_assessment_without_state_digest_v1(
    text, uuid, integer, date, jsonb, text, text[], text, text
  ),
  ledger.get_reconstruction_assessment_without_state_digest_v1(
    uuid, integer, text
  ),
  ledger.record_reconstruction_assessment(
    text, uuid, integer, date, jsonb, text, text[], text, text
  ),
  ledger.get_reconstruction_assessment(uuid, integer, text),
  ledger.get_company_year_close_replay_v1(
    text, uuid, integer, date, text, uuid, text, jsonb, text, text
  ),
  ledger.get_company_year_close_assessment_v1(uuid, integer, text),
  ledger.close_company_year_v1(
    text, uuid, integer, date, text, uuid, text, jsonb,
    text, text[], text, text
  )
from public, anon, authenticated, service_role, ledger_executor,
  ledger_workflow_executor, talli_ledger_backend;

grant execute on function
  ledger.record_reconstruction_assessment(
    text, uuid, integer, date, jsonb, text, text[], text, text
  ),
  ledger.get_reconstruction_assessment(uuid, integer, text),
  ledger.get_company_year_close_replay_v1(
    text, uuid, integer, date, text, uuid, text, jsonb, text, text
  ),
  ledger.get_company_year_close_assessment_v1(uuid, integer, text),
  ledger.close_company_year_v1(
    text, uuid, integer, date, text, uuid, text, jsonb,
    text, text[], text, text
  )
to ledger_executor;

alter table ledger.company_year_close_locks owner to ledger_store_owner;
alter table ledger.company_year_close_assessments owner to ledger_store_owner;
alter table ledger.company_year_close_evidence owner to ledger_store_owner;
alter table ledger.company_year_close_reporting_outputs owner to ledger_store_owner;
alter function ledger.company_year_ledger_state_digest_v1(uuid, integer)
  owner to ledger_store_owner;
alter function ledger.bind_reconstruction_ledger_state_v1()
  owner to ledger_store_owner;
alter function ledger.company_year_close_request_fingerprint_v1(
  uuid, integer, date, text, uuid, text, jsonb, text
) owner to ledger_store_owner;
alter function ledger.company_year_close_is_current_v1(uuid, uuid, integer)
  owner to ledger_store_owner;
alter function ledger.record_reconstruction_assessment(
  text, uuid, integer, date, jsonb, text, text[], text, text
) owner to ledger_store_owner;
alter function ledger.get_reconstruction_assessment(uuid, integer, text)
  owner to ledger_store_owner;
alter function ledger.get_company_year_close_replay_v1(
  text, uuid, integer, date, text, uuid, text, jsonb, text, text
) owner to ledger_store_owner;
alter function ledger.get_company_year_close_assessment_v1(
  uuid, integer, text
) owner to ledger_store_owner;
alter function ledger.close_company_year_v1(
  text, uuid, integer, date, text, uuid, text, jsonb,
  text, text[], text, text
) owner to ledger_store_owner;

drop trigger if exists ledger_company_year_close_locks_immutable
  on ledger.company_year_close_locks;
create trigger ledger_company_year_close_locks_immutable
before update or delete on ledger.company_year_close_locks
for each row execute function backend_system.prevent_ledger_technical_mutation();

drop trigger if exists ledger_company_year_close_assessments_immutable
  on ledger.company_year_close_assessments;
create trigger ledger_company_year_close_assessments_immutable
before update or delete on ledger.company_year_close_assessments
for each row execute function backend_system.prevent_ledger_technical_mutation();

drop trigger if exists ledger_company_year_close_evidence_immutable
  on ledger.company_year_close_evidence;
create trigger ledger_company_year_close_evidence_immutable
before update or delete on ledger.company_year_close_evidence
for each row execute function backend_system.prevent_ledger_technical_mutation();

drop trigger if exists ledger_company_year_close_reporting_outputs_immutable
  on ledger.company_year_close_reporting_outputs;
create trigger ledger_company_year_close_reporting_outputs_immutable
before update or delete on ledger.company_year_close_reporting_outputs
for each row execute function backend_system.prevent_ledger_technical_mutation();

-- Refresh the delegate from whichever canonical post_entry the earlier
-- recutover migrations installed. The wrapper owns no accounting selection;
-- it adds only receipt-first statutory-close serialization.
do $ledger_refresh_post_entry_close_delegate$
begin
  if pg_catalog.to_regprocedure(
    'ledger.post_entry_without_company_year_close_lock_v1(text,uuid,integer,text,text,jsonb,jsonb,boolean,text,text,text,text)'
  ) is not null then
    drop function ledger.post_entry_without_company_year_close_lock_v1(
      text, uuid, integer, text, text, jsonb, jsonb, boolean,
      text, text, text, text
    );
  end if;
  alter function ledger.post_entry(
    text, uuid, integer, text, text, jsonb, jsonb, boolean,
    text, text, text, text
  ) rename to post_entry_without_company_year_close_lock_v1;
end
$ledger_refresh_post_entry_close_delegate$;

create or replace function ledger.post_entry(
  p_idempotency_key text,
  p_company_id uuid,
  p_income_year integer,
  p_entry_kind text,
  p_memo text,
  p_lines jsonb,
  p_risk_flags jsonb,
  p_warning_accepted boolean,
  p_source_capability text,
  p_source_record_id text,
  p_correlation_id text,
  p_verified_subject text
)
returns table (
  ledger_entry_id uuid,
  company_id uuid,
  income_year integer,
  entry_kind text,
  posted_at timestamptz,
  replayed boolean
)
language plpgsql
security definer
set search_path = ''
as $function$
declare
  v_actor_id uuid := public.company_access_auth_uid_v1();
  v_has_receipt boolean;
begin
  if pg_catalog.to_regclass('ledger.entries') is null then
    raise exception 'ledger_cutover_inactive';
  end if;

  -- Preserve the canonical delegate's validation/error ordering when the
  -- receipt scope itself cannot be resolved safely.
  if v_actor_id is null
    or p_verified_subject is null
    or p_verified_subject !~ '^[0-9a-fA-F-]{36}$'
    or v_actor_id is distinct from p_verified_subject::uuid
    or p_company_id is null
    or p_income_year not between 2000 and 2100
    or coalesce(p_idempotency_key, '') !~ '^[A-Za-z0-9._:-]{16,255}$'
  then
    return query select *
    from ledger.post_entry_without_company_year_close_lock_v1(
      p_idempotency_key, p_company_id, p_income_year, p_entry_kind, p_memo,
      p_lines, p_risk_flags, p_warning_accepted, p_source_capability,
      p_source_record_id, p_correlation_id, p_verified_subject
    );
    return;
  end if;

  select exists (
    select 1
    from backend_system.ledger_command_receipts receipt
    where receipt.api_major = 'v1'
      and receipt.actor_id = v_actor_id
      and receipt.company_id = p_company_id
      and receipt.operation_name = 'post_entry'
      and receipt.idempotency_key = p_idempotency_key
  ) into v_has_receipt;

  if not v_has_receipt then
    perform ledger.lock_company_year_v1(p_company_id, p_income_year);

    -- A command may have completed while this transaction waited behind the
    -- company-year lock. Its immutable receipt still wins over a later close.
    select exists (
      select 1
      from backend_system.ledger_command_receipts receipt
      where receipt.api_major = 'v1'
        and receipt.actor_id = v_actor_id
        and receipt.company_id = p_company_id
        and receipt.operation_name = 'post_entry'
        and receipt.idempotency_key = p_idempotency_key
    ) into v_has_receipt;

    if not v_has_receipt and exists (
      select 1
      from ledger.company_year_close_locks close_lock
      where close_lock.company_id = p_company_id
        and close_lock.income_year = p_income_year
    ) then
      raise exception 'ledger_period_locked';
    end if;
  end if;

  return query select *
  from ledger.post_entry_without_company_year_close_lock_v1(
    p_idempotency_key, p_company_id, p_income_year, p_entry_kind, p_memo,
    p_lines, p_risk_flags, p_warning_accepted, p_source_capability,
    p_source_record_id, p_correlation_id, p_verified_subject
  );
end;
$function$;

revoke all on function
  ledger.post_entry_without_company_year_close_lock_v1(
    text, uuid, integer, text, text, jsonb, jsonb, boolean,
    text, text, text, text
  ),
  ledger.post_entry(
    text, uuid, integer, text, text, jsonb, jsonb, boolean,
    text, text, text, text
  )
from public, anon, authenticated, service_role, ledger_executor,
  ledger_workflow_executor, talli_ledger_backend;
grant execute on function ledger.post_entry(
  text, uuid, integer, text, text, jsonb, jsonb, boolean,
  text, text, text, text
) to ledger_executor, ledger_workflow_executor;

alter function ledger.post_entry(
  text, uuid, integer, text, text, jsonb, jsonb, boolean,
  text, text, text, text
) owner to ledger_store_owner;

do $ledger_company_year_close_migration_authority_revoke$
begin
  execute pg_catalog.format('revoke create on schema ledger from %I', current_user);
  revoke create on schema ledger from ledger_store_owner;
  execute pg_catalog.format('revoke ledger_store_owner from %I', current_user);
end
$ledger_company_year_close_migration_authority_revoke$;

commit;
