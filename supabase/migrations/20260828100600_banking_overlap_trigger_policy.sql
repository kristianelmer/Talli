-- EXPAND/MIGRATE FOLLOW-UP: preserve the frozen legacy transaction writer
-- during the bounded mixed-version window without weakening canonical commands.
--
-- The legacy public table already authorizes the outer row operation. Its
-- after-row mirror then enters banking.transactions at trigger depth one. The
-- canonical import function runs at trigger depth zero and therefore remains
-- subject to the consequential company-year admission policy.

begin;

do $banking_overlap_migration_authority$
begin
  execute pg_catalog.format(
    'grant banking_store_owner to %I', current_user
  );
  execute pg_catalog.format(
    'grant ledger_store_owner to %I', current_user
  );
end
$banking_overlap_migration_authority$;
select pg_catalog.set_config(
  'talli.banking_overlap_migration_principal', current_user, true
);

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
grant select, insert, update, delete on public.bank_transactions
  to banking_store_owner;

-- Canonical acceptance is the authoritative write during the observation
-- window. Keep the frozen archive relation byte-equivalent until contract by
-- projecting only the accepted fact and its already-posted ledger lines.
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
grant select, insert, update, delete on public.bank_suggestion_acceptances
  to ledger_store_owner;

set local role ledger_store_owner;
grant usage, create on schema backend_system to ledger_store_owner;
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
revoke all on function
  backend_system.sync_banking_acceptance_to_legacy_v1()
from public, anon, authenticated, service_role;
grant execute on function
  backend_system.sync_banking_acceptance_to_legacy_v1()
to banking_store_owner;
revoke create on schema backend_system from ledger_store_owner;
reset role;

set local role banking_store_owner;
drop trigger if exists banking_acceptances_sync_to_legacy
  on banking.suggestion_acceptances;
create trigger banking_acceptances_sync_to_legacy
after insert or update or delete on banking.suggestion_acceptances
for each row execute function
  backend_system.sync_banking_acceptance_to_legacy_v1();
reset role;

drop policy if exists "banking workflow appends audit events"
  on public.audit_events;
create policy "banking workflow appends audit events"
on public.audit_events for insert to banking_store_owner
with check (
  actor_id = public.company_access_auth_uid_v1()
  and public.company_access_is_accepted_owner_v1(company_id)
);
grant insert on public.audit_events to banking_store_owner;

set local role ledger_store_owner;
grant usage on schema ledger to banking_store_owner;
reset role;

do $banking_overlap_revoke_migration_authority$
begin
  execute pg_catalog.format(
    'revoke banking_store_owner from %I', current_user
  );
  execute pg_catalog.format(
    'revoke ledger_store_owner from %I', current_user
  );
end
$banking_overlap_revoke_migration_authority$;

commit;
