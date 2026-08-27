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
  components_digest text not null check (components_digest ~ '^[0-9a-f]{64}$'),
  correlation_id text not null check (correlation_id ~ '^[A-Za-z0-9._:-]{1,80}$'),
  recorded_by uuid not null references auth.users(id) on delete restrict,
  recorded_at timestamptz not null default pg_catalog.statement_timestamp(),
  unique (company_id, income_year),
  foreign key (opening_entry_id, company_id, income_year)
    references ledger.entries(id, company_id, income_year) on delete restrict,
  check (opening_date = pg_catalog.make_date(income_year, 1, 1))
);

create table if not exists ledger.opening_position_components (
  opening_entry_id uuid not null,
  company_id uuid not null,
  income_year integer not null,
  ordinal integer not null check (ordinal between 1 and 49),
  category text not null check (category in (
    'SUBSIDIARY_LOAN_RECEIVABLE', 'GROUP_COMPANY_LOAN_RECEIVABLE',
    'CORPORATE_SHAREHOLDER_LOAN_RECEIVABLE',
    'BANK', 'RESTRICTED_BANK', 'INVESTMENT', 'SUBSCRIPTION_RECEIVABLE',
    'DIVIDEND_RECEIVABLE', 'GROUP_CONTRIBUTION_RECEIVABLE', 'TAX_RECEIVABLE',
    'REGISTERED_SHARE_CAPITAL', 'SHARE_PREMIUM',
    'UNREGISTERED_CAPITAL_INCREASE', 'UNREGISTERED_CAPITAL_REDUCTION',
    'OTHER_PAID_IN_EQUITY', 'RETAINED_EARNINGS', 'UNCOVERED_LOSS',
    'OTHER_EQUITY',
    'BANK_LOAN_PAYABLE', 'OWNER_LOAN_PAYABLE',
    'INTERCOMPANY_LOAN_PAYABLE', 'SUPPLIER_PAYABLE', 'CURRENT_TAX_PAYABLE',
    'DIVIDEND_PAYABLE', 'GROUP_CONTRIBUTION_PAYABLE'
  )),
  reference_id text not null check (
    pg_catalog.btrim(reference_id) <> ''
    and pg_catalog.length(reference_id) <= 255
  ),
  amount_nok numeric(18, 2) not null check (amount_nok > 0),
  balance_side text not null check (balance_side in ('DEBIT', 'CREDIT')),
  primary key (opening_entry_id, ordinal),
  unique (company_id, income_year, category, reference_id),
  foreign key (opening_entry_id)
    references ledger.opening_position_rebuilds(opening_entry_id)
    on delete restrict
);

create table if not exists ledger.opening_position_component_sources (
  opening_entry_id uuid not null,
  component_ordinal integer not null,
  company_id uuid not null,
  income_year integer not null,
  source_ordinal integer not null check (source_ordinal in (1, 2)),
  source_role text not null check (source_role in ('PRIMARY', 'CORROBORATING')),
  source_capability text not null check (source_capability in (
    'LEDGER', 'BANKING', 'INVESTMENTS', 'CORPORATE_GOVERNANCE',
    'COMPANY_TAX_FILING', 'SHAREHOLDER_REGISTER_FILING', 'DOCUMENTS'
  )),
  source_record_id text not null check (
    pg_catalog.btrim(source_record_id) <> ''
    and pg_catalog.length(source_record_id) <= 255
  ),
  source_revision integer not null check (source_revision >= 1),
  fact_sha256 text not null check (fact_sha256 ~ '^[0-9a-f]{64}$'),
  primary key (opening_entry_id, component_ordinal, source_ordinal),
  unique (
    company_id, income_year, source_capability, source_record_id, source_revision
  ),
  foreign key (opening_entry_id, component_ordinal)
    references ledger.opening_position_components(opening_entry_id, ordinal)
    on delete restrict
);

alter table ledger.opening_position_rebuilds enable row level security;
alter table ledger.opening_position_rebuilds force row level security;
alter table ledger.opening_position_components enable row level security;
alter table ledger.opening_position_components force row level security;
alter table ledger.opening_position_component_sources enable row level security;
alter table ledger.opening_position_component_sources force row level security;

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

