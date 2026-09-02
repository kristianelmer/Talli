-- Canonical owner-dividend governance lifecycle (#144).
begin;

set local lock_timeout = '5s';
set local statement_timeout = '120s';

do $roles$
begin
  if not exists (
    select 1 from pg_catalog.pg_roles
    where rolname = 'corporate_governance_store_owner'
  ) then
    create role corporate_governance_store_owner
      nologin noinherit nobypassrls;
  end if;
  if not exists (
    select 1 from pg_catalog.pg_roles
    where rolname = 'corporate_governance_workflow_executor'
  ) then
    create role corporate_governance_workflow_executor
      nologin noinherit nobypassrls;
  end if;
  if not exists (
    select 1 from pg_catalog.pg_roles
    where rolname = 'corporate_governance_ledger_bridge_owner'
  ) then
    create role corporate_governance_ledger_bridge_owner
      nologin noinherit nobypassrls;
  end if;
end
$roles$;

alter role corporate_governance_store_owner
  nologin noinherit nobypassrls;
alter role corporate_governance_workflow_executor
  nologin noinherit nobypassrls;
alter role corporate_governance_ledger_bridge_owner
  nologin noinherit nobypassrls;

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

select pg_catalog.set_config(
  'talli.corporate_governance_migration_principal', current_user, true
);
set local role ledger_store_owner;
grant usage, create on schema backend_system to ledger_store_owner;
do $backend_system_schema_authority$
begin
  execute pg_catalog.format(
    'grant usage, create on schema backend_system to %I',
    pg_catalog.current_setting(
      'talli.corporate_governance_migration_principal'
    )
  );
end
$backend_system_schema_authority$;
reset role;

create schema if not exists corporate_governance
  authorization corporate_governance_store_owner;
revoke all on schema corporate_governance
from public, anon, authenticated, service_role;
grant usage on schema corporate_governance
to corporate_governance_workflow_executor;
grant usage on schema public to corporate_governance_store_owner;
grant usage on schema extensions to corporate_governance_store_owner;
grant execute on function extensions.digest(text, text)
to corporate_governance_store_owner;
grant execute on function
  public.company_access_auth_uid_v1(),
  public.company_access_auth_jwt_v1(),
  public.company_access_has_current_agreement_v1(uuid),
  public.company_access_is_accepted_owner_v1(uuid),
  public.company_access_company_year_allows_consequential_v1(uuid, integer),
  public.assert_corporate_decision_persisted_facts(
    uuid, integer, text, uuid, jsonb, text
  )
to corporate_governance_store_owner;

create table corporate_governance.owner_dividend_accounting_policies (
  policy_version text primary key check (pg_catalog.btrim(policy_version) <> ''),
  declaration_debit_account text not null check (
    declaration_debit_account ~ '^[0-9]{4}$'
  ),
  dividend_payable_account text not null check (
    dividend_payable_account ~ '^[0-9]{4}$'
  ),
  bank_account text not null check (bank_account ~ '^[0-9]{4}$'),
  reviewer text not null check (pg_catalog.btrim(reviewer) <> ''),
  reviewed_at timestamptz not null,
  evidence_reference text not null check (
    pg_catalog.btrim(evidence_reference) <> ''
  ),
  supersedes_policy_version text unique references
    corporate_governance.owner_dividend_accounting_policies(policy_version)
    on delete restrict,
  enabled boolean not null,
  recorded_by uuid not null references auth.users(id) on delete restrict,
  created_at timestamptz not null,
  check (declaration_debit_account <> dividend_payable_account),
  check (dividend_payable_account <> bank_account)
);

create table corporate_governance.owner_dividend_decisions (
  id uuid primary key,
  document_set_id uuid not null unique,
  company_id uuid not null references public.companies(id) on delete restrict,
  income_year integer not null check (income_year between 2000 and 2100),
  annual_close_source_id uuid not null references public.annual_data(id)
    on delete restrict,
  source_hash text not null check (source_hash ~ '^[0-9a-f]{64}$'),
  canonical_input jsonb not null check (
    pg_catalog.jsonb_typeof(canonical_input) = 'object'
  ),
  decision_hash text not null check (decision_hash ~ '^[0-9a-f]{64}$'),
  declared_amount_ore bigint not null check (declared_amount_ore > 0),
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
  check (canonical_input ->> 'decisionId' = id::text),
  check (canonical_input ->> 'documentSetId' = document_set_id::text),
  check (canonical_input ->> 'companyId' = company_id::text),
  check ((canonical_input ->> 'incomeYear')::integer = income_year),
  check (canonical_input ->> 'sourceHash' = source_hash),
  check (canonical_input ->> 'decisionHash' = decision_hash),
  check (
    (canonical_input -> 'dividend' ->> 'amountOre')::bigint
      = declared_amount_ore
  )
);

create table corporate_governance.owner_dividend_artifacts (
  id uuid primary key,
  decision_id uuid not null references
    corporate_governance.owner_dividend_decisions(id) on delete restrict,
  document_set_id uuid not null,
  company_id uuid not null,
  income_year integer not null,
  artifact_kind text not null check (artifact_kind in (
    'dividend_board_proposal',
    'dividend_general_meeting_minutes'
  )),
  document_id uuid not null,
  content_sha256 text not null check (content_sha256 ~ '^[0-9a-f]{64}$'),
  byte_length bigint not null check (byte_length between 1 and 10485760),
  created_by uuid not null references auth.users(id) on delete restrict,
  created_at timestamptz not null default pg_catalog.statement_timestamp(),
  unique (decision_id, artifact_kind),
  unique (decision_id, document_id),
  unique (company_id, income_year, id),
  foreign key (company_id, income_year, decision_id)
    references corporate_governance.owner_dividend_decisions(
      company_id, income_year, id
    ) on delete restrict
);

create table corporate_governance.owner_dividend_events (
  id uuid primary key default pg_catalog.gen_random_uuid(),
  decision_id uuid not null references
    corporate_governance.owner_dividend_decisions(id) on delete restrict,
  document_set_id uuid not null,
  company_id uuid not null,
  income_year integer not null,
  event_kind text not null check (event_kind in (
    'documents_registered', 'facts_approved'
  )),
  decision_hash text not null check (decision_hash ~ '^[0-9a-f]{64}$'),
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
  foreign key (company_id, income_year, decision_id)
    references corporate_governance.owner_dividend_decisions(
      company_id, income_year, id
    ) on delete restrict
);

create table corporate_governance.owner_dividend_finalizations (
  id uuid primary key,
  decision_id uuid not null unique references
    corporate_governance.owner_dividend_decisions(id) on delete restrict,
  document_set_id uuid not null,
  company_id uuid not null,
  income_year integer not null,
  decision_hash text not null check (decision_hash ~ '^[0-9a-f]{64}$'),
  holding_action_id uuid not null unique,
  accounting_entry_id uuid not null unique references ledger.entries(id)
    on delete restrict,
  declared_amount_ore bigint not null check (declared_amount_ore > 0),
  signed_artifact_hashes jsonb not null check (
    pg_catalog.jsonb_typeof(signed_artifact_hashes) = 'object'
  ),
  accounting_policy_version text not null references
    corporate_governance.owner_dividend_accounting_policies(policy_version)
    on delete restrict,
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
  foreign key (company_id, income_year, decision_id)
    references corporate_governance.owner_dividend_decisions(
      company_id, income_year, id
    ) on delete restrict
);

create table corporate_governance.owner_dividend_payments (
  id uuid primary key,
  decision_id uuid not null references
    corporate_governance.owner_dividend_decisions(id) on delete restrict,
  document_set_id uuid not null,
  company_id uuid not null,
  income_year integer not null,
  decision_hash text not null check (decision_hash ~ '^[0-9a-f]{64}$'),
  holding_action_id uuid not null unique,
  accounting_entry_id uuid not null unique references ledger.entries(id)
    on delete restrict,
  bank_transaction_id uuid not null unique references banking.transactions(id)
    on delete restrict,
  payment_amount_ore bigint not null check (payment_amount_ore > 0),
  bank_transaction_date date not null,
  bank_signed_amount numeric(20, 2) not null check (bank_signed_amount < 0),
  bank_source_sha256 text not null check (
    bank_source_sha256 ~ '^[0-9a-f]{64}$'
  ),
  accounting_policy_version text not null references
    corporate_governance.owner_dividend_accounting_policies(policy_version)
    on delete restrict,
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
  foreign key (company_id, income_year, decision_id)
    references corporate_governance.owner_dividend_decisions(
      company_id, income_year, id
    ) on delete restrict,
  check (
    bank_transaction_date >= pg_catalog.make_date(income_year, 1, 1)
    and bank_transaction_date <= pg_catalog.make_date(income_year, 12, 31)
  )
);

create index owner_dividend_decisions_company_year_idx
on corporate_governance.owner_dividend_decisions(
  company_id, income_year, created_at, id
);
create index owner_dividend_events_decision_idx
on corporate_governance.owner_dividend_events(
  decision_id, created_at, id
);
create index owner_dividend_payments_decision_idx
on corporate_governance.owner_dividend_payments(
  decision_id, created_at, id
);

insert into corporate_governance.owner_dividend_accounting_policies (
  policy_version, declaration_debit_account, dividend_payable_account,
  bank_account, reviewer, reviewed_at, evidence_reference,
  supersedes_policy_version, enabled, recorded_by, created_at
)
select
  policy.policy_version, policy.declaration_debit_account,
  policy.dividend_payable_account, policy.bank_account, policy.reviewer,
  policy.reviewed_at, policy.evidence_reference,
  policy.supersedes_policy_version, policy.enabled, policy.recorded_by,
  policy.created_at
from public.corporate_accounting_policies policy
on conflict (policy_version) do nothing;

-- #148 still owns the shared signed-artifact lifecycle and its owner pages.
-- These exact, private compatibility routines preserve the characterized hard
-- block and project committed #144 receipts until that stage exits.
create or replace function backend_system.owner_dividend_signed_evidence_v1(
  p_decision_id uuid,
  p_document_set_id uuid,
  p_company_id uuid,
  p_income_year integer,
  p_decision_hash text
)
returns jsonb
language plpgsql
stable
security definer
set search_path = ''
as $function$
declare
  v_count integer;
  v_hashes jsonb;
  v_primary_document_id uuid;
begin
  if not exists (
    select 1
    from public.corporate_decisions decision
    join public.corporate_document_sets document_set
      on document_set.decision_id = decision.id
    where decision.id = p_decision_id
      and decision.company_id = p_company_id
      and decision.income_year = p_income_year
      and decision.decision_kind = 'owner_dividend'
      and decision.decision_hash = p_decision_hash
      and document_set.id = p_document_set_id
      and document_set.decision_hash = p_decision_hash
  ) then
    raise exception 'corporate_governance_missing_signed_artifacts';
  end if;
  select pg_catalog.count(*),
    pg_catalog.jsonb_object_agg(
      artifact.artifact_kind, artifact.content_sha256
    )
  into v_count, v_hashes
  from public.corporate_document_artifacts artifact
  where artifact.set_id = p_document_set_id
    and artifact.variant = 'signed_owner_attested'
    and artifact.artifact_kind in (
      'dividend_board_proposal',
      'dividend_general_meeting_minutes'
    );
  select artifact.document_id into v_primary_document_id
  from public.corporate_document_artifacts artifact
  where artifact.set_id = p_document_set_id
    and artifact.variant = 'signed_owner_attested'
    and artifact.artifact_kind = 'dividend_general_meeting_minutes';
  if v_count <> 2
    or not coalesce(v_hashes ? 'dividend_board_proposal', false)
    or not coalesce(
      v_hashes ? 'dividend_general_meeting_minutes', false
    )
    or v_primary_document_id is null
  then
    raise exception 'corporate_governance_missing_signed_artifacts';
  end if;
  return pg_catalog.jsonb_build_object(
    'signedArtifactHashes', v_hashes,
    'primaryDocumentId', v_primary_document_id
  );
end;
$function$;

create or replace function
backend_system.project_owner_dividend_finalization_v1(
  p_request jsonb,
  p_accounting_policy_version text,
  p_signed_artifact_hashes jsonb,
  p_verified_subject text
)
returns void
language plpgsql
security definer
set search_path = ''
as $function$
declare
  v_actor_id uuid := public.company_access_auth_uid_v1();
  v_decision public.corporate_decisions%rowtype;
  v_primary_document_id uuid;
begin
  if v_actor_id is null
    or p_verified_subject !~ '^[0-9a-fA-F-]{36}$'
    or v_actor_id is distinct from p_verified_subject::uuid
  then
    raise exception 'corporate_governance_forbidden';
  end if;
  select decision.* into v_decision
  from public.corporate_decisions decision
  where decision.id = (p_request ->> 'decisionId')::uuid
    and decision.company_id = (p_request ->> 'companyId')::uuid
    and decision.income_year = (p_request ->> 'incomeYear')::integer
    and decision.decision_hash = p_request ->> 'decisionHash';
  if not found or not exists (
    select 1 from public.corporate_document_sets document_set
    where document_set.id = (p_request ->> 'documentSetId')::uuid
      and document_set.decision_id = v_decision.id
      and document_set.decision_hash = v_decision.decision_hash
  ) then
    raise exception 'corporate_governance_invalid_input';
  end if;
  select artifact.document_id into v_primary_document_id
  from public.corporate_document_artifacts artifact
  where artifact.set_id = (p_request ->> 'documentSetId')::uuid
    and artifact.variant = 'signed_owner_attested'
    and artifact.artifact_kind = 'dividend_general_meeting_minutes';

  insert into public.holding_actions (
    id, company_id, income_year, action_type, action_date, payload,
    ledger_entry_id, document_id, risk_level, created_by
  ) values (
    (p_request ->> 'holdingActionId')::uuid, v_decision.company_id,
    v_decision.income_year, 'dividend_to_owner',
    (v_decision.canonical_input -> 'general_meeting' ->> 'meeting_date')::date,
    v_decision.canonical_input || pg_catalog.jsonb_build_object(
      'action_kind', 'owner_dividend_declaration',
      'corporate_decision_id', v_decision.id,
      'accounting_policy_version', p_accounting_policy_version
    ),
    (p_request ->> 'ledgerEntryId')::uuid, v_primary_document_id,
    'ready', v_actor_id
  );
  insert into public.corporate_decision_finalizations (
    id, company_id, income_year, decision_id, finalization_kind,
    holding_action_id, ledger_entry_id, decision_hash,
    signed_artifact_hashes, accounting_policy_version, created_by
  ) values (
    (p_request ->> 'finalizationId')::uuid, v_decision.company_id,
    v_decision.income_year, v_decision.id, 'owner_dividend_declared',
    (p_request ->> 'holdingActionId')::uuid,
    (p_request ->> 'ledgerEntryId')::uuid, v_decision.decision_hash,
    p_signed_artifact_hashes, p_accounting_policy_version, v_actor_id
  );
  insert into public.corporate_document_events (
    id, company_id, income_year, decision_id, set_id, event_kind,
    actor_id, decision_hash, metadata, idempotency_key
  ) values (
    (p_request ->> 'finalizationId')::uuid, v_decision.company_id,
    v_decision.income_year, v_decision.id,
    (p_request ->> 'documentSetId')::uuid, 'finalized', v_actor_id,
    v_decision.decision_hash, pg_catalog.jsonb_build_object(
      'finalization_id', (p_request ->> 'finalizationId')::uuid,
      'finalization_kind', 'owner_dividend_declared',
      'signed_artifact_hashes', p_signed_artifact_hashes,
      'accounting_policy_version', p_accounting_policy_version
    ), p_request ->> 'idempotencyKey'
  );
  insert into public.audit_events (
    company_id, actor_id, category, action, message
  ) values (
    v_decision.company_id, v_actor_id, 'corporate_documents',
    'corporate_decision_finalized',
    'Owner finalized an approved and owner-attested corporate decision.'
  );
end;
$function$;

create or replace function
backend_system.project_owner_dividend_payment_v1(
  p_request jsonb,
  p_payment_amount_ore bigint,
  p_accounting_policy_version text,
  p_verified_subject text
)
returns void
language plpgsql
security definer
set search_path = ''
as $function$
declare
  v_actor_id uuid := public.company_access_auth_uid_v1();
  v_decision public.corporate_decisions%rowtype;
  v_finalization public.corporate_decision_finalizations%rowtype;
  v_remaining_ore bigint;
begin
  if v_actor_id is null
    or p_verified_subject !~ '^[0-9a-fA-F-]{36}$'
    or v_actor_id is distinct from p_verified_subject::uuid
  then
    raise exception 'corporate_governance_forbidden';
  end if;
  select decision.* into v_decision
  from public.corporate_decisions decision
  where decision.id = (p_request ->> 'decisionId')::uuid
    and decision.company_id = (p_request ->> 'companyId')::uuid
    and decision.income_year = (p_request ->> 'incomeYear')::integer
    and decision.decision_hash = p_request ->> 'decisionHash';
  select finalization.* into v_finalization
  from public.corporate_decision_finalizations finalization
  where finalization.decision_id = v_decision.id
    and finalization.finalization_kind = 'owner_dividend_declared'
    and finalization.accounting_policy_version = p_accounting_policy_version;
  if v_decision.id is null or v_finalization.id is null then
    raise exception 'corporate_governance_finalized_declaration_required';
  end if;
  select
    (v_decision.canonical_input -> 'dividend' ->> 'amount_ore')::bigint
      - coalesce(pg_catalog.sum(
        (event.metadata ->> 'amount_ore')::bigint
      ), 0)
      - p_payment_amount_ore
  into v_remaining_ore
  from public.corporate_document_events event
  where event.decision_id = v_decision.id
    and event.event_kind = 'payment_recorded';

  insert into public.holding_actions (
    id, company_id, income_year, action_type, action_date, payload,
    ledger_entry_id, bank_transaction_id, risk_level, created_by
  ) values (
    (p_request ->> 'holdingActionId')::uuid, v_decision.company_id,
    v_decision.income_year, 'dividend_to_owner',
    (p_request ->> 'bankTransactionDate')::date,
    pg_catalog.jsonb_build_object(
      'action_kind', 'owner_dividend_payment',
      'corporate_decision_id', v_decision.id,
      'corporate_finalization_id', v_finalization.id,
      'amount_ore', p_payment_amount_ore,
      'remaining_payable_ore', v_remaining_ore,
      'accounting_policy_version', p_accounting_policy_version
    ),
    (p_request ->> 'ledgerEntryId')::uuid,
    (p_request ->> 'bankTransactionId')::uuid, 'ready', v_actor_id
  );
  insert into public.corporate_document_events (
    id, company_id, income_year, decision_id, set_id, event_kind,
    actor_id, decision_hash, metadata, idempotency_key
  ) values (
    (p_request ->> 'paymentEventId')::uuid, v_decision.company_id,
    v_decision.income_year, v_decision.id,
    (p_request ->> 'documentSetId')::uuid, 'payment_recorded',
    v_actor_id, v_decision.decision_hash,
    pg_catalog.jsonb_build_object(
      'bank_transaction_id', (p_request ->> 'bankTransactionId')::uuid,
      'holding_action_id', (p_request ->> 'holdingActionId')::uuid,
      'ledger_entry_id', (p_request ->> 'ledgerEntryId')::uuid,
      'amount_ore', p_payment_amount_ore,
      'remaining_payable_ore', v_remaining_ore,
      'accounting_policy_version', p_accounting_policy_version
    ), p_request ->> 'idempotencyKey'
  );
  insert into public.audit_events (
    company_id, actor_id, category, action, message
  ) values (
    v_decision.company_id, v_actor_id, 'corporate_documents',
    'owner_dividend_payment_recorded',
    'Bank payment matched to finalized owner dividend payable.'
  );
end;
$function$;

revoke all on function
  backend_system.owner_dividend_signed_evidence_v1(
    uuid, uuid, uuid, integer, text
  ),
  backend_system.project_owner_dividend_finalization_v1(
    jsonb, text, jsonb, text
  ),
  backend_system.project_owner_dividend_payment_v1(
    jsonb, bigint, text, text
  )
from public, anon, authenticated, service_role,
  corporate_governance_workflow_executor;
grant usage on schema backend_system to corporate_governance_store_owner;
grant execute on function
  backend_system.owner_dividend_signed_evidence_v1(
    uuid, uuid, uuid, integer, text
  ),
  backend_system.project_owner_dividend_finalization_v1(
    jsonb, text, jsonb, text
  ),
  backend_system.project_owner_dividend_payment_v1(
    jsonb, bigint, text, text
  )
to corporate_governance_store_owner;

set local role ledger_store_owner;
do $backend_system_schema_authority_revoke$
begin
  execute pg_catalog.format(
    'revoke create on schema backend_system from %I',
    pg_catalog.current_setting(
      'talli.corporate_governance_migration_principal'
    )
  );
end
$backend_system_schema_authority_revoke$;
revoke create on schema backend_system from ledger_store_owner;
reset role;

-- Import the predecessor owner-dividend slice before forced RLS is enabled.
-- IDs, hashes, actors, timestamps, Ledger references, and bank references stay
-- stable so rollback/recutover can reconcile without inventing business facts.
insert into corporate_governance.owner_dividend_decisions (
  id, document_set_id, company_id, income_year, annual_close_source_id,
  source_hash, canonical_input, decision_hash, declared_amount_ore,
  idempotency_key, correlation_id, request_fingerprint, created_by, created_at
)
select
  decision.id, document_set.id, decision.company_id, decision.income_year,
  decision.annual_close_source_id, decision.source_hash,
  pg_catalog.jsonb_build_object(
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
      'resultAfterTaxOre',
        (decision.canonical_input -> 'financial_totals'
          ->> 'result_after_tax_ore')::bigint,
      'equityOre',
        (decision.canonical_input -> 'financial_totals'
          ->> 'equity_ore')::bigint,
      'availableDistributionOre',
        (decision.canonical_input -> 'financial_totals'
          ->> 'available_distribution_ore')::bigint,
      'cashOre',
        (decision.canonical_input -> 'financial_totals'
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
    'dividend', pg_catalog.jsonb_build_object(
      'amountOre',
        (decision.canonical_input -> 'dividend' ->> 'amount_ore')::bigint,
      'paymentDate',
        decision.canonical_input -> 'dividend' ->> 'payment_date',
      'liquidityAfterPaymentOre',
        (decision.canonical_input -> 'dividend'
          ->> 'liquidity_after_payment_ore')::bigint,
      'allocations', coalesce((
        select pg_catalog.jsonb_agg(pg_catalog.jsonb_build_object(
          'shareholderId', allocation.item ->> 'shareholder_id',
          'amountOre', (allocation.item ->> 'amount_ore')::bigint
        ) order by allocation.ordinality)
        from pg_catalog.jsonb_array_elements(
          decision.canonical_input -> 'dividend' -> 'allocations'
        ) with ordinality allocation(item, ordinality)
      ), '[]'::jsonb)
    ),
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
  ),
  decision.decision_hash,
  (decision.canonical_input -> 'dividend' ->> 'amount_ore')::bigint,
  'legacy-owner-dividend:' || decision.id::text,
  'legacy-owner-dividend:' || decision.id::text,
  pg_catalog.encode(extensions.digest(pg_catalog.jsonb_build_object(
    'legacyDecisionId', decision.id,
    'decisionHash', decision.decision_hash
  )::text, 'sha256'), 'hex'),
  decision.created_by, decision.created_at
from public.corporate_decisions decision
join public.corporate_document_sets document_set
  on document_set.decision_id = decision.id
where decision.decision_kind = 'owner_dividend'
on conflict (id) do nothing;

insert into corporate_governance.owner_dividend_artifacts (
  id, decision_id, document_set_id, company_id, income_year,
  artifact_kind, document_id, content_sha256, byte_length,
  created_by, created_at
)
select
  artifact.id, document_set.decision_id, artifact.set_id,
  artifact.company_id, artifact.income_year, artifact.artifact_kind,
  artifact.document_id, artifact.content_sha256, artifact.byte_length,
  artifact.created_by, artifact.created_at
from public.corporate_document_artifacts artifact
join public.corporate_document_sets document_set
  on document_set.id = artifact.set_id
join public.corporate_decisions decision
  on decision.id = document_set.decision_id
where decision.decision_kind = 'owner_dividend'
  and artifact.variant = 'unsigned'
on conflict (id) do nothing;

insert into corporate_governance.owner_dividend_events (
  id, decision_id, document_set_id, company_id, income_year,
  event_kind, decision_hash, idempotency_key, correlation_id,
  request_fingerprint, created_by, created_at
)
select
  event.id, event.decision_id, event.set_id, event.company_id,
  event.income_year, 'documents_registered', event.decision_hash,
  'legacy-event:' || event.id::text,
  'legacy-event:' || event.id::text,
  pg_catalog.encode(extensions.digest(pg_catalog.jsonb_build_object(
    'legacyEventId', event.id, 'eventKind', event.event_kind
  )::text, 'sha256'), 'hex'),
  event.actor_id, event.created_at
from public.corporate_document_events event
join public.corporate_decisions decision on decision.id = event.decision_id
where decision.decision_kind = 'owner_dividend'
  and event.event_kind = 'generated'
on conflict (id) do nothing;

insert into corporate_governance.owner_dividend_events (
  id, decision_id, document_set_id, company_id, income_year,
  event_kind, decision_hash, idempotency_key, correlation_id,
  request_fingerprint, created_by, created_at
)
select
  pg_catalog.md5('owner-dividend-documents:' || decision.id::text)::uuid,
  decision.id, document_set.id, decision.company_id, decision.income_year,
  'documents_registered', decision.decision_hash,
  'legacy-documents:' || decision.id::text,
  'legacy-documents:' || decision.id::text,
  pg_catalog.encode(extensions.digest(pg_catalog.jsonb_build_object(
    'legacyDecisionId', decision.id,
    'eventKind', 'documents_registered'
  )::text, 'sha256'), 'hex'),
  decision.created_by, pg_catalog.max(artifact.created_at)
from public.corporate_decisions decision
join public.corporate_document_sets document_set
  on document_set.decision_id = decision.id
join public.corporate_document_artifacts artifact
  on artifact.set_id = document_set.id and artifact.variant = 'unsigned'
where decision.decision_kind = 'owner_dividend'
  and not exists (
    select 1 from corporate_governance.owner_dividend_events event
    where event.decision_id = decision.id
      and event.event_kind = 'documents_registered'
  )
group by decision.id, document_set.id
having pg_catalog.count(*) = 2
  and pg_catalog.count(distinct artifact.artifact_kind) = 2
on conflict (id) do nothing;

insert into corporate_governance.owner_dividend_events (
  id, decision_id, document_set_id, company_id, income_year,
  event_kind, decision_hash, idempotency_key, correlation_id,
  request_fingerprint, created_by, created_at
)
select
  event.id, event.decision_id, event.set_id, event.company_id,
  event.income_year, 'facts_approved', event.decision_hash,
  'legacy-approval:' || event.id::text,
  'legacy-approval:' || event.id::text,
  pg_catalog.encode(extensions.digest(pg_catalog.jsonb_build_object(
    'legacyEventId', event.id, 'eventKind', 'facts_approved'
  )::text, 'sha256'), 'hex'),
  event.actor_id, event.created_at
from public.corporate_document_events event
join public.corporate_decisions decision on decision.id = event.decision_id
where decision.decision_kind = 'owner_dividend'
  and event.event_kind = 'facts_approved'
on conflict (id) do nothing;

insert into corporate_governance.owner_dividend_finalizations (
  id, decision_id, document_set_id, company_id, income_year,
  decision_hash, holding_action_id, accounting_entry_id,
  declared_amount_ore, signed_artifact_hashes,
  accounting_policy_version, idempotency_key, correlation_id,
  request_fingerprint, created_by, created_at
)
select
  finalization.id, finalization.decision_id, document_set.id,
  finalization.company_id, finalization.income_year,
  finalization.decision_hash, finalization.holding_action_id,
  finalization.ledger_entry_id,
  (decision.canonical_input -> 'dividend' ->> 'amount_ore')::bigint,
  finalization.signed_artifact_hashes,
  finalization.accounting_policy_version,
  'legacy-finalization:' || finalization.id::text,
  'legacy-finalization:' || finalization.id::text,
  pg_catalog.encode(extensions.digest(pg_catalog.jsonb_build_object(
    'legacyFinalizationId', finalization.id,
    'decisionHash', finalization.decision_hash
  )::text, 'sha256'), 'hex'),
  finalization.created_by, finalization.created_at
from public.corporate_decision_finalizations finalization
join public.corporate_decisions decision
  on decision.id = finalization.decision_id
join public.corporate_document_sets document_set
  on document_set.decision_id = decision.id
where finalization.finalization_kind = 'owner_dividend_declared'
on conflict (id) do nothing;

insert into corporate_governance.owner_dividend_payments (
  id, decision_id, document_set_id, company_id, income_year,
  decision_hash, holding_action_id, accounting_entry_id,
  bank_transaction_id, payment_amount_ore, bank_transaction_date,
  bank_signed_amount, bank_source_sha256, accounting_policy_version,
  idempotency_key, correlation_id, request_fingerprint,
  created_by, created_at
)
select
  event.id, event.decision_id, event.set_id, event.company_id,
  event.income_year, event.decision_hash,
  (event.metadata ->> 'holding_action_id')::uuid,
  (event.metadata ->> 'ledger_entry_id')::uuid,
  (event.metadata ->> 'bank_transaction_id')::uuid,
  (event.metadata ->> 'amount_ore')::bigint,
  transaction.transaction_date, transaction.amount,
  transaction.source_hash, finalization.accounting_policy_version,
  'legacy-payment:' || event.id::text,
  'legacy-payment:' || event.id::text,
  pg_catalog.encode(extensions.digest(pg_catalog.jsonb_build_object(
    'legacyPaymentEventId', event.id,
    'bankTransactionId', event.metadata ->> 'bank_transaction_id'
  )::text, 'sha256'), 'hex'),
  event.actor_id, event.created_at
from public.corporate_document_events event
join public.corporate_decisions decision on decision.id = event.decision_id
join public.corporate_decision_finalizations finalization
  on finalization.decision_id = decision.id
join banking.transactions transaction
  on transaction.id = (event.metadata ->> 'bank_transaction_id')::uuid
where decision.decision_kind = 'owner_dividend'
  and event.event_kind = 'payment_recorded'
on conflict (id) do nothing;

alter table corporate_governance.owner_dividend_accounting_policies
  owner to corporate_governance_store_owner;
alter table corporate_governance.owner_dividend_decisions
  owner to corporate_governance_store_owner;
alter table corporate_governance.owner_dividend_artifacts
  owner to corporate_governance_store_owner;
alter table corporate_governance.owner_dividend_events
  owner to corporate_governance_store_owner;
alter table corporate_governance.owner_dividend_finalizations
  owner to corporate_governance_store_owner;
alter table corporate_governance.owner_dividend_payments
  owner to corporate_governance_store_owner;

alter table corporate_governance.owner_dividend_decisions
  enable row level security;
alter table corporate_governance.owner_dividend_accounting_policies
  enable row level security;
alter table corporate_governance.owner_dividend_accounting_policies
  force row level security;
alter table corporate_governance.owner_dividend_decisions
  force row level security;
alter table corporate_governance.owner_dividend_artifacts
  enable row level security;
alter table corporate_governance.owner_dividend_artifacts
  force row level security;
alter table corporate_governance.owner_dividend_events
  enable row level security;
alter table corporate_governance.owner_dividend_events
  force row level security;
alter table corporate_governance.owner_dividend_finalizations
  enable row level security;
alter table corporate_governance.owner_dividend_finalizations
  force row level security;
alter table corporate_governance.owner_dividend_payments
  enable row level security;
alter table corporate_governance.owner_dividend_payments
  force row level security;

revoke all on corporate_governance.owner_dividend_decisions
from public, anon, authenticated, service_role,
  corporate_governance_workflow_executor;
revoke all on corporate_governance.owner_dividend_accounting_policies
from public, anon, authenticated, service_role,
  corporate_governance_workflow_executor;
revoke all on corporate_governance.owner_dividend_artifacts
from public, anon, authenticated, service_role,
  corporate_governance_workflow_executor;
revoke all on corporate_governance.owner_dividend_events
from public, anon, authenticated, service_role,
  corporate_governance_workflow_executor;
revoke all on corporate_governance.owner_dividend_finalizations
from public, anon, authenticated, service_role,
  corporate_governance_workflow_executor;
revoke all on corporate_governance.owner_dividend_payments
from public, anon, authenticated, service_role,
  corporate_governance_workflow_executor;

set local role corporate_governance_store_owner;

create policy governance_reads_accounting_policies
on corporate_governance.owner_dividend_accounting_policies
for select to corporate_governance_store_owner
using (true);

create policy governance_owner_reads_decisions
on corporate_governance.owner_dividend_decisions
for select to corporate_governance_store_owner
using (public.company_access_is_accepted_owner_v1(company_id));
create policy governance_owner_creates_decisions
on corporate_governance.owner_dividend_decisions
for insert to corporate_governance_store_owner
with check (
  created_by = nullif(
    pg_catalog.current_setting('talli.verified_actor_id', true), ''
  )::uuid
  and public.company_access_is_accepted_owner_v1(company_id)
);

create policy governance_owner_reads_artifacts
on corporate_governance.owner_dividend_artifacts
for select to corporate_governance_store_owner
using (public.company_access_is_accepted_owner_v1(company_id));
create policy governance_owner_creates_artifacts
on corporate_governance.owner_dividend_artifacts
for insert to corporate_governance_store_owner
with check (
  created_by = nullif(
    pg_catalog.current_setting('talli.verified_actor_id', true), ''
  )::uuid
  and public.company_access_is_accepted_owner_v1(company_id)
);

create policy governance_owner_reads_events
on corporate_governance.owner_dividend_events
for select to corporate_governance_store_owner
using (public.company_access_is_accepted_owner_v1(company_id));
create policy governance_owner_creates_events
on corporate_governance.owner_dividend_events
for insert to corporate_governance_store_owner
with check (
  created_by = nullif(
    pg_catalog.current_setting('talli.verified_actor_id', true), ''
  )::uuid
  and public.company_access_is_accepted_owner_v1(company_id)
);

create policy governance_owner_reads_finalizations
on corporate_governance.owner_dividend_finalizations
for select to corporate_governance_store_owner
using (public.company_access_is_accepted_owner_v1(company_id));
create policy governance_owner_creates_finalizations
on corporate_governance.owner_dividend_finalizations
for insert to corporate_governance_store_owner
with check (
  created_by = nullif(
    pg_catalog.current_setting('talli.verified_actor_id', true), ''
  )::uuid
  and public.company_access_is_accepted_owner_v1(company_id)
);

create policy governance_owner_reads_payments
on corporate_governance.owner_dividend_payments
for select to corporate_governance_store_owner
using (public.company_access_is_accepted_owner_v1(company_id));
create policy governance_owner_creates_payments
on corporate_governance.owner_dividend_payments
for insert to corporate_governance_store_owner
with check (
  created_by = nullif(
    pg_catalog.current_setting('talli.verified_actor_id', true), ''
  )::uuid
  and public.company_access_is_accepted_owner_v1(company_id)
);

create or replace function corporate_governance.prevent_corporate_governance_mutation()
returns trigger
language plpgsql
security definer
set search_path = ''
as $function$
begin
  raise exception 'corporate_governance_records_are_immutable';
end;
$function$;

create trigger owner_dividend_decisions_immutable
before update or delete on corporate_governance.owner_dividend_decisions
for each row execute function
  corporate_governance.prevent_corporate_governance_mutation();
create trigger owner_dividend_accounting_policies_immutable
before update or delete on
  corporate_governance.owner_dividend_accounting_policies
for each row execute function
  corporate_governance.prevent_corporate_governance_mutation();
create trigger owner_dividend_artifacts_immutable
before update or delete on corporate_governance.owner_dividend_artifacts
for each row execute function
  corporate_governance.prevent_corporate_governance_mutation();
create trigger owner_dividend_events_immutable
before update or delete on corporate_governance.owner_dividend_events
for each row execute function
  corporate_governance.prevent_corporate_governance_mutation();
create trigger owner_dividend_finalizations_immutable
before update or delete on corporate_governance.owner_dividend_finalizations
for each row execute function
  corporate_governance.prevent_corporate_governance_mutation();
create trigger owner_dividend_payments_immutable
before update or delete on corporate_governance.owner_dividend_payments
for each row execute function
  corporate_governance.prevent_corporate_governance_mutation();

create or replace function corporate_governance.request_fingerprint_v1(
  p_request jsonb
)
returns text
language sql
immutable
security definer
set search_path = ''
as $function$
  select pg_catalog.encode(
    extensions.digest(p_request::text, 'sha256'), 'hex'
  )
$function$;

create or replace function corporate_governance.assert_owner_v1(
  p_company_id uuid,
  p_income_year integer,
  p_verified_subject text,
  p_consequential boolean
)
returns uuid
language plpgsql
volatile
security definer
set search_path = ''
as $function$
declare
  v_actor_id uuid := public.company_access_auth_uid_v1();
begin
  if v_actor_id is null
    or p_verified_subject is null
    or p_verified_subject !~ '^[0-9a-fA-F-]{36}$'
    or v_actor_id is distinct from p_verified_subject::uuid
    or v_actor_id is distinct from nullif(
      pg_catalog.current_setting('talli.verified_actor_id', true), ''
    )::uuid
    or not public.company_access_is_accepted_owner_v1(p_company_id)
  then
    raise exception 'corporate_governance_forbidden';
  end if;
  if p_consequential and not
    public.company_access_company_year_allows_consequential_v1(
      p_company_id, p_income_year
    )
  then
    raise exception 'corporate_governance_forbidden';
  end if;
  return v_actor_id;
end;
$function$;

create or replace function corporate_governance.actor_company_role_v1(
  p_company_id uuid,
  p_verified_subject text
)
returns text
language plpgsql
stable
security definer
set search_path = ''
as $function$
declare
  v_actor_id uuid := public.company_access_auth_uid_v1();
begin
  if v_actor_id is null
    or p_verified_subject is null
    or p_verified_subject !~ '^[0-9a-fA-F-]{36}$'
    or v_actor_id is distinct from p_verified_subject::uuid
    or v_actor_id is distinct from nullif(
      pg_catalog.current_setting('talli.verified_actor_id', true), ''
    )::uuid
  then
    raise exception 'corporate_governance_forbidden';
  end if;
  return case
    when public.company_access_is_accepted_owner_v1(p_company_id)
    then 'owner'
    else null
  end;
end;
$function$;

create or replace function corporate_governance.owner_dividend_lifecycle_v1(
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
  v_decision corporate_governance.owner_dividend_decisions%rowtype;
  v_finalization corporate_governance.owner_dividend_finalizations%rowtype;
  v_paid_ore bigint;
  v_latest_payment_entry_id uuid;
  v_state text;
begin
  select decision.* into v_decision
  from corporate_governance.owner_dividend_decisions decision
  where decision.id = p_decision_id;
  if not found then
    raise exception 'corporate_governance_not_found';
  end if;
  select finalization.* into v_finalization
  from corporate_governance.owner_dividend_finalizations finalization
  where finalization.decision_id = p_decision_id;
  select coalesce(pg_catalog.sum(payment.payment_amount_ore), 0)
  into v_paid_ore
  from corporate_governance.owner_dividend_payments payment
  where payment.decision_id = p_decision_id;
  select payment.accounting_entry_id into v_latest_payment_entry_id
  from corporate_governance.owner_dividend_payments payment
  where payment.decision_id = p_decision_id
  order by payment.created_at desc, payment.id desc
  limit 1;

  v_state := case
    when v_paid_ore = v_decision.declared_amount_ore then 'paid'
    when v_paid_ore > 0 then 'partially_paid'
    when v_finalization.id is not null then 'finalized'
    when exists (
      select 1 from corporate_governance.owner_dividend_events event
      where event.decision_id = p_decision_id
        and event.event_kind = 'facts_approved'
    ) then 'facts_approved'
    when exists (
      select 1 from corporate_governance.owner_dividend_events event
      where event.decision_id = p_decision_id
        and event.event_kind = 'documents_registered'
    ) then 'documents_registered'
    else 'proposed'
  end;
  return pg_catalog.jsonb_build_object(
    'decisionId', v_decision.id,
    'documentSetId', v_decision.document_set_id,
    'companyId', v_decision.company_id,
    'incomeYear', v_decision.income_year,
    'decisionHash', v_decision.decision_hash,
    'state', v_state,
    'declaredAmountOre', v_decision.declared_amount_ore,
    'paidAmountOre', v_paid_ore,
    'remainingAmountOre', v_decision.declared_amount_ore - v_paid_ore,
    'finalizationId', v_finalization.id,
    'accountingEntryId', coalesce(
      v_latest_payment_entry_id, v_finalization.accounting_entry_id
    ),
    'replayed', p_replayed
  );
end;
$function$;

create or replace function corporate_governance.propose_owner_dividend_v1(
  p_request jsonb,
  p_canonical_input jsonb,
  p_persisted_facts jsonb,
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
  v_existing corporate_governance.owner_dividend_decisions%rowtype;
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
    or (p_canonical_input -> 'dividend' ->> 'amountOre')::bigint <= 0
    or pg_catalog.jsonb_typeof(
      p_canonical_input -> 'dividend' -> 'allocations'
    ) is distinct from 'array'
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
      v_company_id, v_income_year, 'owner_dividend',
      v_annual_close_source_id, p_persisted_facts,
      p_canonical_input ->> 'decisionHash'
    );
  exception when others then
    raise exception 'corporate_governance_invalid_input';
  end;
  v_fingerprint := corporate_governance.request_fingerprint_v1(
    pg_catalog.jsonb_build_object(
      'request', p_request, 'canonicalInput', p_canonical_input,
      'persistedFacts', p_persisted_facts
    )
  );
  select decision.* into v_existing
  from corporate_governance.owner_dividend_decisions decision
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
  insert into corporate_governance.owner_dividend_decisions (
    id, document_set_id, company_id, income_year, annual_close_source_id,
    source_hash, canonical_input, decision_hash, declared_amount_ore,
    idempotency_key, correlation_id, request_fingerprint, created_by
  ) values (
    v_decision_id, v_document_set_id, v_company_id, v_income_year,
    v_annual_close_source_id, p_canonical_input ->> 'sourceHash',
    p_canonical_input, p_canonical_input ->> 'decisionHash',
    (p_canonical_input -> 'dividend' ->> 'amountOre')::bigint,
    p_request ->> 'idempotencyKey', p_request ->> 'correlationId',
    v_fingerprint, v_actor_id
  );
  return pg_catalog.jsonb_build_object(
    'state', 'proposed', 'replayed', false
  );
end;
$function$;

create or replace function
corporate_governance.register_owner_dividend_documents_v1(
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
  v_decision corporate_governance.owner_dividend_decisions%rowtype;
  v_existing corporate_governance.owner_dividend_events%rowtype;
  v_artifact jsonb;
  v_fingerprint text;
begin
  begin
    select decision.* into v_decision
    from corporate_governance.owner_dividend_decisions decision
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
      from pg_catalog.jsonb_array_elements(
        p_request -> 'artifacts'
      ) artifact
      where artifact ->> 'artifactKind' in (
        'dividend_board_proposal',
        'dividend_general_meeting_minutes'
      )
    ) <> 2
  then
    raise exception 'corporate_governance_invalid_input';
  end if;
  v_fingerprint := corporate_governance.request_fingerprint_v1(p_request);
  select event.* into v_existing
  from corporate_governance.owner_dividend_events event
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
    return corporate_governance.owner_dividend_lifecycle_v1(
      v_decision.id, true
    );
  end if;
  for v_artifact in
    select value from pg_catalog.jsonb_array_elements(
      p_request -> 'artifacts'
    )
  loop
    if coalesce(v_artifact ->> 'contentSha256', '')
        !~ '^[0-9a-f]{64}$'
      or (v_artifact ->> 'byteLength')::bigint not between 1 and 10485760
    then
      raise exception 'corporate_governance_invalid_input';
    end if;
    insert into corporate_governance.owner_dividend_artifacts (
      id, decision_id, document_set_id, company_id, income_year,
      artifact_kind, document_id, content_sha256, byte_length, created_by
    ) values (
      (v_artifact ->> 'artifactId')::uuid, v_decision.id,
      v_decision.document_set_id, v_decision.company_id,
      v_decision.income_year, v_artifact ->> 'artifactKind',
      (v_artifact ->> 'documentId')::uuid,
      v_artifact ->> 'contentSha256',
      (v_artifact ->> 'byteLength')::bigint, v_actor_id
    );
  end loop;
  insert into corporate_governance.owner_dividend_events (
    decision_id, document_set_id, company_id, income_year, event_kind,
    decision_hash, idempotency_key, correlation_id,
    request_fingerprint, created_by
  ) values (
    v_decision.id, v_decision.document_set_id, v_decision.company_id,
    v_decision.income_year, 'documents_registered',
    v_decision.decision_hash, p_request ->> 'idempotencyKey',
    p_request ->> 'correlationId', v_fingerprint, v_actor_id
  );
  return corporate_governance.owner_dividend_lifecycle_v1(
    v_decision.id, false
  );
end;
$function$;

create or replace function corporate_governance.approve_owner_dividend_v1(
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
  v_decision corporate_governance.owner_dividend_decisions%rowtype;
  v_existing corporate_governance.owner_dividend_events%rowtype;
  v_fingerprint text;
begin
  begin
    select decision.* into v_decision
    from corporate_governance.owner_dividend_decisions decision
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
  from corporate_governance.owner_dividend_events event
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
    return corporate_governance.owner_dividend_lifecycle_v1(
      v_decision.id, true
    );
  end if;
  if (
    select pg_catalog.count(*)
    from corporate_governance.owner_dividend_artifacts artifact
    where artifact.decision_id = v_decision.id
  ) <> 2
    or not exists (
      select 1 from corporate_governance.owner_dividend_events event
      where event.decision_id = v_decision.id
        and event.event_kind = 'documents_registered'
    )
    or exists (
      select 1 from corporate_governance.owner_dividend_finalizations item
      where item.decision_id = v_decision.id
    )
  then
    raise exception 'corporate_governance_invalid_input';
  end if;
  insert into corporate_governance.owner_dividend_events (
    id, decision_id, document_set_id, company_id, income_year,
    event_kind, decision_hash, idempotency_key, correlation_id,
    request_fingerprint, created_by
  ) values (
    (p_request ->> 'approvalEventId')::uuid, v_decision.id,
    v_decision.document_set_id, v_decision.company_id,
    v_decision.income_year, 'facts_approved', v_decision.decision_hash,
    p_request ->> 'idempotencyKey', p_request ->> 'correlationId',
    v_fingerprint, v_actor_id
  );
  return corporate_governance.owner_dividend_lifecycle_v1(
    v_decision.id, false
  );
end;
$function$;

create or replace function
corporate_governance.prepare_owner_dividend_finalization_v1(
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
  v_decision corporate_governance.owner_dividend_decisions%rowtype;
  v_existing corporate_governance.owner_dividend_finalizations%rowtype;
  v_policy corporate_governance.owner_dividend_accounting_policies%rowtype;
  v_policy_count integer;
  v_signed_evidence jsonb;
  v_fingerprint text;
begin
  begin
    select decision.* into v_decision
    from corporate_governance.owner_dividend_decisions decision
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
  select finalization.* into v_existing
  from corporate_governance.owner_dividend_finalizations finalization
  where finalization.id = (p_request ->> 'finalizationId')::uuid
    or finalization.decision_id = v_decision.id
    or (
      finalization.created_by = v_actor_id
      and finalization.company_id = v_decision.company_id
      and finalization.idempotency_key = p_request ->> 'idempotencyKey'
    )
  order by finalization.id = (p_request ->> 'finalizationId')::uuid desc
  limit 1;
  if found then
    if v_existing.id <> (p_request ->> 'finalizationId')::uuid
      or v_existing.document_set_id <> (p_request ->> 'documentSetId')::uuid
      or v_existing.decision_hash <> p_request ->> 'decisionHash'
      or v_existing.holding_action_id <> (p_request ->> 'holdingActionId')::uuid
      or v_existing.accounting_entry_id <> (p_request ->> 'ledgerEntryId')::uuid
      or v_existing.idempotency_key <> p_request ->> 'idempotencyKey'
      or v_existing.request_fingerprint <> v_fingerprint
    then
      raise exception 'corporate_governance_idempotency_conflict';
    end if;
    select policy.* into v_policy
    from corporate_governance.owner_dividend_accounting_policies policy
    where policy.policy_version = v_existing.accounting_policy_version;
    return pg_catalog.jsonb_build_object(
      'declaredAmountOre', v_decision.declared_amount_ore,
      'accountingPolicyVersion', v_policy.policy_version,
      'declarationDebitAccount', v_policy.declaration_debit_account,
      'dividendPayableAccount', v_policy.dividend_payable_account,
      'signedArtifactHashes', v_existing.signed_artifact_hashes,
      'replay', corporate_governance.owner_dividend_lifecycle_v1(
        v_decision.id, true
      )
    );
  end if;
  if p_request ->> 'companyId' <> v_decision.company_id::text
    or (p_request ->> 'incomeYear')::integer <> v_decision.income_year
    or p_request ->> 'documentSetId' <> v_decision.document_set_id::text
    or p_request ->> 'decisionHash' <> v_decision.decision_hash
    or coalesce(p_request ->> 'idempotencyKey', '')
      !~ '^[A-Za-z0-9._:-]{16,255}$'
    or not exists (
      select 1 from corporate_governance.owner_dividend_events event
      where event.decision_id = v_decision.id
        and event.event_kind = 'facts_approved'
    )
    or exists (
      select 1 from corporate_governance.owner_dividend_events event
      where event.decision_id = v_decision.id
        and event.event_kind in ('rejected', 'superseded')
    )
  then
    raise exception 'corporate_governance_invalid_input';
  end if;
  select pg_catalog.count(*) into v_policy_count
  from corporate_governance.owner_dividend_accounting_policies policy
  where policy.enabled
    and not exists (
      select 1
      from corporate_governance.owner_dividend_accounting_policies successor
      where successor.enabled
        and successor.supersedes_policy_version = policy.policy_version
    );
  if v_policy_count <> 1 then
    raise exception 'corporate_governance_accounting_policy_disabled';
  end if;
  select policy.* into v_policy
  from corporate_governance.owner_dividend_accounting_policies policy
  where policy.enabled
    and not exists (
      select 1
      from corporate_governance.owner_dividend_accounting_policies successor
      where successor.enabled
        and successor.supersedes_policy_version = policy.policy_version
    )
  order by policy.reviewed_at desc, policy.policy_version
  limit 1;
  v_signed_evidence := backend_system.owner_dividend_signed_evidence_v1(
    v_decision.id, v_decision.document_set_id, v_decision.company_id,
    v_decision.income_year, v_decision.decision_hash
  );
  return pg_catalog.jsonb_build_object(
    'declaredAmountOre', v_decision.declared_amount_ore,
    'accountingPolicyVersion', v_policy.policy_version,
    'declarationDebitAccount', v_policy.declaration_debit_account,
    'dividendPayableAccount', v_policy.dividend_payable_account,
    'signedArtifactHashes', v_signed_evidence -> 'signedArtifactHashes',
    'replay', null
  );
end;
$function$;

create or replace function
corporate_governance.complete_owner_dividend_finalization_v1(
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
  v_decision corporate_governance.owner_dividend_decisions%rowtype;
  v_existing corporate_governance.owner_dividend_finalizations%rowtype;
  v_fingerprint text;
begin
  select decision.* into v_decision
  from corporate_governance.owner_dividend_decisions decision
  where decision.id = (p_request ->> 'decisionId')::uuid
  for update;
  if not found then
    raise exception 'corporate_governance_not_found';
  end if;
  v_actor_id := corporate_governance.assert_owner_v1(
    v_decision.company_id, v_decision.income_year,
    p_verified_subject, true
  );
  v_fingerprint := corporate_governance.request_fingerprint_v1(
    p_request - 'declaredAmountOre' - 'accountingPolicyVersion'
      - 'signedArtifactHashes'
  );
  select finalization.* into v_existing
  from corporate_governance.owner_dividend_finalizations finalization
  where finalization.id = (p_request ->> 'finalizationId')::uuid
    or finalization.decision_id = v_decision.id
  limit 1;
  if found then
    if v_existing.request_fingerprint <> v_fingerprint
      or v_existing.accounting_entry_id <> (p_request ->> 'ledgerEntryId')::uuid
    then
      raise exception 'corporate_governance_idempotency_conflict';
    end if;
    return corporate_governance.owner_dividend_lifecycle_v1(
      v_decision.id, true
    );
  end if;
  if p_request ->> 'companyId' <> v_decision.company_id::text
    or (p_request ->> 'incomeYear')::integer <> v_decision.income_year
    or p_request ->> 'documentSetId' <> v_decision.document_set_id::text
    or p_request ->> 'decisionHash' <> v_decision.decision_hash
    or (p_request ->> 'declaredAmountOre')::bigint
      <> v_decision.declared_amount_ore
    or coalesce(p_request ->> 'accountingPolicyVersion', '') = ''
    or pg_catalog.jsonb_typeof(p_request -> 'signedArtifactHashes')
      is distinct from 'object'
    or not exists (
      select 1
      from corporate_governance.owner_dividend_accounting_policies policy
      where policy.policy_version = p_request ->> 'accountingPolicyVersion'
    )
    or not exists (
      select 1 from corporate_governance.owner_dividend_events event
      where event.decision_id = v_decision.id
        and event.event_kind = 'facts_approved'
    )
    or exists (
      select 1 from corporate_governance.owner_dividend_events event
      where event.decision_id = v_decision.id
        and event.event_kind in ('rejected', 'superseded')
    )
  then
    raise exception 'corporate_governance_invalid_input';
  end if;
  insert into corporate_governance.owner_dividend_finalizations (
    id, decision_id, document_set_id, company_id, income_year,
    decision_hash, holding_action_id, accounting_entry_id,
    declared_amount_ore, signed_artifact_hashes,
    accounting_policy_version, idempotency_key, correlation_id,
    request_fingerprint, created_by
  ) values (
    (p_request ->> 'finalizationId')::uuid, v_decision.id,
    v_decision.document_set_id, v_decision.company_id,
    v_decision.income_year, v_decision.decision_hash,
    (p_request ->> 'holdingActionId')::uuid,
    (p_request ->> 'ledgerEntryId')::uuid,
    v_decision.declared_amount_ore,
    p_request -> 'signedArtifactHashes',
    p_request ->> 'accountingPolicyVersion',
    p_request ->> 'idempotencyKey',
    p_request ->> 'correlationId', v_fingerprint, v_actor_id
  );
  perform backend_system.project_owner_dividend_finalization_v1(
    p_request, p_request ->> 'accountingPolicyVersion',
    p_request -> 'signedArtifactHashes', p_verified_subject
  );
  return corporate_governance.owner_dividend_lifecycle_v1(
    v_decision.id, false
  );
end;
$function$;

reset role;

-- Banking owns inspection and claim of the exact locked bank fact. Governance
-- receives only the immutable facts needed to decide and post one payment.
grant usage, create on schema banking to banking_store_owner;
set local role banking_store_owner;

create or replace function banking.prepare_owner_dividend_transaction_v1(
  p_request jsonb,
  p_verified_subject text
)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $function$
declare
  v_actor_id uuid := public.company_access_auth_uid_v1();
  v_transaction banking.transactions%rowtype;
  v_company_id uuid;
  v_income_year integer;
begin
  if v_actor_id is null
    or p_verified_subject !~ '^[0-9a-fA-F-]{36}$'
    or v_actor_id is distinct from p_verified_subject::uuid
  then
    raise exception 'banking_forbidden';
  end if;
  begin
    v_company_id := (p_request ->> 'companyId')::uuid;
    v_income_year := (p_request ->> 'incomeYear')::integer;
    select transaction.* into v_transaction
    from banking.transactions transaction
    where transaction.id = (p_request ->> 'bankTransactionId')::uuid
      and transaction.company_id = v_company_id
      and transaction.income_year = v_income_year
    for update;
  exception when others then
    raise exception 'banking_invalid_input';
  end;
  if not public.company_access_company_year_allows_consequential_v1(
    v_company_id, v_income_year
  ) then
    raise exception 'banking_forbidden';
  end if;
  if not found then
    raise exception 'banking_transaction_not_found';
  end if;
  if v_transaction.matched_accounting_entry_id is not null
    or v_transaction.matched_action_reference is not null
    or v_transaction.warning_accepted
  then
    raise exception 'banking_transaction_already_reconciled';
  end if;
  if v_transaction.amount >= 0
    or v_transaction.amount <> pg_catalog.round(v_transaction.amount, 2)
  then
    raise exception 'banking_transaction_fact_mismatch';
  end if;
  return pg_catalog.jsonb_build_object(
    'bankTransactionDate', v_transaction.transaction_date,
    'bankSignedAmount', v_transaction.amount,
    'bankSourceSha256', v_transaction.source_hash
  );
end;
$function$;

create or replace function banking.claim_owner_dividend_transaction_v1(
  p_request jsonb,
  p_accounting_entry_id uuid,
  p_verified_subject text
)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $function$
begin
  if coalesce(p_request ->> 'actionReference', '')
      !~ '^[0-9a-fA-F-]{36}$'
  then
    raise exception 'banking_invalid_input';
  end if;
  return banking.claim_transaction_for_external_action_v1(
    p_request, p_accounting_entry_id, p_verified_subject
  );
end;
$function$;

reset role;
revoke create on schema banking from banking_store_owner;

grant usage on schema banking to corporate_governance_store_owner;
grant execute on function banking.prepare_owner_dividend_transaction_v1(
  jsonb, text
) to corporate_governance_store_owner;
grant usage on schema banking
to corporate_governance_workflow_executor;
grant execute on function banking.claim_owner_dividend_transaction_v1(
  jsonb, uuid, text
) to corporate_governance_workflow_executor;

set local role corporate_governance_store_owner;

create or replace function
corporate_governance.prepare_owner_dividend_payment_v1(
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
  v_decision corporate_governance.owner_dividend_decisions%rowtype;
  v_existing corporate_governance.owner_dividend_payments%rowtype;
  v_finalization corporate_governance.owner_dividend_finalizations%rowtype;
  v_policy corporate_governance.owner_dividend_accounting_policies%rowtype;
  v_bank jsonb;
  v_paid_ore bigint;
  v_payment_ore bigint;
  v_fingerprint text;
begin
  select decision.* into v_decision
  from corporate_governance.owner_dividend_decisions decision
  where decision.id = (p_request ->> 'decisionId')::uuid
  for update;
  if not found then
    raise exception 'corporate_governance_not_found';
  end if;
  v_actor_id := corporate_governance.assert_owner_v1(
    v_decision.company_id, v_decision.income_year,
    p_verified_subject, true
  );
  v_fingerprint := corporate_governance.request_fingerprint_v1(p_request);
  select payment.* into v_existing
  from corporate_governance.owner_dividend_payments payment
  where payment.id = (p_request ->> 'paymentEventId')::uuid
    or payment.bank_transaction_id =
      (p_request ->> 'bankTransactionId')::uuid
    or (
      payment.created_by = v_actor_id
      and payment.company_id = v_decision.company_id
      and payment.idempotency_key = p_request ->> 'idempotencyKey'
    )
  order by payment.id = (p_request ->> 'paymentEventId')::uuid desc
  limit 1;
  if found then
    if v_existing.id <> (p_request ->> 'paymentEventId')::uuid
      or v_existing.document_set_id <> (p_request ->> 'documentSetId')::uuid
      or v_existing.decision_hash <> p_request ->> 'decisionHash'
      or v_existing.holding_action_id <> (p_request ->> 'holdingActionId')::uuid
      or v_existing.accounting_entry_id <> (p_request ->> 'ledgerEntryId')::uuid
      or v_existing.bank_transaction_id <>
        (p_request ->> 'bankTransactionId')::uuid
      or v_existing.idempotency_key <> p_request ->> 'idempotencyKey'
      or v_existing.request_fingerprint <> v_fingerprint
    then
      raise exception 'corporate_governance_idempotency_conflict';
    end if;
    select policy.* into v_policy
    from corporate_governance.owner_dividend_accounting_policies policy
    where policy.policy_version = v_existing.accounting_policy_version;
    return pg_catalog.jsonb_build_object(
      'paymentAmountOre', v_existing.payment_amount_ore,
      'bankTransactionDate', v_existing.bank_transaction_date,
      'bankSignedAmount', v_existing.bank_signed_amount,
      'bankSourceSha256', v_existing.bank_source_sha256,
      'accountingPolicyVersion', v_policy.policy_version,
      'dividendPayableAccount', v_policy.dividend_payable_account,
      'bankAccount', v_policy.bank_account,
      'replay', corporate_governance.owner_dividend_lifecycle_v1(
        v_decision.id, true
      )
    );
  end if;
  if p_request ->> 'companyId' <> v_decision.company_id::text
    or (p_request ->> 'incomeYear')::integer <> v_decision.income_year
    or p_request ->> 'documentSetId' <> v_decision.document_set_id::text
    or p_request ->> 'decisionHash' <> v_decision.decision_hash
    or exists (
      select 1 from corporate_governance.owner_dividend_events event
      where event.decision_id = v_decision.id
        and event.event_kind in ('rejected', 'superseded')
    )
  then
    raise exception 'corporate_governance_finalized_declaration_required';
  end if;
  select finalization.* into v_finalization
  from corporate_governance.owner_dividend_finalizations finalization
  where finalization.decision_id = v_decision.id;
  if not found then
    raise exception 'corporate_governance_finalized_declaration_required';
  end if;
  select policy.* into v_policy
  from corporate_governance.owner_dividend_accounting_policies policy
  where policy.policy_version = v_finalization.accounting_policy_version;
  if not found then
    raise exception 'corporate_governance_accounting_policy_disabled';
  end if;
  v_bank := banking.prepare_owner_dividend_transaction_v1(
    p_request, p_verified_subject
  );
  v_payment_ore := pg_catalog.round(
    pg_catalog.abs((v_bank ->> 'bankSignedAmount')::numeric) * 100
  )::bigint;
  select coalesce(pg_catalog.sum(payment.payment_amount_ore), 0)
  into v_paid_ore
  from corporate_governance.owner_dividend_payments payment
  where payment.decision_id = v_decision.id;
  if v_payment_ore <= 0
    or v_payment_ore > v_decision.declared_amount_ore - v_paid_ore
  then
    raise exception 'corporate_governance_payment_exceeds_payable';
  end if;
  return pg_catalog.jsonb_build_object(
    'paymentAmountOre', v_payment_ore,
    'bankTransactionDate', v_bank ->> 'bankTransactionDate',
    'bankSignedAmount', v_bank ->> 'bankSignedAmount',
    'bankSourceSha256', v_bank ->> 'bankSourceSha256',
    'accountingPolicyVersion', v_policy.policy_version,
    'dividendPayableAccount', v_policy.dividend_payable_account,
    'bankAccount', v_policy.bank_account,
    'replay', null
  );
end;
$function$;

create or replace function
corporate_governance.complete_owner_dividend_payment_v1(
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
  v_decision corporate_governance.owner_dividend_decisions%rowtype;
  v_existing corporate_governance.owner_dividend_payments%rowtype;
  v_paid_ore bigint;
  v_fingerprint text;
begin
  select decision.* into v_decision
  from corporate_governance.owner_dividend_decisions decision
  where decision.id = (p_request ->> 'decisionId')::uuid
  for update;
  if not found then
    raise exception 'corporate_governance_not_found';
  end if;
  v_actor_id := corporate_governance.assert_owner_v1(
    v_decision.company_id, v_decision.income_year,
    p_verified_subject, true
  );
  v_fingerprint := corporate_governance.request_fingerprint_v1(
    p_request - 'paymentAmountOre' - 'bankTransactionDate'
      - 'bankSignedAmount' - 'bankSourceSha256'
      - 'accountingPolicyVersion'
  );
  select payment.* into v_existing
  from corporate_governance.owner_dividend_payments payment
  where payment.id = (p_request ->> 'paymentEventId')::uuid
    or payment.bank_transaction_id =
      (p_request ->> 'bankTransactionId')::uuid
  limit 1;
  if found then
    if v_existing.request_fingerprint <> v_fingerprint
      or v_existing.accounting_entry_id <> (p_request ->> 'ledgerEntryId')::uuid
    then
      raise exception 'corporate_governance_idempotency_conflict';
    end if;
    return corporate_governance.owner_dividend_lifecycle_v1(
      v_decision.id, true
    );
  end if;
  if p_request ->> 'companyId' <> v_decision.company_id::text
    or (p_request ->> 'incomeYear')::integer <> v_decision.income_year
    or p_request ->> 'documentSetId' <> v_decision.document_set_id::text
    or p_request ->> 'decisionHash' <> v_decision.decision_hash
    or (p_request ->> 'paymentAmountOre')::bigint <= 0
    or (p_request ->> 'bankSignedAmount')::numeric >= 0
    or pg_catalog.round(
      pg_catalog.abs((p_request ->> 'bankSignedAmount')::numeric) * 100
    )::bigint <> (p_request ->> 'paymentAmountOre')::bigint
    or coalesce(p_request ->> 'bankSourceSha256', '')
      !~ '^[0-9a-f]{64}$'
    or not exists (
      select 1
      from corporate_governance.owner_dividend_finalizations finalization
      where finalization.decision_id = v_decision.id
        and finalization.accounting_policy_version =
          p_request ->> 'accountingPolicyVersion'
    )
    or exists (
      select 1 from corporate_governance.owner_dividend_events event
      where event.decision_id = v_decision.id
        and event.event_kind in ('rejected', 'superseded')
    )
  then
    raise exception 'corporate_governance_invalid_input';
  end if;
  select coalesce(pg_catalog.sum(payment.payment_amount_ore), 0)
  into v_paid_ore
  from corporate_governance.owner_dividend_payments payment
  where payment.decision_id = v_decision.id;
  if (p_request ->> 'paymentAmountOre')::bigint
      > v_decision.declared_amount_ore - v_paid_ore
  then
    raise exception 'corporate_governance_payment_exceeds_payable';
  end if;
  insert into corporate_governance.owner_dividend_payments (
    id, decision_id, document_set_id, company_id, income_year,
    decision_hash, holding_action_id, accounting_entry_id,
    bank_transaction_id, payment_amount_ore, bank_transaction_date,
    bank_signed_amount, bank_source_sha256, accounting_policy_version,
    idempotency_key, correlation_id, request_fingerprint, created_by
  ) values (
    (p_request ->> 'paymentEventId')::uuid, v_decision.id,
    v_decision.document_set_id, v_decision.company_id,
    v_decision.income_year, v_decision.decision_hash,
    (p_request ->> 'holdingActionId')::uuid,
    (p_request ->> 'ledgerEntryId')::uuid,
    (p_request ->> 'bankTransactionId')::uuid,
    (p_request ->> 'paymentAmountOre')::bigint,
    (p_request ->> 'bankTransactionDate')::date,
    (p_request ->> 'bankSignedAmount')::numeric,
    p_request ->> 'bankSourceSha256',
    p_request ->> 'accountingPolicyVersion',
    p_request ->> 'idempotencyKey',
    p_request ->> 'correlationId', v_fingerprint, v_actor_id
  );
  perform backend_system.project_owner_dividend_payment_v1(
    p_request, (p_request ->> 'paymentAmountOre')::bigint,
    p_request ->> 'accountingPolicyVersion', p_verified_subject
  );
  return corporate_governance.owner_dividend_lifecycle_v1(
    v_decision.id, false
  );
end;
$function$;

reset role;

-- Ledger exposes one typed storage bridge; its executor cannot reach the
-- generic writer through the governance database role.
grant usage, create on schema ledger
to corporate_governance_ledger_bridge_owner;
grant execute on function ledger.post_entry_with_id_v1(
  text, uuid, integer, text, text, jsonb, jsonb, boolean,
  text, text, text, text, uuid
) to corporate_governance_ledger_bridge_owner;

set local role corporate_governance_ledger_bridge_owner;

create or replace function ledger.post_corporate_governance_entry_v1(
  p_idempotency_key text,
  p_company_id uuid,
  p_income_year integer,
  p_entry_kind text,
  p_memo text,
  p_lines jsonb,
  p_source_capability text,
  p_source_record_id text,
  p_correlation_id text,
  p_verified_subject text,
  p_requested_entry_id uuid
)
returns table (
  ledger_entry_id uuid,
  company_id uuid,
  income_year integer,
  entry_kind text,
  posted_at timestamptz,
  replayed boolean
)
language plpgsql
security definer
set search_path = ''
as $function$
begin
  if pg_catalog.upper(coalesce(p_entry_kind, '')) not in (
      'OWNER_DIVIDEND_DECLARED', 'OWNER_DIVIDEND_PAYMENT'
    )
    or p_source_capability <> 'CORPORATE_GOVERNANCE'
    or coalesce(p_source_record_id, '') !~ '^[0-9a-fA-F-]{36}$'
  then
    raise exception 'ledger_invalid_input';
  end if;
  return query select * from ledger.post_entry_with_id_v1(
    p_idempotency_key, p_company_id, p_income_year, p_entry_kind,
    p_memo, p_lines, '[]'::jsonb, false, p_source_capability,
    p_source_record_id, p_correlation_id, p_verified_subject,
    p_requested_entry_id
  );
end;
$function$;

reset role;
revoke create on schema ledger
from corporate_governance_ledger_bridge_owner;
revoke all on function ledger.post_corporate_governance_entry_v1(
  text, uuid, integer, text, text, jsonb, text, text, text, text, uuid
) from public, anon, authenticated, service_role, ledger_executor,
  ledger_workflow_executor, talli_ledger_backend;
grant usage on schema ledger
to corporate_governance_workflow_executor;
grant execute on function ledger.post_corporate_governance_entry_v1(
  text, uuid, integer, text, text, jsonb, text, text, text, text, uuid
) to corporate_governance_workflow_executor;

revoke all on function
  corporate_governance.actor_company_role_v1(uuid, text),
  corporate_governance.propose_owner_dividend_v1(
    jsonb, jsonb, jsonb, text
  ),
  corporate_governance.register_owner_dividend_documents_v1(jsonb, text),
  corporate_governance.approve_owner_dividend_v1(jsonb, text),
  corporate_governance.prepare_owner_dividend_finalization_v1(jsonb, text),
  corporate_governance.complete_owner_dividend_finalization_v1(jsonb, text),
  corporate_governance.prepare_owner_dividend_payment_v1(jsonb, text),
  corporate_governance.complete_owner_dividend_payment_v1(jsonb, text)
from public, anon, authenticated, service_role,
  corporate_governance_workflow_executor;
grant execute on function
  corporate_governance.actor_company_role_v1(uuid, text),
  corporate_governance.propose_owner_dividend_v1(
    jsonb, jsonb, jsonb, text
  ),
  corporate_governance.register_owner_dividend_documents_v1(jsonb, text),
  corporate_governance.approve_owner_dividend_v1(jsonb, text),
  corporate_governance.prepare_owner_dividend_finalization_v1(jsonb, text),
  corporate_governance.complete_owner_dividend_finalization_v1(jsonb, text),
  corporate_governance.prepare_owner_dividend_payment_v1(jsonb, text),
  corporate_governance.complete_owner_dividend_payment_v1(jsonb, text)
to corporate_governance_workflow_executor;

revoke all on function
  corporate_governance.request_fingerprint_v1(jsonb),
  corporate_governance.assert_owner_v1(uuid, integer, text, boolean),
  corporate_governance.owner_dividend_lifecycle_v1(uuid, boolean),
  corporate_governance.prevent_corporate_governance_mutation(),
  banking.prepare_owner_dividend_transaction_v1(jsonb, text)
from public, anon, authenticated, service_role,
  corporate_governance_workflow_executor;
revoke all on function banking.claim_owner_dividend_transaction_v1(
  jsonb, uuid, text
) from public, anon, authenticated, service_role, banking_executor,
  banking_workflow_executor, talli_banking_backend;
grant execute on function banking.claim_owner_dividend_transaction_v1(
  jsonb, uuid, text
) to corporate_governance_workflow_executor;

do $backend_membership$
begin
  if exists (
    select 1 from pg_catalog.pg_roles
    where rolname = 'talli_ledger_backend'
  ) then
    grant corporate_governance_workflow_executor to talli_ledger_backend;
  end if;
end
$backend_membership$;

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

commit;
