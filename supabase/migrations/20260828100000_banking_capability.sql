-- EXPAND/MIGRATE: canonical banking capture and reconciliation storage.
--
-- The public tables remain writable during this bounded mixed-version phase.
-- Exact-ID mirrors keep deployed browser imports available until the backend
-- client is live; the contract artifact removes the legacy side only after
-- count/hash reconciliation and rollback rehearsal.

begin;

create schema if not exists banking;
create schema if not exists backend_system;

do $banking_roles$
begin
  if not exists (
    select 1 from pg_catalog.pg_roles where rolname = 'banking_store_owner'
  ) then
    create role banking_store_owner nologin noinherit nobypassrls;
  end if;
  if not exists (
    select 1 from pg_catalog.pg_roles where rolname = 'banking_executor'
  ) then
    create role banking_executor nologin noinherit nobypassrls;
  end if;
  if not exists (
    select 1 from pg_catalog.pg_roles where rolname = 'banking_workflow_store_owner'
  ) then
    create role banking_workflow_store_owner nologin noinherit nobypassrls;
  end if;
  if not exists (
    select 1 from pg_catalog.pg_roles where rolname = 'banking_workflow_executor'
  ) then
    create role banking_workflow_executor nologin noinherit nobypassrls;
  end if;
  if not exists (
    select 1 from pg_catalog.pg_roles where rolname = 'talli_banking_backend'
  ) then
    create role talli_banking_backend nologin noinherit nobypassrls;
  end if;
end
$banking_roles$;

do $banking_migration_authority$
begin
  execute pg_catalog.format(
    'grant ledger_store_owner, banking_store_owner, banking_workflow_store_owner, company_access_executor to %I',
    current_user
  );
  execute pg_catalog.format(
    'grant create on schema banking to %I', current_user
  );
end
$banking_migration_authority$;

select pg_catalog.set_config(
  'talli.banking_migration_principal', current_user, true
);
set local role ledger_store_owner;
grant usage, create on schema backend_system to banking_store_owner,
  banking_workflow_store_owner;
do $banking_backend_system_migration_authority$
begin
  execute pg_catalog.format(
    'grant usage, create on schema backend_system to %I',
    pg_catalog.current_setting('talli.banking_migration_principal')
  );
end
$banking_backend_system_migration_authority$;
reset role;

alter role banking_store_owner nologin noinherit nobypassrls;
alter role banking_executor nologin noinherit nobypassrls;
alter role banking_workflow_store_owner nologin noinherit nobypassrls;
alter role banking_workflow_executor nologin noinherit nobypassrls;
alter role talli_banking_backend nologin noinherit nobypassrls;
grant banking_executor to talli_banking_backend with inherit false, set true;
grant banking_workflow_executor to talli_banking_backend with inherit false, set true;

grant usage, create on schema banking to banking_store_owner;
grant usage on schema extensions to banking_store_owner,
  banking_workflow_store_owner;
grant execute on function extensions.digest(text, text)
  to banking_store_owner, banking_workflow_store_owner;

create table if not exists backend_system.banking_migration_runs (
  id uuid primary key,
  started_at timestamptz not null default pg_catalog.statement_timestamp(),
  completed_at timestamptz
);

create table if not exists backend_system.banking_migration_source_rows (
  run_id uuid not null references backend_system.banking_migration_runs(id)
    on delete restrict,
  source_table text not null check (
    source_table in ('bank_transactions', 'bank_suggestion_acceptances')
  ),
  source_id uuid not null,
  payload jsonb not null,
  payload_sha256 text not null check (payload_sha256 ~ '^[0-9a-f]{64}$'),
  primary key (run_id, source_table, source_id)
);

create table if not exists backend_system.banking_migration_reconciliations (
  run_id uuid not null references backend_system.banking_migration_runs(id)
    on delete restrict,
  source_table text not null check (
    source_table in ('bank_transactions', 'bank_suggestion_acceptances')
  ),
  source_row_count bigint not null check (source_row_count >= 0),
  target_row_count bigint not null check (target_row_count >= 0),
  source_sha256 text not null check (source_sha256 ~ '^[0-9a-f]{64}$'),
  target_sha256 text not null check (target_sha256 ~ '^[0-9a-f]{64}$'),
  recorded_at timestamptz not null default pg_catalog.statement_timestamp(),
  primary key (run_id, source_table),
  check (source_row_count = target_row_count),
  check (source_sha256 = target_sha256)
);

