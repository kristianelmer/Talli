-- Issue #188: bind every January-to-as-of reconstruction assessment to the
-- exact immutable ledger facts it assessed. Source capabilities still own the
-- supplied facts; this migration only proves their persisted ledger coverage.

begin;

do $ledger_economic_facts_migration_authority$
begin
  execute pg_catalog.format('grant ledger_store_owner to %I', current_user);
  execute pg_catalog.format('grant create on schema ledger to %I', current_user);
  grant create on schema ledger to ledger_store_owner;
end
$ledger_economic_facts_migration_authority$;

create table if not exists ledger.reconstruction_economic_fact_sets (
  assessment_id uuid primary key,
  company_id uuid not null,
  income_year integer not null check (income_year between 2000 and 2100),
  as_of date not null,
  fact_count integer not null check (fact_count >= 0),
  facts_digest text not null check (facts_digest ~ '^[0-9a-f]{64}$'),
  unique (assessment_id, company_id, income_year),
  foreign key (assessment_id, company_id, income_year)
    references ledger.reconstruction_assessments(id, company_id, income_year)
    on delete restrict,
  check (extract(year from as_of)::integer = income_year)
);

create table if not exists ledger.reconstruction_economic_facts (
  assessment_id uuid not null,
  company_id uuid not null,
  income_year integer not null check (income_year between 2000 and 2100),
  ordinal integer not null check (ordinal >= 1),
  entry_id uuid not null,
  fact jsonb not null,
  primary key (assessment_id, ordinal),
  unique (assessment_id, entry_id),
  foreign key (assessment_id, company_id, income_year)
    references ledger.reconstruction_economic_fact_sets(
      assessment_id, company_id, income_year
    ) on delete restrict
);

alter table ledger.reconstruction_economic_facts
  add column if not exists fact jsonb;
alter table ledger.reconstruction_economic_facts
  alter column fact set not null;

alter table ledger.reconstruction_economic_fact_sets enable row level security;
alter table ledger.reconstruction_economic_fact_sets force row level security;
alter table ledger.reconstruction_economic_facts enable row level security;
alter table ledger.reconstruction_economic_facts force row level security;

drop policy if exists "ledger store reads reconstruction economic fact sets"
  on ledger.reconstruction_economic_fact_sets;
create policy "ledger store reads reconstruction economic fact sets"
on ledger.reconstruction_economic_fact_sets for select to ledger_store_owner
using (public.company_access_is_accepted_member_v1(company_id));

drop policy if exists "ledger store records reconstruction economic fact sets"
  on ledger.reconstruction_economic_fact_sets;
create policy "ledger store records reconstruction economic fact sets"
on ledger.reconstruction_economic_fact_sets for insert to ledger_store_owner
with check (public.company_access_is_accepted_owner_v1(company_id));

drop policy if exists "ledger store reads reconstruction economic facts"
  on ledger.reconstruction_economic_facts;
create policy "ledger store reads reconstruction economic facts"
on ledger.reconstruction_economic_facts for select to ledger_store_owner
using (public.company_access_is_accepted_member_v1(company_id));

drop policy if exists "ledger store records reconstruction economic facts"
  on ledger.reconstruction_economic_facts;
create policy "ledger store records reconstruction economic facts"
on ledger.reconstruction_economic_facts for insert to ledger_store_owner
with check (public.company_access_is_accepted_owner_v1(company_id));

