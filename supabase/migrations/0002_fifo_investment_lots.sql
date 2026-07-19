-- HoldingSwift investment register: immutable acquisition lots and atomic FIFO writes.

alter table public.investment_positions
  add column if not exists lot_history_status text not null default 'needs_reconstruction';

alter table public.investment_positions
  drop constraint if exists investment_positions_lot_history_status_check;
alter table public.investment_positions
  add constraint investment_positions_lot_history_status_check
  check (lot_history_status in ('complete', 'needs_reconstruction'));

create table if not exists public.investment_lots (
  id uuid primary key default gen_random_uuid(),
  company_id uuid not null references public.companies(id) on delete cascade,
  position_id uuid not null references public.investment_positions(id) on delete restrict,
  acquisition_action_id uuid not null references public.holding_actions(id) on delete restrict,
  acquisition_date date not null,
  original_share_count bigint not null check (original_share_count > 0),
  remaining_share_count bigint not null check (
    remaining_share_count >= 0 and remaining_share_count <= original_share_count
  ),
  original_cost_basis numeric(20, 2) not null check (original_cost_basis > 0),
  remaining_cost_basis numeric(20, 2) not null check (
    remaining_cost_basis >= 0 and remaining_cost_basis <= original_cost_basis
  ),
  created_by uuid not null references auth.users(id) on delete restrict,
  created_at timestamptz not null default now(),
  unique (acquisition_action_id),
  check (remaining_share_count <> 0 or remaining_cost_basis = 0)
);

create table if not exists public.investment_lot_allocations (
  id uuid primary key default gen_random_uuid(),
  company_id uuid not null references public.companies(id) on delete cascade,
  position_id uuid not null references public.investment_positions(id) on delete restrict,
  lot_id uuid not null references public.investment_lots(id) on delete restrict,
  sale_action_id uuid not null references public.holding_actions(id) on delete restrict,
  allocated_share_count bigint not null check (allocated_share_count > 0),
  allocated_cost_basis numeric(20, 2) not null check (allocated_cost_basis >= 0),
  created_by uuid not null references auth.users(id) on delete restrict,
  created_at timestamptz not null default now(),
  unique (sale_action_id, lot_id)
);

create index if not exists investment_lots_position_fifo_idx
  on public.investment_lots(position_id, acquisition_date, id);
create index if not exists investment_lots_company_idx
  on public.investment_lots(company_id);
create index if not exists investment_lot_allocations_sale_idx
  on public.investment_lot_allocations(sale_action_id);
create index if not exists investment_lot_allocations_position_idx
  on public.investment_lot_allocations(position_id);

alter table public.investment_lots enable row level security;
alter table public.investment_lot_allocations enable row level security;

grant select on public.investment_lots to authenticated;
grant select on public.investment_lot_allocations to authenticated;
revoke insert, update, delete on public.investment_lots from authenticated;
revoke insert, update, delete on public.investment_lot_allocations from authenticated;

drop policy if exists "company members can read investment lots" on public.investment_lots;
create policy "company members can read investment lots"
on public.investment_lots for select
to authenticated
using (
  exists (
    select 1
    from public.company_memberships m
    where m.company_id = investment_lots.company_id
      and m.user_id = (select auth.uid())
  )
);

drop policy if exists "company members can read investment lot allocations" on public.investment_lot_allocations;
create policy "company members can read investment lot allocations"
on public.investment_lot_allocations for select
to authenticated
using (
  exists (
    select 1
    from public.company_memberships m
    where m.company_id = investment_lot_allocations.company_id
      and m.user_id = (select auth.uid())
  )
);

-- Investment positions and lots are projections maintained only by the atomic
-- functions below. Removing direct grants closes the bypass around FIFO and
-- concurrent row locking; members retain read access through the existing RLS.
revoke insert, update, delete on public.investment_positions from authenticated;
drop policy if exists "owners can create investment positions" on public.investment_positions;
drop policy if exists "owners can update investment positions" on public.investment_positions;