create table if not exists banking.transactions (
  id uuid primary key,
  company_id uuid not null references public.companies(id) on delete restrict,
  income_year integer not null check (income_year between 2000 and 2100),
  transaction_date date not null,
  text text not null check (
    pg_catalog.btrim(text) <> '' and pg_catalog.char_length(text) <= 500
  ),
  amount numeric(20, 2) not null,
  balance numeric(20, 2),
  source_hash text not null check (source_hash ~ '^[0-9a-f]{64}$'),
  matched_accounting_entry_id uuid references ledger.entries(id) on delete restrict,
  matched_action_reference text,
  warning_accepted boolean not null default false,
  created_by uuid not null references auth.users(id) on delete restrict,
  created_at timestamptz not null default pg_catalog.statement_timestamp(),
  unique (company_id, income_year, source_hash),
  check (transaction_date >= pg_catalog.make_date(income_year, 1, 1)),
  check (transaction_date <= pg_catalog.make_date(income_year, 12, 31))
);

create index if not exists banking_transactions_company_date_idx
  on banking.transactions(company_id, transaction_date desc, id desc);

create table if not exists banking.suggestion_acceptances (
  id uuid primary key,
  company_id uuid not null references public.companies(id) on delete restrict,
  bank_transaction_id uuid not null references banking.transactions(id)
    on delete restrict,
  accounting_entry_id uuid not null references ledger.entries(id) on delete restrict,
  suggestion_kind text not null check (
    suggestion_kind in ('BANK_FEE', 'SYSTEM_SUBSCRIPTION', 'DEPOSIT_INTEREST')
  ),
  rule_version text not null check (
    pg_catalog.btrim(rule_version) <> '' and pg_catalog.char_length(rule_version) <= 80
  ),
  reason text not null check (
    pg_catalog.btrim(reason) <> '' and pg_catalog.char_length(reason) <= 500
  ),
  accepted_by uuid not null references auth.users(id) on delete restrict,
  accepted_at timestamptz not null default pg_catalog.statement_timestamp(),
  unique (bank_transaction_id),
  unique (accounting_entry_id)
);

create index if not exists banking_suggestion_acceptances_company_idx
  on banking.suggestion_acceptances(company_id, accepted_at desc, id desc);

select pg_catalog.pg_advisory_xact_lock(
  pg_catalog.hashtextextended('talli:banking:capability-expand:v1', 0)
);
lock table public.bank_transactions in share row exclusive mode;
lock table public.bank_suggestion_acceptances in share row exclusive mode;

drop trigger if exists banking_migration_runs_immutable
  on backend_system.banking_migration_runs;
drop trigger if exists banking_migration_source_rows_immutable
  on backend_system.banking_migration_source_rows;
drop trigger if exists banking_migration_reconciliations_immutable
  on backend_system.banking_migration_reconciliations;

select pg_catalog.set_config(
  'talli.banking_migration_run_id',
  pg_catalog.gen_random_uuid()::text,
  true
);
insert into backend_system.banking_migration_runs (id)
values (pg_catalog.current_setting('talli.banking_migration_run_id')::uuid);

insert into backend_system.banking_migration_source_rows (
  run_id, source_table, source_id, payload, payload_sha256
)
select
  pg_catalog.current_setting('talli.banking_migration_run_id')::uuid,
  'bank_transactions',
  bank_row.id,
  pg_catalog.to_jsonb(bank_row),
  pg_catalog.encode(
    extensions.digest(pg_catalog.to_jsonb(bank_row)::text, 'sha256'), 'hex'
  )
from public.bank_transactions bank_row
union all
select
  pg_catalog.current_setting('talli.banking_migration_run_id')::uuid,
  'bank_suggestion_acceptances',
  acceptance.id,
  pg_catalog.to_jsonb(acceptance),
  pg_catalog.encode(
    extensions.digest(pg_catalog.to_jsonb(acceptance)::text, 'sha256'), 'hex'
  )
