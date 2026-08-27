-- EXPAND/MIGRATE: ledger authority, durable command journal, and legacy reconciliation.
--
-- This phase keeps the reviewed authenticated overlap writer until the separate
-- contract artifact is applied.  It is replay-safe so the same artifact is also
-- the recutover path after a rehearsed contract rollback.

begin;

create schema if not exists ledger;
create schema if not exists backend_system;

do $ledger_roles$
begin
  if not exists (
    select 1 from pg_catalog.pg_roles where rolname = 'ledger_store_owner'
  ) then
    create role ledger_store_owner nologin noinherit nobypassrls;
  end if;
  if not exists (
    select 1 from pg_catalog.pg_roles where rolname = 'ledger_executor'
  ) then
    create role ledger_executor nologin noinherit nobypassrls;
  end if;
  if not exists (
    select 1 from pg_catalog.pg_roles where rolname = 'talli_ledger_backend'
  ) then
    create role talli_ledger_backend nologin noinherit nobypassrls;
  end if;
  if not exists (
    select 1 from pg_catalog.pg_roles where rolname = 'ledger_workflow_store_owner'
  ) then
    create role ledger_workflow_store_owner nologin noinherit nobypassrls;
  end if;
  if not exists (
    select 1 from pg_catalog.pg_roles where rolname = 'ledger_workflow_executor'
  ) then
    create role ledger_workflow_executor nologin noinherit nobypassrls;
  end if;
end
$ledger_roles$;

alter role ledger_store_owner nologin noinherit nobypassrls;
alter role ledger_executor nologin noinherit nobypassrls;
alter role talli_ledger_backend nologin noinherit nobypassrls;
alter role ledger_workflow_store_owner nologin noinherit nobypassrls;
alter role ledger_workflow_executor nologin noinherit nobypassrls;
grant ledger_executor to talli_ledger_backend with inherit false, set true;
grant ledger_workflow_executor to talli_ledger_backend with inherit false, set true;
grant usage, create on schema ledger, backend_system to ledger_store_owner;
grant usage on schema extensions to ledger_store_owner,
  ledger_workflow_store_owner;
grant execute on function
  extensions.digest(text, text),
  extensions.hmac(text, text, text),
  extensions.gen_random_bytes(integer)
to ledger_store_owner, ledger_workflow_store_owner;
grant usage on schema ledger to ledger_executor;
grant usage on schema backend_system to ledger_executor,
  ledger_workflow_store_owner, ledger_workflow_executor;
grant create on schema backend_system to ledger_workflow_store_owner;
grant usage on schema ledger to ledger_workflow_executor;

create table if not exists backend_system.ledger_migration_runs (
  id uuid primary key,
  started_at timestamptz not null default statement_timestamp(),
  completed_at timestamptz
);
create table if not exists backend_system.ledger_migration_source_rows (
  run_id uuid not null references backend_system.ledger_migration_runs(id)
    on delete restrict,
  source_table text not null,
  source_id uuid not null,
  payload jsonb not null,
  payload_sha256 text not null check (payload_sha256 ~ '^[0-9a-f]{64}$'),
  primary key (run_id, source_table, source_id)
);
create table if not exists backend_system.ledger_migration_quarantine (
  id uuid primary key default gen_random_uuid(),
  run_id uuid not null references backend_system.ledger_migration_runs(id)
    on delete restrict,
  source_table text not null,
  source_id uuid not null,
  reason_code text not null check (btrim(reason_code) <> ''),
  payload jsonb not null,
  payload_sha256 text not null check (payload_sha256 ~ '^[0-9a-f]{64}$'),
  quarantined_at timestamptz not null default statement_timestamp(),
  unique (run_id, source_table, source_id)
);
create table if not exists backend_system.ledger_migration_reconciliations (
  id uuid primary key default gen_random_uuid(),
  run_id uuid not null references backend_system.ledger_migration_runs(id)
    on delete restrict,
  source_table text not null,
  source_row_count bigint not null check (source_row_count >= 0),
  accepted_row_count bigint not null check (accepted_row_count >= 0),
  quarantined_row_count bigint not null check (quarantined_row_count >= 0),
  source_sha256 text not null check (source_sha256 ~ '^[0-9a-f]{64}$'),
  accepted_sha256 text not null check (accepted_sha256 ~ '^[0-9a-f]{64}$'),
  quarantine_sha256 text not null check (quarantine_sha256 ~ '^[0-9a-f]{64}$'),
  recorded_at timestamptz not null default statement_timestamp(),
  unique (run_id, source_table),
  check (source_row_count = accepted_row_count + quarantined_row_count)
);

select pg_catalog.pg_advisory_xact_lock(
  pg_catalog.hashtextextended('talli:ledger:capability-cutover:v1', 0)
);
lock table public.ledger_entries in access exclusive mode;
lock table public.period_locks in access exclusive mode;

select pg_catalog.set_config(
  'talli.ledger_migration_run_id',
  pg_catalog.gen_random_uuid()::text,
  true
);
insert into backend_system.ledger_migration_runs (id)
values (pg_catalog.current_setting('talli.ledger_migration_run_id')::uuid);

insert into backend_system.ledger_migration_source_rows (
  run_id, source_table, source_id, payload, payload_sha256
)
select
  pg_catalog.current_setting('talli.ledger_migration_run_id')::uuid,
  'ledger_entries',
  entry.id,
  pg_catalog.to_jsonb(entry),
  pg_catalog.encode(extensions.digest(pg_catalog.to_jsonb(entry)::text, 'sha256'), 'hex')
from public.ledger_entries entry
union all
select
  pg_catalog.current_setting('talli.ledger_migration_run_id')::uuid,
  'period_locks',
  period_lock.id,
  pg_catalog.to_jsonb(period_lock),
  pg_catalog.encode(
    extensions.digest(pg_catalog.to_jsonb(period_lock)::text, 'sha256'), 'hex'
  )
from public.period_locks period_lock;

-- One physical relation is preserved throughout expand, rollback, and recutover.
-- The ACCESS EXCLUSIVE locks prevent a predecessor write from escaping the
-- pre-transform snapshot while the OIDs move into the capability schema.
do $ledger_move_sources$
begin
  if pg_catalog.to_regclass('public.ledger_entries') is not null then
    alter table public.ledger_entries set schema ledger;
  end if;
  if pg_catalog.to_regclass('ledger.ledger_entries') is not null then
    alter table ledger.ledger_entries rename to entries;
  end if;
  if pg_catalog.to_regclass('public.period_locks') is not null then
    alter table public.period_locks set schema ledger;
  end if;
end
$ledger_move_sources$;

drop trigger if exists ledger_entries_enforce_boundary on ledger.entries;
alter table ledger.entries rename column entry_type to entry_kind;

alter table ledger.entries
  add column if not exists source_capability text,
  add column if not exists source_record_id text,
  add column if not exists correlation_id text;

create table if not exists backend_system.ledger_command_receipts (
  id uuid primary key default gen_random_uuid(),
  api_major text not null check (api_major = 'v1'),
  actor_id uuid not null,
  company_id uuid not null references public.companies(id) on delete restrict,
  operation_name text not null check (operation_name in ('post_entry', 'lock_period')),
  idempotency_key text not null check (
    idempotency_key ~ '^[A-Za-z0-9._:-]{16,255}$'
  ),
  request_fingerprint text not null check (request_fingerprint ~ '^[0-9a-f]{64}$'),
  result jsonb not null,
  completed_at timestamptz not null default statement_timestamp(),
  unique (api_major, actor_id, company_id, operation_name, idempotency_key)
);

create table if not exists backend_system.ledger_workflow_receipts (
  id uuid primary key default gen_random_uuid(),
  api_major text not null check (api_major = 'v1'),
  actor_id uuid not null,
  company_id uuid not null references public.companies(id) on delete restrict,
  operation_name text not null check (operation_name in ('new_year_start')),
  idempotency_key text not null check (
    idempotency_key ~ '^[A-Za-z0-9._:-]{16,255}$'
  ),
  request_fingerprint text not null check (request_fingerprint ~ '^[0-9a-f]{64}$'),
  result jsonb not null,
  completed_at timestamptz not null default statement_timestamp(),
  unique (api_major, actor_id, company_id, operation_name, idempotency_key)
);

create table if not exists backend_system.ledger_cursor_signing_keys (
  id uuid primary key default gen_random_uuid(),
  secret bytea not null check (pg_catalog.octet_length(secret) = 32),
  created_at timestamptz not null default statement_timestamp()
);
insert into backend_system.ledger_cursor_signing_keys (secret)
select extensions.gen_random_bytes(32)
where not exists (
  select 1 from backend_system.ledger_cursor_signing_keys
);

create or replace function ledger.entry_lines_are_valid_v1(
  p_lines jsonb,
  p_allow_missing_currency boolean default false
)
returns boolean
language plpgsql
immutable
set search_path = ''
as $function$
declare
  v_line jsonb;
  v_debit numeric;
  v_credit numeric;
  v_debit_total numeric;
  v_credit_total numeric;
begin
  if pg_catalog.jsonb_typeof(p_lines) is distinct from 'array'
    or pg_catalog.jsonb_array_length(p_lines) < 2
  then
    return false;
  end if;

  for v_line in select value from pg_catalog.jsonb_array_elements(p_lines)
  loop
    if pg_catalog.jsonb_typeof(v_line) is distinct from 'object'
      or coalesce(v_line ->> 'account', '') !~ '^[0-9]{4}$'
      or pg_catalog.btrim(coalesce(v_line ->> 'description', '')) = ''
      or coalesce(v_line ->> 'debit', '') !~ '^[0-9]+([.][0-9]{1,2})?$'
      or coalesce(v_line ->> 'credit', '') !~ '^[0-9]+([.][0-9]{1,2})?$'
      or (
        not p_allow_missing_currency
        and coalesce(v_line ->> 'currency', '') <> 'NOK'
      )
      or (
        p_allow_missing_currency
        and coalesce(v_line ->> 'currency', 'NOK') <> 'NOK'
      )
    then
      return false;
    end if;
    v_debit := (v_line ->> 'debit')::numeric;
    v_credit := (v_line ->> 'credit')::numeric;
    if v_debit < 0 or v_credit < 0
      or round(v_debit, 2) <> v_debit
      or round(v_credit, 2) <> v_credit
      or (v_debit > 0 and v_credit > 0)
    then
      return false;
    end if;
  end loop;

  select
    coalesce(sum((line ->> 'debit')::numeric), 0),
    coalesce(sum((line ->> 'credit')::numeric), 0)
  into v_debit_total, v_credit_total
  from pg_catalog.jsonb_array_elements(p_lines) line;

  return v_debit_total > 0
    and round(v_debit_total, 2) = round(v_credit_total, 2);
exception
  when others then
    return false;
end;
$function$;

create or replace function ledger.normalize_lines_v1(p_lines jsonb)
returns jsonb
language sql
immutable
set search_path = ''
as $function$
  select coalesce(
    pg_catalog.jsonb_agg(
      pg_catalog.jsonb_build_object(
        'account', line ->> 'account',
        'description', pg_catalog.btrim(line ->> 'description'),
        'debit', round((line ->> 'debit')::numeric, 2),
        'credit', round((line ->> 'credit')::numeric, 2),
        'currency', 'NOK'
      ) order by ordinal
    ),
    '[]'::jsonb
  )
  from pg_catalog.jsonb_array_elements(p_lines) with ordinality item(line, ordinal);
