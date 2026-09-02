-- Expand #190 with canonical economic events, immutable source facts,
-- separate cash settlement, explicit company-year policy, and year-end measurement.
begin;

set local lock_timeout = '5s';
set local statement_timeout = '120s';

do $membership$
begin
  execute pg_catalog.format(
    'grant investments_store_owner to %I',
    current_user
  );
end
$membership$;

select pg_catalog.pg_advisory_xact_lock(
  pg_catalog.hashtextextended('talli:investments:lifecycle-measurement:v2', 0)
);

alter table investments.positions
  drop constraint positions_classification_supported_check;
alter table investments.positions
  add constraint positions_classification_supported_check check (
    (
      kind in ('norwegian_private_company', 'norwegian_listed_share')
      and accounting_classification in (
        'subsidiary', 'associate', 'other_long_term', 'current_listed_share'
      )
    ) or (
      kind = 'norwegian_equity_fund'
      and accounting_classification in ('other_long_term', 'current_fund')
    )
  );

alter table investments.positions
  alter column share_count type numeric(38, 12),
  alter column cost_basis type numeric(38, 12),
  alter column tax_basis type numeric(38, 12);
alter table investments.positions
  add constraint positions_id_company_unique unique (id, company_id);
alter table investments.acquisition_lots
  alter column original_share_count type numeric(38, 12),
  alter column remaining_share_count type numeric(38, 12),
  alter column original_cost_basis type numeric(38, 12),
  alter column remaining_cost_basis type numeric(38, 12),
  alter column original_tax_basis type numeric(38, 12),
  alter column remaining_tax_basis type numeric(38, 12);
alter table investments.share_purchases
  alter column share_count type numeric(38, 12),
  alter column purchase_amount type numeric(38, 12),
  alter column transaction_costs type numeric(38, 12),
  alter column capitalized_cost type numeric(38, 12);
alter table investments.share_sales
  alter column sold_share_count type numeric(38, 12),
  alter column proceeds type numeric(38, 12),
  alter column transaction_costs type numeric(38, 12),
  alter column net_proceeds type numeric(38, 12),
  alter column fifo_cost_basis_reduction type numeric(38, 12),
  alter column fifo_tax_basis_reduction type numeric(38, 12),
  alter column book_gain_or_loss type numeric(38, 12),
  alter column tax_gain_or_loss type numeric(38, 12),
  alter column exempt_gain type numeric(38, 12),
  alter column taxable_gain type numeric(38, 12),
  alter column non_deductible_loss type numeric(38, 12),
  alter column deductible_loss type numeric(38, 12),
  alter column remaining_share_count type numeric(38, 12),
  alter column remaining_cost_basis type numeric(38, 12),
  alter column remaining_tax_basis type numeric(38, 12);
alter table investments.share_sale_allocations
  alter column allocated_share_count type numeric(38, 12),
  alter column allocated_cost_basis type numeric(38, 12),
  alter column allocated_book_cost_basis type numeric(38, 12),
  alter column allocated_tax_basis type numeric(38, 12),
  alter column allocated_net_proceeds type numeric(38, 12),
  alter column tax_gain_or_loss type numeric(38, 12),
  alter column exempt_gain type numeric(38, 12),
  alter column taxable_gain type numeric(38, 12),
  alter column non_deductible_loss type numeric(38, 12),
  alter column deductible_loss type numeric(38, 12);
alter table investments.received_dividends
  alter column gross_amount type numeric(38, 12),
  alter column taxable_add_back type numeric(38, 12);
alter table investments.received_fund_distributions
  alter column gross_amount type numeric(38, 12),
  alter column dividend_portion type numeric(38, 12),
  alter column interest_portion type numeric(38, 12),
  alter column taxable_add_back type numeric(38, 12),
  alter column total_taxable_income type numeric(38, 12);

create table investments.company_year_policies (
  company_id uuid not null references public.companies(id) on delete cascade,
  income_year integer not null check (income_year = 2026),
  policy_version text not null check (policy_version = 'domestic_2026_v2'),
  tax_law_version text not null check (tax_law_version = 'norwegian_2026'),
  current_measurement_rule text not null check (
    current_measurement_rule = 'lower_of_cost_and_fair_value'
  ),
  long_term_measurement_rule text not null check (
    long_term_measurement_rule = 'cost_with_evidenced_impairment'
  ),
  created_by uuid not null references auth.users(id) on delete restrict,
  created_at timestamptz not null default pg_catalog.now(),
  primary key (company_id, income_year)
);

