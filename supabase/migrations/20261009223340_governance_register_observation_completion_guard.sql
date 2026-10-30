-- Final Governance write consumes only RF's public identity/time assertion.
-- No original-byte/economic/digest parity claim, amendment, or withdrawal grant.
begin;
set local lock_timeout='5s';
set local statement_timeout='120s';
set local search_path='';
create temporary table rf193_governance_completion_roles(role_name text,prior jsonb) on commit drop;
do $borrow$
declare role_name text; prior jsonb;
begin
 foreach role_name in array array['shareholder_register_filing_store_owner','corporate_governance_store_owner'] loop
  if not pg_catalog.pg_has_role(current_user,role_name,'SET') then
   select pg_catalog.jsonb_build_object('admin',m.admin_option,'inherit',m.inherit_option,'set',m.set_option)
    into prior from pg_catalog.pg_auth_members m
    where m.roleid=role_name::regrole and m.member=current_user::regrole and m.grantor=m.member;
   insert into pg_temp.rf193_governance_completion_roles values(role_name,prior);
   execute pg_catalog.format('grant %I to %I with set true granted by %I',role_name,current_user,current_user);
  end if;
 end loop;
end; $borrow$;
set local role shareholder_register_filing_store_owner;
grant usage on schema shareholder_register_filing to corporate_governance_store_owner;
grant execute on function shareholder_register_filing.assert_current_register_observation_v2(uuid,uuid,integer,integer,text,timestamptz,text) to corporate_governance_store_owner;
reset role;
set local role corporate_governance_store_owner;
-- Freeze the exact predecessor from 20260904220000 plus the company-first
-- wrapper from 20260924080355. MD5 is a drift sentinel, not a facts commitment.
do $rewrite_prepare$
declare before_row pg_catalog.pg_proc%rowtype; after_row pg_catalog.pg_proc%rowtype;
 definition text; owner_had_execute boolean;
 new_body constant text := $new_body$BEGIN
  -- rf193-company-write-guard-v1
  PERFORM corporate_governance.acquire_company_write_guard_v1((p_request->>'companyId')::uuid,p_verified_subject);

declare
  v_actor_id uuid;
  v_company_id uuid;
  v_income_year integer;
  v_event_id uuid;
  v_existing corporate_governance.supported_events%rowtype;
begin
  begin
    v_company_id := (p_request ->> 'companyId')::uuid;
    v_income_year := (p_request ->> 'incomeYear')::integer;
    v_event_id := (p_request ->> 'eventId')::uuid;
  exception when others then
    raise exception 'corporate_governance_invalid_input';
  end;
  v_actor_id := corporate_governance.assert_owner_v1(
    v_company_id, v_income_year, p_verified_subject, true
  );
  perform pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended(
    'talli:corporate-governance:supported-event:' || v_event_id::text, 0
  ));
  select event.* into v_existing
  from corporate_governance.supported_events event
  where event.event_id = v_event_id
    or (event.created_by = v_actor_id
      and event.company_id = v_company_id
      and event.idempotency_key = p_request ->> 'idempotencyKey')
  order by (event.event_id = v_event_id) desc
  limit 1;
  if found then
    -- rf193-governance-replay-null-safe-v1
    if v_existing.event_id is distinct from v_event_id
      or v_existing.company_id is distinct from v_company_id
      or v_existing.income_year is distinct from v_income_year
      or v_existing.event_reference is distinct from (p_request ->> 'eventReference')::uuid
      or v_existing.event_date is distinct from (p_request ->> 'eventDate')::date
      or v_existing.event_kind is distinct from p_request ->> 'eventKind'
      or v_existing.phase is distinct from p_request ->> 'phase'
      or v_existing.facts_sha256 is distinct from p_request ->> 'factsSha256'
    then
      raise exception 'corporate_governance_idempotency_conflict';
    end if;
    return pg_catalog.jsonb_build_object(
      'event', corporate_governance.supported_event_result_v1(
        v_existing.event_id, true
      ),
      'replay', corporate_governance.supported_event_result_v1(
        v_existing.event_id, true
      )
    );
  end if;
  if coalesce(p_request ->> 'idempotencyKey', '')
      !~ '^[A-Za-z0-9._:-]{16,255}$'
    or pg_catalog.btrim(coalesce(p_request ->> 'correlationId', '')) = ''
    or (p_request ->> 'eventReference') !~ '^[0-9a-fA-F-]{36}$'
    or (p_request ->> 'factsSha256') !~ '^[0-9a-f]{64}$'
    or p_request ->> 'policyVersion'
      <> 'corporate-governance-supported-events-2026.1'
    or pg_catalog.jsonb_typeof(p_request -> 'canonicalFacts') <> 'object'
    or pg_catalog.jsonb_typeof(p_request -> 'documentFacts') <> 'array'
    or pg_catalog.jsonb_array_length(p_request -> 'documentFacts')
      not between 1 and 12
    or extract(year from (p_request ->> 'eventDate')::date)::integer
      <> v_income_year
  then
    raise exception 'corporate_governance_invalid_input';
  end if;
  return pg_catalog.jsonb_build_object(
    'event', p_request,
    'replay', null
  );
