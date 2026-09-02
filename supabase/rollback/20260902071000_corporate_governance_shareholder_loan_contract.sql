-- Restore the bounded predecessor shareholder-loan writer for rollback.
begin;

set local lock_timeout = '5s';
set local statement_timeout = '120s';

do $authority$
begin
  execute pg_catalog.format(
    'grant corporate_governance_store_owner, ledger_store_owner to %I',
    current_user
  );
end
$authority$;

select pg_catalog.set_config(
  'talli.corporate_governance_contract_migration_principal',
  current_user,
  true
);
set local role ledger_store_owner;
grant usage, create on schema backend_system to ledger_store_owner;
do $schema_authority$
begin
  execute pg_catalog.format(
    'grant usage, create on schema backend_system to %I',
    pg_catalog.current_setting(
      'talli.corporate_governance_contract_migration_principal'
    )
  );
end
$schema_authority$;
reset role;

select pg_catalog.pg_advisory_xact_lock(
  pg_catalog.hashtextextended(
    'talli:corporate-governance:shareholder-loan-cutover:v1', 0
  )
);
lock table public.holding_actions in share row exclusive mode;
set local role corporate_governance_store_owner;
lock table corporate_governance.shareholder_loans in share row exclusive mode;
reset role;

do $reconciliation$
begin
  if exists (
    select 1
    from corporate_governance.shareholder_loans target
    left join public.holding_actions source on source.id = target.action_id
      and source.action_type = 'shareholder_loan'
      and source.company_id = target.company_id
      and source.income_year = target.income_year
      and source.ledger_entry_id = target.accounting_entry_id
      and source.action_date = target.loan_date
      and source.payload ->> 'direction' = target.direction
      and pg_catalog.round(
        (source.payload ->> 'amount')::numeric * 100
      )::bigint = target.amount_ore
    where source.id is null
  ) then
    raise exception 'corporate_governance_shareholder_loan_rollback_reconciliation_failed';
  end if;
end
$reconciliation$;

do $restore_predecessor$
begin
  if pg_catalog.to_regprocedure(
    'backend_system.prepare_shareholder_loan_v1(jsonb,text)'
  ) is null then
    if pg_catalog.to_regprocedure(
      'backend_system.rollback_145_prepare_shareholder_loan_v1(jsonb,text)'
    ) is null then
      raise exception 'corporate_governance_shareholder_loan_prepare_capsule_missing';
    end if;
    alter function backend_system.rollback_145_prepare_shareholder_loan_v1(
      jsonb, text
    ) rename to prepare_shareholder_loan_v1;
  end if;
  if pg_catalog.to_regprocedure(
    'backend_system.complete_shareholder_loan_v1(jsonb,uuid,jsonb,text)'
  ) is null then
    if pg_catalog.to_regprocedure(
      'backend_system.rollback_145_complete_shareholder_loan_v1(jsonb,uuid,jsonb,text)'
    ) is null then
      raise exception 'corporate_governance_shareholder_loan_complete_capsule_missing';
    end if;
    alter function backend_system.rollback_145_complete_shareholder_loan_v1(
      jsonb, uuid, jsonb, text
    ) rename to complete_shareholder_loan_v1;
  end if;
end
$restore_predecessor$;

grant execute on function backend_system.prepare_shareholder_loan_v1(
  jsonb, text
) to ledger_workflow_executor;
grant execute on function backend_system.complete_shareholder_loan_v1(
  jsonb, uuid, jsonb, text
) to ledger_workflow_executor;

do $schema_authority_revoke$
begin
  execute pg_catalog.format(
    'revoke create on schema backend_system from %I',
    pg_catalog.current_setting(
      'talli.corporate_governance_contract_migration_principal'
    )
  );
end
$schema_authority_revoke$;
set local role ledger_store_owner;
revoke create on schema backend_system from ledger_store_owner;
reset role;

do $authority_revoke$
begin
  execute pg_catalog.format(
    'revoke corporate_governance_store_owner, ledger_store_owner from %I',
    current_user
  );
end
$authority_revoke$;

commit;