create table investments.economic_events (
  event_id uuid primary key,
  company_id uuid not null references public.companies(id) on delete cascade,
  income_year integer not null check (income_year = 2026),
  event_kind text not null check (event_kind in (
    'share_purchase', 'share_sale', 'dividend_received',
    'fund_distribution_received'
  )),
  position_id uuid,
  recognition_date date not null,
  policy_version text not null check (policy_version = 'domestic_2026_v2'),
  idempotency_key text not null check (
    nullif(pg_catalog.btrim(idempotency_key), '') is not null
    and pg_catalog.length(idempotency_key) <= 200
  ),
  request_fingerprint text not null check (request_fingerprint ~ '^[0-9a-f]{64}$'),
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
  recognition_accounting_entry_id uuid not null unique,
  expected_settlement_amount numeric(38, 12) not null check (
    expected_settlement_amount > 0
  ),
  settlement_balance_kind text not null check (
    settlement_balance_kind in ('purchase_payable', 'sale_receivable', 'income_receivable')
  ),
  created_by uuid not null references auth.users(id) on delete restrict,
  created_at timestamptz not null default pg_catalog.now(),
  constraint economic_events_event_company_unique unique (event_id, company_id),
  foreign key (company_id, income_year)
    references investments.company_year_policies(company_id, income_year)
    on delete restrict,
  foreign key (position_id, company_id)
    references investments.positions(id, company_id)
    on delete restrict,
  unique (created_by, company_id, idempotency_key),
  unique (created_by, company_id, request_fingerprint),
  check (
    (evidence_mode = 'linked_sources' and not owner_attested)
    or (evidence_mode = 'manual_fallback' and owner_attested)
  ),
  check (extract(year from recognition_date)::integer = income_year)
);

create table investments.event_sources (
  event_id uuid not null,
  company_id uuid not null references public.companies(id) on delete cascade,
  ordinal integer not null check (ordinal > 0),
  role text not null check (role in ('primary_document', 'supporting_document')),
  source_capability text not null check (source_capability = 'DOCUMENTS'),
  source_record_id uuid not null,
  source_revision integer not null check (source_revision > 0),
  fact_sha256 text not null check (fact_sha256 ~ '^[0-9a-f]{64}$'),
  created_at timestamptz not null default pg_catalog.now(),
  primary key (event_id, ordinal),
  foreign key (event_id, company_id)
    references investments.economic_events(event_id, company_id)
    on delete restrict,
  unique (event_id, source_capability, source_record_id, source_revision)
);

create table investments.cash_settlements (
  settlement_id uuid primary key,
  event_id uuid not null unique,
  company_id uuid not null references public.companies(id) on delete cascade,
  income_year integer not null check (income_year between 2000 and 2100),
  settlement_date date not null,
  amount numeric(38, 12) not null check (amount > 0),
  source_capability text not null check (source_capability = 'BANKING'),
  source_record_id uuid not null,
  source_revision integer not null check (source_revision > 0),
  fact_sha256 text not null check (fact_sha256 ~ '^[0-9a-f]{64}$'),
  idempotency_key text not null check (
    nullif(pg_catalog.btrim(idempotency_key), '') is not null
    and pg_catalog.length(idempotency_key) <= 200
  ),
  request_fingerprint text not null check (request_fingerprint ~ '^[0-9a-f]{64}$'),
  evidence_mode text not null check (
    evidence_mode in ('linked_sources', 'manual_fallback')
  ),
  evidence_reference text not null check (
    nullif(pg_catalog.btrim(evidence_reference), '') is not null
    and pg_catalog.length(evidence_reference) <= 500
  ),
  owner_attested boolean not null,
  evidence_digest text not null check (evidence_digest ~ '^[0-9a-f]{64}$'),
  settlement_accounting_entry_id uuid not null unique,
  created_by uuid not null references auth.users(id) on delete restrict,
  created_at timestamptz not null default pg_catalog.now(),
  foreign key (event_id, company_id)
    references investments.economic_events(event_id, company_id)
    on delete restrict,
  unique (created_by, company_id, idempotency_key),
  unique (created_by, company_id, request_fingerprint),
  check (
    (evidence_mode = 'linked_sources' and not owner_attested)
    or (evidence_mode = 'manual_fallback' and owner_attested)
  ),
  check (extract(year from settlement_date)::integer = income_year)
);

