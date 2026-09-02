begin;

do $membership$
begin
  execute pg_catalog.format(
    'grant investments_store_owner to %I', current_user
  );
end
$membership$;

create policy investments_cash_settlements_owner_supersede_update
on investments.cash_settlements for update to investments_store_owner
using (public.company_access_is_accepted_owner_v1(company_id))
with check (public.company_access_is_accepted_owner_v1(company_id));
grant update (supersedes_settlement_id)
on investments.cash_settlements to investments_store_owner;

create or replace function investments.prepare_settled_event_correction_v1(
  p_request jsonb, p_verified_subject text
) returns jsonb language plpgsql security definer set search_path = ''
as $function$
declare
  v_actor uuid := public.company_access_auth_uid_v1();
  v_company uuid := (p_request ->> 'companyId')::uuid;
  v_original_id uuid := (p_request ->> 'originalRecordId')::uuid;
  v_replacement_id uuid := (p_request ->> 'replacementRecordId')::uuid;
  v_settlement_request jsonb := p_request -> 'settlementCorrection';
  v_settlement_replacement jsonb := v_settlement_request -> 'replacement';
  v_event investments.economic_events%rowtype;
  v_settlement investments.cash_settlements%rowtype;
  v_recognition investments.share_purchase_recognitions%rowtype;
  v_sale investments.share_sales%rowtype;
  v_lot investments.acquisition_lots%rowtype;
  v_position investments.positions%rowtype;
  v_replacement_amount numeric;
