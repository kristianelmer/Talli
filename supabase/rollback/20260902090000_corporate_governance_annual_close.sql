-- Reverse the annual-close proposal store only while no immutable artifacts exist.
begin;

set local lock_timeout = '5s';
set local statement_timeout = '120s';

do $membership$
begin
  execute pg_catalog.format(
    'grant corporate_governance_store_owner, '
      || 'corporate_governance_workflow_executor to %I',
    current_user
  );
end
$membership$;

revoke execute on function corporate_governance.propose_annual_close_v1(
  jsonb, jsonb, jsonb, jsonb, text
) from corporate_governance_workflow_executor;
revoke execute on function
  corporate_governance.register_annual_close_documents_v1(jsonb, text)
from corporate_governance_workflow_executor;

set local role corporate_governance_store_owner;
drop function corporate_governance.register_annual_close_documents_v1(
  jsonb, text
);
drop function corporate_governance.propose_annual_close_v1(
  jsonb, jsonb, jsonb, jsonb, text
);
drop function corporate_governance.annual_close_lifecycle_v1(uuid, boolean);
drop trigger annual_close_finalizations_immutable
  on corporate_governance.annual_close_finalizations;
drop policy governance_owner_creates_annual_close_finalizations
  on corporate_governance.annual_close_finalizations;
drop policy governance_owner_reads_annual_close_finalizations
  on corporate_governance.annual_close_finalizations;
drop table corporate_governance.annual_close_finalizations;
drop trigger annual_close_events_immutable
  on corporate_governance.annual_close_events;
drop policy governance_owner_creates_annual_close_events
  on corporate_governance.annual_close_events;
drop policy governance_owner_reads_annual_close_events
  on corporate_governance.annual_close_events;
drop table corporate_governance.annual_close_events;
drop trigger annual_close_artifacts_immutable
  on corporate_governance.annual_close_artifacts;
drop policy governance_owner_creates_annual_close_artifacts
  on corporate_governance.annual_close_artifacts;
drop policy governance_owner_reads_annual_close_artifacts
  on corporate_governance.annual_close_artifacts;
drop table corporate_governance.annual_close_artifacts;
drop trigger annual_close_decisions_immutable
  on corporate_governance.annual_close_decisions;
drop policy governance_owner_creates_annual_close_decisions
  on corporate_governance.annual_close_decisions;
drop policy governance_owner_reads_annual_close_decisions
  on corporate_governance.annual_close_decisions;
drop table corporate_governance.annual_close_decisions;
reset role;

do $membership_revoke$
begin
  execute pg_catalog.format(
    'revoke corporate_governance_store_owner, '
      || 'corporate_governance_workflow_executor from %I',
    current_user
  );
end
$membership_revoke$;

commit;
