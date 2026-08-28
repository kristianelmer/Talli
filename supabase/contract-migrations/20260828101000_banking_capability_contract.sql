-- CONTRACT RELEASE ARTIFACT: #140 banking backend authority cutover.
-- Apply only after the generated-client browser cutover, backend runtime,
-- reconciliation, and rollback rehearsal pass. This file is intentionally
-- outside the automatic Supabase migration runner.

begin;

do $banking_contract_migration_authority$
begin
  execute pg_catalog.format(
    'grant banking_store_owner, ledger_store_owner, company_archive_projection_executor to %I',
    current_user
  );
  grant create on schema public to banking_store_owner,
    company_archive_projection_executor;
end
$banking_contract_migration_authority$;

set local role banking_store_owner;
drop policy if exists "banking overlap mirrors legacy transactions"
  on banking.transactions;
drop policy if exists "banking overlap mirrors legacy acceptances"
  on banking.suggestion_acceptances;
reset role;

select pg_catalog.pg_advisory_xact_lock(
  pg_catalog.hashtextextended('talli:banking:capability-cutover:v1', 0)
);
lock table public.bank_transactions in share row exclusive mode;
lock table public.bank_suggestion_acceptances in share row exclusive mode;
lock table banking.transactions in share row exclusive mode;
lock table banking.suggestion_acceptances in share row exclusive mode;

drop policy if exists "banking overlap mirrors canonical transactions"
  on public.bank_transactions;
revoke select, insert, update, delete on public.bank_transactions
  from banking_store_owner;
drop policy if exists "banking overlap mirrors canonical acceptances"
  on public.bank_suggestion_acceptances;
revoke select, insert, update, delete on public.bank_suggestion_acceptances
  from ledger_store_owner;

do $banking_contract_transaction_reconciliation$
declare
  source_row_count bigint;
  target_row_count bigint;
  source_sha256 text;
  target_sha256 text;
begin
  select
    pg_catalog.count(*),
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
        )::text, 'sha256'
      ), 'hex'), '' order by bank_row.id), ''), 'sha256'), 'hex')
  into source_row_count, source_sha256
  from public.bank_transactions bank_row;

  select
    pg_catalog.count(*),
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
          'matched_accounting_entry_id', bank_row.matched_accounting_entry_id,
          'matched_action_reference', bank_row.matched_action_reference,
          'warning_accepted', bank_row.warning_accepted,
          'created_by', bank_row.created_by,
          'created_at', bank_row.created_at
        )::text, 'sha256'
      ), 'hex'), '' order by bank_row.id), ''), 'sha256'), 'hex')
  into target_row_count, target_sha256
  from banking.transactions bank_row;

  if source_row_count <> target_row_count
    or source_sha256 <> target_sha256
  then
    raise exception 'banking_contract_transaction_reconciliation_failed';
  end if;
end
$banking_contract_transaction_reconciliation$;

do $banking_contract_acceptance_reconciliation$
declare
  source_row_count bigint;
  target_row_count bigint;
  source_sha256 text;
  target_sha256 text;
begin
  select
    pg_catalog.count(*),
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
        )::text, 'sha256'
      ), 'hex'), '' order by acceptance.id), ''), 'sha256'), 'hex')
  into source_row_count, source_sha256
  from public.bank_suggestion_acceptances acceptance;

  select
    pg_catalog.count(*),
    pg_catalog.encode(extensions.digest(coalesce(pg_catalog.string_agg(
      acceptance.id::text || ':' || pg_catalog.encode(extensions.digest(
        pg_catalog.to_jsonb(acceptance)::text, 'sha256'
      ), 'hex'), '' order by acceptance.id), ''), 'sha256'), 'hex')
  into target_row_count, target_sha256
  from banking.suggestion_acceptances acceptance;

  if source_row_count <> target_row_count
    or source_sha256 <> target_sha256
  then
    raise exception 'banking_contract_acceptance_reconciliation_failed';
  end if;
end
$banking_contract_acceptance_reconciliation$;

