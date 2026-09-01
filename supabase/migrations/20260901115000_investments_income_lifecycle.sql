-- Recognize dividend and fund-distribution income before cash settlement.
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
  pg_catalog.hashtextextended('talli:investments:income-lifecycle:v2', 0)
);

create table investments.received_dividend_recognitions (
  event_id uuid primary key,
  company_id uuid not null references public.companies(id) on delete cascade,
  position_id uuid not null,
  paying_company_name text not null check (
    paying_company_name = pg_catalog.btrim(paying_company_name)
    and paying_company_name <> ''
    and pg_catalog.length(paying_company_name) <= 255
  ),
  declared_date date not null,
  gross_amount numeric(38, 12) not null check (gross_amount > 0),
  lawful_dividend_confirmed boolean not null check (lawful_dividend_confirmed),
  group_exception_claimed boolean not null,
  year_end_ownership_basis_points integer,
  year_end_voting_basis_points integer,
  group_evidence_reference text,
  group_exception_applied boolean not null,
  taxable_add_back numeric(38, 12) not null check (taxable_add_back >= 0),
  evidence_digest text not null check (evidence_digest ~ '^[0-9a-f]{64}$'),
  calculation_id text not null check (calculation_id ~ '^[0-9a-f]{64}$'),
  created_by uuid not null references auth.users(id) on delete restrict,
  created_at timestamptz not null default pg_catalog.now(),
  constraint received_dividend_recognitions_event_company_fk
    foreign key (event_id, company_id)
    references investments.economic_events(event_id, company_id)
    on delete restrict,
  constraint received_dividend_recognitions_position_company_fk
    foreign key (position_id, company_id)
    references investments.positions(id, company_id)
    on delete restrict,
  check (
    (
      group_exception_claimed and group_exception_applied
      and year_end_ownership_basis_points is not null
      and year_end_voting_basis_points is not null
      and year_end_ownership_basis_points > 9000
      and year_end_ownership_basis_points <= 10000
      and year_end_voting_basis_points > 9000
      and year_end_voting_basis_points <= 10000
      and nullif(pg_catalog.btrim(group_evidence_reference), '') is not null
      and pg_catalog.length(group_evidence_reference) <= 255
      and taxable_add_back = 0
    ) or (
      not group_exception_claimed and not group_exception_applied
      and year_end_ownership_basis_points is null
      and year_end_voting_basis_points is null
      and group_evidence_reference is null
    )
  )
);

create table investments.received_fund_distribution_recognitions (
  event_id uuid primary key,
  company_id uuid not null references public.companies(id) on delete cascade,
  position_id uuid not null,
  fund_name text not null check (
    fund_name = pg_catalog.btrim(fund_name) and fund_name <> ''
    and pg_catalog.length(fund_name) <= 255
  ),
  entitlement_date date not null,
  gross_amount numeric(38, 12) not null check (gross_amount > 0),
  opening_fund_equity_ratio_basis_points integer not null check (
    opening_fund_equity_ratio_basis_points between 0 and 10000
  ),
  fund_tax_statement_reference text not null check (
    nullif(pg_catalog.btrim(fund_tax_statement_reference), '') is not null
    and pg_catalog.length(fund_tax_statement_reference) <= 255
  ),
  dividend_portion numeric(38, 12) not null check (dividend_portion >= 0),
  interest_portion numeric(38, 12) not null check (interest_portion >= 0),
  taxable_add_back numeric(38, 12) not null check (taxable_add_back >= 0),
  total_taxable_income numeric(38, 12) not null check (total_taxable_income >= 0),
  evidence_digest text not null check (evidence_digest ~ '^[0-9a-f]{64}$'),
  calculation_id text not null check (calculation_id ~ '^[0-9a-f]{64}$'),
  created_by uuid not null references auth.users(id) on delete restrict,
  created_at timestamptz not null default pg_catalog.now(),
  constraint received_fund_distribution_recognitions_event_company_fk
    foreign key (event_id, company_id)
    references investments.economic_events(event_id, company_id)
    on delete restrict,
  constraint received_fund_distribution_recognitions_position_company_fk
    foreign key (position_id, company_id)
    references investments.positions(id, company_id)
    on delete restrict,
  check (dividend_portion + interest_portion = gross_amount),
  check (total_taxable_income = interest_portion + taxable_add_back)
);