create table investments.position_classifications (
  position_id uuid not null,
  company_id uuid not null references public.companies(id) on delete cascade,
  income_year integer not null check (income_year = 2026),
  accounting_classification text not null check (accounting_classification in (
    'subsidiary', 'associate', 'other_long_term',
    'current_listed_share', 'current_fund'
  )),
  purpose_reference text not null check (
    nullif(pg_catalog.btrim(purpose_reference), '') is not null
  ),
  source_capability text not null check (source_capability = 'DOCUMENTS'),
  source_record_id uuid not null,
  source_revision integer not null check (source_revision > 0),
  fact_sha256 text not null check (fact_sha256 ~ '^[0-9a-f]{64}$'),
  created_by uuid not null references auth.users(id) on delete restrict,
  created_at timestamptz not null default pg_catalog.now(),
  primary key (position_id, income_year),
  foreign key (company_id, income_year)
    references investments.company_year_policies(company_id, income_year)
    on delete restrict,
  foreign key (position_id, company_id)
    references investments.positions(id, company_id)
    on delete restrict,
  unique (position_id, income_year, company_id)
);

create table investments.year_end_measurements (
  measurement_id uuid primary key,
  company_id uuid not null references public.companies(id) on delete cascade,
  income_year integer not null check (income_year = 2026),
  position_id uuid not null,
  as_of date not null,
  policy_version text not null check (policy_version = 'domestic_2026_v2'),
  measurement_rule text not null check (measurement_rule in (
    'lower_of_cost_and_fair_value', 'cost_with_evidenced_impairment'
  )),
  quantity numeric(38, 12) not null check (quantity >= 0),
  source_book_cost numeric(38, 12) not null check (source_book_cost >= 0),
  pre_measurement_book_value numeric(38, 12) not null check (
    pre_measurement_book_value >= 0
  ),
  observed_or_recoverable_value numeric(38, 12) not null check (
    observed_or_recoverable_value >= 0
  ),
  impairment_amount numeric(38, 12) not null check (impairment_amount >= 0),
  reversal_amount numeric(38, 12) not null check (reversal_amount >= 0),
  closing_book_value numeric(38, 12) not null check (closing_book_value >= 0),
  tax_basis numeric(38, 12) not null check (tax_basis >= 0),
  tax_value numeric(38, 12) not null check (tax_value >= 0),
  evidence_digest text not null check (evidence_digest ~ '^[0-9a-f]{64}$'),
  calculation_id text not null check (calculation_id ~ '^[0-9a-f]{64}$'),
  accounting_entry_id uuid unique,
  created_by uuid not null references auth.users(id) on delete restrict,
  created_at timestamptz not null default pg_catalog.now(),
  constraint year_end_measurements_measurement_company_unique
    unique (measurement_id, company_id),
  foreign key (company_id, income_year)
    references investments.company_year_policies(company_id, income_year)
    on delete restrict,
  foreign key (position_id, company_id)
    references investments.positions(id, company_id)
    on delete restrict,
  foreign key (position_id, income_year, company_id)
    references investments.position_classifications(position_id, income_year, company_id)
    on delete restrict,
  unique (position_id, income_year),
  check (as_of = pg_catalog.make_date(income_year, 12, 31)),
  check (not (impairment_amount > 0 and reversal_amount > 0)),
  check (
    closing_book_value = pre_measurement_book_value
      - impairment_amount + reversal_amount
  )
);

create table investments.measurement_sources (
  measurement_id uuid not null,
  company_id uuid not null references public.companies(id) on delete cascade,
  ordinal integer not null check (ordinal > 0),
  role text not null check (role in (
    'holdings_statement', 'market_price', 'valuation', 'tax_value',
    'classification_policy'
  )),
  source_capability text not null check (source_capability = 'DOCUMENTS'),
  source_record_id uuid not null,
  source_revision integer not null check (source_revision > 0),
  fact_sha256 text not null check (fact_sha256 ~ '^[0-9a-f]{64}$'),
  created_at timestamptz not null default pg_catalog.now(),
  primary key (measurement_id, ordinal),
  foreign key (measurement_id, company_id)
    references investments.year_end_measurements(measurement_id, company_id)
    on delete restrict,
  unique (measurement_id, source_record_id, source_revision)
);

create index investments_economic_events_company_year_idx
  on investments.economic_events(company_id, income_year, recognition_date, event_id);
create index investments_event_sources_company_idx
  on investments.event_sources(company_id, event_id, ordinal);
create index investments_cash_settlements_company_year_idx
  on investments.cash_settlements(company_id, income_year, settlement_date, settlement_id);
create index investments_position_classifications_company_year_idx
  on investments.position_classifications(company_id, income_year, position_id);
