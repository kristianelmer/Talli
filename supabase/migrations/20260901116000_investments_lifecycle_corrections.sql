-- Append-only correction and supersession for investment lifecycle records.
begin;

set local lock_timeout = '5s';
set local statement_timeout = '120s';

do $membership$
begin
  execute pg_catalog.format(
    'grant investments_store_owner, investments_workflow_executor to %I',
    current_user
  );
end
$membership$;

select pg_catalog.pg_advisory_xact_lock(
  pg_catalog.hashtextextended('talli:investments:lifecycle-corrections:v2', 0)
);

alter table investments.cash_settlements
  drop constraint cash_settlements_event_id_key;
alter table investments.cash_settlements
  add column supersedes_settlement_id uuid unique,
  add constraint cash_settlements_settlement_company_event_year_key unique (
    settlement_id, company_id, event_id, income_year
  ),
  add constraint cash_settlements_supersedes_same_event_fk foreign key (
    supersedes_settlement_id, company_id, event_id, income_year
  ) references investments.cash_settlements(
    settlement_id, company_id, event_id, income_year
  ) on delete restrict,
  add constraint cash_settlements_supersedes_distinct_check check (
    supersedes_settlement_id is null
    or supersedes_settlement_id <> settlement_id
  );

create table investments.lifecycle_corrections (
  correction_id uuid primary key,
  company_id uuid not null references public.companies(id) on delete cascade,
  income_year integer not null check (income_year = 2026),
  idempotency_key text not null check (
    idempotency_key ~ '^[A-Za-z0-9._:-]{16,255}$'
  ),
  request_fingerprint text not null check (request_fingerprint ~ '^[0-9a-f]{64}$'),
  target_kind text not null check (
    target_kind in ('economic_event', 'cash_settlement')
  ),
  original_record_id uuid not null,
  original_event_id uuid not null,
  original_activity_kind text not null check (
    original_activity_kind in (
      'share_purchase', 'share_sale', 'dividend_received',
      'fund_distribution_received'
    )
  ),
  original_accounting_entry_id uuid not null unique,
  reversal_accounting_entry_id uuid not null unique,
  replacement_record_id uuid not null unique,
  replacement_accounting_entry_id uuid not null unique,
  reason text not null check (
    reason = pg_catalog.btrim(reason) and reason <> ''
    and pg_catalog.length(reason) <= 500
  ),
  evidence_mode text not null check (
    evidence_mode in ('linked_sources', 'manual_fallback')
  ),
  evidence_reference text not null check (
    evidence_reference = pg_catalog.btrim(evidence_reference)
    and evidence_reference <> '' and pg_catalog.length(evidence_reference) <= 500
  ),
  owner_attested boolean not null,
  evidence_digest text not null check (evidence_digest ~ '^[0-9a-f]{64}$'),
  created_by uuid not null references auth.users(id) on delete restrict,
  created_at timestamptz not null default pg_catalog.now(),
  unique (company_id, target_kind, original_record_id),
  unique (correction_id, company_id),
  unique (created_by, company_id, idempotency_key),
  check (original_record_id <> replacement_record_id),
  check (
    (evidence_mode = 'linked_sources' and not owner_attested)
    or (evidence_mode = 'manual_fallback' and owner_attested)
  )
);

create table investments.lifecycle_correction_sources (
  correction_id uuid not null,
  company_id uuid not null references public.companies(id) on delete cascade,
  ordinal integer not null check (ordinal > 0),
  source_capability text not null check (source_capability = 'DOCUMENTS'),
  source_record_id uuid not null,
  source_revision integer not null check (source_revision > 0),
  fact_sha256 text not null check (fact_sha256 ~ '^[0-9a-f]{64}$'),
  created_at timestamptz not null default pg_catalog.now(),
  primary key (correction_id, ordinal),
  unique (
    correction_id, source_capability, source_record_id, source_revision
  ),
  foreign key (correction_id, company_id)
    references investments.lifecycle_corrections(correction_id, company_id)
    on delete restrict,
  foreign key (
    company_id, source_capability, source_record_id, source_revision,
    fact_sha256
  ) references investments.source_fact_registry (
    company_id, source_capability, source_record_id, source_revision,
    fact_sha256
  ) on delete restrict
);

