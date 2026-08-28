-- ROLLBACK: return authority to the #139 ledger-owned banking coordinator.
-- The target writer is disabled first. Canonical banking data and immutable
-- migration evidence are retained so the workflow migration plus contract can
-- be applied again for deterministic recutover.

begin;

do $banking_rollback_migration_authority$
begin
  execute pg_catalog.format(
    'grant banking_store_owner, ledger_store_owner, company_archive_projection_executor to %I',
    current_user
  );
end
$banking_rollback_migration_authority$;
select pg_catalog.set_config(
  'talli.banking_rollback_migration_principal', current_user, true
);
set local role ledger_store_owner;
do $banking_rollback_backend_system_authority$
begin
  execute pg_catalog.format(
    'grant usage, create on schema backend_system to %I',
    pg_catalog.current_setting('talli.banking_rollback_migration_principal')
  );
end
$banking_rollback_backend_system_authority$;
reset role;

select pg_catalog.pg_advisory_xact_lock(
  pg_catalog.hashtextextended('talli:banking:capability-cutover:v1', 0)
);

-- Disable the target writer before exposing the predecessor overlap tables.
revoke execute on function banking.import_statement_v1(jsonb, text)
  from banking_executor;
revoke execute on function banking.prepare_suggestion_acceptance_v1(jsonb, text)
  from banking_workflow_executor;
revoke execute on function banking.complete_suggestion_acceptance_v1(
  jsonb, uuid, text, text
) from banking_workflow_executor;

set local role banking_store_owner;
drop policy if exists "banking overlap mirrors legacy transactions"
  on banking.transactions;
create policy "banking overlap mirrors legacy transactions"
on banking.transactions
as permissive
for all
to banking_store_owner
using (
  pg_catalog.pg_trigger_depth() > 0
  and public.company_access_is_accepted_owner_v1(company_id)
)
with check (
  pg_catalog.pg_trigger_depth() > 0
  and created_by = public.company_access_auth_uid_v1()
  and public.company_access_is_accepted_owner_v1(company_id)
);
drop policy if exists "banking overlap mirrors legacy acceptances"
  on banking.suggestion_acceptances;
create policy "banking overlap mirrors legacy acceptances"
on banking.suggestion_acceptances
as permissive
for all
to banking_store_owner
using (
  pg_catalog.pg_trigger_depth() > 0
  and public.company_access_is_accepted_owner_v1(company_id)
)
with check (
  pg_catalog.pg_trigger_depth() > 0
  and accepted_by = public.company_access_auth_uid_v1()
  and public.company_access_is_accepted_owner_v1(company_id)
);
reset role;

drop trigger if exists company_archive_track_bank_suggestion_acceptances
  on banking.suggestion_acceptances;
drop policy if exists "archive projection reads banking acceptances"
  on banking.suggestion_acceptances;
drop policy if exists "archive projection reads linked ledger lines"
  on ledger.entries;
revoke select on banking.suggestion_acceptances
  from company_archive_projection_executor;
revoke select (id, lines) on ledger.entries
  from company_archive_projection_executor;
revoke usage on schema banking, ledger
  from company_archive_projection_executor;
revoke all on public.bank_suggestion_acceptances
  from public, anon, authenticated, service_role;
revoke all on public.bank_transactions
  from public, anon, authenticated, service_role;
drop view public.bank_suggestion_acceptances;
drop view public.bank_transactions;
drop function public.company_archive_can_read_banking_acceptance_v1(uuid);

create table if not exists public.bank_transactions (
  id uuid primary key default pg_catalog.gen_random_uuid(),
  company_id uuid not null references public.companies(id) on delete cascade,
  income_year integer not null check (income_year between 2000 and 2100),
  transaction_date date not null,
  text text not null,
  amount numeric(20, 2) not null,
  balance numeric(20, 2),
  source_hash text not null,
  matched_entry_id uuid,
  matched_action_id text,
  accepted_warning boolean not null default false,
  created_by uuid not null references auth.users(id) on delete restrict,
  created_at timestamptz not null default pg_catalog.now(),
  unique (company_id, income_year, source_hash)
);

create index if not exists bank_transactions_company_id_year_idx
  on public.bank_transactions(company_id, income_year);

