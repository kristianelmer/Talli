-- EXPAND: versioned company-year eligibility and admission.
--
-- The public precheck and definitive interview are stateless. Only a supported,
-- authenticated acceptance reaches this backend-only RPC, where company,
-- membership, legal acceptance, eligibility evidence, and the company-year
-- promise commit as one RLS-constrained graph.

begin;

-- The v1 HTTP shape remains as a fail-closed compatibility response, but the
-- AS-only backend writer is removed so no internal caller can bypass the
-- definitive company-year admission command.
drop function if exists public.company_access_onboard_company(
  uuid, uuid, text, text, text, text, text, text, text, text, text,
  boolean, text, date, text, text, text, date, text, text, text, text
);

alter table public.company_access_command_receipts
  drop constraint if exists company_access_command_receipts_command_name_check;
alter table public.company_access_command_receipts
  add constraint company_access_command_receipts_command_name_check check (command_name in (
    'create_invitation', 'accept_invitation', 'revoke_invitation',
    'resend_invitation', 'administer_membership', 'request_cancellation',
    'resume_cancellation', 'review_deletion', 'finalize_deletion',
    'onboard_company', 'reaccept_agreement', 'admit_company_year',
    'recheck_company_year_eligibility'
  ));

create table public.company_eligibility_assessments (
  id uuid primary key default gen_random_uuid(),
  company_id uuid not null references public.companies(id) on delete restrict,
  accounting_year integer not null check (accounting_year = 2026),
  operation_id uuid not null,
  previous_assessment_id uuid,
  trigger text not null check (trigger in (
    'initial_admission', 'public_fact_changed', 'material_answer_changed',
    'manifest_changed', 'before_payment', 'before_filing'
  )),
  decision text not null check (decision in ('supported', 'clarify', 'blocked')),
  capability_manifest jsonb not null check (jsonb_typeof(capability_manifest) = 'object'),
  capability_manifest_version text not null check (capability_manifest_version = '2026.1'),
  capability_manifest_sha256 text not null check (
    capability_manifest_sha256 = '9f91a66d0e2cb560d880b6b290c707bc45a8d117a4175780c75e2d1ccdb694de'
  ),
  public_facts jsonb not null check (jsonb_typeof(public_facts) = 'object'),
  public_facts_sha256 text not null check (public_facts_sha256 ~ '^[a-f0-9]{64}$'),
  answers jsonb not null check (jsonb_typeof(answers) = 'object' and answers <> '{}'::jsonb),
  answers_sha256 text not null check (answers_sha256 ~ '^[a-f0-9]{64}$'),
  reason_codes text[] not null default '{}'::text[],
  reason_explanations text[] not null default '{}'::text[],
  next_step_code text not null check (next_step_code <> ''),
  next_step text not null check (next_step <> ''),
  consequential_operations_allowed boolean not null,
  archive_export_available boolean not null check (archive_export_available),
  evaluator_version text not null check (evaluator_version = '2026.1'),
  assessed_by uuid not null references auth.users(id) on delete restrict,
  assessed_at timestamptz not null,
  unique (assessed_by, operation_id),
  unique (id, company_id, accounting_year),
  constraint company_eligibility_assessments_previous_same_company_year_fk
    foreign key (previous_assessment_id, company_id, accounting_year)
    references public.company_eligibility_assessments(id, company_id, accounting_year)
    on delete restrict
);

create table public.company_year_admissions (
  id uuid primary key default gen_random_uuid(),
  company_id uuid not null references public.companies(id) on delete restrict,
  accounting_year integer not null check (accounting_year = 2026),
  eligibility_assessment_id uuid not null unique,
  capability_manifest jsonb not null check (jsonb_typeof(capability_manifest) = 'object'),
  capability_manifest_version text not null check (capability_manifest_version = '2026.1'),
  capability_manifest_sha256 text not null check (
    capability_manifest_sha256 = '9f91a66d0e2cb560d880b6b290c707bc45a8d117a4175780c75e2d1ccdb694de'
  ),
  company_year_promise jsonb not null check (jsonb_typeof(company_year_promise) = 'object'),
  company_year_promise_sha256 text not null check (company_year_promise_sha256 ~ '^[a-f0-9]{64}$'),
  reconstruct_from date not null check (reconstruct_from = date '2026-01-01'),
  admitted_by uuid not null references auth.users(id) on delete restrict,
  admitted_at timestamptz not null,
  unique (company_id, accounting_year),
  unique (id, company_id, accounting_year),
  constraint company_year_admissions_assessment_same_company_year_fk
    foreign key (eligibility_assessment_id, company_id, accounting_year)
    references public.company_eligibility_assessments(id, company_id, accounting_year)
    on delete restrict
);

