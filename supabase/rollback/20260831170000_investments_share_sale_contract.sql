-- BOUNDED ROLLBACK ARTIFACT: investments share sales, issue #142.
-- Restores only the backend predecessor. The browser RPC remains removed.
-- Reapply the paired contract artifact to recutover.

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

do $investments_sale_rollback_reconciliation$
begin
  if exists (
    select 1 from investments.positions canonical
    left join public.investment_positions legacy on legacy.id = canonical.id
    where legacy.id is null
      or legacy.share_count::bigint is distinct from canonical.share_count
      or legacy.cost_basis is distinct from canonical.cost_basis
      or legacy.movements is distinct from canonical.movements
  ) then raise exception 'investments_sale_rollback_position_reconciliation_failed'; end if;

  if exists (
    select 1 from investments.acquisition_lots canonical
    left join public.investment_lots legacy on legacy.id = canonical.id
    where legacy.id is null
      or legacy.remaining_share_count is distinct from canonical.remaining_share_count
      or legacy.remaining_cost_basis is distinct from canonical.remaining_cost_basis
  ) then raise exception 'investments_sale_rollback_lot_reconciliation_failed'; end if;

  if exists (
    select 1 from investments.share_sales canonical
    left join public.holding_actions legacy
      on legacy.id = canonical.action_id and legacy.action_type = 'share_sale'
    where legacy.id is null
      or legacy.ledger_entry_id is distinct from canonical.accounting_entry_id
      or (legacy.payload ->> 'position_id')::uuid is distinct from canonical.position_id
      or (legacy.payload ->> 'sold_share_count')::bigint is distinct from
        canonical.sold_share_count
      or (legacy.payload ->> 'cost_basis_reduction')::numeric is distinct from
        canonical.fifo_cost_basis_reduction
  ) then raise exception 'investments_sale_rollback_sale_reconciliation_failed'; end if;

  if exists (
    select 1 from investments.share_sale_allocations canonical
    left join public.investment_lot_allocations legacy
      on legacy.sale_action_id = canonical.sale_action_id
      and legacy.lot_id = canonical.acquisition_lot_id
    where legacy.sale_action_id is null
      or legacy.allocated_share_count is distinct from canonical.allocated_share_count
      or legacy.allocated_cost_basis is distinct from canonical.allocated_cost_basis
  ) then raise exception 'investments_sale_rollback_allocation_reconciliation_failed'; end if;
end
$investments_sale_rollback_reconciliation$;

revoke execute on function investments.get_share_sale_replay_v1(jsonb, text)
  from investments_workflow_executor;
revoke execute on function investments.prepare_share_sale_v1(jsonb, text)
  from investments_workflow_executor;
revoke execute on function investments.complete_share_sale_v1(jsonb, uuid, text)
  from investments_workflow_executor;

do $investments_sale_rollback_restore_predecessor$
begin
  if pg_catalog.to_regprocedure(
    'backend_system.prepare_investment_sale_fifo_v1(jsonb,text)'
  ) is null then
    if pg_catalog.to_regprocedure(
      'backend_system.rollback_142_prepare_investment_sale_fifo_v1(jsonb,text)'
    ) is null then raise exception 'investments_sale_rollback_prepare_capsule_missing'; end if;
    alter function backend_system.rollback_142_prepare_investment_sale_fifo_v1(
      jsonb, text
    ) rename to prepare_investment_sale_fifo_v1;
  end if;
  if pg_catalog.to_regprocedure(
    'backend_system.complete_investment_sale_fifo_v1(jsonb,uuid,jsonb,text)'
  ) is null then
    if pg_catalog.to_regprocedure(
      'backend_system.rollback_142_complete_investment_sale_fifo_v1(jsonb,uuid,jsonb,text)'
    ) is null then raise exception 'investments_sale_rollback_complete_capsule_missing'; end if;
    alter function backend_system.rollback_142_complete_investment_sale_fifo_v1(
      jsonb, uuid, jsonb, text
    ) rename to complete_investment_sale_fifo_v1;
  end if;
end
$investments_sale_rollback_restore_predecessor$;

do $investments_sale_rollback_repair_predecessor$
declare
  v_definition text;
begin
  select pg_catalog.pg_get_functiondef(
    'backend_system.prepare_investment_sale_fifo_v1(jsonb,text)'::regprocedure
  ) into v_definition;
  if pg_catalog.strpos(
    v_definition,
    'pg_catalog.least(v_left, v_lot.remaining_share_count)'
  ) > 0 then
    execute pg_catalog.replace(
      v_definition,
      'pg_catalog.least(v_left, v_lot.remaining_share_count)',
      'case when v_left < v_lot.remaining_share_count then v_left '
        || 'else v_lot.remaining_share_count end'
    );
  end if;
end
$investments_sale_rollback_repair_predecessor$;

drop trigger if exists share_sales_sync_to_investments on public.holding_actions;
create trigger share_sales_sync_to_investments
after insert on public.holding_actions for each row
execute function backend_system.sync_legacy_share_sale_v1();
drop trigger if exists share_sale_allocations_sync_to_investments
  on public.investment_lot_allocations;
create trigger share_sale_allocations_sync_to_investments
after insert on public.investment_lot_allocations for each row
execute function backend_system.sync_legacy_share_sale_allocation_v1();

grant execute on function backend_system.prepare_investment_sale_fifo_v1(
  jsonb, text
) to ledger_workflow_executor;
grant execute on function backend_system.complete_investment_sale_fifo_v1(
  jsonb, uuid, jsonb, text
) to ledger_workflow_executor;

commit;