$function$;

-- Quarantine malformed predecessor rows before the strict persistence trigger
-- is installed.  The original payload is retained with a deterministic hash;
-- no command receipt or accepted posting is fabricated for rejected history.
insert into backend_system.ledger_migration_quarantine (
  run_id, source_table, source_id, reason_code, payload, payload_sha256
)
select
  pg_catalog.current_setting('talli.ledger_migration_run_id')::uuid,
  'ledger_entries',
  entry.id,
  'LEDGER_LINES_INVALID',
  pg_catalog.to_jsonb(entry),
  pg_catalog.encode(extensions.digest(pg_catalog.to_jsonb(entry)::text, 'sha256'), 'hex')
from ledger.entries entry
where not ledger.entry_lines_are_valid_v1(entry.lines, true)
  or pg_catalog.lower(entry.entry_kind) not in (
    'opening_balance', 'admin_cost', 'administrative_cost', 'manual_journal',
    'bank_rule_suggestion', 'dividend_received',
    'dividend_to_owner_declared', 'owner_dividend_declared',
    'dividend_to_owner_payment', 'owner_dividend_payment',
    'share_purchase', 'share_sale', 'shareholder_loan', 'tax_settlement',
    'bank_interest', 'bank_loan', 'capital_increase',
    'company_tax_accrual', 'group_contribution'
  )
on conflict (run_id, source_table, source_id) do nothing;

delete from ledger.entries entry
where exists (
  select 1
  from backend_system.ledger_migration_quarantine quarantine
  where quarantine.run_id = pg_catalog.current_setting(
      'talli.ledger_migration_run_id'
    )::uuid
    and quarantine.source_table = 'ledger_entries'
    and quarantine.source_id = entry.id
    and quarantine.payload_sha256 = pg_catalog.encode(extensions.digest(
      pg_catalog.to_jsonb(entry)::text, 'sha256'
    ), 'hex')
);

update ledger.entries
set lines = ledger.normalize_lines_v1(lines),
    entry_kind = case pg_catalog.lower(entry_kind)
      when 'opening_balance' then 'OPENING_BALANCE'
      when 'admin_cost' then 'ADMINISTRATIVE_COST'
      when 'administrative_cost' then 'ADMINISTRATIVE_COST'
      when 'manual_journal' then 'MANUAL_JOURNAL'
      when 'bank_rule_suggestion' then 'BANK_RULE_SUGGESTION'
      when 'dividend_received' then 'DIVIDEND_RECEIVED'
      when 'dividend_to_owner_declared' then 'OWNER_DIVIDEND_DECLARED'
      when 'owner_dividend_declared' then 'OWNER_DIVIDEND_DECLARED'
      when 'dividend_to_owner_payment' then 'OWNER_DIVIDEND_PAYMENT'
      when 'owner_dividend_payment' then 'OWNER_DIVIDEND_PAYMENT'
      when 'share_purchase' then 'SHARE_PURCHASE'
      when 'share_sale' then 'SHARE_SALE'
      when 'shareholder_loan' then 'SHAREHOLDER_LOAN'
      when 'tax_settlement' then 'TAX_SETTLEMENT'
      when 'bank_interest' then 'BANK_INTEREST'
      when 'bank_loan' then 'BANK_LOAN'
      when 'capital_increase' then 'CAPITAL_INCREASE'
      when 'company_tax_accrual' then 'COMPANY_TAX_ACCRUAL'
      when 'group_contribution' then 'GROUP_CONTRIBUTION'
    end,
    source_capability = coalesce(
      source_capability,
      case pg_catalog.lower(entry_kind)
        when 'opening_balance' then case
          when setup_id is not null then 'SHAREHOLDER_REGISTER_FILING'
          else 'LEDGER'
        end
        when 'bank_rule_suggestion' then 'BANKING'
        when 'dividend_received' then 'INVESTMENTS'
        when 'share_purchase' then 'INVESTMENTS'
        when 'share_sale' then 'INVESTMENTS'
        when 'dividend_to_owner_declared' then 'CORPORATE_GOVERNANCE'
        when 'owner_dividend_declared' then 'CORPORATE_GOVERNANCE'
        when 'dividend_to_owner_payment' then 'CORPORATE_GOVERNANCE'
        when 'owner_dividend_payment' then 'CORPORATE_GOVERNANCE'
        when 'shareholder_loan' then 'CORPORATE_GOVERNANCE'
        when 'tax_settlement' then 'COMPANY_TAX_FILING'
        when 'bank_interest' then 'BANKING'
        when 'bank_loan' then 'BANKING'
        when 'capital_increase' then 'CORPORATE_GOVERNANCE'
        when 'company_tax_accrual' then 'COMPANY_TAX_FILING'
        when 'group_contribution' then 'CORPORATE_GOVERNANCE'
        else 'LEDGER'
      end
    ),
    source_record_id = coalesce(
      source_record_id,
      case
        when setup_id is not null then 'opening-setup:' || setup_id::text
        else 'legacy:' || id::text
      end
    ),
    correlation_id = coalesce(correlation_id, 'legacy-migration:' || id::text);

alter table ledger.entries
  alter column source_capability set not null,
  alter column source_record_id set not null,
  alter column correlation_id set not null;

alter table ledger.entries
  drop constraint if exists ledger_entries_source_capability_check;
alter table ledger.entries
  add constraint ledger_entries_source_capability_check check (
    source_capability in (
      'LEDGER', 'BANKING', 'INVESTMENTS', 'CORPORATE_GOVERNANCE',
      'COMPANY_TAX_FILING', 'SHAREHOLDER_REGISTER_FILING'
    )
  );

create unique index if not exists ledger_entries_source_capability_record_uidx
  on ledger.entries(company_id, source_capability, source_record_id);
create unique index if not exists ledger_entries_one_opening_company_year_uidx
  on ledger.entries(company_id, income_year)
  where entry_kind = 'OPENING_BALANCE';
create index if not exists ledger_entries_cursor_idx
  on ledger.entries(created_at desc, id desc);
create index if not exists period_locks_cursor_idx
  on ledger.period_locks(locked_at desc, id desc);

create or replace function ledger.enforce_entry_v1()
returns trigger
language plpgsql
security definer
set search_path = ''
as $function$
begin
  new.entry_kind := case pg_catalog.lower(pg_catalog.btrim(new.entry_kind))
    when 'opening_balance' then 'OPENING_BALANCE'
    when 'admin_cost' then 'ADMINISTRATIVE_COST'
    when 'administrative_cost' then 'ADMINISTRATIVE_COST'
    when 'manual_journal' then 'MANUAL_JOURNAL'
    when 'bank_rule_suggestion' then 'BANK_RULE_SUGGESTION'
    when 'dividend_received' then 'DIVIDEND_RECEIVED'
    when 'dividend_to_owner_declared' then 'OWNER_DIVIDEND_DECLARED'
    when 'owner_dividend_declared' then 'OWNER_DIVIDEND_DECLARED'
    when 'dividend_to_owner_payment' then 'OWNER_DIVIDEND_PAYMENT'
    when 'owner_dividend_payment' then 'OWNER_DIVIDEND_PAYMENT'
    when 'share_purchase' then 'SHARE_PURCHASE'
    when 'share_sale' then 'SHARE_SALE'
    when 'shareholder_loan' then 'SHAREHOLDER_LOAN'
    when 'tax_settlement' then 'TAX_SETTLEMENT'
    when 'bank_interest' then 'BANK_INTEREST'
    when 'bank_loan' then 'BANK_LOAN'
    when 'capital_increase' then 'CAPITAL_INCREASE'
    when 'company_tax_accrual' then 'COMPANY_TAX_ACCRUAL'
    when 'group_contribution' then 'GROUP_CONTRIBUTION'
    else pg_catalog.upper(pg_catalog.btrim(new.entry_kind))
  end;
  if new.entry_kind not in (
    'OPENING_BALANCE', 'ADMINISTRATIVE_COST', 'MANUAL_JOURNAL',
    'BANK_RULE_SUGGESTION', 'DIVIDEND_RECEIVED',
    'OWNER_DIVIDEND_DECLARED', 'OWNER_DIVIDEND_PAYMENT', 'SHARE_PURCHASE',
    'SHARE_SALE', 'SHAREHOLDER_LOAN', 'TAX_SETTLEMENT',
    'BANK_INTEREST', 'BANK_LOAN', 'CAPITAL_INCREASE',
    'COMPANY_TAX_ACCRUAL', 'GROUP_CONTRIBUTION'
  ) or not ledger.entry_lines_are_valid_v1(new.lines, true) then
    raise exception 'ledger_invalid_input';
  end if;
  new.lines := ledger.normalize_lines_v1(new.lines);
  new.source_capability := coalesce(
    new.source_capability,
    case new.entry_kind
      when 'OPENING_BALANCE' then case
        when nullif(pg_catalog.to_jsonb(new) ->> 'setup_id', '') is not null
        then 'SHAREHOLDER_REGISTER_FILING'
        else 'LEDGER'
      end
      when 'BANK_RULE_SUGGESTION' then 'BANKING'
      when 'DIVIDEND_RECEIVED' then 'INVESTMENTS'
      when 'SHARE_PURCHASE' then 'INVESTMENTS'
      when 'SHARE_SALE' then 'INVESTMENTS'
      when 'OWNER_DIVIDEND_DECLARED' then 'CORPORATE_GOVERNANCE'
      when 'OWNER_DIVIDEND_PAYMENT' then 'CORPORATE_GOVERNANCE'
      when 'SHAREHOLDER_LOAN' then 'CORPORATE_GOVERNANCE'
      when 'TAX_SETTLEMENT' then 'COMPANY_TAX_FILING'
      when 'BANK_INTEREST' then 'BANKING'
      when 'BANK_LOAN' then 'BANKING'
      when 'CAPITAL_INCREASE' then 'CORPORATE_GOVERNANCE'
      when 'COMPANY_TAX_ACCRUAL' then 'COMPANY_TAX_FILING'
      when 'GROUP_CONTRIBUTION' then 'CORPORATE_GOVERNANCE'
      else 'LEDGER'
    end
  );
  new.source_record_id := coalesce(
    nullif(pg_catalog.btrim(new.source_record_id), ''),
    case
      when new.entry_kind = 'OPENING_BALANCE'
        and nullif(pg_catalog.to_jsonb(new) ->> 'setup_id', '') is not null
      then 'opening-setup:' || (pg_catalog.to_jsonb(new) ->> 'setup_id')
      else 'rollback:' || new.id::text
    end
  );
  new.correlation_id := coalesce(
    nullif(pg_catalog.btrim(new.correlation_id), ''),
    'rollback:' || new.id::text
  );
  return new;
end;
$function$;

drop trigger if exists ledger_entries_enforce_boundary on ledger.entries;
create trigger ledger_entries_enforce_boundary
before insert or update of entry_kind, lines, source_capability, source_record_id
on ledger.entries
for each row execute function ledger.enforce_entry_v1();

