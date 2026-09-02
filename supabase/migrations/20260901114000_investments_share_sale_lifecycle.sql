-- Add canonical share-sale recognition without assuming cash receipt.
begin;

set local lock_timeout = '5s';
set local statement_timeout = '120s';

do $membership$
begin
  execute pg_catalog.format(
    'grant investments_store_owner, investments_workflow_executor, ledger_store_owner to %I',
    current_user
  );
end
$membership$;

select pg_catalog.pg_advisory_xact_lock(
  pg_catalog.hashtextextended('talli:investments:share-sale-lifecycle:v2', 0)
);

create or replace function investments.lifecycle_document_evidence_is_valid_v2(
  p_request jsonb
)
returns boolean
language sql
immutable
set search_path = ''
as $function$
  select
    nullif(pg_catalog.btrim(p_request ->> 'evidenceReference'), '') is not null
    and pg_catalog.length(p_request ->> 'evidenceReference') <= 500
    and pg_catalog.jsonb_typeof(p_request -> 'documentFacts') = 'array'
    and pg_catalog.jsonb_array_length(p_request -> 'documentFacts') between 1 and 50
    and p_request -> 'bankFact' is not distinct from 'null'::jsonb
    and (
      (p_request ->> 'evidenceMode' = 'linked_sources'
        and (p_request ->> 'ownerAttested')::boolean = false)
      or (p_request ->> 'evidenceMode' = 'manual_fallback'
        and (p_request ->> 'ownerAttested')::boolean = true)
    )
    and not exists (
      select 1
      from pg_catalog.jsonb_array_elements(p_request -> 'documentFacts') fact
      where fact ->> 'capability' <> 'DOCUMENTS'
        or coalesce(fact ->> 'recordId', '') !~ '^[0-9a-fA-F-]{36}$'
        or coalesce(fact ->> 'revision', '') !~ '^[1-9][0-9]*$'
        or coalesce(fact ->> 'factSha256', '') !~ '^[0-9a-f]{64}$'
    )
    and not exists (
      select 1
      from pg_catalog.jsonb_array_elements(p_request -> 'documentFacts') fact
      group by fact ->> 'recordId', fact ->> 'revision'
      having pg_catalog.count(*) > 1
    );
$function$;

create or replace function investments.record_lifecycle_document_sources_v2(
  p_company_id uuid,
  p_event_id uuid,
  p_document_facts jsonb
)
returns void
language plpgsql
security definer
set search_path = ''
as $function$
declare
  v_count integer;
begin
  if pg_catalog.jsonb_typeof(p_document_facts) <> 'array'
    or pg_catalog.jsonb_array_length(p_document_facts) not between 1 and 50
  then raise exception 'investments_invalid_input'; end if;

  insert into investments.source_fact_registry (
    company_id, source_capability, source_record_id, source_revision,
    fact_sha256
  )
  select p_company_id, item ->> 'capability',
    (item ->> 'recordId')::uuid, (item ->> 'revision')::integer,
    item ->> 'factSha256'
  from pg_catalog.jsonb_array_elements(p_document_facts) item
  on conflict (
    company_id, source_capability, source_record_id, source_revision
  ) do update set fact_sha256 = excluded.fact_sha256
  where investments.source_fact_registry.fact_sha256 = excluded.fact_sha256;
  get diagnostics v_count = row_count;
  if v_count <> pg_catalog.jsonb_array_length(p_document_facts)
  then raise exception 'investments_invalid_input'; end if;

  insert into investments.event_sources (
    event_id, company_id, ordinal, role, source_capability,
    source_record_id, source_revision, fact_sha256
  )
  select p_event_id, p_company_id, ordinal::integer,
    case when ordinal = 1 then 'primary_document' else 'supporting_document' end,
    item ->> 'capability', (item ->> 'recordId')::uuid,
    (item ->> 'revision')::integer, item ->> 'factSha256'
  from pg_catalog.jsonb_array_elements(p_document_facts)
    with ordinality source(item, ordinal);
end;
$function$;