create index investments_received_dividend_recognitions_company_date_idx
  on investments.received_dividend_recognitions(
    company_id, declared_date, event_id
  );
create index investments_received_fund_recognitions_company_date_idx
  on investments.received_fund_distribution_recognitions(
    company_id, entitlement_date, event_id
  );

alter table investments.received_dividend_recognitions
  owner to investments_store_owner;
alter table investments.received_fund_distribution_recognitions
  owner to investments_store_owner;
alter table investments.received_dividend_recognitions enable row level security;
alter table investments.received_dividend_recognitions force row level security;
alter table investments.received_fund_distribution_recognitions
  enable row level security;
alter table investments.received_fund_distribution_recognitions
  force row level security;

create policy investments_received_dividend_recognitions_member_select
on investments.received_dividend_recognitions for select
to investments_executor, investments_store_owner
using (public.company_access_is_accepted_member_v1(company_id));
create policy investments_received_dividend_recognitions_owner_insert
on investments.received_dividend_recognitions for insert
to investments_store_owner
with check (
  created_by = public.company_access_auth_uid_v1()
  and public.company_access_is_accepted_owner_v1(company_id)
);
create policy investments_received_fund_recognitions_member_select
on investments.received_fund_distribution_recognitions for select
to investments_executor, investments_store_owner
using (public.company_access_is_accepted_member_v1(company_id));
create policy investments_received_fund_recognitions_owner_insert
on investments.received_fund_distribution_recognitions for insert
to investments_store_owner
with check (
  created_by = public.company_access_auth_uid_v1()
  and public.company_access_is_accepted_owner_v1(company_id)
);

grant select, insert on investments.received_dividend_recognitions,
  investments.received_fund_distribution_recognitions
to investments_store_owner;
grant select on investments.received_dividend_recognitions,
  investments.received_fund_distribution_recognitions
to investments_executor;
revoke all on investments.received_dividend_recognitions,
  investments.received_fund_distribution_recognitions
from public, anon, authenticated, service_role, investments_workflow_executor;

create or replace function investments.received_dividend_recognition_fingerprint_v2(
  p_request jsonb
)
returns text language sql immutable set search_path = ''
as $function$
  select pg_catalog.encode(extensions.digest(
    (p_request - array['evidenceDigest', 'correlationId'])::text, 'sha256'
  ), 'hex');
$function$;

create or replace function investments.received_fund_recognition_fingerprint_v2(
  p_request jsonb
)
returns text language sql immutable set search_path = ''
as $function$
  select pg_catalog.encode(extensions.digest(
    (p_request - array['evidenceDigest', 'correlationId'])::text, 'sha256'
  ), 'hex');
$function$;

create or replace function investments.get_received_dividend_recognition_replay_v2(
  p_request jsonb, p_verified_subject text
)
returns jsonb language plpgsql security definer set search_path = ''
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
      (p_request ->> 'companyId') || ':dividend-recognition:' ||
      coalesce(p_request ->> 'idempotencyKey', ''), 0
  )) then raise exception 'investments_idempotency_in_progress'; end if;
  select event.* into v_event from investments.economic_events event
  where event.event_id = (p_request ->> 'eventId')::uuid
     or (
       event.created_by = v_actor_id
       and event.company_id = (p_request ->> 'companyId')::uuid
       and event.idempotency_key = p_request ->> 'idempotencyKey'
     )
  order by (event.event_id = (p_request ->> 'eventId')::uuid) desc limit 1;
  if not found then return null; end if;
  if v_event.event_kind <> 'dividend_received'
    or v_event.company_id <> (p_request ->> 'companyId')::uuid
    or v_event.income_year <> (p_request ->> 'incomeYear')::integer
    or v_event.request_fingerprint <>
      investments.received_dividend_recognition_fingerprint_v2(p_request)
  then raise exception 'investments_idempotency_key_reused'; end if;
  return pg_catalog.jsonb_build_object(
    'eventId', v_event.event_id, 'positionId', v_event.position_id,
    'recognitionAccountingEntryId', v_event.recognition_accounting_entry_id,
    'expectedSettlementAmount', v_event.expected_settlement_amount,
    'settlementBalanceKind', 'dividend_receivable', 'replayed', true
  );