do $ledger_reconcile$
declare
  v_run_id uuid := pg_catalog.current_setting('talli.ledger_migration_run_id')::uuid;
  v_run_at timestamptz := pg_catalog.clock_timestamp();
  v_source text;
  v_source_count bigint;
  v_accepted bigint;
  v_quarantined bigint;
  v_accepted_hash text;
  v_quarantine_hash text;
  v_source_hash text;
begin
  foreach v_source in array array[
    'ledger_entries', 'period_locks'
  ]
  loop
    select count(*), pg_catalog.encode(extensions.digest(coalesce(
      pg_catalog.string_agg(
        source.source_id::text || '|' || source.payload_sha256,
        E'\n' order by source.source_id
      ), ''
    ), 'sha256'), 'hex')
    into v_source_count, v_source_hash
    from backend_system.ledger_migration_source_rows source
    where source.run_id = v_run_id and source.source_table = v_source;

    if v_source = 'ledger_entries' then
      select count(*), pg_catalog.encode(extensions.digest(coalesce(
        pg_catalog.string_agg(
          id::text || '|' || pg_catalog.to_jsonb(entry)::text,
          E'\n' order by id
        ), ''
      ), 'sha256'), 'hex')
      into v_accepted, v_accepted_hash
      from ledger.entries entry;
    else
      select count(*), pg_catalog.encode(extensions.digest(coalesce(
        pg_catalog.string_agg(
          id::text || '|' || pg_catalog.to_jsonb(period_lock)::text,
          E'\n' order by id
        ), ''
      ), 'sha256'), 'hex')
      into v_accepted, v_accepted_hash
      from ledger.period_locks period_lock;
    end if;

    select count(*), pg_catalog.encode(extensions.digest(coalesce(
      pg_catalog.string_agg(
        source.source_id::text || '|' || source.payload_sha256,
        E'\n' order by source.source_id
      ), ''
    ), 'sha256'), 'hex')
    into v_quarantined, v_quarantine_hash
    from backend_system.ledger_migration_source_rows source
    join backend_system.ledger_migration_quarantine quarantine
      on quarantine.run_id = source.run_id
      and quarantine.source_table = source.source_table
      and quarantine.source_id = source.source_id
    where source.run_id = v_run_id and source.source_table = v_source;

    insert into backend_system.ledger_migration_reconciliations (
      run_id, source_table, source_row_count, accepted_row_count,
      quarantined_row_count, source_sha256, accepted_sha256,
      quarantine_sha256, recorded_at
    ) values (
      v_run_id, v_source, v_source_count, v_accepted,
      v_quarantined, v_source_hash, v_accepted_hash,
      v_quarantine_hash, v_run_at
    );
  end loop;
  update backend_system.ledger_migration_runs
  set completed_at = v_run_at
  where id = v_run_id;
end
$ledger_reconcile$;

-- Company access owns this versioned authorization query. Ledger policies and
-- commands consume the contract and never read company-access tables directly.
create or replace function public.company_access_company_year_allows_consequential_v1(
  p_company_id uuid,
  p_income_year integer
)
returns boolean
language plpgsql
volatile
security definer
set search_path = ''
as $function$
declare
  v_admission_id uuid;
begin
  if not public.company_access_is_accepted_owner_v1(p_company_id)
    or coalesce(public.company_access_auth_jwt_v1() ->> 'aal', '') <> 'aal2'
    or not public.company_access_has_current_agreement_v1(p_company_id)
  then
    return false;
  end if;

  select admission.id into v_admission_id
  from public.company_year_admissions admission
  where admission.company_id = p_company_id
    and admission.accounting_year = p_income_year;
  if v_admission_id is null then
    return false;
  end if;

  -- Serialize with eligibility rechecks so a consequential command cannot
  -- observe an assessment that is being superseded in the same instant.
  perform pg_catalog.pg_advisory_xact_lock(
    pg_catalog.hashtextextended(
      'eligibility-recheck|' || v_admission_id::text,
      187
    )
  );

  return exists (
    select 1
    from public.company_year_admissions admission
    join public.company_year_acceptances acceptance
      on acceptance.company_year_admission_id = admission.id
      and acceptance.company_id = admission.company_id
      and acceptance.accounting_year = admission.accounting_year
    join lateral (
      select assessment.decision,
        assessment.consequential_operations_allowed,
        assessment.capability_manifest_version,
        assessment.capability_manifest_sha256
      from public.company_eligibility_assessments assessment
      where assessment.company_id = admission.company_id
        and assessment.accounting_year = admission.accounting_year
      order by assessment.assessed_at desc, assessment.id desc
      limit 1
    ) current_assessment on true
    where admission.id = v_admission_id
      and current_assessment.decision = 'supported'
      and current_assessment.consequential_operations_allowed
      and current_assessment.capability_manifest_version
        = admission.capability_manifest_version
      and current_assessment.capability_manifest_sha256
        = admission.capability_manifest_sha256
      and acceptance.capability_manifest_version
        = admission.capability_manifest_version
      and acceptance.capability_manifest_sha256
        = admission.capability_manifest_sha256
  );
end;
$function$;

do $company_access_contract_owner$
begin
  execute pg_catalog.format('grant company_access_executor to %I', current_user);
  grant create on schema public to company_access_executor;
  alter function public.company_access_company_year_allows_consequential_v1(
    uuid, integer
  ) owner to company_access_executor;
  revoke create on schema public from company_access_executor;
  execute pg_catalog.format('revoke company_access_executor from %I', current_user);
end
$company_access_contract_owner$;
revoke all on function public.company_access_company_year_allows_consequential_v1(
  uuid, integer
) from public, anon, authenticated, service_role, ledger_executor;
grant execute on function public.company_access_company_year_allows_consequential_v1(
  uuid, integer
) to ledger_store_owner;

alter table ledger.entries enable row level security;
alter table ledger.entries force row level security;
alter table ledger.period_locks enable row level security;
alter table ledger.period_locks force row level security;
alter table backend_system.ledger_command_receipts enable row level security;
alter table backend_system.ledger_command_receipts force row level security;
alter table backend_system.ledger_workflow_receipts enable row level security;
alter table backend_system.ledger_workflow_receipts force row level security;

grant usage on schema public to ledger_store_owner;
grant execute on function
  public.company_access_auth_uid_v1(),
  public.company_access_auth_jwt_v1(),
  public.company_access_has_current_agreement_v1(uuid),
  public.company_access_is_accepted_owner_v1(uuid),
  public.company_access_is_accepted_member_v1(uuid)
to ledger_store_owner;
grant select, insert on ledger.entries, ledger.period_locks
to ledger_store_owner;
grant select, insert on backend_system.ledger_command_receipts
to ledger_store_owner;
grant usage on schema public, ledger to ledger_workflow_store_owner;
grant execute on function
  public.company_access_auth_uid_v1(),
  public.company_access_auth_jwt_v1(),
  public.company_access_has_current_agreement_v1(uuid),
  public.company_access_is_accepted_owner_v1(uuid),
  public.company_access_is_accepted_member_v1(uuid),
  public.company_access_company_year_allows_consequential_v1(uuid, integer)
to ledger_workflow_store_owner;
grant select, insert on public.opening_balance_setups,
  public.opening_shareholders
to ledger_workflow_store_owner;
grant select, insert on backend_system.ledger_workflow_receipts
to ledger_workflow_store_owner;
grant select on backend_system.ledger_cursor_signing_keys
to ledger_store_owner;
revoke all on ledger.entries, ledger.period_locks
from ledger_executor, talli_ledger_backend;
revoke all on backend_system.ledger_command_receipts,
  backend_system.ledger_workflow_receipts,
  backend_system.ledger_cursor_signing_keys,
  backend_system.ledger_migration_runs,
  backend_system.ledger_migration_source_rows,
  backend_system.ledger_migration_reconciliations,
  backend_system.ledger_migration_quarantine
from ledger_executor, talli_ledger_backend;

drop policy if exists "ledger workflow reads receipts"
  on backend_system.ledger_workflow_receipts;
create policy "ledger workflow reads receipts"
on backend_system.ledger_workflow_receipts for select
to ledger_workflow_store_owner
using (
  actor_id = public.company_access_auth_uid_v1()
  and public.company_access_is_accepted_owner_v1(company_id)
);
drop policy if exists "ledger workflow appends receipts"
  on backend_system.ledger_workflow_receipts;
create policy "ledger workflow appends receipts"
on backend_system.ledger_workflow_receipts for insert
to ledger_workflow_store_owner
with check (
  actor_id = public.company_access_auth_uid_v1()
  and public.company_access_is_accepted_owner_v1(company_id)
);

drop policy if exists "ledger workflow creates opening setups"
  on public.opening_balance_setups;
create policy "ledger workflow creates opening setups"
on public.opening_balance_setups for insert to ledger_workflow_store_owner
with check (
  created_by = public.company_access_auth_uid_v1()
  and public.company_access_is_accepted_owner_v1(company_id)
);
drop policy if exists "ledger workflow reads opening setups"
  on public.opening_balance_setups;
create policy "ledger workflow reads opening setups"
on public.opening_balance_setups for select to ledger_workflow_store_owner
using (public.company_access_is_accepted_member_v1(company_id));
drop policy if exists "ledger workflow creates opening shareholders"
  on public.opening_shareholders;
create policy "ledger workflow creates opening shareholders"
on public.opening_shareholders for insert to ledger_workflow_store_owner
with check (
  created_by = public.company_access_auth_uid_v1()
  and public.company_access_is_accepted_owner_v1(company_id)
);
drop policy if exists "ledger workflow reads opening shareholders"
  on public.opening_shareholders;
create policy "ledger workflow reads opening shareholders"
on public.opening_shareholders for select to ledger_workflow_store_owner
using (public.company_access_is_accepted_member_v1(company_id));
drop policy if exists "ledger store reads entries" on ledger.entries;
create policy "ledger store reads entries"
on ledger.entries for select to ledger_store_owner
using (public.company_access_is_accepted_member_v1(company_id));

drop policy if exists "ledger store posts entries" on ledger.entries;
create policy "ledger store posts entries"
on ledger.entries for insert to ledger_store_owner
with check (
  created_by = public.company_access_auth_uid_v1()
  and public.company_access_is_accepted_owner_v1(company_id)
  and public.company_access_company_year_allows_consequential_v1(
    company_id, income_year
  )
);

drop policy if exists "ledger store reads period locks" on ledger.period_locks;
create policy "ledger store reads period locks"
on ledger.period_locks for select to ledger_store_owner
using (public.company_access_is_accepted_member_v1(company_id));

drop policy if exists "ledger store creates period locks" on ledger.period_locks;
create policy "ledger store creates period locks"
on ledger.period_locks for insert to ledger_store_owner
with check (
  locked_by = public.company_access_auth_uid_v1()
  and public.company_access_is_accepted_owner_v1(company_id)
  and public.company_access_company_year_allows_consequential_v1(
    company_id, income_year
  )
);

drop policy if exists "ledger store reads command receipts"
  on backend_system.ledger_command_receipts;
