-- Reverse the owner-dividend expand only before canonical lifecycle data exists.
begin;

set local lock_timeout = '5s';
set local statement_timeout = '120s';

do $membership$
begin
  execute pg_catalog.format(
    'grant corporate_governance_store_owner, '
      || 'corporate_governance_workflow_executor, '
      || 'corporate_governance_ledger_bridge_owner, '
      || 'banking_store_owner, ledger_store_owner to %I',
    current_user
  );
end
$membership$;

do $safety$
begin
  if exists (
    select 1
    from corporate_governance.owner_dividend_decisions source
    left join public.corporate_decisions target on target.id = source.id
      and target.decision_hash = source.decision_hash
    left join public.corporate_document_sets document_set
      on document_set.id = source.document_set_id
      and document_set.decision_id = source.id
      and document_set.decision_hash = source.decision_hash
    where target.id is null or document_set.id is null
  ) or exists (
    select 1
    from corporate_governance.owner_dividend_artifacts source
    left join public.corporate_document_artifacts target
      on target.id = source.id
      and target.document_id = source.document_id
      and target.content_sha256 = source.content_sha256
      and target.byte_length = source.byte_length
    where target.id is null
  ) or exists (
    select 1
    from corporate_governance.owner_dividend_events source
    where source.event_kind = 'facts_approved'
      and not exists (
        select 1 from public.corporate_document_events target
        where target.decision_id = source.decision_id
          and target.event_kind = 'facts_approved'
          and target.decision_hash = source.decision_hash
      )
  ) or exists (
    select 1
    from corporate_governance.owner_dividend_finalizations source
    left join public.corporate_decision_finalizations target
      on target.id = source.id
      and target.decision_id = source.decision_id
      and target.ledger_entry_id = source.accounting_entry_id
      and target.holding_action_id = source.holding_action_id
      and target.decision_hash = source.decision_hash
    where target.id is null
  ) or exists (
    select 1
    from corporate_governance.owner_dividend_payments source
    where not exists (
      select 1 from public.corporate_document_events target
      where target.id = source.id
        and target.decision_id = source.decision_id
        and target.event_kind = 'payment_recorded'
        and (target.metadata ->> 'bank_transaction_id')::uuid
          = source.bank_transaction_id
        and (target.metadata ->> 'ledger_entry_id')::uuid
          = source.accounting_entry_id
        and (target.metadata ->> 'holding_action_id')::uuid
          = source.holding_action_id
    )
  ) then
    raise exception 'corporate_governance_owner_dividend_rollback_unsafe';
  end if;
end
$safety$;

do $backend_membership$
begin
  if exists (
    select 1 from pg_catalog.pg_roles
    where rolname = 'talli_ledger_backend'
  ) then
    revoke corporate_governance_workflow_executor from talli_ledger_backend;
  end if;
end
$backend_membership$;

revoke execute on function ledger.post_corporate_governance_entry_v1(
  text, uuid, integer, text, text, jsonb, text, text, text, text, uuid
) from corporate_governance_workflow_executor;
set local role corporate_governance_ledger_bridge_owner;
drop function ledger.post_corporate_governance_entry_v1(
  text, uuid, integer, text, text, jsonb, text, text, text, text, uuid
);
reset role;
revoke execute on function ledger.post_entry_with_id_v1(
  text, uuid, integer, text, text, jsonb, jsonb, boolean,
  text, text, text, text, uuid
) from corporate_governance_ledger_bridge_owner;
revoke usage on schema ledger
from corporate_governance_workflow_executor,
  corporate_governance_ledger_bridge_owner;

revoke execute on function banking.claim_owner_dividend_transaction_v1(
  jsonb, uuid, text
) from corporate_governance_workflow_executor;
revoke execute on function banking.prepare_owner_dividend_transaction_v1(
  jsonb, text
) from corporate_governance_store_owner;
set local role banking_store_owner;
drop function banking.claim_owner_dividend_transaction_v1(
  jsonb, uuid, text
);
drop function banking.prepare_owner_dividend_transaction_v1(jsonb, text);
reset role;
revoke usage on schema banking
from corporate_governance_workflow_executor,
  corporate_governance_store_owner;

revoke execute on function
  backend_system.owner_dividend_signed_evidence_v1(
    uuid, uuid, uuid, integer, text
  ),
  backend_system.project_owner_dividend_finalization_v1(
    jsonb, text, jsonb, text
  ),
  backend_system.project_owner_dividend_payment_v1(
    jsonb, bigint, text, text
  )
from corporate_governance_store_owner;
drop function backend_system.project_owner_dividend_payment_v1(
  jsonb, bigint, text, text
);
drop function backend_system.project_owner_dividend_finalization_v1(
  jsonb, text, jsonb, text
);
drop function backend_system.owner_dividend_signed_evidence_v1(
  uuid, uuid, uuid, integer, text
);
revoke usage on schema backend_system from corporate_governance_store_owner;

set local role corporate_governance_store_owner;
drop function corporate_governance.actor_company_role_v1(uuid, text);
drop function corporate_governance.propose_owner_dividend_v1(
  jsonb, jsonb, jsonb, text
);
drop function corporate_governance.register_owner_dividend_documents_v1(
  jsonb, text
);
drop function corporate_governance.approve_owner_dividend_v1(jsonb, text);
drop function corporate_governance.prepare_owner_dividend_finalization_v1(
  jsonb, text
);
drop function corporate_governance.complete_owner_dividend_finalization_v1(
  jsonb, text
);
drop function corporate_governance.prepare_owner_dividend_payment_v1(
  jsonb, text
);
drop function corporate_governance.complete_owner_dividend_payment_v1(
  jsonb, text
);
drop function corporate_governance.owner_dividend_lifecycle_v1(
  uuid, boolean
);
drop function corporate_governance.assert_owner_v1(
  uuid, integer, text, boolean
);
drop function corporate_governance.request_fingerprint_v1(jsonb);
drop table corporate_governance.owner_dividend_payments;
drop table corporate_governance.owner_dividend_finalizations;
drop table corporate_governance.owner_dividend_events;
drop table corporate_governance.owner_dividend_artifacts;
drop table corporate_governance.owner_dividend_decisions;
drop table corporate_governance.owner_dividend_accounting_policies;
drop function corporate_governance.prevent_corporate_governance_mutation();
drop schema corporate_governance;
reset role;
revoke execute on function
  public.company_access_auth_uid_v1(),
  public.company_access_auth_jwt_v1(),
  public.company_access_has_current_agreement_v1(uuid),
  public.company_access_is_accepted_owner_v1(uuid),
  public.company_access_company_year_allows_consequential_v1(uuid, integer),
  public.assert_corporate_decision_persisted_facts(
    uuid, integer, text, uuid, jsonb, text
  )
from corporate_governance_store_owner;
revoke execute on function extensions.digest(text, text)
from corporate_governance_store_owner;
revoke usage on schema extensions from corporate_governance_store_owner;
revoke usage on schema public from corporate_governance_store_owner;

do $membership_revoke$
begin
  execute pg_catalog.format(
    'revoke corporate_governance_store_owner, '
      || 'corporate_governance_workflow_executor, '
      || 'corporate_governance_ledger_bridge_owner, '
      || 'banking_store_owner, ledger_store_owner from %I',
    current_user
  );
end
$membership_revoke$;

drop role if exists corporate_governance_ledger_bridge_owner;
drop role if exists corporate_governance_workflow_executor;
drop role if exists corporate_governance_store_owner;

commit;
