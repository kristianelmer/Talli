-- Issue #188: phase-linked loss-coverage capital-reduction receiver.
-- Python owns accounting translation. This additive coordinator persists only
-- approved lifecycle identity, amount continuity, chronology, and provenance.

begin;

do $ledger_loss_reduction_migration_authority$
begin
  execute pg_catalog.format('grant ledger_store_owner to %I', current_user);
  execute pg_catalog.format('grant create on schema ledger to %I', current_user);
  grant create on schema ledger to ledger_store_owner;
end
$ledger_loss_reduction_migration_authority$;

create table if not exists ledger.loss_coverage_capital_reduction_phases (
  company_id uuid not null references public.companies(id) on delete restrict,
  capital_reduction_reference_id text not null check (
    pg_catalog.btrim(capital_reduction_reference_id) <> ''
    and pg_catalog.length(capital_reduction_reference_id) <= 255
  ),
  phase text not null check (phase in (
    'DECIDED_NOT_REGISTERED', 'REGISTERED',
    'FIRST_RECOGNIZED_AFTER_REGISTRATION'
  )),
  entry_id uuid not null unique,
  income_year integer not null check (income_year between 2000 and 2100),
  event_date date not null,
  nominal_reduction numeric(18, 2) not null check (nominal_reduction > 0),
  recorded_at timestamptz not null default pg_catalog.statement_timestamp(),
  primary key (company_id, capital_reduction_reference_id, phase),
  foreign key (entry_id, company_id, income_year)
    references ledger.entries(id, company_id, income_year) on delete restrict,
  check (extract(year from event_date)::integer = income_year)
);

alter table ledger.loss_coverage_capital_reduction_phases enable row level security;
alter table ledger.loss_coverage_capital_reduction_phases force row level security;

drop policy if exists "ledger store reads loss coverage capital reduction phases"
  on ledger.loss_coverage_capital_reduction_phases;
create policy "ledger store reads loss coverage capital reduction phases"
on ledger.loss_coverage_capital_reduction_phases for select to ledger_store_owner
using (public.company_access_is_accepted_member_v1(company_id));

drop policy if exists "ledger store records loss coverage capital reduction phases"
  on ledger.loss_coverage_capital_reduction_phases;
create policy "ledger store records loss coverage capital reduction phases"
on ledger.loss_coverage_capital_reduction_phases for insert to ledger_store_owner
with check (
  public.company_access_is_accepted_owner_v1(company_id)
  and public.company_access_company_year_allows_consequential_v1(
    company_id, income_year
  )
);

create or replace function ledger.record_loss_coverage_capital_reduction_decision_v1(
  p_idempotency_key text,
  p_company_id uuid,
  p_income_year integer,
  p_capital_reduction_reference_id text,
  p_nominal_reduction numeric,
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
    raise exception 'ledger_loss_coverage_capital_reduction_phase_invalid';
  end if;
  select pg_catalog.array_agg(item ->> 'capability' order by item ->> 'capability')
  into v_capabilities
  from pg_catalog.jsonb_array_elements(p_sources) source(item);
  if p_source_capability is distinct from 'CORPORATE_GOVERNANCE'
    or p_sources -> 0 ->> 'capability' is distinct from 'CORPORATE_GOVERNANCE'
    or v_capabilities is distinct from array[
      'CORPORATE_GOVERNANCE', 'DOCUMENTS'
    ]::text[]
    or pg_catalog.btrim(coalesce(p_capital_reduction_reference_id, '')) = ''
    or pg_catalog.length(p_capital_reduction_reference_id) > 255
    or p_nominal_reduction is null or p_nominal_reduction <= 0
    or pg_catalog.round(p_nominal_reduction, 2) is distinct from p_nominal_reduction
    or not ledger.entry_lines_are_valid_v1(p_lines, false)
  then
    raise exception 'ledger_loss_coverage_capital_reduction_phase_invalid';
  end if;
  select coalesce(pg_catalog.sum((item ->> 'debit')::numeric), 0)
  into v_journal_debit
  from pg_catalog.jsonb_array_elements(
    ledger.normalize_lines_v1(p_lines)
  ) line(item);
  if v_journal_debit is distinct from p_nominal_reduction then
    raise exception 'ledger_loss_coverage_capital_reduction_amount_mismatch';
  end if;

  select * into strict v_post
  from ledger.post_supported_entry_v1(
    p_idempotency_key, p_company_id, p_income_year, 'CAPITAL_REDUCTION',
    p_memo, p_lines, p_source_capability, p_source_record_id,
    p_correlation_id, p_verified_subject, p_event_date, p_rule_version,
    p_sources
  );

  perform pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended(
    'ledger:loss-coverage-capital-reduction:v1:' || p_company_id::text || ':'
      || pg_catalog.btrim(p_capital_reduction_reference_id),
    0
  ));

  if v_post.replayed then
    if not exists (
      select 1 from ledger.loss_coverage_capital_reduction_phases phase_record
      where phase_record.company_id = p_company_id
        and phase_record.capital_reduction_reference_id =
          pg_catalog.btrim(p_capital_reduction_reference_id)
        and phase_record.phase = 'DECIDED_NOT_REGISTERED'
        and phase_record.entry_id = v_post.ledger_entry_id
        and phase_record.income_year = p_income_year
        and phase_record.event_date = p_event_date
        and phase_record.nominal_reduction = p_nominal_reduction
    ) then
      raise exception 'ledger_idempotency_key_reused';
    end if;
  else
    if exists (
      select 1 from ledger.loss_coverage_capital_reduction_phases phase_record
      where phase_record.company_id = p_company_id
        and phase_record.capital_reduction_reference_id =
          pg_catalog.btrim(p_capital_reduction_reference_id)
    ) then
      raise exception 'ledger_loss_coverage_capital_reduction_phase_already_recorded';
    end if;
    insert into ledger.loss_coverage_capital_reduction_phases (
      company_id, capital_reduction_reference_id, phase, entry_id,
      income_year, event_date, nominal_reduction
    ) values (
      p_company_id, pg_catalog.btrim(p_capital_reduction_reference_id),
      'DECIDED_NOT_REGISTERED', v_post.ledger_entry_id, p_income_year,
      p_event_date, p_nominal_reduction
    );
  end if;

  return query select
    v_post.ledger_entry_id, v_post.company_id, v_post.income_year,
    v_post.entry_kind, v_post.posted_at, v_post.replayed;