create table public.company_year_acceptances (
  id uuid primary key default gen_random_uuid(),
  company_year_admission_id uuid not null unique,
  company_id uuid not null references public.companies(id) on delete restrict,
  accounting_year integer not null check (accounting_year = 2026),
  accepted_by uuid not null references auth.users(id) on delete restrict,
  customer_legal_name text not null check (customer_legal_name <> ''),
  customer_org_number text not null check (customer_org_number ~ '^[0-9]{9}$'),
  business_terms_version text not null check (business_terms_version = '2026-07-17'),
  business_terms_effective_date date not null check (business_terms_effective_date = date '2026-07-17'),
  business_terms_path text not null check (business_terms_path = '/vilkar'),
  business_terms_sha256 text not null check (
    business_terms_sha256 = 'f64a7f6a9758389fca8985a883a945d84c849f5b3316944621507db336992543'
  ),
  dpa_version text not null check (dpa_version = '2026-07-17'),
  dpa_effective_date date not null check (dpa_effective_date = date '2026-07-17'),
  dpa_path text not null check (dpa_path = '/databehandleravtale'),
  dpa_sha256 text not null check (
    dpa_sha256 = '083ee63c1917ef227068befd7706ba2d636c52070ed4d880a8efae720528191c'
  ),
  privacy_notice_version text not null check (privacy_notice_version = '2026-07-15'),
  privacy_notice_effective_date date not null check (privacy_notice_effective_date = date '2026-07-15'),
  privacy_notice_path text not null check (privacy_notice_path = '/personvern'),
  privacy_notice_sha256 text not null check (
    privacy_notice_sha256 = '4777d7b1bce8218219db06f40c255ca9ef6e0d5f1c84ccdc9b5616b75b9d472c'
  ),
  capability_manifest_version text not null check (capability_manifest_version = '2026.1'),
  capability_manifest_sha256 text not null check (
    capability_manifest_sha256 = '9f91a66d0e2cb560d880b6b290c707bc45a8d117a4175780c75e2d1ccdb694de'
  ),
  authority_statement_version text not null check (authority_statement_version = 'authority-v1'),
  acceptance_method text not null check (acceptance_method = 'in_app_clickwrap'),
  accepted_at timestamptz not null,
  unique (company_id, accounting_year),
  constraint company_year_acceptances_admission_same_company_year_fk
    foreign key (company_year_admission_id, company_id, accounting_year)
    references public.company_year_admissions(id, company_id, accounting_year)
    on delete restrict
);

create index company_eligibility_assessments_company_year_idx
  on public.company_eligibility_assessments(company_id, accounting_year, assessed_at desc);
create index company_year_admissions_company_idx
  on public.company_year_admissions(company_id, admitted_at desc);

create or replace function public.company_access_prevent_admission_evidence_mutation()
returns trigger
language plpgsql
set search_path = ''
as $function$
begin
  raise exception 'company_access_admission_evidence_is_immutable';
end;
$function$;

create trigger company_eligibility_assessments_immutable
before update or delete on public.company_eligibility_assessments
for each row execute function public.company_access_prevent_admission_evidence_mutation();
create trigger company_year_admissions_immutable
before update or delete on public.company_year_admissions
for each row execute function public.company_access_prevent_admission_evidence_mutation();
create trigger company_year_acceptances_immutable
before update or delete on public.company_year_acceptances
for each row execute function public.company_access_prevent_admission_evidence_mutation();

alter table public.company_eligibility_assessments enable row level security;
alter table public.company_year_admissions enable row level security;
alter table public.company_year_acceptances enable row level security;

create or replace function public.company_access_is_accepted_member_v1(p_company_id uuid)
returns boolean
language sql
stable
security definer
set search_path = ''
as $function$
  select exists (
    select 1 from public.company_memberships m
    where m.company_id = p_company_id
      and m.user_id = (select public.company_access_auth_uid_v1())
      and m.accepted_at is not null
  );
$function$;

create policy "company members read eligibility assessments"
on public.company_eligibility_assessments for select
to company_access_executor
using (public.company_access_is_accepted_member_v1(company_id));
create policy "company access appends supported assessments"
on public.company_eligibility_assessments for insert
to company_access_executor
with check (
  assessed_by = (select public.company_access_auth_uid_v1())
  and public.company_access_is_accepted_owner_v1(company_id)
);

create policy "company members read company year admissions"
on public.company_year_admissions for select
to company_access_executor
using (public.company_access_is_accepted_member_v1(company_id));
create policy "company access appends company year admissions"
on public.company_year_admissions for insert
to company_access_executor
with check (
  admitted_by = (select public.company_access_auth_uid_v1())
  and public.company_access_is_accepted_owner_v1(company_id)
);

