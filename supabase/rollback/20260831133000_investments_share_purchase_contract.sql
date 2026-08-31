-- BOUNDED ROLLBACK ARTIFACT: investments share purchases, issue #141.
-- Restores only the backend predecessor coordinator. The removed browser RPC
-- remains removed. Reapply the paired contract artifact to recutover.

begin;

select pg_catalog.pg_advisory_xact_lock(
  pg_catalog.hashtextextended('talli:investments:purchase-cutover:v1', 0)
);
lock table public.investment_positions in share row exclusive mode;
lock table public.investment_lots in share row exclusive mode;
lock table public.holding_actions in share row exclusive mode;
lock table investments.positions in share row exclusive mode;
lock table investments.acquisition_lots in share row exclusive mode;
lock table investments.share_purchases in share row exclusive mode;

-- The overlap bridge must make every canonical row visible to the predecessor
-- before the successor writer is disabled.
do $investments_rollback_reconciliation$
begin
  if exists (
    select 1 from investments.positions target
    left join public.investment_positions source on source.id = target.id
    where source.id is null
      or source.company_id <> target.company_id
      or source.investment_key <> target.investment_key
      or source.share_count::bigint <> target.share_count
      or source.cost_basis <> target.cost_basis
      or source.movements <> target.movements
  ) then
    raise exception 'investments_rollback_position_reconciliation_failed';
  end if;
  if exists (
    select 1 from investments.acquisition_lots target
    left join public.investment_lots source on source.id = target.id
    where source.id is null
      or source.position_id <> target.position_id
      or source.acquisition_action_id <> target.acquisition_action_id
      or source.remaining_share_count <> target.remaining_share_count
      or source.remaining_cost_basis <> target.remaining_cost_basis
  ) then
    raise exception 'investments_rollback_lot_reconciliation_failed';
  end if;
  if exists (
    select 1 from investments.share_purchases target
    left join public.holding_actions source
      on source.id = target.action_id and source.action_type = 'share_purchase'
    where source.id is null
      or source.company_id <> target.company_id
      or coalesce(
        nullif(source.payload ->> 'position_id', '')::uuid,
        (select position.id from public.investment_positions position
         where position.company_id = source.company_id
           and position.investment_key =
             pg_catalog.btrim(source.payload ->> 'investment_key'))
      ) <> target.position_id
      or (source.payload ->> 'acquisition_lot_id')::uuid <> target.acquisition_lot_id
      or (source.payload ->> 'share_count')::bigint <> target.share_count
      or (source.payload ->> 'purchase_amount')::numeric <> target.purchase_amount
  ) then
    raise exception 'investments_rollback_purchase_reconciliation_failed';
  end if;
end
$investments_rollback_reconciliation$;

revoke execute on function investments.get_share_purchase_replay_v1(jsonb, text)
  from investments_workflow_executor;
revoke execute on function investments.prepare_share_purchase_v1(jsonb, text)
  from investments_workflow_executor;
revoke execute on function investments.complete_share_purchase_v1(
  jsonb, uuid, jsonb, text
) from investments_workflow_executor;
revoke execute on function ledger.post_entry(
  text, uuid, integer, text, text, jsonb, jsonb, boolean,
  text, text, text, text
) from investments_workflow_executor;

do $investments_rollback_restore_predecessor$
begin
  if pg_catalog.to_regprocedure(
    'backend_system.prepare_investment_purchase_fifo_v1(jsonb,text)'
  ) is null then
    if pg_catalog.to_regprocedure(
      'backend_system.rollback_141_prepare_investment_purchase_fifo_v1(jsonb,text)'
    ) is null then
      raise exception 'investments_rollback_prepare_capsule_missing';
    end if;
    alter function backend_system.rollback_141_prepare_investment_purchase_fifo_v1(
      jsonb, text
    ) rename to prepare_investment_purchase_fifo_v1;
  end if;
  if pg_catalog.to_regprocedure(
    'backend_system.complete_investment_purchase_fifo_v1(jsonb,uuid,jsonb,text)'
  ) is null then
    if pg_catalog.to_regprocedure(
      'backend_system.rollback_141_complete_investment_purchase_fifo_v1(jsonb,uuid,jsonb,text)'
    ) is null then
      raise exception 'investments_rollback_complete_capsule_missing';
    end if;
    alter function backend_system.rollback_141_complete_investment_purchase_fifo_v1(
      jsonb, uuid, jsonb, text
    ) rename to complete_investment_purchase_fifo_v1;
  end if;
end
$investments_rollback_restore_predecessor$;

grant execute on function backend_system.prepare_investment_purchase_fifo_v1(
  jsonb, text
) to ledger_workflow_executor;
grant execute on function backend_system.complete_investment_purchase_fifo_v1(
  jsonb, uuid, jsonb, text
) to ledger_workflow_executor;

commit;
