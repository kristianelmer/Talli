-- Issue #188 expand: immutable January-to-date reconstruction evidence.
-- Posting/lock enforcement remains disabled until the #188 contract migration.

create table ledger.reconstruction_assessments (
  id uuid primary key default pg_catalog.gen_random_uuid(),
  company_id uuid not null references public.companies(id) on delete restrict,
  income_year integer not null check (income_year between 2000 and 2100),
  as_of date not null,
  state text not null check (state in ('BLOCKED', 'READY')),
  gap_codes text[] not null,
  evidence_digest text not null check (evidence_digest ~ '^[0-9a-f]{64}$'),
  correlation_id text not null check (
    correlation_id ~ '^[A-Za-z0-9._:-]{1,80}$'
  ),
  recorded_by uuid not null,
  recorded_at timestamptz not null default pg_catalog.statement_timestamp(),
  unique (id, company_id, income_year),
  check (extract(year from as_of)::integer = income_year),
  check (
    (state = 'READY' and pg_catalog.cardinality(gap_codes) = 0)
    or (state = 'BLOCKED' and pg_catalog.cardinality(gap_codes) > 0)
  )
);

create table ledger.reconstruction_evidence (
  assessment_id uuid not null,
  company_id uuid not null,
  income_year integer not null,
  ordinal integer not null check (ordinal between 1 and 13),
  kind text not null,
  issuer text not null,
  confirmation text not null check (confirmation in ('CONFIRMED', 'GAP', 'UNKNOWN')),
  source_record_id text not null check (
    pg_catalog.btrim(source_record_id) <> ''
    and pg_catalog.length(source_record_id) <= 255
  ),
  fact_sha256 text not null check (fact_sha256 ~ '^[0-9a-f]{64}$'),
  coverage_from date,
  coverage_through date,
  gap_code text,
  primary key (assessment_id, ordinal),
  unique (assessment_id, kind, issuer),
  foreign key (assessment_id, company_id, income_year)
    references ledger.reconstruction_assessments(id, company_id, income_year)
    on delete restrict,
  check ((coverage_from is null) = (coverage_through is null)),
  check (coverage_from is null or coverage_from <= coverage_through),
  check (
    (confirmation = 'CONFIRMED' and gap_code is null)
    or (
      confirmation in ('GAP', 'UNKNOWN')
      and pg_catalog.btrim(coalesce(gap_code, '')) <> ''
    )
  )
);

create index reconstruction_assessments_company_year_idx
  on ledger.reconstruction_assessments(
    company_id, income_year, recorded_at desc, id desc
  );

alter table ledger.reconstruction_assessments enable row level security;
alter table ledger.reconstruction_assessments force row level security;
alter table ledger.reconstruction_evidence enable row level security;
alter table ledger.reconstruction_evidence force row level security;

create policy "ledger store reads reconstruction assessments"
on ledger.reconstruction_assessments for select to ledger_store_owner
using (public.company_access_is_accepted_member_v1(company_id));

create policy "ledger store records reconstruction assessments"
on ledger.reconstruction_assessments for insert to ledger_store_owner
with check (
  public.company_access_is_accepted_owner_v1(company_id)
  and recorded_by = public.company_access_auth_uid_v1()
);

create policy "ledger store reads reconstruction evidence"
on ledger.reconstruction_evidence for select to ledger_store_owner
using (public.company_access_is_accepted_member_v1(company_id));

create policy "ledger store records reconstruction evidence"
on ledger.reconstruction_evidence for insert to ledger_store_owner
with check (public.company_access_is_accepted_owner_v1(company_id));

alter table backend_system.ledger_command_receipts
  drop constraint ledger_command_receipts_operation_name_check;
alter table backend_system.ledger_command_receipts
  add constraint ledger_command_receipts_operation_name_check
  check (operation_name in ('post_entry', 'lock_period', 'record_reconstruction'));

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
  recorded_at timestamptz,
  replayed boolean
)
language plpgsql
security definer
set search_path = ''
as $function$
declare
  v_actor_id uuid := public.company_access_auth_uid_v1();
  v_receipt backend_system.ledger_command_receipts%rowtype;
  v_assessment_id uuid;
  v_recorded_at timestamptz := pg_catalog.statement_timestamp();
  v_evidence_digest text;
  v_computed_state text;
  v_computed_gaps text[];
  v_fingerprint text;
  v_result jsonb;