create policy "company members read company year acceptances"
on public.company_year_acceptances for select
to company_access_executor
using (public.company_access_is_accepted_member_v1(company_id));
create policy "company access appends company year acceptances"
on public.company_year_acceptances for insert
to company_access_executor
with check (
  accepted_by = (select public.company_access_auth_uid_v1())
  and public.company_access_is_accepted_owner_v1(company_id)
);

drop policy if exists "company access commands read receipts"
  on public.company_access_command_receipts;
create policy "company access commands read receipts"
on public.company_access_command_receipts for select
to company_access_executor
using (
  actor_id = (select public.company_access_auth_uid_v1())
  and (
    command_name in (
      'accept_invitation', 'onboard_company', 'admit_company_year',
      'recheck_company_year_eligibility'
    )
    or (
      command_name = 'reaccept_agreement'
      and public.company_access_is_accepted_owner_v1(company_id)
    )
    or (
      command_name in (
        'create_invitation', 'revoke_invitation', 'resend_invitation',
        'administer_membership', 'request_cancellation', 'resume_cancellation',
        'finalize_deletion'
      )
      and expires_at > statement_timestamp()
      and coalesce((select public.company_access_auth_jwt_v1()) ->> 'aal', '') = 'aal2'
      and public.company_access_is_accepted_owner_v1(company_id)
    )
    or (
      command_name = 'review_deletion'
      and expires_at > statement_timestamp()
      and public.company_access_has_fresh_mfa_v1()
      and public.company_access_is_active_admin_v1()
    )
  )
);

create or replace function public.company_access_admit_company_year(
  p_operation_id uuid,
  p_verified_subject uuid,
  p_verified_email text,
  p_org_number text,
  p_name text,
  p_entity_type text,
  p_address text,
  p_postal_code text,
  p_city text,
  p_status_text text,
  p_source text,
  p_accounting_year integer,
  p_reconstruct_from date,
  p_public_facts_json text,
  p_public_facts_sha256 text,
  p_answers_json text,
  p_answers_sha256 text,
  p_capability_manifest_json text,
  p_capability_manifest_version text,
  p_capability_manifest_sha256 text,
  p_company_year_promise_json text,
  p_company_year_promise_sha256 text,
  p_business_terms_version text,
  p_business_terms_effective_date date,
  p_business_terms_path text,
  p_business_terms_sha256 text,
  p_dpa_version text,
  p_dpa_effective_date date,
  p_dpa_path text,
  p_dpa_sha256 text,
  p_privacy_notice_version text,
  p_privacy_notice_effective_date date,
  p_privacy_notice_path text,
  p_privacy_notice_sha256 text,
  p_authority_statement_version text,
  p_acceptance_method text
)
returns table (
  company_id uuid,
  company_year_admission_id uuid,
  accounting_year integer,
  reconstruct_from date,
  capability_manifest_version text,
  capability_manifest_sha256 text,
  current_agreement_accepted boolean,
  replayed boolean
)
language plpgsql
security definer
set search_path = ''
as $function$
declare
  v_actor_id uuid := public.company_access_auth_uid_v1();
  v_current_subject uuid;
  v_current_email text;
  v_email text := pg_catalog.lower(pg_catalog.btrim(p_verified_email));
  v_company_id uuid;
  v_assessment_id uuid;
  v_admission_id uuid;
  v_existing_assessment_id uuid;
  v_existing_public_facts_sha256 text;
  v_existing_answers_sha256 text;
  v_existing_manifest_sha256 text;
  v_receipt public.company_access_command_receipts%rowtype;
  v_public_facts jsonb;
  v_answers jsonb;
  v_capability_manifest jsonb;
  v_company_year_promise jsonb;
  v_now timestamptz := statement_timestamp();
  v_fingerprint text;
