-- Issue #188: phase-linked ordinary NOK cash-capital-increase receiver.
-- Python owns accounting translation. This additive coordinator persists only
-- approved phase identity, amount continuity, chronology, and provenance.

begin;

do $ledger_cash_capital_increase_migration_authority$
begin
  execute pg_catalog.format('grant ledger_store_owner to %I', current_user);
  execute pg_catalog.format('grant create on schema ledger to %I', current_user);
  grant create on schema ledger to ledger_store_owner;
end
$ledger_cash_capital_increase_migration_authority$;

create table if not exists ledger.cash_capital_increase_phases (
  company_id uuid not null references public.companies(id) on delete restrict,
  capital_increase_reference_id text not null check (
    pg_catalog.btrim(capital_increase_reference_id) <> ''
    and pg_catalog.length(capital_increase_reference_id) <= 255
  ),
  phase text not null check (phase in (
    'BINDING_SUBSCRIPTION', 'RESTRICTED_PAYMENT', 'REGISTERED'
  )),
  entry_id uuid not null unique,
  income_year integer not null check (income_year between 2000 and 2100),
  event_date date not null,
  nominal_increase numeric(18, 2) not null check (nominal_increase > 0),
  share_premium numeric(18, 2) not null check (share_premium >= 0),
  recorded_at timestamptz not null default pg_catalog.statement_timestamp(),
  primary key (company_id, capital_increase_reference_id, phase),
  foreign key (entry_id, company_id, income_year)
    references ledger.entries(id, company_id, income_year) on delete restrict,
  check (extract(year from event_date)::integer = income_year)
);

alter table ledger.cash_capital_increase_phases enable row level security;
alter table ledger.cash_capital_increase_phases force row level security;

drop policy if exists "ledger store reads cash capital increase phases"
  on ledger.cash_capital_increase_phases;
create policy "ledger store reads cash capital increase phases"
on ledger.cash_capital_increase_phases for select to ledger_store_owner
using (public.company_access_is_accepted_member_v1(company_id));

drop policy if exists "ledger store records cash capital increase phases"
  on ledger.cash_capital_increase_phases;
create policy "ledger store records cash capital increase phases"
on ledger.cash_capital_increase_phases for insert to ledger_store_owner
with check (
  public.company_access_is_accepted_owner_v1(company_id)
  and public.company_access_company_year_allows_consequential_v1(
    company_id, income_year
  )
);

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
    and phase_record.phase = p_phase;
$function$;