create or replace function investments.share_sale_recognition_fingerprint_v2(
  p_request jsonb
)
returns text
language sql
immutable
set search_path = ''
as $function$
  select pg_catalog.encode(extensions.digest(
    (p_request - array[
      'netProceeds', 'evidenceDigest', 'correlationId'
    ])::text,
    'sha256'
  ), 'hex');
$function$;

create or replace function investments.get_share_sale_recognition_replay_v2(
  p_request jsonb,
  p_verified_subject text
)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $function$
declare
  v_actor_id uuid := public.company_access_auth_uid_v1();
  v_event investments.economic_events%rowtype;
begin
  if v_actor_id is null or v_actor_id is distinct from p_verified_subject::uuid
    or not public.company_access_is_accepted_owner_v1(
      (p_request ->> 'companyId')::uuid
    )
  then raise exception 'investments_forbidden'; end if;
  if not pg_catalog.pg_try_advisory_xact_lock(pg_catalog.hashtextextended(
    'investments:v2:' || v_actor_id::text || ':' ||
      (p_request ->> 'companyId') || ':share-sale:' ||
      coalesce(p_request ->> 'idempotencyKey', ''), 0
  )) then raise exception 'investments_idempotency_in_progress'; end if;

  select event.* into v_event
  from investments.economic_events event
  where event.event_id = (p_request ->> 'eventId')::uuid
     or (
       event.created_by = v_actor_id
       and event.company_id = (p_request ->> 'companyId')::uuid
       and event.idempotency_key = p_request ->> 'idempotencyKey'
     )
  order by (event.event_id = (p_request ->> 'eventId')::uuid) desc
  limit 1;
  if not found then return null; end if;
  if v_event.event_kind <> 'share_sale'
    or v_event.company_id <> (p_request ->> 'companyId')::uuid
    or v_event.income_year <> (p_request ->> 'incomeYear')::integer
    or v_event.request_fingerprint <>
      investments.share_sale_recognition_fingerprint_v2(p_request)
  then raise exception 'investments_idempotency_key_reused'; end if;
  return pg_catalog.jsonb_build_object(
    'eventId', v_event.event_id,
    'positionId', v_event.position_id,
    'recognitionAccountingEntryId', v_event.recognition_accounting_entry_id,
    'expectedSettlementAmount', v_event.expected_settlement_amount,
    'settlementBalanceKind', v_event.settlement_balance_kind,
    'replayed', true
  );
end;
$function$;

create or replace function investments.prepare_share_sale_recognition_v2(
  p_request jsonb,
  p_verified_subject text
)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $function$
declare
  v_actor_id uuid := public.company_access_auth_uid_v1();
  v_company_id uuid := (p_request ->> 'companyId')::uuid;
  v_position investments.positions%rowtype;
  v_lot investments.acquisition_lots%rowtype;
  v_sold numeric := (p_request ->> 'soldShareCount')::numeric;
  v_proceeds numeric := (p_request ->> 'proceeds')::numeric;
  v_costs numeric := (p_request ->> 'transactionCosts')::numeric;
  v_net numeric := (p_request ->> 'netProceeds')::numeric;
  v_sale_ratio integer := nullif(
    p_request ->> 'saleYearFundEquityRatioBasisPoints', ''
  )::integer;
  v_fund_reference text := nullif(pg_catalog.btrim(
    p_request ->> 'fundTaxStatementReference'
  ), '');
  v_available_shares numeric;
  v_available_book numeric;
  v_available_tax numeric;
  v_left numeric;
  v_allocated_shares numeric;
  v_allocated_book numeric;
  v_allocated_tax numeric;
  v_book_cost numeric := 0;
  v_tax_basis numeric := 0;
  v_order integer := 0;
  v_lot_facts jsonb := '[]'::jsonb;
