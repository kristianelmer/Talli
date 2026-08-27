-- Issue #188: one complete, typed and evidenced Jan-1 opening position.
-- Python selects canonical accounts and lines. This coordinator atomically
-- persists the single opening journal, semantic components and their sources.

begin;

do $ledger_opening_position_migration_authority$
begin
  execute pg_catalog.format('grant ledger_store_owner to %I', current_user);
  execute pg_catalog.format('grant create on schema ledger to %I', current_user);
  grant create on schema ledger to ledger_store_owner;
end
$ledger_opening_position_migration_authority$;

create table if not exists ledger.opening_position_rebuilds (
  opening_entry_id uuid primary key,
  company_id uuid not null references public.companies(id) on delete restrict,
  income_year integer not null check (income_year between 2000 and 2100),
  opening_date date not null,
  opening_mode text not null check (
    opening_mode in ('NEW_COMPANY', 'PRIOR_CLOSE_RECONSTRUCTION')
  ),
  components_digest text not null check (components_digest ~ '^[0-9a-f]{64}$'),
  correlation_id text not null check (correlation_id ~ '^[A-Za-z0-9._:-]{1,80}$'),
  recorded_by uuid not null references auth.users(id) on delete restrict,
  recorded_at timestamptz not null default pg_catalog.statement_timestamp(),
  unique (company_id, income_year),
  unique (opening_entry_id, company_id, income_year),
  foreign key (opening_entry_id, company_id, income_year)
    references ledger.entries(id, company_id, income_year) on delete restrict,
  check (opening_date = pg_catalog.make_date(income_year, 1, 1))
);

create table if not exists ledger.opening_position_components (
  opening_entry_id uuid not null,
  company_id uuid not null,
  income_year integer not null,
  ordinal integer not null check (ordinal >= 1),
  component_kind text not null check (component_kind in (
    'CLASSIFIED_BALANCE', 'BANK_LOAN', 'INVESTMENT',
    'CAPITAL_INCREASE', 'CAPITAL_REDUCTION',
    'DIVIDEND_RECEIVABLE', 'DIVIDEND_PAYABLE'
  )),
  category text not null check (category in (
    'SUBSIDIARY_LOAN_RECEIVABLE', 'GROUP_COMPANY_LOAN_RECEIVABLE',
    'CORPORATE_SHAREHOLDER_LOAN_RECEIVABLE',
    'BANK', 'RESTRICTED_BANK',
    'SUBSIDIARY_INVESTMENT', 'ASSOCIATE_INVESTMENT',
    'OTHER_LONG_TERM_INVESTMENT', 'CURRENT_LISTED_SHARE_INVESTMENT',
    'CURRENT_FUND_INVESTMENT', 'SUBSCRIPTION_RECEIVABLE',
    'DIVIDEND_RECEIVABLE', 'GROUP_CONTRIBUTION_RECEIVABLE', 'TAX_RECEIVABLE',
    'ACCRUED_INTEREST_RECEIVABLE', 'DEFERRED_TAX_ASSET',
    'REGISTERED_SHARE_CAPITAL', 'SHARE_PREMIUM',
    'UNREGISTERED_CAPITAL_INCREASE', 'UNREGISTERED_CAPITAL_REDUCTION',
    'OTHER_PAID_IN_EQUITY', 'RETAINED_EARNINGS', 'UNCOVERED_LOSS',
    'OTHER_EQUITY',
    'LONG_TERM_BANK_LOAN_PAYABLE', 'SHORT_TERM_BANK_LOAN_PAYABLE',
    'OWNER_LOAN_PAYABLE',
    'INTERCOMPANY_LOAN_PAYABLE', 'SUPPLIER_PAYABLE', 'CURRENT_TAX_PAYABLE',
    'DEFERRED_TAX_LIABILITY', 'ACCRUED_INTEREST_PAYABLE',
    'DIVIDEND_PAYABLE', 'GROUP_CONTRIBUTION_PAYABLE'
  )),
  reference_id text not null check (
    pg_catalog.btrim(reference_id) <> ''
    and pg_catalog.length(reference_id) <= 255
  ),
  lifecycle_phase text check (
    lifecycle_phase is null or (
      pg_catalog.btrim(lifecycle_phase) <> ''
      and pg_catalog.length(lifecycle_phase) <= 80
    )
  ),
  account text not null check (account ~ '^[0-9]{4}$'),
  amount_nok numeric(18, 2) not null check (amount_nok > 0),
  nominal_increase_nok numeric(18, 2),
  share_premium_nok numeric(18, 2),
  nominal_reduction_nok numeric(18, 2),
  balance_side text not null check (balance_side in ('DEBIT', 'CREDIT')),
  primary key (opening_entry_id, ordinal),
  unique (company_id, income_year, category, reference_id),
  unique (opening_entry_id, ordinal, company_id, income_year),
  foreign key (opening_entry_id, company_id, income_year)
    references ledger.opening_position_rebuilds(
      opening_entry_id, company_id, income_year
    )
    on delete restrict,
  check (
    (
      component_kind = 'CAPITAL_INCREASE'
      and nominal_increase_nok > 0
      and share_premium_nok >= 0
      and nominal_reduction_nok is null
    ) or (
      component_kind = 'CAPITAL_REDUCTION'
      and nominal_increase_nok is null
      and share_premium_nok is null
      and nominal_reduction_nok > 0
    ) or (
      component_kind not in ('CAPITAL_INCREASE', 'CAPITAL_REDUCTION')
      and nominal_increase_nok is null
      and share_premium_nok is null
      and nominal_reduction_nok is null
    )
  )
);

create unique index if not exists opening_position_components_bank_loan_reference_key
on ledger.opening_position_components (company_id, reference_id)
where category in (
  'LONG_TERM_BANK_LOAN_PAYABLE', 'SHORT_TERM_BANK_LOAN_PAYABLE'
);

create unique index if not exists opening_position_components_capital_increase_reference_key
on ledger.opening_position_components (company_id, reference_id)
where component_kind = 'CAPITAL_INCREASE'
  and category = 'UNREGISTERED_CAPITAL_INCREASE';

create unique index if not exists opening_position_components_capital_reduction_reference_key
on ledger.opening_position_components (company_id, reference_id)
where component_kind = 'CAPITAL_REDUCTION'
  and category = 'UNREGISTERED_CAPITAL_REDUCTION';