create or replace function ledger.record_cash_capital_increase_subscription_v1(
  p_idempotency_key text,
  p_company_id uuid,
  p_income_year integer,
  p_capital_increase_reference_id text,
  p_nominal_increase numeric,
  p_share_premium numeric,
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
  v_total numeric;
  v_journal_debit numeric;
begin
  if pg_catalog.jsonb_typeof(p_sources) is distinct from 'array' then
    raise exception 'ledger_cash_capital_increase_phase_invalid';
  end if;
  select pg_catalog.array_agg(item ->> 'capability' order by item ->> 'capability')
  into v_capabilities
  from pg_catalog.jsonb_array_elements(p_sources) source(item);
  if p_source_capability is distinct from 'CORPORATE_GOVERNANCE'
    or p_sources -> 0 ->> 'capability' is distinct from 'CORPORATE_GOVERNANCE'
    or v_capabilities is distinct from array[
      'CORPORATE_GOVERNANCE', 'DOCUMENTS'
    ]::text[]
    or pg_catalog.btrim(coalesce(p_capital_increase_reference_id, '')) = ''
    or pg_catalog.length(p_capital_increase_reference_id) > 255
    or p_nominal_increase is null or p_share_premium is null
    or p_nominal_increase <= 0 or p_share_premium < 0
    or pg_catalog.round(p_nominal_increase, 2) is distinct from p_nominal_increase
    or pg_catalog.round(p_share_premium, 2) is distinct from p_share_premium
    or not ledger.entry_lines_are_valid_v1(p_lines, false)
  then
    raise exception 'ledger_cash_capital_increase_phase_invalid';
  end if;
  v_total := p_nominal_increase + p_share_premium;
  select coalesce(pg_catalog.sum((item ->> 'debit')::numeric), 0)
  into v_journal_debit
  from pg_catalog.jsonb_array_elements(
    ledger.normalize_lines_v1(p_lines)
  ) line(item);
  if v_journal_debit is distinct from v_total then
    raise exception 'ledger_cash_capital_increase_amount_mismatch';
  end if;

  select * into strict v_post
  from ledger.post_supported_entry_v1(
    p_idempotency_key, p_company_id, p_income_year, 'CAPITAL_INCREASE',
    p_memo, p_lines, p_source_capability, p_source_record_id,
    p_correlation_id, p_verified_subject, p_event_date, p_rule_version,
    p_sources
  );

  perform pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended(
    'ledger:cash-capital-increase:v1:' || p_company_id::text || ':'
      || pg_catalog.btrim(p_capital_increase_reference_id),
    0
  ));

  if v_post.replayed then
    if not exists (
      select 1 from ledger.cash_capital_increase_phases phase_record
      where phase_record.company_id = p_company_id
        and phase_record.capital_increase_reference_id =
          pg_catalog.btrim(p_capital_increase_reference_id)
        and phase_record.phase = 'BINDING_SUBSCRIPTION'
        and phase_record.entry_id = v_post.ledger_entry_id
        and phase_record.income_year = p_income_year
        and phase_record.event_date = p_event_date
        and phase_record.nominal_increase = p_nominal_increase
        and phase_record.share_premium = p_share_premium
    ) then
      raise exception 'ledger_idempotency_key_reused';
    end if;
  else
    if exists (
      select 1 from ledger.cash_capital_increase_phases phase_record
      where phase_record.company_id = p_company_id
        and phase_record.capital_increase_reference_id =
          pg_catalog.btrim(p_capital_increase_reference_id)
    ) or exists (
      select 1 from ledger.cash_capital_increase_phase_basis_v1(
        p_company_id, p_capital_increase_reference_id,
        'BINDING_SUBSCRIPTION'
      )
    ) then
      raise exception 'ledger_cash_capital_increase_phase_already_recorded';
    end if;
    insert into ledger.cash_capital_increase_phases (
      company_id, capital_increase_reference_id, phase, entry_id,
      income_year, event_date, nominal_increase, share_premium
    ) values (
      p_company_id, pg_catalog.btrim(p_capital_increase_reference_id),
      'BINDING_SUBSCRIPTION', v_post.ledger_entry_id, p_income_year,
      p_event_date, p_nominal_increase, p_share_premium
    );
  end if;

  return query select
    v_post.ledger_entry_id, v_post.company_id, v_post.income_year,
    v_post.entry_kind, v_post.posted_at, v_post.replayed;
end;
$function$;

