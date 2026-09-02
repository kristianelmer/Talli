-- BOUNDED ROLLBACK ARTIFACT: supported domestic investment patterns, issue #190.
-- This cutback is deliberately refused after any #190 action has been written.
-- Existing predecessor rows are retained and the exact pre-#190 routines are
-- restored from the capsules created by the forward migration.

begin;

do $membership$
begin
  execute pg_catalog.format(
    'grant investments_store_owner, investments_workflow_executor, ledger_store_owner, company_archive_projection_executor to %I',
    current_user
  );
end
$membership$;

select pg_catalog.pg_advisory_xact_lock(
  pg_catalog.hashtextextended('talli:investments:supported-patterns:v1', 0)
);
lock table investments.positions in share row exclusive mode;
lock table investments.acquisition_lots in share row exclusive mode;
lock table investments.share_purchases in share row exclusive mode;
lock table investments.share_sales in share row exclusive mode;
lock table investments.share_sale_allocations in share row exclusive mode;
lock table investments.received_dividends in share row exclusive mode;
lock table investments.received_fund_distributions in share row exclusive mode;
lock table investments.corrections in share row exclusive mode;

do $rollback_guard$
begin
  if exists (select 1 from investments.received_fund_distributions)
    or exists (select 1 from investments.corrections)
    or exists (
      select 1 from investments.positions position
      where position.kind <> 'norwegian_private_company'
        or position.accounting_classification <> 'other_long_term'
        or position.tax_basis <> position.cost_basis
        or position.fund_equity_ratio_basis_points is not null
        or position.fund_tax_statement_reference is not null
    )
    or exists (
      select 1 from investments.share_purchases purchase
      where purchase.evidence_reference not like 'legacy-import:%'
        or purchase.transaction_costs <> 0
        or purchase.capitalized_cost <> purchase.purchase_amount
    )
    or exists (
      select 1 from investments.share_sales sale
      where sale.evidence_reference not like 'legacy-import:%'
        or sale.transaction_costs <> 0
        or sale.net_proceeds <> sale.proceeds
        or sale.fifo_tax_basis_reduction <> sale.fifo_cost_basis_reduction
    )
    or exists (
      select 1 from investments.received_dividends dividend
      where dividend.evidence_reference not like 'legacy-import:%'
        or dividend.group_exception_claimed
    )
  then
    raise exception 'investments_supported_patterns_rollback_has_new_data';
  end if;
end
$rollback_guard$;

drop trigger if exists investments_pre_190_position_defaults
  on investments.positions;
drop trigger if exists investments_pre_190_lot_defaults
  on investments.acquisition_lots;
drop trigger if exists investments_pre_190_purchase_defaults
  on investments.share_purchases;
drop trigger if exists investments_pre_190_sale_defaults
  on investments.share_sales;
drop trigger if exists investments_pre_190_allocation_defaults
  on investments.share_sale_allocations;
drop trigger if exists investments_pre_190_dividend_defaults
  on investments.received_dividends;
drop policy if exists investments_supported_patterns_overlap_audit_insert
  on public.audit_events;
drop function if exists investments.normalize_pre_190_overlap_row_v1();

drop function investments.complete_correction_v1(jsonb, uuid, uuid, uuid, text);
drop function investments.prepare_correction_v1(jsonb, text);
drop function investments.get_correction_replay_v1(jsonb, text);
drop function investments.correction_fingerprint_v1(jsonb);
set local role ledger_store_owner;
drop function ledger.investment_correction_matches_v1(
  uuid, uuid, uuid, uuid, integer, uuid, uuid
);
drop function ledger.link_investment_correction_v1(
  uuid, integer, uuid, uuid, uuid, uuid, text, text, date, text
);
reset role;

drop function investments.complete_received_fund_distribution_v1(jsonb, uuid, text);
drop function investments.prepare_received_fund_distribution_v1(jsonb, text);
drop function investments.get_received_fund_distribution_replay_v1(jsonb, text);
drop function investments.received_fund_distribution_fingerprint_v1(jsonb);

drop function investments.complete_share_purchase_v1(jsonb, uuid, jsonb, text);
drop function investments.prepare_share_purchase_v1(jsonb, text);
drop function investments.get_share_purchase_replay_v1(jsonb, text);
drop function investments.share_purchase_fingerprint_v1(jsonb);
drop function investments.complete_share_sale_v1(jsonb, uuid, text);
drop function investments.prepare_share_sale_v1(jsonb, text);
drop function investments.get_share_sale_replay_v1(jsonb, text);
drop function investments.share_sale_fingerprint_v1(jsonb);
drop function investments.complete_received_dividend_v1(jsonb, uuid, text);
drop function investments.prepare_received_dividend_v1(jsonb, text);
drop function investments.get_received_dividend_replay_v1(jsonb, text);
drop function investments.received_dividend_fingerprint_v1(jsonb);

drop table investments.corrections;
drop table investments.received_fund_distributions;