begin
  if v_actor_id is null or v_actor_id is distinct from p_verified_subject::uuid
    or not public.company_access_is_accepted_owner_v1(v_company_id)
  then raise exception 'investments_forbidden'; end if;
  if not pg_catalog.pg_try_advisory_xact_lock(pg_catalog.hashtextextended(
    'investments:v2:' || v_actor_id::text || ':' || v_company_id::text ||
      ':share-sale:' || coalesce(p_request ->> 'idempotencyKey', ''), 0
  )) then raise exception 'investments_idempotency_in_progress'; end if;
  if coalesce(p_request ->> 'idempotencyKey', '')
      !~ '^[A-Za-z0-9._:-]{16,255}$'
    or (p_request ->> 'incomeYear')::integer <> 2026
    or v_sold <= 0 or v_sold >= 1e26
    or v_sold <> pg_catalog.round(v_sold, 12)
    or v_proceeds <= 0 or v_costs < 0 or v_costs >= v_proceeds
    or v_net <> v_proceeds - v_costs
    or pg_catalog.round(v_proceeds, 2) <> v_proceeds
    or pg_catalog.round(v_costs, 2) <> v_costs
    or extract(year from (p_request ->> 'saleDate')::date)::integer <> 2026
    or p_request ->> 'evidenceDigest' !~ '^[0-9a-f]{64}$'
    or not investments.lifecycle_document_evidence_is_valid_v2(p_request)
  then raise exception 'investments_invalid_input'; end if;
  if exists (
    select 1 from investments.economic_events event
    where event.event_id = (p_request ->> 'eventId')::uuid
       or (
         event.created_by = v_actor_id and event.company_id = v_company_id
         and event.idempotency_key = p_request ->> 'idempotencyKey'
       )
  ) or exists (
    select 1 from investments.share_sales sale
    where sale.action_id = (p_request ->> 'eventId')::uuid
       or (
         sale.created_by = v_actor_id and sale.company_id = v_company_id
         and sale.idempotency_key = p_request ->> 'idempotencyKey'
       )
  ) then raise exception 'investments_idempotency_key_reused'; end if;

  select position.* into v_position
  from investments.positions position
  where position.id = (p_request ->> 'positionId')::uuid
  for update;
  if not found or v_position.company_id <> v_company_id
    or v_position.lot_history_status <> 'complete'
    or not exists (
      select 1 from investments.company_year_policies policy
      where policy.company_id = v_company_id and policy.income_year = 2026
        and policy.policy_version = 'domestic_2026_v2'
    )
    or not exists (
      select 1 from investments.position_classifications classification
      where classification.position_id = v_position.id
        and classification.company_id = v_company_id
        and classification.income_year = 2026
        and classification.accounting_classification =
          v_position.accounting_classification
    )
    or (
      v_position.kind = 'norwegian_equity_fund'
      and (v_sale_ratio is null or v_sale_ratio not between 0 and 10000
        or v_fund_reference is null)
    )
    or (
      v_position.kind <> 'norwegian_equity_fund'
      and (v_sale_ratio is not null or v_fund_reference is not null)
    )
  then raise exception 'investments_invalid_input'; end if;

  perform 1 from investments.acquisition_lots lot
  where lot.position_id = v_position.id and lot.remaining_share_count > 0
  order by lot.acquisition_date, lot.id for update;
  select coalesce(pg_catalog.sum(lot.remaining_share_count), 0),
    coalesce(pg_catalog.sum(lot.remaining_cost_basis), 0),
    coalesce(pg_catalog.sum(lot.remaining_tax_basis), 0)
  into v_available_shares, v_available_book, v_available_tax
  from investments.acquisition_lots lot
  where lot.position_id = v_position.id and lot.remaining_share_count > 0;
  if v_available_shares = 0 or v_sold > v_available_shares
    or v_available_shares <> v_position.share_count
    or v_available_book <> v_position.cost_basis
    or v_available_tax <> v_position.tax_basis
  then raise exception 'investments_invalid_input'; end if;

  v_left := v_sold;
  for v_lot in
    select lot.* from investments.acquisition_lots lot
    where lot.position_id = v_position.id and lot.remaining_share_count > 0
    order by lot.acquisition_date, lot.id for update
  loop
    exit when v_left = 0;
    v_allocated_shares := least(v_left, v_lot.remaining_share_count);
    v_allocated_book := case
      when v_allocated_shares = v_lot.remaining_share_count
        then v_lot.remaining_cost_basis
      else pg_catalog.round(
        v_lot.remaining_cost_basis * v_allocated_shares /
          v_lot.remaining_share_count, 2
      )
    end;
    v_allocated_tax := case
      when v_allocated_shares = v_lot.remaining_share_count
        then v_lot.remaining_tax_basis
      else pg_catalog.round(
        v_lot.remaining_tax_basis * v_allocated_shares /
          v_lot.remaining_share_count, 2
      )
    end;
    v_order := v_order + 1;
    v_lot_facts := v_lot_facts || pg_catalog.jsonb_build_array(
      pg_catalog.jsonb_build_object(
        'lotId', v_lot.id,
        'allocationOrder', v_order,
        'acquisitionDate', v_lot.acquisition_date,
        'allocatedShareCount', v_allocated_shares,
        'allocatedBookCostBasis', v_allocated_book,
        'allocatedTaxBasis', v_allocated_tax,
        'acquisitionYearFundEquityRatioBasisPoints',
          v_lot.acquisition_year_fund_equity_ratio_basis_points
      )
    );
    v_book_cost := v_book_cost + v_allocated_book;
    v_tax_basis := v_tax_basis + v_allocated_tax;
    v_left := v_left - v_allocated_shares;
  end loop;
  if v_left <> 0 then raise exception 'investments_dependency_unavailable'; end if;

  return pg_catalog.jsonb_build_object(
    'positionId', v_position.id,
    'investmentName', v_position.name,
    'investmentKind', v_position.kind,
    'accountingClassification', v_position.accounting_classification,
    'fifoBookCostBasisReduction', v_book_cost,
    'fifoTaxBasisReduction', v_tax_basis,
    'lotFacts', v_lot_facts
  );
