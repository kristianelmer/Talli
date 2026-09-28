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
      or not exists (
        select 1 from public.corporate_document_events evidence
        where evidence.id = source.event_id
          and evidence.decision_id = source.decision_id
          and evidence.event_kind = 'finalized'
          and evidence.occurred_at = source.occurred_at
          and evidence.created_at = source.created_at
      )
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
        and target.occurred_at = source.occurred_at
        and target.created_at = source.created_at
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

-- Later guarded reporting/writer entry points add these cross-owner grants.
-- Retire only Governance's authority; Ledger keeps its own guards and readers.
do $revoke_guard_successors$
begin
  set local role ledger_store_owner;
  if pg_catalog.to_regprocedure(
    'ledger.acquire_company_write_guard_v1(uuid,text)'
  ) is not null then
    revoke execute on function ledger.acquire_company_write_guard_v1(uuid,text)
      from corporate_governance_store_owner;
  end if;
  if pg_catalog.to_regprocedure(
    'ledger.list_entry_amendments_v1(uuid,text)'
  ) is not null then
    revoke execute on function ledger.list_entry_amendments_v1(uuid,text)
      from corporate_governance_store_owner;
  end if;
  revoke usage on schema ledger from corporate_governance_store_owner;
  reset role;
end
$revoke_guard_successors$;

-- Evidence assertions survive this rollback under their own capability owners.
-- Remove this retiring caller's grants without changing any other consumer.
do $revoke_evidence_successors$
declare
  item record;
  signature text;
  borrowed boolean;
  prior jsonb;
begin
  for item in select * from (values
    ('documents_store_owner', 'documents', array[
      'documents.assert_retained_metadata_v1(text,text)',
      'documents.assert_retained_original_v1(uuid,uuid,uuid,integer,text,text,integer,timestamptz,text)'
    ]),
    ('shareholder_register_filing_store_owner', 'shareholder_register_filing', array[
      'shareholder_register_filing.assert_current_register_observation_v1(uuid,uuid,integer,integer,text,text)'
    ])
  ) evidence(owner_role, schema_name, signatures) loop
    if pg_catalog.to_regnamespace(item.schema_name) is null then continue; end if;
    borrowed := not pg_catalog.pg_has_role(current_user, item.owner_role, 'SET');
    prior := null;
    if borrowed then
      select pg_catalog.jsonb_build_object('admin', m.admin_option,
        'inherit', m.inherit_option, 'set', m.set_option) into prior
      from pg_catalog.pg_auth_members m
      where m.roleid = pg_catalog.to_regrole(item.owner_role)
        and m.member = pg_catalog.to_regrole(current_user) and m.grantor = m.member;
      execute pg_catalog.format('grant %I to %I with set true granted by %I',
        item.owner_role, current_user, current_user);
    end if;
    execute pg_catalog.format('set local role %I', item.owner_role);
    foreach signature in array item.signatures loop
      if pg_catalog.to_regprocedure(signature) is not null then
        execute pg_catalog.format('revoke execute on function %s from corporate_governance_workflow_executor', signature);
      end if;
    end loop;
    execute pg_catalog.format('revoke usage on schema %I from corporate_governance_workflow_executor', item.schema_name);
    reset role;
    if borrowed then
      execute pg_catalog.format('revoke %I from %I granted by %I', item.owner_role, current_user, current_user);
      if prior is not null then
        execute pg_catalog.format('grant %I to %I with admin %s, inherit %s, set %s granted by %I',
          item.owner_role, current_user, prior->>'admin', prior->>'inherit', prior->>'set', current_user);
      end if;
    end if;
  end loop;
end
$revoke_evidence_successors$;

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

do $revoke_ledger_projections$
begin
  if pg_catalog.to_regprocedure(
    'backend_system.owner_dividend_signed_evidence_v1(uuid,uuid,uuid,integer,text)'
  ) is not null then
    revoke execute on function
      backend_system.owner_dividend_signed_evidence_v1(
        uuid, uuid, uuid, integer, text
      ) from corporate_governance_store_owner;
  end if;
  if pg_catalog.to_regprocedure(
    'backend_system.project_owner_dividend_finalization_v1(jsonb,text,jsonb,text)'
  ) is not null then
    revoke execute on function
      backend_system.project_owner_dividend_finalization_v1(
        jsonb, text, jsonb, text
      ) from corporate_governance_store_owner;
  end if;
  if pg_catalog.to_regprocedure(
    'backend_system.project_owner_dividend_payment_v1(jsonb,bigint,text,text)'
  ) is not null then
    revoke execute on function
      backend_system.project_owner_dividend_payment_v1(
        jsonb, bigint, text, text
      ) from corporate_governance_store_owner;
  end if;
end
$revoke_ledger_projections$;
drop function if exists backend_system.project_owner_dividend_payment_v1(
  jsonb, bigint, text, text
);
drop function if exists backend_system.project_owner_dividend_finalization_v1(
  jsonb, text, jsonb, text
);
drop function if exists backend_system.owner_dividend_signed_evidence_v1(
  uuid, uuid, uuid, integer, text
);
revoke usage on schema backend_system from corporate_governance_store_owner;

set local role corporate_governance_store_owner;
-- The later contract rollback retains reviewed writer definitions only so it
-- can be re-cut over. A chained rollback beyond this capability boundary must
-- discard those private backups before dropping the owned schema.
drop function if exists
  corporate_governance.prepare_owner_dividend_finalization_contract_v1(
    jsonb, text
  );
drop function if exists
  corporate_governance.complete_owner_dividend_finalization_contract_v1(
    jsonb, text
  );
drop function if exists
  corporate_governance.prepare_owner_dividend_payment_contract_v1(jsonb, text);
drop function if exists
  corporate_governance.complete_owner_dividend_payment_contract_v1(jsonb, text);
drop function if exists
  corporate_governance.finalize_annual_close_contract_v1(jsonb, text);
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
-- The complete capability rollback also retires its additive guard entry points.
-- All guarded Governance tables are gone before the trigger function is dropped.
-- RESTRICT is intentional: unexpected dependencies must still abort rollback.
drop function if exists corporate_governance.read_guarded_reporting_year_inputs_v1(
  uuid, integer, text
);
drop function if exists corporate_governance.lock_company_write_v1();
drop function if exists corporate_governance.acquire_company_write_guard_v1(uuid,text);
drop schema corporate_governance;
reset role;
revoke execute on function
  public.company_access_auth_uid_v1(),
  public.company_access_auth_jwt_v1(),
  public.company_access_has_current_agreement_v1(uuid),
  public.company_access_is_accepted_owner_v1(uuid),
  public.company_access_company_year_allows_consequential_v1(uuid, integer)
from corporate_governance_store_owner;
do $revoke_predecessor_assertion$
begin
  if pg_catalog.to_regprocedure(
    'public.assert_corporate_decision_persisted_facts(uuid,integer,text,uuid,jsonb,text)'
  ) is not null then
    revoke execute on function public.assert_corporate_decision_persisted_facts(
      uuid, integer, text, uuid, jsonb, text
    ) from corporate_governance_store_owner;
  end if;
end
$revoke_predecessor_assertion$;
do $revoke_company_guard$
begin
  if pg_catalog.to_regprocedure(
    'public.company_archive_lock_company_v1(uuid)'
  ) is not null then
    revoke execute on function public.company_archive_lock_company_v1(uuid)
      from corporate_governance_store_owner;
  end if;
end
$revoke_company_guard$;
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