create or replace function ledger.record_cash_capital_increase_restricted_payment_v1(
  p_idempotency_key text,
  p_company_id uuid,
  p_income_year integer,
  p_capital_increase_reference_id text,
  p_nominal_increase numeric,
  p_share_premium numeric,
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
  v_total numeric;
  v_journal_debit numeric;
  v_subscription record;
begin
  if pg_catalog.jsonb_typeof(p_sources) is distinct from 'array' then
    raise exception 'ledger_cash_capital_increase_phase_invalid';
  end if;
  select pg_catalog.array_agg(item ->> 'capability' order by item ->> 'capability')
  into v_capabilities
  from pg_catalog.jsonb_array_elements(p_sources) source(item);
  if p_source_capability is distinct from 'CORPORATE_GOVERNANCE'
    or p_sources -> 0 ->> 'capability' is distinct from 'CORPORATE_GOVERNANCE'
    or v_capabilities is distinct from array[
      'BANKING', 'CORPORATE_GOVERNANCE', 'DOCUMENTS'
    ]::text[]
    or pg_catalog.btrim(coalesce(p_capital_increase_reference_id, '')) = ''
    or pg_catalog.length(p_capital_increase_reference_id) > 255
    or p_nominal_increase is null or p_share_premium is null
    or p_nominal_increase <= 0 or p_share_premium < 0
    or pg_catalog.round(p_nominal_increase, 2) is distinct from p_nominal_increase
    or pg_catalog.round(p_share_premium, 2) is distinct from p_share_premium
    or not ledger.entry_lines_are_valid_v1(p_lines, false)
  then
    raise exception 'ledger_cash_capital_increase_phase_invalid';
  end if;
  v_total := p_nominal_increase + p_share_premium;
  select coalesce(pg_catalog.sum((item ->> 'debit')::numeric), 0)
  into v_journal_debit
  from pg_catalog.jsonb_array_elements(
    ledger.normalize_lines_v1(p_lines)
  ) line(item);
  if v_journal_debit is distinct from v_total then
    raise exception 'ledger_cash_capital_increase_amount_mismatch';
  end if;

  select * into strict v_post
  from ledger.post_supported_entry_v1(
    p_idempotency_key, p_company_id, p_income_year, 'CAPITAL_INCREASE',
    p_memo, p_lines, p_source_capability, p_source_record_id,
    p_correlation_id, p_verified_subject, p_event_date, p_rule_version,
    p_sources
  );

  perform pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended(
    'ledger:cash-capital-increase:v1:' || p_company_id::text || ':'
      || pg_catalog.btrim(p_capital_increase_reference_id),
    0
  ));

  if v_post.replayed then
    if not exists (
      select 1 from ledger.cash_capital_increase_phases phase_record
      where phase_record.company_id = p_company_id
        and phase_record.capital_increase_reference_id =
          pg_catalog.btrim(p_capital_increase_reference_id)
        and phase_record.phase = 'RESTRICTED_PAYMENT'
        and phase_record.entry_id = v_post.ledger_entry_id
        and phase_record.income_year = p_income_year
        and phase_record.event_date = p_event_date
        and phase_record.nominal_increase = p_nominal_increase
        and phase_record.share_premium = p_share_premium
    ) then
      raise exception 'ledger_idempotency_key_reused';
    end if;
  else
    select basis.* into v_subscription
    from ledger.cash_capital_increase_phase_basis_v1(
      p_company_id, p_capital_increase_reference_id, 'BINDING_SUBSCRIPTION'
    ) basis;
    if not found then
      raise exception 'ledger_opening_capital_increase_anchor_missing';
    end if;
    if v_subscription.nominal_increase is distinct from p_nominal_increase
      or v_subscription.share_premium is distinct from p_share_premium
    then
      raise exception 'ledger_cash_capital_increase_amount_mismatch';
    end if;
    if p_event_date < v_subscription.event_date then
      raise exception 'ledger_cash_capital_increase_phase_invalid';
    end if;
    if exists (
      select 1 from ledger.cash_capital_increase_phase_basis_v1(
        p_company_id, p_capital_increase_reference_id,
        'RESTRICTED_PAYMENT'
      )
    ) then
      raise exception 'ledger_cash_capital_increase_phase_already_recorded';
    end if;
    insert into ledger.cash_capital_increase_phases (
      company_id, capital_increase_reference_id, phase, entry_id,
      income_year, event_date, nominal_increase, share_premium
    ) values (
      p_company_id, pg_catalog.btrim(p_capital_increase_reference_id),
      'RESTRICTED_PAYMENT', v_post.ledger_entry_id, p_income_year,
      p_event_date, p_nominal_increase, p_share_premium
    );
  end if;

  return query select
    v_post.ledger_entry_id, v_post.company_id, v_post.income_year,
    v_post.entry_kind, v_post.posted_at, v_post.replayed;
end;
$function$;

