-- Execute the #190 recognition/settlement lifecycle behind private, typed RPCs.
begin;

set local lock_timeout = '5s';
set local statement_timeout = '120s';

do $membership$
begin
  execute pg_catalog.format(
    'grant investments_store_owner, investments_executor, investments_workflow_executor, ledger_store_owner, company_archive_projection_executor to %I',
    current_user
  );
end
$membership$;

select pg_catalog.set_config(
  'talli.investments_lifecycle_migration_principal', current_user, true
);

grant usage on schema extensions to investments_store_owner;
grant execute on function extensions.digest(text, text)
  to investments_store_owner;

select pg_catalog.pg_advisory_xact_lock(
  pg_catalog.hashtextextended('talli:investments:lifecycle-workflow:v2', 0)
);

alter table investments.economic_events
  drop constraint economic_events_settlement_balance_kind_check;
alter table investments.economic_events
  add constraint economic_events_settlement_balance_kind_check check (
    settlement_balance_kind in (
      'purchase_payable', 'sale_receivable',
      'dividend_receivable', 'fund_distribution_receivable'
    )
  );

create table investments.source_fact_registry (
  company_id uuid not null references public.companies(id) on delete cascade,
  source_capability text not null check (
    source_capability in ('BANKING', 'DOCUMENTS')
  ),
  source_record_id uuid not null,
  source_revision integer not null check (source_revision > 0),
  fact_sha256 text not null check (fact_sha256 ~ '^[0-9a-f]{64}$'),
  created_at timestamptz not null default pg_catalog.now(),
  primary key (
    company_id, source_capability, source_record_id, source_revision
  ),
  unique (
    company_id, source_capability, source_record_id, source_revision,
    fact_sha256
  )
);

insert into investments.source_fact_registry (
  company_id, source_capability, source_record_id, source_revision,
  fact_sha256
)
select source.company_id, source.source_capability, source.source_record_id,
  source.source_revision, source.fact_sha256
from investments.event_sources source
union
select settlement.company_id, settlement.source_capability,
  settlement.source_record_id, settlement.source_revision,
  settlement.fact_sha256
from investments.cash_settlements settlement;

alter table investments.event_sources
  add constraint event_sources_registered_fact_fk foreign key (
    company_id, source_capability, source_record_id, source_revision,
    fact_sha256
  ) references investments.source_fact_registry (
    company_id, source_capability, source_record_id, source_revision,
    fact_sha256
  ) on delete restrict;
alter table investments.cash_settlements
  add constraint cash_settlements_registered_fact_fk foreign key (
    company_id, source_capability, source_record_id, source_revision,
    fact_sha256
  ) references investments.source_fact_registry (
    company_id, source_capability, source_record_id, source_revision,
    fact_sha256
  ) on delete restrict;

create table investments.share_purchase_recognitions (
  event_id uuid primary key,
  company_id uuid not null references public.companies(id) on delete cascade,
  income_year integer not null check (income_year = 2026),
  idempotency_key text not null check (
    idempotency_key ~ '^[A-Za-z0-9._:-]{16,255}$'
  ),
  request_fingerprint text not null check (
    request_fingerprint ~ '^[0-9a-f]{64}$'
  ),
  position_id uuid not null,
  acquisition_lot_id uuid not null unique
    references investments.acquisition_lots(id) on delete restrict,
  position_created boolean not null,
  investment_key text not null,
  investment_name text not null,
  investment_kind text not null,
  accounting_classification text not null,
  acquisition_date date not null,
  share_count numeric(38, 12) not null check (share_count > 0),
  purchase_amount numeric(38, 12) not null check (purchase_amount > 0),
  transaction_costs numeric(38, 12) not null check (transaction_costs >= 0),
  acquisition_cost numeric(38, 12) not null check (
    acquisition_cost = purchase_amount + transaction_costs
  ),
  org_number text,
  fund_equity_ratio_basis_points integer,
  fund_tax_statement_reference text,
  evidence_mode text not null check (
    evidence_mode in ('linked_sources', 'manual_fallback')
  ),
  evidence_reference text not null check (
    nullif(pg_catalog.btrim(evidence_reference), '') is not null
    and pg_catalog.length(evidence_reference) <= 500
  ),
  owner_attested boolean not null,
  evidence_digest text not null check (evidence_digest ~ '^[0-9a-f]{64}$'),
  calculation_id text not null check (calculation_id ~ '^[0-9a-f]{64}$'),
  completed_event_id uuid,
  created_by uuid not null references auth.users(id) on delete restrict,
  created_at timestamptz not null default pg_catalog.now(),
  completed_at timestamptz,
  constraint share_purchase_recognitions_event_company_unique
    unique (event_id, company_id),
  foreign key (position_id, company_id)
    references investments.positions(id, company_id) on delete restrict,
  foreign key (completed_event_id, company_id)
    references investments.economic_events(event_id, company_id)
    on delete restrict,
  unique (created_by, company_id, idempotency_key),
  unique (created_by, company_id, request_fingerprint),
  check (extract(year from acquisition_date)::integer = income_year),
  check (
    (completed_event_id is null and completed_at is null)
    or (completed_event_id = event_id and completed_at is not null)
  ),
  check (
    (evidence_mode = 'linked_sources' and not owner_attested)
    or (evidence_mode = 'manual_fallback' and owner_attested)
  )
);

create index investments_share_purchase_recognitions_company_year_idx
  on investments.share_purchase_recognitions(
    company_id, income_year, acquisition_date, event_id
  );