begin
  begin
    v_public_facts := p_public_facts_json::jsonb;
    v_answers := p_answers_json::jsonb;
    v_capability_manifest := p_capability_manifest_json::jsonb;
    v_company_year_promise := p_company_year_promise_json::jsonb;
  exception when others then
    raise exception 'company_access_invalid_request' using errcode = 'P0001';
  end;

  select identity.user_id, identity.email
  into v_current_subject, v_current_email
  from public.company_access_current_identity_v1() identity;
  if p_operation_id is null
     or v_actor_id is null
     or v_current_subject is null
     or p_verified_subject is distinct from v_actor_id
     or p_verified_subject is distinct from v_current_subject
     or v_email is distinct from v_current_email
     or v_current_email is distinct from pg_catalog.lower(coalesce(public.company_access_auth_jwt_v1() ->> 'email', '')) then
    raise exception 'company_access_not_found' using errcode = 'P0001';
  end if;

  if p_org_number is null or p_org_number !~ '^[0-9]{9}$'
     or p_name is null or pg_catalog.btrim(p_name) = ''
     or p_entity_type is distinct from 'AS'
     or p_status_text is distinct from 'aktiv'
     or p_source is distinct from 'brreg'
     or p_accounting_year is distinct from 2026
     or p_reconstruct_from is distinct from date '2026-01-01'
     or p_capability_manifest_version is distinct from '2026.1'
     or p_capability_manifest_sha256 is distinct from '9f91a66d0e2cb560d880b6b290c707bc45a8d117a4175780c75e2d1ccdb694de'
     or p_business_terms_version is distinct from '2026-07-17'
     or p_business_terms_effective_date is distinct from date '2026-07-17'
     or p_business_terms_path is distinct from '/vilkar'
     or p_business_terms_sha256 is distinct from 'f64a7f6a9758389fca8985a883a945d84c849f5b3316944621507db336992543'
     or p_dpa_version is distinct from '2026-07-17'
     or p_dpa_effective_date is distinct from date '2026-07-17'
     or p_dpa_path is distinct from '/databehandleravtale'
     or p_dpa_sha256 is distinct from '083ee63c1917ef227068befd7706ba2d636c52070ed4d880a8efae720528191c'
     or p_privacy_notice_version is distinct from '2026-07-15'
     or p_privacy_notice_effective_date is distinct from date '2026-07-15'
     or p_privacy_notice_path is distinct from '/personvern'
     or p_privacy_notice_sha256 is distinct from '4777d7b1bce8218219db06f40c255ca9ef6e0d5f1c84ccdc9b5616b75b9d472c'
     or p_authority_statement_version is distinct from 'authority-v1'
     or p_acceptance_method is distinct from 'in_app_clickwrap'
     or p_public_facts_sha256 !~ '^[a-f0-9]{64}$'
     or p_answers_sha256 !~ '^[a-f0-9]{64}$'
     or pg_catalog.jsonb_typeof(v_public_facts) is distinct from 'object'
     or pg_catalog.jsonb_typeof(v_answers) is distinct from 'object'
     or pg_catalog.jsonb_typeof(v_capability_manifest) is distinct from 'object'
     or pg_catalog.jsonb_typeof(v_company_year_promise) is distinct from 'object'
     or v_answers = '{}'::jsonb
     or v_public_facts ->> 'orgNumber' is distinct from p_org_number
     or v_public_facts ->> 'name' is distinct from p_name
     or v_public_facts ->> 'entityType' is distinct from p_entity_type
     or v_public_facts ->> 'statusText' is distinct from p_status_text
     or v_public_facts ->> 'source' is distinct from p_source
     or public.company_access_token_hash_v1(p_public_facts_json) is distinct from p_public_facts_sha256
     or public.company_access_token_hash_v1(p_answers_json) is distinct from p_answers_sha256
     or public.company_access_token_hash_v1(p_capability_manifest_json) is distinct from p_capability_manifest_sha256
     or p_company_year_promise_sha256 !~ '^[a-f0-9]{64}$'
     or public.company_access_token_hash_v1(p_company_year_promise_json) is distinct from p_company_year_promise_sha256
     or (v_company_year_promise ->> 'accountingYear')::integer is distinct from p_accounting_year
     or v_company_year_promise ->> 'reconstructionRequiredFrom' is distinct from p_reconstruct_from::text
     or v_company_year_promise ->> 'onlyAccountingAndFilingProduct' is distinct from 'true' then
    raise exception 'company_access_invalid_request' using errcode = 'P0001';
  end if;

  v_fingerprint := public.company_access_token_hash_v1(pg_catalog.concat_ws(
    '|', p_org_number, p_name, p_entity_type, p_address, p_postal_code, p_city,
    p_status_text, p_source, p_accounting_year::text, p_reconstruct_from::text,
    p_public_facts_sha256, p_answers_sha256,
    p_capability_manifest_version, p_capability_manifest_sha256,
    p_company_year_promise_sha256,
    p_business_terms_version, p_business_terms_effective_date::text,
    p_business_terms_path, p_business_terms_sha256,
    p_dpa_version, p_dpa_effective_date::text, p_dpa_path, p_dpa_sha256,
    p_privacy_notice_version, p_privacy_notice_effective_date::text,
    p_privacy_notice_path, p_privacy_notice_sha256,
    p_authority_statement_version, p_acceptance_method
  ));

  perform pg_catalog.pg_advisory_xact_lock(
    pg_catalog.hashtextextended(
      v_actor_id::text || '|admit|' || p_org_number || '|' || p_accounting_year::text,
      187
    )
  );

  select r.* into v_receipt
  from public.company_access_command_receipts r
  where r.actor_id = v_actor_id
    and r.operation_id = p_operation_id
    and r.command_name = 'admit_company_year';
  if found then
    if v_receipt.request_fingerprint is distinct from v_fingerprint then
      raise exception 'company_access_conflict' using errcode = 'P0001';
    end if;
    return query select
      v_receipt.company_id,
      (v_receipt.result ->> 'company_year_admission_id')::uuid,
      (v_receipt.result ->> 'accounting_year')::integer,
      (v_receipt.result ->> 'reconstruct_from')::date,
      v_receipt.result ->> 'capability_manifest_version',
      v_receipt.result ->> 'capability_manifest_sha256',
      true,
      true;
    return;
  end if;

  select c.id into v_company_id
  from public.companies c
  where c.org_number = p_org_number
  limit 1;

  if v_company_id is null then
    insert into public.companies (
      org_number, name, entity_type, address, postal_code, city, status_text,
      source, created_by, identity_confirmed_at, identity_locked_at
    ) values (
      p_org_number, p_name, p_entity_type, coalesce(p_address, ''),
      coalesce(p_postal_code, ''), coalesce(p_city, ''), p_status_text,
      p_source, v_actor_id, v_now, v_now
    ) returning id into v_company_id;

    insert into public.company_memberships (
      company_id, user_id, role, invited_by, accepted_at
    ) values (v_company_id, v_actor_id, 'owner', null, v_now);
  elsif not public.company_access_is_accepted_owner_v1(v_company_id) then
    raise exception 'company_access_conflict' using errcode = 'P0001';
  end if;

  select a.id, a.eligibility_assessment_id, e.public_facts_sha256,
    e.answers_sha256, a.capability_manifest_sha256
  into v_admission_id, v_existing_assessment_id, v_existing_public_facts_sha256,
    v_existing_answers_sha256, v_existing_manifest_sha256
  from public.company_year_admissions a
  join public.company_eligibility_assessments e on e.id = a.eligibility_assessment_id
  where a.company_id = v_company_id
    and a.accounting_year = p_accounting_year;
  if found then
    if v_existing_public_facts_sha256 is distinct from p_public_facts_sha256
       or v_existing_answers_sha256 is distinct from p_answers_sha256
       or v_existing_manifest_sha256 is distinct from p_capability_manifest_sha256 then
      raise exception 'company_access_conflict' using errcode = 'P0001';
    end if;
    insert into public.company_access_command_receipts (
      operation_id, command_name, actor_id, company_id,
      request_fingerprint, result, expires_at
    ) values (
      p_operation_id, 'admit_company_year', v_actor_id, v_company_id,
      v_fingerprint,
      pg_catalog.jsonb_build_object(
        'company_id', v_company_id,
        'company_year_admission_id', v_admission_id,
        'accounting_year', p_accounting_year,
        'reconstruct_from', p_reconstruct_from,
        'capability_manifest_version', p_capability_manifest_version,
        'capability_manifest_sha256', p_capability_manifest_sha256,
        'current_agreement_accepted', true
      ),
      'infinity'::timestamptz
    );
    return query select v_company_id, v_admission_id, p_accounting_year,
      p_reconstruct_from, p_capability_manifest_version,
      p_capability_manifest_sha256, true, true;
    return;
  end if;

  if not public.company_access_has_current_agreement_v1(v_company_id) then
    insert into public.customer_agreement_acceptances (
      company_id, accepted_by, customer_legal_name, customer_org_number,
      business_terms_version, business_terms_effective_date,
      business_terms_path, business_terms_sha256,
      dpa_version, dpa_effective_date, dpa_path, dpa_sha256,
      authority_statement_version, acceptance_method, accepted_at
    ) values (
      v_company_id, v_actor_id, p_name, p_org_number,
      p_business_terms_version, p_business_terms_effective_date,
      p_business_terms_path, p_business_terms_sha256,
      p_dpa_version, p_dpa_effective_date, p_dpa_path, p_dpa_sha256,
      p_authority_statement_version, p_acceptance_method, v_now
    );
  end if;

  insert into public.company_eligibility_assessments (
    company_id, accounting_year, operation_id, previous_assessment_id,
    trigger, decision, capability_manifest,
    capability_manifest_version, capability_manifest_sha256,
    public_facts, public_facts_sha256, answers, answers_sha256,
    reason_codes, reason_explanations, next_step_code, next_step,
    consequential_operations_allowed, archive_export_available,
    evaluator_version, assessed_by, assessed_at
  ) values (
    v_company_id, p_accounting_year, p_operation_id, null,
    'initial_admission', 'supported', v_capability_manifest,
    p_capability_manifest_version, p_capability_manifest_sha256,
    v_public_facts, p_public_facts_sha256, v_answers, p_answers_sha256,
    '{}'::text[], '{}'::text[], 'CREATE_ACCOUNT_AND_ACCEPT',
    'Opprett konto og godta selskapsåret når du er klar.',
    true, true, '2026.1', v_actor_id, v_now
  ) returning id into v_assessment_id;

  insert into public.company_year_admissions (
    company_id, accounting_year, eligibility_assessment_id,
    capability_manifest, capability_manifest_version, capability_manifest_sha256,
    company_year_promise, company_year_promise_sha256,
    reconstruct_from, admitted_by, admitted_at
  ) values (
    v_company_id, p_accounting_year, v_assessment_id,
    v_capability_manifest, p_capability_manifest_version, p_capability_manifest_sha256,
    v_company_year_promise, p_company_year_promise_sha256,
    p_reconstruct_from, v_actor_id, v_now
  ) returning id into v_admission_id;

  insert into public.company_year_acceptances (
    company_year_admission_id, company_id, accounting_year, accepted_by,
    customer_legal_name, customer_org_number,
    business_terms_version, business_terms_effective_date,
    business_terms_path, business_terms_sha256,
    dpa_version, dpa_effective_date, dpa_path, dpa_sha256,
    privacy_notice_version, privacy_notice_effective_date,
    privacy_notice_path, privacy_notice_sha256,
    capability_manifest_version, capability_manifest_sha256,
    authority_statement_version, acceptance_method, accepted_at
  ) values (
    v_admission_id, v_company_id, p_accounting_year, v_actor_id,
    p_name, p_org_number,
    p_business_terms_version, p_business_terms_effective_date,
    p_business_terms_path, p_business_terms_sha256,
    p_dpa_version, p_dpa_effective_date, p_dpa_path, p_dpa_sha256,
    p_privacy_notice_version, p_privacy_notice_effective_date,
    p_privacy_notice_path, p_privacy_notice_sha256,
    p_capability_manifest_version, p_capability_manifest_sha256,
    p_authority_statement_version, p_acceptance_method, v_now
  );

  insert into public.company_access_command_receipts (
    operation_id, command_name, actor_id, company_id,
    request_fingerprint, result, expires_at
  ) values (
    p_operation_id, 'admit_company_year', v_actor_id, v_company_id,
    v_fingerprint,
    pg_catalog.jsonb_build_object(
      'company_id', v_company_id,
      'company_year_admission_id', v_admission_id,
      'accounting_year', p_accounting_year,
      'reconstruct_from', p_reconstruct_from,
      'capability_manifest_version', p_capability_manifest_version,
      'capability_manifest_sha256', p_capability_manifest_sha256,
      'current_agreement_accepted', true
    ),
    'infinity'::timestamptz
  );

  return query select v_company_id, v_admission_id, p_accounting_year,
    p_reconstruct_from, p_capability_manifest_version,
    p_capability_manifest_sha256, true, false;