begin
  if v_actor_id is null
    or p_verified_subject is null
    or p_verified_subject !~ '^[0-9a-fA-F-]{36}$'
    or v_actor_id is distinct from p_verified_subject::uuid
  then
    raise exception 'ledger_forbidden';
  end if;
  if p_company_id is null
    or p_income_year not between 2000 and 2100
    or extract(year from p_as_of)::integer <> p_income_year
    or coalesce(p_idempotency_key, '') !~ '^[A-Za-z0-9._:-]{16,255}$'
    or coalesce(p_correlation_id, '') !~ '^[A-Za-z0-9._:-]{1,80}$'
    or pg_catalog.jsonb_typeof(p_evidence) is distinct from 'array'
    or pg_catalog.jsonb_array_length(p_evidence) <> 13
  then
    raise exception 'ledger_invalid_input';
  end if;
  if not public.company_access_is_accepted_member_v1(p_company_id) then
    raise exception 'ledger_not_found';
  end if;
  if not public.company_access_is_accepted_owner_v1(p_company_id) then
    raise exception 'ledger_forbidden';
  end if;
  if not public.company_access_company_year_allows_consequential_v1(
    p_company_id, p_income_year
  ) then
    raise exception 'ledger_company_year_not_admitted';
  end if;

  if exists (
    with expected(kind, issuer) as (values
      ('PRIOR_CLOSING_OPENING', 'LEDGER'),
      ('BANK_MOVEMENTS', 'BANKING'),
      ('BANK_RECONCILIATION', 'BANKING'),
      ('INVESTMENTS', 'INVESTMENTS'),
      ('SHAREHOLDERS', 'SHAREHOLDER_REGISTER_FILING'),
      ('LOANS', 'BANKING'),
      ('LOANS', 'CORPORATE_GOVERNANCE'),
      ('EQUITY', 'CORPORATE_GOVERNANCE'),
      ('EQUITY', 'SHAREHOLDER_REGISTER_FILING'),
      ('TAX_HISTORY', 'COMPANY_TAX_FILING'),
      ('CURRENT_YEAR_ACTIVITY', 'LEDGER'),
      ('DOCUMENTS', 'DOCUMENTS'),
      ('UNSUPPORTED_ACTIVITY_CHECK', 'COMPANY_ACCESS')
    ), supplied as (
      select item ->> 'kind' kind, item ->> 'issuer' issuer
      from pg_catalog.jsonb_array_elements(p_evidence) item
    )
    (select * from expected except all select * from supplied)
    union all
    (select * from supplied except all select * from expected)
  ) then
    raise exception 'ledger_reconstruction_evidence_incomplete';
  end if;

  if exists (
    select 1
    from pg_catalog.jsonb_array_elements(p_evidence) item
    where item ->> 'confirmation' not in ('CONFIRMED', 'GAP', 'UNKNOWN')
      or coalesce(item ->> 'sourceRecordId', '') = ''
      or coalesce(item ->> 'factSha256', '') !~ '^[0-9a-f]{64}$'
      or (
        (item ? 'coverageFrom') is distinct from (item ? 'coverageThrough')
      )
      or (
        item ->> 'confirmation' = 'CONFIRMED'
        and item ->> 'gapCode' is not null
      )
      or (
        item ->> 'confirmation' in ('GAP', 'UNKNOWN')
        and coalesce(item ->> 'gapCode', '') = ''
      )
      or (
        item ->> 'gapCode' is not null
        and item ->> 'gapCode' <> case item ->> 'kind'
          when 'PRIOR_CLOSING_OPENING' then 'PRIOR_CLOSING_MISMATCH'
          when 'BANK_MOVEMENTS' then 'BANK_MOVEMENTS_INCOMPLETE'
          when 'BANK_RECONCILIATION' then 'BANK_NOT_RECONCILED'
          when 'INVESTMENTS' then 'INVESTMENTS_UNCONFIRMED'
          when 'SHAREHOLDERS' then 'SHAREHOLDERS_UNCONFIRMED'
          when 'LOANS' then 'LOANS_UNCONFIRMED'
          when 'EQUITY' then 'EQUITY_UNCONFIRMED'
          when 'TAX_HISTORY' then 'TAX_HISTORY_UNCONFIRMED'
          when 'CURRENT_YEAR_ACTIVITY' then 'CURRENT_ACTIVITY_INCOMPLETE'
          when 'DOCUMENTS' then 'DOCUMENTS_INCOMPLETE'
          when 'UNSUPPORTED_ACTIVITY_CHECK' then 'UNSUPPORTED_ACTIVITY_FOUND'
        end
      )
      or (
        item ->> 'kind' in ('BANK_MOVEMENTS', 'CURRENT_YEAR_ACTIVITY')
        and (
          coalesce(item ->> 'coverageFrom', '') = ''
          or coalesce(item ->> 'coverageThrough', '') = ''
          or (item ->> 'coverageFrom')::date <> pg_catalog.make_date(p_income_year, 1, 1)
          or (item ->> 'coverageThrough')::date <> p_as_of
        )
      )
  ) then
    raise exception 'ledger_invalid_input';
  end if;

  select coalesce(
    pg_catalog.array_agg(item ->> 'gapCode' order by ordinal)
      filter (where item ->> 'confirmation' <> 'CONFIRMED'),
    '{}'::text[]
  ) into v_computed_gaps
  from pg_catalog.jsonb_array_elements(p_evidence) with ordinality source(item, ordinal);
  v_computed_state := case
    when pg_catalog.cardinality(v_computed_gaps) = 0 then 'READY'
    else 'BLOCKED'
  end;
  if p_state is distinct from v_computed_state
    or p_gap_codes is distinct from v_computed_gaps
  then
    raise exception 'ledger_invalid_input';
  end if;

  v_evidence_digest := pg_catalog.encode(
    extensions.digest(p_evidence::text, 'sha256'), 'hex'
  );
  v_fingerprint := pg_catalog.encode(extensions.digest(
    pg_catalog.jsonb_build_object(
      'companyId', p_company_id,
      'incomeYear', p_income_year,
      'asOf', p_as_of,
      'evidenceDigest', v_evidence_digest,
      'state', v_computed_state,
      'gapCodes', v_computed_gaps,
      'correlationId', p_correlation_id
    )::text,
    'sha256'
  ), 'hex');

  perform ledger.lock_company_year_v1(p_company_id, p_income_year);
  if not pg_catalog.pg_try_advisory_xact_lock(pg_catalog.hashtextextended(
    'ledger:v1:' || v_actor_id::text || ':' || p_company_id::text
      || ':record_reconstruction:' || p_idempotency_key,
    0
  )) then
    raise exception 'ledger_idempotency_in_progress';
  end if;
  select receipt.* into v_receipt
  from backend_system.ledger_command_receipts receipt
  where receipt.api_major = 'v1'
    and receipt.actor_id = v_actor_id
    and receipt.company_id = p_company_id
    and receipt.operation_name = 'record_reconstruction'
    and receipt.idempotency_key = p_idempotency_key;
  if found then
    if v_receipt.request_fingerprint <> v_fingerprint then
      raise exception 'ledger_idempotency_key_reused';
    end if;
    return query select
      (v_receipt.result ->> 'assessment_id')::uuid,
      (v_receipt.result ->> 'company_id')::uuid,
      (v_receipt.result ->> 'income_year')::integer,
      (v_receipt.result ->> 'as_of')::date,
      v_receipt.result ->> 'state',
      array(select pg_catalog.jsonb_array_elements_text(v_receipt.result -> 'gap_codes')),
      v_receipt.result ->> 'evidence_digest',
      (v_receipt.result ->> 'recorded_at')::timestamptz,
      true;
    return;
  end if;

  v_assessment_id := pg_catalog.gen_random_uuid();
  insert into ledger.reconstruction_assessments (
    id, company_id, income_year, as_of, state, gap_codes, evidence_digest,
    correlation_id, recorded_by, recorded_at
  ) values (
    v_assessment_id, p_company_id, p_income_year, p_as_of, v_computed_state,
    v_computed_gaps, v_evidence_digest, p_correlation_id, v_actor_id, v_recorded_at
  );

  insert into ledger.reconstruction_evidence (
    assessment_id, company_id, income_year, ordinal, kind, issuer, confirmation,
    source_record_id, fact_sha256, coverage_from, coverage_through, gap_code
  )
  select
    v_assessment_id, p_company_id, p_income_year, ordinal::integer,
    item ->> 'kind', item ->> 'issuer', item ->> 'confirmation',
    item ->> 'sourceRecordId', item ->> 'factSha256',
    (item ->> 'coverageFrom')::date, (item ->> 'coverageThrough')::date,
    item ->> 'gapCode'
  from pg_catalog.jsonb_array_elements(p_evidence) with ordinality source(item, ordinal);

  v_result := pg_catalog.jsonb_build_object(
    'assessment_id', v_assessment_id,
    'company_id', p_company_id,
    'income_year', p_income_year,
    'as_of', p_as_of,
    'state', v_computed_state,
    'gap_codes', pg_catalog.to_jsonb(v_computed_gaps),
    'evidence_digest', v_evidence_digest,
    'recorded_at', v_recorded_at
  );
  insert into backend_system.ledger_command_receipts (
    api_major, actor_id, company_id, operation_name, idempotency_key,
    request_fingerprint, result
  ) values (
    'v1', v_actor_id, p_company_id, 'record_reconstruction', p_idempotency_key,
    v_fingerprint, v_result
  );

  return query select
    v_assessment_id, p_company_id, p_income_year, p_as_of, v_computed_state,
    v_computed_gaps, v_evidence_digest, v_recorded_at, false;
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
  recorded_at timestamptz,
  replayed boolean
)
language plpgsql
security definer
set search_path = ''
as $function$
begin
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
  select
    assessment.id, assessment.company_id, assessment.income_year,
    assessment.as_of, assessment.state, assessment.gap_codes,
    assessment.evidence_digest, assessment.recorded_at, false
  from ledger.reconstruction_assessments assessment
  where assessment.company_id = p_company_id
    and assessment.income_year = p_income_year
  order by assessment.recorded_at desc, assessment.id desc
  limit 1;
