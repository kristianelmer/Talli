-- #190: executable year-end investment measurement with one atomic ledger post.
begin;

set local lock_timeout = '5s';
set local statement_timeout = '120s';

do $authority$
begin
  execute pg_catalog.format('grant ledger_store_owner to %I', current_user);
  execute pg_catalog.format('grant investments_store_owner to %I', current_user);
  execute pg_catalog.format('grant create on schema ledger to %I', current_user);
  grant create on schema ledger to ledger_store_owner;
end
$authority$;

alter table investments.year_end_measurements
  add column idempotency_key text,
  add column request_fingerprint text,
  add column evidence_mode text,
  add column evidence_reference text,
  add column owner_attested boolean;

alter table investments.year_end_measurements
  add constraint year_end_measurements_idempotency_key_check check (
    idempotency_key ~ '^[A-Za-z0-9._:-]{16,255}$'
  ),
  add constraint year_end_measurements_request_fingerprint_check check (
    request_fingerprint ~ '^[0-9a-f]{64}$'
  ),
  add constraint year_end_measurements_evidence_mode_check check (
    evidence_mode in ('linked_sources', 'manual_fallback')
  ),
  add constraint year_end_measurements_evidence_reference_check check (
    nullif(pg_catalog.btrim(evidence_reference), '') is not null
    and pg_catalog.length(evidence_reference) <= 500
  ),
  add constraint year_end_measurements_evidence_authority_check check (
    (evidence_mode = 'linked_sources' and not owner_attested)
    or (evidence_mode = 'manual_fallback' and owner_attested)
  ),
  add constraint year_end_measurements_actor_idempotency_unique
    unique (created_by, company_id, idempotency_key);