end;
$function$;

create or replace function investments.complete_share_sale_recognition_v2(
  p_request jsonb,
  p_entry_id uuid,
  p_prepared jsonb,
  p_verified_subject text
)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $function$
declare
  v_actor_id uuid := public.company_access_auth_uid_v1();
  v_company_id uuid := (p_request ->> 'companyId')::uuid;
  v_event_id uuid := (p_request ->> 'eventId')::uuid;
  v_position investments.positions%rowtype;
  v_lot investments.acquisition_lots%rowtype;
  v_calc jsonb;
  v_sold numeric := (p_request ->> 'soldShareCount')::numeric;
  v_proceeds numeric := (p_request ->> 'proceeds')::numeric;
  v_costs numeric := (p_request ->> 'transactionCosts')::numeric;
  v_net numeric := (p_prepared ->> 'netProceeds')::numeric;
  v_book_cost numeric := (p_prepared ->> 'fifoBookCostBasisReduction')::numeric;
  v_tax_basis numeric := (p_prepared ->> 'fifoTaxBasisReduction')::numeric;
  v_left numeric;
  v_allocated_shares numeric;
  v_allocated_book numeric;
  v_allocated_tax numeric;
  v_checked_book numeric := 0;
  v_checked_tax numeric := 0;
  v_available_shares numeric;
  v_available_book numeric;
  v_available_tax numeric;
  v_remaining_shares numeric;
  v_remaining_book numeric;
  v_remaining_tax numeric;
  v_order integer := 0;
  v_count integer;