alter table investments.source_fact_registry enable row level security;
alter table investments.source_fact_registry force row level security;
alter table investments.share_purchase_recognitions enable row level security;
alter table investments.share_purchase_recognitions force row level security;

create policy investments_source_fact_registry_member_select
on investments.source_fact_registry for select
to investments_executor, investments_store_owner
using (public.company_access_is_accepted_member_v1(company_id));
create policy investments_source_fact_registry_owner_insert
on investments.source_fact_registry for insert to investments_store_owner
with check (public.company_access_is_accepted_owner_v1(company_id));

create policy investments_share_purchase_recognitions_member_select
on investments.share_purchase_recognitions for select
to investments_executor, investments_store_owner
using (public.company_access_is_accepted_member_v1(company_id));
create policy investments_share_purchase_recognitions_owner_insert
on investments.share_purchase_recognitions for insert to investments_store_owner
with check (
  created_by = public.company_access_auth_uid_v1()
  and public.company_access_is_accepted_owner_v1(company_id)
);
create policy investments_share_purchase_recognitions_owner_update
on investments.share_purchase_recognitions for update to investments_store_owner
using (public.company_access_is_accepted_owner_v1(company_id))
with check (
  created_by = public.company_access_auth_uid_v1()
  and public.company_access_is_accepted_owner_v1(company_id)
);

alter table investments.source_fact_registry owner to investments_store_owner;
alter table investments.share_purchase_recognitions owner to investments_store_owner;

grant select, insert on investments.source_fact_registry
  to investments_store_owner;
grant select, insert, update on investments.share_purchase_recognitions
  to investments_store_owner;
grant select on investments.source_fact_registry,
  investments.share_purchase_recognitions to investments_executor;
revoke all on investments.source_fact_registry,
  investments.share_purchase_recognitions
from public, anon, authenticated, service_role;

create or replace function investments.share_purchase_recognition_fingerprint_v2(
  p_request jsonb
)
returns text language sql immutable set search_path = ''
as $function$
  select pg_catalog.encode(extensions.digest(
    (p_request - array[
      'acquisitionCost', 'evidenceDigest', 'calculationId', 'correlationId'
    ])::text,
    'sha256'
  ), 'hex');
$function$;

create or replace function investments.cash_settlement_fingerprint_v2(
  p_request jsonb
)
returns text language sql immutable set search_path = ''
as $function$
  select pg_catalog.encode(extensions.digest(
    (p_request - array['evidenceDigest', 'correlationId'])::text,
    'sha256'
  ), 'hex');
$function$;