-- Disable every predecessor writer before removing the overlap storage.
revoke execute on function public.accept_bank_transaction_suggestion(
  uuid, text, text
) from public, anon, authenticated, service_role;
revoke execute on function
  backend_system.prepare_bank_transaction_suggestion_v1(jsonb, text),
  backend_system.complete_bank_transaction_suggestion_v1(
    jsonb, uuid, jsonb, text
  )
from public, anon, authenticated, service_role, ledger_executor,
  ledger_store_owner, ledger_workflow_executor, talli_ledger_backend;

drop trigger if exists banking_transactions_sync_to_legacy
  on banking.transactions;
drop trigger if exists bank_transactions_sync_to_banking
  on public.bank_transactions;
drop trigger if exists bank_acceptances_sync_to_banking
  on public.bank_suggestion_acceptances;
drop trigger if exists banking_acceptances_sync_to_legacy
  on banking.suggestion_acceptances;
drop trigger if exists company_archive_track_bank_suggestion_acceptances
  on public.bank_suggestion_acceptances;

drop function public.accept_bank_transaction_suggestion(uuid, text, text);
drop function backend_system.complete_bank_transaction_suggestion_v1(jsonb, uuid, jsonb, text);
drop function backend_system.prepare_bank_transaction_suggestion_v1(jsonb, text);
drop function backend_system.sync_legacy_bank_transaction_to_banking_v1();
drop function backend_system.sync_banking_transaction_to_legacy_v1();
drop function backend_system.sync_legacy_bank_acceptance_to_banking_v1();
drop function backend_system.sync_banking_acceptance_to_legacy_v1();

-- A later serialized capability may still carry an opaque bank transaction
-- reference. Preserve referential integrity against the canonical owner.
alter table public.holding_actions
  drop constraint if exists holding_actions_bank_transaction_id_fkey;
alter table public.holding_actions
  add constraint holding_actions_bank_transaction_id_fkey
  foreign key (bank_transaction_id) references banking.transactions(id)
  on delete restrict;

delete from public.bank_suggestion_acceptances;
delete from public.bank_transactions;

do $banking_legacy_acceptance_empty_preflight$
begin
  if pg_catalog.to_regclass('public.bank_suggestion_acceptances') is not null
    and exists (select 1 from public.bank_suggestion_acceptances)
  then
    raise exception 'banking_contract_legacy_acceptances_not_empty';
  end if;
end
$banking_legacy_acceptance_empty_preflight$;

drop table if exists public.bank_suggestion_acceptances;

do $banking_legacy_transaction_empty_preflight$
begin
  if pg_catalog.to_regclass('public.bank_transactions') is not null
    and exists (select 1 from public.bank_transactions)
  then
    raise exception 'banking_contract_legacy_transactions_not_empty';
  end if;
end
$banking_legacy_transaction_empty_preflight$;

drop table if exists public.bank_transactions;

-- Frozen later-stage ledger coordinators may read or claim a bank fact, but
-- the compatibility relation has no browser authority and owns no policy.
create view public.bank_transactions
with (security_barrier = true)
as
select
  bank_row.id,
  bank_row.company_id,
  bank_row.income_year,
  bank_row.transaction_date,
  bank_row.text,
  bank_row.amount,
  bank_row.balance,
  bank_row.source_hash,
  bank_row.matched_accounting_entry_id as matched_entry_id,
  bank_row.matched_action_reference as matched_action_id,
  bank_row.warning_accepted as accepted_warning,
  bank_row.created_by,
  bank_row.created_at
from banking.transactions bank_row;
alter view public.bank_transactions owner to banking_store_owner;
revoke all on public.bank_transactions
  from public, anon, authenticated, service_role;

do $banking_frozen_consumer_grants$
declare
  frozen_consumer_owner name;
