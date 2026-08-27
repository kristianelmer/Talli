-- Phase-aware rollback for the #139 ledger contract release artifact.
-- The target writer is disabled first. One physical store is then returned to
-- the frozen legacy facade. Evidence/receipts remain immutable for recutover.

begin;

select pg_catalog.pg_advisory_xact_lock(
  pg_catalog.hashtextextended('talli:ledger:capability-cutover:v1', 0)
);

-- Exactly one writer: disable every target entry point before exposing legacy.
revoke all on function
  backend_system.prepare_administrative_cost_v1(jsonb, text),
  backend_system.complete_administrative_cost_v1(jsonb, uuid, jsonb, text),
  backend_system.prepare_investment_dividend_v1(jsonb, text),
  backend_system.complete_investment_dividend_v1(jsonb, uuid, jsonb, text),
  backend_system.prepare_shareholder_loan_v1(jsonb, text),
  backend_system.complete_shareholder_loan_v1(jsonb, uuid, jsonb, text),
  backend_system.prepare_tax_settlement_v1(jsonb, text),
  backend_system.complete_tax_settlement_v1(jsonb, uuid, jsonb, text),
  backend_system.prepare_bank_transaction_suggestion_v1(jsonb, text),
  backend_system.complete_bank_transaction_suggestion_v1(jsonb, uuid, jsonb, text),
  backend_system.prepare_investment_purchase_fifo_v1(jsonb, text),
  backend_system.complete_investment_purchase_fifo_v1(jsonb, uuid, jsonb, text),
  backend_system.prepare_investment_sale_fifo_v1(jsonb, text),
  backend_system.complete_investment_sale_fifo_v1(jsonb, uuid, jsonb, text),
  backend_system.prepare_corporate_decision_finalization_v1(jsonb, text),
  backend_system.complete_corporate_decision_finalization_v1(jsonb, uuid, jsonb, text),
  backend_system.prepare_owner_dividend_payment_v1(jsonb, text),
  backend_system.complete_owner_dividend_payment_v1(jsonb, uuid, jsonb, text),
  ledger.post_entry_with_id_v1(
    text, uuid, integer, text, text, jsonb, jsonb, boolean,
    text, text, text, text, uuid
  )
from ledger_workflow_executor, talli_ledger_backend;
revoke all on function
  backend_system.claim_ledger_workflow_v1(text, text, uuid, jsonb, text),
  backend_system.record_opening_snapshot_legacy_v1(
    uuid, integer, numeric, numeric, integer, numeric, jsonb, text
  ),
  backend_system.complete_ledger_workflow_v1(
    text, text, uuid, jsonb, jsonb, text
  )