end;
$function$;

create or replace function ledger.record_loss_coverage_capital_reduction_registration_v1(
  p_idempotency_key text,
  p_company_id uuid,
  p_income_year integer,
  p_capital_reduction_reference_id text,
  p_nominal_reduction numeric,
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
  v_decision ledger.loss_coverage_capital_reduction_phases%rowtype;
begin
  if pg_catalog.jsonb_typeof(p_sources) is distinct from 'array' then
    raise exception 'ledger_loss_coverage_capital_reduction_phase_invalid';
  end if;
  select pg_catalog.array_agg(item ->> 'capability' order by item ->> 'capability')
  into v_capabilities
  from pg_catalog.jsonb_array_elements(p_sources) source(item);
  if p_source_capability is distinct from 'CORPORATE_GOVERNANCE'
    or p_sources -> 0 ->> 'capability' is distinct from 'CORPORATE_GOVERNANCE'
    or v_capabilities is distinct from array[
      'CORPORATE_GOVERNANCE', 'DOCUMENTS',
      'SHAREHOLDER_REGISTER_FILING'
    ]::text[]
    or pg_catalog.btrim(coalesce(p_capital_reduction_reference_id, '')) = ''
    or pg_catalog.length(p_capital_reduction_reference_id) > 255
    or p_nominal_reduction is null or p_nominal_reduction <= 0
    or pg_catalog.round(p_nominal_reduction, 2) is distinct from p_nominal_reduction
    or not ledger.entry_lines_are_valid_v1(p_lines, false)
  then
    raise exception 'ledger_loss_coverage_capital_reduction_phase_invalid';
  end if;
  select coalesce(pg_catalog.sum((item ->> 'debit')::numeric), 0)
  into v_journal_debit
  from pg_catalog.jsonb_array_elements(
    ledger.normalize_lines_v1(p_lines)
  ) line(item);
  if v_journal_debit is distinct from p_nominal_reduction then
    raise exception 'ledger_loss_coverage_capital_reduction_amount_mismatch';
  end if;

  select * into strict v_post
  from ledger.post_supported_entry_v1(
    p_idempotency_key, p_company_id, p_income_year, 'CAPITAL_REDUCTION',
    p_memo, p_lines, p_source_capability, p_source_record_id,
    p_correlation_id, p_verified_subject, p_event_date, p_rule_version,
    p_sources
  );

  perform pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended(
    'ledger:loss-coverage-capital-reduction:v1:' || p_company_id::text || ':'
      || pg_catalog.btrim(p_capital_reduction_reference_id),
    0
  ));

  if v_post.replayed then
    if not exists (
      select 1 from ledger.loss_coverage_capital_reduction_phases phase_record
      where phase_record.company_id = p_company_id
        and phase_record.capital_reduction_reference_id =
          pg_catalog.btrim(p_capital_reduction_reference_id)
        and phase_record.phase = 'REGISTERED'
        and phase_record.entry_id = v_post.ledger_entry_id
        and phase_record.income_year = p_income_year
        and phase_record.event_date = p_event_date
        and phase_record.nominal_reduction = p_nominal_reduction
    ) then
      raise exception 'ledger_idempotency_key_reused';
    end if;
  else
    select phase_record.* into v_decision
    from ledger.loss_coverage_capital_reduction_phases phase_record
    where phase_record.company_id = p_company_id
      and phase_record.capital_reduction_reference_id =
        pg_catalog.btrim(p_capital_reduction_reference_id)
      and phase_record.phase = 'DECIDED_NOT_REGISTERED';
    if not found then
      if exists (
        select 1 from ledger.loss_coverage_capital_reduction_phases phase_record
        where phase_record.company_id = p_company_id
          and phase_record.capital_reduction_reference_id =
            pg_catalog.btrim(p_capital_reduction_reference_id)
      ) then
        raise exception 'ledger_loss_coverage_capital_reduction_phase_already_recorded';
      end if;
      raise exception 'ledger_opening_capital_reduction_anchor_missing';
    end if;
    if v_decision.nominal_reduction is distinct from p_nominal_reduction then
      raise exception 'ledger_loss_coverage_capital_reduction_amount_mismatch';
    end if;
    if p_event_date < v_decision.event_date then
      raise exception 'ledger_loss_coverage_capital_reduction_phase_invalid';
    end if;
    if exists (
      select 1 from ledger.loss_coverage_capital_reduction_phases phase_record
      where phase_record.company_id = p_company_id
        and phase_record.capital_reduction_reference_id =
          pg_catalog.btrim(p_capital_reduction_reference_id)
        and phase_record.phase = 'REGISTERED'
    ) then
      raise exception 'ledger_loss_coverage_capital_reduction_phase_already_recorded';
    end if;
    insert into ledger.loss_coverage_capital_reduction_phases (
      company_id, capital_reduction_reference_id, phase, entry_id,
      income_year, event_date, nominal_reduction
    ) values (
      p_company_id, pg_catalog.btrim(p_capital_reduction_reference_id),
      'REGISTERED', v_post.ledger_entry_id, p_income_year,
      p_event_date, p_nominal_reduction
    );
  end if;

  return query select
    v_post.ledger_entry_id, v_post.company_id, v_post.income_year,
    v_post.entry_kind, v_post.posted_at, v_post.replayed;
