-- CONTRACT RELEASE ARTIFACT: #139 ledger backend authority cutover.
-- Apply only after every production caller uses the Python/generated-client
-- boundary and the expand reconciliation has been reviewed.

begin;

do $ledger_contract_migration_authority$
begin
  execute pg_catalog.format('grant ledger_store_owner to %I', current_user);
end
$ledger_contract_migration_authority$;

select pg_catalog.pg_advisory_xact_lock(
  pg_catalog.hashtextextended('talli:ledger:capability-cutover:v1', 0)
);

do $ledger_writer_coordinator_barrier$
declare
  v_signature text;
begin
  foreach v_signature in array array[
    'backend_system.prepare_administrative_cost_v1(jsonb,text)',
    'backend_system.complete_administrative_cost_v1(jsonb,uuid,jsonb,text)',
    'backend_system.prepare_investment_dividend_v1(jsonb,text)',
    'backend_system.complete_investment_dividend_v1(jsonb,uuid,jsonb,text)',
    'backend_system.prepare_shareholder_loan_v1(jsonb,text)',
    'backend_system.complete_shareholder_loan_v1(jsonb,uuid,jsonb,text)',
    'backend_system.prepare_tax_settlement_v1(jsonb,text)',
    'backend_system.complete_tax_settlement_v1(jsonb,uuid,jsonb,text)',
    'backend_system.prepare_bank_transaction_suggestion_v1(jsonb,text)',
    'backend_system.complete_bank_transaction_suggestion_v1(jsonb,uuid,jsonb,text)',
    'backend_system.prepare_investment_purchase_fifo_v1(jsonb,text)',
    'backend_system.complete_investment_purchase_fifo_v1(jsonb,uuid,jsonb,text)',
    'backend_system.prepare_investment_sale_fifo_v1(jsonb,text)',
    'backend_system.complete_investment_sale_fifo_v1(jsonb,uuid,jsonb,text)',
    'backend_system.prepare_corporate_decision_finalization_v1(jsonb,text)',
    'backend_system.complete_corporate_decision_finalization_v1(jsonb,uuid,jsonb,text)',
    'backend_system.prepare_owner_dividend_payment_v1(jsonb,text)',
    'backend_system.complete_owner_dividend_payment_v1(jsonb,uuid,jsonb,text)',
    'ledger.post_entry_with_id_v1(text,uuid,integer,text,text,jsonb,jsonb,boolean,text,text,text,text,uuid)'
  ] loop
    if pg_catalog.to_regprocedure(v_signature) is null then
      raise exception 'ledger_contract_writer_coordinator_missing:%', v_signature;
    end if;
  end loop;
end
$ledger_writer_coordinator_barrier$;

do $ledger_contract_reconciliation$
declare
  v_latest_run_id uuid;
begin
  select run.id into v_latest_run_id
  from backend_system.ledger_migration_runs run
  where run.completed_at is not null
  order by run.completed_at desc, run.id desc
  limit 1;

  if v_latest_run_id is null or not exists (
    select 1
    from backend_system.ledger_migration_reconciliations reconciliation
    where reconciliation.run_id = v_latest_run_id
    group by reconciliation.run_id
    having count(*) = 2
      and pg_catalog.bool_and(
        reconciliation.source_row_count
          = reconciliation.accepted_row_count
            + reconciliation.quarantined_row_count
      )
      and pg_catalog.bool_and(
        pg_catalog.char_length(reconciliation.source_sha256) = 64
      )
      and pg_catalog.bool_and(
        pg_catalog.char_length(reconciliation.accepted_sha256) = 64
      )
      and pg_catalog.bool_and(
        pg_catalog.char_length(reconciliation.quarantine_sha256) = 64
      )
  ) then
    raise exception 'ledger_contract_reconciliation_missing';
  end if;

  if exists (
    select 1
    from backend_system.ledger_migration_quarantine quarantine
    where pg_catalog.btrim(quarantine.reason_code) = ''
      or pg_catalog.char_length(quarantine.payload_sha256) <> 64
  ) then
    raise exception 'ledger_contract_quarantine_incomplete';
  end if;
end
$ledger_contract_reconciliation$;