create or replace function ledger.company_year_economic_facts_v1(
  p_company_id uuid,
  p_income_year integer,
  p_entry_ids uuid[]
)
returns jsonb
language sql
stable
security definer
set search_path = ''
as $function$
  select coalesce(pg_catalog.jsonb_agg(fact order by event_date, entry_id), '[]'::jsonb)
  from (
    select coalesce(context.event_date, entry.posted_at::date) event_date,
      entry.id entry_id,
      pg_catalog.jsonb_build_object(
        'entryId', entry.id,
        'eventDate', coalesce(context.event_date, entry.posted_at::date),
        'entryKind', entry.entry_kind,
        'memo', entry.memo,
        'lines', entry.lines,
        'correlationId', entry.correlation_id,
        'ruleVersion', context.rule_version,
        'sources', coalesce((
          select pg_catalog.jsonb_agg(
            pg_catalog.jsonb_build_object(
              'role', source.source_role,
              'capability', source.source_capability,
              'recordId', source.source_record_id,
              'revision', source.source_revision,
              'factSha256', source.fact_sha256
            ) order by source.ordinal
          )
          from ledger.entry_sources source
          where source.entry_id = entry.id
        ), pg_catalog.jsonb_build_array(pg_catalog.jsonb_build_object(
          'role', 'PRIMARY',
          'capability', entry.source_capability,
          'recordId', entry.source_record_id,
          'revision', null,
          'factSha256', null
        ))),
        'corrections', coalesce((
          select pg_catalog.jsonb_agg(
            pg_catalog.jsonb_build_object(
              'originalEntryId', correction.original_entry_id,
              'reversalEntryId', correction.reversal_entry_id,
              'replacementEntryId', correction.replacement_entry_id,
              'reason', correction.reason,
              'correctedBy', correction.corrected_by,
              'correctedAt', correction.corrected_at
            ) order by correction.original_entry_id
          )
          from ledger.entry_corrections correction
          where entry.id in (
            correction.original_entry_id,
            correction.reversal_entry_id,
            correction.replacement_entry_id
          )
        ), '[]'::jsonb),
        'postedBy', entry.created_by,
        'postedAt', entry.posted_at
      ) fact
    from ledger.entries entry
    left join ledger.entry_contexts context on context.entry_id = entry.id
    where entry.company_id = p_company_id
      and entry.income_year = p_income_year
      and entry.id = any(p_entry_ids)
  ) canonical;
$function$;

create or replace function ledger.get_company_year_economic_fact_candidates_v1(
  p_company_id uuid,
  p_income_year integer,
  p_as_of date,
  p_verified_subject text
)
returns table (
  entry_ids uuid[],
  facts_digest text,
  fact_count integer,
  facts jsonb
)
language plpgsql
stable
security definer
set search_path = ''
as $function$
begin
  if public.company_access_auth_uid_v1() is null
    or p_verified_subject is null
    or p_verified_subject !~ '^[0-9a-fA-F-]{36}$'
    or public.company_access_auth_uid_v1() is distinct from p_verified_subject::uuid
  then
    raise exception 'ledger_forbidden';
  end if;
  if p_income_year not between 2000 and 2100
    or p_as_of is null
    or extract(year from p_as_of)::integer <> p_income_year
  then
    raise exception 'ledger_invalid_input';
  end if;
  if not public.company_access_is_accepted_member_v1(p_company_id) then
    raise exception 'ledger_not_found';
  end if;
  select coalesce(pg_catalog.array_agg(entry.id order by entry.id), '{}'::uuid[])
  into entry_ids
  from ledger.entries entry
  left join ledger.entry_contexts context on context.entry_id = entry.id
  where entry.company_id = p_company_id
    and entry.income_year = p_income_year
    and coalesce(context.event_date, entry.posted_at::date)
      between pg_catalog.make_date(p_income_year, 1, 1)
      and p_as_of;
  facts := ledger.company_year_economic_facts_v1(
    p_company_id, p_income_year, entry_ids
  );
  facts_digest := pg_catalog.encode(
    extensions.digest(facts::text, 'sha256'), 'hex'
  );
  fact_count := pg_catalog.cardinality(entry_ids);
  return next;
end;
$function$;