create index investments_lifecycle_corrections_company_idx
  on investments.lifecycle_corrections(company_id, correction_id);

alter table investments.lifecycle_corrections owner to investments_store_owner;
alter table investments.lifecycle_correction_sources owner to investments_store_owner;
alter table investments.lifecycle_corrections enable row level security;
alter table investments.lifecycle_corrections force row level security;
alter table investments.lifecycle_correction_sources enable row level security;
alter table investments.lifecycle_correction_sources force row level security;
create policy investments_lifecycle_corrections_member_select
on investments.lifecycle_corrections for select
to investments_executor, investments_store_owner
using (public.company_access_is_accepted_member_v1(company_id));
create policy investments_lifecycle_corrections_owner_insert
on investments.lifecycle_corrections for insert to investments_store_owner
with check (
  created_by = public.company_access_auth_uid_v1()
  and public.company_access_is_accepted_owner_v1(company_id)
);
create policy investments_lifecycle_correction_sources_member_select
on investments.lifecycle_correction_sources for select
to investments_executor, investments_store_owner
using (public.company_access_is_accepted_member_v1(company_id));
create policy investments_lifecycle_correction_sources_owner_insert
on investments.lifecycle_correction_sources for insert to investments_store_owner
with check (public.company_access_is_accepted_owner_v1(company_id));
grant select, insert on investments.lifecycle_corrections,
  investments.lifecycle_correction_sources to investments_store_owner;
grant select on investments.lifecycle_corrections,
  investments.lifecycle_correction_sources to investments_executor;
revoke all on investments.lifecycle_corrections,
  investments.lifecycle_correction_sources
from public, anon, authenticated, service_role, investments_workflow_executor;

create or replace function investments.lifecycle_correction_fingerprint_v2(
  p_request jsonb
)
returns text language sql immutable set search_path = ''
as $function$
  select pg_catalog.encode(extensions.digest(
    (p_request - array['evidenceDigest', 'correlationId'])::text, 'sha256'
  ), 'hex');
$function$;

create or replace function investments.lifecycle_cash_evidence_is_valid_v2(
  p_request jsonb
)
returns boolean language sql immutable set search_path = ''
as $function$
  select
    nullif(pg_catalog.btrim(p_request ->> 'evidenceReference'), '') is not null
    and pg_catalog.length(p_request ->> 'evidenceReference') <= 500
    and p_request -> 'documentFacts' = '[]'::jsonb
    and pg_catalog.jsonb_typeof(p_request -> 'bankFact') = 'object'
    and p_request -> 'bankFact' ->> 'capability' = 'BANKING'
    and coalesce(p_request -> 'bankFact' ->> 'recordId', '')
      ~ '^[0-9a-fA-F-]{36}$'
    and coalesce(p_request -> 'bankFact' ->> 'revision', '')
      ~ '^[1-9][0-9]*$'
    and coalesce(p_request -> 'bankFact' ->> 'factSha256', '')
      ~ '^[0-9a-f]{64}$'
    and (
      (p_request ->> 'evidenceMode' = 'linked_sources'
        and (p_request ->> 'ownerAttested')::boolean = false)
      or (p_request ->> 'evidenceMode' = 'manual_fallback'
        and (p_request ->> 'ownerAttested')::boolean = true)
    );
$function$;