exception
  when unique_violation then
    raise exception 'company_access_conflict' using errcode = 'P0001';
end;
$function$;

create or replace function public.company_access_recheck_company_year_eligibility(
  p_operation_id uuid,
  p_verified_subject uuid,
  p_company_year_admission_id uuid,
  p_company_id uuid,
  p_accounting_year integer,
  p_previous_assessment_id uuid,
  p_trigger text,
  p_decision text,
  p_capability_manifest_json text,
  p_capability_manifest_version text,
  p_capability_manifest_sha256 text,
  p_public_facts_json text,
  p_public_facts_sha256 text,
  p_answers_json text,
  p_answers_sha256 text,
  p_reason_codes text[],
  p_reason_explanations text[],
  p_next_step_code text,
  p_next_step text,
  p_consequential_operations_allowed boolean,
  p_archive_export_available boolean
)
returns table (
  company_year_eligibility_assessment_id uuid,
  replayed boolean
)
language plpgsql
security definer
set search_path = ''
as $function$
declare
  v_actor_id uuid := public.company_access_auth_uid_v1();
  v_current_subject uuid;
  v_admission_company_id uuid;
  v_admission_year integer;
  v_org_number text;
  v_latest_assessment_id uuid;
  v_assessment_id uuid;
  v_capability_manifest jsonb;
  v_public_facts jsonb;
  v_answers jsonb;
  v_receipt public.company_access_command_receipts%rowtype;
  v_fingerprint text;
  v_now timestamptz := statement_timestamp();
