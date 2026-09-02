-- CONTRACT RELEASE ARTIFACT: corporate_governance stage exit #148
-- Contract the predecessor corporate-governance store after canonical cutover.
begin;

set local lock_timeout = '5s';
set local statement_timeout = '120s';
select pg_catalog.set_config(
  'talli.corporate_governance_contract_principal', current_user, true
);

do $membership$
begin
  execute pg_catalog.format(
    'grant corporate_governance_store_owner, '
      || 'corporate_governance_workflow_executor, '
      || 'company_archive_projection_executor, ledger_store_owner to %I',
    current_user
  );
  execute pg_catalog.format(
    'grant documents_store_owner to %I with set true', current_user
  );
end
$membership$;

set local role company_archive_projection_executor;
do $archive_authority$
begin
  execute pg_catalog.format(
    'grant execute on function public.company_archive_track_source_write_v1() to %I',
    pg_catalog.current_setting(
      'talli.corporate_governance_contract_principal'
    )
  );
end
$archive_authority$;
reset role;

-- Every predecessor identity and immutable hash must be present in exactly one
-- canonical decision family before any legacy object is removed.
do $reconciliation$
begin
  if exists (
    select 1
    from public.corporate_decisions legacy
    left join corporate_governance.owner_dividend_decisions owner_decision
      on owner_decision.id = legacy.id
      and owner_decision.decision_hash = legacy.decision_hash
    left join corporate_governance.annual_close_decisions annual_decision
      on annual_decision.id = legacy.id
      and annual_decision.decision_hash = legacy.decision_hash
    where (legacy.decision_kind = 'owner_dividend'
        and owner_decision.id is null)
      or (legacy.decision_kind = 'annual_close'
        and annual_decision.id is null)
  ) then
    raise exception 'corporate_governance_decision_reconciliation_failed';
  end if;

  if exists (
    select 1
    from public.corporate_accounting_policies legacy
    left join corporate_governance.owner_dividend_accounting_policies current
      on current.policy_version = legacy.policy_version
      and current.declaration_debit_account
        = legacy.declaration_debit_account
      and current.dividend_payable_account = legacy.dividend_payable_account
      and current.bank_account = legacy.bank_account
    where current.policy_version is null
  ) then
    raise exception 'corporate_governance_policy_reconciliation_failed';
  end if;

  if exists (
    select 1
    from public.corporate_document_artifacts legacy
    left join corporate_governance.owner_dividend_artifacts owner_artifact
      on owner_artifact.id = legacy.id
      and owner_artifact.content_sha256 = legacy.content_sha256
      and owner_artifact.document_id = legacy.document_id
    left join corporate_governance.annual_close_artifacts annual_artifact
      on annual_artifact.id = legacy.id
      and annual_artifact.content_sha256 = legacy.content_sha256
      and annual_artifact.document_id = legacy.document_id
    where owner_artifact.id is null and annual_artifact.id is null
  ) then
    raise exception 'corporate_governance_artifact_reconciliation_failed';
  end if;

  if exists (
    select 1
    from public.corporate_decision_finalizations legacy
    left join corporate_governance.owner_dividend_finalizations owner_item
      on owner_item.id = legacy.id
      and owner_item.decision_hash = legacy.decision_hash
    left join corporate_governance.annual_close_finalizations annual_item
      on annual_item.id = legacy.id
      and annual_item.decision_hash = legacy.decision_hash
    where owner_item.id is null and annual_item.id is null
  ) then
    raise exception 'corporate_governance_finalization_reconciliation_failed';
  end if;

  if exists (
    select 1
    from public.holding_actions legacy
    where legacy.action_type = 'shareholder_loan'
      and not exists (
        select 1 from corporate_governance.shareholder_loans current
        where current.action_id = legacy.id
          and current.accounting_entry_id = legacy.ledger_entry_id
      )
  ) then
    raise exception 'corporate_governance_shareholder_loan_reconciliation_failed';
  end if;

  if exists (
    select 1
    from public.holding_actions legacy
    where legacy.action_type = 'dividend_to_owner'
      and not exists (
        select 1
        from corporate_governance.owner_dividend_finalizations current
        where current.holding_action_id = legacy.id
          and current.accounting_entry_id = legacy.ledger_entry_id
        union all
        select 1
        from corporate_governance.owner_dividend_payments current
        where current.holding_action_id = legacy.id
          and current.accounting_entry_id = legacy.ledger_entry_id
      )
  ) then
    raise exception 'corporate_governance_owner_dividend_reconciliation_failed';
  end if;
