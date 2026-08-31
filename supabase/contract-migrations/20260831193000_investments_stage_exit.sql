-- CONTRACT RELEASE ARTIFACT: complete investments stage exit, issue #143.
-- Apply after the three slice contracts and their bounded rollback rehearsal.

begin;

do $investments_stage_exit_membership$
begin
  execute pg_catalog.format(
    'grant investments_store_owner, ledger_store_owner to %I', current_user
  );
end
$investments_stage_exit_membership$;

select pg_catalog.pg_advisory_xact_lock(
  pg_catalog.hashtextextended('talli:investments:stage-exit:v1', 0)
);
lock table public.holding_actions in share row exclusive mode;
lock table public.investment_positions in share row exclusive mode;
lock table public.investment_lots in share row exclusive mode;
lock table public.investment_lot_allocations in share row exclusive mode;
lock table investments.positions in share row exclusive mode;
lock table investments.acquisition_lots in share row exclusive mode;
lock table investments.share_purchases in share row exclusive mode;
lock table investments.share_sales in share row exclusive mode;
lock table investments.share_sale_allocations in share row exclusive mode;
lock table investments.received_dividends in share row exclusive mode;

do $investments_stage_exit_reconciliation$
begin
  if exists (
    select 1 from investments.positions canonical
    full join public.investment_positions legacy on legacy.id = canonical.id
    where canonical.id is null or legacy.id is null
      or canonical.company_id is distinct from legacy.company_id
      or canonical.investment_key is distinct from legacy.investment_key
      or canonical.share_count is distinct from legacy.share_count::bigint
      or canonical.cost_basis is distinct from legacy.cost_basis
      or canonical.movements is distinct from legacy.movements
      or canonical.lot_history_status is distinct from legacy.lot_history_status
  ) then raise exception 'investments_stage_exit_position_reconciliation_failed'; end if;

  if exists (
    select 1 from investments.acquisition_lots canonical
    full join public.investment_lots legacy on legacy.id = canonical.id
    where canonical.id is null or legacy.id is null
      or canonical.position_id is distinct from legacy.position_id
      or canonical.acquisition_action_id is distinct from legacy.acquisition_action_id
      or canonical.remaining_share_count is distinct from legacy.remaining_share_count
      or canonical.remaining_cost_basis is distinct from legacy.remaining_cost_basis
  ) then raise exception 'investments_stage_exit_lot_reconciliation_failed'; end if;

  if exists (
    select 1 from investments.share_sale_allocations canonical
    full join public.investment_lot_allocations legacy
      on legacy.sale_action_id = canonical.sale_action_id
      and legacy.lot_id = canonical.acquisition_lot_id
    where canonical.sale_action_id is null or legacy.sale_action_id is null
      or canonical.id is distinct from legacy.id
      or canonical.position_id is distinct from legacy.position_id
      or canonical.allocated_share_count is distinct from legacy.allocated_share_count
      or canonical.allocated_cost_basis is distinct from legacy.allocated_cost_basis
  ) then raise exception 'investments_stage_exit_allocation_reconciliation_failed'; end if;

  if exists (
    select 1 from public.holding_actions legacy
    where legacy.action_type = 'share_purchase'
      and not exists (
        select 1 from investments.share_purchases canonical
        where canonical.action_id = legacy.id
          and canonical.accounting_entry_id is not distinct from legacy.ledger_entry_id
      )
  ) or exists (
    select 1 from public.holding_actions legacy
    where legacy.action_type = 'share_sale'
      and not exists (
        select 1 from investments.share_sales canonical
        where canonical.action_id = legacy.id
          and canonical.accounting_entry_id is not distinct from legacy.ledger_entry_id
      )
  ) or exists (
    select 1 from public.holding_actions legacy
    where legacy.action_type = 'dividend_received'
      and not exists (
        select 1 from investments.received_dividends canonical
        where canonical.action_id = legacy.id
          and canonical.accounting_entry_id is not distinct from legacy.ledger_entry_id
      )
  ) then raise exception 'investments_stage_exit_activity_reconciliation_failed'; end if;

  if exists (
    select 1 from investments.share_purchases canonical
    where not exists (
      select 1 from public.holding_actions legacy
      where legacy.id = canonical.action_id and legacy.action_type = 'share_purchase'
    )
  ) or exists (
    select 1 from investments.share_sales canonical
    where not exists (
      select 1 from public.holding_actions legacy
      where legacy.id = canonical.action_id and legacy.action_type = 'share_sale'
    )
  ) or exists (
    select 1 from investments.received_dividends canonical
    where not exists (
      select 1 from public.holding_actions legacy
      where legacy.id = canonical.action_id and legacy.action_type = 'dividend_received'
    )
  ) then raise exception 'investments_stage_exit_activity_count_failed'; end if;
