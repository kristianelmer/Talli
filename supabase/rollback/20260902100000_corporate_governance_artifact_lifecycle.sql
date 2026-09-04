-- Roll back #148 owner-dividend lifecycle expansion without losing new evidence.
begin;

set local lock_timeout = '5s';
set local statement_timeout = '120s';

do $membership$
begin
  execute pg_catalog.format(
    'grant corporate_governance_store_owner, ledger_store_owner, '
      || 'backend_system_annual_data_reader, '
      || 'corporate_governance_workflow_executor to %I',
    current_user
  );
  execute pg_catalog.format(
    'grant documents_store_owner to %I with set true', current_user
  );
end
$membership$;

select pg_catalog.set_config(
  'talli.corporate_governance_lifecycle_principal', current_user, true
);

insert into public.corporate_document_artifacts (
  id, company_id, income_year, set_id, artifact_kind, variant,
  document_id, content_sha256, byte_length, mime_type, storage_key,
  supersedes_artifact_id, created_by, created_at
)
select
  artifact.id, artifact.company_id, artifact.income_year,
  artifact.document_set_id, artifact.artifact_kind, artifact.variant,
  artifact.document_id, artifact.content_sha256, artifact.byte_length,
  document.content_type, document.storage_key,
  artifact.supersedes_artifact_id, artifact.created_by, artifact.created_at
from corporate_governance.owner_dividend_artifacts artifact
join public.documents document on document.id = artifact.document_id
where artifact.variant = 'signed_owner_attested'
on conflict (id) do nothing;

insert into public.corporate_document_events (
  id, company_id, income_year, decision_id, set_id, artifact_id,
  event_kind, actor_id, occurred_at, decision_hash, content_sha256,
  metadata, idempotency_key, created_at
)
select
  event.id, event.company_id, event.income_year, event.decision_id,
  event.document_set_id, event.artifact_id, event.event_kind,
  event.created_by, event.occurred_at, event.decision_hash,
  event.content_sha256, event.metadata,
  'canonical-event:' || event.id::text, event.created_at
from corporate_governance.owner_dividend_events event
where event.event_kind in (
  'signing_requested', 'signed_copy_attested', 'superseded', 'rejected'
)
on conflict (id) do nothing;

set local role corporate_governance_workflow_executor;
drop function if exists
  backend_system.register_corporate_governance_documents_v1(
    text, jsonb, text
  );
drop function if exists
  backend_system.attest_corporate_governance_signed_artifact_v1(
    text, jsonb, text
  );
drop function if exists
  backend_system.complete_corporate_governance_shareholder_loan_v1(
    jsonb, text
  );
drop function if exists
  backend_system.register_corporate_governance_evidence_v1(
    text, uuid, uuid, uuid, integer, text, text, text, bigint, uuid
  );
reset role;

set local role corporate_governance_store_owner;

drop function if exists
  corporate_governance.record_owner_dividend_event_v1(jsonb, text);
drop function if exists
  corporate_governance.attest_owner_dividend_signed_artifact_v1(jsonb, text);
reset role;

set local role documents_store_owner;
delete from documents.evidence_references
where source_capability = 'corporate_governance';
revoke execute on function documents.register_evidence_reference_v1(
  text, text, uuid, uuid, uuid, integer, text, text, text, bigint, uuid
) from corporate_governance_workflow_executor;
revoke usage on schema documents from corporate_governance_workflow_executor;
reset role;

set local role backend_system_annual_data_reader;
drop function if exists
  backend_system.list_annual_data_legacy_v1(uuid, integer, text);
reset role;
revoke usage on schema backend_system
from corporate_governance_workflow_executor;
drop policy if exists "annual data compatibility reader reads owner facts"
on public.annual_data;
revoke select on public.annual_data
from backend_system_annual_data_reader;
revoke usage on schema public
from backend_system_annual_data_reader;
revoke execute on function
  public.company_access_auth_uid_v1(),
  public.company_access_is_accepted_owner_v1(uuid)
from backend_system_annual_data_reader;
set local role ledger_store_owner;
revoke usage on schema backend_system
from backend_system_annual_data_reader;
reset role;
set local role corporate_governance_store_owner;
drop function if exists
  corporate_governance.read_corporate_lifecycle_v1(uuid[], uuid, text);

do $restore_owner_lifecycle$
declare
  v_definition text;
begin
  v_definition := pg_catalog.pg_get_functiondef(
    'corporate_governance.owner_dividend_lifecycle_pre148_v1(uuid,boolean)'::regprocedure
  );
  v_definition := pg_catalog.replace(
    v_definition,
    'FUNCTION corporate_governance.owner_dividend_lifecycle_pre148_v1',
    'FUNCTION corporate_governance.owner_dividend_lifecycle_v1'
  );
  execute v_definition;
end
$restore_owner_lifecycle$;

do $restore_owner_finalization_preparation$
declare
  v_definition text;
begin
  v_definition := pg_catalog.pg_get_functiondef(
    'corporate_governance.prepare_owner_dividend_finalization_pre148_v1(jsonb,text)'::regprocedure
  );
  v_definition := pg_catalog.replace(
    v_definition,
    'FUNCTION corporate_governance.prepare_owner_dividend_finalization_pre148_v1',
    'FUNCTION corporate_governance.prepare_owner_dividend_finalization_v1'
  );
  execute v_definition;