begin
  if v_actor is null or v_actor is distinct from p_verified_subject::uuid
    or not public.company_access_is_accepted_owner_v1(v_company)
  then raise exception 'investments_forbidden'; end if;
  if not pg_catalog.pg_try_advisory_xact_lock(pg_catalog.hashtextextended(
    'investments:v2:' || v_company::text || ':settled-event-correction:' ||
      v_original_id::text, 0
  )) then raise exception 'investments_idempotency_in_progress'; end if;
  if p_request ->> 'targetKind' <> 'economic_event'
    or p_request ->> 'originalActivityKind' not in (
      'share_purchase', 'share_sale', 'dividend_received',
      'fund_distribution_received'
    )
    or p_request ->> 'replacementActivityKind' is distinct from
      p_request ->> 'originalActivityKind'
    or v_original_id = v_replacement_id
    or coalesce(p_request ->> 'idempotencyKey', '')
      !~ '^[A-Za-z0-9._:-]{16,255}$'
    or (p_request ->> 'incomeYear')::integer <> 2026
    or extract(year from (p_request ->> 'correctionDate')::date)::integer <> 2026
    or nullif(pg_catalog.btrim(p_request ->> 'reason'), '') is null
    or pg_catalog.length(p_request ->> 'reason') > 500
    or p_request ->> 'evidenceDigest' !~ '^[0-9a-f]{64}$'
    or not investments.lifecycle_document_evidence_is_valid_v2(p_request)
    or pg_catalog.jsonb_typeof(v_settlement_request) <> 'object'
    or v_settlement_request ->> 'targetKind' <> 'cash_settlement'
    or v_settlement_request ->> 'companyId' <> v_company::text
    or v_settlement_request ->> 'originalActivityKind' is distinct from
      p_request ->> 'originalActivityKind'
    or (v_settlement_request ->> 'correctionId')::uuid =
      (p_request ->> 'correctionId')::uuid
    or coalesce(v_settlement_request ->> 'idempotencyKey', '')
      !~ '^[A-Za-z0-9._:-]{16,255}$'
    or v_settlement_request ->> 'idempotencyKey' =
      p_request ->> 'idempotencyKey'
    or (v_settlement_request ->> 'incomeYear')::integer <> 2026
    or extract(year from
      (v_settlement_request ->> 'correctionDate')::date)::integer <> 2026
    or nullif(pg_catalog.btrim(v_settlement_request ->> 'reason'), '') is null
    or pg_catalog.length(v_settlement_request ->> 'reason') > 500
    or v_settlement_request ->> 'evidenceDigest' !~ '^[0-9a-f]{64}$'
    or not investments.lifecycle_document_evidence_is_valid_v2(v_settlement_request)
    or pg_catalog.jsonb_typeof(v_settlement_replacement) <> 'object'
    or v_settlement_request ->> 'replacementRecordId' is distinct from
      v_settlement_replacement ->> 'settlementId'
    or v_settlement_request ->> 'originalRecordId' =
      v_settlement_request ->> 'replacementRecordId'
    or v_settlement_replacement ->> 'eventId' <> v_replacement_id::text
    or not investments.lifecycle_cash_evidence_is_valid_v2(
      v_settlement_replacement
    )
  then raise exception 'investments_invalid_input'; end if;

  if exists (
    select 1 from investments.lifecycle_corrections correction
    where correction.correction_id in (
      (p_request ->> 'correctionId')::uuid,
      (v_settlement_request ->> 'correctionId')::uuid
    ) or (correction.company_id = v_company and (
      (correction.target_kind = 'economic_event'
        and correction.original_record_id = v_original_id)
      or (correction.target_kind = 'cash_settlement'
        and correction.original_record_id =
          (v_settlement_request ->> 'originalRecordId')::uuid)
    ))
  ) or exists (
    select 1 from investments.economic_events replacement
    where replacement.event_id = v_replacement_id
  ) or exists (
    select 1 from investments.cash_settlements replacement
    where replacement.settlement_id =
      (v_settlement_replacement ->> 'settlementId')::uuid
  ) then raise exception 'investments_idempotency_key_reused'; end if;

  select event.* into v_event from investments.economic_events event
  where event.event_id = v_original_id;
  select settlement.* into v_settlement
  from investments.cash_settlements settlement
  where settlement.settlement_id =
      (v_settlement_request ->> 'originalRecordId')::uuid
    and settlement.event_id = v_original_id;
  if v_event.event_id is null or v_settlement.settlement_id is null
    or v_event.company_id <> v_company or v_settlement.company_id <> v_company
    or v_event.event_kind <> p_request ->> 'originalActivityKind'
    or exists (select 1 from investments.cash_settlements newer
      where newer.supersedes_settlement_id = v_settlement.settlement_id)
  then raise exception
    'investments_dependency_unavailable: settled_event_identity';
  end if;

  v_replacement_amount := case v_event.event_kind
    when 'share_purchase' then
      (p_request #>> '{replacement,purchaseAmount}')::numeric
      + (p_request #>> '{replacement,transactionCosts}')::numeric
    when 'share_sale' then
      (p_request #>> '{replacement,proceeds}')::numeric
      - (p_request #>> '{replacement,transactionCosts}')::numeric
    when 'dividend_received' then
      (p_request #>> '{replacement,grossAmount}')::numeric
    else (p_request #>> '{replacement,grossAmount}')::numeric
  end;
  if v_replacement_amount <= 0
    or pg_catalog.round(v_replacement_amount, 2) <> v_replacement_amount
    or (v_settlement_replacement ->> 'amount')::numeric
      <> v_replacement_amount
  then raise exception 'investments_invalid_input'; end if;

  if v_event.event_kind = 'share_purchase' then
    select recognition.* into v_recognition
    from investments.share_purchase_recognitions recognition
    where recognition.event_id = v_event.event_id;
    select lot.* into v_lot from investments.acquisition_lots lot
    where lot.id = v_recognition.acquisition_lot_id for update;
    select position.* into v_position from investments.positions position
    where position.id = v_event.position_id for update;
    if v_recognition.event_id is null or v_lot.id is null or v_position.id is null
      or v_lot.remaining_share_count <> v_lot.original_share_count
      or v_lot.remaining_cost_basis <> v_lot.original_cost_basis
      or v_lot.remaining_tax_basis <> v_lot.original_tax_basis
      or exists (select 1 from investments.economic_events later
        where later.position_id = v_event.position_id
          and (later.created_at, later.event_id) >
            (v_event.created_at, v_event.event_id))
    then raise exception 'investments_dependency_unavailable: settled_purchase_state'; end if;
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
            'correction_id', p_request ->> 'correctionId',
            'movement_type', 'settled_event_correction_reversal',
            'movement_date', p_request ->> 'correctionDate',
            'corrected_event_id', v_event.event_id,
            'share_delta', -v_lot.original_share_count,
            'book_cost_basis_delta', -v_lot.original_cost_basis,
            'tax_basis_delta', -v_lot.original_tax_basis,
            'evidence_digest', p_request ->> 'evidenceDigest')),
        updated_at = pg_catalog.now()
    where id = v_position.id
      and share_count >= v_lot.original_share_count
      and cost_basis >= v_lot.original_cost_basis
      and tax_basis >= v_lot.original_tax_basis;
    if not found then raise exception 'investments_dependency_unavailable: settled_purchase_update'; end if;
  elsif v_event.event_kind = 'share_sale' then
    select sale.* into v_sale from investments.share_sales sale
    where sale.action_id = v_event.event_id;
    select position.* into v_position from investments.positions position
    where position.id = v_event.position_id for update;
    if v_sale.action_id is null or v_position.id is null
      or exists (select 1 from investments.economic_events later
        where later.position_id = v_event.position_id
          and (later.created_at, later.event_id) >
            (v_event.created_at, v_event.event_id))
    then raise exception 'investments_dependency_unavailable: settled_sale_state'; end if;
    perform 1 from investments.acquisition_lots lot
    join investments.share_sale_allocations allocation
      on allocation.acquisition_lot_id = lot.id
    where allocation.sale_action_id = v_sale.action_id
    order by allocation.allocation_order for update of lot;
    if not found then raise exception 'investments_dependency_unavailable: settled_sale_lots'; end if;
    update investments.acquisition_lots lot
    set remaining_share_count = lot.remaining_share_count
          + allocation.allocated_share_count,
        remaining_cost_basis = lot.remaining_cost_basis
          + allocation.allocated_book_cost_basis,
        remaining_tax_basis = lot.remaining_tax_basis
          + allocation.allocated_tax_basis
    from investments.share_sale_allocations allocation
    where allocation.sale_action_id = v_sale.action_id
      and allocation.acquisition_lot_id = lot.id;
    update investments.positions
    set share_count = share_count + v_sale.sold_share_count,
        cost_basis = cost_basis + v_sale.fifo_cost_basis_reduction,
        tax_basis = tax_basis + v_sale.fifo_tax_basis_reduction,
        movements = movements || pg_catalog.jsonb_build_array(
          pg_catalog.jsonb_build_object(
            'correction_id', p_request ->> 'correctionId',
            'movement_type', 'settled_event_correction_reversal',
            'movement_date', p_request ->> 'correctionDate',
            'corrected_event_id', v_event.event_id,
            'share_delta', v_sale.sold_share_count,
            'book_cost_basis_delta', v_sale.fifo_cost_basis_reduction,
            'tax_basis_delta', v_sale.fifo_tax_basis_reduction,
            'evidence_digest', p_request ->> 'evidenceDigest')),
        updated_at = pg_catalog.now()
    where id = v_position.id;
  else
    select position.* into v_position from investments.positions position
    where position.id = v_event.position_id for update;
  end if;

  return pg_catalog.jsonb_build_object(
    'originalRecognitionAccountingEntryId',
      v_event.recognition_accounting_entry_id,
    'originalPositionId', v_event.position_id,
    'originalSettlementAccountingEntryId',
      v_settlement.settlement_accounting_entry_id,
    'originalSettlementId', v_settlement.settlement_id,
    'settlementBalanceKind', v_event.settlement_balance_kind,
    'replacementAmount', v_replacement_amount,
    'replacementEventFactSha256',
      investments.cash_settlement_fingerprint_v2(v_settlement_replacement)
  );
end;
$function$;

create or replace function investments.complete_settled_event_correction_v1(
  p_request jsonb,
  p_original_event_entry uuid, p_replacement_event_entry uuid,
  p_event_reversal_entry uuid,
  p_original_settlement_entry uuid, p_replacement_settlement_entry uuid,
  p_settlement_reversal_entry uuid, p_verified_subject text
) returns jsonb language plpgsql security definer set search_path = ''
as $function$
declare
  v_actor uuid := public.company_access_auth_uid_v1();
  v_company uuid := (p_request ->> 'companyId')::uuid;
  v_settlement_request jsonb := p_request -> 'settlementCorrection';
  v_settlement_replacement jsonb := v_settlement_request -> 'replacement';
  v_original_event investments.economic_events%rowtype;
  v_replacement_event investments.economic_events%rowtype;
  v_original_settlement investments.cash_settlements%rowtype;
  v_replacement_settlement investments.cash_settlements%rowtype;
begin
  if v_actor is null or v_actor is distinct from p_verified_subject::uuid
    or not public.company_access_is_accepted_owner_v1(v_company)
    or not ledger.investment_correction_matches_v1(
      p_original_event_entry, p_event_reversal_entry,
      p_replacement_event_entry, v_company, 2026,
      (p_request ->> 'originalRecordId')::uuid,
      (p_request ->> 'replacementRecordId')::uuid)
    or not ledger.investment_correction_matches_v1(
      p_original_settlement_entry, p_settlement_reversal_entry,
      p_replacement_settlement_entry, v_company, 2026,
      (v_settlement_request ->> 'originalRecordId')::uuid,
      (v_settlement_request ->> 'replacementRecordId')::uuid)
  then raise exception 'investments_dependency_unavailable'; end if;
  if p_request ->> 'targetKind' <> 'economic_event'
    or p_request ->> 'originalActivityKind' not in (
      'share_purchase', 'share_sale', 'dividend_received',
      'fund_distribution_received'
    )
    or p_request ->> 'replacementActivityKind' is distinct from
      p_request ->> 'originalActivityKind'
    or (p_request ->> 'originalRecordId')::uuid =
      (p_request ->> 'replacementRecordId')::uuid
    or (p_request ->> 'incomeYear')::integer <> 2026
    or extract(year from (p_request ->> 'correctionDate')::date)::integer <> 2026
    or nullif(pg_catalog.btrim(p_request ->> 'reason'), '') is null
    or pg_catalog.length(p_request ->> 'reason') > 500
    or p_request ->> 'evidenceDigest' !~ '^[0-9a-f]{64}$'
    or not investments.lifecycle_document_evidence_is_valid_v2(p_request)
    or pg_catalog.jsonb_typeof(v_settlement_request) <> 'object'
    or v_settlement_request ->> 'targetKind' <> 'cash_settlement'
    or v_settlement_request ->> 'companyId' <> v_company::text
    or v_settlement_request ->> 'originalActivityKind' is distinct from
      p_request ->> 'originalActivityKind'
    or (v_settlement_request ->> 'correctionId')::uuid =
      (p_request ->> 'correctionId')::uuid
    or v_settlement_request ->> 'idempotencyKey' =
      p_request ->> 'idempotencyKey'
    or (v_settlement_request ->> 'incomeYear')::integer <> 2026
    or extract(year from
      (v_settlement_request ->> 'correctionDate')::date)::integer <> 2026
    or nullif(pg_catalog.btrim(v_settlement_request ->> 'reason'), '') is null
    or pg_catalog.length(v_settlement_request ->> 'reason') > 500
    or v_settlement_request ->> 'evidenceDigest' !~ '^[0-9a-f]{64}$'
    or not investments.lifecycle_document_evidence_is_valid_v2(
      v_settlement_request
    )
    or pg_catalog.jsonb_typeof(v_settlement_replacement) <> 'object'
    or v_settlement_request ->> 'replacementRecordId' is distinct from
      v_settlement_replacement ->> 'settlementId'
    or v_settlement_replacement ->> 'eventId' is distinct from
      p_request ->> 'replacementRecordId'
    or not investments.lifecycle_cash_evidence_is_valid_v2(
      v_settlement_replacement
    )
  then raise exception 'investments_invalid_input'; end if;

  select event.* into strict v_original_event
  from investments.economic_events event
  where event.event_id = (p_request ->> 'originalRecordId')::uuid
    and event.company_id = v_company;
  select event.* into strict v_replacement_event
  from investments.economic_events event
  where event.event_id = (p_request ->> 'replacementRecordId')::uuid
    and event.company_id = v_company;
  select settlement.* into strict v_original_settlement
  from investments.cash_settlements settlement
  where settlement.settlement_id =
    (v_settlement_request ->> 'originalRecordId')::uuid
    and settlement.company_id = v_company for update;
  select settlement.* into strict v_replacement_settlement
  from investments.cash_settlements settlement
  where settlement.settlement_id =
    (v_settlement_request ->> 'replacementRecordId')::uuid
    and settlement.company_id = v_company for update;
  if v_original_event.recognition_accounting_entry_id
      <> p_original_event_entry
    or v_replacement_event.recognition_accounting_entry_id
      <> p_replacement_event_entry
    or v_original_settlement.event_id <> v_original_event.event_id
    or v_replacement_settlement.event_id <> v_replacement_event.event_id
    or v_original_settlement.settlement_accounting_entry_id
      <> p_original_settlement_entry
    or v_replacement_settlement.settlement_accounting_entry_id
      <> p_replacement_settlement_entry
    or v_replacement_event.event_kind <> v_original_event.event_kind
    or v_replacement_event.position_id <> v_original_event.position_id
    or v_replacement_settlement.amount
      <> v_replacement_event.expected_settlement_amount
    or v_replacement_settlement.supersedes_settlement_id is not null
    or exists (
      select 1 from investments.cash_settlements newer
      where newer.supersedes_settlement_id = v_original_settlement.settlement_id
    )
  then raise exception 'investments_dependency_unavailable'; end if;

  update investments.cash_settlements
  set supersedes_settlement_id = v_original_settlement.settlement_id
  where settlement_id = v_replacement_settlement.settlement_id
    and supersedes_settlement_id is null;
  if not found then raise exception 'investments_dependency_unavailable'; end if;

  insert into investments.lifecycle_corrections (
    correction_id, company_id, income_year, idempotency_key,
    request_fingerprint, target_kind, original_record_id, original_event_id,
    original_activity_kind, original_accounting_entry_id,
    reversal_accounting_entry_id, replacement_record_id,
    replacement_accounting_entry_id, reason, evidence_mode,
    evidence_reference, owner_attested, evidence_digest, created_by
  ) values
  (
    (p_request ->> 'correctionId')::uuid, v_company, 2026,
    p_request ->> 'idempotencyKey',
    investments.lifecycle_correction_fingerprint_v2(p_request),
    'economic_event', v_original_event.event_id, v_original_event.event_id,
    v_original_event.event_kind, p_original_event_entry,
    p_event_reversal_entry, v_replacement_event.event_id,
    p_replacement_event_entry, pg_catalog.btrim(p_request ->> 'reason'),
    p_request ->> 'evidenceMode',
    pg_catalog.btrim(p_request ->> 'evidenceReference'),
    (p_request ->> 'ownerAttested')::boolean,
    p_request ->> 'evidenceDigest', v_actor
  ),
  (
    (v_settlement_request ->> 'correctionId')::uuid, v_company, 2026,
    v_settlement_request ->> 'idempotencyKey',
    investments.lifecycle_correction_fingerprint_v2(v_settlement_request),
    'cash_settlement', v_original_settlement.settlement_id,
    v_original_event.event_id, v_original_event.event_kind,
    p_original_settlement_entry, p_settlement_reversal_entry,
    v_replacement_settlement.settlement_id, p_replacement_settlement_entry,
    pg_catalog.btrim(v_settlement_request ->> 'reason'),
    v_settlement_request ->> 'evidenceMode',
    pg_catalog.btrim(v_settlement_request ->> 'evidenceReference'),
    (v_settlement_request ->> 'ownerAttested')::boolean,
    v_settlement_request ->> 'evidenceDigest', v_actor
  );
  perform investments.record_lifecycle_correction_sources_v2(
    v_company, (p_request ->> 'correctionId')::uuid,
    p_request -> 'documentFacts');
  perform investments.record_lifecycle_correction_sources_v2(
    v_company, (v_settlement_request ->> 'correctionId')::uuid,
    v_settlement_request -> 'documentFacts');
  insert into public.audit_events (
    company_id, actor_id, category, action, message
  ) values (
    v_company, v_actor, 'ledger', 'settled_investment_corrected',
    'Oppgjort investeringshendelse og kontantoppgjør korrigert atomisk.'
  );
  return pg_catalog.jsonb_build_object(
    'correctionId', p_request ->> 'correctionId',
    'targetKind', 'economic_event',
    'originalRecordId', v_original_event.event_id,
    'replacementRecordId', v_replacement_event.event_id,
    'reversalAccountingEntryId', p_event_reversal_entry,
    'replacementAccountingEntryId', p_replacement_event_entry,
    'replayed', false
  );
end;
$function$;

alter function investments.prepare_settled_event_correction_v1(jsonb, text)
  owner to investments_store_owner;
alter function investments.complete_settled_event_correction_v1(
  jsonb, uuid, uuid, uuid, uuid, uuid, uuid, text
) owner to investments_store_owner;
revoke all on function
  investments.prepare_settled_event_correction_v1(jsonb, text),
  investments.complete_settled_event_correction_v1(
    jsonb, uuid, uuid, uuid, uuid, uuid, uuid, text
  ) from public, anon, authenticated, service_role;
grant execute on function
  investments.prepare_settled_event_correction_v1(jsonb, text),
  investments.complete_settled_event_correction_v1(
    jsonb, uuid, uuid, uuid, uuid, uuid, uuid, text
  ) to investments_workflow_executor;

do $membership_revoke$
begin
  execute pg_catalog.format(
    'revoke investments_store_owner from %I', current_user
  );
end
$membership_revoke$;

commit;
