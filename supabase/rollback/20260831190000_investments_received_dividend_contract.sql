-- BOUNDED ROLLBACK ARTIFACT: investments received dividends, issue #143.
-- Restores only the backend predecessor. Reapply the contract to recutover.

begin;

do $investments_dividend_rollback_authority$
begin
  execute pg_catalog.format(
    'grant investments_store_owner, ledger_store_owner to %I', current_user
  );
end
$investments_dividend_rollback_authority$;

select pg_catalog.set_config(
  'talli.investments_contract_migration_principal', current_user, true
);
set local role ledger_store_owner;
grant usage, create on schema backend_system to ledger_store_owner;
do $investments_dividend_rollback_schema_authority$
begin
  execute pg_catalog.format(
    'grant usage, create on schema backend_system to %I',
    pg_catalog.current_setting(
      'talli.investments_contract_migration_principal'
    )
  );
end
$investments_dividend_rollback_schema_authority$;
reset role;

select pg_catalog.pg_advisory_xact_lock(
  pg_catalog.hashtextextended('talli:investments:dividend-cutover:v1', 0)
);
lock table public.holding_actions in share row exclusive mode;
lock table investments.positions in share row exclusive mode;
lock table investments.received_dividends in share row exclusive mode;

do $investments_dividend_rollback_reconciliation$
begin
  if exists (
    select 1 from investments.received_dividends canonical
    left join public.holding_actions legacy
      on legacy.id = canonical.action_id
      and legacy.action_type = 'dividend_received'
    left join investments.positions bound_position
      on bound_position.id = canonical.position_id
    where legacy.id is null
      or legacy.ledger_entry_id is distinct from canonical.accounting_entry_id
      or (
        (legacy.payload ->> 'linked_investment_id') is distinct from
          canonical.position_id::text
        and (legacy.payload ->> 'linked_investment_id') is distinct from
          bound_position.investment_key
      )
      or (legacy.payload ->> 'gross_amount')::numeric is distinct from
        canonical.gross_amount
      or (legacy.payload ->> 'taxable_add_back')::numeric is distinct from
        canonical.taxable_add_back
  ) then raise exception 'investments_dividend_rollback_reconciliation_failed'; end if;
end
$investments_dividend_rollback_reconciliation$;

revoke execute on function investments.get_received_dividend_replay_v1(jsonb, text)
  from investments_workflow_executor;
revoke execute on function investments.prepare_received_dividend_v1(jsonb, text)
  from investments_workflow_executor;
revoke execute on function investments.complete_received_dividend_v1(jsonb, uuid, text)
  from investments_workflow_executor;

do $investments_dividend_rollback_restore_predecessor$
begin
  if pg_catalog.to_regprocedure(
    'backend_system.prepare_investment_dividend_v1(jsonb,text)'
  ) is null then
    if pg_catalog.to_regprocedure(
      'backend_system.rollback_143_prepare_investment_dividend_v1(jsonb,text)'
    ) is null then
      raise exception 'investments_dividend_rollback_prepare_capsule_missing';
    end if;
    alter function backend_system.rollback_143_prepare_investment_dividend_v1(
      jsonb, text
    ) rename to prepare_investment_dividend_v1;
  end if;
  if pg_catalog.to_regprocedure(
    'backend_system.complete_investment_dividend_v1(jsonb,uuid,jsonb,text)'
  ) is null then
    if pg_catalog.to_regprocedure(
      'backend_system.rollback_143_complete_investment_dividend_v1(jsonb,uuid,jsonb,text)'
    ) is null then
      raise exception 'investments_dividend_rollback_complete_capsule_missing';
    end if;
    alter function backend_system.rollback_143_complete_investment_dividend_v1(
      jsonb, uuid, jsonb, text
    ) rename to complete_investment_dividend_v1;
  end if;
end
$investments_dividend_rollback_restore_predecessor$;

drop trigger if exists received_dividends_sync_to_investments
  on public.holding_actions;
create trigger received_dividends_sync_to_investments
after insert on public.holding_actions for each row
execute function backend_system.sync_legacy_received_dividend_v1();

grant execute on function backend_system.prepare_investment_dividend_v1(
  jsonb, text
) to ledger_workflow_executor;
grant execute on function backend_system.complete_investment_dividend_v1(
  jsonb, uuid, jsonb, text
) to ledger_workflow_executor;

do $investments_dividend_rollback_schema_authority_revoke$
begin
  execute pg_catalog.format(
    'revoke create on schema backend_system from %I',
    pg_catalog.current_setting(
      'talli.investments_contract_migration_principal'
    )
  );
end
$investments_dividend_rollback_schema_authority_revoke$;
set local role ledger_store_owner;
revoke create on schema backend_system from ledger_store_owner;
reset role;

do $investments_dividend_rollback_authority_revoke$
begin
  execute pg_catalog.format(
    'revoke investments_store_owner, ledger_store_owner from %I', current_user
  );
end
$investments_dividend_rollback_authority_revoke$;

commit;