from ledger_workflow_executor, talli_ledger_backend;
revoke all on function ledger.post_entry(
  text, uuid, integer, text, text, jsonb, jsonb, boolean,
  text, text, text, text
) from ledger_workflow_executor;
revoke ledger_workflow_executor from talli_ledger_backend;
revoke all on function ledger.post_entry(
  text, uuid, integer, text, text, jsonb, jsonb, boolean,
  text, text, text, text
) from ledger_executor, talli_ledger_backend;
revoke all on function ledger.post_supported_entry_v1(
  text, uuid, integer, text, text, jsonb, text, text, text, text,
  date, text, jsonb
) from ledger_executor, ledger_workflow_executor, talli_ledger_backend;
revoke all on function ledger.correct_entry_v1(
  text, uuid, integer, uuid, text, text, text, jsonb, text, text,
  date, text, text, jsonb
) from ledger_executor, ledger_workflow_executor, talli_ledger_backend;
revoke all on function ledger.record_reconstruction_assessment(
  text, uuid, integer, date, jsonb, text, text[], text, text
) from ledger_executor, ledger_workflow_executor, talli_ledger_backend;
revoke all on function ledger.close_company_year_v1(
  text, uuid, integer, date, text, uuid, text, jsonb,
  text, text[], text, text
) from ledger_executor, ledger_workflow_executor, talli_ledger_backend;
revoke all on function ledger.record_received_dividend_decision_v1(
  text, uuid, integer, text, jsonb, text, text, text, text, date, text, jsonb
) from ledger_executor, ledger_workflow_executor, talli_ledger_backend;
revoke all on function ledger.record_received_dividend_payment_v1(
  text, uuid, integer, uuid, text, jsonb, text, text, text, text,
  date, text, jsonb
) from ledger_executor, ledger_workflow_executor, talli_ledger_backend;
revoke all on function ledger.record_bank_loan_disbursement_v1(
  text, uuid, integer, text, numeric, text, jsonb, text, text, text,
  text, date, text, jsonb
) from ledger_executor, ledger_workflow_executor, talli_ledger_backend;
revoke all on function ledger.record_bank_loan_payment_v1(
  text, uuid, integer, text, numeric, numeric, numeric, text, jsonb,
  text, text, text, text, date, text, jsonb
) from ledger_executor, ledger_workflow_executor, talli_ledger_backend;
revoke all on function ledger.record_cash_capital_increase_subscription_v1(
  text, uuid, integer, text, numeric, numeric, text, jsonb, text, text,
  text, text, date, text, jsonb
) from ledger_executor, ledger_workflow_executor, talli_ledger_backend;
revoke all on function ledger.record_cash_capital_increase_restricted_payment_v1(
  text, uuid, integer, text, numeric, numeric, text, jsonb, text, text,
  text, text, date, text, jsonb
) from ledger_executor, ledger_workflow_executor, talli_ledger_backend;
revoke all on function ledger.record_cash_capital_increase_registration_v1(
  text, uuid, integer, text, numeric, numeric, text, jsonb, text, text,
  text, text, date, text, jsonb
) from ledger_executor, ledger_workflow_executor, talli_ledger_backend;
revoke all on function ledger.lock_period(
  text, uuid, integer, text, text, text
) from ledger_executor, talli_ledger_backend;
revoke all on function ledger.list_entries(uuid[], text, integer, text)
  from ledger_executor, talli_ledger_backend;
revoke all on function ledger.list_period_locks(uuid[], text, integer, text)
  from ledger_executor, talli_ledger_backend;
-- Keep the backend's NOINHERIT membership in the read-only executor so the
-- opening-snapshot compatibility query remains available throughout rollback.
-- Every ledger writer and ledger-table query above is still explicitly revoked.

drop trigger if exists ledger_entries_enforce_boundary on ledger.entries;
drop policy if exists "ledger store reads entries" on ledger.entries;
drop policy if exists "ledger store posts entries" on ledger.entries;
drop policy if exists "ledger store reads period locks" on ledger.period_locks;
drop policy if exists "ledger store creates period locks" on ledger.period_locks;

-- Restore the predecessor correlation column without losing target entries.
alter table ledger.entries add column if not exists setup_id uuid;
update ledger.entries
set setup_id = pg_catalog.substring(
  source_record_id, '^opening-setup:([0-9a-fA-F-]{36})$'
)::uuid
where entry_kind = 'OPENING_BALANCE'
  and setup_id is null
  and source_record_id ~ '^opening-setup:[0-9a-fA-F-]{36}$';
alter table ledger.entries
  add constraint ledger_entries_setup_id_fkey
  foreign key (setup_id) references public.opening_balance_setups(id)
  on delete restrict;

-- Restore the predecessor value vocabulary together with its table shape. The
-- next expand deterministically normalizes these values back to capability
-- vocabulary, so rollback and recutover remain lossless.
update ledger.entries
set entry_kind = case entry_kind
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
end;

alter table ledger.entries rename column entry_kind to entry_type;
alter table ledger.entries rename to ledger_entries;
alter table ledger.ledger_entries set schema public;
alter table ledger.period_locks set schema public;