create or replace function ledger.enforce_entry_v1()
returns trigger language plpgsql security definer set search_path = ''
as $function$
begin
  new.entry_kind := case pg_catalog.lower(pg_catalog.btrim(new.entry_kind))
    when 'opening_balance' then 'OPENING_BALANCE'
    when 'admin_cost' then 'ADMINISTRATIVE_COST'
    when 'administrative_cost' then 'ADMINISTRATIVE_COST'
    when 'manual_journal' then 'MANUAL_JOURNAL'
    when 'bank_rule_suggestion' then 'BANK_RULE_SUGGESTION'
    when 'dividend_received' then 'DIVIDEND_RECEIVED'
    when 'dividend_to_owner_declared' then 'OWNER_DIVIDEND_DECLARED'
    when 'owner_dividend_declared' then 'OWNER_DIVIDEND_DECLARED'
    when 'dividend_to_owner_payment' then 'OWNER_DIVIDEND_PAYMENT'
    when 'owner_dividend_payment' then 'OWNER_DIVIDEND_PAYMENT'
    when 'share_purchase' then 'SHARE_PURCHASE'
    when 'share_sale' then 'SHARE_SALE'
    when 'shareholder_loan' then 'SHAREHOLDER_LOAN'
    when 'tax_settlement' then 'TAX_SETTLEMENT'
    when 'investment_measurement' then 'INVESTMENT_MEASUREMENT'
    else pg_catalog.upper(pg_catalog.btrim(new.entry_kind))
  end;
  if new.entry_kind not in (
    'OPENING_BALANCE', 'ADMINISTRATIVE_COST', 'MANUAL_JOURNAL',
    'BANK_RULE_SUGGESTION', 'DIVIDEND_RECEIVED',
    'OWNER_DIVIDEND_DECLARED', 'OWNER_DIVIDEND_PAYMENT', 'SHARE_PURCHASE',
    'SHARE_SALE', 'SHAREHOLDER_LOAN', 'TAX_SETTLEMENT',
    'BANK_INTEREST', 'BANK_LOAN', 'CAPITAL_INCREASE',
    'CAPITAL_REDUCTION', 'COMPANY_TAX_ACCRUAL', 'GROUP_CONTRIBUTION',
    'INTERCOMPANY_LOAN', 'CORRECTION_REVERSAL', 'INVESTMENT_MEASUREMENT'
  ) or not ledger.entry_lines_are_valid_v1(new.lines, true) then
    raise exception 'ledger_invalid_input';
  end if;
  new.lines := ledger.normalize_lines_v1(new.lines);
  new.source_capability := coalesce(
    new.source_capability,
    case new.entry_kind
      when 'OPENING_BALANCE' then case
        when nullif(pg_catalog.to_jsonb(new) ->> 'setup_id', '') is not null
        then 'SHAREHOLDER_REGISTER_FILING'
        else 'LEDGER'
      end
      when 'BANK_RULE_SUGGESTION' then 'BANKING'
      when 'DIVIDEND_RECEIVED' then 'INVESTMENTS'
      when 'SHARE_PURCHASE' then 'INVESTMENTS'
      when 'SHARE_SALE' then 'INVESTMENTS'
      when 'INVESTMENT_MEASUREMENT' then 'INVESTMENTS'
      when 'OWNER_DIVIDEND_DECLARED' then 'CORPORATE_GOVERNANCE'
      when 'OWNER_DIVIDEND_PAYMENT' then 'CORPORATE_GOVERNANCE'
      when 'SHAREHOLDER_LOAN' then 'CORPORATE_GOVERNANCE'
      when 'TAX_SETTLEMENT' then 'COMPANY_TAX_FILING'
      when 'BANK_INTEREST' then 'BANKING'
      when 'BANK_LOAN' then 'BANKING'
      when 'CAPITAL_INCREASE' then 'CORPORATE_GOVERNANCE'
      when 'CAPITAL_REDUCTION' then 'CORPORATE_GOVERNANCE'
      when 'COMPANY_TAX_ACCRUAL' then 'COMPANY_TAX_FILING'
      when 'GROUP_CONTRIBUTION' then 'CORPORATE_GOVERNANCE'
      when 'INTERCOMPANY_LOAN' then 'CORPORATE_GOVERNANCE'
      else 'LEDGER'
    end
  );
  new.source_record_id := coalesce(
    nullif(pg_catalog.btrim(new.source_record_id), ''),
    case
      when new.entry_kind = 'OPENING_BALANCE'
        and nullif(pg_catalog.to_jsonb(new) ->> 'setup_id', '') is not null
      then 'opening-setup:' || (pg_catalog.to_jsonb(new) ->> 'setup_id')
      else 'rollback:' || new.id::text
    end
  );
  new.correlation_id := coalesce(
    nullif(pg_catalog.btrim(new.correlation_id), ''),
    'rollback:' || new.id::text
  );
  return new;
end;
$function$;

create or replace function investments.complete_year_end_measurement_v2(
  p_request jsonb, p_entry_id uuid, p_prepared jsonb,
  p_verified_subject text
)
returns jsonb language plpgsql security definer set search_path = ''
as $function$
declare
  v_actor uuid := public.company_access_auth_uid_v1();
  v_company uuid := (p_request ->> 'companyId')::uuid;
  v_position investments.positions%rowtype;
  v_impairment numeric := (p_prepared ->> 'impairmentAmount')::numeric;
  v_document_facts jsonb := p_request -> 'documentFacts';
  v_count integer;
  v_lot_book_total numeric;
  v_last_lot_id uuid;