end
$reconciliation$;

-- New commands no longer project shareholder loans into holding_actions, and
-- proposal validation no longer calls the predecessor SQL policy engine.
do $cut_remaining_projections$
declare
  v_definition text;
  v_rewritten text;
begin
  v_definition := pg_catalog.pg_get_functiondef(
    'corporate_governance.complete_shareholder_loan_v1(jsonb,text)'::regprocedure
  );
  if pg_catalog.strpos(
    v_definition, 'backend_system.project_shareholder_loan_v1'
  ) > 0 then
    v_rewritten := pg_catalog.replace(v_definition, $old$
  perform backend_system.project_shareholder_loan_v1(
    p_request, p_verified_subject
  );$old$, '');
    if v_rewritten = v_definition then
      raise exception 'corporate_governance_shareholder_projection_definition_drift';
    end if;
    execute v_rewritten;
  end if;

  v_definition := pg_catalog.pg_get_functiondef(
    'corporate_governance.propose_owner_dividend_v1(jsonb,jsonb,jsonb,text)'::regprocedure
  );
  if pg_catalog.strpos(
    v_definition, 'public.assert_corporate_decision_persisted_facts'
  ) > 0 then
    v_rewritten := pg_catalog.regexp_replace(
      v_definition,
      E'  begin\\n    perform public\\.assert_corporate_decision_persisted_facts\\([\\s\\S]+?  end;\\n  v_fingerprint :=',
      E'  v_fingerprint :=',
      'n'
    );
    if v_rewritten = v_definition then
      raise exception 'corporate_governance_owner_proposal_definition_drift';
    end if;
    execute v_rewritten;
  end if;

  v_definition := pg_catalog.pg_get_functiondef(
    'corporate_governance.propose_annual_close_v1(jsonb,jsonb,jsonb,jsonb,text)'::regprocedure
  );
  if pg_catalog.strpos(
    v_definition, 'public.assert_corporate_decision_persisted_facts'
  ) > 0 then
    v_rewritten := pg_catalog.regexp_replace(
      v_definition,
      E'  begin\\n    perform public\\.assert_corporate_decision_persisted_facts\\([\\s\\S]+?  end;\\n  v_fingerprint :=',
      E'  v_fingerprint :=',
      'n'
    );
    if v_rewritten = v_definition then
      raise exception 'corporate_governance_annual_proposal_definition_drift';
    end if;
    execute v_rewritten;
  end if;
end
$cut_remaining_projections$;

-- Documents retains only its boolean evidence boundary, now backed by the
-- canonical governance stores.
set local role documents_store_owner;
do $documents_authority$
begin
  execute pg_catalog.format(
    'grant usage on schema documents to %I',
    pg_catalog.current_setting(
      'talli.corporate_governance_contract_principal'
    )
  );
end
$documents_authority$;
reset role;

create or replace function documents.has_evidence_references_v1(
  p_document_id uuid
)
returns boolean
language plpgsql
security definer
set search_path = ''
stable
as $function$
declare
  v_investment_linked boolean := false;
begin
  if pg_catalog.to_regclass('investments.source_fact_registry') is not null then
    execute $query$
      select exists (
        select 1 from investments.source_fact_registry item
        where item.source_capability='DOCUMENTS'
          and item.source_record_id=$1
      )
    $query$ into v_investment_linked using p_document_id;
  end if;
  return exists (
      select 1 from public.holding_actions item
      where item.document_id = p_document_id
        and item.action_type not in ('shareholder_loan', 'dividend_to_owner')
    )
    or exists (
      select 1 from corporate_governance.owner_dividend_artifacts item
      where item.document_id = p_document_id
    )
    or exists (
      select 1 from corporate_governance.annual_close_artifacts item
      where item.document_id = p_document_id
    )
    or exists (
      select 1 from corporate_governance.shareholder_loans item
      where item.document_id = p_document_id
    )
    or exists (
      select 1 from public.filing_submissions item
      where coalesce(item.feedback_document_ids, '[]'::jsonb)
          @> pg_catalog.jsonb_build_array(p_document_id::text)
        or item.receipt_id = p_document_id::text
    )
    or exists (
      select 1 from public.production_feedback_artifacts item
      where item.document_id = p_document_id
    )
    or v_investment_linked
    or exists (
      select 1
      from public.ledger_entries item
      join public.documents document on document.id = p_document_id
      where item.company_id = document.company_id
        and pg_catalog.strpos(item.memo, p_document_id::text) > 0
    );