create or replace function public.reject_direct_investment_action()
returns trigger
language plpgsql
set search_path = public, pg_temp
as $$
begin
  if new.action_type in ('share_purchase', 'share_sale')
    and coalesce(current_setting('talli.investment_action_write', true), '') <> 'on'
  then
    raise exception 'investment_action_requires_atomic_rpc';
  end if;
  return new;
end;
$$;

drop trigger if exists holding_actions_require_investment_rpc on public.holding_actions;
create trigger holding_actions_require_investment_rpc
before insert on public.holding_actions
for each row execute function public.reject_direct_investment_action();

create or replace function public.record_share_purchase_fifo(
  p_action_id uuid,
  p_company_id uuid,
  p_income_year integer,
  p_investment_key text,
  p_investment_name text,
  p_investment_kind text,
  p_tax_treatment text,
  p_acquisition_date date,
  p_share_count bigint,
  p_purchase_amount numeric,
  p_org_number text,
  p_bank_transaction_id uuid,
  p_document_id uuid,
  p_document_status text
)
returns jsonb
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
  v_actor_id uuid := auth.uid();
  v_existing_action public.holding_actions%rowtype;
  v_position public.investment_positions%rowtype;
  v_position_id uuid;
  v_position_was_created boolean := false;
  v_entry_id uuid := gen_random_uuid();
  v_lot_id uuid := gen_random_uuid();
  v_bank public.bank_transactions%rowtype;
  v_document public.documents%rowtype;
  v_payload jsonb;
  v_lines jsonb;
  v_row_count integer;
