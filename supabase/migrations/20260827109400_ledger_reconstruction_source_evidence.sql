-- Issue #188: bind every reconstruction assessment to 13 immutable,
-- revisioned source-owner attestations covering January 1 through the cutoff.

begin;

do $ledger_source_evidence_migration_authority$
begin
  execute pg_catalog.format('grant ledger_store_owner to %I', current_user);
  execute pg_catalog.format('grant create on schema ledger to %I', current_user);
  grant create on schema ledger to ledger_store_owner;
end
$ledger_source_evidence_migration_authority$;

create table if not exists ledger.reconstruction_source_evidence_sets (
  assessment_id uuid primary key,
  company_id uuid not null,
  income_year integer not null check (income_year between 2000 and 2100),
  evidence_count integer not null check (evidence_count = 13),
  evidence_digest text not null check (evidence_digest ~ '^[0-9a-f]{64}$'),
  unique (assessment_id, company_id, income_year),
  foreign key (assessment_id, company_id, income_year)
    references ledger.reconstruction_assessments(id, company_id, income_year)
    on delete restrict
);

create table if not exists ledger.reconstruction_source_evidence_bindings (
  assessment_id uuid not null,
  company_id uuid not null,
  income_year integer not null,
  ordinal integer not null check (ordinal between 1 and 13),
  source_revision integer not null check (source_revision >= 1),
  primary key (assessment_id, ordinal),
  foreign key (assessment_id, company_id, income_year)
    references ledger.reconstruction_source_evidence_sets(
      assessment_id, company_id, income_year
    ) on delete restrict,
  foreign key (assessment_id, ordinal)
    references ledger.reconstruction_evidence(assessment_id, ordinal)
    on delete restrict
);

alter table ledger.reconstruction_source_evidence_sets enable row level security;
alter table ledger.reconstruction_source_evidence_sets force row level security;
alter table ledger.reconstruction_source_evidence_bindings enable row level security;
alter table ledger.reconstruction_source_evidence_bindings force row level security;

drop policy if exists "ledger store reads reconstruction source evidence sets"
  on ledger.reconstruction_source_evidence_sets;
create policy "ledger store reads reconstruction source evidence sets"
on ledger.reconstruction_source_evidence_sets for select to ledger_store_owner
using (public.company_access_is_accepted_member_v1(company_id));
drop policy if exists "ledger store records reconstruction source evidence sets"
  on ledger.reconstruction_source_evidence_sets;
create policy "ledger store records reconstruction source evidence sets"
on ledger.reconstruction_source_evidence_sets for insert to ledger_store_owner
with check (public.company_access_is_accepted_owner_v1(company_id));

drop policy if exists "ledger store reads reconstruction source evidence bindings"
  on ledger.reconstruction_source_evidence_bindings;
create policy "ledger store reads reconstruction source evidence bindings"
on ledger.reconstruction_source_evidence_bindings for select to ledger_store_owner
using (public.company_access_is_accepted_member_v1(company_id));
drop policy if exists "ledger store records reconstruction source evidence bindings"
  on ledger.reconstruction_source_evidence_bindings;
create policy "ledger store records reconstruction source evidence bindings"
on ledger.reconstruction_source_evidence_bindings for insert to ledger_store_owner
with check (public.company_access_is_accepted_owner_v1(company_id));

