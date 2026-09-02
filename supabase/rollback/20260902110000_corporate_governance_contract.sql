-- Restore a read-only predecessor projection while retaining canonical writers.
begin;

set local lock_timeout = '5s';
set local statement_timeout = '120s';
select pg_catalog.set_config(
  'talli.corporate_governance_contract_rollback_principal', current_user, true
);

do $membership$
begin
  execute pg_catalog.format(
    'grant company_archive_projection_executor to %I', current_user
  );
end
$membership$;

create table if not exists public.corporate_accounting_policies (
  policy_version text primary key,
  declaration_debit_account text not null,
  dividend_payable_account text not null,
  bank_account text not null,
  reviewer text not null,
  reviewed_at timestamptz not null,
  evidence_reference text not null,
  supersedes_policy_version text,
  enabled boolean not null,
  recorded_by uuid not null,
  created_at timestamptz not null
);

create table if not exists public.corporate_decisions (
  id uuid primary key,
  company_id uuid not null,
  income_year integer not null,
  decision_kind text not null,
  annual_close_source_id uuid,
  source_hash text not null,
  canonical_input jsonb not null,
  decision_hash text not null,
  supersedes_decision_id uuid,
  created_by uuid not null,
  created_at timestamptz not null
);

create table if not exists public.corporate_document_sets (
  id uuid primary key,
  company_id uuid not null,
  income_year integer not null,
  decision_id uuid not null unique,
  template_family text not null,
  template_version text not null,
  decision_hash text not null,
  supersedes_set_id uuid,
  created_by uuid not null,
  created_at timestamptz not null
);

create table if not exists public.corporate_document_artifacts (
  id uuid primary key,
  company_id uuid not null,
  income_year integer not null,
  set_id uuid not null,
  artifact_kind text not null,
  variant text not null,
  document_id uuid not null,
  content_sha256 text not null,
  byte_length bigint not null,
  mime_type text not null,
  storage_key text not null,
  supersedes_artifact_id uuid,
  created_by uuid not null,
  created_at timestamptz not null,
  unique (set_id, artifact_kind, variant),
  unique (storage_key)
);

create table if not exists public.corporate_document_events (
  id uuid primary key,
  company_id uuid not null,
  income_year integer not null,
  decision_id uuid not null,
  set_id uuid not null,
  artifact_id uuid,
  event_kind text not null,
  actor_id uuid not null,
  occurred_at timestamptz not null,
  decision_hash text not null,
  content_sha256 text,
  metadata jsonb not null,
  idempotency_key text not null unique,
  created_at timestamptz not null
);

create table if not exists public.corporate_decision_finalizations (
  id uuid primary key,
  company_id uuid not null,
  income_year integer not null,
  decision_id uuid not null unique,
  finalization_kind text not null,
  holding_action_id uuid,
  ledger_entry_id uuid,
  annual_close_source_id uuid,
  decision_hash text not null,
  signed_artifact_hashes jsonb not null,
  accounting_policy_version text,
  created_by uuid not null,
  created_at timestamptz not null
);

insert into public.corporate_accounting_policies
select * from corporate_governance.owner_dividend_accounting_policies;

insert into public.corporate_decisions
select
  decision.id, decision.company_id, decision.income_year,
  'owner_dividend', decision.annual_close_source_id,
  decision.source_hash, decision.canonical_input, decision.decision_hash,
  null::uuid, decision.created_by, decision.created_at
from corporate_governance.owner_dividend_decisions decision
union all
select
  decision.id, decision.company_id, decision.income_year,
  'annual_close', decision.annual_close_source_id,
  decision.source_hash, decision.canonical_input, decision.decision_hash,
  null::uuid, decision.created_by, decision.created_at
from corporate_governance.annual_close_decisions decision;

insert into public.corporate_document_sets
select
  decision.document_set_id, decision.company_id, decision.income_year,
  decision.id, decision.canonical_input ->> 'templateFamily',
  decision.canonical_input ->> 'templateVersion', decision.decision_hash,
  null::uuid, decision.created_by, decision.created_at