create unique index if not exists opening_position_components_dividend_reference_key
on ledger.opening_position_components (company_id, component_kind, reference_id)
where component_kind in ('DIVIDEND_RECEIVABLE', 'DIVIDEND_PAYABLE');

create table if not exists ledger.opening_position_component_sources (
  opening_entry_id uuid not null,
  component_ordinal integer not null,
  company_id uuid not null,
  income_year integer not null,
  source_ordinal integer not null check (source_ordinal >= 1),
  source_role text not null check (source_role in ('PRIMARY', 'CORROBORATING')),
  source_capability text not null check (source_capability in (
    'LEDGER', 'BANKING', 'INVESTMENTS', 'CORPORATE_GOVERNANCE',
    'COMPANY_TAX_FILING', 'SHAREHOLDER_REGISTER_FILING',
    'ANNUAL_ACCOUNTS_FILING', 'DOCUMENTS'
  )),
  source_record_id text not null check (
    pg_catalog.btrim(source_record_id) <> ''
    and pg_catalog.length(source_record_id) <= 255
  ),
  source_revision integer not null check (source_revision >= 1),
  fact_sha256 text not null check (fact_sha256 ~ '^[0-9a-f]{64}$'),
  primary key (opening_entry_id, component_ordinal, source_ordinal),
  unique (
    opening_entry_id, component_ordinal,
    source_capability, source_record_id, source_revision
  ),
  foreign key (
    opening_entry_id, component_ordinal, company_id, income_year
  ) references ledger.opening_position_components(
    opening_entry_id, ordinal, company_id, income_year
  )
    on delete restrict
);

create table if not exists ledger.opening_received_dividend_settlements (
  company_id uuid not null references public.companies(id) on delete restrict,
  decision_reference_id text not null check (
    pg_catalog.btrim(decision_reference_id) <> ''
    and pg_catalog.length(decision_reference_id) <= 255
  ),
  opening_entry_id uuid not null,
  opening_component_ordinal integer not null,
  opening_income_year integer not null check (
    opening_income_year between 2000 and 2100
  ),
  payment_entry_id uuid not null unique,
  payment_income_year integer not null check (
    payment_income_year between 2000 and 2100
  ),
  recorded_at timestamptz not null default pg_catalog.statement_timestamp(),
  primary key (company_id, decision_reference_id),
  foreign key (
    opening_entry_id, opening_component_ordinal, company_id,
    opening_income_year
  ) references ledger.opening_position_components(
    opening_entry_id, ordinal, company_id, income_year
  ) on delete restrict,
  foreign key (payment_entry_id, company_id, payment_income_year)
    references ledger.entries(id, company_id, income_year) on delete restrict,
  check (payment_income_year >= opening_income_year)
);

alter table ledger.opening_position_rebuilds enable row level security;
alter table ledger.opening_position_rebuilds force row level security;
alter table ledger.opening_position_components enable row level security;
alter table ledger.opening_position_components force row level security;
alter table ledger.opening_position_component_sources enable row level security;
alter table ledger.opening_position_component_sources force row level security;
alter table ledger.opening_received_dividend_settlements enable row level security;
alter table ledger.opening_received_dividend_settlements force row level security;

drop policy if exists "ledger store reads opening position rebuilds"
  on ledger.opening_position_rebuilds;
create policy "ledger store reads opening position rebuilds"
on ledger.opening_position_rebuilds for select to ledger_store_owner
using (public.company_access_is_accepted_member_v1(company_id));
drop policy if exists "ledger store records opening position rebuilds"
  on ledger.opening_position_rebuilds;
create policy "ledger store records opening position rebuilds"
on ledger.opening_position_rebuilds for insert to ledger_store_owner
with check (
  recorded_by = public.company_access_auth_uid_v1()
  and public.company_access_is_accepted_owner_v1(company_id)
  and public.company_access_company_year_allows_consequential_v1(
    company_id, income_year
  )
);
drop policy if exists "ledger store reads opening position components"
  on ledger.opening_position_components;
create policy "ledger store reads opening position components"
on ledger.opening_position_components for select to ledger_store_owner
using (public.company_access_is_accepted_member_v1(company_id));
drop policy if exists "ledger store records opening position components"
  on ledger.opening_position_components;
create policy "ledger store records opening position components"
on ledger.opening_position_components for insert to ledger_store_owner
with check (public.company_access_is_accepted_owner_v1(company_id));
drop policy if exists "ledger store reads opening position component sources"
  on ledger.opening_position_component_sources;
create policy "ledger store reads opening position component sources"
on ledger.opening_position_component_sources for select to ledger_store_owner
using (public.company_access_is_accepted_member_v1(company_id));
drop policy if exists "ledger store records opening position component sources"
  on ledger.opening_position_component_sources;
create policy "ledger store records opening position component sources"
on ledger.opening_position_component_sources for insert to ledger_store_owner
with check (public.company_access_is_accepted_owner_v1(company_id));
drop policy if exists "ledger store reads opening dividend settlements"
  on ledger.opening_received_dividend_settlements;
create policy "ledger store reads opening dividend settlements"
on ledger.opening_received_dividend_settlements for select to ledger_store_owner
using (public.company_access_is_accepted_member_v1(company_id));
drop policy if exists "ledger store records opening dividend settlements"
  on ledger.opening_received_dividend_settlements;
create policy "ledger store records opening dividend settlements"
on ledger.opening_received_dividend_settlements for insert to ledger_store_owner
with check (
  public.company_access_is_accepted_owner_v1(company_id)
  and public.company_access_company_year_allows_consequential_v1(
    company_id, payment_income_year
  )
);

-- Keep the supported-entry storage coordinator private. Public callers retain
-- the stable supported-entry name, but that wrapper rejects OPENING_BALANCE;
-- only this typed receiver may reach the private storage coordinator.
do $ledger_opening_private_supported_entry$
begin
  if pg_catalog.to_regprocedure(
    'ledger.post_supported_entry_storage_v1(text,uuid,integer,text,text,jsonb,text,text,text,text,date,text,jsonb)'
  ) is null then
    alter function ledger.post_supported_entry_v1(
      text, uuid, integer, text, text, jsonb, text, text, text, text,
      date, text, jsonb
    ) rename to post_supported_entry_storage_v1;
  end if;
end
$ledger_opening_private_supported_entry$;