create or replace function ledger.post_investment_lifecycle_entry_v2(
  p_idempotency_key text,
  p_company_id uuid,
  p_income_year integer,
  p_entry_kind text,
  p_memo text,
  p_lines jsonb,
  p_source_capability text,
  p_source_record_id text,
  p_correlation_id text,
  p_verified_subject text,
  p_event_date date,
  p_rule_version text,
  p_sources jsonb
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
  v_corroborating_capability text;
begin
  if p_source_capability <> 'INVESTMENTS'
    or p_entry_kind not in ('SHARE_PURCHASE', 'SHARE_SALE', 'DIVIDEND_RECEIVED')
    or p_rule_version <> 'ledger-supported-patterns-2026.1'
    or pg_catalog.jsonb_typeof(p_sources) <> 'array'
    or pg_catalog.jsonb_array_length(p_sources) < 2
    or p_sources -> 0 ->> 'role' <> 'PRIMARY'
    or p_sources -> 0 ->> 'capability' <> 'INVESTMENTS'
    or p_sources -> 0 ->> 'recordId' <> p_source_record_id
    or exists (
      select 1
      from pg_catalog.jsonb_array_elements(p_sources) with ordinality source(item, ordinal)
      where ordinal > 1 and item ->> 'role' <> 'CORROBORATING'
    )
  then raise exception 'ledger_invalid_input'; end if;

  select p_sources -> 1 ->> 'capability'
  into v_corroborating_capability;
  if v_corroborating_capability not in ('BANKING', 'DOCUMENTS')
    or exists (
      select 1
      from pg_catalog.jsonb_array_elements(p_sources) with ordinality source(item, ordinal)
      where ordinal > 1
        and item ->> 'capability' <> v_corroborating_capability
    )
  then raise exception 'ledger_source_capability_mismatch'; end if;

  -- Documentary packs recognize an economic event. A single banking fact
  -- settles it. This wrapper cannot post unrelated ledger source topologies.
  if (v_corroborating_capability = 'BANKING'
      and pg_catalog.jsonb_array_length(p_sources) <> 2)
    or (v_corroborating_capability = 'DOCUMENTS'
      and pg_catalog.jsonb_array_length(p_sources) not between 2 and 51)
  then raise exception 'ledger_source_capability_mismatch'; end if;

  return query
  select posted.ledger_entry_id, posted.company_id, posted.income_year,
    posted.entry_kind, posted.posted_at, posted.replayed
  from ledger.post_supported_entry_v1(
    p_idempotency_key, p_company_id, p_income_year, p_entry_kind, p_memo,
    p_lines, p_source_capability, p_source_record_id, p_correlation_id,
    p_verified_subject, p_event_date, p_rule_version, p_sources
  ) posted;
end;
$function$;

create or replace function ledger.investment_lifecycle_entry_matches_v2(
  p_entry_id uuid,
  p_company_id uuid,
  p_income_year integer,
  p_entry_kind text,
  p_primary_record_id uuid,
  p_primary_fact_sha256 text,
  p_event_date date,
  p_corroborating_facts jsonb
)
returns boolean
language sql
stable
security definer
set search_path = ''
as $function$
  select exists (
    select 1
    from ledger.entries entry
    join ledger.entry_contexts context on context.entry_id = entry.id
    where entry.id = p_entry_id
      and entry.company_id = p_company_id
      and entry.income_year = p_income_year
      and entry.entry_kind = p_entry_kind
      and entry.source_capability = 'INVESTMENTS'
      and entry.source_record_id = p_primary_record_id::text
      and context.event_date = p_event_date
      and context.rule_version = 'ledger-supported-patterns-2026.1'
      and public.company_access_is_accepted_owner_v1(entry.company_id)
      and (
        select pg_catalog.count(*)
        from ledger.entry_sources source
        where source.entry_id = entry.id
      ) = pg_catalog.jsonb_array_length(p_corroborating_facts) + 1
      and exists (
        select 1 from ledger.entry_sources source
        where source.entry_id = entry.id
          and source.ordinal = 1
          and source.source_role = 'PRIMARY'
          and source.source_capability = 'INVESTMENTS'
          and source.source_record_id = p_primary_record_id::text
          and source.source_revision = 1
          and source.fact_sha256 = p_primary_fact_sha256
      )
      and not exists (
        select 1
        from pg_catalog.jsonb_array_elements(p_corroborating_facts)
          with ordinality fact(item, ordinal)
        where not exists (
          select 1 from ledger.entry_sources source
          where source.entry_id = entry.id
            and source.ordinal = fact.ordinal + 1
            and source.source_role = 'CORROBORATING'
            and source.source_capability = fact.item ->> 'capability'
            and source.source_record_id = fact.item ->> 'recordId'
            and source.source_revision =
              (fact.item ->> 'revision')::integer
            and source.fact_sha256 = fact.item ->> 'factSha256'
        )
      )
  );
$function$;

create or replace function investments.get_share_purchase_recognition_replay_v2(
  p_request jsonb, p_verified_subject text
)
returns jsonb language plpgsql security definer set search_path = ''
as $function$
declare
  v_actor_id uuid := public.company_access_auth_uid_v1();
  v_recognition investments.share_purchase_recognitions%rowtype;
  v_event investments.economic_events%rowtype;
begin
  if v_actor_id is null or v_actor_id is distinct from p_verified_subject::uuid
    or not public.company_access_is_accepted_owner_v1(
      (p_request ->> 'companyId')::uuid
    )
  then raise exception 'investments_forbidden'; end if;
  if not pg_catalog.pg_try_advisory_xact_lock(pg_catalog.hashtextextended(
    'investments:v2:' || v_actor_id::text || ':' ||
      (p_request ->> 'companyId') || ':share-purchase:' ||
      coalesce(p_request ->> 'idempotencyKey', ''), 0
  )) then raise exception 'investments_idempotency_in_progress'; end if;
  select recognition.* into v_recognition
  from investments.share_purchase_recognitions recognition
  where recognition.event_id = (p_request ->> 'eventId')::uuid
     or (
       recognition.created_by = v_actor_id
       and recognition.company_id = (p_request ->> 'companyId')::uuid
       and recognition.idempotency_key = p_request ->> 'idempotencyKey'
     )
  order by (recognition.event_id = (p_request ->> 'eventId')::uuid) desc
  limit 1;
  if not found then return null; end if;
  if v_recognition.company_id <> (p_request ->> 'companyId')::uuid
    or v_recognition.income_year <> (p_request ->> 'incomeYear')::integer
    or v_recognition.request_fingerprint <>
      investments.share_purchase_recognition_fingerprint_v2(p_request)
  then raise exception 'investments_idempotency_key_reused'; end if;
  if v_recognition.completed_event_id is null then
    raise exception 'investments_idempotency_in_progress';
  end if;
  select event.* into strict v_event
  from investments.economic_events event
  where event.event_id = v_recognition.event_id
    and event.company_id = v_recognition.company_id;
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

create or replace function investments.prepare_share_purchase_recognition_v2(
  p_request jsonb, p_verified_subject text
)
returns jsonb language plpgsql security definer set search_path = ''
as $function$
declare
  v_actor_id uuid := public.company_access_auth_uid_v1();
  v_company_id uuid := (p_request ->> 'companyId')::uuid;
  v_event_id uuid := (p_request ->> 'eventId')::uuid;
  v_kind text := p_request ->> 'investmentKind';
  v_classification text := p_request ->> 'accountingClassification';
  v_key text := pg_catalog.btrim(p_request ->> 'investmentKey');
  v_name text := pg_catalog.btrim(p_request ->> 'investmentName');
  v_org text := nullif(pg_catalog.btrim(p_request ->> 'orgNumber'), '');
  v_count numeric := (p_request ->> 'shareCount')::numeric;
  v_purchase numeric := (p_request ->> 'purchaseAmount')::numeric;
  v_costs numeric := (p_request ->> 'transactionCosts')::numeric;
  v_acquisition_cost numeric := (p_request ->> 'acquisitionCost')::numeric;
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
    'investments:v2:' || v_actor_id::text || ':' || v_company_id::text ||
      ':share-purchase:' || coalesce(p_request ->> 'idempotencyKey', ''), 0
  )) then raise exception 'investments_idempotency_in_progress'; end if;
  if coalesce(p_request ->> 'idempotencyKey', '')
      !~ '^[A-Za-z0-9._:-]{16,255}$'
    or (p_request ->> 'incomeYear')::integer <> 2026
    or v_key = '' or pg_catalog.length(v_key) > 255
    or v_name = '' or pg_catalog.length(v_name) > 255
    or v_count <= 0 or v_count >= 1e26 or v_count <> pg_catalog.round(v_count, 12)
    or v_purchase <= 0 or v_costs < 0
    or v_acquisition_cost <> v_purchase + v_costs
    or pg_catalog.round(v_purchase, 2) <> v_purchase
    or pg_catalog.round(v_costs, 2) <> v_costs
    or extract(year from (p_request ->> 'acquisitionDate')::date)::integer <> 2026
    or p_request ->> 'evidenceDigest' !~ '^[0-9a-f]{64}$'
    or p_request ->> 'calculationId' !~ '^[0-9a-f]{64}$'
    or nullif(pg_catalog.btrim(p_request ->> 'evidenceReference'), '') is null
    or pg_catalog.length(p_request ->> 'evidenceReference') > 500
    or pg_catalog.jsonb_typeof(p_request -> 'documentFacts') <> 'array'
    or pg_catalog.jsonb_array_length(p_request -> 'documentFacts') not between 1 and 50
    or p_request -> 'bankFact' is distinct from 'null'::jsonb
    or not (
      (p_request ->> 'evidenceMode' = 'linked_sources'
        and (p_request ->> 'ownerAttested')::boolean = false)
      or (p_request ->> 'evidenceMode' = 'manual_fallback'
        and (p_request ->> 'ownerAttested')::boolean = true)
    )
    or exists (
      select 1
      from pg_catalog.jsonb_array_elements(p_request -> 'documentFacts') fact
      where fact ->> 'capability' <> 'DOCUMENTS'
        or coalesce(fact ->> 'recordId', '') !~ '^[0-9a-fA-F-]{36}$'
        or coalesce(fact ->> 'revision', '') !~ '^[1-9][0-9]*$'
        or coalesce(fact ->> 'factSha256', '') !~ '^[0-9a-f]{64}$'
    )
    or exists (
      select 1
      from pg_catalog.jsonb_array_elements(p_request -> 'documentFacts') fact
      group by fact ->> 'recordId', fact ->> 'revision'
      having pg_catalog.count(*) > 1
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
    select 1 from investments.share_purchase_recognitions recognition
    where recognition.event_id = v_event_id
       or (
         recognition.created_by = v_actor_id
         and recognition.company_id = v_company_id
         and recognition.idempotency_key = p_request ->> 'idempotencyKey'
       )
  ) then raise exception 'investments_idempotency_key_reused'; end if;

  insert into investments.company_year_policies (
    company_id, income_year, policy_version, tax_law_version,
    current_measurement_rule, long_term_measurement_rule, created_by
  ) values (
    v_company_id, 2026, 'domestic_2026_v2', 'norwegian_2026',
    'lower_of_cost_and_fair_value', 'cost_with_evidenced_impairment',
    v_actor_id
  ) on conflict (company_id, income_year) do nothing;

  select position.* into v_position
  from investments.positions position
  where position.company_id = v_company_id and position.investment_key = v_key
  for update;
  if found then
    if v_position.name <> v_name or v_position.kind <> v_kind
      or v_position.accounting_classification <> v_classification
      or v_position.tax_treatment <> 'fritaksmetoden'
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
      'fritaksmetoden', v_org, v_fund_ratio, v_fund_reference,
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
    v_lot_id, v_company_id, v_position.id, v_event_id,
    (p_request ->> 'acquisitionDate')::date,
    v_count, 0, v_acquisition_cost, 0, v_acquisition_cost, 0,
    v_fund_ratio, v_fund_reference, v_actor_id
  );

  insert into investments.share_purchase_recognitions (
    event_id, company_id, income_year, idempotency_key,
    request_fingerprint, position_id, acquisition_lot_id, position_created,
    investment_key, investment_name, investment_kind,
    accounting_classification, acquisition_date, share_count,
    purchase_amount, transaction_costs, acquisition_cost, org_number,
    fund_equity_ratio_basis_points, fund_tax_statement_reference,
    evidence_mode, evidence_reference, owner_attested, evidence_digest,
    calculation_id, created_by
  ) values (
    v_event_id, v_company_id, 2026, p_request ->> 'idempotencyKey',
    investments.share_purchase_recognition_fingerprint_v2(p_request),
    v_position.id, v_lot_id, v_position_created, v_key, v_name, v_kind,
    v_classification, (p_request ->> 'acquisitionDate')::date, v_count,
    v_purchase, v_costs, v_acquisition_cost, v_org, v_fund_ratio,
    v_fund_reference, p_request ->> 'evidenceMode',
    pg_catalog.btrim(p_request ->> 'evidenceReference'),
    (p_request ->> 'ownerAttested')::boolean,
    p_request ->> 'evidenceDigest', p_request ->> 'calculationId', v_actor_id
  );

  return pg_catalog.jsonb_build_object(
    'positionId', v_position.id,
    'lotId', v_lot_id,
    'positionCreated', v_position_created,
    'investmentName', v_name,
    'accountingClassification', v_classification,
    'acquisitionCost', v_acquisition_cost,
    'expectedSettlementAmount', v_acquisition_cost,
    'settlementBalanceKind', 'purchase_payable',
    'evidenceDigest', p_request ->> 'evidenceDigest',
    'calculationId', p_request ->> 'calculationId'
  );
