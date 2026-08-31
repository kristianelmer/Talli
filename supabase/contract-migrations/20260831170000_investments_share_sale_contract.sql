-- CONTRACT RELEASE ARTIFACT: investments share sales, issue #142.
-- Apply only after the overlap backend and generated-client web are deployed.

begin;

select pg_catalog.pg_advisory_xact_lock(
  pg_catalog.hashtextextended('talli:investments:sale-cutover:v1', 0)
);
lock table public.investment_positions in share row exclusive mode;
lock table public.investment_lots in share row exclusive mode;
lock table public.investment_lot_allocations in share row exclusive mode;
lock table public.holding_actions in share row exclusive mode;
lock table investments.positions in share row exclusive mode;
lock table investments.acquisition_lots in share row exclusive mode;
lock table investments.share_sales in share row exclusive mode;
lock table investments.share_sale_allocations in share row exclusive mode;

-- Disable predecessor entry points before the final comparison. Conditional
-- revocation makes the artifact safe to reapply after the bounded rollback.
do $investments_sale_contract_disable_predecessor$
begin
  if pg_catalog.to_regprocedure(
    'backend_system.prepare_investment_sale_fifo_v1(jsonb,text)'
  ) is not null then
    revoke execute on function backend_system.prepare_investment_sale_fifo_v1(
      jsonb, text
    ) from public, anon, authenticated, service_role, ledger_executor,
      ledger_store_owner, ledger_workflow_executor, talli_ledger_backend;
  end if;
  if pg_catalog.to_regprocedure(
    'backend_system.complete_investment_sale_fifo_v1(jsonb,uuid,jsonb,text)'
  ) is not null then
    revoke execute on function backend_system.complete_investment_sale_fifo_v1(
      jsonb, uuid, jsonb, text
    ) from public, anon, authenticated, service_role, ledger_executor,
      ledger_store_owner, ledger_workflow_executor, talli_ledger_backend;
  end if;
  if pg_catalog.to_regprocedure(
    'public.record_share_sale_fifo(uuid,uuid,integer,uuid,date,bigint,numeric,uuid,uuid,text)'
  ) is not null then
    revoke execute on function public.record_share_sale_fifo(
      uuid, uuid, integer, uuid, date, bigint, numeric, uuid, uuid, text
    ) from public, anon, authenticated, service_role;
  end if;
end
$investments_sale_contract_disable_predecessor$;

do $investments_sale_contract_reconciliation$
begin
  if exists (
    select 1
    from investments.positions canonical
    full join public.investment_positions legacy on legacy.id = canonical.id
    where canonical.id is null or legacy.id is null
      or canonical.company_id is distinct from legacy.company_id
      or canonical.investment_key is distinct from legacy.investment_key
      or canonical.name is distinct from legacy.name
      or canonical.kind is distinct from legacy.kind
      or canonical.tax_treatment is distinct from legacy.tax_treatment
      or canonical.org_number is distinct from legacy.org_number
      or canonical.share_count is distinct from legacy.share_count::bigint
      or canonical.cost_basis is distinct from legacy.cost_basis
      or canonical.movements is distinct from legacy.movements
      or canonical.lot_history_status is distinct from legacy.lot_history_status
  ) then raise exception 'investments_sale_contract_position_reconciliation_failed'; end if;

  if exists (
    select 1
    from investments.acquisition_lots canonical
    full join public.investment_lots legacy on legacy.id = canonical.id
    where canonical.id is null or legacy.id is null
      or canonical.company_id is distinct from legacy.company_id
      or canonical.position_id is distinct from legacy.position_id
      or canonical.acquisition_action_id is distinct from legacy.acquisition_action_id
      or canonical.acquisition_date is distinct from legacy.acquisition_date
      or canonical.original_share_count is distinct from legacy.original_share_count
      or canonical.remaining_share_count is distinct from legacy.remaining_share_count
      or canonical.original_cost_basis is distinct from legacy.original_cost_basis
      or canonical.remaining_cost_basis is distinct from legacy.remaining_cost_basis
  ) then raise exception 'investments_sale_contract_lot_reconciliation_failed'; end if;

  if exists (
    select 1 from investments.share_sales sale
    where not sale.legacy_imported
      and (sale.accounting_entry_id is null or sale.completed_at is null)
  ) then raise exception 'investments_sale_contract_sale_in_progress'; end if;

  if exists (
    select 1
    from investments.share_sales canonical
    full join (
      select action.* from public.holding_actions action
      where action.action_type = 'share_sale'
    ) legacy on legacy.id = canonical.action_id
    where canonical.action_id is null or legacy.id is null
      or canonical.company_id is distinct from legacy.company_id
      or canonical.income_year is distinct from legacy.income_year
      or canonical.position_id is distinct from (legacy.payload ->> 'position_id')::uuid
      or canonical.accounting_entry_id is distinct from legacy.ledger_entry_id
      or canonical.sale_date is distinct from coalesce(
        (legacy.payload ->> 'sale_date')::date, legacy.action_date
      )
      or canonical.sold_share_count is distinct from
        (legacy.payload ->> 'sold_share_count')::bigint
      or canonical.proceeds is distinct from (legacy.payload ->> 'proceeds')::numeric
      or canonical.fifo_cost_basis_reduction is distinct from
        (legacy.payload ->> 'cost_basis_reduction')::numeric
      or canonical.gain_or_loss is distinct from
        (legacy.payload ->> 'gain_or_loss')::numeric
      or canonical.remaining_share_count is distinct from
        (legacy.payload ->> 'remaining_share_count')::bigint
      or canonical.remaining_cost_basis is distinct from
        (legacy.payload ->> 'remaining_cost_basis')::numeric
      or canonical.bank_transaction_id is distinct from legacy.bank_transaction_id
      or canonical.document_id is distinct from legacy.document_id
      or canonical.document_status is distinct from coalesce(
        legacy.payload ->> 'document_status', 'not_required'
      )
  ) then raise exception 'investments_sale_contract_sale_reconciliation_failed'; end if;

  if exists (
    select 1
    from investments.share_sale_allocations canonical
    full join public.investment_lot_allocations legacy
      on legacy.sale_action_id = canonical.sale_action_id
      and legacy.lot_id = canonical.acquisition_lot_id
    where canonical.sale_action_id is null or legacy.sale_action_id is null
      or canonical.company_id is distinct from legacy.company_id
      or canonical.position_id is distinct from legacy.position_id
      or canonical.allocated_share_count is distinct from legacy.allocated_share_count
      or canonical.allocated_cost_basis is distinct from legacy.allocated_cost_basis
  ) then raise exception 'investments_sale_contract_allocation_reconciliation_failed'; end if;

  if exists (
    select 1
    from investments.share_sales sale
    left join ledger.entries entry on entry.id = sale.accounting_entry_id
    where sale.accounting_entry_id is not null
      and (entry.id is null
        or entry.company_id <> sale.company_id
        or entry.entry_kind <> 'SHARE_SALE'
        or entry.source_capability <> 'INVESTMENTS'
        or entry.source_record_id <> sale.action_id::text)
  ) then raise exception 'investments_sale_contract_ledger_binding_failed'; end if;