create or replace function ledger.post_supported_entry_v1(
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
begin
  if pg_catalog.upper(coalesce(p_entry_kind, '')) = 'OPENING_BALANCE' then
    raise exception 'ledger_invalid_input';
  end if;
  return query select *
  from ledger.post_supported_entry_storage_v1(
    p_idempotency_key, p_company_id, p_income_year, p_entry_kind, p_memo,
    p_lines, p_source_capability, p_source_record_id, p_correlation_id,
    p_verified_subject, p_event_date, p_rule_version, p_sources
  );
end;
$function$;

create or replace function ledger.rebuild_company_year_opening_v1(
  p_idempotency_key text,
  p_company_id uuid,
  p_income_year integer,
  p_opening_date date,
  p_opening_mode text,
  p_memo text,
  p_lines jsonb,
  p_source_capability text,
  p_source_record_id text,
  p_correlation_id text,
  p_verified_subject text,
  p_sources jsonb,
  p_components jsonb
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
  v_post record;
  v_component_digest text;
  v_component_count integer;
  v_component jsonb;
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
    or p_opening_date is distinct from pg_catalog.make_date(p_income_year, 1, 1)
    or p_opening_mode not in ('NEW_COMPANY', 'PRIOR_CLOSE_RECONSTRUCTION')
    or pg_catalog.btrim(coalesce(p_source_capability, '')) = ''
    or pg_catalog.btrim(coalesce(p_source_record_id, '')) = ''
    or pg_catalog.jsonb_typeof(p_components) is distinct from 'array'
    or pg_catalog.jsonb_array_length(p_components) < 1
    or pg_catalog.jsonb_typeof(p_sources) is distinct from 'array'
    or pg_catalog.jsonb_array_length(p_sources) < 2
    or not ledger.entry_lines_are_valid_v1(p_lines, false)
    or pg_catalog.jsonb_array_length(p_lines)
      is distinct from pg_catalog.jsonb_array_length(p_components)
  then
    raise exception 'ledger_opening_balance_invalid';
  end if;

  if p_sources -> 0 ->> 'role' is distinct from 'PRIMARY'
    or p_sources -> 0 ->> 'capability' is distinct from p_source_capability
    or p_sources -> 0 ->> 'recordId' is distinct from p_source_record_id
  then
    raise exception 'ledger_opening_evidence_invalid';
  end if;

  for v_component in
    select item
    from pg_catalog.jsonb_array_elements(p_components) component(item)
  loop
    if coalesce(v_component ->> 'ordinal', '') !~ '^[1-9][0-9]*$'
      or v_component ->> 'componentKind' not in (
        'CLASSIFIED_BALANCE', 'BANK_LOAN', 'INVESTMENT',
        'CAPITAL_INCREASE', 'CAPITAL_REDUCTION',
        'DIVIDEND_RECEIVABLE', 'DIVIDEND_PAYABLE'
      )
      or pg_catalog.btrim(coalesce(v_component ->> 'category', '')) = ''
      or pg_catalog.btrim(coalesce(v_component ->> 'referenceId', '')) = ''
      or pg_catalog.length(v_component ->> 'referenceId') > 255
      or (
        v_component ->> 'lifecyclePhase' is not null
        and (
          pg_catalog.btrim(v_component ->> 'lifecyclePhase') = ''
          or pg_catalog.length(v_component ->> 'lifecyclePhase') > 80
        )
      )
      or coalesce(v_component ->> 'account', '') !~ '^[0-9]{4}$'
      or coalesce(v_component ->> 'amountNok', '')
        !~ '^[0-9]+([.][0-9]{1,2})?$'
      or (v_component ->> 'amountNok')::numeric <= 0
      or (
        v_component ->> 'componentKind' = 'CAPITAL_INCREASE'
        and (
          coalesce(v_component ->> 'nominalIncreaseNok', '')
            !~ '^[0-9]+([.][0-9]{1,2})?$'
          or (v_component ->> 'nominalIncreaseNok')::numeric <= 0
          or coalesce(v_component ->> 'sharePremiumNok', '')
            !~ '^[0-9]+([.][0-9]{1,2})?$'
          or (v_component ->> 'sharePremiumNok')::numeric < 0
          or v_component ->> 'nominalReductionNok' is not null
        )
      )
      or (
        v_component ->> 'componentKind' = 'CAPITAL_REDUCTION'
        and (
          coalesce(v_component ->> 'nominalReductionNok', '')
            !~ '^[0-9]+([.][0-9]{1,2})?$'
          or (v_component ->> 'nominalReductionNok')::numeric <= 0
          or v_component ->> 'nominalIncreaseNok' is not null
          or v_component ->> 'sharePremiumNok' is not null
        )
      )
      or (
        v_component ->> 'componentKind' not in (
          'CAPITAL_INCREASE', 'CAPITAL_REDUCTION'
        )
        and (
          v_component ->> 'nominalIncreaseNok' is not null
          or v_component ->> 'sharePremiumNok' is not null
          or v_component ->> 'nominalReductionNok' is not null
        )
      )
      or v_component ->> 'balanceSide' not in ('DEBIT', 'CREDIT')
      or pg_catalog.jsonb_typeof(v_component -> 'sources') is distinct from 'array'
      or pg_catalog.jsonb_array_length(v_component -> 'sources') < 2
      or v_component -> 'sources' -> 0 ->> 'role' is distinct from 'PRIMARY'
      or exists (
        select 1
        from pg_catalog.jsonb_array_elements(v_component -> 'sources')
          with ordinality source(item, ordinal)
        where (ordinal > 1 and item ->> 'role' is distinct from 'CORROBORATING')
          or pg_catalog.btrim(coalesce(item ->> 'capability', '')) = ''
          or pg_catalog.btrim(coalesce(item ->> 'recordId', '')) = ''
          or pg_catalog.length(item ->> 'recordId') > 255
          or coalesce(item ->> 'revision', '') !~ '^[1-9][0-9]*$'
          or coalesce(item ->> 'factSha256', '') !~ '^[0-9a-f]{64}$'
      )
    then
      raise exception 'ledger_opening_evidence_invalid';
    end if;
  end loop;

  select pg_catalog.count(*) into v_component_count
  from (
    select item ->> 'category', item ->> 'referenceId'
    from pg_catalog.jsonb_array_elements(p_components) component(item)
    group by item ->> 'category', item ->> 'referenceId'
  ) unique_components;
  if v_component_count <> pg_catalog.jsonb_array_length(p_components)
    or exists (
      select 1 from (
        select item,
          pg_catalog.row_number() over (
            order by item ->> 'category', item ->> 'referenceId'
          ) expected_ordinal
        from pg_catalog.jsonb_array_elements(p_components) component(item)
      ) ordered
      where (item ->> 'ordinal')::integer <> expected_ordinal
    )
    or exists (
      select 1
      from pg_catalog.jsonb_array_elements(p_components) component(item)
      group by (item ->> 'ordinal')::integer
      having pg_catalog.count(*) > 1
    )
  then
    raise exception 'ledger_opening_balance_invalid';
  end if;

  if exists (
    select 1
    from pg_catalog.jsonb_array_elements(p_components) component(item)
    cross join lateral pg_catalog.jsonb_array_elements(item -> 'sources')
      component_source(source_item)
    where not exists (
      select 1 from pg_catalog.jsonb_array_elements(p_sources) entry_source(entry_item)
      where entry_item ->> 'capability' = source_item ->> 'capability'
        and entry_item ->> 'recordId' = source_item ->> 'recordId'
        and entry_item ->> 'revision' = source_item ->> 'revision'
        and entry_item ->> 'factSha256' = source_item ->> 'factSha256'
    )
  ) then
    raise exception 'ledger_opening_evidence_invalid';
  end if;

  if exists (
    select 1
    from pg_catalog.jsonb_array_elements(p_components) component(item)
    join lateral (
      select line
      from pg_catalog.jsonb_array_elements(ledger.normalize_lines_v1(p_lines))
        with ordinality line_item(line, ordinal)
      where ordinal = (item ->> 'ordinal')::integer
    ) matched on true
    where matched.line ->> 'account' is distinct from item ->> 'account'
      or case item ->> 'balanceSide'
      when 'DEBIT' then
        (matched.line ->> 'debit')::numeric
          is distinct from (item ->> 'amountNok')::numeric
        or (matched.line ->> 'credit')::numeric <> 0
      when 'CREDIT' then
        (matched.line ->> 'credit')::numeric
          is distinct from (item ->> 'amountNok')::numeric
        or (matched.line ->> 'debit')::numeric <> 0
      else true
    end
  ) then
    raise exception 'ledger_opening_balance_invalid';
  end if;

  v_component_digest := pg_catalog.encode(
    extensions.digest(p_components::text, 'sha256'), 'hex'
  );

  select * into strict v_post
  from ledger.post_supported_entry_storage_v1(
    p_idempotency_key, p_company_id, p_income_year, 'OPENING_BALANCE',
    p_memo, p_lines, p_source_capability, p_source_record_id,
    p_correlation_id, p_verified_subject, p_opening_date,
    'ledger-supported-patterns-2026.1', p_sources
  );

  if v_post.replayed then
    if not exists (
      select 1 from ledger.opening_position_rebuilds rebuild
      where rebuild.opening_entry_id = v_post.ledger_entry_id
        and rebuild.company_id = p_company_id
        and rebuild.income_year = p_income_year
        and rebuild.opening_date = p_opening_date
        and rebuild.opening_mode = p_opening_mode
        and rebuild.components_digest = v_component_digest
        and rebuild.correlation_id = p_correlation_id
    ) then
      raise exception 'ledger_idempotency_key_reused';
    end if;
    return query select v_post.ledger_entry_id, v_post.company_id,
      v_post.income_year, v_post.entry_kind, v_post.posted_at, true;
    return;
  end if;

  for v_component in
    select item
    from pg_catalog.jsonb_array_elements(p_components) component(item)
    where item ->> 'category' in (
      'LONG_TERM_BANK_LOAN_PAYABLE', 'SHORT_TERM_BANK_LOAN_PAYABLE'
    )
    order by item ->> 'referenceId'
  loop
    perform pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended(
      'ledger:bank-loan:v1:' || p_company_id::text || ':'
        || pg_catalog.btrim(v_component ->> 'referenceId'), 0
    ));
    if exists (
      select 1 from ledger.bank_loan_anchors anchor
      where anchor.company_id = p_company_id
        and anchor.loan_reference_id = pg_catalog.btrim(
          v_component ->> 'referenceId'
        )
    ) then
      raise exception 'ledger_bank_loan_already_exists';
    end if;
  end loop;

  insert into ledger.opening_position_rebuilds (
    opening_entry_id, company_id, income_year, opening_date, opening_mode,
    components_digest, correlation_id, recorded_by, recorded_at
  ) values (
    v_post.ledger_entry_id, p_company_id, p_income_year, p_opening_date,
    p_opening_mode, v_component_digest, p_correlation_id, v_actor_id,
    v_post.posted_at
  );
  insert into ledger.opening_position_components (
    opening_entry_id, company_id, income_year, ordinal, component_kind,
    category, reference_id, lifecycle_phase, account, amount_nok,
    nominal_increase_nok, share_premium_nok, nominal_reduction_nok,
    balance_side
  )
  select v_post.ledger_entry_id, p_company_id, p_income_year,
    (item ->> 'ordinal')::integer, item ->> 'componentKind',
    item ->> 'category', pg_catalog.btrim(item ->> 'referenceId'),
    item ->> 'lifecyclePhase', item ->> 'account',
    (item ->> 'amountNok')::numeric,
    (item ->> 'nominalIncreaseNok')::numeric,
    (item ->> 'sharePremiumNok')::numeric,
    (item ->> 'nominalReductionNok')::numeric,
    item ->> 'balanceSide'
  from pg_catalog.jsonb_array_elements(p_components) component(item);
  insert into ledger.opening_position_component_sources (
    opening_entry_id, component_ordinal, company_id, income_year,
    source_ordinal, source_role, source_capability, source_record_id,
    source_revision, fact_sha256
  )
  select v_post.ledger_entry_id, (component.item ->> 'ordinal')::integer,
    p_company_id, p_income_year, source.ordinal::integer,
    source.item ->> 'role', source.item ->> 'capability',
    source.item ->> 'recordId', (source.item ->> 'revision')::integer,
    source.item ->> 'factSha256'
  from pg_catalog.jsonb_array_elements(p_components) component(item)
  cross join lateral pg_catalog.jsonb_array_elements(component.item -> 'sources')
    with ordinality source(item, ordinal);

  return query select v_post.ledger_entry_id, v_post.company_id,
    v_post.income_year, v_post.entry_kind, v_post.posted_at, false;
end;
$function$;

create or replace function ledger.cash_capital_increase_phase_basis_v1(
  p_company_id uuid,
  p_capital_increase_reference_id text,
  p_phase text
)
returns table (
  event_date date,
  nominal_increase numeric,
  share_premium numeric
)
language sql
stable
security definer
set search_path = ''
as $function$
  select phase_record.event_date, phase_record.nominal_increase,
    phase_record.share_premium
  from ledger.cash_capital_increase_phases phase_record
  where phase_record.company_id = p_company_id
    and phase_record.capital_increase_reference_id =
      pg_catalog.btrim(p_capital_increase_reference_id)
    and phase_record.phase = p_phase
  union all
  select rebuild.opening_date, component.nominal_increase_nok,
    component.share_premium_nok
  from ledger.opening_position_components component
  join ledger.opening_position_rebuilds rebuild
    on rebuild.opening_entry_id = component.opening_entry_id
  where component.company_id = p_company_id
    and component.component_kind = 'CAPITAL_INCREASE'
    and component.category = 'UNREGISTERED_CAPITAL_INCREASE'
    and component.reference_id = pg_catalog.btrim(
      p_capital_increase_reference_id
    )
    and (
      (p_phase = 'BINDING_SUBSCRIPTION' and component.lifecycle_phase in (
        'BINDING_SUBSCRIPTION', 'RESTRICTED_PAYMENT'
      ))
      or (
        p_phase = 'RESTRICTED_PAYMENT'
        and component.lifecycle_phase = 'RESTRICTED_PAYMENT'
      )
    );
$function$;

create or replace function ledger.loss_coverage_capital_reduction_basis_v1(
  p_company_id uuid,
  p_capital_reduction_reference_id text
)
returns table (event_date date, nominal_reduction numeric)
language sql
stable
security definer
set search_path = ''
as $function$
  select phase_record.event_date, phase_record.nominal_reduction
  from ledger.loss_coverage_capital_reduction_phases phase_record
  where phase_record.company_id = p_company_id
    and phase_record.capital_reduction_reference_id =
      pg_catalog.btrim(p_capital_reduction_reference_id)
    and phase_record.phase = 'DECIDED_NOT_REGISTERED'
  union all
  select rebuild.opening_date, component.nominal_reduction_nok
  from ledger.opening_position_components component
  join ledger.opening_position_rebuilds rebuild
    on rebuild.opening_entry_id = component.opening_entry_id
  where component.company_id = p_company_id
    and component.component_kind = 'CAPITAL_REDUCTION'
    and component.category = 'UNREGISTERED_CAPITAL_REDUCTION'
    and component.lifecycle_phase = 'DECIDED_NOT_REGISTERED'
    and component.reference_id = pg_catalog.btrim(
      p_capital_reduction_reference_id
    );
$function$;

create or replace function ledger.record_received_dividend_payment_by_reference_v1(
  p_idempotency_key text,
  p_company_id uuid,
  p_income_year integer,
  p_decision_reference_id text,
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
  v_post record;
  v_capabilities text[];
  v_opening_entry_id uuid;
  v_opening_component_ordinal integer;
  v_opening_income_year integer;
  v_opening_date date;
  v_decision_total numeric;
  v_payment_total numeric;
begin
  if pg_catalog.jsonb_typeof(p_sources) is distinct from 'array' then
    raise exception 'ledger_invalid_input';
  end if;
  select pg_catalog.array_agg(item ->> 'capability' order by item ->> 'capability')
  into v_capabilities
  from pg_catalog.jsonb_array_elements(p_sources) source(item);
  if pg_catalog.btrim(coalesce(p_decision_reference_id, '')) = ''
    or pg_catalog.length(p_decision_reference_id) > 255
    or p_source_capability is distinct from 'INVESTMENTS'
    or p_sources -> 0 ->> 'capability' is distinct from 'INVESTMENTS'
    or v_capabilities is distinct from array['BANKING', 'INVESTMENTS']::text[]
  then
    raise exception 'ledger_source_capability_mismatch';
  end if;

  select * into strict v_post
  from ledger.post_supported_entry_v1(
    p_idempotency_key, p_company_id, p_income_year, 'DIVIDEND_RECEIVED',
    p_memo, p_lines, p_source_capability, p_source_record_id,
    p_correlation_id, p_verified_subject, p_event_date, p_rule_version,
    p_sources
  );

  perform pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended(
    'ledger:received-dividend-reference:v1:' || p_company_id::text || ':'
      || pg_catalog.btrim(p_decision_reference_id), 0
  ));

  if v_post.replayed then
    if not exists (
      select 1 from ledger.opening_received_dividend_settlements settlement
      where settlement.company_id = p_company_id
        and settlement.decision_reference_id =
          pg_catalog.btrim(p_decision_reference_id)
        and settlement.payment_entry_id = v_post.ledger_entry_id
        and settlement.payment_income_year = p_income_year
    ) then
      raise exception 'ledger_idempotency_key_reused';
    end if;
  else
    select component.opening_entry_id, component.ordinal,
      component.income_year, rebuild.opening_date, component.amount_nok
    into v_opening_entry_id, v_opening_component_ordinal,
      v_opening_income_year, v_opening_date, v_decision_total
    from ledger.opening_position_components component
    join ledger.opening_position_rebuilds rebuild
      on rebuild.opening_entry_id = component.opening_entry_id
      and rebuild.company_id = component.company_id
      and rebuild.income_year = component.income_year
    where component.company_id = p_company_id
      and component.component_kind = 'DIVIDEND_RECEIVABLE'
      and component.category = 'DIVIDEND_RECEIVABLE'
      and component.reference_id = pg_catalog.btrim(p_decision_reference_id);
    if not found or p_event_date < v_opening_date then
      raise exception 'ledger_received_dividend_decision_invalid';
    end if;
    if exists (
      select 1 from ledger.opening_received_dividend_settlements settlement
      where settlement.company_id = p_company_id
        and settlement.decision_reference_id =
          pg_catalog.btrim(p_decision_reference_id)
    ) then
      raise exception 'ledger_received_dividend_already_settled';
    end if;
    select coalesce(pg_catalog.sum((line ->> 'debit')::numeric), 0)
    into v_payment_total
    from pg_catalog.jsonb_array_elements(
      ledger.normalize_lines_v1(p_lines)
    ) source(line);
    if v_decision_total <= 0
      or v_decision_total is distinct from v_payment_total
    then
      raise exception 'ledger_received_dividend_decision_invalid';
    end if;
    insert into ledger.opening_received_dividend_settlements (
      company_id, decision_reference_id, opening_entry_id,
      opening_component_ordinal, opening_income_year, payment_entry_id,
      payment_income_year
    ) values (
      p_company_id, pg_catalog.btrim(p_decision_reference_id),
      v_opening_entry_id, v_opening_component_ordinal,
      v_opening_income_year, v_post.ledger_entry_id, p_income_year
    );
  end if;

  return query select v_post.ledger_entry_id, v_post.company_id,
    v_post.income_year, v_post.entry_kind, v_post.posted_at, v_post.replayed;
end;
$function$;

alter table ledger.bank_loan_payment_allocations
  drop constraint if exists bank_loan_payment_allocations_company_id_loan_reference_id_fkey;

create or replace function ledger.bank_loan_principal_basis_v1(
  p_company_id uuid,
  p_loan_reference_id text
)
returns table (basis_date date, principal_basis numeric)
language sql
stable
security definer
set search_path = ''
as $function$
  select anchor.disbursement_event_date, anchor.principal_disbursed
  from ledger.bank_loan_anchors anchor
  where anchor.company_id = p_company_id
    and anchor.loan_reference_id = pg_catalog.btrim(p_loan_reference_id)
  union all
  select rebuild.opening_date, component.amount_nok
  from ledger.opening_position_components component
  join ledger.opening_position_rebuilds rebuild
    on rebuild.opening_entry_id = component.opening_entry_id
  where component.company_id = p_company_id
    and component.category in (
      'LONG_TERM_BANK_LOAN_PAYABLE', 'SHORT_TERM_BANK_LOAN_PAYABLE'
    )
    and component.reference_id = pg_catalog.btrim(p_loan_reference_id);
$function$;

create or replace function ledger.prevent_bank_loan_basis_collision_v1()
returns trigger
language plpgsql
security definer
set search_path = ''
as $function$
declare
  v_new jsonb := pg_catalog.to_jsonb(new);
begin
  if tg_table_name = 'bank_loan_anchors' and exists (
    select 1 from ledger.opening_position_components component
    where component.company_id = (v_new ->> 'company_id')::uuid
      and component.category in (
        'LONG_TERM_BANK_LOAN_PAYABLE', 'SHORT_TERM_BANK_LOAN_PAYABLE'
      )
      and component.reference_id = v_new ->> 'loan_reference_id'
  ) then
    raise exception 'ledger_bank_loan_already_exists';
  end if;
  if tg_table_name = 'opening_position_components'
    and v_new ->> 'category' in (
      'LONG_TERM_BANK_LOAN_PAYABLE', 'SHORT_TERM_BANK_LOAN_PAYABLE'
    )
    and exists (
      select 1 from ledger.bank_loan_anchors anchor
      where anchor.company_id = (v_new ->> 'company_id')::uuid
        and anchor.loan_reference_id = v_new ->> 'reference_id'
    )
  then
    raise exception 'ledger_bank_loan_already_exists';
  end if;
  return new;
end;
$function$;

create or replace function ledger.require_bank_loan_payment_basis_v1()
returns trigger
language plpgsql
security definer
set search_path = ''
as $function$
begin
  if not exists (
    select 1 from ledger.bank_loan_principal_basis_v1(
      new.company_id, new.loan_reference_id
    ) basis
    where new.payment_event_date >= basis.basis_date
  ) then
    raise exception 'ledger_opening_loan_anchor_missing';
  end if;
  return new;
end;
$function$;

drop trigger if exists ledger_bank_loan_basis_collision
  on ledger.bank_loan_anchors;
create trigger ledger_bank_loan_basis_collision
before insert on ledger.bank_loan_anchors
for each row execute function ledger.prevent_bank_loan_basis_collision_v1();
drop trigger if exists ledger_opening_bank_loan_basis_collision
  on ledger.opening_position_components;
create trigger ledger_opening_bank_loan_basis_collision
before insert on ledger.opening_position_components
for each row execute function ledger.prevent_bank_loan_basis_collision_v1();
drop trigger if exists ledger_bank_loan_payment_basis
  on ledger.bank_loan_payment_allocations;
create trigger ledger_bank_loan_payment_basis
before insert on ledger.bank_loan_payment_allocations
for each row execute function ledger.require_bank_loan_payment_basis_v1();

create or replace function ledger.record_bank_loan_payment_v1(
  p_idempotency_key text, p_company_id uuid, p_income_year integer,
  p_loan_reference_id text, p_principal numeric, p_interest numeric,
  p_fee numeric, p_memo text, p_lines jsonb, p_source_capability text,
  p_source_record_id text, p_correlation_id text, p_verified_subject text,
  p_event_date date, p_rule_version text, p_sources jsonb
)
returns table (
  ledger_entry_id uuid, company_id uuid, income_year integer,
  entry_kind text, posted_at timestamptz, replayed boolean
)
language plpgsql security definer set search_path = ''
as $function$
declare
  v_post record;
  v_capabilities text[];
  v_anchor record;
  v_principal_paid numeric;
  v_journal_debit numeric;
begin
  if pg_catalog.jsonb_typeof(p_sources) is distinct from 'array' then
    raise exception 'ledger_invalid_input';
  end if;
  select pg_catalog.array_agg(item ->> 'capability' order by item ->> 'capability')
  into v_capabilities
  from pg_catalog.jsonb_array_elements(p_sources) source(item);
  if p_source_capability is distinct from 'BANKING'
    or p_sources -> 0 ->> 'capability' is distinct from 'BANKING'
    or v_capabilities is distinct from array['BANKING', 'DOCUMENTS']::text[]
    or pg_catalog.btrim(coalesce(p_loan_reference_id, '')) = ''
    or pg_catalog.length(p_loan_reference_id) > 255
    or p_principal is null or p_interest is null or p_fee is null
    or p_principal < 0 or p_interest < 0 or p_fee < 0
    or p_principal + p_interest + p_fee <= 0
    or pg_catalog.round(p_principal, 2) is distinct from p_principal
    or pg_catalog.round(p_interest, 2) is distinct from p_interest
    or pg_catalog.round(p_fee, 2) is distinct from p_fee
    or not ledger.entry_lines_are_valid_v1(p_lines, false)
  then raise exception 'ledger_bank_loan_event_invalid'; end if;
  select coalesce(pg_catalog.sum((item ->> 'debit')::numeric), 0)
  into v_journal_debit
  from pg_catalog.jsonb_array_elements(ledger.normalize_lines_v1(p_lines)) line(item);
  if v_journal_debit is distinct from p_principal + p_interest + p_fee then
    raise exception 'ledger_bank_loan_event_invalid';
  end if;
  select * into strict v_post from ledger.post_supported_entry_v1(
    p_idempotency_key, p_company_id, p_income_year, 'BANK_LOAN', p_memo,
    p_lines, p_source_capability, p_source_record_id, p_correlation_id,
    p_verified_subject, p_event_date, p_rule_version, p_sources
  );
  perform pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended(
    'ledger:bank-loan:v1:' || p_company_id::text || ':'
      || pg_catalog.btrim(p_loan_reference_id), 0
  ));
  if v_post.replayed then
    if not exists (
      select 1 from ledger.bank_loan_payment_allocations allocation
      where allocation.payment_entry_id = v_post.ledger_entry_id
        and allocation.company_id = p_company_id
        and allocation.loan_reference_id = pg_catalog.btrim(p_loan_reference_id)
        and allocation.payment_income_year = p_income_year
        and allocation.payment_event_date = p_event_date
        and allocation.principal_paid = p_principal
        and allocation.interest_paid = p_interest
        and allocation.fee_paid = p_fee
    ) then raise exception 'ledger_idempotency_key_reused'; end if;
  else
    select basis.* into v_anchor from ledger.bank_loan_principal_basis_v1(
      p_company_id, p_loan_reference_id
    ) basis;
    if not found then raise exception 'ledger_opening_loan_anchor_missing'; end if;
    if p_event_date < v_anchor.basis_date then
      raise exception 'ledger_bank_loan_event_invalid';
    end if;
    select coalesce(pg_catalog.sum(allocation.principal_paid), 0)
    into v_principal_paid
    from ledger.bank_loan_payment_allocations allocation
    where allocation.company_id = p_company_id
      and allocation.loan_reference_id = pg_catalog.btrim(p_loan_reference_id);
    if v_principal_paid + p_principal > v_anchor.principal_basis then
      raise exception 'ledger_bank_loan_principal_exceeded';
    end if;
    insert into ledger.bank_loan_payment_allocations (
      payment_entry_id, company_id, loan_reference_id, payment_income_year,
      payment_event_date, principal_paid, interest_paid, fee_paid
    ) values (
      v_post.ledger_entry_id, p_company_id,
      pg_catalog.btrim(p_loan_reference_id), p_income_year, p_event_date,
      p_principal, p_interest, p_fee
    );
  end if;
  return query select v_post.ledger_entry_id, v_post.company_id,
    v_post.income_year, v_post.entry_kind, v_post.posted_at, v_post.replayed;