create or replace function investments.record_lifecycle_correction_sources_v2(
  p_company_id uuid, p_correction_id uuid, p_document_facts jsonb
)
returns void language plpgsql security definer set search_path = ''
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
  insert into investments.lifecycle_correction_sources (
    correction_id, company_id, ordinal, source_capability,
    source_record_id, source_revision, fact_sha256
  )
  select p_correction_id, p_company_id, ordinal::integer,
    item ->> 'capability', (item ->> 'recordId')::uuid,
    (item ->> 'revision')::integer, item ->> 'factSha256'
  from pg_catalog.jsonb_array_elements(p_document_facts)
    with ordinality source(item, ordinal);
end;
$function$;

create or replace function investments.get_lifecycle_correction_replay_v2(
  p_request jsonb, p_verified_subject text
)
returns jsonb language plpgsql security definer set search_path = ''
as $function$
declare
  v_actor_id uuid := public.company_access_auth_uid_v1();
  v_row investments.lifecycle_corrections%rowtype;
begin
  if v_actor_id is null or v_actor_id is distinct from p_verified_subject::uuid
    or not public.company_access_is_accepted_owner_v1(
      (p_request ->> 'companyId')::uuid
    )
  then raise exception 'investments_forbidden'; end if;
  select correction.* into v_row
  from investments.lifecycle_corrections correction
  where correction.correction_id = (p_request ->> 'correctionId')::uuid
     or (
       correction.created_by = v_actor_id
       and correction.company_id = (p_request ->> 'companyId')::uuid
       and correction.idempotency_key = p_request ->> 'idempotencyKey'
     )
  order by (
    correction.correction_id = (p_request ->> 'correctionId')::uuid
  ) desc limit 1;
  if not found then return null; end if;
  if v_row.request_fingerprint <>
    investments.lifecycle_correction_fingerprint_v2(p_request)
  then raise exception 'investments_idempotency_key_reused'; end if;
  return pg_catalog.jsonb_build_object(
    'correctionId', v_row.correction_id,
    'targetKind', v_row.target_kind,
    'originalRecordId', v_row.original_record_id,
    'replacementRecordId', v_row.replacement_record_id,
    'reversalAccountingEntryId', v_row.reversal_accounting_entry_id,
    'replacementAccountingEntryId', v_row.replacement_accounting_entry_id,
    'replayed', true
  );
end;
$function$;

create or replace function investments.prepare_economic_event_correction_v2(
  p_request jsonb, p_verified_subject text
)
returns jsonb language plpgsql security definer set search_path = ''
as $function$
declare
  v_actor_id uuid := public.company_access_auth_uid_v1();
  v_company_id uuid := (p_request ->> 'companyId')::uuid;
  v_original_id uuid := (p_request ->> 'originalRecordId')::uuid;
  v_replacement_id uuid := (p_request ->> 'replacementRecordId')::uuid;
  v_event investments.economic_events%rowtype;
  v_recognition investments.share_purchase_recognitions%rowtype;
  v_sale investments.share_sales%rowtype;
  v_lot investments.acquisition_lots%rowtype;
  v_position investments.positions%rowtype;
