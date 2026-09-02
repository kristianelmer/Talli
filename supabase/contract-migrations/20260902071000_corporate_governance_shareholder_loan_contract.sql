-- CONTRACT RELEASE ARTIFACT: canonical shareholder loans, issue #145.
-- Apply only after the governance API and generated-client web are deployed.
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

do $disable_predecessor$
begin
  if pg_catalog.to_regprocedure(
    'backend_system.prepare_shareholder_loan_v1(jsonb,text)'
  ) is not null then
    revoke execute on function backend_system.prepare_shareholder_loan_v1(
      jsonb, text
    ) from public, anon, authenticated, service_role, ledger_executor,
      ledger_store_owner, ledger_workflow_executor, talli_ledger_backend;
  end if;
  if pg_catalog.to_regprocedure(
    'backend_system.complete_shareholder_loan_v1(jsonb,uuid,jsonb,text)'
  ) is not null then
    revoke execute on function backend_system.complete_shareholder_loan_v1(
      jsonb, uuid, jsonb, text
    ) from public, anon, authenticated, service_role, ledger_executor,
      ledger_store_owner, ledger_workflow_executor, talli_ledger_backend;
  end if;
end
$disable_predecessor$;

do $reconciliation$
begin
  if exists (
    select 1
    from public.holding_actions source
    full join corporate_governance.shareholder_loans target
      on target.action_id = source.id
      and source.action_type = 'shareholder_loan'
    where (source.action_type = 'shareholder_loan' or source.id is null)
      and (
        source.id is null or target.action_id is null
        or source.company_id <> target.company_id
        or source.income_year <> target.income_year
        or source.action_date <> target.loan_date
        or source.ledger_entry_id <> target.accounting_entry_id
        or source.bank_transaction_id is distinct from target.bank_transaction_id
        or source.document_id is distinct from target.document_id
        or source.payload ->> 'direction' <> target.direction
        or pg_catalog.btrim(source.payload ->> 'counterparty_name')
          <> target.counterparty_name
        or source.payload ->> 'document_status' <> target.document_status
        or coalesce(
          (source.payload ->> 'interest_modelled')::boolean, false
        ) <> target.interest_modelled
        or coalesce(
          (source.payload ->> 'related_party_security')::boolean, false
        ) <> target.related_party_security
        or pg_catalog.round(
          (source.payload ->> 'amount')::numeric * 100
        )::bigint <> target.amount_ore
      )
  ) then
    raise exception 'corporate_governance_shareholder_loan_contract_reconciliation_failed';
  end if;
  if exists (
    select 1 from corporate_governance.shareholder_loans loan
    left join ledger.entries entry on entry.id = loan.accounting_entry_id
    where entry.id is null
      or entry.company_id <> loan.company_id
      or entry.income_year <> loan.income_year
      or entry.entry_kind <> 'SHAREHOLDER_LOAN'
      or entry.source_record_id <> loan.action_id::text
  ) then
    raise exception 'corporate_governance_shareholder_loan_ledger_binding_failed';
  end if;
end
$reconciliation$;

do $capsule_predecessor$
begin
  if pg_catalog.to_regprocedure(
    'backend_system.rollback_145_prepare_shareholder_loan_v1(jsonb,text)'
  ) is not null and pg_catalog.to_regprocedure(
    'backend_system.prepare_shareholder_loan_v1(jsonb,text)'
  ) is not null then
    raise exception 'corporate_governance_shareholder_loan_duplicate_prepare_capsule';
  end if;
  if pg_catalog.to_regprocedure(
    'backend_system.prepare_shareholder_loan_v1(jsonb,text)'
  ) is not null then
    alter function backend_system.prepare_shareholder_loan_v1(jsonb, text)
      rename to rollback_145_prepare_shareholder_loan_v1;
  end if;
  if pg_catalog.to_regprocedure(
    'backend_system.rollback_145_complete_shareholder_loan_v1(jsonb,uuid,jsonb,text)'
  ) is not null and pg_catalog.to_regprocedure(
    'backend_system.complete_shareholder_loan_v1(jsonb,uuid,jsonb,text)'
  ) is not null then
    raise exception 'corporate_governance_shareholder_loan_duplicate_complete_capsule';
  end if;
  if pg_catalog.to_regprocedure(
    'backend_system.complete_shareholder_loan_v1(jsonb,uuid,jsonb,text)'
  ) is not null then
    alter function backend_system.complete_shareholder_loan_v1(
      jsonb, uuid, jsonb, text
    ) rename to rollback_145_complete_shareholder_loan_v1;
  end if;
end
$capsule_predecessor$;

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