end;
$function$;

create or replace function ledger.company_year_ledger_state_digest_v1(
  p_company_id uuid, p_income_year integer
)
returns text language sql stable security definer set search_path = ''
as $function$
  select pg_catalog.encode(extensions.digest(
    pg_catalog.jsonb_build_object(
      'entries', coalesce((select pg_catalog.jsonb_agg(pg_catalog.to_jsonb(e) order by e.id)
        from ledger.entries e where e.company_id = p_company_id and e.income_year = p_income_year), '[]'::jsonb),
      'contexts', coalesce((select pg_catalog.jsonb_agg(pg_catalog.to_jsonb(c) order by c.entry_id)
        from ledger.entry_contexts c where c.company_id = p_company_id and c.income_year = p_income_year), '[]'::jsonb),
      'sources', coalesce((select pg_catalog.jsonb_agg(pg_catalog.to_jsonb(s) order by s.entry_id, s.ordinal)
        from ledger.entry_sources s where s.company_id = p_company_id and s.income_year = p_income_year), '[]'::jsonb),
      'corrections', coalesce((select pg_catalog.jsonb_agg(pg_catalog.to_jsonb(c) order by c.original_entry_id)
        from ledger.entry_corrections c where c.company_id = p_company_id and c.income_year = p_income_year), '[]'::jsonb),
      'openingRebuilds', coalesce((select pg_catalog.jsonb_agg(pg_catalog.to_jsonb(r) order by r.opening_entry_id)
        from ledger.opening_position_rebuilds r where r.company_id = p_company_id and r.income_year = p_income_year), '[]'::jsonb),
      'openingComponents', coalesce((select pg_catalog.jsonb_agg(pg_catalog.to_jsonb(c) order by c.opening_entry_id, c.ordinal)
        from ledger.opening_position_components c where c.company_id = p_company_id and c.income_year = p_income_year), '[]'::jsonb),
      'openingSources', coalesce((select pg_catalog.jsonb_agg(pg_catalog.to_jsonb(s) order by s.opening_entry_id, s.component_ordinal, s.source_ordinal)
        from ledger.opening_position_component_sources s where s.company_id = p_company_id and s.income_year = p_income_year), '[]'::jsonb),
      'bankLoanAnchors', coalesce((select pg_catalog.jsonb_agg(pg_catalog.to_jsonb(a) order by a.loan_reference_id)
        from ledger.bank_loan_anchors a where a.company_id = p_company_id and a.disbursement_income_year = p_income_year), '[]'::jsonb),
      'bankLoanPayments', coalesce((select pg_catalog.jsonb_agg(pg_catalog.to_jsonb(a) order by a.payment_entry_id)
        from ledger.bank_loan_payment_allocations a where a.company_id = p_company_id and a.payment_income_year = p_income_year), '[]'::jsonb),
      'receivedDividendDecisions', coalesce((select pg_catalog.jsonb_agg(pg_catalog.to_jsonb(d) order by d.decision_entry_id)
        from ledger.received_dividend_decisions d where d.company_id = p_company_id and d.income_year = p_income_year), '[]'::jsonb),
      'receivedDividendSettlements', coalesce((select pg_catalog.jsonb_agg(pg_catalog.to_jsonb(s) order by s.payment_entry_id)
        from ledger.received_dividend_settlements s where s.company_id = p_company_id and s.payment_income_year = p_income_year), '[]'::jsonb),
      'openingReceivedDividendSettlements', coalesce((select pg_catalog.jsonb_agg(pg_catalog.to_jsonb(s) order by s.payment_entry_id)
        from ledger.opening_received_dividend_settlements s where s.company_id = p_company_id and s.payment_income_year = p_income_year), '[]'::jsonb),
      'capitalIncreasePhases', coalesce((select pg_catalog.jsonb_agg(pg_catalog.to_jsonb(p) order by p.entry_id)
        from ledger.cash_capital_increase_phases p where p.company_id = p_company_id and p.income_year = p_income_year), '[]'::jsonb),
      'capitalReductionPhases', coalesce((select pg_catalog.jsonb_agg(pg_catalog.to_jsonb(p) order by p.entry_id)
        from ledger.loss_coverage_capital_reduction_phases p where p.company_id = p_company_id and p.income_year = p_income_year), '[]'::jsonb)
    )::text, 'sha256'
  ), 'hex');