from public.bank_suggestion_acceptances acceptance;

insert into banking.transactions (
  id, company_id, income_year, transaction_date, text, amount, balance,
  source_hash, matched_accounting_entry_id, matched_action_reference,
  warning_accepted, created_by, created_at
)
select
  bank_row.id,
  bank_row.company_id,
  bank_row.income_year,
  bank_row.transaction_date,
  bank_row.text,
  bank_row.amount,
  bank_row.balance,
  bank_row.source_hash,
  bank_row.matched_entry_id,
  bank_row.matched_action_id,
  bank_row.accepted_warning,
  bank_row.created_by,
  bank_row.created_at
from public.bank_transactions bank_row
on conflict (id) do update set
  company_id = excluded.company_id,
  income_year = excluded.income_year,
  transaction_date = excluded.transaction_date,
  text = excluded.text,
  amount = excluded.amount,
  balance = excluded.balance,
  source_hash = excluded.source_hash,
  matched_accounting_entry_id = excluded.matched_accounting_entry_id,
  matched_action_reference = excluded.matched_action_reference,
  warning_accepted = excluded.warning_accepted,
  created_by = excluded.created_by,
  created_at = excluded.created_at;

insert into banking.suggestion_acceptances (
  id, company_id, bank_transaction_id, accounting_entry_id, suggestion_kind,
  rule_version, reason, accepted_by, accepted_at
)
select
  acceptance.id,
  acceptance.company_id,
  acceptance.bank_transaction_id,
  acceptance.ledger_entry_id,
  pg_catalog.upper(acceptance.rule_id),
  acceptance.rule_version,
  acceptance.reason,
  acceptance.accepted_by,
  acceptance.accepted_at
from public.bank_suggestion_acceptances acceptance
on conflict (id) do update set
  company_id = excluded.company_id,
  bank_transaction_id = excluded.bank_transaction_id,
  accounting_entry_id = excluded.accounting_entry_id,
  suggestion_kind = excluded.suggestion_kind,
  rule_version = excluded.rule_version,
  reason = excluded.reason,
  accepted_by = excluded.accepted_by,
  accepted_at = excluded.accepted_at;

insert into backend_system.banking_migration_reconciliations (
  run_id, source_table, source_row_count, target_row_count,
  source_sha256, target_sha256
)
select
  pg_catalog.current_setting('talli.banking_migration_run_id')::uuid,
  'bank_transactions',
  source_set.row_count,
  target_set.row_count,
  source_set.sha256,
  target_set.sha256
from (
  select
    pg_catalog.count(*) as row_count,
    pg_catalog.encode(extensions.digest(coalesce(pg_catalog.string_agg(
      bank_row.id::text || ':' || pg_catalog.encode(extensions.digest(
        pg_catalog.jsonb_build_object(
          'id', bank_row.id,
          'company_id', bank_row.company_id,
          'income_year', bank_row.income_year,
          'transaction_date', bank_row.transaction_date,
          'text', bank_row.text,
          'amount', bank_row.amount,
          'balance', bank_row.balance,
          'source_hash', bank_row.source_hash,
          'matched_accounting_entry_id', bank_row.matched_entry_id,
          'matched_action_reference', bank_row.matched_action_id,
          'warning_accepted', bank_row.accepted_warning,
          'created_by', bank_row.created_by,
          'created_at', bank_row.created_at
        )::text,
        'sha256'
      ), 'hex'), '' order by bank_row.id), ''), 'sha256'), 'hex') as sha256
  from public.bank_transactions bank_row
) source_set
cross join (
  select
    pg_catalog.count(*) as row_count,
    pg_catalog.encode(extensions.digest(coalesce(pg_catalog.string_agg(
      bank_row.id::text || ':' || pg_catalog.encode(extensions.digest(
        pg_catalog.to_jsonb(bank_row)::text, 'sha256'
      ), 'hex'), '' order by bank_row.id), ''), 'sha256'), 'hex') as sha256
  from banking.transactions bank_row
) target_set;