end
$investments_sale_contract_reconciliation$;

-- Retain the exact backend predecessor under ungranted rollback-only names.
do $investments_sale_contract_capsule_predecessor$
begin
  if pg_catalog.to_regprocedure(
    'backend_system.rollback_142_prepare_investment_sale_fifo_v1(jsonb,text)'
  ) is not null and pg_catalog.to_regprocedure(
    'backend_system.prepare_investment_sale_fifo_v1(jsonb,text)'
  ) is not null then
    raise exception 'investments_sale_contract_duplicate_prepare_capsule';
  end if;
  if pg_catalog.to_regprocedure(
    'backend_system.prepare_investment_sale_fifo_v1(jsonb,text)'
  ) is not null then
    alter function backend_system.prepare_investment_sale_fifo_v1(jsonb, text)
      rename to rollback_142_prepare_investment_sale_fifo_v1;
  end if;
  if pg_catalog.to_regprocedure(
    'backend_system.rollback_142_complete_investment_sale_fifo_v1(jsonb,uuid,jsonb,text)'
  ) is not null and pg_catalog.to_regprocedure(
    'backend_system.complete_investment_sale_fifo_v1(jsonb,uuid,jsonb,text)'
  ) is not null then
    raise exception 'investments_sale_contract_duplicate_complete_capsule';
  end if;
  if pg_catalog.to_regprocedure(
    'backend_system.complete_investment_sale_fifo_v1(jsonb,uuid,jsonb,text)'
  ) is not null then
    alter function backend_system.complete_investment_sale_fifo_v1(
      jsonb, uuid, jsonb, text
    ) rename to rollback_142_complete_investment_sale_fifo_v1;
  end if;
end
$investments_sale_contract_capsule_predecessor$;

drop trigger if exists share_sales_sync_to_investments on public.holding_actions;
drop trigger if exists share_sale_allocations_sync_to_investments
  on public.investment_lot_allocations;
drop function if exists public.record_share_sale_fifo(
  uuid, uuid, integer, uuid, date, bigint, numeric, uuid, uuid, text
);

grant execute on function ledger.post_entry(
  text, uuid, integer, text, text, jsonb, jsonb, boolean,
  text, text, text, text
) to investments_workflow_executor;
grant execute on function investments.get_share_sale_replay_v1(jsonb, text)
  to investments_workflow_executor;
grant execute on function investments.prepare_share_sale_v1(jsonb, text)
  to investments_workflow_executor;
grant execute on function investments.complete_share_sale_v1(jsonb, uuid, text)
  to investments_workflow_executor;

commit;