create table if not exists public.bank_suggestion_acceptances (
  id uuid primary key default pg_catalog.gen_random_uuid(),
  company_id uuid not null references public.companies(id) on delete cascade,
  bank_transaction_id uuid not null unique
    references public.bank_transactions(id) on delete restrict,
  ledger_entry_id uuid not null unique,
  rule_id text not null check (
    rule_id in ('bank_fee', 'system_subscription', 'deposit_interest')
  ),
  rule_version text not null check (rule_version <> ''),
  reason text not null check (reason <> ''),
  lines jsonb not null check (pg_catalog.jsonb_typeof(lines) = 'array'),
  accepted_by uuid not null references auth.users(id) on delete restrict,
  accepted_at timestamptz not null default pg_catalog.now()
);

create index if not exists bank_suggestion_acceptances_company_idx
  on public.bank_suggestion_acceptances(company_id);

insert into public.bank_transactions (
  id, company_id, income_year, transaction_date, text, amount, balance,
  source_hash, matched_entry_id, matched_action_id, accepted_warning,
  created_by, created_at
)
select
  bank_row.id, bank_row.company_id, bank_row.income_year,
  bank_row.transaction_date, bank_row.text, bank_row.amount, bank_row.balance,
  bank_row.source_hash, bank_row.matched_accounting_entry_id,
  bank_row.matched_action_reference, bank_row.warning_accepted,
  bank_row.created_by, bank_row.created_at
from banking.transactions bank_row;

insert into public.bank_suggestion_acceptances (
  id, company_id, bank_transaction_id, ledger_entry_id, rule_id,
  rule_version, reason, lines, accepted_by, accepted_at
)
select
  acceptance.id, acceptance.company_id, acceptance.bank_transaction_id,
  acceptance.accounting_entry_id, pg_catalog.lower(acceptance.suggestion_kind),
  acceptance.rule_version, acceptance.reason, entry.lines,
  acceptance.accepted_by, acceptance.accepted_at
from banking.suggestion_acceptances acceptance
join ledger.entries entry on entry.id = acceptance.accounting_entry_id;

alter table public.bank_transactions enable row level security;
alter table public.bank_suggestion_acceptances enable row level security;

drop policy if exists "company members can read bank transactions"
  on public.bank_transactions;
create policy "company members can read bank transactions"
on public.bank_transactions for select to authenticated
using (public.company_access_is_accepted_member_v1(company_id));
drop policy if exists "owners can create bank transactions"
  on public.bank_transactions;
create policy "owners can create bank transactions"
on public.bank_transactions for insert to authenticated
with check (
  created_by = public.company_access_auth_uid_v1()
  and public.company_access_is_accepted_owner_v1(company_id)
);
drop policy if exists "owners can update bank transactions"
  on public.bank_transactions;
create policy "owners can update bank transactions"
on public.bank_transactions for update to authenticated
using (public.company_access_is_accepted_owner_v1(company_id))
with check (
  created_by = public.company_access_auth_uid_v1()
  and public.company_access_is_accepted_owner_v1(company_id)
);
drop policy if exists "banking overlap mirrors canonical transactions"
  on public.bank_transactions;
create policy "banking overlap mirrors canonical transactions"
on public.bank_transactions
as permissive
for all
to banking_store_owner
using (
  pg_catalog.pg_trigger_depth() > 0
  and public.company_access_is_accepted_owner_v1(company_id)
)
with check (
  pg_catalog.pg_trigger_depth() > 0
  and created_by = public.company_access_auth_uid_v1()
  and public.company_access_is_accepted_owner_v1(company_id)
);
drop policy if exists "banking overlap mirrors canonical acceptances"
  on public.bank_suggestion_acceptances;
create policy "banking overlap mirrors canonical acceptances"
on public.bank_suggestion_acceptances
as permissive
for all
to ledger_store_owner
using (
  pg_catalog.pg_trigger_depth() > 0
  and public.company_access_is_accepted_owner_v1(company_id)
)
with check (
  pg_catalog.pg_trigger_depth() > 0
  and accepted_by = public.company_access_auth_uid_v1()
  and public.company_access_is_accepted_owner_v1(company_id)
);
drop policy if exists "company members can read bank suggestion acceptances"
  on public.bank_suggestion_acceptances;