create or replace function ledger.rebuild_company_year_opening_v1(
  p_idempotency_key text,
  p_company_id uuid,
  p_income_year integer,
  p_opening_date date,
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
  v_expected_primary text;
  v_expected_corroborating text;
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
    or p_source_capability is distinct from 'LEDGER'
    or pg_catalog.btrim(coalesce(p_source_record_id, '')) = ''
    or pg_catalog.jsonb_typeof(p_components) is distinct from 'array'
    or pg_catalog.jsonb_array_length(p_components) not between 2 and 49
    or pg_catalog.jsonb_typeof(p_sources) is distinct from 'array'
    or pg_catalog.jsonb_array_length(p_sources)
      is distinct from 1 + (2 * pg_catalog.jsonb_array_length(p_components))
    or not ledger.entry_lines_are_valid_v1(p_lines, false)
    or pg_catalog.jsonb_array_length(p_lines)
      is distinct from pg_catalog.jsonb_array_length(p_components)
  then
    raise exception 'ledger_opening_balance_invalid';
  end if;

  if p_sources -> 0 ->> 'role' is distinct from 'PRIMARY'
    or p_sources -> 0 ->> 'capability' is distinct from 'LEDGER'
    or p_sources -> 0 ->> 'recordId' is distinct from p_source_record_id
  then
    raise exception 'ledger_opening_evidence_invalid';
  end if;

  for v_component in
    select item
    from pg_catalog.jsonb_array_elements(p_components) component(item)
  loop
    v_expected_primary := case v_component ->> 'category'
      when 'SUBSIDIARY_LOAN_RECEIVABLE' then 'CORPORATE_GOVERNANCE'
      when 'GROUP_COMPANY_LOAN_RECEIVABLE' then 'CORPORATE_GOVERNANCE'
      when 'CORPORATE_SHAREHOLDER_LOAN_RECEIVABLE' then 'CORPORATE_GOVERNANCE'
      when 'BANK' then 'BANKING'
      when 'RESTRICTED_BANK' then 'BANKING'
      when 'INVESTMENT' then 'INVESTMENTS'
      when 'SUBSCRIPTION_RECEIVABLE' then 'CORPORATE_GOVERNANCE'
      when 'DIVIDEND_RECEIVABLE' then 'INVESTMENTS'
      when 'GROUP_CONTRIBUTION_RECEIVABLE' then 'CORPORATE_GOVERNANCE'
      when 'TAX_RECEIVABLE' then 'COMPANY_TAX_FILING'
      when 'REGISTERED_SHARE_CAPITAL' then 'SHAREHOLDER_REGISTER_FILING'
      when 'SHARE_PREMIUM' then 'SHAREHOLDER_REGISTER_FILING'
      when 'UNREGISTERED_CAPITAL_INCREASE' then 'CORPORATE_GOVERNANCE'
      when 'UNREGISTERED_CAPITAL_REDUCTION' then 'CORPORATE_GOVERNANCE'
      when 'OTHER_PAID_IN_EQUITY' then 'CORPORATE_GOVERNANCE'
      when 'RETAINED_EARNINGS' then 'COMPANY_TAX_FILING'
      when 'UNCOVERED_LOSS' then 'COMPANY_TAX_FILING'
      when 'OTHER_EQUITY' then 'COMPANY_TAX_FILING'
      when 'BANK_LOAN_PAYABLE' then 'BANKING'
      when 'OWNER_LOAN_PAYABLE' then 'CORPORATE_GOVERNANCE'
      when 'INTERCOMPANY_LOAN_PAYABLE' then 'CORPORATE_GOVERNANCE'
      when 'SUPPLIER_PAYABLE' then 'DOCUMENTS'
      when 'CURRENT_TAX_PAYABLE' then 'COMPANY_TAX_FILING'
      when 'DIVIDEND_PAYABLE' then 'CORPORATE_GOVERNANCE'
      when 'GROUP_CONTRIBUTION_PAYABLE' then 'CORPORATE_GOVERNANCE'
      else null
    end;
    v_expected_corroborating := case
      when v_component ->> 'category' = 'SUPPLIER_PAYABLE' then 'LEDGER'
      else 'DOCUMENTS'
    end;
    if v_expected_primary is null
      or coalesce(v_component ->> 'ordinal', '') !~ '^[1-9][0-9]*$'
      or (v_component ->> 'ordinal')::integer not between 1 and 49
      or pg_catalog.btrim(coalesce(v_component ->> 'referenceId', '')) = ''
      or pg_catalog.length(v_component ->> 'referenceId') > 255
      or coalesce(v_component ->> 'amountNok', '')
        !~ '^[0-9]+([.][0-9]{1,2})?$'
      or (v_component ->> 'amountNok')::numeric <= 0
      or (v_component ->> 'balanceSide') is distinct from (case
        when v_component ->> 'category' in (
          'BANK', 'RESTRICTED_BANK', 'INVESTMENT',
          'SUBSIDIARY_LOAN_RECEIVABLE', 'GROUP_COMPANY_LOAN_RECEIVABLE',
          'CORPORATE_SHAREHOLDER_LOAN_RECEIVABLE',
          'SUBSCRIPTION_RECEIVABLE', 'DIVIDEND_RECEIVABLE',
          'GROUP_CONTRIBUTION_RECEIVABLE', 'TAX_RECEIVABLE',
          'UNREGISTERED_CAPITAL_REDUCTION', 'UNCOVERED_LOSS'
        ) then 'DEBIT' else 'CREDIT' end)
      or pg_catalog.jsonb_typeof(v_component -> 'sources') is distinct from 'array'
      or pg_catalog.jsonb_array_length(v_component -> 'sources') <> 2
      or v_component -> 'sources' -> 0 ->> 'role' is distinct from 'PRIMARY'
      or v_component -> 'sources' -> 0 ->> 'capability'
        is distinct from v_expected_primary
      or v_component -> 'sources' -> 1 ->> 'role'
        is distinct from 'CORROBORATING'
      or v_component -> 'sources' -> 1 ->> 'capability'
        is distinct from v_expected_corroborating
      or exists (
        select 1
        from pg_catalog.jsonb_array_elements(v_component -> 'sources') source(item)
        where pg_catalog.btrim(coalesce(item ->> 'recordId', '')) = ''
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
    or exists (
      select 1
      from pg_catalog.jsonb_array_elements(p_components) component(item),
        lateral pg_catalog.jsonb_array_elements(item -> 'sources') source(source_item)
      where source_item ->> 'capability' = p_sources -> 0 ->> 'capability'
        and source_item ->> 'recordId' = p_sources -> 0 ->> 'recordId'
        and source_item ->> 'revision' = p_sources -> 0 ->> 'revision'
    )
    or exists (
      select 1
      from pg_catalog.jsonb_array_elements(p_components) component(item),
        lateral pg_catalog.jsonb_array_elements(item -> 'sources') source(source_item)
      group by source_item ->> 'capability', source_item ->> 'recordId',
        source_item ->> 'revision'
      having pg_catalog.count(*) > 1
    )
  then
    raise exception 'ledger_opening_source_overlap';
  end if;

  if exists (
    select 1
    from pg_catalog.jsonb_array_elements(p_components) component(item)
    cross join lateral pg_catalog.jsonb_array_elements(item -> 'sources')
      component_source(source_item)
    where not exists (
      select 1 from pg_catalog.jsonb_array_elements(p_sources) entry_source(entry_item)
      where entry_item ->> 'role' = 'CORROBORATING'
        and entry_item ->> 'capability' = source_item ->> 'capability'
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
    where case item ->> 'balanceSide'
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
  from ledger.post_supported_entry_v1(
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
    where item ->> 'category' = 'BANK_LOAN_PAYABLE'
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
    opening_entry_id, company_id, income_year, opening_date,
    components_digest, correlation_id, recorded_by, recorded_at
  ) values (
    v_post.ledger_entry_id, p_company_id, p_income_year, p_opening_date,
    v_component_digest, p_correlation_id, v_actor_id, v_post.posted_at
  );
  insert into ledger.opening_position_components (
    opening_entry_id, company_id, income_year, ordinal, category,
    reference_id, amount_nok, balance_side
  )
  select v_post.ledger_entry_id, p_company_id, p_income_year,
    (item ->> 'ordinal')::integer, item ->> 'category',
    pg_catalog.btrim(item ->> 'referenceId'), (item ->> 'amountNok')::numeric,
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
    and component.category = 'BANK_LOAN_PAYABLE'
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
      and component.category = 'BANK_LOAN_PAYABLE'
      and component.reference_id = v_new ->> 'loan_reference_id'
  ) then
    raise exception 'ledger_bank_loan_already_exists';
  end if;
  if tg_table_name = 'opening_position_components'
    and v_new ->> 'category' = 'BANK_LOAN_PAYABLE'
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
      'capitalIncreasePhases', coalesce((select pg_catalog.jsonb_agg(pg_catalog.to_jsonb(p) order by p.entry_id)
        from ledger.cash_capital_increase_phases p where p.company_id = p_company_id and p.income_year = p_income_year), '[]'::jsonb),
      'capitalReductionPhases', coalesce((select pg_catalog.jsonb_agg(pg_catalog.to_jsonb(p) order by p.entry_id)
        from ledger.loss_coverage_capital_reduction_phases p where p.company_id = p_company_id and p.income_year = p_income_year), '[]'::jsonb)
    )::text, 'sha256'
  ), 'hex');
$function$;

revoke all on ledger.opening_position_rebuilds,
  ledger.opening_position_components, ledger.opening_position_component_sources
from public, anon, authenticated, ledger_executor, ledger_workflow_executor;
grant select, insert on ledger.opening_position_rebuilds,
  ledger.opening_position_components, ledger.opening_position_component_sources
to ledger_store_owner;
revoke all on function ledger.rebuild_company_year_opening_v1(
  text, uuid, integer, date, text, jsonb, text, text, text, text, jsonb, jsonb
) from public, anon, authenticated, service_role, ledger_workflow_executor;
grant execute on function ledger.rebuild_company_year_opening_v1(
  text, uuid, integer, date, text, jsonb, text, text, text, text, jsonb, jsonb
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
alter function ledger.rebuild_company_year_opening_v1(
  text, uuid, integer, date, text, jsonb, text, text, text, text, jsonb, jsonb
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

do $ledger_opening_position_migration_authority_revoke$
begin
  execute pg_catalog.format('revoke create on schema ledger from %I', current_user);
  revoke create on schema ledger from ledger_store_owner;
  execute pg_catalog.format('revoke ledger_store_owner from %I', current_user);
end
$ledger_opening_position_migration_authority_revoke$;

commit;