begin
  if v_actor_id is null or v_actor_id is distinct from p_verified_subject::uuid
    or not public.company_access_is_accepted_owner_v1(v_company_id)
  then raise exception 'investments_forbidden'; end if;
  if not pg_catalog.pg_try_advisory_xact_lock(pg_catalog.hashtextextended(
    'investments:v2:' || v_actor_id::text || ':' || v_company_id::text ||
      ':event-correction:' || coalesce(p_request ->> 'idempotencyKey', ''), 0
  )) then raise exception 'investments_idempotency_in_progress'; end if;
  if p_request ->> 'targetKind' <> 'economic_event'
    or coalesce(p_request ->> 'idempotencyKey', '')
      !~ '^[A-Za-z0-9._:-]{16,255}$'
    or (p_request ->> 'incomeYear')::integer <> 2026
    or extract(year from (p_request ->> 'correctionDate')::date)::integer <> 2026
    or v_original_id = v_replacement_id
    or p_request ->> 'originalActivityKind' not in (
      'share_purchase', 'share_sale', 'dividend_received',
      'fund_distribution_received'
    )
    or p_request ->> 'replacementActivityKind' is distinct from
      p_request ->> 'originalActivityKind'
    or nullif(pg_catalog.btrim(p_request ->> 'reason'), '') is null
    or pg_catalog.length(p_request ->> 'reason') > 500
    or p_request ->> 'evidenceDigest' !~ '^[0-9a-f]{64}$'
    or not investments.lifecycle_document_evidence_is_valid_v2(p_request)
  then raise exception 'investments_invalid_input'; end if;
  if not pg_catalog.pg_try_advisory_xact_lock(pg_catalog.hashtextextended(
    'investments:v2:' || v_company_id::text ||
      ':correction-target:economic_event:' || v_original_id::text, 0
  )) then raise exception 'investments_idempotency_in_progress'; end if;
  if exists (
    select 1 from investments.lifecycle_corrections correction
    where correction.correction_id = (p_request ->> 'correctionId')::uuid
       or (correction.company_id = v_company_id
         and correction.target_kind = 'economic_event'
         and correction.original_record_id = v_original_id)
       or (correction.created_by = v_actor_id
         and correction.company_id = v_company_id
         and correction.idempotency_key = p_request ->> 'idempotencyKey')
  ) or exists (
    select 1 from investments.economic_events replacement
    where replacement.event_id = v_replacement_id
  ) then raise exception 'investments_idempotency_key_reused'; end if;

  select event.* into v_event from investments.economic_events event
  where event.event_id = v_original_id;
  if not found or v_event.company_id <> v_company_id
    or v_event.income_year <> 2026
    or v_event.event_kind <> p_request ->> 'originalActivityKind'
    or exists (
      select 1 from investments.cash_settlements settlement
      where settlement.event_id = v_event.event_id
    )
  then raise exception 'investments_dependency_unavailable'; end if;

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
      or exists (
        select 1 from investments.economic_events later
        where later.position_id = v_event.position_id
          and (later.created_at, later.event_id) >
            (v_event.created_at, v_event.event_id)
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
            'correction_id', p_request ->> 'correctionId',
            'movement_type', 'event_correction_reversal',
            'movement_date', p_request ->> 'correctionDate',
            'corrected_event_id', v_event.event_id,
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
  elsif v_event.event_kind = 'share_sale' then
    select sale.* into v_sale from investments.share_sales sale
    where sale.action_id = v_event.event_id;
    select position.* into v_position from investments.positions position
    where position.id = v_event.position_id for update;
    if v_sale.action_id is null or v_position.id is null or exists (
      select 1 from investments.economic_events later
      where later.position_id = v_event.position_id
        and (later.created_at, later.event_id) >
          (v_event.created_at, v_event.event_id)
    ) then raise exception 'investments_dependency_unavailable'; end if;
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
    update investments.positions
    set share_count = share_count + v_sale.sold_share_count,
        cost_basis = cost_basis + v_sale.fifo_cost_basis_reduction,
        tax_basis = tax_basis + v_sale.fifo_tax_basis_reduction,
        movements = movements || pg_catalog.jsonb_build_array(
          pg_catalog.jsonb_build_object(
            'correction_id', p_request ->> 'correctionId',
            'movement_type', 'event_correction_reversal',
            'movement_date', p_request ->> 'correctionDate',
            'corrected_event_id', v_event.event_id,
            'share_delta', v_sale.sold_share_count,
            'book_cost_basis_delta', v_sale.fifo_cost_basis_reduction,
            'tax_basis_delta', v_sale.fifo_tax_basis_reduction,
            'evidence_digest', p_request ->> 'evidenceDigest'
          )
        ), updated_at = pg_catalog.now()
    where id = v_position.id;
    if not found then raise exception 'investments_dependency_unavailable'; end if;
  end if;

  return pg_catalog.jsonb_build_object(
    'originalAccountingEntryId', v_event.recognition_accounting_entry_id,
    'originalPositionId', v_event.position_id,
    'originalEventId', v_event.event_id,
    'originalActivityKind', v_event.event_kind
  );
end;
$function$;

create or replace function investments.prepare_cash_settlement_correction_v2(
  p_request jsonb, p_verified_subject text
)
returns jsonb language plpgsql security definer set search_path = ''
as $function$
declare
  v_actor_id uuid := public.company_access_auth_uid_v1();
  v_company_id uuid := (p_request ->> 'companyId')::uuid;
  v_original_id uuid := (p_request ->> 'originalRecordId')::uuid;
  v_replacement jsonb := p_request -> 'replacement';
  v_original investments.cash_settlements%rowtype;
  v_event investments.economic_events%rowtype;
  v_amount numeric := (v_replacement ->> 'amount')::numeric;
begin
  if v_actor_id is null or v_actor_id is distinct from p_verified_subject::uuid
    or not public.company_access_is_accepted_owner_v1(v_company_id)
  then raise exception 'investments_forbidden'; end if;
  if not pg_catalog.pg_try_advisory_xact_lock(pg_catalog.hashtextextended(
    'investments:v2:' || v_actor_id::text || ':' || v_company_id::text ||
      ':settlement-correction:' || coalesce(p_request ->> 'idempotencyKey', ''), 0
  )) then raise exception 'investments_idempotency_in_progress'; end if;
  if p_request ->> 'targetKind' <> 'cash_settlement'
    or coalesce(p_request ->> 'idempotencyKey', '')
      !~ '^[A-Za-z0-9._:-]{16,255}$'
    or (p_request ->> 'incomeYear')::integer <> 2026
    or extract(year from (p_request ->> 'correctionDate')::date)::integer <> 2026
    or nullif(pg_catalog.btrim(p_request ->> 'reason'), '') is null
    or pg_catalog.length(p_request ->> 'reason') > 500
    or p_request ->> 'evidenceDigest' !~ '^[0-9a-f]{64}$'
    or not investments.lifecycle_document_evidence_is_valid_v2(p_request)
    or pg_catalog.jsonb_typeof(v_replacement) <> 'object'
    or v_replacement ->> 'companyId' <> v_company_id::text
    or (v_replacement ->> 'incomeYear')::integer <> 2026
    or (v_replacement ->> 'settlementId')::uuid = v_original_id
    or coalesce(v_replacement ->> 'idempotencyKey', '')
      !~ '^[A-Za-z0-9._:-]{16,255}$'
    or extract(year from (v_replacement ->> 'settlementDate')::date)::integer <> 2026
    or v_amount <= 0 or pg_catalog.round(v_amount, 2) <> v_amount
    or v_replacement ->> 'evidenceDigest' !~ '^[0-9a-f]{64}$'
    or not investments.lifecycle_cash_evidence_is_valid_v2(v_replacement)
  then raise exception 'investments_invalid_input'; end if;
  if not pg_catalog.pg_try_advisory_xact_lock(pg_catalog.hashtextextended(
    'investments:v2:' || v_company_id::text ||
      ':correction-target:cash_settlement:' || v_original_id::text, 0
  )) then raise exception 'investments_idempotency_in_progress'; end if;
  if exists (
    select 1 from investments.lifecycle_corrections correction
    where correction.correction_id = (p_request ->> 'correctionId')::uuid
       or (correction.company_id = v_company_id
         and correction.target_kind = 'cash_settlement'
         and correction.original_record_id = v_original_id)
       or (correction.created_by = v_actor_id
         and correction.company_id = v_company_id
         and correction.idempotency_key = p_request ->> 'idempotencyKey')
  ) or exists (
    select 1 from investments.cash_settlements replacement
    where replacement.settlement_id = (v_replacement ->> 'settlementId')::uuid
       or (replacement.created_by = v_actor_id
         and replacement.company_id = v_company_id
         and replacement.idempotency_key = v_replacement ->> 'idempotencyKey')
  ) then raise exception 'investments_idempotency_key_reused'; end if;
  select settlement.* into v_original
  from investments.cash_settlements settlement
  where settlement.settlement_id = v_original_id;
  if not found or v_original.company_id <> v_company_id
    or v_original.income_year <> 2026
    or exists (
      select 1 from investments.cash_settlements newer
      where newer.supersedes_settlement_id = v_original.settlement_id
    )
    or v_replacement ->> 'eventId' <> v_original.event_id::text
    or v_amount <> v_original.amount
  then raise exception 'investments_dependency_unavailable'; end if;
  select event.* into strict v_event from investments.economic_events event
  where event.event_id = v_original.event_id;
  return pg_catalog.jsonb_build_object(
    'originalAccountingEntryId', v_original.settlement_accounting_entry_id,
    'originalSettlementId', v_original.settlement_id,
    'eventId', v_event.event_id,
    'recognitionAccountingEntryId', v_event.recognition_accounting_entry_id,
    'settlementBalanceKind', v_event.settlement_balance_kind,
    'amount', v_original.amount,
    'eventFactSha256',
      investments.cash_settlement_fingerprint_v2(v_replacement),
    'evidenceDigest', v_replacement ->> 'evidenceDigest',
    'originalActivityKind', v_event.event_kind
  );
end;
$function$;

create or replace function investments.complete_lifecycle_correction_v2(
  p_request jsonb, p_original_entry_id uuid, p_replacement_entry_id uuid,
  p_reversal_entry_id uuid, p_verified_subject text
)
returns jsonb language plpgsql security definer set search_path = ''
as $function$
declare
  v_actor_id uuid := public.company_access_auth_uid_v1();
  v_company_id uuid := (p_request ->> 'companyId')::uuid;
  v_target_kind text := p_request ->> 'targetKind';
  v_original_id uuid := (p_request ->> 'originalRecordId')::uuid;
  v_replacement_id uuid := (p_request ->> 'replacementRecordId')::uuid;
  v_original_event_id uuid;
  v_activity_kind text;
  v_original_settlement investments.cash_settlements%rowtype;
  v_event investments.economic_events%rowtype;
  v_replacement jsonb := p_request -> 'replacement';
  v_bank_fact jsonb;
  v_entry_kind text;
  v_count integer;
begin
  if v_actor_id is null or v_actor_id is distinct from p_verified_subject::uuid
    or not ledger.investment_correction_matches_v1(
      p_original_entry_id, p_reversal_entry_id, p_replacement_entry_id,
      v_company_id, 2026, v_original_id, v_replacement_id
    )
  then raise exception 'investments_dependency_unavailable'; end if;
  if not pg_catalog.pg_try_advisory_xact_lock(pg_catalog.hashtextextended(
    'investments:v2:' || v_company_id::text || ':correction-target:' ||
      v_target_kind || ':' || v_original_id::text, 0
  )) then raise exception 'investments_idempotency_in_progress'; end if;

  if v_target_kind = 'economic_event' then
    select original.* into strict v_event
    from investments.economic_events original
    where original.event_id = v_original_id and original.company_id = v_company_id;
    if v_event.recognition_accounting_entry_id <> p_original_entry_id
      or exists (
        select 1 from investments.cash_settlements settlement
        where settlement.event_id = v_event.event_id
      )
      or not exists (
        select 1 from investments.economic_events replacement
        where replacement.event_id = v_replacement_id
          and replacement.company_id = v_company_id
          and replacement.event_kind = v_event.event_kind
          and replacement.recognition_accounting_entry_id = p_replacement_entry_id
      )
    then raise exception 'investments_dependency_unavailable'; end if;
    v_original_event_id := v_event.event_id;
    v_activity_kind := v_event.event_kind;
  elsif v_target_kind = 'cash_settlement' then
    select settlement.* into strict v_original_settlement
    from investments.cash_settlements settlement
    where settlement.settlement_id = v_original_id
      and settlement.company_id = v_company_id;
    select event.* into strict v_event from investments.economic_events event
    where event.event_id = v_original_settlement.event_id;
    v_bank_fact := v_replacement -> 'bankFact';
    v_entry_kind := case v_event.event_kind
      when 'share_purchase' then 'SHARE_PURCHASE'
      when 'share_sale' then 'SHARE_SALE'
      else 'DIVIDEND_RECEIVED'
    end;
    if v_original_settlement.settlement_accounting_entry_id <> p_original_entry_id
      or (v_replacement ->> 'settlementId')::uuid <> v_replacement_id
      or v_replacement ->> 'eventId' <> v_event.event_id::text
      or (v_replacement ->> 'amount')::numeric <> v_original_settlement.amount
      or not investments.lifecycle_cash_evidence_is_valid_v2(v_replacement)
      or not ledger.investment_lifecycle_entry_matches_v2(
        p_replacement_entry_id, v_company_id, 2026, v_entry_kind,
        v_replacement_id,
        investments.cash_settlement_fingerprint_v2(v_replacement),
        (v_replacement ->> 'settlementDate')::date,
        pg_catalog.jsonb_build_array(v_bank_fact)
      )
    then raise exception 'investments_dependency_unavailable'; end if;
    insert into investments.source_fact_registry (
      company_id, source_capability, source_record_id, source_revision,
      fact_sha256
    ) values (
      v_company_id, v_bank_fact ->> 'capability',
      (v_bank_fact ->> 'recordId')::uuid,
      (v_bank_fact ->> 'revision')::integer,
      v_bank_fact ->> 'factSha256'
    ) on conflict (
      company_id, source_capability, source_record_id, source_revision
    ) do update set fact_sha256 = excluded.fact_sha256
    where investments.source_fact_registry.fact_sha256 = excluded.fact_sha256;
    get diagnostics v_count = row_count;
    if v_count <> 1 then raise exception 'investments_invalid_input'; end if;
    insert into investments.cash_settlements (
      settlement_id, event_id, company_id, income_year, settlement_date,
      amount, source_capability, source_record_id, source_revision,
      fact_sha256, idempotency_key, request_fingerprint, evidence_mode,
      evidence_reference, owner_attested, evidence_digest,
      settlement_accounting_entry_id, created_by, supersedes_settlement_id
    ) values (
      v_replacement_id, v_event.event_id, v_company_id, 2026,
      (v_replacement ->> 'settlementDate')::date,
      (v_replacement ->> 'amount')::numeric,
      v_bank_fact ->> 'capability', (v_bank_fact ->> 'recordId')::uuid,
      (v_bank_fact ->> 'revision')::integer,
      v_bank_fact ->> 'factSha256', v_replacement ->> 'idempotencyKey',
      investments.cash_settlement_fingerprint_v2(v_replacement),
      v_replacement ->> 'evidenceMode',
      pg_catalog.btrim(v_replacement ->> 'evidenceReference'),
      (v_replacement ->> 'ownerAttested')::boolean,
      v_replacement ->> 'evidenceDigest', p_replacement_entry_id,
      v_actor_id, v_original_id
    );
    v_original_event_id := v_event.event_id;
    v_activity_kind := v_event.event_kind;
  else
    raise exception 'investments_invalid_input';
  end if;

  insert into investments.lifecycle_corrections (
    correction_id, company_id, income_year, idempotency_key,
    request_fingerprint, target_kind, original_record_id, original_event_id,
    original_activity_kind, original_accounting_entry_id,
    reversal_accounting_entry_id, replacement_record_id,
    replacement_accounting_entry_id, reason, evidence_mode,
    evidence_reference, owner_attested, evidence_digest, created_by
  ) values (
    (p_request ->> 'correctionId')::uuid, v_company_id, 2026,
    p_request ->> 'idempotencyKey',
    investments.lifecycle_correction_fingerprint_v2(p_request),
    v_target_kind, v_original_id, v_original_event_id, v_activity_kind,
    p_original_entry_id, p_reversal_entry_id, v_replacement_id,
    p_replacement_entry_id, pg_catalog.btrim(p_request ->> 'reason'),
    p_request ->> 'evidenceMode',
    pg_catalog.btrim(p_request ->> 'evidenceReference'),
    (p_request ->> 'ownerAttested')::boolean,
    p_request ->> 'evidenceDigest', v_actor_id
  );
  perform investments.record_lifecycle_correction_sources_v2(
    v_company_id, (p_request ->> 'correctionId')::uuid,
    p_request -> 'documentFacts'
  );
  insert into public.audit_events (company_id, actor_id, category, action, message)
  values (
    v_company_id, v_actor_id, 'ledger', 'investment_lifecycle_corrected',
    'Investeringshendelse korrigert med full reversering og erstatningsspor.'
  );
  return pg_catalog.jsonb_build_object(
    'correctionId', p_request ->> 'correctionId',
    'targetKind', v_target_kind, 'originalRecordId', v_original_id,
    'replacementRecordId', v_replacement_id,
    'reversalAccountingEntryId', p_reversal_entry_id,
    'replacementAccountingEntryId', p_replacement_entry_id,
    'replayed', false
  );
end;
$function$;

alter function investments.lifecycle_correction_fingerprint_v2(jsonb)
  owner to investments_store_owner;
alter function investments.lifecycle_cash_evidence_is_valid_v2(jsonb)
  owner to investments_store_owner;
alter function investments.record_lifecycle_correction_sources_v2(
  uuid, uuid, jsonb
) owner to investments_store_owner;
alter function investments.get_lifecycle_correction_replay_v2(jsonb, text)
  owner to investments_store_owner;
alter function investments.prepare_economic_event_correction_v2(jsonb, text)
  owner to investments_store_owner;
alter function investments.prepare_cash_settlement_correction_v2(jsonb, text)
  owner to investments_store_owner;
alter function investments.complete_lifecycle_correction_v2(
  jsonb, uuid, uuid, uuid, text
) owner to investments_store_owner;

revoke all on function
  investments.lifecycle_correction_fingerprint_v2(jsonb),
  investments.lifecycle_cash_evidence_is_valid_v2(jsonb),
  investments.record_lifecycle_correction_sources_v2(uuid, uuid, jsonb),
  investments.get_lifecycle_correction_replay_v2(jsonb, text),
  investments.prepare_economic_event_correction_v2(jsonb, text),
  investments.prepare_cash_settlement_correction_v2(jsonb, text),
  investments.complete_lifecycle_correction_v2(
    jsonb, uuid, uuid, uuid, text
  )
from public, anon, authenticated, service_role;
grant execute on function
  investments.get_lifecycle_correction_replay_v2(jsonb, text),
  investments.prepare_economic_event_correction_v2(jsonb, text),
  investments.prepare_cash_settlement_correction_v2(jsonb, text),
  investments.complete_lifecycle_correction_v2(
    jsonb, uuid, uuid, uuid, text
  )
to investments_workflow_executor;
grant execute on function
  investments.lifecycle_correction_fingerprint_v2(jsonb),
  investments.lifecycle_cash_evidence_is_valid_v2(jsonb),
  investments.record_lifecycle_correction_sources_v2(uuid, uuid, jsonb)
to investments_store_owner;

do $membership_revoke$
begin
  execute pg_catalog.format(
    'revoke investments_store_owner, investments_workflow_executor from %I',
    current_user
  );
end
$membership_revoke$;

commit;
