-- Issue #188: every downstream close output must declare the exact immutable
-- economic-fact set accepted by the reconstruction it reports from. The source
-- record ID, revision, and result hash remain source-owner attestations; this
-- receiver does not claim to prove the source owner's derivation.

begin;

do $ledger_close_output_facts_migration_authority$
begin
  execute pg_catalog.format('grant ledger_store_owner to %I', current_user);
  execute pg_catalog.format('grant create on schema ledger to %I', current_user);
  grant create on schema ledger to ledger_store_owner;
end
$ledger_close_output_facts_migration_authority$;

alter table ledger.company_year_close_reporting_outputs
  add column if not exists economic_facts_digest text;
alter table ledger.company_year_close_reporting_outputs
  drop constraint if exists ledger_close_output_economic_facts_digest_valid;
alter table ledger.company_year_close_reporting_outputs
  add constraint ledger_close_output_economic_facts_digest_valid check (
    economic_facts_digest is null
    or economic_facts_digest ~ '^[0-9a-f]{64}$'
  );

create or replace function ledger.bind_company_year_close_output_economic_facts_v1()
returns trigger
language plpgsql
security definer
set search_path = ''
as $function$
begin
  select fact_set.facts_digest into new.economic_facts_digest
  from ledger.company_year_close_assessments assessment
  join ledger.reconstruction_economic_fact_sets fact_set
    on fact_set.assessment_id = assessment.reconstruction_assessment_id
    and fact_set.company_id = assessment.company_id
    and fact_set.income_year = assessment.income_year
  where assessment.id = new.assessment_id
    and assessment.company_id = new.company_id
    and assessment.income_year = new.income_year;
  if not found then
    raise exception 'ledger_company_year_close_reconstruction_stale';
  end if;
  return new;
end;
$function$;

drop trigger if exists ledger_company_year_close_output_bind_economic_facts
  on ledger.company_year_close_reporting_outputs;
create trigger ledger_company_year_close_output_bind_economic_facts
before insert on ledger.company_year_close_reporting_outputs
for each row execute function
  ledger.bind_company_year_close_output_economic_facts_v1();

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
        where reconstruction.id = assessment.reconstruction_assessment_id
          and reconstruction.ledger_state_digest = assessment.ledger_state_digest
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

do $ledger_close_output_facts_interface$
begin
  if pg_catalog.to_regprocedure(
    'ledger.close_company_year_without_economic_facts_v1(text,uuid,integer,date,text,uuid,text,jsonb,text,text[],text,text)'
  ) is null then
    alter function ledger.close_company_year_v1(
      text, uuid, integer, date, text, uuid, text, jsonb,
      text, text[], text, text
    ) rename to close_company_year_without_economic_facts_v1;
  elsif pg_catalog.strpos(
    pg_catalog.pg_get_functiondef(pg_catalog.to_regprocedure(
      'ledger.close_company_year_v1(text,uuid,integer,date,text,uuid,text,jsonb,text,text[],text,text)'
    )),
    'close_company_year_without_economic_facts_v1'
  ) = 0 then
    -- A recutover migration refreshed the public raw recorder. Replace the
    -- stale private delegate with that exact current implementation before
    -- reinstalling the economic-fact wrapper below.
    drop function ledger.close_company_year_without_economic_facts_v1(
      text, uuid, integer, date, text, uuid, text, jsonb,
      text, text[], text, text
    );
    alter function ledger.close_company_year_v1(
      text, uuid, integer, date, text, uuid, text, jsonb,
      text, text[], text, text
    ) rename to close_company_year_without_economic_facts_v1;
  end if;
end
$ledger_close_output_facts_interface$;

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
  v_economic_facts_digest text;
begin
  -- The predecessor authenticates, validates, and holds the company-year lock.
  -- Any binding failure below rolls its assessment, lock, outputs, and receipt
  -- back in this same transaction.
  select legacy.* into strict v_legacy
  from ledger.close_company_year_without_economic_facts_v1(
    p_idempotency_key, p_company_id, p_income_year, p_period_end, p_reason,
    p_reconstruction_assessment_id, p_reconstruction_digest, p_evidence,
    p_derived_state, p_gap_codes, p_correlation_id, p_verified_subject
  ) legacy;

  select fact_set.facts_digest into v_economic_facts_digest
  from ledger.reconstruction_economic_fact_sets fact_set
  where fact_set.assessment_id = p_reconstruction_assessment_id
    and fact_set.company_id = p_company_id
    and fact_set.income_year = p_income_year;
  if not found or exists (
    select 1
    from pg_catalog.jsonb_array_elements(p_evidence) item
    cross join lateral pg_catalog.jsonb_array_elements(item -> 'outputs') output
    where output ->> 'economicFactsDigest'
      is distinct from v_economic_facts_digest
  ) then
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

revoke all on function ledger.close_company_year_without_economic_facts_v1(
  text, uuid, integer, date, text, uuid, text, jsonb,
  text, text[], text, text
) from public, anon, authenticated, service_role, ledger_executor,
  ledger_workflow_executor, talli_ledger_backend;
revoke all on function ledger.close_company_year_v1(
  text, uuid, integer, date, text, uuid, text, jsonb,
  text, text[], text, text
) from public, anon, authenticated, service_role,
  ledger_workflow_executor, talli_ledger_backend;
revoke all on function ledger.bind_company_year_close_output_economic_facts_v1()
  from public, anon, authenticated, service_role, ledger_executor,
  ledger_workflow_executor, talli_ledger_backend;
grant execute on function ledger.close_company_year_v1(
  text, uuid, integer, date, text, uuid, text, jsonb,
  text, text[], text, text
) to ledger_executor;

alter function ledger.bind_company_year_close_output_economic_facts_v1()
  owner to ledger_store_owner;
alter function ledger.company_year_close_is_current_v1(uuid, uuid, integer)
  owner to ledger_store_owner;
alter function ledger.close_company_year_without_economic_facts_v1(
  text, uuid, integer, date, text, uuid, text, jsonb,
  text, text[], text, text
) owner to ledger_store_owner;
alter function ledger.close_company_year_v1(
  text, uuid, integer, date, text, uuid, text, jsonb,
  text, text[], text, text
) owner to ledger_store_owner;

do $ledger_close_output_facts_migration_authority_revoke$
begin
  execute pg_catalog.format('revoke create on schema ledger from %I', current_user);
  revoke create on schema ledger from ledger_store_owner;
  execute pg_catalog.format('revoke ledger_store_owner from %I', current_user);
end
$ledger_close_output_facts_migration_authority_revoke$;

commit;