create policy "ledger store reads command receipts"
on backend_system.ledger_command_receipts for select to ledger_store_owner
using (
  actor_id = public.company_access_auth_uid_v1()
  and public.company_access_is_accepted_owner_v1(company_id)
);
drop policy if exists "ledger store appends command receipts"
  on backend_system.ledger_command_receipts;
create policy "ledger store appends command receipts"
on backend_system.ledger_command_receipts for insert to ledger_store_owner
with check (
  actor_id = public.company_access_auth_uid_v1()
  and public.company_access_is_accepted_owner_v1(company_id)
);

create or replace function backend_system.prevent_ledger_technical_mutation()
returns trigger
language plpgsql
set search_path = ''
as $function$
begin
  raise exception 'ledger_technical_evidence_is_immutable';
end;
$function$;

drop trigger if exists ledger_command_receipts_immutable
  on backend_system.ledger_command_receipts;
create trigger ledger_command_receipts_immutable
before update or delete on backend_system.ledger_command_receipts
for each row execute function backend_system.prevent_ledger_technical_mutation();
drop trigger if exists ledger_workflow_receipts_immutable
  on backend_system.ledger_workflow_receipts;
create trigger ledger_workflow_receipts_immutable
before update or delete on backend_system.ledger_workflow_receipts
for each row execute function backend_system.prevent_ledger_technical_mutation();
drop trigger if exists ledger_cursor_signing_keys_immutable
  on backend_system.ledger_cursor_signing_keys;
create trigger ledger_cursor_signing_keys_immutable
before update or delete on backend_system.ledger_cursor_signing_keys
for each row execute function backend_system.prevent_ledger_technical_mutation();
drop trigger if exists ledger_migration_source_rows_immutable
  on backend_system.ledger_migration_source_rows;
create trigger ledger_migration_source_rows_immutable
before update or delete on backend_system.ledger_migration_source_rows
for each row execute function backend_system.prevent_ledger_technical_mutation();
drop trigger if exists ledger_migration_quarantine_immutable
  on backend_system.ledger_migration_quarantine;
create trigger ledger_migration_quarantine_immutable
before update or delete on backend_system.ledger_migration_quarantine
for each row execute function backend_system.prevent_ledger_technical_mutation();
drop trigger if exists ledger_migration_reconciliations_immutable
  on backend_system.ledger_migration_reconciliations;
create trigger ledger_migration_reconciliations_immutable
before update or delete on backend_system.ledger_migration_reconciliations
for each row execute function backend_system.prevent_ledger_technical_mutation();

create or replace function backend_system.claim_ledger_workflow_v1(
  p_operation_name text,
  p_idempotency_key text,
  p_company_id uuid,
  p_request jsonb,
  p_verified_subject text
)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $function$
declare
  v_actor_id uuid := public.company_access_auth_uid_v1();
  v_fingerprint text;
  v_receipt backend_system.ledger_workflow_receipts%rowtype;
begin
  if v_actor_id is null
    or p_verified_subject is null
    or p_verified_subject !~ '^[0-9a-fA-F-]{36}$'
    or v_actor_id is distinct from p_verified_subject::uuid
  then
    raise exception 'ledger_forbidden';
  end if;
  if p_operation_name <> 'new_year_start'
    or p_company_id is null
    or coalesce(p_idempotency_key, '') !~ '^[A-Za-z0-9._:-]{16,255}$'
    or pg_catalog.jsonb_typeof(p_request) is distinct from 'object'
  then
    raise exception 'ledger_invalid_input';
  end if;
  if not public.company_access_is_accepted_member_v1(p_company_id) then
    raise exception 'ledger_not_found';
  end if;
  if not public.company_access_is_accepted_owner_v1(p_company_id) then
    raise exception 'ledger_forbidden';
  end if;

  v_fingerprint := pg_catalog.encode(
    extensions.digest(p_request::text, 'sha256'), 'hex'
  );
  if not pg_catalog.pg_try_advisory_xact_lock(pg_catalog.hashtextextended(
    'ledger-workflow:v1:' || v_actor_id::text || ':' || p_company_id::text
      || ':' || p_operation_name || ':' || p_idempotency_key,
    0
  )) then
    raise exception 'ledger_idempotency_in_progress';
  end if;

  select receipt.* into v_receipt
  from backend_system.ledger_workflow_receipts receipt
  where receipt.api_major = 'v1'
    and receipt.actor_id = v_actor_id
    and receipt.company_id = p_company_id
    and receipt.operation_name = p_operation_name
    and receipt.idempotency_key = p_idempotency_key;
  if not found then
    return null;
  end if;
  if v_receipt.request_fingerprint <> v_fingerprint then
    raise exception 'ledger_idempotency_key_reused';
  end if;
  return v_receipt.result;
end;
$function$;

create or replace function backend_system.record_opening_snapshot_legacy_v1(
  p_company_id uuid,
  p_income_year integer,
  p_bank_balance numeric,
  p_share_capital numeric,
  p_share_count integer,
  p_nominal_value numeric,
  p_shareholders jsonb,
  p_verified_subject text
)
returns uuid
language plpgsql
security definer
set search_path = ''
as $function$
declare
  v_actor_id uuid := public.company_access_auth_uid_v1();
  v_setup_id uuid := pg_catalog.gen_random_uuid();
  v_shareholder jsonb;
  v_name text;
  v_kind text;
  v_national_id text;
  v_org_number text;
  v_shares integer;
  v_total_shares bigint := 0;
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
    or p_bank_balance is null or p_bank_balance < 0
    or p_bank_balance <> pg_catalog.round(p_bank_balance, 2)
    or p_share_capital is null or p_share_capital < 0
    or p_share_capital <> pg_catalog.round(p_share_capital, 2)
    or p_share_count is null or p_share_count <= 0
    or p_nominal_value is null or p_nominal_value <= 0
    or p_nominal_value <> pg_catalog.round(p_nominal_value, 2)
    or p_share_capital <> pg_catalog.round(p_share_count * p_nominal_value, 2)
    or pg_catalog.jsonb_typeof(p_shareholders) is distinct from 'array'
    or pg_catalog.jsonb_array_length(p_shareholders) not between 1 and 100
  then
    raise exception 'ledger_invalid_input';
  end if;
  if not public.company_access_is_accepted_member_v1(p_company_id) then
    raise exception 'ledger_not_found';
  end if;
  if not public.company_access_is_accepted_owner_v1(p_company_id) then
    raise exception 'ledger_forbidden';
  end if;
  -- Every ledger writer takes the company-year lock before the eligibility
  -- recheck lock. Keeping this order identical to ledger.post_entry prevents
  -- a new-year workflow and another posting from deadlocking each other.
  perform ledger.lock_company_year_v1(p_company_id, p_income_year);
  if coalesce(public.company_access_auth_jwt_v1() ->> 'aal', '') <> 'aal2'
    or not public.company_access_company_year_allows_consequential_v1(
      p_company_id, p_income_year
    )
  then
    raise exception 'ledger_company_year_not_admitted';
  end if;

  if exists (
    select 1 from public.opening_balance_setups setup
    where setup.company_id = p_company_id
      and setup.income_year = p_income_year
  ) then
    raise exception 'ledger_opening_already_exists';
  end if;

  for v_shareholder in
    select value from pg_catalog.jsonb_array_elements(p_shareholders)
  loop
    if pg_catalog.jsonb_typeof(v_shareholder) is distinct from 'object'
      or pg_catalog.jsonb_typeof(v_shareholder -> 'name') is distinct from 'string'
      or pg_catalog.jsonb_typeof(v_shareholder -> 'shareholderKind')
        is distinct from 'string'
      or pg_catalog.jsonb_typeof(v_shareholder -> 'shareCount')
        is distinct from 'number'
      or (v_shareholder ->> 'shareCount') !~ '^[0-9]+$'
    then
      raise exception 'ledger_invalid_input';
    end if;
    v_name := pg_catalog.btrim(v_shareholder ->> 'name');
    v_kind := v_shareholder ->> 'shareholderKind';
    v_national_id := nullif(pg_catalog.btrim(
      coalesce(v_shareholder ->> 'nationalId', '')
    ), '');
    v_org_number := nullif(pg_catalog.btrim(
      coalesce(v_shareholder ->> 'orgNumber', '')
    ), '');
    v_shares := (v_shareholder ->> 'shareCount')::integer;
    if v_name = '' or pg_catalog.char_length(v_name) > 255
      or v_kind not in ('norwegian_person', 'norwegian_company')
      or v_shares < 0
      or (v_kind = 'norwegian_person' and coalesce(v_national_id, '') !~ '^[0-9]{11}$')
      or (v_kind = 'norwegian_company' and coalesce(v_org_number, '') !~ '^[0-9]{9}$')
    then
      raise exception 'ledger_invalid_input';
    end if;
    v_total_shares := v_total_shares + v_shares;
  end loop;
  if v_total_shares <> p_share_count then
    raise exception 'ledger_invalid_input';
  end if;

  insert into public.opening_balance_setups (
    id, company_id, income_year, bank_balance, share_capital,
    share_count, nominal_value, created_by
  ) values (
    v_setup_id, p_company_id, p_income_year, p_bank_balance, p_share_capital,
    p_share_count, p_nominal_value, v_actor_id
  );
  insert into public.opening_shareholders (
    setup_id, company_id, name, shareholder_kind, national_id,
    org_number, share_count, created_by
  )
  select
    v_setup_id,
    p_company_id,
    pg_catalog.btrim(value ->> 'name'),
    value ->> 'shareholderKind',
    nullif(pg_catalog.btrim(coalesce(value ->> 'nationalId', '')), ''),
    nullif(pg_catalog.btrim(coalesce(value ->> 'orgNumber', '')), ''),
    (value ->> 'shareCount')::integer,
    v_actor_id
  from pg_catalog.jsonb_array_elements(p_shareholders);
  return v_setup_id;
end;
$function$;

-- Read-only compatibility projection for the still-legacy opening tables. The
-- active ledger stage names the returned compatibility facts outside the
-- frozen future capability contract and leaves filing policy unchanged.
create or replace function backend_system.list_opening_snapshots_legacy_v1(
  p_company_ids uuid[],
  p_cursor text,
  p_limit integer,
  p_verified_subject text
)
returns table (items jsonb, next_cursor text, has_more boolean)
language plpgsql
stable
security definer
set search_path = ''
as $function$
declare
  v_actor_id uuid := public.company_access_auth_uid_v1();
  v_company_count integer;
  v_distinct_company_count integer;
  v_cursor_created_at timestamptz;
  v_cursor_id uuid;
  v_encoded text;
  v_signature text;
  v_payload jsonb;
  v_key_id uuid;
  v_issued_at timestamptz;
  v_companies text;
  v_company_hash text;
  v_count integer;
  v_last_created_at timestamptz;
  v_last_id uuid;