end
$restore_owner_finalization_preparation$;

do $restore_owner_finalization_completion$
declare
  v_definition text;
begin
  if pg_catalog.to_regprocedure(
    'corporate_governance.complete_owner_dividend_finalization_pre148_v1(jsonb,text)'
  ) is null then
    return;
  end if;
  v_definition := pg_catalog.pg_get_functiondef(
    pg_catalog.to_regprocedure(
      'corporate_governance.complete_owner_dividend_finalization_pre148_v1(jsonb,text)'
    )
  );
  v_definition := pg_catalog.replace(
    v_definition,
    'FUNCTION corporate_governance.complete_owner_dividend_finalization_pre148_v1',
    'FUNCTION corporate_governance.complete_owner_dividend_finalization_v1'
  );
  execute v_definition;
end
$restore_owner_finalization_completion$;

do $restore_owner_payment_completion$
declare
  v_definition text;
begin
  if pg_catalog.to_regprocedure(
    'corporate_governance.complete_owner_dividend_payment_pre148_v1(jsonb,text)'
  ) is null then
    return;
  end if;
  v_definition := pg_catalog.pg_get_functiondef(
    pg_catalog.to_regprocedure(
      'corporate_governance.complete_owner_dividend_payment_pre148_v1(jsonb,text)'
    )
  );
  v_definition := pg_catalog.replace(
    v_definition,
    'FUNCTION corporate_governance.complete_owner_dividend_payment_pre148_v1',
    'FUNCTION corporate_governance.complete_owner_dividend_payment_v1'
  );
  execute v_definition;
end
$restore_owner_payment_completion$;

drop function
  corporate_governance.owner_dividend_lifecycle_pre148_v1(uuid, boolean);
drop function
  corporate_governance.prepare_owner_dividend_finalization_pre148_v1(
    jsonb, text
  );
drop function if exists
  corporate_governance.complete_owner_dividend_finalization_pre148_v1(
    jsonb, text
  );
drop function if exists
  corporate_governance.complete_owner_dividend_payment_pre148_v1(
    jsonb, text
  );

drop trigger owner_dividend_events_immutable
  on corporate_governance.owner_dividend_events;
drop trigger owner_dividend_artifacts_immutable
  on corporate_governance.owner_dividend_artifacts;
reset role;
delete from corporate_governance.owner_dividend_events
where event_kind in (
  'signing_requested', 'signed_copy_attested', 'superseded', 'rejected'
);
set local role corporate_governance_store_owner;
drop index if exists corporate_governance.owner_dividend_events_singleton_idx;
alter table corporate_governance.owner_dividend_events
  drop constraint if exists owner_dividend_events_signed_evidence_check,
  drop constraint if exists owner_dividend_events_artifact_fk,
  drop constraint if exists owner_dividend_events_metadata_check,
  drop constraint if exists owner_dividend_events_content_sha256_check,
  drop constraint if exists owner_dividend_events_event_kind_check;
alter table corporate_governance.owner_dividend_events
  drop column metadata,
  drop column content_sha256,
  drop column artifact_id,
  drop column occurred_at;
alter table corporate_governance.owner_dividend_events
  add constraint owner_dividend_events_event_kind_check check (
    event_kind in ('documents_registered', 'facts_approved')
  );

reset role;
delete from corporate_governance.owner_dividend_artifacts
where variant = 'signed_owner_attested';
set local role corporate_governance_store_owner;
alter table corporate_governance.owner_dividend_artifacts
  drop constraint if exists owner_dividend_artifacts_variant_supersedes_check,
  drop constraint if exists owner_dividend_artifacts_supersedes_check,
  drop constraint if exists owner_dividend_artifacts_supersedes_fk,
  drop constraint if exists owner_dividend_artifacts_variant_unique,
  drop constraint if exists owner_dividend_artifacts_variant_check;
alter table corporate_governance.owner_dividend_artifacts
  drop column supersedes_artifact_id,
  drop column variant;
alter table corporate_governance.owner_dividend_artifacts
  add constraint owner_dividend_artifacts_decision_id_artifact_kind_key unique (
    decision_id, artifact_kind
  );
alter table corporate_governance.owner_dividend_decisions
  drop column supersedes_document_set_id,
  drop column supersedes_decision_id;

create trigger owner_dividend_events_immutable
before update or delete on corporate_governance.owner_dividend_events
for each row execute function
  corporate_governance.prevent_corporate_governance_mutation();
create trigger owner_dividend_artifacts_immutable
before update or delete on corporate_governance.owner_dividend_artifacts
for each row execute function
  corporate_governance.prevent_corporate_governance_mutation();

reset role;

do $membership_revoke$
begin
  execute pg_catalog.format(
    'revoke corporate_governance_store_owner, ledger_store_owner, '
      || 'backend_system_annual_data_reader, '
      || 'corporate_governance_workflow_executor, '
      || 'company_access_executor from %I',
    pg_catalog.current_setting(
      'talli.corporate_governance_lifecycle_principal'
    )
  );
  execute pg_catalog.format(
    'revoke documents_store_owner from %I',
    pg_catalog.current_setting(
      'talli.corporate_governance_lifecycle_principal'
    )
  );
end
$membership_revoke$;

drop role backend_system_annual_data_reader;

commit;