begin
  begin
    v_capability_manifest := p_capability_manifest_json::jsonb;
    v_public_facts := p_public_facts_json::jsonb;
    v_answers := p_answers_json::jsonb;
  exception when others then
    raise exception 'company_access_invalid_request' using errcode = 'P0001';
  end;

  select identity.user_id into v_current_subject
  from public.company_access_current_identity_v1() identity;
  if p_operation_id is null
     or v_actor_id is null
     or v_current_subject is null
     or p_verified_subject is distinct from v_actor_id
     or p_verified_subject is distinct from v_current_subject then
    raise exception 'company_access_not_found' using errcode = 'P0001';
  end if;

  select a.company_id, a.accounting_year, c.org_number
  into v_admission_company_id, v_admission_year, v_org_number
  from public.company_year_admissions a
  join public.companies c on c.id = a.company_id
  where a.id = p_company_year_admission_id;
  if not found
     or v_admission_company_id is distinct from p_company_id
     or v_admission_year is distinct from p_accounting_year
     or not public.company_access_is_accepted_owner_v1(v_admission_company_id) then
    raise exception 'company_access_not_found' using errcode = 'P0001';
  end if;

  if p_accounting_year is distinct from 2026
     or p_trigger not in (
       'public_fact_changed', 'material_answer_changed', 'manifest_changed',
       'before_payment', 'before_filing'
     )
     or p_decision not in ('supported', 'clarify', 'blocked')
     or p_capability_manifest_version is distinct from '2026.1'
     or p_capability_manifest_sha256 is distinct from '9f91a66d0e2cb560d880b6b290c707bc45a8d117a4175780c75e2d1ccdb694de'
     or pg_catalog.jsonb_typeof(v_capability_manifest) is distinct from 'object'
     or public.company_access_token_hash_v1(p_capability_manifest_json)
          is distinct from p_capability_manifest_sha256
     or pg_catalog.jsonb_typeof(v_public_facts) is distinct from 'object'
     or v_public_facts ->> 'orgNumber' is distinct from v_org_number
     or public.company_access_token_hash_v1(p_public_facts_json)
          is distinct from p_public_facts_sha256
     or p_public_facts_sha256 !~ '^[a-f0-9]{64}$'
     or pg_catalog.jsonb_typeof(v_answers) is distinct from 'object'
     or v_answers = '{}'::jsonb
     or public.company_access_token_hash_v1(p_answers_json)
          is distinct from p_answers_sha256
     or p_answers_sha256 !~ '^[a-f0-9]{64}$'
     or p_reason_codes is null
     or p_reason_explanations is null
     or p_next_step is null
     or pg_catalog.btrim(p_next_step) = ''
     or p_archive_export_available is distinct from true
     or (
       p_decision = 'supported'
       and (
         p_reason_codes <> '{}'::text[]
         or p_reason_explanations <> '{}'::text[]
         or p_next_step_code is distinct from 'CONTINUE_COMPANY_YEAR'
         or p_consequential_operations_allowed is distinct from true
       )
     )
     or (
       p_decision = 'clarify'
       and (
         p_reason_codes = '{}'::text[]
         or p_reason_explanations = '{}'::text[]
         or p_next_step_code is distinct from 'PAUSE_AND_CLARIFY'
         or p_consequential_operations_allowed is distinct from false
       )
     )
     or (
       p_decision = 'blocked'
       and (
         p_reason_codes = '{}'::text[]
         or p_reason_explanations = '{}'::text[]
         or p_next_step_code is distinct from 'STOP_EXPORT_AND_CONTACT'
         or p_consequential_operations_allowed is distinct from false
       )
     ) then
    raise exception 'company_access_invalid_request' using errcode = 'P0001';
  end if;

  v_fingerprint := public.company_access_token_hash_v1(pg_catalog.concat_ws(
    '|', p_company_year_admission_id::text, p_company_id::text,
    p_accounting_year::text, p_previous_assessment_id::text, p_trigger,
    p_decision, p_capability_manifest_sha256, p_public_facts_sha256,
    p_answers_sha256, pg_catalog.array_to_string(p_reason_codes, ','),
    pg_catalog.array_to_string(p_reason_explanations, ','),
    p_next_step_code, p_next_step, p_consequential_operations_allowed::text,
    p_archive_export_available::text
  ));

  perform pg_catalog.pg_advisory_xact_lock(
    pg_catalog.hashtextextended(
      'eligibility-recheck|' || p_company_year_admission_id::text,
      187
    )
  );

  select r.* into v_receipt
  from public.company_access_command_receipts r
  where r.actor_id = v_actor_id
    and r.operation_id = p_operation_id
    and r.command_name = 'recheck_company_year_eligibility';
  if found then
    if v_receipt.company_id is distinct from p_company_id
       or v_receipt.request_fingerprint is distinct from v_fingerprint then
      raise exception 'company_access_conflict' using errcode = 'P0001';
    end if;
    return query select
      (v_receipt.result ->> 'company_year_eligibility_assessment_id')::uuid,
      true;
    return;
  end if;

  select e.id into v_latest_assessment_id
  from public.company_eligibility_assessments e
  where e.company_id = p_company_id
    and e.accounting_year = p_accounting_year
  order by e.assessed_at desc, e.id desc
  limit 1;
  if v_latest_assessment_id is distinct from p_previous_assessment_id then
    raise exception 'company_access_conflict' using errcode = 'P0001';
  end if;

  insert into public.company_eligibility_assessments (
    company_id, accounting_year, operation_id, previous_assessment_id,
    trigger, decision, capability_manifest,
    capability_manifest_version, capability_manifest_sha256,
    public_facts, public_facts_sha256, answers, answers_sha256,
    reason_codes, reason_explanations, next_step_code, next_step,
    consequential_operations_allowed, archive_export_available,
    evaluator_version, assessed_by, assessed_at
  ) values (
    p_company_id, p_accounting_year, p_operation_id, p_previous_assessment_id,
    p_trigger, p_decision, v_capability_manifest,
    p_capability_manifest_version, p_capability_manifest_sha256,
    v_public_facts, p_public_facts_sha256, v_answers, p_answers_sha256,
    p_reason_codes, p_reason_explanations, p_next_step_code, p_next_step,
    p_consequential_operations_allowed, true,
    '2026.1', v_actor_id, v_now
  ) returning id into v_assessment_id;

  insert into public.company_access_command_receipts (
    operation_id, command_name, actor_id, company_id,
    request_fingerprint, result, expires_at
  ) values (
    p_operation_id, 'recheck_company_year_eligibility', v_actor_id, p_company_id,
    v_fingerprint,
    pg_catalog.jsonb_build_object(
      'company_year_eligibility_assessment_id', v_assessment_id,
      'company_year_admission_id', p_company_year_admission_id,
      'decision', p_decision
    ),
    'infinity'::timestamptz
  );

  return query select v_assessment_id, false;