begin
  for frozen_consumer_owner in
    select distinct owner.rolname
    from pg_catalog.pg_proc routine
    join pg_catalog.pg_namespace namespace
      on namespace.oid = routine.pronamespace
    join pg_catalog.pg_roles owner on owner.oid = routine.proowner
    where namespace.nspname in ('backend_system', 'public')
      and routine.proname in (
        'prepare_administrative_cost_v1',
        'complete_administrative_cost_v1',
        'prepare_investment_dividend_v1',
        'complete_investment_dividend_v1',
        'prepare_shareholder_loan_v1',
        'complete_shareholder_loan_v1',
        'prepare_tax_settlement_v1',
        'complete_tax_settlement_v1',
        'prepare_investment_purchase_fifo_v1',
        'complete_investment_purchase_fifo_v1',
        'prepare_investment_sale_fifo_v1',
        'complete_investment_sale_fifo_v1',
        'prepare_owner_dividend_payment_v1',
        'complete_owner_dividend_payment_v1',
        'record_share_purchase_fifo',
        'record_share_sale_fifo',
        'record_owner_dividend_payment'
      )
  loop
    execute pg_catalog.format(
      'grant select, update on public.bank_transactions to %I',
      frozen_consumer_owner
    );
  end loop;
end
$banking_frozen_consumer_grants$;

-- The later company-archive stage keeps its exact read shape without owning a
-- second banking store or suggestion rule. Ledger lines are projected from
-- the already-linked canonical accounting entry.
grant usage on schema banking, ledger to company_archive_projection_executor;
grant select on banking.suggestion_acceptances
  to company_archive_projection_executor;
grant select (id, lines) on ledger.entries
  to company_archive_projection_executor;
grant execute on function public.company_access_is_accepted_member_v1(uuid)
  to company_archive_projection_executor;

create or replace function public.company_archive_can_read_banking_acceptance_v1(
  p_company_id uuid
)
returns boolean
language sql
stable
security definer
set search_path = ''
as $function$
  select public.company_access_is_accepted_member_v1(p_company_id);
$function$;
alter function public.company_archive_can_read_banking_acceptance_v1(uuid)
  owner to company_archive_projection_executor;
revoke all on function
  public.company_archive_can_read_banking_acceptance_v1(uuid)
from public, anon, authenticated, service_role;
grant execute on function
  public.company_archive_can_read_banking_acceptance_v1(uuid)
to authenticated;

drop policy if exists "archive projection reads banking acceptances"
  on banking.suggestion_acceptances;
create policy "archive projection reads banking acceptances"
on banking.suggestion_acceptances for select
to company_archive_projection_executor
using (public.company_archive_can_read_banking_acceptance_v1(company_id));
drop policy if exists "archive projection reads linked ledger lines"
  on ledger.entries;
create policy "archive projection reads linked ledger lines"
on ledger.entries for select to company_archive_projection_executor
using (public.company_archive_can_read_banking_acceptance_v1(company_id));

create view public.bank_suggestion_acceptances
with (security_barrier = true)
as
select
  acceptance.id,
  acceptance.company_id,
  acceptance.bank_transaction_id,
  acceptance.accounting_entry_id as ledger_entry_id,
  pg_catalog.lower(acceptance.suggestion_kind) as rule_id,
  acceptance.rule_version,
  acceptance.reason,
  entry.lines,
  acceptance.accepted_by,
  acceptance.accepted_at
from banking.suggestion_acceptances acceptance
join ledger.entries entry on entry.id = acceptance.accounting_entry_id
where public.company_archive_can_read_banking_acceptance_v1(
  acceptance.company_id
);
alter view public.bank_suggestion_acceptances
  owner to company_archive_projection_executor;
revoke all on public.bank_suggestion_acceptances
  from public, anon, authenticated, service_role;
grant select on public.bank_suggestion_acceptances to authenticated;

create trigger company_archive_track_bank_suggestion_acceptances
before insert or update or delete on banking.suggestion_acceptances
for each row execute function public.company_archive_track_source_write_v1(
  'company', 'company_id'
);

revoke all on banking.transactions, banking.suggestion_acceptances
  from public, anon, authenticated, service_role;
revoke usage on schema banking from public, anon, authenticated, service_role;

do $banking_contract_migration_authority_revoke$
begin
  revoke create on schema public from banking_store_owner,
    company_archive_projection_executor;
  execute pg_catalog.format(
    'revoke banking_store_owner, ledger_store_owner, company_archive_projection_executor from %I',
    current_user
  );
end
$banking_contract_migration_authority_revoke$;

commit;