create policy "company members can read bank suggestion acceptances"
on public.bank_suggestion_acceptances for select to authenticated
using (public.company_access_is_accepted_member_v1(company_id));

grant select, insert, update on public.bank_transactions to authenticated;
grant select on public.bank_suggestion_acceptances to authenticated;
grant all on public.bank_transactions, public.bank_suggestion_acceptances
  to service_role;
grant select, insert, update, delete on public.bank_transactions,
  public.bank_suggestion_acceptances to banking_store_owner;
grant select, insert, update, delete on public.bank_suggestion_acceptances
  to ledger_store_owner;

alter table public.holding_actions
  drop constraint if exists holding_actions_bank_transaction_id_fkey;
alter table public.holding_actions
  add constraint holding_actions_bank_transaction_id_fkey
  foreign key (bank_transaction_id) references public.bank_transactions(id)
  on delete restrict;

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

create or replace function backend_system.sync_banking_acceptance_to_legacy_v1()
returns trigger
language plpgsql
security definer
set search_path = ''
as $function$
declare
  v_lines jsonb;
begin
  if pg_catalog.pg_trigger_depth() > 1 then
    return coalesce(new, old);
  end if;
  if tg_op = 'DELETE' then
    delete from public.bank_suggestion_acceptances where id = old.id;
    return old;
  end if;
  select entry.lines into strict v_lines
  from ledger.entries entry
  where entry.id = new.accounting_entry_id
    and entry.company_id = new.company_id
    and entry.source_capability = 'BANKING'
    and entry.source_record_id = new.id::text;
  insert into public.bank_suggestion_acceptances (
    id, company_id, bank_transaction_id, ledger_entry_id, rule_id,
    rule_version, reason, lines, accepted_by, accepted_at
  ) values (
    new.id, new.company_id, new.bank_transaction_id,
    new.accounting_entry_id, pg_catalog.lower(new.suggestion_kind),
    new.rule_version, new.reason, v_lines, new.accepted_by, new.accepted_at
  )
  on conflict (id) do update set
    company_id = excluded.company_id,
    bank_transaction_id = excluded.bank_transaction_id,
    ledger_entry_id = excluded.ledger_entry_id,
    rule_id = excluded.rule_id,
    rule_version = excluded.rule_version,
    reason = excluded.reason,
    lines = excluded.lines,
    accepted_by = excluded.accepted_by,
    accepted_at = excluded.accepted_at;
  return new;
exception
  when no_data_found or too_many_rows then
    raise exception 'banking_acceptance_ledger_binding_missing';
end;
$function$;

alter function backend_system.sync_legacy_bank_transaction_to_banking_v1()
  owner to banking_store_owner;
alter function backend_system.sync_banking_transaction_to_legacy_v1()
  owner to banking_store_owner;
alter function backend_system.sync_legacy_bank_acceptance_to_banking_v1()
  owner to banking_store_owner;
alter function backend_system.sync_banking_acceptance_to_legacy_v1()
  owner to ledger_store_owner;
revoke all on function
  backend_system.sync_banking_acceptance_to_legacy_v1()
from public, anon, authenticated, service_role;
grant execute on function
  backend_system.sync_banking_acceptance_to_legacy_v1()
to banking_store_owner;

create trigger bank_transactions_sync_to_banking
after insert or update or delete on public.bank_transactions
for each row execute function
  backend_system.sync_legacy_bank_transaction_to_banking_v1();
create trigger banking_transactions_sync_to_legacy
after insert or update or delete on banking.transactions
for each row execute function
  backend_system.sync_banking_transaction_to_legacy_v1();
create trigger bank_acceptances_sync_to_banking
after insert or update or delete on public.bank_suggestion_acceptances
for each row execute function
  backend_system.sync_legacy_bank_acceptance_to_banking_v1();
create trigger banking_acceptances_sync_to_legacy
after insert or update or delete on banking.suggestion_acceptances
for each row execute function
  backend_system.sync_banking_acceptance_to_legacy_v1();
create trigger company_archive_track_bank_suggestion_acceptances
before insert or update or delete on public.bank_suggestion_acceptances
for each row execute function public.company_archive_track_source_write_v1(
  'company', 'company_id'
);