-- Retire every predecessor SQL routine that can author an accounting result.
revoke execute on function public.accept_bank_transaction_suggestion(
  uuid, text, text
) from public, anon, authenticated, service_role;
revoke execute on function public.record_share_purchase_fifo(
  uuid, uuid, integer, text, text, text, text, date, bigint, numeric,
  text, uuid, uuid, text
) from public, anon, authenticated, service_role;
revoke execute on function public.record_share_sale_fifo(
  uuid, uuid, integer, uuid, date, bigint, numeric, uuid, uuid, text
) from public, anon, authenticated, service_role;
revoke execute on function public.finalize_corporate_decision(jsonb)
  from public, anon, authenticated, service_role;
revoke execute on function public.record_owner_dividend_payment(jsonb)
  from public, anon, authenticated, service_role;

-- The public relations were frozen, security-invoker overlap facades. The
-- physical ledger relations remain in ledger and continue to keep their OIDs.
revoke all on public.ledger_entries
  from public, anon, authenticated, service_role;
revoke all on public.period_locks
  from public, anon, authenticated, service_role;
drop view public.ledger_entries;
drop view public.period_locks;

revoke all on ledger.entries, ledger.period_locks
  from public, anon, authenticated, service_role;
revoke usage on schema ledger
  from public, anon, authenticated, service_role;

drop policy if exists "company members can read ledger entries"
  on ledger.entries;
drop policy if exists "owners can create ledger entries"
  on ledger.entries;
drop policy if exists "company members can read period locks"
  on ledger.period_locks;
drop policy if exists "owners can create period locks"
  on ledger.period_locks;

-- Other capabilities retain only opaque ledger IDs. The one frozen archive
-- freshness trigger remains attached to the physical relation through the
-- schema move; it owns no ledger policy and is retired with its capability.
alter table public.bank_transactions
  drop constraint if exists bank_transactions_matched_entry_id_fkey;
alter table public.holding_actions
  drop constraint if exists holding_actions_ledger_entry_id_fkey;
alter table public.bank_suggestion_acceptances
  drop constraint if exists bank_suggestion_acceptances_ledger_entry_id_fkey;
alter table public.corporate_decision_finalizations
  drop constraint if exists corporate_decision_finalizations_ledger_entry_id_fkey;

do $ledger_archive_freshness_barrier$
declare
  v_trigger_count integer;
  v_trigger_valid boolean;
begin
  if pg_catalog.to_regprocedure(
    'public.company_archive_track_source_write_v1()'
  ) is null then
    raise exception 'ledger_archive_freshness_function_missing';
  end if;

  select pg_catalog.count(*), pg_catalog.bool_and(
    trigger.tgname = 'company_archive_track_ledger_entries'
    and trigger.tgenabled in ('O', 'A')
    and trigger.tgtype = 31
    and trigger.tgnargs = 2
    and pg_catalog.encode(trigger.tgargs, 'hex')
      = '7965617200636f6d70616e795f696400'
  ) into v_trigger_count, v_trigger_valid
    from pg_catalog.pg_trigger trigger
    where trigger.tgrelid = 'ledger.entries'::pg_catalog.regclass
      and trigger.tgfoid = pg_catalog.to_regprocedure(
        'public.company_archive_track_source_write_v1()'
      )
      and not trigger.tgisinternal;

  if v_trigger_count <> 1 or not coalesce(v_trigger_valid, false) then
    raise exception 'ledger_archive_freshness_trigger_invalid';
  end if;
end
$ledger_archive_freshness_barrier$;

alter table ledger.entries
  drop constraint if exists ledger_entries_setup_id_fkey;
do $ledger_setup_reference_barrier$
begin
  if exists (
    select 1 from ledger.entries
    where setup_id is not null and entry_kind <> 'OPENING_BALANCE'
  ) then
    raise exception 'ledger_contract_unsupported_legacy_setup_reference';
  end if;
end
$ledger_setup_reference_barrier$;
alter table ledger.entries drop column setup_id;

-- Opening/shareholder persistence belongs to its frozen target shell. Browser
-- code may no longer start a company year through direct table mutation.
revoke insert, update, delete on public.opening_balance_setups
  from public, anon, authenticated, service_role;
revoke insert, update, delete on public.opening_shareholders
  from public, anon, authenticated, service_role;
drop policy if exists "owners can create opening balance setups"
  on public.opening_balance_setups;
drop policy if exists "owners can create opening shareholders"
  on public.opening_shareholders;

do $ledger_contract_migration_authority_revoke$
begin
  execute pg_catalog.format('revoke ledger_store_owner from %I', current_user);
end
$ledger_contract_migration_authority_revoke$;

commit;