create or replace function ledger.record_reconstruction_assessment(
  p_idempotency_key text,
  p_company_id uuid,
  p_income_year integer,
  p_as_of date,
  p_evidence jsonb,
  p_economic_fact_entry_ids uuid[],
  p_state text,
  p_gap_codes text[],
  p_correlation_id text,
  p_verified_subject text
)
returns table (
  assessment_id uuid,
  company_id uuid,
  income_year integer,
  as_of date,
  state text,
  gap_codes text[],
  evidence_digest text,
  ledger_state_digest text,
  economic_facts_digest text,
  economic_fact_count integer,
  recorded_at timestamptz,
  replayed boolean
)
language plpgsql
security definer
set search_path = ''
as $function$
declare
  v_legacy record;
  v_requested_ids uuid[];
  v_expected_ids uuid[];
  v_fact_ids_by_date uuid[];
  v_facts jsonb;
  v_facts_digest text;
  v_stored ledger.reconstruction_economic_fact_sets%rowtype;
begin
  if p_company_id is null
    or p_income_year not between 2000 and 2100
    or p_as_of is null
    or extract(year from p_as_of)::integer <> p_income_year
    or p_economic_fact_entry_ids is null
  then
    raise exception 'ledger_reconstruction_economic_facts_invalid';
  end if;
  select coalesce(pg_catalog.array_agg(entry_id order by entry_id), '{}'::uuid[])
  into v_requested_ids
  from pg_catalog.unnest(p_economic_fact_entry_ids) entry_id;
  if pg_catalog.cardinality(v_requested_ids)
      <> (select pg_catalog.count(distinct entry_id)
          from pg_catalog.unnest(p_economic_fact_entry_ids) entry_id)
  then
    raise exception 'ledger_reconstruction_economic_facts_invalid';
  end if;

  -- The legacy recorder authenticates the actor, validates the evidence, and
  -- holds the same company-year transaction lock as every posting command.
  -- Resolve the complete fact set only after that lock is held, so a
  -- concurrent posting cannot commit between completeness validation and the
  -- immutable snapshot. Any later failure still rolls this call back atomically.
  select legacy.* into strict v_legacy
  from ledger.record_reconstruction_assessment_without_state_digest_v1(
    p_idempotency_key, p_company_id, p_income_year, p_as_of, p_evidence,
    p_state, p_gap_codes, p_correlation_id, p_verified_subject
  ) legacy;

  select coalesce(pg_catalog.array_agg(entry.id order by entry.id), '{}'::uuid[]),
    coalesce(pg_catalog.array_agg(
      entry.id order by coalesce(context.event_date, entry.posted_at::date), entry.id
    ), '{}'::uuid[])
  into v_expected_ids, v_fact_ids_by_date
  from ledger.entries entry
  left join ledger.entry_contexts context on context.entry_id = entry.id
  where entry.company_id = p_company_id
    and entry.income_year = p_income_year
    and coalesce(context.event_date, entry.posted_at::date)
      between pg_catalog.make_date(p_income_year, 1, 1)
      and p_as_of;

  if v_requested_ids is distinct from v_expected_ids
    or exists (
      select 1
      from pg_catalog.unnest(v_expected_ids) expected(entry_id)
      where exists (
          select 1 from ledger.entry_contexts context
          where context.entry_id = expected.entry_id
        )
        and (
          (select pg_catalog.count(*) from ledger.entry_sources source
           where source.entry_id = expected.entry_id) < 1
          or (select pg_catalog.count(*) from ledger.entry_sources source
              where source.entry_id = expected.entry_id
                and source.source_role = 'PRIMARY') <> 1
        )
    )
  then
    raise exception 'ledger_reconstruction_economic_facts_invalid';
  end if;

  v_facts := ledger.company_year_economic_facts_v1(
    p_company_id, p_income_year, v_fact_ids_by_date
  );
  v_facts_digest := pg_catalog.encode(
    extensions.digest(v_facts::text, 'sha256'), 'hex'
  );

  if v_legacy.replayed then
    select fact_set.* into v_stored
    from ledger.reconstruction_economic_fact_sets fact_set
    where fact_set.assessment_id = v_legacy.assessment_id;
    if not found
      or v_stored.facts_digest is distinct from v_facts_digest
      or v_stored.fact_count is distinct from pg_catalog.cardinality(v_fact_ids_by_date)
      or v_fact_ids_by_date is distinct from (
        select coalesce(pg_catalog.array_agg(fact.entry_id order by fact.ordinal), '{}'::uuid[])
        from ledger.reconstruction_economic_facts fact
        where fact.assessment_id = v_legacy.assessment_id
      )
    then
      raise exception 'ledger_idempotency_key_reused';
    end if;
  else
    insert into ledger.reconstruction_economic_fact_sets (
      assessment_id, company_id, income_year, as_of, fact_count, facts_digest
    ) values (
      v_legacy.assessment_id, p_company_id, p_income_year, p_as_of,
      pg_catalog.cardinality(v_fact_ids_by_date), v_facts_digest
    );
    insert into ledger.reconstruction_economic_facts (
      assessment_id, company_id, income_year, ordinal, entry_id, fact
    )
    select v_legacy.assessment_id, p_company_id, p_income_year,
      id.ordinal::integer, id.entry_id, payload.fact
    from pg_catalog.unnest(v_fact_ids_by_date)
      with ordinality id(entry_id, ordinal)
    join pg_catalog.jsonb_array_elements(v_facts)
      with ordinality payload(fact, ordinal) using (ordinal);
  end if;

  return query select v_legacy.assessment_id, v_legacy.company_id,
    v_legacy.income_year, v_legacy.as_of, v_legacy.state, v_legacy.gap_codes,
    v_legacy.evidence_digest, assessment.ledger_state_digest,
    v_facts_digest, pg_catalog.cardinality(v_fact_ids_by_date),
    v_legacy.recorded_at, v_legacy.replayed
  from ledger.reconstruction_assessments assessment
  where assessment.id = v_legacy.assessment_id;