do $ledger_source_evidence_interface$
begin
  if pg_catalog.to_regprocedure(
    'ledger.record_reconstruction_assessment_without_source_evidence_v1(text,uuid,integer,date,jsonb,uuid[],text,text[],text,text)'
  ) is null then
    alter function ledger.record_reconstruction_assessment(
      text, uuid, integer, date, jsonb, uuid[], text, text[], text, text
    ) rename to record_reconstruction_assessment_without_source_evidence_v1;
  elsif pg_catalog.strpos(
    pg_catalog.pg_get_functiondef(pg_catalog.to_regprocedure(
      'ledger.record_reconstruction_assessment(text,uuid,integer,date,jsonb,uuid[],text,text[],text,text)'
    )),
    'record_reconstruction_assessment_without_source_evidence_v1'
  ) = 0 then
    -- Recutover refreshed the economic-fact recorder. Promote that exact
    -- implementation to the private delegate before reinstalling this wrapper.
    drop function ledger.record_reconstruction_assessment_without_source_evidence_v1(
      text, uuid, integer, date, jsonb, uuid[], text, text[], text, text
    );
    alter function ledger.record_reconstruction_assessment(
      text, uuid, integer, date, jsonb, uuid[], text, text[], text, text
    ) rename to record_reconstruction_assessment_without_source_evidence_v1;
  end if;
end
$ledger_source_evidence_interface$;

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
  v_source_set ledger.reconstruction_source_evidence_sets%rowtype;
begin
  if p_company_id is null
    or p_income_year not between 2000 and 2100
    or p_as_of is null
    or extract(year from p_as_of)::integer <> p_income_year
    or pg_catalog.jsonb_typeof(p_evidence) is distinct from 'array'
    or pg_catalog.jsonb_array_length(p_evidence) <> 13
    or exists (
      select 1
      from pg_catalog.jsonb_array_elements(p_evidence) item
      where case
          when coalesce(item ->> 'sourceRevision', '') ~ '^[1-9][0-9]{0,9}$'
          then (item ->> 'sourceRevision')::numeric <= 2147483647
          else false
        end is not true
        or coalesce(item ->> 'coverageFrom', '') = ''
        or coalesce(item ->> 'coverageThrough', '') = ''
        or (item ->> 'coverageFrom')::date
          <> pg_catalog.make_date(p_income_year, 1, 1)
        or (item ->> 'coverageThrough')::date <> p_as_of
    )
  then
    raise exception 'ledger_reconstruction_source_evidence_invalid';
  end if;

  select legacy.* into strict v_legacy
  from ledger.record_reconstruction_assessment_without_source_evidence_v1(
    p_idempotency_key, p_company_id, p_income_year, p_as_of, p_evidence,
    p_economic_fact_entry_ids, p_state, p_gap_codes, p_correlation_id,
    p_verified_subject
  ) legacy;

  if v_legacy.replayed then
    select source_set.* into v_source_set
    from ledger.reconstruction_source_evidence_sets source_set
    where source_set.assessment_id = v_legacy.assessment_id;
    if not found
      or v_source_set.evidence_count <> 13
      or v_source_set.evidence_digest is distinct from v_legacy.evidence_digest
      or exists (
        select 1
        from pg_catalog.jsonb_array_elements(p_evidence)
          with ordinality source(item, ordinal)
        where not exists (
          select 1
          from ledger.reconstruction_source_evidence_bindings binding
          where binding.assessment_id = v_legacy.assessment_id
            and binding.ordinal = source.ordinal
            and binding.source_revision = (source.item ->> 'sourceRevision')::integer
        )
      )
    then
      raise exception 'ledger_reconstruction_source_evidence_invalid';
    end if;
  else
    insert into ledger.reconstruction_source_evidence_sets (
      assessment_id, company_id, income_year, evidence_count, evidence_digest
    ) values (
      v_legacy.assessment_id, p_company_id, p_income_year, 13,
      v_legacy.evidence_digest
    );
    insert into ledger.reconstruction_source_evidence_bindings (
      assessment_id, company_id, income_year, ordinal, source_revision
    )
    select v_legacy.assessment_id, p_company_id, p_income_year,
      source.ordinal::integer, (source.item ->> 'sourceRevision')::integer
    from pg_catalog.jsonb_array_elements(p_evidence)
      with ordinality source(item, ordinal);
  end if;

  return query select v_legacy.assessment_id, v_legacy.company_id,
    v_legacy.income_year, v_legacy.as_of, v_legacy.state, v_legacy.gap_codes,
    v_legacy.evidence_digest, v_legacy.ledger_state_digest,
    v_legacy.economic_facts_digest, v_legacy.economic_fact_count,
    v_legacy.recorded_at, v_legacy.replayed;