end
$investments_stage_exit_reconciliation$;

do $investments_stage_exit_reference_preflight$
begin
  if exists (
    select 1
    from public.corporate_decision_finalizations finalization
    join public.holding_actions action
      on action.id = finalization.holding_action_id
    where action.action_type in (
      'share_purchase', 'share_sale', 'dividend_received'
    )
  ) then
    raise exception 'investments_stage_exit_unexpected_governance_reference';
  end if;
end
$investments_stage_exit_reference_preflight$;

create or replace function investments.complete_share_purchase_v1(
  p_request jsonb,
  p_entry_id uuid,
  p_prepared jsonb,
  p_verified_subject text
)
returns jsonb language plpgsql security definer set search_path = ''
as $function$
declare
  v_actor_id uuid := public.company_access_auth_uid_v1();
  v_purchase investments.share_purchases%rowtype;
begin
  if v_actor_id is null or v_actor_id is distinct from p_verified_subject::uuid then
    raise exception 'investments_forbidden';
  end if;
  select purchase.* into v_purchase
  from investments.share_purchases purchase
  where purchase.action_id = (p_request ->> 'actionId')::uuid
  for update;
  if not found
    or v_purchase.request_fingerprint <>
      investments.share_purchase_fingerprint_v1(p_request)
    or v_purchase.position_id <> (p_prepared ->> 'positionId')::uuid
    or v_purchase.acquisition_lot_id <> (p_prepared ->> 'lotId')::uuid
    or v_purchase.position_created <>
      (p_prepared ->> 'positionCreated')::boolean
    or not ledger.investment_entry_matches_v1(
      p_entry_id, v_purchase.company_id, v_purchase.action_id
    )
  then raise exception 'investments_dependency_unavailable'; end if;
  if v_purchase.accounting_entry_id is not null then
    if v_purchase.accounting_entry_id <> p_entry_id then
      raise exception 'investments_idempotency_key_reused';
    end if;
    return pg_catalog.jsonb_build_object(
      'actionId', v_purchase.action_id, 'positionId', v_purchase.position_id,
      'lotId', v_purchase.acquisition_lot_id,
      'accountingEntryId', v_purchase.accounting_entry_id,
      'positionCreated', v_purchase.position_created, 'replayed', true
    );
  end if;
  insert into investments.acquisition_lots (
    id, company_id, position_id, acquisition_action_id, acquisition_date,
    original_share_count, remaining_share_count, original_cost_basis,
    remaining_cost_basis, created_by
  ) values (
    v_purchase.acquisition_lot_id, v_purchase.company_id, v_purchase.position_id,
    v_purchase.action_id, v_purchase.acquisition_date,
    v_purchase.share_count, v_purchase.share_count,
    v_purchase.purchase_amount, v_purchase.purchase_amount, v_actor_id
  );
  update investments.positions
  set share_count = share_count + v_purchase.share_count,
      cost_basis = cost_basis + v_purchase.purchase_amount,
      movements = movements || pg_catalog.jsonb_build_array(pg_catalog.jsonb_build_object(
        'action_id', v_purchase.action_id, 'movement_type', 'purchase',
        'movement_date', v_purchase.acquisition_date,
        'share_delta', v_purchase.share_count,
        'cost_basis_delta', v_purchase.purchase_amount,
        'amount', v_purchase.purchase_amount,
        'lot_id', v_purchase.acquisition_lot_id
      )),
      updated_at = pg_catalog.now()
  where id = v_purchase.position_id;
  update investments.share_purchases
  set accounting_entry_id = p_entry_id, completed_at = pg_catalog.now()
  where action_id = v_purchase.action_id;
  insert into public.audit_events (company_id, actor_id, category, action, message)
  values (
    v_purchase.company_id, v_actor_id, 'ledger', 'share_purchase_recorded',
    'Aksjekjøp postert for ' || v_purchase.investment_name || ' i ' ||
      v_purchase.income_year || '.'
  );
  return pg_catalog.jsonb_build_object(
    'actionId', v_purchase.action_id, 'positionId', v_purchase.position_id,
    'lotId', v_purchase.acquisition_lot_id, 'accountingEntryId', p_entry_id,
    'positionCreated', v_purchase.position_created, 'replayed', false
  );
