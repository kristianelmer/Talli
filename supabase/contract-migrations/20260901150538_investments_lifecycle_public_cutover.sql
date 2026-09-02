-- Contract-stage cutover for #190: keep legacy data and bounded rollback
-- routines, but make every v1 investment writer unreachable from the
-- application workflow role after the public API has moved to lifecycle v2.
begin;

set local lock_timeout = '5s';
set local statement_timeout = '120s';

select pg_catalog.pg_advisory_xact_lock(
  pg_catalog.hashtextextended(
    'talli:investments:lifecycle-public-cutover:contract',
    0
  )
);

do $membership$
begin
  execute pg_catalog.format(
    'grant investments_store_owner, ledger_store_owner to %I',
    current_user
  );
end
$membership$;

set local role investments_store_owner;

-- Corrections are allowed to cite an immutable document fact that an earlier
-- recognition already registered. A no-op UPDATE upsert is still an UPDATE to
-- PostgreSQL RLS, so validate the existing hash after an insert-only conflict
-- path instead of granting mutation authority over the fact registry.
create or replace function investments.record_lifecycle_correction_sources_v2(
  p_company_id uuid, p_correction_id uuid, p_document_facts jsonb
)
returns void language plpgsql security definer set search_path = ''
as $function$
declare
  v_count integer;
begin
  if pg_catalog.jsonb_typeof(p_document_facts) <> 'array'
    or pg_catalog.jsonb_array_length(p_document_facts) not between 1 and 50
  then raise exception 'investments_invalid_input'; end if;

  insert into investments.source_fact_registry (
    company_id, source_capability, source_record_id, source_revision,
    fact_sha256
  )
  select p_company_id, item ->> 'capability',
    (item ->> 'recordId')::uuid, (item ->> 'revision')::integer,
    item ->> 'factSha256'
  from pg_catalog.jsonb_array_elements(p_document_facts) item
  on conflict (
    company_id, source_capability, source_record_id, source_revision
  ) do nothing;

  select pg_catalog.count(*) into v_count
  from pg_catalog.jsonb_array_elements(p_document_facts) item
  join investments.source_fact_registry registered
    on registered.company_id = p_company_id
   and registered.source_capability = item ->> 'capability'
   and registered.source_record_id = (item ->> 'recordId')::uuid
   and registered.source_revision = (item ->> 'revision')::integer
   and registered.fact_sha256 = item ->> 'factSha256';
  if v_count <> pg_catalog.jsonb_array_length(p_document_facts)
  then raise exception 'investments_invalid_input'; end if;

  insert into investments.lifecycle_correction_sources (
    correction_id, company_id, ordinal, source_capability,
    source_record_id, source_revision, fact_sha256
  )
  select p_correction_id, p_company_id, ordinal::integer,
    item ->> 'capability', (item ->> 'recordId')::uuid,
    (item ->> 'revision')::integer, item ->> 'factSha256'
  from pg_catalog.jsonb_array_elements(p_document_facts)
    with ordinality source(item, ordinal);
end;
$function$;

-- Banking publishes immutable transaction records rather than a versioned fact
-- stream. Reject caller-invented revisions before ledger posting, including on
-- corrected settlements, and retain the same invariant at the table boundary.
create or replace function investments.cash_settlement_fingerprint_v2(
  p_request jsonb
)
returns text language plpgsql immutable set search_path = ''
as $function$
begin
  if p_request -> 'bankFact' ->> 'revision' <> '1'
  then raise exception 'investments_invalid_input'; end if;
  return pg_catalog.encode(extensions.digest(
    (p_request - array['evidenceDigest', 'correlationId'])::text,
    'sha256'
  ), 'hex');
end;
$function$;

create or replace function investments.lifecycle_cash_evidence_is_valid_v2(
  p_request jsonb
)
returns boolean language sql immutable set search_path = ''
as $function$
  select
    nullif(pg_catalog.btrim(p_request ->> 'evidenceReference'), '') is not null
    and pg_catalog.length(p_request ->> 'evidenceReference') <= 500
    and p_request -> 'documentFacts' = '[]'::jsonb
    and pg_catalog.jsonb_typeof(p_request -> 'bankFact') = 'object'
    and p_request -> 'bankFact' ->> 'capability' = 'BANKING'
    and coalesce(p_request -> 'bankFact' ->> 'recordId', '')
      ~ '^[0-9a-fA-F-]{36}$'
    and p_request -> 'bankFact' ->> 'revision' = '1'
    and coalesce(p_request -> 'bankFact' ->> 'factSha256', '')
      ~ '^[0-9a-f]{64}$'
    and (
      (p_request ->> 'evidenceMode' = 'linked_sources'
        and (p_request ->> 'ownerAttested')::boolean = false)
      or (p_request ->> 'evidenceMode' = 'manual_fallback'
        and (p_request ->> 'ownerAttested')::boolean = true)
    );