end;
$function$;

create or replace function investments.get_received_fund_distribution_recognition_replay_v2(
  p_request jsonb, p_verified_subject text
)
returns jsonb language plpgsql security definer set search_path = ''
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
      (p_request ->> 'companyId') || ':fund-recognition:' ||
      coalesce(p_request ->> 'idempotencyKey', ''), 0
  )) then raise exception 'investments_idempotency_in_progress'; end if;
  select event.* into v_event from investments.economic_events event
  where event.event_id = (p_request ->> 'eventId')::uuid
     or (
       event.created_by = v_actor_id
       and event.company_id = (p_request ->> 'companyId')::uuid
       and event.idempotency_key = p_request ->> 'idempotencyKey'
     )
  order by (event.event_id = (p_request ->> 'eventId')::uuid) desc limit 1;
  if not found then return null; end if;
  if v_event.event_kind <> 'fund_distribution_received'
    or v_event.company_id <> (p_request ->> 'companyId')::uuid
    or v_event.income_year <> (p_request ->> 'incomeYear')::integer
    or v_event.request_fingerprint <>
      investments.received_fund_recognition_fingerprint_v2(p_request)
  then raise exception 'investments_idempotency_key_reused'; end if;
  return pg_catalog.jsonb_build_object(
    'eventId', v_event.event_id, 'positionId', v_event.position_id,
    'recognitionAccountingEntryId', v_event.recognition_accounting_entry_id,
    'expectedSettlementAmount', v_event.expected_settlement_amount,
    'settlementBalanceKind', 'fund_distribution_receivable', 'replayed', true
  );
end;
$function$;