end;
$function$;

create or replace function ledger.get_reconstruction_economic_facts_v1(
  p_assessment_id uuid,
  p_verified_subject text
)
returns table (
  assessment_id uuid,
  company_id uuid,
  income_year integer,
  as_of date,
  facts_digest text,
  fact_count integer,
  facts jsonb
)
language plpgsql
stable
security definer
set search_path = ''
as $function$
declare
  v_set ledger.reconstruction_economic_fact_sets%rowtype;
begin
  if public.company_access_auth_uid_v1() is null
    or p_verified_subject is null
    or p_verified_subject !~ '^[0-9a-fA-F-]{36}$'
    or public.company_access_auth_uid_v1() is distinct from p_verified_subject::uuid
  then
    raise exception 'ledger_forbidden';
  end if;
  select fact_set.* into v_set
  from ledger.reconstruction_economic_fact_sets fact_set
  where fact_set.assessment_id = p_assessment_id;
  if not found or not public.company_access_is_accepted_member_v1(v_set.company_id) then
    raise exception 'ledger_not_found';
  end if;
  return query select v_set.assessment_id, v_set.company_id, v_set.income_year,
    v_set.as_of, v_set.facts_digest, v_set.fact_count,
    coalesce((
      select pg_catalog.jsonb_agg(fact.fact order by fact.ordinal)
      from ledger.reconstruction_economic_facts fact
      where fact.assessment_id = p_assessment_id
    ), '[]'::jsonb);
end;
$function$;

create or replace function ledger.get_reconstruction_assessment_with_economic_facts_v1(
  p_company_id uuid,
  p_income_year integer,
  p_verified_subject text
)
returns table (
  assessment_id uuid,
  company_id uuid,
  income_year integer,
  as_of date,
  state text,
  gap_codes text[],
  evidence_digest text,
  ledger_state_digest text,
  economic_facts_digest text,
  economic_fact_count integer,
  recorded_at timestamptz,
  replayed boolean
)
language sql
stable
security definer
set search_path = ''
as $function$
  select assessment.assessment_id, assessment.company_id,
    assessment.income_year, assessment.as_of, assessment.state,
    assessment.gap_codes, assessment.evidence_digest,
    assessment.ledger_state_digest, fact_set.facts_digest,
    fact_set.fact_count, assessment.recorded_at, assessment.replayed
  from ledger.get_reconstruction_assessment(
    p_company_id, p_income_year, p_verified_subject
  ) assessment
  left join ledger.reconstruction_economic_fact_sets fact_set
    on fact_set.assessment_id = assessment.assessment_id;