$function$;

revoke all on ledger.opening_position_rebuilds,
  ledger.opening_position_components, ledger.opening_position_component_sources,
  ledger.opening_received_dividend_settlements
from public, anon, authenticated, ledger_executor, ledger_workflow_executor;
grant select, insert on ledger.opening_position_rebuilds,
  ledger.opening_position_components, ledger.opening_position_component_sources,
  ledger.opening_received_dividend_settlements
to ledger_store_owner;
revoke all on function ledger.rebuild_company_year_opening_v1(
  text, uuid, integer, date, text, text, jsonb,
  text, text, text, text, jsonb, jsonb
) from public, anon, authenticated, service_role, ledger_workflow_executor;
grant execute on function ledger.rebuild_company_year_opening_v1(
  text, uuid, integer, date, text, text, jsonb,
  text, text, text, text, jsonb, jsonb
) to ledger_executor, ledger_workflow_executor;
revoke all on function ledger.post_supported_entry_storage_v1(
  text, uuid, integer, text, text, jsonb, text, text, text, text,
  date, text, jsonb
) from public, anon, authenticated, service_role, ledger_executor,
  ledger_workflow_executor;
revoke all on function ledger.post_supported_entry_v1(
  text, uuid, integer, text, text, jsonb, text, text, text, text,
  date, text, jsonb
) from public, anon, authenticated, service_role, ledger_workflow_executor;
grant execute on function ledger.post_supported_entry_v1(
  text, uuid, integer, text, text, jsonb, text, text, text, text,
  date, text, jsonb
) to ledger_executor;
revoke all on function ledger.record_received_dividend_payment_by_reference_v1(
  text, uuid, integer, text, text, jsonb, text, text, text, text,
  date, text, jsonb
) from public, anon, authenticated, service_role, ledger_workflow_executor;
grant execute on function ledger.record_received_dividend_payment_by_reference_v1(
  text, uuid, integer, text, text, jsonb, text, text, text, text,
  date, text, jsonb
) to ledger_executor;
revoke all on function ledger.bank_loan_principal_basis_v1(uuid, text)
from public, anon, authenticated, service_role, ledger_executor,
  ledger_workflow_executor;
