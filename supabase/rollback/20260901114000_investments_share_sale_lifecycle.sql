-- Remove the sale-recognition RPCs only while no canonical sale exists.
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
  pg_catalog.hashtextextended('talli:investments:share-sale-lifecycle:v2', 0)
);

do $guard$
begin
  if exists (
    select 1 from investments.economic_events event
    where event.event_kind = 'share_sale'
      and event.policy_version = 'domestic_2026_v2'
  ) then
    raise exception 'investments_share_sale_lifecycle_rollback_unsafe';
  end if;
end
$guard$;

revoke all on function
  investments.get_share_sale_recognition_replay_v2(jsonb, text),
  investments.prepare_share_sale_recognition_v2(jsonb, text),
  investments.complete_share_sale_recognition_v2(jsonb, uuid, jsonb, text)
from investments_workflow_executor;

set local role investments_store_owner;
drop function if exists investments.complete_share_sale_recognition_v2(
  jsonb, uuid, jsonb, text
);
drop function if exists investments.prepare_share_sale_recognition_v2(jsonb, text);
drop function if exists investments.get_share_sale_recognition_replay_v2(jsonb, text);
drop function if exists investments.share_sale_recognition_fingerprint_v2(jsonb);
drop function if exists investments.record_lifecycle_document_sources_v2(uuid, uuid, jsonb);
drop function if exists investments.lifecycle_document_evidence_is_valid_v2(jsonb);
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