create index investments_year_end_measurements_company_year_idx
  on investments.year_end_measurements(company_id, income_year, position_id);
create index investments_measurement_sources_company_idx
  on investments.measurement_sources(company_id, measurement_id, ordinal);

alter table investments.company_year_policies enable row level security;
alter table investments.company_year_policies force row level security;
alter table investments.economic_events enable row level security;
alter table investments.economic_events force row level security;
alter table investments.event_sources enable row level security;
alter table investments.event_sources force row level security;
alter table investments.cash_settlements enable row level security;
alter table investments.cash_settlements force row level security;
alter table investments.position_classifications enable row level security;
alter table investments.position_classifications force row level security;
alter table investments.year_end_measurements enable row level security;
alter table investments.year_end_measurements force row level security;
alter table investments.measurement_sources enable row level security;
alter table investments.measurement_sources force row level security;

create policy investments_company_year_policies_member_select
on investments.company_year_policies for select to investments_executor, investments_store_owner
using (public.company_access_is_accepted_member_v1(company_id));
create policy investments_economic_events_member_select
on investments.economic_events for select to investments_executor, investments_store_owner
using (public.company_access_is_accepted_member_v1(company_id));
create policy investments_event_sources_member_select
on investments.event_sources for select to investments_executor, investments_store_owner
using (public.company_access_is_accepted_member_v1(company_id));
create policy investments_cash_settlements_member_select
on investments.cash_settlements for select to investments_executor, investments_store_owner
using (public.company_access_is_accepted_member_v1(company_id));
create policy investments_position_classifications_member_select
on investments.position_classifications for select to investments_executor, investments_store_owner
using (public.company_access_is_accepted_member_v1(company_id));
create policy investments_year_end_measurements_member_select
on investments.year_end_measurements for select to investments_executor, investments_store_owner
using (public.company_access_is_accepted_member_v1(company_id));
create policy investments_measurement_sources_member_select
on investments.measurement_sources for select to investments_executor, investments_store_owner
using (public.company_access_is_accepted_member_v1(company_id));

create policy investments_company_year_policies_owner_insert
on investments.company_year_policies for insert to investments_store_owner
with check (
  created_by = public.company_access_auth_uid_v1()
  and public.company_access_is_accepted_owner_v1(company_id)
);
create policy investments_economic_events_owner_insert
on investments.economic_events for insert to investments_store_owner
with check (
  created_by = public.company_access_auth_uid_v1()
  and public.company_access_is_accepted_owner_v1(company_id)
);
create policy investments_event_sources_owner_insert
on investments.event_sources for insert to investments_store_owner
with check (public.company_access_is_accepted_owner_v1(company_id));
create policy investments_cash_settlements_owner_insert
on investments.cash_settlements for insert to investments_store_owner
with check (
  created_by = public.company_access_auth_uid_v1()
  and public.company_access_is_accepted_owner_v1(company_id)
);
create policy investments_position_classifications_owner_insert
on investments.position_classifications for insert to investments_store_owner
with check (
  created_by = public.company_access_auth_uid_v1()
  and public.company_access_is_accepted_owner_v1(company_id)
);
create policy investments_year_end_measurements_owner_insert
on investments.year_end_measurements for insert to investments_store_owner
with check (
  created_by = public.company_access_auth_uid_v1()
  and public.company_access_is_accepted_owner_v1(company_id)
);
create policy investments_measurement_sources_owner_insert
on investments.measurement_sources for insert to investments_store_owner
with check (public.company_access_is_accepted_owner_v1(company_id));

alter table investments.company_year_policies owner to investments_store_owner;
alter table investments.economic_events owner to investments_store_owner;
alter table investments.event_sources owner to investments_store_owner;
alter table investments.cash_settlements owner to investments_store_owner;
alter table investments.position_classifications owner to investments_store_owner;
alter table investments.year_end_measurements owner to investments_store_owner;
alter table investments.measurement_sources owner to investments_store_owner;

revoke all on investments.company_year_policies,
  investments.economic_events,
  investments.event_sources,
  investments.cash_settlements,
  investments.position_classifications,
  investments.year_end_measurements,
  investments.measurement_sources
from public, anon, authenticated, service_role;
grant select on investments.company_year_policies,
  investments.economic_events,
  investments.event_sources,
  investments.cash_settlements,
  investments.position_classifications,
  investments.year_end_measurements,
  investments.measurement_sources
to investments_executor;

do $membership_revoke$
begin
  execute pg_catalog.format(
    'revoke investments_store_owner from %I',
    current_user
  );
end
$membership_revoke$;

commit;