end;
$function$;

create or replace function investments.complete_share_purchase_recognition_v2(
  p_request jsonb, p_entry_id uuid, p_prepared jsonb,
  p_verified_subject text
)
returns jsonb language plpgsql security definer set search_path = ''
as $function$
declare
  v_actor_id uuid := public.company_access_auth_uid_v1();
  v_recognition investments.share_purchase_recognitions%rowtype;
  v_count integer;
begin
  if v_actor_id is null or v_actor_id is distinct from p_verified_subject::uuid
  then raise exception 'investments_forbidden'; end if;
  select recognition.* into v_recognition
  from investments.share_purchase_recognitions recognition
  where recognition.event_id = (p_request ->> 'eventId')::uuid
  for update;
  if not found
    or v_recognition.company_id <> (p_request ->> 'companyId')::uuid
    or v_recognition.request_fingerprint <>
      investments.share_purchase_recognition_fingerprint_v2(p_request)
    or v_recognition.position_id <> (p_prepared ->> 'positionId')::uuid
    or v_recognition.acquisition_lot_id <> (p_prepared ->> 'lotId')::uuid
    or v_recognition.acquisition_cost <>
      (p_prepared ->> 'acquisitionCost')::numeric
    or v_recognition.acquisition_cost <>
      (p_prepared ->> 'expectedSettlementAmount')::numeric
    or p_prepared ->> 'settlementBalanceKind' <> 'purchase_payable'
    or v_recognition.evidence_digest <> p_prepared ->> 'evidenceDigest'
    or v_recognition.calculation_id <> p_prepared ->> 'calculationId'
    or not ledger.investment_lifecycle_entry_matches_v2(
      p_entry_id, v_recognition.company_id, v_recognition.income_year,
      'SHARE_PURCHASE', v_recognition.event_id,
      v_recognition.calculation_id, v_recognition.acquisition_date,
      p_request -> 'documentFacts'
    )
  then raise exception 'investments_dependency_unavailable'; end if;
  if v_recognition.completed_event_id is not null then
    if exists (
      select 1 from investments.economic_events event
      where event.event_id = v_recognition.event_id
        and event.recognition_accounting_entry_id = p_entry_id
    ) then
      return pg_catalog.jsonb_build_object(
        'eventId', v_recognition.event_id,
        'positionId', v_recognition.position_id,
        'recognitionAccountingEntryId', p_entry_id,
        'expectedSettlementAmount', v_recognition.acquisition_cost,
        'settlementBalanceKind', 'purchase_payable',
        'replayed', true
      );
    end if;
    raise exception 'investments_idempotency_key_reused';
  end if;

  insert into investments.source_fact_registry (
    company_id, source_capability, source_record_id, source_revision,
    fact_sha256
  )
  select v_recognition.company_id, item ->> 'capability',
    (item ->> 'recordId')::uuid, (item ->> 'revision')::integer,
    item ->> 'factSha256'
  from pg_catalog.jsonb_array_elements(p_request -> 'documentFacts') item
  on conflict (
    company_id, source_capability, source_record_id, source_revision
  ) do update set fact_sha256 = excluded.fact_sha256
  where investments.source_fact_registry.fact_sha256 = excluded.fact_sha256;
  get diagnostics v_count = row_count;
  if v_count <> pg_catalog.jsonb_array_length(p_request -> 'documentFacts')
  then raise exception 'investments_invalid_input'; end if;

  insert into investments.economic_events (
    event_id, company_id, income_year, event_kind, position_id,
    recognition_date, policy_version, idempotency_key, request_fingerprint,
    evidence_mode, evidence_reference, owner_attested, evidence_digest,
    calculation_id, recognition_accounting_entry_id,
    expected_settlement_amount, settlement_balance_kind, created_by
  ) values (
    v_recognition.event_id, v_recognition.company_id,
    v_recognition.income_year, 'share_purchase', v_recognition.position_id,
    v_recognition.acquisition_date, 'domestic_2026_v2',
    v_recognition.idempotency_key, v_recognition.request_fingerprint,
    v_recognition.evidence_mode, v_recognition.evidence_reference,
    v_recognition.owner_attested, v_recognition.evidence_digest,
    v_recognition.calculation_id, p_entry_id,
    v_recognition.acquisition_cost, 'purchase_payable', v_actor_id
  );

  insert into investments.event_sources (
    event_id, company_id, ordinal, role, source_capability,
    source_record_id, source_revision, fact_sha256
  )
  select v_recognition.event_id, v_recognition.company_id,
    ordinal::integer,
    case when ordinal = 1 then 'primary_document' else 'supporting_document' end,
    item ->> 'capability', (item ->> 'recordId')::uuid,
    (item ->> 'revision')::integer, item ->> 'factSha256'
  from pg_catalog.jsonb_array_elements(p_request -> 'documentFacts')
    with ordinality source(item, ordinal);

  insert into investments.position_classifications (
    position_id, company_id, income_year, accounting_classification,
    purpose_reference, source_capability, source_record_id,
    source_revision, fact_sha256, created_by
  ) values (
    v_recognition.position_id, v_recognition.company_id,
    v_recognition.income_year, v_recognition.accounting_classification,
    v_recognition.evidence_reference,
    p_request -> 'documentFacts' -> 0 ->> 'capability',
    (p_request -> 'documentFacts' -> 0 ->> 'recordId')::uuid,
    (p_request -> 'documentFacts' -> 0 ->> 'revision')::integer,
    p_request -> 'documentFacts' -> 0 ->> 'factSha256', v_actor_id
  ) on conflict (position_id, income_year) do nothing;
  if not exists (
    select 1 from investments.position_classifications classification
    where classification.position_id = v_recognition.position_id
      and classification.company_id = v_recognition.company_id
      and classification.income_year = v_recognition.income_year
      and classification.accounting_classification =
        v_recognition.accounting_classification
  ) then raise exception 'investments_invalid_input'; end if;

  update investments.acquisition_lots
  set remaining_share_count = original_share_count,
      remaining_cost_basis = original_cost_basis,
      remaining_tax_basis = original_tax_basis
  where id = v_recognition.acquisition_lot_id
    and remaining_share_count = 0 and remaining_cost_basis = 0
    and remaining_tax_basis = 0;
  get diagnostics v_count = row_count;
  if v_count <> 1 then raise exception 'investments_dependency_unavailable'; end if;

  update investments.positions
  set share_count = share_count + v_recognition.share_count,
      cost_basis = cost_basis + v_recognition.acquisition_cost,
      tax_basis = tax_basis + v_recognition.acquisition_cost,
      movements = movements || pg_catalog.jsonb_build_array(
        pg_catalog.jsonb_build_object(
          'event_id', v_recognition.event_id,
          'movement_type', 'purchase_recognition',
          'movement_date', v_recognition.acquisition_date,
          'share_delta', v_recognition.share_count,
          'book_cost_basis_delta', v_recognition.acquisition_cost,
          'tax_basis_delta', v_recognition.acquisition_cost,
          'calculation_id', v_recognition.calculation_id,
          'evidence_digest', v_recognition.evidence_digest
        )
      ), updated_at = pg_catalog.now()
  where id = v_recognition.position_id;
  get diagnostics v_count = row_count;
  if v_count <> 1 then raise exception 'investments_dependency_unavailable'; end if;

  update investments.share_purchase_recognitions
  set completed_event_id = event_id, completed_at = pg_catalog.now()
  where event_id = v_recognition.event_id;

  insert into public.audit_events (company_id, actor_id, category, action, message)
  values (
    v_recognition.company_id, v_actor_id, 'ledger',
    'investment_purchase_recognized',
    'Investeringskjøp innregnet uten å anta kontantoppgjør.'
  );

  return pg_catalog.jsonb_build_object(
    'eventId', v_recognition.event_id,
    'positionId', v_recognition.position_id,
    'recognitionAccountingEntryId', p_entry_id,
    'expectedSettlementAmount', v_recognition.acquisition_cost,
    'settlementBalanceKind', 'purchase_payable',
    'replayed', false
  );