insert into backend_system.banking_migration_reconciliations (
  run_id, source_table, source_row_count, target_row_count,
  source_sha256, target_sha256
)
select
  pg_catalog.current_setting('talli.banking_migration_run_id')::uuid,
  'bank_suggestion_acceptances',
  source_set.row_count,
  target_set.row_count,
  source_set.sha256,
  target_set.sha256
from (
  select
    pg_catalog.count(*) as row_count,
    pg_catalog.encode(extensions.digest(coalesce(pg_catalog.string_agg(
      acceptance.id::text || ':' || pg_catalog.encode(extensions.digest(
        pg_catalog.jsonb_build_object(
          'id', acceptance.id,
          'company_id', acceptance.company_id,
          'bank_transaction_id', acceptance.bank_transaction_id,
          'accounting_entry_id', acceptance.ledger_entry_id,
          'suggestion_kind', pg_catalog.upper(acceptance.rule_id),
          'rule_version', acceptance.rule_version,
          'reason', acceptance.reason,
          'accepted_by', acceptance.accepted_by,
          'accepted_at', acceptance.accepted_at
        )::text,
        'sha256'
      ), 'hex'), '' order by acceptance.id), ''), 'sha256'), 'hex') as sha256
  from public.bank_suggestion_acceptances acceptance
) source_set
cross join (
  select
    pg_catalog.count(*) as row_count,
    pg_catalog.encode(extensions.digest(coalesce(pg_catalog.string_agg(
      acceptance.id::text || ':' || pg_catalog.encode(extensions.digest(
        pg_catalog.to_jsonb(acceptance)::text, 'sha256'
      ), 'hex'), '' order by acceptance.id), ''), 'sha256'), 'hex') as sha256
  from banking.suggestion_acceptances acceptance
) target_set;

create or replace function backend_system.sync_legacy_bank_transaction_to_banking_v1()
returns trigger
language plpgsql
security definer
set search_path = ''
as $function$
begin
  if pg_catalog.pg_trigger_depth() > 1 then
    return coalesce(new, old);
  end if;
  if tg_op = 'DELETE' then
    delete from banking.transactions where id = old.id;
    return old;
  end if;
  insert into banking.transactions (
    id, company_id, income_year, transaction_date, text, amount, balance,
    source_hash, matched_accounting_entry_id, matched_action_reference,
    warning_accepted, created_by, created_at
  ) values (
    new.id, new.company_id, new.income_year, new.transaction_date, new.text,
    new.amount, new.balance, new.source_hash, new.matched_entry_id,
    new.matched_action_id, new.accepted_warning, new.created_by, new.created_at
  )
  on conflict (id) do update set
    company_id = excluded.company_id,
    income_year = excluded.income_year,
    transaction_date = excluded.transaction_date,
    text = excluded.text,
    amount = excluded.amount,
    balance = excluded.balance,
    source_hash = excluded.source_hash,
    matched_accounting_entry_id = excluded.matched_accounting_entry_id,
    matched_action_reference = excluded.matched_action_reference,
    warning_accepted = excluded.warning_accepted,
    created_by = excluded.created_by,
    created_at = excluded.created_at;
  return new;
end;
$function$;

create or replace function backend_system.sync_banking_transaction_to_legacy_v1()
returns trigger
language plpgsql
security definer
set search_path = ''
as $function$
begin
  if pg_catalog.pg_trigger_depth() > 1 then
    return coalesce(new, old);
  end if;
  if tg_op = 'DELETE' then
    delete from public.bank_transactions where id = old.id;
    return old;
  end if;
  insert into public.bank_transactions (
    id, company_id, income_year, transaction_date, text, amount, balance,
    source_hash, matched_entry_id, matched_action_id, accepted_warning,
    created_by, created_at
  ) values (
    new.id, new.company_id, new.income_year, new.transaction_date, new.text,
    new.amount, new.balance, new.source_hash, new.matched_accounting_entry_id,
    new.matched_action_reference, new.warning_accepted, new.created_by,
    new.created_at
  )
  on conflict (id) do update set
    company_id = excluded.company_id,
    income_year = excluded.income_year,
    transaction_date = excluded.transaction_date,
    text = excluded.text,
    amount = excluded.amount,
    balance = excluded.balance,
    source_hash = excluded.source_hash,
    matched_entry_id = excluded.matched_entry_id,
    matched_action_id = excluded.matched_action_id,
    accepted_warning = excluded.accepted_warning,
    created_by = excluded.created_by,
    created_at = excluded.created_at;
  return new;
