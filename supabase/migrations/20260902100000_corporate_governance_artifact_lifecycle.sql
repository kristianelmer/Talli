-- Complete immutable signed-artifact lifecycle and canonical read model (#148).
begin;

set local lock_timeout = '5s';
set local statement_timeout = '120s';

do $roles$
begin
  if not exists (
    select 1 from pg_catalog.pg_roles
    where rolname = 'backend_system_annual_data_reader'
  ) then
    create role backend_system_annual_data_reader
      nologin noinherit nobypassrls;
  end if;
end
$roles$;

alter role backend_system_annual_data_reader
  nologin noinherit nobypassrls;

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

-- Documents owns the evidence registry and document-row lock. Only the named
-- backend-system workflow receives its command contract; Governance itself
-- receives no Documents privilege or table access.
set local role documents_store_owner;
grant usage on schema documents to corporate_governance_workflow_executor;
grant execute on function documents.register_evidence_reference_v1(
  text, text, uuid, uuid, uuid, integer, text, text, text, bigint, uuid
) to corporate_governance_workflow_executor;
reset role;

set local role corporate_governance_store_owner;

alter table corporate_governance.owner_dividend_decisions
  add column supersedes_decision_id uuid,
  add column supersedes_document_set_id uuid;

alter table corporate_governance.owner_dividend_artifacts
  drop constraint if exists owner_dividend_artifacts_decision_id_artifact_kind_key;
alter table corporate_governance.owner_dividend_artifacts
  add column variant text not null default 'unsigned',
  add column supersedes_artifact_id uuid;
alter table corporate_governance.owner_dividend_artifacts
  add constraint owner_dividend_artifacts_variant_check check (
    variant in ('unsigned', 'signed_owner_attested')
  ),
  add constraint owner_dividend_artifacts_variant_unique unique (
    decision_id, artifact_kind, variant
  ),
  add constraint owner_dividend_artifacts_supersedes_fk foreign key (
    company_id, income_year, supersedes_artifact_id
  ) references corporate_governance.owner_dividend_artifacts(
    company_id, income_year, id
  ) on delete restrict,
  add constraint owner_dividend_artifacts_supersedes_check check (
    supersedes_artifact_id is null or supersedes_artifact_id <> id
  ),
  add constraint owner_dividend_artifacts_variant_supersedes_check check (
    (variant = 'unsigned' and supersedes_artifact_id is null)
    or (
      variant = 'signed_owner_attested'
      and supersedes_artifact_id is not null
    )
  );

alter table corporate_governance.owner_dividend_events
  drop constraint if exists owner_dividend_events_event_kind_check,
  drop constraint if exists owner_dividend_events_decision_id_event_kind_key;
alter table corporate_governance.owner_dividend_events
  add column artifact_id uuid,
  add column content_sha256 text,
  add column metadata jsonb not null default '{}'::jsonb,
  add column occurred_at timestamptz;
alter table corporate_governance.owner_dividend_events
  add constraint owner_dividend_events_event_kind_check check (
    event_kind in (
      'documents_registered', 'facts_approved', 'signing_requested',
      'signed_copy_attested', 'superseded', 'rejected'
    )
  ),
  add constraint owner_dividend_events_content_sha256_check check (
    content_sha256 is null or content_sha256 ~ '^[0-9a-f]{64}$'
  ),
  add constraint owner_dividend_events_metadata_check check (
    pg_catalog.jsonb_typeof(metadata) = 'object'
  ),
  add constraint owner_dividend_events_artifact_fk foreign key (
    company_id, income_year, artifact_id
  ) references corporate_governance.owner_dividend_artifacts(
    company_id, income_year, id
  ) on delete restrict,
  add constraint owner_dividend_events_signed_evidence_check check (
    (
      event_kind = 'signed_copy_attested'
      and artifact_id is not null
      and content_sha256 is not null
    )
    or event_kind <> 'signed_copy_attested'
  );
create unique index owner_dividend_events_singleton_idx
on corporate_governance.owner_dividend_events(decision_id, event_kind)
where event_kind in (
  'facts_approved', 'signing_requested', 'superseded', 'rejected'
);

-- The predecessor recorded one generated event per unsigned artifact. Restore
-- those exact event facts now that the canonical event table can carry its
-- artifact reference, content hash, and metadata.
drop trigger owner_dividend_events_immutable
  on corporate_governance.owner_dividend_events;
drop trigger owner_dividend_decisions_immutable
  on corporate_governance.owner_dividend_decisions;
reset role;
update corporate_governance.owner_dividend_decisions current
set supersedes_decision_id = legacy.supersedes_decision_id,
    supersedes_document_set_id = document_set.supersedes_set_id
from public.corporate_decisions legacy
join public.corporate_document_sets document_set
  on document_set.decision_id = legacy.id
where legacy.decision_kind = 'owner_dividend'
  and current.id = legacy.id;
update corporate_governance.owner_dividend_events current
set artifact_id = legacy.artifact_id,
    content_sha256 = legacy.content_sha256,
    metadata = legacy.metadata,
    occurred_at = legacy.occurred_at
from public.corporate_document_events legacy
join public.corporate_decisions decision on decision.id = legacy.decision_id
where decision.decision_kind = 'owner_dividend'
  and current.id = legacy.id;
update corporate_governance.owner_dividend_events
set occurred_at = created_at
where occurred_at is null;
set local role corporate_governance_store_owner;
alter table corporate_governance.owner_dividend_events
  alter column occurred_at set default pg_catalog.statement_timestamp(),
  alter column occurred_at set not null;
create trigger owner_dividend_decisions_immutable
before update or delete on corporate_governance.owner_dividend_decisions
for each row execute function
  corporate_governance.prevent_corporate_governance_mutation();
create trigger owner_dividend_events_immutable
before update or delete on corporate_governance.owner_dividend_events
for each row execute function
  corporate_governance.prevent_corporate_governance_mutation();

-- Import signed owner-dividend evidence and lifecycle transitions that #144
-- intentionally left in the predecessor store until this stage-exit slice.
reset role;

insert into corporate_governance.owner_dividend_artifacts (
  id, decision_id, document_set_id, company_id, income_year,
  artifact_kind, variant, document_id, content_sha256, byte_length,
  supersedes_artifact_id, created_by, created_at
)
select
  signed.id, decision.id, signed.set_id, signed.company_id,
  signed.income_year, signed.artifact_kind, signed.variant,
  signed.document_id, signed.content_sha256, signed.byte_length,
  signed.supersedes_artifact_id, signed.created_by, signed.created_at
from public.corporate_document_artifacts signed
join public.corporate_document_sets document_set on document_set.id = signed.set_id
join public.corporate_decisions decision on decision.id = document_set.decision_id
where decision.decision_kind = 'owner_dividend'
  and signed.variant = 'signed_owner_attested'
on conflict (id) do nothing;

insert into corporate_governance.owner_dividend_events (
  id, decision_id, document_set_id, company_id, income_year, artifact_id,
  event_kind, decision_hash, content_sha256, metadata, idempotency_key,
  correlation_id, request_fingerprint, created_by, occurred_at, created_at
)
select
  event.id, event.decision_id, event.set_id, event.company_id,
  event.income_year, event.artifact_id, event.event_kind,
  event.decision_hash, event.content_sha256, event.metadata,
  'legacy-event:' || event.id::text,
  'legacy-event:' || event.id::text,
  pg_catalog.encode(extensions.digest(pg_catalog.jsonb_build_object(
    'legacyEventId', event.id, 'eventKind', event.event_kind
  )::text, 'sha256'), 'hex'),
  event.actor_id, event.occurred_at, event.created_at
from public.corporate_document_events event
join public.corporate_decisions decision on decision.id = event.decision_id
where decision.decision_kind = 'owner_dividend'
  and event.event_kind in (
    'signing_requested', 'signed_copy_attested', 'superseded', 'rejected'
  )
on conflict (id) do nothing;

set local role corporate_governance_store_owner;

do $preserve_owner_lifecycle$
declare
  v_definition text;
begin
  v_definition := pg_catalog.pg_get_functiondef(
    'corporate_governance.owner_dividend_lifecycle_v1(uuid,boolean)'::regprocedure
  );
  v_definition := pg_catalog.replace(
    v_definition,
    'FUNCTION corporate_governance.owner_dividend_lifecycle_v1',
    'FUNCTION corporate_governance.owner_dividend_lifecycle_pre148_v1'
  );
  execute v_definition;
end
$preserve_owner_lifecycle$;

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
    when exists (
      select 1 from corporate_governance.owner_dividend_events event
      where event.decision_id = p_decision_id
        and event.event_kind = 'rejected'
    ) then 'rejected'
    when exists (
      select 1 from corporate_governance.owner_dividend_events event
      where event.decision_id = p_decision_id
        and event.event_kind = 'superseded'
    ) then 'superseded'
    when v_paid_ore = v_decision.declared_amount_ore then 'paid'
    when v_paid_ore > 0 then 'partially_paid'
    when v_finalization.id is not null then 'finalized'
    when 2 = (
      select pg_catalog.count(*)
      from corporate_governance.owner_dividend_artifacts artifact
      where artifact.decision_id = p_decision_id
        and artifact.variant = 'signed_owner_attested'
    ) then 'signed_owner_attested'
    when exists (
      select 1 from corporate_governance.owner_dividend_events event
      where event.decision_id = p_decision_id
        and event.event_kind = 'signing_requested'
    ) then 'signing_requested'
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

-- Frozen read-only projection for the future annual-compliance store. It is a
-- backend-system compatibility seam, not a corporate-governance business API.
reset role;
set local role ledger_store_owner;
grant usage, create on schema backend_system
to backend_system_annual_data_reader;
reset role;
grant usage on schema public to backend_system_annual_data_reader;
grant select on public.annual_data to backend_system_annual_data_reader;
grant execute on function
  public.company_access_auth_uid_v1(),
  public.company_access_is_accepted_owner_v1(uuid)
to backend_system_annual_data_reader;
drop policy if exists "annual data compatibility reader reads owner facts"
on public.annual_data;
create policy "annual data compatibility reader reads owner facts"
on public.annual_data for select
to backend_system_annual_data_reader
using (public.company_access_is_accepted_owner_v1(company_id));
set local role backend_system_annual_data_reader;
create or replace function backend_system.list_annual_data_legacy_v1(
  p_company_id uuid,
  p_income_year integer,
  p_verified_subject text
)
returns jsonb
language plpgsql
stable
security definer
set search_path = ''
as $function$
begin
  if p_company_id is null or p_income_year not between 2000 and 2200
    or p_verified_subject is null
    or p_verified_subject !~ '^[0-9a-fA-F-]{36}$'
    or public.company_access_auth_uid_v1()
      is distinct from p_verified_subject::uuid
    or not public.company_access_is_accepted_owner_v1(p_company_id)
  then
    raise exception 'corporate_governance_forbidden';
  end if;

  return coalesce((
    select pg_catalog.jsonb_agg(
      pg_catalog.jsonb_build_object(
        'sourceId', item.id,
        'companyId', item.company_id,
        'incomeYear', item.income_year,
        'answers', item.answers,
        'confirmations', item.confirmations,
        'noActivityConfirmed', item.no_activity_confirmed,
        'annualFullTimeEquivalents', item.annual_full_time_equivalents,
        'completedAt', item.completed_at,
        'updatedAt', item.updated_at
      ) order by item.income_year desc, item.id
    )
    from public.annual_data item
    where item.company_id = p_company_id
      and item.income_year <= p_income_year
  ), '[]'::jsonb);
end;
$function$;
reset role;
set local role ledger_store_owner;
revoke create on schema backend_system
from backend_system_annual_data_reader;
reset role;
set local role corporate_governance_store_owner;

create or replace function corporate_governance.read_corporate_lifecycle_v1(
  p_company_ids uuid[],
  p_decision_id uuid,
  p_verified_subject text
)
returns jsonb
language plpgsql
stable
security definer
set search_path = ''
as $function$
declare
  v_company_id uuid;
  v_match_count integer;
begin
  if (p_decision_id is null) = (p_company_ids is null)
    or (p_company_ids is not null and pg_catalog.cardinality(p_company_ids) = 0)
  then
    raise exception 'corporate_governance_invalid_input';
  end if;
  if p_decision_id is not null then
    select pg_catalog.count(*), pg_catalog.min(candidate.company_id::text)::uuid
    into v_match_count, v_company_id
    from (
      select decision.company_id
      from corporate_governance.owner_dividend_decisions decision
      where decision.id = p_decision_id
      union all
      select decision.company_id
      from corporate_governance.annual_close_decisions decision
      where decision.id = p_decision_id
    ) candidate;
    if v_match_count = 0 then
      raise exception 'corporate_governance_not_found';
    elsif v_match_count <> 1 then
      raise exception 'corporate_governance_idempotency_conflict';
    end if;
    if corporate_governance.actor_company_role_v1(
      v_company_id, p_verified_subject
    ) is null then
      raise exception 'corporate_governance_forbidden';
    end if;
  else
    foreach v_company_id in array p_company_ids loop
      if corporate_governance.actor_company_role_v1(
        v_company_id, p_verified_subject
      ) is null then
        raise exception 'corporate_governance_forbidden';
      end if;
    end loop;
  end if;

  return pg_catalog.jsonb_build_object(
    'decisions', coalesce((
      select pg_catalog.jsonb_agg(item.payload order by item.created_at desc, item.id)
      from (
        select decision.id, decision.created_at,
          pg_catalog.jsonb_build_object(
            'decisionId', decision.id,
            'documentSetId', decision.document_set_id,
            'companyId', decision.company_id,
            'incomeYear', decision.income_year,
            'decisionKind', 'owner_dividend',
            'annualCloseSourceId', decision.annual_close_source_id,
            'sourceHash', decision.source_hash,
            'sourceHashUsesCurrentBasis',
              decision.source_hash_uses_current_basis,
            'canonicalInput', decision.canonical_input,
            'decisionHash', decision.decision_hash,
            'supersedesDecisionId', decision.supersedes_decision_id,
            'createdBy', decision.created_by,
            'createdAt', decision.created_at
          ) payload
        from corporate_governance.owner_dividend_decisions decision
        where (
          p_decision_id is not null and decision.id = p_decision_id
        ) or (
          p_decision_id is null and decision.company_id = any(p_company_ids)
        )
        union all
        select decision.id, decision.created_at,
          pg_catalog.jsonb_build_object(
            'decisionId', decision.id,
            'documentSetId', decision.document_set_id,
            'companyId', decision.company_id,
            'incomeYear', decision.income_year,
            'decisionKind', 'annual_close',
            'annualCloseSourceId', decision.annual_close_source_id,
            'sourceHash', decision.source_hash,
            'sourceHashUsesCurrentBasis',
              decision.source_hash_uses_current_basis,
            'canonicalInput', decision.canonical_input,
            'decisionHash', decision.decision_hash,
            'supersedesDecisionId', decision.supersedes_decision_id,
            'createdBy', decision.created_by,
            'createdAt', decision.created_at
          ) payload
        from corporate_governance.annual_close_decisions decision
        where (
          p_decision_id is not null and decision.id = p_decision_id
        ) or (
          p_decision_id is null and decision.company_id = any(p_company_ids)
        )
      ) item
    ), '[]'::jsonb),
    'documentSets', coalesce((
      select pg_catalog.jsonb_agg(item.payload order by item.created_at desc, item.id)
      from (
        select decision.document_set_id id, decision.created_at,
          pg_catalog.jsonb_build_object(
            'documentSetId', decision.document_set_id,
            'companyId', decision.company_id,
            'incomeYear', decision.income_year,
            'decisionId', decision.id,
            'templateFamily', decision.canonical_input ->> 'templateFamily',
            'templateVersion', decision.canonical_input ->> 'templateVersion',
            'decisionHash', decision.decision_hash,
            'supersedesDocumentSetId', decision.supersedes_document_set_id,
            'createdBy', decision.created_by,
            'createdAt', decision.created_at
          ) payload
        from corporate_governance.owner_dividend_decisions decision
        where (
          p_decision_id is not null and decision.id = p_decision_id
        ) or (
          p_decision_id is null and decision.company_id = any(p_company_ids)
        )
        union all
        select decision.document_set_id id, decision.created_at,
          pg_catalog.jsonb_build_object(
            'documentSetId', decision.document_set_id,
            'companyId', decision.company_id,
            'incomeYear', decision.income_year,
            'decisionId', decision.id,
            'templateFamily', decision.canonical_input ->> 'templateFamily',
            'templateVersion', decision.canonical_input ->> 'templateVersion',
            'decisionHash', decision.decision_hash,
            'supersedesDocumentSetId', decision.supersedes_document_set_id,
            'createdBy', decision.created_by,
            'createdAt', decision.created_at
          ) payload
        from corporate_governance.annual_close_decisions decision
        where (
          p_decision_id is not null and decision.id = p_decision_id
        ) or (
          p_decision_id is null and decision.company_id = any(p_company_ids)
        )
      ) item
    ), '[]'::jsonb),
    'artifacts', coalesce((
      select pg_catalog.jsonb_agg(item.payload order by item.created_at, item.id)
      from (
        select artifact.id, artifact.created_at,
          pg_catalog.jsonb_build_object(
            'artifactId', artifact.id,
            'companyId', artifact.company_id,
            'incomeYear', artifact.income_year,
            'documentSetId', artifact.document_set_id,
            'artifactKind', artifact.artifact_kind,
            'variant', artifact.variant,
            'documentId', artifact.document_id,
            'contentSha256', artifact.content_sha256,
            'byteLength', artifact.byte_length,
            'supersedesArtifactId', artifact.supersedes_artifact_id,
            'createdBy', artifact.created_by,
            'createdAt', artifact.created_at
          ) payload
        from corporate_governance.owner_dividend_artifacts artifact
        where (
          p_decision_id is not null and artifact.decision_id = p_decision_id
        ) or (
          p_decision_id is null and artifact.company_id = any(p_company_ids)
        )
        union all
        select artifact.id, artifact.created_at,
          pg_catalog.jsonb_build_object(
            'artifactId', artifact.id,
            'companyId', artifact.company_id,
            'incomeYear', artifact.income_year,
            'documentSetId', artifact.document_set_id,
            'artifactKind', artifact.artifact_kind,
            'variant', artifact.variant,
            'documentId', artifact.document_id,
            'contentSha256', artifact.content_sha256,
            'byteLength', artifact.byte_length,
            'supersedesArtifactId', artifact.supersedes_artifact_id,
            'createdBy', artifact.created_by,
            'createdAt', artifact.created_at
          ) payload
        from corporate_governance.annual_close_artifacts artifact
        where (
          p_decision_id is not null and artifact.decision_id = p_decision_id
        ) or (
          p_decision_id is null and artifact.company_id = any(p_company_ids)
        )
      ) item
    ), '[]'::jsonb),
    'events', coalesce((
      select pg_catalog.jsonb_agg(item.payload order by item.occurred_at, item.id)
      from (
        select event.id, event.occurred_at,
          pg_catalog.jsonb_build_object(
            'eventId', event.id,
            'companyId', event.company_id,
            'incomeYear', event.income_year,
            'decisionId', event.decision_id,
            'documentSetId', event.document_set_id,
            'artifactId', event.artifact_id,
            'eventKind', event.event_kind,
            'actorId', event.created_by,
            'occurredAt', event.occurred_at,
            'createdAt', event.created_at,
            'decisionHash', event.decision_hash,
            'contentSha256', event.content_sha256,
            'metadata', event.metadata,
            'idempotencyKey', event.idempotency_key
          ) payload
        from corporate_governance.owner_dividend_events event
        where (
          p_decision_id is not null and event.decision_id = p_decision_id
        ) or (
          p_decision_id is null and event.company_id = any(p_company_ids)
        )
        union all
        select event.id, event.occurred_at,
          pg_catalog.jsonb_build_object(
            'eventId', event.id,
            'companyId', event.company_id,
            'incomeYear', event.income_year,
            'decisionId', event.decision_id,
            'documentSetId', event.document_set_id,
            'artifactId', event.artifact_id,
            'eventKind', event.event_kind,
            'actorId', event.created_by,
            'occurredAt', event.occurred_at,
            'createdAt', event.created_at,
            'decisionHash', event.decision_hash,
            'contentSha256', event.content_sha256,
            'metadata', event.metadata,
            'idempotencyKey', event.idempotency_key
          ) payload
        from corporate_governance.annual_close_events event
        where (
          p_decision_id is not null and event.decision_id = p_decision_id
        ) or (
          p_decision_id is null and event.company_id = any(p_company_ids)
        )
        union all
        select finalization.event_id id, finalization.occurred_at,
          pg_catalog.jsonb_build_object(
            'eventId', finalization.event_id,
            'companyId', finalization.company_id,
            'incomeYear', finalization.income_year,
            'decisionId', finalization.decision_id,
            'documentSetId', finalization.document_set_id,
            'artifactId', null,
            'eventKind', 'finalized',
            'actorId', finalization.created_by,
            'occurredAt', finalization.occurred_at,
            'createdAt', finalization.created_at,
            'decisionHash', finalization.decision_hash,
            'contentSha256', null,
            'metadata', pg_catalog.jsonb_build_object(
              'finalizationId', finalization.id,
              'finalizationKind', 'owner_dividend_declared',
              'signedArtifactHashes', finalization.signed_artifact_hashes,
              'accountingPolicyVersion', finalization.accounting_policy_version
            ),
            'idempotencyKey', finalization.idempotency_key
          ) payload
        from corporate_governance.owner_dividend_finalizations finalization
        where (
          p_decision_id is not null and finalization.decision_id = p_decision_id
        ) or (
          p_decision_id is null and finalization.company_id = any(p_company_ids)
        )
        union all
        select payment.id, payment.occurred_at,
          pg_catalog.jsonb_build_object(
            'eventId', payment.id,
            'companyId', payment.company_id,
            'incomeYear', payment.income_year,
            'decisionId', payment.decision_id,
            'documentSetId', payment.document_set_id,
            'artifactId', null,
            'eventKind', 'payment_recorded',
            'actorId', payment.created_by,
            'occurredAt', payment.occurred_at,
            'createdAt', payment.created_at,
            'decisionHash', payment.decision_hash,
            'contentSha256', null,
            'metadata', pg_catalog.jsonb_build_object(
              'bankTransactionId', payment.bank_transaction_id,
              'holdingActionId', payment.holding_action_id,
              'ledgerEntryId', payment.accounting_entry_id,
              'amountOre', payment.payment_amount_ore,
              'remainingPayableOre', decision.declared_amount_ore - (
                select coalesce(pg_catalog.sum(earlier.payment_amount_ore), 0)
                from corporate_governance.owner_dividend_payments earlier
                where earlier.decision_id = payment.decision_id
                  and (
                    earlier.created_at < payment.created_at
                    or (
                      earlier.created_at = payment.created_at
                      and earlier.id <= payment.id
                    )
                  )
              ),
              'accountingPolicyVersion', payment.accounting_policy_version
            ),
            'idempotencyKey', payment.idempotency_key
          ) payload
        from corporate_governance.owner_dividend_payments payment
        join corporate_governance.owner_dividend_decisions decision
          on decision.id = payment.decision_id
        where (
          p_decision_id is not null and payment.decision_id = p_decision_id
        ) or (
          p_decision_id is null and payment.company_id = any(p_company_ids)
        )
        union all
        select finalization.event_id id, finalization.occurred_at,
          pg_catalog.jsonb_build_object(
            'eventId', finalization.event_id,
            'companyId', finalization.company_id,
            'incomeYear', finalization.income_year,
            'decisionId', finalization.decision_id,
            'documentSetId', finalization.document_set_id,
            'artifactId', null,
            'eventKind', 'finalized',
            'actorId', finalization.created_by,
            'occurredAt', finalization.occurred_at,
            'createdAt', finalization.created_at,
            'decisionHash', finalization.decision_hash,
            'contentSha256', null,
            'metadata', pg_catalog.jsonb_build_object(
              'finalizationId', finalization.id,
              'finalizationKind', 'annual_close_adopted',
              'signedArtifactHashes', finalization.signed_artifact_hashes
            ),
            'idempotencyKey', finalization.idempotency_key
          ) payload
        from corporate_governance.annual_close_finalizations finalization
        where (
          p_decision_id is not null and finalization.decision_id = p_decision_id
        ) or (
          p_decision_id is null and finalization.company_id = any(p_company_ids)
        )
      ) item
    ), '[]'::jsonb),
    'finalizations', coalesce((
      select pg_catalog.jsonb_agg(item.payload order by item.created_at, item.id)
      from (
        select finalization.id, finalization.created_at,
          pg_catalog.jsonb_build_object(
            'finalizationId', finalization.id,
            'companyId', finalization.company_id,
            'incomeYear', finalization.income_year,
            'decisionId', finalization.decision_id,
            'finalizationKind', 'owner_dividend_declared',
            'holdingActionId', finalization.holding_action_id,
            'accountingEntryId', finalization.accounting_entry_id,
            'annualCloseSourceId', null,
            'decisionHash', finalization.decision_hash,
            'signedArtifactHashes', finalization.signed_artifact_hashes,
            'accountingPolicyVersion', finalization.accounting_policy_version,
            'createdBy', finalization.created_by,
            'createdAt', finalization.created_at
          ) payload
        from corporate_governance.owner_dividend_finalizations finalization
        where (
          p_decision_id is not null and finalization.decision_id = p_decision_id
        ) or (
          p_decision_id is null and finalization.company_id = any(p_company_ids)
        )
        union all
        select finalization.id, finalization.created_at,
          pg_catalog.jsonb_build_object(
            'finalizationId', finalization.id,
            'companyId', finalization.company_id,
            'incomeYear', finalization.income_year,
            'decisionId', finalization.decision_id,
            'finalizationKind', 'annual_close_adopted',
            'holdingActionId', null,
            'accountingEntryId', null,
            'annualCloseSourceId', finalization.annual_close_source_id,
            'decisionHash', finalization.decision_hash,
            'signedArtifactHashes', finalization.signed_artifact_hashes,
            'accountingPolicyVersion', null,
            'createdBy', finalization.created_by,
            'createdAt', finalization.created_at
          ) payload
        from corporate_governance.annual_close_finalizations finalization
        where (
          p_decision_id is not null and finalization.decision_id = p_decision_id
        ) or (
          p_decision_id is null and finalization.company_id = any(p_company_ids)
        )
      ) item
    ), '[]'::jsonb)
  );
end;
$function$;

create or replace function
corporate_governance.attest_owner_dividend_signed_artifact_v1(
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
  v_unsigned corporate_governance.owner_dividend_artifacts%rowtype;
  v_existing corporate_governance.owner_dividend_events%rowtype;
  v_fingerprint text;
begin
  begin
    perform (p_request ->> 'unsignedArtifactId')::uuid;
    perform (p_request ->> 'signedArtifactId')::uuid;
    perform (p_request ->> 'signedDocumentId')::uuid;
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
    or p_request ->> 'artifactKind' not in (
      'dividend_board_proposal', 'dividend_general_meeting_minutes'
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
  from corporate_governance.owner_dividend_events event
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
    return corporate_governance.owner_dividend_lifecycle_v1(
      v_decision.id, true
    );
  end if;
  if not exists (
      select 1 from corporate_governance.owner_dividend_events event
      where event.decision_id = v_decision.id
        and event.event_kind = 'facts_approved'
    )
    or exists (
      select 1 from corporate_governance.owner_dividend_events event
      where event.decision_id = v_decision.id
        and event.event_kind in ('rejected', 'superseded')
    )
    or exists (
      select 1 from corporate_governance.owner_dividend_finalizations item
      where item.decision_id = v_decision.id
    )
  then
    raise exception 'corporate_governance_invalid_input';
  end if;
  select artifact.* into v_unsigned
  from corporate_governance.owner_dividend_artifacts artifact
  where artifact.id = (p_request ->> 'unsignedArtifactId')::uuid
    and artifact.decision_id = v_decision.id
    and artifact.document_set_id = v_decision.document_set_id
    and artifact.variant = 'unsigned'
    and artifact.artifact_kind = p_request ->> 'artifactKind'
  for share;
  if not found then
    raise exception 'corporate_governance_invalid_input';
  end if;
  insert into corporate_governance.owner_dividend_artifacts (
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
  insert into corporate_governance.owner_dividend_events (
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
  return corporate_governance.owner_dividend_lifecycle_v1(
    v_decision.id, false
  );
end;
$function$;

-- Finalization reads signed evidence exclusively from the canonical store.
do $preserve_owner_finalization_preparation$
declare
  v_definition text;
begin
  v_definition := pg_catalog.pg_get_functiondef(
    'corporate_governance.prepare_owner_dividend_finalization_v1(jsonb,text)'::regprocedure
  );
  v_definition := pg_catalog.replace(
    v_definition,
    'FUNCTION corporate_governance.prepare_owner_dividend_finalization_v1',
    'FUNCTION corporate_governance.prepare_owner_dividend_finalization_pre148_v1'
  );
  execute v_definition;
end
$preserve_owner_finalization_preparation$;

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
  v_signed_count integer;
  v_signed_hashes jsonb;
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
  select pg_catalog.count(*), pg_catalog.jsonb_object_agg(
    artifact.artifact_kind, artifact.content_sha256
  )
  into v_signed_count, v_signed_hashes
  from corporate_governance.owner_dividend_artifacts artifact
  where artifact.decision_id = v_decision.id
    and artifact.variant = 'signed_owner_attested';
  if v_signed_count <> 2
    or not coalesce(v_signed_hashes ? 'dividend_board_proposal', false)
    or not coalesce(
      v_signed_hashes ? 'dividend_general_meeting_minutes', false
    )
  then
    raise exception 'corporate_governance_missing_signed_artifacts';
  end if;
  return pg_catalog.jsonb_build_object(
    'declaredAmountOre', v_decision.declared_amount_ore,
    'accountingPolicyVersion', v_policy.policy_version,
    'declarationDebitAccount', v_policy.declaration_debit_account,
    'dividendPayableAccount', v_policy.dividend_payable_account,
    'signedArtifactHashes', v_signed_hashes,
    'replay', null
  );
end;
$function$;

create or replace function corporate_governance.record_owner_dividend_event_v1(
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
  v_event_kind text := p_request ->> 'eventKind';
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
  from corporate_governance.owner_dividend_events event
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
    return corporate_governance.owner_dividend_lifecycle_v1(
      v_decision.id, true
    );
  end if;
  if exists (
      select 1 from corporate_governance.owner_dividend_finalizations item
      where item.decision_id = v_decision.id
    )
    or exists (
      select 1 from corporate_governance.owner_dividend_events event
      where event.decision_id = v_decision.id
        and event.event_kind in ('rejected', 'superseded')
    )
    or (
      v_event_kind = 'signing_requested'
      and not exists (
        select 1 from corporate_governance.owner_dividend_events event
        where event.decision_id = v_decision.id
          and event.event_kind = 'facts_approved'
      )
    )
  then
    raise exception 'corporate_governance_invalid_input';
  end if;
  insert into corporate_governance.owner_dividend_events (
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
  return corporate_governance.owner_dividend_lifecycle_v1(
    v_decision.id, false
  );
end;
$function$;

-- Stop projecting canonical finalizations and payments back into predecessor
-- governance tables. Preserve exact definitions for a lossless rollback.
do $cut_owner_legacy_projections$
declare
  v_definition text;
  v_backup text;
  v_rewritten text;
begin
  v_definition := pg_catalog.pg_get_functiondef(
    'corporate_governance.complete_owner_dividend_finalization_v1(jsonb,text)'::regprocedure
  );
  v_backup := pg_catalog.replace(
    v_definition,
    'FUNCTION corporate_governance.complete_owner_dividend_finalization_v1',
    'FUNCTION corporate_governance.complete_owner_dividend_finalization_pre148_v1'
  );
  execute v_backup;
  v_rewritten := pg_catalog.replace(v_definition, $old$
  perform backend_system.project_owner_dividend_finalization_v1(
    p_request, p_request ->> 'accountingPolicyVersion',
    p_request -> 'signedArtifactHashes', p_verified_subject
  );$old$, '');
  if v_rewritten = v_definition then
    raise exception 'corporate_governance_finalization_projection_definition_drift';
  end if;
  execute v_rewritten;

  v_definition := pg_catalog.pg_get_functiondef(
    'corporate_governance.complete_owner_dividend_payment_v1(jsonb,text)'::regprocedure
  );
  v_backup := pg_catalog.replace(
    v_definition,
    'FUNCTION corporate_governance.complete_owner_dividend_payment_v1',
    'FUNCTION corporate_governance.complete_owner_dividend_payment_pre148_v1'
  );
  execute v_backup;
  v_rewritten := pg_catalog.replace(v_definition, $old$
  perform backend_system.project_owner_dividend_payment_v1(
    p_request, (p_request ->> 'paymentAmountOre')::bigint,
    p_request ->> 'accountingPolicyVersion', p_verified_subject
  );$old$, '');
  if v_rewritten = v_definition then
    raise exception 'corporate_governance_payment_projection_definition_drift';
  end if;
  execute v_rewritten;
end
$cut_owner_legacy_projections$;

reset role;

-- Explicit backend-system coordinators compose Governance commands with the
-- Documents evidence command in one request-bound transaction.
set local role ledger_store_owner;
grant usage, create on schema backend_system
to corporate_governance_workflow_executor;
reset role;

set local role corporate_governance_workflow_executor;

create or replace function
backend_system.register_corporate_governance_evidence_v1(
  p_source_record_type text,
  p_source_record_id uuid,
  p_document_id uuid,
  p_company_id uuid,
  p_income_year integer,
  p_linked_to text,
  p_status text,
  p_content_sha256 text,
  p_byte_length bigint,
  p_actor_id uuid
)
returns void language plpgsql security definer set search_path = ''
as $function$
begin
  if p_source_record_type not in (
    'owner_dividend_artifacts',
    'annual_close_artifacts',
    'shareholder_loans'
  ) then
    raise exception 'corporate_governance_invalid_input';
  end if;
  perform documents.register_evidence_reference_v1(
    'corporate_governance',
    p_source_record_type,
    p_source_record_id,
    p_document_id,
    p_company_id,
    p_income_year,
    p_linked_to,
    p_status,
    p_content_sha256,
    p_byte_length,
    p_actor_id
  );
end
$function$;

create or replace function
backend_system.register_corporate_governance_documents_v1(
  p_decision_kind text,
  p_request jsonb,
  p_verified_subject text
)
returns jsonb language plpgsql security definer set search_path = ''
as $function$
declare
  v_artifact jsonb;
  v_result jsonb;
  v_source_record_type text;
begin
  if p_decision_kind = 'owner_dividend' then
    v_result := corporate_governance.register_owner_dividend_documents_v1(
      p_request, p_verified_subject
    );
    v_source_record_type := 'owner_dividend_artifacts';
  elsif p_decision_kind = 'annual_close' then
    v_result := corporate_governance.register_annual_close_documents_v1(
      p_request, p_verified_subject
    );
    v_source_record_type := 'annual_close_artifacts';
  else
    raise exception 'corporate_governance_invalid_input';
  end if;
  for v_artifact in
    select value from pg_catalog.jsonb_array_elements(p_request -> 'artifacts')
  loop
    perform backend_system.register_corporate_governance_evidence_v1(
      v_source_record_type,
      (v_artifact ->> 'artifactId')::uuid,
      (v_artifact ->> 'documentId')::uuid,
      (p_request ->> 'companyId')::uuid,
      (p_request ->> 'incomeYear')::integer,
      'corporate_decision:' || (p_request ->> 'decisionId'),
      'generated_unsigned',
      v_artifact ->> 'contentSha256',
      (v_artifact ->> 'byteLength')::bigint,
      p_verified_subject::uuid
    );
  end loop;
  return v_result;
end
$function$;

create or replace function
backend_system.attest_corporate_governance_signed_artifact_v1(
  p_decision_kind text,
  p_request jsonb,
  p_verified_subject text
)
returns jsonb language plpgsql security definer set search_path = ''
as $function$
declare
  v_result jsonb;
  v_source_record_type text;
begin
  if p_decision_kind = 'owner_dividend' then
    v_result := corporate_governance.attest_owner_dividend_signed_artifact_v1(
      p_request, p_verified_subject
    );
    v_source_record_type := 'owner_dividend_artifacts';
  elsif p_decision_kind = 'annual_close' then
    v_result := corporate_governance.attest_annual_close_signed_artifact_v1(
      p_request, p_verified_subject
    );
    v_source_record_type := 'annual_close_artifacts';
  else
    raise exception 'corporate_governance_invalid_input';
  end if;
  perform backend_system.register_corporate_governance_evidence_v1(
    v_source_record_type,
    (p_request ->> 'signedArtifactId')::uuid,
    (p_request ->> 'signedDocumentId')::uuid,
    (p_request ->> 'companyId')::uuid,
    (p_request ->> 'incomeYear')::integer,
    'corporate_decision:' || (p_request ->> 'decisionId'),
    'signed_owner_attested',
    p_request ->> 'contentSha256',
    (p_request ->> 'byteLength')::bigint,
    p_verified_subject::uuid
  );
  return v_result;
end
$function$;

create or replace function
backend_system.complete_corporate_governance_shareholder_loan_v1(
  p_request jsonb,
  p_verified_subject text
)
returns jsonb language plpgsql security definer set search_path = ''
as $function$
declare v_result jsonb;
begin
  v_result := corporate_governance.complete_shareholder_loan_v1(
    p_request, p_verified_subject
  );
  if nullif(p_request ->> 'documentId', '') is not null then
    perform backend_system.register_corporate_governance_evidence_v1(
      'shareholder_loans',
      (p_request ->> 'actionId')::uuid,
      (p_request ->> 'documentId')::uuid,
      (p_request ->> 'companyId')::uuid,
      (p_request ->> 'incomeYear')::integer,
      null, null, null, null,
      p_verified_subject::uuid
    );
  end if;
  return v_result;
end
$function$;

revoke all on function
  backend_system.register_corporate_governance_evidence_v1(
    text, uuid, uuid, uuid, integer, text, text, text, bigint, uuid
  ),
  backend_system.register_corporate_governance_documents_v1(
    text, jsonb, text
  ),
  backend_system.attest_corporate_governance_signed_artifact_v1(
    text, jsonb, text
  ),
  backend_system.complete_corporate_governance_shareholder_loan_v1(
    jsonb, text
  )
from public, anon, authenticated, service_role;

reset role;

do $backfill_document_evidence$
declare artifact record;
begin
  for artifact in
    select
      'owner_dividend_artifacts'::text as source_record_type,
      item.id, item.document_id, item.company_id, item.income_year,
      item.decision_id, item.variant, item.content_sha256,
      item.byte_length, item.created_by
    from corporate_governance.owner_dividend_artifacts item
    union all
    select
      'annual_close_artifacts'::text as source_record_type,
      item.id, item.document_id, item.company_id, item.income_year,
      item.decision_id, item.variant, item.content_sha256,
      item.byte_length, item.created_by
    from corporate_governance.annual_close_artifacts item
  loop
    perform documents.backfill_evidence_reference_v1(
      'corporate_governance',
      artifact.source_record_type,
      artifact.id,
      artifact.document_id,
      artifact.company_id,
      artifact.income_year,
      'corporate_decision:' || artifact.decision_id::text,
      case artifact.variant
        when 'unsigned' then 'generated_unsigned'
        when 'signed_owner_attested' then 'signed_owner_attested'
        else null
      end,
      artifact.content_sha256,
      artifact.byte_length,
      artifact.created_by
    );
  end loop;
  for artifact in
    select
      item.action_id as id, item.document_id, item.company_id,
      item.income_year, item.created_by
    from corporate_governance.shareholder_loans item
    where item.document_id is not null
  loop
    perform documents.backfill_evidence_reference_v1(
      'corporate_governance',
      'shareholder_loans',
      artifact.id,
      artifact.document_id,
      artifact.company_id,
      artifact.income_year,
      null,
      null,
      null,
      null,
      artifact.created_by
    );
  end loop;
end
$backfill_document_evidence$;

reset role;

set local role ledger_store_owner;
revoke create on schema backend_system
from corporate_governance_workflow_executor;
reset role;

grant usage on schema backend_system
to corporate_governance_workflow_executor;

revoke all on function
  corporate_governance.record_owner_dividend_event_v1(jsonb, text),
  corporate_governance.attest_owner_dividend_signed_artifact_v1(jsonb, text),
  backend_system.list_annual_data_legacy_v1(uuid, integer, text),
  corporate_governance.read_corporate_lifecycle_v1(uuid[], uuid, text),
  corporate_governance.owner_dividend_lifecycle_pre148_v1(uuid, boolean),
  corporate_governance.prepare_owner_dividend_finalization_pre148_v1(
    jsonb, text
  ),
  corporate_governance.complete_owner_dividend_finalization_pre148_v1(
    jsonb, text
  ),
  corporate_governance.complete_owner_dividend_payment_pre148_v1(
    jsonb, text
  )
from public, anon, authenticated, service_role;
grant execute on function
  corporate_governance.record_owner_dividend_event_v1(jsonb, text),
  corporate_governance.attest_owner_dividend_signed_artifact_v1(jsonb, text),
  backend_system.list_annual_data_legacy_v1(uuid, integer, text),
  corporate_governance.read_corporate_lifecycle_v1(uuid[], uuid, text)
to corporate_governance_workflow_executor;

do $backend_system_role_authority_revoke$
begin
  execute pg_catalog.format(
    'revoke ledger_store_owner, backend_system_annual_data_reader, '
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
$backend_system_role_authority_revoke$;

commit;