end;
$function$;

set local role documents_store_owner;
do $documents_authority_revoke$
begin
  execute pg_catalog.format(
    'revoke usage on schema documents from %I',
    pg_catalog.current_setting(
      'talli.corporate_governance_contract_principal'
    )
  );
end
$documents_authority_revoke$;
reset role;

-- Canonical writes invalidate archive generations directly.
do $archive_sources$
declare
  source record;
begin
  for source in select * from (values
    ('owner_dividend_accounting_policies', 'company', 'recorded_by'),
    ('owner_dividend_decisions', 'year', 'company_id'),
    ('owner_dividend_artifacts', 'year', 'company_id'),
    ('owner_dividend_events', 'year', 'company_id'),
    ('owner_dividend_finalizations', 'year', 'company_id'),
    ('owner_dividend_payments', 'year', 'company_id'),
    ('shareholder_loans', 'year', 'company_id'),
    ('annual_close_decisions', 'year', 'company_id'),
    ('annual_close_artifacts', 'year', 'company_id'),
    ('annual_close_events', 'year', 'company_id'),
    ('annual_close_finalizations', 'year', 'company_id')
  ) as inventory(table_name, invalidation_scope, company_column)
  loop
    -- Policies are global reviewed configuration and do not carry a company;
    -- all company-year generations are invalidated explicitly below.
    if source.table_name <> 'owner_dividend_accounting_policies' then
      execute pg_catalog.format(
        'create trigger %I before insert or update or delete on corporate_governance.%I for each row execute function public.company_archive_track_source_write_v1(%L, %L)',
        'company_archive_track_' || source.table_name,
        source.table_name, source.invalidation_scope, source.company_column
      );
    end if;
  end loop;
end
$archive_sources$;

-- Remove governance rows from the generic holding ledger only after their
-- canonical counterparts have reconciled.
delete from public.holding_actions
where action_type in ('shareholder_loan', 'dividend_to_owner');

drop function if exists public.create_corporate_document_draft(jsonb);
drop function if exists public.record_corporate_document_event(jsonb);
drop function if exists public.attest_corporate_signed_artifact(jsonb);
drop function if exists public.finalize_corporate_decision(jsonb);
drop function if exists public.record_owner_dividend_payment(jsonb);

drop function if exists
  backend_system.complete_corporate_decision_finalization_v1(
    jsonb, uuid, jsonb, text
  );
drop function if exists
  backend_system.prepare_corporate_decision_finalization_v1(jsonb, text);
drop function if exists
  backend_system.complete_owner_dividend_payment_v1(
    jsonb, uuid, jsonb, text
  );
drop function if exists
  backend_system.prepare_owner_dividend_payment_v1(jsonb, text);
drop function if exists backend_system.owner_dividend_signed_evidence_v1(
  uuid, uuid, uuid, integer, text
);
drop function if exists
  backend_system.complete_shareholder_loan_v1(jsonb, uuid, jsonb, text);
drop function if exists
  backend_system.prepare_shareholder_loan_v1(jsonb, text);
drop function if exists
  backend_system.project_owner_dividend_finalization_v1(
    jsonb, text, jsonb, text
  );
drop function if exists
  backend_system.project_owner_dividend_payment_v1(
    jsonb, bigint, text, text
  );
set local role ledger_store_owner;
drop function if exists
  backend_system.project_shareholder_loan_v1(jsonb, text);
reset role;

drop trigger if exists company_archive_track_corporate_document_events
  on public.corporate_document_events;
drop trigger if exists prevent_corporate_document_events_mutation
  on public.corporate_document_events;