exception when invalid_text_representation or numeric_value_out_of_range
  or datetime_field_overflow then
  raise exception 'corporate_governance_invalid_input';
end;
END;
$new_body$;
begin
 select * into before_row from pg_catalog.pg_proc
  where oid=pg_catalog.to_regprocedure('corporate_governance.prepare_supported_event_v1(jsonb,text)');
 if before_row.oid is null or before_row.proowner<>current_user::regrole
  or not before_row.prosecdef or before_row.provolatile<>'v'
  or before_row.prolang<>(select oid from pg_catalog.pg_language where lanname='plpgsql')
  or before_row.proconfig is distinct from array['search_path=""']::text[]
 then raise exception 'corporate_governance_completion_definition_drift'; end if;
 if before_row.prosrc=new_body then return; end if;
 if pg_catalog.md5(before_row.prosrc)<>'483ab0d59913625ee33f002aff47abb9'
 then raise exception 'corporate_governance_completion_definition_drift'; end if;
 definition:=pg_catalog.pg_get_functiondef(before_row.oid);
 if pg_catalog.length(definition)-pg_catalog.length(pg_catalog.replace(definition,before_row.prosrc,''))<>pg_catalog.length(before_row.prosrc)
 then raise exception 'corporate_governance_completion_definition_drift'; end if;
 owner_had_execute:=pg_catalog.has_function_privilege(current_user,before_row.oid,'EXECUTE');
 if not owner_had_execute then execute pg_catalog.format('grant execute on function %s to %I',before_row.oid::regprocedure,current_user); end if;
 execute pg_catalog.replace(definition,before_row.prosrc,new_body);
 if not owner_had_execute then execute pg_catalog.format('revoke execute on function %s from %I',before_row.oid::regprocedure,current_user); end if;
 select * into after_row from pg_catalog.pg_proc where oid=before_row.oid;
 if (pg_catalog.to_jsonb(after_row)-'prosrc') is distinct from (pg_catalog.to_jsonb(before_row)-'prosrc')
 then raise exception 'corporate_governance_completion_definition_drift'; end if;
end; $rewrite_prepare$;
-- Freeze the exact predecessor from 20260904220000 plus the company-first
-- wrapper from 20260924080355. MD5 is a drift sentinel, not a facts commitment.
do $rewrite_complete$
declare before_row pg_catalog.pg_proc%rowtype; after_row pg_catalog.pg_proc%rowtype;
 definition text; owner_had_execute boolean;
 new_body constant text := $new_body$BEGIN
  -- rf193-company-write-guard-v1
  PERFORM corporate_governance.acquire_company_write_guard_v1((p_request->>'companyId')::uuid,p_verified_subject);

declare
  v_actor_id uuid;
  v_recorded_at timestamptz := statement_timestamp();
  v_field text;
  v_fact jsonb;
  v_revision integer;
  v_company_id uuid := (p_request ->> 'companyId')::uuid;
  v_income_year integer := (p_request ->> 'incomeYear')::integer;
  v_event_id uuid := (p_request ->> 'eventId')::uuid;
  v_existing corporate_governance.supported_events%rowtype;