begin
  if v_actor_id is null then
    raise exception 'authentication_required';
  end if;
  if not exists (
    select 1 from public.company_memberships m
    where m.company_id = p_company_id and m.user_id = v_actor_id and m.role = 'owner'
  ) then
    raise exception 'company_owner_required';
  end if;
  if exists (
    select 1 from public.period_locks pl
    where pl.company_id = p_company_id and pl.income_year = p_income_year
  ) then
    raise exception 'income_year_locked';
  end if;

  select * into v_existing_action
  from public.holding_actions
  where id = p_action_id;
  if found then
    if v_existing_action.company_id <> p_company_id or v_existing_action.action_type <> 'share_purchase' then
      raise exception 'idempotency_key_conflict';
    end if;
    return jsonb_build_object(
      'action_id', v_existing_action.id,
      'ledger_entry_id', v_existing_action.ledger_entry_id,
      'idempotent', true
    );
  end if;

  p_investment_key := btrim(p_investment_key);
  p_investment_name := btrim(p_investment_name);
  p_org_number := nullif(btrim(coalesce(p_org_number, '')), '');
  if p_action_id is null or p_company_id is null or p_investment_key = '' or p_investment_name = '' then
    raise exception 'invalid_purchase_identity';
  end if;
  if p_investment_kind <> 'norwegian_private_company' or p_tax_treatment <> 'fritaksmetoden' then
    raise exception 'unsupported_investment_treatment';
  end if;
  if p_share_count is null or p_share_count <= 0 then
    raise exception 'invalid_share_count';
  end if;
  if p_purchase_amount is null or p_purchase_amount <= 0 or round(p_purchase_amount, 2) <> p_purchase_amount then
    raise exception 'invalid_purchase_amount';
  end if;
  if p_acquisition_date is null or extract(year from p_acquisition_date)::integer <> p_income_year then
    raise exception 'purchase_date_income_year_mismatch';
  end if;
  if p_org_number is not null and p_org_number !~ '^[0-9]{9}$' then
    raise exception 'invalid_org_number';
  end if;
  if p_document_status not in ('attached', 'missing_accepted_warning', 'not_required') then
    raise exception 'invalid_document_status';
  end if;

  if p_bank_transaction_id is not null then
    select * into v_bank
    from public.bank_transactions
    where id = p_bank_transaction_id
    for update;
    if not found
      or v_bank.company_id <> p_company_id
      or v_bank.income_year <> p_income_year
      or v_bank.matched_entry_id is not null
      or v_bank.matched_action_id is not null
      or v_bank.accepted_warning
      or v_bank.amount <> -p_purchase_amount
    then
      raise exception 'bank_transaction_mismatch';
    end if;
  end if;

  if p_document_id is not null then
    select * into v_document from public.documents where id = p_document_id;
    if not found or v_document.company_id <> p_company_id or v_document.income_year <> p_income_year then
      raise exception 'document_mismatch';
    end if;
  end if;

  insert into public.investment_positions (
    company_id, investment_key, name, kind, tax_treatment, org_number,
    share_count, cost_basis, movements, lot_history_status, created_by
  ) values (
    p_company_id, p_investment_key, p_investment_name, p_investment_kind, p_tax_treatment, p_org_number,
    0, 0, '[]'::jsonb, 'complete', v_actor_id
  )
  on conflict (company_id, investment_key) do nothing
  returning id into v_position_id;

  if v_position_id is null then
    select * into v_position
    from public.investment_positions
    where company_id = p_company_id and investment_key = p_investment_key
    for update;
    v_position_id := v_position.id;
    if v_position.kind <> p_investment_kind
      or v_position.tax_treatment <> p_tax_treatment
      or coalesce(v_position.org_number, '') <> coalesce(p_org_number, '')
    then
      raise exception 'investment_position_identity_conflict';
    end if;
    if v_position.lot_history_status = 'needs_reconstruction'
      and v_position.share_count = 0 and v_position.cost_basis = 0
    then
      update public.investment_positions
      set lot_history_status = 'complete'
      where id = v_position_id;
    end if;
  else
    v_position_was_created := true;
  end if;

  v_lines := jsonb_build_array(
    jsonb_build_object('account', '1800', 'description', 'Investment in ' || p_investment_name, 'debit', p_purchase_amount, 'credit', 0),
    jsonb_build_object('account', '1920', 'description', 'Paid from bank', 'debit', 0, 'credit', p_purchase_amount)
  );
  v_payload := jsonb_build_object(
    'investment_key', p_investment_key,
    'investment_name', p_investment_name,
    'investment_kind', p_investment_kind,
    'tax_treatment', p_tax_treatment,
    'acquisition_date', p_acquisition_date,
    'share_count', p_share_count,
    'purchase_amount', p_purchase_amount,
    'org_number', p_org_number,
    'bank_transaction_id', p_bank_transaction_id,
    'document_id', p_document_id,
    'document_status', p_document_status,
    'acquisition_lot_id', v_lot_id
  );

  perform set_config('talli.investment_action_write', 'on', true);
  insert into public.ledger_entries (
    id, company_id, income_year, entry_type, memo, lines, risk_flags, created_by
  ) values (
    v_entry_id, p_company_id, p_income_year, 'share_purchase',
    'Share purchase: ' || p_investment_name, v_lines, '[]'::jsonb, v_actor_id
  );
  insert into public.holding_actions (
    id, company_id, income_year, action_type, action_date, payload, ledger_entry_id,
    bank_transaction_id, document_id, risk_level, created_by
  ) values (
    p_action_id, p_company_id, p_income_year, 'share_purchase', p_acquisition_date, v_payload, v_entry_id,
    p_bank_transaction_id, p_document_id, 'ready', v_actor_id
  );
  insert into public.investment_lots (
    id, company_id, position_id, acquisition_action_id, acquisition_date,
    original_share_count, remaining_share_count, original_cost_basis,
    remaining_cost_basis, created_by
  ) values (
    v_lot_id, p_company_id, v_position_id, p_action_id, p_acquisition_date,
    p_share_count, p_share_count, p_purchase_amount, p_purchase_amount, v_actor_id
  );

  update public.investment_positions
  set share_count = share_count + p_share_count,
      cost_basis = cost_basis + p_purchase_amount,
      movements = movements || jsonb_build_array(jsonb_build_object(
        'action_id', p_action_id,
        'movement_type', 'purchase',
        'movement_date', p_acquisition_date,
        'share_delta', p_share_count,
        'cost_basis_delta', p_purchase_amount,
        'amount', p_purchase_amount,
        'lot_id', v_lot_id
      )),
      updated_at = now()
  where id = v_position_id;

  if p_bank_transaction_id is not null then
    update public.bank_transactions
    set matched_action_id = p_action_id::text
    where id = p_bank_transaction_id and matched_action_id is null and matched_entry_id is null;
    get diagnostics v_row_count = row_count;
    if v_row_count <> 1 then
      raise exception 'bank_transaction_concurrent_match';
    end if;
  end if;

  insert into public.audit_events (company_id, actor_id, category, action, message)
  values (
    p_company_id, v_actor_id, 'ledger', 'share_purchase_recorded',
    'Aksjekjøp postert for ' || p_investment_name || ' i ' || p_income_year || '.'
  );

  return jsonb_build_object(
    'action_id', p_action_id,
    'ledger_entry_id', v_entry_id,
    'position_id', v_position_id,
    'lot_id', v_lot_id,
    'position_created', v_position_was_created,
    'idempotent', false,
    'payload', v_payload
  );
