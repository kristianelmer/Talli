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

-- Recreate the predecessor projection before removing the canonical store so a
-- rollback after cutover retains every decision, artifact, event, and
-- finalization. The legacy input shape is deliberately reconstructed rather
-- than leaking the Python contract's camel-case wire format into old checks.
insert into public.corporate_decisions (
  id, company_id, income_year, decision_kind, annual_close_source_id,
  source_hash, canonical_input, decision_hash, supersedes_decision_id,
  created_by, created_at
)
select
  decision.id, decision.company_id, decision.income_year, 'annual_close',
  decision.annual_close_source_id, decision.source_hash,
  coalesce(
    decision.persisted_facts -> 'legacyCanonicalInput',
    pg_catalog.jsonb_build_object(
      'decision_kind', 'annual_close',
      'company_id', decision.company_id,
      'income_year', decision.income_year,
      'organization_number',
        decision.canonical_input ->> 'organizationNumber',
      'legal_name', decision.canonical_input ->> 'legalName',
      'annual_close_source_id', decision.annual_close_source_id,
      'source_hash', decision.source_hash,
      'template_family', decision.canonical_input ->> 'templateFamily',
      'template_version', decision.canonical_input ->> 'templateVersion',
      'annual_basis_year',
        (decision.canonical_input ->> 'annualBasisYear')::integer,
      'financial_totals', pg_catalog.jsonb_build_object(
        'result_after_tax_ore', decision.canonical_input
          -> 'financialTotals' ->> 'resultAfterTaxOre',
        'equity_ore', decision.canonical_input
          -> 'financialTotals' ->> 'equityOre',
        'available_distribution_ore', decision.canonical_input
          -> 'financialTotals' ->> 'availableDistributionOre',
        'cash_ore', decision.canonical_input
          -> 'financialTotals' ->> 'cashOre'
      ),
      'board_meeting', pg_catalog.jsonb_build_object(
        'meeting_date', decision.canonical_input
          -> 'boardMeeting' ->> 'meetingDate',
        'meeting_time', decision.canonical_input
          -> 'boardMeeting' ->> 'meetingTime',
        'place', decision.canonical_input -> 'boardMeeting' ->> 'place',
        'treatment_method', decision.canonical_input
          -> 'boardMeeting' ->> 'treatmentMethod'
      ),
      'board_participants', coalesce((
        select pg_catalog.jsonb_agg(pg_catalog.jsonb_build_object(
          'participant_id', participant.item ->> 'participantId',
          'name', participant.item ->> 'name',
          'role', participant.item ->> 'role'
        ) order by participant.ordinality)
        from pg_catalog.jsonb_array_elements(
          decision.canonical_input -> 'boardParticipants'
        ) with ordinality participant(item, ordinality)
      ), '[]'::jsonb),
      'general_meeting', pg_catalog.jsonb_build_object(
        'meeting_date', decision.canonical_input
          -> 'generalMeeting' ->> 'meetingDate',
        'meeting_time', decision.canonical_input
          -> 'generalMeeting' ->> 'meetingTime',
        'place', decision.canonical_input -> 'generalMeeting' ->> 'place',
        'meeting_form', decision.canonical_input
          -> 'generalMeeting' ->> 'meetingForm',
        'chair_name', decision.canonical_input
          -> 'generalMeeting' ->> 'chairName',
        'co_signer_name', decision.canonical_input
          -> 'generalMeeting' ->> 'coSignerName'
      ),
      'shareholders', coalesce((
        select pg_catalog.jsonb_agg(pg_catalog.jsonb_build_object(
          'shareholder_id', shareholder.item ->> 'shareholderId',
          'name', shareholder.item ->> 'name',
          'share_count', shareholder.item ->> 'shareCount',
          'represented_share_count',
            shareholder.item ->> 'representedShareCount',
          'vote', shareholder.item ->> 'vote'
        ) order by shareholder.ordinality)
        from pg_catalog.jsonb_array_elements(
          decision.canonical_input -> 'shareholders'
        ) with ordinality shareholder(item, ordinality)
      ), '[]'::jsonb),
      'total_company_shares',
        decision.canonical_input ->> 'totalCompanyShares',
      'one_share_class_confirmed',
        decision.canonical_input ->> 'oneShareClassConfirmed',
      'dividend', 'null'::jsonb,
      'annual_result_allocation_ore',
        decision.annual_result_allocation_ore,
      'confirmations', pg_catalog.jsonb_build_object(
        'latest_approved_annual_accounts', decision.canonical_input
          -> 'confirmations' ->> 'latestApprovedAnnualAccounts',
        'supported_dividend_basis', decision.canonical_input
          -> 'confirmations' ->> 'supportedDividendBasis',
        'full_board_participation', decision.canonical_input
          -> 'confirmations' ->> 'fullBoardParticipation',
        'full_share_representation', decision.canonical_input
          -> 'confirmations' ->> 'fullShareRepresentation',
        'unanimous_board', decision.canonical_input
          -> 'confirmations' ->> 'unanimousBoard',
        'unanimous_shareholders', decision.canonical_input
          -> 'confirmations' ->> 'unanimousShareholders',
        'proportional_allocation', decision.canonical_input
          -> 'confirmations' ->> 'proportionalAllocation',
        'prudent_equity_and_liquidity', decision.canonical_input
          -> 'confirmations' ->> 'prudentEquityAndLiquidity'
      )
    )
  ),
  decision.decision_hash, null, decision.created_by, decision.created_at