$function$;

-- One immutable bank fact represents one cash movement. Reusing it for a
-- second economic event would double-post cash while appearing reconciled.
-- Keep this safety constraint through rollback so a recutover cannot admit
-- duplicate evidence during the predecessor overlap.
do $bank_fact_uniqueness$
begin
  if exists (
    select 1
    from investments.cash_settlements settlement
    group by settlement.company_id, settlement.source_capability,
      settlement.source_record_id
    having pg_catalog.count(*) > 1
  ) or exists (
    select 1 from investments.cash_settlements settlement
    where settlement.source_revision <> 1
  ) then
    raise exception 'investments_lifecycle_bank_fact_duplicate';
  end if;

  if not exists (
    select 1
    from pg_catalog.pg_constraint constraint_record
    join pg_catalog.pg_namespace namespace
      on namespace.oid = constraint_record.connamespace
    where namespace.nspname = 'investments'
      and constraint_record.conname =
        'cash_settlements_bank_fact_revision_check'
  ) then
    alter table investments.cash_settlements
      add constraint cash_settlements_bank_fact_revision_check
      check (source_revision = 1);
  end if;

  if not exists (
    select 1
    from pg_catalog.pg_constraint constraint_record
    join pg_catalog.pg_namespace namespace
      on namespace.oid = constraint_record.connamespace
    where namespace.nspname = 'investments'
      and constraint_record.conname = 'cash_settlements_bank_fact_key'
  ) then
    alter table investments.cash_settlements
      add constraint cash_settlements_bank_fact_key unique (
        company_id, source_capability, source_record_id
      );
  end if;
end
$bank_fact_uniqueness$;

revoke execute on function
  investments.get_share_purchase_replay_v1(jsonb, text),
  investments.prepare_share_purchase_v1(jsonb, text),
  investments.complete_share_purchase_v1(jsonb, uuid, jsonb, text),
  investments.get_share_sale_replay_v1(jsonb, text),
  investments.prepare_share_sale_v1(jsonb, text),
  investments.complete_share_sale_v1(jsonb, uuid, text),
  investments.get_received_dividend_replay_v1(jsonb, text),
  investments.prepare_received_dividend_v1(jsonb, text),
  investments.complete_received_dividend_v1(jsonb, uuid, text),
  investments.get_received_fund_distribution_replay_v1(jsonb, text),
  investments.prepare_received_fund_distribution_v1(jsonb, text),
  investments.complete_received_fund_distribution_v1(jsonb, uuid, text),
  investments.get_correction_replay_v1(jsonb, text),
  investments.prepare_correction_v1(jsonb, text),
  investments.complete_correction_v1(jsonb, uuid, uuid, uuid, text)
from investments_workflow_executor;

reset role;
grant create on schema ledger to ledger_store_owner;
set local role ledger_store_owner;

do $ledger_correction_routine$
begin
  if pg_catalog.to_regprocedure(
    'ledger.link_investment_correction_v1(uuid,integer,uuid,uuid,uuid,uuid,text,text,date,text)'
  ) is not null and pg_catalog.to_regprocedure(
    'ledger.link_investment_lifecycle_correction_v2(uuid,integer,uuid,uuid,uuid,uuid,text,text,date,text)'
  ) is null then
    execute 'alter function ledger.link_investment_correction_v1(uuid, integer, uuid, uuid, uuid, uuid, text, text, date, text) rename to link_investment_lifecycle_correction_v2';
  elsif pg_catalog.to_regprocedure(
    'ledger.link_investment_correction_v1(uuid,integer,uuid,uuid,uuid,uuid,text,text,date,text)'
  ) is not null or pg_catalog.to_regprocedure(
    'ledger.link_investment_lifecycle_correction_v2(uuid,integer,uuid,uuid,uuid,uuid,text,text,date,text)'
  ) is null then
    raise exception 'investments_lifecycle_public_cutover_routine_unsafe';
  end if;
end
$ledger_correction_routine$;

revoke all on function ledger.link_investment_lifecycle_correction_v2(
  uuid, integer, uuid, uuid, uuid, uuid, text, text, date, text
)
from public, anon, authenticated, service_role, investments_workflow_executor;

grant execute on function ledger.link_investment_lifecycle_correction_v2(
  uuid, integer, uuid, uuid, uuid, uuid, text, text, date, text
)
to investments_workflow_executor;

reset role;
revoke create on schema ledger from ledger_store_owner;

do $membership_revoke$
begin
  execute pg_catalog.format(
    'revoke investments_store_owner, ledger_store_owner from %I',
    current_user
  );
end
$membership_revoke$;

commit;