begin
  if v_actor is null or p_verified_subject !~ '^[0-9a-fA-F-]{36}$'
    or v_actor is distinct from p_verified_subject::uuid
    or not public.company_access_is_accepted_owner_v1(v_company)
  then raise exception 'investments_forbidden'; end if;
  select position.* into v_position from investments.positions position
  where position.id = (p_request ->> 'positionId')::uuid for update;
  if not found or v_position.company_id <> v_company
    or (p_prepared ->> 'positionId')::uuid <> v_position.id
    or (p_prepared ->> 'quantity')::numeric <> v_position.share_count
    or (p_prepared ->> 'sourceBookCost')::numeric <> v_position.cost_basis
    or (p_prepared ->> 'preMeasurementBookValue')::numeric < 0
    or (p_prepared ->> 'observedOrRecoverableValue')::numeric < 0
    or v_impairment < 0
    or (p_prepared ->> 'reversalAmount')::numeric <> 0
    or (p_prepared ->> 'closingBookValue')::numeric < 0
    or (p_prepared ->> 'closingBookValue')::numeric
      <> (p_prepared ->> 'preMeasurementBookValue')::numeric - v_impairment
    or (p_prepared ->> 'taxBasis')::numeric <> v_position.tax_basis
    or p_prepared ->> 'evidenceDigest' !~ '^[0-9a-f]{64}$'
    or p_prepared ->> 'calculationId' !~ '^[0-9a-f]{64}$'
    or (
      v_position.accounting_classification in (
        'current_listed_share', 'current_fund'
      ) and p_prepared ->> 'measurementRule'
        <> 'lower_of_cost_and_fair_value'
    )
    or (
      v_position.accounting_classification in (
        'subsidiary', 'associate', 'other_long_term'
      ) and p_prepared ->> 'measurementRule'
        <> 'cost_with_evidenced_impairment'
    )
    or (v_impairment > 0) <> (p_entry_id is not null)
  then raise exception 'investments_invalid_input'; end if;

  perform 1 from investments.acquisition_lots lot
  where lot.position_id = v_position.id
    and lot.company_id = v_company
    and lot.remaining_share_count > 0
  order by lot.acquisition_date, lot.id
  for update;
  select coalesce(pg_catalog.sum(lot.remaining_cost_basis), 0),
    (pg_catalog.array_agg(
      lot.id order by lot.acquisition_date desc, lot.id desc
    ))[1]
  into v_lot_book_total, v_last_lot_id
  from investments.acquisition_lots lot
  where lot.position_id = v_position.id
    and lot.company_id = v_company
    and lot.remaining_share_count > 0;
  if v_lot_book_total <> v_position.cost_basis
    or (v_position.share_count > 0 and v_last_lot_id is null)
  then raise exception 'investments_dependency_unavailable'; end if;

  if p_entry_id is not null and not ledger.investment_lifecycle_entry_matches_v2(
    p_entry_id, v_company, 2026, 'INVESTMENT_MEASUREMENT',
    (p_request ->> 'measurementId')::uuid,
    p_prepared ->> 'calculationId', date '2026-12-31', v_document_facts
  ) then raise exception 'investments_dependency_unavailable'; end if;

  insert into investments.source_fact_registry (
    company_id, source_capability, source_record_id, source_revision,
    fact_sha256
  ) select v_company, item ->> 'capability',
    (item ->> 'recordId')::uuid, (item ->> 'revision')::integer,
    item ->> 'factSha256'
  from pg_catalog.jsonb_array_elements(v_document_facts) item
  on conflict (
    company_id, source_capability, source_record_id, source_revision
  ) do update set fact_sha256 = excluded.fact_sha256
  where investments.source_fact_registry.fact_sha256 = excluded.fact_sha256;
  get diagnostics v_count = row_count;
  if v_count <> pg_catalog.jsonb_array_length(v_document_facts)
  then raise exception 'investments_invalid_input'; end if;

  insert into investments.year_end_measurements (
    measurement_id, company_id, income_year, position_id, as_of,
    policy_version, measurement_rule, quantity, source_book_cost,
    pre_measurement_book_value, observed_or_recoverable_value,
    impairment_amount, reversal_amount, closing_book_value, tax_basis,
    tax_value, evidence_digest, calculation_id, accounting_entry_id,
    created_by, idempotency_key, request_fingerprint, evidence_mode,
    evidence_reference, owner_attested
  ) values (
    (p_request ->> 'measurementId')::uuid, v_company, 2026, v_position.id,
    date '2026-12-31', 'domestic_2026_v2',
    p_prepared ->> 'measurementRule',
    (p_prepared ->> 'quantity')::numeric,
    (p_prepared ->> 'sourceBookCost')::numeric,
    (p_prepared ->> 'preMeasurementBookValue')::numeric,
    (p_prepared ->> 'observedOrRecoverableValue')::numeric, v_impairment,
    0, (p_prepared ->> 'closingBookValue')::numeric,
    (p_prepared ->> 'taxBasis')::numeric,
    (p_prepared ->> 'taxValue')::numeric,
    p_prepared ->> 'evidenceDigest', p_prepared ->> 'calculationId',
    p_entry_id, v_actor, p_request ->> 'idempotencyKey',
    investments.year_end_measurement_fingerprint_v2(p_request),
    p_request ->> 'evidenceMode', p_request ->> 'evidenceReference',
    (p_request ->> 'ownerAttested')::boolean
  );
  insert into investments.measurement_sources (
    measurement_id, company_id, ordinal, role, source_capability,
    source_record_id, source_revision, fact_sha256
  ) select (p_request ->> 'measurementId')::uuid, v_company,
    ordinal::integer,
    case when ordinal = 1 then 'holdings_statement' else 'valuation' end,
    item ->> 'capability', (item ->> 'recordId')::uuid,
    (item ->> 'revision')::integer, item ->> 'factSha256'
  from pg_catalog.jsonb_array_elements(v_document_facts)
    with ordinality source(item, ordinal);
  if v_impairment > 0 then
    update investments.acquisition_lots lot
    set remaining_cost_basis = pg_catalog.round(
      lot.remaining_cost_basis
        * (p_prepared ->> 'closingBookValue')::numeric
        / v_position.cost_basis,
      12
    )
    where lot.position_id = v_position.id
      and lot.company_id = v_company
      and lot.remaining_share_count > 0;
    select pg_catalog.sum(lot.remaining_cost_basis)
    into v_lot_book_total
    from investments.acquisition_lots lot
    where lot.position_id = v_position.id
      and lot.company_id = v_company
      and lot.remaining_share_count > 0;
    update investments.acquisition_lots lot
    set remaining_cost_basis = lot.remaining_cost_basis
      + (p_prepared ->> 'closingBookValue')::numeric - v_lot_book_total
    where lot.id = v_last_lot_id and lot.company_id = v_company;
    update investments.positions
    set cost_basis = (p_prepared ->> 'closingBookValue')::numeric,
        updated_at = pg_catalog.statement_timestamp()
    where id = v_position.id and cost_basis = v_position.cost_basis;
    get diagnostics v_count = row_count;
    if v_count <> 1 then raise exception 'investments_dependency_unavailable'; end if;
  end if;
  insert into public.audit_events (
    company_id, actor_id, category, action, message
  ) values (
    v_company, v_actor, 'ledger', 'investment_year_end_measured',
    'Årssluttmåling registrert for investering ' || v_position.id::text || '.'
  );
  return pg_catalog.jsonb_build_object(
    'measurementId', p_request ->> 'measurementId',
    'positionId', v_position.id, 'accountingEntryId', p_entry_id,
    'measurementRule', p_prepared ->> 'measurementRule',
    'closingBookValue', p_prepared ->> 'closingBookValue',
    'taxBasis', p_prepared ->> 'taxBasis',
    'taxValue', p_prepared ->> 'taxValue', 'replayed', false
  );
