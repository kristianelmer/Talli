-- Issue #188: phase-linked received-dividend recognition.
-- Python selects the accounting route. These wrappers only persist the
-- already-derived balanced entry and enforce immutable decision/payment lineage.

begin;

do $ledger_received_dividend_migration_authority$
begin
  execute pg_catalog.format('grant ledger_store_owner to %I', current_user);
  execute pg_catalog.format('grant create on schema ledger to %I', current_user);
  grant create on schema ledger to ledger_store_owner;
end
$ledger_received_dividend_migration_authority$;

create table if not exists ledger.received_dividend_decisions (
  decision_entry_id uuid primary key,
  company_id uuid not null references public.companies(id) on delete restrict,
  income_year integer not null check (income_year between 2000 and 2100),
  recorded_at timestamptz not null default pg_catalog.statement_timestamp(),
  unique (decision_entry_id, company_id, income_year),
  foreign key (decision_entry_id, company_id, income_year)
    references ledger.entries(id, company_id, income_year) on delete restrict
);

create table if not exists ledger.received_dividend_settlements (
  decision_entry_id uuid primary key,
  payment_entry_id uuid not null unique,
  company_id uuid not null references public.companies(id) on delete restrict,
  decision_income_year integer not null check (
    decision_income_year between 2000 and 2100
  ),
  payment_income_year integer not null check (
    payment_income_year between 2000 and 2100
  ),
  recorded_at timestamptz not null default pg_catalog.statement_timestamp(),
  foreign key (decision_entry_id, company_id, decision_income_year)
    references ledger.received_dividend_decisions(
      decision_entry_id, company_id, income_year
    ) on delete restrict,
  foreign key (payment_entry_id, company_id, payment_income_year)
    references ledger.entries(id, company_id, income_year) on delete restrict,
  check (
    decision_entry_id <> payment_entry_id
    and payment_income_year >= decision_income_year
  )
);

alter table ledger.received_dividend_decisions enable row level security;
alter table ledger.received_dividend_decisions force row level security;
alter table ledger.received_dividend_settlements enable row level security;
alter table ledger.received_dividend_settlements force row level security;

drop policy if exists "ledger store reads received dividend decisions"
  on ledger.received_dividend_decisions;
create policy "ledger store reads received dividend decisions"
on ledger.received_dividend_decisions for select to ledger_store_owner
using (public.company_access_is_accepted_member_v1(company_id));

drop policy if exists "ledger store records received dividend decisions"
  on ledger.received_dividend_decisions;
create policy "ledger store records received dividend decisions"
on ledger.received_dividend_decisions for insert to ledger_store_owner
with check (
  public.company_access_is_accepted_owner_v1(company_id)
  and public.company_access_company_year_allows_consequential_v1(
    company_id, income_year
  )
);

drop policy if exists "ledger store reads received dividend settlements"
  on ledger.received_dividend_settlements;
create policy "ledger store reads received dividend settlements"
on ledger.received_dividend_settlements for select to ledger_store_owner
using (public.company_access_is_accepted_member_v1(company_id));

drop policy if exists "ledger store records received dividend settlements"
  on ledger.received_dividend_settlements;
create policy "ledger store records received dividend settlements"
on ledger.received_dividend_settlements for insert to ledger_store_owner
with check (
  public.company_access_is_accepted_owner_v1(company_id)
  and public.company_access_company_year_allows_consequential_v1(
    company_id, payment_income_year
  )
);