begin
  if v_actor_id is null or v_actor_id is distinct from p_verified_subject::uuid
    or not public.company_access_is_accepted_owner_v1(v_company_id)
  then raise exception 'investments_forbidden'; end if;
  if not pg_catalog.pg_try_advisory_xact_lock(pg_catalog.hashtextextended(
    'investments:v2:' || v_actor_id::text || ':' || v_company_id::text ||
      ':share-sale:' || coalesce(p_request ->> 'idempotencyKey', ''), 0
  )) then raise exception 'investments_idempotency_in_progress'; end if;
  if v_net <> v_proceeds - v_costs
    or p_prepared ->> 'evidenceDigest' !~ '^[0-9a-f]{64}$'
    or p_prepared ->> 'calculationId' !~ '^[0-9a-f]{64}$'
    or (p_prepared ->> 'bookGainOrLoss')::numeric <> v_net - v_book_cost
    or (p_prepared ->> 'taxGainOrLoss')::numeric <> v_net - v_tax_basis
    or pg_catalog.jsonb_typeof(p_prepared -> 'lotCalculations') <> 'array'
    or not investments.lifecycle_document_evidence_is_valid_v2(p_request)
    or not ledger.investment_lifecycle_entry_matches_v2(
      p_entry_id, v_company_id, 2026, 'SHARE_SALE', v_event_id,
      p_prepared ->> 'calculationId', (p_request ->> 'saleDate')::date,
      p_request -> 'documentFacts'
    )
  then raise exception 'investments_dependency_unavailable'; end if;
  if (
      (p_prepared ->> 'taxGainOrLoss')::numeric >= 0
      and ((p_prepared ->> 'exemptGain')::numeric
        + (p_prepared ->> 'taxableGain')::numeric <>
          (p_prepared ->> 'taxGainOrLoss')::numeric
        or (p_prepared ->> 'nonDeductibleLoss')::numeric <> 0
        or (p_prepared ->> 'deductibleLoss')::numeric <> 0)
    ) or (
      (p_prepared ->> 'taxGainOrLoss')::numeric < 0
      and ((p_prepared ->> 'nonDeductibleLoss')::numeric
        + (p_prepared ->> 'deductibleLoss')::numeric <>
          -(p_prepared ->> 'taxGainOrLoss')::numeric
        or (p_prepared ->> 'exemptGain')::numeric <> 0
        or (p_prepared ->> 'taxableGain')::numeric <> 0)
    )
  then raise exception 'investments_dependency_unavailable'; end if;
  if exists (
    select 1 from investments.economic_events event
    where event.event_id = v_event_id
       or (
         event.created_by = v_actor_id and event.company_id = v_company_id
         and event.idempotency_key = p_request ->> 'idempotencyKey'
       )
  ) or exists (
    select 1 from investments.share_sales sale
    where sale.action_id = v_event_id
       or (
         sale.created_by = v_actor_id and sale.company_id = v_company_id
         and sale.idempotency_key = p_request ->> 'idempotencyKey'
       )
  ) then raise exception 'investments_idempotency_key_reused'; end if;

  select position.* into v_position
  from investments.positions position
  where position.id = (p_request ->> 'positionId')::uuid
  for update;
  if not found or v_position.company_id <> v_company_id
    or v_position.id <> (p_prepared ->> 'positionId')::uuid
  then raise exception 'investments_dependency_unavailable'; end if;
  perform 1 from investments.acquisition_lots lot
  where lot.position_id = v_position.id and lot.remaining_share_count > 0
  order by lot.acquisition_date, lot.id for update;
  select coalesce(pg_catalog.sum(lot.remaining_share_count), 0),
    coalesce(pg_catalog.sum(lot.remaining_cost_basis), 0),
    coalesce(pg_catalog.sum(lot.remaining_tax_basis), 0)
  into v_available_shares, v_available_book, v_available_tax
  from investments.acquisition_lots lot
  where lot.position_id = v_position.id and lot.remaining_share_count > 0;
  if v_available_shares <> v_position.share_count
    or v_available_book <> v_position.cost_basis
    or v_available_tax <> v_position.tax_basis
    or v_sold > v_available_shares
  then raise exception 'investments_dependency_unavailable'; end if;

  insert into investments.share_sales (
    action_id, company_id, income_year, idempotency_key, request_fingerprint,
    position_id, accounting_entry_id, legacy_imported, sale_date,
    sold_share_count, proceeds, transaction_costs, net_proceeds,
    fifo_cost_basis_reduction, fifo_tax_basis_reduction,
    gain_or_loss, book_gain_or_loss, tax_gain_or_loss,
    exempt_gain, taxable_gain, non_deductible_loss, deductible_loss,
    remaining_share_count, remaining_cost_basis, remaining_tax_basis,
    sale_year_fund_equity_ratio_basis_points, fund_tax_statement_reference,
    bank_transaction_id, document_id, document_status,
    evidence_mode, evidence_reference, evidence_digest, owner_attested,
    calculation_id, created_by, completed_at
  ) values (
    v_event_id, v_company_id, 2026, p_request ->> 'idempotencyKey',
    investments.share_sale_recognition_fingerprint_v2(p_request),
    v_position.id, p_entry_id, false, (p_request ->> 'saleDate')::date,
    v_sold, v_proceeds, v_costs, v_net, v_book_cost, v_tax_basis,
    (p_prepared ->> 'bookGainOrLoss')::numeric,
    (p_prepared ->> 'bookGainOrLoss')::numeric,
    (p_prepared ->> 'taxGainOrLoss')::numeric,
    (p_prepared ->> 'exemptGain')::numeric,
    (p_prepared ->> 'taxableGain')::numeric,
    (p_prepared ->> 'nonDeductibleLoss')::numeric,
    (p_prepared ->> 'deductibleLoss')::numeric,
    v_available_shares - v_sold, v_available_book - v_book_cost,
    v_available_tax - v_tax_basis,
    nullif(p_request ->> 'saleYearFundEquityRatioBasisPoints', '')::integer,
    nullif(pg_catalog.btrim(p_request ->> 'fundTaxStatementReference'), ''),
    null, (p_request -> 'documentFacts' -> 0 ->> 'recordId')::uuid,
    'attached', p_request ->> 'evidenceMode',
    pg_catalog.btrim(p_request ->> 'evidenceReference'),
    p_prepared ->> 'evidenceDigest', (p_request ->> 'ownerAttested')::boolean,
    p_prepared ->> 'calculationId', v_actor_id, pg_catalog.now()
  );

  v_left := v_sold;
  for v_lot in
    select lot.* from investments.acquisition_lots lot
    where lot.position_id = v_position.id and lot.remaining_share_count > 0
    order by lot.acquisition_date, lot.id for update
  loop
    exit when v_left = 0;
    v_allocated_shares := least(v_left, v_lot.remaining_share_count);
    v_allocated_book := case
      when v_allocated_shares = v_lot.remaining_share_count
        then v_lot.remaining_cost_basis
      else pg_catalog.round(
        v_lot.remaining_cost_basis * v_allocated_shares /
          v_lot.remaining_share_count, 2
      )
    end;
    v_allocated_tax := case
      when v_allocated_shares = v_lot.remaining_share_count
        then v_lot.remaining_tax_basis
      else pg_catalog.round(
        v_lot.remaining_tax_basis * v_allocated_shares /
          v_lot.remaining_share_count, 2
      )
    end;
    v_order := v_order + 1;
    select value into v_calc
    from pg_catalog.jsonb_array_elements(p_prepared -> 'lotCalculations') value
    where (value ->> 'lotId')::uuid = v_lot.id
      and (value ->> 'allocationOrder')::integer = v_order;
    if not found
      or (v_calc ->> 'allocatedShareCount')::numeric <> v_allocated_shares
      or (v_calc ->> 'allocatedBookCostBasis')::numeric <> v_allocated_book
      or (v_calc ->> 'allocatedTaxBasis')::numeric <> v_allocated_tax
      or (v_calc ->> 'taxGainOrLoss')::numeric <>
        (v_calc ->> 'allocatedNetProceeds')::numeric - v_allocated_tax
      or (v_position.kind = 'norwegian_equity_fund'
        and nullif(v_calc ->> 'averageFundEquityRatioBasisPoints', '') is null)
      or (v_position.kind <> 'norwegian_equity_fund'
        and nullif(v_calc ->> 'averageFundEquityRatioBasisPoints', '') is not null)
    then raise exception 'investments_dependency_unavailable'; end if;

    insert into investments.share_sale_allocations (
      sale_action_id, company_id, position_id, acquisition_lot_id,
      allocation_order, acquisition_date, allocated_share_count,
      allocated_cost_basis, allocated_book_cost_basis, allocated_tax_basis,
      allocated_net_proceeds, average_fund_equity_ratio_basis_points,
      tax_gain_or_loss, exempt_gain, taxable_gain,
      non_deductible_loss, deductible_loss, created_by
    ) values (
      v_event_id, v_company_id, v_position.id, v_lot.id, v_order,
      v_lot.acquisition_date, v_allocated_shares,
      v_allocated_book, v_allocated_book, v_allocated_tax,
      (v_calc ->> 'allocatedNetProceeds')::numeric,
      nullif(v_calc ->> 'averageFundEquityRatioBasisPoints', '')::numeric,
      (v_calc ->> 'taxGainOrLoss')::numeric,
      (v_calc ->> 'exemptGain')::numeric,
      (v_calc ->> 'taxableGain')::numeric,
      (v_calc ->> 'nonDeductibleLoss')::numeric,
      (v_calc ->> 'deductibleLoss')::numeric, v_actor_id
    );
    update investments.acquisition_lots
    set remaining_share_count = remaining_share_count - v_allocated_shares,
        remaining_cost_basis = remaining_cost_basis - v_allocated_book,
        remaining_tax_basis = remaining_tax_basis - v_allocated_tax
    where id = v_lot.id
      and remaining_share_count = v_lot.remaining_share_count
      and remaining_cost_basis = v_lot.remaining_cost_basis
      and remaining_tax_basis = v_lot.remaining_tax_basis;
    get diagnostics v_count = row_count;
    if v_count <> 1 then raise exception 'investments_dependency_unavailable'; end if;
    v_checked_book := v_checked_book + v_allocated_book;
    v_checked_tax := v_checked_tax + v_allocated_tax;
    v_left := v_left - v_allocated_shares;
  end loop;

  if v_left <> 0 or v_checked_book <> v_book_cost
    or v_checked_tax <> v_tax_basis
    or (select pg_catalog.count(*) from investments.share_sale_allocations allocation
      where allocation.sale_action_id = v_event_id) <>
      pg_catalog.jsonb_array_length(p_prepared -> 'lotCalculations')
    or (select coalesce(pg_catalog.sum(allocation.allocated_net_proceeds), 0)
      from investments.share_sale_allocations allocation
      where allocation.sale_action_id = v_event_id) <> v_net
    or (select coalesce(pg_catalog.sum(allocation.tax_gain_or_loss), 0)
      from investments.share_sale_allocations allocation
      where allocation.sale_action_id = v_event_id) <>
      (p_prepared ->> 'taxGainOrLoss')::numeric
    or (select coalesce(pg_catalog.sum(allocation.exempt_gain), 0)
      from investments.share_sale_allocations allocation
      where allocation.sale_action_id = v_event_id) <>
      (p_prepared ->> 'exemptGain')::numeric
    or (select coalesce(pg_catalog.sum(allocation.taxable_gain), 0)
      from investments.share_sale_allocations allocation
      where allocation.sale_action_id = v_event_id) <>
      (p_prepared ->> 'taxableGain')::numeric
    or (select coalesce(pg_catalog.sum(allocation.non_deductible_loss), 0)
      from investments.share_sale_allocations allocation
      where allocation.sale_action_id = v_event_id) <>
      (p_prepared ->> 'nonDeductibleLoss')::numeric
    or (select coalesce(pg_catalog.sum(allocation.deductible_loss), 0)
      from investments.share_sale_allocations allocation
      where allocation.sale_action_id = v_event_id) <>
      (p_prepared ->> 'deductibleLoss')::numeric
  then raise exception 'investments_dependency_unavailable'; end if;

  select coalesce(pg_catalog.sum(lot.remaining_share_count), 0),
    coalesce(pg_catalog.sum(lot.remaining_cost_basis), 0),
    coalesce(pg_catalog.sum(lot.remaining_tax_basis), 0)
  into v_remaining_shares, v_remaining_book, v_remaining_tax
  from investments.acquisition_lots lot
  where lot.position_id = v_position.id and lot.remaining_share_count > 0;
  update investments.positions
  set share_count = v_remaining_shares,
      cost_basis = v_remaining_book,
      tax_basis = v_remaining_tax,
      movements = movements || pg_catalog.jsonb_build_array(
        pg_catalog.jsonb_build_object(
          'event_id', v_event_id,
          'movement_type', 'sale_recognition',
          'movement_date', (p_request ->> 'saleDate')::date,
          'share_delta', -v_sold,
          'book_cost_basis_delta', -v_book_cost,
          'tax_basis_delta', -v_tax_basis,
          'book_gain_or_loss', p_prepared ->> 'bookGainOrLoss',
          'tax_gain_or_loss', p_prepared ->> 'taxGainOrLoss',
          'calculation_id', p_prepared ->> 'calculationId',
          'evidence_digest', p_prepared ->> 'evidenceDigest'
        )
      ),
      updated_at = pg_catalog.now()
  where id = v_position.id;
  get diagnostics v_count = row_count;
  if v_count <> 1 then raise exception 'investments_dependency_unavailable'; end if;

  insert into investments.economic_events (
    event_id, company_id, income_year, event_kind, position_id,
    recognition_date, policy_version, idempotency_key, request_fingerprint,
    evidence_mode, evidence_reference, owner_attested, evidence_digest,
    calculation_id, recognition_accounting_entry_id,
    expected_settlement_amount, settlement_balance_kind, created_by
  ) values (
    v_event_id, v_company_id, 2026, 'share_sale', v_position.id,
    (p_request ->> 'saleDate')::date, 'domestic_2026_v2',
    p_request ->> 'idempotencyKey',
    investments.share_sale_recognition_fingerprint_v2(p_request),
    p_request ->> 'evidenceMode',
    pg_catalog.btrim(p_request ->> 'evidenceReference'),
    (p_request ->> 'ownerAttested')::boolean,
    p_prepared ->> 'evidenceDigest', p_prepared ->> 'calculationId',
    p_entry_id, v_net, 'sale_receivable', v_actor_id
  );
  perform investments.record_lifecycle_document_sources_v2(
    v_company_id, v_event_id, p_request -> 'documentFacts'
  );

  insert into public.audit_events (company_id, actor_id, category, action, message)
  values (
    v_company_id, v_actor_id, 'ledger', 'investment_sale_recognized',
    'Investeringssalg innregnet uten å anta kontantoppgjør.'
  );
  return pg_catalog.jsonb_build_object(
    'eventId', v_event_id,
    'positionId', v_position.id,
    'recognitionAccountingEntryId', p_entry_id,
    'expectedSettlementAmount', v_net,
    'settlementBalanceKind', 'sale_receivable',
    'replayed', false
  );