end;
$function$;

create or replace function ledger.post_investment_lifecycle_entry_v2(
  p_idempotency_key text, p_company_id uuid, p_income_year integer,
  p_entry_kind text, p_memo text, p_lines jsonb,
  p_source_capability text, p_source_record_id text,
  p_correlation_id text, p_verified_subject text, p_event_date date,
  p_rule_version text, p_sources jsonb
)
returns table (
  ledger_entry_id uuid, company_id uuid, income_year integer,
  entry_kind text, posted_at timestamptz, replayed boolean
)
language plpgsql security definer set search_path = ''
as $function$
declare v_corroborating_capability text;
begin
  if p_source_capability <> 'INVESTMENTS'
    or p_entry_kind not in (
      'SHARE_PURCHASE', 'SHARE_SALE', 'DIVIDEND_RECEIVED',
      'INVESTMENT_MEASUREMENT'
    )
    or p_rule_version <> 'ledger-supported-patterns-2026.1'
    or pg_catalog.jsonb_typeof(p_sources) <> 'array'
    or pg_catalog.jsonb_array_length(p_sources) < 2
    or p_sources -> 0 ->> 'role' <> 'PRIMARY'
    or p_sources -> 0 ->> 'capability' <> 'INVESTMENTS'
    or p_sources -> 0 ->> 'recordId' <> p_source_record_id
    or exists (
      select 1 from pg_catalog.jsonb_array_elements(p_sources)
        with ordinality source(item, ordinal)
      where ordinal > 1 and item ->> 'role' <> 'CORROBORATING'
    )
  then raise exception 'ledger_invalid_input'; end if;
  select p_sources -> 1 ->> 'capability' into v_corroborating_capability;
  if v_corroborating_capability not in ('BANKING', 'DOCUMENTS')
    or exists (
      select 1 from pg_catalog.jsonb_array_elements(p_sources)
        with ordinality source(item, ordinal)
      where ordinal > 1
        and item ->> 'capability' <> v_corroborating_capability
    )
  then raise exception 'ledger_source_capability_mismatch'; end if;
  if (v_corroborating_capability = 'BANKING'
      and pg_catalog.jsonb_array_length(p_sources) <> 2)
    or (v_corroborating_capability = 'DOCUMENTS'
      and pg_catalog.jsonb_array_length(p_sources) not between 2 and 51)
  then raise exception 'ledger_source_capability_mismatch'; end if;
  return query select * from ledger.post_supported_entry_v1(
    p_idempotency_key, p_company_id, p_income_year, p_entry_kind, p_memo,
    p_lines, p_source_capability, p_source_record_id, p_correlation_id,
    p_verified_subject, p_event_date, p_rule_version, p_sources
  );
