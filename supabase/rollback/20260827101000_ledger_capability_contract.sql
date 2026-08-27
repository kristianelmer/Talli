-- Phase-aware rollback for the #139 ledger contract release artifact.
-- The target writer is disabled first. One physical store is then returned to
-- the frozen legacy facade. Evidence/receipts remain immutable for recutover.

begin;

select pg_catalog.pg_advisory_xact_lock(
  pg_catalog.hashtextextended('talli:ledger:capability-cutover:v1', 0)
);

-- Exactly one writer: disable every target entry point before exposing legacy.
revoke all on function ledger.post_entry(
  text, uuid, integer, text, text, jsonb, jsonb, boolean,
  text, text, text, text
) from ledger_executor, talli_ledger_backend;
revoke all on function ledger.lock_period(
  text, uuid, integer, text, text, text
) from ledger_executor, talli_ledger_backend;
revoke all on function ledger.list_entries(uuid[], text, integer, text)
  from ledger_executor, talli_ledger_backend;
revoke all on function ledger.list_period_locks(uuid[], text, integer, text)
  from ledger_executor, talli_ledger_backend;
revoke ledger_executor from talli_ledger_backend;

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
begin
  if not ledger.entry_lines_are_valid_v1(new.lines, true) then
    raise exception 'ledger_invalid_input';
  end if;
  new.source_capability := coalesce(
    new.source_capability,
    case pg_catalog.lower(pg_catalog.btrim(new.entry_type))
      when 'opening_balance' then 'SHAREHOLDER_REGISTER_FILING'
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
  ) is not null then
    create trigger company_archive_track_ledger_entries
    before insert or update or delete on public.ledger_entries
    for each row execute function public.company_archive_track_source_write_v1(
      'year', 'company_id'
    );
  end if;
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