create or replace function investments.prepare_received_dividend_recognition_v2(
  p_request jsonb, p_verified_subject text
)
returns jsonb language plpgsql security definer set search_path = ''
as $function$
declare
  v_actor_id uuid := public.company_access_auth_uid_v1();
  v_company_id uuid := (p_request ->> 'companyId')::uuid;
  v_position investments.positions%rowtype;
  v_name text := pg_catalog.btrim(p_request ->> 'payingCompanyName');
  v_gross numeric := (p_request ->> 'grossAmount')::numeric;
  v_claimed boolean := (p_request ->> 'groupExceptionClaimed')::boolean;
  v_ownership integer := nullif(
    p_request ->> 'yearEndOwnershipBasisPoints', ''
  )::integer;
  v_voting integer := nullif(
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
    'investments:v2:' || v_actor_id::text || ':' || v_company_id::text ||
      ':dividend-recognition:' || coalesce(p_request ->> 'idempotencyKey', ''), 0
  )) then raise exception 'investments_idempotency_in_progress'; end if;
  if coalesce(p_request ->> 'idempotencyKey', '')
      !~ '^[A-Za-z0-9._:-]{16,255}$'
    or (p_request ->> 'incomeYear')::integer <> 2026
    or extract(year from (p_request ->> 'declaredDate')::date)::integer <> 2026
    or v_name = '' or pg_catalog.length(v_name) > 255
    or v_gross <= 0 or pg_catalog.round(v_gross, 2) <> v_gross
    or (p_request ->> 'lawfulDividendConfirmed')::boolean is not true
    or pg_catalog.jsonb_typeof(p_request -> 'groupExceptionClaimed') <> 'boolean'
    or v_claimed is null
    or p_request ->> 'evidenceDigest' !~ '^[0-9a-f]{64}$'
    or not investments.lifecycle_document_evidence_is_valid_v2(p_request)
    or (
      v_claimed and (
        v_ownership is null or v_ownership not between 9001 and 10000
        or v_voting is null or v_voting not between 9001 and 10000
        or v_group_reference is null
        or pg_catalog.length(v_group_reference) > 255
      )
    )
    or (
      not v_claimed and (
        v_ownership is not null or v_voting is not null
        or v_group_reference is not null
      )
    )
  then raise exception 'investments_invalid_input'; end if;
  if exists (
    select 1 from investments.economic_events event
    where event.event_id = (p_request ->> 'eventId')::uuid
       or (event.created_by = v_actor_id and event.company_id = v_company_id
         and event.idempotency_key = p_request ->> 'idempotencyKey')
  ) or exists (
    select 1 from investments.received_dividends dividend
    where dividend.action_id = (p_request ->> 'eventId')::uuid
       or (dividend.created_by = v_actor_id and dividend.company_id = v_company_id
         and dividend.idempotency_key = p_request ->> 'idempotencyKey')
  ) then raise exception 'investments_idempotency_key_reused'; end if;
  select position.* into v_position from investments.positions position
  where position.id = (p_request ->> 'positionId')::uuid for update;
  if not found or v_position.company_id <> v_company_id
    or v_position.kind not in (
      'norwegian_private_company', 'norwegian_listed_share'
    )
    or v_position.tax_treatment <> 'fritaksmetoden'
    or not exists (
      select 1 from investments.company_year_policies policy
      where policy.company_id = v_company_id and policy.income_year = 2026
        and policy.policy_version = 'domestic_2026_v2'
    )
  then raise exception 'investments_invalid_input'; end if;
  return pg_catalog.jsonb_build_object(
    'positionId', v_position.id, 'investmentName', v_position.name,
    'investmentKind', v_position.kind
  );
end;
$function$;

create or replace function investments.prepare_received_fund_distribution_recognition_v2(
  p_request jsonb, p_verified_subject text
)
returns jsonb language plpgsql security definer set search_path = ''
as $function$
declare
  v_actor_id uuid := public.company_access_auth_uid_v1();
  v_company_id uuid := (p_request ->> 'companyId')::uuid;
  v_position investments.positions%rowtype;
  v_name text := pg_catalog.btrim(p_request ->> 'fundName');
  v_reference text := pg_catalog.btrim(
    p_request ->> 'fundTaxStatementReference'
  );
  v_gross numeric := (p_request ->> 'grossAmount')::numeric;
  v_ratio integer := (p_request ->> 'openingFundEquityRatioBasisPoints')::integer;
