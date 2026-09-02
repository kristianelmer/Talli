-- Complete supported domestic investment patterns (issue #190).
-- Tax/accounting classifications and calculations enter as Python-owned facts;
-- PostgreSQL owns authorization, atomic persistence, FIFU allocation, and replay.

begin;

do $membership$
begin
  execute pg_catalog.format(
    'grant investments_store_owner, investments_executor, investments_workflow_executor, company_access_executor, ledger_store_owner, company_archive_projection_executor to %I',
    current_user
  );
end
$membership$;

select pg_catalog.set_config(
  'talli.investments_190_migration_principal', current_user, true
);

-- Fingerprints run under the private store owner with an empty search path.
-- Supabase revokes PUBLIC access to the extensions schema, so grant only the
-- exact pgcrypto boundary used by the investments functions.
grant usage on schema extensions to investments_store_owner;
grant execute on function extensions.digest(text, text)
  to investments_store_owner;

select pg_catalog.pg_advisory_xact_lock(
  pg_catalog.hashtextextended('talli:investments:supported-patterns:v1', 0)
);
lock table investments.positions in share row exclusive mode;
lock table investments.acquisition_lots in share row exclusive mode;
lock table investments.share_purchases in share row exclusive mode;
lock table investments.share_sales in share row exclusive mode;
lock table investments.share_sale_allocations in share row exclusive mode;
lock table investments.received_dividends in share row exclusive mode;

-- Preserve the exact predecessor routines so the bounded rollback can restore
-- the pre-#190 request shape without duplicating old PL/pgSQL here.
alter function investments.share_purchase_fingerprint_v1(jsonb)
  rename to rollback_190_share_purchase_fingerprint_v1;
alter function investments.get_share_purchase_replay_v1(jsonb, text)
  rename to rollback_190_get_share_purchase_replay_v1;
alter function investments.prepare_share_purchase_v1(jsonb, text)
  rename to rollback_190_prepare_share_purchase_v1;
alter function investments.complete_share_purchase_v1(jsonb, uuid, jsonb, text)
  rename to rollback_190_complete_share_purchase_v1;
alter function investments.share_sale_fingerprint_v1(jsonb)
  rename to rollback_190_share_sale_fingerprint_v1;
alter function investments.get_share_sale_replay_v1(jsonb, text)
  rename to rollback_190_get_share_sale_replay_v1;
alter function investments.prepare_share_sale_v1(jsonb, text)
  rename to rollback_190_prepare_share_sale_v1;
alter function investments.complete_share_sale_v1(jsonb, uuid, text)
  rename to rollback_190_complete_share_sale_v1;
alter function investments.received_dividend_fingerprint_v1(jsonb)
  rename to rollback_190_received_dividend_fingerprint_v1;
alter function investments.get_received_dividend_replay_v1(jsonb, text)
  rename to rollback_190_get_received_dividend_replay_v1;
alter function investments.prepare_received_dividend_v1(jsonb, text)
  rename to rollback_190_prepare_received_dividend_v1;
alter function investments.complete_received_dividend_v1(jsonb, uuid, text)
  rename to rollback_190_complete_received_dividend_v1;

alter table investments.positions drop constraint if exists positions_kind_check;
alter table investments.positions
  add column accounting_classification text,
  add column fund_equity_ratio_basis_points integer,
  add column fund_tax_statement_reference text,
  add column tax_basis numeric(20, 2);
update investments.positions
set accounting_classification = 'other_long_term',
    tax_basis = cost_basis
where accounting_classification is null or tax_basis is null;
alter table investments.positions
  alter column accounting_classification set not null,
  alter column tax_basis set not null,
  add constraint positions_kind_supported_check check (
    kind in (
      'norwegian_private_company',
      'norwegian_listed_share',
      'norwegian_equity_fund'
    )
  ),
  add constraint positions_classification_supported_check check (
    (kind = 'norwegian_private_company' and accounting_classification in (
      'subsidiary', 'associate', 'other_long_term'
    ))
    or (kind = 'norwegian_listed_share'
      and accounting_classification = 'current_listed_share')
    or (kind = 'norwegian_equity_fund'
      and accounting_classification = 'current_fund')
  ),
  add constraint positions_fund_evidence_check check (
    (
      kind = 'norwegian_equity_fund'
      and fund_equity_ratio_basis_points between 0 and 10000
      and nullif(pg_catalog.btrim(fund_tax_statement_reference), '') is not null
    ) or (
      kind <> 'norwegian_equity_fund'
      and fund_equity_ratio_basis_points is null
      and fund_tax_statement_reference is null
    )
  ),
  add constraint positions_tax_basis_nonnegative_check check (tax_basis >= 0);

alter table investments.acquisition_lots
  add column original_tax_basis numeric(20, 2),
  add column remaining_tax_basis numeric(20, 2),
  add column acquisition_year_fund_equity_ratio_basis_points integer,
  add column fund_tax_statement_reference text;
update investments.acquisition_lots
set original_tax_basis = original_cost_basis,
    remaining_tax_basis = remaining_cost_basis
where original_tax_basis is null or remaining_tax_basis is null;
alter table investments.acquisition_lots
  alter column original_tax_basis set not null,
  alter column remaining_tax_basis set not null,
  add constraint acquisition_lots_tax_basis_check check (
    original_tax_basis > 0
    and remaining_tax_basis >= 0
    and remaining_tax_basis <= original_tax_basis
    and (remaining_share_count <> 0 or remaining_tax_basis = 0)
  ),
  add constraint acquisition_lots_fund_ratio_check check (
    acquisition_year_fund_equity_ratio_basis_points is null
    or acquisition_year_fund_equity_ratio_basis_points between 0 and 10000
  );

alter table investments.share_purchases drop constraint if exists share_purchases_investment_kind_check;
alter table investments.share_purchases
  add column accounting_classification text,
  add column transaction_costs numeric(20, 2) not null default 0,
  add column capitalized_cost numeric(20, 2),
  add column fund_equity_ratio_basis_points integer,
  add column fund_tax_statement_reference text,
  add column evidence_mode text,
  add column evidence_reference text,
  add column evidence_digest text,
  add column owner_attested boolean,
  add column calculation_id text;
update investments.share_purchases purchase
set accounting_classification = position.accounting_classification,
    capitalized_cost = purchase.purchase_amount,
    fund_equity_ratio_basis_points = position.fund_equity_ratio_basis_points,
    fund_tax_statement_reference = position.fund_tax_statement_reference,
    evidence_mode = 'manual_fallback',
    evidence_reference = 'legacy-import:' || purchase.action_id::text,
    evidence_digest = pg_catalog.encode(
      extensions.digest(purchase.request_fingerprint, 'sha256'), 'hex'
    ),
    owner_attested = true,
    calculation_id = pg_catalog.encode(
      extensions.digest('legacy-calculation:' || purchase.action_id::text, 'sha256'),
      'hex'
    )
from investments.positions position
where position.id = purchase.position_id;
alter table investments.share_purchases
  alter column accounting_classification set not null,
  alter column capitalized_cost set not null,
  alter column evidence_mode set not null,
  alter column evidence_reference set not null,
  alter column evidence_digest set not null,
  alter column owner_attested set not null,
  alter column calculation_id set not null,
  add constraint share_purchases_investment_kind_supported_check check (
    investment_kind in (
      'norwegian_private_company', 'norwegian_listed_share',
      'norwegian_equity_fund'
    )
  ),
  add constraint share_purchases_costs_check check (
    transaction_costs >= 0 and capitalized_cost = purchase_amount + transaction_costs
  ),
  add constraint share_purchases_evidence_digest_check check (
    evidence_digest ~ '^[0-9a-f]{64}$' and calculation_id ~ '^[0-9a-f]{64}$'
  );

alter table investments.share_sales
  add column transaction_costs numeric(20, 2) not null default 0,
  add column net_proceeds numeric(20, 2),
  add column fifo_tax_basis_reduction numeric(20, 2),
  add column book_gain_or_loss numeric(20, 2),
  add column tax_gain_or_loss numeric(20, 2),
  add column exempt_gain numeric(20, 2),
  add column taxable_gain numeric(20, 2),
  add column non_deductible_loss numeric(20, 2),
  add column deductible_loss numeric(20, 2),
  add column remaining_tax_basis numeric(20, 2),
  add column sale_year_fund_equity_ratio_basis_points integer,
  add column fund_tax_statement_reference text,
  add column evidence_mode text,
  add column evidence_reference text,
  add column evidence_digest text,
  add column owner_attested boolean,
  add column calculation_id text;
update investments.share_sales sale
set net_proceeds = sale.proceeds,
    fifo_tax_basis_reduction = sale.fifo_cost_basis_reduction,
    book_gain_or_loss = sale.gain_or_loss,
    tax_gain_or_loss = sale.gain_or_loss,
    exempt_gain = case when sale.gain_or_loss > 0 then sale.gain_or_loss else 0 end,
    taxable_gain = 0,
    non_deductible_loss = case when sale.gain_or_loss < 0 then -sale.gain_or_loss else 0 end,
    deductible_loss = 0,
    remaining_tax_basis = sale.remaining_cost_basis,
    evidence_mode = 'manual_fallback',
    evidence_reference = 'legacy-import:' || sale.action_id::text,
    evidence_digest = pg_catalog.encode(
      extensions.digest(sale.request_fingerprint, 'sha256'), 'hex'
    ),
    owner_attested = true,
    calculation_id = pg_catalog.encode(
      extensions.digest('legacy-calculation:' || sale.action_id::text, 'sha256'),
      'hex'
    );
alter table investments.share_sales
  alter column net_proceeds set not null,
  alter column fifo_tax_basis_reduction set not null,
  alter column book_gain_or_loss set not null,
  alter column tax_gain_or_loss set not null,
  alter column exempt_gain set not null,
  alter column taxable_gain set not null,
  alter column non_deductible_loss set not null,
  alter column deductible_loss set not null,
  alter column remaining_tax_basis set not null,
  alter column evidence_mode set not null,
  alter column evidence_reference set not null,
  alter column evidence_digest set not null,
  alter column owner_attested set not null,
  alter column calculation_id set not null,
  add constraint share_sales_amounts_check check (
    transaction_costs >= 0 and transaction_costs < proceeds
    and net_proceeds = proceeds - transaction_costs
    and book_gain_or_loss = net_proceeds - fifo_cost_basis_reduction
    and tax_gain_or_loss = net_proceeds - fifo_tax_basis_reduction
    and exempt_gain >= 0 and taxable_gain >= 0
    and non_deductible_loss >= 0 and deductible_loss >= 0
    and remaining_tax_basis >= 0
  ),
  add constraint share_sales_fund_ratio_check check (
    sale_year_fund_equity_ratio_basis_points is null
    or sale_year_fund_equity_ratio_basis_points between 0 and 10000
  ),
  add constraint share_sales_digest_check check (
    evidence_digest ~ '^[0-9a-f]{64}$' and calculation_id ~ '^[0-9a-f]{64}$'
  );

alter table investments.share_sale_allocations
  add column allocated_book_cost_basis numeric(20, 2),
  add column allocated_tax_basis numeric(20, 2),
  add column allocated_net_proceeds numeric(20, 2),
  add column average_fund_equity_ratio_basis_points numeric(10, 2),
  add column tax_gain_or_loss numeric(20, 2),
  add column exempt_gain numeric(20, 2),
  add column taxable_gain numeric(20, 2),
  add column non_deductible_loss numeric(20, 2),
  add column deductible_loss numeric(20, 2);
update investments.share_sale_allocations
set allocated_book_cost_basis = allocated_cost_basis,
    allocated_tax_basis = allocated_cost_basis,
    allocated_net_proceeds = allocated_cost_basis,
    tax_gain_or_loss = 0,
    exempt_gain = 0,
    taxable_gain = 0,
    non_deductible_loss = 0,
    deductible_loss = 0;
alter table investments.share_sale_allocations
  alter column allocated_book_cost_basis set not null,
  alter column allocated_tax_basis set not null,
  alter column allocated_net_proceeds set not null,
  alter column tax_gain_or_loss set not null,
  alter column exempt_gain set not null,
  alter column taxable_gain set not null,
  alter column non_deductible_loss set not null,
  alter column deductible_loss set not null;

alter table investments.received_dividends
  alter column taxable_add_back drop not null,
  add column lawful_dividend_confirmed boolean,
  add column group_exception_claimed boolean,
  add column year_end_ownership_basis_points integer,
  add column year_end_voting_basis_points integer,
  add column group_evidence_reference text,
  add column group_exception_applied boolean,
  add column evidence_mode text,
  add column evidence_reference text,
  add column evidence_digest text,
  add column owner_attested boolean,
  add column calculation_id text;
update investments.received_dividends dividend
set lawful_dividend_confirmed = true,
    group_exception_claimed = false,
    group_exception_applied = false,
    evidence_mode = 'manual_fallback',
    evidence_reference = 'legacy-import:' || dividend.action_id::text,
    evidence_digest = pg_catalog.encode(
      extensions.digest(dividend.request_fingerprint, 'sha256'), 'hex'
    ),
    owner_attested = true,
    calculation_id = pg_catalog.encode(
      extensions.digest('legacy-calculation:' || dividend.action_id::text, 'sha256'),
      'hex'
    );
alter table investments.received_dividends
  alter column lawful_dividend_confirmed set not null,
  alter column group_exception_claimed set not null,
  alter column group_exception_applied set not null,
  alter column evidence_mode set not null,
  alter column evidence_reference set not null,
  alter column evidence_digest set not null,
  alter column owner_attested set not null,
  alter column calculation_id set not null,
  add constraint received_dividends_group_evidence_check check (
    (
      group_exception_claimed
      and year_end_ownership_basis_points > 9000
      and year_end_ownership_basis_points <= 10000
      and year_end_voting_basis_points > 9000
      and year_end_voting_basis_points <= 10000
      and nullif(pg_catalog.btrim(group_evidence_reference), '') is not null
    ) or (
      not group_exception_claimed
      and year_end_ownership_basis_points is null
      and year_end_voting_basis_points is null
      and group_evidence_reference is null
    )
  ),
  add constraint received_dividends_calculation_check check (
    (completed_at is null and taxable_add_back is null)
    or (
      completed_at is not null and taxable_add_back is not null
      and group_exception_applied = group_exception_claimed
    )
  ),
  add constraint received_dividends_digest_check check (
    evidence_digest ~ '^[0-9a-f]{64}$' and calculation_id ~ '^[0-9a-f]{64}$'
  );

-- A freshly created local database still includes the bounded #143 overlap
-- triggers because destructive contract migrations are released separately.
-- When those predecessor triggers exist, fill only the new #190 columns from
-- their already-characterized domestic-private-share facts. Production, where
-- #143 has exited, receives neither these triggers nor the helper function.
create function investments.normalize_pre_190_overlap_row_v1()
returns trigger language plpgsql security definer set search_path = ''
as $function$
declare
  v_tax_gain numeric;
begin
  if tg_table_name = 'positions' then
    new.accounting_classification := coalesce(
      new.accounting_classification, 'other_long_term'
    );
    new.tax_basis := coalesce(new.tax_basis, new.cost_basis);
  elsif tg_table_name = 'acquisition_lots' then
    new.original_tax_basis := coalesce(
      new.original_tax_basis, new.original_cost_basis
    );
    new.remaining_tax_basis := coalesce(
      new.remaining_tax_basis, new.remaining_cost_basis
    );
  elsif tg_table_name = 'share_purchases' then
    new.accounting_classification := coalesce(
      new.accounting_classification, 'other_long_term'
    );
    new.transaction_costs := coalesce(new.transaction_costs, 0);
    new.capitalized_cost := coalesce(
      new.capitalized_cost, new.purchase_amount + new.transaction_costs
    );
    new.evidence_mode := coalesce(new.evidence_mode, 'manual_fallback');
    new.evidence_reference := coalesce(
      new.evidence_reference, 'legacy-import:' || new.action_id::text
    );
    new.evidence_digest := coalesce(new.evidence_digest, pg_catalog.encode(
      extensions.digest(new.request_fingerprint, 'sha256'), 'hex'
    ));
    new.owner_attested := coalesce(new.owner_attested, true);
    new.calculation_id := coalesce(new.calculation_id, pg_catalog.encode(
      extensions.digest(
        'legacy-calculation:' || new.action_id::text, 'sha256'
      ), 'hex'
    ));
  elsif tg_table_name = 'share_sales' then
    new.transaction_costs := coalesce(new.transaction_costs, 0);
    new.net_proceeds := coalesce(
      new.net_proceeds, new.proceeds - new.transaction_costs
    );
    new.fifo_tax_basis_reduction := coalesce(
      new.fifo_tax_basis_reduction, new.fifo_cost_basis_reduction
    );
    new.book_gain_or_loss := coalesce(
      new.book_gain_or_loss,
      new.net_proceeds - new.fifo_cost_basis_reduction
    );
    v_tax_gain := new.net_proceeds - new.fifo_tax_basis_reduction;
    new.tax_gain_or_loss := coalesce(new.tax_gain_or_loss, v_tax_gain);
    new.exempt_gain := coalesce(new.exempt_gain, greatest(v_tax_gain, 0));
    new.taxable_gain := coalesce(new.taxable_gain, 0);
    new.non_deductible_loss := coalesce(
      new.non_deductible_loss, greatest(-v_tax_gain, 0)
    );
    new.deductible_loss := coalesce(new.deductible_loss, 0);
    new.remaining_tax_basis := coalesce(
      new.remaining_tax_basis, new.remaining_cost_basis
    );
    new.evidence_mode := coalesce(new.evidence_mode, 'manual_fallback');
    new.evidence_reference := coalesce(
      new.evidence_reference, 'legacy-import:' || new.action_id::text
    );
    new.evidence_digest := coalesce(new.evidence_digest, pg_catalog.encode(
      extensions.digest(new.request_fingerprint, 'sha256'), 'hex'
    ));
    new.owner_attested := coalesce(new.owner_attested, true);
    new.calculation_id := coalesce(new.calculation_id, pg_catalog.encode(
      extensions.digest(
        'legacy-calculation:' || new.action_id::text, 'sha256'
      ), 'hex'
    ));
  elsif tg_table_name = 'share_sale_allocations' then
    new.allocated_book_cost_basis := coalesce(
      new.allocated_book_cost_basis, new.allocated_cost_basis
    );
    new.allocated_tax_basis := coalesce(
      new.allocated_tax_basis, new.allocated_cost_basis
    );
    new.allocated_net_proceeds := coalesce(
      new.allocated_net_proceeds, new.allocated_cost_basis
    );
    new.tax_gain_or_loss := coalesce(new.tax_gain_or_loss, 0);
    new.exempt_gain := coalesce(new.exempt_gain, 0);
    new.taxable_gain := coalesce(new.taxable_gain, 0);
    new.non_deductible_loss := coalesce(new.non_deductible_loss, 0);
    new.deductible_loss := coalesce(new.deductible_loss, 0);
  elsif tg_table_name = 'received_dividends' then
    new.lawful_dividend_confirmed := coalesce(
      new.lawful_dividend_confirmed, true
    );
    new.group_exception_claimed := coalesce(
      new.group_exception_claimed, false
    );
    new.group_exception_applied := coalesce(
      new.group_exception_applied, false
    );
    new.evidence_mode := coalesce(new.evidence_mode, 'manual_fallback');
    new.evidence_reference := coalesce(
      new.evidence_reference, 'legacy-import:' || new.action_id::text
    );
    new.evidence_digest := coalesce(new.evidence_digest, pg_catalog.encode(
      extensions.digest(new.request_fingerprint, 'sha256'), 'hex'
    ));
    new.owner_attested := coalesce(new.owner_attested, true);
    new.calculation_id := coalesce(new.calculation_id, pg_catalog.encode(
      extensions.digest(
        'legacy-calculation:' || new.action_id::text, 'sha256'
      ), 'hex'
    ));
  end if;
  return new;
end;
$function$;
alter function investments.normalize_pre_190_overlap_row_v1()
  owner to investments_store_owner;
revoke all on function investments.normalize_pre_190_overlap_row_v1()
  from public, anon, authenticated, service_role;

do $pre_190_overlap$
begin
  if exists (
    select 1 from pg_catalog.pg_trigger
    where tgname = 'investment_positions_sync_to_investments'
      and not tgisinternal
  ) then
    execute $sql$create trigger investments_pre_190_position_defaults
      before insert or update on investments.positions
      for each row execute function investments.normalize_pre_190_overlap_row_v1()$sql$;
    execute $sql$create trigger investments_pre_190_lot_defaults
      before insert or update on investments.acquisition_lots
      for each row execute function investments.normalize_pre_190_overlap_row_v1()$sql$;
    execute $sql$create trigger investments_pre_190_purchase_defaults
      before insert or update on investments.share_purchases
      for each row execute function investments.normalize_pre_190_overlap_row_v1()$sql$;
    execute $sql$create trigger investments_pre_190_sale_defaults
      before insert or update on investments.share_sales
      for each row execute function investments.normalize_pre_190_overlap_row_v1()$sql$;
    execute $sql$create trigger investments_pre_190_allocation_defaults
      before insert or update on investments.share_sale_allocations
      for each row execute function investments.normalize_pre_190_overlap_row_v1()$sql$;
    execute $sql$create trigger investments_pre_190_dividend_defaults
      before insert or update on investments.received_dividends
      for each row execute function investments.normalize_pre_190_overlap_row_v1()$sql$;
    execute $sql$create policy investments_supported_patterns_overlap_audit_insert
      on public.audit_events for insert to investments_store_owner
      with check (
        actor_id = public.company_access_auth_uid_v1()
        and public.company_access_is_accepted_owner_v1(company_id)
      )$sql$;
  else
    execute 'drop function investments.normalize_pre_190_overlap_row_v1()';
  end if;
end
$pre_190_overlap$;

create table investments.received_fund_distributions (
  action_id uuid primary key,
  company_id uuid not null references public.companies(id) on delete cascade,
  income_year integer not null check (income_year between 2000 and 2100),
  idempotency_key text not null,
  request_fingerprint text not null check (request_fingerprint ~ '^[0-9a-f]{64}$'),
  position_id uuid not null references investments.positions(id) on delete restrict,
  accounting_entry_id uuid unique,
  fund_name text not null check (
    fund_name = pg_catalog.btrim(fund_name) and fund_name <> ''
    and pg_catalog.length(fund_name) <= 255
  ),
  entitlement_date date not null,
  paid_date date not null,
  gross_amount numeric(20, 2) not null check (gross_amount > 0),
  opening_fund_equity_ratio_basis_points integer not null check (
    opening_fund_equity_ratio_basis_points between 0 and 10000
  ),
  fund_tax_statement_reference text not null check (
    nullif(pg_catalog.btrim(fund_tax_statement_reference), '') is not null
  ),
  dividend_portion numeric(20, 2),
  interest_portion numeric(20, 2),
  taxable_add_back numeric(20, 2),
  total_taxable_income numeric(20, 2),
  bank_transaction_id uuid,
  document_id uuid,
  document_status text not null check (
    document_status in ('attached', 'missing_accepted_warning', 'not_required')
  ),
  evidence_mode text not null check (
    evidence_mode in ('linked_sources', 'manual_fallback')
  ),
  evidence_reference text not null check (
    nullif(pg_catalog.btrim(evidence_reference), '') is not null
  ),
  evidence_digest text not null check (evidence_digest ~ '^[0-9a-f]{64}$'),
  owner_attested boolean not null,
  calculation_id text,
  created_by uuid not null references auth.users(id) on delete restrict,
  created_at timestamptz not null default pg_catalog.now(),
  completed_at timestamptz,
  check (entitlement_date <= paid_date),
  check (
    (accounting_entry_id is null and completed_at is null
      and dividend_portion is null and interest_portion is null
      and taxable_add_back is null and total_taxable_income is null
      and calculation_id is null)
    or (accounting_entry_id is not null and completed_at is not null
      and dividend_portion >= 0 and interest_portion >= 0
      and dividend_portion + interest_portion = gross_amount
      and taxable_add_back >= 0 and total_taxable_income >= 0
      and calculation_id ~ '^[0-9a-f]{64}$')
  ),
  unique (created_by, company_id, idempotency_key)
);
create index investments_received_fund_distributions_company_year_idx
  on investments.received_fund_distributions(
    company_id, income_year, paid_date, action_id
  );
alter table investments.received_fund_distributions owner to investments_store_owner;
alter table investments.received_fund_distributions enable row level security;
alter table investments.received_fund_distributions force row level security;
create policy investments_received_fund_distributions_member_select
on investments.received_fund_distributions for select
to investments_executor, investments_store_owner
using (public.company_access_is_accepted_member_v1(company_id));
create policy investments_received_fund_distributions_owner_insert
on investments.received_fund_distributions for insert to investments_store_owner
with check (
  created_by = public.company_access_auth_uid_v1()
  and public.company_access_is_accepted_owner_v1(company_id)
);
create policy investments_received_fund_distributions_owner_update
on investments.received_fund_distributions for update to investments_store_owner
using (public.company_access_is_accepted_owner_v1(company_id))
with check (
  created_by = public.company_access_auth_uid_v1()
  and public.company_access_is_accepted_owner_v1(company_id)
);

create or replace function investments.share_purchase_fingerprint_v1(p_request jsonb)
returns text language sql immutable set search_path = ''
as $function$
  select pg_catalog.encode(extensions.digest(
    (p_request - array['capitalizedCost', 'evidenceDigest', 'calculationId'])::text,
    'sha256'
  ), 'hex');
$function$;

create or replace function investments.share_sale_fingerprint_v1(p_request jsonb)
returns text language sql immutable set search_path = ''
as $function$
  select pg_catalog.encode(extensions.digest(
    (p_request - array[
      'netProceeds', 'evidenceDigest', 'bookGainOrLoss', 'taxGainOrLoss',
      'exemptGain', 'taxableGain', 'nonDeductibleLoss', 'deductibleLoss',
      'calculationId', 'lotCalculations'
    ])::text,
    'sha256'
  ), 'hex');
$function$;

create or replace function investments.received_dividend_fingerprint_v1(p_request jsonb)
returns text language sql immutable set search_path = ''
as $function$
  select pg_catalog.encode(extensions.digest(
    (p_request - array[
      'taxableAddBack', 'groupExceptionApplied', 'evidenceDigest',
      'calculationId'
    ])::text,
    'sha256'
  ), 'hex');
$function$;

create or replace function investments.received_fund_distribution_fingerprint_v1(
  p_request jsonb
)
returns text language sql immutable set search_path = ''
as $function$
  select pg_catalog.encode(extensions.digest(
    (p_request - array[
      'dividendPortion', 'interestPortion', 'taxableAddBack',
      'totalTaxableIncome', 'evidenceDigest', 'calculationId'
    ])::text,
    'sha256'
  ), 'hex');
$function$;

create or replace function investments.get_share_purchase_replay_v1(
  p_request jsonb, p_verified_subject text
)
returns jsonb language plpgsql security definer set search_path = ''
as $function$
declare
  v_actor_id uuid := public.company_access_auth_uid_v1();
  v_purchase investments.share_purchases%rowtype;
begin
  if v_actor_id is null or v_actor_id is distinct from p_verified_subject::uuid
    or not public.company_access_is_accepted_owner_v1(
      (p_request ->> 'companyId')::uuid
    )
  then raise exception 'investments_forbidden'; end if;
  if not pg_catalog.pg_try_advisory_xact_lock(pg_catalog.hashtextextended(
    'investments:v1:' || v_actor_id::text || ':' ||
      (p_request ->> 'companyId') || ':share-purchase:' ||
      coalesce(p_request ->> 'idempotencyKey', ''), 0
  )) then raise exception 'investments_idempotency_in_progress'; end if;
  select purchase.* into v_purchase
  from investments.share_purchases purchase
  where purchase.action_id = (p_request ->> 'actionId')::uuid
     or (
       purchase.created_by = v_actor_id
       and purchase.company_id = (p_request ->> 'companyId')::uuid
       and purchase.idempotency_key = p_request ->> 'idempotencyKey'
     )
  order by (purchase.action_id = (p_request ->> 'actionId')::uuid) desc
  limit 1;
  if not found then return null; end if;
  if (
      not v_purchase.legacy_imported
      and v_purchase.request_fingerprint <>
        investments.share_purchase_fingerprint_v1(p_request)
    )
    or v_purchase.company_id <> (p_request ->> 'companyId')::uuid
    or v_purchase.income_year <> (p_request ->> 'incomeYear')::integer
  then raise exception 'investments_idempotency_key_reused'; end if;
  if v_purchase.accounting_entry_id is null then
    raise exception 'investments_idempotency_in_progress';
  end if;
  return pg_catalog.jsonb_build_object(
    'actionId', v_purchase.action_id,
    'positionId', v_purchase.position_id,
    'lotId', v_purchase.acquisition_lot_id,
    'accountingEntryId', v_purchase.accounting_entry_id,
    'positionCreated', v_purchase.position_created,
    'replayed', true
  );
end;
$function$;

create or replace function investments.prepare_share_purchase_v1(
  p_request jsonb, p_verified_subject text
)
returns jsonb language plpgsql security definer set search_path = ''
as $function$
declare
  v_actor_id uuid := public.company_access_auth_uid_v1();
  v_company_id uuid := (p_request ->> 'companyId')::uuid;
  v_kind text := p_request ->> 'investmentKind';
  v_classification text := p_request ->> 'accountingClassification';
  v_key text := pg_catalog.btrim(p_request ->> 'investmentKey');
  v_name text := pg_catalog.btrim(p_request ->> 'investmentName');
  v_org text := nullif(pg_catalog.btrim(p_request ->> 'orgNumber'), '');
  v_count bigint := (p_request ->> 'shareCount')::bigint;
  v_purchase numeric := (p_request ->> 'purchaseAmount')::numeric;
  v_costs numeric := (p_request ->> 'transactionCosts')::numeric;
  v_capitalized numeric := (p_request ->> 'capitalizedCost')::numeric;
  v_fund_ratio integer := nullif(
    p_request ->> 'fundEquityRatioBasisPoints', ''
  )::integer;
  v_fund_reference text := nullif(pg_catalog.btrim(
    p_request ->> 'fundTaxStatementReference'
  ), '');
  v_position investments.positions%rowtype;
  v_position_created boolean := false;
  v_lot_id uuid := extensions.gen_random_uuid();
begin
  if v_actor_id is null or v_actor_id is distinct from p_verified_subject::uuid
    or not public.company_access_is_accepted_owner_v1(v_company_id)
  then raise exception 'investments_forbidden'; end if;
  if not pg_catalog.pg_try_advisory_xact_lock(pg_catalog.hashtextextended(
    'investments:v1:' || v_actor_id::text || ':' || v_company_id::text ||
      ':share-purchase:' || coalesce(p_request ->> 'idempotencyKey', ''), 0
  )) then raise exception 'investments_idempotency_in_progress'; end if;
  if coalesce(p_request ->> 'idempotencyKey', '') !~ '^[A-Za-z0-9._:-]{16,255}$'
    or v_key = '' or v_name = '' or pg_catalog.length(v_name) > 255
    or v_count <= 0 or v_purchase <= 0 or v_costs < 0
    or v_capitalized <> v_purchase + v_costs
    or pg_catalog.round(v_purchase, 2) <> v_purchase
    or pg_catalog.round(v_costs, 2) <> v_costs
    or (p_request ->> 'acquisitionDate')::date is null
    or extract(year from (p_request ->> 'acquisitionDate')::date)::integer
      <> (p_request ->> 'incomeYear')::integer
    or p_request ->> 'taxTreatment' <> 'fritaksmetoden'
    or p_request ->> 'evidenceDigest' !~ '^[0-9a-f]{64}$'
    or p_request ->> 'calculationId' !~ '^[0-9a-f]{64}$'
    or nullif(pg_catalog.btrim(p_request ->> 'evidenceReference'), '') is null
    or not (
      (
        p_request ->> 'evidenceMode' = 'linked_sources'
        and nullif(p_request ->> 'bankTransactionId', '') is not null
        and nullif(p_request ->> 'documentId', '') is not null
        and p_request ->> 'documentStatus' = 'attached'
        and (p_request ->> 'ownerAttested')::boolean = false
      ) or (
        p_request ->> 'evidenceMode' = 'manual_fallback'
        and nullif(p_request ->> 'bankTransactionId', '') is null
        and nullif(p_request ->> 'documentId', '') is null
        and p_request ->> 'documentStatus' = 'missing_accepted_warning'
        and (p_request ->> 'ownerAttested')::boolean = true
      )
    )
    or not (
      (v_kind = 'norwegian_private_company'
        and v_classification in ('subsidiary', 'associate', 'other_long_term')
        and v_org ~ '^[0-9]{9}$' and v_fund_ratio is null
        and v_fund_reference is null)
      or (v_kind = 'norwegian_listed_share'
        and v_classification = 'current_listed_share'
        and v_key ~ '^NO[A-Z0-9]{10}$'
        and (v_org is null or v_org ~ '^[0-9]{9}$')
        and v_fund_ratio is null and v_fund_reference is null)
      or (v_kind = 'norwegian_equity_fund'
        and v_classification = 'current_fund'
        and v_key ~ '^NO[A-Z0-9]{10}$' and v_org is null
        and v_fund_ratio between 0 and 10000
        and v_fund_reference is not null)
    )
  then raise exception 'investments_invalid_input'; end if;
  if exists (
    select 1 from investments.share_purchases purchase
    where purchase.action_id = (p_request ->> 'actionId')::uuid
       or (purchase.created_by = v_actor_id and purchase.company_id = v_company_id
         and purchase.idempotency_key = p_request ->> 'idempotencyKey')
  ) then raise exception 'investments_idempotency_key_reused'; end if;

  select position.* into v_position from investments.positions position
  where position.company_id = v_company_id and position.investment_key = v_key
  for update;
  if found then
    if v_position.name <> v_name or v_position.kind <> v_kind
      or v_position.accounting_classification <> v_classification
      or v_position.tax_treatment <> p_request ->> 'taxTreatment'
      or v_position.org_number is distinct from v_org
      or v_position.fund_equity_ratio_basis_points is distinct from v_fund_ratio
      or v_position.fund_tax_statement_reference is distinct from v_fund_reference
      or v_position.lot_history_status <> 'complete'
    then raise exception 'investments_invalid_input'; end if;
  else
    insert into investments.positions (
      company_id, investment_key, name, kind, accounting_classification,
      tax_treatment, org_number, fund_equity_ratio_basis_points,
      fund_tax_statement_reference, share_count, cost_basis, tax_basis,
      movements, lot_history_status, created_by
    ) values (
      v_company_id, v_key, v_name, v_kind, v_classification,
      p_request ->> 'taxTreatment', v_org, v_fund_ratio, v_fund_reference,
      0, 0, 0, '[]'::jsonb, 'complete', v_actor_id
    ) returning * into v_position;
    v_position_created := true;
  end if;

  insert into investments.acquisition_lots (
    id, company_id, position_id, acquisition_action_id, acquisition_date,
    original_share_count, remaining_share_count,
    original_cost_basis, remaining_cost_basis,
    original_tax_basis, remaining_tax_basis,
    acquisition_year_fund_equity_ratio_basis_points,
    fund_tax_statement_reference, created_by
  ) values (
    v_lot_id, v_company_id, v_position.id,
    (p_request ->> 'actionId')::uuid,
    (p_request ->> 'acquisitionDate')::date,
    v_count, 0, v_capitalized, 0, v_capitalized, 0,
    v_fund_ratio, v_fund_reference, v_actor_id
  );
  insert into investments.share_purchases (
    action_id, company_id, income_year, idempotency_key, request_fingerprint,
    position_id, acquisition_lot_id, position_created, legacy_imported,
    investment_key, investment_name, investment_kind,
    accounting_classification, tax_treatment, acquisition_date, share_count,
    purchase_amount, transaction_costs, capitalized_cost, org_number,
    fund_equity_ratio_basis_points, fund_tax_statement_reference,
    bank_transaction_id, document_id, document_status,
    evidence_mode, evidence_reference, evidence_digest, owner_attested,
    calculation_id, created_by
  ) values (
    (p_request ->> 'actionId')::uuid, v_company_id,
    (p_request ->> 'incomeYear')::integer, p_request ->> 'idempotencyKey',
    investments.share_purchase_fingerprint_v1(p_request),
    v_position.id, v_lot_id, v_position_created, false,
    v_key, v_name, v_kind, v_classification, p_request ->> 'taxTreatment',
    (p_request ->> 'acquisitionDate')::date, v_count,
    v_purchase, v_costs, v_capitalized, v_org, v_fund_ratio, v_fund_reference,
    nullif(p_request ->> 'bankTransactionId', '')::uuid,
    nullif(p_request ->> 'documentId', '')::uuid,
    p_request ->> 'documentStatus', p_request ->> 'evidenceMode',
    pg_catalog.btrim(p_request ->> 'evidenceReference'),
    p_request ->> 'evidenceDigest', (p_request ->> 'ownerAttested')::boolean,
    p_request ->> 'calculationId', v_actor_id
  );
  return pg_catalog.jsonb_build_object(
    'positionId', v_position.id, 'lotId', v_lot_id,
    'positionCreated', v_position_created, 'investmentName', v_name,
    'accountingClassification', v_classification,
    'capitalizedCost', v_capitalized,
    'evidenceDigest', p_request ->> 'evidenceDigest',
    'calculationId', p_request ->> 'calculationId'
  );
end;
$function$;

create or replace function investments.complete_share_purchase_v1(
  p_request jsonb, p_entry_id uuid, p_prepared jsonb, p_verified_subject text
)
returns jsonb language plpgsql security definer set search_path = ''
as $function$
declare
  v_actor_id uuid := public.company_access_auth_uid_v1();
  v_purchase investments.share_purchases%rowtype;
  v_count integer;
begin
  if v_actor_id is null or v_actor_id is distinct from p_verified_subject::uuid
  then raise exception 'investments_forbidden'; end if;
  select purchase.* into v_purchase from investments.share_purchases purchase
  where purchase.action_id = (p_request ->> 'actionId')::uuid for update;
  if not found
    or v_purchase.request_fingerprint <>
      investments.share_purchase_fingerprint_v1(p_request)
    or v_purchase.position_id <> (p_prepared ->> 'positionId')::uuid
    or v_purchase.acquisition_lot_id <> (p_prepared ->> 'lotId')::uuid
    or v_purchase.capitalized_cost <> (p_prepared ->> 'capitalizedCost')::numeric
    or v_purchase.evidence_digest <> p_prepared ->> 'evidenceDigest'
    or v_purchase.calculation_id <> p_prepared ->> 'calculationId'
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
  update investments.acquisition_lots
  set remaining_share_count = original_share_count,
      remaining_cost_basis = original_cost_basis,
      remaining_tax_basis = original_tax_basis
  where id = v_purchase.acquisition_lot_id
    and remaining_share_count = 0 and remaining_cost_basis = 0
    and remaining_tax_basis = 0;
  get diagnostics v_count = row_count;
  if v_count <> 1 then raise exception 'investments_dependency_unavailable'; end if;
  update investments.positions
  set share_count = share_count + v_purchase.share_count,
      cost_basis = cost_basis + v_purchase.capitalized_cost,
      tax_basis = tax_basis + v_purchase.capitalized_cost,
      movements = movements || pg_catalog.jsonb_build_array(
        pg_catalog.jsonb_build_object(
          'action_id', v_purchase.action_id, 'movement_type', 'purchase',
          'movement_date', v_purchase.acquisition_date,
          'share_delta', v_purchase.share_count,
          'book_cost_basis_delta', v_purchase.capitalized_cost,
          'tax_basis_delta', v_purchase.capitalized_cost,
          'calculation_id', v_purchase.calculation_id,
          'evidence_digest', v_purchase.evidence_digest
        )
      ), updated_at = pg_catalog.now()
  where id = v_purchase.position_id;
  get diagnostics v_count = row_count;
  if v_count <> 1 then raise exception 'investments_dependency_unavailable'; end if;
  update investments.share_purchases
  set accounting_entry_id = p_entry_id, completed_at = pg_catalog.now()
  where action_id = v_purchase.action_id;
  insert into public.audit_events (company_id, actor_id, category, action, message)
  values (
    v_purchase.company_id, v_actor_id, 'ledger', 'share_purchase_recorded',
    'Investeringskjøp postert for ' || v_purchase.investment_name || ' i ' ||
      v_purchase.income_year || '.'
  );
  return pg_catalog.jsonb_build_object(
    'actionId', v_purchase.action_id, 'positionId', v_purchase.position_id,
    'lotId', v_purchase.acquisition_lot_id, 'accountingEntryId', p_entry_id,
    'positionCreated', v_purchase.position_created, 'replayed', false
  );
end;
$function$;

create or replace function investments.get_share_sale_replay_v1(
  p_request jsonb, p_verified_subject text
)
returns jsonb language plpgsql security definer set search_path = ''
as $function$
declare
  v_actor_id uuid := public.company_access_auth_uid_v1();
  v_sale investments.share_sales%rowtype;
begin
  if v_actor_id is null or v_actor_id is distinct from p_verified_subject::uuid
    or not public.company_access_is_accepted_owner_v1(
      (p_request ->> 'companyId')::uuid
    )
  then raise exception 'investments_forbidden'; end if;
  if not pg_catalog.pg_try_advisory_xact_lock(pg_catalog.hashtextextended(
    'investments:v1:' || v_actor_id::text || ':' ||
      (p_request ->> 'companyId') || ':share-sale:' ||
      coalesce(p_request ->> 'idempotencyKey', ''), 0
  )) then raise exception 'investments_idempotency_in_progress'; end if;
  select sale.* into v_sale from investments.share_sales sale
  where sale.action_id = (p_request ->> 'actionId')::uuid
     or (sale.created_by = v_actor_id
       and sale.company_id = (p_request ->> 'companyId')::uuid
       and sale.idempotency_key = p_request ->> 'idempotencyKey')
  order by (sale.action_id = (p_request ->> 'actionId')::uuid) desc
  limit 1;
  if not found then return null; end if;
  if (not v_sale.legacy_imported and v_sale.request_fingerprint <>
      investments.share_sale_fingerprint_v1(p_request))
    or v_sale.company_id <> (p_request ->> 'companyId')::uuid
    or v_sale.income_year <> (p_request ->> 'incomeYear')::integer
  then raise exception 'investments_idempotency_key_reused'; end if;
  if v_sale.accounting_entry_id is null then
    raise exception 'investments_idempotency_in_progress';
  end if;
  return pg_catalog.jsonb_build_object(
    'actionId', v_sale.action_id, 'positionId', v_sale.position_id,
    'accountingEntryId', v_sale.accounting_entry_id, 'replayed', true
  );
end;
$function$;

create or replace function investments.prepare_share_sale_v1(
  p_request jsonb, p_verified_subject text
)
returns jsonb language plpgsql security definer set search_path = ''
as $function$
declare
  v_actor_id uuid := public.company_access_auth_uid_v1();
  v_company_id uuid := (p_request ->> 'companyId')::uuid;
  v_position investments.positions%rowtype;
  v_lot investments.acquisition_lots%rowtype;
  v_sold bigint := (p_request ->> 'soldShareCount')::bigint;
  v_proceeds numeric := (p_request ->> 'proceeds')::numeric;
  v_costs numeric := (p_request ->> 'transactionCosts')::numeric;
  v_net numeric := (p_request ->> 'netProceeds')::numeric;
  v_sale_ratio integer := nullif(
    p_request ->> 'saleYearFundEquityRatioBasisPoints', ''
  )::integer;
  v_fund_reference text := nullif(pg_catalog.btrim(
    p_request ->> 'fundTaxStatementReference'
  ), '');
  v_available_shares bigint;
  v_available_book numeric;
  v_available_tax numeric;
  v_left bigint;
  v_allocated_shares bigint;
  v_allocated_book numeric;
  v_allocated_tax numeric;
  v_book_cost numeric := 0;
  v_tax_basis numeric := 0;
  v_order integer := 0;
  v_lot_facts jsonb := '[]'::jsonb;
begin
  if v_actor_id is null or v_actor_id is distinct from p_verified_subject::uuid
    or not public.company_access_is_accepted_owner_v1(v_company_id)
  then raise exception 'investments_forbidden'; end if;
  if not pg_catalog.pg_try_advisory_xact_lock(pg_catalog.hashtextextended(
    'investments:v1:' || v_actor_id::text || ':' || v_company_id::text ||
      ':share-sale:' || coalesce(p_request ->> 'idempotencyKey', ''), 0
  )) then raise exception 'investments_idempotency_in_progress'; end if;
  if coalesce(p_request ->> 'idempotencyKey', '') !~ '^[A-Za-z0-9._:-]{16,255}$'
    or v_sold <= 0 or v_proceeds <= 0 or v_costs < 0 or v_costs >= v_proceeds
    or v_net <> v_proceeds - v_costs
    or pg_catalog.round(v_proceeds, 2) <> v_proceeds
    or pg_catalog.round(v_costs, 2) <> v_costs
    or extract(year from (p_request ->> 'saleDate')::date)::integer
      <> (p_request ->> 'incomeYear')::integer
    or p_request ->> 'evidenceDigest' !~ '^[0-9a-f]{64}$'
    or nullif(pg_catalog.btrim(p_request ->> 'evidenceReference'), '') is null
    or not (
      (p_request ->> 'evidenceMode' = 'linked_sources'
        and nullif(p_request ->> 'bankTransactionId', '') is not null
        and nullif(p_request ->> 'documentId', '') is not null
        and p_request ->> 'documentStatus' = 'attached'
        and (p_request ->> 'ownerAttested')::boolean = false)
      or (p_request ->> 'evidenceMode' = 'manual_fallback'
        and nullif(p_request ->> 'bankTransactionId', '') is null
        and nullif(p_request ->> 'documentId', '') is null
        and p_request ->> 'documentStatus' = 'missing_accepted_warning'
        and (p_request ->> 'ownerAttested')::boolean = true)
    )
  then raise exception 'investments_invalid_input'; end if;
  if exists (
    select 1 from investments.share_sales sale
    where sale.action_id = (p_request ->> 'actionId')::uuid
       or (sale.created_by = v_actor_id and sale.company_id = v_company_id
         and sale.idempotency_key = p_request ->> 'idempotencyKey')
  ) then raise exception 'investments_idempotency_key_reused'; end if;

  select position.* into v_position from investments.positions position
  where position.id = (p_request ->> 'positionId')::uuid for update;
  if not found or v_position.company_id <> v_company_id
    or v_position.lot_history_status <> 'complete'
    or (
      v_position.kind = 'norwegian_equity_fund'
      and (v_sale_ratio is null or v_sale_ratio not between 0 and 10000
        or v_fund_reference is null)
    )
    or (
      v_position.kind <> 'norwegian_equity_fund'
      and (v_sale_ratio is not null or v_fund_reference is not null)
    )
  then raise exception 'investments_invalid_input'; end if;
  perform 1 from investments.acquisition_lots lot
  where lot.position_id = v_position.id and lot.remaining_share_count > 0
  order by lot.acquisition_date, lot.id for update;
  select coalesce(pg_catalog.sum(lot.remaining_share_count), 0),
    coalesce(pg_catalog.sum(lot.remaining_cost_basis), 0),
    coalesce(pg_catalog.sum(lot.remaining_tax_basis), 0)
  into v_available_shares, v_available_book, v_available_tax
  from investments.acquisition_lots lot
  where lot.position_id = v_position.id and lot.remaining_share_count > 0;
  if v_available_shares = 0 or v_sold > v_available_shares
    or v_available_shares <> v_position.share_count
    or v_available_book <> v_position.cost_basis
    or v_available_tax <> v_position.tax_basis
  then raise exception 'investments_invalid_input'; end if;

  v_left := v_sold;
  for v_lot in
    select lot.* from investments.acquisition_lots lot
    where lot.position_id = v_position.id and lot.remaining_share_count > 0
    order by lot.acquisition_date, lot.id for update
  loop
    exit when v_left = 0;
    v_allocated_shares := case when v_left < v_lot.remaining_share_count
      then v_left else v_lot.remaining_share_count end;
    v_allocated_book := case
      when v_allocated_shares = v_lot.remaining_share_count
        then v_lot.remaining_cost_basis
      else pg_catalog.round(v_lot.remaining_cost_basis * v_allocated_shares /
        v_lot.remaining_share_count, 2) end;
    v_allocated_tax := case
      when v_allocated_shares = v_lot.remaining_share_count
        then v_lot.remaining_tax_basis
      else pg_catalog.round(v_lot.remaining_tax_basis * v_allocated_shares /
        v_lot.remaining_share_count, 2) end;
    v_order := v_order + 1;
    v_lot_facts := v_lot_facts || pg_catalog.jsonb_build_array(
      pg_catalog.jsonb_build_object(
        'lotId', v_lot.id, 'allocationOrder', v_order,
        'acquisitionDate', v_lot.acquisition_date,
        'allocatedShareCount', v_allocated_shares,
        'allocatedBookCostBasis', v_allocated_book,
        'allocatedTaxBasis', v_allocated_tax,
        'acquisitionYearFundEquityRatioBasisPoints',
          v_lot.acquisition_year_fund_equity_ratio_basis_points
      )
    );
    v_book_cost := v_book_cost + v_allocated_book;
    v_tax_basis := v_tax_basis + v_allocated_tax;
    v_left := v_left - v_allocated_shares;
  end loop;
  if v_left <> 0 then raise exception 'investments_dependency_unavailable'; end if;
  insert into investments.share_sales (
    action_id, company_id, income_year, idempotency_key, request_fingerprint,
    position_id, legacy_imported, sale_date, sold_share_count,
    proceeds, transaction_costs, net_proceeds,
    fifo_cost_basis_reduction, fifo_tax_basis_reduction,
    gain_or_loss, book_gain_or_loss, tax_gain_or_loss,
    exempt_gain, taxable_gain, non_deductible_loss, deductible_loss,
    remaining_share_count, remaining_cost_basis, remaining_tax_basis,
    sale_year_fund_equity_ratio_basis_points, fund_tax_statement_reference,
    bank_transaction_id, document_id, document_status,
    evidence_mode, evidence_reference, evidence_digest, owner_attested,
    calculation_id, created_by
  ) values (
    (p_request ->> 'actionId')::uuid, v_company_id,
    (p_request ->> 'incomeYear')::integer, p_request ->> 'idempotencyKey',
    investments.share_sale_fingerprint_v1(p_request), v_position.id, false,
    (p_request ->> 'saleDate')::date, v_sold, v_proceeds, v_costs, v_net,
    v_book_cost, v_tax_basis, v_net - v_book_cost,
    v_net - v_book_cost, v_net - v_tax_basis, 0, 0, 0, 0,
    v_available_shares - v_sold, v_available_book - v_book_cost,
    v_available_tax - v_tax_basis,
    v_sale_ratio, v_fund_reference,
    nullif(p_request ->> 'bankTransactionId', '')::uuid,
    nullif(p_request ->> 'documentId', '')::uuid,
    p_request ->> 'documentStatus', p_request ->> 'evidenceMode',
    pg_catalog.btrim(p_request ->> 'evidenceReference'),
    p_request ->> 'evidenceDigest', (p_request ->> 'ownerAttested')::boolean,
    pg_catalog.repeat('0', 64), v_actor_id
  );
  return pg_catalog.jsonb_build_object(
    'positionId', v_position.id, 'investmentName', v_position.name,
    'investmentKind', v_position.kind,
    'accountingClassification', v_position.accounting_classification,
    'fifoBookCostBasisReduction', v_book_cost,
    'fifoTaxBasisReduction', v_tax_basis, 'lotFacts', v_lot_facts
  );
end;
$function$;

create or replace function investments.complete_share_sale_v1(
  p_request jsonb, p_entry_id uuid, p_verified_subject text
)
returns jsonb language plpgsql security definer set search_path = ''
as $function$
declare
  v_actor_id uuid := public.company_access_auth_uid_v1();
  v_sale investments.share_sales%rowtype;
  v_position investments.positions%rowtype;
  v_lot investments.acquisition_lots%rowtype;
  v_calc jsonb;
  v_left bigint;
  v_allocated_shares bigint;
  v_allocated_book numeric;
  v_allocated_tax numeric;
  v_book_cost numeric := 0;
  v_tax_basis numeric := 0;
  v_remaining_shares bigint;
  v_remaining_book numeric;
  v_remaining_tax numeric;
  v_order integer := 0;
  v_count integer;
begin
  if v_actor_id is null or v_actor_id is distinct from p_verified_subject::uuid
  then raise exception 'investments_forbidden'; end if;
  select sale.* into v_sale from investments.share_sales sale
  where sale.action_id = (p_request ->> 'actionId')::uuid for update;
  if not found or v_sale.request_fingerprint <>
      investments.share_sale_fingerprint_v1(p_request)
    or p_request ->> 'calculationId' !~ '^[0-9a-f]{64}$'
    or p_request ->> 'evidenceDigest' <> v_sale.evidence_digest
    or (p_request ->> 'bookGainOrLoss')::numeric <>
      v_sale.net_proceeds - v_sale.fifo_cost_basis_reduction
    or (p_request ->> 'taxGainOrLoss')::numeric <>
      v_sale.net_proceeds - v_sale.fifo_tax_basis_reduction
    or not ledger.investment_sale_entry_matches_v1(
      p_entry_id, v_sale.company_id, v_sale.action_id
    )
  then raise exception 'investments_dependency_unavailable'; end if;
  if v_sale.accounting_entry_id is not null then
    if v_sale.accounting_entry_id <> p_entry_id then
      raise exception 'investments_idempotency_key_reused'; end if;
    return pg_catalog.jsonb_build_object(
      'actionId', v_sale.action_id, 'positionId', v_sale.position_id,
      'accountingEntryId', v_sale.accounting_entry_id, 'replayed', true
    );
  end if;
  if (
      (p_request ->> 'taxGainOrLoss')::numeric >= 0
      and ((p_request ->> 'exemptGain')::numeric
        + (p_request ->> 'taxableGain')::numeric <>
          (p_request ->> 'taxGainOrLoss')::numeric
        or (p_request ->> 'nonDeductibleLoss')::numeric <> 0
        or (p_request ->> 'deductibleLoss')::numeric <> 0)
    ) or (
      (p_request ->> 'taxGainOrLoss')::numeric < 0
      and ((p_request ->> 'nonDeductibleLoss')::numeric
        + (p_request ->> 'deductibleLoss')::numeric <>
          -(p_request ->> 'taxGainOrLoss')::numeric
        or (p_request ->> 'exemptGain')::numeric <> 0
        or (p_request ->> 'taxableGain')::numeric <> 0)
    )
  then raise exception 'investments_dependency_unavailable'; end if;
  select position.* into v_position from investments.positions position
  where position.id = v_sale.position_id for update;
  if not found or v_position.share_count < v_sale.sold_share_count
    or v_position.cost_basis < v_sale.fifo_cost_basis_reduction
    or v_position.tax_basis < v_sale.fifo_tax_basis_reduction
  then raise exception 'investments_dependency_unavailable'; end if;

  v_left := v_sale.sold_share_count;
  for v_lot in
    select lot.* from investments.acquisition_lots lot
    where lot.position_id = v_sale.position_id and lot.remaining_share_count > 0
    order by lot.acquisition_date, lot.id for update
  loop
    exit when v_left = 0;
    v_allocated_shares := case when v_left < v_lot.remaining_share_count
      then v_left else v_lot.remaining_share_count end;
    v_allocated_book := case when v_allocated_shares = v_lot.remaining_share_count
      then v_lot.remaining_cost_basis else pg_catalog.round(
        v_lot.remaining_cost_basis * v_allocated_shares /
          v_lot.remaining_share_count, 2) end;
    v_allocated_tax := case when v_allocated_shares = v_lot.remaining_share_count
      then v_lot.remaining_tax_basis else pg_catalog.round(
        v_lot.remaining_tax_basis * v_allocated_shares /
          v_lot.remaining_share_count, 2) end;
    v_order := v_order + 1;
    select value into v_calc
    from pg_catalog.jsonb_array_elements(p_request -> 'lotCalculations') value
    where (value ->> 'lotId')::uuid = v_lot.id
      and (value ->> 'allocationOrder')::integer = v_order;
    if not found
      or (v_calc ->> 'taxGainOrLoss')::numeric <>
        (v_calc ->> 'allocatedNetProceeds')::numeric - v_allocated_tax
      or (v_position.kind = 'norwegian_equity_fund'
        and nullif(v_calc ->> 'averageFundEquityRatioBasisPoints', '') is null)
      or (v_position.kind <> 'norwegian_equity_fund'
        and nullif(v_calc ->> 'averageFundEquityRatioBasisPoints', '') is not null)
    then raise exception 'investments_dependency_unavailable'; end if;
    insert into investments.share_sale_allocations (
      sale_action_id, company_id, position_id, acquisition_lot_id,
      allocation_order, acquisition_date, allocated_share_count,
      allocated_cost_basis, allocated_book_cost_basis, allocated_tax_basis,
      allocated_net_proceeds, average_fund_equity_ratio_basis_points,
      tax_gain_or_loss, exempt_gain, taxable_gain,
      non_deductible_loss, deductible_loss, created_by
    ) values (
      v_sale.action_id, v_sale.company_id, v_sale.position_id, v_lot.id,
      v_order, v_lot.acquisition_date, v_allocated_shares,
      v_allocated_book, v_allocated_book, v_allocated_tax,
      (v_calc ->> 'allocatedNetProceeds')::numeric,
      nullif(v_calc ->> 'averageFundEquityRatioBasisPoints', '')::numeric,
      (v_calc ->> 'taxGainOrLoss')::numeric,
      (v_calc ->> 'exemptGain')::numeric,
      (v_calc ->> 'taxableGain')::numeric,
      (v_calc ->> 'nonDeductibleLoss')::numeric,
      (v_calc ->> 'deductibleLoss')::numeric, v_actor_id
    );
    update investments.acquisition_lots
    set remaining_share_count = remaining_share_count - v_allocated_shares,
        remaining_cost_basis = remaining_cost_basis - v_allocated_book,
        remaining_tax_basis = remaining_tax_basis - v_allocated_tax
    where id = v_lot.id and remaining_share_count = v_lot.remaining_share_count
      and remaining_cost_basis = v_lot.remaining_cost_basis
      and remaining_tax_basis = v_lot.remaining_tax_basis;
    get diagnostics v_count = row_count;
    if v_count <> 1 then raise exception 'investments_dependency_unavailable'; end if;
    v_book_cost := v_book_cost + v_allocated_book;
    v_tax_basis := v_tax_basis + v_allocated_tax;
    v_left := v_left - v_allocated_shares;
  end loop;
  if v_left <> 0 or v_book_cost <> v_sale.fifo_cost_basis_reduction
    or v_tax_basis <> v_sale.fifo_tax_basis_reduction
    or (select count(*) from investments.share_sale_allocations allocation
      where allocation.sale_action_id = v_sale.action_id) <>
      pg_catalog.jsonb_array_length(p_request -> 'lotCalculations')
    or (select coalesce(pg_catalog.sum(allocation.allocated_net_proceeds), 0)
      from investments.share_sale_allocations allocation
      where allocation.sale_action_id = v_sale.action_id) <> v_sale.net_proceeds
    or (select coalesce(pg_catalog.sum(allocation.tax_gain_or_loss), 0)
      from investments.share_sale_allocations allocation
      where allocation.sale_action_id = v_sale.action_id) <>
      (p_request ->> 'taxGainOrLoss')::numeric
    or (select coalesce(pg_catalog.sum(allocation.exempt_gain), 0)
      from investments.share_sale_allocations allocation
      where allocation.sale_action_id = v_sale.action_id) <>
      (p_request ->> 'exemptGain')::numeric
    or (select coalesce(pg_catalog.sum(allocation.taxable_gain), 0)
      from investments.share_sale_allocations allocation
      where allocation.sale_action_id = v_sale.action_id) <>
      (p_request ->> 'taxableGain')::numeric
    or (select coalesce(pg_catalog.sum(allocation.non_deductible_loss), 0)
      from investments.share_sale_allocations allocation
      where allocation.sale_action_id = v_sale.action_id) <>
      (p_request ->> 'nonDeductibleLoss')::numeric
    or (select coalesce(pg_catalog.sum(allocation.deductible_loss), 0)
      from investments.share_sale_allocations allocation
      where allocation.sale_action_id = v_sale.action_id) <>
      (p_request ->> 'deductibleLoss')::numeric
  then raise exception 'investments_dependency_unavailable'; end if;
  select coalesce(pg_catalog.sum(lot.remaining_share_count), 0),
    coalesce(pg_catalog.sum(lot.remaining_cost_basis), 0),
    coalesce(pg_catalog.sum(lot.remaining_tax_basis), 0)
  into v_remaining_shares, v_remaining_book, v_remaining_tax
  from investments.acquisition_lots lot
  where lot.position_id = v_sale.position_id and lot.remaining_share_count > 0;
  update investments.positions
  set share_count = v_remaining_shares, cost_basis = v_remaining_book,
      tax_basis = v_remaining_tax,
      movements = movements || pg_catalog.jsonb_build_array(
        pg_catalog.jsonb_build_object(
          'action_id', v_sale.action_id, 'movement_type', 'sale',
          'movement_date', v_sale.sale_date,
          'share_delta', -v_sale.sold_share_count,
          'book_cost_basis_delta', -v_sale.fifo_cost_basis_reduction,
          'tax_basis_delta', -v_sale.fifo_tax_basis_reduction,
          'book_gain_or_loss', p_request ->> 'bookGainOrLoss',
          'tax_gain_or_loss', p_request ->> 'taxGainOrLoss',
          'calculation_id', p_request ->> 'calculationId',
          'evidence_digest', p_request ->> 'evidenceDigest'
        )
      ), updated_at = pg_catalog.now()
  where id = v_sale.position_id;
  update investments.share_sales
  set accounting_entry_id = p_entry_id, completed_at = pg_catalog.now(),
      book_gain_or_loss = (p_request ->> 'bookGainOrLoss')::numeric,
      gain_or_loss = (p_request ->> 'bookGainOrLoss')::numeric,
      tax_gain_or_loss = (p_request ->> 'taxGainOrLoss')::numeric,
      exempt_gain = (p_request ->> 'exemptGain')::numeric,
      taxable_gain = (p_request ->> 'taxableGain')::numeric,
      non_deductible_loss = (p_request ->> 'nonDeductibleLoss')::numeric,
      deductible_loss = (p_request ->> 'deductibleLoss')::numeric,
      remaining_tax_basis = v_remaining_tax,
      calculation_id = p_request ->> 'calculationId'
  where action_id = v_sale.action_id;
  insert into public.audit_events (company_id, actor_id, category, action, message)
  values (
    v_sale.company_id, v_actor_id, 'ledger', 'share_sale_recorded',
    'Investeringssalg postert for ' || v_position.name || ' i ' ||
      v_sale.income_year || '.'
  );
  return pg_catalog.jsonb_build_object(
    'actionId', v_sale.action_id, 'positionId', v_sale.position_id,
    'accountingEntryId', p_entry_id, 'replayed', false
  );
end;
$function$;

create or replace function investments.get_received_dividend_replay_v1(
  p_request jsonb, p_verified_subject text
)
returns jsonb language plpgsql security definer set search_path = ''
as $function$
declare
  v_actor_id uuid := public.company_access_auth_uid_v1();
  v_dividend investments.received_dividends%rowtype;
begin
  if v_actor_id is null or v_actor_id is distinct from p_verified_subject::uuid
    or not public.company_access_is_accepted_owner_v1(
      (p_request ->> 'companyId')::uuid
    )
  then raise exception 'investments_forbidden'; end if;
  if not pg_catalog.pg_try_advisory_xact_lock(pg_catalog.hashtextextended(
    'investments:v1:' || v_actor_id::text || ':' ||
      (p_request ->> 'companyId') || ':received-dividend:' ||
      coalesce(p_request ->> 'idempotencyKey', ''), 0
  )) then raise exception 'investments_idempotency_in_progress'; end if;
  select dividend.* into v_dividend from investments.received_dividends dividend
  where dividend.action_id = (p_request ->> 'actionId')::uuid
     or (dividend.created_by = v_actor_id
       and dividend.company_id = (p_request ->> 'companyId')::uuid
       and dividend.idempotency_key = p_request ->> 'idempotencyKey')
  order by (dividend.action_id = (p_request ->> 'actionId')::uuid) desc
  limit 1;
  if not found then return null; end if;
  if (not v_dividend.legacy_imported and v_dividend.request_fingerprint <>
      investments.received_dividend_fingerprint_v1(p_request))
    or v_dividend.company_id <> (p_request ->> 'companyId')::uuid
    or v_dividend.income_year <> (p_request ->> 'incomeYear')::integer
  then raise exception 'investments_idempotency_key_reused'; end if;
  if v_dividend.accounting_entry_id is null then
    raise exception 'investments_idempotency_in_progress';
  end if;
  return pg_catalog.jsonb_build_object(
    'actionId', v_dividend.action_id, 'positionId', v_dividend.position_id,
    'accountingEntryId', v_dividend.accounting_entry_id,
    'taxableAddBack', v_dividend.taxable_add_back, 'replayed', true
  );
end;
$function$;

create or replace function investments.prepare_received_dividend_v1(
  p_request jsonb, p_verified_subject text
)
returns jsonb language plpgsql security definer set search_path = ''
as $function$
declare
  v_actor_id uuid := public.company_access_auth_uid_v1();
  v_company_id uuid := (p_request ->> 'companyId')::uuid;
  v_position investments.positions%rowtype;
  v_name text := pg_catalog.btrim(p_request ->> 'payingCompanyName');
  v_group boolean := (p_request ->> 'groupExceptionClaimed')::boolean;
  v_ownership integer := nullif(
    p_request ->> 'yearEndOwnershipBasisPoints', ''
  )::integer;
  v_votes integer := nullif(
    p_request ->> 'yearEndVotingBasisPoints', ''
  )::integer;
  v_group_reference text := nullif(pg_catalog.btrim(
    p_request ->> 'groupEvidenceReference'
  ), '');
begin
  if v_actor_id is null or v_actor_id is distinct from p_verified_subject::uuid
    or not public.company_access_is_accepted_owner_v1(v_company_id)
  then raise exception 'investments_forbidden'; end if;
  if not pg_catalog.pg_try_advisory_xact_lock(pg_catalog.hashtextextended(
    'investments:v1:' || v_actor_id::text || ':' || v_company_id::text ||
      ':received-dividend:' || coalesce(p_request ->> 'idempotencyKey', ''), 0
  )) then raise exception 'investments_idempotency_in_progress'; end if;
  if coalesce(p_request ->> 'idempotencyKey', '') !~ '^[A-Za-z0-9._:-]{16,255}$'
    or v_name = '' or pg_catalog.length(v_name) > 255
    or (p_request ->> 'grossAmount')::numeric <= 0
    or pg_catalog.round((p_request ->> 'grossAmount')::numeric, 2) <>
      (p_request ->> 'grossAmount')::numeric
    or (p_request ->> 'declaredDate')::date > (p_request ->> 'paidDate')::date
    or extract(year from (p_request ->> 'declaredDate')::date)::integer <>
      (p_request ->> 'incomeYear')::integer
    or extract(year from (p_request ->> 'paidDate')::date)::integer <>
      (p_request ->> 'incomeYear')::integer
    or p_request ->> 'taxTreatment' <> 'fritaksmetoden'
    or (p_request ->> 'lawfulDividendConfirmed')::boolean is not true
    or not (
      (v_group and v_ownership > 9000 and v_ownership <= 10000
        and v_votes > 9000 and v_votes <= 10000
        and v_group_reference is not null)
      or (not v_group and v_ownership is null and v_votes is null
        and v_group_reference is null)
    )
    or p_request ->> 'evidenceDigest' !~ '^[0-9a-f]{64}$'
    or nullif(pg_catalog.btrim(p_request ->> 'evidenceReference'), '') is null
    or not (
      (p_request ->> 'evidenceMode' = 'linked_sources'
        and nullif(p_request ->> 'bankTransactionId', '') is not null
        and nullif(p_request ->> 'documentId', '') is not null
        and p_request ->> 'documentStatus' = 'attached'
        and (p_request ->> 'ownerAttested')::boolean = false)
      or (p_request ->> 'evidenceMode' = 'manual_fallback'
        and nullif(p_request ->> 'bankTransactionId', '') is null
        and nullif(p_request ->> 'documentId', '') is null
        and p_request ->> 'documentStatus' = 'missing_accepted_warning'
        and (p_request ->> 'ownerAttested')::boolean = true)
    )
  then raise exception 'investments_invalid_input'; end if;
  if exists (
    select 1 from investments.received_dividends dividend
    where dividend.action_id = (p_request ->> 'actionId')::uuid
       or (dividend.created_by = v_actor_id and dividend.company_id = v_company_id
         and dividend.idempotency_key = p_request ->> 'idempotencyKey')
  ) then raise exception 'investments_idempotency_key_reused'; end if;
  select position.* into v_position from investments.positions position
  where position.id = (p_request ->> 'positionId')::uuid for update;
  if not found or v_position.company_id <> v_company_id
    or v_position.kind not in (
      'norwegian_private_company', 'norwegian_listed_share'
    )
  then raise exception 'investments_invalid_input'; end if;
  insert into investments.received_dividends (
    action_id, company_id, income_year, idempotency_key, request_fingerprint,
    position_id, legacy_imported, paying_company_name, declared_date, paid_date,
    gross_amount, tax_treatment, taxable_add_back,
    lawful_dividend_confirmed, group_exception_claimed,
    year_end_ownership_basis_points, year_end_voting_basis_points,
    group_evidence_reference, group_exception_applied,
    bank_transaction_id, document_id, document_status,
    evidence_mode, evidence_reference, evidence_digest, owner_attested,
    calculation_id, created_by
  ) values (
    (p_request ->> 'actionId')::uuid, v_company_id,
    (p_request ->> 'incomeYear')::integer, p_request ->> 'idempotencyKey',
    investments.received_dividend_fingerprint_v1(p_request),
    v_position.id, false, v_name,
    (p_request ->> 'declaredDate')::date,
    (p_request ->> 'paidDate')::date,
    (p_request ->> 'grossAmount')::numeric, p_request ->> 'taxTreatment', null,
    true, v_group, v_ownership, v_votes, v_group_reference, v_group,
    nullif(p_request ->> 'bankTransactionId', '')::uuid,
    nullif(p_request ->> 'documentId', '')::uuid,
    p_request ->> 'documentStatus', p_request ->> 'evidenceMode',
    pg_catalog.btrim(p_request ->> 'evidenceReference'),
    p_request ->> 'evidenceDigest', (p_request ->> 'ownerAttested')::boolean,
    pg_catalog.repeat('0', 64), v_actor_id
  );
  return pg_catalog.jsonb_build_object(
    'positionId', v_position.id, 'investmentName', v_position.name,
    'investmentKind', v_position.kind
  );
end;
$function$;

create or replace function investments.complete_received_dividend_v1(
  p_request jsonb, p_entry_id uuid, p_verified_subject text
)
returns jsonb language plpgsql security definer set search_path = ''
as $function$
declare
  v_actor_id uuid := public.company_access_auth_uid_v1();
  v_dividend investments.received_dividends%rowtype;
begin
  if v_actor_id is null or v_actor_id is distinct from p_verified_subject::uuid
  then raise exception 'investments_forbidden'; end if;
  select dividend.* into v_dividend from investments.received_dividends dividend
  where dividend.action_id = (p_request ->> 'actionId')::uuid for update;
  if not found or v_dividend.request_fingerprint <>
      investments.received_dividend_fingerprint_v1(p_request)
    or p_request ->> 'calculationId' !~ '^[0-9a-f]{64}$'
    or p_request ->> 'evidenceDigest' <> v_dividend.evidence_digest
    or (p_request ->> 'groupExceptionApplied')::boolean <>
      v_dividend.group_exception_claimed
    or (p_request ->> 'taxableAddBack')::numeric < 0
    or not ledger.investment_dividend_entry_matches_v1(
      p_entry_id, v_dividend.company_id, v_dividend.action_id
    )
  then raise exception 'investments_dependency_unavailable'; end if;
  if v_dividend.accounting_entry_id is not null then
    if v_dividend.accounting_entry_id <> p_entry_id then
      raise exception 'investments_idempotency_key_reused'; end if;
    return pg_catalog.jsonb_build_object(
      'actionId', v_dividend.action_id, 'positionId', v_dividend.position_id,
      'accountingEntryId', v_dividend.accounting_entry_id,
      'taxableAddBack', v_dividend.taxable_add_back, 'replayed', true
    );
  end if;
  update investments.received_dividends
  set accounting_entry_id = p_entry_id, completed_at = pg_catalog.now(),
      taxable_add_back = (p_request ->> 'taxableAddBack')::numeric,
      group_exception_applied = (p_request ->> 'groupExceptionApplied')::boolean,
      calculation_id = p_request ->> 'calculationId'
  where action_id = v_dividend.action_id;
  insert into public.audit_events (company_id, actor_id, category, action, message)
  values (
    v_dividend.company_id, v_actor_id, 'ledger',
    'dividend_received_recorded',
    'Mottatt utbytte postert fra ' || v_dividend.paying_company_name ||
      ' for ' || v_dividend.income_year || '.'
  );
  return pg_catalog.jsonb_build_object(
    'actionId', v_dividend.action_id, 'positionId', v_dividend.position_id,
    'accountingEntryId', p_entry_id,
    'taxableAddBack', (p_request ->> 'taxableAddBack')::numeric,
    'replayed', false
  );
end;
$function$;

create or replace function investments.get_received_fund_distribution_replay_v1(
  p_request jsonb, p_verified_subject text
)
returns jsonb language plpgsql security definer set search_path = ''
as $function$
declare
  v_actor_id uuid := public.company_access_auth_uid_v1();
  v_distribution investments.received_fund_distributions%rowtype;
begin
  if v_actor_id is null or v_actor_id is distinct from p_verified_subject::uuid
    or not public.company_access_is_accepted_owner_v1(
      (p_request ->> 'companyId')::uuid
    )
  then raise exception 'investments_forbidden'; end if;
  if not pg_catalog.pg_try_advisory_xact_lock(pg_catalog.hashtextextended(
    'investments:v1:' || v_actor_id::text || ':' ||
      (p_request ->> 'companyId') || ':fund-distribution:' ||
      coalesce(p_request ->> 'idempotencyKey', ''), 0
  )) then raise exception 'investments_idempotency_in_progress'; end if;
  select distribution.* into v_distribution
  from investments.received_fund_distributions distribution
  where distribution.action_id = (p_request ->> 'actionId')::uuid
     or (distribution.created_by = v_actor_id
       and distribution.company_id = (p_request ->> 'companyId')::uuid
       and distribution.idempotency_key = p_request ->> 'idempotencyKey')
  order by (distribution.action_id = (p_request ->> 'actionId')::uuid) desc
  limit 1;
  if not found then return null; end if;
  if v_distribution.request_fingerprint <>
      investments.received_fund_distribution_fingerprint_v1(p_request)
    or v_distribution.company_id <> (p_request ->> 'companyId')::uuid
    or v_distribution.income_year <> (p_request ->> 'incomeYear')::integer
  then raise exception 'investments_idempotency_key_reused'; end if;
  if v_distribution.accounting_entry_id is null then
    raise exception 'investments_idempotency_in_progress'; end if;
  return pg_catalog.jsonb_build_object(
    'actionId', v_distribution.action_id,
    'positionId', v_distribution.position_id,
    'accountingEntryId', v_distribution.accounting_entry_id,
    'dividendPortion', v_distribution.dividend_portion,
    'interestPortion', v_distribution.interest_portion,
    'taxableAddBack', v_distribution.taxable_add_back,
    'totalTaxableIncome', v_distribution.total_taxable_income,
    'replayed', true
  );
end;
$function$;

create or replace function investments.prepare_received_fund_distribution_v1(
  p_request jsonb, p_verified_subject text
)
returns jsonb language plpgsql security definer set search_path = ''
as $function$
declare
  v_actor_id uuid := public.company_access_auth_uid_v1();
  v_company_id uuid := (p_request ->> 'companyId')::uuid;
  v_position investments.positions%rowtype;
  v_name text := pg_catalog.btrim(p_request ->> 'fundName');
  v_tax_reference text := pg_catalog.btrim(
    p_request ->> 'fundTaxStatementReference'
  );
  v_ratio integer := (p_request ->> 'openingFundEquityRatioBasisPoints')::integer;
begin
  if v_actor_id is null or v_actor_id is distinct from p_verified_subject::uuid
    or not public.company_access_is_accepted_owner_v1(v_company_id)
  then raise exception 'investments_forbidden'; end if;
  if not pg_catalog.pg_try_advisory_xact_lock(pg_catalog.hashtextextended(
    'investments:v1:' || v_actor_id::text || ':' || v_company_id::text ||
      ':fund-distribution:' || coalesce(p_request ->> 'idempotencyKey', ''), 0
  )) then raise exception 'investments_idempotency_in_progress'; end if;
  if coalesce(p_request ->> 'idempotencyKey', '') !~ '^[A-Za-z0-9._:-]{16,255}$'
    or v_name = '' or pg_catalog.length(v_name) > 255
    or v_tax_reference = '' or pg_catalog.length(v_tax_reference) > 255
    or v_ratio not between 0 and 10000
    or (p_request ->> 'grossAmount')::numeric <= 0
    or pg_catalog.round((p_request ->> 'grossAmount')::numeric, 2) <>
      (p_request ->> 'grossAmount')::numeric
    or (p_request ->> 'entitlementDate')::date > (p_request ->> 'paidDate')::date
    or extract(year from (p_request ->> 'entitlementDate')::date)::integer <>
      (p_request ->> 'incomeYear')::integer
    or extract(year from (p_request ->> 'paidDate')::date)::integer <>
      (p_request ->> 'incomeYear')::integer
    or p_request ->> 'evidenceDigest' !~ '^[0-9a-f]{64}$'
    or nullif(pg_catalog.btrim(p_request ->> 'evidenceReference'), '') is null
    or not (
      (p_request ->> 'evidenceMode' = 'linked_sources'
        and nullif(p_request ->> 'bankTransactionId', '') is not null
        and nullif(p_request ->> 'documentId', '') is not null
        and p_request ->> 'documentStatus' = 'attached'
        and (p_request ->> 'ownerAttested')::boolean = false)
      or (p_request ->> 'evidenceMode' = 'manual_fallback'
        and nullif(p_request ->> 'bankTransactionId', '') is null
        and nullif(p_request ->> 'documentId', '') is null
        and p_request ->> 'documentStatus' = 'missing_accepted_warning'
        and (p_request ->> 'ownerAttested')::boolean = true)
    )
  then raise exception 'investments_invalid_input'; end if;
  if exists (
    select 1 from investments.received_fund_distributions distribution
    where distribution.action_id = (p_request ->> 'actionId')::uuid
       or (distribution.created_by = v_actor_id
         and distribution.company_id = v_company_id
         and distribution.idempotency_key = p_request ->> 'idempotencyKey')
  ) then raise exception 'investments_idempotency_key_reused'; end if;
  select position.* into v_position from investments.positions position
  where position.id = (p_request ->> 'positionId')::uuid for update;
  if not found or v_position.company_id <> v_company_id
    or v_position.kind <> 'norwegian_equity_fund'
  then raise exception 'investments_invalid_input'; end if;
  insert into investments.received_fund_distributions (
    action_id, company_id, income_year, idempotency_key, request_fingerprint,
    position_id, fund_name, entitlement_date, paid_date, gross_amount,
    opening_fund_equity_ratio_basis_points, fund_tax_statement_reference,
    bank_transaction_id, document_id, document_status,
    evidence_mode, evidence_reference, evidence_digest, owner_attested,
    created_by
  ) values (
    (p_request ->> 'actionId')::uuid, v_company_id,
    (p_request ->> 'incomeYear')::integer, p_request ->> 'idempotencyKey',
    investments.received_fund_distribution_fingerprint_v1(p_request),
    v_position.id, v_name,
    (p_request ->> 'entitlementDate')::date,
    (p_request ->> 'paidDate')::date,
    (p_request ->> 'grossAmount')::numeric, v_ratio, v_tax_reference,
    nullif(p_request ->> 'bankTransactionId', '')::uuid,
    nullif(p_request ->> 'documentId', '')::uuid,
    p_request ->> 'documentStatus', p_request ->> 'evidenceMode',
    pg_catalog.btrim(p_request ->> 'evidenceReference'),
    p_request ->> 'evidenceDigest', (p_request ->> 'ownerAttested')::boolean,
    v_actor_id
  );
  return pg_catalog.jsonb_build_object(
    'positionId', v_position.id, 'investmentName', v_position.name,
    'investmentKind', v_position.kind
  );
end;
$function$;

create or replace function investments.complete_received_fund_distribution_v1(
  p_request jsonb, p_entry_id uuid, p_verified_subject text
)
returns jsonb language plpgsql security definer set search_path = ''
as $function$
declare
  v_actor_id uuid := public.company_access_auth_uid_v1();
  v_distribution investments.received_fund_distributions%rowtype;
  v_dividend numeric := (p_request ->> 'dividendPortion')::numeric;
  v_interest numeric := (p_request ->> 'interestPortion')::numeric;
  v_add_back numeric := (p_request ->> 'taxableAddBack')::numeric;
  v_taxable numeric := (p_request ->> 'totalTaxableIncome')::numeric;
begin
  if v_actor_id is null or v_actor_id is distinct from p_verified_subject::uuid
  then raise exception 'investments_forbidden'; end if;
  select distribution.* into v_distribution
  from investments.received_fund_distributions distribution
  where distribution.action_id = (p_request ->> 'actionId')::uuid for update;
  if not found or v_distribution.request_fingerprint <>
      investments.received_fund_distribution_fingerprint_v1(p_request)
    or p_request ->> 'calculationId' !~ '^[0-9a-f]{64}$'
    or p_request ->> 'evidenceDigest' <> v_distribution.evidence_digest
    or v_dividend < 0 or v_interest < 0 or v_add_back < 0 or v_taxable < 0
    or v_dividend + v_interest <> v_distribution.gross_amount
    or v_taxable <> v_interest + v_add_back
    or not ledger.investment_dividend_entry_matches_v1(
      p_entry_id, v_distribution.company_id, v_distribution.action_id
    )
  then raise exception 'investments_dependency_unavailable'; end if;
  if v_distribution.accounting_entry_id is not null then
    if v_distribution.accounting_entry_id <> p_entry_id then
      raise exception 'investments_idempotency_key_reused'; end if;
    return pg_catalog.jsonb_build_object(
      'actionId', v_distribution.action_id,
      'positionId', v_distribution.position_id,
      'accountingEntryId', v_distribution.accounting_entry_id,
      'dividendPortion', v_distribution.dividend_portion,
      'interestPortion', v_distribution.interest_portion,
      'taxableAddBack', v_distribution.taxable_add_back,
      'totalTaxableIncome', v_distribution.total_taxable_income,
      'replayed', true
    );
  end if;
  update investments.received_fund_distributions
  set accounting_entry_id = p_entry_id, completed_at = pg_catalog.now(),
      dividend_portion = v_dividend, interest_portion = v_interest,
      taxable_add_back = v_add_back, total_taxable_income = v_taxable,
      calculation_id = p_request ->> 'calculationId'
  where action_id = v_distribution.action_id;
  insert into public.audit_events (company_id, actor_id, category, action, message)
  values (
    v_distribution.company_id, v_actor_id, 'ledger',
    'fund_distribution_received_recorded',
    'Mottatt fondsutdeling postert fra ' || v_distribution.fund_name ||
      ' for ' || v_distribution.income_year || '.'
  );
  return pg_catalog.jsonb_build_object(
    'actionId', v_distribution.action_id,
    'positionId', v_distribution.position_id,
    'accountingEntryId', p_entry_id,
    'dividendPortion', v_dividend, 'interestPortion', v_interest,
    'taxableAddBack', v_add_back, 'totalTaxableIncome', v_taxable,
    'replayed', false
  );
end;
$function$;

create table investments.corrections (
  correction_id uuid primary key,
  company_id uuid not null references public.companies(id) on delete cascade,
  income_year integer not null check (income_year between 2000 and 2100),
  idempotency_key text not null check (
    idempotency_key ~ '^[A-Za-z0-9._:-]{16,255}$'
  ),
  request_fingerprint text not null check (
    request_fingerprint ~ '^[0-9a-f]{64}$'
  ),
  original_action_id uuid not null,
  original_activity_kind text not null check (
    original_activity_kind in (
      'share_purchase', 'share_sale', 'dividend_received',
      'fund_distribution_received'
    )
  ),
  reversal_accounting_entry_id uuid not null unique,
  replacement_action_id uuid not null unique,
  replacement_activity_kind text not null check (
    replacement_activity_kind in (
      'share_purchase', 'share_sale', 'dividend_received',
      'fund_distribution_received'
    )
  ),
  replacement_accounting_entry_id uuid not null unique,
  reason text not null check (
    reason = pg_catalog.btrim(reason) and reason <> ''
    and pg_catalog.length(reason) <= 500
  ),
  bank_transaction_id uuid,
  document_id uuid,
  document_status text not null check (
    document_status in ('attached', 'missing_accepted_warning', 'not_required')
  ),
  evidence_mode text not null check (
    evidence_mode in ('linked_sources', 'manual_fallback')
  ),
  evidence_reference text not null check (
    evidence_reference = pg_catalog.btrim(evidence_reference)
    and evidence_reference <> ''
    and pg_catalog.length(evidence_reference) <= 255
  ),
  evidence_digest text not null check (evidence_digest ~ '^[0-9a-f]{64}$'),
  owner_attested boolean not null,
  created_by uuid not null references auth.users(id) on delete restrict,
  created_at timestamptz not null default pg_catalog.now(),
  unique (company_id, original_action_id),
  unique (created_by, company_id, idempotency_key),
  check (original_action_id <> replacement_action_id),
  check (original_activity_kind = replacement_activity_kind)
);
alter table investments.corrections owner to investments_store_owner;
alter table investments.corrections enable row level security;
alter table investments.corrections force row level security;
create policy investments_corrections_member_select
on investments.corrections for select
to investments_executor, investments_store_owner
using (public.company_access_is_accepted_member_v1(company_id));
create policy investments_corrections_owner_insert
on investments.corrections for insert to investments_store_owner
with check (
  created_by = public.company_access_auth_uid_v1()
  and public.company_access_is_accepted_owner_v1(company_id)
);

create or replace function investments.correction_fingerprint_v1(p_request jsonb)
returns text language sql immutable set search_path = ''
as $function$
  select pg_catalog.encode(extensions.digest(
    (p_request - 'correlationId')::text, 'sha256'
  ), 'hex')
$function$;

create or replace function investments.get_correction_replay_v1(
  p_request jsonb, p_verified_subject text
)
returns jsonb language plpgsql security definer set search_path = ''
as $function$
declare
  v_actor_id uuid := public.company_access_auth_uid_v1();
  v_row investments.corrections%rowtype;
begin
  if v_actor_id is null or v_actor_id is distinct from p_verified_subject::uuid
  then raise exception 'investments_forbidden'; end if;
  select correction.* into v_row from investments.corrections correction
  where correction.correction_id = (p_request ->> 'correctionId')::uuid
     or (correction.created_by = v_actor_id
       and correction.company_id = (p_request ->> 'companyId')::uuid
       and correction.idempotency_key = p_request ->> 'idempotencyKey');
  if not found then return null; end if;
  if v_row.request_fingerprint <> investments.correction_fingerprint_v1(p_request)
  then raise exception 'investments_idempotency_key_reused'; end if;
  return pg_catalog.jsonb_build_object(
    'correctionId', v_row.correction_id,
    'originalActionId', v_row.original_action_id,
    'replacementActionId', v_row.replacement_action_id,
    'reversalAccountingEntryId', v_row.reversal_accounting_entry_id,
    'replacementAccountingEntryId', v_row.replacement_accounting_entry_id,
    'replayed', true
  );
end;
$function$;

create or replace function investments.prepare_correction_v1(
  p_request jsonb, p_verified_subject text
)
returns jsonb language plpgsql security definer set search_path = ''
as $function$
declare
  v_actor_id uuid := public.company_access_auth_uid_v1();
  v_company_id uuid := (p_request ->> 'companyId')::uuid;
  v_original_action_id uuid := (p_request ->> 'originalActionId')::uuid;
  v_replacement_action_id uuid := (p_request ->> 'replacementActionId')::uuid;
  v_kind text := p_request ->> 'originalActivityKind';
  v_position_id uuid;
  v_original_entry_id uuid;
  v_created_at timestamptz;
  v_purchase investments.share_purchases%rowtype;
  v_sale investments.share_sales%rowtype;
  v_lot investments.acquisition_lots%rowtype;
  v_position investments.positions%rowtype;
begin
  if v_actor_id is null or v_actor_id is distinct from p_verified_subject::uuid
    or not public.company_access_is_accepted_owner_v1(v_company_id)
  then raise exception 'investments_forbidden'; end if;
  if not pg_catalog.pg_try_advisory_xact_lock(pg_catalog.hashtextextended(
    'investments:v1:' || v_actor_id::text || ':' || v_company_id::text ||
      ':correction:' || coalesce(p_request ->> 'idempotencyKey', ''), 0
  )) then raise exception 'investments_idempotency_in_progress'; end if;
  if coalesce(p_request ->> 'idempotencyKey', '') !~ '^[A-Za-z0-9._:-]{16,255}$'
    or v_original_action_id = v_replacement_action_id
    or v_kind not in (
      'share_purchase', 'share_sale', 'dividend_received',
      'fund_distribution_received'
    )
    or p_request ->> 'replacementActivityKind' is distinct from v_kind
    or pg_catalog.btrim(coalesce(p_request ->> 'reason', '')) = ''
    or pg_catalog.length(p_request ->> 'reason') > 500
    or p_request ->> 'evidenceDigest' !~ '^[0-9a-f]{64}$'
    or not coalesce((
      (p_request ->> 'evidenceMode' = 'linked_sources'
        and p_request ->> 'bankTransactionId' is not null
        and p_request ->> 'documentId' is not null
        and p_request ->> 'documentStatus' = 'attached'
        and (p_request ->> 'ownerAttested')::boolean = false)
      or (p_request ->> 'evidenceMode' = 'manual_fallback'
        and p_request ->> 'bankTransactionId' is null
        and p_request ->> 'documentId' is null
        and p_request ->> 'documentStatus' = 'missing_accepted_warning'
        and (p_request ->> 'ownerAttested')::boolean = true)
    ), false)
    or nullif(pg_catalog.btrim(p_request ->> 'evidenceReference'), '') is null
    or pg_catalog.length(p_request ->> 'evidenceReference') > 255
    or extract(year from (p_request ->> 'correctionDate')::date)::integer
      <> (p_request ->> 'incomeYear')::integer
  then raise exception 'investments_invalid_input'; end if;
  if exists (
    select 1 from investments.corrections correction
    where correction.correction_id = (p_request ->> 'correctionId')::uuid
       or (correction.created_by = v_actor_id
         and correction.company_id = v_company_id
         and correction.idempotency_key = p_request ->> 'idempotencyKey')
       or (correction.company_id = v_company_id
         and correction.original_action_id = v_original_action_id)
  ) then raise exception 'investments_idempotency_key_reused'; end if;
  if exists (select 1 from investments.share_purchases where action_id = v_replacement_action_id)
    or exists (select 1 from investments.share_sales where action_id = v_replacement_action_id)
    or exists (select 1 from investments.received_dividends where action_id = v_replacement_action_id)
    or exists (select 1 from investments.received_fund_distributions where action_id = v_replacement_action_id)
  then raise exception 'investments_idempotency_key_reused'; end if;

  if v_kind = 'share_purchase' then
    select purchase.* into v_purchase from investments.share_purchases purchase
    where purchase.action_id = v_original_action_id for update;
    if not found or v_purchase.company_id <> v_company_id
      or v_purchase.income_year <> (p_request ->> 'incomeYear')::integer
      or v_purchase.accounting_entry_id is null
    then raise exception 'investments_invalid_input'; end if;
    select lot.* into v_lot from investments.acquisition_lots lot
    where lot.id = v_purchase.acquisition_lot_id for update;
    select position.* into v_position from investments.positions position
    where position.id = v_purchase.position_id for update;
    if not found or v_lot.remaining_share_count <> v_lot.original_share_count
      or v_lot.remaining_cost_basis <> v_lot.original_cost_basis
      or v_lot.remaining_tax_basis <> v_lot.original_tax_basis
      or exists (
        select 1 from investments.share_sales later
        where later.position_id = v_purchase.position_id
          and later.accounting_entry_id is not null
          and (later.created_at, later.action_id) >
            (v_purchase.created_at, v_purchase.action_id)
      )
    then raise exception 'investments_dependency_unavailable'; end if;
    update investments.acquisition_lots
    set remaining_share_count = 0, remaining_cost_basis = 0,
        remaining_tax_basis = 0
    where id = v_lot.id;
    update investments.positions
    set share_count = share_count - v_lot.original_share_count,
        cost_basis = cost_basis - v_lot.original_cost_basis,
        tax_basis = tax_basis - v_lot.original_tax_basis,
        movements = movements || pg_catalog.jsonb_build_array(
          pg_catalog.jsonb_build_object(
            'action_id', p_request ->> 'correctionId',
            'movement_type', 'correction_reversal',
            'movement_date', p_request ->> 'correctionDate',
            'corrected_action_id', v_original_action_id,
            'share_delta', -v_lot.original_share_count,
            'book_cost_basis_delta', -v_lot.original_cost_basis,
            'tax_basis_delta', -v_lot.original_tax_basis,
            'evidence_digest', p_request ->> 'evidenceDigest'
          )
        ), updated_at = pg_catalog.now()
    where id = v_position.id
      and share_count >= v_lot.original_share_count
      and cost_basis >= v_lot.original_cost_basis
      and tax_basis >= v_lot.original_tax_basis;
    if not found then raise exception 'investments_dependency_unavailable'; end if;
    v_position_id := v_purchase.position_id;
    v_original_entry_id := v_purchase.accounting_entry_id;
    v_created_at := v_purchase.created_at;
  elsif v_kind = 'share_sale' then
    select sale.* into v_sale from investments.share_sales sale
    where sale.action_id = v_original_action_id for update;
    if not found or v_sale.company_id <> v_company_id
      or v_sale.income_year <> (p_request ->> 'incomeYear')::integer
      or v_sale.accounting_entry_id is null
      or exists (
        select 1 from investments.share_sales later
        where later.position_id = v_sale.position_id
          and later.accounting_entry_id is not null
          and (later.created_at, later.action_id) >
            (v_sale.created_at, v_sale.action_id)
      )
      or exists (
        select 1 from investments.share_purchases later
        where later.position_id = v_sale.position_id
          and later.accounting_entry_id is not null
          and (later.created_at, later.action_id) >
            (v_sale.created_at, v_sale.action_id)
      )
    then raise exception 'investments_dependency_unavailable'; end if;
    perform 1 from investments.acquisition_lots lot
    join investments.share_sale_allocations allocation
      on allocation.acquisition_lot_id = lot.id
    where allocation.sale_action_id = v_sale.action_id
    order by allocation.allocation_order for update of lot;
    if not found then raise exception 'investments_dependency_unavailable'; end if;
    update investments.acquisition_lots lot
    set remaining_share_count = lot.remaining_share_count + allocation.allocated_share_count,
        remaining_cost_basis = lot.remaining_cost_basis + allocation.allocated_book_cost_basis,
        remaining_tax_basis = lot.remaining_tax_basis + allocation.allocated_tax_basis
    from investments.share_sale_allocations allocation
    where allocation.sale_action_id = v_sale.action_id
      and allocation.acquisition_lot_id = lot.id;
    update investments.positions position
    set share_count = position.share_count + v_sale.sold_share_count,
        cost_basis = position.cost_basis + v_sale.fifo_cost_basis_reduction,
        tax_basis = position.tax_basis + v_sale.fifo_tax_basis_reduction,
        movements = movements || pg_catalog.jsonb_build_array(
          pg_catalog.jsonb_build_object(
            'action_id', p_request ->> 'correctionId',
            'movement_type', 'correction_reversal',
            'movement_date', p_request ->> 'correctionDate',
            'corrected_action_id', v_original_action_id,
            'share_delta', v_sale.sold_share_count,
            'book_cost_basis_delta', v_sale.fifo_cost_basis_reduction,
            'tax_basis_delta', v_sale.fifo_tax_basis_reduction,
            'evidence_digest', p_request ->> 'evidenceDigest'
          )
        ), updated_at = pg_catalog.now()
    where position.id = v_sale.position_id;
    if not found then raise exception 'investments_dependency_unavailable'; end if;
    v_position_id := v_sale.position_id;
    v_original_entry_id := v_sale.accounting_entry_id;
    v_created_at := v_sale.created_at;
  elsif v_kind = 'dividend_received' then
    select dividend.position_id, dividend.accounting_entry_id, dividend.created_at
    into v_position_id, v_original_entry_id, v_created_at
    from investments.received_dividends dividend
    where dividend.action_id = v_original_action_id
      and dividend.company_id = v_company_id
      and dividend.income_year = (p_request ->> 'incomeYear')::integer
      and dividend.accounting_entry_id is not null for update;
    if not found then raise exception 'investments_invalid_input'; end if;
  else
    select distribution.position_id, distribution.accounting_entry_id,
      distribution.created_at
    into v_position_id, v_original_entry_id, v_created_at
    from investments.received_fund_distributions distribution
    where distribution.action_id = v_original_action_id
      and distribution.company_id = v_company_id
      and distribution.income_year = (p_request ->> 'incomeYear')::integer
      and distribution.accounting_entry_id is not null for update;
    if not found then raise exception 'investments_invalid_input'; end if;
  end if;
  return pg_catalog.jsonb_build_object(
    'originalAccountingEntryId', v_original_entry_id,
    'originalPositionId', v_position_id,
    'originalCreatedAt', v_created_at
  );
end;
$function$;

-- The migration principal is deliberately NOINHERIT from ledger ownership.
-- Switch explicitly so Supabase's migration runner can create the narrow
-- correction bridge without granting CREATE on the ledger schema to runtime
-- roles or relying on superuser authority.
grant create on schema ledger to ledger_store_owner;
set local role ledger_store_owner;

create or replace function ledger.link_investment_correction_v1(
  p_company_id uuid, p_income_year integer, p_original_entry_id uuid,
  p_replacement_entry_id uuid, p_original_action_id uuid,
  p_replacement_action_id uuid, p_reason text, p_correlation_id text,
  p_event_date date, p_verified_subject text
)
returns uuid language plpgsql security definer set search_path = ''
as $function$
declare
  v_actor_id uuid := public.company_access_auth_uid_v1();
  v_original ledger.entries%rowtype;
  v_replacement ledger.entries%rowtype;
  v_reversal_entry_id uuid := pg_catalog.gen_random_uuid();
  v_reversal_lines jsonb;
  v_original_digest text;
begin
  if v_actor_id is null or v_actor_id is distinct from p_verified_subject::uuid
    or not public.company_access_is_accepted_owner_v1(p_company_id)
  then raise exception 'investments_forbidden'; end if;
  select entry.* into v_original from ledger.entries entry
  where entry.id = p_original_entry_id and entry.company_id = p_company_id
    and entry.income_year = p_income_year;
  select entry.* into v_replacement from ledger.entries entry
  where entry.id = p_replacement_entry_id and entry.company_id = p_company_id
    and entry.income_year = p_income_year;
  if v_original.id is null or v_replacement.id is null
    or v_original.entry_kind not in ('SHARE_PURCHASE', 'SHARE_SALE', 'DIVIDEND_RECEIVED')
    or v_replacement.entry_kind <> v_original.entry_kind
    or v_original.source_capability <> 'INVESTMENTS'
    or v_replacement.source_capability <> 'INVESTMENTS'
    or v_original.source_record_id <> p_original_action_id::text
    or v_replacement.source_record_id <> p_replacement_action_id::text
    or exists (select 1 from ledger.entry_corrections correction
      where correction.original_entry_id = p_original_entry_id)
  then raise exception 'investments_dependency_unavailable'; end if;
  select pg_catalog.jsonb_agg(pg_catalog.jsonb_build_object(
    'account', line ->> 'account', 'description', line ->> 'description',
    'debit', pg_catalog.round((line ->> 'credit')::numeric, 2),
    'credit', pg_catalog.round((line ->> 'debit')::numeric, 2),
    'currency', 'NOK'
  ) order by ordinal) into v_reversal_lines
  from pg_catalog.jsonb_array_elements(v_original.lines)
    with ordinality item(line, ordinal);
  v_original_digest := pg_catalog.encode(
    extensions.digest(pg_catalog.to_jsonb(v_original)::text, 'sha256'), 'hex'
  );
  insert into ledger.entries (
    id, company_id, income_year, entry_kind, memo, lines, risk_flags,
    warning_accepted_by, warning_accepted_at, posted_at, created_by, created_at,
    source_capability, source_record_id, correlation_id
  ) values (
    v_reversal_entry_id, p_company_id, p_income_year, 'CORRECTION_REVERSAL',
    'Full investment reversal: ' || pg_catalog.btrim(p_reason),
    v_reversal_lines, '[]'::jsonb, null, null, pg_catalog.statement_timestamp(),
    v_actor_id, pg_catalog.statement_timestamp(), 'LEDGER',
    'correction-reversal:' || p_original_entry_id::text,
    pg_catalog.btrim(p_correlation_id)
  );
  insert into ledger.entry_contexts (
    entry_id, company_id, income_year, event_date, rule_version,
    sources_digest, recorded_at
  ) values (
    v_reversal_entry_id, p_company_id, p_income_year, p_event_date,
    'ledger-supported-patterns-2026.1',
    pg_catalog.encode(extensions.digest(
      pg_catalog.jsonb_build_array(pg_catalog.jsonb_build_object(
        'role', 'PRIMARY', 'capability', 'LEDGER',
        'recordId', p_original_entry_id::text, 'revision', 1,
        'factSha256', v_original_digest
      ))::text, 'sha256'
    ), 'hex'), pg_catalog.statement_timestamp()
  );
  insert into ledger.entry_sources (
    entry_id, company_id, income_year, ordinal, source_role,
    source_capability, source_record_id, source_revision, fact_sha256
  ) values (
    v_reversal_entry_id, p_company_id, p_income_year, 1, 'PRIMARY', 'LEDGER',
    p_original_entry_id::text, 1, v_original_digest
  );
  insert into ledger.entry_corrections (
    original_entry_id, reversal_entry_id, replacement_entry_id,
    company_id, income_year, reason, corrected_by, corrected_at
  ) values (
    p_original_entry_id, v_reversal_entry_id, p_replacement_entry_id,
    p_company_id, p_income_year, pg_catalog.btrim(p_reason), v_actor_id,
    pg_catalog.statement_timestamp()
  );
  return v_reversal_entry_id;
end;
$function$;

create or replace function ledger.investment_correction_matches_v1(
  p_original_entry_id uuid, p_reversal_entry_id uuid,
  p_replacement_entry_id uuid, p_company_id uuid, p_income_year integer,
  p_original_action_id uuid, p_replacement_action_id uuid
)
returns boolean language sql stable security definer set search_path = ''
as $function$
  select exists (
    select 1 from ledger.entry_corrections correction
    where correction.original_entry_id = p_original_entry_id
      and correction.reversal_entry_id = p_reversal_entry_id
      and correction.replacement_entry_id = p_replacement_entry_id
      and correction.company_id = p_company_id
      and correction.income_year = p_income_year
      and exists (
        select 1 from ledger.entries original
        where original.id = p_original_entry_id
          and original.source_capability = 'INVESTMENTS'
          and original.source_record_id = p_original_action_id::text
      )
      and exists (
        select 1 from ledger.entries replacement
        where replacement.id = p_replacement_entry_id
          and replacement.source_capability = 'INVESTMENTS'
          and replacement.source_record_id = p_replacement_action_id::text
      )
  )
$function$;

reset role;
revoke create on schema ledger from ledger_store_owner;

create or replace function investments.complete_correction_v1(
  p_request jsonb, p_original_entry_id uuid, p_replacement_entry_id uuid,
  p_reversal_entry_id uuid, p_verified_subject text
)
returns jsonb language plpgsql security definer set search_path = ''
as $function$
declare
  v_actor_id uuid := public.company_access_auth_uid_v1();
  v_company_id uuid := (p_request ->> 'companyId')::uuid;
begin
  if v_actor_id is null or v_actor_id is distinct from p_verified_subject::uuid
    or not ledger.investment_correction_matches_v1(
      p_original_entry_id, p_reversal_entry_id, p_replacement_entry_id,
      v_company_id, (p_request ->> 'incomeYear')::integer,
      (p_request ->> 'originalActionId')::uuid,
      (p_request ->> 'replacementActionId')::uuid
    )
  then raise exception 'investments_dependency_unavailable'; end if;
  insert into investments.corrections (
    correction_id, company_id, income_year, idempotency_key,
    request_fingerprint, original_action_id, original_activity_kind,
    reversal_accounting_entry_id, replacement_action_id,
    replacement_activity_kind, replacement_accounting_entry_id,
    reason, bank_transaction_id, document_id, document_status,
    evidence_mode, evidence_reference, evidence_digest, owner_attested,
    created_by
  ) values (
    (p_request ->> 'correctionId')::uuid, v_company_id,
    (p_request ->> 'incomeYear')::integer, p_request ->> 'idempotencyKey',
    investments.correction_fingerprint_v1(p_request),
    (p_request ->> 'originalActionId')::uuid,
    p_request ->> 'originalActivityKind', p_reversal_entry_id,
    (p_request ->> 'replacementActionId')::uuid,
    p_request ->> 'replacementActivityKind', p_replacement_entry_id,
    pg_catalog.btrim(p_request ->> 'reason'),
    (p_request ->> 'bankTransactionId')::uuid,
    (p_request ->> 'documentId')::uuid,
    p_request ->> 'documentStatus', p_request ->> 'evidenceMode',
    pg_catalog.btrim(p_request ->> 'evidenceReference'),
    p_request ->> 'evidenceDigest',
    (p_request ->> 'ownerAttested')::boolean, v_actor_id
  );
  insert into public.audit_events (company_id, actor_id, category, action, message)
  values (
    v_company_id, v_actor_id, 'ledger', 'investment_corrected',
    'Investeringshendelse korrigert med full reversering og erstatning.'
  );
  return pg_catalog.jsonb_build_object(
    'correctionId', p_request ->> 'correctionId',
    'originalActionId', p_request ->> 'originalActionId',
    'replacementActionId', p_request ->> 'replacementActionId',
    'reversalAccountingEntryId', p_reversal_entry_id,
    'replacementAccountingEntryId', p_replacement_entry_id,
    'replayed', false
  );
end;
$function$;

grant select on investments.received_fund_distributions,
  investments.corrections to investments_executor;
grant select, insert, update on investments.received_fund_distributions
  to investments_store_owner;
grant select, insert on investments.corrections to investments_store_owner;
grant insert on public.audit_events to investments_store_owner;

alter function investments.share_purchase_fingerprint_v1(jsonb)
  owner to investments_store_owner;
alter function investments.get_share_purchase_replay_v1(jsonb, text)
  owner to investments_store_owner;
alter function investments.prepare_share_purchase_v1(jsonb, text)
  owner to investments_store_owner;
alter function investments.complete_share_purchase_v1(jsonb, uuid, jsonb, text)
  owner to investments_store_owner;
alter function investments.share_sale_fingerprint_v1(jsonb)
  owner to investments_store_owner;
alter function investments.get_share_sale_replay_v1(jsonb, text)
  owner to investments_store_owner;
alter function investments.prepare_share_sale_v1(jsonb, text)
  owner to investments_store_owner;
alter function investments.complete_share_sale_v1(jsonb, uuid, text)
  owner to investments_store_owner;
alter function investments.received_dividend_fingerprint_v1(jsonb)
  owner to investments_store_owner;
alter function investments.get_received_dividend_replay_v1(jsonb, text)
  owner to investments_store_owner;
alter function investments.prepare_received_dividend_v1(jsonb, text)
  owner to investments_store_owner;
alter function investments.complete_received_dividend_v1(jsonb, uuid, text)
  owner to investments_store_owner;
alter function investments.received_fund_distribution_fingerprint_v1(jsonb)
  owner to investments_store_owner;
alter function investments.get_received_fund_distribution_replay_v1(jsonb, text)
  owner to investments_store_owner;
alter function investments.prepare_received_fund_distribution_v1(jsonb, text)
  owner to investments_store_owner;
alter function investments.complete_received_fund_distribution_v1(jsonb, uuid, text)
  owner to investments_store_owner;
alter function investments.correction_fingerprint_v1(jsonb)
  owner to investments_store_owner;
alter function investments.get_correction_replay_v1(jsonb, text)
  owner to investments_store_owner;
alter function investments.prepare_correction_v1(jsonb, text)
  owner to investments_store_owner;
alter function investments.complete_correction_v1(
  jsonb, uuid, uuid, uuid, text
) owner to investments_store_owner;
alter function ledger.link_investment_correction_v1(
  uuid, integer, uuid, uuid, uuid, uuid, text, text, date, text
) owner to ledger_store_owner;
alter function ledger.investment_correction_matches_v1(
  uuid, uuid, uuid, uuid, integer, uuid, uuid
) owner to ledger_store_owner;

revoke all on function
  investments.share_purchase_fingerprint_v1(jsonb),
  investments.get_share_purchase_replay_v1(jsonb, text),
  investments.prepare_share_purchase_v1(jsonb, text),
  investments.complete_share_purchase_v1(jsonb, uuid, jsonb, text),
  investments.share_sale_fingerprint_v1(jsonb),
  investments.get_share_sale_replay_v1(jsonb, text),
  investments.prepare_share_sale_v1(jsonb, text),
  investments.complete_share_sale_v1(jsonb, uuid, text),
  investments.received_dividend_fingerprint_v1(jsonb),
  investments.get_received_dividend_replay_v1(jsonb, text),
  investments.prepare_received_dividend_v1(jsonb, text),
  investments.complete_received_dividend_v1(jsonb, uuid, text),
  investments.received_fund_distribution_fingerprint_v1(jsonb),
  investments.get_received_fund_distribution_replay_v1(jsonb, text),
  investments.prepare_received_fund_distribution_v1(jsonb, text),
  investments.complete_received_fund_distribution_v1(jsonb, uuid, text),
  investments.correction_fingerprint_v1(jsonb),
  investments.get_correction_replay_v1(jsonb, text),
  investments.prepare_correction_v1(jsonb, text),
  investments.complete_correction_v1(jsonb, uuid, uuid, uuid, text),
  ledger.link_investment_correction_v1(
    uuid, integer, uuid, uuid, uuid, uuid, text, text, date, text
  ),
  ledger.investment_correction_matches_v1(
    uuid, uuid, uuid, uuid, integer, uuid, uuid
  )
from public, anon, authenticated, service_role;
grant execute on function
  investments.get_share_purchase_replay_v1(jsonb, text),
  investments.prepare_share_purchase_v1(jsonb, text),
  investments.complete_share_purchase_v1(jsonb, uuid, jsonb, text),
  investments.get_share_sale_replay_v1(jsonb, text),
  investments.prepare_share_sale_v1(jsonb, text),
  investments.complete_share_sale_v1(jsonb, uuid, text),
  investments.get_received_dividend_replay_v1(jsonb, text),
  investments.prepare_received_dividend_v1(jsonb, text),
  investments.complete_received_dividend_v1(jsonb, uuid, text),
  investments.get_received_fund_distribution_replay_v1(jsonb, text),
  investments.prepare_received_fund_distribution_v1(jsonb, text),
  investments.complete_received_fund_distribution_v1(jsonb, uuid, text),
  investments.get_correction_replay_v1(jsonb, text),
  investments.prepare_correction_v1(jsonb, text),
  investments.complete_correction_v1(jsonb, uuid, uuid, uuid, text),
  ledger.link_investment_correction_v1(
    uuid, integer, uuid, uuid, uuid, uuid, text, text, date, text
  )
to investments_workflow_executor;
grant execute on function ledger.investment_correction_matches_v1(
  uuid, uuid, uuid, uuid, integer, uuid, uuid
) to investments_store_owner;

set local role company_archive_projection_executor;
do $archive_authority$
begin
  execute pg_catalog.format(
    'grant execute on function public.company_archive_track_source_write_v1() to %I',
    pg_catalog.current_setting('talli.investments_190_migration_principal')
  );
end
$archive_authority$;
reset role;
create trigger company_archive_track_investments_received_fund_distributions
after insert or update or delete on investments.received_fund_distributions
for each row execute function public.company_archive_track_source_write_v1(
  'year', 'company_id'
);
create trigger company_archive_track_investments_corrections
after insert or update or delete on investments.corrections
for each row execute function public.company_archive_track_source_write_v1(
  'year', 'company_id'
);
set local role company_archive_projection_executor;
do $archive_authority_revoke$
begin
  execute pg_catalog.format(
    'revoke execute on function public.company_archive_track_source_write_v1() from %I',
    pg_catalog.current_setting('talli.investments_190_migration_principal')
  );
end
$archive_authority_revoke$;
reset role;

revoke all on investments.received_fund_distributions,
  investments.corrections from public, anon, authenticated, service_role;

do $membership_revoke$
begin
  execute pg_catalog.format(
    'revoke investments_store_owner, investments_executor, investments_workflow_executor, company_access_executor, ledger_store_owner, company_archive_projection_executor from %I',
    current_user
  );
end
$membership_revoke$;

commit;