$function$;

revoke all on ledger.reconstruction_economic_fact_sets,
  ledger.reconstruction_economic_facts from public, anon, authenticated;
grant select, insert on ledger.reconstruction_economic_fact_sets,
  ledger.reconstruction_economic_facts to ledger_store_owner;

revoke all on function ledger.record_reconstruction_assessment(
  text, uuid, integer, date, jsonb, text, text[], text, text
) from public, anon, authenticated, ledger_executor;
revoke all on function ledger.record_reconstruction_assessment(
  text, uuid, integer, date, jsonb, uuid[], text, text[], text, text
) from public, anon, authenticated;
revoke all on function ledger.get_reconstruction_economic_facts_v1(uuid, text)
  from public, anon, authenticated;
revoke all on function ledger.get_reconstruction_assessment_with_economic_facts_v1(
  uuid, integer, text
) from public, anon, authenticated;
revoke all on function ledger.get_company_year_economic_fact_candidates_v1(
  uuid, integer, date, text
) from public, anon, authenticated;
revoke all on function ledger.company_year_economic_facts_v1(uuid, integer, uuid[])
  from public, anon, authenticated;
grant execute on function ledger.record_reconstruction_assessment(
  text, uuid, integer, date, jsonb, uuid[], text, text[], text, text
) to ledger_executor;
grant execute on function ledger.get_reconstruction_economic_facts_v1(uuid, text)
  to ledger_executor;
grant execute on function ledger.get_reconstruction_assessment_with_economic_facts_v1(
  uuid, integer, text
) to ledger_executor;
grant execute on function ledger.get_company_year_economic_fact_candidates_v1(
  uuid, integer, date, text
) to ledger_executor;

alter table ledger.reconstruction_economic_fact_sets owner to ledger_store_owner;
alter table ledger.reconstruction_economic_facts owner to ledger_store_owner;
alter function ledger.company_year_economic_facts_v1(uuid, integer, uuid[])
  owner to ledger_store_owner;
alter function ledger.get_company_year_economic_fact_candidates_v1(
  uuid, integer, date, text
) owner to ledger_store_owner;
alter function ledger.record_reconstruction_assessment(
  text, uuid, integer, date, jsonb, uuid[], text, text[], text, text
) owner to ledger_store_owner;
alter function ledger.get_reconstruction_economic_facts_v1(uuid, text)
  owner to ledger_store_owner;
alter function ledger.get_reconstruction_assessment_with_economic_facts_v1(
  uuid, integer, text
) owner to ledger_store_owner;

drop trigger if exists reconstruction_economic_fact_sets_immutable
  on ledger.reconstruction_economic_fact_sets;
create trigger reconstruction_economic_fact_sets_immutable
before update or delete on ledger.reconstruction_economic_fact_sets
for each row execute function backend_system.prevent_ledger_technical_mutation();

drop trigger if exists reconstruction_economic_facts_immutable
  on ledger.reconstruction_economic_facts;
create trigger reconstruction_economic_facts_immutable
before update or delete on ledger.reconstruction_economic_facts
for each row execute function backend_system.prevent_ledger_technical_mutation();

do $ledger_economic_facts_migration_authority_revoke$
begin
  execute pg_catalog.format('revoke create on schema ledger from %I', current_user);
  revoke create on schema ledger from ledger_store_owner;
  execute pg_catalog.format('revoke ledger_store_owner from %I', current_user);
end
$ledger_economic_facts_migration_authority_revoke$;

commit;