-- The public RPC was already disabled by #139. Preserve that predecessor
-- object identity without restoring a browser writer or a SQL policy copy.
create or replace function public.accept_bank_transaction_suggestion(
  p_bank_transaction_id uuid,
  p_rule_id text,
  p_rule_version text
)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $function$
begin
  raise exception 'banking_legacy_rpc_retired';
end;
$function$;
revoke all on function public.accept_bank_transaction_suggestion(
  uuid, text, text
) from public, anon, authenticated, service_role;

create or replace function backend_system.prepare_bank_transaction_suggestion_v1(
  p_request jsonb, p_verified_subject text
)
returns jsonb language plpgsql security definer set search_path = ''
as $function$
declare
  v_replay jsonb;
  v_bank public.bank_transactions%rowtype;
  v_existing public.bank_suggestion_acceptances%rowtype;
  v_bank_match boolean;
  v_subscription_match boolean;
  v_interest_match boolean;
  v_match_count integer;
  v_rule text := p_request ->> 'rule';
  v_version text := p_request ->> 'ruleVersion';
  v_text text;
  v_amount numeric;
  v_reason text;
begin
  v_replay := backend_system.claim_ledger_writer_v1(
    'accept_bank_transaction_suggestion', p_request, p_verified_subject
  );
  if v_replay is not null then
    return pg_catalog.jsonb_build_object('replay', v_replay);
  end if;
  perform backend_system.lock_ledger_writer_year_v1(p_request);
  select bank.* into v_bank from public.bank_transactions bank
  where bank.id = (p_request ->> 'bankTransactionId')::uuid for update;
  if not found or v_bank.company_id <> (p_request ->> 'companyId')::uuid
    or v_bank.income_year <> (p_request ->> 'incomeYear')::integer
  then raise exception 'ledger_invalid_input'; end if;
  select acceptance.* into v_existing
  from public.bank_suggestion_acceptances acceptance
  where acceptance.bank_transaction_id = v_bank.id;
  if found then
    if v_existing.rule_id = v_rule and v_existing.rule_version = v_version
      and v_bank.matched_entry_id = v_existing.ledger_entry_id
    then
      return pg_catalog.jsonb_build_object(
        'replay', backend_system.ledger_writer_entry_result_v1(
          v_existing.ledger_entry_id,
          pg_catalog.jsonb_build_object(
            'acceptanceId', v_existing.id, 'rule', v_rule,
            'ruleVersion', v_version, 'auditRequired', false
          )
        )
      );
    end if;
    raise exception 'ledger_idempotency_key_reused';
  end if;
  if v_bank.matched_entry_id is not null or v_bank.matched_action_id is not null
    or v_bank.accepted_warning or v_version <> '2026-07-13.1'
  then raise exception 'ledger_invalid_input'; end if;
  v_text := pg_catalog.lower(pg_catalog.btrim(coalesce(v_bank.text, '')));
  v_bank_match := v_text ~ '(^|[^[:alnum:]])(årsgebyr|arsgebyr|bankgebyr|bank fee|annual fee)($|[^[:alnum:]])';
  v_subscription_match := v_text ~ '(^|[^[:alnum:]])(systemabonnement|system subscription)($|[^[:alnum:]])';
  v_interest_match := v_text ~ '(^|[^[:alnum:]])(renter|rente|interest)($|[^[:alnum:]])';
  v_match_count := v_bank_match::integer + v_subscription_match::integer
    + v_interest_match::integer;
  if v_match_count <> 1
    or (v_rule = 'bank_fee' and not v_bank_match)
    or (v_rule = 'system_subscription' and not v_subscription_match)
    or (v_rule = 'deposit_interest' and not v_interest_match)
    or v_rule not in ('bank_fee', 'system_subscription', 'deposit_interest')
    or (v_rule in ('bank_fee', 'system_subscription') and v_bank.amount >= 0)
    or (v_rule = 'deposit_interest' and v_bank.amount <= 0)
  then raise exception 'ledger_invalid_input'; end if;
  v_amount := pg_catalog.round(pg_catalog.abs(v_bank.amount), 2);
  if v_amount <= 0 then raise exception 'ledger_invalid_input'; end if;
  v_reason := case v_rule
    when 'bank_fee' then 'Teksten beskriver et bankgebyr og beløpet er en utbetaling.'
    when 'system_subscription' then 'Teksten beskriver et systemabonnement og beløpet er en utbetaling.'
    else 'Teksten beskriver renteinntekt og beløpet er en innbetaling.' end;
  return pg_catalog.jsonb_build_object(
    'replay', null, 'amount', v_amount, 'transactionText', v_bank.text,
    'reason', v_reason
  );
