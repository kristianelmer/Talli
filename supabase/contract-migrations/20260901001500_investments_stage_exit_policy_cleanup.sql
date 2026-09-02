-- CONTRACT RELEASE ARTIFACT: investments stage-exit policy cleanup, issue #143.
-- Apply only after 20260831193000_investments_stage_exit.sql. This idempotent
-- follow-up removes overlap policies left by an earlier hosted stage-exit build.

begin;

do $investments_policy_cleanup_membership$
begin
  execute pg_catalog.format(
    'grant investments_store_owner to %I', current_user
  );
end
$investments_policy_cleanup_membership$;

select pg_catalog.pg_advisory_xact_lock(
  pg_catalog.hashtextextended('talli:investments:stage-exit:v1', 0)
);

drop policy if exists "investments successor mirrors actions"
  on public.holding_actions;
drop policy if exists "investments successor appends audit"
  on public.audit_events;

set local role investments_store_owner;
drop policy if exists investments_positions_workflow_insert
  on investments.positions;
drop policy if exists investments_positions_workflow_update
  on investments.positions;
drop policy if exists investments_lots_workflow_insert
  on investments.acquisition_lots;
reset role;

do $investments_policy_cleanup_membership_revoke$
begin
  execute pg_catalog.format(
    'revoke investments_store_owner from %I', current_user
  );
end
$investments_policy_cleanup_membership_revoke$;

commit;