end;
$function$;

create or replace function backend_system.sync_legacy_bank_acceptance_to_banking_v1()
returns trigger
language plpgsql
security definer
set search_path = ''
as $function$
begin
  if pg_catalog.pg_trigger_depth() > 1 then
    return coalesce(new, old);
  end if;
  if tg_op = 'DELETE' then
    delete from banking.suggestion_acceptances where id = old.id;
    return old;
  end if;
  insert into banking.suggestion_acceptances (
    id, company_id, bank_transaction_id, accounting_entry_id,
    suggestion_kind, rule_version, reason, accepted_by, accepted_at
  ) values (
    new.id, new.company_id, new.bank_transaction_id, new.ledger_entry_id,
    pg_catalog.upper(new.rule_id), new.rule_version, new.reason,
    new.accepted_by, new.accepted_at
  )
  on conflict (id) do update set
    company_id = excluded.company_id,
    bank_transaction_id = excluded.bank_transaction_id,
    accounting_entry_id = excluded.accounting_entry_id,
    suggestion_kind = excluded.suggestion_kind,
    rule_version = excluded.rule_version,
    reason = excluded.reason,
    accepted_by = excluded.accepted_by,
    accepted_at = excluded.accepted_at;
  return new;
end;
$function$;

alter function backend_system.sync_legacy_bank_transaction_to_banking_v1()
  owner to banking_store_owner;
alter function backend_system.sync_banking_transaction_to_legacy_v1()
  owner to banking_store_owner;
alter function backend_system.sync_legacy_bank_acceptance_to_banking_v1()
  owner to banking_store_owner;

drop trigger if exists bank_transactions_sync_to_banking
  on public.bank_transactions;
create trigger bank_transactions_sync_to_banking
after insert or update or delete on public.bank_transactions
for each row execute function
  backend_system.sync_legacy_bank_transaction_to_banking_v1();

drop trigger if exists banking_transactions_sync_to_legacy
  on banking.transactions;
create trigger banking_transactions_sync_to_legacy
after insert or update or delete on banking.transactions
for each row execute function
  backend_system.sync_banking_transaction_to_legacy_v1();

drop trigger if exists bank_acceptances_sync_to_banking
  on public.bank_suggestion_acceptances;
create trigger bank_acceptances_sync_to_banking
after insert or update or delete on public.bank_suggestion_acceptances
for each row execute function
  backend_system.sync_legacy_bank_acceptance_to_banking_v1();

create or replace function backend_system.prevent_banking_migration_evidence_mutation()
returns trigger
language plpgsql
set search_path = ''
as $function$
begin
  raise exception 'banking_migration_evidence_is_immutable';
end;
$function$;

alter function backend_system.prevent_banking_migration_evidence_mutation()
  owner to banking_store_owner;

update backend_system.banking_migration_runs
set completed_at = pg_catalog.statement_timestamp()
where id = pg_catalog.current_setting('talli.banking_migration_run_id')::uuid;

drop trigger if exists banking_migration_runs_immutable
  on backend_system.banking_migration_runs;
create trigger banking_migration_runs_immutable
before update or delete on backend_system.banking_migration_runs
for each row execute function
  backend_system.prevent_banking_migration_evidence_mutation();
drop trigger if exists banking_migration_source_rows_immutable
  on backend_system.banking_migration_source_rows;
create trigger banking_migration_source_rows_immutable
before update or delete on backend_system.banking_migration_source_rows
for each row execute function
  backend_system.prevent_banking_migration_evidence_mutation();
drop trigger if exists banking_migration_reconciliations_immutable
  on backend_system.banking_migration_reconciliations;