end;
$function$;

create or replace function ledger.get_reconstruction_assessment_with_source_evidence_v1(
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
  source_evidence_digest text,
  source_evidence_count integer,
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
    assessment.ledger_state_digest, source_set.evidence_digest,
    source_set.evidence_count, assessment.economic_facts_digest,
    assessment.economic_fact_count, assessment.recorded_at,
    assessment.replayed
  from ledger.get_reconstruction_assessment_with_economic_facts_v1(
    p_company_id, p_income_year, p_verified_subject
  ) assessment
  left join ledger.reconstruction_source_evidence_sets source_set
    on source_set.assessment_id = assessment.assessment_id;
$function$;

create or replace function ledger.company_year_close_is_current_v1(
  p_assessment_id uuid,
  p_company_id uuid,
  p_income_year integer
)
returns boolean
language sql
stable
security definer
set search_path = ''
as $function$
  select exists (
    select 1
    from ledger.company_year_close_assessments assessment
    where assessment.id = p_assessment_id
      and assessment.company_id = p_company_id
      and assessment.income_year = p_income_year
      and assessment.id = (
        select latest.id
        from ledger.company_year_close_assessments latest
        where latest.company_id = p_company_id
          and latest.income_year = p_income_year
        order by latest.recorded_at desc, latest.id desc
        limit 1
      )
      and assessment.reconstruction_assessment_id = (
        select reconstruction.id
        from ledger.reconstruction_assessments reconstruction
        where reconstruction.company_id = p_company_id
          and reconstruction.income_year = p_income_year
        order by reconstruction.recorded_at desc, reconstruction.id desc
        limit 1
      )
      and assessment.ledger_state_digest =
        ledger.company_year_ledger_state_digest_v1(p_company_id, p_income_year)
      and exists (
        select 1
        from ledger.reconstruction_assessments reconstruction
        join ledger.reconstruction_economic_fact_sets fact_set
          on fact_set.assessment_id = reconstruction.id
          and fact_set.company_id = reconstruction.company_id
          and fact_set.income_year = reconstruction.income_year
        join ledger.reconstruction_source_evidence_sets source_set
          on source_set.assessment_id = reconstruction.id
          and source_set.company_id = reconstruction.company_id
          and source_set.income_year = reconstruction.income_year
        where reconstruction.id = assessment.reconstruction_assessment_id
          and reconstruction.ledger_state_digest = assessment.ledger_state_digest
          and source_set.evidence_count = 13
          and source_set.evidence_digest = reconstruction.evidence_digest
          and (
            select pg_catalog.count(*)
            from ledger.reconstruction_source_evidence_bindings binding
            where binding.assessment_id = source_set.assessment_id
          ) = 13
          and not exists (
            select 1
            from ledger.company_year_close_reporting_outputs output
            where output.assessment_id = assessment.id
              and output.economic_facts_digest is distinct from
                fact_set.facts_digest
          )
      )
      and not exists (
        select 1 from ledger.company_year_close_evidence evidence
        where evidence.assessment_id = assessment.id
          and evidence.ledger_state_digest <> assessment.ledger_state_digest
      )
      and not exists (
        select 1 from ledger.company_year_close_reporting_outputs output
        where output.assessment_id = assessment.id
          and output.ledger_state_digest <> assessment.ledger_state_digest
      )
  );
$function$;

do $ledger_close_source_evidence_interface$
begin
  if pg_catalog.to_regprocedure(
    'ledger.close_company_year_without_source_evidence_v1(text,uuid,integer,date,text,uuid,text,jsonb,text,text[],text,text)'
  ) is null then
    alter function ledger.close_company_year_v1(
      text, uuid, integer, date, text, uuid, text, jsonb,
      text, text[], text, text
    ) rename to close_company_year_without_source_evidence_v1;
  elsif pg_catalog.strpos(
    pg_catalog.pg_get_functiondef(pg_catalog.to_regprocedure(
      'ledger.close_company_year_v1(text,uuid,integer,date,text,uuid,text,jsonb,text,text[],text,text)'
    )),
    'close_company_year_without_source_evidence_v1'
  ) = 0 then
    drop function ledger.close_company_year_without_source_evidence_v1(
      text, uuid, integer, date, text, uuid, text, jsonb,
      text, text[], text, text
    );
    alter function ledger.close_company_year_v1(
      text, uuid, integer, date, text, uuid, text, jsonb,
      text, text[], text, text
    ) rename to close_company_year_without_source_evidence_v1;
  end if;
end
$ledger_close_source_evidence_interface$;

create or replace function ledger.close_company_year_v1(
  p_idempotency_key text,
  p_company_id uuid,
  p_income_year integer,
  p_period_end date,
  p_reason text,
  p_reconstruction_assessment_id uuid,
  p_reconstruction_digest text,
  p_evidence jsonb,
  p_derived_state text,
  p_gap_codes text[],
  p_correlation_id text,
  p_verified_subject text
)
returns table (
  assessment_id uuid,
  reconstruction_assessment_id uuid,
  close_lock_id uuid,
  company_id uuid,
  income_year integer,
  period_end date,
  state text,
  gap_codes text[],
  evidence_digest text,
  ledger_state_digest text,
  recorded_at timestamptz,
  is_current boolean,
  replayed boolean
)
language plpgsql
security definer
set search_path = ''
as $function$
declare
  v_legacy record;
  v_source_set ledger.reconstruction_source_evidence_sets%rowtype;
begin
  -- Preserve the predecessor's authentication, validation, idempotency, and
  -- company-year lock. A missing source binding rolls every close side effect
  -- back in this same transaction.
  select legacy.* into strict v_legacy
  from ledger.close_company_year_without_source_evidence_v1(
    p_idempotency_key, p_company_id, p_income_year, p_period_end, p_reason,
    p_reconstruction_assessment_id, p_reconstruction_digest, p_evidence,
    p_derived_state, p_gap_codes, p_correlation_id, p_verified_subject
  ) legacy;

  select source_set.* into v_source_set
  from ledger.reconstruction_source_evidence_sets source_set
  where source_set.assessment_id = p_reconstruction_assessment_id
    and source_set.company_id = p_company_id
    and source_set.income_year = p_income_year;
  if not found
    or v_source_set.evidence_count <> 13
    or v_source_set.evidence_digest is distinct from p_reconstruction_digest
    or (
      select pg_catalog.count(*)
      from ledger.reconstruction_source_evidence_bindings binding
      where binding.assessment_id = p_reconstruction_assessment_id
    ) <> 13
  then
    raise exception 'ledger_company_year_close_reconstruction_stale';
  end if;

  return query select v_legacy.assessment_id,
    v_legacy.reconstruction_assessment_id, v_legacy.close_lock_id,
    v_legacy.company_id, v_legacy.income_year, v_legacy.period_end,
    v_legacy.state, v_legacy.gap_codes, v_legacy.evidence_digest,
    v_legacy.ledger_state_digest, v_legacy.recorded_at,
    ledger.company_year_close_is_current_v1(
      v_legacy.assessment_id, v_legacy.company_id, v_legacy.income_year
    ), v_legacy.replayed;
end;
$function$;

revoke all on ledger.reconstruction_source_evidence_sets,
  ledger.reconstruction_source_evidence_bindings
from public, anon, authenticated, service_role, ledger_executor,
  ledger_workflow_executor, talli_ledger_backend;
grant select, insert on ledger.reconstruction_source_evidence_sets,
  ledger.reconstruction_source_evidence_bindings to ledger_store_owner;

revoke all on function ledger.record_reconstruction_assessment_without_source_evidence_v1(
  text, uuid, integer, date, jsonb, uuid[], text, text[], text, text
) from public, anon, authenticated, service_role, ledger_executor,
  ledger_workflow_executor, talli_ledger_backend;
revoke all on function ledger.record_reconstruction_assessment(
  text, uuid, integer, date, jsonb, uuid[], text, text[], text, text
) from public, anon, authenticated, service_role,
  ledger_workflow_executor, talli_ledger_backend;
revoke all on function ledger.get_reconstruction_assessment_with_economic_facts_v1(
  uuid, integer, text
) from public, anon, authenticated, service_role, ledger_executor,
  ledger_workflow_executor, talli_ledger_backend;
revoke all on function ledger.get_reconstruction_assessment_with_source_evidence_v1(
  uuid, integer, text
) from public, anon, authenticated, service_role,
  ledger_workflow_executor, talli_ledger_backend;
revoke all on function ledger.close_company_year_without_source_evidence_v1(
  text, uuid, integer, date, text, uuid, text, jsonb,
  text, text[], text, text
) from public, anon, authenticated, service_role, ledger_executor,
  ledger_workflow_executor, talli_ledger_backend;
revoke all on function ledger.close_company_year_v1(
  text, uuid, integer, date, text, uuid, text, jsonb,
  text, text[], text, text
) from public, anon, authenticated, service_role,
  ledger_workflow_executor, talli_ledger_backend;
grant execute on function ledger.record_reconstruction_assessment(
  text, uuid, integer, date, jsonb, uuid[], text, text[], text, text
) to ledger_executor;
grant execute on function ledger.get_reconstruction_assessment_with_source_evidence_v1(
  uuid, integer, text
) to ledger_executor;
grant execute on function ledger.close_company_year_v1(
  text, uuid, integer, date, text, uuid, text, jsonb,
  text, text[], text, text
) to ledger_executor;

alter table ledger.reconstruction_source_evidence_sets owner to ledger_store_owner;
alter table ledger.reconstruction_source_evidence_bindings owner to ledger_store_owner;
alter function ledger.record_reconstruction_assessment_without_source_evidence_v1(
  text, uuid, integer, date, jsonb, uuid[], text, text[], text, text
) owner to ledger_store_owner;
alter function ledger.record_reconstruction_assessment(
  text, uuid, integer, date, jsonb, uuid[], text, text[], text, text
) owner to ledger_store_owner;
alter function ledger.get_reconstruction_assessment_with_source_evidence_v1(
  uuid, integer, text
) owner to ledger_store_owner;
alter function ledger.company_year_close_is_current_v1(uuid, uuid, integer)
  owner to ledger_store_owner;
alter function ledger.close_company_year_without_source_evidence_v1(
  text, uuid, integer, date, text, uuid, text, jsonb,
  text, text[], text, text
) owner to ledger_store_owner;
alter function ledger.close_company_year_v1(
  text, uuid, integer, date, text, uuid, text, jsonb,
  text, text[], text, text
) owner to ledger_store_owner;

drop trigger if exists reconstruction_source_evidence_sets_immutable
  on ledger.reconstruction_source_evidence_sets;
create trigger reconstruction_source_evidence_sets_immutable
before update or delete on ledger.reconstruction_source_evidence_sets
for each row execute function backend_system.prevent_ledger_technical_mutation();
drop trigger if exists reconstruction_source_evidence_bindings_immutable
  on ledger.reconstruction_source_evidence_bindings;
create trigger reconstruction_source_evidence_bindings_immutable
before update or delete on ledger.reconstruction_source_evidence_bindings
for each row execute function backend_system.prevent_ledger_technical_mutation();

do $ledger_source_evidence_migration_authority_revoke$
begin
  execute pg_catalog.format('revoke create on schema ledger from %I', current_user);
  revoke create on schema ledger from ledger_store_owner;
  execute pg_catalog.format('revoke ledger_store_owner from %I', current_user);
end
$ledger_source_evidence_migration_authority_revoke$;

commit;
