-- BOUNDED ROLLBACK ARTIFACT: complete investments stage exit, issue #143.
-- Restores the predecessor data stores as read-only recovery copies. The three
-- slice rollback artifacts remain the rehearsed workflow cutback mechanism.

begin;

select pg_catalog.pg_advisory_xact_lock(
  pg_catalog.hashtextextended('talli:investments:stage-exit:v1', 0)
);
lock table public.holding_actions in share row exclusive mode;
lock table investments.positions in share row exclusive mode;
lock table investments.acquisition_lots in share row exclusive mode;
lock table investments.share_purchases in share row exclusive mode;
lock table investments.share_sales in share row exclusive mode;
lock table investments.share_sale_allocations in share row exclusive mode;
lock table investments.received_dividends in share row exclusive mode;

alter table public.holding_actions
  drop constraint if exists holding_actions_action_type_check;
alter table public.holding_actions
  add constraint holding_actions_action_type_check check (
    action_type in (
      'dividend_received', 'share_purchase', 'share_sale',
      'dividend_to_owner', 'shareholder_loan', 'tax_settlement'
    )
  );

insert into public.holding_actions (
  id, company_id, income_year, action_type, action_date, payload,
  ledger_entry_id, bank_transaction_id, document_id, risk_level,
  created_by, created_at
)
select
  purchase.action_id, purchase.company_id, purchase.income_year,
  'share_purchase', purchase.acquisition_date,
  pg_catalog.jsonb_build_object(
    'investment_key', purchase.investment_key,
    'investment_name', purchase.investment_name,
    'investment_kind', purchase.investment_kind,
    'tax_treatment', purchase.tax_treatment,
    'org_number', purchase.org_number,
    'share_count', purchase.share_count,
    'purchase_amount', purchase.purchase_amount,
    'acquisition_lot_id', purchase.acquisition_lot_id,
    'document_status', purchase.document_status
  ),
  purchase.accounting_entry_id, purchase.bank_transaction_id,
  purchase.document_id, 'ready', purchase.created_by, purchase.created_at
from investments.share_purchases purchase
on conflict (id) do nothing;

insert into public.holding_actions (
  id, company_id, income_year, action_type, action_date, payload,
  ledger_entry_id, bank_transaction_id, document_id, risk_level,
  created_by, created_at
)
select
  sale.action_id, sale.company_id, sale.income_year, 'share_sale',
  sale.sale_date,
  pg_catalog.jsonb_build_object(
    'investment_id', sale.position_id,
    'share_count', sale.sold_share_count,
    'proceeds', sale.proceeds,
    'cost_basis', sale.fifo_cost_basis_reduction,
    'gain_or_loss', sale.gain_or_loss,
    'remaining_share_count', sale.remaining_share_count,
    'remaining_cost_basis', sale.remaining_cost_basis,
    'document_status', sale.document_status
  ),
  sale.accounting_entry_id, sale.bank_transaction_id, sale.document_id,
  'ready', sale.created_by, sale.created_at
from investments.share_sales sale
on conflict (id) do nothing;

insert into public.holding_actions (
  id, company_id, income_year, action_type, action_date, payload,
  ledger_entry_id, bank_transaction_id, document_id, risk_level,
  created_by, created_at
)
select
  dividend.action_id, dividend.company_id, dividend.income_year,
  'dividend_received', dividend.paid_date,
  pg_catalog.jsonb_build_object(
    'linked_investment_id', dividend.position_id,
    'paying_company_name', dividend.paying_company_name,
    'declared_date', dividend.declared_date,
    'paid_date', dividend.paid_date,
    'gross_amount', dividend.gross_amount,
    'tax_treatment', dividend.tax_treatment,
    'taxable_add_back', dividend.taxable_add_back,
    'document_status', dividend.document_status
  ),
  dividend.accounting_entry_id, dividend.bank_transaction_id,
  dividend.document_id, 'ready', dividend.created_by, dividend.created_at
from investments.received_dividends dividend
on conflict (id) do nothing;