end;
$function$;

create or replace function investments.complete_share_sale_v1(
  p_request jsonb,
  p_entry_id uuid,
  p_verified_subject text
)
returns jsonb language plpgsql security definer set search_path = ''
as $function$
declare
  v_actor_id uuid := public.company_access_auth_uid_v1();
  v_sale investments.share_sales%rowtype;
  v_position investments.positions%rowtype;
  v_lot investments.acquisition_lots%rowtype;
  v_left bigint;
  v_allocated_shares bigint;
  v_allocated_cost numeric;
  v_cost numeric := 0;
  v_remaining_shares bigint;
  v_remaining_cost numeric;
  v_order integer := 0;
  v_count integer;
begin
  if v_actor_id is null or v_actor_id is distinct from p_verified_subject::uuid then
    raise exception 'investments_forbidden';
  end if;
  select sale.* into v_sale from investments.share_sales sale
  where sale.action_id = (p_request ->> 'actionId')::uuid for update;
  if not found
    or v_sale.request_fingerprint <> investments.share_sale_fingerprint_v1(p_request)
    or not ledger.investment_sale_entry_matches_v1(
      p_entry_id, v_sale.company_id, v_sale.action_id
    )
  then raise exception 'investments_dependency_unavailable'; end if;
  if v_sale.accounting_entry_id is not null then
    if v_sale.accounting_entry_id <> p_entry_id then
      raise exception 'investments_idempotency_key_reused';
    end if;
    return pg_catalog.jsonb_build_object(
      'actionId', v_sale.action_id,
      'positionId', v_sale.position_id,
      'accountingEntryId', v_sale.accounting_entry_id,
      'replayed', true
    );
  end if;
  select position.* into v_position from investments.positions position
  where position.id = v_sale.position_id for update;
  if not found or v_position.company_id <> v_sale.company_id
    or v_position.lot_history_status <> 'complete'
    or v_position.share_count <> v_sale.remaining_share_count + v_sale.sold_share_count
    or v_position.cost_basis < v_sale.fifo_cost_basis_reduction
  then raise exception 'investments_dependency_unavailable'; end if;
  v_left := v_sale.sold_share_count;
  for v_lot in
    select lot.* from investments.acquisition_lots lot
    where lot.position_id = v_sale.position_id and lot.remaining_share_count > 0
    order by lot.acquisition_date, lot.id for update
  loop
    exit when v_left = 0;
    v_allocated_shares := case
      when v_left < v_lot.remaining_share_count then v_left
      else v_lot.remaining_share_count
    end;
    v_allocated_cost := case
      when v_allocated_shares = v_lot.remaining_share_count
        then v_lot.remaining_cost_basis
      else pg_catalog.round(
        v_lot.remaining_cost_basis * v_allocated_shares /
          v_lot.remaining_share_count,
        2
      )
    end;
    v_order := v_order + 1;
    insert into investments.share_sale_allocations (
      sale_action_id, company_id, position_id, acquisition_lot_id,
      allocation_order, acquisition_date, allocated_share_count,
      allocated_cost_basis, created_by
    ) values (
      v_sale.action_id, v_sale.company_id, v_sale.position_id, v_lot.id,
      v_order, v_lot.acquisition_date, v_allocated_shares,
      v_allocated_cost, v_actor_id
    );
    update investments.acquisition_lots
    set remaining_share_count = remaining_share_count - v_allocated_shares,
        remaining_cost_basis = remaining_cost_basis - v_allocated_cost
    where id = v_lot.id
      and remaining_share_count = v_lot.remaining_share_count
      and remaining_cost_basis = v_lot.remaining_cost_basis;
    get diagnostics v_count = row_count;
    if v_count <> 1 then raise exception 'investments_dependency_unavailable'; end if;
    v_left := v_left - v_allocated_shares;
    v_cost := v_cost + v_allocated_cost;
  end loop;
  if v_left <> 0 or v_cost <> v_sale.fifo_cost_basis_reduction then
    raise exception 'investments_dependency_unavailable';
  end if;
  select coalesce(pg_catalog.sum(lot.remaining_share_count), 0),
    coalesce(pg_catalog.sum(lot.remaining_cost_basis), 0)
  into v_remaining_shares, v_remaining_cost
  from investments.acquisition_lots lot
  where lot.position_id = v_sale.position_id and lot.remaining_share_count > 0;
  if v_remaining_shares <> v_sale.remaining_share_count
    or v_remaining_cost <> v_sale.remaining_cost_basis
  then raise exception 'investments_dependency_unavailable'; end if;
  update investments.positions
  set share_count = v_remaining_shares,
      cost_basis = v_remaining_cost,
      movements = movements || pg_catalog.jsonb_build_array(
        pg_catalog.jsonb_build_object(
          'action_id', v_sale.action_id, 'movement_type', 'sale',
          'movement_date', v_sale.sale_date,
          'share_delta', -v_sale.sold_share_count,
          'cost_basis_delta', -v_sale.fifo_cost_basis_reduction,
          'amount', v_sale.proceeds, 'gain_or_loss', v_sale.gain_or_loss,
          'lot_allocations', (
            select pg_catalog.jsonb_agg(pg_catalog.jsonb_build_object(
              'lot_id', allocation.acquisition_lot_id,
              'acquisition_date', allocation.acquisition_date,
              'share_count', allocation.allocated_share_count,
              'cost_basis', allocation.allocated_cost_basis
            ) order by allocation.allocation_order)
            from investments.share_sale_allocations allocation
            where allocation.sale_action_id = v_sale.action_id
          )
        )
      ),
      updated_at = pg_catalog.now()
  where id = v_sale.position_id;
  get diagnostics v_count = row_count;
  if v_count <> 1 then raise exception 'investments_dependency_unavailable'; end if;
  update investments.share_sales
  set accounting_entry_id = p_entry_id, completed_at = pg_catalog.now()
  where action_id = v_sale.action_id;
  insert into public.audit_events (company_id, actor_id, category, action, message)
  values (
    v_sale.company_id, v_actor_id, 'ledger', 'share_sale_recorded',
    'Aksjesalg postert for ' || v_position.name || ' i ' || v_sale.income_year || '.'
  );
  return pg_catalog.jsonb_build_object(
    'actionId', v_sale.action_id,
    'positionId', v_sale.position_id,
    'accountingEntryId', p_entry_id,
    'replayed', false
  );