end;
$$;

create or replace function public.record_share_sale_fifo(
  p_action_id uuid,
  p_company_id uuid,
  p_income_year integer,
  p_position_id uuid,
  p_sale_date date,
  p_sold_share_count bigint,
  p_proceeds numeric,
  p_bank_transaction_id uuid,
  p_document_id uuid,
  p_document_status text
)
returns jsonb
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
  v_actor_id uuid := auth.uid();
  v_existing_action public.holding_actions%rowtype;
  v_position public.investment_positions%rowtype;
  v_bank public.bank_transactions%rowtype;
  v_document public.documents%rowtype;
  v_lot record;
  v_entry_id uuid := gen_random_uuid();
  v_available_shares bigint;
  v_available_cost numeric(20, 2);
  v_shares_to_allocate bigint;
  v_allocated_shares bigint;
  v_allocated_cost numeric(20, 2);
  v_cost_basis_reduction numeric(20, 2) := 0;
  v_remaining_shares bigint;
  v_remaining_cost numeric(20, 2);
  v_gain_or_loss numeric(20, 2);
  v_allocations jsonb := '[]'::jsonb;
  v_payload jsonb;
  v_lines jsonb;
  v_row_count integer;
begin
  if v_actor_id is null then
    raise exception 'authentication_required';
  end if;
  if not exists (
    select 1 from public.company_memberships m
    where m.company_id = p_company_id and m.user_id = v_actor_id and m.role = 'owner'
  ) then
    raise exception 'company_owner_required';
  end if;
  if exists (
    select 1 from public.period_locks pl
    where pl.company_id = p_company_id and pl.income_year = p_income_year
  ) then
    raise exception 'income_year_locked';
  end if;

  select * into v_existing_action
  from public.holding_actions
  where id = p_action_id;
  if found then
    if v_existing_action.company_id <> p_company_id or v_existing_action.action_type <> 'share_sale' then
      raise exception 'idempotency_key_conflict';
    end if;
    return jsonb_build_object(
      'action_id', v_existing_action.id,
      'ledger_entry_id', v_existing_action.ledger_entry_id,
      'idempotent', true,
      'payload', v_existing_action.payload
    );
  end if;

  if p_action_id is null or p_position_id is null then
    raise exception 'invalid_sale_identity';
  end if;
  if p_sold_share_count is null or p_sold_share_count <= 0 then
    raise exception 'invalid_sold_share_count';
  end if;
  if p_proceeds is null or p_proceeds < 0 or round(p_proceeds, 2) <> p_proceeds then
    raise exception 'invalid_proceeds';
  end if;
  if p_sale_date is null or extract(year from p_sale_date)::integer <> p_income_year then
    raise exception 'sale_date_income_year_mismatch';
  end if;
  if p_document_status not in ('attached', 'missing_accepted_warning', 'not_required') then
    raise exception 'invalid_document_status';
  end if;

  select * into v_position
  from public.investment_positions
  where id = p_position_id
  for update;
  if not found or v_position.company_id <> p_company_id then
    raise exception 'investment_position_mismatch';
  end if;
  if v_position.lot_history_status <> 'complete' then
    raise exception 'lot_history_incomplete';
  end if;

  perform 1
  from public.investment_lots l
  where l.position_id = p_position_id and l.remaining_share_count > 0
  order by l.acquisition_date, l.id
  for update;
  select coalesce(sum(l.remaining_share_count), 0), coalesce(sum(l.remaining_cost_basis), 0)
  into v_available_shares, v_available_cost
  from public.investment_lots l
  where l.position_id = p_position_id and l.remaining_share_count > 0;
  if v_available_shares = 0 then
    raise exception 'missing_acquisition_lots';
  end if;
  if v_available_shares::numeric <> v_position.share_count or v_available_cost <> v_position.cost_basis then
    raise exception 'lot_position_mismatch';
  end if;
  if p_sold_share_count > v_available_shares then
    raise exception 'sale_exceeds_lots';
  end if;

  if p_bank_transaction_id is not null then
    select * into v_bank
    from public.bank_transactions
    where id = p_bank_transaction_id
    for update;
    if not found
      or v_bank.company_id <> p_company_id
      or v_bank.income_year <> p_income_year
      or v_bank.matched_entry_id is not null
      or v_bank.matched_action_id is not null
      or v_bank.accepted_warning
      or v_bank.amount <> p_proceeds
    then
      raise exception 'bank_transaction_mismatch';
    end if;
  end if;
  if p_document_id is not null then
    select * into v_document from public.documents where id = p_document_id;
    if not found or v_document.company_id <> p_company_id or v_document.income_year <> p_income_year then
      raise exception 'document_mismatch';
    end if;
  end if;

  v_shares_to_allocate := p_sold_share_count;
  for v_lot in
    select *
    from public.investment_lots l
    where l.position_id = p_position_id and l.remaining_share_count > 0
    order by l.acquisition_date, l.id
    for update
  loop
    exit when v_shares_to_allocate = 0;
    v_allocated_shares := least(v_shares_to_allocate, v_lot.remaining_share_count);
    if v_allocated_shares = v_lot.remaining_share_count then
      v_allocated_cost := v_lot.remaining_cost_basis;
    else
      v_allocated_cost := round(
        v_lot.remaining_cost_basis * v_allocated_shares / v_lot.remaining_share_count,
        2
      );
    end if;
    update public.investment_lots
    set remaining_share_count = remaining_share_count - v_allocated_shares,
        remaining_cost_basis = remaining_cost_basis - v_allocated_cost
    where id = v_lot.id;
    v_shares_to_allocate := v_shares_to_allocate - v_allocated_shares;
    v_cost_basis_reduction := v_cost_basis_reduction + v_allocated_cost;
    v_allocations := v_allocations || jsonb_build_array(jsonb_build_object(
      'lot_id', v_lot.id,
      'acquisition_date', v_lot.acquisition_date,
      'share_count', v_allocated_shares,
      'cost_basis', v_allocated_cost
    ));
  end loop;
  if v_shares_to_allocate <> 0 then
    raise exception 'sale_allocation_incomplete';
  end if;

  select coalesce(sum(l.remaining_share_count), 0), coalesce(sum(l.remaining_cost_basis), 0)
  into v_remaining_shares, v_remaining_cost
  from public.investment_lots l
  where l.position_id = p_position_id and l.remaining_share_count > 0;
  v_gain_or_loss := p_proceeds - v_cost_basis_reduction;
  v_payload := jsonb_build_object(
    'position_id', p_position_id,
    'investment_key', v_position.investment_key,
    'investment_name', v_position.name,
    'sale_date', p_sale_date,
    'sold_share_count', p_sold_share_count,
    'proceeds', p_proceeds,
    'cost_basis_reduction', v_cost_basis_reduction,
    'gain_or_loss', v_gain_or_loss,
    'tax_treatment', v_position.tax_treatment,
    'remaining_share_count', v_remaining_shares,
    'remaining_cost_basis', v_remaining_cost,
    'lot_allocations', v_allocations,
    'bank_transaction_id', p_bank_transaction_id,
    'document_id', p_document_id,
    'document_status', p_document_status
  );
  v_lines := jsonb_build_array(
    jsonb_build_object('account', '1920', 'description', 'Sale proceeds received in bank', 'debit', p_proceeds, 'credit', 0),
    jsonb_build_object('account', '1800', 'description', 'Cost basis reduction: ' || v_position.name, 'debit', 0, 'credit', v_cost_basis_reduction)
  );
  if v_gain_or_loss > 0 then
    v_lines := v_lines || jsonb_build_array(jsonb_build_object(
      'account', '8070', 'description', 'Share sale gain: ' || v_position.name,
      'debit', 0, 'credit', v_gain_or_loss
    ));
  elsif v_gain_or_loss < 0 then
    v_lines := v_lines || jsonb_build_array(jsonb_build_object(
      'account', '8090', 'description', 'Share sale loss: ' || v_position.name,
      'debit', abs(v_gain_or_loss), 'credit', 0
    ));
  end if;

  perform set_config('talli.investment_action_write', 'on', true);
  insert into public.ledger_entries (
    id, company_id, income_year, entry_type, memo, lines, risk_flags, created_by
  ) values (
    v_entry_id, p_company_id, p_income_year, 'share_sale',
    'Share sale: ' || v_position.name, v_lines, '[]'::jsonb, v_actor_id
  );
  insert into public.holding_actions (
    id, company_id, income_year, action_type, action_date, payload, ledger_entry_id,
    bank_transaction_id, document_id, risk_level, created_by
  ) values (
    p_action_id, p_company_id, p_income_year, 'share_sale', p_sale_date, v_payload, v_entry_id,
    p_bank_transaction_id, p_document_id, 'ready', v_actor_id
  );
  insert into public.investment_lot_allocations (
    company_id, position_id, lot_id, sale_action_id,
    allocated_share_count, allocated_cost_basis, created_by
  )
  select
    p_company_id,
    p_position_id,
    (item ->> 'lot_id')::uuid,
    p_action_id,
    (item ->> 'share_count')::bigint,
    (item ->> 'cost_basis')::numeric,
    v_actor_id
  from jsonb_array_elements(v_allocations) item;

  update public.investment_positions
  set share_count = v_remaining_shares,
      cost_basis = v_remaining_cost,
      movements = movements || jsonb_build_array(jsonb_build_object(
        'action_id', p_action_id,
        'movement_type', 'sale',
        'movement_date', p_sale_date,
        'share_delta', -p_sold_share_count,
        'cost_basis_delta', -v_cost_basis_reduction,
        'amount', p_proceeds,
        'gain_or_loss', v_gain_or_loss,
        'lot_allocations', v_allocations
      )),
      updated_at = now()
  where id = p_position_id;

  if p_bank_transaction_id is not null then
    update public.bank_transactions
    set matched_action_id = p_action_id::text
    where id = p_bank_transaction_id and matched_action_id is null and matched_entry_id is null;
    get diagnostics v_row_count = row_count;
    if v_row_count <> 1 then
      raise exception 'bank_transaction_concurrent_match';
    end if;
  end if;
  insert into public.audit_events (company_id, actor_id, category, action, message)
  values (
    p_company_id, v_actor_id, 'ledger', 'share_sale_recorded',
    'Aksjesalg postert for ' || v_position.name || ' i ' || p_income_year || '.'
  );

  return jsonb_build_object(
    'action_id', p_action_id,
    'ledger_entry_id', v_entry_id,
    'position_id', p_position_id,
    'idempotent', false,
    'payload', v_payload
  );
end;
$$;

revoke all on function public.record_share_purchase_fifo(
  uuid, uuid, integer, text, text, text, text, date, bigint, numeric, text, uuid, uuid, text
) from public;
revoke all on function public.record_share_sale_fifo(
  uuid, uuid, integer, uuid, date, bigint, numeric, uuid, uuid, text
) from public;
grant execute on function public.record_share_purchase_fifo(
  uuid, uuid, integer, text, text, text, text, date, bigint, numeric, text, uuid, uuid, text
) to authenticated;
grant execute on function public.record_share_sale_fifo(
  uuid, uuid, integer, uuid, date, bigint, numeric, uuid, uuid, text
) to authenticated;
