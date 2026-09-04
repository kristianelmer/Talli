-- Canonical annual-close decisions and immutable document lifecycle (#148).
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

create table corporate_governance.annual_close_decisions (
  id uuid primary key,
  document_set_id uuid not null unique,
  company_id uuid not null references public.companies(id) on delete restrict,
  income_year integer not null check (income_year between 2000 and 2100),
  annual_close_source_id uuid not null,
  source_hash text not null check (source_hash ~ '^[0-9a-f]{64}$'),
  source_hash_uses_current_basis boolean not null default true,
  canonical_input jsonb not null check (
    pg_catalog.jsonb_typeof(canonical_input) = 'object'
  ),
  persisted_facts jsonb not null check (
    pg_catalog.jsonb_typeof(persisted_facts) = 'object'
  ),
  generated_artifacts jsonb not null check (
    pg_catalog.jsonb_typeof(generated_artifacts) = 'array'
    and pg_catalog.jsonb_array_length(generated_artifacts) = 2
  ),
  decision_hash text not null check (decision_hash ~ '^[0-9a-f]{64}$'),
  annual_result_allocation_ore bigint not null,
  supersedes_decision_id uuid,
  supersedes_document_set_id uuid,
  idempotency_key text not null check (
    idempotency_key ~ '^[A-Za-z0-9._:-]{16,255}$'
  ),
  correlation_id text not null check (
    pg_catalog.btrim(correlation_id) <> ''
    and pg_catalog.char_length(correlation_id) <= 255
  ),
  request_fingerprint text not null check (
    request_fingerprint ~ '^[0-9a-f]{64}$'
  ),
  created_by uuid not null references auth.users(id) on delete restrict,
  created_at timestamptz not null default pg_catalog.statement_timestamp(),
  unique (created_by, company_id, idempotency_key),
  unique (company_id, income_year, id),
  check (canonical_input ->> 'decisionKind' = 'annual_close'),
  check (canonical_input ->> 'decisionId' = id::text),
  check (canonical_input ->> 'documentSetId' = document_set_id::text),
  check (canonical_input ->> 'companyId' = company_id::text),
  check ((canonical_input ->> 'incomeYear')::integer = income_year),
  check (canonical_input ->> 'sourceHash' = source_hash),
  check (canonical_input ->> 'decisionHash' = decision_hash),
  check (canonical_input -> 'dividend' = 'null'::jsonb),
  check (
    (canonical_input ->> 'annualResultAllocationOre')::bigint
      = annual_result_allocation_ore
  )
);

alter table corporate_governance.annual_close_decisions
  enable row level security;
alter table corporate_governance.annual_close_decisions
  force row level security;
revoke all on corporate_governance.annual_close_decisions
from public, anon, authenticated, service_role,
  corporate_governance_workflow_executor;

create policy governance_owner_reads_annual_close_decisions
on corporate_governance.annual_close_decisions
for select to corporate_governance_store_owner
using (public.company_access_is_accepted_owner_v1(company_id));
create policy governance_owner_creates_annual_close_decisions
on corporate_governance.annual_close_decisions
for insert to corporate_governance_store_owner
with check (
  created_by = nullif(
    pg_catalog.current_setting('talli.verified_actor_id', true), ''
  )::uuid
  and public.company_access_is_accepted_owner_v1(company_id)
);

create trigger annual_close_decisions_immutable
before update or delete on corporate_governance.annual_close_decisions
for each row execute function
  corporate_governance.prevent_corporate_governance_mutation();

create table corporate_governance.annual_close_artifacts (
  id uuid primary key,
  decision_id uuid not null references
    corporate_governance.annual_close_decisions(id) on delete restrict,
  document_set_id uuid not null,
  company_id uuid not null,
  income_year integer not null,
  artifact_kind text not null check (artifact_kind in (
    'annual_board_minutes', 'annual_general_meeting_minutes'
  )),
  variant text not null check (variant in (
    'unsigned', 'signed_owner_attested'
  )),
  document_id uuid not null,
  content_sha256 text not null check (content_sha256 ~ '^[0-9a-f]{64}$'),
  byte_length bigint not null check (byte_length between 1 and 10485760),
  supersedes_artifact_id uuid,
  created_by uuid not null references auth.users(id) on delete restrict,
  created_at timestamptz not null default pg_catalog.statement_timestamp(),
  unique (decision_id, artifact_kind, variant),
  unique (decision_id, document_id),
  unique (company_id, income_year, id),
  foreign key (company_id, income_year, decision_id)
    references corporate_governance.annual_close_decisions(
      company_id, income_year, id
    ) on delete restrict,
  foreign key (company_id, income_year, supersedes_artifact_id)
    references corporate_governance.annual_close_artifacts(
      company_id, income_year, id
    ) on delete restrict,
  check (supersedes_artifact_id is null or supersedes_artifact_id <> id),
  check (
    (variant = 'unsigned' and supersedes_artifact_id is null)
    or (variant = 'signed_owner_attested' and supersedes_artifact_id is not null)
  )
);

create table corporate_governance.annual_close_events (
  id uuid primary key default pg_catalog.gen_random_uuid(),
  decision_id uuid not null references
    corporate_governance.annual_close_decisions(id) on delete restrict,
  document_set_id uuid not null,
  company_id uuid not null,
  income_year integer not null,
  event_kind text not null check (event_kind in (
    'documents_registered', 'facts_approved', 'signing_requested',
    'signed_copy_attested', 'superseded', 'rejected'
  )),
  artifact_id uuid,
  decision_hash text not null check (decision_hash ~ '^[0-9a-f]{64}$'),
  content_sha256 text check (
    content_sha256 is null or content_sha256 ~ '^[0-9a-f]{64}$'
  ),
  metadata jsonb not null default '{}'::jsonb check (
    pg_catalog.jsonb_typeof(metadata) = 'object'
  ),
  idempotency_key text not null check (
    idempotency_key ~ '^[A-Za-z0-9._:-]{16,255}$'
  ),
  correlation_id text not null check (
    pg_catalog.btrim(correlation_id) <> ''
    and pg_catalog.char_length(correlation_id) <= 255
  ),
  request_fingerprint text not null check (
    request_fingerprint ~ '^[0-9a-f]{64}$'
  ),
  created_by uuid not null references auth.users(id) on delete restrict,
  occurred_at timestamptz not null default pg_catalog.statement_timestamp(),
  created_at timestamptz not null default pg_catalog.statement_timestamp(),
  unique (created_by, company_id, idempotency_key),
  unique (company_id, income_year, id),
  foreign key (company_id, income_year, decision_id)
    references corporate_governance.annual_close_decisions(
      company_id, income_year, id
    ) on delete restrict,
  foreign key (company_id, income_year, artifact_id)
    references corporate_governance.annual_close_artifacts(
      company_id, income_year, id
    ) on delete restrict,
  check (
    (event_kind = 'signed_copy_attested'
      and artifact_id is not null and content_sha256 is not null)
    or event_kind <> 'signed_copy_attested'
  )
);

create unique index annual_close_events_singleton_idx
on corporate_governance.annual_close_events(decision_id, event_kind)
where event_kind in (
  'facts_approved', 'signing_requested', 'superseded', 'rejected'
);

create table corporate_governance.annual_close_finalizations (
  id uuid primary key,
  event_id uuid not null unique default pg_catalog.gen_random_uuid(),
  decision_id uuid not null unique references
    corporate_governance.annual_close_decisions(id) on delete restrict,
  document_set_id uuid not null,
  company_id uuid not null,
  income_year integer not null,
  annual_close_source_id uuid not null,
  decision_hash text not null check (decision_hash ~ '^[0-9a-f]{64}$'),
  signed_artifact_hashes jsonb not null check (
    pg_catalog.jsonb_typeof(signed_artifact_hashes) = 'object'
  ),
  idempotency_key text not null check (
    idempotency_key ~ '^[A-Za-z0-9._:-]{16,255}$'
  ),
  correlation_id text not null check (
    pg_catalog.btrim(correlation_id) <> ''
    and pg_catalog.char_length(correlation_id) <= 255
  ),
  request_fingerprint text not null check (
    request_fingerprint ~ '^[0-9a-f]{64}$'
  ),
  created_by uuid not null references auth.users(id) on delete restrict,
  occurred_at timestamptz not null default pg_catalog.statement_timestamp(),
  created_at timestamptz not null default pg_catalog.statement_timestamp(),
  unique (created_by, company_id, idempotency_key),
  unique (company_id, income_year, id),
  foreign key (company_id, income_year, decision_id)
    references corporate_governance.annual_close_decisions(
      company_id, income_year, id
    ) on delete restrict
);

-- Reconcile the predecessor annual-close lifecycle before forced RLS is
-- enabled. Stable identities, hashes, document references, actors, and times
-- are preserved; only key casing is normalized to the Python contract.
insert into corporate_governance.annual_close_decisions (
  id, document_set_id, company_id, income_year, annual_close_source_id,
  source_hash, source_hash_uses_current_basis, canonical_input,
  persisted_facts, generated_artifacts,
  decision_hash, annual_result_allocation_ore, supersedes_decision_id,
  supersedes_document_set_id, idempotency_key,
  correlation_id, request_fingerprint, created_by, created_at
)
select
  decision.id, document_set.id, decision.company_id, decision.income_year,
  decision.annual_close_source_id, decision.source_hash, false,
  case when decision.canonical_input ? 'decisionId'
    then decision.canonical_input
    else pg_catalog.jsonb_build_object(
      'decisionKind', 'annual_close',
      'decisionId', decision.id,
      'documentSetId', document_set.id,
      'companyId', decision.company_id,
      'organizationNumber', decision.canonical_input ->> 'organization_number',
      'legalName', decision.canonical_input ->> 'legal_name',
      'incomeYear', decision.income_year,
      'annualCloseSourceId', decision.annual_close_source_id,
      'sourceHash', decision.source_hash,
      'templateFamily', decision.canonical_input ->> 'template_family',
      'templateVersion', decision.canonical_input ->> 'template_version',
      'annualBasisYear',
        (decision.canonical_input ->> 'annual_basis_year')::integer,
      'financialTotals', pg_catalog.jsonb_build_object(
        'resultAfterTaxOre', (decision.canonical_input -> 'financial_totals'
          ->> 'result_after_tax_ore')::bigint,
        'equityOre', (decision.canonical_input -> 'financial_totals'
          ->> 'equity_ore')::bigint,
        'availableDistributionOre',
          (decision.canonical_input -> 'financial_totals'
            ->> 'available_distribution_ore')::bigint,
        'cashOre', (decision.canonical_input -> 'financial_totals'
          ->> 'cash_ore')::bigint
      ),
      'boardMeeting', pg_catalog.jsonb_build_object(
        'meetingDate', decision.canonical_input -> 'board_meeting'
          ->> 'meeting_date',
        'meetingTime', decision.canonical_input -> 'board_meeting'
          ->> 'meeting_time',
        'place', decision.canonical_input -> 'board_meeting' ->> 'place',
        'treatmentMethod', decision.canonical_input -> 'board_meeting'
          ->> 'treatment_method'
      ),
      'boardParticipants', coalesce((
        select pg_catalog.jsonb_agg(pg_catalog.jsonb_build_object(
          'participantId', participant.item ->> 'participant_id',
          'name', participant.item ->> 'name',
          'role', participant.item ->> 'role'
        ) order by participant.ordinality)
        from pg_catalog.jsonb_array_elements(
          decision.canonical_input -> 'board_participants'
        ) with ordinality participant(item, ordinality)
      ), '[]'::jsonb),
      'generalMeeting', pg_catalog.jsonb_build_object(
        'meetingDate', decision.canonical_input -> 'general_meeting'
          ->> 'meeting_date',
        'meetingTime', decision.canonical_input -> 'general_meeting'
          ->> 'meeting_time',
        'place', decision.canonical_input -> 'general_meeting' ->> 'place',
        'meetingForm', decision.canonical_input -> 'general_meeting'
          ->> 'meeting_form',
        'chairName', decision.canonical_input -> 'general_meeting'
          ->> 'chair_name',
        'coSignerName', decision.canonical_input -> 'general_meeting'
          ->> 'co_signer_name'
      ),
      'shareholders', coalesce((
        select pg_catalog.jsonb_agg(pg_catalog.jsonb_build_object(
          'shareholderId', shareholder.item ->> 'shareholder_id',
          'name', shareholder.item ->> 'name',
          'shareCount', (shareholder.item ->> 'share_count')::bigint,
          'representedShareCount',
            (shareholder.item ->> 'represented_share_count')::bigint,
          'vote', shareholder.item ->> 'vote'
        ) order by shareholder.ordinality)
        from pg_catalog.jsonb_array_elements(
          decision.canonical_input -> 'shareholders'
        ) with ordinality shareholder(item, ordinality)
      ), '[]'::jsonb),
      'totalCompanyShares',
        (decision.canonical_input ->> 'total_company_shares')::bigint,
      'oneShareClassConfirmed',
        (decision.canonical_input ->> 'one_share_class_confirmed')::boolean,
      'dividend', 'null'::jsonb,
      'annualResultAllocationOre',
        (decision.canonical_input ->> 'annual_result_allocation_ore')::bigint,
      'confirmations', pg_catalog.jsonb_build_object(
        'latestApprovedAnnualAccounts',
          (decision.canonical_input -> 'confirmations'
            ->> 'latest_approved_annual_accounts')::boolean,
        'supportedDividendBasis',
          (decision.canonical_input -> 'confirmations'
            ->> 'supported_dividend_basis')::boolean,
        'fullBoardParticipation',
          (decision.canonical_input -> 'confirmations'
            ->> 'full_board_participation')::boolean,
        'fullShareRepresentation',
          (decision.canonical_input -> 'confirmations'
            ->> 'full_share_representation')::boolean,
        'unanimousBoard',
          (decision.canonical_input -> 'confirmations'
            ->> 'unanimous_board')::boolean,
        'unanimousShareholders',
          (decision.canonical_input -> 'confirmations'
            ->> 'unanimous_shareholders')::boolean,
        'proportionalAllocation',
          (decision.canonical_input -> 'confirmations'
            ->> 'proportional_allocation')::boolean,
        'prudentEquityAndLiquidity',
          (decision.canonical_input -> 'confirmations'
            ->> 'prudent_equity_and_liquidity')::boolean
      ),
      'decisionHash', decision.decision_hash
    )
  end,
  pg_catalog.jsonb_build_object(
    'legacyCanonicalInput', decision.canonical_input,
    'reconciledAt', pg_catalog.statement_timestamp()
  ),
  generated.items,
  decision.decision_hash,
  coalesce(
    (decision.canonical_input ->> 'annualResultAllocationOre')::bigint,
    (decision.canonical_input ->> 'annual_result_allocation_ore')::bigint
  ),
  decision.supersedes_decision_id, document_set.supersedes_set_id,
  'legacy-annual-close:' || decision.id::text,
  'legacy-annual-close:' || decision.id::text,
  pg_catalog.encode(extensions.digest(pg_catalog.jsonb_build_object(
    'legacyDecisionId', decision.id,
    'decisionHash', decision.decision_hash
  )::text, 'sha256'), 'hex'),
  decision.created_by, decision.created_at
from public.corporate_decisions decision
join public.corporate_document_sets document_set
  on document_set.decision_id = decision.id
cross join lateral (
  select pg_catalog.jsonb_agg(pg_catalog.jsonb_build_object(
    'artifactKind', artifact.artifact_kind,
    'filename', document.name,
    'templateVersion', document_set.template_version,
    'decisionHash', decision.decision_hash,
    'contentSha256', artifact.content_sha256,
    'byteLength', artifact.byte_length
  ) order by artifact.artifact_kind) items
  from public.corporate_document_artifacts artifact
  join public.documents document on document.id = artifact.document_id
  where artifact.set_id = document_set.id and artifact.variant = 'unsigned'
) generated
where decision.decision_kind = 'annual_close'
  and pg_catalog.jsonb_array_length(generated.items) = 2
on conflict (id) do nothing;

insert into corporate_governance.annual_close_artifacts (
  id, decision_id, document_set_id, company_id, income_year,
  artifact_kind, variant, document_id, content_sha256, byte_length,
  supersedes_artifact_id, created_by, created_at
)
select
  artifact.id, decision.id, artifact.set_id, artifact.company_id,
  artifact.income_year, artifact.artifact_kind, artifact.variant,
  artifact.document_id, artifact.content_sha256, artifact.byte_length,
  artifact.supersedes_artifact_id, artifact.created_by, artifact.created_at
from public.corporate_document_artifacts artifact
join public.corporate_document_sets document_set on document_set.id = artifact.set_id
join corporate_governance.annual_close_decisions decision
  on decision.id = document_set.decision_id
on conflict (id) do nothing;

insert into corporate_governance.annual_close_events (
  id, decision_id, document_set_id, company_id, income_year, artifact_id,
  event_kind, decision_hash, content_sha256, metadata, idempotency_key,
  correlation_id, request_fingerprint, created_by, occurred_at, created_at
)
select
  event.id, event.decision_id, event.set_id, event.company_id,
  event.income_year, event.artifact_id,
  case when event.event_kind = 'generated'
    then 'documents_registered' else event.event_kind end,
  event.decision_hash, event.content_sha256, event.metadata,
  'legacy-event:' || event.id::text,
  'legacy-event:' || event.id::text,
  pg_catalog.encode(extensions.digest(pg_catalog.jsonb_build_object(
    'legacyEventId', event.id, 'eventKind', event.event_kind
  )::text, 'sha256'), 'hex'),
  event.actor_id, event.occurred_at, event.created_at
from public.corporate_document_events event
join corporate_governance.annual_close_decisions decision
  on decision.id = event.decision_id
where event.event_kind in (
  'generated', 'facts_approved', 'signing_requested',
  'signed_copy_attested', 'superseded', 'rejected'
)
on conflict (id) do nothing;

insert into corporate_governance.annual_close_events (
  id, decision_id, document_set_id, company_id, income_year, event_kind,
  decision_hash, metadata, idempotency_key, correlation_id,
  request_fingerprint, created_by, occurred_at, created_at
)
select
  pg_catalog.md5('annual-close-documents:' || decision.id::text)::uuid,
  decision.id, decision.document_set_id, decision.company_id,
  decision.income_year, 'documents_registered', decision.decision_hash,
  '{}'::jsonb, 'legacy-documents:' || decision.id::text,
  'legacy-documents:' || decision.id::text,
  pg_catalog.encode(extensions.digest(pg_catalog.jsonb_build_object(
    'legacyDecisionId', decision.id, 'eventKind', 'documents_registered'
  )::text, 'sha256'), 'hex'),
  decision.created_by, pg_catalog.max(artifact.created_at),
  pg_catalog.max(artifact.created_at)
from corporate_governance.annual_close_decisions decision
join corporate_governance.annual_close_artifacts artifact
  on artifact.decision_id = decision.id and artifact.variant = 'unsigned'
where not exists (
  select 1 from corporate_governance.annual_close_events event
  where event.decision_id = decision.id
    and event.event_kind = 'documents_registered'
)
group by decision.id
having pg_catalog.count(*) = 2
on conflict (id) do nothing;

insert into corporate_governance.annual_close_finalizations (
  id, event_id, decision_id, document_set_id, company_id, income_year,
  annual_close_source_id, decision_hash, signed_artifact_hashes,
  idempotency_key, correlation_id, request_fingerprint,
  created_by, occurred_at, created_at
)
select
  finalization.id, coalesce(event.id, finalization.id),
  finalization.decision_id, decision.document_set_id,
  finalization.company_id, finalization.income_year,
  finalization.annual_close_source_id, finalization.decision_hash,
  finalization.signed_artifact_hashes,
  'legacy-finalization:' || finalization.id::text,
  'legacy-finalization:' || finalization.id::text,
  pg_catalog.encode(extensions.digest(pg_catalog.jsonb_build_object(
    'legacyFinalizationId', finalization.id,
    'decisionHash', finalization.decision_hash
  )::text, 'sha256'), 'hex'),
  finalization.created_by,
  coalesce(event.occurred_at, finalization.created_at),
  coalesce(event.created_at, finalization.created_at)
from public.corporate_decision_finalizations finalization
join corporate_governance.annual_close_decisions decision
  on decision.id = finalization.decision_id
left join lateral (
  select evidence.id, evidence.occurred_at, evidence.created_at
  from public.corporate_document_events evidence
  where evidence.decision_id = finalization.decision_id
    and evidence.event_kind = 'finalized'
    and evidence.metadata ->> 'finalization_id' = finalization.id::text
  order by evidence.created_at, evidence.id
  limit 1
) event on true
where finalization.finalization_kind = 'annual_close_adopted'
on conflict (id) do nothing;

alter table corporate_governance.annual_close_decisions
  owner to corporate_governance_store_owner;
alter table corporate_governance.annual_close_artifacts
  owner to corporate_governance_store_owner;
alter table corporate_governance.annual_close_events
  owner to corporate_governance_store_owner;
alter table corporate_governance.annual_close_finalizations
  owner to corporate_governance_store_owner;

alter table corporate_governance.annual_close_artifacts
  enable row level security;
alter table corporate_governance.annual_close_artifacts
  force row level security;
alter table corporate_governance.annual_close_events
  enable row level security;
alter table corporate_governance.annual_close_events
  force row level security;
alter table corporate_governance.annual_close_finalizations
  enable row level security;
alter table corporate_governance.annual_close_finalizations
  force row level security;
revoke all on
  corporate_governance.annual_close_artifacts,
  corporate_governance.annual_close_events,
  corporate_governance.annual_close_finalizations
from public, anon, authenticated, service_role,
  corporate_governance_workflow_executor;

create policy governance_owner_reads_annual_close_artifacts
on corporate_governance.annual_close_artifacts
for select to corporate_governance_store_owner
using (public.company_access_is_accepted_owner_v1(company_id));
create policy governance_owner_creates_annual_close_artifacts
on corporate_governance.annual_close_artifacts
for insert to corporate_governance_store_owner
with check (
  created_by = nullif(
    pg_catalog.current_setting('talli.verified_actor_id', true), ''
  )::uuid
  and public.company_access_is_accepted_owner_v1(company_id)
);
create policy governance_owner_reads_annual_close_events
on corporate_governance.annual_close_events
for select to corporate_governance_store_owner
using (public.company_access_is_accepted_owner_v1(company_id));
create policy governance_owner_creates_annual_close_events
on corporate_governance.annual_close_events
for insert to corporate_governance_store_owner
with check (
  created_by = nullif(
    pg_catalog.current_setting('talli.verified_actor_id', true), ''
  )::uuid
  and public.company_access_is_accepted_owner_v1(company_id)
);
create policy governance_owner_reads_annual_close_finalizations
on corporate_governance.annual_close_finalizations
for select to corporate_governance_store_owner
using (public.company_access_is_accepted_owner_v1(company_id));
create policy governance_owner_creates_annual_close_finalizations
on corporate_governance.annual_close_finalizations
for insert to corporate_governance_store_owner
with check (
  created_by = nullif(
    pg_catalog.current_setting('talli.verified_actor_id', true), ''
  )::uuid
  and public.company_access_is_accepted_owner_v1(company_id)
);

create trigger annual_close_artifacts_immutable
before update or delete on corporate_governance.annual_close_artifacts
for each row execute function
  corporate_governance.prevent_corporate_governance_mutation();
create trigger annual_close_events_immutable
before update or delete on corporate_governance.annual_close_events
for each row execute function
  corporate_governance.prevent_corporate_governance_mutation();
create trigger annual_close_finalizations_immutable
before update or delete on corporate_governance.annual_close_finalizations
for each row execute function
  corporate_governance.prevent_corporate_governance_mutation();

set local role corporate_governance_store_owner;

create or replace function corporate_governance.annual_close_lifecycle_v1(
  p_decision_id uuid,
  p_replayed boolean
)
returns jsonb
language plpgsql
stable
security definer
set search_path = ''
as $function$
declare
  v_decision corporate_governance.annual_close_decisions%rowtype;
  v_finalization_id uuid;
  v_generated jsonb;
  v_signed jsonb;
  v_state text;
begin
  select decision.* into v_decision
  from corporate_governance.annual_close_decisions decision
  where decision.id = p_decision_id;
  if not found then
    raise exception 'corporate_governance_not_found';
  end if;
  select pg_catalog.jsonb_object_agg(
    artifact.artifact_kind, artifact.content_sha256
  ) filter (where artifact.variant = 'unsigned'),
  pg_catalog.jsonb_object_agg(
    artifact.artifact_kind, artifact.content_sha256
  ) filter (where artifact.variant = 'signed_owner_attested')
  into v_generated, v_signed
  from corporate_governance.annual_close_artifacts artifact
  where artifact.decision_id = p_decision_id;
  select finalization.id into v_finalization_id
  from corporate_governance.annual_close_finalizations finalization
  where finalization.decision_id = p_decision_id;
  v_state := case
    when exists (
      select 1 from corporate_governance.annual_close_events event
      where event.decision_id = p_decision_id and event.event_kind = 'rejected'
    ) then 'rejected'
    when exists (
      select 1 from corporate_governance.annual_close_events event
      where event.decision_id = p_decision_id
        and event.event_kind = 'superseded'
    ) then 'superseded'
    when v_finalization_id is not null then 'finalized'
    when coalesce(v_signed, '{}'::jsonb) ? 'annual_board_minutes'
      and coalesce(v_signed, '{}'::jsonb)
        ? 'annual_general_meeting_minutes'
      then 'signed_owner_attested'
    when exists (
      select 1 from corporate_governance.annual_close_events event
      where event.decision_id = p_decision_id
        and event.event_kind = 'signing_requested'
    ) then 'signing_requested'
    when exists (
      select 1 from corporate_governance.annual_close_events event
      where event.decision_id = p_decision_id
        and event.event_kind = 'facts_approved'
    ) then 'facts_approved'
    when coalesce(v_generated, '{}'::jsonb) ? 'annual_board_minutes'
      and coalesce(v_generated, '{}'::jsonb)
        ? 'annual_general_meeting_minutes'
      then 'documents_registered'
    else 'proposed'
  end;
  return pg_catalog.jsonb_build_object(
    'decisionId', v_decision.id,
    'documentSetId', v_decision.document_set_id,
    'companyId', v_decision.company_id,
    'incomeYear', v_decision.income_year,
    'decisionHash', v_decision.decision_hash,
    'state', v_state,
    'generatedArtifactHashes', coalesce(v_generated, '{}'::jsonb),
    'signedArtifactHashes', coalesce(v_signed, '{}'::jsonb),
    'finalizationId', v_finalization_id,
    'replayed', p_replayed
  );
end;
$function$;

create or replace function corporate_governance.propose_annual_close_v1(
  p_request jsonb,
  p_canonical_input jsonb,
  p_persisted_facts jsonb,
  p_generated_artifacts jsonb,
  p_verified_subject text
)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $function$
declare
  v_actor_id uuid;
  v_company_id uuid;
  v_income_year integer;
  v_decision_id uuid;
  v_document_set_id uuid;
  v_annual_close_source_id uuid;
  v_fingerprint text;
  v_existing corporate_governance.annual_close_decisions%rowtype;
begin
  begin
    v_company_id := (p_request ->> 'companyId')::uuid;
    v_income_year := (p_request ->> 'incomeYear')::integer;
    v_decision_id := (p_request ->> 'decisionId')::uuid;
    v_document_set_id := (p_request ->> 'documentSetId')::uuid;
    v_annual_close_source_id :=
      (p_canonical_input ->> 'annualCloseSourceId')::uuid;
  exception when others then
    raise exception 'corporate_governance_invalid_input';
  end;
  v_actor_id := corporate_governance.assert_owner_v1(
    v_company_id, v_income_year, p_verified_subject, false
  );
  if v_income_year not between 2000 and 2100
    or coalesce(p_request ->> 'idempotencyKey', '')
      !~ '^[A-Za-z0-9._:-]{16,255}$'
    or pg_catalog.btrim(coalesce(p_request ->> 'correlationId', '')) = ''
    or pg_catalog.jsonb_typeof(p_canonical_input) is distinct from 'object'
    or pg_catalog.jsonb_typeof(p_persisted_facts) is distinct from 'object'
    or pg_catalog.jsonb_typeof(p_generated_artifacts) is distinct from 'array'
    or pg_catalog.jsonb_array_length(p_generated_artifacts) <> 2
    or (
      select pg_catalog.count(distinct artifact ->> 'artifactKind')
      from pg_catalog.jsonb_array_elements(p_generated_artifacts) artifact
      where artifact ->> 'artifactKind' in (
        'annual_board_minutes',
        'annual_general_meeting_minutes'
      )
        and artifact ->> 'decisionHash'
          = p_canonical_input ->> 'decisionHash'
        and artifact ->> 'templateVersion'
          = p_canonical_input ->> 'templateVersion'
        and coalesce(artifact ->> 'contentSha256', '')
          ~ '^[0-9a-f]{64}$'
        and (artifact ->> 'byteLength')::bigint between 1 and 10485760
    ) <> 2
    or p_canonical_input ->> 'decisionKind' <> 'annual_close'
    or p_canonical_input ->> 'decisionId' is distinct from v_decision_id::text
    or p_canonical_input ->> 'documentSetId'
      is distinct from v_document_set_id::text
    or p_canonical_input ->> 'companyId' is distinct from v_company_id::text
    or (p_canonical_input ->> 'incomeYear')::integer <> v_income_year
    or coalesce(p_canonical_input ->> 'sourceHash', '') !~ '^[0-9a-f]{64}$'
    or coalesce(p_canonical_input ->> 'decisionHash', '') !~ '^[0-9a-f]{64}$'
    or p_canonical_input ->> 'templateFamily' <> 'norwegian_simple_as'
    or pg_catalog.btrim(
      coalesce(p_canonical_input ->> 'templateVersion', '')
    ) = ''
    or p_canonical_input -> 'dividend' is distinct from 'null'::jsonb
    or (p_canonical_input ->> 'annualResultAllocationOre')::bigint
      <> (p_canonical_input -> 'financialTotals'
        ->> 'resultAfterTaxOre')::bigint
    or p_canonical_input -> 'confirmations' is distinct from
      pg_catalog.jsonb_build_object(
        'latestApprovedAnnualAccounts', true,
        'supportedDividendBasis', true,
        'fullBoardParticipation', true,
        'fullShareRepresentation', true,
        'unanimousBoard', true,
        'unanimousShareholders', true,
        'proportionalAllocation', true,
        'prudentEquityAndLiquidity', true
      )
  then
    raise exception 'corporate_governance_invalid_input';
  end if;
  begin
    perform public.assert_corporate_decision_persisted_facts(
      v_company_id, v_income_year, 'annual_close',
      v_annual_close_source_id, p_persisted_facts,
      p_canonical_input ->> 'decisionHash'
    );
  exception when others then
    raise exception 'corporate_governance_invalid_input';
  end;
  v_fingerprint := corporate_governance.request_fingerprint_v1(
    pg_catalog.jsonb_build_object(
      'request', p_request, 'canonicalInput', p_canonical_input,
      'persistedFacts', p_persisted_facts,
      'generatedArtifacts', p_generated_artifacts
    )
  );
  select decision.* into v_existing
  from corporate_governance.annual_close_decisions decision
  where decision.id = v_decision_id
    or decision.document_set_id = v_document_set_id
    or (
      decision.created_by = v_actor_id
      and decision.company_id = v_company_id
      and decision.idempotency_key = p_request ->> 'idempotencyKey'
    )
  order by decision.id = v_decision_id desc
  limit 1
  for update;
  if found then
    if v_existing.id <> v_decision_id
      or v_existing.document_set_id <> v_document_set_id
      or v_existing.company_id <> v_company_id
      or v_existing.income_year <> v_income_year
      or v_existing.idempotency_key <> p_request ->> 'idempotencyKey'
      or v_existing.request_fingerprint <> v_fingerprint
    then
      raise exception 'corporate_governance_idempotency_conflict';
    end if;
    return pg_catalog.jsonb_build_object(
      'state', 'proposed', 'replayed', true
    );
  end if;
  insert into corporate_governance.annual_close_decisions (
    id, document_set_id, company_id, income_year, annual_close_source_id,
    source_hash, canonical_input, persisted_facts, generated_artifacts,
    decision_hash,
    annual_result_allocation_ore, idempotency_key, correlation_id,
    request_fingerprint, created_by
  ) values (
    v_decision_id, v_document_set_id, v_company_id, v_income_year,
    v_annual_close_source_id, p_canonical_input ->> 'sourceHash',
    p_canonical_input, p_persisted_facts, p_generated_artifacts,
    p_canonical_input ->> 'decisionHash',
    (p_canonical_input ->> 'annualResultAllocationOre')::bigint,
    p_request ->> 'idempotencyKey', p_request ->> 'correlationId',
    v_fingerprint, v_actor_id
  );
  return pg_catalog.jsonb_build_object(
    'state', 'proposed', 'replayed', false
  );
end;
$function$;

create or replace function
corporate_governance.register_annual_close_documents_v1(
  p_request jsonb,
  p_verified_subject text
)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $function$
declare
  v_actor_id uuid;
  v_decision corporate_governance.annual_close_decisions%rowtype;
  v_existing corporate_governance.annual_close_events%rowtype;
  v_artifact jsonb;
  v_expected jsonb;
  v_fingerprint text;
begin
  begin
    select decision.* into v_decision
    from corporate_governance.annual_close_decisions decision
    where decision.id = (p_request ->> 'decisionId')::uuid
    for update;
  exception when others then
    raise exception 'corporate_governance_invalid_input';
  end;
  if not found then
    raise exception 'corporate_governance_not_found';
  end if;
  v_actor_id := corporate_governance.assert_owner_v1(
    v_decision.company_id, v_decision.income_year,
    p_verified_subject, false
  );
  if p_request ->> 'companyId' <> v_decision.company_id::text
    or p_request ->> 'documentSetId' <> v_decision.document_set_id::text
    or p_request ->> 'decisionHash' <> v_decision.decision_hash
    or coalesce(p_request ->> 'idempotencyKey', '')
      !~ '^[A-Za-z0-9._:-]{16,255}$'
    or pg_catalog.jsonb_typeof(p_request -> 'artifacts')
      is distinct from 'array'
    or pg_catalog.jsonb_array_length(p_request -> 'artifacts') <> 2
    or (
      select pg_catalog.count(distinct artifact ->> 'artifactKind')
      from pg_catalog.jsonb_array_elements(p_request -> 'artifacts') artifact
      where artifact ->> 'artifactKind' in (
        'annual_board_minutes', 'annual_general_meeting_minutes'
      )
    ) <> 2
  then
    raise exception 'corporate_governance_invalid_input';
  end if;
  v_fingerprint := corporate_governance.request_fingerprint_v1(p_request);
  select event.* into v_existing
  from corporate_governance.annual_close_events event
  where event.decision_id = v_decision.id
    and (
      event.event_kind = 'documents_registered'
      or (
        event.created_by = v_actor_id
        and event.idempotency_key = p_request ->> 'idempotencyKey'
      )
    )
  order by event.event_kind = 'documents_registered' desc
  limit 1;
  if found then
    if v_existing.event_kind <> 'documents_registered'
      or v_existing.idempotency_key <> p_request ->> 'idempotencyKey'
      or v_existing.request_fingerprint <> v_fingerprint
    then
      raise exception 'corporate_governance_idempotency_conflict';
    end if;
    return corporate_governance.annual_close_lifecycle_v1(
      v_decision.id, true
    );
  end if;
  for v_artifact in
    select value
    from pg_catalog.jsonb_array_elements(p_request -> 'artifacts')
  loop
    select expected.value into v_expected
    from pg_catalog.jsonb_array_elements(
      v_decision.generated_artifacts
    ) expected(value)
    where expected ->> 'artifactKind' = v_artifact ->> 'artifactKind';
    if v_expected is null
      or v_artifact ->> 'contentSha256'
        is distinct from v_expected ->> 'contentSha256'
      or (v_artifact ->> 'byteLength')::bigint
        is distinct from (v_expected ->> 'byteLength')::bigint
    then
      raise exception 'corporate_governance_invalid_input';
    end if;
    insert into corporate_governance.annual_close_artifacts (
      id, decision_id, document_set_id, company_id, income_year,
      artifact_kind, variant, document_id, content_sha256, byte_length,
      created_by
    ) values (
      (v_artifact ->> 'artifactId')::uuid, v_decision.id,
      v_decision.document_set_id, v_decision.company_id,
      v_decision.income_year, v_artifact ->> 'artifactKind', 'unsigned',
      (v_artifact ->> 'documentId')::uuid,
      v_artifact ->> 'contentSha256',
      (v_artifact ->> 'byteLength')::bigint, v_actor_id
    );
  end loop;
  insert into corporate_governance.annual_close_events (
    decision_id, document_set_id, company_id, income_year, event_kind,
    decision_hash, idempotency_key, correlation_id,
    request_fingerprint, created_by
  ) values (
    v_decision.id, v_decision.document_set_id, v_decision.company_id,
    v_decision.income_year, 'documents_registered',
    v_decision.decision_hash, p_request ->> 'idempotencyKey',
    p_request ->> 'correlationId', v_fingerprint, v_actor_id
  );
  return corporate_governance.annual_close_lifecycle_v1(
    v_decision.id, false
  );
end;
$function$;

create or replace function corporate_governance.approve_annual_close_v1(
  p_request jsonb,
  p_verified_subject text
)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $function$
declare
  v_actor_id uuid;
  v_decision corporate_governance.annual_close_decisions%rowtype;
  v_existing corporate_governance.annual_close_events%rowtype;
  v_fingerprint text;
begin
  begin
    select decision.* into v_decision
    from corporate_governance.annual_close_decisions decision
    where decision.id = (p_request ->> 'decisionId')::uuid
    for update;
  exception when others then
    raise exception 'corporate_governance_invalid_input';
  end;
  if not found then
    raise exception 'corporate_governance_not_found';
  end if;
  v_actor_id := corporate_governance.assert_owner_v1(
    v_decision.company_id, v_decision.income_year,
    p_verified_subject, true
  );
  if p_request ->> 'companyId' <> v_decision.company_id::text
    or p_request ->> 'documentSetId' <> v_decision.document_set_id::text
    or p_request ->> 'decisionHash' <> v_decision.decision_hash
    or coalesce(p_request ->> 'idempotencyKey', '')
      !~ '^[A-Za-z0-9._:-]{16,255}$'
    or coalesce(p_request ->> 'approvalEventId', '')
      !~ '^[0-9a-fA-F-]{36}$'
  then
    raise exception 'corporate_governance_invalid_input';
  end if;
  v_fingerprint := corporate_governance.request_fingerprint_v1(p_request);
  select event.* into v_existing
  from corporate_governance.annual_close_events event
  where event.id = (p_request ->> 'approvalEventId')::uuid
    or (
      event.decision_id = v_decision.id
      and event.event_kind = 'facts_approved'
    )
    or (
      event.created_by = v_actor_id
      and event.company_id = v_decision.company_id
      and event.idempotency_key = p_request ->> 'idempotencyKey'
    )
  order by event.id = (p_request ->> 'approvalEventId')::uuid desc
  limit 1;
  if found then
    if v_existing.id <> (p_request ->> 'approvalEventId')::uuid
      or v_existing.event_kind <> 'facts_approved'
      or v_existing.idempotency_key <> p_request ->> 'idempotencyKey'
      or v_existing.request_fingerprint <> v_fingerprint
    then
      raise exception 'corporate_governance_idempotency_conflict';
    end if;
    return corporate_governance.annual_close_lifecycle_v1(
      v_decision.id, true
    );
  end if;
  if (
    select pg_catalog.count(*)
    from corporate_governance.annual_close_artifacts artifact
    where artifact.decision_id = v_decision.id
      and artifact.variant = 'unsigned'
  ) <> 2
    or not exists (
      select 1 from corporate_governance.annual_close_events event
      where event.decision_id = v_decision.id
        and event.event_kind = 'documents_registered'
    )
    or exists (
      select 1 from corporate_governance.annual_close_finalizations item
      where item.decision_id = v_decision.id
    )
    or exists (
      select 1 from corporate_governance.annual_close_events event
      where event.decision_id = v_decision.id
        and event.event_kind in ('rejected', 'superseded')
    )
  then
    raise exception 'corporate_governance_invalid_input';
  end if;
  insert into corporate_governance.annual_close_events (
    id, decision_id, document_set_id, company_id, income_year,
    event_kind, decision_hash, metadata, idempotency_key, correlation_id,
    request_fingerprint, created_by
  ) values (
    (p_request ->> 'approvalEventId')::uuid, v_decision.id,
    v_decision.document_set_id, v_decision.company_id,
    v_decision.income_year, 'facts_approved', v_decision.decision_hash,
    '{"attestation":"owner_reviewed_persisted_facts"}'::jsonb,
    p_request ->> 'idempotencyKey', p_request ->> 'correlationId',
    v_fingerprint, v_actor_id
  );
  return corporate_governance.annual_close_lifecycle_v1(
    v_decision.id, false
  );
end;
$function$;

create or replace function corporate_governance.record_annual_close_event_v1(
  p_request jsonb,
  p_verified_subject text
)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $function$
declare
  v_actor_id uuid;
  v_decision corporate_governance.annual_close_decisions%rowtype;
  v_existing corporate_governance.annual_close_events%rowtype;
  v_fingerprint text;
  v_event_kind text := p_request ->> 'eventKind';
begin
  begin
    select decision.* into v_decision
    from corporate_governance.annual_close_decisions decision
    where decision.id = (p_request ->> 'decisionId')::uuid
    for update;
  exception when others then
    raise exception 'corporate_governance_invalid_input';
  end;
  if not found then
    raise exception 'corporate_governance_not_found';
  end if;
  v_actor_id := corporate_governance.assert_owner_v1(
    v_decision.company_id, v_decision.income_year,
    p_verified_subject, true
  );
  if p_request ->> 'companyId' <> v_decision.company_id::text
    or p_request ->> 'documentSetId' <> v_decision.document_set_id::text
    or p_request ->> 'decisionHash' <> v_decision.decision_hash
    or v_event_kind not in ('signing_requested', 'superseded', 'rejected')
    or coalesce(p_request ->> 'idempotencyKey', '')
      !~ '^[A-Za-z0-9._:-]{16,255}$'
    or pg_catalog.jsonb_typeof(p_request -> 'metadata')
      is distinct from 'object'
  then
    raise exception 'corporate_governance_invalid_input';
  end if;
  v_fingerprint := corporate_governance.request_fingerprint_v1(p_request);
  select event.* into v_existing
  from corporate_governance.annual_close_events event
  where event.id = (p_request ->> 'eventId')::uuid
    or (event.decision_id = v_decision.id and event.event_kind = v_event_kind)
    or (
      event.created_by = v_actor_id
      and event.company_id = v_decision.company_id
      and event.idempotency_key = p_request ->> 'idempotencyKey'
    )
  order by event.id = (p_request ->> 'eventId')::uuid desc
  limit 1;
  if found then
    if v_existing.id <> (p_request ->> 'eventId')::uuid
      or v_existing.event_kind <> v_event_kind
      or v_existing.idempotency_key <> p_request ->> 'idempotencyKey'
      or v_existing.request_fingerprint <> v_fingerprint
    then
      raise exception 'corporate_governance_idempotency_conflict';
    end if;
    return corporate_governance.annual_close_lifecycle_v1(
      v_decision.id, true
    );
  end if;
  if exists (
      select 1 from corporate_governance.annual_close_finalizations item
      where item.decision_id = v_decision.id
    )
    or exists (
      select 1 from corporate_governance.annual_close_events event
      where event.decision_id = v_decision.id
        and event.event_kind in ('rejected', 'superseded')
    )
    or (
      v_event_kind = 'signing_requested'
      and not exists (
        select 1 from corporate_governance.annual_close_events event
        where event.decision_id = v_decision.id
          and event.event_kind = 'facts_approved'
      )
    )
  then
    raise exception 'corporate_governance_invalid_input';
  end if;
  insert into corporate_governance.annual_close_events (
    id, decision_id, document_set_id, company_id, income_year,
    event_kind, decision_hash, metadata, idempotency_key, correlation_id,
    request_fingerprint, created_by
  ) values (
    (p_request ->> 'eventId')::uuid, v_decision.id,
    v_decision.document_set_id, v_decision.company_id,
    v_decision.income_year, v_event_kind, v_decision.decision_hash,
    p_request -> 'metadata', p_request ->> 'idempotencyKey',
    p_request ->> 'correlationId', v_fingerprint, v_actor_id
  );
  return corporate_governance.annual_close_lifecycle_v1(
    v_decision.id, false
  );
end;
$function$;

create or replace function
corporate_governance.attest_annual_close_signed_artifact_v1(
  p_request jsonb,
  p_verified_subject text
)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $function$
declare
  v_actor_id uuid;
  v_decision corporate_governance.annual_close_decisions%rowtype;
  v_unsigned corporate_governance.annual_close_artifacts%rowtype;
  v_existing corporate_governance.annual_close_events%rowtype;
  v_fingerprint text;
begin
  begin
    perform (p_request ->> 'unsignedArtifactId')::uuid;
    perform (p_request ->> 'signedArtifactId')::uuid;
    perform (p_request ->> 'signedDocumentId')::uuid;
    select decision.* into v_decision
    from corporate_governance.annual_close_decisions decision
    where decision.id = (p_request ->> 'decisionId')::uuid
    for update;
  exception when others then
    raise exception 'corporate_governance_invalid_input';
  end;
  if not found then
    raise exception 'corporate_governance_not_found';
  end if;
  v_actor_id := corporate_governance.assert_owner_v1(
    v_decision.company_id, v_decision.income_year,
    p_verified_subject, true
  );
  if p_request ->> 'companyId' <> v_decision.company_id::text
    or p_request ->> 'documentSetId' <> v_decision.document_set_id::text
    or p_request ->> 'decisionHash' <> v_decision.decision_hash
    or p_request ->> 'artifactKind' not in (
      'annual_board_minutes', 'annual_general_meeting_minutes'
    )
    or coalesce(p_request ->> 'contentSha256', '')
      !~ '^[0-9a-f]{64}$'
    or (p_request ->> 'byteLength')::bigint not between 1 and 10485760
    or pg_catalog.btrim(coalesce(p_request ->> 'filename', '')) = ''
    or pg_catalog.char_length(p_request ->> 'filename') > 255
    or pg_catalog.jsonb_typeof(p_request -> 'signers')
      is distinct from 'array'
    or pg_catalog.jsonb_array_length(p_request -> 'signers') = 0
    or coalesce(p_request ->> 'idempotencyKey', '')
      !~ '^[A-Za-z0-9._:-]{16,255}$'
  then
    raise exception 'corporate_governance_invalid_input';
  end if;
  if exists (
    select 1
    from pg_catalog.jsonb_array_elements(p_request -> 'signers') signer
    where pg_catalog.jsonb_typeof(signer) is distinct from 'string'
      or pg_catalog.btrim(signer #>> '{}') = ''
  ) then
    raise exception 'corporate_governance_invalid_input';
  end if;
  v_fingerprint := corporate_governance.request_fingerprint_v1(p_request);
  select event.* into v_existing
  from corporate_governance.annual_close_events event
  where event.created_by = v_actor_id
    and event.company_id = v_decision.company_id
    and event.idempotency_key = p_request ->> 'idempotencyKey';
  if found then
    if v_existing.event_kind <> 'signed_copy_attested'
      or v_existing.artifact_id <> (p_request ->> 'signedArtifactId')::uuid
      or v_existing.content_sha256 <> p_request ->> 'contentSha256'
      or v_existing.request_fingerprint <> v_fingerprint
    then
      raise exception 'corporate_governance_idempotency_conflict';
    end if;
    return corporate_governance.annual_close_lifecycle_v1(
      v_decision.id, true
    );
  end if;
  if not exists (
      select 1 from corporate_governance.annual_close_events event
      where event.decision_id = v_decision.id
        and event.event_kind = 'facts_approved'
    )
    or exists (
      select 1 from corporate_governance.annual_close_events event
      where event.decision_id = v_decision.id
        and event.event_kind in ('rejected', 'superseded')
    )
    or exists (
      select 1 from corporate_governance.annual_close_finalizations item
      where item.decision_id = v_decision.id
    )
  then
    raise exception 'corporate_governance_invalid_input';
  end if;
  select artifact.* into v_unsigned
  from corporate_governance.annual_close_artifacts artifact
  where artifact.id = (p_request ->> 'unsignedArtifactId')::uuid
    and artifact.decision_id = v_decision.id
    and artifact.document_set_id = v_decision.document_set_id
    and artifact.variant = 'unsigned'
    and artifact.artifact_kind = p_request ->> 'artifactKind'
  for share;
  if not found then
    raise exception 'corporate_governance_invalid_input';
  end if;
  insert into corporate_governance.annual_close_artifacts (
    id, decision_id, document_set_id, company_id, income_year,
    artifact_kind, variant, document_id, content_sha256, byte_length,
    supersedes_artifact_id, created_by
  ) values (
    (p_request ->> 'signedArtifactId')::uuid, v_decision.id,
    v_decision.document_set_id, v_decision.company_id,
    v_decision.income_year, v_unsigned.artifact_kind,
    'signed_owner_attested', (p_request ->> 'signedDocumentId')::uuid,
    p_request ->> 'contentSha256', (p_request ->> 'byteLength')::bigint,
    v_unsigned.id, v_actor_id
  );
  insert into corporate_governance.annual_close_events (
    decision_id, document_set_id, company_id, income_year, artifact_id,
    event_kind, decision_hash, content_sha256, metadata,
    idempotency_key, correlation_id, request_fingerprint, created_by
  ) values (
    v_decision.id, v_decision.document_set_id, v_decision.company_id,
    v_decision.income_year, (p_request ->> 'signedArtifactId')::uuid,
    'signed_copy_attested', v_decision.decision_hash,
    p_request ->> 'contentSha256',
    pg_catalog.jsonb_build_object(
      'signers', p_request -> 'signers',
      'attestation', 'owner_attested_external_signature',
      'unsignedArtifactId', v_unsigned.id,
      'signedDocumentId', (p_request ->> 'signedDocumentId')::uuid,
      'filename', p_request ->> 'filename'
    ),
    p_request ->> 'idempotencyKey', p_request ->> 'correlationId',
    v_fingerprint, v_actor_id
  );
  return corporate_governance.annual_close_lifecycle_v1(
    v_decision.id, false
  );
end;
$function$;

create or replace function corporate_governance.finalize_annual_close_v1(
  p_request jsonb,
  p_verified_subject text
)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $function$
declare
  v_actor_id uuid;
  v_decision corporate_governance.annual_close_decisions%rowtype;
  v_existing corporate_governance.annual_close_finalizations%rowtype;
  v_fingerprint text;
  v_signed_hashes jsonb;
begin
  begin
    select decision.* into v_decision
    from corporate_governance.annual_close_decisions decision
    where decision.id = (p_request ->> 'decisionId')::uuid
    for update;
  exception when others then
    raise exception 'corporate_governance_invalid_input';
  end;
  if not found then
    raise exception 'corporate_governance_not_found';
  end if;
  v_actor_id := corporate_governance.assert_owner_v1(
    v_decision.company_id, v_decision.income_year,
    p_verified_subject, true
  );
  v_fingerprint := corporate_governance.request_fingerprint_v1(p_request);
  select item.* into v_existing
  from corporate_governance.annual_close_finalizations item
  where item.id = (p_request ->> 'finalizationId')::uuid
    or item.decision_id = v_decision.id
    or (
      item.created_by = v_actor_id
      and item.company_id = v_decision.company_id
      and item.idempotency_key = p_request ->> 'idempotencyKey'
    )
  order by item.id = (p_request ->> 'finalizationId')::uuid desc
  limit 1;
  if found then
    if v_existing.id <> (p_request ->> 'finalizationId')::uuid
      or v_existing.idempotency_key <> p_request ->> 'idempotencyKey'
      or v_existing.request_fingerprint <> v_fingerprint
    then
      raise exception 'corporate_governance_idempotency_conflict';
    end if;
    return corporate_governance.annual_close_lifecycle_v1(
      v_decision.id, true
    );
  end if;
  select pg_catalog.jsonb_object_agg(
    artifact.artifact_kind, artifact.content_sha256
  ) into v_signed_hashes
  from corporate_governance.annual_close_artifacts artifact
  where artifact.decision_id = v_decision.id
    and artifact.variant = 'signed_owner_attested';
  if p_request ->> 'companyId' <> v_decision.company_id::text
    or p_request ->> 'documentSetId' <> v_decision.document_set_id::text
    or p_request ->> 'decisionHash' <> v_decision.decision_hash
    or coalesce(p_request ->> 'idempotencyKey', '')
      !~ '^[A-Za-z0-9._:-]{16,255}$'
    or not (
      coalesce(v_signed_hashes, '{}'::jsonb) ? 'annual_board_minutes'
    )
    or not (
      coalesce(v_signed_hashes, '{}'::jsonb)
        ? 'annual_general_meeting_minutes'
    )
    or exists (
      select 1 from corporate_governance.annual_close_events event
      where event.decision_id = v_decision.id
        and event.event_kind in ('rejected', 'superseded')
    )
  then
    raise exception 'corporate_governance_invalid_input';
  end if;
  insert into corporate_governance.annual_close_finalizations (
    id, decision_id, document_set_id, company_id, income_year,
    annual_close_source_id, decision_hash, signed_artifact_hashes,
    idempotency_key, correlation_id, request_fingerprint, created_by
  ) values (
    (p_request ->> 'finalizationId')::uuid, v_decision.id,
    v_decision.document_set_id, v_decision.company_id,
    v_decision.income_year, v_decision.annual_close_source_id,
    v_decision.decision_hash, v_signed_hashes,
    p_request ->> 'idempotencyKey', p_request ->> 'correlationId',
    v_fingerprint, v_actor_id
  );
  return corporate_governance.annual_close_lifecycle_v1(
    v_decision.id, false
  );
end;
$function$;

reset role;

revoke all on function corporate_governance.propose_annual_close_v1(
  jsonb, jsonb, jsonb, jsonb, text
) from public, anon, authenticated, service_role,
  corporate_governance_workflow_executor;
grant execute on function corporate_governance.propose_annual_close_v1(
  jsonb, jsonb, jsonb, jsonb, text
) to corporate_governance_workflow_executor;
revoke all on function
  corporate_governance.register_annual_close_documents_v1(jsonb, text)
from public, anon, authenticated, service_role,
  corporate_governance_workflow_executor;
grant execute on function
  corporate_governance.register_annual_close_documents_v1(jsonb, text)
to corporate_governance_workflow_executor;
revoke all on function corporate_governance.approve_annual_close_v1(
  jsonb, text
) from public, anon, authenticated, service_role,
  corporate_governance_workflow_executor;
grant execute on function corporate_governance.approve_annual_close_v1(
  jsonb, text
) to corporate_governance_workflow_executor;
revoke all on function corporate_governance.record_annual_close_event_v1(
  jsonb, text
) from public, anon, authenticated, service_role,
  corporate_governance_workflow_executor;
grant execute on function corporate_governance.record_annual_close_event_v1(
  jsonb, text
) to corporate_governance_workflow_executor;
revoke all on function
  corporate_governance.attest_annual_close_signed_artifact_v1(jsonb, text)
from public, anon, authenticated, service_role,
  corporate_governance_workflow_executor;
grant execute on function
  corporate_governance.attest_annual_close_signed_artifact_v1(jsonb, text)
to corporate_governance_workflow_executor;
revoke all on function corporate_governance.finalize_annual_close_v1(
  jsonb, text
) from public, anon, authenticated, service_role,
  corporate_governance_workflow_executor;
grant execute on function corporate_governance.finalize_annual_close_v1(
  jsonb, text
) to corporate_governance_workflow_executor;
revoke all on function corporate_governance.annual_close_lifecycle_v1(
  uuid, boolean
) from public, anon, authenticated, service_role,
  corporate_governance_workflow_executor;

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