end;
$function$;

create or replace function investments.year_end_measurement_fingerprint_v2(
  p_request jsonb
)
returns text language sql immutable set search_path = ''
as $function$
  select pg_catalog.encode(extensions.digest(
    (p_request - array['evidenceDigest', 'correlationId'])::text, 'sha256'
  ), 'hex');
$function$;

create or replace function investments.get_year_end_measurement_replay_v2(
  p_request jsonb, p_verified_subject text
)
returns jsonb language plpgsql security definer set search_path = ''
as $function$
declare
  v_actor uuid := public.company_access_auth_uid_v1();
  v_row investments.year_end_measurements%rowtype;
begin
  if v_actor is null or p_verified_subject !~ '^[0-9a-fA-F-]{36}$'
    or v_actor is distinct from p_verified_subject::uuid
  then raise exception 'investments_forbidden'; end if;
  select measurement.* into v_row
  from investments.year_end_measurements measurement
  where measurement.measurement_id = (p_request ->> 'measurementId')::uuid
     or (
       measurement.created_by = v_actor
       and measurement.company_id = (p_request ->> 'companyId')::uuid
       and measurement.idempotency_key = p_request ->> 'idempotencyKey'
     )
  order by (measurement.measurement_id =
    (p_request ->> 'measurementId')::uuid) desc limit 1;
  if not found then return null; end if;
  if v_row.company_id <> (p_request ->> 'companyId')::uuid
    or not public.company_access_is_accepted_owner_v1(v_row.company_id)
    or v_row.request_fingerprint <>
      investments.year_end_measurement_fingerprint_v2(p_request)
  then raise exception 'investments_idempotency_key_reused'; end if;
  return pg_catalog.jsonb_build_object(
    'measurementId', v_row.measurement_id, 'positionId', v_row.position_id,
    'accountingEntryId', v_row.accounting_entry_id,
    'measurementRule', v_row.measurement_rule,
    'closingBookValue', v_row.closing_book_value,
    'taxBasis', v_row.tax_basis, 'taxValue', v_row.tax_value,
    'replayed', true
  );
end;
$function$;