end;
$function$;

revoke all on ledger.reconstruction_assessments,
  ledger.reconstruction_evidence from public, anon, authenticated;
grant select, insert on ledger.reconstruction_assessments,
  ledger.reconstruction_evidence to ledger_store_owner;

revoke all on function ledger.record_reconstruction_assessment(
  text, uuid, integer, date, jsonb, text, text[], text, text
) from public, anon, authenticated;
revoke all on function ledger.get_reconstruction_assessment(
  uuid, integer, text
) from public, anon, authenticated;
grant execute on function ledger.record_reconstruction_assessment(
  text, uuid, integer, date, jsonb, text, text[], text, text
) to ledger_executor;
grant execute on function ledger.get_reconstruction_assessment(
  uuid, integer, text
) to ledger_executor;

alter table ledger.reconstruction_assessments owner to ledger_store_owner;
alter table ledger.reconstruction_evidence owner to ledger_store_owner;
alter function ledger.record_reconstruction_assessment(
  text, uuid, integer, date, jsonb, text, text[], text, text
) owner to ledger_store_owner;
alter function ledger.get_reconstruction_assessment(
  uuid, integer, text
) owner to ledger_store_owner;

create trigger reconstruction_assessments_immutable
before update or delete on ledger.reconstruction_assessments
for each row execute function backend_system.prevent_ledger_technical_mutation();

create trigger reconstruction_evidence_immutable
before update or delete on ledger.reconstruction_evidence
for each row execute function backend_system.prevent_ledger_technical_mutation();