end;
$function$;

create or replace function investments.get_cash_settlement_replay_v2(
  p_request jsonb, p_verified_subject text
)
returns jsonb language plpgsql security definer set search_path = ''
as $function$
declare
  v_actor_id uuid := public.company_access_auth_uid_v1();
  v_settlement investments.cash_settlements%rowtype;
begin
  if v_actor_id is null or v_actor_id is distinct from p_verified_subject::uuid
    or not public.company_access_is_accepted_owner_v1(
      (p_request ->> 'companyId')::uuid
    )
  then raise exception 'investments_forbidden'; end if;
  if not pg_catalog.pg_try_advisory_xact_lock(pg_catalog.hashtextextended(
    'investments:v2:' || v_actor_id::text || ':' ||
      (p_request ->> 'companyId') || ':cash-settlement:' ||
      coalesce(p_request ->> 'idempotencyKey', ''), 0
  )) then raise exception 'investments_idempotency_in_progress'; end if;
  select settlement.* into v_settlement
  from investments.cash_settlements settlement
  where settlement.settlement_id = (p_request ->> 'settlementId')::uuid
     or (
       settlement.created_by = v_actor_id
       and settlement.company_id = (p_request ->> 'companyId')::uuid
       and settlement.idempotency_key = p_request ->> 'idempotencyKey'
     )
  order by (settlement.settlement_id =
    (p_request ->> 'settlementId')::uuid) desc
  limit 1;
  if not found then return null; end if;
  if v_settlement.company_id <> (p_request ->> 'companyId')::uuid
    or v_settlement.income_year <> (p_request ->> 'incomeYear')::integer
    or v_settlement.request_fingerprint <>
      investments.cash_settlement_fingerprint_v2(p_request)
  then raise exception 'investments_idempotency_key_reused'; end if;
  return pg_catalog.jsonb_build_object(
    'settlementId', v_settlement.settlement_id,
    'eventId', v_settlement.event_id,
    'settlementAccountingEntryId', v_settlement.settlement_accounting_entry_id,
    'replayed', true
  );
