begin;

set local lock_timeout = '5s';

do $membership$
begin
  execute pg_catalog.format('grant banking_store_owner to %I', current_user);
end
$membership$;

revoke execute on function banking.claim_transaction_for_external_action_v1(
  jsonb, uuid, text
) from public, anon, authenticated, service_role, banking_executor,
  banking_workflow_executor, investments_workflow_executor,
  talli_banking_backend;

set local role banking_store_owner;
drop function banking.claim_transaction_for_external_action_v1(
  jsonb, uuid, text
);
reset role;

do $membership_revoke$
begin
  execute pg_catalog.format('revoke banking_store_owner from %I', current_user);
end
$membership_revoke$;

commit;