revoke all on function ledger.prevent_bank_loan_basis_collision_v1()
from public, anon, authenticated, service_role, ledger_executor,
  ledger_workflow_executor;
revoke all on function ledger.require_bank_loan_payment_basis_v1()
from public, anon, authenticated, service_role, ledger_executor,
  ledger_workflow_executor;
revoke all on function ledger.company_year_ledger_state_digest_v1(uuid, integer)
from public, anon, authenticated, service_role, ledger_executor,
  ledger_workflow_executor;

alter table ledger.opening_position_rebuilds owner to ledger_store_owner;
alter table ledger.opening_position_components owner to ledger_store_owner;
alter table ledger.opening_position_component_sources owner to ledger_store_owner;
alter table ledger.opening_received_dividend_settlements owner to ledger_store_owner;
alter function ledger.rebuild_company_year_opening_v1(
  text, uuid, integer, date, text, text, jsonb,
  text, text, text, text, jsonb, jsonb
) owner to ledger_store_owner;
alter function ledger.post_supported_entry_storage_v1(
  text, uuid, integer, text, text, jsonb, text, text, text, text,
  date, text, jsonb
) owner to ledger_store_owner;
alter function ledger.post_supported_entry_v1(
  text, uuid, integer, text, text, jsonb, text, text, text, text,
  date, text, jsonb
) owner to ledger_store_owner;
alter function ledger.record_received_dividend_payment_by_reference_v1(
  text, uuid, integer, text, text, jsonb, text, text, text, text,
  date, text, jsonb
) owner to ledger_store_owner;
alter function ledger.bank_loan_principal_basis_v1(uuid, text)
  owner to ledger_store_owner;