end;
$function$;

create or replace function backend_system.complete_bank_transaction_suggestion_v1(
  p_request jsonb, p_entry_id uuid, p_prepared jsonb, p_verified_subject text
)
returns jsonb language plpgsql security definer set search_path = ''
as $function$
declare
  v_actor_id uuid := public.company_access_auth_uid_v1();
  v_acceptance_id uuid := (p_request ->> 'acceptanceId')::uuid;
  v_bank_id uuid := (p_request ->> 'bankTransactionId')::uuid;
  v_entry ledger.entries%rowtype;
  v_result jsonb;
  v_count integer;
begin
  select entry.* into v_entry from ledger.entries entry where entry.id = p_entry_id;
  if v_actor_id is distinct from p_verified_subject::uuid
    or pg_catalog.jsonb_typeof(p_prepared) is distinct from 'object'
    or not found or v_entry.company_id <> (p_request ->> 'companyId')::uuid
    or v_entry.entry_kind <> 'BANK_RULE_SUGGESTION'
    or v_entry.source_record_id <> v_acceptance_id::text
  then raise exception 'ledger_dependency_unavailable'; end if;
  insert into public.bank_suggestion_acceptances (
    id, company_id, bank_transaction_id, ledger_entry_id, rule_id,
    rule_version, reason, lines, accepted_by
  ) values (
    v_acceptance_id, v_entry.company_id, v_bank_id, p_entry_id,
    p_request ->> 'rule', p_request ->> 'ruleVersion',
    p_prepared ->> 'reason', v_entry.lines, v_actor_id
  );
  update public.bank_transactions set matched_entry_id = p_entry_id
  where id = v_bank_id and matched_entry_id is null
    and matched_action_id is null and not accepted_warning;
  get diagnostics v_count = row_count;
  if v_count <> 1 then raise exception 'ledger_idempotency_key_reused'; end if;
  insert into public.audit_events (company_id, actor_id, category, action, message)
  values (
    v_entry.company_id, v_actor_id, 'bank', 'bank_suggestion_accepted',
    'Eier godkjente bankregel ' || (p_request ->> 'rule') || ' versjon '
      || (p_request ->> 'ruleVersion') || '.'
  );
  v_result := backend_system.ledger_writer_entry_result_v1(
    p_entry_id,
    pg_catalog.jsonb_build_object(
      'acceptanceId', v_acceptance_id, 'rule', p_request ->> 'rule',
      'ruleVersion', p_request ->> 'ruleVersion', 'auditRequired', false
    )
  );
  return backend_system.complete_ledger_writer_v1(
    'accept_bank_transaction_suggestion', p_request, v_result,
    p_verified_subject
  );
end;
$function$;

revoke all on function
  backend_system.prepare_bank_transaction_suggestion_v1(jsonb, text),
  backend_system.complete_bank_transaction_suggestion_v1(
    jsonb, uuid, jsonb, text
  )
from public, anon, authenticated, service_role, ledger_executor,
  ledger_store_owner, ledger_workflow_executor, talli_ledger_backend;
grant execute on function
  backend_system.prepare_bank_transaction_suggestion_v1(jsonb, text),
  backend_system.complete_bank_transaction_suggestion_v1(
    jsonb, uuid, jsonb, text
  )
to ledger_workflow_executor;

set local role ledger_store_owner;
do $banking_rollback_backend_system_authority_revoke$
begin
  execute pg_catalog.format(
    'revoke create on schema backend_system from %I',
    pg_catalog.current_setting('talli.banking_rollback_migration_principal')
  );
end
$banking_rollback_backend_system_authority_revoke$;
reset role;

do $banking_rollback_migration_authority_revoke$
begin
  execute pg_catalog.format(
    'revoke banking_store_owner, ledger_store_owner, company_archive_projection_executor from %I',
    current_user
  );
end
$banking_rollback_migration_authority_revoke$;

commit;