create or replace function investments.prepare_year_end_measurement_v2(
  p_request jsonb, p_verified_subject text
)
returns jsonb language plpgsql security definer set search_path = ''
as $function$
declare
  v_actor uuid := public.company_access_auth_uid_v1();
  v_position investments.positions%rowtype;
  v_company uuid := (p_request ->> 'companyId')::uuid;
begin
  if v_actor is null or p_verified_subject !~ '^[0-9a-fA-F-]{36}$'
    or v_actor is distinct from p_verified_subject::uuid
    or not public.company_access_is_accepted_owner_v1(v_company)
  then raise exception 'investments_forbidden'; end if;
  if (p_request ->> 'incomeYear')::integer <> 2026
    or (p_request ->> 'asOf')::date <> date '2026-12-31'
    or coalesce(p_request ->> 'idempotencyKey', '')
      !~ '^[A-Za-z0-9._:-]{16,255}$'
    or p_request ->> 'evidenceDigest' !~ '^[0-9a-f]{64}$'
    or not investments.lifecycle_document_evidence_is_valid_v2(p_request)
    or (p_request ->> 'observedOrRecoverableValue')::numeric < 0
    or (p_request ->> 'taxValue')::numeric < 0
    or pg_catalog.round(
      (p_request ->> 'observedOrRecoverableValue')::numeric, 2
    ) <> (p_request ->> 'observedOrRecoverableValue')::numeric
    or pg_catalog.round((p_request ->> 'taxValue')::numeric, 2)
      <> (p_request ->> 'taxValue')::numeric
  then raise exception 'investments_invalid_input'; end if;
  if exists (
    select 1 from investments.year_end_measurements measurement
    where measurement.measurement_id = (p_request ->> 'measurementId')::uuid
       or (measurement.created_by = v_actor
         and measurement.company_id = v_company
         and measurement.idempotency_key = p_request ->> 'idempotencyKey')
       or (measurement.position_id = (p_request ->> 'positionId')::uuid
         and measurement.income_year = 2026)
  ) then raise exception 'investments_idempotency_key_reused'; end if;
  select position.* into v_position from investments.positions position
  where position.id = (p_request ->> 'positionId')::uuid for update;
  if not found or v_position.company_id <> v_company
    or v_position.lot_history_status <> 'complete'
    or not exists (
      select 1 from investments.position_classifications classification
      where classification.position_id = v_position.id
        and classification.company_id = v_company
        and classification.income_year = 2026
        and classification.accounting_classification =
          v_position.accounting_classification
    )
  then raise exception 'investments_invalid_input'; end if;
  return pg_catalog.jsonb_build_object(
    'positionId', v_position.id, 'investmentName', v_position.name,
    'investmentKind', v_position.kind,
    'accountingClassification', v_position.accounting_classification,
    'quantity', v_position.share_count,
    'sourceBookCost', v_position.cost_basis,
    'preMeasurementBookValue', v_position.cost_basis,
    'taxBasis', v_position.tax_basis
  );
end;
$function$;