begin
  if v_actor_id is null or v_actor_id is distinct from p_verified_subject::uuid
    or not public.company_access_is_accepted_owner_v1(v_company_id)
  then raise exception 'investments_forbidden'; end if;
  if not pg_catalog.pg_try_advisory_xact_lock(pg_catalog.hashtextextended(
    'investments:v2:' || v_actor_id::text || ':' || v_company_id::text ||
      ':fund-recognition:' || coalesce(p_request ->> 'idempotencyKey', ''), 0
  )) then raise exception 'investments_idempotency_in_progress'; end if;
  if coalesce(p_request ->> 'idempotencyKey', '')
      !~ '^[A-Za-z0-9._:-]{16,255}$'
    or (p_request ->> 'incomeYear')::integer <> 2026
    or extract(year from (p_request ->> 'entitlementDate')::date)::integer <> 2026
    or v_name = '' or pg_catalog.length(v_name) > 255
    or v_reference = '' or pg_catalog.length(v_reference) > 255
    or v_gross <= 0 or pg_catalog.round(v_gross, 2) <> v_gross
    or v_ratio not between 0 and 10000
    or p_request ->> 'evidenceDigest' !~ '^[0-9a-f]{64}$'
    or not investments.lifecycle_document_evidence_is_valid_v2(p_request)
  then raise exception 'investments_invalid_input'; end if;
  if exists (
    select 1 from investments.economic_events event
    where event.event_id = (p_request ->> 'eventId')::uuid
       or (event.created_by = v_actor_id and event.company_id = v_company_id
         and event.idempotency_key = p_request ->> 'idempotencyKey')
  ) or exists (
    select 1 from investments.received_fund_distributions distribution
    where distribution.action_id = (p_request ->> 'eventId')::uuid
       or (distribution.created_by = v_actor_id
         and distribution.company_id = v_company_id
         and distribution.idempotency_key = p_request ->> 'idempotencyKey')
  ) then raise exception 'investments_idempotency_key_reused'; end if;
  select position.* into v_position from investments.positions position
  where position.id = (p_request ->> 'positionId')::uuid for update;
  if not found or v_position.company_id <> v_company_id
    or v_position.kind <> 'norwegian_equity_fund'
    or v_position.tax_treatment <> 'fritaksmetoden'
    or not exists (
      select 1 from investments.company_year_policies policy
      where policy.company_id = v_company_id and policy.income_year = 2026
        and policy.policy_version = 'domestic_2026_v2'
    )
  then raise exception 'investments_invalid_input'; end if;
  return pg_catalog.jsonb_build_object(
    'positionId', v_position.id, 'investmentName', v_position.name,
    'investmentKind', v_position.kind
  );
end;
$function$;

create or replace function investments.complete_received_dividend_recognition_v2(
  p_request jsonb, p_entry_id uuid, p_prepared jsonb,
  p_verified_subject text
)
returns jsonb language plpgsql security definer set search_path = ''
as $function$
declare
  v_actor_id uuid := public.company_access_auth_uid_v1();
  v_company_id uuid := (p_request ->> 'companyId')::uuid;
  v_event_id uuid := (p_request ->> 'eventId')::uuid;
  v_position investments.positions%rowtype;
  v_gross numeric := (p_request ->> 'grossAmount')::numeric;
  v_claimed boolean := (p_request ->> 'groupExceptionClaimed')::boolean;
  v_add_back numeric := (p_prepared ->> 'taxableAddBack')::numeric;
