-- Remove empty income lifecycle routines and restore the predecessor balance kind.
begin;

set local lock_timeout = '5s';
set local statement_timeout = '120s';

do $membership$
begin
  execute pg_catalog.format(
    'grant investments_store_owner, investments_workflow_executor to %I',
    current_user
  );
end
$membership$;

select pg_catalog.pg_advisory_xact_lock(
  pg_catalog.hashtextextended('talli:investments:income-lifecycle:v2', 0)
);

do $guard$
begin
  if exists (
    select 1 from investments.economic_events event
    where event.event_kind in (
      'dividend_received', 'fund_distribution_received'
    ) and event.policy_version = 'domestic_2026_v2'
  ) then
    raise exception 'investments_income_lifecycle_rollback_unsafe';
  end if;
end
$guard$;

revoke all on function
  investments.get_received_dividend_recognition_replay_v2(jsonb, text),
  investments.get_received_fund_distribution_recognition_replay_v2(jsonb, text),
  investments.prepare_received_dividend_recognition_v2(jsonb, text),
  investments.prepare_received_fund_distribution_recognition_v2(jsonb, text),
  investments.complete_received_dividend_recognition_v2(
    jsonb, uuid, jsonb, text
  ),
  investments.complete_received_fund_distribution_recognition_v2(
    jsonb, uuid, jsonb, text
  )
from investments_workflow_executor;

set local role investments_store_owner;
drop function if exists investments.complete_received_fund_distribution_recognition_v2(
  jsonb, uuid, jsonb, text
);
drop function if exists investments.complete_received_dividend_recognition_v2(
  jsonb, uuid, jsonb, text
);
drop function if exists investments.prepare_received_fund_distribution_recognition_v2(
  jsonb, text
);
drop function if exists investments.prepare_received_dividend_recognition_v2(
  jsonb, text
);
drop function if exists investments.get_received_fund_distribution_recognition_replay_v2(
  jsonb, text
);
drop function if exists investments.get_received_dividend_recognition_replay_v2(
  jsonb, text
);
drop function if exists investments.received_fund_recognition_fingerprint_v2(jsonb);
drop function if exists investments.received_dividend_recognition_fingerprint_v2(jsonb);
drop table investments.received_fund_distribution_recognitions;
drop table investments.received_dividend_recognitions;
reset role;

do $membership_revoke$
begin
  execute pg_catalog.format(
    'revoke investments_store_owner, investments_workflow_executor from %I',
    current_user
  );
end
$membership_revoke$;

commit;
