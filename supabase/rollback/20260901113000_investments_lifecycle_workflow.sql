-- Remove only an unused lifecycle workflow; never erase recognized facts.
begin;

set local lock_timeout = '5s';
set local statement_timeout = '120s';

do $membership$
begin
  execute pg_catalog.format(
    'grant investments_store_owner, investments_workflow_executor, ledger_store_owner, company_archive_projection_executor to %I',
    current_user
  );
end
$membership$;

revoke execute on function
  investments.get_share_purchase_recognition_replay_v2(jsonb, text),
  investments.prepare_share_purchase_recognition_v2(jsonb, text),
  investments.complete_share_purchase_recognition_v2(
    jsonb, uuid, jsonb, text
  ),
  investments.get_cash_settlement_replay_v2(jsonb, text),
  investments.prepare_cash_settlement_v2(jsonb, text),
  investments.complete_cash_settlement_v2(jsonb, uuid, jsonb, text),
  ledger.post_investment_lifecycle_entry_v2(
    text, uuid, integer, text, text, jsonb, text, text, text, text,
    date, text, jsonb
  )
from investments_workflow_executor;

do $guard$
begin
  if exists (
    select 1 from investments.share_purchase_recognitions
  ) or exists (
    select 1 from investments.cash_settlements
  ) or exists (
    select 1 from investments.event_sources
  ) then
    raise exception 'investments_lifecycle_workflow_rollback_unsafe';
  end if;
end
$guard$;

drop trigger if exists company_archive_track_investments_cash_settlements
  on investments.cash_settlements;
drop trigger if exists company_archive_track_investments_economic_events
  on investments.economic_events;

drop function if exists investments.complete_cash_settlement_v2(
  jsonb, uuid, jsonb, text
);
drop function if exists investments.prepare_cash_settlement_v2(jsonb, text);
drop function if exists investments.get_cash_settlement_replay_v2(jsonb, text);
drop function if exists investments.complete_share_purchase_recognition_v2(
  jsonb, uuid, jsonb, text
);
drop function if exists investments.prepare_share_purchase_recognition_v2(
  jsonb, text
);
drop function if exists investments.get_share_purchase_recognition_replay_v2(
  jsonb, text
);
drop function if exists investments.cash_settlement_fingerprint_v2(jsonb);
drop function if exists investments.share_purchase_recognition_fingerprint_v2(
  jsonb
);
drop function if exists ledger.investment_lifecycle_entry_matches_v2(
  uuid, uuid, integer, text, uuid, text, date, jsonb
);
drop function if exists ledger.post_investment_lifecycle_entry_v2(
  text, uuid, integer, text, text, jsonb, text, text, text, text,
  date, text, jsonb
);

alter table investments.cash_settlements
  drop constraint cash_settlements_registered_fact_fk;
alter table investments.event_sources
  drop constraint event_sources_registered_fact_fk;
drop table investments.share_purchase_recognitions;
drop table investments.source_fact_registry;

alter table investments.economic_events
  drop constraint economic_events_settlement_balance_kind_check;
alter table investments.economic_events
  add constraint economic_events_settlement_balance_kind_check check (
    settlement_balance_kind in (
      'purchase_payable', 'sale_receivable', 'income_receivable'
    )
  );

do $membership_revoke$
begin
  execute pg_catalog.format(
    'revoke investments_store_owner, investments_workflow_executor, ledger_store_owner, company_archive_projection_executor from %I',
    current_user
  );
end
$membership_revoke$;

commit;