begin
  if v_actor_id is null or v_actor_id is distinct from p_verified_subject::uuid
    or not public.company_access_is_accepted_owner_v1(v_company_id)
  then raise exception 'investments_forbidden'; end if;
  if not pg_catalog.pg_try_advisory_xact_lock(pg_catalog.hashtextextended(
    'investments:v2:' || v_actor_id::text || ':' || v_company_id::text ||
      ':dividend-recognition:' || coalesce(p_request ->> 'idempotencyKey', ''), 0
  )) then raise exception 'investments_idempotency_in_progress'; end if;
  if p_prepared ->> 'evidenceDigest' !~ '^[0-9a-f]{64}$'
    or p_prepared ->> 'calculationId' !~ '^[0-9a-f]{64}$'
    or (p_prepared ->> 'groupExceptionApplied')::boolean <> v_claimed
    or (v_claimed and v_add_back <> 0)
    or (not v_claimed and v_add_back <> pg_catalog.round(v_gross * 0.03, 2))
    or not investments.lifecycle_document_evidence_is_valid_v2(p_request)
    or not ledger.investment_lifecycle_entry_matches_v2(
      p_entry_id, v_company_id, 2026, 'DIVIDEND_RECEIVED', v_event_id,
      p_prepared ->> 'calculationId', (p_request ->> 'declaredDate')::date,
      p_request -> 'documentFacts'
    )
  then raise exception 'investments_dependency_unavailable'; end if;
  if exists (
    select 1 from investments.economic_events event
    where event.event_id = v_event_id
       or (event.created_by = v_actor_id and event.company_id = v_company_id
         and event.idempotency_key = p_request ->> 'idempotencyKey')
  ) then raise exception 'investments_idempotency_key_reused'; end if;
  select position.* into v_position from investments.positions position
  where position.id = (p_request ->> 'positionId')::uuid for update;
  if not found or v_position.company_id <> v_company_id
    or v_position.id <> (p_prepared ->> 'positionId')::uuid
  then raise exception 'investments_dependency_unavailable'; end if;

  insert into investments.economic_events (
    event_id, company_id, income_year, event_kind, position_id,
    recognition_date, policy_version, idempotency_key, request_fingerprint,
    evidence_mode, evidence_reference, owner_attested, evidence_digest,
    calculation_id, recognition_accounting_entry_id,
    expected_settlement_amount, settlement_balance_kind, created_by
  ) values (
    v_event_id, v_company_id, 2026, 'dividend_received', v_position.id,
    (p_request ->> 'declaredDate')::date, 'domestic_2026_v2',
    p_request ->> 'idempotencyKey',
    investments.received_dividend_recognition_fingerprint_v2(p_request),
    p_request ->> 'evidenceMode',
    pg_catalog.btrim(p_request ->> 'evidenceReference'),
    (p_request ->> 'ownerAttested')::boolean,
    p_prepared ->> 'evidenceDigest', p_prepared ->> 'calculationId',
    p_entry_id, v_gross, 'dividend_receivable', v_actor_id
  );
  insert into investments.received_dividend_recognitions (
    event_id, company_id, position_id, paying_company_name, declared_date,
    gross_amount, lawful_dividend_confirmed, group_exception_claimed,
    year_end_ownership_basis_points, year_end_voting_basis_points,
    group_evidence_reference, group_exception_applied, taxable_add_back,
    evidence_digest, calculation_id, created_by
  ) values (
    v_event_id, v_company_id, v_position.id,
    pg_catalog.btrim(p_request ->> 'payingCompanyName'),
    (p_request ->> 'declaredDate')::date, v_gross,
    (p_request ->> 'lawfulDividendConfirmed')::boolean, v_claimed,
    nullif(p_request ->> 'yearEndOwnershipBasisPoints', '')::integer,
    nullif(p_request ->> 'yearEndVotingBasisPoints', '')::integer,
    nullif(pg_catalog.btrim(p_request ->> 'groupEvidenceReference'), ''),
    (p_prepared ->> 'groupExceptionApplied')::boolean, v_add_back,
    p_prepared ->> 'evidenceDigest', p_prepared ->> 'calculationId', v_actor_id
  );
  perform investments.record_lifecycle_document_sources_v2(
    v_company_id, v_event_id, p_request -> 'documentFacts'
  );
  insert into public.audit_events (company_id, actor_id, category, action, message)
  values (
    v_company_id, v_actor_id, 'ledger', 'investment_dividend_recognized',
    'Investeringsutbytte innregnet på beslutningsdato uten å anta betaling.'
  );
  return pg_catalog.jsonb_build_object(
    'eventId', v_event_id, 'positionId', v_position.id,
    'recognitionAccountingEntryId', p_entry_id,
    'expectedSettlementAmount', v_gross,
    'settlementBalanceKind', 'dividend_receivable', 'replayed', false
  );
end;
$function$;