end;
$function$;

create or replace function investments.complete_received_dividend_v1(
  p_request jsonb,
  p_entry_id uuid,
  p_verified_subject text
)
returns jsonb language plpgsql security definer set search_path = ''
as $function$
declare
  v_actor_id uuid := public.company_access_auth_uid_v1();
  v_dividend investments.received_dividends%rowtype;
  v_count integer;
begin
  if v_actor_id is null or v_actor_id is distinct from p_verified_subject::uuid then
    raise exception 'investments_forbidden';
  end if;
  select dividend.* into v_dividend
  from investments.received_dividends dividend
  where dividend.action_id = (p_request ->> 'actionId')::uuid for update;
  if not found
    or v_dividend.request_fingerprint <>
      investments.received_dividend_fingerprint_v1(p_request)
    or not ledger.investment_dividend_entry_matches_v1(
      p_entry_id, v_dividend.company_id, v_dividend.action_id
    )
  then raise exception 'investments_dependency_unavailable'; end if;
  if v_dividend.accounting_entry_id is not null then
    if v_dividend.accounting_entry_id <> p_entry_id then
      raise exception 'investments_idempotency_key_reused';
    end if;
    return pg_catalog.jsonb_build_object(
      'actionId', v_dividend.action_id,
      'positionId', v_dividend.position_id,
      'accountingEntryId', v_dividend.accounting_entry_id,
      'taxableAddBack', v_dividend.taxable_add_back,
      'replayed', true
    );
  end if;
  update investments.received_dividends
  set accounting_entry_id = p_entry_id, completed_at = pg_catalog.now()
  where action_id = v_dividend.action_id and accounting_entry_id is null;
  get diagnostics v_count = row_count;
  if v_count <> 1 then raise exception 'investments_dependency_unavailable'; end if;
  insert into public.audit_events (company_id, actor_id, category, action, message)
  values (
    v_dividend.company_id, v_actor_id, 'ledger',
    'dividend_received_recorded',
    'Mottatt utbytte postert fra ' || v_dividend.paying_company_name ||
      ' for ' || v_dividend.income_year || '.'
  );
  return pg_catalog.jsonb_build_object(
    'actionId', v_dividend.action_id,
    'positionId', v_dividend.position_id,
    'accountingEntryId', p_entry_id,
    'taxableAddBack', v_dividend.taxable_add_back,
    'replayed', false
  );
