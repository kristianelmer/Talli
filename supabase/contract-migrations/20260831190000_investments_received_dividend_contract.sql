-- CONTRACT RELEASE ARTIFACT: investments received dividends, issue #143.
-- Apply only after the overlap backend and generated-client web are deployed.

begin;

select pg_catalog.pg_advisory_xact_lock(
  pg_catalog.hashtextextended('talli:investments:dividend-cutover:v1', 0)
);
lock table public.holding_actions in share row exclusive mode;
lock table investments.positions in share row exclusive mode;
lock table investments.received_dividends in share row exclusive mode;

do $investments_dividend_contract_disable_predecessor$
begin
  if pg_catalog.to_regprocedure(
    'backend_system.prepare_investment_dividend_v1(jsonb,text)'
  ) is not null then
    revoke execute on function backend_system.prepare_investment_dividend_v1(
      jsonb, text
    ) from public, anon, authenticated, service_role, ledger_executor,
      ledger_store_owner, ledger_workflow_executor, talli_ledger_backend;
  end if;
  if pg_catalog.to_regprocedure(
    'backend_system.complete_investment_dividend_v1(jsonb,uuid,jsonb,text)'
  ) is not null then
    revoke execute on function backend_system.complete_investment_dividend_v1(
      jsonb, uuid, jsonb, text
    ) from public, anon, authenticated, service_role, ledger_executor,
      ledger_store_owner, ledger_workflow_executor, talli_ledger_backend;
  end if;
end
$investments_dividend_contract_disable_predecessor$;

do $investments_dividend_contract_reconciliation$
begin
  if exists (
    select 1 from investments.received_dividends dividend
    where not dividend.legacy_imported
      and (dividend.accounting_entry_id is null or dividend.completed_at is null)
  ) then raise exception 'investments_dividend_contract_in_progress'; end if;

  if exists (
    select 1
    from investments.received_dividends canonical
    full join (
      select action.* from public.holding_actions action
      where action.action_type = 'dividend_received'
    ) legacy on legacy.id = canonical.action_id
    left join investments.positions bound_position
      on bound_position.id = canonical.position_id
    where canonical.action_id is null or legacy.id is null
      or canonical.company_id is distinct from legacy.company_id
      or canonical.income_year is distinct from legacy.income_year
      or (
        canonical.position_id::text is distinct from
          (legacy.payload ->> 'linked_investment_id')
        and bound_position.investment_key is distinct from
          (legacy.payload ->> 'linked_investment_id')
      )
      or canonical.accounting_entry_id is distinct from legacy.ledger_entry_id
      or canonical.paying_company_name is distinct from
        pg_catalog.btrim(legacy.payload ->> 'paying_company_name')
      or canonical.declared_date is distinct from
        (legacy.payload ->> 'declared_date')::date
      or canonical.paid_date is distinct from coalesce(
        (legacy.payload ->> 'paid_date')::date, legacy.action_date
      )
      or canonical.gross_amount is distinct from
        (legacy.payload ->> 'gross_amount')::numeric
      or canonical.tax_treatment is distinct from coalesce(
        legacy.payload ->> 'tax_treatment', 'fritaksmetoden'
      )
      or canonical.taxable_add_back is distinct from coalesce(
        (legacy.payload ->> 'taxable_add_back')::numeric,
        pg_catalog.round((legacy.payload ->> 'gross_amount')::numeric * 0.03, 2)
      )
      or canonical.bank_transaction_id is distinct from legacy.bank_transaction_id
      or canonical.document_id is distinct from legacy.document_id
      or canonical.document_status is distinct from coalesce(
        legacy.payload ->> 'document_status', 'not_required'
      )
  ) then raise exception 'investments_dividend_contract_reconciliation_failed'; end if;

  if exists (
    select 1
    from investments.received_dividends dividend
    left join investments.positions position on position.id = dividend.position_id
    where position.id is null or position.company_id <> dividend.company_id
      or position.tax_treatment <> 'fritaksmetoden'
  ) then raise exception 'investments_dividend_contract_position_binding_failed'; end if;

  if exists (
    select 1
    from investments.received_dividends dividend
    left join ledger.entries entry on entry.id = dividend.accounting_entry_id
    where dividend.accounting_entry_id is not null
      and (entry.id is null
        or entry.company_id <> dividend.company_id
        or entry.entry_kind <> 'DIVIDEND_RECEIVED'
        or entry.source_capability <> 'INVESTMENTS'
        or entry.source_record_id <> dividend.action_id::text)
  ) then raise exception 'investments_dividend_contract_ledger_binding_failed'; end if;
end
$investments_dividend_contract_reconciliation$;

do $investments_dividend_contract_capsule_predecessor$
begin
  if pg_catalog.to_regprocedure(
    'backend_system.rollback_143_prepare_investment_dividend_v1(jsonb,text)'
  ) is not null and pg_catalog.to_regprocedure(
    'backend_system.prepare_investment_dividend_v1(jsonb,text)'
  ) is not null then
    raise exception 'investments_dividend_contract_duplicate_prepare_capsule';
  end if;
  if pg_catalog.to_regprocedure(
    'backend_system.prepare_investment_dividend_v1(jsonb,text)'
  ) is not null then
    alter function backend_system.prepare_investment_dividend_v1(jsonb, text)
      rename to rollback_143_prepare_investment_dividend_v1;
  end if;
  if pg_catalog.to_regprocedure(
    'backend_system.rollback_143_complete_investment_dividend_v1(jsonb,uuid,jsonb,text)'
  ) is not null and pg_catalog.to_regprocedure(
    'backend_system.complete_investment_dividend_v1(jsonb,uuid,jsonb,text)'
  ) is not null then
    raise exception 'investments_dividend_contract_duplicate_complete_capsule';
  end if;
  if pg_catalog.to_regprocedure(
    'backend_system.complete_investment_dividend_v1(jsonb,uuid,jsonb,text)'
  ) is not null then
    alter function backend_system.complete_investment_dividend_v1(
      jsonb, uuid, jsonb, text
    ) rename to rollback_143_complete_investment_dividend_v1;
  end if;
end
$investments_dividend_contract_capsule_predecessor$;

drop trigger if exists received_dividends_sync_to_investments
  on public.holding_actions;

grant execute on function ledger.post_entry(
  text, uuid, integer, text, text, jsonb, jsonb, boolean,
  text, text, text, text
) to investments_workflow_executor;
grant execute on function investments.get_received_dividend_replay_v1(jsonb, text)
  to investments_workflow_executor;
grant execute on function investments.prepare_received_dividend_v1(jsonb, text)
  to investments_workflow_executor;
grant execute on function investments.complete_received_dividend_v1(jsonb, uuid, text)
  to investments_workflow_executor;

commit;