begin
  v_actor_id := corporate_governance.assert_owner_v1(
    v_company_id, v_income_year, p_verified_subject, true
  );
  perform pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended(
    'talli:corporate-governance:supported-event:' || v_event_id::text, 0
  ));
  select event.* into v_existing
  from corporate_governance.supported_events event
  where event.event_id = v_event_id
  for update;
  if found then
    if v_existing.company_id is distinct from v_company_id
      or v_existing.income_year is distinct from v_income_year
      or v_existing.facts_sha256 is distinct from (p_request ->> 'factsSha256')
      or v_existing.accounting_entry_id
        is distinct from (p_request ->> 'accountingEntryId')::uuid
    then
      raise exception 'corporate_governance_idempotency_conflict';
    end if;
    return corporate_governance.supported_event_result_v1(v_event_id, true);
  end if;
  -- rf193-governance-register-completion-v1
  -- Identity agreement precedes the event discriminator. This is not canonical
  -- hash/economics/original-byte verification: that remains the owner workflow.
  if pg_catalog.jsonb_typeof(p_request) is distinct from 'object'
    or pg_catalog.jsonb_typeof(p_request->'canonicalFacts') is distinct from 'object'
  then raise exception 'corporate_governance_invalid_input'; end if;
  foreach v_field in array array['companyId','eventId','eventReference','eventDate','eventKind','phase','policyVersion'] loop
    if pg_catalog.jsonb_typeof(p_request->v_field) is distinct from 'string'
      or (p_request->v_field) is distinct from (p_request->'canonicalFacts'->v_field)
    then raise exception 'corporate_governance_invalid_input'; end if;
  end loop;
  if pg_catalog.jsonb_typeof(p_request->'incomeYear') is distinct from 'number'
    or (p_request->>'incomeYear') !~ '^[0-9]{4}$'
    or (p_request->'incomeYear') is distinct from (p_request->'canonicalFacts'->'incomeYear')
  then raise exception 'corporate_governance_invalid_input'; end if;
  if (p_request->>'eventKind'='cash_capital_increase' and p_request->>'phase'='registered')
    or (p_request->>'eventKind'='loss_coverage_capital_reduction'
      and p_request->>'phase' in ('registered','first_recognized_after_registration')) then
    v_fact:=p_request->'canonicalFacts'->'shareholderRegisterFact';
    if pg_catalog.jsonb_typeof(v_fact) is distinct from 'object'
      or (v_fact-array['record_id','revision','fact_sha256']) <> '{}'::jsonb
      or pg_catalog.jsonb_typeof(v_fact->'record_id') is distinct from 'object'
      or ((v_fact->'record_id')-'value') <> '{}'::jsonb
      or pg_catalog.jsonb_typeof(v_fact->'record_id'->'value') is distinct from 'string'
      or coalesce(v_fact->'record_id'->>'value','') !~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
      or pg_catalog.jsonb_typeof(v_fact->'revision') is distinct from 'number'
      or coalesce(v_fact->>'revision','') !~ '^[1-9][0-9]{0,9}$'
      or pg_catalog.jsonb_typeof(v_fact->'fact_sha256') is distinct from 'string'
      or coalesce(v_fact->>'fact_sha256','') !~ '^[0-9a-f]{64}$'
      or pg_catalog.jsonb_typeof(p_request->'shareholderRegisterSourceId') is distinct from 'string'
      or (p_request->'shareholderRegisterSourceId') is distinct from (v_fact->'record_id'->'value')
    then raise exception 'corporate_governance_invalid_input'; end if;
    v_revision:=(v_fact->>'revision')::integer;
    -- Conservative statement-start cutoff survives waiting for the company
    -- lock; use this same instant for the immutable event's recordedAt.
    perform shareholder_register_filing.assert_current_register_observation_v2(
      (v_fact->'record_id'->>'value')::uuid,v_company_id,v_income_year,
      v_revision,v_fact->>'fact_sha256',v_recorded_at,p_verified_subject);
  end if;
  insert into corporate_governance.supported_events (
    event_id, event_reference, company_id, income_year, event_date,
    event_kind, phase, policy_version, canonical_facts, facts_sha256,
    document_facts, bank_transaction_id, shareholder_register_source_id,
    tax_calculation_source_id, accounting_entry_id, correction_of_event_id,
    idempotency_key, correlation_id, created_by, created_at
  ) values (
    v_event_id,
    (p_request ->> 'eventReference')::uuid,
    v_company_id,
    v_income_year,
    (p_request ->> 'eventDate')::date,
    p_request ->> 'eventKind',
    p_request ->> 'phase',
    p_request ->> 'policyVersion',
    p_request -> 'canonicalFacts',
    p_request ->> 'factsSha256',
    p_request -> 'documentFacts',
    nullif(p_request ->> 'bankTransactionId', '')::uuid,
    nullif(p_request ->> 'shareholderRegisterSourceId', '')::uuid,
    nullif(p_request ->> 'taxCalculationSourceId', '')::uuid,
    (p_request ->> 'accountingEntryId')::uuid,
    nullif(p_request ->> 'correctionOfEventId', '')::uuid,
    p_request ->> 'idempotencyKey',
    p_request ->> 'correlationId',
    v_actor_id, v_recorded_at
  );
  return corporate_governance.supported_event_result_v1(v_event_id, false);
