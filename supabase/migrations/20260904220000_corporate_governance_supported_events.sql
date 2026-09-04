-- Complete the provider-neutral capital, financing and group event source (#191).
begin;

set local lock_timeout = '5s';
set local statement_timeout = '120s';

select pg_catalog.set_config(
  'talli.corporate_governance_191_had_store_owner',
  pg_catalog.pg_has_role(
    current_user, 'corporate_governance_store_owner', 'member'
  )::text,
  true
);
select pg_catalog.set_config(
  'talli.corporate_governance_191_had_banking_owner',
  pg_catalog.pg_has_role(current_user, 'banking_store_owner', 'member')::text,
  true
);
select pg_catalog.set_config(
  'talli.corporate_governance_191_had_ledger_owner',
  pg_catalog.pg_has_role(current_user, 'ledger_store_owner', 'member')::text,
  true
);
select pg_catalog.set_config(
  'talli.corporate_governance_191_had_archive_owner',
  pg_catalog.pg_has_role(
    current_user, 'company_archive_projection_executor', 'member'
  )::text,
  true
);

do $membership$
begin
  execute pg_catalog.format(
    'grant corporate_governance_store_owner, banking_store_owner, '
      || 'ledger_store_owner, '
      || 'company_archive_projection_executor to %I',
    current_user
  );
end
$membership$;

select pg_catalog.set_config(
  'talli.corporate_governance_191_migration_principal', current_user, true
);

create table corporate_governance.supported_events (
  event_id uuid primary key,
  event_reference uuid not null,
  company_id uuid not null references public.companies(id) on delete restrict,
  income_year integer not null check (income_year between 2000 and 2100),
  event_date date not null,
  event_kind text not null check (event_kind in (
    'cash_capital_increase', 'loss_coverage_capital_reduction',
    'intercompany_loan', 'owner_loan', 'bank_loan', 'group_contribution'
  )),
  phase text not null check (phase in (
    'binding_subscription', 'restricted_payment', 'registered',
    'decided_not_registered', 'first_recognized_after_registration',
    'funding', 'disbursement', 'payment', 'decision'
  )),
  policy_version text not null check (
    policy_version = 'corporate-governance-supported-events-2026.1'
  ),
  canonical_facts jsonb not null check (
    pg_catalog.jsonb_typeof(canonical_facts) = 'object'
  ),
  facts_sha256 text not null check (facts_sha256 ~ '^[0-9a-f]{64}$'),
  document_facts jsonb not null check (
    pg_catalog.jsonb_typeof(document_facts) = 'array'
    and pg_catalog.jsonb_array_length(document_facts) between 1 and 12
  ),
  bank_transaction_id uuid references banking.transactions(id) on delete restrict,
  shareholder_register_source_id uuid,
  tax_calculation_source_id uuid,
  accounting_entry_id uuid not null unique,
  correction_of_event_id uuid references corporate_governance.supported_events(event_id)
    on delete restrict,
  idempotency_key text not null check (
    idempotency_key ~ '^[A-Za-z0-9._:-]{16,255}$'
  ),
  correlation_id text not null check (
    pg_catalog.btrim(correlation_id) <> ''
    and pg_catalog.char_length(correlation_id) <= 255
  ),
  created_by uuid not null references auth.users(id) on delete restrict,
  created_at timestamptz not null default pg_catalog.statement_timestamp(),
  unique (created_by, company_id, idempotency_key),
  unique (company_id, income_year, event_id),
  foreign key (accounting_entry_id, company_id, income_year)
    references ledger.entries(id, company_id, income_year) on delete restrict,
  check (extract(year from event_date)::integer = income_year),
  check (
    (event_kind = 'cash_capital_increase' and phase in (
      'binding_subscription', 'restricted_payment', 'registered'
    ))
    or (event_kind = 'loss_coverage_capital_reduction' and phase in (
      'decided_not_registered', 'registered',
      'first_recognized_after_registration'
    ))
    or (event_kind = 'intercompany_loan' and phase = 'funding')
    or (event_kind = 'owner_loan' and phase = 'funding')
    or (event_kind = 'bank_loan' and phase in ('disbursement', 'payment'))
    or (event_kind = 'group_contribution' and phase = 'decision')
  )
);

alter table corporate_governance.supported_events
  owner to corporate_governance_store_owner;
alter table corporate_governance.supported_events enable row level security;
alter table corporate_governance.supported_events force row level security;

revoke all on corporate_governance.supported_events
from public, anon, authenticated, service_role,
  corporate_governance_workflow_executor;

set local role corporate_governance_store_owner;

create policy governance_owner_reads_supported_events
on corporate_governance.supported_events
for select to corporate_governance_store_owner
using (public.company_access_is_accepted_owner_v1(company_id));

create policy governance_owner_creates_supported_events
on corporate_governance.supported_events
for insert to corporate_governance_store_owner
with check (
  created_by = nullif(
    pg_catalog.current_setting('talli.verified_actor_id', true), ''
  )::uuid
  and public.company_access_is_accepted_owner_v1(company_id)
);

create trigger supported_events_immutable
before update or delete on corporate_governance.supported_events
for each row execute function
  corporate_governance.prevent_corporate_governance_mutation();

create or replace function corporate_governance.supported_event_result_v1(
  p_event_id uuid,
  p_replayed boolean
)
returns jsonb
language plpgsql
stable
security definer
set search_path = ''
as $function$
declare
  v_event corporate_governance.supported_events%rowtype;
begin
  select event.* into v_event
  from corporate_governance.supported_events event
  where event.event_id = p_event_id;
  if not found then
    raise exception 'corporate_governance_not_found';
  end if;
  return pg_catalog.jsonb_build_object(
    'eventId', v_event.event_id,
    'eventReference', v_event.event_reference,
    'companyId', v_event.company_id,
    'incomeYear', v_event.income_year,
    'eventDate', v_event.event_date,
    'eventKind', v_event.event_kind,
    'phase', v_event.phase,
    'policyVersion', v_event.policy_version,
    'canonicalFacts', v_event.canonical_facts,
    'factsSha256', v_event.facts_sha256,
    'accountingEntryId', v_event.accounting_entry_id,
    'bankTransactionId', v_event.bank_transaction_id,
    'correctionOfEventId', v_event.correction_of_event_id,
    'recordedAt', v_event.created_at,
    'replayed', p_replayed
  );
end;
$function$;

create or replace function corporate_governance.prepare_supported_event_v1(
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
    if v_existing.event_id <> v_event_id
      or v_existing.company_id <> v_company_id
      or v_existing.income_year <> v_income_year
      or v_existing.event_reference <> (p_request ->> 'eventReference')::uuid
      or v_existing.event_date <> (p_request ->> 'eventDate')::date
      or v_existing.event_kind <> p_request ->> 'eventKind'
      or v_existing.phase <> p_request ->> 'phase'
      or v_existing.facts_sha256 <> p_request ->> 'factsSha256'
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
$function$;

create or replace function corporate_governance.complete_supported_event_v1(
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
    if v_existing.facts_sha256 <> p_request ->> 'factsSha256'
      or v_existing.accounting_entry_id
        <> (p_request ->> 'accountingEntryId')::uuid
    then
      raise exception 'corporate_governance_idempotency_conflict';
    end if;
    return corporate_governance.supported_event_result_v1(v_event_id, true);
  end if;
  insert into corporate_governance.supported_events (
    event_id, event_reference, company_id, income_year, event_date,
    event_kind, phase, policy_version, canonical_facts, facts_sha256,
    document_facts, bank_transaction_id, shareholder_register_source_id,
    tax_calculation_source_id, accounting_entry_id, correction_of_event_id,
    idempotency_key, correlation_id, created_by
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
    v_actor_id
  );
  return corporate_governance.supported_event_result_v1(v_event_id, false);
exception when unique_violation then
  raise exception 'corporate_governance_idempotency_conflict';
when invalid_text_representation or numeric_value_out_of_range
  or datetime_field_overflow then
  raise exception 'corporate_governance_invalid_input';
end;
$function$;

create or replace function corporate_governance.list_supported_events_v1(
  p_company_ids uuid[],
  p_verified_subject text
)
returns setof jsonb
language plpgsql
stable
security definer
set search_path = ''
as $function$
declare
  v_company_id uuid;
begin
  if p_company_ids is null
    or pg_catalog.array_length(p_company_ids, 1) is null
    or pg_catalog.array_length(p_company_ids, 1) > 100
  then
    raise exception 'corporate_governance_invalid_input';
  end if;
  foreach v_company_id in array p_company_ids loop
    perform corporate_governance.assert_owner_v1(
      v_company_id, null, p_verified_subject, false
    );
  end loop;
  return query
  select corporate_governance.supported_event_result_v1(event.event_id, false)
  from corporate_governance.supported_events event
  where event.company_id = any(p_company_ids)
  order by event.event_date, event.created_at, event.event_id;
end;
$function$;

reset role;

set local role company_archive_projection_executor;
do $archive_authority$
begin
  execute pg_catalog.format(
    'grant execute on function public.company_archive_track_source_write_v1() to %I',
    pg_catalog.current_setting(
      'talli.corporate_governance_191_migration_principal'
    )
  );
end
$archive_authority$;
reset role;

create trigger company_archive_track_supported_events
after insert or update or delete on corporate_governance.supported_events
for each row execute function
  public.company_archive_track_source_write_v1('year', 'company_id');

set local role company_archive_projection_executor;
do $archive_authority_revoke$
begin
  execute pg_catalog.format(
    'revoke execute on function public.company_archive_track_source_write_v1() from %I',
    pg_catalog.current_setting(
      'talli.corporate_governance_191_migration_principal'
    )
  );
end
$archive_authority_revoke$;
reset role;

grant execute on function
  corporate_governance.prepare_supported_event_v1(jsonb, text),
  corporate_governance.complete_supported_event_v1(jsonb, text),
  corporate_governance.list_supported_events_v1(uuid[], text)
to corporate_governance_workflow_executor;

do $revoke_membership$
begin
  if pg_catalog.current_setting(
    'talli.corporate_governance_191_had_store_owner'
  )::boolean is false then
    execute pg_catalog.format(
      'revoke corporate_governance_store_owner from %I', current_user
    );
  end if;
  if pg_catalog.current_setting(
    'talli.corporate_governance_191_had_banking_owner'
  )::boolean is false then
    execute pg_catalog.format(
      'revoke banking_store_owner from %I', current_user
    );
  end if;
  if pg_catalog.current_setting(
    'talli.corporate_governance_191_had_ledger_owner'
  )::boolean is false then
    execute pg_catalog.format(
      'revoke ledger_store_owner from %I', current_user
    );
  end if;
  if pg_catalog.current_setting(
    'talli.corporate_governance_191_had_archive_owner'
  )::boolean is false then
    execute pg_catalog.format(
      'revoke company_archive_projection_executor from %I', current_user
    );
  end if;
end
$revoke_membership$;

commit;