alter function ledger.prevent_bank_loan_basis_collision_v1()
  owner to ledger_store_owner;
alter function ledger.require_bank_loan_payment_basis_v1()
  owner to ledger_store_owner;
alter function ledger.company_year_ledger_state_digest_v1(uuid, integer)
  owner to ledger_store_owner;

drop trigger if exists ledger_opening_position_rebuilds_immutable
  on ledger.opening_position_rebuilds;
create trigger ledger_opening_position_rebuilds_immutable
before update or delete on ledger.opening_position_rebuilds
for each row execute function backend_system.prevent_ledger_technical_mutation();
drop trigger if exists ledger_opening_position_components_immutable
  on ledger.opening_position_components;
create trigger ledger_opening_position_components_immutable
before update or delete on ledger.opening_position_components
for each row execute function backend_system.prevent_ledger_technical_mutation();
drop trigger if exists ledger_opening_position_component_sources_immutable
  on ledger.opening_position_component_sources;
create trigger ledger_opening_position_component_sources_immutable
before update or delete on ledger.opening_position_component_sources
for each row execute function backend_system.prevent_ledger_technical_mutation();
drop trigger if exists ledger_opening_received_dividend_settlements_immutable
  on ledger.opening_received_dividend_settlements;
create trigger ledger_opening_received_dividend_settlements_immutable
before update or delete on ledger.opening_received_dividend_settlements
for each row execute function backend_system.prevent_ledger_technical_mutation();

do $ledger_opening_position_migration_authority_revoke$
begin
  execute pg_catalog.format('revoke create on schema ledger from %I', current_user);
  revoke create on schema ledger from ledger_store_owner;
  execute pg_catalog.format('revoke ledger_store_owner from %I', current_user);
end
$ledger_opening_position_migration_authority_revoke$;

commit;
