begin;

-- Restore the predecessor manual-evidence validation during bounded rollback.

create or replace function investments.prepare_share_purchase_v1(
  p_request jsonb, p_verified_subject text
)
returns jsonb language plpgsql security definer set search_path = ''
as $function$
declare
  v_actor_id uuid := public.company_access_auth_uid_v1();
  v_company_id uuid := (p_request ->> 'companyId')::uuid;
  v_kind text := p_request ->> 'investmentKind';
  v_classification text := p_request ->> 'accountingClassification';
  v_key text := pg_catalog.btrim(p_request ->> 'investmentKey');
  v_name text := pg_catalog.btrim(p_request ->> 'investmentName');
  v_org text := nullif(pg_catalog.btrim(p_request ->> 'orgNumber'), '');
  v_count bigint := (p_request ->> 'shareCount')::bigint;
  v_purchase numeric := (p_request ->> 'purchaseAmount')::numeric;
  v_costs numeric := (p_request ->> 'transactionCosts')::numeric;
  v_capitalized numeric := (p_request ->> 'capitalizedCost')::numeric;
  v_fund_ratio integer := nullif(
    p_request ->> 'fundEquityRatioBasisPoints', ''
  )::integer;
  v_fund_reference text := nullif(pg_catalog.btrim(
    p_request ->> 'fundTaxStatementReference'
  ), '');
  v_position investments.positions%rowtype;
  v_position_created boolean := false;
  v_lot_id uuid := extensions.gen_random_uuid();
