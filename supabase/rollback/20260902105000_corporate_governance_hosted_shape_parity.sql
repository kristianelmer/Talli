-- The parity repair is additive and intentionally retained during rollback.
-- Dropping event identity or occurrence time would discard immutable evidence
-- and invalidate both the #148 lifecycle reader and its safe contract rollback.
begin;

set local lock_timeout = '5s';
set local statement_timeout = '120s';

do $required_shape$
begin
  if not exists (
    select 1
    from information_schema.columns
    where table_schema = 'corporate_governance'
      and table_name = 'owner_dividend_finalizations'
      and column_name = 'event_id'
  ) or not exists (
    select 1
    from information_schema.columns
    where table_schema = 'corporate_governance'
      and table_name = 'owner_dividend_finalizations'
      and column_name = 'occurred_at'
  ) or not exists (
    select 1
    from information_schema.columns
    where table_schema = 'corporate_governance'
      and table_name = 'owner_dividend_payments'
      and column_name = 'occurred_at'
  ) then
    raise exception 'corporate_governance_hosted_shape_parity_missing';
  end if;
end
$required_shape$;

commit;
