begin;

do $rollback_guard$
begin
  if exists (
    select 1 from public.audit_events
    where action = 'settled_investment_corrected'
  ) then
    raise exception 'investments_settled_event_corrections_rollback_unsafe';
  end if;
end;
$rollback_guard$;

revoke all on function
  investments.prepare_settled_event_correction_v1(jsonb, text),
  investments.complete_settled_event_correction_v1(
    jsonb, uuid, uuid, uuid, uuid, uuid, uuid, text
  ) from investments_workflow_executor;
drop function investments.complete_settled_event_correction_v1(
  jsonb, uuid, uuid, uuid, uuid, uuid, uuid, text
);
drop function investments.prepare_settled_event_correction_v1(jsonb, text);
revoke update (supersedes_settlement_id)
on investments.cash_settlements from investments_store_owner;
drop policy investments_cash_settlements_owner_supersede_update
on investments.cash_settlements;

commit;
