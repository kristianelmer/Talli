begin;

do $membership$
begin
  execute pg_catalog.format(
    'grant investments_store_owner to %I', current_user
  );
end
$membership$;

do $rollback_guard$
begin
  if exists (select 1 from investments.position_boundary_confirmations) then
    raise exception 'rollback_refused_investment_boundary_confirmations_exist';
  end if;
end;
$rollback_guard$;

revoke all on function
  investments.complete_share_purchase_recognition_v3(jsonb, uuid, jsonb, text),
  investments.prepare_share_sale_recognition_v3(jsonb, text),
  investments.prepare_received_dividend_recognition_v3(jsonb, text),
  investments.prepare_received_fund_distribution_recognition_v3(jsonb, text),
  investments.prepare_year_end_measurement_v4(jsonb, text)
from investments_workflow_executor;

grant execute on function
  investments.complete_share_purchase_recognition_v2(jsonb, uuid, jsonb, text),
  investments.prepare_share_sale_recognition_v2(jsonb, text),
  investments.prepare_received_dividend_recognition_v2(jsonb, text),
  investments.prepare_received_fund_distribution_recognition_v2(jsonb, text),
  investments.prepare_year_end_measurement_v3(jsonb, text)
to investments_workflow_executor;

drop function investments.prepare_year_end_measurement_v4(jsonb, text);
drop function investments.prepare_received_fund_distribution_recognition_v3(jsonb, text);
drop function investments.prepare_received_dividend_recognition_v3(jsonb, text);
drop function investments.prepare_share_sale_recognition_v3(jsonb, text);
drop function investments.complete_share_purchase_recognition_v3(jsonb, uuid, jsonb, text);
drop function investments.assert_position_boundary_supported_v1(uuid, uuid, text);
drop table investments.position_boundary_confirmations;

do $membership_revoke$
begin
  execute pg_catalog.format(
    'revoke investments_store_owner from %I', current_user
  );
end
$membership_revoke$;

commit;