alter table investments.positions
  drop constraint positions_kind_supported_check,
  drop constraint positions_classification_supported_check,
  drop constraint positions_fund_evidence_check,
  drop constraint positions_tax_basis_nonnegative_check,
  drop column accounting_classification,
  drop column fund_equity_ratio_basis_points,
  drop column fund_tax_statement_reference,
  drop column tax_basis,
  add constraint positions_kind_check check (
    kind = 'norwegian_private_company'
  );

alter table investments.acquisition_lots
  drop constraint acquisition_lots_tax_basis_check,
  drop constraint acquisition_lots_fund_ratio_check,
  drop column original_tax_basis,
  drop column remaining_tax_basis,
  drop column acquisition_year_fund_equity_ratio_basis_points,
  drop column fund_tax_statement_reference;

alter table investments.share_purchases
  drop constraint share_purchases_investment_kind_supported_check,
  drop constraint share_purchases_costs_check,
  drop constraint share_purchases_evidence_digest_check,
  drop column accounting_classification,
  drop column transaction_costs,
  drop column capitalized_cost,
  drop column fund_equity_ratio_basis_points,
  drop column fund_tax_statement_reference,
  drop column evidence_mode,
  drop column evidence_reference,
  drop column evidence_digest,
  drop column owner_attested,
  drop column calculation_id,
  add constraint share_purchases_investment_kind_check check (
    investment_kind = 'norwegian_private_company'
  );

alter table investments.share_sales
  drop constraint share_sales_amounts_check,
  drop constraint share_sales_fund_ratio_check,
  drop constraint share_sales_digest_check,
  drop column transaction_costs,
  drop column net_proceeds,
  drop column fifo_tax_basis_reduction,
  drop column book_gain_or_loss,
  drop column tax_gain_or_loss,
  drop column exempt_gain,
  drop column taxable_gain,
  drop column non_deductible_loss,
  drop column deductible_loss,
  drop column remaining_tax_basis,
  drop column sale_year_fund_equity_ratio_basis_points,
  drop column fund_tax_statement_reference,
  drop column evidence_mode,
  drop column evidence_reference,
  drop column evidence_digest,
  drop column owner_attested,
  drop column calculation_id;

alter table investments.share_sale_allocations
  drop column allocated_book_cost_basis,
  drop column allocated_tax_basis,
  drop column allocated_net_proceeds,
  drop column average_fund_equity_ratio_basis_points,
  drop column tax_gain_or_loss,
  drop column exempt_gain,
  drop column taxable_gain,
  drop column non_deductible_loss,
  drop column deductible_loss;

alter table investments.received_dividends
  drop constraint received_dividends_group_evidence_check,
  drop constraint received_dividends_calculation_check,
  drop constraint received_dividends_digest_check,
  drop column lawful_dividend_confirmed,
  drop column group_exception_claimed,
  drop column year_end_ownership_basis_points,
  drop column year_end_voting_basis_points,
  drop column group_evidence_reference,
  drop column group_exception_applied,
  drop column evidence_mode,
  drop column evidence_reference,
  drop column evidence_digest,
  drop column owner_attested,
  drop column calculation_id,
  alter column taxable_add_back set not null;

alter function investments.rollback_190_share_purchase_fingerprint_v1(jsonb)
  rename to share_purchase_fingerprint_v1;
alter function investments.rollback_190_get_share_purchase_replay_v1(jsonb, text)
  rename to get_share_purchase_replay_v1;
alter function investments.rollback_190_prepare_share_purchase_v1(jsonb, text)
  rename to prepare_share_purchase_v1;
alter function investments.rollback_190_complete_share_purchase_v1(jsonb, uuid, jsonb, text)
  rename to complete_share_purchase_v1;
alter function investments.rollback_190_share_sale_fingerprint_v1(jsonb)
  rename to share_sale_fingerprint_v1;
alter function investments.rollback_190_get_share_sale_replay_v1(jsonb, text)
  rename to get_share_sale_replay_v1;
alter function investments.rollback_190_prepare_share_sale_v1(jsonb, text)
  rename to prepare_share_sale_v1;
alter function investments.rollback_190_complete_share_sale_v1(jsonb, uuid, text)
  rename to complete_share_sale_v1;
alter function investments.rollback_190_received_dividend_fingerprint_v1(jsonb)
  rename to received_dividend_fingerprint_v1;
alter function investments.rollback_190_get_received_dividend_replay_v1(jsonb, text)
  rename to get_received_dividend_replay_v1;
alter function investments.rollback_190_prepare_received_dividend_v1(jsonb, text)
  rename to prepare_received_dividend_v1;
alter function investments.rollback_190_complete_received_dividend_v1(jsonb, uuid, text)
  rename to complete_received_dividend_v1;

do $membership_revoke$
begin
  execute pg_catalog.format(
    'revoke investments_store_owner, investments_workflow_executor, ledger_store_owner, company_archive_projection_executor from %I',
    current_user
  );
end
$membership_revoke$;

commit;