drop trigger if exists company_archive_track_corporate_decision_finalizations
  on public.corporate_decision_finalizations;
drop trigger if exists prevent_corporate_decision_finalizations_mutation
  on public.corporate_decision_finalizations;
drop trigger if exists company_archive_track_corporate_document_artifacts
  on public.corporate_document_artifacts;
drop trigger if exists prevent_corporate_document_artifacts_mutation
  on public.corporate_document_artifacts;
drop trigger if exists company_archive_track_corporate_document_sets
  on public.corporate_document_sets;
drop trigger if exists prevent_corporate_document_sets_mutation
  on public.corporate_document_sets;
drop trigger if exists company_archive_track_corporate_decisions
  on public.corporate_decisions;
drop trigger if exists prevent_corporate_decisions_mutation
  on public.corporate_decisions;
drop trigger if exists prevent_corporate_accounting_policies_mutation
  on public.corporate_accounting_policies;

delete from public.corporate_document_events;
delete from public.corporate_decision_finalizations;
delete from public.corporate_document_artifacts;
delete from public.corporate_document_sets;
delete from public.corporate_decisions;
delete from public.corporate_accounting_policies;

do $empty_preflight$
begin
  if pg_catalog.to_regclass('public.corporate_document_events') is not null
    and exists (select 1 from public.corporate_document_events)
  then raise exception 'corporate_document_events_not_empty'; end if;
  if pg_catalog.to_regclass('public.corporate_decision_finalizations') is not null
    and exists (select 1 from public.corporate_decision_finalizations)
  then raise exception 'corporate_decision_finalizations_not_empty'; end if;
  if pg_catalog.to_regclass('public.corporate_document_artifacts') is not null
    and exists (select 1 from public.corporate_document_artifacts)
  then raise exception 'corporate_document_artifacts_not_empty'; end if;
  if pg_catalog.to_regclass('public.corporate_document_sets') is not null
    and exists (select 1 from public.corporate_document_sets)
  then raise exception 'corporate_document_sets_not_empty'; end if;
  if pg_catalog.to_regclass('public.corporate_decisions') is not null
    and exists (select 1 from public.corporate_decisions)
  then raise exception 'corporate_decisions_not_empty'; end if;
  if pg_catalog.to_regclass('public.corporate_accounting_policies') is not null
    and exists (select 1 from public.corporate_accounting_policies)
  then raise exception 'corporate_accounting_policies_not_empty'; end if;
end
$empty_preflight$;

drop table if exists public.corporate_document_events;
drop table if exists public.corporate_decision_finalizations;
drop table if exists public.corporate_document_artifacts;
drop table if exists public.corporate_document_sets;
drop table if exists public.corporate_decisions;
drop table if exists public.corporate_accounting_policies;

drop function if exists public.assert_corporate_decision_persisted_facts(
  uuid, integer, text, uuid, jsonb, text
);
drop function if exists public.canonical_corporate_json_text(jsonb);
drop function if exists public.assert_fresh_corporate_step_up(uuid);
drop function if exists public.assert_corporate_owner(uuid);
drop function if exists public.prevent_corporate_record_mutation();

-- Rollback-only definitions retained by the expand migration are no longer
-- part of the live schema once the contract has completed.
drop function if exists
  corporate_governance.owner_dividend_lifecycle_pre148_v1(uuid, boolean);
drop function if exists
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

set local role company_archive_projection_executor;
do $membership_revoke$
begin
  execute pg_catalog.format(
    'revoke execute on function public.company_archive_track_source_write_v1() from %I',
    pg_catalog.current_setting(
      'talli.corporate_governance_contract_principal'
    )
  );
end
$membership_revoke$;
reset role;

do $archive_membership_revoke$
begin
  execute pg_catalog.format(
    'revoke company_archive_projection_executor, ledger_store_owner from %I',
    pg_catalog.current_setting(
      'talli.corporate_governance_contract_principal'
    )
  );
  execute pg_catalog.format(
    'grant documents_store_owner to %I with set false',
    pg_catalog.current_setting(
      'talli.corporate_governance_contract_principal'
    )
  );
end
$archive_membership_revoke$;

commit;
