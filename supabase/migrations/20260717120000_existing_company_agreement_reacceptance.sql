create or replace function public.append_company_agreement_acceptance(
  p_actor_id uuid,
  p_company_id uuid,
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
  v_acceptance_id uuid;
  v_company_name text;
  v_org_number text;
  v_now timestamptz := now();
begin
  if auth.role() is distinct from 'service_role' then raise exception 'service_role_required'; end if;
  if p_actor_id is null then raise exception 'authenticated_actor_required'; end if;
  if p_company_id is null then raise exception 'invalid_company_id'; end if;
  if p_business_terms_version is distinct from '2026-07-17'
    or p_business_terms_effective_date is distinct from date '2026-07-17'
    or p_business_terms_path is distinct from '/vilkar'
    or p_business_terms_sha256 is distinct from 'f64a7f6a9758389fca8985a883a945d84c849f5b3316944621507db336992543'
    or p_dpa_version is distinct from '2026-07-17'
    or p_dpa_effective_date is distinct from date '2026-07-17'
    or p_dpa_path is distinct from '/databehandleravtale'
    or p_dpa_sha256 is distinct from '083ee63c1917ef227068befd7706ba2d636c52070ed4d880a8efae720528191c'
    or p_authority_statement_version is distinct from 'authority-v1'
    or p_acceptance_method is distinct from 'in_app_clickwrap' then
    raise exception 'stale_or_invalid_agreement_evidence';
  end if;

  if not exists (
    select 1
    from public.company_memberships m
    where m.company_id = p_company_id
      and m.user_id = p_actor_id
      and m.role = 'owner'
      and m.accepted_at is not null
  ) then
    raise exception 'accepted_owner_membership_required';
  end if;

  select c.name, c.org_number
  into v_company_name, v_org_number
  from public.companies c
  where c.id = p_company_id;
  if not found then raise exception 'company_not_found'; end if;

  perform pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended(p_company_id::text, 0));

  select a.id
  into v_acceptance_id
  from public.customer_agreement_acceptances a
  where a.company_id = p_company_id
    and a.business_terms_version = p_business_terms_version
    and a.business_terms_effective_date = p_business_terms_effective_date
    and a.business_terms_path = p_business_terms_path
    and a.business_terms_sha256 = p_business_terms_sha256
    and a.dpa_version = p_dpa_version
    and a.dpa_effective_date = p_dpa_effective_date
    and a.dpa_path = p_dpa_path
    and a.dpa_sha256 = p_dpa_sha256
    and a.authority_statement_version = p_authority_statement_version
    and a.acceptance_method = p_acceptance_method
  order by a.accepted_at desc
  limit 1;
  if v_acceptance_id is not null then return v_acceptance_id; end if;

  insert into public.customer_agreement_acceptances (
    company_id, accepted_by, customer_legal_name, customer_org_number,
    business_terms_version, business_terms_effective_date, business_terms_path, business_terms_sha256,
    dpa_version, dpa_effective_date, dpa_path, dpa_sha256,
    authority_statement_version, acceptance_method, accepted_at
  ) values (
    p_company_id, p_actor_id, v_company_name, v_org_number,
    p_business_terms_version, p_business_terms_effective_date, p_business_terms_path, p_business_terms_sha256,
    p_dpa_version, p_dpa_effective_date, p_dpa_path, p_dpa_sha256,
    p_authority_statement_version, p_acceptance_method, v_now
  ) returning id into v_acceptance_id;

  insert into public.audit_events (company_id, actor_id, category, action, message)
  values (
    p_company_id, p_actor_id, 'company', 'customer_agreement_reaccepted',
    'Oppdatert kundeavtale og databehandleravtale uttrykkelig akseptert.'
  );

  return v_acceptance_id;
end;
$$;

revoke all on function public.append_company_agreement_acceptance(
  uuid, uuid, text, date, text, text, text, date, text, text, text, text
)
from public, anon, authenticated, service_role;

grant execute on function public.append_company_agreement_acceptance(
  uuid, uuid, text, date, text, text, text, date, text, text, text, text
)
to service_role;