create or replace function ledger.record_cash_capital_increase_registration_v1(
  p_idempotency_key text,
  p_company_id uuid,
  p_income_year integer,
  p_capital_increase_reference_id text,
  p_nominal_increase numeric,
  p_share_premium numeric,
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
  v_total numeric;
  v_journal_debit numeric;
  v_subscription record;
  v_payment record;
begin
  if pg_catalog.jsonb_typeof(p_sources) is distinct from 'array' then
    raise exception 'ledger_cash_capital_increase_phase_invalid';
  end if;
  select pg_catalog.array_agg(item ->> 'capability' order by item ->> 'capability')
  into v_capabilities
  from pg_catalog.jsonb_array_elements(p_sources) source(item);
  if p_source_capability is distinct from 'CORPORATE_GOVERNANCE'
    or p_sources -> 0 ->> 'capability' is distinct from 'CORPORATE_GOVERNANCE'
    or v_capabilities is distinct from array[
      'BANKING', 'CORPORATE_GOVERNANCE', 'DOCUMENTS',
      'SHAREHOLDER_REGISTER_FILING'
    ]::text[]
    or pg_catalog.btrim(coalesce(p_capital_increase_reference_id, '')) = ''
    or pg_catalog.length(p_capital_increase_reference_id) > 255
    or p_nominal_increase is null or p_share_premium is null
    or p_nominal_increase <= 0 or p_share_premium < 0
    or pg_catalog.round(p_nominal_increase, 2) is distinct from p_nominal_increase
    or pg_catalog.round(p_share_premium, 2) is distinct from p_share_premium
    or not ledger.entry_lines_are_valid_v1(p_lines, false)
  then
    raise exception 'ledger_cash_capital_increase_phase_invalid';
  end if;
  v_total := p_nominal_increase + p_share_premium;
  select coalesce(pg_catalog.sum((item ->> 'debit')::numeric), 0)
  into v_journal_debit
  from pg_catalog.jsonb_array_elements(
    ledger.normalize_lines_v1(p_lines)
  ) line(item);
  if v_journal_debit is distinct from v_total * 2 then
    raise exception 'ledger_cash_capital_increase_amount_mismatch';
  end if;

  select * into strict v_post
  from ledger.post_supported_entry_v1(
    p_idempotency_key, p_company_id, p_income_year, 'CAPITAL_INCREASE',
    p_memo, p_lines, p_source_capability, p_source_record_id,
    p_correlation_id, p_verified_subject, p_event_date, p_rule_version,
    p_sources
  );

  perform pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended(
    'ledger:cash-capital-increase:v1:' || p_company_id::text || ':'
      || pg_catalog.btrim(p_capital_increase_reference_id),
    0
  ));

  if v_post.replayed then
    if not exists (
      select 1 from ledger.cash_capital_increase_phases phase_record
      where phase_record.company_id = p_company_id
        and phase_record.capital_increase_reference_id =
          pg_catalog.btrim(p_capital_increase_reference_id)
        and phase_record.phase = 'REGISTERED'
        and phase_record.entry_id = v_post.ledger_entry_id
        and phase_record.income_year = p_income_year
        and phase_record.event_date = p_event_date
        and phase_record.nominal_increase = p_nominal_increase
        and phase_record.share_premium = p_share_premium
    ) then
      raise exception 'ledger_idempotency_key_reused';
    end if;
  else
    select basis.* into v_subscription
    from ledger.cash_capital_increase_phase_basis_v1(
      p_company_id, p_capital_increase_reference_id, 'BINDING_SUBSCRIPTION'
    ) basis;
    if not found then
      raise exception 'ledger_opening_capital_increase_anchor_missing';
    end if;
    select basis.* into v_payment
    from ledger.cash_capital_increase_phase_basis_v1(
      p_company_id, p_capital_increase_reference_id, 'RESTRICTED_PAYMENT'
    ) basis;
    if not found then
      raise exception 'ledger_cash_capital_increase_phase_missing';
    end if;
    if v_subscription.nominal_increase is distinct from p_nominal_increase
      or v_subscription.share_premium is distinct from p_share_premium
      or v_payment.nominal_increase is distinct from p_nominal_increase
      or v_payment.share_premium is distinct from p_share_premium
    then
      raise exception 'ledger_cash_capital_increase_amount_mismatch';
    end if;
    if p_event_date < v_payment.event_date then
      raise exception 'ledger_cash_capital_increase_phase_invalid';
    end if;
    if exists (
      select 1 from ledger.cash_capital_increase_phases phase_record
      where phase_record.company_id = p_company_id
        and phase_record.capital_increase_reference_id =
          pg_catalog.btrim(p_capital_increase_reference_id)
        and phase_record.phase = 'REGISTERED'
    ) then
      raise exception 'ledger_cash_capital_increase_phase_already_recorded';
    end if;
    insert into ledger.cash_capital_increase_phases (
      company_id, capital_increase_reference_id, phase, entry_id,
      income_year, event_date, nominal_increase, share_premium
    ) values (
      p_company_id, pg_catalog.btrim(p_capital_increase_reference_id),
      'REGISTERED', v_post.ledger_entry_id, p_income_year,
      p_event_date, p_nominal_increase, p_share_premium
    );
  end if;

  return query select
    v_post.ledger_entry_id, v_post.company_id, v_post.income_year,
    v_post.entry_kind, v_post.posted_at, v_post.replayed;