exception when unique_violation then
  raise exception 'corporate_governance_idempotency_conflict';
when invalid_text_representation or numeric_value_out_of_range
  or datetime_field_overflow then
  raise exception 'corporate_governance_invalid_input';
end;
END;
$new_body$;
begin
 select * into before_row from pg_catalog.pg_proc
  where oid=pg_catalog.to_regprocedure('corporate_governance.complete_supported_event_v1(jsonb,text)');
 if before_row.oid is null or before_row.proowner<>current_user::regrole
  or not before_row.prosecdef or before_row.provolatile<>'v'
  or before_row.prolang<>(select oid from pg_catalog.pg_language where lanname='plpgsql')
  or before_row.proconfig is distinct from array['search_path=""']::text[]
 then raise exception 'corporate_governance_completion_definition_drift'; end if;
 if before_row.prosrc=new_body then return; end if;
 if pg_catalog.md5(before_row.prosrc)<>'1d053d66724a6f04c51822c125a2b1f9'
 then raise exception 'corporate_governance_completion_definition_drift'; end if;
 definition:=pg_catalog.pg_get_functiondef(before_row.oid);
 if pg_catalog.length(definition)-pg_catalog.length(pg_catalog.replace(definition,before_row.prosrc,''))<>pg_catalog.length(before_row.prosrc)
 then raise exception 'corporate_governance_completion_definition_drift'; end if;
 owner_had_execute:=pg_catalog.has_function_privilege(current_user,before_row.oid,'EXECUTE');
 if not owner_had_execute then execute pg_catalog.format('grant execute on function %s to %I',before_row.oid::regprocedure,current_user); end if;
 execute pg_catalog.replace(definition,before_row.prosrc,new_body);
 if not owner_had_execute then execute pg_catalog.format('revoke execute on function %s from %I',before_row.oid::regprocedure,current_user); end if;
 select * into after_row from pg_catalog.pg_proc where oid=before_row.oid;
 if (pg_catalog.to_jsonb(after_row)-'prosrc') is distinct from (pg_catalog.to_jsonb(before_row)-'prosrc')
 then raise exception 'corporate_governance_completion_definition_drift'; end if;
end; $rewrite_complete$;
reset role;
do $restore$
declare r record;
begin
 for r in select * from pg_temp.rf193_governance_completion_roles loop
  execute pg_catalog.format('revoke %I from %I granted by %I',r.role_name,current_user,current_user);
  if r.prior is not null then execute pg_catalog.format('grant %I to %I with admin %s,inherit %s,set %s granted by %I',
   r.role_name,current_user,r.prior->>'admin',r.prior->>'inherit',r.prior->>'set',current_user); end if;
 end loop;
end; $restore$;
commit;
