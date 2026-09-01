-- Keep correction-source replay insert-only on the forward runtime chain.
-- The contract cutover already carries this implementation, but contract
-- migrations are not part of a fresh Supabase migration replay and cannot
-- repair an already-expanded hosted database by themselves.
begin;

set local lock_timeout = '5s';
set local statement_timeout = '120s';

select pg_catalog.pg_advisory_xact_lock(
  pg_catalog.hashtextextended(
    'talli:investments:lifecycle-correction-source-idempotence',
    0
  )
);

do $membership$
begin
  execute pg_catalog.format(
    'grant investments_store_owner to %I',
    current_user
  );
end
$membership$;

set local role investments_store_owner;

-- Corrections may cite a document fact registered by the original lifecycle
-- record. ON CONFLICT DO UPDATE still needs UPDATE RLS authority even when the
-- value is unchanged, so retain immutable facts and reconcile their hashes.
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

reset role;

do $membership_revoke$
begin
  execute pg_catalog.format(
    'revoke investments_store_owner from %I',
    current_user
  );
end
$membership_revoke$;

commit;