create or replace function investments.complete_received_fund_distribution_recognition_v2(
  p_request jsonb, p_entry_id uuid, p_prepared jsonb,
  p_verified_subject text
)
returns jsonb language plpgsql security definer set search_path = ''
as $function$
declare
  v_actor_id uuid := public.company_access_auth_uid_v1();
  v_company_id uuid := (p_request ->> 'companyId')::uuid;
  v_event_id uuid := (p_request ->> 'eventId')::uuid;
  v_position investments.positions%rowtype;
  v_gross numeric := (p_request ->> 'grossAmount')::numeric;
  v_ratio integer := (p_request ->> 'openingFundEquityRatioBasisPoints')::integer;
  v_dividend numeric := (p_prepared ->> 'dividendPortion')::numeric;
  v_interest numeric := (p_prepared ->> 'interestPortion')::numeric;
  v_add_back numeric := (p_prepared ->> 'taxableAddBack')::numeric;
  v_total numeric := (p_prepared ->> 'totalTaxableIncome')::numeric;
  v_expected_dividend numeric;
begin
  if v_actor_id is null or v_actor_id is distinct from p_verified_subject::uuid
    or not public.company_access_is_accepted_owner_v1(v_company_id)
  then raise exception 'investments_forbidden'; end if;
  if not pg_catalog.pg_try_advisory_xact_lock(pg_catalog.hashtextextended(
    'investments:v2:' || v_actor_id::text || ':' || v_company_id::text ||
      ':fund-recognition:' || coalesce(p_request ->> 'idempotencyKey', ''), 0
  )) then raise exception 'investments_idempotency_in_progress'; end if;
  v_expected_dividend := case
    when v_ratio > 8000 then v_gross
    when v_ratio < 2000 then 0
    else pg_catalog.round(v_gross * v_ratio / 10000, 2)
  end;
  if p_prepared ->> 'evidenceDigest' !~ '^[0-9a-f]{64}$'
    or p_prepared ->> 'calculationId' !~ '^[0-9a-f]{64}$'
    or v_dividend <> v_expected_dividend
    or v_interest <> v_gross - v_dividend
    or v_add_back <> pg_catalog.round(v_dividend * 0.03, 2)
    or v_total <> v_interest + v_add_back
    or not investments.lifecycle_document_evidence_is_valid_v2(p_request)
    or not ledger.investment_lifecycle_entry_matches_v2(
      p_entry_id, v_company_id, 2026, 'DIVIDEND_RECEIVED', v_event_id,
      p_prepared ->> 'calculationId', (p_request ->> 'entitlementDate')::date,
      p_request -> 'documentFacts'
    )
  then raise exception 'investments_dependency_unavailable'; end if;
  if exists (
    select 1 from investments.economic_events event
    where event.event_id = v_event_id
       or (event.created_by = v_actor_id and event.company_id = v_company_id
         and event.idempotency_key = p_request ->> 'idempotencyKey')
  ) then raise exception 'investments_idempotency_key_reused'; end if;
  select position.* into v_position from investments.positions position
  where position.id = (p_request ->> 'positionId')::uuid for update;
  if not found or v_position.company_id <> v_company_id
    or v_position.id <> (p_prepared ->> 'positionId')::uuid
    or v_position.kind <> 'norwegian_equity_fund'
  then raise exception 'investments_dependency_unavailable'; end if;

  insert into investments.economic_events (
    event_id, company_id, income_year, event_kind, position_id,
    recognition_date, policy_version, idempotency_key, request_fingerprint,
    evidence_mode, evidence_reference, owner_attested, evidence_digest,
    calculation_id, recognition_accounting_entry_id,
    expected_settlement_amount, settlement_balance_kind, created_by
  ) values (
    v_event_id, v_company_id, 2026, 'fund_distribution_received', v_position.id,
    (p_request ->> 'entitlementDate')::date, 'domestic_2026_v2',
    p_request ->> 'idempotencyKey',
    investments.received_fund_recognition_fingerprint_v2(p_request),
    p_request ->> 'evidenceMode',
    pg_catalog.btrim(p_request ->> 'evidenceReference'),
    (p_request ->> 'ownerAttested')::boolean,
    p_prepared ->> 'evidenceDigest', p_prepared ->> 'calculationId',
    p_entry_id, v_gross, 'fund_distribution_receivable', v_actor_id
  );
  insert into investments.received_fund_distribution_recognitions (
    event_id, company_id, position_id, fund_name, entitlement_date,
    gross_amount, opening_fund_equity_ratio_basis_points,
    fund_tax_statement_reference, dividend_portion, interest_portion,
    taxable_add_back, total_taxable_income, evidence_digest,
    calculation_id, created_by
  ) values (
    v_event_id, v_company_id, v_position.id,
    pg_catalog.btrim(p_request ->> 'fundName'),
    (p_request ->> 'entitlementDate')::date, v_gross, v_ratio,
    pg_catalog.btrim(p_request ->> 'fundTaxStatementReference'),
    v_dividend, v_interest, v_add_back, v_total,
    p_prepared ->> 'evidenceDigest', p_prepared ->> 'calculationId', v_actor_id
  );
  perform investments.record_lifecycle_document_sources_v2(
    v_company_id, v_event_id, p_request -> 'documentFacts'
  );
  insert into public.audit_events (company_id, actor_id, category, action, message)
  values (
    v_company_id, v_actor_id, 'ledger',
    'investment_fund_distribution_recognized',
    'Fondsutdeling innregnet på opptjeningsdato uten å anta betaling.'
  );
  return pg_catalog.jsonb_build_object(
    'eventId', v_event_id, 'positionId', v_position.id,
    'recognitionAccountingEntryId', p_entry_id,
    'expectedSettlementAmount', v_gross,
    'settlementBalanceKind', 'fund_distribution_receivable', 'replayed', false
  );