create or replace function ledger.record_received_dividend_decision_v1(
  p_idempotency_key text,
  p_company_id uuid,
  p_income_year integer,
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
begin
  if pg_catalog.jsonb_typeof(p_sources) is distinct from 'array' then
    raise exception 'ledger_invalid_input';
  end if;
  select pg_catalog.array_agg(item ->> 'capability' order by item ->> 'capability')
  into v_capabilities
  from pg_catalog.jsonb_array_elements(p_sources) source(item);
  if p_source_capability is distinct from 'INVESTMENTS'
    or p_sources -> 0 ->> 'capability' is distinct from 'INVESTMENTS'
    or v_capabilities is distinct from array[
      'COMPANY_TAX_FILING', 'DOCUMENTS', 'INVESTMENTS'
    ]::text[]
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

  if v_post.replayed then
    if not exists (
      select 1 from ledger.received_dividend_decisions decision
      where decision.decision_entry_id = v_post.ledger_entry_id
        and decision.company_id = p_company_id
        and decision.income_year = p_income_year
    ) then
      raise exception 'ledger_idempotency_key_reused';
    end if;
  else
    insert into ledger.received_dividend_decisions (
      decision_entry_id, company_id, income_year
    ) values (
      v_post.ledger_entry_id, p_company_id, p_income_year
    );
  end if;

  return query select
    v_post.ledger_entry_id, v_post.company_id, v_post.income_year,
    v_post.entry_kind, v_post.posted_at, v_post.replayed;
end;
$function$;

create or replace function ledger.record_received_dividend_payment_v1(
  p_idempotency_key text,
  p_company_id uuid,
  p_income_year integer,
  p_decision_entry_id uuid,
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
  v_decision_lines jsonb;
  v_decision_event_date date;
  v_decision_income_year integer;
  v_decision_total numeric;
  v_payment_total numeric;
begin
  if pg_catalog.jsonb_typeof(p_sources) is distinct from 'array' then
    raise exception 'ledger_invalid_input';
  end if;
  select pg_catalog.array_agg(item ->> 'capability' order by item ->> 'capability')
  into v_capabilities
  from pg_catalog.jsonb_array_elements(p_sources) source(item);
  if p_decision_entry_id is null
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

  -- Payments can settle a decision in a later company-year, so the canonical
  -- payment-year lock is not sufficient to serialize this one-time lifecycle.
  -- An advisory lock preserves immutable forced-RLS decision rows while making
  -- every contender re-read settlement state after the winner commits.
  perform pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended(
    'ledger:received-dividend-decision:v1:' || p_decision_entry_id::text,
    0
  ));

  if v_post.replayed then
    if not exists (
      select 1 from ledger.received_dividend_settlements settlement
      where settlement.decision_entry_id = p_decision_entry_id
        and settlement.payment_entry_id = v_post.ledger_entry_id
        and settlement.company_id = p_company_id
        and settlement.payment_income_year = p_income_year
    ) then
      raise exception 'ledger_idempotency_key_reused';
    end if;
  else
    select entry.lines, context.event_date, decision.income_year
    into v_decision_lines, v_decision_event_date, v_decision_income_year
    from ledger.received_dividend_decisions decision
    join ledger.entries entry
      on entry.id = decision.decision_entry_id
      and entry.company_id = decision.company_id
      and entry.income_year = decision.income_year
    join ledger.entry_contexts context
      on context.entry_id = decision.decision_entry_id
      and context.company_id = decision.company_id
      and context.income_year = decision.income_year
    where decision.decision_entry_id = p_decision_entry_id
      and decision.company_id = p_company_id;
    if not found then
      raise exception 'ledger_received_dividend_decision_invalid';
    end if;
    if p_event_date < v_decision_event_date then
      raise exception 'ledger_received_dividend_decision_invalid';
    end if;
    if exists (
      select 1 from ledger.received_dividend_settlements settlement
      where settlement.decision_entry_id = p_decision_entry_id
    ) then
      raise exception 'ledger_received_dividend_already_settled';
    end if;
    select coalesce(pg_catalog.sum((line ->> 'debit')::numeric), 0)
    into v_decision_total
    from pg_catalog.jsonb_array_elements(v_decision_lines) source(line);
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
    insert into ledger.received_dividend_settlements (
      decision_entry_id, payment_entry_id, company_id,
      decision_income_year, payment_income_year
    ) values (
      p_decision_entry_id, v_post.ledger_entry_id, p_company_id,
      v_decision_income_year, p_income_year
    );
  end if;

  return query select
    v_post.ledger_entry_id, v_post.company_id, v_post.income_year,
    v_post.entry_kind, v_post.posted_at, v_post.replayed;
end;
$function$;

revoke all on ledger.received_dividend_decisions,
  ledger.received_dividend_settlements
from public, anon, authenticated, ledger_executor, ledger_workflow_executor;
grant select, insert on ledger.received_dividend_decisions,
  ledger.received_dividend_settlements
to ledger_store_owner;

revoke all on function ledger.record_received_dividend_decision_v1(
  text, uuid, integer, text, jsonb, text, text, text, text, date, text, jsonb
) from public, anon, authenticated;
revoke all on function ledger.record_received_dividend_payment_v1(
  text, uuid, integer, uuid, text, jsonb, text, text, text, text,
  date, text, jsonb
) from public, anon, authenticated;
grant execute on function ledger.record_received_dividend_decision_v1(
  text, uuid, integer, text, jsonb, text, text, text, text, date, text, jsonb
) to ledger_executor;
grant execute on function ledger.record_received_dividend_payment_v1(
  text, uuid, integer, uuid, text, jsonb, text, text, text, text,
  date, text, jsonb
) to ledger_executor;

alter table ledger.received_dividend_decisions owner to ledger_store_owner;
alter table ledger.received_dividend_settlements owner to ledger_store_owner;
alter function ledger.record_received_dividend_decision_v1(
  text, uuid, integer, text, jsonb, text, text, text, text, date, text, jsonb
) owner to ledger_store_owner;
alter function ledger.record_received_dividend_payment_v1(
  text, uuid, integer, uuid, text, jsonb, text, text, text, text,
  date, text, jsonb
) owner to ledger_store_owner;

drop trigger if exists ledger_received_dividend_decisions_immutable
  on ledger.received_dividend_decisions;
create trigger ledger_received_dividend_decisions_immutable
before update or delete on ledger.received_dividend_decisions
for each row execute function backend_system.prevent_ledger_technical_mutation();

drop trigger if exists ledger_received_dividend_settlements_immutable
  on ledger.received_dividend_settlements;
create trigger ledger_received_dividend_settlements_immutable
before update or delete on ledger.received_dividend_settlements
for each row execute function backend_system.prevent_ledger_technical_mutation();

do $ledger_received_dividend_migration_authority_revoke$
begin
  execute pg_catalog.format('revoke create on schema ledger from %I', current_user);
  revoke create on schema ledger from ledger_store_owner;
  execute pg_catalog.format('revoke ledger_store_owner from %I', current_user);
end
$ledger_received_dividend_migration_authority_revoke$;

commit;