-- Target-only metadata stays on the one physical relation so a later recutover
-- can reconcile rollback-era rows without fabricating history.
create or replace function public.ledger_legacy_enforce_v1()
returns trigger
language plpgsql
security definer
set search_path = ''
as $function$
declare
  v_company_year_closed boolean := false;
  v_legacy_actor_id text := nullif(
    pg_catalog.current_setting('request.jwt.claim.sub', true), ''
  );
begin
  if tg_op = 'INSERT'
    and pg_catalog.lower(pg_catalog.btrim(new.entry_type)) = 'correction_reversal'
  then
    raise exception 'ledger_invalid_input';
  end if;
  if tg_op = 'UPDATE'
    and pg_catalog.lower(pg_catalog.btrim(new.entry_type)) = 'correction_reversal'
    and pg_catalog.lower(pg_catalog.btrim(old.entry_type)) <> 'correction_reversal'
  then
    raise exception 'ledger_invalid_input';
  end if;
  if pg_catalog.to_regclass('ledger.company_year_close_locks') is not null then
    -- The restored predecessor authorizes with Supabase auth.uid(), while the
    -- preserved target evidence uses the verified-actor RLS helper. Bridge the
    -- already-authenticated legacy subject transaction-locally for this guard.
    if nullif(
      pg_catalog.current_setting('talli.verified_actor_id', true), ''
    ) is null and v_legacy_actor_id is not null then
      perform pg_catalog.set_config(
        'talli.verified_actor_id', v_legacy_actor_id, true
      );
    end if;
    execute
      'select exists (
        select 1 from ledger.company_year_close_locks close_lock
        where close_lock.company_id = $1 and close_lock.income_year = $2
      )'
    into v_company_year_closed
    using new.company_id, new.income_year;
  end if;
  if v_company_year_closed then
    raise exception 'ledger_period_locked';
  end if;
  if not ledger.entry_lines_are_valid_v1(new.lines, true) then
    raise exception 'ledger_invalid_input';
  end if;
  new.source_capability := coalesce(
    new.source_capability,
    case pg_catalog.lower(pg_catalog.btrim(new.entry_type))
      when 'opening_balance' then case
        when new.setup_id is not null then 'SHAREHOLDER_REGISTER_FILING'
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
      else 'LEDGER'
    end
  );
  new.source_record_id := coalesce(
    nullif(pg_catalog.btrim(new.source_record_id), ''),
    case when new.setup_id is not null
      then 'opening-setup:' || new.setup_id::text
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
alter function public.ledger_legacy_enforce_v1() owner to ledger_store_owner;
revoke all on function public.ledger_legacy_enforce_v1()
  from public, anon, authenticated, service_role, ledger_executor,
    talli_ledger_backend;
create trigger ledger_entries_enforce_boundary
before insert or update of entry_type, lines, source_capability, source_record_id
on public.ledger_entries
for each row execute function public.ledger_legacy_enforce_v1();

grant select, insert on public.ledger_entries to authenticated;
grant select, insert on public.period_locks to authenticated;
grant select, insert on public.opening_balance_setups to authenticated;
grant select, insert on public.opening_shareholders to authenticated;

drop policy if exists "company members can read ledger entries"
  on public.ledger_entries;
create policy "company members can read ledger entries"
on public.ledger_entries for select to authenticated
using (
  exists (
    select 1 from public.company_memberships membership
    where membership.company_id = ledger_entries.company_id
      and membership.user_id = (select auth.uid())
      and membership.accepted_at is not null
  )
);
drop policy if exists "owners can create ledger entries"
  on public.ledger_entries;
create policy "owners can create ledger entries"
on public.ledger_entries for insert to authenticated
with check (
  created_by = (select auth.uid())
  and not exists (
    select 1 from public.period_locks period_lock
    where period_lock.company_id = ledger_entries.company_id
      and period_lock.income_year = ledger_entries.income_year
  )
  and exists (
    select 1 from public.company_memberships membership
    where membership.company_id = ledger_entries.company_id
      and membership.user_id = (select auth.uid())
      and membership.role = 'owner'
      and membership.accepted_at is not null
  )
);

drop policy if exists "company members can read period locks"
  on public.period_locks;
create policy "company members can read period locks"
on public.period_locks for select to authenticated
using (
  exists (
    select 1 from public.company_memberships membership
    where membership.company_id = period_locks.company_id
      and membership.user_id = (select auth.uid())
      and membership.accepted_at is not null
  )
);
drop policy if exists "owners can create period locks"
  on public.period_locks;
create policy "owners can create period locks"
on public.period_locks for insert to authenticated
with check (
  locked_by = (select auth.uid())
  and exists (
    select 1 from public.company_memberships membership
    where membership.company_id = period_locks.company_id
      and membership.user_id = (select auth.uid())
      and membership.role = 'owner'
      and membership.accepted_at is not null
  )
);

drop policy if exists "owners can create opening balance setups"
  on public.opening_balance_setups;
create policy "owners can create opening balance setups"
on public.opening_balance_setups for insert to authenticated
with check (
  created_by = (select auth.uid())
  and not exists (
    select 1 from public.period_locks period_lock
    where period_lock.company_id = opening_balance_setups.company_id
      and period_lock.income_year = opening_balance_setups.income_year
  )
  and exists (
    select 1 from public.company_memberships membership
    where membership.company_id = opening_balance_setups.company_id
      and membership.user_id = (select auth.uid())
      and membership.role = 'owner'
      and membership.accepted_at is not null
  )
);
drop policy if exists "owners can create opening shareholders"
  on public.opening_shareholders;
create policy "owners can create opening shareholders"
on public.opening_shareholders for insert to authenticated
with check (
  created_by = (select auth.uid())
  and exists (
    select 1 from public.company_memberships membership
    where membership.company_id = opening_shareholders.company_id
      and membership.user_id = (select auth.uid())
      and membership.role = 'owner'
      and membership.accepted_at is not null
  )
);

alter table public.bank_transactions
  add constraint bank_transactions_matched_entry_id_fkey
  foreign key (matched_entry_id) references public.ledger_entries(id)
  on delete set null;
alter table public.holding_actions
  add constraint holding_actions_ledger_entry_id_fkey
  foreign key (ledger_entry_id) references public.ledger_entries(id)
  on delete restrict;
alter table public.bank_suggestion_acceptances
  add constraint bank_suggestion_acceptances_ledger_entry_id_fkey
  foreign key (ledger_entry_id) references public.ledger_entries(id)
  on delete restrict;
alter table public.corporate_decision_finalizations
  add constraint corporate_decision_finalizations_ledger_entry_id_fkey
  foreign key (ledger_entry_id) references public.ledger_entries(id)
  on delete restrict;

do $restore_archive_trigger$
begin
  if pg_catalog.to_regprocedure(
    'public.company_archive_track_source_write_v1()'
  ) is null then
    raise exception 'ledger_archive_freshness_function_missing';
  end if;
  drop trigger if exists company_archive_track_ledger_entries
    on public.ledger_entries;
  create trigger company_archive_track_ledger_entries
  before insert or update or delete on public.ledger_entries
  for each row execute function public.company_archive_track_source_write_v1(
    'year', 'company_id'
  );
end
$restore_archive_trigger$;

grant execute on function public.accept_bank_transaction_suggestion(
  uuid, text, text
) to authenticated, service_role;
grant execute on function public.record_share_purchase_fifo(
  uuid, uuid, integer, text, text, text, text, date, bigint, numeric,
  text, uuid, uuid, text
) to authenticated, service_role;
grant execute on function public.record_share_sale_fifo(
  uuid, uuid, integer, uuid, date, bigint, numeric, uuid, uuid, text
) to authenticated, service_role;
grant execute on function public.finalize_corporate_decision(jsonb)
  to authenticated, service_role;
grant execute on function public.record_owner_dividend_payment(jsonb)
  to authenticated, service_role;

commit;