end;
$function$;

create or replace function investments.prepare_cash_settlement_v2(
  p_request jsonb, p_verified_subject text
)
returns jsonb language plpgsql security definer set search_path = ''
as $function$
declare
  v_actor_id uuid := public.company_access_auth_uid_v1();
  v_company_id uuid := (p_request ->> 'companyId')::uuid;
  v_event investments.economic_events%rowtype;
  v_amount numeric := (p_request ->> 'amount')::numeric;
begin
  if v_actor_id is null or v_actor_id is distinct from p_verified_subject::uuid
    or not public.company_access_is_accepted_owner_v1(v_company_id)
  then raise exception 'investments_forbidden'; end if;
  if not pg_catalog.pg_try_advisory_xact_lock(pg_catalog.hashtextextended(
    'investments:v2:' || v_actor_id::text || ':' || v_company_id::text ||
      ':cash-settlement:' || coalesce(p_request ->> 'idempotencyKey', ''), 0
  )) then raise exception 'investments_idempotency_in_progress'; end if;
  if coalesce(p_request ->> 'idempotencyKey', '')
      !~ '^[A-Za-z0-9._:-]{16,255}$'
    or (p_request ->> 'incomeYear')::integer not between 2000 and 2100
    or extract(year from (p_request ->> 'settlementDate')::date)::integer
      <> (p_request ->> 'incomeYear')::integer
    or v_amount <= 0 or pg_catalog.round(v_amount, 2) <> v_amount
    or p_request ->> 'evidenceDigest' !~ '^[0-9a-f]{64}$'
    or nullif(pg_catalog.btrim(p_request ->> 'evidenceReference'), '') is null
    or pg_catalog.length(p_request ->> 'evidenceReference') > 500
    or p_request -> 'documentFacts' is distinct from '[]'::jsonb
    or pg_catalog.jsonb_typeof(p_request -> 'bankFact') <> 'object'
    or p_request -> 'bankFact' ->> 'capability' <> 'BANKING'
    or coalesce(p_request -> 'bankFact' ->> 'recordId', '')
      !~ '^[0-9a-fA-F-]{36}$'
    or coalesce(p_request -> 'bankFact' ->> 'revision', '')
      !~ '^[1-9][0-9]*$'
    or coalesce(p_request -> 'bankFact' ->> 'factSha256', '')
      !~ '^[0-9a-f]{64}$'
    or not (
      (p_request ->> 'evidenceMode' = 'linked_sources'
        and (p_request ->> 'ownerAttested')::boolean = false)
      or (p_request ->> 'evidenceMode' = 'manual_fallback'
        and (p_request ->> 'ownerAttested')::boolean = true)
    )
  then raise exception 'investments_invalid_input'; end if;
  if exists (
    select 1 from investments.cash_settlements settlement
    where settlement.settlement_id = (p_request ->> 'settlementId')::uuid
       or (
         settlement.created_by = v_actor_id
         and settlement.company_id = v_company_id
         and settlement.idempotency_key = p_request ->> 'idempotencyKey'
       )
  ) then raise exception 'investments_idempotency_key_reused'; end if;

  perform pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended(
    'investments:v2:event-settlement:' || (p_request ->> 'eventId'), 0
  ));
  select event.* into v_event
  from investments.economic_events event
  where event.event_id = (p_request ->> 'eventId')::uuid;
  if not found or v_event.company_id <> v_company_id
    or v_event.expected_settlement_amount <> v_amount
    or exists (
      select 1 from investments.cash_settlements settlement
      where settlement.event_id = v_event.event_id
    )
  then raise exception 'investments_invalid_input'; end if;

  return pg_catalog.jsonb_build_object(
    'eventId', v_event.event_id,
    'recognitionAccountingEntryId', v_event.recognition_accounting_entry_id,
    'settlementBalanceKind', v_event.settlement_balance_kind,
    'amount', v_event.expected_settlement_amount,
    'eventFactSha256', investments.cash_settlement_fingerprint_v2(p_request),
    'evidenceDigest', p_request ->> 'evidenceDigest'
  );
