-- Issue #188: linked ordinary NOK bank-loan disbursements and payments.
-- Python owns account selection and journal translation. These wrappers persist
-- the derived entries and enforce loan identity, chronology, and principal roll-forward.

create table if not exists ledger.bank_loan_anchors (
  company_id uuid not null references public.companies(id) on delete restrict,
  loan_reference_id text not null check (
    pg_catalog.btrim(loan_reference_id) <> ''
    and pg_catalog.length(loan_reference_id) <= 255
  ),
  disbursement_entry_id uuid not null unique,
  disbursement_income_year integer not null check (
    disbursement_income_year between 2000 and 2100
  ),
  disbursement_event_date date not null,
  principal_disbursed numeric(18, 2) not null check (principal_disbursed > 0),
  recorded_at timestamptz not null default pg_catalog.statement_timestamp(),
  primary key (company_id, loan_reference_id),
  foreign key (disbursement_entry_id, company_id, disbursement_income_year)
    references ledger.entries(id, company_id, income_year) on delete restrict,
  check (
    extract(year from disbursement_event_date)::integer
      = disbursement_income_year
  )
);

create table if not exists ledger.bank_loan_payment_allocations (
  payment_entry_id uuid primary key,
  company_id uuid not null references public.companies(id) on delete restrict,
  loan_reference_id text not null,
  payment_income_year integer not null check (
    payment_income_year between 2000 and 2100
  ),
  payment_event_date date not null,
  principal_paid numeric(18, 2) not null check (principal_paid >= 0),
  interest_paid numeric(18, 2) not null check (interest_paid >= 0),
  fee_paid numeric(18, 2) not null check (fee_paid >= 0),
  recorded_at timestamptz not null default pg_catalog.statement_timestamp(),
  foreign key (company_id, loan_reference_id)
    references ledger.bank_loan_anchors(company_id, loan_reference_id)
    on delete restrict,
  foreign key (payment_entry_id, company_id, payment_income_year)
    references ledger.entries(id, company_id, income_year) on delete restrict,
  check (
    extract(year from payment_event_date)::integer = payment_income_year
    and principal_paid + interest_paid + fee_paid > 0
  )
);

alter table ledger.bank_loan_anchors enable row level security;
alter table ledger.bank_loan_anchors force row level security;
alter table ledger.bank_loan_payment_allocations enable row level security;
alter table ledger.bank_loan_payment_allocations force row level security;

drop policy if exists "ledger store reads bank loan anchors"
  on ledger.bank_loan_anchors;
create policy "ledger store reads bank loan anchors"
on ledger.bank_loan_anchors for select to ledger_store_owner
using (public.company_access_is_accepted_member_v1(company_id));

drop policy if exists "ledger store records bank loan anchors"
  on ledger.bank_loan_anchors;
create policy "ledger store records bank loan anchors"
on ledger.bank_loan_anchors for insert to ledger_store_owner
with check (
  public.company_access_is_accepted_owner_v1(company_id)
  and public.company_access_company_year_allows_consequential_v1(
    company_id, disbursement_income_year
  )
);

drop policy if exists "ledger store reads bank loan payment allocations"
  on ledger.bank_loan_payment_allocations;
create policy "ledger store reads bank loan payment allocations"
on ledger.bank_loan_payment_allocations for select to ledger_store_owner
using (public.company_access_is_accepted_member_v1(company_id));

drop policy if exists "ledger store records bank loan payment allocations"
  on ledger.bank_loan_payment_allocations;
create policy "ledger store records bank loan payment allocations"
on ledger.bank_loan_payment_allocations for insert to ledger_store_owner
with check (
  public.company_access_is_accepted_owner_v1(company_id)
  and public.company_access_company_year_allows_consequential_v1(
    company_id, payment_income_year
  )
);

create or replace function ledger.record_bank_loan_disbursement_v1(
  p_idempotency_key text,
  p_company_id uuid,
  p_income_year integer,
  p_loan_reference_id text,
  p_principal numeric,
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
    or p_principal is null
    or p_principal <= 0
    or pg_catalog.round(p_principal, 2) is distinct from p_principal
    or not ledger.entry_lines_are_valid_v1(p_lines, false)
  then
    raise exception 'ledger_bank_loan_event_invalid';
  end if;
  select coalesce(pg_catalog.sum((item ->> 'debit')::numeric), 0)
  into v_journal_debit
  from pg_catalog.jsonb_array_elements(
    ledger.normalize_lines_v1(p_lines)
  ) line(item);
  if v_journal_debit is distinct from p_principal then
    raise exception 'ledger_bank_loan_event_invalid';
  end if;

  select * into strict v_post
  from ledger.post_supported_entry_v1(
    p_idempotency_key, p_company_id, p_income_year, 'BANK_LOAN',
    p_memo, p_lines, p_source_capability, p_source_record_id,
    p_correlation_id, p_verified_subject, p_event_date, p_rule_version,
    p_sources
  );

  perform pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended(
    'ledger:bank-loan:v1:' || p_company_id::text || ':'
      || pg_catalog.btrim(p_loan_reference_id),
    0
  ));

  if v_post.replayed then
    if not exists (
      select 1 from ledger.bank_loan_anchors anchor
      where anchor.company_id = p_company_id
        and anchor.loan_reference_id = pg_catalog.btrim(p_loan_reference_id)
        and anchor.disbursement_entry_id = v_post.ledger_entry_id
        and anchor.disbursement_income_year = p_income_year
        and anchor.disbursement_event_date = p_event_date
        and anchor.principal_disbursed = p_principal
    ) then
      raise exception 'ledger_idempotency_key_reused';
    end if;
  else
    if exists (
      select 1 from ledger.bank_loan_anchors anchor
      where anchor.company_id = p_company_id
        and anchor.loan_reference_id = pg_catalog.btrim(p_loan_reference_id)
    ) then
      raise exception 'ledger_bank_loan_already_exists';
    end if;
    insert into ledger.bank_loan_anchors (
      company_id, loan_reference_id, disbursement_entry_id,
      disbursement_income_year, disbursement_event_date, principal_disbursed
    ) values (
      p_company_id, pg_catalog.btrim(p_loan_reference_id), v_post.ledger_entry_id,
      p_income_year, p_event_date, p_principal
    );
  end if;

  return query select
    v_post.ledger_entry_id, v_post.company_id, v_post.income_year,
    v_post.entry_kind, v_post.posted_at, v_post.replayed;