begin
  if v_actor_id is null or v_actor_id is distinct from p_verified_subject::uuid
    or not public.company_access_is_accepted_owner_v1(v_company_id)
  then raise exception 'investments_forbidden'; end if;
  if not pg_catalog.pg_try_advisory_xact_lock(pg_catalog.hashtextextended(
    'investments:v1:' || v_actor_id::text || ':' || v_company_id::text ||
      ':share-purchase:' || coalesce(p_request ->> 'idempotencyKey', ''), 0
  )) then raise exception 'investments_idempotency_in_progress'; end if;
  if coalesce(p_request ->> 'idempotencyKey', '') !~ '^[A-Za-z0-9._:-]{16,255}$'
    or v_key = '' or v_name = '' or pg_catalog.length(v_name) > 255
    or v_count <= 0 or v_purchase <= 0 or v_costs < 0
    or v_capitalized <> v_purchase + v_costs
    or pg_catalog.round(v_purchase, 2) <> v_purchase
    or pg_catalog.round(v_costs, 2) <> v_costs
    or (p_request ->> 'acquisitionDate')::date is null
    or extract(year from (p_request ->> 'acquisitionDate')::date)::integer
      <> (p_request ->> 'incomeYear')::integer
    or p_request ->> 'taxTreatment' <> 'fritaksmetoden'
    or p_request ->> 'evidenceDigest' !~ '^[0-9a-f]{64}$'
    or p_request ->> 'calculationId' !~ '^[0-9a-f]{64}$'
    or nullif(pg_catalog.btrim(p_request ->> 'evidenceReference'), '') is null
    or not (
      (
        p_request ->> 'evidenceMode' = 'linked_sources'
        and nullif(p_request ->> 'bankTransactionId', '') is not null
        and nullif(p_request ->> 'documentId', '') is not null
        and p_request ->> 'documentStatus' = 'attached'
        and (p_request ->> 'ownerAttested')::boolean = false
      ) or (
        p_request ->> 'evidenceMode' = 'manual_fallback'
        and nullif(p_request ->> 'bankTransactionId', '') is null
        and nullif(p_request ->> 'documentId', '') is null
        and p_request ->> 'documentStatus' = 'missing_accepted_warning'
        and (p_request ->> 'ownerAttested')::boolean = true
      )
    )
    or not (
      (v_kind = 'norwegian_private_company'
        and v_classification in ('subsidiary', 'associate', 'other_long_term')
        and v_org ~ '^[0-9]{9}$' and v_fund_ratio is null
        and v_fund_reference is null)
      or (v_kind = 'norwegian_listed_share'
        and v_classification = 'current_listed_share'
        and v_key ~ '^NO[A-Z0-9]{10}$'
        and (v_org is null or v_org ~ '^[0-9]{9}$')
        and v_fund_ratio is null and v_fund_reference is null)
      or (v_kind = 'norwegian_equity_fund'
        and v_classification = 'current_fund'
        and v_key ~ '^NO[A-Z0-9]{10}$' and v_org is null
        and v_fund_ratio between 0 and 10000
        and v_fund_reference is not null)
    )
  then raise exception 'investments_invalid_input'; end if;
  if exists (
    select 1 from investments.share_purchases purchase
    where purchase.action_id = (p_request ->> 'actionId')::uuid
       or (purchase.created_by = v_actor_id and purchase.company_id = v_company_id
         and purchase.idempotency_key = p_request ->> 'idempotencyKey')
  ) then raise exception 'investments_idempotency_key_reused'; end if;

  select position.* into v_position from investments.positions position
  where position.company_id = v_company_id and position.investment_key = v_key
  for update;
  if found then
    if v_position.name <> v_name or v_position.kind <> v_kind
      or v_position.accounting_classification <> v_classification
      or v_position.tax_treatment <> p_request ->> 'taxTreatment'
      or v_position.org_number is distinct from v_org
      or v_position.fund_equity_ratio_basis_points is distinct from v_fund_ratio
      or v_position.fund_tax_statement_reference is distinct from v_fund_reference
      or v_position.lot_history_status <> 'complete'
    then raise exception 'investments_invalid_input'; end if;
  else
    insert into investments.positions (
      company_id, investment_key, name, kind, accounting_classification,
      tax_treatment, org_number, fund_equity_ratio_basis_points,
      fund_tax_statement_reference, share_count, cost_basis, tax_basis,
      movements, lot_history_status, created_by
    ) values (
      v_company_id, v_key, v_name, v_kind, v_classification,
      p_request ->> 'taxTreatment', v_org, v_fund_ratio, v_fund_reference,
      0, 0, 0, '[]'::jsonb, 'complete', v_actor_id
    ) returning * into v_position;
    v_position_created := true;
  end if;

  insert into investments.acquisition_lots (
    id, company_id, position_id, acquisition_action_id, acquisition_date,
    original_share_count, remaining_share_count,
    original_cost_basis, remaining_cost_basis,
    original_tax_basis, remaining_tax_basis,
    acquisition_year_fund_equity_ratio_basis_points,
    fund_tax_statement_reference, created_by
  ) values (
    v_lot_id, v_company_id, v_position.id,
    (p_request ->> 'actionId')::uuid,
    (p_request ->> 'acquisitionDate')::date,
    v_count, 0, v_capitalized, 0, v_capitalized, 0,
    v_fund_ratio, v_fund_reference, v_actor_id
  );
  insert into investments.share_purchases (
    action_id, company_id, income_year, idempotency_key, request_fingerprint,
    position_id, acquisition_lot_id, position_created, legacy_imported,
    investment_key, investment_name, investment_kind,
    accounting_classification, tax_treatment, acquisition_date, share_count,
    purchase_amount, transaction_costs, capitalized_cost, org_number,
    fund_equity_ratio_basis_points, fund_tax_statement_reference,
    bank_transaction_id, document_id, document_status,
    evidence_mode, evidence_reference, evidence_digest, owner_attested,
    calculation_id, created_by
  ) values (
    (p_request ->> 'actionId')::uuid, v_company_id,
    (p_request ->> 'incomeYear')::integer, p_request ->> 'idempotencyKey',
    investments.share_purchase_fingerprint_v1(p_request),
    v_position.id, v_lot_id, v_position_created, false,
    v_key, v_name, v_kind, v_classification, p_request ->> 'taxTreatment',
    (p_request ->> 'acquisitionDate')::date, v_count,
    v_purchase, v_costs, v_capitalized, v_org, v_fund_ratio, v_fund_reference,
    nullif(p_request ->> 'bankTransactionId', '')::uuid,
    nullif(p_request ->> 'documentId', '')::uuid,
    p_request ->> 'documentStatus', p_request ->> 'evidenceMode',
    pg_catalog.btrim(p_request ->> 'evidenceReference'),
    p_request ->> 'evidenceDigest', (p_request ->> 'ownerAttested')::boolean,
    p_request ->> 'calculationId', v_actor_id
  );
  return pg_catalog.jsonb_build_object(
    'positionId', v_position.id, 'lotId', v_lot_id,
    'positionCreated', v_position_created, 'investmentName', v_name,
    'accountingClassification', v_classification,
    'capitalizedCost', v_capitalized,
    'evidenceDigest', p_request ->> 'evidenceDigest',
    'calculationId', p_request ->> 'calculationId'
  );
end;
$function$;