end;
$function$;

alter function investments.received_dividend_recognition_fingerprint_v2(jsonb)
  owner to investments_store_owner;
alter function investments.received_fund_recognition_fingerprint_v2(jsonb)
  owner to investments_store_owner;
alter function investments.get_received_dividend_recognition_replay_v2(jsonb, text)
  owner to investments_store_owner;
alter function investments.get_received_fund_distribution_recognition_replay_v2(
  jsonb, text
) owner to investments_store_owner;
alter function investments.prepare_received_dividend_recognition_v2(jsonb, text)
  owner to investments_store_owner;
alter function investments.prepare_received_fund_distribution_recognition_v2(
  jsonb, text
) owner to investments_store_owner;
alter function investments.complete_received_dividend_recognition_v2(
  jsonb, uuid, jsonb, text
) owner to investments_store_owner;
alter function investments.complete_received_fund_distribution_recognition_v2(
  jsonb, uuid, jsonb, text
) owner to investments_store_owner;

revoke all on function
  investments.received_dividend_recognition_fingerprint_v2(jsonb),
  investments.received_fund_recognition_fingerprint_v2(jsonb),
  investments.get_received_dividend_recognition_replay_v2(jsonb, text),
  investments.get_received_fund_distribution_recognition_replay_v2(jsonb, text),
  investments.prepare_received_dividend_recognition_v2(jsonb, text),
  investments.prepare_received_fund_distribution_recognition_v2(jsonb, text),
  investments.complete_received_dividend_recognition_v2(
    jsonb, uuid, jsonb, text
  ),
  investments.complete_received_fund_distribution_recognition_v2(
    jsonb, uuid, jsonb, text
  )
from public, anon, authenticated, service_role;

grant execute on function
  investments.get_received_dividend_recognition_replay_v2(jsonb, text),
  investments.get_received_fund_distribution_recognition_replay_v2(jsonb, text),
  investments.prepare_received_dividend_recognition_v2(jsonb, text),
  investments.prepare_received_fund_distribution_recognition_v2(jsonb, text),
  investments.complete_received_dividend_recognition_v2(
    jsonb, uuid, jsonb, text
  ),
  investments.complete_received_fund_distribution_recognition_v2(
    jsonb, uuid, jsonb, text
  )
to investments_workflow_executor;
grant execute on function
  investments.received_dividend_recognition_fingerprint_v2(jsonb),
  investments.received_fund_recognition_fingerprint_v2(jsonb)
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