create table if not exists public.investment_positions (
  id uuid primary key default extensions.gen_random_uuid(),
  company_id uuid not null references public.companies(id) on delete cascade,
  investment_key text not null check (investment_key <> ''),
  name text not null check (name <> ''),
  kind text not null check (kind = 'norwegian_private_company'),
  tax_treatment text not null check (tax_treatment = 'fritaksmetoden'),
  org_number text check (org_number is null or org_number ~ '^[0-9]{9}$'),
  share_count numeric not null check (share_count >= 0),
  cost_basis numeric not null check (cost_basis >= 0),
  movements jsonb not null default '[]'::jsonb,
  lot_history_status text not null default 'needs_reconstruction' check (
    lot_history_status in ('complete', 'needs_reconstruction')
  ),
  created_by uuid not null references auth.users(id) on delete restrict,
  created_at timestamptz not null default pg_catalog.now(),
  updated_at timestamptz not null default pg_catalog.now(),
  unique (company_id, investment_key)
);

create table if not exists public.investment_lots (
  id uuid primary key default extensions.gen_random_uuid(),
  company_id uuid not null references public.companies(id) on delete cascade,
  position_id uuid not null references public.investment_positions(id) on delete restrict,
  acquisition_action_id uuid not null unique
    references public.holding_actions(id) on delete restrict,
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
  created_at timestamptz not null default pg_catalog.now(),
  check (remaining_share_count <> 0 or remaining_cost_basis = 0)
);

create table if not exists public.investment_lot_allocations (
  id uuid primary key default extensions.gen_random_uuid(),
  company_id uuid not null references public.companies(id) on delete cascade,
  position_id uuid not null references public.investment_positions(id) on delete restrict,
  lot_id uuid not null references public.investment_lots(id) on delete restrict,
  sale_action_id uuid not null references public.holding_actions(id) on delete restrict,
  allocated_share_count bigint not null check (allocated_share_count > 0),
  allocated_cost_basis numeric(20, 2) not null check (allocated_cost_basis >= 0),
  created_by uuid not null references auth.users(id) on delete restrict,
  created_at timestamptz not null default pg_catalog.now(),
  unique (sale_action_id, lot_id)
);

insert into public.investment_positions (
  id, company_id, investment_key, name, kind, tax_treatment, org_number,
  share_count, cost_basis, movements, lot_history_status,
  created_by, created_at, updated_at
)
select id, company_id, investment_key, name, kind, tax_treatment, org_number,
  share_count, cost_basis, movements, lot_history_status,
  created_by, created_at, updated_at
from investments.positions
on conflict (id) do nothing;

insert into public.investment_lots (
  id, company_id, position_id, acquisition_action_id, acquisition_date,
  original_share_count, remaining_share_count, original_cost_basis,
  remaining_cost_basis, created_by, created_at
)
select id, company_id, position_id, acquisition_action_id, acquisition_date,
  original_share_count, remaining_share_count, original_cost_basis,
  remaining_cost_basis, created_by, created_at
from investments.acquisition_lots
on conflict (id) do nothing;

insert into public.investment_lot_allocations (
  id, company_id, position_id, lot_id, sale_action_id,
  allocated_share_count, allocated_cost_basis, created_by, created_at
)
select id, company_id, position_id, acquisition_lot_id, sale_action_id,
  allocated_share_count, allocated_cost_basis, created_by, created_at
from investments.share_sale_allocations
on conflict (id) do nothing;

create index if not exists investment_lots_position_fifo_idx
  on public.investment_lots(position_id, acquisition_date, id);
create index if not exists investment_lots_company_idx
  on public.investment_lots(company_id);
create index if not exists investment_lot_allocations_sale_idx
  on public.investment_lot_allocations(sale_action_id);
create index if not exists investment_lot_allocations_position_idx
  on public.investment_lot_allocations(position_id);

alter table public.investment_positions enable row level security;
alter table public.investment_lots enable row level security;
alter table public.investment_lot_allocations enable row level security;
create policy "company members can read investment positions"
on public.investment_positions for select to authenticated
using (public.company_access_is_accepted_member_v1(company_id));
create policy "company members can read investment lots"
on public.investment_lots for select to authenticated
using (public.company_access_is_accepted_member_v1(company_id));
create policy "company members can read investment lot allocations"
on public.investment_lot_allocations for select to authenticated
using (public.company_access_is_accepted_member_v1(company_id));
grant select on public.investment_positions, public.investment_lots,
  public.investment_lot_allocations to authenticated;

commit;
