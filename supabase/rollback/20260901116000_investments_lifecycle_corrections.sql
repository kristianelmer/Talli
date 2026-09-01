-- Remove correction support only while no lifecycle correction exists.
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
  pg_catalog.hashtextextended('talli:investments:lifecycle-corrections:v2', 0)
);

do $guard$
begin
  if exists (select 1 from investments.lifecycle_corrections)
    or exists (
      select 1 from investments.cash_settlements
      where supersedes_settlement_id is not null
    )
  then raise exception 'investments_lifecycle_corrections_rollback_unsafe'; end if;
end
$guard$;

revoke all on function
  investments.get_lifecycle_correction_replay_v2(jsonb, text),
  investments.prepare_economic_event_correction_v2(jsonb, text),
  investments.prepare_cash_settlement_correction_v2(jsonb, text),
  investments.complete_lifecycle_correction_v2(
    jsonb, uuid, uuid, uuid, text
  )
from investments_workflow_executor;

set local role investments_store_owner;
drop function if exists investments.complete_lifecycle_correction_v2(
  jsonb, uuid, uuid, uuid, text
);
drop function if exists investments.prepare_cash_settlement_correction_v2(
  jsonb, text
);
drop function if exists investments.prepare_economic_event_correction_v2(
  jsonb, text
);
drop function if exists investments.get_lifecycle_correction_replay_v2(jsonb, text);
drop function if exists investments.record_lifecycle_correction_sources_v2(
  uuid, uuid, jsonb
);
drop function if exists investments.lifecycle_cash_evidence_is_valid_v2(jsonb);
drop function if exists investments.lifecycle_correction_fingerprint_v2(jsonb);
drop table investments.lifecycle_correction_sources;
drop table investments.lifecycle_corrections;
alter table investments.cash_settlements
  drop constraint cash_settlements_supersedes_same_event_fk,
  drop constraint cash_settlements_supersedes_distinct_check,
  drop constraint cash_settlements_settlement_company_event_year_key,
  drop column supersedes_settlement_id;
alter table investments.cash_settlements
  add constraint cash_settlements_event_id_key unique (event_id);
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