begin
  if v_actor_id is null
    or p_verified_subject is null
    or p_verified_subject !~ '^[0-9a-fA-F-]{36}$'
    or v_actor_id is distinct from p_verified_subject::uuid
  then
    raise exception 'ledger_forbidden';
  end if;
  if p_company_ids is null
    or pg_catalog.cardinality(p_company_ids) = 0
    or pg_catalog.cardinality(p_company_ids) > 100
    or p_limit is null
    or p_limit < 1 or p_limit > 100
    or (p_cursor is not null and pg_catalog.length(p_cursor) > 4096)
  then
    raise exception 'ledger_invalid_input';
  end if;
  select pg_catalog.count(company_id), pg_catalog.count(distinct company_id)
  into v_company_count, v_distinct_company_count
  from pg_catalog.unnest(p_company_ids) company_id;
  if v_company_count <> pg_catalog.cardinality(p_company_ids)
    or v_distinct_company_count <> v_company_count
  then
    raise exception 'ledger_invalid_input';
  end if;

  select coalesce(
    pg_catalog.string_agg(company_id::text, ',' order by company_id), ''
  ) into v_companies
  from pg_catalog.unnest(p_company_ids) company_id;
  v_company_hash := pg_catalog.encode(
    extensions.digest(v_companies, 'sha256'), 'hex'
  );

  if p_cursor is not null then
    begin
      v_encoded := pg_catalog.split_part(p_cursor, '.', 1);
      v_signature := pg_catalog.split_part(p_cursor, '.', 2);
      if v_encoded = '' or v_signature !~ '^[0-9a-f]{64}$'
        or pg_catalog.split_part(p_cursor, '.', 3) <> ''
      then
        raise exception 'ledger_invalid_cursor';
      end if;
      v_payload := pg_catalog.convert_from(pg_catalog.decode(
        pg_catalog.translate(v_encoded, '-_', '+/') ||
          pg_catalog.repeat(
            '=', (4 - pg_catalog.length(v_encoded) % 4) % 4
          ),
        'base64'
      ), 'UTF8')::jsonb;
      v_key_id := (v_payload ->> 'kid')::uuid;
      v_issued_at := (v_payload ->> 'issuedAt')::timestamptz;
      if ledger.cursor_secret_v1(v_key_id) is null
        or v_signature <> pg_catalog.encode(extensions.hmac(
          v_encoded, ledger.cursor_secret_v1(v_key_id), 'sha256'
        ), 'hex')
        or v_issued_at < pg_catalog.statement_timestamp() - interval '7 days'
        or v_issued_at > pg_catalog.statement_timestamp() + interval '5 minutes'
        or v_payload ->> 'resource' <> 'opening_snapshots'
        or v_payload ->> 'companies' <> v_company_hash
      then
        raise exception 'ledger_invalid_cursor';
      end if;
      v_cursor_created_at := (v_payload ->> 'createdAt')::timestamptz;
      v_cursor_id := (v_payload ->> 'id')::uuid;
    exception
      when others then
        raise exception 'ledger_invalid_cursor';
    end;
  end if;

  select pg_catalog.count(*) into v_count
  from (
    select setup.id
    from public.opening_balance_setups setup
    where setup.company_id = any(p_company_ids)
      and public.company_access_is_accepted_member_v1(setup.company_id)
      and (
        p_cursor is null
        or (setup.created_at, setup.id)
          < (v_cursor_created_at, v_cursor_id)
      )
    order by setup.created_at desc, setup.id desc
    limit p_limit + 1
  ) visible;
  has_more := v_count > p_limit;

  if exists (
    select 1
    from (
      select setup.bank_balance, setup.share_capital, setup.nominal_value
      from public.opening_balance_setups setup
      where setup.company_id = any(p_company_ids)
        and public.company_access_is_accepted_member_v1(setup.company_id)
        and (
          p_cursor is null
          or (setup.created_at, setup.id)
            < (v_cursor_created_at, v_cursor_id)
        )
      order by setup.created_at desc, setup.id desc
      limit p_limit
    ) page_setup
    where page_setup.bank_balance <> pg_catalog.round(page_setup.bank_balance, 2)
      or page_setup.share_capital <> pg_catalog.round(page_setup.share_capital, 2)
      or page_setup.nominal_value <> pg_catalog.round(page_setup.nominal_value, 2)
  ) then
    raise exception 'ledger_dependency_unavailable';
  end if;

  if exists (
    select 1
    from (
      select setup.id
      from public.opening_balance_setups setup
      where setup.company_id = any(p_company_ids)
        and public.company_access_is_accepted_member_v1(setup.company_id)
        and (
          p_cursor is null
          or (setup.created_at, setup.id)
            < (v_cursor_created_at, v_cursor_id)
        )
      order by setup.created_at desc, setup.id desc
      limit p_limit
    ) page_setup
    where exists (
      select 1
      from public.opening_shareholders shareholder
      where shareholder.setup_id = page_setup.id
      offset 100 limit 1
    )
  ) then
    raise exception 'ledger_dependency_unavailable';
  end if;

  select coalesce(
    pg_catalog.jsonb_agg(snapshot.item order by snapshot.created_at desc, snapshot.id desc),
    '[]'::jsonb
  )
  into items
  from (
    select
      setup.created_at,
      setup.id,
      pg_catalog.jsonb_build_object(
        'setupId', setup.id,
        'companyId', setup.company_id,
        'incomeYear', setup.income_year,
        'bankBalance', setup.bank_balance::text,
        'shareCapital', setup.share_capital::text,
        'shareCount', setup.share_count,
        'nominalValue', setup.nominal_value::text,
        'lockedAt', setup.locked_at,
        'createdAt', setup.created_at,
        'createdBy', setup.created_by,
        'shareholders', (
          select coalesce(
            pg_catalog.jsonb_agg(
              pg_catalog.jsonb_build_object(
                'shareholderId', shareholder.id,
                'setupId', shareholder.setup_id,
                'companyId', shareholder.company_id,
                'name', shareholder.name,
                'shareholderKind', shareholder.shareholder_kind,
                'nationalId', shareholder.national_id,
                'orgNumber', shareholder.org_number,
                'shareCount', shareholder.share_count
              ) order by shareholder.id
            ),
            '[]'::jsonb
          )
          from (
            select shareholder.*
            from public.opening_shareholders shareholder
            where shareholder.setup_id = setup.id
            order by shareholder.id
            limit 101
          ) shareholder
        )
      ) item
    from public.opening_balance_setups setup
    where setup.company_id = any(p_company_ids)
      and public.company_access_is_accepted_member_v1(setup.company_id)
      and (
        p_cursor is null
        or (setup.created_at, setup.id)
          < (v_cursor_created_at, v_cursor_id)
      )
    order by setup.created_at desc, setup.id desc
    limit p_limit
  ) snapshot;

  if has_more and pg_catalog.jsonb_array_length(items) > 0 then
    select setup.created_at, setup.id
    into v_last_created_at, v_last_id
    from public.opening_balance_setups setup
    where setup.company_id = any(p_company_ids)
      and public.company_access_is_accepted_member_v1(setup.company_id)
      and (
        p_cursor is null
        or (setup.created_at, setup.id)
          < (v_cursor_created_at, v_cursor_id)
      )
    order by setup.created_at desc, setup.id desc
    offset p_limit - 1 limit 1;
    next_cursor := ledger.cursor_encode_v1(
      'opening_snapshots', p_company_ids, v_last_created_at, v_last_id
    );
  else
    next_cursor := null;
  end if;
  return next;
end;
$function$;

create or replace function backend_system.complete_ledger_workflow_v1(
  p_operation_name text,
  p_idempotency_key text,
  p_company_id uuid,
  p_request jsonb,
  p_result jsonb,
  p_verified_subject text
)
returns void
language plpgsql
security definer
set search_path = ''
as $function$
declare
  v_actor_id uuid := public.company_access_auth_uid_v1();
  v_fingerprint text;
begin
  if v_actor_id is null
    or p_verified_subject is null
    or p_verified_subject !~ '^[0-9a-fA-F-]{36}$'
    or v_actor_id is distinct from p_verified_subject::uuid
    or p_operation_name <> 'new_year_start'
    or p_company_id is null
    or coalesce(p_idempotency_key, '') !~ '^[A-Za-z0-9._:-]{16,255}$'
    or pg_catalog.jsonb_typeof(p_request) is distinct from 'object'
    or pg_catalog.jsonb_typeof(p_result) is distinct from 'object'
  then
    raise exception 'ledger_invalid_input';
  end if;
  v_fingerprint := pg_catalog.encode(
    extensions.digest(p_request::text, 'sha256'), 'hex'
  );
  insert into backend_system.ledger_workflow_receipts (
    api_major, actor_id, company_id, operation_name, idempotency_key,
    request_fingerprint, result
  ) values (
    'v1', v_actor_id, p_company_id, p_operation_name, p_idempotency_key,
    v_fingerprint, p_result
  );
end;
$function$;

create or replace function ledger.lock_company_year_v1(
  p_company_id uuid,
  p_income_year integer
)
returns void
language plpgsql
security definer
set search_path = ''
as $function$
begin
  if p_company_id is null or p_income_year not between 2000 and 2100 then
    raise exception 'ledger_invalid_input';
  end if;
  perform pg_catalog.pg_advisory_xact_lock(
    pg_catalog.hashtextextended(p_company_id::text || ':' || p_income_year::text, 0)
  );
end;
$function$;