end;
$function$;

grant insert on public.audit_events to investments_store_owner;
drop policy if exists "investments append audit" on public.audit_events;
create policy "investments append audit"
on public.audit_events for insert to investments_store_owner
with check (
  actor_id = public.company_access_auth_uid_v1()
  and public.company_access_is_accepted_owner_v1(company_id)
);

-- Archive receipts are authoritative only while every canonical investment
-- source participates in the company-wide generation boundary. The legacy
-- public-table triggers disappear with their tables below.
drop trigger if exists company_archive_track_investments_positions
  on investments.positions;
create trigger company_archive_track_investments_positions
before insert or update or delete on investments.positions for each row
execute function public.company_archive_track_source_write_v1('company', 'company_id');
drop trigger if exists company_archive_track_investments_acquisition_lots
  on investments.acquisition_lots;
create trigger company_archive_track_investments_acquisition_lots
before insert or update or delete on investments.acquisition_lots for each row
execute function public.company_archive_track_source_write_v1('company', 'company_id');
drop trigger if exists company_archive_track_investments_share_purchases
  on investments.share_purchases;
create trigger company_archive_track_investments_share_purchases
before insert or update or delete on investments.share_purchases for each row
execute function public.company_archive_track_source_write_v1('year', 'company_id');
drop trigger if exists company_archive_track_investments_share_sales
  on investments.share_sales;
create trigger company_archive_track_investments_share_sales
before insert or update or delete on investments.share_sales for each row
execute function public.company_archive_track_source_write_v1('year', 'company_id');
drop trigger if exists company_archive_track_investments_share_sale_allocations
  on investments.share_sale_allocations;
create trigger company_archive_track_investments_share_sale_allocations
before insert or update or delete on investments.share_sale_allocations for each row
execute function public.company_archive_track_source_write_v1('company', 'company_id');
drop trigger if exists company_archive_track_investments_received_dividends
  on investments.received_dividends;
create trigger company_archive_track_investments_received_dividends
before insert or update or delete on investments.received_dividends for each row
execute function public.company_archive_track_source_write_v1('year', 'company_id');

drop policy if exists investments_positions_successor_overlap
  on investments.positions;
drop policy if exists investments_lots_successor_overlap
  on investments.acquisition_lots;
drop policy if exists investments_purchases_successor_overlap
  on investments.share_purchases;
drop policy if exists investments_share_sales_predecessor_overlap
  on investments.share_sales;
drop policy if exists investments_share_sale_allocations_predecessor_overlap
  on investments.share_sale_allocations;
drop policy if exists investments_received_dividends_predecessor_overlap
  on investments.received_dividends;

drop trigger if exists share_purchases_sync_to_investments
  on public.holding_actions;
drop trigger if exists share_sales_sync_to_investments
  on public.holding_actions;
drop trigger if exists received_dividends_sync_to_investments
  on public.holding_actions;
drop trigger if exists holding_actions_require_investment_rpc
  on public.holding_actions;

delete from public.investment_lot_allocations;
delete from public.investment_lots;
delete from public.investment_positions;
delete from public.holding_actions
where action_type in ('share_purchase', 'share_sale', 'dividend_received');

