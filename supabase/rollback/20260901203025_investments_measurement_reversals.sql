begin;

do $rollback_guard$
begin
  if exists (
    select 1 from investments.year_end_measurements
    where reversal_amount > 0
  ) then
    raise exception 'investments_measurement_reversals_rollback_unsafe';
  end if;
end
$rollback_guard$;

revoke all on function
  investments.prepare_year_end_measurement_v3(jsonb, text),
  investments.complete_year_end_measurement_v3(jsonb, uuid, jsonb, text)
from investments_workflow_executor;

drop function investments.complete_year_end_measurement_v3(
  jsonb, uuid, jsonb, text
);
drop function investments.prepare_year_end_measurement_v3(jsonb, text);

commit;