end;
$function$;

create or replace function investments.complete_cash_settlement_v2(
  p_request jsonb, p_entry_id uuid, p_prepared jsonb,
  p_verified_subject text
)
returns jsonb language plpgsql security definer set search_path = ''
as $function$
declare
  v_actor_id uuid := public.company_access_auth_uid_v1();
  v_event investments.economic_events%rowtype;
  v_entry_kind text;
  v_bank_fact jsonb := p_request -> 'bankFact';
  v_fingerprint text := investments.cash_settlement_fingerprint_v2(p_request);
  v_count integer;
begin
  if v_actor_id is null or v_actor_id is distinct from p_verified_subject::uuid
  then raise exception 'investments_forbidden'; end if;
  perform pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended(
    'investments:v2:event-settlement:' || (p_request ->> 'eventId'), 0
  ));
  select event.* into v_event
  from investments.economic_events event
  where event.event_id = (p_request ->> 'eventId')::uuid;
  v_entry_kind := case v_event.event_kind
    when 'share_purchase' then 'SHARE_PURCHASE'
    when 'share_sale' then 'SHARE_SALE'
    else 'DIVIDEND_RECEIVED'
  end;
  if not found or v_event.company_id <> (p_request ->> 'companyId')::uuid
    or v_event.recognition_accounting_entry_id <>
      (p_prepared ->> 'recognitionAccountingEntryId')::uuid
    or v_event.settlement_balance_kind <>
      p_prepared ->> 'settlementBalanceKind'
    or v_event.expected_settlement_amount <> (p_request ->> 'amount')::numeric
    or v_event.expected_settlement_amount <> (p_prepared ->> 'amount')::numeric
    or p_prepared ->> 'eventId' <> v_event.event_id::text
    or p_prepared ->> 'eventFactSha256' <> v_fingerprint
    or p_prepared ->> 'evidenceDigest' <> p_request ->> 'evidenceDigest'
    or not ledger.investment_lifecycle_entry_matches_v2(
      p_entry_id, v_event.company_id,
      (p_request ->> 'incomeYear')::integer, v_entry_kind,
      (p_request ->> 'settlementId')::uuid, v_fingerprint,
      (p_request ->> 'settlementDate')::date,
      pg_catalog.jsonb_build_array(v_bank_fact)
    )
  then raise exception 'investments_dependency_unavailable'; end if;
  if exists (
    select 1 from investments.cash_settlements settlement
    where settlement.event_id = v_event.event_id
       or settlement.settlement_id = (p_request ->> 'settlementId')::uuid
  ) then raise exception 'investments_idempotency_key_reused'; end if;

  insert into investments.source_fact_registry (
    company_id, source_capability, source_record_id, source_revision,
    fact_sha256
  ) values (
    v_event.company_id, v_bank_fact ->> 'capability',
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
    settlement_accounting_entry_id, created_by
  ) values (
    (p_request ->> 'settlementId')::uuid, v_event.event_id,
    v_event.company_id, (p_request ->> 'incomeYear')::integer,
    (p_request ->> 'settlementDate')::date,
    (p_request ->> 'amount')::numeric, v_bank_fact ->> 'capability',
    (v_bank_fact ->> 'recordId')::uuid,
    (v_bank_fact ->> 'revision')::integer,
    v_bank_fact ->> 'factSha256', p_request ->> 'idempotencyKey',
    v_fingerprint, p_request ->> 'evidenceMode',
    pg_catalog.btrim(p_request ->> 'evidenceReference'),
    (p_request ->> 'ownerAttested')::boolean,
    p_request ->> 'evidenceDigest', p_entry_id, v_actor_id
  );

  insert into public.audit_events (company_id, actor_id, category, action, message)
  values (
    v_event.company_id, v_actor_id, 'ledger', 'investment_cash_settled',
    'Investeringsoppgjør koblet til innregnet hendelse og bankfaktum.'
  );

  return pg_catalog.jsonb_build_object(
    'settlementId', p_request ->> 'settlementId',
    'eventId', v_event.event_id,
    'settlementAccountingEntryId', p_entry_id,
    'replayed', false
  );
