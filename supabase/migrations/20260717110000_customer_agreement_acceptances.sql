do $$
begin
  create table public.customer_agreement_acceptances (
    id uuid primary key default gen_random_uuid(),
    company_id uuid not null references public.companies(id) on delete restrict,
    accepted_by uuid not null references auth.users(id) on delete restrict,
    customer_legal_name text not null check (customer_legal_name <> ''),
    customer_org_number text not null check (customer_org_number ~ '^[0-9]{9}$'),
    business_terms_version text not null check (business_terms_version <> ''),
    business_terms_effective_date date not null,
    business_terms_path text not null check (business_terms_path <> ''),
    business_terms_sha256 text not null check (business_terms_sha256 ~ '^[a-f0-9]{64}$'),
    dpa_version text not null check (dpa_version <> ''),
    dpa_effective_date date not null,
    dpa_path text not null check (dpa_path <> ''),
    dpa_sha256 text not null check (dpa_sha256 ~ '^[a-f0-9]{64}$'),
    authority_statement_version text not null check (authority_statement_version <> ''),
    acceptance_method text not null check (acceptance_method = 'in_app_clickwrap'),
    accepted_at timestamptz not null,
    created_at timestamptz not null default now()
  );
exception
  when duplicate_table then null;
end;
$$;

create index if not exists customer_agreement_acceptances_company_id_idx
on public.customer_agreement_acceptances(company_id);

create or replace function public.prevent_customer_agreement_acceptance_mutation()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  raise exception 'customer_agreement_acceptance_is_immutable';
end;
$$;

drop trigger if exists prevent_customer_agreement_acceptance_mutation
on public.customer_agreement_acceptances;

create trigger prevent_customer_agreement_acceptance_mutation
before update or delete on public.customer_agreement_acceptances
for each row execute function public.prevent_customer_agreement_acceptance_mutation();

alter table public.customer_agreement_acceptances enable row level security;

drop policy if exists "company members can read customer agreement acceptances"
on public.customer_agreement_acceptances;

create policy "company members can read customer agreement acceptances"
on public.customer_agreement_acceptances
for select
to authenticated
using (
  exists (
    select 1
    from public.company_memberships m
    where m.company_id = customer_agreement_acceptances.company_id
      and m.user_id = (select auth.uid())
      and m.accepted_at is not null
  )
);

create or replace function public.create_company_workspace_with_acceptance(
  p_actor_id uuid,
  p_org_number text,
  p_name text,
  p_entity_type text,
  p_address text,
  p_postal_code text,
  p_city text,
  p_status_text text,
  p_source text,
  p_business_terms_version text,
  p_business_terms_effective_date date,
  p_business_terms_path text,
  p_business_terms_sha256 text,
  p_dpa_version text,
  p_dpa_effective_date date,
  p_dpa_path text,
  p_dpa_sha256 text,
  p_authority_statement_version text,
  p_acceptance_method text
)
returns uuid
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_actor_id uuid := p_actor_id;
  v_company_id uuid;
  v_now timestamptz := now();
begin
  if auth.role() is distinct from 'service_role' then raise exception 'service_role_required'; end if;
  if p_actor_id is null then raise exception 'authenticated_actor_required'; end if;
  if p_org_number is null or p_org_number !~ '^[0-9]{9}$' then raise exception 'invalid_org_number'; end if;
  if p_name is null or p_name = '' then raise exception 'invalid_company_name'; end if;
  if p_entity_type is distinct from 'AS' then raise exception 'unsupported_entity_type'; end if;
  if p_acceptance_method is distinct from 'in_app_clickwrap' then raise exception 'invalid_acceptance_method'; end if;
  if p_authority_statement_version is distinct from 'authority-v1' then raise exception 'invalid_authority_statement'; end if;
  if p_business_terms_version is null or p_business_terms_version = ''
    or p_dpa_version is null or p_dpa_version = '' then
    raise exception 'invalid_contract_version';
  end if;
  if p_business_terms_effective_date is null or p_dpa_effective_date is null then
    raise exception 'invalid_contract_effective_date';
  end if;
  if p_business_terms_path is null or p_business_terms_path = ''
    or p_dpa_path is null or p_dpa_path = '' then
    raise exception 'invalid_contract_path';
  end if;
  if p_business_terms_sha256 is null or p_business_terms_sha256 !~ '^[a-f0-9]{64}$'
    or p_dpa_sha256 is null or p_dpa_sha256 !~ '^[a-f0-9]{64}$' then
    raise exception 'invalid_contract_digest';
  end if;

  insert into public.companies (
    org_number,
    name,
    entity_type,
    address,
    postal_code,
    city,
    status_text,
    source,
    created_by,
    identity_confirmed_at,
    identity_locked_at
  )
  values (
    p_org_number,
    p_name,
    p_entity_type,
    p_address,
    p_postal_code,
    p_city,
    p_status_text,
    p_source,
    v_actor_id,
    v_now,
    v_now
  )
  returning id into v_company_id;

  insert into public.company_memberships (company_id, user_id, role, accepted_at)
  values (v_company_id, v_actor_id, 'owner', v_now);

  insert into public.customer_agreement_acceptances (
    company_id,
    accepted_by,
    customer_legal_name,
    customer_org_number,
    business_terms_version,
    business_terms_effective_date,
    business_terms_path,
    business_terms_sha256,
    dpa_version,
    dpa_effective_date,
    dpa_path,
    dpa_sha256,
    authority_statement_version,
    acceptance_method,
    accepted_at
  )
  values (
    v_company_id,
    v_actor_id,
    p_name,
    p_org_number,
    p_business_terms_version,
    p_business_terms_effective_date,
    p_business_terms_path,
    p_business_terms_sha256,
    p_dpa_version,
    p_dpa_effective_date,
    p_dpa_path,
    p_dpa_sha256,
    p_authority_statement_version,
    'in_app_clickwrap',
    v_now
  );

  insert into public.audit_events (company_id, actor_id, category, action, message)
  values (
    v_company_id,
    v_actor_id,
    'company',
    'workspace_created',
    'Selskapsarbeidsflate opprettet med dokumentert avtaleaksept.'
  );

  return v_company_id;
end;
$$;

revoke all on table public.customer_agreement_acceptances from public, anon, authenticated, service_role;
grant select on table public.customer_agreement_acceptances to authenticated;
grant select on table public.customer_agreement_acceptances to service_role;

revoke all on function public.prevent_customer_agreement_acceptance_mutation()
from public, anon, authenticated, service_role;

revoke all on function public.create_company_workspace_with_acceptance(
  uuid, text, text, text, text, text, text, text, text, text, date, text, text, text, date, text, text, text, text
)
from public, anon, authenticated, service_role;

grant execute on function public.create_company_workspace_with_acceptance(
  uuid, text, text, text, text, text, text, text, text, text, date, text, text, text, date, text, text, text, text
)
to service_role;