from corporate_governance.annual_close_decisions decision
on conflict (id) do nothing;

insert into public.corporate_document_sets (
  id, company_id, income_year, decision_id, template_family,
  template_version, decision_hash, supersedes_set_id, created_by, created_at
)
select
  decision.document_set_id, decision.company_id, decision.income_year,
  decision.id, decision.canonical_input ->> 'templateFamily',
  decision.canonical_input ->> 'templateVersion', decision.decision_hash,
  null, decision.created_by, decision.created_at
from corporate_governance.annual_close_decisions decision
on conflict (id) do nothing;

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
from corporate_governance.annual_close_artifacts artifact
join public.documents document on document.id = artifact.document_id
on conflict (id) do nothing;

insert into public.corporate_document_events (
  id, company_id, income_year, decision_id, set_id, artifact_id,
  event_kind, actor_id, occurred_at, decision_hash, content_sha256,
  metadata, idempotency_key, created_at
)
select
  event.id, event.company_id, event.income_year, event.decision_id,
  event.document_set_id, event.artifact_id, event.event_kind,
  event.created_by, event.created_at, event.decision_hash,
  event.content_sha256, event.metadata,
  'canonical-event:' || event.id::text, event.created_at
from corporate_governance.annual_close_events event
where event.event_kind <> 'documents_registered'
on conflict (id) do nothing;

insert into public.corporate_decision_finalizations (
  id, company_id, income_year, decision_id, finalization_kind,
  holding_action_id, ledger_entry_id, annual_close_source_id,
  decision_hash, signed_artifact_hashes, accounting_policy_version,
  created_by, created_at
)
select
  finalization.id, finalization.company_id, finalization.income_year,
  finalization.decision_id, 'annual_close_adopted', null, null,
  finalization.annual_close_source_id, finalization.decision_hash,
  finalization.signed_artifact_hashes, null,
  finalization.created_by, finalization.created_at
from corporate_governance.annual_close_finalizations finalization
on conflict (id) do nothing;

set local role corporate_governance_store_owner;
drop function if exists corporate_governance.finalize_annual_close_v1(jsonb, text);
drop function if exists corporate_governance.attest_annual_close_signed_artifact_v1(jsonb, text);
drop function if exists corporate_governance.record_annual_close_event_v1(jsonb, text);
drop function if exists corporate_governance.approve_annual_close_v1(jsonb, text);
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