end;
$function$;

alter function investments.share_purchase_recognition_fingerprint_v2(jsonb)
  owner to investments_store_owner;
alter function investments.cash_settlement_fingerprint_v2(jsonb)
  owner to investments_store_owner;
alter function investments.get_share_purchase_recognition_replay_v2(jsonb, text)
  owner to investments_store_owner;
alter function investments.prepare_share_purchase_recognition_v2(jsonb, text)
  owner to investments_store_owner;
alter function investments.complete_share_purchase_recognition_v2(
  jsonb, uuid, jsonb, text
) owner to investments_store_owner;
alter function investments.get_cash_settlement_replay_v2(jsonb, text)
  owner to investments_store_owner;
alter function investments.prepare_cash_settlement_v2(jsonb, text)
  owner to investments_store_owner;
alter function investments.complete_cash_settlement_v2(
  jsonb, uuid, jsonb, text
) owner to investments_store_owner;
alter function ledger.post_investment_lifecycle_entry_v2(
  text, uuid, integer, text, text, jsonb, text, text, text, text,
  date, text, jsonb
) owner to ledger_store_owner;
alter function ledger.investment_lifecycle_entry_matches_v2(
  uuid, uuid, integer, text, uuid, text, date, jsonb
) owner to ledger_store_owner;

revoke all on function
  investments.share_purchase_recognition_fingerprint_v2(jsonb),
  investments.cash_settlement_fingerprint_v2(jsonb),
  investments.get_share_purchase_recognition_replay_v2(jsonb, text),
  investments.prepare_share_purchase_recognition_v2(jsonb, text),
  investments.complete_share_purchase_recognition_v2(
    jsonb, uuid, jsonb, text
  ),
  investments.get_cash_settlement_replay_v2(jsonb, text),
  investments.prepare_cash_settlement_v2(jsonb, text),
  investments.complete_cash_settlement_v2(jsonb, uuid, jsonb, text),
  ledger.post_investment_lifecycle_entry_v2(
    text, uuid, integer, text, text, jsonb, text, text, text, text,
    date, text, jsonb
  ),
  ledger.investment_lifecycle_entry_matches_v2(
    uuid, uuid, integer, text, uuid, text, date, jsonb
  )
from public, anon, authenticated, service_role;

grant execute on function
  investments.get_share_purchase_recognition_replay_v2(jsonb, text),
  investments.prepare_share_purchase_recognition_v2(jsonb, text),
  investments.complete_share_purchase_recognition_v2(
    jsonb, uuid, jsonb, text
  ),
  investments.get_cash_settlement_replay_v2(jsonb, text),
  investments.prepare_cash_settlement_v2(jsonb, text),
  investments.complete_cash_settlement_v2(jsonb, uuid, jsonb, text),
  ledger.post_investment_lifecycle_entry_v2(
    text, uuid, integer, text, text, jsonb, text, text, text, text,
    date, text, jsonb
  )
to investments_workflow_executor;
grant execute on function ledger.investment_lifecycle_entry_matches_v2(
  uuid, uuid, integer, text, uuid, text, date, jsonb
) to investments_store_owner;

set local role company_archive_projection_executor;
do $archive_authority$
begin
  execute pg_catalog.format(
    'grant execute on function public.company_archive_track_source_write_v1() to %I',
    pg_catalog.current_setting('talli.investments_lifecycle_migration_principal')
  );
end
$archive_authority$;
reset role;

create trigger company_archive_track_investments_economic_events
after insert or update or delete on investments.economic_events
for each row execute function public.company_archive_track_source_write_v1(
  'year', 'company_id'
);
create trigger company_archive_track_investments_cash_settlements
after insert or update or delete on investments.cash_settlements
for each row execute function public.company_archive_track_source_write_v1(
  'year', 'company_id'
);

set local role company_archive_projection_executor;
do $archive_authority_revoke$
begin
  execute pg_catalog.format(
    'revoke execute on function public.company_archive_track_source_write_v1() from %I',
    pg_catalog.current_setting('talli.investments_lifecycle_migration_principal')
  );
end
$archive_authority_revoke$;
reset role;

do $membership_revoke$
begin
  execute pg_catalog.format(
    'revoke investments_store_owner, investments_executor, investments_workflow_executor, ledger_store_owner, company_archive_projection_executor from %I',
    current_user
  );
end
$membership_revoke$;

commit;