create trigger banking_migration_reconciliations_immutable
before update or delete on backend_system.banking_migration_reconciliations
for each row execute function
  backend_system.prevent_banking_migration_evidence_mutation();

alter table banking.transactions enable row level security;
alter table banking.transactions force row level security;
alter table banking.suggestion_acceptances enable row level security;
alter table banking.suggestion_acceptances force row level security;
alter table backend_system.banking_migration_runs enable row level security;
alter table backend_system.banking_migration_runs force row level security;
alter table backend_system.banking_migration_source_rows enable row level security;
alter table backend_system.banking_migration_source_rows force row level security;
alter table backend_system.banking_migration_reconciliations enable row level security;
alter table backend_system.banking_migration_reconciliations force row level security;

drop policy if exists "banking store reads transactions" on banking.transactions;
create policy "banking store reads transactions"
on banking.transactions for select to banking_store_owner
using (public.company_access_is_accepted_member_v1(company_id));
drop policy if exists "banking store creates transactions" on banking.transactions;
create policy "banking store creates transactions"
on banking.transactions for insert to banking_store_owner
with check (
  created_by = public.company_access_auth_uid_v1()
  and public.company_access_is_accepted_owner_v1(company_id)
  and public.company_access_company_year_allows_consequential_v1(
    company_id, income_year
  )
);
drop policy if exists "banking store updates transactions" on banking.transactions;
create policy "banking store updates transactions"
on banking.transactions for update to banking_store_owner
using (public.company_access_is_accepted_owner_v1(company_id))
with check (
  public.company_access_is_accepted_owner_v1(company_id)
  and public.company_access_company_year_allows_consequential_v1(
    company_id, income_year
  )
);

drop policy if exists "banking store reads acceptances"
  on banking.suggestion_acceptances;
create policy "banking store reads acceptances"
on banking.suggestion_acceptances for select to banking_store_owner
using (public.company_access_is_accepted_member_v1(company_id));
drop policy if exists "banking store creates acceptances"
  on banking.suggestion_acceptances;
create policy "banking store creates acceptances"
on banking.suggestion_acceptances for insert to banking_store_owner
with check (
  accepted_by = public.company_access_auth_uid_v1()
  and public.company_access_is_accepted_owner_v1(company_id)
);

revoke all on schema banking from public, anon, authenticated, service_role;
grant usage on schema banking to banking_store_owner,
  banking_executor, banking_workflow_store_owner, banking_workflow_executor;
revoke all on banking.transactions, banking.suggestion_acceptances
  from public, anon, authenticated, service_role, banking_executor,
    banking_workflow_executor;
grant select, insert, update, delete on
  banking.transactions, banking.suggestion_acceptances
to banking_store_owner;

-- Bounded overlap authority for the target-to-legacy mirror. The contract
-- artifact revokes this before removing the public tables.
grant select, insert, update, delete on
  public.bank_transactions, public.bank_suggestion_acceptances
to banking_store_owner;

alter table banking.transactions owner to banking_store_owner;
alter table banking.suggestion_acceptances owner to banking_store_owner;
alter table backend_system.banking_migration_runs owner to banking_store_owner;
alter table backend_system.banking_migration_source_rows owner to banking_store_owner;
alter table backend_system.banking_migration_reconciliations owner to banking_store_owner;
alter schema banking owner to banking_store_owner;

revoke create on schema banking from banking_store_owner;
set local role ledger_store_owner;
revoke create on schema backend_system from banking_store_owner,
  banking_workflow_store_owner;
do $banking_revoke_backend_system_migration_authority$
begin
  execute pg_catalog.format(
    'revoke create on schema backend_system from %I',
    pg_catalog.current_setting('talli.banking_migration_principal')
  );
end
$banking_revoke_backend_system_migration_authority$;
reset role;
do $banking_revoke_migration_authority$
begin
  execute pg_catalog.format(
    'revoke create on schema banking from %I', current_user
  );
  execute pg_catalog.format(
    'revoke ledger_store_owner, banking_store_owner, banking_workflow_store_owner, company_access_executor from %I',
    current_user
  );
end
$banking_revoke_migration_authority$;

commit;
