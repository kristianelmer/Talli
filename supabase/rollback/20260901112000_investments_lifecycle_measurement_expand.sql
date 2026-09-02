begin;

set local lock_timeout = '5s';
set local statement_timeout = '120s';

do $membership$
begin
  execute pg_catalog.format(
    'grant investments_store_owner to %I',
    current_user
  );
end
$membership$;

select pg_catalog.pg_advisory_xact_lock(
  pg_catalog.hashtextextended('talli:investments:lifecycle-measurement:v2', 0)
);

do $rollback_guard$
begin
  if exists (select 1 from investments.economic_events)
     or exists (select 1 from investments.cash_settlements)
     or exists (select 1 from investments.year_end_measurements)
     or exists (select 1 from investments.position_classifications)
     or exists (select 1 from investments.company_year_policies) then
    raise exception 'investments_lifecycle_measurement_rollback_unsafe';
  end if;
end
$rollback_guard$;

drop table investments.measurement_sources;
drop table investments.year_end_measurements;
drop table investments.position_classifications;
drop table investments.cash_settlements;
drop table investments.event_sources;
drop table investments.economic_events;
drop table investments.company_year_policies;

set role investments_store_owner;

alter table investments.positions
  drop constraint positions_id_company_unique;

alter table investments.received_fund_distributions
  alter column total_taxable_income type numeric(20, 2),
  alter column taxable_add_back type numeric(20, 2),
  alter column interest_portion type numeric(20, 2),
  alter column dividend_portion type numeric(20, 2),
  alter column gross_amount type numeric(20, 2);
alter table investments.received_dividends
  alter column taxable_add_back type numeric(20, 2),
  alter column gross_amount type numeric(20, 2);
alter table investments.share_sale_allocations
  alter column deductible_loss type numeric(20, 2),
  alter column non_deductible_loss type numeric(20, 2),
  alter column taxable_gain type numeric(20, 2),
  alter column exempt_gain type numeric(20, 2),
  alter column tax_gain_or_loss type numeric(20, 2),
  alter column allocated_net_proceeds type numeric(20, 2),
  alter column allocated_tax_basis type numeric(20, 2),
  alter column allocated_book_cost_basis type numeric(20, 2),
  alter column allocated_cost_basis type numeric(20, 2),
  alter column allocated_share_count type bigint;
alter table investments.share_sales
  alter column remaining_tax_basis type numeric(20, 2),
  alter column remaining_cost_basis type numeric(20, 2),
  alter column remaining_share_count type bigint,
  alter column deductible_loss type numeric(20, 2),
  alter column non_deductible_loss type numeric(20, 2),
  alter column taxable_gain type numeric(20, 2),
  alter column exempt_gain type numeric(20, 2),
  alter column tax_gain_or_loss type numeric(20, 2),
  alter column book_gain_or_loss type numeric(20, 2),
  alter column fifo_tax_basis_reduction type numeric(20, 2),
  alter column fifo_cost_basis_reduction type numeric(20, 2),
  alter column net_proceeds type numeric(20, 2),
  alter column transaction_costs type numeric(20, 2),
  alter column proceeds type numeric(20, 2),
  alter column sold_share_count type bigint;
alter table investments.share_purchases
  alter column capitalized_cost type numeric(20, 2),
  alter column transaction_costs type numeric(20, 2),
  alter column purchase_amount type numeric(20, 2),
  alter column share_count type bigint;
alter table investments.acquisition_lots
  alter column remaining_tax_basis type numeric(20, 2),
  alter column original_tax_basis type numeric(20, 2),
  alter column remaining_cost_basis type numeric(20, 2),
  alter column original_cost_basis type numeric(20, 2),
  alter column remaining_share_count type bigint,
  alter column original_share_count type bigint;
alter table investments.positions
  alter column tax_basis type numeric(20, 2),
  alter column cost_basis type numeric(20, 2),
  alter column share_count type bigint;

alter table investments.positions
  drop constraint positions_classification_supported_check;
alter table investments.positions
  add constraint positions_classification_supported_check check (
    (kind = 'norwegian_private_company' and accounting_classification in (
      'subsidiary', 'associate', 'other_long_term'
    ))
    or (kind = 'norwegian_listed_share'
      and accounting_classification = 'current_listed_share')
    or (kind = 'norwegian_equity_fund'
      and accounting_classification = 'current_fund')
  );

reset role;

do $membership_revoke$
begin
  execute pg_catalog.format(
    'revoke investments_store_owner from %I',
    current_user
  );
end
$membership_revoke$;

commit;