end;
$function$;

create or replace function ledger.record_loss_coverage_capital_reduction_direct_registration_v1(
  p_idempotency_key text,
  p_company_id uuid,
  p_income_year integer,
  p_capital_reduction_reference_id text,
  p_nominal_reduction numeric,
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
    raise exception 'ledger_loss_coverage_capital_reduction_phase_invalid';
  end if;
  select pg_catalog.array_agg(item ->> 'capability' order by item ->> 'capability')
  into v_capabilities
  from pg_catalog.jsonb_array_elements(p_sources) source(item);
  if p_source_capability is distinct from 'CORPORATE_GOVERNANCE'
    or p_sources -> 0 ->> 'capability' is distinct from 'CORPORATE_GOVERNANCE'
    or v_capabilities is distinct from array[
      'CORPORATE_GOVERNANCE', 'DOCUMENTS',
      'SHAREHOLDER_REGISTER_FILING'
    ]::text[]
    or pg_catalog.btrim(coalesce(p_capital_reduction_reference_id, '')) = ''
    or pg_catalog.length(p_capital_reduction_reference_id) > 255
    or p_nominal_reduction is null or p_nominal_reduction <= 0
    or pg_catalog.round(p_nominal_reduction, 2) is distinct from p_nominal_reduction
    or not ledger.entry_lines_are_valid_v1(p_lines, false)
  then
    raise exception 'ledger_loss_coverage_capital_reduction_phase_invalid';
  end if;
  select coalesce(pg_catalog.sum((item ->> 'debit')::numeric), 0)
  into v_journal_debit
  from pg_catalog.jsonb_array_elements(
    ledger.normalize_lines_v1(p_lines)
  ) line(item);
  if v_journal_debit is distinct from p_nominal_reduction then
    raise exception 'ledger_loss_coverage_capital_reduction_amount_mismatch';
  end if;

  select * into strict v_post
  from ledger.post_supported_entry_v1(
    p_idempotency_key, p_company_id, p_income_year, 'CAPITAL_REDUCTION',
    p_memo, p_lines, p_source_capability, p_source_record_id,
    p_correlation_id, p_verified_subject, p_event_date, p_rule_version,
    p_sources
  );

  perform pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended(
    'ledger:loss-coverage-capital-reduction:v1:' || p_company_id::text || ':'
      || pg_catalog.btrim(p_capital_reduction_reference_id),
    0
  ));

  if v_post.replayed then
    if not exists (
      select 1 from ledger.loss_coverage_capital_reduction_phases phase_record
      where phase_record.company_id = p_company_id
        and phase_record.capital_reduction_reference_id =
          pg_catalog.btrim(p_capital_reduction_reference_id)
        and phase_record.phase = 'FIRST_RECOGNIZED_AFTER_REGISTRATION'
        and phase_record.entry_id = v_post.ledger_entry_id
        and phase_record.income_year = p_income_year
        and phase_record.event_date = p_event_date
        and phase_record.nominal_reduction = p_nominal_reduction
    ) then
      raise exception 'ledger_idempotency_key_reused';
    end if;
  else
    if exists (
      select 1 from ledger.loss_coverage_capital_reduction_phases phase_record
      where phase_record.company_id = p_company_id
        and phase_record.capital_reduction_reference_id =
          pg_catalog.btrim(p_capital_reduction_reference_id)
    ) then
      raise exception 'ledger_loss_coverage_capital_reduction_phase_already_recorded';
    end if;
    insert into ledger.loss_coverage_capital_reduction_phases (
      company_id, capital_reduction_reference_id, phase, entry_id,
      income_year, event_date, nominal_reduction
    ) values (
      p_company_id, pg_catalog.btrim(p_capital_reduction_reference_id),
      'FIRST_RECOGNIZED_AFTER_REGISTRATION', v_post.ledger_entry_id,
      p_income_year, p_event_date, p_nominal_reduction
    );
  end if;

  return query select
    v_post.ledger_entry_id, v_post.company_id, v_post.income_year,
    v_post.entry_kind, v_post.posted_at, v_post.replayed;