create or replace function ledger.post_entry(
  p_idempotency_key text,
  p_company_id uuid,
  p_income_year integer,
  p_entry_kind text,
  p_memo text,
  p_lines jsonb,
  p_risk_flags jsonb,
  p_warning_accepted boolean,
  p_source_capability text,
  p_source_record_id text,
  p_correlation_id text,
  p_verified_subject text
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
  v_receipt backend_system.ledger_command_receipts%rowtype;
  v_entry_id uuid;
  v_posted_at timestamptz;
  v_computed_fingerprint text;
  v_result jsonb;
begin
  if v_actor_id is null
    or p_verified_subject is null
    or p_verified_subject !~ '^[0-9a-fA-F-]{36}$'
    or v_actor_id is distinct from p_verified_subject::uuid
  then
    raise exception 'ledger_forbidden';
  end if;
  if p_company_id is null or p_income_year not between 2000 and 2100
    or coalesce(p_idempotency_key, '') !~ '^[A-Za-z0-9._:-]{16,255}$'
    or pg_catalog.btrim(coalesce(p_memo, '')) = ''
    or pg_catalog.btrim(coalesce(p_source_record_id, '')) = ''
    or pg_catalog.btrim(coalesce(p_correlation_id, '')) = ''
    or p_source_capability not in (
      'LEDGER', 'BANKING', 'INVESTMENTS', 'CORPORATE_GOVERNANCE',
      'COMPANY_TAX_FILING', 'SHAREHOLDER_REGISTER_FILING'
    )
    or pg_catalog.upper(coalesce(p_entry_kind, '')) not in (
      'OPENING_BALANCE', 'ADMINISTRATIVE_COST', 'MANUAL_JOURNAL',
      'BANK_RULE_SUGGESTION', 'DIVIDEND_RECEIVED',
      'OWNER_DIVIDEND_DECLARED', 'OWNER_DIVIDEND_PAYMENT', 'SHARE_PURCHASE',
      'SHARE_SALE', 'SHAREHOLDER_LOAN', 'TAX_SETTLEMENT',
      'BANK_INTEREST', 'BANK_LOAN', 'CAPITAL_INCREASE',
      'COMPANY_TAX_ACCRUAL', 'GROUP_CONTRIBUTION'
    )
    or pg_catalog.jsonb_typeof(p_risk_flags) is distinct from 'array'
    or not ledger.entry_lines_are_valid_v1(p_lines, false)
  then
    raise exception 'ledger_invalid_input';
  end if;

  if not public.company_access_is_accepted_member_v1(p_company_id) then
    raise exception 'ledger_not_found';
  end if;
  if not public.company_access_is_accepted_owner_v1(p_company_id) then
    raise exception 'ledger_forbidden';
  end if;

  v_computed_fingerprint := pg_catalog.encode(extensions.digest(
    pg_catalog.jsonb_build_object(
      'companyId', p_company_id,
      'incomeYear', p_income_year,
      'entryKind', pg_catalog.upper(p_entry_kind),
      'memo', pg_catalog.btrim(p_memo),
      'lines', ledger.normalize_lines_v1(p_lines),
      'riskFlags', p_risk_flags,
      'warningAccepted', p_warning_accepted,
      'sourceCapability', p_source_capability,
      'sourceRecordId', pg_catalog.btrim(p_source_record_id)
    )::text,
    'sha256'
  ), 'hex');
  if not pg_catalog.pg_try_advisory_xact_lock(pg_catalog.hashtextextended(
    'ledger:v1:' || v_actor_id::text || ':' || p_company_id::text
      || ':post_entry:' || p_idempotency_key,
    0
  )) then
    raise exception 'ledger_idempotency_in_progress';
  end if;

  select receipt.* into v_receipt
  from backend_system.ledger_command_receipts receipt
  where receipt.api_major = 'v1'
    and receipt.actor_id = v_actor_id
    and receipt.company_id = p_company_id
    and receipt.operation_name = 'post_entry'
    and receipt.idempotency_key = p_idempotency_key;
  if found then
    if v_receipt.request_fingerprint <> v_computed_fingerprint then
      raise exception 'ledger_idempotency_key_reused';
    end if;
    return query select
      (v_receipt.result ->> 'ledger_entry_id')::uuid,
      (v_receipt.result ->> 'company_id')::uuid,
      (v_receipt.result ->> 'income_year')::integer,
      v_receipt.result ->> 'entry_kind',
      (v_receipt.result ->> 'posted_at')::timestamptz,
      true as replayed;
    return;
  end if;

  perform ledger.lock_company_year_v1(p_company_id, p_income_year);
  if not public.company_access_company_year_allows_consequential_v1(
    p_company_id, p_income_year
  ) then
    raise exception 'ledger_company_year_not_admitted';
  end if;

  if exists (
    select 1 from ledger.period_locks period_lock
    where period_lock.company_id = p_company_id
      and period_lock.income_year = p_income_year
  ) then
    raise exception 'ledger_period_locked';
  end if;
  if exists (
    select 1 from ledger.entries entry
    where entry.company_id = p_company_id
      and entry.source_capability = p_source_capability
      and entry.source_record_id = p_source_record_id
  ) then
    raise exception 'ledger_idempotency_key_reused';
  end if;
  if pg_catalog.upper(p_entry_kind) = 'OPENING_BALANCE' and exists (
    select 1 from ledger.entries entry
    where entry.company_id = p_company_id
      and entry.income_year = p_income_year
      and entry.entry_kind = 'OPENING_BALANCE'
  ) then
    raise exception 'ledger_opening_already_exists';
  end if;

  v_entry_id := pg_catalog.gen_random_uuid();
  v_posted_at := pg_catalog.statement_timestamp();

  insert into ledger.entries (
    id, company_id, income_year, entry_kind, memo, lines, risk_flags,
    warning_accepted_by, warning_accepted_at, posted_at, created_by, created_at,
    source_capability, source_record_id, correlation_id
  ) values (
    v_entry_id, p_company_id, p_income_year, pg_catalog.upper(p_entry_kind),
    pg_catalog.btrim(p_memo), ledger.normalize_lines_v1(p_lines),
    p_risk_flags,
    case when p_warning_accepted then v_actor_id else null end,
    case when p_warning_accepted then v_posted_at else null end,
    v_posted_at, v_actor_id, v_posted_at,
    p_source_capability, pg_catalog.btrim(p_source_record_id),
    pg_catalog.btrim(p_correlation_id)
  );

  v_result := pg_catalog.jsonb_build_object(
    'ledger_entry_id', v_entry_id,
    'company_id', p_company_id,
    'income_year', p_income_year,
    'entry_kind', pg_catalog.upper(p_entry_kind),
    'posted_at', v_posted_at
  );
  insert into backend_system.ledger_command_receipts (
    api_major, actor_id, company_id, operation_name, idempotency_key,
    request_fingerprint, result
  ) values (
    'v1', v_actor_id, p_company_id, 'post_entry', p_idempotency_key,
    v_computed_fingerprint, v_result
  );

  return query select
    v_entry_id, p_company_id, p_income_year, pg_catalog.upper(p_entry_kind),
    v_posted_at, false as replayed;
end;
$function$;

create or replace function ledger.lock_period(
  p_idempotency_key text,
  p_company_id uuid,
  p_income_year integer,
  p_reason text,
  p_correlation_id text,
  p_verified_subject text
)
returns table (
  period_lock_id uuid,
  company_id uuid,
  income_year integer,
  reason text,
  locked_by uuid,
  locked_at timestamptz,
  replayed boolean
)
language plpgsql
security definer
set search_path = ''
as $function$
declare
  v_actor_id uuid := public.company_access_auth_uid_v1();
  v_receipt backend_system.ledger_command_receipts%rowtype;
  v_lock_id uuid;
  v_locked_at timestamptz;
  v_computed_fingerprint text;
  v_result jsonb;
begin
  if v_actor_id is null
    or p_verified_subject is null
    or p_verified_subject !~ '^[0-9a-fA-F-]{36}$'
    or v_actor_id is distinct from p_verified_subject::uuid
  then
    raise exception 'ledger_forbidden';
  end if;
  if p_company_id is null or p_income_year not between 2000 and 2100
    or coalesce(p_idempotency_key, '') !~ '^[A-Za-z0-9._:-]{16,255}$'
    or pg_catalog.btrim(coalesce(p_reason, '')) = ''
    or pg_catalog.btrim(coalesce(p_correlation_id, '')) = ''
  then
    raise exception 'ledger_invalid_input';
  end if;

  if not public.company_access_is_accepted_member_v1(p_company_id) then
    raise exception 'ledger_not_found';
  end if;
  if not public.company_access_is_accepted_owner_v1(p_company_id) then
    raise exception 'ledger_forbidden';
  end if;

  v_computed_fingerprint := pg_catalog.encode(extensions.digest(
    pg_catalog.jsonb_build_object(
      'companyId', p_company_id,
      'incomeYear', p_income_year,
      'reason', pg_catalog.btrim(p_reason)
    )::text,
    'sha256'
  ), 'hex');
  if not pg_catalog.pg_try_advisory_xact_lock(pg_catalog.hashtextextended(
    'ledger:v1:' || v_actor_id::text || ':' || p_company_id::text
      || ':lock_period:' || p_idempotency_key,
    0
  )) then
    raise exception 'ledger_idempotency_in_progress';
  end if;

  select receipt.* into v_receipt
  from backend_system.ledger_command_receipts receipt
  where receipt.api_major = 'v1'
    and receipt.actor_id = v_actor_id
    and receipt.company_id = p_company_id
    and receipt.operation_name = 'lock_period'
    and receipt.idempotency_key = p_idempotency_key;
  if found then
    if v_receipt.request_fingerprint <> v_computed_fingerprint then
      raise exception 'ledger_idempotency_key_reused';
    end if;
    return query select
      (v_receipt.result ->> 'period_lock_id')::uuid,
      (v_receipt.result ->> 'company_id')::uuid,
      (v_receipt.result ->> 'income_year')::integer,
      v_receipt.result ->> 'reason',
      (v_receipt.result ->> 'locked_by')::uuid,
      (v_receipt.result ->> 'locked_at')::timestamptz,
      true as replayed;
    return;
  end if;

  perform ledger.lock_company_year_v1(p_company_id, p_income_year);
  if not public.company_access_company_year_allows_consequential_v1(
    p_company_id, p_income_year
  ) then
    raise exception 'ledger_company_year_not_admitted';
  end if;

  if exists (
    select 1 from ledger.period_locks period_lock
    where period_lock.company_id = p_company_id
      and period_lock.income_year = p_income_year
  ) then
    raise exception 'ledger_period_locked';
  end if;

  v_lock_id := pg_catalog.gen_random_uuid();
  v_locked_at := pg_catalog.statement_timestamp();
  insert into ledger.period_locks (
    id, company_id, income_year, reason, locked_by, locked_at
  ) values (
    v_lock_id, p_company_id, p_income_year, pg_catalog.btrim(p_reason),
    v_actor_id, v_locked_at
  );

  v_result := pg_catalog.jsonb_build_object(
    'period_lock_id', v_lock_id,
    'company_id', p_company_id,
    'income_year', p_income_year,
    'reason', pg_catalog.btrim(p_reason),
    'locked_by', v_actor_id,
    'locked_at', v_locked_at
  );
  insert into backend_system.ledger_command_receipts (
    api_major, actor_id, company_id, operation_name, idempotency_key,
    request_fingerprint, result
  ) values (
    'v1', v_actor_id, p_company_id, 'lock_period', p_idempotency_key,
    v_computed_fingerprint, v_result
  );

  return query select
    v_lock_id, p_company_id, p_income_year, pg_catalog.btrim(p_reason),
    v_actor_id, v_locked_at, false as replayed;
end;
$function$;

create or replace function ledger.cursor_secret_v1(p_key_id uuid)
returns text
language sql
stable
security definer
set search_path = ''
as $function$
  select pg_catalog.encode(signing_key.secret, 'hex')
  from backend_system.ledger_cursor_signing_keys signing_key
  where signing_key.id = p_key_id;
$function$;

create or replace function ledger.cursor_encode_v1(
  p_resource text,
  p_company_ids uuid[],
  p_created_at timestamptz,
  p_id uuid
)
returns text
language plpgsql
stable
security definer
set search_path = ''
as $function$
declare
  v_key_id uuid;
  v_companies text;
  v_payload text;
  v_encoded text;
  v_signature text;
begin
  select signing_key.id into v_key_id
  from backend_system.ledger_cursor_signing_keys signing_key
  order by signing_key.created_at desc, signing_key.id desc
  limit 1;
  if v_key_id is null then
    raise exception 'ledger_invalid_cursor';
  end if;
  select coalesce(pg_catalog.string_agg(company_id::text, ',' order by company_id), '')
  into v_companies
  from pg_catalog.unnest(p_company_ids) company_id;
  v_payload := pg_catalog.jsonb_build_object(
    'resource', p_resource,
    'kid', v_key_id,
    'issuedAt', pg_catalog.statement_timestamp(),
    'companies', pg_catalog.encode(extensions.digest(v_companies, 'sha256'), 'hex'),
    'createdAt', p_created_at,
    'id', p_id
  )::text;
  v_encoded := pg_catalog.translate(
    pg_catalog.replace(
      pg_catalog.encode(pg_catalog.convert_to(v_payload, 'UTF8'), 'base64'),
      E'\n', ''
    ), '+/', '-_'
  );
  v_signature := pg_catalog.encode(extensions.hmac(
    v_encoded, ledger.cursor_secret_v1(v_key_id), 'sha256'
  ), 'hex');
  return v_encoded || '.' || v_signature;
end;
$function$;

create or replace function ledger.list_entries(
  p_company_ids uuid[],
  p_cursor text,
  p_limit integer,
  p_verified_subject text
)
returns table (items jsonb, next_cursor text, has_more boolean)
language plpgsql
security definer
set search_path = ''
as $function$
declare
  v_actor_id uuid := public.company_access_auth_uid_v1();
  v_cursor_created_at timestamptz;
  v_cursor_id uuid;
  v_encoded text;
  v_signature text;
  v_payload jsonb;
  v_key_id uuid;
  v_issued_at timestamptz;
  v_companies text;
  v_company_hash text;
  v_count integer;
  v_last_created_at timestamptz;
  v_last_id uuid;
begin
  if v_actor_id is null or p_verified_subject is null
    or p_verified_subject !~ '^[0-9a-fA-F-]{36}$'
    or v_actor_id is distinct from p_verified_subject::uuid
  then
    raise exception 'ledger_forbidden';
  end if;
  if p_limit is null or p_limit < 1 or p_limit > 100
    or p_company_ids is null or pg_catalog.cardinality(p_company_ids) = 0
    or pg_catalog.cardinality(p_company_ids) > 100
    or (p_cursor is not null and pg_catalog.length(p_cursor) > 4096)
  then
    raise exception 'ledger_invalid_input';
  end if;
  select coalesce(pg_catalog.string_agg(company_id::text, ',' order by company_id), '')
  into v_companies from pg_catalog.unnest(p_company_ids) company_id;
  v_company_hash := pg_catalog.encode(extensions.digest(v_companies, 'sha256'), 'hex');

  if p_cursor is not null then
    begin
      v_encoded := pg_catalog.split_part(p_cursor, '.', 1);
      v_signature := pg_catalog.split_part(p_cursor, '.', 2);
      if v_encoded = '' or v_signature !~ '^[0-9a-f]{64}$'
        or pg_catalog.split_part(p_cursor, '.', 3) <> '' then
        raise exception 'ledger_invalid_cursor';
      end if;
      v_payload := pg_catalog.convert_from(pg_catalog.decode(
        pg_catalog.translate(v_encoded, '-_', '+/') ||
          pg_catalog.repeat('=', (4 - pg_catalog.length(v_encoded) % 4) % 4),
        'base64'
      ), 'UTF8')::jsonb;
      v_key_id := (v_payload ->> 'kid')::uuid;
      v_issued_at := (v_payload ->> 'issuedAt')::timestamptz;
      if ledger.cursor_secret_v1(v_key_id) is null
        or v_signature <> pg_catalog.encode(extensions.hmac(
          v_encoded, ledger.cursor_secret_v1(v_key_id), 'sha256'
        ), 'hex')
        or v_issued_at < pg_catalog.statement_timestamp() - interval '7 days'
        or v_issued_at > pg_catalog.statement_timestamp() + interval '5 minutes'
      then
        raise exception 'ledger_invalid_cursor';
      end if;
      if v_payload ->> 'resource' <> 'entries'
        or v_payload ->> 'companies' <> v_company_hash
      then
        raise exception 'ledger_invalid_cursor';
      end if;
      v_cursor_created_at := (v_payload ->> 'createdAt')::timestamptz;
      v_cursor_id := (v_payload ->> 'id')::uuid;
    exception
      when others then
        raise exception 'ledger_invalid_cursor';
    end;
  end if;

  select count(*) into v_count
  from (
    select entry.id
    from ledger.entries entry
    where entry.company_id = any(p_company_ids)
      and public.company_access_is_accepted_member_v1(entry.company_id)
      and (p_cursor is null or (entry.created_at, entry.id) < (v_cursor_created_at, v_cursor_id))
    order by entry.created_at desc, entry.id desc
    limit p_limit + 1
  ) visible;
  has_more := v_count > p_limit;

  select coalesce(pg_catalog.jsonb_agg(item order by created_at desc, id desc), '[]'::jsonb)
  into items
  from (
    select entry.created_at, entry.id, pg_catalog.jsonb_build_object(
      'entryId', entry.id,
      'companyId', entry.company_id,
      'incomeYear', entry.income_year,
      'entryKind', entry.entry_kind,
      'sourceCapability', entry.source_capability,
      'sourceRecordId', entry.source_record_id,
      'createdAt', entry.created_at,
      'memo', entry.memo,
      'lines', entry.lines,
      'riskFlags', entry.risk_flags,
      'warningAcceptedBy', entry.warning_accepted_by,
      'warningAcceptedAt', entry.warning_accepted_at,
      'postedBy', entry.created_by,
      'postedAt', entry.posted_at
    ) item
    from ledger.entries entry
    where entry.company_id = any(p_company_ids)
      and public.company_access_is_accepted_member_v1(entry.company_id)
      and (p_cursor is null or (entry.created_at, entry.id) < (v_cursor_created_at, v_cursor_id))
    order by entry.created_at desc, entry.id desc
    limit p_limit
  ) page_rows;

  if has_more and pg_catalog.jsonb_array_length(items) > 0 then
    select entry.created_at, entry.id
    into v_last_created_at, v_last_id
    from ledger.entries entry
    where entry.company_id = any(p_company_ids)
      and public.company_access_is_accepted_member_v1(entry.company_id)
      and (p_cursor is null or (entry.created_at, entry.id) < (v_cursor_created_at, v_cursor_id))
    order by entry.created_at desc, entry.id desc
    offset p_limit - 1 limit 1;
    next_cursor := ledger.cursor_encode_v1(
      'entries', p_company_ids, v_last_created_at, v_last_id
    );
  else
    next_cursor := null;
  end if;
  return next;
end;
$function$;

create or replace function ledger.list_period_locks(
  p_company_ids uuid[],
  p_cursor text,
  p_limit integer,
  p_verified_subject text
)
returns table (items jsonb, next_cursor text, has_more boolean)
language plpgsql
security definer
set search_path = ''
as $function$
declare
  v_actor_id uuid := public.company_access_auth_uid_v1();
  v_cursor_created_at timestamptz;
  v_cursor_id uuid;
  v_encoded text;
  v_signature text;
  v_payload jsonb;
  v_key_id uuid;
  v_issued_at timestamptz;
  v_companies text;
  v_company_hash text;
  v_count integer;
  v_last_created_at timestamptz;
  v_last_id uuid;
begin
  if v_actor_id is null or p_verified_subject is null
    or p_verified_subject !~ '^[0-9a-fA-F-]{36}$'
    or v_actor_id is distinct from p_verified_subject::uuid
  then
    raise exception 'ledger_forbidden';
  end if;
  if p_limit is null or p_limit < 1 or p_limit > 100
    or p_company_ids is null or pg_catalog.cardinality(p_company_ids) = 0
    or pg_catalog.cardinality(p_company_ids) > 100
    or (p_cursor is not null and pg_catalog.length(p_cursor) > 4096)
  then
    raise exception 'ledger_invalid_input';
  end if;
  select coalesce(pg_catalog.string_agg(company_id::text, ',' order by company_id), '')
  into v_companies from pg_catalog.unnest(p_company_ids) company_id;
  v_company_hash := pg_catalog.encode(extensions.digest(v_companies, 'sha256'), 'hex');

  if p_cursor is not null then
    begin
      v_encoded := pg_catalog.split_part(p_cursor, '.', 1);
      v_signature := pg_catalog.split_part(p_cursor, '.', 2);
      if v_encoded = '' or v_signature !~ '^[0-9a-f]{64}$'
        or pg_catalog.split_part(p_cursor, '.', 3) <> '' then
        raise exception 'ledger_invalid_cursor';
      end if;
      v_payload := pg_catalog.convert_from(pg_catalog.decode(
        pg_catalog.translate(v_encoded, '-_', '+/') ||
          pg_catalog.repeat('=', (4 - pg_catalog.length(v_encoded) % 4) % 4),
        'base64'
      ), 'UTF8')::jsonb;
      v_key_id := (v_payload ->> 'kid')::uuid;
      v_issued_at := (v_payload ->> 'issuedAt')::timestamptz;
      if ledger.cursor_secret_v1(v_key_id) is null
        or v_signature <> pg_catalog.encode(extensions.hmac(
          v_encoded, ledger.cursor_secret_v1(v_key_id), 'sha256'
        ), 'hex')
        or v_issued_at < pg_catalog.statement_timestamp() - interval '7 days'
        or v_issued_at > pg_catalog.statement_timestamp() + interval '5 minutes'
      then
        raise exception 'ledger_invalid_cursor';
      end if;
      if v_payload ->> 'resource' <> 'period_locks'
        or v_payload ->> 'companies' <> v_company_hash
      then
        raise exception 'ledger_invalid_cursor';
      end if;
      v_cursor_created_at := (v_payload ->> 'createdAt')::timestamptz;
      v_cursor_id := (v_payload ->> 'id')::uuid;
    exception
      when others then
        raise exception 'ledger_invalid_cursor';
    end;
  end if;

  select count(*) into v_count
  from (
    select period_lock.id
    from ledger.period_locks period_lock
    where period_lock.company_id = any(p_company_ids)
      and public.company_access_is_accepted_member_v1(period_lock.company_id)
      and (p_cursor is null or (period_lock.locked_at, period_lock.id) < (v_cursor_created_at, v_cursor_id))
    order by period_lock.locked_at desc, period_lock.id desc
    limit p_limit + 1
  ) visible;
  has_more := v_count > p_limit;

  select coalesce(pg_catalog.jsonb_agg(item order by created_at desc, id desc), '[]'::jsonb)
  into items
  from (
    select period_lock.locked_at as created_at, period_lock.id,
      pg_catalog.jsonb_build_object(
        'periodLockId', period_lock.id,
        'companyId', period_lock.company_id,
        'incomeYear', period_lock.income_year,
        'reason', period_lock.reason,
        'lockedBy', period_lock.locked_by,
        'lockedAt', period_lock.locked_at
      ) item
    from ledger.period_locks period_lock
    where period_lock.company_id = any(p_company_ids)
      and public.company_access_is_accepted_member_v1(period_lock.company_id)
      and (p_cursor is null or (period_lock.locked_at, period_lock.id) < (v_cursor_created_at, v_cursor_id))
    order by period_lock.locked_at desc, period_lock.id desc
    limit p_limit
  ) page_rows;

  if has_more and pg_catalog.jsonb_array_length(items) > 0 then
    select period_lock.locked_at, period_lock.id
    into v_last_created_at, v_last_id
    from ledger.period_locks period_lock
    where period_lock.company_id = any(p_company_ids)
      and public.company_access_is_accepted_member_v1(period_lock.company_id)
      and (p_cursor is null or (period_lock.locked_at, period_lock.id) < (v_cursor_created_at, v_cursor_id))
    order by period_lock.locked_at desc, period_lock.id desc
    offset p_limit - 1 limit 1;
    next_cursor := ledger.cursor_encode_v1(
      'period_locks', p_company_ids, v_last_created_at, v_last_id
    );
  else
    next_cursor := null;
  end if;
  return next;
end;
$function$;

-- Expand keeps a frozen public facade for already-deployed callers. These are
-- simple, security-invoker views over the same physical relations; no duplicate
-- ledger store or posting implementation is introduced. Contract removes them.
create or replace view public.ledger_entries
with (security_invoker = true)
as
select
  id,
  company_id,
  setup_id,
  income_year,
  case entry_kind
    when 'OPENING_BALANCE' then 'opening_balance'
    when 'ADMINISTRATIVE_COST' then 'admin_cost'
    when 'MANUAL_JOURNAL' then 'manual_journal'
    when 'BANK_RULE_SUGGESTION' then 'bank_rule_suggestion'
    when 'DIVIDEND_RECEIVED' then 'dividend_received'
    when 'OWNER_DIVIDEND_DECLARED' then 'dividend_to_owner_declared'
    when 'OWNER_DIVIDEND_PAYMENT' then 'dividend_to_owner_payment'
    when 'SHARE_PURCHASE' then 'share_purchase'
    when 'SHARE_SALE' then 'share_sale'
    when 'SHAREHOLDER_LOAN' then 'shareholder_loan'
    when 'TAX_SETTLEMENT' then 'tax_settlement'
    else pg_catalog.lower(entry_kind)
  end as entry_type,
  memo,
  coalesce(
    (
      select pg_catalog.jsonb_agg(line.item - 'currency' order by line.ordinality)
      from pg_catalog.jsonb_array_elements(entries.lines)
        with ordinality as line(item, ordinality)
    ),
    '[]'::jsonb
  ) as lines,
  risk_flags,
  warning_accepted_by,
  warning_accepted_at,
  posted_at,
  created_by,
  created_at
from ledger.entries;

-- The value projection above deliberately freezes the predecessor vocabulary,
-- so the compatibility view needs an explicit insert path. The invoker performs
-- the underlying insert and therefore remains subject to ledger.entries RLS.
create or replace function public.ledger_entries_legacy_insert_v1()
returns trigger
language plpgsql
set search_path = ''
as $function$
declare
  v_entry_kind text;
begin
  insert into ledger.entries (
    id, company_id, setup_id, income_year, entry_kind, memo, lines, risk_flags,
    warning_accepted_by, warning_accepted_at, posted_at, created_by, created_at
  ) values (
    coalesce(new.id, pg_catalog.gen_random_uuid()),
    new.company_id,
    new.setup_id,
    new.income_year,
    new.entry_type,
    new.memo,
    new.lines,
    coalesce(new.risk_flags, '[]'::jsonb),
    new.warning_accepted_by,
    new.warning_accepted_at,
    coalesce(new.posted_at, pg_catalog.statement_timestamp()),
    new.created_by,
    coalesce(new.created_at, pg_catalog.statement_timestamp())
  )
  returning
    id, company_id, setup_id, income_year, entry_kind, memo, lines, risk_flags,
    warning_accepted_by, warning_accepted_at, posted_at, created_by, created_at
  into
    new.id, new.company_id, new.setup_id, new.income_year, v_entry_kind,
    new.memo, new.lines, new.risk_flags, new.warning_accepted_by,
    new.warning_accepted_at, new.posted_at, new.created_by, new.created_at;

  new.entry_type := case v_entry_kind
    when 'OPENING_BALANCE' then 'opening_balance'
    when 'ADMINISTRATIVE_COST' then 'admin_cost'
    when 'MANUAL_JOURNAL' then 'manual_journal'
    when 'BANK_RULE_SUGGESTION' then 'bank_rule_suggestion'
    when 'DIVIDEND_RECEIVED' then 'dividend_received'
    when 'OWNER_DIVIDEND_DECLARED' then 'dividend_to_owner_declared'
    when 'OWNER_DIVIDEND_PAYMENT' then 'dividend_to_owner_payment'
    when 'SHARE_PURCHASE' then 'share_purchase'
    when 'SHARE_SALE' then 'share_sale'
    when 'SHAREHOLDER_LOAN' then 'shareholder_loan'
    when 'TAX_SETTLEMENT' then 'tax_settlement'
    else pg_catalog.lower(v_entry_kind)
  end;
  select coalesce(
    pg_catalog.jsonb_agg(line.item - 'currency' order by line.ordinality),
    '[]'::jsonb
  )
  into new.lines
  from pg_catalog.jsonb_array_elements(new.lines)
    with ordinality as line(item, ordinality);
  return new;
end;
$function$;

drop trigger if exists ledger_entries_legacy_insert
  on public.ledger_entries;
create trigger ledger_entries_legacy_insert
instead of insert on public.ledger_entries
for each row execute function public.ledger_entries_legacy_insert_v1();

create or replace view public.period_locks
with (security_invoker = true)
as
select id, company_id, income_year, reason, locked_by, locked_at
from ledger.period_locks;

grant usage on schema ledger to authenticated;
grant select, insert on ledger.entries, ledger.period_locks to authenticated;
grant select, insert on public.ledger_entries, public.period_locks to authenticated;

-- Hosted Supabase's migration principal is intentionally not a superuser.
-- Give only the temporary SET membership needed to transfer ownership, then
-- revoke it again before this transaction commits.
do $ledger_store_ownership_membership$
begin
  execute pg_catalog.format(
    'grant ledger_store_owner to %I', current_user
  );
end
$ledger_store_ownership_membership$;

alter table ledger.entries owner to ledger_store_owner;
alter table ledger.period_locks owner to ledger_store_owner;
alter table backend_system.ledger_command_receipts owner to ledger_store_owner;
alter table backend_system.ledger_cursor_signing_keys owner to ledger_store_owner;

do $ledger_workflow_ownership$
begin
  execute pg_catalog.format(
    'grant ledger_workflow_store_owner to %I', current_user
  );
  alter table backend_system.ledger_workflow_receipts
    owner to ledger_workflow_store_owner;
  alter function backend_system.claim_ledger_workflow_v1(
    text, text, uuid, jsonb, text
  ) owner to ledger_workflow_store_owner;
  alter function backend_system.record_opening_snapshot_legacy_v1(
    uuid, integer, numeric, numeric, integer, numeric, jsonb, text
  ) owner to ledger_workflow_store_owner;
  alter function backend_system.list_opening_snapshots_legacy_v1(
    uuid[], text, integer, text
  ) owner to ledger_workflow_store_owner;
  alter function backend_system.complete_ledger_workflow_v1(
    text, text, uuid, jsonb, jsonb, text
  ) owner to ledger_workflow_store_owner;
  execute pg_catalog.format(
    'revoke ledger_workflow_store_owner from %I', current_user
  );
end
$ledger_workflow_ownership$;

revoke create on schema backend_system from ledger_workflow_store_owner;

alter function ledger.entry_lines_are_valid_v1(jsonb, boolean)
  owner to ledger_store_owner;
alter function ledger.normalize_lines_v1(jsonb)
  owner to ledger_store_owner;
alter function ledger.enforce_entry_v1()
  owner to ledger_store_owner;
alter function backend_system.prevent_ledger_technical_mutation()
  owner to ledger_store_owner;
alter function ledger.lock_company_year_v1(uuid, integer)
  owner to ledger_store_owner;
alter function ledger.post_entry(
  text, uuid, integer, text, text, jsonb, jsonb, boolean,
  text, text, text, text
) owner to ledger_store_owner;
alter function ledger.lock_period(
  text, uuid, integer, text, text, text
) owner to ledger_store_owner;
alter function ledger.cursor_secret_v1(uuid) owner to ledger_store_owner;
alter function ledger.cursor_encode_v1(text, uuid[], timestamptz, uuid)
  owner to ledger_store_owner;
alter function ledger.list_entries(uuid[], text, integer, text)
  owner to ledger_store_owner;
alter function ledger.list_period_locks(uuid[], text, integer, text)
  owner to ledger_store_owner;

revoke all on function
  ledger.entry_lines_are_valid_v1(jsonb, boolean),
  ledger.normalize_lines_v1(jsonb),
  ledger.enforce_entry_v1(),
  backend_system.prevent_ledger_technical_mutation(),
  ledger.lock_company_year_v1(uuid, integer),
  ledger.post_entry(
    text, uuid, integer, text, text, jsonb, jsonb, boolean,
    text, text, text, text
  ),
  ledger.lock_period(text, uuid, integer, text, text, text),
  ledger.cursor_secret_v1(uuid),
  ledger.cursor_encode_v1(text, uuid[], timestamptz, uuid),
  ledger.list_entries(uuid[], text, integer, text),
  ledger.list_period_locks(uuid[], text, integer, text)
from public, anon, authenticated, service_role, ledger_executor,
  ledger_workflow_executor, talli_ledger_backend;

revoke all on function
  backend_system.claim_ledger_workflow_v1(text, text, uuid, jsonb, text),
  backend_system.record_opening_snapshot_legacy_v1(
    uuid, integer, numeric, numeric, integer, numeric, jsonb, text
  ),
  backend_system.list_opening_snapshots_legacy_v1(uuid[], text, integer, text),
  backend_system.complete_ledger_workflow_v1(
    text, text, uuid, jsonb, jsonb, text
  )
from public, anon, authenticated, service_role, ledger_executor,
  ledger_store_owner, ledger_workflow_executor, talli_ledger_backend;

grant execute on function
  ledger.post_entry(
    text, uuid, integer, text, text, jsonb, jsonb, boolean,
    text, text, text, text
  ),
  ledger.lock_period(text, uuid, integer, text, text, text),
  ledger.list_entries(uuid[], text, integer, text),
  ledger.list_period_locks(uuid[], text, integer, text)
to ledger_executor;

grant execute on function
  backend_system.list_opening_snapshots_legacy_v1(uuid[], text, integer, text)
to ledger_executor;

grant execute on function
  ledger.cursor_secret_v1(uuid),
  ledger.cursor_encode_v1(text, uuid[], timestamptz, uuid)
to ledger_workflow_store_owner;

grant execute on function
  backend_system.claim_ledger_workflow_v1(text, text, uuid, jsonb, text),
  backend_system.record_opening_snapshot_legacy_v1(
    uuid, integer, numeric, numeric, integer, numeric, jsonb, text
  ),
  backend_system.complete_ledger_workflow_v1(
    text, text, uuid, jsonb, jsonb, text
  ),
  ledger.post_entry(
    text, uuid, integer, text, text, jsonb, jsonb, boolean,
    text, text, text, text
  )
to ledger_workflow_executor;

grant execute on function ledger.lock_company_year_v1(uuid, integer)
to ledger_workflow_store_owner;

alter schema ledger owner to ledger_store_owner;
alter schema backend_system owner to ledger_store_owner;
revoke create on schema ledger, backend_system from ledger_store_owner;

do $ledger_store_ownership_membership_revoke$
begin
  execute pg_catalog.format(
    'revoke ledger_store_owner from %I', current_user
  );
end
$ledger_store_ownership_membership_revoke$;

commit;