do $investments_legacy_allocations_empty_preflight$
begin
  if pg_catalog.to_regclass('public.investment_lot_allocations') is not null
    and exists (select 1 from public.investment_lot_allocations)
  then raise exception 'investments_stage_exit_legacy_allocations_not_empty'; end if;
end
$investments_legacy_allocations_empty_preflight$;
drop table if exists public.investment_lot_allocations;

do $investments_legacy_lots_empty_preflight$
begin
  if pg_catalog.to_regclass('public.investment_lots') is not null
    and exists (select 1 from public.investment_lots)
  then raise exception 'investments_stage_exit_legacy_lots_not_empty'; end if;
end
$investments_legacy_lots_empty_preflight$;
drop table if exists public.investment_lots;

do $investments_legacy_positions_empty_preflight$
begin
  if pg_catalog.to_regclass('public.investment_positions') is not null
    and exists (select 1 from public.investment_positions)
  then raise exception 'investments_stage_exit_legacy_positions_not_empty'; end if;
end
$investments_legacy_positions_empty_preflight$;
drop table if exists public.investment_positions;

alter table public.holding_actions
  drop constraint if exists holding_actions_action_type_check;
alter table public.holding_actions
  add constraint holding_actions_action_type_check check (
    action_type in ('dividend_to_owner', 'shareholder_loan', 'tax_settlement')
  );

drop function if exists public.reject_direct_investment_action();
drop function if exists backend_system.align_legacy_share_sale_allocation_id_v1();
drop function if exists backend_system.sync_legacy_investment_position_v1();
drop function if exists backend_system.sync_legacy_investment_lot_v1();
drop function if exists backend_system.sync_legacy_share_purchase_v1();
drop function if exists backend_system.sync_legacy_share_sale_v1();
drop function if exists backend_system.sync_legacy_share_sale_allocation_v1();
drop function if exists backend_system.sync_legacy_received_dividend_v1();
drop function if exists backend_system.mirror_investment_purchase_to_successor_v1(
  uuid, uuid, uuid
);
drop function if exists backend_system.mirror_investment_sale_to_legacy_v1(
  uuid, uuid, uuid
);
drop function if exists backend_system.mirror_received_dividend_to_legacy_v1(
  uuid, uuid, uuid
);
drop function if exists backend_system.rollback_141_prepare_investment_purchase_fifo_v1(
  jsonb, text
);
drop function if exists backend_system.rollback_141_complete_investment_purchase_fifo_v1(
  jsonb, uuid, jsonb, text
);
drop function if exists backend_system.rollback_142_prepare_investment_sale_fifo_v1(
  jsonb, text
);
drop function if exists backend_system.rollback_142_complete_investment_sale_fifo_v1(
  jsonb, uuid, jsonb, text
);
drop function if exists backend_system.rollback_143_prepare_investment_dividend_v1(
  jsonb, text
);
drop function if exists backend_system.rollback_143_complete_investment_dividend_v1(
  jsonb, uuid, jsonb, text
);
drop function if exists backend_system.prepare_investment_purchase_fifo_v1(
  jsonb, text
);
drop function if exists backend_system.complete_investment_purchase_fifo_v1(
  jsonb, uuid, jsonb, text
);
drop function if exists backend_system.prepare_investment_sale_fifo_v1(
  jsonb, text
);
drop function if exists backend_system.complete_investment_sale_fifo_v1(
  jsonb, uuid, jsonb, text
);
drop function if exists backend_system.prepare_investment_dividend_v1(
  jsonb, text
);
drop function if exists backend_system.complete_investment_dividend_v1(
  jsonb, uuid, jsonb, text
);

revoke select, insert, update on investments.positions,
  investments.acquisition_lots, investments.share_purchases,
  investments.share_sales, investments.share_sale_allocations,
  investments.received_dividends from ledger_store_owner;
revoke usage on schema investments from ledger_store_owner;

do $investments_stage_exit_revoke$
begin
  execute pg_catalog.format(
    'revoke investments_store_owner, ledger_store_owner from %I', current_user
  );
end
$investments_stage_exit_revoke$;

commit;