exception
  when unique_violation then
    raise exception 'company_access_conflict' using errcode = 'P0001';
end;
$function$;

grant select, insert on public.company_eligibility_assessments,
  public.company_year_admissions, public.company_year_acceptances
to company_access_executor;
revoke all on public.company_eligibility_assessments,
  public.company_year_admissions, public.company_year_acceptances
from public, anon, authenticated, service_role;

revoke all on function public.company_access_prevent_admission_evidence_mutation()
from public, anon, authenticated, service_role;
revoke all on function public.company_access_is_accepted_member_v1(uuid)
from public, anon, authenticated, service_role;
grant execute on function public.company_access_is_accepted_member_v1(uuid)
to company_access_executor;

do $ownership$
begin
  execute pg_catalog.format('grant company_access_executor to %I', current_user);
  grant create on schema public to company_access_executor;
  alter function public.company_access_admit_company_year(
    uuid,uuid,text,text,text,text,text,text,text,text,text,integer,date,
    text,text,text,text,text,text,text,text,text,text,date,text,text,text,
    date,text,text,text,date,text,text,text,text
  ) owner to company_access_executor;
  alter function public.company_access_recheck_company_year_eligibility(
    uuid,uuid,uuid,uuid,integer,uuid,text,text,text,text,text,text,text,
    text,text,text[],text[],text,text,boolean,boolean
  ) owner to company_access_executor;
  revoke create on schema public from company_access_executor;
end
$ownership$;

set role company_access_executor;
revoke all on function public.company_access_admit_company_year(
  uuid,uuid,text,text,text,text,text,text,text,text,text,integer,date,
  text,text,text,text,text,text,text,text,text,text,date,text,text,text,
  date,text,text,text,date,text,text,text,text
) from public, anon, authenticated, service_role;
grant execute on function public.company_access_admit_company_year(
  uuid,uuid,text,text,text,text,text,text,text,text,text,integer,date,
  text,text,text,text,text,text,text,text,text,text,date,text,text,text,
  date,text,text,text,date,text,text,text,text
) to company_access_executor;
revoke all on function public.company_access_recheck_company_year_eligibility(
  uuid,uuid,uuid,uuid,integer,uuid,text,text,text,text,text,text,text,
  text,text,text[],text[],text,text,boolean,boolean
) from public, anon, authenticated, service_role;
grant execute on function public.company_access_recheck_company_year_eligibility(
  uuid,uuid,uuid,uuid,integer,uuid,text,text,text,text,text,text,text,
  text,text,text[],text[],text,text,boolean,boolean
) to company_access_executor;
reset role;

do $ownership$
begin
  execute pg_catalog.format('revoke company_access_executor from %I', current_user);
end
$ownership$;

commit;