end;
$function$;

create or replace function ledger.record_bank_loan_payment_v1(
  p_idempotency_key text,
  p_company_id uuid,
  p_income_year integer,
  p_loan_reference_id text,
  p_principal numeric,
  p_interest numeric,
  p_fee numeric,
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
  v_anchor ledger.bank_loan_anchors%rowtype;
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
  then
    raise exception 'ledger_bank_loan_event_invalid';
  end if;
  select coalesce(pg_catalog.sum((item ->> 'debit')::numeric), 0)
  into v_journal_debit
  from pg_catalog.jsonb_array_elements(
    ledger.normalize_lines_v1(p_lines)
  ) line(item);
  if v_journal_debit is distinct from p_principal + p_interest + p_fee then
    raise exception 'ledger_bank_loan_event_invalid';
  end if;

  select * into strict v_post
  from ledger.post_supported_entry_v1(
    p_idempotency_key, p_company_id, p_income_year, 'BANK_LOAN',
    p_memo, p_lines, p_source_capability, p_source_record_id,
    p_correlation_id, p_verified_subject, p_event_date, p_rule_version,
    p_sources
  );

  perform pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended(
    'ledger:bank-loan:v1:' || p_company_id::text || ':'
      || pg_catalog.btrim(p_loan_reference_id),
    0
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
    ) then
      raise exception 'ledger_idempotency_key_reused';
    end if;
  else
    select anchor.* into v_anchor
    from ledger.bank_loan_anchors anchor
    where anchor.company_id = p_company_id
      and anchor.loan_reference_id = pg_catalog.btrim(p_loan_reference_id);
    if not found then
      raise exception 'ledger_opening_loan_anchor_missing';
    end if;
    if p_event_date < v_anchor.disbursement_event_date then
      raise exception 'ledger_bank_loan_event_invalid';
    end if;
    select coalesce(pg_catalog.sum(allocation.principal_paid), 0)
    into v_principal_paid
    from ledger.bank_loan_payment_allocations allocation
    where allocation.company_id = p_company_id
      and allocation.loan_reference_id = pg_catalog.btrim(p_loan_reference_id);
    if v_principal_paid + p_principal > v_anchor.principal_disbursed then
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

  return query select
    v_post.ledger_entry_id, v_post.company_id, v_post.income_year,
    v_post.entry_kind, v_post.posted_at, v_post.replayed;
end;
$function$;

revoke all on ledger.bank_loan_anchors,
  ledger.bank_loan_payment_allocations
from public, anon, authenticated, ledger_executor, ledger_workflow_executor;
grant select, insert on ledger.bank_loan_anchors,
  ledger.bank_loan_payment_allocations
to ledger_store_owner;

revoke all on function ledger.record_bank_loan_disbursement_v1(
  text, uuid, integer, text, numeric, text, jsonb, text, text, text,
  text, date, text, jsonb
) from public, anon, authenticated;
revoke all on function ledger.record_bank_loan_payment_v1(
  text, uuid, integer, text, numeric, numeric, numeric, text, jsonb,
  text, text, text, text, date, text, jsonb
) from public, anon, authenticated;
grant execute on function ledger.record_bank_loan_disbursement_v1(
  text, uuid, integer, text, numeric, text, jsonb, text, text, text,
  text, date, text, jsonb
) to ledger_executor;
grant execute on function ledger.record_bank_loan_payment_v1(
  text, uuid, integer, text, numeric, numeric, numeric, text, jsonb,
  text, text, text, text, date, text, jsonb
) to ledger_executor;

alter table ledger.bank_loan_anchors owner to ledger_store_owner;
alter table ledger.bank_loan_payment_allocations owner to ledger_store_owner;
alter function ledger.record_bank_loan_disbursement_v1(
  text, uuid, integer, text, numeric, text, jsonb, text, text, text,
  text, date, text, jsonb
) owner to ledger_store_owner;
alter function ledger.record_bank_loan_payment_v1(
  text, uuid, integer, text, numeric, numeric, numeric, text, jsonb,
  text, text, text, text, date, text, jsonb
) owner to ledger_store_owner;

drop trigger if exists ledger_bank_loan_anchors_immutable
  on ledger.bank_loan_anchors;
create trigger ledger_bank_loan_anchors_immutable
before update or delete on ledger.bank_loan_anchors
for each row execute function backend_system.prevent_ledger_technical_mutation();

drop trigger if exists ledger_bank_loan_payment_allocations_immutable
  on ledger.bank_loan_payment_allocations;
create trigger ledger_bank_loan_payment_allocations_immutable
before update or delete on ledger.bank_loan_payment_allocations
for each row execute function backend_system.prevent_ledger_technical_mutation();