end;
$function$;

alter function investments.lifecycle_document_evidence_is_valid_v2(jsonb)
  owner to investments_store_owner;
alter function investments.record_lifecycle_document_sources_v2(uuid, uuid, jsonb)
  owner to investments_store_owner;
alter function investments.share_sale_recognition_fingerprint_v2(jsonb)
  owner to investments_store_owner;
alter function investments.get_share_sale_recognition_replay_v2(jsonb, text)
  owner to investments_store_owner;
alter function investments.prepare_share_sale_recognition_v2(jsonb, text)
  owner to investments_store_owner;
alter function investments.complete_share_sale_recognition_v2(
  jsonb, uuid, jsonb, text
) owner to investments_store_owner;

revoke all on function
  investments.lifecycle_document_evidence_is_valid_v2(jsonb),
  investments.record_lifecycle_document_sources_v2(uuid, uuid, jsonb),
  investments.share_sale_recognition_fingerprint_v2(jsonb),
  investments.get_share_sale_recognition_replay_v2(jsonb, text),
  investments.prepare_share_sale_recognition_v2(jsonb, text),
  investments.complete_share_sale_recognition_v2(jsonb, uuid, jsonb, text)
from public, anon, authenticated, service_role;

grant execute on function
  investments.get_share_sale_recognition_replay_v2(jsonb, text),
  investments.prepare_share_sale_recognition_v2(jsonb, text),
  investments.complete_share_sale_recognition_v2(jsonb, uuid, jsonb, text)
to investments_workflow_executor;
grant execute on function
  investments.lifecycle_document_evidence_is_valid_v2(jsonb),
  investments.record_lifecycle_document_sources_v2(uuid, uuid, jsonb),
  investments.share_sale_recognition_fingerprint_v2(jsonb)
to investments_store_owner;

do $membership_revoke$
begin
  execute pg_catalog.format(
    'revoke investments_store_owner, investments_workflow_executor, ledger_store_owner from %I',
    current_user
  );
end
$membership_revoke$;

commit;