end;
$function$;

revoke all on ledger.loss_coverage_capital_reduction_phases
from public, anon, authenticated, service_role, ledger_executor,
  ledger_workflow_executor, talli_ledger_backend;
grant select, insert on ledger.loss_coverage_capital_reduction_phases
to ledger_store_owner;

revoke all on function ledger.record_loss_coverage_capital_reduction_decision_v1(
  text, uuid, integer, text, numeric, text, jsonb, text, text, text,
  text, date, text, jsonb
) from public, anon, authenticated, service_role,
  ledger_workflow_executor, talli_ledger_backend;
revoke all on function ledger.record_loss_coverage_capital_reduction_registration_v1(
  text, uuid, integer, text, numeric, text, jsonb, text, text, text,
  text, date, text, jsonb
) from public, anon, authenticated, service_role,
  ledger_workflow_executor, talli_ledger_backend;
revoke all on function ledger.record_loss_coverage_capital_reduction_direct_registration_v1(
  text, uuid, integer, text, numeric, text, jsonb, text, text, text,
  text, date, text, jsonb
) from public, anon, authenticated, service_role,
  ledger_workflow_executor, talli_ledger_backend;

grant execute on function ledger.record_loss_coverage_capital_reduction_decision_v1(
  text, uuid, integer, text, numeric, text, jsonb, text, text, text,
  text, date, text, jsonb
) to ledger_executor;
grant execute on function ledger.record_loss_coverage_capital_reduction_registration_v1(
  text, uuid, integer, text, numeric, text, jsonb, text, text, text,
  text, date, text, jsonb
) to ledger_executor;
grant execute on function ledger.record_loss_coverage_capital_reduction_direct_registration_v1(
  text, uuid, integer, text, numeric, text, jsonb, text, text, text,
  text, date, text, jsonb
) to ledger_executor;

alter table ledger.loss_coverage_capital_reduction_phases owner to ledger_store_owner;
alter function ledger.record_loss_coverage_capital_reduction_decision_v1(
  text, uuid, integer, text, numeric, text, jsonb, text, text, text,
  text, date, text, jsonb
) owner to ledger_store_owner;
alter function ledger.record_loss_coverage_capital_reduction_registration_v1(
  text, uuid, integer, text, numeric, text, jsonb, text, text, text,
  text, date, text, jsonb
) owner to ledger_store_owner;
alter function ledger.record_loss_coverage_capital_reduction_direct_registration_v1(
  text, uuid, integer, text, numeric, text, jsonb, text, text, text,
  text, date, text, jsonb
) owner to ledger_store_owner;

drop trigger if exists ledger_loss_coverage_capital_reduction_phases_immutable
  on ledger.loss_coverage_capital_reduction_phases;
create trigger ledger_loss_coverage_capital_reduction_phases_immutable
before update or delete on ledger.loss_coverage_capital_reduction_phases
for each row execute function backend_system.prevent_ledger_technical_mutation();

do $ledger_loss_reduction_migration_authority_revoke$
begin
  execute pg_catalog.format('revoke create on schema ledger from %I', current_user);
  revoke create on schema ledger from ledger_store_owner;
  execute pg_catalog.format('revoke ledger_store_owner from %I', current_user);
end
$ledger_loss_reduction_migration_authority_revoke$;

commit;