create or replace function investments.prepare_share_sale_v1(
  p_request jsonb, p_verified_subject text
)
returns jsonb language plpgsql security definer set search_path = ''
as $function$
declare
  v_actor_id uuid := public.company_access_auth_uid_v1();
  v_company_id uuid := (p_request ->> 'companyId')::uuid;
  v_position investments.positions%rowtype;
  v_lot investments.acquisition_lots%rowtype;
  v_sold bigint := (p_request ->> 'soldShareCount')::bigint;
  v_proceeds numeric := (p_request ->> 'proceeds')::numeric;
  v_costs numeric := (p_request ->> 'transactionCosts')::numeric;
  v_net numeric := (p_request ->> 'netProceeds')::numeric;
  v_sale_ratio integer := nullif(
    p_request ->> 'saleYearFundEquityRatioBasisPoints', ''
  )::integer;
  v_fund_reference text := nullif(pg_catalog.btrim(
    p_request ->> 'fundTaxStatementReference'
  ), '');
  v_available_shares bigint;
  v_available_book numeric;
  v_available_tax numeric;
  v_left bigint;
  v_allocated_shares bigint;
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
    'investments:v1:' || v_actor_id::text || ':' || v_company_id::text ||
      ':share-sale:' || coalesce(p_request ->> 'idempotencyKey', ''), 0
  )) then raise exception 'investments_idempotency_in_progress'; end if;
  if coalesce(p_request ->> 'idempotencyKey', '') !~ '^[A-Za-z0-9._:-]{16,255}$'
    or v_sold <= 0 or v_proceeds <= 0 or v_costs < 0 or v_costs >= v_proceeds
    or v_net <> v_proceeds - v_costs
    or pg_catalog.round(v_proceeds, 2) <> v_proceeds
    or pg_catalog.round(v_costs, 2) <> v_costs
    or extract(year from (p_request ->> 'saleDate')::date)::integer
      <> (p_request ->> 'incomeYear')::integer
    or p_request ->> 'evidenceDigest' !~ '^[0-9a-f]{64}$'
    or nullif(pg_catalog.btrim(p_request ->> 'evidenceReference'), '') is null
    or not (
      (p_request ->> 'evidenceMode' = 'linked_sources'
        and nullif(p_request ->> 'bankTransactionId', '') is not null
        and nullif(p_request ->> 'documentId', '') is not null
        and p_request ->> 'documentStatus' = 'attached'
        and (p_request ->> 'ownerAttested')::boolean = false)
      or (p_request ->> 'evidenceMode' = 'manual_fallback'
        and nullif(p_request ->> 'bankTransactionId', '') is null
        and nullif(p_request ->> 'documentId', '') is null
        and p_request ->> 'documentStatus' = 'missing_accepted_warning'
        and (p_request ->> 'ownerAttested')::boolean = true)
    )
  then raise exception 'investments_invalid_input'; end if;
  if exists (
    select 1 from investments.share_sales sale
    where sale.action_id = (p_request ->> 'actionId')::uuid
       or (sale.created_by = v_actor_id and sale.company_id = v_company_id
         and sale.idempotency_key = p_request ->> 'idempotencyKey')
  ) then raise exception 'investments_idempotency_key_reused'; end if;

  select position.* into v_position from investments.positions position
  where position.id = (p_request ->> 'positionId')::uuid for update;
  if not found or v_position.company_id <> v_company_id
    or v_position.lot_history_status <> 'complete'
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
    v_allocated_shares := case when v_left < v_lot.remaining_share_count
      then v_left else v_lot.remaining_share_count end;
    v_allocated_book := case
      when v_allocated_shares = v_lot.remaining_share_count
        then v_lot.remaining_cost_basis
      else pg_catalog.round(v_lot.remaining_cost_basis * v_allocated_shares /
        v_lot.remaining_share_count, 2) end;
    v_allocated_tax := case
      when v_allocated_shares = v_lot.remaining_share_count
        then v_lot.remaining_tax_basis
      else pg_catalog.round(v_lot.remaining_tax_basis * v_allocated_shares /
        v_lot.remaining_share_count, 2) end;
    v_order := v_order + 1;
    v_lot_facts := v_lot_facts || pg_catalog.jsonb_build_array(
      pg_catalog.jsonb_build_object(
        'lotId', v_lot.id, 'allocationOrder', v_order,
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
  insert into investments.share_sales (
    action_id, company_id, income_year, idempotency_key, request_fingerprint,
    position_id, legacy_imported, sale_date, sold_share_count,
    proceeds, transaction_costs, net_proceeds,
    fifo_cost_basis_reduction, fifo_tax_basis_reduction,
    gain_or_loss, book_gain_or_loss, tax_gain_or_loss,
    exempt_gain, taxable_gain, non_deductible_loss, deductible_loss,
    remaining_share_count, remaining_cost_basis, remaining_tax_basis,
    sale_year_fund_equity_ratio_basis_points, fund_tax_statement_reference,
    bank_transaction_id, document_id, document_status,
    evidence_mode, evidence_reference, evidence_digest, owner_attested,
    calculation_id, created_by
  ) values (
    (p_request ->> 'actionId')::uuid, v_company_id,
    (p_request ->> 'incomeYear')::integer, p_request ->> 'idempotencyKey',
    investments.share_sale_fingerprint_v1(p_request), v_position.id, false,
    (p_request ->> 'saleDate')::date, v_sold, v_proceeds, v_costs, v_net,
    v_book_cost, v_tax_basis, v_net - v_book_cost,
    v_net - v_book_cost, v_net - v_tax_basis, 0, 0, 0, 0,
    v_available_shares - v_sold, v_available_book - v_book_cost,
    v_available_tax - v_tax_basis,
    v_sale_ratio, v_fund_reference,
    nullif(p_request ->> 'bankTransactionId', '')::uuid,
    nullif(p_request ->> 'documentId', '')::uuid,
    p_request ->> 'documentStatus', p_request ->> 'evidenceMode',
    pg_catalog.btrim(p_request ->> 'evidenceReference'),
    p_request ->> 'evidenceDigest', (p_request ->> 'ownerAttested')::boolean,
    pg_catalog.repeat('0', 64), v_actor_id
  );
  return pg_catalog.jsonb_build_object(
    'positionId', v_position.id, 'investmentName', v_position.name,
    'investmentKind', v_position.kind,
    'accountingClassification', v_position.accounting_classification,
    'fifoBookCostBasisReduction', v_book_cost,
    'fifoTaxBasisReduction', v_tax_basis, 'lotFacts', v_lot_facts
  );
end;
$function$;

create or replace function investments.prepare_received_dividend_v1(
  p_request jsonb, p_verified_subject text
)
returns jsonb language plpgsql security definer set search_path = ''
as $function$
declare
  v_actor_id uuid := public.company_access_auth_uid_v1();
  v_company_id uuid := (p_request ->> 'companyId')::uuid;
  v_position investments.positions%rowtype;
  v_name text := pg_catalog.btrim(p_request ->> 'payingCompanyName');
  v_group boolean := (p_request ->> 'groupExceptionClaimed')::boolean;
  v_ownership integer := nullif(
    p_request ->> 'yearEndOwnershipBasisPoints', ''
  )::integer;
  v_votes integer := nullif(
    p_request ->> 'yearEndVotingBasisPoints', ''
  )::integer;
  v_group_reference text := nullif(pg_catalog.btrim(
    p_request ->> 'groupEvidenceReference'
  ), '');
begin
  if v_actor_id is null or v_actor_id is distinct from p_verified_subject::uuid
    or not public.company_access_is_accepted_owner_v1(v_company_id)
  then raise exception 'investments_forbidden'; end if;
  if not pg_catalog.pg_try_advisory_xact_lock(pg_catalog.hashtextextended(
    'investments:v1:' || v_actor_id::text || ':' || v_company_id::text ||
      ':received-dividend:' || coalesce(p_request ->> 'idempotencyKey', ''), 0
  )) then raise exception 'investments_idempotency_in_progress'; end if;
  if coalesce(p_request ->> 'idempotencyKey', '') !~ '^[A-Za-z0-9._:-]{16,255}$'
    or v_name = '' or pg_catalog.length(v_name) > 255
    or (p_request ->> 'grossAmount')::numeric <= 0
    or pg_catalog.round((p_request ->> 'grossAmount')::numeric, 2) <>
      (p_request ->> 'grossAmount')::numeric
    or (p_request ->> 'declaredDate')::date > (p_request ->> 'paidDate')::date
    or extract(year from (p_request ->> 'declaredDate')::date)::integer <>
      (p_request ->> 'incomeYear')::integer
    or extract(year from (p_request ->> 'paidDate')::date)::integer <>
      (p_request ->> 'incomeYear')::integer
    or p_request ->> 'taxTreatment' <> 'fritaksmetoden'
    or (p_request ->> 'lawfulDividendConfirmed')::boolean is not true
    or not (
      (v_group and v_ownership > 9000 and v_ownership <= 10000
        and v_votes > 9000 and v_votes <= 10000
        and v_group_reference is not null)
      or (not v_group and v_ownership is null and v_votes is null
        and v_group_reference is null)
    )
    or p_request ->> 'evidenceDigest' !~ '^[0-9a-f]{64}$'
    or nullif(pg_catalog.btrim(p_request ->> 'evidenceReference'), '') is null
    or not (
      (p_request ->> 'evidenceMode' = 'linked_sources'
        and nullif(p_request ->> 'bankTransactionId', '') is not null
        and nullif(p_request ->> 'documentId', '') is not null
        and p_request ->> 'documentStatus' = 'attached'
        and (p_request ->> 'ownerAttested')::boolean = false)
      or (p_request ->> 'evidenceMode' = 'manual_fallback'
        and nullif(p_request ->> 'bankTransactionId', '') is null
        and nullif(p_request ->> 'documentId', '') is null
        and p_request ->> 'documentStatus' = 'missing_accepted_warning'
        and (p_request ->> 'ownerAttested')::boolean = true)
    )
  then raise exception 'investments_invalid_input'; end if;
  if exists (
    select 1 from investments.received_dividends dividend
    where dividend.action_id = (p_request ->> 'actionId')::uuid
       or (dividend.created_by = v_actor_id and dividend.company_id = v_company_id
         and dividend.idempotency_key = p_request ->> 'idempotencyKey')
  ) then raise exception 'investments_idempotency_key_reused'; end if;
  select position.* into v_position from investments.positions position
  where position.id = (p_request ->> 'positionId')::uuid for update;
  if not found or v_position.company_id <> v_company_id
    or v_position.kind not in (
      'norwegian_private_company', 'norwegian_listed_share'
    )
  then raise exception 'investments_invalid_input'; end if;
  insert into investments.received_dividends (
    action_id, company_id, income_year, idempotency_key, request_fingerprint,
    position_id, legacy_imported, paying_company_name, declared_date, paid_date,
    gross_amount, tax_treatment, taxable_add_back,
    lawful_dividend_confirmed, group_exception_claimed,
    year_end_ownership_basis_points, year_end_voting_basis_points,
    group_evidence_reference, group_exception_applied,
    bank_transaction_id, document_id, document_status,
    evidence_mode, evidence_reference, evidence_digest, owner_attested,
    calculation_id, created_by
  ) values (
    (p_request ->> 'actionId')::uuid, v_company_id,
    (p_request ->> 'incomeYear')::integer, p_request ->> 'idempotencyKey',
    investments.received_dividend_fingerprint_v1(p_request),
    v_position.id, false, v_name,
    (p_request ->> 'declaredDate')::date,
    (p_request ->> 'paidDate')::date,
    (p_request ->> 'grossAmount')::numeric, p_request ->> 'taxTreatment', null,
    true, v_group, v_ownership, v_votes, v_group_reference, v_group,
    nullif(p_request ->> 'bankTransactionId', '')::uuid,
    nullif(p_request ->> 'documentId', '')::uuid,
    p_request ->> 'documentStatus', p_request ->> 'evidenceMode',
    pg_catalog.btrim(p_request ->> 'evidenceReference'),
    p_request ->> 'evidenceDigest', (p_request ->> 'ownerAttested')::boolean,
    pg_catalog.repeat('0', 64), v_actor_id
  );
  return pg_catalog.jsonb_build_object(
    'positionId', v_position.id, 'investmentName', v_position.name,
    'investmentKind', v_position.kind
  );
end;
$function$;

create or replace function investments.prepare_received_fund_distribution_v1(
  p_request jsonb, p_verified_subject text
)
returns jsonb language plpgsql security definer set search_path = ''
as $function$
declare
  v_actor_id uuid := public.company_access_auth_uid_v1();
  v_company_id uuid := (p_request ->> 'companyId')::uuid;
  v_position investments.positions%rowtype;
  v_name text := pg_catalog.btrim(p_request ->> 'fundName');
  v_tax_reference text := pg_catalog.btrim(
    p_request ->> 'fundTaxStatementReference'
  );
  v_ratio integer := (p_request ->> 'openingFundEquityRatioBasisPoints')::integer;
begin
  if v_actor_id is null or v_actor_id is distinct from p_verified_subject::uuid
    or not public.company_access_is_accepted_owner_v1(v_company_id)
  then raise exception 'investments_forbidden'; end if;
  if not pg_catalog.pg_try_advisory_xact_lock(pg_catalog.hashtextextended(
    'investments:v1:' || v_actor_id::text || ':' || v_company_id::text ||
      ':fund-distribution:' || coalesce(p_request ->> 'idempotencyKey', ''), 0
  )) then raise exception 'investments_idempotency_in_progress'; end if;
  if coalesce(p_request ->> 'idempotencyKey', '') !~ '^[A-Za-z0-9._:-]{16,255}$'
    or v_name = '' or pg_catalog.length(v_name) > 255
    or v_tax_reference = '' or pg_catalog.length(v_tax_reference) > 255
    or v_ratio not between 0 and 10000
    or (p_request ->> 'grossAmount')::numeric <= 0
    or pg_catalog.round((p_request ->> 'grossAmount')::numeric, 2) <>
      (p_request ->> 'grossAmount')::numeric
    or (p_request ->> 'entitlementDate')::date > (p_request ->> 'paidDate')::date
    or extract(year from (p_request ->> 'entitlementDate')::date)::integer <>
      (p_request ->> 'incomeYear')::integer
    or extract(year from (p_request ->> 'paidDate')::date)::integer <>
      (p_request ->> 'incomeYear')::integer
    or p_request ->> 'evidenceDigest' !~ '^[0-9a-f]{64}$'
    or nullif(pg_catalog.btrim(p_request ->> 'evidenceReference'), '') is null
    or not (
      (p_request ->> 'evidenceMode' = 'linked_sources'
        and nullif(p_request ->> 'bankTransactionId', '') is not null
        and nullif(p_request ->> 'documentId', '') is not null
        and p_request ->> 'documentStatus' = 'attached'
        and (p_request ->> 'ownerAttested')::boolean = false)
      or (p_request ->> 'evidenceMode' = 'manual_fallback'
        and nullif(p_request ->> 'bankTransactionId', '') is null
        and nullif(p_request ->> 'documentId', '') is null
        and p_request ->> 'documentStatus' = 'missing_accepted_warning'
        and (p_request ->> 'ownerAttested')::boolean = true)
    )
  then raise exception 'investments_invalid_input'; end if;
  if exists (
    select 1 from investments.received_fund_distributions distribution
    where distribution.action_id = (p_request ->> 'actionId')::uuid
       or (distribution.created_by = v_actor_id
         and distribution.company_id = v_company_id
         and distribution.idempotency_key = p_request ->> 'idempotencyKey')
  ) then raise exception 'investments_idempotency_key_reused'; end if;
  select position.* into v_position from investments.positions position
  where position.id = (p_request ->> 'positionId')::uuid for update;
  if not found or v_position.company_id <> v_company_id
    or v_position.kind <> 'norwegian_equity_fund'
  then raise exception 'investments_invalid_input'; end if;
  insert into investments.received_fund_distributions (
    action_id, company_id, income_year, idempotency_key, request_fingerprint,
    position_id, fund_name, entitlement_date, paid_date, gross_amount,
    opening_fund_equity_ratio_basis_points, fund_tax_statement_reference,
    bank_transaction_id, document_id, document_status,
    evidence_mode, evidence_reference, evidence_digest, owner_attested,
    created_by
  ) values (
    (p_request ->> 'actionId')::uuid, v_company_id,
    (p_request ->> 'incomeYear')::integer, p_request ->> 'idempotencyKey',
    investments.received_fund_distribution_fingerprint_v1(p_request),
    v_position.id, v_name,
    (p_request ->> 'entitlementDate')::date,
    (p_request ->> 'paidDate')::date,
    (p_request ->> 'grossAmount')::numeric, v_ratio, v_tax_reference,
    nullif(p_request ->> 'bankTransactionId', '')::uuid,
    nullif(p_request ->> 'documentId', '')::uuid,
    p_request ->> 'documentStatus', p_request ->> 'evidenceMode',
    pg_catalog.btrim(p_request ->> 'evidenceReference'),
    p_request ->> 'evidenceDigest', (p_request ->> 'ownerAttested')::boolean,
    v_actor_id
  );
  return pg_catalog.jsonb_build_object(
    'positionId', v_position.id, 'investmentName', v_position.name,
    'investmentKind', v_position.kind
  );
end;
$function$;

create or replace function investments.prepare_correction_v1(
  p_request jsonb, p_verified_subject text
)
returns jsonb language plpgsql security definer set search_path = ''
as $function$
declare
  v_actor_id uuid := public.company_access_auth_uid_v1();
  v_company_id uuid := (p_request ->> 'companyId')::uuid;
  v_original_action_id uuid := (p_request ->> 'originalActionId')::uuid;
  v_replacement_action_id uuid := (p_request ->> 'replacementActionId')::uuid;
  v_kind text := p_request ->> 'originalActivityKind';
  v_position_id uuid;
  v_original_entry_id uuid;
  v_created_at timestamptz;
  v_purchase investments.share_purchases%rowtype;
  v_sale investments.share_sales%rowtype;
  v_lot investments.acquisition_lots%rowtype;
  v_position investments.positions%rowtype;
begin
  if v_actor_id is null or v_actor_id is distinct from p_verified_subject::uuid
    or not public.company_access_is_accepted_owner_v1(v_company_id)
  then raise exception 'investments_forbidden'; end if;
  if not pg_catalog.pg_try_advisory_xact_lock(pg_catalog.hashtextextended(
    'investments:v1:' || v_actor_id::text || ':' || v_company_id::text ||
      ':correction:' || coalesce(p_request ->> 'idempotencyKey', ''), 0
  )) then raise exception 'investments_idempotency_in_progress'; end if;
  if coalesce(p_request ->> 'idempotencyKey', '') !~ '^[A-Za-z0-9._:-]{16,255}$'
    or v_original_action_id = v_replacement_action_id
    or v_kind not in (
      'share_purchase', 'share_sale', 'dividend_received',
      'fund_distribution_received'
    )
    or p_request ->> 'replacementActivityKind' is distinct from v_kind
    or pg_catalog.btrim(coalesce(p_request ->> 'reason', '')) = ''
    or pg_catalog.length(p_request ->> 'reason') > 500
    or p_request ->> 'evidenceDigest' !~ '^[0-9a-f]{64}$'
    or not coalesce((
      (p_request ->> 'evidenceMode' = 'linked_sources'
        and p_request ->> 'bankTransactionId' is not null
        and p_request ->> 'documentId' is not null
        and p_request ->> 'documentStatus' = 'attached'
        and (p_request ->> 'ownerAttested')::boolean = false)
      or (p_request ->> 'evidenceMode' = 'manual_fallback'
        and p_request ->> 'bankTransactionId' is null
        and p_request ->> 'documentId' is null
        and p_request ->> 'documentStatus' = 'missing_accepted_warning'
        and (p_request ->> 'ownerAttested')::boolean = true)
    ), false)
    or nullif(pg_catalog.btrim(p_request ->> 'evidenceReference'), '') is null
    or pg_catalog.length(p_request ->> 'evidenceReference') > 255
    or extract(year from (p_request ->> 'correctionDate')::date)::integer
      <> (p_request ->> 'incomeYear')::integer
  then raise exception 'investments_invalid_input'; end if;
  if exists (
    select 1 from investments.corrections correction
    where correction.correction_id = (p_request ->> 'correctionId')::uuid
       or (correction.created_by = v_actor_id
         and correction.company_id = v_company_id
         and correction.idempotency_key = p_request ->> 'idempotencyKey')
       or (correction.company_id = v_company_id
         and correction.original_action_id = v_original_action_id)
  ) then raise exception 'investments_idempotency_key_reused'; end if;
  if exists (select 1 from investments.share_purchases where action_id = v_replacement_action_id)
    or exists (select 1 from investments.share_sales where action_id = v_replacement_action_id)
    or exists (select 1 from investments.received_dividends where action_id = v_replacement_action_id)
    or exists (select 1 from investments.received_fund_distributions where action_id = v_replacement_action_id)
  then raise exception 'investments_idempotency_key_reused'; end if;

  if v_kind = 'share_purchase' then
    select purchase.* into v_purchase from investments.share_purchases purchase
    where purchase.action_id = v_original_action_id for update;
    if not found or v_purchase.company_id <> v_company_id
      or v_purchase.income_year <> (p_request ->> 'incomeYear')::integer
      or v_purchase.accounting_entry_id is null
    then raise exception 'investments_invalid_input'; end if;
    select lot.* into v_lot from investments.acquisition_lots lot
    where lot.id = v_purchase.acquisition_lot_id for update;
    select position.* into v_position from investments.positions position
    where position.id = v_purchase.position_id for update;
    if not found or v_lot.remaining_share_count <> v_lot.original_share_count
      or v_lot.remaining_cost_basis <> v_lot.original_cost_basis
      or v_lot.remaining_tax_basis <> v_lot.original_tax_basis
      or exists (
        select 1 from investments.share_sales later
        where later.position_id = v_purchase.position_id
          and later.accounting_entry_id is not null
          and (later.created_at, later.action_id) >
            (v_purchase.created_at, v_purchase.action_id)
      )
    then raise exception 'investments_dependency_unavailable'; end if;
    update investments.acquisition_lots
    set remaining_share_count = 0, remaining_cost_basis = 0,
        remaining_tax_basis = 0
    where id = v_lot.id;
    update investments.positions
    set share_count = share_count - v_lot.original_share_count,
        cost_basis = cost_basis - v_lot.original_cost_basis,
        tax_basis = tax_basis - v_lot.original_tax_basis,
        movements = movements || pg_catalog.jsonb_build_array(
          pg_catalog.jsonb_build_object(
            'action_id', p_request ->> 'correctionId',
            'movement_type', 'correction_reversal',
            'movement_date', p_request ->> 'correctionDate',
            'corrected_action_id', v_original_action_id,
            'share_delta', -v_lot.original_share_count,
            'book_cost_basis_delta', -v_lot.original_cost_basis,
            'tax_basis_delta', -v_lot.original_tax_basis,
            'evidence_digest', p_request ->> 'evidenceDigest'
          )
        ), updated_at = pg_catalog.now()
    where id = v_position.id
      and share_count >= v_lot.original_share_count
      and cost_basis >= v_lot.original_cost_basis
      and tax_basis >= v_lot.original_tax_basis;
    if not found then raise exception 'investments_dependency_unavailable'; end if;
    v_position_id := v_purchase.position_id;
    v_original_entry_id := v_purchase.accounting_entry_id;
    v_created_at := v_purchase.created_at;
  elsif v_kind = 'share_sale' then
    select sale.* into v_sale from investments.share_sales sale
    where sale.action_id = v_original_action_id for update;
    if not found or v_sale.company_id <> v_company_id
      or v_sale.income_year <> (p_request ->> 'incomeYear')::integer
      or v_sale.accounting_entry_id is null
      or exists (
        select 1 from investments.share_sales later
        where later.position_id = v_sale.position_id
          and later.accounting_entry_id is not null
          and (later.created_at, later.action_id) >
            (v_sale.created_at, v_sale.action_id)
      )
      or exists (
        select 1 from investments.share_purchases later
        where later.position_id = v_sale.position_id
          and later.accounting_entry_id is not null
          and (later.created_at, later.action_id) >
            (v_sale.created_at, v_sale.action_id)
      )
    then raise exception 'investments_dependency_unavailable'; end if;
    perform 1 from investments.acquisition_lots lot
    join investments.share_sale_allocations allocation
      on allocation.acquisition_lot_id = lot.id
    where allocation.sale_action_id = v_sale.action_id
    order by allocation.allocation_order for update of lot;
    if not found then raise exception 'investments_dependency_unavailable'; end if;
    update investments.acquisition_lots lot
    set remaining_share_count = lot.remaining_share_count + allocation.allocated_share_count,
        remaining_cost_basis = lot.remaining_cost_basis + allocation.allocated_book_cost_basis,
        remaining_tax_basis = lot.remaining_tax_basis + allocation.allocated_tax_basis
    from investments.share_sale_allocations allocation
    where allocation.sale_action_id = v_sale.action_id
      and allocation.acquisition_lot_id = lot.id;
    update investments.positions position
    set share_count = position.share_count + v_sale.sold_share_count,
        cost_basis = position.cost_basis + v_sale.fifo_cost_basis_reduction,
        tax_basis = position.tax_basis + v_sale.fifo_tax_basis_reduction,
        movements = movements || pg_catalog.jsonb_build_array(
          pg_catalog.jsonb_build_object(
            'action_id', p_request ->> 'correctionId',
            'movement_type', 'correction_reversal',
            'movement_date', p_request ->> 'correctionDate',
            'corrected_action_id', v_original_action_id,
            'share_delta', v_sale.sold_share_count,
            'book_cost_basis_delta', v_sale.fifo_cost_basis_reduction,
            'tax_basis_delta', v_sale.fifo_tax_basis_reduction,
            'evidence_digest', p_request ->> 'evidenceDigest'
          )
        ), updated_at = pg_catalog.now()
    where position.id = v_sale.position_id;
    if not found then raise exception 'investments_dependency_unavailable'; end if;
    v_position_id := v_sale.position_id;
    v_original_entry_id := v_sale.accounting_entry_id;
    v_created_at := v_sale.created_at;
  elsif v_kind = 'dividend_received' then
    select dividend.position_id, dividend.accounting_entry_id, dividend.created_at
    into v_position_id, v_original_entry_id, v_created_at
    from investments.received_dividends dividend
    where dividend.action_id = v_original_action_id
      and dividend.company_id = v_company_id
      and dividend.income_year = (p_request ->> 'incomeYear')::integer
      and dividend.accounting_entry_id is not null for update;
    if not found then raise exception 'investments_invalid_input'; end if;
  else
    select distribution.position_id, distribution.accounting_entry_id,
      distribution.created_at
    into v_position_id, v_original_entry_id, v_created_at
    from investments.received_fund_distributions distribution
    where distribution.action_id = v_original_action_id
      and distribution.company_id = v_company_id
      and distribution.income_year = (p_request ->> 'incomeYear')::integer
      and distribution.accounting_entry_id is not null for update;
    if not found then raise exception 'investments_invalid_input'; end if;
  end if;
  return pg_catalog.jsonb_build_object(
    'originalAccountingEntryId', v_original_entry_id,
    'originalPositionId', v_position_id,
    'originalCreatedAt', v_created_at
  );
end;
$function$;

commit;