from corporate_governance.owner_dividend_decisions decision
union all
select
  decision.document_set_id, decision.company_id, decision.income_year,
  decision.id, decision.canonical_input ->> 'templateFamily',
  decision.canonical_input ->> 'templateVersion', decision.decision_hash,
  null::uuid, decision.created_by, decision.created_at
from corporate_governance.annual_close_decisions decision;

insert into public.corporate_document_artifacts
select
  artifact.id, artifact.company_id, artifact.income_year,
  artifact.document_set_id, artifact.artifact_kind, artifact.variant,
  artifact.document_id, artifact.content_sha256, artifact.byte_length,
  document.content_type, document.storage_key,
  artifact.supersedes_artifact_id, artifact.created_by, artifact.created_at
from corporate_governance.owner_dividend_artifacts artifact
join public.documents document on document.id = artifact.document_id
union all
select
  artifact.id, artifact.company_id, artifact.income_year,
  artifact.document_set_id, artifact.artifact_kind, artifact.variant,
  artifact.document_id, artifact.content_sha256, artifact.byte_length,
  document.content_type, document.storage_key,
  artifact.supersedes_artifact_id, artifact.created_by, artifact.created_at
from corporate_governance.annual_close_artifacts artifact
join public.documents document on document.id = artifact.document_id;

insert into public.corporate_document_events
select
  event.id, event.company_id, event.income_year, event.decision_id,
  event.document_set_id, event.artifact_id,
  case when event.event_kind = 'documents_registered'
    then 'generated' else event.event_kind end,
  event.created_by, event.created_at, event.decision_hash,
  event.content_sha256, event.metadata,
  'canonical-event:' || event.id::text, event.created_at
from corporate_governance.owner_dividend_events event
union all
select
  event.id, event.company_id, event.income_year, event.decision_id,
  event.document_set_id, event.artifact_id,
  case when event.event_kind = 'documents_registered'
    then 'generated' else event.event_kind end,
  event.created_by, event.created_at, event.decision_hash,
  event.content_sha256, event.metadata,
  'canonical-event:' || event.id::text, event.created_at
from corporate_governance.annual_close_events event;

insert into public.corporate_decision_finalizations
select
  item.id, item.company_id, item.income_year, item.decision_id,
  'owner_dividend_declared', item.holding_action_id,
  item.accounting_entry_id, null::uuid, item.decision_hash,
  item.signed_artifact_hashes, item.accounting_policy_version,
  item.created_by, item.created_at
from corporate_governance.owner_dividend_finalizations item
union all
select
  item.id, item.company_id, item.income_year, item.decision_id,
  'annual_close_adopted', null::uuid, null::uuid, item.annual_close_source_id,
  item.decision_hash, item.signed_artifact_hashes, null,
  item.created_by, item.created_at
from corporate_governance.annual_close_finalizations item;

insert into public.holding_actions (
  id, company_id, income_year, action_type, action_date, payload,
  ledger_entry_id, bank_transaction_id, document_id, risk_level,
  blocker_code, created_by, created_at
)
select
  loan.action_id, loan.company_id, loan.income_year, 'shareholder_loan',
  loan.loan_date, pg_catalog.jsonb_build_object(
    'loan_date', loan.loan_date,
    'amount', loan.amount_ore / 100.0,
    'direction', loan.direction,
    'counterparty_name', loan.counterparty_name,
    'document_status', loan.document_status,
    'interest_modelled', loan.interest_modelled,
    'related_party_security', loan.related_party_security,
    'bank_transaction_id', loan.bank_transaction_id,
    'document_id', loan.document_id
  ), loan.accounting_entry_id, loan.bank_transaction_id, loan.document_id,
  'ready', null, loan.created_by, loan.created_at
from corporate_governance.shareholder_loans loan
on conflict (id) do nothing;