create or replace function ledger.post_entry_without_company_year_close_lock_v1(
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
  v_receipt backend_system.ledger_command_receipts%rowtype;
  v_entry_id uuid;
  v_posted_at timestamptz;
  v_computed_fingerprint text;
  v_result jsonb;
begin
  if v_actor_id is null
    or p_verified_subject is null
    or p_verified_subject !~ '^[0-9a-fA-F-]{36}$'
    or v_actor_id is distinct from p_verified_subject::uuid
  then
    raise exception 'ledger_forbidden';
  end if;
  if p_company_id is null or p_income_year not between 2000 and 2100
    or coalesce(p_idempotency_key, '') !~ '^[A-Za-z0-9._:-]{16,255}$'
    or pg_catalog.btrim(coalesce(p_memo, '')) = ''
    or pg_catalog.btrim(coalesce(p_source_record_id, '')) = ''
    or pg_catalog.btrim(coalesce(p_correlation_id, '')) = ''
    or p_source_capability not in (
      'LEDGER', 'BANKING', 'INVESTMENTS', 'CORPORATE_GOVERNANCE',
      'COMPANY_TAX_FILING', 'SHAREHOLDER_REGISTER_FILING',
      'ANNUAL_ACCOUNTS_FILING', 'DOCUMENTS'
    )
    or pg_catalog.upper(coalesce(p_entry_kind, '')) not in (
      'OPENING_BALANCE', 'ADMINISTRATIVE_COST', 'MANUAL_JOURNAL',
      'BANK_RULE_SUGGESTION', 'DIVIDEND_RECEIVED',
      'OWNER_DIVIDEND_DECLARED', 'OWNER_DIVIDEND_PAYMENT', 'SHARE_PURCHASE',
      'SHARE_SALE', 'SHAREHOLDER_LOAN', 'TAX_SETTLEMENT',
      'BANK_INTEREST', 'BANK_LOAN', 'CAPITAL_INCREASE',
      'CAPITAL_REDUCTION', 'COMPANY_TAX_ACCRUAL', 'GROUP_CONTRIBUTION',
      'INTERCOMPANY_LOAN', 'INVESTMENT_MEASUREMENT'
    )
    or pg_catalog.jsonb_typeof(p_risk_flags) is distinct from 'array'
    or not ledger.entry_lines_are_valid_v1(p_lines, false)
  then
    raise exception 'ledger_invalid_input';
  end if;

  if not public.company_access_is_accepted_member_v1(p_company_id) then
    raise exception 'ledger_not_found';
  end if;
  if not public.company_access_is_accepted_owner_v1(p_company_id) then
    raise exception 'ledger_forbidden';
  end if;

  v_computed_fingerprint := pg_catalog.encode(extensions.digest(
    pg_catalog.jsonb_build_object(
      'companyId', p_company_id,
      'incomeYear', p_income_year,
      'entryKind', pg_catalog.upper(p_entry_kind),
      'memo', pg_catalog.btrim(p_memo),
      'lines', ledger.normalize_lines_v1(p_lines),
      'riskFlags', p_risk_flags,
      'warningAccepted', p_warning_accepted,
      'sourceCapability', p_source_capability,
      'sourceRecordId', pg_catalog.btrim(p_source_record_id)
    )::text,
    'sha256'
  ), 'hex');
  if not pg_catalog.pg_try_advisory_xact_lock(pg_catalog.hashtextextended(
    'ledger:v1:' || v_actor_id::text || ':' || p_company_id::text
      || ':post_entry:' || p_idempotency_key,
    0
  )) then
    raise exception 'ledger_idempotency_in_progress';
  end if;

  select receipt.* into v_receipt
  from backend_system.ledger_command_receipts receipt
  where receipt.api_major = 'v1'
    and receipt.actor_id = v_actor_id
    and receipt.company_id = p_company_id
    and receipt.operation_name = 'post_entry'
    and receipt.idempotency_key = p_idempotency_key;
  if found then
    if v_receipt.request_fingerprint <> v_computed_fingerprint then
      raise exception 'ledger_idempotency_key_reused';
    end if;
    return query select
      (v_receipt.result ->> 'ledger_entry_id')::uuid,
      (v_receipt.result ->> 'company_id')::uuid,
      (v_receipt.result ->> 'income_year')::integer,
      v_receipt.result ->> 'entry_kind',
      (v_receipt.result ->> 'posted_at')::timestamptz,
      true;
    return;
  end if;

  perform ledger.lock_company_year_v1(p_company_id, p_income_year);
  if not public.company_access_company_year_allows_consequential_v1(
    p_company_id, p_income_year
  ) then
    raise exception 'ledger_company_year_not_admitted';
  end if;
  if exists (
    select 1 from ledger.period_locks period_lock
    where period_lock.company_id = p_company_id
      and period_lock.income_year = p_income_year
  ) then
    raise exception 'ledger_period_locked';
  end if;
  if exists (
    select 1 from ledger.entries entry
    where entry.company_id = p_company_id
      and entry.source_capability = p_source_capability
      and entry.source_record_id = p_source_record_id
  ) then
    raise exception 'ledger_idempotency_key_reused';
  end if;
  if pg_catalog.upper(p_entry_kind) = 'OPENING_BALANCE' and exists (
    select 1 from ledger.entries entry
    where entry.company_id = p_company_id
      and entry.income_year = p_income_year
      and entry.entry_kind = 'OPENING_BALANCE'
  ) then
    raise exception 'ledger_opening_already_exists';
  end if;

  v_entry_id := pg_catalog.gen_random_uuid();
  v_posted_at := pg_catalog.statement_timestamp();
  insert into ledger.entries (
    id, company_id, income_year, entry_kind, memo, lines, risk_flags,
    warning_accepted_by, warning_accepted_at, posted_at, created_by, created_at,
    source_capability, source_record_id, correlation_id
  ) values (
    v_entry_id, p_company_id, p_income_year, pg_catalog.upper(p_entry_kind),
    pg_catalog.btrim(p_memo), ledger.normalize_lines_v1(p_lines),
    p_risk_flags,
    case when p_warning_accepted then v_actor_id else null end,
    case when p_warning_accepted then v_posted_at else null end,
    v_posted_at, v_actor_id, v_posted_at,
    p_source_capability, pg_catalog.btrim(p_source_record_id),
    pg_catalog.btrim(p_correlation_id)
  );
  v_result := pg_catalog.jsonb_build_object(
    'ledger_entry_id', v_entry_id,
    'company_id', p_company_id,
    'income_year', p_income_year,
    'entry_kind', pg_catalog.upper(p_entry_kind),
    'posted_at', v_posted_at
  );
  insert into backend_system.ledger_command_receipts (
    api_major, actor_id, company_id, operation_name, idempotency_key,
    request_fingerprint, result
  ) values (
    'v1', v_actor_id, p_company_id, 'post_entry', p_idempotency_key,
    v_computed_fingerprint, v_result
  );

  return query select
    v_entry_id, p_company_id, p_income_year, pg_catalog.upper(p_entry_kind),
    v_posted_at, false;
end;
$function$;

alter function investments.year_end_measurement_fingerprint_v2(jsonb)
  owner to investments_store_owner;
alter function investments.get_year_end_measurement_replay_v2(jsonb, text)
  owner to investments_store_owner;
alter function investments.prepare_year_end_measurement_v2(jsonb, text)
  owner to investments_store_owner;
alter function investments.complete_year_end_measurement_v2(
  jsonb, uuid, jsonb, text
) owner to investments_store_owner;
alter function ledger.post_entry_without_company_year_close_lock_v1(
  text, uuid, integer, text, text, jsonb, jsonb, boolean,
  text, text, text, text
) owner to ledger_store_owner;
alter function ledger.post_investment_lifecycle_entry_v2(
  text, uuid, integer, text, text, jsonb, text, text, text, text,
  date, text, jsonb
) owner to ledger_store_owner;

revoke all on function
  investments.year_end_measurement_fingerprint_v2(jsonb),
  investments.get_year_end_measurement_replay_v2(jsonb, text),
  investments.prepare_year_end_measurement_v2(jsonb, text),
  investments.complete_year_end_measurement_v2(jsonb, uuid, jsonb, text)
from public, anon, authenticated, service_role;
grant execute on function
  investments.get_year_end_measurement_replay_v2(jsonb, text),
  investments.prepare_year_end_measurement_v2(jsonb, text),
  investments.complete_year_end_measurement_v2(jsonb, uuid, jsonb, text)
to investments_workflow_executor;

do $authority_revoke$
begin
  execute pg_catalog.format('revoke create on schema ledger from %I', current_user);
  revoke create on schema ledger from ledger_store_owner;
  execute pg_catalog.format('revoke ledger_store_owner from %I', current_user);
  execute pg_catalog.format('revoke investments_store_owner from %I', current_user);
end
$authority_revoke$;

commit;