end;
$function$;

revoke all on ledger.cash_capital_increase_phases
from public, anon, authenticated, ledger_executor, ledger_workflow_executor;
grant select, insert on ledger.cash_capital_increase_phases
to ledger_store_owner;
revoke all on function ledger.cash_capital_increase_phase_basis_v1(
  uuid, text, text
) from public, anon, authenticated, service_role, ledger_executor,
  ledger_workflow_executor;

revoke all on function ledger.record_cash_capital_increase_subscription_v1(
  text, uuid, integer, text, numeric, numeric, text, jsonb, text, text,
  text, text, date, text, jsonb
) from public, anon, authenticated;
revoke all on function ledger.record_cash_capital_increase_restricted_payment_v1(
  text, uuid, integer, text, numeric, numeric, text, jsonb, text, text,
  text, text, date, text, jsonb
) from public, anon, authenticated;
revoke all on function ledger.record_cash_capital_increase_registration_v1(
  text, uuid, integer, text, numeric, numeric, text, jsonb, text, text,
  text, text, date, text, jsonb
) from public, anon, authenticated;

grant execute on function ledger.record_cash_capital_increase_subscription_v1(
  text, uuid, integer, text, numeric, numeric, text, jsonb, text, text,
  text, text, date, text, jsonb
) to ledger_executor;
grant execute on function ledger.record_cash_capital_increase_restricted_payment_v1(
  text, uuid, integer, text, numeric, numeric, text, jsonb, text, text,
  text, text, date, text, jsonb
) to ledger_executor;
grant execute on function ledger.record_cash_capital_increase_registration_v1(
  text, uuid, integer, text, numeric, numeric, text, jsonb, text, text,
  text, text, date, text, jsonb
) to ledger_executor;

alter table ledger.cash_capital_increase_phases owner to ledger_store_owner;
alter function ledger.cash_capital_increase_phase_basis_v1(uuid, text, text)
  owner to ledger_store_owner;
alter function ledger.record_cash_capital_increase_subscription_v1(
  text, uuid, integer, text, numeric, numeric, text, jsonb, text, text,
  text, text, date, text, jsonb
) owner to ledger_store_owner;
alter function ledger.record_cash_capital_increase_restricted_payment_v1(
  text, uuid, integer, text, numeric, numeric, text, jsonb, text, text,
  text, text, date, text, jsonb
) owner to ledger_store_owner;
alter function ledger.record_cash_capital_increase_registration_v1(
  text, uuid, integer, text, numeric, numeric, text, jsonb, text, text,
  text, text, date, text, jsonb
) owner to ledger_store_owner;

drop trigger if exists ledger_cash_capital_increase_phases_immutable
  on ledger.cash_capital_increase_phases;
create trigger ledger_cash_capital_increase_phases_immutable
before update or delete on ledger.cash_capital_increase_phases
for each row execute function backend_system.prevent_ledger_technical_mutation();

do $ledger_cash_capital_increase_migration_authority_revoke$
begin
  execute pg_catalog.format('revoke create on schema ledger from %I', current_user);
  revoke create on schema ledger from ledger_store_owner;
  execute pg_catalog.format('revoke ledger_store_owner from %I', current_user);
end
$ledger_cash_capital_increase_migration_authority_revoke$;

commit;