insert into public.holding_actions (
  id, company_id, income_year, action_type, action_date, payload,
  ledger_entry_id, document_id, risk_level, blocker_code,
  created_by, created_at
)
select
  item.holding_action_id, item.company_id, item.income_year,
  'dividend_to_owner', item.created_at::date,
  decision.canonical_input || pg_catalog.jsonb_build_object(
    'action_kind', 'owner_dividend_declaration',
    'corporate_decision_id', item.decision_id,
    'accounting_policy_version', item.accounting_policy_version
  ), item.accounting_entry_id, artifact.document_id,
  'ready', null, item.created_by, item.created_at
from corporate_governance.owner_dividend_finalizations item
join corporate_governance.owner_dividend_decisions decision
  on decision.id = item.decision_id
left join corporate_governance.owner_dividend_artifacts artifact
  on artifact.decision_id = item.decision_id
  and artifact.artifact_kind = 'dividend_general_meeting_minutes'
  and artifact.variant = 'signed_owner_attested'
on conflict (id) do nothing;

insert into public.holding_actions (
  id, company_id, income_year, action_type, action_date, payload,
  ledger_entry_id, bank_transaction_id, risk_level, blocker_code,
  created_by, created_at
)
select
  item.holding_action_id, item.company_id, item.income_year,
  'dividend_to_owner', item.bank_transaction_date,
  pg_catalog.jsonb_build_object(
    'action_kind', 'owner_dividend_payment',
    'corporate_decision_id', item.decision_id,
    'amount_ore', item.payment_amount_ore,
    'accounting_policy_version', item.accounting_policy_version
  ), item.accounting_entry_id, item.bank_transaction_id,
  'ready', null, item.created_by, item.created_at
from corporate_governance.owner_dividend_payments item
on conflict (id) do nothing;

grant select on
  public.corporate_accounting_policies,
  public.corporate_decisions,
  public.corporate_document_sets,
  public.corporate_document_artifacts,
  public.corporate_document_events,
  public.corporate_decision_finalizations
to authenticated;
revoke insert, update, delete on
  public.corporate_accounting_policies,
  public.corporate_decisions,
  public.corporate_document_sets,
  public.corporate_document_artifacts,
  public.corporate_document_events,
  public.corporate_decision_finalizations
from public, anon, authenticated, service_role;

set local role company_archive_projection_executor;
do $archive_authority$
begin
  execute pg_catalog.format(
    'grant execute on function public.company_archive_track_source_write_v1() to %I',
    pg_catalog.current_setting(
      'talli.corporate_governance_contract_rollback_principal'
    )
  );
end
$archive_authority$;
reset role;

do $archive_sources$
declare
  table_name text;
begin
  foreach table_name in array array[
    'owner_dividend_decisions', 'owner_dividend_artifacts',
    'owner_dividend_events', 'owner_dividend_finalizations',
    'owner_dividend_payments', 'shareholder_loans',
    'annual_close_decisions', 'annual_close_artifacts',
    'annual_close_events', 'annual_close_finalizations'
  ] loop
    execute pg_catalog.format(
      'drop trigger if exists %I on corporate_governance.%I',
      'company_archive_track_' || table_name, table_name
    );
  end loop;
  foreach table_name in array array[
    'corporate_decisions', 'corporate_document_sets',
    'corporate_document_artifacts', 'corporate_document_events',
    'corporate_decision_finalizations'
  ] loop
    execute pg_catalog.format(
      'create trigger %I before insert or update or delete on public.%I for each row execute function public.company_archive_track_source_write_v1(%L, %L)',
      'company_archive_track_' || table_name,
      table_name, 'year', 'company_id'
    );
  end loop;
end
$archive_sources$;

set local role company_archive_projection_executor;
do $archive_authority_revoke$
begin
  execute pg_catalog.format(
    'revoke execute on function public.company_archive_track_source_write_v1() from %I',
    pg_catalog.current_setting(
      'talli.corporate_governance_contract_rollback_principal'
    )
  );
end
$archive_authority_revoke$;
reset role;

do $membership_revoke$
begin
  execute pg_catalog.format(
    'revoke company_archive_projection_executor from %I',
    pg_catalog.current_setting(
      'talli.corporate_governance_contract_rollback_principal'
    )
  );
end
$membership_revoke$;

commit;
