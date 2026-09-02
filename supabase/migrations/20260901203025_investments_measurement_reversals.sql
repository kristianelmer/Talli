-- #190: permit evidenced impairment reversals up to the remaining acquisition-cost ceiling.

begin;

do $membership$
begin
  execute pg_catalog.format(
    'grant investments_store_owner to %I', current_user
  );
end
$membership$;

create or replace function investments.prepare_year_end_measurement_v3(
  p_request jsonb, p_verified_subject text
)
returns jsonb language plpgsql security definer set search_path = ''
as $function$
declare
  v_actor uuid := public.company_access_auth_uid_v1();
  v_position investments.positions%rowtype;
  v_company uuid := (p_request ->> 'companyId')::uuid;
  v_source_book_cost numeric;
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
  if v_position.id is null or v_position.company_id <> v_company
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
  select coalesce(pg_catalog.sum(pg_catalog.round(
    lot.original_cost_basis * lot.remaining_share_count
      / lot.original_share_count, 12
  )), 0)
  into v_source_book_cost
  from investments.acquisition_lots lot
  where lot.position_id = v_position.id
    and lot.company_id = v_company
    and lot.remaining_share_count > 0;
  if v_source_book_cost < v_position.cost_basis
  then raise exception 'investments_dependency_unavailable'; end if;
  return pg_catalog.jsonb_build_object(
    'positionId', v_position.id, 'investmentName', v_position.name,
    'investmentKind', v_position.kind,
    'accountingClassification', v_position.accounting_classification,
    'quantity', v_position.share_count,
    'sourceBookCost', v_source_book_cost,
    'preMeasurementBookValue', v_position.cost_basis,
    'taxBasis', v_position.tax_basis
  );
end;
$function$;

create or replace function investments.complete_year_end_measurement_v3(
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
  v_reversal numeric := (p_prepared ->> 'reversalAmount')::numeric;
  v_closing numeric := (p_prepared ->> 'closingBookValue')::numeric;
  v_document_facts jsonb := p_request -> 'documentFacts';
  v_count integer;
  v_lot_book_total numeric;
  v_source_book_total numeric;
  v_last_lot_id uuid;
begin
  if v_actor is null or p_verified_subject !~ '^[0-9a-fA-F-]{36}$'
    or v_actor is distinct from p_verified_subject::uuid
    or not public.company_access_is_accepted_owner_v1(v_company)
  then raise exception 'investments_forbidden'; end if;
  select position.* into v_position from investments.positions position
  where position.id = (p_request ->> 'positionId')::uuid for update;
  perform 1 from investments.acquisition_lots lot
  where lot.position_id = v_position.id
    and lot.company_id = v_company
    and lot.remaining_share_count > 0
  order by lot.acquisition_date, lot.id
  for update;
  select coalesce(pg_catalog.sum(lot.remaining_cost_basis), 0),
    coalesce(pg_catalog.sum(pg_catalog.round(
      lot.original_cost_basis * lot.remaining_share_count
        / lot.original_share_count, 12
    )), 0),
    (pg_catalog.array_agg(
      lot.id order by lot.acquisition_date desc, lot.id desc
    ))[1]
  into v_lot_book_total, v_source_book_total, v_last_lot_id
  from investments.acquisition_lots lot
  where lot.position_id = v_position.id
    and lot.company_id = v_company
    and lot.remaining_share_count > 0;
  if v_position.id is null or v_position.company_id <> v_company
    or (p_prepared ->> 'positionId')::uuid <> v_position.id
    or (p_prepared ->> 'quantity')::numeric <> v_position.share_count
    or (p_prepared ->> 'sourceBookCost')::numeric <> v_source_book_total
    or (p_prepared ->> 'preMeasurementBookValue')::numeric <> v_position.cost_basis
    or (p_prepared ->> 'observedOrRecoverableValue')::numeric < 0
    or v_impairment < 0 or v_reversal < 0
    or (v_impairment > 0 and v_reversal > 0)
    or v_closing < 0 or v_closing > v_source_book_total
    or v_closing <> v_position.cost_basis - v_impairment + v_reversal
    or (p_prepared ->> 'taxBasis')::numeric <> v_position.tax_basis
    or p_prepared ->> 'evidenceDigest' !~ '^[0-9a-f]{64}$'
    or p_prepared ->> 'calculationId' !~ '^[0-9a-f]{64}$'
    or v_lot_book_total <> v_position.cost_basis
    or (v_position.share_count > 0 and v_last_lot_id is null)
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
    or ((v_impairment > 0 or v_reversal > 0) <> (p_entry_id is not null))
  then raise exception 'investments_invalid_input'; end if;

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
    (p_prepared ->> 'quantity')::numeric, v_source_book_total,
    v_position.cost_basis,
    (p_prepared ->> 'observedOrRecoverableValue')::numeric,
    v_impairment, v_reversal, v_closing,
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
  if v_impairment > 0 or v_reversal > 0 then
    update investments.acquisition_lots lot
    set remaining_cost_basis = pg_catalog.round(
      (lot.original_cost_basis * lot.remaining_share_count
        / lot.original_share_count) * v_closing / v_source_book_total,
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
      + v_closing - v_lot_book_total
    where lot.id = v_last_lot_id and lot.company_id = v_company;
    update investments.positions
    set cost_basis = v_closing,
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
    'closingBookValue', v_closing,
    'taxBasis', p_prepared ->> 'taxBasis',
    'taxValue', p_prepared ->> 'taxValue', 'replayed', false
  );
end;
$function$;

alter function investments.prepare_year_end_measurement_v3(jsonb, text)
  owner to investments_store_owner;
alter function investments.complete_year_end_measurement_v3(
  jsonb, uuid, jsonb, text
) owner to investments_store_owner;

revoke all on function
  investments.prepare_year_end_measurement_v3(jsonb, text),
  investments.complete_year_end_measurement_v3(jsonb, uuid, jsonb, text)
from public, anon, authenticated, service_role;
grant execute on function
  investments.prepare_year_end_measurement_v3(jsonb, text),
  investments.complete_year_end_measurement_v3(jsonb, uuid, jsonb, text)
to investments_workflow_executor;

do $membership_revoke$
begin
  execute pg_catalog.format(
    'revoke investments_store_owner from %I', current_user
  );
end
$membership_revoke$;

commit;
